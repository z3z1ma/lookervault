# Python API Contract: Looker Content Restoration

**Feature**: 004-looker-restoration
**Date**: 2025-12-13
**Status**: Complete

## Overview

This document defines the internal Python API contracts for the restoration module. These classes and functions form the core restoration engine.

---

## 1. Deserializer

**Module**: `lookervault.restoration.deserializer`

### 1.1 ContentDeserializer

Deserializes SQLite binary blobs back into Looker SDK model instances or dictionaries.

```python
class ContentDeserializer:
    """Deserializes content_data blobs to Looker SDK Write* models or dicts."""

    def deserialize(
        self,
        content_data: bytes,
        content_type: ContentType,
        as_dict: bool = True
    ) -> dict[str, Any] | model.Model:
        """Deserialize binary content data to SDK model or dict.

        Args:
            content_data: Binary blob from SQLite content_items.content_data
            content_type: ContentType enum value
            as_dict: If True, return plain dict; if False, return SDK Write* model instance

        Returns:
            Deserialized content as dict or SDK model instance

        Raises:
            DeserializationError: If content_data is corrupted or invalid format
            ValueError: If content_type is not supported
        """

    def validate_schema(
        self,
        content_dict: dict[str, Any],
        content_type: ContentType
    ) -> list[str]:
        """Validate content against SDK model schema.

        Args:
            content_dict: Deserialized content dictionary
            content_type: ContentType enum value

        Returns:
            List of validation error messages (empty if valid)
        """
```

---

## 2. Restorer

**Module**: `lookervault.restoration.restorer`

### 2.1 ContentRestorer (Protocol)

```python
class ContentRestorer(Protocol):
    """Protocol for content restoration operations."""

    def restore_single(
        self,
        content_id: str,
        content_type: ContentType,
        dry_run: bool = False
    ) -> RestorationResult:
        """Restore a single content item.

        Args:
            content_id: ID of content to restore
            content_type: ContentType enum value
            dry_run: If True, validate without making API calls

        Returns:
            RestorationResult with operation details

        Raises:
            NotFoundError: If content not found in SQLite
            ValidationError: If content fails validation
            APIError: If Looker API call fails
        """

    def restore_bulk(
        self,
        content_type: ContentType,
        config: RestorationConfig
    ) -> RestorationSummary:
        """Restore all content of a given type.

        Args:
            content_type: ContentType enum value
            config: Restoration configuration

        Returns:
            RestorationSummary with aggregated results
        """

    def check_exists(
        self,
        content_id: str,
        content_type: ContentType
    ) -> bool:
        """Check if content exists in destination Looker instance.

        Args:
            content_id: Content ID to check
            content_type: ContentType enum value

        Returns:
            True if exists, False otherwise
        """
```

### 2.2 LookerContentRestorer

Implementation of ContentRestorer using Looker SDK.

```python
class LookerContentRestorer:
    """Looker SDK-based content restorer implementation."""

    def __init__(
        self,
        client: LookerClient,
        repository: ContentRepository,
        rate_limiter: AdaptiveRateLimiter | None = None,
        id_mapper: IDMapper | None = None
    ):
        """Initialize restorer.

        Args:
            client: LookerClient for API calls
            repository: SQLite repository for reading content
            rate_limiter: Optional adaptive rate limiter
            id_mapper: Optional ID mapper for cross-instance migration
        """

    def restore_single(
        self,
        content_id: str,
        content_type: ContentType,
        dry_run: bool = False
    ) -> RestorationResult:
        """Restore single content item.

        Flow:
          1. Fetch content from SQLite
          2. Deserialize content_data
          3. Validate content
          4. Check if destination ID exists (GET request)
          5. If exists: call update_* (PATCH)
             If not exists: call create_* (POST)
          6. Record ID mapping if created
          7. Return RestorationResult

        Args:
            content_id: Content ID
            content_type: ContentType
            dry_run: Validate only

        Returns:
            RestorationResult
        """

    def restore_bulk(
        self,
        content_type: ContentType,
        config: RestorationConfig
    ) -> RestorationSummary:
        """Restore all content of type (delegates to ParallelOrchestrator).

        Args:
            content_type: ContentType
            config: RestorationConfig

        Returns:
            RestorationSummary
        """

    @retry_on_rate_limit
    def _call_api_update(
        self,
        content_type: ContentType,
        content_id: str,
        content_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Call SDK update_* method with retry logic.

        Args:
            content_type: ContentType
            content_id: Content ID
            content_dict: Content data

        Returns:
            API response as dict

        Raises:
            RateLimitError: If rate limited (retryable)
            ValidationError: If 422 validation error (not retryable)
            APIError: For other API errors
        """

    @retry_on_rate_limit
    def _call_api_create(
        self,
        content_type: ContentType,
        content_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Call SDK create_* method with retry logic.

        Args:
            content_type: ContentType
            content_dict: Content data

        Returns:
            API response as dict (includes new ID)

        Raises:
            RateLimitError: If rate limited (retryable)
            ValidationError: If 422 validation error (not retryable)
            APIError: For other API errors
        """

    def check_exists(
        self,
        content_id: str,
        content_type: ContentType
    ) -> bool:
        """Check if content exists via GET request.

        Args:
            content_id: Content ID
            content_type: ContentType

        Returns:
            True if exists (200 OK), False if not found (404)
        """
```

---

## 3. Dependency Graph

**Module**: `lookervault.restoration.dependency_graph`

### 3.1 DependencyGraph

Manages dependency ordering for content types.

```python
class DependencyGraph:
    """Manages content type dependency ordering."""

    def get_restoration_order(
        self,
        content_types: list[ContentType] | None = None
    ) -> list[ContentType]:
        """Get content types in dependency order.

        Args:
            content_types: Specific types to order (None = all types)

        Returns:
            Content types sorted by dependency order (dependencies first)

        Example:
            >>> graph = DependencyGraph()
            >>> graph.get_restoration_order([ContentType.DASHBOARD, ContentType.FOLDER])
            [ContentType.FOLDER, ContentType.DASHBOARD]
        """

    def validate_no_cycles(self) -> bool:
        """Validate dependency graph has no circular dependencies.

        Returns:
            True if acyclic, raises error if cycles detected

        Raises:
            DependencyError: If circular dependency detected
        """

    def get_dependencies(
        self,
        content_type: ContentType
    ) -> list[ContentType]:
        """Get direct dependencies for a content type.

        Args:
            content_type: ContentType to query

        Returns:
            List of content types that must be restored first

        Example:
            >>> graph.get_dependencies(ContentType.DASHBOARD)
            [ContentType.FOLDER, ContentType.LOOK, ContentType.USER]
        """
```

---

## 4. ID Mapper

**Module**: `lookervault.restoration.id_mapper`

### 4.1 IDMapper

Maps source IDs to destination IDs for cross-instance migration.

```python
class IDMapper:
    """Manages ID mappings for cross-instance migration."""

    def __init__(
        self,
        repository: ContentRepository,
        source_instance: str,
        destination_instance: str
    ):
        """Initialize ID mapper.

        Args:
            repository: SQLite repository for storing mappings
            source_instance: Source Looker instance URL
            destination_instance: Destination Looker instance URL
        """

    def save_mapping(
        self,
        content_type: ContentType,
        source_id: str,
        destination_id: str,
        session_id: str | None = None
    ) -> None:
        """Save source ID → destination ID mapping.

        Args:
            content_type: ContentType
            source_id: Original ID from source instance
            destination_id: New ID in destination instance
            session_id: Optional session ID for tracking
        """

    def get_destination_id(
        self,
        content_type: ContentType,
        source_id: str
    ) -> str | None:
        """Get destination ID for source ID.

        Args:
            content_type: ContentType
            source_id: Source ID to look up

        Returns:
            Destination ID if mapping exists, None otherwise
        """

    def translate_references(
        self,
        content_dict: dict[str, Any],
        content_type: ContentType
    ) -> dict[str, Any]:
        """Translate FK references from source IDs to destination IDs.

        Args:
            content_dict: Content data with potential FK references
            content_type: ContentType

        Returns:
            Content dict with translated IDs

        Example:
            Input:  {"folder_id": "123", "title": "Dashboard"}
            Output: {"folder_id": "456", "title": "Dashboard"}
            (if mapping exists: 123 → 456)
        """

    def clear_mappings(
        self,
        content_type: ContentType | None = None
    ) -> int:
        """Clear ID mappings.

        Args:
            content_type: Specific type to clear (None = all types)

        Returns:
            Number of mappings cleared
        """

    def is_same_instance(self) -> bool:
        """Check if source and destination are same instance.

        Returns:
            True if same instance (no ID mapping needed)
        """
```

---

## 5. Dead Letter Queue

**Module**: `lookervault.restoration.dead_letter_queue`

### 5.1 DeadLetterQueue

Manages failed restoration items.

```python
class DeadLetterQueue:
    """Dead letter queue for failed restoration items."""

    def __init__(self, repository: ContentRepository):
        """Initialize DLQ.

        Args:
            repository: SQLite repository for storing DLQ entries
        """

    def add(
        self,
        session_id: str,
        content_id: str,
        content_type: ContentType,
        content_data: bytes,
        error: Exception,
        retry_count: int = 0
    ) -> int:
        """Add failed item to DLQ.

        Args:
            session_id: Restoration session ID
            content_id: Content ID that failed
            content_type: ContentType
            content_data: Original content blob
            error: Exception that caused failure
            retry_count: Number of retries attempted

        Returns:
            DLQ entry ID
        """

    def get(self, dlq_id: int) -> DeadLetterItem | None:
        """Retrieve DLQ entry by ID.

        Args:
            dlq_id: DLQ entry ID

        Returns:
            DeadLetterItem if found, None otherwise
        """

    def list(
        self,
        session_id: str | None = None,
        content_type: ContentType | None = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[DeadLetterItem]:
        """List DLQ entries with filters.

        Args:
            session_id: Filter by session
            content_type: Filter by type
            limit: Max entries
            offset: Pagination offset

        Returns:
            List of DeadLetterItem
        """

    def retry(
        self,
        dlq_id: int,
        restorer: ContentRestorer
    ) -> RestorationResult:
        """Retry restoration for DLQ entry.

        Args:
            dlq_id: DLQ entry ID
            restorer: ContentRestorer instance

        Returns:
            RestorationResult

        Side effects:
            - If successful: removes entry from DLQ
            - If failed: updates retry_count
        """

    def clear(
        self,
        session_id: str | None = None,
        content_type: ContentType | None = None
    ) -> int:
        """Clear DLQ entries.

        Args:
            session_id: Clear entries for session
            content_type: Clear entries for type

        Returns:
            Number of entries cleared
        """
```

---

## 6. Parallel Orchestrator

**Module**: `lookervault.restoration.parallel_orchestrator`

### 6.1 ParallelRestorationOrchestrator

Orchestrates parallel restoration across multiple worker threads.

```python
class ParallelRestorationOrchestrator:
    """Orchestrates parallel restoration with worker threads."""

    def __init__(
        self,
        restorer: ContentRestorer,
        repository: ContentRepository,
        config: RestorationConfig,
        rate_limiter: AdaptiveRateLimiter,
        metrics: ThreadSafeMetrics,
        dlq: DeadLetterQueue,
        id_mapper: IDMapper | None = None
    ):
        """Initialize orchestrator.

        Args:
            restorer: Content restorer instance
            repository: SQLite repository
            config: Restoration configuration
            rate_limiter: Adaptive rate limiter
            metrics: Thread-safe metrics
            dlq: Dead letter queue
            id_mapper: Optional ID mapper
        """

    def restore(
        self,
        content_type: ContentType,
        session_id: str
    ) -> RestorationSummary:
        """Execute parallel restoration for content type.

        Flow:
          1. Query SQLite for all content IDs of type
          2. Distribute IDs to worker queue
          3. Worker threads:
             a. Claim ID from queue
             b. Fetch content from SQLite (thread-local connection)
             c. Call restorer.restore_single()
             d. Update metrics
             e. Save checkpoint every N items
             f. On error: retry or add to DLQ
          4. Wait for all workers to complete
          5. Return aggregated results

        Args:
            content_type: ContentType to restore
            session_id: Restoration session ID

        Returns:
            RestorationSummary with aggregated results
        """

    def restore_all(
        self,
        content_types: list[ContentType],
        session_id: str
    ) -> dict[ContentType, RestorationSummary]:
        """Restore multiple content types in dependency order.

        Args:
            content_types: Content types to restore
            session_id: Restoration session ID

        Returns:
            Dict of ContentType → RestorationSummary
        """

    def resume(
        self,
        session_id: str
    ) -> RestorationSummary:
        """Resume interrupted restoration session.

        Flow:
          1. Query for incomplete checkpoints
          2. Extract completed_ids from checkpoint_data
          3. Filter out completed_ids from restoration query
          4. Continue restoration from next item

        Args:
            session_id: Session ID to resume

        Returns:
            RestorationSummary
        """
```

---

## 7. Validation

**Module**: `lookervault.restoration.validation`

### 7.1 RestorationValidator

Validates content before restoration.

```python
class RestorationValidator:
    """Validates content before restoration."""

    def validate_pre_flight(
        self,
        db_path: Path,
        client: LookerClient
    ) -> list[str]:
        """Run pre-flight validation checks.

        Checks:
          - SQLite file exists and is readable
          - SQLite schema version compatible
          - Looker API connectivity
          - Looker API authentication
          - Destination instance version compatible

        Args:
            db_path: Path to SQLite database
            client: LookerClient instance

        Returns:
            List of validation error messages (empty if all pass)
        """

    def validate_content(
        self,
        content_dict: dict[str, Any],
        content_type: ContentType
    ) -> list[str]:
        """Validate individual content item.

        Checks:
          - Required fields present
          - Field types correct
          - FK references valid (if strict mode)

        Args:
            content_dict: Deserialized content
            content_type: ContentType

        Returns:
            List of validation error messages (empty if valid)
        """

    def validate_dependencies(
        self,
        content_dict: dict[str, Any],
        content_type: ContentType,
        client: LookerClient
    ) -> list[str]:
        """Validate dependencies exist in destination.

        Args:
            content_dict: Content data
            content_type: ContentType
            client: LookerClient for checking existence

        Returns:
            List of missing dependency errors (empty if all exist)
        """
```

---

## 8. Exceptions

**Module**: `lookervault.exceptions` (extend existing)

### 8.1 Restoration-Specific Exceptions

```python
class RestorationError(Exception):
    """Base exception for restoration errors."""

class DeserializationError(RestorationError):
    """Content deserialization failed."""

class ValidationError(RestorationError):
    """Content validation failed."""

class DependencyError(RestorationError):
    """Dependency not satisfied."""

class IDMappingError(RestorationError):
    """ID mapping operation failed."""
```

---

## 9. Progress Tracking

**Module**: `lookervault.extraction.progress` (reuse existing)

### 9.1 ProgressTracker (Existing)

Reuse existing ProgressTracker for real-time progress updates.

```python
# Usage example in ParallelOrchestrator
progress = ProgressTracker(
    total=total_items,
    description=f"Restoring {content_type.name.lower()}s"
)

with progress:
    for result in worker_results:
        progress.update(1)
        progress.set_postfix(
            success=metrics.success_count,
            errors=metrics.error_count,
            throughput=f"{metrics.throughput:.1f} items/sec"
        )
```

---

## Summary

The Python API provides:

1. **ContentDeserializer**: Binary blob → SDK models/dicts
2. **ContentRestorer**: Core restoration logic (update/create)
3. **DependencyGraph**: Dependency ordering
4. **IDMapper**: Cross-instance ID translation
5. **DeadLetterQueue**: Failed item management
6. **ParallelOrchestrator**: Parallel execution coordinator
7. **RestorationValidator**: Pre-flight and per-item validation
8. **Custom Exceptions**: Restoration-specific error types

All APIs follow existing patterns from the extraction module, ensuring consistency and code reuse.
