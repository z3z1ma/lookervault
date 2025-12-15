"""Tests for metadata models and management."""

from datetime import datetime
from pathlib import Path

import pytest

from lookervault.export.metadata import (
    ExportMetadata,
    ExportStrategy,
    FolderInfo,
    MetadataManager,
    YamlContentMetadata,
)


class TestFolderInfo:
    """Test FolderInfo data model."""

    def test_create_folder_info(self):
        """Create FolderInfo instance."""
        folder = FolderInfo(
            id="123",
            name="Sales",
            parent_id=None,
            path="Sales",
            depth=0,
            child_count=5,
        )

        assert folder.id == "123"
        assert folder.name == "Sales"
        assert folder.parent_id is None
        assert folder.path == "Sales"
        assert folder.depth == 0
        assert folder.child_count == 5

    def test_folder_info_to_dict(self):
        """Serialize FolderInfo to dict."""
        folder = FolderInfo(
            id="123",
            name="Sales",
            parent_id="100",
            path="Parent/Sales",
            depth=1,
            child_count=3,
            original_name="Sales: Q1",
            sanitized=True,
        )

        result = folder.to_dict()

        assert result["id"] == "123"
        assert result["name"] == "Sales"
        assert result["parent_id"] == "100"
        assert result["path"] == "Parent/Sales"
        assert result["depth"] == 1
        assert result["child_count"] == 3
        assert result["original_name"] == "Sales: Q1"
        assert result["sanitized"] is True

    def test_folder_info_from_dict(self):
        """Deserialize FolderInfo from dict."""
        data = {
            "id": "123",
            "name": "Sales",
            "parent_id": "100",
            "path": "Parent/Sales",
            "depth": 1,
            "child_count": 3,
            "original_name": "Sales: Q1",
            "sanitized": True,
        }

        folder = FolderInfo.from_dict(data)

        assert folder.id == "123"
        assert folder.name == "Sales"
        assert folder.parent_id == "100"
        assert folder.sanitized is True

    def test_folder_info_round_trip(self):
        """Round-trip FolderInfo serialization."""
        original = FolderInfo(
            id="456",
            name="Marketing",
            parent_id=None,
            path="Marketing",
            depth=0,
            child_count=10,
        )

        data = original.to_dict()
        restored = FolderInfo.from_dict(data)

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.parent_id == original.parent_id
        assert restored.depth == original.depth


class TestExportMetadata:
    """Test ExportMetadata data model."""

    def test_create_export_metadata(self):
        """Create ExportMetadata instance."""
        metadata = ExportMetadata(
            version="1.0.0",
            export_timestamp=datetime.now(),
            strategy=ExportStrategy.FULL,
            database_schema_version=2,
            content_type_counts={"DASHBOARD": 100, "LOOK": 50},
            total_items=150,
        )

        assert metadata.version == "1.0.0"
        assert metadata.strategy == ExportStrategy.FULL
        assert metadata.total_items == 150

    def test_export_metadata_to_dict(self):
        """Serialize ExportMetadata to dict."""
        timestamp = datetime.now()
        metadata = ExportMetadata(
            version="1.0.0",
            export_timestamp=timestamp,
            strategy=ExportStrategy.FULL,
            database_schema_version=2,
            content_type_counts={"DASHBOARD": 100},
            total_items=100,
            source_database="/path/to/db.sqlite",
            checksum="sha256:abc123",
        )

        result = metadata.to_dict()

        assert result["version"] == "1.0.0"
        assert result["strategy"] == "full"
        assert result["database_schema_version"] == 2
        assert result["total_items"] == 100
        assert result["source_database"] == "/path/to/db.sqlite"
        assert result["checksum"] == "sha256:abc123"

    def test_export_metadata_from_dict(self):
        """Deserialize ExportMetadata from dict."""
        data = {
            "version": "1.0.0",
            "export_timestamp": "2025-12-14T10:00:00",
            "strategy": "full",
            "database_schema_version": 2,
            "content_type_counts": {"DASHBOARD": 100},
            "total_items": 100,
        }

        metadata = ExportMetadata.from_dict(data)

        assert metadata.version == "1.0.0"
        assert metadata.strategy == ExportStrategy.FULL
        assert metadata.total_items == 100

    def test_export_metadata_with_folder_map(self):
        """ExportMetadata with folder_map."""
        folder = FolderInfo(
            id="123", name="Sales", parent_id=None, path="Sales", depth=0, child_count=5
        )

        metadata = ExportMetadata(
            version="1.0.0",
            export_timestamp=datetime.now(),
            strategy=ExportStrategy.FOLDER,
            database_schema_version=2,
            content_type_counts={"DASHBOARD": 100},
            total_items=100,
            folder_map={"123": folder},
        )

        result = metadata.to_dict()

        assert "folder_map" in result
        assert "123" in result["folder_map"]
        assert result["folder_map"]["123"]["name"] == "Sales"

    def test_export_metadata_round_trip(self):
        """Round-trip ExportMetadata serialization."""
        original = ExportMetadata(
            version="1.0.0",
            export_timestamp=datetime(2025, 12, 14, 10, 0, 0),
            strategy=ExportStrategy.FULL,
            database_schema_version=2,
            content_type_counts={"DASHBOARD": 100, "LOOK": 50},
            total_items=150,
        )

        data = original.to_dict()
        restored = ExportMetadata.from_dict(data)

        assert restored.version == original.version
        assert restored.strategy == original.strategy
        assert restored.total_items == original.total_items


class TestYamlContentMetadata:
    """Test YamlContentMetadata data model."""

    def test_create_yaml_content_metadata(self):
        """Create YamlContentMetadata instance."""
        metadata = YamlContentMetadata(
            db_id="123",
            content_type="DASHBOARD",
            exported_at=datetime.now(),
            content_size=1024,
            checksum="sha256:abc123",
        )

        assert metadata.db_id == "123"
        assert metadata.content_type == "DASHBOARD"
        assert metadata.content_size == 1024

    def test_yaml_content_metadata_to_dict(self):
        """Serialize YamlContentMetadata to dict."""
        timestamp = datetime.now()
        metadata = YamlContentMetadata(
            db_id="123",
            content_type="DASHBOARD",
            exported_at=timestamp,
            content_size=1024,
            checksum="sha256:abc123",
            folder_path="Sales/Regional",
        )

        result = metadata.to_dict()

        assert result["db_id"] == "123"
        assert result["content_type"] == "DASHBOARD"
        assert result["content_size"] == 1024
        assert result["checksum"] == "sha256:abc123"
        assert result["folder_path"] == "Sales/Regional"

    def test_yaml_content_metadata_from_dict(self):
        """Deserialize YamlContentMetadata from dict."""
        data = {
            "db_id": "123",
            "content_type": "DASHBOARD",
            "exported_at": "2025-12-14T10:00:00",
            "content_size": 1024,
            "checksum": "sha256:abc123",
        }

        metadata = YamlContentMetadata.from_dict(data)

        assert metadata.db_id == "123"
        assert metadata.content_type == "DASHBOARD"
        assert metadata.content_size == 1024

    def test_yaml_content_metadata_round_trip(self):
        """Round-trip YamlContentMetadata serialization."""
        original = YamlContentMetadata(
            db_id="456",
            content_type="LOOK",
            exported_at=datetime(2025, 12, 14, 10, 0, 0),
            content_size=512,
            checksum="sha256:def456",
        )

        data = original.to_dict()
        restored = YamlContentMetadata.from_dict(data)

        assert restored.db_id == original.db_id
        assert restored.content_type == original.content_type
        assert restored.content_size == original.content_size


class TestMetadataManager:
    """Test MetadataManager."""

    def test_generate_metadata_full_strategy(self):
        """Generate metadata for full strategy."""
        manager = MetadataManager()
        metadata = manager.generate_metadata(
            strategy=ExportStrategy.FULL,
            content_type_counts={"DASHBOARD": 100, "LOOK": 50},
            database_schema_version=2,
            source_database=Path("/path/to/db.sqlite"),
            checksum="sha256:abc123",
        )

        assert metadata.strategy == ExportStrategy.FULL
        assert metadata.total_items == 150
        assert metadata.content_type_counts["DASHBOARD"] == 100
        assert metadata.source_database == "/path/to/db.sqlite"

    def test_generate_metadata_folder_strategy(self):
        """Generate metadata for folder strategy."""
        manager = MetadataManager()
        folder = FolderInfo(
            id="123", name="Sales", parent_id=None, path="Sales", depth=0, child_count=5
        )

        metadata = manager.generate_metadata(
            strategy=ExportStrategy.FOLDER,
            content_type_counts={"DASHBOARD": 100},
            database_schema_version=2,
            folder_map={"123": folder},
        )

        assert metadata.strategy == ExportStrategy.FOLDER
        assert metadata.folder_map is not None
        assert "123" in metadata.folder_map

    def test_save_metadata(self, tmp_path):
        """Save metadata to file."""
        manager = MetadataManager()
        metadata = ExportMetadata(
            version="1.0.0",
            export_timestamp=datetime.now(),
            strategy=ExportStrategy.FULL,
            database_schema_version=2,
            content_type_counts={"DASHBOARD": 100},
            total_items=100,
        )

        manager.save_metadata(metadata, tmp_path)

        metadata_file = tmp_path / "metadata.json"
        assert metadata_file.exists()

    def test_load_metadata(self, tmp_path):
        """Load metadata from file."""
        manager = MetadataManager()

        # Create metadata file
        original = ExportMetadata(
            version="1.0.0",
            export_timestamp=datetime.now(),
            strategy=ExportStrategy.FULL,
            database_schema_version=2,
            content_type_counts={"DASHBOARD": 100},
            total_items=100,
        )
        manager.save_metadata(original, tmp_path)

        # Load it back
        loaded = manager.load_metadata(tmp_path)

        assert loaded.version == original.version
        assert loaded.strategy == original.strategy
        assert loaded.total_items == original.total_items

    def test_load_metadata_missing_file_raises_error(self, tmp_path):
        """Load metadata from missing file raises error."""
        manager = MetadataManager()

        with pytest.raises(FileNotFoundError, match="metadata.json not found"):
            manager.load_metadata(tmp_path)

    def test_load_metadata_invalid_json_raises_error(self, tmp_path):
        """Load invalid metadata file raises error."""
        manager = MetadataManager()
        metadata_file = tmp_path / "metadata.json"
        metadata_file.write_text("not valid json")

        with pytest.raises(ValueError, match="Invalid metadata.json"):
            manager.load_metadata(tmp_path)

    def test_save_load_round_trip(self, tmp_path):
        """Save and load metadata round-trip."""
        manager = MetadataManager()

        original = manager.generate_metadata(
            strategy=ExportStrategy.FULL,
            content_type_counts={"DASHBOARD": 100, "LOOK": 50},
            database_schema_version=2,
            source_database=Path("/path/to/db.sqlite"),
            checksum="sha256:abc123",
        )

        manager.save_metadata(original, tmp_path)
        loaded = manager.load_metadata(tmp_path)

        assert loaded.version == original.version
        assert loaded.strategy == original.strategy
        assert loaded.total_items == original.total_items
        assert loaded.checksum == original.checksum


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_export_metadata_with_empty_counts(self):
        """ExportMetadata with empty content_type_counts."""
        metadata = ExportMetadata(
            version="1.0.0",
            export_timestamp=datetime.now(),
            strategy=ExportStrategy.FULL,
            database_schema_version=2,
            content_type_counts={},
            total_items=0,
        )

        assert metadata.total_items == 0

    def test_export_metadata_with_content_type_filter(self):
        """ExportMetadata with content_type_filter."""
        metadata = ExportMetadata(
            version="1.0.0",
            export_timestamp=datetime.now(),
            strategy=ExportStrategy.FULL,
            database_schema_version=2,
            content_type_counts={"DASHBOARD": 100},
            total_items=100,
            content_type_filter=["DASHBOARD"],
        )

        result = metadata.to_dict()
        assert "content_type_filter" in result
        assert result["content_type_filter"] == ["DASHBOARD"]

    def test_folder_info_without_sanitization(self):
        """FolderInfo without sanitization."""
        folder = FolderInfo(
            id="123", name="Sales", parent_id=None, path="Sales", depth=0, child_count=5
        )

        result = folder.to_dict()
        assert result["sanitized"] is False
        assert result["original_name"] is None

    def test_yaml_content_metadata_without_folder_path(self):
        """YamlContentMetadata without folder_path."""
        metadata = YamlContentMetadata(
            db_id="123",
            content_type="DASHBOARD",
            exported_at=datetime.now(),
            content_size=1024,
            checksum="sha256:abc123",
        )

        result = metadata.to_dict()
        assert "folder_path" not in result or result.get("folder_path") is None

    def test_metadata_manager_version_constant(self):
        """MetadataManager has version constant."""
        manager = MetadataManager()
        assert hasattr(manager, "METADATA_VERSION")
        assert manager.METADATA_VERSION == "1.0.0"

    def test_generate_metadata_calculates_total_items(self):
        """generate_metadata calculates total_items from counts."""
        manager = MetadataManager()
        metadata = manager.generate_metadata(
            strategy=ExportStrategy.FULL,
            content_type_counts={"DASHBOARD": 100, "LOOK": 50, "USER": 25},
            database_schema_version=2,
        )

        assert metadata.total_items == 175
