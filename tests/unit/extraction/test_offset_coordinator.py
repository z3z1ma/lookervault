"""Unit tests for OffsetCoordinator."""

import threading

from lookervault.extraction.offset_coordinator import OffsetCoordinator


class TestOffsetCoordinator:
    """Tests for OffsetCoordinator class."""

    def test_initial_state(self):
        """Test coordinator initializes with correct state."""
        coordinator = OffsetCoordinator(stride=100)
        assert coordinator.get_current_offset() == 0, (
            f"Expected initial offset to be 0 but got {coordinator.get_current_offset()}"
        )
        assert coordinator.get_workers_done() == 0, (
            f"Expected initial workers_done to be 0 but got {coordinator.get_workers_done()}"
        )

    def test_claim_range_returns_sequential_offsets(self):
        """Test that claim_range returns sequential offset ranges."""
        coordinator = OffsetCoordinator(stride=100)

        # First claim
        offset, limit = coordinator.claim_range()
        assert offset == 0, f"Expected first offset to be 0 but got {offset}"
        assert limit == 100, f"Expected limit to be 100 but got {limit}"

        # Second claim
        offset, limit = coordinator.claim_range()
        assert offset == 100, f"Expected second offset to be 100 but got {offset}"
        assert limit == 100, f"Expected limit to be 100 but got {limit}"

        # Third claim
        offset, limit = coordinator.claim_range()
        assert offset == 200, f"Expected third offset to be 200 but got {offset}"
        assert limit == 100, f"Expected limit to be 100 but got {limit}"

    def test_claim_range_with_custom_stride(self):
        """Test claim_range with different stride values."""
        coordinator = OffsetCoordinator(stride=50)

        offset, limit = coordinator.claim_range()
        assert offset == 0, f"Expected first offset to be 0 but got {offset}"
        assert limit == 50, f"Expected limit to be 50 but got {limit}"

        offset, limit = coordinator.claim_range()
        assert offset == 50, f"Expected second offset to be 50 but got {offset}"
        assert limit == 50, f"Expected limit to be 50 but got {limit}"

        offset, limit = coordinator.claim_range()
        assert offset == 100, f"Expected third offset to be 100 but got {offset}"
        assert limit == 50, f"Expected limit to be 50 but got {limit}"

    def test_mark_worker_complete(self):
        """Test marking workers as complete."""
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(3)

        assert coordinator.get_workers_done() == 0, (
            f"Expected 0 workers done initially but got {coordinator.get_workers_done()}"
        )
        assert not coordinator.all_workers_done(), "Expected all_workers_done to be False initially"

        coordinator.mark_worker_complete()
        assert coordinator.get_workers_done() == 1, (
            f"Expected 1 worker done after first mark but got {coordinator.get_workers_done()}"
        )
        assert not coordinator.all_workers_done(), (
            "Expected all_workers_done to be False with 1/3 workers"
        )

        coordinator.mark_worker_complete()
        assert coordinator.get_workers_done() == 2, (
            f"Expected 2 workers done after second mark but got {coordinator.get_workers_done()}"
        )
        assert not coordinator.all_workers_done(), (
            "Expected all_workers_done to be False with 2/3 workers"
        )

        coordinator.mark_worker_complete()
        assert coordinator.get_workers_done() == 3, (
            f"Expected 3 workers done after third mark but got {coordinator.get_workers_done()}"
        )
        assert coordinator.all_workers_done(), (
            "Expected all_workers_done to be True with 3/3 workers"
        )

    def test_all_workers_done_edge_cases(self):
        """Test all_workers_done with edge cases."""
        coordinator = OffsetCoordinator(stride=100)

        # Zero workers
        coordinator.set_total_workers(0)
        assert coordinator.all_workers_done(), (
            "Expected all_workers_done to be True with 0 workers (vacuously true)"
        )

        # One worker
        coordinator.set_total_workers(1)
        assert not coordinator.all_workers_done(), (
            "Expected all_workers_done to be False with 1 incomplete worker"
        )
        coordinator.mark_worker_complete()
        assert coordinator.all_workers_done(), (
            "Expected all_workers_done to be True with 1 complete worker"
        )

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
        threads = [threading.Thread(target=worker_claim_ranges) for _ in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all claims are unique and sequential
        claimed_ranges.sort()
        expected_claims = num_workers * claims_per_worker
        assert len(claimed_ranges) == expected_claims, (
            f"Expected {expected_claims} unique claims but got {len(claimed_ranges)}"
        )

        for i, (offset, limit) in enumerate(claimed_ranges):
            expected_offset = i * 100
            assert offset == expected_offset, (
                f"Expected offset {expected_offset} at index {i} but got {offset}"
            )
            assert limit == 100, f"Expected limit to be 100 at index {i} but got {limit}"

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
        assert coordinator.get_workers_done() == num_workers, (
            f"Expected {num_workers} workers done but got {coordinator.get_workers_done()}"
        )
        assert coordinator.all_workers_done(), (
            "Expected all_workers_done to be True after all workers marked complete"
        )

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
        assert len(completed) == num_workers, (
            f"Expected {num_workers} workers to complete but got {len(completed)}"
        )
        assert coordinator.get_workers_done() == num_workers, (
            f"Expected {num_workers} workers done but got {coordinator.get_workers_done()}"
        )
        assert coordinator.all_workers_done(), (
            "Expected all_workers_done to be True after all workers complete"
        )
        expected_offset = num_workers * 10 * 100  # 5 workers * 10 claims * 100 stride
        assert coordinator.get_current_offset() == expected_offset, (
            f"Expected offset to be {expected_offset} but got {coordinator.get_current_offset()}"
        )

    def test_set_total_workers(self):
        """Test setting total workers count."""
        coordinator = OffsetCoordinator(stride=100)

        coordinator.set_total_workers(5)
        assert not coordinator.all_workers_done(), (
            "Expected all_workers_done to be False with 0/5 workers"
        )

        for _ in range(4):
            coordinator.mark_worker_complete()
            assert not coordinator.all_workers_done(), (
                "Expected all_workers_done to be False with <5 workers"
            )

        coordinator.mark_worker_complete()
        assert coordinator.all_workers_done(), (
            "Expected all_workers_done to be True with 5/5 workers"
        )

    def test_claim_range_does_not_interfere_with_completion(self):
        """Test that claiming ranges doesn't affect worker completion tracking."""
        coordinator = OffsetCoordinator(stride=100)
        coordinator.set_total_workers(2)

        # Claim ranges
        coordinator.claim_range()
        coordinator.claim_range()
        coordinator.claim_range()

        # Verify completion tracking unaffected
        assert coordinator.get_workers_done() == 0, (
            f"Expected 0 workers done after claims but got {coordinator.get_workers_done()}"
        )
        assert not coordinator.all_workers_done(), (
            "Expected all_workers_done to be False with 0 complete workers"
        )

        # Mark workers complete
        coordinator.mark_worker_complete()
        coordinator.mark_worker_complete()

        # Verify completion
        assert coordinator.all_workers_done(), (
            "Expected all_workers_done to be True with 2/2 complete workers"
        )

        # Claim more ranges after completion (shouldn't affect completion status)
        coordinator.claim_range()
        coordinator.claim_range()

        assert coordinator.all_workers_done(), (
            "Expected all_workers_done to remain True after post-completion claims"
        )
