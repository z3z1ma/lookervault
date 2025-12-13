"""Orchestration of content extraction workflow."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from lookervault.exceptions import OrchestrationError
from lookervault.extraction.batch_processor import MemoryAwareBatchProcessor
from lookervault.extraction.progress import ProgressTracker
from lookervault.looker.extractor import ContentExtractor
from lookervault.storage.models import (
    Checkpoint,
    ContentItem,
    ContentType,
    ExtractionSession,
    SessionStatus,
)
from lookervault.storage.repository import ContentRepository
from lookervault.storage.serializer import ContentSerializer

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
        extractor: ContentExtractor,
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
            items_iterator = self.extractor.extract_all(
                ContentType(content_type),
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

            # Extract common fields
            item_id = str(item_dict.get("id", "unknown"))
            name = item_dict.get("title") or item_dict.get("name") or item_id

            # Handle owner fields
            owner_id = None
            owner_email = None
            if "user_id" in item_dict:
                owner_id = item_dict["user_id"]
            if "owner_id" in item_dict:
                owner_id = item_dict["owner_id"]
            if "email" in item_dict:
                owner_email = item_dict["email"]

            # Handle timestamps
            created_at = datetime.fromisoformat(
                item_dict.get("created_at", datetime.now().isoformat())
            )
            updated_at = datetime.fromisoformat(
                item_dict.get("updated_at", datetime.now().isoformat())
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
            )
        except Exception as e:
            raise OrchestrationError(f"Failed to convert item to ContentItem: {e}") from e
