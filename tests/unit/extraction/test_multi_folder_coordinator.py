"""Unit tests for MultiFolderOffsetCoordinator."""

import threading

from lookervault.extraction.multi_folder_coordinator import (
    FolderRange,
    MultiFolderOffsetCoordinator,
)


class TestFolderRange:
    """Tests for FolderRange dataclass."""

    def test_initialization(self):
        """Test FolderRange initializes with correct defaults."""
        folder_range = FolderRange(folder_id="123")
        assert folder_range.folder_id == "123"
        assert folder_range.current_offset == 0
        assert folder_range.workers_done == 0
        assert folder_range.total_claimed == 0


class TestMultiFolderOffsetCoordinator:
    """Tests for MultiFolderOffsetCoordinator class."""

    def test_initialization(self):
        """Test coordinator initializes with correct state."""
        folder_ids = ["123", "456", "789"]
        coordinator = MultiFolderOffsetCoordinator(folder_ids=folder_ids, stride=100)

        assert len(coordinator._folder_ranges) == 3
        assert "123" in coordinator._folder_ranges
        assert "456" in coordinator._folder_ranges
        assert "789" in coordinator._folder_ranges

        # Verify all folders start at offset 0
        for folder_id in folder_ids:
            folder_range = coordinator._folder_ranges[folder_id]
            assert folder_range.current_offset == 0
            assert folder_range.workers_done == 0
            assert folder_range.total_claimed == 0

    def test_set_total_workers(self):
        """Test setting total workers count."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456"], stride=100)
        coordinator.set_total_workers(8)
        assert coordinator._total_workers == 8

    def test_claim_range_round_robin(self):
        """Test that claim_range distributes work across folders using round-robin."""
        folder_ids = ["123", "456", "789"]
        coordinator = MultiFolderOffsetCoordinator(folder_ids=folder_ids, stride=100)
        coordinator.set_total_workers(3)

        # First round: should cycle through all folders
        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "123"
        assert offset == 0
        assert limit == 100

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "456"
        assert offset == 0
        assert limit == 100

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "789"
        assert offset == 0
        assert limit == 100

        # Second round: should cycle through again with incremented offsets
        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "123"
        assert offset == 100
        assert limit == 100

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "456"
        assert offset == 100
        assert limit == 100

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "789"
        assert offset == 100
        assert limit == 100

    def test_claim_range_with_custom_stride(self):
        """Test claim_range with different stride values."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456"], stride=50)
        coordinator.set_total_workers(2)

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "123"
        assert offset == 0
        assert limit == 50

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "456"
        assert offset == 0
        assert limit == 50

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "123"
        assert offset == 50
        assert limit == 50

    def test_mark_folder_complete(self):
        """Test marking folders as complete."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456"], stride=100)
        coordinator.set_total_workers(3)

        # Mark folder 123 complete by 3 workers
        coordinator.mark_folder_complete("123")
        assert coordinator._folder_ranges["123"].workers_done == 1

        coordinator.mark_folder_complete("123")
        assert coordinator._folder_ranges["123"].workers_done == 2

        coordinator.mark_folder_complete("123")
        assert coordinator._folder_ranges["123"].workers_done == 3

        # Folder 456 should be unaffected
        assert coordinator._folder_ranges["456"].workers_done == 0

    def test_claim_range_skips_exhausted_folders(self):
        """Test that exhausted folders are skipped in round-robin."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456", "789"], stride=100)
        coordinator.set_total_workers(2)

        # Claim from folder 123
        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "123"

        # Mark folder 123 as exhausted (2 workers done = total workers)
        coordinator.mark_folder_complete("123")
        coordinator.mark_folder_complete("123")

        # Next claims should skip folder 123
        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "456"

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "789"

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "456"  # Wraps around, skips 123

        folder_id, offset, limit = coordinator.claim_range()
        assert folder_id == "789"

    def test_claim_range_returns_none_when_all_exhausted(self):
        """Test that claim_range returns None when all folders are exhausted."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456"], stride=100)
        coordinator.set_total_workers(1)

        # Mark both folders as exhausted
        coordinator.mark_folder_complete("123")
        coordinator.mark_folder_complete("456")

        # Should return None
        result = coordinator.claim_range()
        assert result is None

        # Subsequent calls should also return None
        result = coordinator.claim_range()
        assert result is None

    def test_per_folder_offset_tracking(self):
        """Test that each folder maintains its own offset counter."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456"], stride=100)
        coordinator.set_total_workers(2)

        # Track claims by folder
        folder_123_claims = []
        folder_456_claims = []

        # Claim 6 ranges (3 per folder due to round-robin)
        for _ in range(6):
            folder_id, offset, limit = coordinator.claim_range()
            if folder_id == "123":
                folder_123_claims.append(offset)
            else:
                folder_456_claims.append(offset)

        # Verify folder 123 got sequential offsets
        assert folder_123_claims == [0, 100, 200]

        # Verify folder 456 got sequential offsets independently
        assert folder_456_claims == [0, 100, 200]

    def test_get_statistics(self):
        """Test getting per-folder statistics."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456"], stride=100)
        coordinator.set_total_workers(3)

        # Claim ranges and mark completions
        coordinator.claim_range()  # folder 123, offset 0
        coordinator.claim_range()  # folder 456, offset 0
        coordinator.claim_range()  # folder 123, offset 100
        coordinator.mark_folder_complete("123")
        coordinator.mark_folder_complete("123")

        stats = coordinator.get_statistics()

        assert "123" in stats
        assert "456" in stats

        assert stats["123"]["current_offset"] == 200
        assert stats["123"]["workers_done"] == 2
        assert stats["123"]["total_claimed"] == 2

        assert stats["456"]["current_offset"] == 100
        assert stats["456"]["workers_done"] == 0
        assert stats["456"]["total_claimed"] == 1

    def test_thread_safety_concurrent_claims(self):
        """Test that concurrent claim_range calls are thread-safe."""
        folder_ids = ["123", "456", "789"]
        coordinator = MultiFolderOffsetCoordinator(folder_ids=folder_ids, stride=100)
        coordinator.set_total_workers(10)

        num_workers = 10
        claims_per_worker = 30
        claimed_ranges = []
        lock = threading.Lock()

        def worker_claim_ranges():
            for _ in range(claims_per_worker):
                result = coordinator.claim_range()
                if result is not None:
                    with lock:
                        claimed_ranges.append(result)

        # Launch workers
        threads = [threading.Thread(target=worker_claim_ranges) for _ in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all claims are valid
        assert len(claimed_ranges) == num_workers * claims_per_worker

        # Group claims by folder
        folder_claims = {"123": [], "456": [], "789": []}
        for folder_id, offset, limit in claimed_ranges:
            assert folder_id in folder_ids
            assert limit == 100
            folder_claims[folder_id].append(offset)

        # Verify each folder's offsets are unique and sequential
        for folder_id in folder_ids:
            offsets = sorted(folder_claims[folder_id])
            # Each offset should be unique
            assert len(offsets) == len(set(offsets))
            # Offsets should be multiples of stride
            for offset in offsets:
                assert offset % 100 == 0

    def test_thread_safety_concurrent_completion(self):
        """Test that concurrent mark_folder_complete calls are thread-safe."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456"], stride=100)
        num_workers = 10
        coordinator.set_total_workers(num_workers)

        def worker_mark_complete(folder_id):
            coordinator.mark_folder_complete(folder_id)

        # Launch workers for folder 123
        threads = [
            threading.Thread(target=worker_mark_complete, args=("123",)) for _ in range(num_workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify final state
        assert coordinator._folder_ranges["123"].workers_done == num_workers
        assert coordinator._folder_ranges["456"].workers_done == 0

    def test_thread_safety_mixed_operations(self):
        """Test thread safety with concurrent claims and completions."""
        folder_ids = ["123", "456", "789"]
        coordinator = MultiFolderOffsetCoordinator(folder_ids=folder_ids, stride=100)
        num_workers = 8
        coordinator.set_total_workers(num_workers)

        completed_folders = {folder_id: [] for folder_id in folder_ids}
        lock = threading.Lock()

        def worker(worker_id):
            # Each worker claims 15 ranges
            for _ in range(15):
                result = coordinator.claim_range()
                if result is None:
                    break

            # Mark completion for all folders
            for folder_id in folder_ids:
                coordinator.mark_folder_complete(folder_id)
                with lock:
                    completed_folders[folder_id].append(worker_id)

        # Launch workers
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all workers marked all folders complete
        for folder_id in folder_ids:
            assert len(completed_folders[folder_id]) == num_workers
            assert coordinator._folder_ranges[folder_id].workers_done == num_workers

    def test_single_folder_behavior(self):
        """Test coordinator behavior with a single folder."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123"], stride=100)
        coordinator.set_total_workers(3)

        # Should always return same folder
        for i in range(5):
            folder_id, offset, limit = coordinator.claim_range()
            assert folder_id == "123"
            assert offset == i * 100
            assert limit == 100

        # Mark as exhausted
        coordinator.mark_folder_complete("123")
        coordinator.mark_folder_complete("123")
        coordinator.mark_folder_complete("123")

        # Should return None
        assert coordinator.claim_range() is None

    def test_realistic_multi_folder_extraction_simulation(self):
        """Simulate realistic multi-folder extraction workflow."""
        # Scenario: 3 folders, 8 workers, each folder has different amount of data
        folder_ids = ["123", "456", "789"]
        coordinator = MultiFolderOffsetCoordinator(folder_ids=folder_ids, stride=100)
        num_workers = 8
        coordinator.set_total_workers(num_workers)

        # Simulate folder sizes (number of items)
        # folder 123: 250 items (3 pages)
        # folder 456: 150 items (2 pages)
        # folder 789: 50 items (1 page)
        folder_sizes = {"123": 250, "456": 150, "789": 50}

        fetched_items = {folder_id: [] for folder_id in folder_ids}
        workers_done_per_folder = dict.fromkeys(folder_ids, 0)
        lock = threading.Lock()

        def worker(worker_id):
            while True:
                result = coordinator.claim_range()
                if result is None:
                    break

                folder_id, offset, limit = result

                # Simulate fetching data from API
                folder_size = folder_sizes[folder_id]
                items_to_fetch = min(limit, max(0, folder_size - offset))

                with lock:
                    if items_to_fetch > 0:
                        fetched_items[folder_id].extend(range(offset, offset + items_to_fetch))

                # If we got fewer items than requested, mark folder complete
                if items_to_fetch < limit:
                    coordinator.mark_folder_complete(folder_id)
                    with lock:
                        workers_done_per_folder[folder_id] += 1

        # Launch workers
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all items fetched for each folder
        assert sorted(fetched_items["123"]) == list(range(250))
        assert sorted(fetched_items["456"]) == list(range(150))
        assert sorted(fetched_items["789"]) == list(range(50))

        # Verify each folder marked complete by at least one worker
        for folder_id in folder_ids:
            assert workers_done_per_folder[folder_id] >= 1

        # Verify coordinator is exhausted
        assert coordinator.claim_range() is None

    def test_total_claimed_increments_correctly(self):
        """Test that total_claimed counter increments for each folder."""
        coordinator = MultiFolderOffsetCoordinator(folder_ids=["123", "456"], stride=100)
        coordinator.set_total_workers(2)

        # Claim from each folder multiple times
        for _ in range(3):
            coordinator.claim_range()  # folder 123
            coordinator.claim_range()  # folder 456

        stats = coordinator.get_statistics()
        assert stats["123"]["total_claimed"] == 3
        assert stats["456"]["total_claimed"] == 3
