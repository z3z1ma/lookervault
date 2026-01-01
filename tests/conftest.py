"""Shared pytest fixtures and factory functions for LookerVault tests.

This module provides reusable test data and mock objects to reduce boilerplate
across tests and maintain consistency.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from lookervault.config.models import (
    Configuration,
    LookerConfig,
    ParallelConfig,
    RestorationConfig,
)
from lookervault.storage.models import (
    ContentItem,
    ContentType,
    DeadLetterItem,
    RestorationResult,
    RestorationSummary,
    RestorationTask,
)

#
# Mock Fixtures
#


@pytest.fixture
def mock_client():
    """Mock LookerClient.

    Returns:
        MagicMock: Mock Looker client instance.
    """
    return MagicMock()


@pytest.fixture
def mock_repository():
    """Mock ContentRepository.

    Returns:
        MagicMock: Mock content repository instance.
    """
    return MagicMock()


@pytest.fixture
def mock_serializer():
    """Mock content serializer.

    Returns:
        MagicMock: Mock serializer instance.
    """
    mock_serializer = Mock()
    mock_serializer.serialize = Mock(return_value=b"serialized_data")
    mock_serializer.deserialize = Mock(return_value={"id": "test"})
    return mock_serializer


@pytest.fixture
def mock_progress():
    """Mock progress tracker.

    Returns:
        MagicMock: Mock progress instance.
    """
    return MagicMock()


#
# Database Fixtures
#


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing.

    Returns:
        sqlite3.Connection: In-memory database connection.
    """
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create temporary database file path.

    Args:
        tmp_path: Pytest temporary path fixture.

    Returns:
        Path: Temporary file path for database.
    """
    return tmp_path / "test_lookervault.db"


#
# Configuration Fixtures
#


@pytest.fixture
def sample_looker_config() -> LookerConfig:
    """Create sample Looker configuration.

    Returns:
        LookerConfig: Sample Looker API configuration.
    """
    return LookerConfig(
        api_url="https://looker.example.com:19999",
        client_id="test_client_id",
        client_secret="test_client_secret",
        timeout=120,
        verify_ssl=True,
    )


@pytest.fixture
def sample_parallel_config() -> ParallelConfig:
    """Create sample parallel configuration.

    Returns:
        ParallelConfig: Sample parallel extraction configuration.
    """
    return ParallelConfig(
        workers=8,
        queue_size=800,
        batch_size=100,
        rate_limit_per_minute=100,
        rate_limit_per_second=10,
        adaptive_rate_limiting=True,
    )


@pytest.fixture
def sample_restoration_config() -> RestorationConfig:
    """Create sample restoration configuration.

    Returns:
        RestorationConfig: Sample restoration configuration.
    """
    return RestorationConfig(
        destination_instance="https://looker.example.com:19999",
        workers=8,
        rate_limit_per_minute=120,
        rate_limit_per_second=10,
        checkpoint_interval=100,
        max_retries=5,
        dry_run=False,
    )


@pytest.fixture
def sample_config(sample_looker_config) -> Configuration:
    """Create complete sample configuration.

    Args:
        sample_looker_config: Sample Looker configuration fixture.

    Returns:
        Configuration: Complete configuration object.
    """
    return Configuration(looker=sample_looker_config)


@pytest.fixture
def dry_run_config() -> RestorationConfig:
    """Create restoration config for dry run mode.

    Returns:
        RestorationConfig: Dry run configuration.
    """
    return RestorationConfig(
        destination_instance="https://looker.example.com:19999",
        dry_run=True,
        workers=4,
    )


#
# Sample Content Fixtures
#


@pytest.fixture
def sample_dashboard() -> dict:
    """Create sample dashboard content data.

    Returns:
        dict: Sample dashboard structure.
    """
    return {
        "id": "123",
        "title": "Test Dashboard",
        "folder_id": "456",
        "space_id": None,
        "user_id": 789,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-15T00:00:00Z",
        "dashboard_elements": [
            {"id": "el1", "title": "Element 1"},
            {"id": "el2", "title": "Element 2"},
        ],
    }


@pytest.fixture
def sample_look() -> dict:
    """Create sample look content data.

    Returns:
        dict: Sample look structure.
    """
    return {
        "id": "456",
        "title": "Test Look",
        "folder_id": "789",
        "user_id": 100,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-15T00:00:00Z",
        "query_id": 200,
        "lookml": "view: test_view { dimension: test_dim { sql: ${TABLE}.id ;; } }",
    }


@pytest.fixture
def sample_user() -> dict:
    """Create sample user content data.

    Returns:
        dict: Sample user structure.
    """
    return {
        "id": "100",
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-15T00:00:00Z",
    }


@pytest.fixture
def sample_folder() -> dict:
    """Create sample folder content data.

    Returns:
        dict: Sample folder structure.
    """
    return {
        "id": "200",
        "name": "Test Folder",
        "parent_id": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-15T00:00:00Z",
    }


@pytest.fixture
def sample_board() -> dict:
    """Create sample board content data.

    Returns:
        dict: Sample board structure.
    """
    return {
        "id": "300",
        "title": "Test Board",
        "folder_id": "200",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-15T00:00:00Z",
    }


@pytest.fixture
def sample_group() -> dict:
    """Create sample group content data.

    Returns:
        dict: Sample group structure.
    """
    return {
        "id": "400",
        "name": "Test Group",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-15T00:00:00Z",
    }


@pytest.fixture
def sample_role() -> dict:
    """Create sample role content data.

    Returns:
        dict: Sample role structure.
    """
    return {
        "id": "500",
        "name": "Test Role",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-15T00:00:00Z",
    }


#
# Content Item Factory Functions
#


def create_test_content_item(
    content_id: str = "test_id",
    content_type: ContentType = ContentType.DASHBOARD,
    name: str = "Test Content",
    content_data: bytes = b'{"test": "data"}',
    owner_id: int | None = None,
    owner_email: str | None = None,
    folder_id: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> ContentItem:
    """Create a test ContentItem with default values.

    Args:
        content_id: Content ID (default: "test_id")
        content_type: ContentType enum value
        name: Content name
        content_data: Serialized content bytes
        owner_id: Optional owner user ID
        owner_email: Optional owner email
        folder_id: Optional folder ID
        created_at: Creation timestamp (default: current time)
        updated_at: Last update timestamp (default: current time)

    Returns:
        ContentItem: Test content item instance.
    """
    now = datetime.now(UTC)
    return ContentItem(
        id=content_id,
        content_type=content_type.value,
        name=name,
        content_data=content_data,
        owner_id=owner_id,
        owner_email=owner_email,
        folder_id=folder_id,
        created_at=created_at or now,
        updated_at=updated_at or now,
        synced_at=now,
    )


def create_test_dashboard(
    dashboard_id: str = "test_dashboard",
    title: str = "Test Dashboard",
    folder_id: str | None = "test_folder",
    content_data: bytes | None = None,
) -> ContentItem:
    """Create test dashboard content item.

    Args:
        dashboard_id: Dashboard ID (default: "test_dashboard")
        title: Dashboard title
        folder_id: Parent folder ID (default: "test_folder")
        content_data: Optional serialized dashboard data

    Returns:
        ContentItem: Dashboard content item.
    """
    if content_data is None:
        content_data = (
            b'{"id": "' + dashboard_id.encode() + b'", "title": "' + title.encode() + b'"}'
        )

    return create_test_content_item(
        content_id=dashboard_id,
        content_type=ContentType.DASHBOARD,
        name=title,
        folder_id=folder_id,
        content_data=content_data,
    )


def create_test_look(
    look_id: str = "test_look",
    title: str = "Test Look",
    folder_id: str | None = "test_folder",
    query_id: int = 100,
    content_data: bytes | None = None,
) -> ContentItem:
    """Create test look content item.

    Args:
        look_id: Look ID (default: "test_look")
        title: Look title
        folder_id: Parent folder ID (default: "test_folder")
        query_id: Associated query ID
        content_data: Optional serialized look data

    Returns:
        ContentItem: Look content item.
    """
    if content_data is None:
        content_data = b'{"id": "' + look_id.encode() + b'", "title": "' + title.encode() + b'"}'

    return create_test_content_item(
        content_id=look_id,
        content_type=ContentType.LOOK,
        name=title,
        folder_id=folder_id,
        content_data=content_data,
    )


def create_test_user(
    user_id: str = "test_user",
    email: str = "test@example.com",
    first_name: str = "Test",
    last_name: str = "User",
    content_data: bytes | None = None,
) -> ContentItem:
    """Create test user content item.

    Args:
        user_id: User ID (default: "test_user")
        email: User email
        first_name: User first name
        last_name: User last name
        content_data: Optional serialized user data

    Returns:
        ContentItem: User content item.
    """
    if content_data is None:
        content_data = b'{"id": "' + user_id.encode() + b'", "email": "' + email.encode() + b'"}'

    return create_test_content_item(
        content_id=user_id,
        content_type=ContentType.USER,
        name=f"{first_name} {last_name}",
        content_data=content_data,
    )


def create_test_folder(
    folder_id: str = "test_folder",
    name: str = "Test Folder",
    parent_id: str | None = None,
    content_data: bytes | None = None,
) -> ContentItem:
    """Create test folder content item.

    Args:
        folder_id: Folder ID (default: "test_folder")
        name: Folder name
        parent_id: Parent folder ID (None for root folders)
        content_data: Optional serialized folder data

    Returns:
        ContentItem: Folder content item.
    """
    if content_data is None:
        content_data = b'{"id": "' + folder_id.encode() + b'", "name": "' + name.encode() + b'"}'

    return create_test_content_item(
        content_id=folder_id,
        content_type=ContentType.FOLDER,
        name=name,
        content_data=content_data,
    )


def create_test_board(
    board_id: str = "test_board",
    title: str = "Test Board",
    folder_id: str | None = "test_folder",
    content_data: bytes | None = None,
) -> ContentItem:
    """Create test board content item.

    Args:
        board_id: Board ID (default: "test_board")
        title: Board title
        folder_id: Parent folder ID
        content_data: Optional serialized board data

    Returns:
        ContentItem: Board content item.
    """
    if content_data is None:
        content_data = b'{"id": "' + board_id.encode() + b'", "title": "' + title.encode() + b'"}'

    return create_test_content_item(
        content_id=board_id,
        content_type=ContentType.BOARD,
        name=title,
        folder_id=folder_id,
        content_data=content_data,
    )


def create_test_group(
    group_id: str = "test_group",
    name: str = "Test Group",
    content_data: bytes | None = None,
) -> ContentItem:
    """Create test group content item.

    Args:
        group_id: Group ID (default: "test_group")
        name: Group name
        content_data: Optional serialized group data

    Returns:
        ContentItem: Group content item.
    """
    if content_data is None:
        content_data = b'{"id": "' + group_id.encode() + b'", "name": "' + name.encode() + b'"}'

    return create_test_content_item(
        content_id=group_id,
        content_type=ContentType.GROUP,
        name=name,
        content_data=content_data,
    )


def create_test_role(
    role_id: str = "test_role",
    name: str = "Test Role",
    content_data: bytes | None = None,
) -> ContentItem:
    """Create test role content item.

    Args:
        role_id: Role ID (default: "test_role")
        name: Role name
        content_data: Optional serialized role data

    Returns:
        ContentItem: Role content item.
    """
    if content_data is None:
        content_data = b'{"id": "' + role_id.encode() + b'", "name": "' + name.encode() + b'"}'

    return create_test_content_item(
        content_id=role_id,
        content_type=ContentType.ROLE,
        name=name,
        content_data=content_data,
    )


#
# Restoration Result Factory Functions
#


def create_test_restoration_result(
    content_id: str = "test_id",
    content_type: ContentType = ContentType.DASHBOARD,
    status: str = "created",
    destination_id: str | None = None,
    error_message: str | None = None,
    retry_count: int = 0,
    duration_ms: float = 100.0,
    metadata: dict[str, Any] | None = None,
) -> RestorationResult:
    """Create a test RestorationResult with default values.

    Args:
        content_id: Original content ID from backup
        content_type: ContentType enum value
        status: Result status ("created", "updated", "failed", "skipped")
        destination_id: Looker ID in destination instance
        error_message: Error message if status is "failed"
        retry_count: Number of retry attempts
        duration_ms: Operation duration in milliseconds
        metadata: Optional metadata dict

    Returns:
        RestorationResult: Test restoration result instance.
    """
    return RestorationResult(
        content_id=content_id,
        content_type=content_type.value,
        status=status,
        destination_id=destination_id or f"dest_{content_id}",
        error_message=error_message,
        retry_count=retry_count,
        duration_ms=duration_ms,
        metadata=metadata,
    )


def create_test_success_result(
    content_id: str = "test_id",
    content_type: ContentType = ContentType.DASHBOARD,
    status: str = "created",
) -> RestorationResult:
    """Create test successful restoration result.

    Args:
        content_id: Content ID
        content_type: ContentType enum value
        status: "created" or "updated"

    Returns:
        RestorationResult: Successful result.
    """
    return create_test_restoration_result(
        content_id=content_id,
        content_type=content_type,
        status=status,
        duration_ms=100.0,
    )


def create_test_failure_result(
    content_id: str = "test_id",
    content_type: ContentType = ContentType.DASHBOARD,
    error_message: str = "Test error",
) -> RestorationResult:
    """Create test failed restoration result.

    Args:
        content_id: Content ID
        content_type: ContentType enum value
        error_message: Error message

    Returns:
        RestorationResult: Failed result.
    """
    return create_test_restoration_result(
        content_id=content_id,
        content_type=content_type,
        status="failed",
        error_message=error_message,
        duration_ms=50.0,
    )


#
# Dead Letter Item Factory Functions
#


def create_test_dlq_item(
    session_id: str = "test_session",
    content_id: str = "test_id",
    content_type: ContentType = ContentType.DASHBOARD,
    error_message: str = "Test error",
    error_type: str = "APIError",
    retry_count: int = 0,
    content_data: bytes = b"{}",
) -> DeadLetterItem:
    """Create test DeadLetterItem with default values.

    Args:
        session_id: Restoration session ID
        content_id: Content ID that failed
        content_type: ContentType enum value
        error_message: Error message
        error_type: Categorized error type
        retry_count: Number of retry attempts
        content_data: Serialized content bytes

    Returns:
        DeadLetterItem: Test DLQ item instance.
    """
    return DeadLetterItem(
        session_id=session_id,
        content_id=content_id,
        content_type=content_type.value,
        content_data=content_data,
        error_message=error_message,
        error_type=error_type,
        retry_count=retry_count,
        failed_at=datetime.now(UTC),
    )


#
# Restoration Task Factory Functions
#


def create_test_restoration_task(
    content_id: str = "test_id",
    content_type: ContentType = ContentType.DASHBOARD,
    content_data: bytes | None = None,
    status: str = "pending",
    priority: int = 0,
    retry_count: int = 0,
    error_message: str | None = None,
) -> RestorationTask:
    """Create test RestorationTask with default values.

    Args:
        content_id: Content ID
        content_type: ContentType enum value
        content_data: Optional serialized content bytes
        status: Task status ("pending", "in_progress", "completed", "failed")
        priority: Task priority (higher = more important)
        retry_count: Number of retry attempts
        error_message: Error message if status is "failed"

    Returns:
        RestorationTask: Test restoration task instance.
    """
    return RestorationTask(
        content_id=content_id,
        content_type=content_type.value,
        content_data=content_data,
        status=status,
        priority=priority,
        retry_count=retry_count,
        error_message=error_message,
    )


#
# Content Type Lists
#


@pytest.fixture
def all_content_types() -> list[ContentType]:
    """List of all ContentType enum values.

    Returns:
        list[ContentType]: All available content types.
    """
    return [
        ContentType.DASHBOARD,
        ContentType.LOOK,
        ContentType.LOOKML_MODEL,
        ContentType.EXPLORE,
        ContentType.FOLDER,
        ContentType.BOARD,
        ContentType.USER,
        ContentType.GROUP,
        ContentType.ROLE,
        ContentType.PERMISSION_SET,
        ContentType.MODEL_SET,
        ContentType.SCHEDULED_PLAN,
    ]


@pytest.fixture
def restorable_content_types() -> list[ContentType]:
    """List of restorable ContentType enum values.

    Excludes EXPLORE which is read-only via API.

    Returns:
        list[ContentType]: Restorable content types.
    """
    return [
        ContentType.USER,
        ContentType.GROUP,
        ContentType.PERMISSION_SET,
        ContentType.MODEL_SET,
        ContentType.ROLE,
        ContentType.FOLDER,
        ContentType.LOOKML_MODEL,
        ContentType.LOOK,
        ContentType.DASHBOARD,
        ContentType.BOARD,
        ContentType.SCHEDULED_PLAN,
    ]


#
# Bulk Content Generation
#


def create_test_content_batch(
    count: int,
    content_type: ContentType = ContentType.DASHBOARD,
    start_id: int = 1,
) -> list[dict]:
    """Create batch of test content items for API responses.

    Args:
        count: Number of items to create
        content_type: ContentType enum value
        start_id: Starting ID number

    Returns:
        list[dict]: List of content dictionaries.
    """
    items = []
    for i in range(count):
        content_id = str(start_id + i)
        if content_type == ContentType.DASHBOARD:
            items.append(
                {
                    "id": content_id,
                    "title": f"Dashboard {content_id}",
                    "folder_id": "1",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-15T00:00:00Z",
                }
            )
        elif content_type == ContentType.LOOK:
            items.append(
                {
                    "id": content_id,
                    "title": f"Look {content_id}",
                    "folder_id": "1",
                    "query_id": 100 + i,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-15T00:00:00Z",
                }
            )
        elif content_type == ContentType.USER:
            items.append(
                {
                    "id": content_id,
                    "first_name": f"User{content_id}",
                    "last_name": "Test",
                    "email": f"user{content_id}@example.com",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-15T00:00:00Z",
                }
            )
        else:
            items.append(
                {
                    "id": content_id,
                    "title": f"{content_type.name.title()} {content_id}",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-15T00:00:00Z",
                }
            )
    return items


def create_test_restoration_summary(
    session_id: str = "test_session",
    total_items: int = 100,
    success_count: int = 95,
    created_count: int = 80,
    updated_count: int = 15,
    error_count: int = 5,
    skipped_count: int = 0,
    duration_seconds: float = 10.0,
    content_type_breakdown: dict[int, int] | None = None,
    error_breakdown: dict[str, int] | None = None,
) -> RestorationSummary:
    """Create test RestorationSummary with default values.

    Args:
        session_id: Restoration session ID
        total_items: Total items attempted
        success_count: Successfully restored items
        created_count: Items created
        updated_count: Items updated
        error_count: Failed items
        skipped_count: Skipped items
        duration_seconds: Total duration
        content_type_breakdown: Optional content type breakdown
        error_breakdown: Optional error type breakdown

    Returns:
        RestorationSummary: Test restoration summary instance.
    """
    if content_type_breakdown is None:
        content_type_breakdown = {ContentType.DASHBOARD.value: 100}

    if error_breakdown is None:
        error_breakdown = {"ValidationError": 3, "NotFoundError": 2}

    return RestorationSummary(
        session_id=session_id,
        total_items=total_items,
        success_count=success_count,
        created_count=created_count,
        updated_count=updated_count,
        error_count=error_count,
        skipped_count=skipped_count,
        duration_seconds=duration_seconds,
        average_throughput=total_items / duration_seconds if duration_seconds > 0 else 0.0,
        content_type_breakdown=content_type_breakdown,
        error_breakdown=error_breakdown,
    )
