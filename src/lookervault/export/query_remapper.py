"""Query Remapping Infrastructure for YAML Export/Import.

This module provides utilities for tracking and deduplicating queries during
the Looker content import process, ensuring that identical queries are
not recreated and dashboard element references are correctly updated.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class QueryRemapEntry:
    """Single query remapping record."""

    original_query_id: str  # Old query ID from YAML
    new_query_id: str  # New query ID created in database
    query_hash: str  # SHA-256 hash of query definition
    dashboard_element_ids: list[str] = field(
        default_factory=list
    )  # Elements referencing this query
    created_at: datetime = field(default_factory=datetime.now)  # When new query was created


class QueryRemappingTable:
    """In-memory table for query ID remapping with hash-based deduplication."""

    def __init__(self):
        """Initialize query remapping data structures."""
        self.entries: dict[str, QueryRemapEntry] = {}  # query_hash → entry
        self.hash_index: dict[str, str] = {}  # query_hash → new_query_id
        self.modified_queries: set[str] = set()  # Set of modified query hashes
        self.created_queries: set[str] = set()  # Set of newly created query IDs

    def get_or_create(self, query_def: dict, original_id: str) -> str:
        """
        Get existing query ID or mark for creation based on query definition hash.

        Args:
            query_def (dict): The query definition to hash
            original_id (str): The original query ID from the YAML

        Returns:
            str: The new or existing query ID
        """
        query_hash = self._hash_query(query_def)

        # Check if query hash already exists in index
        if query_hash in self.hash_index:
            # Reuse existing query (shared query deduplication)
            existing_query_id = self.hash_index[query_hash]
            return existing_query_id

        # Generate a new query ID
        new_query_id = f"q_{datetime.now().timestamp()}"

        # Create new query remapping entry
        entry = QueryRemapEntry(
            original_query_id=original_id,
            new_query_id=new_query_id,
            query_hash=query_hash,
            dashboard_element_ids=[],  # Will be populated later
        )

        # Store in entries and hash index
        self.entries[query_hash] = entry
        self.hash_index[query_hash] = new_query_id

        # Track modifications and creations
        self.modified_queries.add(query_hash)
        self.created_queries.add(new_query_id)

        return new_query_id

    def _hash_query(self, query_def: dict) -> str:
        """
        Generate a SHA-256 hash of a normalized query definition.

        Args:
            query_def (dict): The query definition to hash

        Returns:
            str: SHA-256 hash of the normalized query
        """
        # Normalize query definition: sort keys, create canonical JSON representation
        normalized = json.dumps(
            {
                k: (sorted(v) if isinstance(v, list) else v)
                for k, v in sorted(query_def.items())
                # Exclude runtime/metadata fields from hash calculation
                if k not in {"id", "created_at", "updated_at", "user_id", "share_url"}
            },
            sort_keys=True,
            separators=(",", ":"),  # Compact representation
        )

        # Compute SHA-256 hash
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def record_element_reference(self, query_hash: str, dashboard_element_id: str) -> None:
        """
        Record a dashboard element that references a particular query.

        Args:
            query_hash (str): The hash of the query
            dashboard_element_id (str): The ID of the referencing dashboard element
        """
        if query_hash in self.entries:
            self.entries[query_hash].dashboard_element_ids.append(dashboard_element_id)

    def to_dict(self) -> dict:
        """
        Convert query remapping table to a dictionary representation.

        Returns:
            dict: A JSON-serializable representation of the query mappings
        """
        return {
            "query_remapping": {
                hash_key: {
                    "original_query_id": entry.original_query_id,
                    "new_query_id": entry.new_query_id,
                    "query_hash": entry.query_hash,
                    "dashboard_element_ids": entry.dashboard_element_ids,
                    "created_at": entry.created_at.isoformat(),
                }
                for hash_key, entry in self.entries.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QueryRemappingTable":
        """
        Reconstruct query remapping table from a dictionary.

        Args:
            data (dict): Dictionary representation of query remapping

        Returns:
            QueryRemappingTable: Reconstructed query remapping table
        """
        table = cls()
        for hash_key, entry_data in data.get("query_remapping", {}).items():
            entry = QueryRemapEntry(
                original_query_id=entry_data["original_query_id"],
                new_query_id=entry_data["new_query_id"],
                query_hash=entry_data["query_hash"],
                dashboard_element_ids=entry_data["dashboard_element_ids"],
                created_at=datetime.fromisoformat(entry_data["created_at"]),
            )
            table.entries[hash_key] = entry
            table.hash_index[hash_key] = entry_data["new_query_id"]
        return table
