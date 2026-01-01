"""Unpacker module for converting SQLite content to YAML files.

This module provides the ContentUnpacker class, responsible for exporting Looker
content from a SQLite database to YAML files with comprehensive metadata.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import msgspec.msgpack
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from lookervault.export.checksum import compute_export_checksum
from lookervault.export.folder_tree import FolderTreeBuilder, FolderTreeNode
from lookervault.export.metadata import ExportStrategy, FolderInfo, MetadataManager
from lookervault.export.yaml_serializer import YamlSerializer
from lookervault.storage.models import ContentItem, ContentType
from lookervault.storage.repository import ContentRepository


class ContentUnpacker:
    """Handles exporting Looker content from SQLite to YAML files.

    Supports two strategies for export:
    1. Full strategy: All content organized by type
    2. Folder strategy: Dashboards/looks mirroring folder hierarchy
    """

    def __init__(
        self,
        repository: ContentRepository,
        yaml_serializer: YamlSerializer,
        metadata_manager: MetadataManager | None = None,
    ):
        """Initialize ContentUnpacker with required dependencies.

        Args:
            repository: ContentRepository for accessing database
            yaml_serializer: YamlSerializer for converting to YAML
            metadata_manager: Optional MetadataManager for generating metadata
        """
        self._repository = repository
        self._yaml_serializer = yaml_serializer
        self._metadata_manager = metadata_manager or MetadataManager()
        self._logger = logging.getLogger(__name__)

    def _check_disk_space(self, output_dir: Path, db_path: Path) -> None:
        """Check available disk space before export (T071).

        Args:
            output_dir: Target directory for export
            db_path: Source database path (for size estimation)

        Raises:
            RuntimeError: If insufficient disk space available
        """
        try:
            # Get database size as baseline estimate
            db_size_bytes = db_path.stat().st_size if db_path.exists() else 0

            # Estimate export size (YAML is typically 2-3x larger than msgpack)
            # Add 50% safety margin
            estimated_size = int(db_size_bytes * 3.5)

            # Check available disk space
            stat = shutil.disk_usage(output_dir)
            available_bytes = stat.free

            if available_bytes < estimated_size:
                available_gb = available_bytes / (1024**3)
                required_gb = estimated_size / (1024**3)
                raise RuntimeError(
                    f"Insufficient disk space. "
                    f"Available: {available_gb:.2f} GB, "
                    f"Estimated required: {required_gb:.2f} GB"
                )

            # Warning if less than 2x estimated size available
            if available_bytes < estimated_size * 2:
                available_gb = available_bytes / (1024**3)
                self._logger.warning(
                    f"Low disk space warning: {available_gb:.2f} GB available. "
                    f"Export may fill most remaining space."
                )

        except OSError as e:
            self._logger.warning(f"Could not check disk space: {e}")

    def unpack_full(
        self,
        db_path: Path,
        output_dir: Path,
        content_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export all content to YAML organized by content type.

        Args:
            db_path: Path to SQLite database
            output_dir: Root directory for YAML export
            content_types: Optional list of content types to export

        Returns:
            Metadata about the export operation

        Raises:
            RuntimeError: If insufficient disk space or filesystem errors (T071, T072)
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            raise RuntimeError(f"Cannot create output directory {output_dir}: {e}") from e

        # Determine content types to export
        if content_types:
            export_types = [ContentType[ct.upper()] for ct in content_types]
        else:
            export_types = list(ContentType)

        # Check disk space before proceeding (T071)
        self._check_disk_space(output_dir, db_path)

        # Create subdirectories for each content type (T072 - error handling)
        for content_type in export_types:
            try:
                (output_dir / content_type.name.lower()).mkdir(exist_ok=True)
            except (PermissionError, OSError) as e:
                raise RuntimeError(f"Cannot create directory for {content_type.name}: {e}") from e

        # Tracking variables
        content_type_counts: dict[str, int] = {}
        total_items = 0

        # Rich progress bar for export tracking
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            DownloadColumn(),
            TimeRemainingColumn(),
        ) as progress:
            export_task = progress.add_task(
                "[green]Exporting content...",
                total=len(export_types),
            )

            # Export each content type
            for content_type in reversed(export_types):
                progress.update(export_task, description=f"Exporting {content_type.name}")

                # Fetch content items for this type
                content_items: list[ContentItem] = self._repository.list_content(
                    content_type=content_type
                )
                content_type_counts[content_type.name] = len(content_items)
                total_items += len(content_items)

                type_progress = progress.add_task(
                    f"[cyan]{content_type.name} items",
                    total=len(content_items),
                )

                for item in content_items:
                    # Serialize item to YAML
                    exported_dict = msgspec.msgpack.decode(item.content_data)

                    # Compute SHA-256 checksum directly from msgpack blob (much faster)
                    blob_checksum = hashlib.sha256(item.content_data).hexdigest()

                    # Add metadata section
                    exported_dict["_metadata"] = {
                        "db_id": str(item.id),
                        "content_type": content_type.name,
                        "exported_at": datetime.now().isoformat(),
                        "content_size": len(item.content_data),
                        "checksum": f"sha256:{blob_checksum}",
                    }

                    # Write to YAML (T072 - error handling)
                    yaml_path = output_dir / f"{content_type.name.lower()}/{item.id}.yaml"
                    try:
                        yaml_str = self._yaml_serializer.serialize(exported_dict)
                        yaml_path.write_text(yaml_str)
                    except (PermissionError, OSError) as e:
                        self._logger.error(f"Failed to write {yaml_path}: {e}")
                        raise RuntimeError(f"Cannot write YAML file {yaml_path}: {e}") from e

                    progress.update(type_progress, advance=1)

                progress.update(export_task, advance=1)

        # Compute overall export checksum
        export_checksum = compute_export_checksum(output_dir)

        # Generate metadata
        metadata = self._metadata_manager.generate_metadata(
            strategy=ExportStrategy.FULL,
            content_type_counts=content_type_counts,
            database_schema_version=self._repository.get_schema_version(),
            source_database=db_path,
            folder_map=None,
            checksum=export_checksum,
        )

        # Write metadata
        metadata_file = output_dir / "metadata.json"
        with metadata_file.open("w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

        return {
            "total_items": total_items,
            "content_type_counts": content_type_counts,
            "export_checksum": export_checksum,
        }

    def unpack_folder(
        self,
        db_path: Path,
        output_dir: Path,
        content_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export dashboards and looks organized by folder hierarchy.

        Args:
            db_path: Path to SQLite database
            output_dir: Root directory for YAML export
            content_types: Optional list of content types to export (default: Dashboard/Look)

        Returns:
            Metadata about the export operation
        """
        import logging

        logger = logging.getLogger(__name__)

        output_dir.mkdir(parents=True, exist_ok=True)

        # Create _orphaned directory for missing folders
        (output_dir / "_orphaned").mkdir(exist_ok=True)

        # Fetch all folders from repository
        folders = self._repository.list_content(content_type=ContentType.FOLDER)

        # Build folder hierarchy tree
        tree_builder = FolderTreeBuilder()
        try:
            root_nodes = tree_builder.build_from_folders(
                [msgspec.msgpack.decode(folder.content_data) for folder in folders]
            )
        except ValueError as e:
            logger.error(f"Folder hierarchy error: {e}")
            raise RuntimeError(f"Circular reference detected in folder hierarchy: {e}") from e

        # Create directory structure
        tree_builder.create_directory_hierarchy(root_nodes, output_dir)

        # Determine content types to export (default to dashboards/looks)
        if content_types:
            export_types = [ContentType[ct.upper()] for ct in content_types]
        else:
            export_types = [ContentType.DASHBOARD, ContentType.LOOK]

        # Build folder map for metadata - include ALL nodes, not just root_nodes
        all_nodes = tree_builder.get_all_nodes(root_nodes)
        folder_map = {
            node.id: FolderInfo(
                id=node.id,
                name=node.name,
                parent_id=node.parent_id,
                path=node.filesystem_path,
                depth=node.depth,
                child_count=len(node.children),
                original_name=node.name if node.name != node.sanitized_name else None,
                sanitized=node.name != node.sanitized_name,
            )
            for node in all_nodes.values()
        }

        # Tracking variables
        content_type_counts: dict[str, int] = {}
        total_items = 0

        # Rich progress bar for export tracking
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            DownloadColumn(),
            TimeRemainingColumn(),
        ) as progress:
            export_task = progress.add_task(
                "[green]Exporting content...",
                total=len(export_types),
            )

            # Tracking node for content type - include ALL nodes
            content_nodes: dict[str, dict[str, FolderTreeNode]] = {
                content_type.name: all_nodes.copy()
                for content_type in export_types
            }

            # Export each content type
            for content_type in export_types:
                progress.update(export_task, description=f"Exporting {content_type.name}")

                # Fetch content items for this type
                content_items: list[ContentItem] = self._repository.list_content(
                    content_type=content_type
                )
                content_type_counts[content_type.name] = len(content_items)
                total_items += len(content_items)

                type_progress = progress.add_task(
                    f"[cyan]{content_type.name} items",
                    total=len(content_items),
                )

                for item in content_items:
                    # Serialize item to YAML
                    exported_dict = msgspec.msgpack.decode(item.content_data)

                    # Compute SHA-256 checksum directly from msgpack blob (much faster)
                    blob_checksum = hashlib.sha256(item.content_data).hexdigest()

                    # Determine folder path (handle orphans)
                    folder_id = exported_dict.get("folder_id")

                    if not folder_id or folder_id not in folder_map:
                        # Orphaned item (no folder or invalid folder_id)
                        yaml_path = output_dir / "_orphaned" / f"{item.id}.yaml"
                        logger.warning(f"Item {item.id} has missing/invalid folder_id: {folder_id}")
                        node = None
                    else:
                        # Lookup folder node
                        node = content_nodes[content_type.name].get(folder_id)

                        if node:
                            # Update folder stats
                            if content_type == ContentType.DASHBOARD:
                                node.dashboard_count += 1
                            elif content_type == ContentType.LOOK:
                                node.look_count += 1

                            # Use node's filesystem_path
                            yaml_path = output_dir / f"{node.filesystem_path}/{item.id}.yaml"
                        else:
                            # Fallback to orphaned if no matching node found
                            yaml_path = output_dir / "_orphaned" / f"{item.id}.yaml"
                            logger.warning(f"Folder node not found for {item.id}: {folder_id}")

                    # Add metadata section
                    exported_dict["_metadata"] = {
                        "db_id": str(item.id),
                        "content_type": content_type.name,
                        "exported_at": datetime.now().isoformat(),
                        "content_size": len(item.content_data),
                        "checksum": f"sha256:{blob_checksum}",
                        "folder_path": node.filesystem_path if node else None,
                    }

                    # Write to YAML
                    yaml_str = self._yaml_serializer.serialize(exported_dict)
                    yaml_path.write_text(yaml_str)

                    progress.update(type_progress, advance=1)

                progress.update(export_task, advance=1)

        # Compute overall export checksum
        export_checksum = compute_export_checksum(output_dir)

        # Generate metadata
        metadata = self._metadata_manager.generate_metadata(
            strategy=ExportStrategy.FOLDER,
            content_type_counts=content_type_counts,
            database_schema_version=self._repository.get_schema_version(),
            source_database=db_path,
            folder_map=folder_map,
            checksum=export_checksum,
        )

        # Write metadata
        metadata_file = output_dir / "metadata.json"
        with metadata_file.open("w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

        return {
            "total_items": total_items,
            "content_type_counts": content_type_counts,
            "export_checksum": export_checksum,
        }
