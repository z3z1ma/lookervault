"""Tests for QueryRemappingTable."""

from datetime import datetime

import pytest

from lookervault.export.query_remapper import QueryRemapEntry, QueryRemappingTable


class TestQueryRemappingTable:
    """Test QueryRemappingTable."""

    def test_create_empty_table(self):
        """Create empty query remapping table."""
        table = QueryRemappingTable()

        assert len(table.entries) == 0
        assert len(table.hash_index) == 0
        assert len(table.modified_queries) == 0
        assert len(table.created_queries) == 0

    def test_get_or_create_first_query(self):
        """First query creates new entry."""
        table = QueryRemappingTable()
        query_def = {"model": "sales", "view": "orders", "fields": ["orders.count"]}

        new_id = table.get_or_create(query_def, "original_123")

        assert new_id is not None
        assert new_id != "original_123"
        assert new_id in table.created_queries
        assert len(table.entries) == 1

    def test_get_or_create_same_query_returns_existing(self):
        """Same query definition returns existing ID."""
        table = QueryRemappingTable()
        query_def = {"model": "sales", "view": "orders", "fields": ["orders.count"]}

        id1 = table.get_or_create(query_def, "original_1")
        id2 = table.get_or_create(query_def, "original_2")

        # Should return same ID for identical queries
        assert id1 == id2
        assert len(table.entries) == 1
        assert len(table.created_queries) == 1

    def test_get_or_create_different_query_creates_new(self):
        """Different query definition creates new entry."""
        table = QueryRemappingTable()
        query1 = {"model": "sales", "view": "orders", "fields": ["orders.count"]}
        query2 = {"model": "sales", "view": "customers", "fields": ["customers.count"]}

        id1 = table.get_or_create(query1, "original_1")
        id2 = table.get_or_create(query2, "original_2")

        assert id1 != id2
        assert len(table.entries) == 2
        assert len(table.created_queries) == 2

    def test_hash_query_ignores_metadata_fields(self):
        """Query hash ignores metadata fields."""
        table = QueryRemappingTable()
        query1 = {
            "model": "sales",
            "view": "orders",
            "fields": ["orders.count"],
            "id": "old_id",
            "created_at": "2025-01-01",
        }
        query2 = {
            "model": "sales",
            "view": "orders",
            "fields": ["orders.count"],
            "id": "different_id",
            "created_at": "2025-12-14",
        }

        id1 = table.get_or_create(query1, "original_1")
        id2 = table.get_or_create(query2, "original_2")

        # Should be same hash despite different metadata
        assert id1 == id2

    def test_hash_query_normalizes_list_order(self):
        """Query hash normalizes list order."""
        table = QueryRemappingTable()
        query1 = {"model": "sales", "view": "orders", "fields": ["count", "total"]}
        query2 = {"model": "sales", "view": "orders", "fields": ["total", "count"]}

        hash1 = table._hash_query(query1)
        hash2 = table._hash_query(query2)

        # Should be same hash (lists are sorted)
        assert hash1 == hash2

    def test_record_element_reference(self):
        """Record dashboard element reference to query."""
        table = QueryRemappingTable()
        query_def = {"model": "sales", "view": "orders", "fields": ["orders.count"]}

        new_id = table.get_or_create(query_def, "original_123")
        query_hash = table._hash_query(query_def)
        table.record_element_reference(query_hash, "element_1")

        entry = table.entries[query_hash]
        assert "element_1" in entry.dashboard_element_ids

    def test_record_multiple_element_references(self):
        """Record multiple element references to same query."""
        table = QueryRemappingTable()
        query_def = {"model": "sales", "view": "orders", "fields": ["orders.count"]}

        new_id = table.get_or_create(query_def, "original_123")
        query_hash = table._hash_query(query_def)
        table.record_element_reference(query_hash, "element_1")
        table.record_element_reference(query_hash, "element_2")

        entry = table.entries[query_hash]
        assert len(entry.dashboard_element_ids) == 2
        assert "element_1" in entry.dashboard_element_ids
        assert "element_2" in entry.dashboard_element_ids


class TestToDict:
    """Test to_dict serialization."""

    def test_empty_table_to_dict(self):
        """Serialize empty table."""
        table = QueryRemappingTable()
        result = table.to_dict()

        assert "query_remapping" in result
        assert len(result["query_remapping"]) == 0

    def test_single_entry_to_dict(self):
        """Serialize table with single entry."""
        table = QueryRemappingTable()
        query_def = {"model": "sales", "view": "orders", "fields": ["orders.count"]}
        new_id = table.get_or_create(query_def, "original_123")

        result = table.to_dict()

        assert len(result["query_remapping"]) == 1
        # Get first entry
        entry_data = list(result["query_remapping"].values())[0]
        assert entry_data["original_query_id"] == "original_123"
        assert entry_data["new_query_id"] == new_id

    def test_to_dict_contains_all_fields(self):
        """Serialized entry contains all required fields."""
        table = QueryRemappingTable()
        query_def = {"model": "sales", "view": "orders", "fields": ["orders.count"]}
        new_id = table.get_or_create(query_def, "original_123")
        query_hash = table._hash_query(query_def)
        table.record_element_reference(query_hash, "element_1")

        result = table.to_dict()
        entry_data = list(result["query_remapping"].values())[0]

        assert "original_query_id" in entry_data
        assert "new_query_id" in entry_data
        assert "query_hash" in entry_data
        assert "dashboard_element_ids" in entry_data
        assert "created_at" in entry_data

    def test_to_dict_preserves_element_references(self):
        """Element references are preserved in serialization."""
        table = QueryRemappingTable()
        query_def = {"model": "sales", "view": "orders", "fields": ["orders.count"]}
        new_id = table.get_or_create(query_def, "original_123")
        query_hash = table._hash_query(query_def)
        table.record_element_reference(query_hash, "element_1")
        table.record_element_reference(query_hash, "element_2")

        result = table.to_dict()
        entry_data = list(result["query_remapping"].values())[0]

        assert len(entry_data["dashboard_element_ids"]) == 2
        assert "element_1" in entry_data["dashboard_element_ids"]
        assert "element_2" in entry_data["dashboard_element_ids"]


class TestFromDict:
    """Test from_dict deserialization."""

    def test_from_dict_empty_table(self):
        """Deserialize empty table."""
        data = {"query_remapping": {}}
        table = QueryRemappingTable.from_dict(data)

        assert len(table.entries) == 0
        assert len(table.hash_index) == 0

    def test_from_dict_single_entry(self):
        """Deserialize table with single entry."""
        data = {
            "query_remapping": {
                "hash_123": {
                    "original_query_id": "original_123",
                    "new_query_id": "new_456",
                    "query_hash": "hash_123",
                    "dashboard_element_ids": ["element_1"],
                    "created_at": "2025-12-14T10:00:00",
                }
            }
        }

        table = QueryRemappingTable.from_dict(data)

        assert len(table.entries) == 1
        assert "hash_123" in table.entries
        assert table.entries["hash_123"].original_query_id == "original_123"
        assert table.entries["hash_123"].new_query_id == "new_456"

    def test_from_dict_multiple_entries(self):
        """Deserialize table with multiple entries."""
        data = {
            "query_remapping": {
                "hash_1": {
                    "original_query_id": "orig_1",
                    "new_query_id": "new_1",
                    "query_hash": "hash_1",
                    "dashboard_element_ids": [],
                    "created_at": "2025-12-14T10:00:00",
                },
                "hash_2": {
                    "original_query_id": "orig_2",
                    "new_query_id": "new_2",
                    "query_hash": "hash_2",
                    "dashboard_element_ids": ["elem_1"],
                    "created_at": "2025-12-14T10:01:00",
                },
            }
        }

        table = QueryRemappingTable.from_dict(data)

        assert len(table.entries) == 2
        assert len(table.hash_index) == 2

    def test_from_dict_preserves_element_references(self):
        """Element references are preserved in deserialization."""
        data = {
            "query_remapping": {
                "hash_123": {
                    "original_query_id": "original_123",
                    "new_query_id": "new_456",
                    "query_hash": "hash_123",
                    "dashboard_element_ids": ["element_1", "element_2"],
                    "created_at": "2025-12-14T10:00:00",
                }
            }
        }

        table = QueryRemappingTable.from_dict(data)
        entry = table.entries["hash_123"]

        assert len(entry.dashboard_element_ids) == 2
        assert "element_1" in entry.dashboard_element_ids
        assert "element_2" in entry.dashboard_element_ids


class TestRoundTrip:
    """Test round-trip serialization/deserialization."""

    def test_round_trip_preserves_data(self):
        """Round-trip preserves all data."""
        # Create original table
        original = QueryRemappingTable()
        query1 = {"model": "sales", "view": "orders", "fields": ["orders.count"]}
        query2 = {"model": "sales", "view": "customers", "fields": ["customers.count"]}

        id1 = original.get_or_create(query1, "orig_1")
        id2 = original.get_or_create(query2, "orig_2")

        hash1 = original._hash_query(query1)
        hash2 = original._hash_query(query2)

        original.record_element_reference(hash1, "elem_1")
        original.record_element_reference(hash2, "elem_2")

        # Serialize and deserialize
        data = original.to_dict()
        restored = QueryRemappingTable.from_dict(data)

        # Verify data is preserved
        assert len(restored.entries) == len(original.entries)
        assert len(restored.hash_index) == len(original.hash_index)

        # Check specific entries
        assert restored.entries[hash1].original_query_id == "orig_1"
        assert restored.entries[hash2].original_query_id == "orig_2"
        assert restored.hash_index[hash1] == id1
        assert restored.hash_index[hash2] == id2


class TestQueryDeduplication:
    """Test query deduplication scenarios."""

    def test_deduplicate_identical_queries(self):
        """Identical queries are deduplicated."""
        table = QueryRemappingTable()
        query = {"model": "sales", "view": "orders", "fields": ["orders.count"]}

        # Create same query 3 times
        id1 = table.get_or_create(query, "orig_1")
        id2 = table.get_or_create(query, "orig_2")
        id3 = table.get_or_create(query, "orig_3")

        # All should map to same ID
        assert id1 == id2 == id3
        assert len(table.entries) == 1
        assert len(table.created_queries) == 1

    def test_deduplicate_queries_different_order(self):
        """Queries with different field order are deduplicated."""
        table = QueryRemappingTable()
        query1 = {
            "model": "sales",
            "view": "orders",
            "fields": ["orders.count", "orders.total"],
        }
        query2 = {
            "model": "sales",
            "view": "orders",
            "fields": ["orders.total", "orders.count"],
        }

        id1 = table.get_or_create(query1, "orig_1")
        id2 = table.get_or_create(query2, "orig_2")

        # Should deduplicate despite different order
        assert id1 == id2
        assert len(table.entries) == 1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_query_with_empty_fields(self):
        """Query with empty fields list."""
        table = QueryRemappingTable()
        query = {"model": "sales", "view": "orders", "fields": []}

        new_id = table.get_or_create(query, "original_123")

        assert new_id is not None
        assert len(table.entries) == 1

    def test_query_with_nested_structures(self):
        """Query with nested structures."""
        table = QueryRemappingTable()
        query = {
            "model": "sales",
            "view": "orders",
            "fields": ["orders.count"],
            "filters": {"date": "2025-01-01", "region": "US"},
        }

        new_id = table.get_or_create(query, "original_123")

        assert new_id is not None

    def test_query_hash_stability(self):
        """Query hash is stable across multiple calls."""
        table = QueryRemappingTable()
        query = {"model": "sales", "view": "orders", "fields": ["orders.count"]}

        hash1 = table._hash_query(query)
        hash2 = table._hash_query(query)

        assert hash1 == hash2

    def test_record_element_reference_nonexistent_hash(self):
        """Recording element reference for nonexistent hash is a no-op."""
        table = QueryRemappingTable()

        # This should not raise an error
        table.record_element_reference("nonexistent_hash", "element_1")

    def test_from_dict_missing_query_remapping_key(self):
        """from_dict with missing query_remapping key."""
        data = {}  # Missing 'query_remapping'
        table = QueryRemappingTable.from_dict(data)

        assert len(table.entries) == 0
