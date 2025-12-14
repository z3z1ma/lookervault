"""Content restoration engine for Looker objects.

This module provides the core LookerContentRestorer class that handles:
- Single-item restoration from SQLite backups to Looker instances
- Deserialization and validation of content before restoration
- Smart update vs. create logic based on destination existence
- Rate limiting and retry logic for API calls
- ID mapping for cross-instance migrations
"""

import logging
import time
from typing import Any, Protocol

from looker_sdk import error as looker_error

from lookervault.exceptions import (
    DeserializationError,
    NotFoundError,
    RateLimitError,
    RestorationError,
    ValidationError,
)
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
from lookervault.extraction.retry import retry_on_rate_limit
from lookervault.looker.client import LookerClient
from lookervault.restoration.deserializer import ContentDeserializer
from lookervault.restoration.validation import RestorationValidator
from lookervault.storage.models import ContentType, RestorationResult
from lookervault.storage.repository import ContentRepository

logger = logging.getLogger(__name__)


class IDMapper(Protocol):
    """Protocol for ID mapping operations during cross-instance migration."""

    def save_mapping(
        self,
        content_type: ContentType,
        source_id: str,
        destination_id: str,
        session_id: str | None = None,
    ) -> None:
        """Save source ID → destination ID mapping."""
        ...

    def get_destination_id(self, content_type: ContentType, source_id: str) -> str | None:
        """Get destination ID for source ID."""
        ...

    def translate_references(
        self, content_dict: dict[str, Any], content_type: ContentType
    ) -> dict[str, Any]:
        """Translate FK references from source IDs to destination IDs."""
        ...


class LookerContentRestorer:
    """Looker SDK-based content restorer implementation.

    This class provides the core restoration engine for single-item and bulk
    content restoration from SQLite backups to Looker instances. It handles:

    - Fetching content from SQLite repository
    - Deserializing binary blobs to SDK-compatible dictionaries
    - Validating content against Looker API schemas
    - Checking destination instance for existing content
    - Creating new content or updating existing content via API
    - Recording ID mappings for cross-instance migrations
    - Rate limiting and retry logic for resilient API operations

    The restoration flow follows these steps:
    1. Fetch content from SQLite (content_items table)
    2. Deserialize content_data blob to dict
    3. Validate content structure and required fields
    4. Check if content exists in destination (GET request)
    5. If exists: update (PATCH), if not: create (POST)
    6. Record ID mapping if created and id_mapper provided
    7. Return RestorationResult with status, duration, errors

    Examples:
        >>> # Basic single-item restoration
        >>> client = LookerClient(api_url, client_id, client_secret)
        >>> repo = SQLiteContentRepository("backup.db")
        >>> restorer = LookerContentRestorer(client, repo)
        >>> result = restorer.restore_single("42", ContentType.DASHBOARD)
        >>> print(f"Status: {result.status}, Destination ID: {result.destination_id}")

        >>> # Dry run validation without API calls
        >>> result = restorer.restore_single("42", ContentType.DASHBOARD, dry_run=True)
        >>> if result.status == "failed":
        ...     print(f"Validation errors: {result.error_message}")

        >>> # Cross-instance migration with ID mapping
        >>> id_mapper = IDMapper(repo, "source.looker.com", "dest.looker.com")
        >>> rate_limiter = AdaptiveRateLimiter(requests_per_minute=100)
        >>> restorer = LookerContentRestorer(client, repo, rate_limiter, id_mapper)
        >>> result = restorer.restore_single("42", ContentType.DASHBOARD)
    """

    # SDK method name mapping for content types
    # Format: {ContentType: (get_method, create_method, update_method)}
    _SDK_METHOD_MAP: dict[ContentType, tuple[str, str, str]] = {
        ContentType.DASHBOARD: ("dashboard", "create_dashboard", "update_dashboard"),
        ContentType.LOOK: ("look", "create_look", "update_look"),
        ContentType.FOLDER: ("folder", "create_folder", "update_folder"),
        ContentType.USER: ("user", "create_user", "update_user"),
        ContentType.GROUP: ("group", "create_group", "update_group"),
        ContentType.ROLE: ("role", "create_role", "update_role"),
        ContentType.BOARD: ("board", "create_board", "update_board"),
        ContentType.SCHEDULED_PLAN: (
            "scheduled_plan",
            "create_scheduled_plan",
            "update_scheduled_plan",
        ),
        ContentType.LOOKML_MODEL: ("lookml_model", "create_lookml_model", "update_lookml_model"),
        ContentType.PERMISSION_SET: (
            "permission_set",
            "create_permission_set",
            "update_permission_set",
        ),
        ContentType.MODEL_SET: ("model_set", "create_model_set", "update_model_set"),
    }

    def __init__(
        self,
        client: LookerClient,
        repository: ContentRepository,
        rate_limiter: AdaptiveRateLimiter | None = None,
        id_mapper: IDMapper | None = None,
    ):
        """Initialize LookerContentRestorer.

        Args:
            client: LookerClient for API calls to destination instance
            repository: SQLite repository for reading content from backups
            rate_limiter: Optional adaptive rate limiter for API throttling
            id_mapper: Optional ID mapper for cross-instance migration

        Examples:
            >>> # Basic setup
            >>> client = LookerClient(api_url, client_id, client_secret)
            >>> repo = SQLiteContentRepository("backup.db")
            >>> restorer = LookerContentRestorer(client, repo)

            >>> # With rate limiting
            >>> rate_limiter = AdaptiveRateLimiter(requests_per_minute=100, requests_per_second=10)
            >>> restorer = LookerContentRestorer(client, repo, rate_limiter=rate_limiter)

            >>> # With ID mapping for cross-instance migration
            >>> id_mapper = IDMapper(repo, "source.looker.com", "dest.looker.com")
            >>> restorer = LookerContentRestorer(client, repo, id_mapper=id_mapper)
        """
        self.client = client
        self.repository = repository
        self.rate_limiter = rate_limiter
        self.id_mapper = id_mapper

        # Initialize helper components
        self.deserializer = ContentDeserializer()
        self.validator = RestorationValidator()

        logger.info(
            f"Initialized LookerContentRestorer: "
            f"rate_limiter={'enabled' if rate_limiter else 'disabled'}, "
            f"id_mapper={'enabled' if id_mapper else 'disabled'}"
        )

    def check_exists(self, content_id: str, content_type: ContentType) -> bool:
        """Check if content exists in destination Looker instance.

        Performs a GET request to check if the content ID already exists in the
        destination instance. This is used to determine whether to create new
        content or update existing content.

        Args:
            content_id: Content ID to check (original ID from backup)
            content_type: ContentType enum value

        Returns:
            True if content exists (200 OK), False if not found (404)

        Raises:
            RestorationError: If content_type is not supported
            Exception: For unexpected API errors (non-404, non-200)

        Examples:
            >>> restorer = LookerContentRestorer(client, repo)
            >>> exists = restorer.check_exists("42", ContentType.DASHBOARD)
            >>> if exists:
            ...     print("Dashboard 42 exists, will update")
            >>> else:
            ...     print("Dashboard 42 not found, will create")
        """
        # Validate content type is supported
        if content_type not in self._SDK_METHOD_MAP:
            raise RestorationError(
                f"Unsupported content type for restoration: {content_type}. "
                f"Supported types: {list(self._SDK_METHOD_MAP.keys())}"
            )

        # Get the SDK method name for this content type
        get_method_name, _, _ = self._SDK_METHOD_MAP[content_type]

        try:
            # Call SDK get method (e.g., client.sdk.dashboard("42"))
            get_method = getattr(self.client.sdk, get_method_name)
            get_method(content_id)

            logger.debug(f"{content_type.name} {content_id} exists in destination")
            return True

        except looker_error.SDKError as e:
            error_str = str(e)

            # 404 means content doesn't exist - this is expected
            if "404" in error_str or "Not Found" in error_str:
                logger.debug(f"{content_type.name} {content_id} not found in destination")
                return False

            # Other errors (401, 403, 500, etc.) are unexpected
            logger.warning(
                f"Unexpected API error checking {content_type.name} {content_id} existence: {error_str}"
            )
            # Raise to caller - they should handle this appropriately
            raise

    @retry_on_rate_limit
    def _call_api_update(
        self, content_type: ContentType, content_id: str, content_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Call SDK update_* method with retry logic for PATCH operations.

        Updates existing content in the destination Looker instance. This method
        is decorated with retry logic that handles HTTP 429 rate limit errors
        with exponential backoff.

        Args:
            content_type: ContentType enum value
            content_id: Content ID to update
            content_dict: Content data as dictionary (SDK-compatible format)

        Returns:
            API response as dictionary containing updated content

        Raises:
            RateLimitError: If rate limited (HTTP 429) - retryable by decorator
            ValidationError: If 422 validation error (not retryable)
            RestorationError: For other API errors

        Examples:
            >>> content_dict = {"title": "Updated Dashboard", "folder_id": "123"}
            >>> response = restorer._call_api_update(ContentType.DASHBOARD, "42", content_dict)
            >>> print(f"Updated dashboard ID: {response['id']}")
        """
        # Apply rate limiting if configured
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Get the SDK update method name
        _, _, update_method_name = self._SDK_METHOD_MAP[content_type]

        try:
            # Call SDK update method (e.g., client.sdk.update_dashboard("42", body))
            update_method = getattr(self.client.sdk, update_method_name)
            response = update_method(content_id, body=content_dict)

            # Notify rate limiter of success
            if self.rate_limiter:
                self.rate_limiter.on_success()

            logger.debug(f"Successfully updated {content_type.name} {content_id}")

            # Convert Looker SDK model to dict
            if hasattr(response, "__dict__"):
                return dict(response)
            return response

        except looker_error.SDKError as e:
            error_str = str(e)

            # HTTP 429 - Rate limit exceeded (retryable)
            if "429" in error_str or "Too Many Requests" in error_str:
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()

                logger.warning(f"Rate limit hit updating {content_type.name} {content_id}")
                raise RateLimitError(f"Rate limit exceeded: {error_str}") from e

            # HTTP 422 - Validation error (not retryable)
            if "422" in error_str or "Unprocessable" in error_str:
                logger.error(
                    f"Validation error updating {content_type.name} {content_id}: {error_str}"
                )
                raise ValidationError(f"Content validation failed: {error_str}") from e

            # Other errors
            logger.error(f"API error updating {content_type.name} {content_id}: {error_str}")
            raise RestorationError(f"Failed to update content: {error_str}") from e

    @retry_on_rate_limit
    def _call_api_create(
        self, content_type: ContentType, content_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Call SDK create_* method with retry logic for POST operations.

        Creates new content in the destination Looker instance. This method
        is decorated with retry logic that handles HTTP 429 rate limit errors
        with exponential backoff.

        Args:
            content_type: ContentType enum value
            content_dict: Content data as dictionary (SDK-compatible format)

        Returns:
            API response as dictionary containing created content (includes new ID)

        Raises:
            RateLimitError: If rate limited (HTTP 429) - retryable by decorator
            ValidationError: If 422 validation error (not retryable)
            RestorationError: For other API errors

        Examples:
            >>> content_dict = {"title": "New Dashboard", "folder_id": "123"}
            >>> response = restorer._call_api_create(ContentType.DASHBOARD, content_dict)
            >>> print(f"Created dashboard with new ID: {response['id']}")
        """
        # Apply rate limiting if configured
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Get the SDK create method name
        _, create_method_name, _ = self._SDK_METHOD_MAP[content_type]

        try:
            # Call SDK create method (e.g., client.sdk.create_dashboard(body))
            create_method = getattr(self.client.sdk, create_method_name)
            response = create_method(body=content_dict)

            # Notify rate limiter of success
            if self.rate_limiter:
                self.rate_limiter.on_success()

            logger.debug(f"Successfully created {content_type.name}")

            # Convert Looker SDK model to dict
            if hasattr(response, "__dict__"):
                return dict(response)
            return response

        except looker_error.SDKError as e:
            error_str = str(e)

            # HTTP 429 - Rate limit exceeded (retryable)
            if "429" in error_str or "Too Many Requests" in error_str:
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()

                logger.warning(f"Rate limit hit creating {content_type.name}")
                raise RateLimitError(f"Rate limit exceeded: {error_str}") from e

            # HTTP 422 - Validation error (not retryable)
            if "422" in error_str or "Unprocessable" in error_str:
                logger.error(f"Validation error creating {content_type.name}: {error_str}")
                raise ValidationError(f"Content validation failed: {error_str}") from e

            # Other errors
            logger.error(f"API error creating {content_type.name}: {error_str}")
            raise RestorationError(f"Failed to create content: {error_str}") from e

    def restore_single(
        self, content_id: str, content_type: ContentType, dry_run: bool = False
    ) -> RestorationResult:
        """Restore a single content item from SQLite backup to Looker instance.

        This is the main restoration method that orchestrates the complete
        restoration flow:
        1. Fetch content from SQLite repository
        2. Deserialize binary blob to dictionary
        3. Validate content structure and fields
        4. (Optional) Translate foreign key references if id_mapper provided
        5. Check if content exists in destination instance
        6. If exists: update via PATCH, if not: create via POST
        7. Record ID mapping if created and id_mapper provided
        8. Return RestorationResult with status, duration, errors

        Args:
            content_id: Content ID to restore (from backup)
            content_type: ContentType enum value
            dry_run: If True, validate content without making API calls

        Returns:
            RestorationResult with operation details:
            - status: "success", "created", "updated", "failed", "skipped"
            - destination_id: New/existing ID in destination instance
            - error_message: Error details if restoration failed
            - retry_count: Number of retries attempted
            - duration_ms: Time taken for operation

        Raises:
            NotFoundError: If content not found in SQLite repository
            DeserializationError: If content_data blob is corrupted
            ValidationError: If content fails validation (dry_run only)

        Examples:
            >>> # Basic restoration
            >>> result = restorer.restore_single("42", ContentType.DASHBOARD)
            >>> if result.status in ["created", "updated"]:
            ...     print(f"Success! Destination ID: {result.destination_id}")
            >>> else:
            ...     print(f"Failed: {result.error_message}")

            >>> # Dry run validation
            >>> result = restorer.restore_single("42", ContentType.DASHBOARD, dry_run=True)
            >>> if result.status == "success":
            ...     print("Content is valid and ready to restore")

            >>> # Check result status
            >>> if result.status == "created":
            ...     print(f"Created new content with ID {result.destination_id}")
            >>> elif result.status == "updated":
            ...     print(f"Updated existing content {result.destination_id}")
            >>> elif result.status == "failed":
            ...     print(f"Restoration failed: {result.error_message}")
        """
        start_time = time.time()
        retry_count = 0

        try:
            # Step 1: Fetch content from SQLite repository
            logger.info(f"Restoring {content_type.name} {content_id} (dry_run={dry_run})")

            content_item = self.repository.get_content(content_id)
            if content_item is None:
                raise NotFoundError(
                    f"{content_type.name} {content_id} not found in SQLite repository"
                )

            # Verify content_type matches
            if content_item.content_type != content_type.value:
                raise ValidationError(
                    f"Content type mismatch: expected {content_type.name} ({content_type.value}), "
                    f"found type {content_item.content_type} for content_id {content_id}"
                )

            # Step 2: Deserialize binary blob to dictionary
            try:
                content_dict = self.deserializer.deserialize(
                    content_item.content_data, content_type, as_dict=True
                )
            except DeserializationError as e:
                logger.error(f"Deserialization failed for {content_type.name} {content_id}: {e}")
                raise

            # Step 3: Validate content structure and required fields
            validation_errors = self.validator.validate_content(content_dict, content_type)
            if validation_errors:
                error_msg = f"Content validation failed: {'; '.join(validation_errors)}"
                logger.error(f"{content_type.name} {content_id}: {error_msg}")
                raise ValidationError(error_msg)

            # If dry_run, stop here after validation
            if dry_run:
                duration_ms = (time.time() - start_time) * 1000
                logger.info(f"Dry run validation passed for {content_type.name} {content_id}")
                return RestorationResult(
                    content_id=content_id,
                    content_type=content_type.value,
                    status="success",
                    duration_ms=duration_ms,
                )

            # Step 4: Translate foreign key references if id_mapper provided
            if self.id_mapper:
                content_dict = self.id_mapper.translate_references(content_dict, content_type)

            # Step 5: Check if content exists in destination
            exists = self.check_exists(content_id, content_type)

            # Step 6: Update existing or create new content
            response_dict: dict[str, Any]
            operation: str

            if exists:
                # Update existing content (PATCH)
                operation = "updated"
                response_dict = self._call_api_update(content_type, content_id, content_dict)
                destination_id = content_id  # Same ID for updates

            else:
                # Create new content (POST)
                operation = "created"
                # Remove 'id' field from content_dict if present (API will assign new ID)
                content_dict.pop("id", None)

                response_dict = self._call_api_create(content_type, content_dict)

                # Extract destination_id from response
                destination_id = str(response_dict.get("id", content_id))

                # Step 7: Record ID mapping if created and id_mapper provided
                if self.id_mapper and destination_id != content_id:
                    self.id_mapper.save_mapping(
                        content_type=content_type,
                        source_id=content_id,
                        destination_id=destination_id,
                    )

            # Step 8: Return successful RestorationResult
            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                f"Successfully {operation} {content_type.name} {content_id} "
                f"(destination_id={destination_id}, duration={duration_ms:.1f}ms)"
            )

            return RestorationResult(
                content_id=content_id,
                content_type=content_type.value,
                status=operation,
                destination_id=destination_id,
                retry_count=retry_count,
                duration_ms=duration_ms,
            )

        except NotFoundError as e:
            # Content not in SQLite - return failed result
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Content not found: {e}")

            return RestorationResult(
                content_id=content_id,
                content_type=content_type.value,
                status="failed",
                error_message=str(e),
                retry_count=retry_count,
                duration_ms=duration_ms,
            )

        except (DeserializationError, ValidationError) as e:
            # Deserialization or validation failed - return failed result
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Validation/deserialization failed: {e}")

            return RestorationResult(
                content_id=content_id,
                content_type=content_type.value,
                status="failed",
                error_message=str(e),
                retry_count=retry_count,
                duration_ms=duration_ms,
            )

        except RateLimitError as e:
            # Rate limit error - already retried by decorator, still failed
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Rate limit error (after retries): {e}")

            return RestorationResult(
                content_id=content_id,
                content_type=content_type.value,
                status="failed",
                error_message=f"Rate limit exceeded after retries: {e}",
                retry_count=retry_count,
                duration_ms=duration_ms,
            )

        except RestorationError as e:
            # Generic restoration error
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Restoration error: {e}")

            return RestorationResult(
                content_id=content_id,
                content_type=content_type.value,
                status="failed",
                error_message=str(e),
                retry_count=retry_count,
                duration_ms=duration_ms,
            )

        except Exception as e:
            # Unexpected error
            duration_ms = (time.time() - start_time) * 1000
            logger.exception(f"Unexpected error restoring {content_type.name} {content_id}: {e}")

            return RestorationResult(
                content_id=content_id,
                content_type=content_type.value,
                status="failed",
                error_message=f"Unexpected error: {e}",
                retry_count=retry_count,
                duration_ms=duration_ms,
            )
