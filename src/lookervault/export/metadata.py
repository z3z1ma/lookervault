"""Metadata models and management for YAML export/import.

This module defines metadata structures for export manifests and content tracking.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class ExportStrategy(str, Enum):
    """Export organization strategy."""

    FULL = "full"  # Content organized by type
    FOLDER = "folder"  # Dashboards/looks in folder hierarchy


@dataclass
class FolderInfo:
    """Folder metadata for hierarchy reconstruction."""

    id: str  # Looker folder ID
    name: str  # Folder display name
    parent_id: str | None  # Parent folder ID (None for root folders)
    path: str  # Sanitized filesystem path (e.g., "Sales/Regional/West")
    depth: int  # Nesting level (0 = root)
    child_count: int  # Number of direct children (folders + content)

    # Sanitization metadata
    original_name: str | None = None  # If name was sanitized, store original
    sanitized: bool = False  # True if path was modified for filesystem safety

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "path": self.path,
            "depth": self.depth,
            "child_count": self.child_count,
            "original_name": self.original_name,
            "sanitized": self.sanitized,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FolderInfo:
        """Create from dictionary loaded from JSON."""
        return cls(
            id=data["id"],
            name=data["name"],
            parent_id=data.get("parent_id"),
            path=data["path"],
            depth=data["depth"],
            child_count=data["child_count"],
            original_name=data.get("original_name"),
            sanitized=data.get("sanitized", False),
        )


@dataclass
class ExportMetadata:
    """Export manifest metadata stored in metadata.json."""

    # Required fields
    version: str  # Metadata format version (e.g., "1.0.0")
    export_timestamp: datetime  # When export was created
    strategy: ExportStrategy  # Export strategy used
    database_schema_version: int  # SQLite schema version (from schema.py)

    # Content summary
    content_type_counts: dict[str, int]  # ContentType.name → count
    total_items: int  # Total content items exported

    # Optional fields (strategy-dependent)
    folder_map: dict[str, FolderInfo] | None = None  # Only for folder strategy

    # Export configuration
    content_type_filter: list[str] | None = None  # If --content-types was used
    source_database: str | None = None  # Original database path

    # Checksum for integrity validation
    checksum: str | None = None  # SHA-256 of all YAML files combined

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data: dict[str, Any] = {
            "version": self.version,
            "export_timestamp": self.export_timestamp.isoformat(),
            "strategy": self.strategy.value,
            "database_schema_version": self.database_schema_version,
            "content_type_counts": self.content_type_counts,
            "total_items": self.total_items,
        }

        if self.folder_map is not None:
            data["folder_map"] = {
                folder_id: folder_info.to_dict()
                for folder_id, folder_info in self.folder_map.items()
            }

        if self.content_type_filter is not None:
            data["content_type_filter"] = self.content_type_filter

        if self.source_database is not None:
            data["source_database"] = self.source_database

        if self.checksum is not None:
            data["checksum"] = self.checksum

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExportMetadata:
        """Create from dictionary loaded from JSON."""
        folder_map = None
        if "folder_map" in data and data["folder_map"] is not None:
            folder_map = {
                folder_id: FolderInfo.from_dict(folder_data)
                for folder_id, folder_data in data["folder_map"].items()
            }

        return cls(
            version=data["version"],
            export_timestamp=datetime.fromisoformat(data["export_timestamp"]),
            strategy=ExportStrategy(data["strategy"]),
            database_schema_version=data["database_schema_version"],
            content_type_counts=data["content_type_counts"],
            total_items=data["total_items"],
            folder_map=folder_map,
            content_type_filter=data.get("content_type_filter"),
            source_database=data.get("source_database"),
            checksum=data.get("checksum"),
        )


@dataclass
class YamlContentMetadata:
    """Internal metadata embedded in YAML files (_metadata section)."""

    db_id: str  # Original database row ID
    content_type: str  # ContentType enum name
    exported_at: datetime  # Export timestamp
    content_size: int  # Original msgpack blob size
    checksum: str  # SHA-256 of original blob
    folder_path: str | None = None  # Only for folder strategy

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML embedding."""
        data = {
            "db_id": self.db_id,
            "content_type": self.content_type,
            "exported_at": self.exported_at.isoformat(),
            "content_size": self.content_size,
            "checksum": self.checksum,
        }

        if self.folder_path is not None:
            data["folder_path"] = self.folder_path

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> YamlContentMetadata:
        """Create from dictionary loaded from YAML."""
        return cls(
            db_id=data["db_id"],
            content_type=data["content_type"],
            exported_at=datetime.fromisoformat(data["exported_at"]),
            content_size=data["content_size"],
            checksum=data["checksum"],
            folder_path=data.get("folder_path"),
        )


class MetadataManager:
    """Manager for generating and loading export metadata."""

    METADATA_VERSION = "1.0.0"

    def generate_metadata(
        self,
        strategy: ExportStrategy,
        content_type_counts: dict[str, int],
        database_schema_version: int,
        source_database: Path | None = None,
        content_type_filter: list[str] | None = None,
        folder_map: dict[str, FolderInfo] | None = None,
        checksum: str | None = None,
    ) -> ExportMetadata:
        """Generate export metadata.

        Args:
            strategy: Export strategy used
            content_type_counts: Count of items per content type
            database_schema_version: SQLite schema version
            source_database: Path to source database (optional)
            content_type_filter: Content types filter if used (optional)
            folder_map: Folder hierarchy map for folder strategy (optional)
            checksum: SHA-256 checksum of all YAML files (optional)

        Returns:
            ExportMetadata instance ready for serialization
        """
        total_items = sum(content_type_counts.values())

        return ExportMetadata(
            version=self.METADATA_VERSION,
            export_timestamp=datetime.now(),
            strategy=strategy,
            database_schema_version=database_schema_version,
            content_type_counts=content_type_counts,
            total_items=total_items,
            folder_map=folder_map,
            content_type_filter=content_type_filter,
            source_database=str(source_database) if source_database else None,
            checksum=checksum,
        )

    def save_metadata(self, metadata: ExportMetadata, output_dir: Path) -> None:
        """Save metadata to metadata.json in output directory.

        Args:
            metadata: ExportMetadata instance to save
            output_dir: Directory where metadata.json will be written
        """
        metadata_file = output_dir / "metadata.json"
        with metadata_file.open("w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

    def load_metadata(self, export_dir: Path) -> ExportMetadata:
        """Load and parse metadata.json from export directory.

        Args:
            export_dir: Directory containing metadata.json

        Returns:
            ExportMetadata instance

        Raises:
            FileNotFoundError: If metadata.json doesn't exist
            ValueError: If metadata.json is invalid
        """
        metadata_file = export_dir / "metadata.json"

        if not metadata_file.exists():
            raise FileNotFoundError(
                f"metadata.json not found in {export_dir}. "
                "This directory may not be a valid export."
            )

        try:
            with metadata_file.open("r") as f:
                data = json.load(f)
            return ExportMetadata.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValueError(f"Invalid metadata.json: {e}") from e
