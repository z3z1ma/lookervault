"""Tests for pagination in Looker API extraction."""

from unittest.mock import Mock

from lookervault.looker.extractor import LookerContentExtractor
from lookervault.storage.models import ContentType


class TestExtractAllWithPagination:
    """Test extract_all method uses pagination for dashboards and looks."""

    def test_extract_all_dashboards_single_page(self):
        """Test pagination with results fitting in one page via public API."""
        # Mock Looker client
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock search_dashboards to return 50 items (less than batch_size)
        mock_dashboards = [Mock(id=str(i), title=f"Dashboard {i}") for i in range(50)]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)

        # Extract dashboards with batch_size=100 via public API
        results = list(extractor.extract_all(content_type=ContentType.DASHBOARD, batch_size=100))

        # Should make exactly one API call
        assert mock_sdk.search_dashboards.call_count == 1
        # Should return all 50 items
        assert len(results) == 50

    def test_extract_all_dashboards_multiple_pages(self):
        """Test pagination with results spanning multiple pages via public API."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Simulate 250 dashboards with batch_size=100
        # Page 1: 100 items (offset=0)
        # Page 2: 100 items (offset=100)
        # Page 3: 50 items (offset=200)

        def mock_search(fields=None, limit=100, offset=0):
            if offset == 0:
                return [Mock(id=str(i), title=f"Dashboard {i}") for i in range(100)]
            elif offset == 100:
                return [Mock(id=str(i), title=f"Dashboard {i}") for i in range(100, 200)]
            elif offset == 200:
                return [Mock(id=str(i), title=f"Dashboard {i}") for i in range(200, 250)]
            else:
                return []

        mock_sdk.search_dashboards.side_effect = mock_search

        extractor = LookerContentExtractor(client=mock_client)
        results = list(extractor.extract_all(content_type=ContentType.DASHBOARD, batch_size=100))

        # Should make 3 API calls
        assert mock_sdk.search_dashboards.call_count == 3
        # Should return all 250 items
        assert len(results) == 250

    def test_extract_all_dashboards_empty_result(self):
        """Test pagination with no results via public API."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.return_value = []

        extractor = LookerContentExtractor(client=mock_client)
        results = list(extractor.extract_all(content_type=ContentType.DASHBOARD, batch_size=100))

        # Should make one API call
        assert mock_sdk.search_dashboards.call_count == 1
        # Should return no items
        assert len(results) == 0

    def test_extract_all_looks_large_instance(self):
        """Test pagination handles 10,000+ looks via public API."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Simulate 10,000 looks with batch_size=100
        # Would require 100 API calls
        call_count = 0

        def mock_search(fields=None, limit=100, offset=0):
            nonlocal call_count
            call_count += 1

            start = offset
            end = min(offset + limit, 10000)

            if start >= 10000:
                return []

            return [Mock(id=str(i), title=f"Look {i}") for i in range(start, end)]

        mock_sdk.search_looks.side_effect = mock_search

        extractor = LookerContentExtractor(client=mock_client)
        results = list(extractor.extract_all(content_type=ContentType.LOOK, batch_size=100))

        # Should make 101 API calls (100 pages + 1 empty check at end)
        # This is correct behavior - pagination checks for more results
        assert call_count == 101
        # Should return all 10,000 items
        assert len(results) == 10000


class TestBatchSizeConfiguration:
    """Test that batch_size parameter is respected via public API."""

    def test_custom_batch_size_dashboards(self):
        """Test using custom batch size for dashboards."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.return_value = [Mock(id="1")]

        extractor = LookerContentExtractor(client=mock_client)
        list(extractor.extract_all(content_type=ContentType.DASHBOARD, batch_size=50))

        # Should use custom batch size
        mock_sdk.search_dashboards.assert_called_with(fields=None, limit=50, offset=0)

    def test_small_batch_size_for_rate_limiting(self):
        """Test small batch size to avoid rate limits."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.return_value = [Mock(id="1")]

        extractor = LookerContentExtractor(client=mock_client)
        list(extractor.extract_all(content_type=ContentType.DASHBOARD, batch_size=25))

        # Should use smaller batch size
        mock_sdk.search_dashboards.assert_called_with(fields=None, limit=25, offset=0)
