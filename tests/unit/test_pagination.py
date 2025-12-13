"""Tests for pagination in Looker API extraction."""

from unittest.mock import Mock

from lookervault.looker.extractor import LookerContentExtractor
from lookervault.storage.models import ContentType


class TestDashboardPagination:
    """Test paginated dashboard extraction."""

    def test_paginate_dashboards_single_page(self):
        """Test pagination with results fitting in one page."""
        # Mock Looker client
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock search_dashboards to return 50 items (less than batch_size)
        mock_dashboards = [Mock(id=str(i), title=f"Dashboard {i}") for i in range(50)]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)

        # Extract dashboards with batch_size=100
        results = list(extractor._paginate_dashboards(fields=None, batch_size=100))

        # Should make exactly one API call
        assert mock_sdk.search_dashboards.call_count == 1
        # Should return all 50 items
        assert len(results) == 50

    def test_paginate_dashboards_multiple_pages(self):
        """Test pagination with results spanning multiple pages."""
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
        results = list(extractor._paginate_dashboards(fields=None, batch_size=100))

        # Should make 3 API calls
        assert mock_sdk.search_dashboards.call_count == 3
        # Should return all 250 items
        assert len(results) == 250

    def test_paginate_dashboards_empty_result(self):
        """Test pagination with no results."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.return_value = []

        extractor = LookerContentExtractor(client=mock_client)
        results = list(extractor._paginate_dashboards(fields=None, batch_size=100))

        # Should make one API call
        assert mock_sdk.search_dashboards.call_count == 1
        # Should return no items
        assert len(results) == 0

    def test_paginate_dashboards_with_filters(self):
        """Test pagination with field filters."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_dashboards = [Mock(id="1", title="Test")]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)
        results = list(extractor._paginate_dashboards(fields="id,title", batch_size=100))

        # Should pass fields parameter to API
        mock_sdk.search_dashboards.assert_called_once_with(fields="id,title", limit=100, offset=0)
        assert len(results) == 1


class TestLooksPagination:
    """Test paginated looks extraction."""

    def test_paginate_looks_large_instance(self):
        """Test pagination handles 10,000+ looks."""
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
        results = list(extractor._paginate_looks(fields=None, batch_size=100))

        # Should make 101 API calls (100 pages + 1 empty check at end)
        # This is correct behavior - pagination checks for more results
        assert call_count == 101
        # Should return all 10,000 items
        assert len(results) == 10000


class TestExtractAllWithPagination:
    """Test extract_all method uses pagination for dashboards and looks."""

    def test_extract_all_dashboards_uses_pagination(self):
        """Test that extract_all delegates to _paginate_dashboards."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_dashboards = [Mock(id="1", title="Test")]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)

        # Extract dashboards (consume iterator)
        list(extractor.extract_all(content_type=ContentType.DASHBOARD, batch_size=100))

        # Should call search_dashboards (pagination) not all_dashboards
        assert mock_sdk.search_dashboards.called
        assert not mock_sdk.all_dashboards.called

    def test_extract_all_looks_uses_pagination(self):
        """Test that extract_all delegates to _paginate_looks."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_looks = [Mock(id="1", title="Test")]
        mock_sdk.search_looks.return_value = mock_looks

        extractor = LookerContentExtractor(client=mock_client)

        # Extract looks (consume iterator)
        list(extractor.extract_all(content_type=ContentType.LOOK, batch_size=100))

        # Should call search_looks (pagination) not all_looks
        assert mock_sdk.search_looks.called
        assert not mock_sdk.all_looks.called


class TestBatchSizeConfiguration:
    """Test that batch_size parameter is respected."""

    def test_custom_batch_size_dashboards(self):
        """Test using custom batch size for dashboards."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.return_value = [Mock(id="1")]

        extractor = LookerContentExtractor(client=mock_client)
        list(extractor._paginate_dashboards(fields=None, batch_size=50))

        # Should use custom batch size
        mock_sdk.search_dashboards.assert_called_with(fields=None, limit=50, offset=0)

    def test_small_batch_size_for_rate_limiting(self):
        """Test small batch size to avoid rate limits."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.return_value = [Mock(id="1")]

        extractor = LookerContentExtractor(client=mock_client)
        list(extractor._paginate_dashboards(fields=None, batch_size=25))

        # Should use smaller batch size
        mock_sdk.search_dashboards.assert_called_with(fields=None, limit=25, offset=0)
