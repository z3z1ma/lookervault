"""Edge case tests for extraction module.

Tests cover:
- Empty result sets from API
- Network timeouts during extraction
- Malformed API responses
- Rate limiting scenarios
- Concurrent database writes
- Item processing failures mid-batch
"""

from unittest.mock import Mock

import pytest

from lookervault.config.models import ParallelConfig
from lookervault.exceptions import ProcessingError
from lookervault.extraction.batch_processor import MemoryAwareBatchProcessor
from lookervault.extraction.offset_coordinator import OffsetCoordinator
from lookervault.extraction.orchestrator import ExtractionConfig
from lookervault.extraction.parallel_orchestrator import ParallelOrchestrator
from lookervault.storage.models import ContentType


def create_orchestrator_with_mocks():
    """Create orchestrator with mocked dependencies."""
    mock_extractor = Mock()
    mock_repository = Mock()
    mock_repository.save_content = Mock()
    mock_repository.close_thread_connection = Mock()
    mock_serializer = Mock()
    mock_serializer.serialize = Mock(return_value=b"serialized_data")
    mock_progress = Mock()

    extraction_config = ExtractionConfig(
        content_types=[ContentType.DASHBOARD.value],
        batch_size=100,
        fields="id,title",
        incremental=False,
        resume=False,
    )

    parallel_config = ParallelConfig(
        workers=4,
        queue_size=400,
        batch_size=100,
        rate_limit_per_minute=100,
        rate_limit_per_second=10,
        adaptive_rate_limiting=False,
    )

    orchestrator = ParallelOrchestrator(
        extractor=mock_extractor,
        repository=mock_repository,
        serializer=mock_serializer,
        progress=mock_progress,
        config=extraction_config,
        parallel_config=parallel_config,
    )

    return orchestrator, mock_extractor, mock_repository, mock_serializer


class TestEmptyResults:
    """Tests for handling empty result sets from API."""

    def test_parallel_worker_empty_first_fetch(self):
        """Test worker handles empty result on first fetch."""
        orchestrator, mock_extractor, mock_repository, _ = create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Return empty immediately
        mock_extractor.extract_range.return_value = []

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        assert items_processed == 0
        assert mock_extractor.extract_range.call_count == 1
        assert mock_repository.save_content.call_count == 0
        assert coordinator.get_workers_done() == 1

    def test_parallel_worker_empty_after_multiple_batches(self):
        """Test worker handles empty result after successful batches."""
        orchestrator, mock_extractor, mock_repository, _ = create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Return data then empty
        mock_extractor.extract_range.side_effect = [
            [{"id": str(i), "title": f"Dashboard {i}"} for i in range(100)],
            [],  # Empty result
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        assert items_processed == 100
        assert mock_extractor.extract_range.call_count == 2

    def test_batch_processor_with_empty_iterator(self):
        """Test batch processor handles empty iterator gracefully."""
        processor = MemoryAwareBatchProcessor(enable_monitoring=False)

        def identity(x):
            return x

        results = list(processor.process_batches(iter([]), identity, batch_size=10))
        assert results == []

    def test_batch_processor_single_item(self):
        """Test batch processor handles single item."""
        processor = MemoryAwareBatchProcessor(enable_monitoring=False)

        def double(x):
            return x * 2

        results = list(processor.process_batches(iter([5]), double, batch_size=10))
        assert results == [10]


class TestMalformedResponses:
    """Tests for handling malformed API responses."""

    def test_missing_id_field(self):
        """Test handling of items missing ID field."""
        orchestrator, mock_extractor, mock_repository, mock_serializer = (
            create_orchestrator_with_mocks()
        )
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Item missing 'id' field
        mock_extractor.extract_range.side_effect = [
            [
                {"title": "No ID Dashboard"},  # Missing id
                {"id": "123", "title": "Good Dashboard"},
            ],
            [],
        ]

        mock_repository.save_content.side_effect = [None, None]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should process both items (one gets "unknown" id)
        assert items_processed == 2
        assert mock_repository.save_content.call_count == 2

    def test_missing_title_field(self):
        """Test handling of items missing title field."""
        orchestrator, mock_extractor, mock_repository, _ = create_orchestrator_with_mocks()
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Item missing 'title' field
        mock_extractor.extract_range.side_effect = [
            [{"id": "123"}],  # Missing title
            [],
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should process item (title defaults to "Untitled {id}")
        assert items_processed == 1
        # Verify the saved item has id as name
        saved_item = mock_repository.save_content.call_args[0][0]
        assert saved_item.name == "Untitled 123"

    def test_invalid_owner_id_format(self):
        """Test handling of invalid owner_id format."""
        orchestrator, mock_extractor, mock_repository, mock_serializer = (
            create_orchestrator_with_mocks()
        )
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # owner_id as non-convertible string
        mock_extractor.extract_range.side_effect = [
            [{"id": "123", "title": "Test", "user_id": "not_a_number"}],
            [],
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should process item with owner_id set to None
        assert items_processed == 1
        saved_item = mock_repository.save_content.call_args[0][0]
        assert saved_item.owner_id is None

    def test_missing_timestamps(self):
        """Test handling of items missing timestamp fields."""
        orchestrator, mock_extractor, mock_repository, _ = create_orchestrator_with_mocks()
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Item missing timestamps - parse_timestamp returns default (now)
        mock_extractor.extract_range.side_effect = [
            [{"id": "123", "title": "No Timestamps"}],  # Missing timestamps
            [],
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should process item with default timestamps
        assert items_processed == 1
        saved_item = mock_repository.save_content.call_args[0][0]
        assert saved_item.created_at is not None
        assert saved_item.updated_at is not None

    def test_lookml_model_with_name_identifier(self):
        """Test LookML model uses 'name' as identifier."""
        orchestrator, mock_extractor, mock_repository, mock_serializer = (
            create_orchestrator_with_mocks()
        )
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # LookML model uses 'name' not 'id'
        mock_extractor.extract_range.side_effect = [
            [{"name": "my_model", "label": "My Model"}],  # No 'id' field
            [],
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.LOOKML_MODEL.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        assert items_processed == 1
        saved_item = mock_repository.save_content.call_args[0][0]
        # LookML models use 'name' as id, not prefixed
        assert saved_item.id == "my_model"


class TestNetworkTimeouts:
    """Tests for handling network timeouts during extraction."""

    def test_api_timeout_continues_to_next_range(self):
        """Test worker continues after timeout."""
        orchestrator, mock_extractor, mock_repository, _ = create_orchestrator_with_mocks()
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # First call times out, second succeeds
        mock_extractor.extract_range.side_effect = [
            TimeoutError("API timeout"),
            [{"id": "1"}],
            [],
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Worker logs error and continues to next iteration
        assert items_processed == 1
        assert mock_extractor.extract_range.call_count == 2

    def test_connection_error_retries(self):
        """Test worker handles connection errors."""
        orchestrator, mock_extractor, mock_repository, _ = create_orchestrator_with_mocks()
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Connection error then success
        mock_extractor.extract_range.side_effect = [
            ConnectionError("Connection refused"),
            [{"id": "1"}],
            [],
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Worker logs error and continues to next iteration
        assert items_processed == 1

    def test_consecutive_timeouts(self):
        """Test worker handles multiple consecutive timeouts."""
        orchestrator, mock_extractor, mock_repository, _ = create_orchestrator_with_mocks()
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Multiple timeouts then success
        mock_extractor.extract_range.side_effect = [
            TimeoutError("Timeout 1"),
            TimeoutError("Timeout 2"),
            TimeoutError("Timeout 3"),
            [{"id": "1"}],
            [],
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Worker logs errors and continues until success
        assert items_processed == 1
        assert mock_extractor.extract_range.call_count == 4


class TestSerializationFailures:
    """Tests for handling serialization failures."""

    def test_serialize_failure_skips_item(self):
        """Test item skipped when serialization fails."""
        orchestrator, mock_extractor, mock_repository, mock_serializer = (
            create_orchestrator_with_mocks()
        )
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Serialization fails for second item
        mock_serializer.serialize.side_effect = [
            b"data1",
            Exception("Serialization failed"),
            b"data3",
        ]

        mock_extractor.extract_range.side_effect = [
            [
                {"id": "1", "title": "Item 1"},
                {"id": "2", "title": "Item 2"},
                {"id": "3", "title": "Item 3"},
            ],
            [],
        ]

        mock_repository.save_content.side_effect = [None, Exception("DB error"), None]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should process 1 item successfully (1 serialization failure + 1 DB error)
        assert items_processed == 1

    def test_serialize_with_none_values(self):
        """Test serialization handles None values correctly."""
        from lookervault.storage.serializer import MsgpackSerializer

        serializer = MsgpackSerializer()

        # Should handle None values
        data: dict[str, str | None] = {"id": "123", "title": None, "folder_id": None}
        serialized = serializer.serialize(data)
        deserialized = serializer.deserialize(serialized)

        # Type assertion: we know we serialized a dict, so we get a dict back
        assert isinstance(deserialized, dict)
        assert deserialized["id"] == "123"
        assert deserialized["title"] is None
        assert deserialized["folder_id"] is None

    def test_serialize_with_special_characters(self):
        """Test serialization handles special characters."""
        from lookervault.storage.serializer import MsgpackSerializer

        serializer = MsgpackSerializer()

        # Should handle unicode and special chars
        data = {
            "id": "123",
            "title": "Test with émojis 🎉 and spëcial çhars",
            "description": "Line 1\nLine 2\tTabbed",
        }
        serialized = serializer.serialize(data)
        deserialized = serializer.deserialize(serialized)

        # Type assertion: we know we serialized a dict, so we get a dict back
        assert isinstance(deserialized, dict)
        assert deserialized["title"] == data["title"]
        assert deserialized["description"] == data["description"]

    def test_serialize_with_nested_structures(self):
        """Test serialization handles nested structures."""
        from lookervault.storage.serializer import MsgpackSerializer

        serializer = MsgpackSerializer()

        # Should handle nested dicts and lists
        data = {
            "id": "123",
            "nested": {"key": "value", "numbers": [1, 2, 3]},
            "list_of_dicts": [{"a": 1}, {"b": 2}],
        }
        serialized = serializer.serialize(data)
        deserialized = serializer.deserialize(serialized)

        # Type assertion: we know we serialized a dict, so we get a dict back
        assert isinstance(deserialized, dict)
        assert deserialized == data


class TestItemProcessingFailures:
    """Tests for handling item processing failures mid-batch."""

    def test_partial_batch_processing(self):
        """Test worker continues after mid-batch failure."""
        orchestrator, mock_extractor, mock_repository, _ = create_orchestrator_with_mocks()
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Third item fails to save
        mock_extractor.extract_range.side_effect = [
            [
                {"id": "1", "title": "Good 1"},
                {"id": "2", "title": "Good 2"},
                {"id": "3", "title": "Bad"},
                {"id": "4", "title": "Good 3"},
            ],
            [],
        ]

        mock_repository.save_content.side_effect = [
            None,  # Good 1
            None,  # Good 2
            Exception("Save failed"),  # Bad fails
            None,  # Good 3
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should process 3 items successfully
        assert items_processed == 3

    def test_conversion_failure_continues(self):
        """Test worker continues after item conversion failure."""
        orchestrator, mock_extractor, mock_repository, mock_serializer = (
            create_orchestrator_with_mocks()
        )
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Mock serialize to fail for second item
        mock_serializer.serialize.side_effect = [
            b"data1",  # First item OK
            Exception("Conversion failed"),  # Second item fails
            b"data3",  # Third item OK
        ]

        mock_extractor.extract_range.side_effect = [
            [
                {
                    "id": "1",
                    "title": "Item 1",
                    "created_at": "2024-01-01",
                    "updated_at": "2024-01-01",
                },
                {
                    "id": "2",
                    "title": "Item 2",
                    "created_at": "2024-01-01",
                    "updated_at": "2024-01-01",
                },
                {
                    "id": "3",
                    "title": "Item 3",
                    "created_at": "2024-01-01",
                    "updated_at": "2024-01-01",
                },
            ],
            [],
        ]

        mock_repository.save_content.side_effect = [
            None,  # First item
            None,  # Third item
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should process 2 items successfully (1 conversion failure)
        assert items_processed == 2


class TestBatchProcessorEdgeCases:
    """Tests for batch processor edge cases."""

    def test_processor_exception_propagates(self):
        """Test exceptions in processor propagate correctly."""
        processor = MemoryAwareBatchProcessor(enable_monitoring=False)

        def failing_processor(x):
            if x == 5:
                raise ValueError("Cannot process 5")
            return x * 2

        with pytest.raises(ProcessingError):
            list(processor.process_batches(iter([1, 2, 5, 3]), failing_processor, batch_size=2))

    def test_batch_size_larger_than_input(self):
        """Test batch size larger than input iterator."""
        processor = MemoryAwareBatchProcessor(enable_monitoring=False)

        results = list(processor.process_batches(iter([1, 2, 3]), lambda x: x * 2, batch_size=100))
        assert results == [2, 4, 6]

    def test_batch_size_one(self):
        """Test batch size of 1."""
        processor = MemoryAwareBatchProcessor(enable_monitoring=False)

        results = list(processor.process_batches(iter([1, 2, 3]), lambda x: x * 2, batch_size=1))
        assert results == [2, 4, 6]

    def test_processor_returns_none(self):
        """Test processor that returns None for some items."""
        processor = MemoryAwareBatchProcessor(enable_monitoring=False)

        def sometimes_none(x):
            return None if x == 2 else x * 2

        results = list(processor.process_batches(iter([1, 2, 3]), sometimes_none, batch_size=2))
        assert results == [2, None, 6]
