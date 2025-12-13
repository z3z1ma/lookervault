"""Unit tests for OffsetCoordinator."""

import threading
from lookervault.extraction.offset_coordinator import OffsetCoordinator


class TestOffsetCoordinator:
    """Tests for OffsetCoordinator class."""

    def test_initial_state(self):
        """Test coordinator initializes with correct state."""
        coordinator = OffsetCoordinator(stride=100)
        assert coordinator.get_current_offset() == 0
        assert coordinator.get_workers_done() == 0

    def test_claim_range_returns_sequential_offsets(self):
        """Test that claim_range returns sequential offset ranges."""
        coordinator = OffsetCoordinator(stride=100)

        # First claim
        offset, limit = coordinator.claim_range()
        assert offset == 0
        assert limit == 100

        # Second claim
        offset, limit = coordinator.claim_range()
        assert offset == 100
        assert limit == 100

        # Third claim
        offset, limit = coordinator.claim_range()
        assert offset == 200
        assert limit == 100

    def test_claim_range_with_custom_stride(self):
        """Test claim_range with different stride values."""
        coordinator = OffsetCoordinator(stride=50)

        offset, limit = coordinator.claim_range()
        assert offset == 0
        assert limit == 50

        offset, limit = coordinator.claim_range()
        assert offset == 50
        assert limit == 50

        offset, limit = coordinator.claim_range()
        assert offset == 100
        assert limit == 50

    def test_mark_worker_complete(self):
        """Test marking workers as complete."""
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(3)

        assert coordinator.get_workers_done() == 0
        assert not coordinator.all_workers_done()

        coordinator.mark_worker_complete()
        assert coordinator.get_workers_done() == 1
        assert not coordinator.all_workers_done()

        coordinator.mark_worker_complete()
        assert coordinator.get_workers_done() == 2
        assert not coordinator.all_workers_done()

        coordinator.mark_worker_complete()
        assert coordinator.get_workers_done() == 3
        assert coordinator.all_workers_done()

    def test_all_workers_done_edge_cases(self):
        """Test all_workers_done with edge cases."""
        coordinator = OffsetCoordinator(stride=100)

        # Zero workers
        coordinator.set_total_workers(0)
        assert coordinator.all_workers_done()  # Vacuously true

        # One worker
        coordinator.set_total_workers(1)
        assert not coordinator.all_workers_done()
        coordinator.mark_worker_complete()
        assert coordinator.all_workers_done()

    def test_thread_safety_concurrent_claims(self):
        """Test that concurrent claim_range calls are thread-safe."""
        coordinator = OffsetCoordinator(stride=100)
        num_workers = 10
        claims_per_worker = 100

        claimed_ranges = []
        lock = threading.Lock()

        def worker_claim_ranges():
            for _ in range(claims_per_worker):
                offset, limit = coordinator.claim_range()
                with lock:
                    claimed_ranges.append((offset, limit))

        # Launch workers
        threads = [
            threading.Thread(target=worker_claim_ranges) for _ in range(num_workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all claims are unique and sequential
        claimed_ranges.sort()
        assert len(claimed_ranges) == num_workers * claims_per_worker

        for i, (offset, limit) in enumerate(claimed_ranges):
            expected_offset = i * 100
            assert offset == expected_offset
            assert limit == 100

    def test_thread_safety_concurrent_completion(self):
        """Test that concurrent mark_worker_complete calls are thread-safe."""
        coordinator = OffsetCoordinator(stride=100)
        num_workers = 10
        coordinator.set_total_workers(num_workers)

        def worker_mark_complete():
            coordinator.mark_worker_complete()

        # Launch workers
        threads = [threading.Thread(target=worker_mark_complete) for _ in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify final state
        assert coordinator.get_workers_done() == num_workers
        assert coordinator.all_workers_done()

    def test_thread_safety_mixed_operations(self):
        """Test thread safety with concurrent claims and completions."""
        coordinator = OffsetCoordinator(stride=100)
        num_workers = 5
        coordinator.set_total_workers(num_workers)

        completed = []
        lock = threading.Lock()

        def worker(worker_id):
            # Each worker claims 10 ranges
            for _ in range(10):
                coordinator.claim_range()

            # Then marks itself complete
            coordinator.mark_worker_complete()
            with lock:
                completed.append(worker_id)

        # Launch workers
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify final state
        assert len(completed) == num_workers
        assert coordinator.get_workers_done() == num_workers
        assert coordinator.all_workers_done()
        assert coordinator.get_current_offset() == num_workers * 10 * 100  # 5 workers * 10 claims * 100 stride

    def test_set_total_workers(self):
        """Test setting total workers count."""
        coordinator = OffsetCoordinator(stride=100)

        coordinator.set_total_workers(5)
        assert not coordinator.all_workers_done()

        for _ in range(4):
            coordinator.mark_worker_complete()
            assert not coordinator.all_workers_done()

        coordinator.mark_worker_complete()
        assert coordinator.all_workers_done()

    def test_claim_range_does_not_interfere_with_completion(self):
        """Test that claiming ranges doesn't affect worker completion tracking."""
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(2)

        # Claim ranges
        coordinator.claim_range()
        coordinator.claim_range()
        coordinator.claim_range()

        # Verify completion tracking unaffected
        assert coordinator.get_workers_done() == 0
        assert not coordinator.all_workers_done()

        # Mark workers complete
        coordinator.mark_worker_complete()
        coordinator.mark_worker_complete()

        # Verify completion
        assert coordinator.all_workers_done()

        # Claim more ranges after completion (shouldn't affect completion status)
        coordinator.claim_range()
        coordinator.claim_range()

        assert coordinator.all_workers_done()
