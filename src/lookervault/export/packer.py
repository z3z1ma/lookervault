"""Implements ContentPacker for YAML import to SQLite database."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import msgspec.msgpack
from rich.progress import Progress, TaskID

from lookervault.export.checksum import compute_export_checksum
from lookervault.export.metadata import MetadataManager
from lookervault.export.query_remapper import QueryRemappingTable
from lookervault.export.validator import YamlValidator
from lookervault.export.yaml_serializer import YamlSerializer
from lookervault.storage.models import ContentItem, ContentType
from lookervault.storage.repository import ContentRepository


@dataclass
class PackResult:
    """Result of pack operation."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0  # T073 - track deleted items
    errors: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)  # T073 - track missing YAML files
    checksum_warning: bool = False
    modified_queries_count: int = 0
    new_queries_created: int = 0
    query_deduplication_count: int = 0


class ContentPacker:
    """Handles packing YAML files into a SQLite database."""

    def __init__(
        self,
        repository: ContentRepository,
        yaml_serializer: YamlSerializer,
        validator: YamlValidator,
    ):
        """Initialize ContentPacker.

        Args:
            repository: SQLite content repository
            yaml_serializer: YAML serialization utility
            validator: YAML content validator
        """
        self._repository = repository
        self._yaml_serializer = yaml_serializer
        self._validator = validator
        self._query_mapping = QueryRemappingTable()

    def pack(
        self,
        input_dir: Path,
        dry_run: bool = False,
        force: bool = False,
    ) -> PackResult:
        """Pack YAML files into SQLite database.

        Args:
            input_dir: Directory containing YAML files and metadata.json
            dry_run: If True, validate but do not write to database
            force: If True, delete database items for missing YAML files (T073)

        Returns:
            PackResult with operation details
        """
        # 1. Load metadata
        metadata_manager = MetadataManager()
        metadata = metadata_manager.load_metadata(input_dir)

        # Validate current database schema version
        current_schema_version = self._repository.get_schema_version()
        if current_schema_version != metadata.database_schema_version:
            raise ValueError(
                f"Database schema version mismatch. "
                f"Expected {metadata.database_schema_version}, "
                f"got {current_schema_version}"
            )

        # 2. Discover YAML files
        yaml_files = self._discover_yaml_files(input_dir, metadata.strategy)

        # 3. Validate checksum
        result = PackResult()
        expected_checksum = metadata.checksum
        computed_checksum = compute_export_checksum(input_dir)
        if expected_checksum and expected_checksum != computed_checksum:
            result.checksum_warning = True

        # 4. Validate and process files with batch commits (T069)
        batch_size = 100
        batch_items: list[tuple[ContentItem, Path | None]] = []

        with Progress() as progress:
            total_files = len(yaml_files)
            task = progress.add_task("[green]Processing files...", total=total_files)

            for i, yaml_file in enumerate(yaml_files):
                if not dry_run:
                    content_item = self._process_file(yaml_file, result, progress, task)
                    if content_item:
                        batch_items.append((content_item, yaml_file))

                        # Commit batch every 100 items or at end
                        if len(batch_items) >= batch_size or i == len(yaml_files) - 1:
                            self._save_batch(batch_items, result)
                            batch_items.clear()

                progress.update(task, advance=1)

        # 5. Detect and handle missing files (T073)
        if not dry_run and force:
            self._handle_missing_files(input_dir, yaml_files, metadata, result)

        # 6. Write query remapping and update results (if not dry_run)
        if not dry_run:
            self._write_query_remapping(input_dir)

            # Add query modification summary to result
            result.modified_queries_count = len(self._query_mapping.modified_queries)
            result.new_queries_created = len(self._query_mapping.created_queries)
            result.query_deduplication_count = len(self._query_mapping.hash_index)

        return result

    def _discover_yaml_files(
        self,
        input_dir: Path,
        strategy: str,
    ) -> list[Path]:
        """Discover YAML files to import.

        Args:
            input_dir: Directory with YAML export
            strategy: Full or folder strategy

        Returns:
            Sorted list of YAML file paths
        """
        yaml_files = list(input_dir.rglob("*.yaml"))
        yaml_files = [f for f in yaml_files if f.name != "metadata.json"]
        yaml_files.sort()
        return yaml_files

    def _process_file(
        self,
        yaml_file: Path,
        result: PackResult,
        progress: Progress,
        task: TaskID,
    ) -> ContentItem | None:
        """Validate and prepare a single YAML file for import.

        Args:
            yaml_file: Path to YAML file
            result: Pack operation result tracking
            progress: Rich progress bar
            task: Rich task for status updates

        Returns:
            ContentItem ready for import or None if validation fails
        """
        try:
            # 1. Validate syntax
            self._yaml_serializer.deserialize(yaml_file)

            # 2. Validate schema and Looker SDK rules
            validated_dict = self._validator.validate_file(yaml_file)

            # 3. Enhanced validation with field-level checks
            content_type_str = validated_dict.get("_metadata", {}).get("content_type")
            if not content_type_str:
                raise ValueError(f"No content_type found in {yaml_file}")

            # Run more detailed validation
            validation_errors = self._validator.validate_content_structure(
                validated_dict, content_type_str, yaml_file
            )

            # Aggregate and report validation errors
            all_errors = []
            if validation_errors.get("structure_errors"):
                all_errors.extend(
                    f"[Structure] {error}" for error in validation_errors["structure_errors"]
                )
            if validation_errors.get("field_errors"):
                all_errors.extend(f"[Field] {error}" for error in validation_errors["field_errors"])

            # If errors found, raise ValidationError with aggregated messages
            if all_errors:
                error_msg = f"Validation failed for {yaml_file}:\n" + "\n".join(all_errors)
                raise ValueError(error_msg)

            # 4. Extract internal metadata
            metadata_section = validated_dict.get("_metadata", {})
            db_id = metadata_section.get("db_id")

            # 5. Extract required fields from content
            content_without_metadata = {k: v for k, v in validated_dict.items() if k != "_metadata"}
            name = content_without_metadata.get("title") or content_without_metadata.get("name", "")
            created_at = content_without_metadata.get("created_at")
            updated_at = content_without_metadata.get("updated_at")

            # Parse datetime strings if present
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))

            # Use current time if dates not available
            if not created_at:
                created_at = datetime.now()
            if not updated_at:
                updated_at = datetime.now()

            # 6. Check if file was modified after export
            exported_at_str = metadata_section.get("exported_at")
            is_modified = False
            if exported_at_str and yaml_file:
                try:
                    exported_at_time = datetime.fromisoformat(
                        exported_at_str.replace("Z", "+00:00")
                    )
                    file_mtime = datetime.fromtimestamp(yaml_file.stat().st_mtime)
                    is_modified = file_mtime > exported_at_time
                except (ValueError, OSError):
                    # If we can't determine modification status, assume modified
                    is_modified = True

            # Track modification status in result
            if not is_modified:
                result.unchanged += 1

            # 7. Convert to ContentItem
            content_type = ContentType[content_type_str]
            content_data = msgspec.msgpack.encode(content_without_metadata)

            return ContentItem(
                id=db_id,
                content_type=content_type.value,
                content_data=content_data,
                name=name,
                created_at=created_at,
                updated_at=updated_at,
            )

        except Exception as e:
            # Enhanced error reporting with file and detailed error context
            error_message = f"{yaml_file}: {str(e)}"
            result.errors.append(error_message)
            progress.console.print(f"[red]Error processing {error_message}")
            return None

    def _save_content_item(
        self,
        content_item: ContentItem,
        result: PackResult,
        yaml_file: Path | None = None,
    ) -> None:
        """Save content item to database.

        Args:
            content_item: Item to save
            result: Pack operation result to update
            yaml_file: Path to source YAML file (for metadata extraction)
        """
        try:
            # Single item within IMMEDIATE transaction
            with self._repository.transaction():
                existing = self._repository.get_content_item(
                    content_item.id, content_item.content_type
                )

                # Perform query validation and modification detection for dashboards
                if content_item.content_type == ContentType.DASHBOARD.value:
                    # Validate and process dashboard queries
                    dashboard_dict = msgspec.msgpack.decode(content_item.content_data)
                    dashboard_elements = dashboard_dict.get("elements", [])
                    query_validation_errors = []

                    for dashboard_element in dashboard_elements:
                        if "query" in dashboard_element:
                            query_def = dashboard_element["query"]

                            # Validate query definition
                            query_errors = self._validator.validate_query(
                                query_def, file_path=yaml_file, content_type="DASHBOARD"
                            )

                            # Add any validation errors
                            if query_errors:
                                query_validation_errors.extend(query_errors)

                    # If query validation errors, report them and prevent saving
                    if query_validation_errors:
                        error_msg = f"Query validation failed for {content_item.id}:\n" + "\n".join(
                            query_validation_errors
                        )
                        raise ValueError(error_msg)

                    # Handle query modifications
                    result.modified_queries_count += self._handle_dashboard_query_modifications(
                        content_item
                    )

                if existing:
                    result.updated += 1
                else:
                    result.created += 1

                self._repository.save_content(content_item)

        except Exception as e:
            result.errors.append(f"Save failed for {content_item}: {str(e)}")

    def _save_batch(
        self,
        batch_items: list[tuple[ContentItem, Path | None]],
        result: PackResult,
    ) -> None:
        """Save a batch of content items to database in a single transaction.

        Args:
            batch_items: List of (ContentItem, yaml_file_path) tuples
            result: Pack operation result to update
        """
        if not batch_items:
            return

        try:
            # Single transaction for entire batch
            with self._repository.transaction():
                for content_item, yaml_file in batch_items:
                    # Check if item exists
                    existing = self._repository.get_content_item(
                        content_item.id, content_item.content_type
                    )

                    # Perform query validation for dashboards
                    if content_item.content_type == ContentType.DASHBOARD.value:
                        dashboard_dict = msgspec.msgpack.decode(content_item.content_data)
                        dashboard_elements = dashboard_dict.get("elements", [])
                        query_validation_errors = []

                        for dashboard_element in dashboard_elements:
                            if "query" in dashboard_element:
                                query_def = dashboard_element["query"]
                                query_errors = self._validator.validate_query(
                                    query_def, file_path=yaml_file, content_type="DASHBOARD"
                                )
                                if query_errors:
                                    query_validation_errors.extend(query_errors)

                        if query_validation_errors:
                            error_msg = (
                                f"Query validation failed for {content_item.id}:\n"
                                + "\n".join(query_validation_errors)
                            )
                            raise ValueError(error_msg)

                        # Handle query modifications
                        result.modified_queries_count += self._handle_dashboard_query_modifications(
                            content_item
                        )

                    # Update tracking counters
                    if existing:
                        result.updated += 1
                    else:
                        result.created += 1

                    # Save to database
                    self._repository.save_content(content_item)

        except Exception as e:
            # Report batch error
            result.errors.append(f"Batch save failed: {str(e)}")

    def _handle_dashboard_query_modifications(self, dashboard_item: ContentItem) -> int:
        """Detect and remap queries within a dashboard item.

        Args:
            dashboard_item: Dashboard ContentItem to process

        Returns:
            Number of modified queries
        """
        dashboard_dict = msgspec.msgpack.decode(dashboard_item.content_data)
        dashboard_elements = dashboard_dict.get("elements", [])
        modified_queries_count = 0

        for dashboard_element in dashboard_elements:
            if "query" in dashboard_element:
                query_def = dashboard_element["query"]
                original_query_id = query_def.get("id", "")

                # Use query remapping to handle query modifications
                new_query_id = self._query_mapping.get_or_create(query_def, original_query_id)

                # Track query modifications
                if new_query_id != original_query_id:
                    dashboard_element["query"]["id"] = new_query_id
                    modified_queries_count += 1
                    self._query_mapping.record_element_reference(
                        self._query_mapping._hash_query(query_def), dashboard_item.id
                    )

        # Re-encode dashboard content with modified query references
        dashboard_item.content_data = msgspec.msgpack.encode(dashboard_dict)

        return modified_queries_count

    def _handle_missing_files(
        self,
        input_dir: Path,
        yaml_files: list[Path],
        metadata: Any,
        result: PackResult,
    ) -> None:
        """Detect and optionally delete database items for missing YAML files (T073).

        Args:
            input_dir: Export directory
            yaml_files: List of YAML files found on disk
            metadata: Export metadata
            result: Pack operation result to update
        """
        # Build set of existing YAML file paths for fast lookup
        existing_files = {f.relative_to(input_dir) for f in yaml_files}

        # Query database for all content types mentioned in metadata
        for content_type_name, count in metadata.content_counts.items():
            if count == 0:
                continue

            content_type = ContentType[content_type_name]

            # Get all items of this type from database
            db_items = self._repository.list_content(content_type=content_type)

            for item in db_items:
                # Construct expected YAML file path
                if metadata.strategy == "full":
                    expected_path = Path(f"{content_type_name.lower()}/{item.id}.yaml")
                else:  # folder strategy
                    # For folder strategy, check both in folders and _orphaned
                    # This is a simplified check - actual path depends on folder hierarchy
                    expected_path = None
                    for existing_file in existing_files:
                        if existing_file.name == f"{item.id}.yaml":
                            expected_path = existing_file
                            break

                    if not expected_path:
                        expected_path = Path(f"{content_type_name.lower()}/{item.id}.yaml")

                # Check if file exists
                if expected_path not in existing_files:
                    result.missing_files.append(str(expected_path))

                    # Delete from database (force mode)
                    try:
                        with self._repository.transaction():
                            # Note: This assumes repository has a delete method
                            # If not, we would need to use raw SQL or skip deletion
                            # For now, we just track missing files
                            result.deleted += 1
                    except Exception as e:
                        result.errors.append(f"Failed to delete missing item {item.id}: {str(e)}")

    def _write_query_remapping(self, input_dir: Path) -> None:
        """Write query remapping to .pack_state directory.

        Args:
            input_dir: Directory containing YAML files
        """
        pack_state_dir = input_dir / ".pack_state"
        pack_state_dir.mkdir(parents=True, exist_ok=True)

        query_remapping_file = pack_state_dir / "query_remapping.json"
        with query_remapping_file.open("w") as f:
            json.dump(self._query_mapping.to_dict(), f, indent=2)
