"""Unit tests for ContentExtractor.extract_range()."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from lookervault.exceptions import ExtractionError
from lookervault.looker.extractor import LookerContentExtractor
from lookervault.storage.models import ContentType


class TestExtractRange:
    """Tests for ContentExtractor.extract_range() method."""

    def test_extract_range_dashboards_basic(self):
        """Test basic dashboard range extraction."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock API response
        mock_dashboards = [
            Mock(id="1", title="Dashboard 1"),
            Mock(id="2", title="Dashboard 2"),
            Mock(id="3", title="Dashboard 3"),
        ]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)

        # Extract range
        results = extractor.extract_range(
            content_type=ContentType.DASHBOARD, offset=0, limit=100, fields="id,title"
        )

        # Verify API call
        mock_sdk.search_dashboards.assert_called_once_with(fields="id,title", limit=100, offset=0)

        # Verify results
        assert len(results) == 3
        assert results[0]["id"] == "1"
        assert results[0]["title"] == "Dashboard 1"

    def test_extract_range_looks(self):
        """Test looks range extraction."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_looks = [Mock(id="100", title="Look 100") for _ in range(50)]
        mock_sdk.search_looks.return_value = mock_looks

        extractor = LookerContentExtractor(client=mock_client)

        results = extractor.extract_range(content_type=ContentType.LOOK, offset=200, limit=50)

        # Verify API call with correct offset
        mock_sdk.search_looks.assert_called_once_with(fields=None, limit=50, offset=200)
        assert len(results) == 50

    def test_extract_range_users(self):
        """Test users range extraction (includes embed users)."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_users = [Mock(id=str(i), email=f"user{i}@example.com") for i in range(25)]
        mock_sdk.all_users.return_value = mock_users

        extractor = LookerContentExtractor(client=mock_client)

        results = extractor.extract_range(content_type=ContentType.USER, offset=500, limit=100)

        mock_sdk.all_users.assert_called_once_with(fields=None, limit=100, offset=500)
        assert len(results) == 25

    def test_extract_range_groups(self):
        """Test groups range extraction."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_groups = [Mock(id=str(i), name=f"Group {i}") for i in range(10)]
        mock_sdk.all_groups.return_value = mock_groups

        extractor = LookerContentExtractor(client=mock_client)

        results = extractor.extract_range(content_type=ContentType.GROUP, offset=0, limit=100)

        mock_sdk.all_groups.assert_called_once_with(fields=None, limit=100, offset=0)
        assert len(results) == 10

    def test_extract_range_roles(self):
        """Test roles range extraction."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_roles = [Mock(id=str(i), name=f"Role {i}") for i in range(5)]
        mock_sdk.search_roles.return_value = mock_roles

        extractor = LookerContentExtractor(client=mock_client)

        results = extractor.extract_range(content_type=ContentType.ROLE, offset=100, limit=50)

        mock_sdk.search_roles.assert_called_once_with(fields=None, limit=50, offset=100)
        assert len(results) == 5

    def test_extract_range_empty_results(self):
        """Test extract_range with empty results (end of data)."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.return_value = []

        extractor = LookerContentExtractor(client=mock_client)

        results = extractor.extract_range(
            content_type=ContentType.DASHBOARD, offset=1000, limit=100
        )

        assert len(results) == 0
        assert results == []

    def test_extract_range_partial_results(self):
        """Test extract_range returning fewer items than limit (last page)."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Return only 30 items when limit is 100 (last page)
        mock_dashboards = [Mock(id=str(i), title=f"Dashboard {i}") for i in range(30)]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)

        results = extractor.extract_range(content_type=ContentType.DASHBOARD, offset=970, limit=100)

        assert len(results) == 30

    def test_extract_range_with_fields_filter(self):
        """Test extract_range passes fields parameter correctly."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_dashboards = [Mock(id="1", title="Test", description="Desc")]
        mock_sdk.search_dashboards.return_value = mock_dashboards

        extractor = LookerContentExtractor(client=mock_client)

        extractor.extract_range(
            content_type=ContentType.DASHBOARD,
            offset=0,
            limit=50,
            fields="id,title,description",
        )

        mock_sdk.search_dashboards.assert_called_once_with(
            fields="id,title,description", limit=50, offset=0
        )

    def test_extract_range_with_updated_after_filter(self):
        """Test extract_range filters by updated_after timestamp."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Create mock dashboards with different updated_at times
        old_dashboard = Mock(
            id="1",
            title="Old Dashboard",
            updated_at="2024-01-01T00:00:00Z",
        )
        new_dashboard = Mock(
            id="2",
            title="New Dashboard",
            updated_at="2024-12-01T00:00:00Z",
        )

        mock_sdk.search_dashboards.return_value = [old_dashboard, new_dashboard]

        extractor = LookerContentExtractor(client=mock_client)

        # Filter for items updated after 2024-06-01
        cutoff_date = datetime(2024, 6, 1, tzinfo=UTC)
        results = extractor.extract_range(
            content_type=ContentType.DASHBOARD,
            offset=0,
            limit=100,
            updated_after=cutoff_date,
        )

        # Should only include the new dashboard
        assert len(results) == 1
        assert results[0]["id"] == "2"
        assert results[0]["title"] == "New Dashboard"

    def test_extract_range_unsupported_content_type(self):
        """Test extract_range raises error for unsupported content types."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        extractor = LookerContentExtractor(client=mock_client)

        # Non-paginated content types should raise ExtractionError (wrapping ValueError)
        with pytest.raises(
            ExtractionError,
            match="Failed to extract range for LOOKML_MODEL.*Content type LOOKML_MODEL does not support range extraction",
        ):
            extractor.extract_range(content_type=ContentType.LOOKML_MODEL, offset=0, limit=100)

        with pytest.raises(
            ExtractionError,
            match="Failed to extract range for FOLDER.*Content type FOLDER does not support range extraction",
        ):
            extractor.extract_range(content_type=ContentType.FOLDER, offset=0, limit=100)

        with pytest.raises(
            ExtractionError,
            match="Failed to extract range for BOARD.*Content type BOARD does not support range extraction",
        ):
            extractor.extract_range(content_type=ContentType.BOARD, offset=0, limit=100)

    def test_extract_range_api_error_handling(self):
        """Test extract_range handles API errors correctly."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Simulate API error
        mock_sdk.search_dashboards.side_effect = Exception("API connection timeout")

        extractor = LookerContentExtractor(client=mock_client)

        with pytest.raises(
            ExtractionError,
            match="Failed to extract range for DASHBOARD.*offset=0.*limit=100",
        ):
            extractor.extract_range(content_type=ContentType.DASHBOARD, offset=0, limit=100)

    def test_extract_range_none_results(self):
        """Test extract_range handles None API response."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        mock_sdk.search_dashboards.return_value = None

        extractor = LookerContentExtractor(client=mock_client)

        results = extractor.extract_range(content_type=ContentType.DASHBOARD, offset=0, limit=100)

        # Should return empty list for None results
        assert results == []

    def test_extract_range_different_offsets_and_limits(self):
        """Test extract_range with various offset/limit combinations."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        extractor = LookerContentExtractor(client=mock_client)

        # Test various offset/limit combinations
        test_cases = [
            (0, 10),
            (100, 50),
            (1000, 100),
            (5000, 25),
        ]

        for offset, limit in test_cases:
            mock_sdk.search_dashboards.return_value = [Mock(id=str(i)) for i in range(limit)]

            results = extractor.extract_range(
                content_type=ContentType.DASHBOARD, offset=offset, limit=limit
            )

            # Verify API call
            mock_sdk.search_dashboards.assert_called_with(fields=None, limit=limit, offset=offset)

            # Verify results
            assert len(results) == limit

    def test_extract_range_all_supported_content_types(self):
        """Test extract_range works for all supported paginated content types."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock returns for all supported types
        mock_sdk.search_dashboards.return_value = [Mock(id="1")]
        mock_sdk.search_looks.return_value = [Mock(id="2")]
        mock_sdk.all_users.return_value = [Mock(id="3")]
        mock_sdk.all_groups.return_value = [Mock(id="4")]
        mock_sdk.search_roles.return_value = [Mock(id="5")]

        extractor = LookerContentExtractor(client=mock_client)

        supported_types = [
            (ContentType.DASHBOARD, "search_dashboards"),
            (ContentType.LOOK, "search_looks"),
            (ContentType.USER, "all_users"),
            (ContentType.GROUP, "all_groups"),
            (ContentType.ROLE, "search_roles"),
        ]

        for content_type, api_method in supported_types:
            results = extractor.extract_range(content_type=content_type, offset=0, limit=100)

            # Verify correct API method was called
            getattr(mock_sdk, api_method).assert_called()

            # Verify results returned
            assert len(results) > 0

    def test_extract_range_preserves_sdk_object_structure(self):
        """Test extract_range properly converts SDK objects to dicts."""
        mock_client = Mock()
        mock_sdk = Mock()
        mock_client.sdk = mock_sdk

        # Mock dashboard with various fields
        mock_dashboard = Mock(
            id="123",
            title="Test Dashboard",
            description="Test description",
            user_id="456",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-12-01T00:00:00Z",
        )
        mock_sdk.search_dashboards.return_value = [mock_dashboard]

        extractor = LookerContentExtractor(client=mock_client)

        results = extractor.extract_range(content_type=ContentType.DASHBOARD, offset=0, limit=100)

        # Verify SDK object was converted to dict
        assert len(results) == 1
        result = results[0]
        assert isinstance(result, dict)
        assert result["id"] == "123"
        assert result["title"] == "Test Dashboard"
