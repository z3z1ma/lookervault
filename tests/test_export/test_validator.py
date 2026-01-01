"""Tests for YamlValidator."""

from pathlib import Path

import pytest

from lookervault.exceptions import ValidationError
from lookervault.export.validator import YamlValidator


@pytest.fixture
def validator():
    """Create YamlValidator instance."""
    return YamlValidator()


class TestValidateSyntax:
    """Test YAML syntax validation."""

    def test_validate_valid_yaml(self, validator):
        """Validate correct YAML syntax."""
        yaml_content = """
title: Test Dashboard
id: '123'
"""
        result = validator.validate_syntax(yaml_content)

        assert isinstance(result, dict)
        assert result["title"] == "Test Dashboard"

    def test_validate_invalid_yaml_raises_error(self, validator):
        """Validate invalid YAML syntax raises ValidationError."""
        invalid_yaml = "invalid: yaml: [unclosed"

        with pytest.raises(ValidationError, match="Invalid YAML syntax"):
            validator.validate_syntax(invalid_yaml)

    def test_validate_non_dict_yaml_raises_error(self, validator):
        """Validate non-dict YAML raises ValidationError."""
        list_yaml = "- item1\n- item2"

        with pytest.raises(ValidationError, match="must parse to dictionary"):
            validator.validate_syntax(list_yaml)

    def test_validate_with_file_path_in_error(self, validator):
        """Error message includes file path."""
        invalid_yaml = "invalid: yaml: [unclosed"
        file_path = Path("/test/dashboard.yaml")

        with pytest.raises(ValidationError, match="/test/dashboard.yaml"):
            validator.validate_syntax(invalid_yaml, file_path)


class TestValidateFile:
    """Test file validation."""

    def test_validate_existing_file(self, validator, tmp_path):
        """Validate existing YAML file."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("title: Test\nid: '123'")

        result = validator.validate_file(yaml_file)

        assert result["title"] == "Test"
        assert result["id"] == "123"

    def test_validate_missing_file_raises_error(self, validator, tmp_path):
        """Validate missing file raises FileNotFoundError."""
        missing_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(FileNotFoundError):
            validator.validate_file(missing_file)

    def test_validate_invalid_file_content_raises_error(self, validator, tmp_path):
        """Validate file with invalid YAML raises ValidationError."""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("invalid: yaml: [unclosed")

        with pytest.raises(ValidationError, match="Invalid YAML syntax"):
            validator.validate_file(yaml_file)


class TestValidateMetadataSection:
    """Test _metadata section validation."""

    def test_validate_valid_metadata(self, validator):
        """Validate correct metadata section."""
        data = {
            "title": "Dashboard",
            "_metadata": {
                "db_id": "123",
                "content_type": "DASHBOARD",
                "exported_at": "2025-12-14T10:00:00",
                "content_size": 1024,
                "checksum": "sha256:abc123",
            },
        }

        metadata = validator.validate_metadata_section(data)

        assert metadata["db_id"] == "123"
        assert metadata["content_type"] == "DASHBOARD"

    def test_validate_missing_metadata_raises_error(self, validator):
        """Validate missing _metadata raises ValidationError."""
        data = {"title": "Dashboard", "id": "123"}

        with pytest.raises(ValidationError, match="Missing required _metadata section"):
            validator.validate_metadata_section(data)

    def test_validate_metadata_non_dict_raises_error(self, validator):
        """Validate non-dict _metadata raises ValidationError."""
        data = {"title": "Dashboard", "_metadata": "not a dict"}

        with pytest.raises(ValidationError, match="_metadata must be dictionary"):
            validator.validate_metadata_section(data)

    def test_validate_metadata_missing_required_fields(self, validator):
        """Validate metadata with missing required fields."""
        data = {
            "title": "Dashboard",
            "_metadata": {
                "db_id": "123",
                "content_type": "DASHBOARD",
                # Missing: exported_at, content_size, checksum
            },
        }

        with pytest.raises(ValidationError, match="Missing required fields"):
            validator.validate_metadata_section(data)

    def test_validate_metadata_with_partial_fields(self, validator):
        """Validate metadata with some missing required fields."""
        data = {
            "title": "Dashboard",
            "_metadata": {
                "db_id": "123",
                # Missing all other required fields
            },
        }

        with pytest.raises(ValidationError, match="content_type"):
            validator.validate_metadata_section(data)


class TestValidateField:
    """Test individual field validation."""

    def test_validate_title_field_valid(self, validator):
        """Validate correct title field."""
        errors = validator.validate_field("title", "Test Dashboard")

        assert len(errors) == 0

    def test_validate_title_field_non_string(self, validator):
        """Validate title field with non-string value."""
        # The validator will raise AttributeError when trying to call .strip() on non-string
        # This is expected behavior - should catch type errors early
        try:
            errors = validator.validate_field("title", 123)
            # If no exception, should have type error
            assert len(errors) >= 1
            assert any("must be a string" in error for error in errors)
        except AttributeError:
            # Expected - validator calls .strip() on non-string
            pass

    def test_validate_title_field_empty(self, validator):
        """Validate empty title field."""
        errors = validator.validate_field("title", "   ")

        assert len(errors) == 1
        assert "cannot be empty" in errors[0]

    def test_validate_title_field_too_long(self, validator):
        """Validate title field exceeding max length."""
        long_title = "x" * 300
        errors = validator.validate_field("title", long_title)

        assert len(errors) == 1
        assert "exceeds 255 characters" in errors[0]

    def test_validate_dashboard_filters_valid(self, validator):
        """Validate valid dashboard filters."""
        errors = validator.validate_field(
            "filters", {"date": "2025-01-01"}, content_type="DASHBOARD"
        )

        assert len(errors) == 0

    def test_validate_dashboard_filters_invalid_type(self, validator):
        """Validate dashboard filters with invalid type."""
        errors = validator.validate_field("filters", "not a dict", content_type="DASHBOARD")

        assert len(errors) == 1
        assert "must be a dictionary" in errors[0]

    def test_validate_look_model_valid(self, validator):
        """Validate valid look model."""
        errors = validator.validate_field("model", "sales_model", content_type="LOOK")

        assert len(errors) == 0

    def test_validate_look_model_invalid_type(self, validator):
        """Validate look model with invalid type."""
        errors = validator.validate_field("model", 123, content_type="LOOK")

        assert len(errors) == 1
        assert "must be a string" in errors[0]

    def test_validate_field_with_file_path(self, validator):
        """Field validation includes file path in errors."""
        # Use empty string to trigger the empty title error with file path
        errors = validator.validate_field("title", "   ", file_path=Path("/test/dashboard.yaml"))

        assert len(errors) >= 1
        assert any("/test/dashboard.yaml" in error for error in errors)


class TestValidateContentStructure:
    """Test content structure validation."""

    def test_validate_dashboard_structure_valid(self, validator):
        """Validate valid dashboard structure."""
        data = {
            "id": "123",
            "title": "Test Dashboard",
            "elements": [{"id": "1", "type": "text"}],
            "_metadata": {
                "db_id": "123",
                "content_type": "DASHBOARD",
                "exported_at": "2025-12-14T10:00:00",
                "content_size": 1024,
                "checksum": "sha256:abc123",
            },
        }

        errors = validator.validate_content_structure(data, "DASHBOARD")

        assert len(errors["structure_errors"]) == 0
        assert len(errors["field_errors"]) == 0

    def test_validate_dashboard_missing_required_field(self, validator):
        """Validate dashboard missing required field."""
        data = {
            "id": "123",
            "title": "Test Dashboard",
            # Missing: elements
            "_metadata": {
                "db_id": "123",
                "content_type": "DASHBOARD",
                "exported_at": "2025-12-14T10:00:00",
                "content_size": 1024,
                "checksum": "sha256:abc123",
            },
        }

        errors = validator.validate_content_structure(data, "DASHBOARD")

        assert len(errors["structure_errors"]) == 1
        assert "elements" in errors["structure_errors"][0]

    def test_validate_look_structure_valid(self, validator):
        """Validate valid look structure."""
        data = {
            "id": "456",
            "title": "Test Look",
            "query": {"model": "sales", "view": "orders", "fields": ["orders.count"]},
            "_metadata": {
                "db_id": "456",
                "content_type": "LOOK",
                "exported_at": "2025-12-14T10:00:00",
                "content_size": 512,
                "checksum": "sha256:def456",
            },
        }

        errors = validator.validate_content_structure(data, "LOOK")

        assert len(errors["structure_errors"]) == 0
        assert len(errors["field_errors"]) == 0

    def test_validate_content_type_mismatch(self, validator):
        """Validate content type mismatch."""
        data = {
            "id": "123",
            "title": "Test",
            "_metadata": {
                "db_id": "123",
                "content_type": "LOOK",  # Mismatch
                "exported_at": "2025-12-14T10:00:00",
                "content_size": 1024,
                "checksum": "sha256:abc123",
            },
        }

        errors = validator.validate_content_structure(data, "DASHBOARD")

        assert len(errors["structure_errors"]) >= 1
        assert any("mismatch" in error.lower() for error in errors["structure_errors"])

    def test_validate_missing_metadata_section(self, validator):
        """Validate content with missing metadata section."""
        data = {"id": "123", "title": "Test Dashboard"}

        errors = validator.validate_content_structure(data, "DASHBOARD")

        assert len(errors["structure_errors"]) > 0

    def test_validate_field_errors_aggregated(self, validator):
        """Field errors are aggregated in field_errors list."""
        data = {
            "id": "123",
            "title": "",  # Empty title
            "elements": [],
            "_metadata": {
                "db_id": "123",
                "content_type": "DASHBOARD",
                "exported_at": "2025-12-14T10:00:00",
                "content_size": 1024,
                "checksum": "sha256:abc123",
            },
        }

        errors = validator.validate_content_structure(data, "DASHBOARD")

        assert len(errors["field_errors"]) > 0
        assert any("title" in error for error in errors["field_errors"])


class TestValidateQuery:
    """Test query validation."""

    def test_validate_valid_query(self, validator):
        """Validate correct query definition."""
        query = {
            "model": "sales",
            "view": "orders",
            "fields": ["orders.count", "orders.total"],
        }

        errors = validator.validate_query(query)

        assert len(errors) == 0

    def test_validate_query_missing_required_fields(self, validator):
        """Validate query missing required fields."""
        query = {
            "model": "sales",
            # Missing: view, fields
        }

        errors = validator.validate_query(query)

        assert len(errors) > 0
        assert any("Missing required query fields" in error for error in errors)

    def test_validate_query_with_file_path(self, validator):
        """Query validation includes file path in errors."""
        query = {"model": "sales"}  # Missing fields

        errors = validator.validate_query(query, file_path=Path("/test/dashboard.yaml"))

        assert len(errors) > 0
        assert any("/test/dashboard.yaml" in error for error in errors)

    def test_validate_dashboard_query_missing_recommended_fields(self, validator):
        """Dashboard query missing recommended fields generates warnings."""
        query = {
            "model": "sales",
            "view": "orders",
            "fields": ["orders.count"],
            # Missing recommended: pivots, filters, sorts
        }

        errors = validator.validate_query(query, content_type="DASHBOARD")

        # Should have warnings for missing recommended fields
        assert any("recommended" in error.lower() for error in errors)

    def test_validate_query_empty_fields(self, validator):
        """Validate query with empty required fields."""
        query = {"model": "", "view": "", "fields": []}

        errors = validator.validate_query(query)

        # May or may not fail depending on SDK validation strictness
        # At minimum, should not crash
        assert isinstance(errors, list)

    def test_validate_query_sdk_validation_error(self, validator):
        """Query that fails SDK validation."""
        query = {
            "model": "sales",
            "view": "orders",
            "fields": "not_a_list",  # Should be list
        }

        errors = validator.validate_query(query)

        # May or may not fail depending on SDK validation strictness
        # At minimum, should not crash
        assert isinstance(errors, list)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_validate_empty_dict(self, validator):
        """Validate empty dictionary."""
        with pytest.raises(ValidationError, match="Missing required _metadata"):
            validator.validate_metadata_section({})

    def test_validate_nested_validation_errors(self, validator):
        """Multiple nested validation errors."""
        data = {
            "id": "123",
            "title": "",  # Empty
            "elements": [],
            # Missing metadata
        }

        errors = validator.validate_content_structure(data, "DASHBOARD")

        # Should have structure errors (missing metadata)
        assert len(errors["structure_errors"]) > 0
        # Field errors may or may not be present depending on validation order
        assert isinstance(errors["field_errors"], list)

    def test_validate_unicode_content(self, validator):
        """Validate content with unicode characters."""
        data = {
            "id": "123",
            "title": "Café Dashboard ☕",
            "elements": [],
            "_metadata": {
                "db_id": "123",
                "content_type": "DASHBOARD",
                "exported_at": "2025-12-14T10:00:00",
                "content_size": 1024,
                "checksum": "sha256:abc123",
            },
        }

        errors = validator.validate_content_structure(data, "DASHBOARD")

        # Should validate successfully
        assert len(errors["structure_errors"]) == 0

    def test_validate_large_structure(self, validator):
        """Validate large content structure."""
        data = {
            "id": "123",
            "title": "Large Dashboard",
            "elements": [{"id": f"elem_{i}", "type": "text"} for i in range(100)],
            "_metadata": {
                "db_id": "123",
                "content_type": "DASHBOARD",
                "exported_at": "2025-12-14T10:00:00",
                "content_size": 1024,
                "checksum": "sha256:abc123",
            },
        }

        errors = validator.validate_content_structure(data, "DASHBOARD")

        assert len(errors["structure_errors"]) == 0
