# Internal API Contracts: Looker Content Extraction

**Feature**: 002-looker-content-extraction
**Date**: 2025-12-13
**Type**: Internal Python Interfaces

## Overview

This document defines the internal API contracts between modules in the extraction system. All interfaces use Python protocols for type safety without tight coupling.

---

## Module Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     CLI Layer                            │
│  cli/commands/extract.py, cli/commands/verify.py        │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│                Extraction Orchestrator                   │
│         extraction/orchestrator.py                       │
│  - Coordinates extraction workflow                       │
│  - Manages content type iteration                        │
│  - Handles session lifecycle                             │
└──┬────────┬────────┬────────┬────────────────────────┬──┘
   │        │        │        │                        │
   ▼        ▼        ▼        ▼                        ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌────────┐     ┌──────────────┐
│Looker│ │Batch │ │Retry │ │Progress│     │   Storage    │
│Client│ │Proc  │ │Logic │ │Tracker │     │  Repository  │
└──────┘ └──────┘ └──────┘ └────────┘     └──────────────┘
                                                   │
                                                   ▼
                                          ┌───────────────┐
                                          │  Serializer   │
                                          └───────────────┘
```

---

## 1. Storage Layer Contracts

### 1.1 ContentRepository Protocol

**Purpose**: Abstract interface for content storage operations.

**Module**: `lookervault.storage.repository`

```python
from typing import Protocol, Sequence, Optional
from datetime import datetime
from lookervault.storage.models import ContentItem, Checkpoint, ExtractionSession

class ContentRepository(Protocol):
    """Protocol for content storage operations."""

    def save_content(self, item: ContentItem) -> None:
        """
        Save or update a content item.

        Args:
            item: ContentItem to persist

        Raises:
            StorageError: If save fails
        """
        ...

    def get_content(self, content_id: str) -> Optional[ContentItem]:
        """
        Retrieve content by ID.

        Args:
            content_id: Unique content identifier

        Returns:
            ContentItem if found, None otherwise
        """
        ...

    def list_content(
        self,
        content_type: int,
        include_deleted: bool = False,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Sequence[ContentItem]:
        """
        List content items by type.

        Args:
            content_type: ContentType enum value
            include_deleted: Include soft-deleted items
            limit: Maximum items to return
            offset: Pagination offset

        Returns:
            Sequence of ContentItem objects
        """
        ...

    def delete_content(self, content_id: str, soft: bool = True) -> None:
        """
        Delete content item.

        Args:
            content_id: Unique content identifier
            soft: If True, soft delete. If False, hard delete.

        Raises:
            NotFoundError: If content doesn't exist
        """
        ...

    def save_checkpoint(self, checkpoint: Checkpoint) -> int:
        """
        Save extraction checkpoint.

        Args:
            checkpoint: Checkpoint object

        Returns:
            Checkpoint ID

        Raises:
            StorageError: If save fails
        """
        ...

    def get_latest_checkpoint(
        self, content_type: int, session_id: Optional[str] = None
    ) -> Optional[Checkpoint]:
        """
        Get most recent incomplete checkpoint for content type.

        Args:
            content_type: ContentType enum value
            session_id: Optional session filter

        Returns:
            Latest Checkpoint or None
        """
        ...

    def create_session(self, session: ExtractionSession) -> None:
        """Create new extraction session."""
        ...

    def update_session(self, session: ExtractionSession) -> None:
        """Update existing extraction session."""
        ...
```

**Implementation Requirements**:
- Thread-safe operations
- Atomic transactions for multi-item operations
- Proper error handling with custom exceptions
- Connection pooling if needed

---

### 1.2 Serializer Protocol

**Purpose**: Abstract interface for content serialization.

**Module**: `lookervault.storage.serializer`

```python
from typing import Protocol, Any

class ContentSerializer(Protocol):
    """Protocol for serializing/deserializing Looker content."""

    def serialize(self, data: dict[str, Any] | list[Any]) -> bytes:
        """
        Serialize Python object to bytes.

        Args:
            data: Python dict/list from Looker API

        Returns:
            Serialized bytes for BLOB storage

        Raises:
            SerializationError: If serialization fails
        """
        ...

    def deserialize(self, blob: bytes) -> dict[str, Any] | list[Any]:
        """
        Deserialize bytes to Python object.

        Args:
            blob: Binary data from storage

        Returns:
            Original Python dict/list

        Raises:
            DeserializationError: If deserialization fails
        """
        ...

    def validate(self, blob: bytes) -> bool:
        """
        Validate that blob can be deserialized.

        Args:
            blob: Binary data to validate

        Returns:
            True if valid, False otherwise
        """
        ...
```

**Implementation**: `MsgpackSerializer` using msgspec library.

---

## 2. Extraction Layer Contracts

### 2.1 ContentExtractor Protocol

**Purpose**: Abstract interface for extracting content from Looker.

**Module**: `lookervault.looker.extractor`

```python
from typing import Protocol, Sequence, Iterator, Any
from lookervault.storage.models import ContentType

class ContentExtractor(Protocol):
    """Protocol for extracting content from Looker API."""

    def extract_all(
        self,
        content_type: ContentType,
        fields: Optional[str] = None,
        batch_size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """
        Extract all content of given type.

        Args:
            content_type: Type of content to extract
            fields: Comma-separated field list (Looker API format)
            batch_size: Items per batch for paginated endpoints

        Yields:
            Individual content items as dicts

        Raises:
            ExtractionError: If extraction fails
            RateLimitError: If rate limited (will be retried)
        """
        ...

    def extract_one(self, content_type: ContentType, content_id: str) -> dict[str, Any]:
        """
        Extract single content item.

        Args:
            content_type: Type of content
            content_id: Looker ID

        Returns:
            Content item as dict

        Raises:
            NotFoundError: If content doesn't exist
            ExtractionError: If extraction fails
        """
        ...

    def test_connection(self) -> bool:
        """
        Test Looker API connection.

        Returns:
            True if connected, False otherwise
        """
        ...
```

**Implementation Requirements**:
- Automatic pagination for endpoints that need it
- Retry logic via decorator (tenacity)
- Rate limit handling
- Proper Looker SDK error translation

---

### 2.2 BatchProcessor Protocol

**Purpose**: Memory-efficient batch processing.

**Module**: `lookervault.extraction.batch_processor`

```python
from typing import Protocol, Iterator, Callable, TypeVar, Generic

T = TypeVar("T")
R = TypeVar("R")

class BatchProcessor(Protocol, Generic[T, R]):
    """Protocol for processing items in memory-safe batches."""

    def process_batches(
        self,
        items: Iterator[T],
        processor: Callable[[T], R],
        batch_size: int = 100,
    ) -> Iterator[R]:
        """
        Process items in batches to manage memory.

        Args:
            items: Iterator of input items
            processor: Function to process each item
            batch_size: Items per batch

        Yields:
            Processed results

        Raises:
            ProcessingError: If batch processing fails
        """
        ...

    def get_memory_usage(self) -> tuple[int, int]:
        """
        Get current memory usage.

        Returns:
            Tuple of (current_bytes, peak_bytes)
        """
        ...
```

---

### 2.3 ProgressTracker Protocol

**Purpose**: Track and display extraction progress.

**Module**: `lookervault.extraction.progress`

```python
from typing import Protocol
from enum import Enum

class OutputMode(Enum):
    HUMAN = "table"  # Rich progress bars
    MACHINE = "json"  # Structured JSON output

class ProgressTracker(Protocol):
    """Protocol for tracking extraction progress."""

    def start_task(
        self, task_id: str, description: str, total: Optional[int] = None
    ) -> None:
        """
        Start tracking a new task.

        Args:
            task_id: Unique task identifier
            description: Human-readable description
            total: Total items (None if unknown)
        """
        ...

    def update_task(self, task_id: str, advance: int = 1) -> None:
        """
        Update task progress.

        Args:
            task_id: Task identifier
            advance: Items to advance by
        """
        ...

    def complete_task(self, task_id: str) -> None:
        """Mark task as complete."""
        ...

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark task as failed."""
        ...

    def emit_event(self, event: str, **data: Any) -> None:
        """
        Emit structured event (for JSON mode).

        Args:
            event: Event type
            **data: Event payload
        """
        ...
```

**Implementations**:
- `RichProgressTracker`: Uses Rich library for terminal output
- `JsonProgressTracker`: Emits structured JSON events

---

## 3. Orchestration Contracts

### 3.1 ExtractionOrchestrator

**Purpose**: Coordinate entire extraction workflow.

**Module**: `lookervault.extraction.orchestrator`

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ExtractionConfig:
    """Configuration for extraction operation."""
    content_types: list[int]  # ContentType enum values
    batch_size: int = 100
    fields: Optional[str] = None
    resume: bool = True
    verify: bool = False
    output_mode: str = "table"

@dataclass
class ExtractionResult:
    """Result of extraction operation."""
    session_id: str
    total_items: int
    items_by_type: dict[int, int]
    errors: int
    duration_seconds: float
    checkpoints_created: int

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
        """Initialize orchestrator with dependencies."""
        ...

    def extract(self) -> ExtractionResult:
        """
        Execute extraction workflow.

        Returns:
            ExtractionResult with summary

        Raises:
            OrchestrationError: If extraction fails
        """
        ...

    def resume_extraction(self, session_id: str) -> ExtractionResult:
        """
        Resume interrupted extraction.

        Args:
            session_id: Previous session to resume

        Returns:
            ExtractionResult with summary
        """
        ...
```

**Workflow**:
1. Create extraction session
2. For each content type:
   - Check for incomplete checkpoint
   - Extract items (via ContentExtractor)
   - Process in batches (via BatchProcessor)
   - Serialize (via Serializer)
   - Save (via Repository)
   - Create checkpoint
   - Update progress
3. Complete session
4. Return results

---

## 4. Data Models

### 4.1 ContentItem

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class ContentItem:
    """Represents a single content item."""
    id: str
    content_type: int
    name: str
    created_at: datetime
    updated_at: datetime
    content_data: bytes  # Serialized binary
    owner_id: Optional[int] = None
    owner_email: Optional[str] = None
    synced_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    content_size: Optional[int] = None

    def __post_init__(self):
        """Auto-calculate fields if not provided."""
        if self.synced_at is None:
            self.synced_at = datetime.now()
        if self.content_size is None:
            self.content_size = len(self.content_data)
```

### 4.2 Checkpoint

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class Checkpoint:
    """Represents an extraction checkpoint."""
    content_type: int
    checkpoint_data: dict  # Will be serialized to JSON
    started_at: datetime = field(default_factory=datetime.now)
    id: Optional[int] = None
    session_id: Optional[str] = None
    completed_at: Optional[datetime] = None
    item_count: int = 0
    error_message: Optional[str] = None
```

### 4.3 ExtractionSession

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4

@dataclass
class ExtractionSession:
    """Represents an extraction session."""
    id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=datetime.now)
    status: str = "pending"
    total_items: int = 0
    error_count: int = 0
    completed_at: Optional[datetime] = None
    config: Optional[dict] = None
    metadata: Optional[dict] = None
```

---

## 5. Error Hierarchy

```python
class LookerVaultError(Exception):
    """Base exception for LookerVault."""
    pass

class StorageError(LookerVaultError):
    """Storage layer error."""
    pass

class NotFoundError(StorageError):
    """Content not found."""
    pass

class SerializationError(LookerVaultError):
    """Serialization/deserialization error."""
    pass

class ExtractionError(LookerVaultError):
    """Content extraction error."""
    pass

class RateLimitError(ExtractionError):
    """API rate limit exceeded (retryable)."""
    def __init__(self, retry_after: Optional[int] = None):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after}s")

class OrchestrationError(LookerVaultError):
    """Orchestration workflow error."""
    pass

class ProcessingError(LookerVaultError):
    """Batch processing error."""
    pass
```

---

## 6. Dependency Injection

**Pattern**: Constructor injection with protocols

**Example**:
```python
# Application composition root
def create_extraction_orchestrator(
    config: ExtractionConfig,
    looker_client: LookerClient,
) -> ExtractionOrchestrator:
    """Factory for creating orchestrator with all dependencies."""

    # Create dependencies
    serializer = MsgpackSerializer()
    repository = SQLiteContentRepository(db_path="looker.db")
    extractor = LookerContentExtractor(client=looker_client)

    progress = (
        RichProgressTracker()
        if config.output_mode == "table"
        else JsonProgressTracker()
    )

    # Wire up orchestrator
    return ExtractionOrchestrator(
        extractor=extractor,
        repository=repository,
        serializer=serializer,
        progress=progress,
        config=config,
    )
```

---

## 7. Testing Contracts

### Test Doubles

**Mock Repository:**
```python
class InMemoryRepository(ContentRepository):
    """In-memory repository for testing."""
    def __init__(self):
        self.items: dict[str, ContentItem] = {}
        self.checkpoints: list[Checkpoint] = []
        self.sessions: dict[str, ExtractionSession] = {}

    def save_content(self, item: ContentItem) -> None:
        self.items[item.id] = item

    # ... implement other methods
```

**Mock Extractor:**
```python
class MockContentExtractor(ContentExtractor):
    """Mock extractor for testing."""
    def __init__(self, mock_data: list[dict]):
        self.mock_data = mock_data

    def extract_all(self, content_type, fields=None, batch_size=100):
        return iter(self.mock_data)

    # ... implement other methods
```

---

## 8. API Contract Guarantees

### Repository Contracts

1. **Atomicity**: Multi-item operations are atomic (all succeed or all rollback)
2. **Idempotency**: Repeated saves with same ID update existing record
3. **Isolation**: Concurrent operations don't corrupt data
4. **Error Handling**: All errors raised as StorageError subclasses

### Extractor Contracts

1. **Pagination**: Transparently handles pagination (caller gets iterator)
2. **Retry**: Automatic retry on transient failures (via tenacity)
3. **Rate Limits**: Raises RateLimitError for 429 responses
4. **Streaming**: Returns iterator (not list) to manage memory

### Progress Contracts

1. **Mode Switching**: Supports both human/JSON modes
2. **Thread Safety**: Can be called from multiple threads
3. **Non-Blocking**: Progress updates don't block extraction
4. **Structured Events**: JSON mode emits parseable events

---

## Contract Validation

### Runtime Validation

Use `typing.runtime_checkable`:
```python
from typing import runtime_checkable, Protocol

@runtime_checkable
class ContentRepository(Protocol):
    ...

# Validate at runtime
assert isinstance(repo, ContentRepository), "Invalid repository implementation"
```

### Type Checking

All contracts are type-checkable with mypy/ty:
```bash
ty check src/
```

### Contract Tests

Test that implementations satisfy protocols:
```python
def test_sqlite_repository_satisfies_protocol():
    """Verify SQLiteRepository implements ContentRepository."""
    repo = SQLiteContentRepository(":memory:")
    assert isinstance(repo, ContentRepository)
```

---

## Summary

| Contract | Type | Purpose | Implementations |
|----------|------|---------|----------------|
| ContentRepository | Protocol | Storage operations | SQLiteContentRepository |
| ContentSerializer | Protocol | Serialization | MsgpackSerializer |
| ContentExtractor | Protocol | API extraction | LookerContentExtractor |
| BatchProcessor | Protocol | Batch processing | MemoryAwareBatchProcessor |
| ProgressTracker | Protocol | Progress tracking | RichProgressTracker, JsonProgressTracker |
| ExtractionOrchestrator | Class | Workflow coordination | ExtractionOrchestrator |

**Total Contracts**: 6 protocols
**Error Types**: 8 custom exceptions
**Data Models**: 3 dataclasses

All contracts use Python typing for static analysis and runtime validation.
