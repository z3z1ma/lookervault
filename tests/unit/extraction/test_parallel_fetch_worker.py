"""Unit tests for ParallelOrchestrator._parallel_fetch_worker()."""

from datetime import UTC, datetime
from unittest.mock import Mock, call

from lookervault.config.models import ParallelConfig
from lookervault.extraction.offset_coordinator import OffsetCoordinator
from lookervault.extraction.orchestrator import ExtractionConfig
from lookervault.extraction.parallel_orchestrator import ParallelOrchestrator
from lookervault.storage.models import ContentType


class TestParallelFetchWorker:
    """Tests for _parallel_fetch_worker method."""

    def create_orchestrator_with_mocks(self):
        """Create orchestrator with mocked dependencies."""
        # Mock extractor
        mock_extractor = Mock()

        # Mock repository
        mock_repository = Mock()
        mock_repository.save_content = Mock()
        mock_repository.close_thread_connection = Mock()

        # Mock serializer
        mock_serializer = Mock()
        mock_serializer.serialize = Mock(return_value=b"serialized_data")

        # Mock progress
        mock_progress = Mock()

        # Create configs
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

        # Create orchestrator
        orchestrator = ParallelOrchestrator(
            extractor=mock_extractor,
            repository=mock_repository,
            serializer=mock_serializer,
            progress=mock_progress,
            config=extraction_config,
            parallel_config=parallel_config,
        )

        return orchestrator, mock_extractor, mock_repository, mock_serializer

    def test_parallel_fetch_worker_basic_flow(self):
        """Test basic flow of parallel fetch worker."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        # Setup coordinator
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Mock extract_range to return full batch then partial batch (last page)
        mock_extractor.extract_range.side_effect = [
            [{"id": str(i), "title": f"Dashboard {i}"} for i in range(100)],  # Full batch
            [
                {"id": "100", "title": "Dashboard 100"},
                {"id": "101", "title": "Dashboard 101"},
                {"id": "102", "title": "Dashboard 102"},
            ],  # Partial batch (< 100, triggers stop)
        ]

        # Run worker
        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields="id,title",
            updated_after=None,
        )

        # Verify results
        assert items_processed == 103
        assert mock_extractor.extract_range.call_count == 2
        assert mock_repository.save_content.call_count == 103
        assert mock_repository.close_thread_connection.call_count == 1
        assert coordinator.get_workers_done() == 1
        assert coordinator.all_workers_done()

    def test_parallel_fetch_worker_multiple_batches(self):
        """Test worker fetching multiple batches until end of data."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Mock 3 full batches, then partial batch (last page)
        mock_extractor.extract_range.side_effect = [
            [{"id": str(i)} for i in range(100)],  # Batch 1: 100 items
            [{"id": str(i)} for i in range(100, 200)],  # Batch 2: 100 items
            [{"id": str(i)} for i in range(200, 300)],  # Batch 3: 100 items
            [{"id": str(i)} for i in range(300, 350)],  # Batch 4: 50 items (last)
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Verify
        assert items_processed == 350
        assert mock_extractor.extract_range.call_count == 4
        assert mock_repository.save_content.call_count == 350
        assert coordinator.get_workers_done() == 1

    def test_parallel_fetch_worker_empty_results_immediately(self):
        """Test worker hitting end-of-data on first fetch."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

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

    def test_parallel_fetch_worker_claims_correct_offset_ranges(self):
        """Test worker claims sequential offset ranges."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=50)
        coordinator.set_total_workers(1)

        # Return items for 3 batches, then empty
        mock_extractor.extract_range.side_effect = [
            [{"id": "1"}] * 50,  # offset=0, limit=50
            [{"id": "2"}] * 50,  # offset=50, limit=50
            [{"id": "3"}] * 50,  # offset=100, limit=50
            [],  # offset=150 (end)
        ]

        orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Verify offset progression
        expected_calls = [
            call(
                ContentType.DASHBOARD,
                offset=0,
                limit=50,
                fields=None,
                updated_after=None,
            ),
            call(
                ContentType.DASHBOARD,
                offset=50,
                limit=50,
                fields=None,
                updated_after=None,
            ),
            call(
                ContentType.DASHBOARD,
                offset=100,
                limit=50,
                fields=None,
                updated_after=None,
            ),
            call(
                ContentType.DASHBOARD,
                offset=150,
                limit=50,
                fields=None,
                updated_after=None,
            ),
        ]

        mock_extractor.extract_range.assert_has_calls(expected_calls)

    def test_parallel_fetch_worker_with_updated_after_filter(self):
        """Test worker passes updated_after filter to extract_range."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        mock_extractor.extract_range.return_value = []

        cutoff_date = datetime(2024, 6, 1, tzinfo=UTC)

        orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields="id,title",
            updated_after=cutoff_date,
        )

        # Verify updated_after passed through
        mock_extractor.extract_range.assert_called_once_with(
            ContentType.DASHBOARD,
            offset=0,
            limit=100,
            fields="id,title",
            updated_after=cutoff_date,
        )

    def test_parallel_fetch_worker_handles_api_errors_gracefully(self):
        """Test worker continues after API fetch errors."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # First fetch fails, second succeeds with partial batch (triggers stop)
        mock_extractor.extract_range.side_effect = [
            Exception("API timeout"),
            [{"id": "1"}],  # Partial batch (< 100, triggers stop)
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should skip failed fetch and continue
        assert items_processed == 1
        assert mock_extractor.extract_range.call_count == 2
        assert mock_repository.save_content.call_count == 1

    def test_parallel_fetch_worker_handles_item_save_errors_gracefully(self):
        """Test worker continues after individual item save errors."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        mock_extractor.extract_range.side_effect = [
            [
                {"id": "1", "title": "Good"},
                {"id": "2", "title": "Bad"},  # Will fail to save
                {"id": "3", "title": "Good"},
            ],
            [],
        ]

        # Second save call fails
        mock_repository.save_content.side_effect = [
            None,  # Success
            Exception("Database error"),  # Failure
            None,  # Success
        ]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should have processed 2 items successfully (1 failed)
        assert items_processed == 2
        assert mock_repository.save_content.call_count == 3

    def test_parallel_fetch_worker_always_closes_connection(self):
        """Test worker always closes thread-local connection in finally block."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Test normal completion
        mock_extractor.extract_range.return_value = []

        orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        assert mock_repository.close_thread_connection.call_count == 1

        # Test with item-level error (should still close connection)
        mock_repository.close_thread_connection.reset_mock()
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        mock_extractor.extract_range.side_effect = [
            [{"id": "1"}],  # Partial batch (triggers stop)
        ]
        # Make save_content fail
        mock_repository.save_content.side_effect = Exception("Database error")

        orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should still close connection despite item error
        assert mock_repository.close_thread_connection.call_count == 1

    def test_parallel_fetch_worker_updates_metrics(self):
        """Test worker updates metrics correctly."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        mock_extractor.extract_range.side_effect = [
            [{"id": str(i)} for i in range(5)],
            [],
        ]

        orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Verify metrics were updated
        snapshot = orchestrator.metrics.snapshot()
        assert snapshot["total"] == 5
        assert snapshot["by_type"][ContentType.DASHBOARD.value] == 5

    def test_parallel_fetch_worker_with_different_content_types(self):
        """Test worker handles different content types correctly."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        mock_extractor.extract_range.side_effect = [[{"id": "1"}], []]

        # Test with LOOK content type
        orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.LOOK.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Verify extract_range called with LOOK
        assert mock_extractor.extract_range.call_args_list[0][0][0] == ContentType.LOOK

        # Reset and test with USER
        mock_extractor.reset_mock()
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)
        mock_extractor.extract_range.side_effect = [[{"id": "user1"}], []]

        orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.USER.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        assert mock_extractor.extract_range.call_args_list[0][0][0] == ContentType.USER

    def test_parallel_fetch_worker_stops_on_partial_batch(self):
        """Test worker stops when receiving fewer items than limit."""
        orchestrator, mock_extractor, mock_repository, _ = self.create_orchestrator_with_mocks()

        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(1)

        # Return partial batch (75 items when limit is 100)
        mock_extractor.extract_range.return_value = [{"id": str(i)} for i in range(75)]

        items_processed = orchestrator._parallel_fetch_worker(
            worker_id=0,
            content_type=ContentType.DASHBOARD.value,
            coordinator=coordinator,
            fields=None,
            updated_after=None,
        )

        # Should process items and stop (not fetch again)
        assert items_processed == 75
        assert mock_extractor.extract_range.call_count == 1
        assert coordinator.get_workers_done() == 1
