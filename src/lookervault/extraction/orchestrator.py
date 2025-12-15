"""Orchestration of content extraction workflow."""

import itertools
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from lookervault.exceptions import OrchestrationError
from lookervault.extraction.batch_processor import MemoryAwareBatchProcessor
from lookervault.extraction.progress import ProgressTracker
from lookervault.storage.models import (
    Checkpoint,
    ContentItem,
    ContentType,
    ExtractionSession,
    SessionStatus,
)
from lookervault.storage.repository import ContentRepository
from lookervault.storage.serializer import ContentSerializer

if TYPE_CHECKING:
    from lookervault.looker.extractor import ContentExtractor

logger = logging.getLogger(__name__)


@dataclass
class ExtractionConfig:
    """Configuration for extraction operation."""

    content_types: list[int]
    batch_size: int = 100
    fields: str | None = None
    resume: bool = True
    incremental: bool = False
    verify: bool = False
    output_mode: str = "table"
    folder_ids: set[str] | None = None
    recursive_folders: bool = False


@dataclass
class ExtractionResult:
    """Result of extraction operation."""

    session_id: str
    total_items: int
    items_by_type: dict[int, int] = field(default_factory=dict)
    errors: int = 0
    duration_seconds: float = 0.0
    checkpoints_created: int = 0
    new_items: int = 0
    updated_items: int = 0
    deleted_items: int = 0


class ExtractionOrchestrator:
    """Orchestrates content extraction workflow."""

    def __init__(
        self,
        extractor: "ContentExtractor",
        repository: ContentRepository,
        serializer: ContentSerializer,
        progress: ProgressTracker,
        config: ExtractionConfig,
    ):
        """Initialize orchestrator with dependencies.

        Args:
            extractor: Content extractor
            repository: Storage repository
            serializer: Content serializer
            progress: Progress tracker
            config: Extraction configuration
        """
        self.extractor = extractor
        self.repository = repository
        self.serializer = serializer
        self.progress = progress
        self.config = config
        self.batch_processor = MemoryAwareBatchProcessor()

    def extract(self) -> ExtractionResult:
        """Execute extraction workflow.

        Returns:
            ExtractionResult with summary

        Raises:
            OrchestrationError: If extraction fails
        """
        start_time = datetime.now()

        # Create extraction session
        session = ExtractionSession(
            status=SessionStatus.RUNNING,
            config={
                "content_types": self.config.content_types,
                "batch_size": self.config.batch_size,
                "fields": self.config.fields,
            },
        )
        self.repository.create_session(session)

        logger.info(f"Starting extraction session {session.id}")

        result = ExtractionResult(session_id=session.id, total_items=0)

        try:
            # Expand folder hierarchy BEFORE any content type extraction
            if self.config.folder_ids and self.config.recursive_folders:
                self._expand_folder_hierarchy_early(session)

            # Extract each content type
            for content_type in self.config.content_types:
                items_extracted = self._extract_content_type(content_type, session.id)
                result.items_by_type[content_type] = items_extracted
                result.total_items += items_extracted

            # Mark session as complete
            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.now()
            session.total_items = result.total_items
            self.repository.update_session(session)

            # Calculate duration
            result.duration_seconds = (datetime.now() - start_time).total_seconds()

            logger.info(
                f"Extraction complete: {result.total_items} items in {result.duration_seconds:.1f}s"
            )

            return result

        except Exception as e:
            # Mark session as failed
            session.status = SessionStatus.FAILED
            session.error_count = 1
            self.repository.update_session(session)

            logger.error(f"Extraction failed: {e}")
            raise OrchestrationError(f"Extraction failed: {e}") from e

    def _extract_content_type(self, content_type: int, session_id: str) -> int:
        """Extract all items of a specific content type.

        Args:
            content_type: ContentType enum value
            session_id: Extraction session ID

        Returns:
            Number of items extracted

        Raises:
            OrchestrationError: If extraction fails
        """
        content_type_name = ContentType(content_type).name.lower()
        task_id = f"extract_{content_type_name}"

        logger.info(f"Extracting {content_type_name}")

        # Check for existing incomplete checkpoint if resume enabled
        if self.config.resume:
            checkpoint = self.repository.get_latest_checkpoint(content_type, session_id)
            if checkpoint:
                logger.info(f"Found checkpoint for {content_type_name}, resuming")
                return self._resume_extraction(content_type, checkpoint)

        # Start new extraction
        checkpoint = Checkpoint(
            session_id=session_id,
            content_type=content_type,
            checkpoint_data={
                "content_type": content_type_name,
                "batch_size": self.config.batch_size,
                "incremental": self.config.incremental,
            },
        )
        # Save initial checkpoint
        self.repository.save_checkpoint(checkpoint)

        try:
            # Determine timestamp for incremental extraction
            updated_after = None
            if self.config.incremental:
                updated_after = self.repository.get_last_sync_timestamp(content_type)
                if updated_after:
                    logger.info(
                        f"Incremental mode: extracting {content_type_name} "
                        f"updated after {updated_after.isoformat()}"
                    )

            # Extract items from Looker API
            # Handle folder-level filtering for dashboards and looks
            content_type_enum = ContentType(content_type)
            supports_folder_filtering = content_type_enum in [
                ContentType.DASHBOARD,
                ContentType.LOOK,
            ]

            if (
                self.config.folder_ids
                and supports_folder_filtering
                and len(self.config.folder_ids) > 1
            ):
                # Multi-folder: Chain iterators (one per folder_id)
                logger.info(
                    f"Using sequential multi-folder extraction for {content_type_name} "
                    f"({len(self.config.folder_ids)} folders)"
                )
                iterators = [
                    self.extractor.extract_all(
                        content_type_enum,
                        fields=self.config.fields,
                        batch_size=self.config.batch_size,
                        updated_after=updated_after,
                        folder_id=folder_id,
                    )
                    for folder_id in self.config.folder_ids
                ]
                items_iterator = itertools.chain(*iterators)
            elif (
                self.config.folder_ids
                and supports_folder_filtering
                and len(self.config.folder_ids) == 1
            ):
                # Single folder: SDK-level filtering
                folder_id = list(self.config.folder_ids)[0]
                logger.info(
                    f"Using SDK-level folder filtering for {content_type_name} (folder_id={folder_id})"
                )
                items_iterator = self.extractor.extract_all(
                    content_type_enum,
                    fields=self.config.fields,
                    batch_size=self.config.batch_size,
                    updated_after=updated_after,
                    folder_id=folder_id,
                )
            else:
                # No folder filtering or content type doesn't support it
                items_iterator = self.extractor.extract_all(
                    content_type_enum,
                    fields=self.config.fields,
                    batch_size=self.config.batch_size,
                    updated_after=updated_after,
                )

            # For incremental mode, get existing IDs for soft delete detection
            existing_ids = set()
            extracted_ids = set()
            if self.config.incremental:
                existing_ids = self.repository.get_content_ids(content_type)

            # Count items first to show progress (if we can)
            # For now, start with unknown total
            self.progress.start_task(task_id, f"Extracting {content_type_name}", total=None)

            items_count = 0
            for item_dict in items_iterator:
                # Create ContentItem
                content_item = self._dict_to_content_item(item_dict, content_type)

                # Track extracted IDs for soft delete detection
                if self.config.incremental:
                    extracted_ids.add(content_item.id)

                # Save to repository
                self.repository.save_content(content_item)

                # Update progress
                items_count += 1
                self.progress.update_task(task_id, advance=1)

            # Handle soft deletes in incremental mode
            deleted_count = 0
            if self.config.incremental and updated_after:
                deleted_ids = existing_ids - extracted_ids
                for deleted_id in deleted_ids:
                    self.repository.delete_content(deleted_id, soft=True)
                    deleted_count += 1

                if deleted_count > 0:
                    logger.info(f"Marked {deleted_count} {content_type_name} as deleted")

            # Complete checkpoint
            checkpoint.completed_at = datetime.now()
            checkpoint.item_count = items_count
            checkpoint.checkpoint_data["total_processed"] = items_count
            checkpoint.checkpoint_data["deleted_items"] = deleted_count

            # Update checkpoint in DB
            self.repository.update_checkpoint(checkpoint)

            self.progress.complete_task(task_id)
            logger.info(f"Completed {content_type_name}: {items_count} items")

            return items_count

        except Exception as e:
            self.progress.fail_task(task_id, str(e))
            logger.error(f"Failed to extract {content_type_name}: {e}")
            raise OrchestrationError(f"Failed to extract {content_type_name}: {e}") from e

    def _resume_extraction(self, content_type: int, checkpoint: Checkpoint) -> int:
        """Resume extraction from checkpoint.

        Args:
            content_type: ContentType enum value
            checkpoint: Checkpoint to resume from

        Returns:
            Number of items extracted

        Raises:
            OrchestrationError: If resume fails
        """
        content_type_name = ContentType(content_type).name.lower()
        logger.info(f"Resuming extraction for {content_type_name}")

        # Validate checkpoint data
        try:
            checkpoint_data = checkpoint.checkpoint_data
            if not isinstance(checkpoint_data, dict):
                raise ValueError("Invalid checkpoint data format")

            # Check if checkpoint has required fields
            total_processed = checkpoint_data.get("total_processed", 0)

            logger.info(
                f"Checkpoint found: {total_processed} items already processed for {content_type_name}"
            )

            # Check if extraction was actually complete (checkpoint just wasn't updated)
            # Count current items in database
            existing_items = self.repository.list_content(
                content_type=content_type, include_deleted=False
            )
            existing_count = len(existing_items)

            if existing_count >= total_processed and total_processed > 0:
                # Extraction appears complete, just mark checkpoint as done
                logger.info(
                    f"Extraction appears complete ({existing_count} items in DB), "
                    "marking checkpoint as complete"
                )
                checkpoint.completed_at = datetime.now()
                checkpoint.item_count = existing_count
                self.repository.update_checkpoint(checkpoint)
                return existing_count

            # Resume extraction - for simplicity, we'll re-extract all items
            # The repository's upsert logic will handle duplicates efficiently
            logger.warning(
                f"Resuming from beginning for {content_type_name} (will skip duplicates via upsert)"
            )

            # Clear the checkpoint and start fresh extraction
            # This is simpler and safer than trying to track exact offsets
            checkpoint.completed_at = None
            checkpoint.error_message = None
            self.repository.update_checkpoint(checkpoint)

            # Re-extract (upserts will handle duplicates)
            return self._extract_content_type(content_type, checkpoint.session_id)

        except Exception as e:
            logger.error(f"Failed to resume extraction for {content_type_name}: {e}")
            # If resume fails, try starting fresh
            logger.warning(f"Resume failed, attempting fresh extraction for {content_type_name}")
            checkpoint.error_message = f"Resume failed: {e}"
            self.repository.update_checkpoint(checkpoint)
            return self._extract_content_type(content_type, checkpoint.session_id)

    @staticmethod
    def _get_item_id(item_dict: dict[str, Any], content_type: int) -> str | None:
        """Get the identifier field for an item based on content type.

        Args:
            item_dict: Raw API response dictionary
            content_type: ContentType enum value

        Returns:
            Item identifier or None if not found
        """
        # LookML Models use 'name' as their identifier, not 'id'
        if content_type == ContentType.LOOKML_MODEL:
            return item_dict.get("name")

        # All other content types use 'id'
        return item_dict.get("id")

    def _dict_to_content_item(self, item_dict: dict, content_type: int) -> ContentItem:
        """Convert API response dict to ContentItem.

        Args:
            item_dict: Dictionary from Looker API
            content_type: ContentType enum value

        Returns:
            ContentItem object

        Raises:
            OrchestrationError: If conversion fails
        """
        try:
            # Serialize content
            content_data = self.serializer.serialize(item_dict)

            # Extract common fields - some content types use 'name' instead of 'id'
            item_id = self._get_item_id(item_dict, content_type)
            if not item_id:
                item_id = "unknown"
                logger.warning(
                    f"Item missing identifier field for {ContentType(content_type).name}"
                )

            item_id = str(item_id)
            name = item_dict.get("title") or item_dict.get("name") or item_id

            # Extract metadata
            owner_id = item_dict.get("user_id")
            # Convert owner_id to int if present (Looker API may return as string)
            if owner_id is not None:
                try:
                    owner_id = int(owner_id)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Could not convert owner_id '{owner_id}' to int for item {item_id}"
                    )
                    owner_id = None

            owner_email = None
            if "user" in item_dict and isinstance(item_dict["user"], dict):
                owner_email = item_dict["user"].get("email")

            # Extract folder_id if present (dashboards, looks, boards)
            folder_id = None
            if "folder_id" in item_dict and item_dict["folder_id"] is not None:
                folder_id = str(item_dict["folder_id"])

            # Parse timestamps
            created_at = datetime.now(UTC)
            updated_at = datetime.now(UTC)

            if "created_at" in item_dict and item_dict["created_at"]:
                try:
                    created_at_val = item_dict["created_at"]
                    if isinstance(created_at_val, str):
                        created_at = datetime.fromisoformat(created_at_val.replace("Z", "+00:00"))
                    elif isinstance(created_at_val, datetime):
                        created_at = created_at_val
                    elif isinstance(created_at_val, int | float):
                        # Unix timestamp
                        created_at = datetime.fromtimestamp(created_at_val, tz=UTC)
                    else:
                        logger.warning(
                            f"Unexpected type for created_at: {type(created_at_val).__name__} = {created_at_val}"
                        )
                except (ValueError, AttributeError, TypeError) as e:
                    logger.warning(
                        f"Could not parse created_at (type: {type(item_dict['created_at']).__name__}) "
                        f"'{item_dict['created_at']}' for item {item_id}: {e}"
                    )

            if "updated_at" in item_dict and item_dict["updated_at"]:
                try:
                    updated_at_val = item_dict["updated_at"]
                    if isinstance(updated_at_val, str):
                        updated_at = datetime.fromisoformat(updated_at_val.replace("Z", "+00:00"))
                    elif isinstance(updated_at_val, datetime):
                        updated_at = updated_at_val
                    elif isinstance(updated_at_val, int | float):
                        # Unix timestamp
                        updated_at = datetime.fromtimestamp(updated_at_val, tz=UTC)
                    else:
                        logger.warning(
                            f"Unexpected type for updated_at: {type(updated_at_val).__name__} = {updated_at_val}"
                        )
                except (ValueError, AttributeError, TypeError) as e:
                    logger.warning(
                        f"Could not parse updated_at (type: {type(item_dict['updated_at']).__name__}) "
                        f"'{item_dict['updated_at']}' for item {item_id}: {e}"
                    )

            # Create composite ID
            content_type_name = ContentType(content_type).name.lower()
            composite_id = f"{content_type_name}::{item_id}"

            return ContentItem(
                id=composite_id,
                content_type=content_type,
                name=name,
                owner_id=owner_id,
                owner_email=owner_email,
                created_at=created_at,
                updated_at=updated_at,
                content_data=content_data,
                folder_id=folder_id,
            )
        except Exception as e:
            raise OrchestrationError(f"Failed to convert item to ContentItem: {e}") from e

    def _expand_folder_hierarchy_early(self, session: ExtractionSession) -> None:
        """Expand folder hierarchy BEFORE content extraction.

        This method attempts to expand folder IDs recursively by:
        1. Checking if folders are already in the repository
        2. If yes: expanding immediately using cached hierarchy
        3. If no: extracting folders first, then expanding

        This ensures multi-folder iterator chaining works correctly.

        Args:
            session: Current extraction session (for metadata caching)
        """
        from lookervault.folder.hierarchy import FolderHierarchyResolver

        root_folder_ids = list(self.config.folder_ids)

        # Try to load folders from repository
        try:
            hierarchy_resolver = FolderHierarchyResolver(self.repository)

            # Check if folders exist in repository
            folder_count = len(
                self.repository.list_content(
                    content_type=ContentType.FOLDER.value, include_deleted=False
                )
            )

            if folder_count > 0:
                # Folders exist - expand immediately
                logger.info(
                    f"Found {folder_count} folders in repository, expanding hierarchy immediately"
                )
                all_folder_ids = hierarchy_resolver.get_all_descendant_ids(
                    root_folder_ids, include_roots=True
                )

                # Update config with expanded folder IDs
                self.config.folder_ids = all_folder_ids

                logger.info(
                    f"Expanded {len(root_folder_ids)} root folder(s) to "
                    f"{len(all_folder_ids)} total folder(s) recursively (from repository cache)"
                )
            else:
                # No folders in DB - must extract them first
                logger.info(
                    "No folders in repository, extracting folders first for recursive expansion"
                )

                # Ensure FOLDER content type is in extraction list
                if ContentType.FOLDER.value not in self.config.content_types:
                    logger.warning(
                        "Adding ContentType.FOLDER to extraction list for recursive folder expansion"
                    )
                    # Prepend folders to ensure they're extracted first
                    self.config.content_types.insert(0, ContentType.FOLDER.value)

                # Extract folders
                logger.info("Extracting folders for hierarchy expansion")
                self._extract_content_type(ContentType.FOLDER.value, session.id)

                # Now expand hierarchy
                hierarchy_resolver = FolderHierarchyResolver(
                    self.repository
                )  # Reload with fresh data
                all_folder_ids = hierarchy_resolver.get_all_descendant_ids(
                    root_folder_ids, include_roots=True
                )

                # Update config with expanded folder IDs
                self.config.folder_ids = all_folder_ids

                logger.info(
                    f"Expanded {len(root_folder_ids)} root folder(s) to "
                    f"{len(all_folder_ids)} total folder(s) recursively (after extracting folders)"
                )

        except Exception as e:
            logger.error(f"Failed to expand folder hierarchy: {e}")
            raise OrchestrationError(f"Folder hierarchy expansion failed: {e}") from e
