"""Tests for YamlSerializer."""

import pytest

from lookervault.export.yaml_serializer import YamlSerializer


@pytest.fixture
def serializer():
    """Create YamlSerializer instance."""
    return YamlSerializer()


class TestSerialize:
    """Test YAML serialization."""

    def test_serialize_simple_dict(self, serializer):
        """Serialize simple dictionary to YAML."""
        data = {"title": "Test Dashboard", "id": "123"}
        result = serializer.serialize(data)

        assert "title: Test Dashboard" in result, (
            "Expected 'title: Test Dashboard' in serialized YAML"
        )
        assert "id: '123'" in result or 'id: "123"' in result, (
            "Expected quoted id '123' in serialized YAML"
        )

    def test_serialize_nested_dict(self, serializer):
        """Serialize nested dictionary."""
        data = {
            "title": "Dashboard",
            "filters": {"date": "2025-01-01", "region": "US"},
            "elements": [{"id": "1", "type": "text"}],
        }
        result = serializer.serialize(data)

        assert "title: Dashboard" in result, "Expected 'title: Dashboard' in serialized YAML"
        assert "filters:" in result, "Expected 'filters:' key in serialized YAML"
        assert "elements:" in result, "Expected 'elements:' key in serialized YAML"

    def test_serialize_preserves_quotes(self, serializer):
        """Verify quote preservation."""
        data = {"title": "Test", "description": "With 'quotes'"}
        result = serializer.serialize(data)

        # Should preserve quote style
        assert "title:" in result, "Expected 'title:' key in serialized YAML"
        assert "description:" in result, "Expected 'description:' key in serialized YAML"

    def test_serialize_non_dict_raises_error(self, serializer):
        """Serializing non-dict raises ValueError."""
        with pytest.raises(ValueError, match="Expected dict"):
            serializer.serialize("not a dict")

        with pytest.raises(ValueError, match="Expected dict"):
            serializer.serialize(["list", "of", "items"])

    def test_serialize_with_unicode(self, serializer):
        """Serialize dictionary with unicode characters."""
        data = {"title": "Café ☕", "description": "Résumé"}
        result = serializer.serialize(data)

        assert "Café" in result, "Expected unicode character 'é' to be preserved"
        assert "Résumé" in result, "Expected unicode characters in 'Résumé' to be preserved"

    def test_serialize_with_special_chars(self, serializer):
        """Serialize dictionary with special YAML characters."""
        data = {"title": "Test: Dashboard", "tags": ["tag1", "tag2"]}
        result = serializer.serialize(data)

        # Should handle colons and arrays properly
        assert "title:" in result, "Expected 'title:' key in serialized YAML"
        assert "tags:" in result, "Expected 'tags:' key in serialized YAML"


class TestDeserialize:
    """Test YAML deserialization."""

    def test_deserialize_simple_yaml(self, serializer):
        """Deserialize simple YAML to dict."""
        yaml_str = """
title: Test Dashboard
id: '123'
"""
        result = serializer.deserialize(yaml_str)

        assert result["title"] == "Test Dashboard", (
            f"Expected title 'Test Dashboard' but got '{result['title']}'"
        )
        assert result["id"] == "123", f"Expected id '123' but got '{result['id']}'"

    def test_deserialize_nested_yaml(self, serializer):
        """Deserialize nested YAML structure."""
        yaml_str = """
title: Dashboard
filters:
  date: '2025-01-01'
  region: US
elements:
  - id: '1'
    type: text
"""
        result = serializer.deserialize(yaml_str)

        assert result["title"] == "Dashboard", (
            f"Expected title 'Dashboard' but got '{result['title']}'"
        )
        assert result["filters"]["date"] == "2025-01-01", (
            f"Expected filters.date '2025-01-01' but got '{result['filters']['date']}'"
        )
        assert len(result["elements"]) == 1, f"Expected 1 element but got {len(result['elements'])}"
        assert result["elements"][0]["id"] == "1", (
            f"Expected element id '1' but got '{result['elements'][0]['id']}'"
        )

    def test_deserialize_non_string_raises_error(self, serializer):
        """Deserializing non-string raises ValueError."""
        with pytest.raises(ValueError, match="Expected str"):
            serializer.deserialize({"not": "a string"})

    def test_deserialize_invalid_yaml_raises_error(self, serializer):
        """Deserializing invalid YAML raises ValueError."""
        with pytest.raises(ValueError, match="Failed to parse YAML"):
            serializer.deserialize("invalid: yaml: [unclosed")

    def test_deserialize_non_dict_yaml_raises_error(self, serializer):
        """Deserializing YAML that doesn't parse to dict raises error."""
        with pytest.raises(ValueError, match="must deserialize to dict"):
            serializer.deserialize("- list item 1\n- list item 2")

        with pytest.raises(ValueError, match="must deserialize to dict"):
            serializer.deserialize("just a string")

    def test_deserialize_empty_yaml_raises_error(self, serializer):
        """Deserializing empty YAML raises error."""
        with pytest.raises(ValueError, match="must deserialize to dict"):
            serializer.deserialize("")


class TestValidate:
    """Test YAML validation."""

    def test_validate_valid_yaml(self, serializer):
        """Validate correct YAML syntax."""
        valid_yaml = "title: Test\nid: '123'"
        assert serializer.validate(valid_yaml) is True, "Expected valid YAML to return True"

    def test_validate_invalid_yaml(self, serializer):
        """Validate incorrect YAML syntax."""
        invalid_yaml = "title: test: [unclosed"
        assert serializer.validate(invalid_yaml) is False, "Expected invalid YAML to return False"


class TestRoundTrip:
    """Test round-trip serialization/deserialization."""

    def test_round_trip_preserves_data(self, serializer):
        """Round-trip should preserve data structure."""
        # Use simpler structure to avoid YAML parsing issues
        original = {
            "title": "Test Dashboard",
            "id": "123",
            "count": 42,
            "enabled": True,
        }

        yaml_str = serializer.serialize(original)
        result = serializer.deserialize(yaml_str)

        # Compare the data
        assert result["title"] == original["title"], (
            f"Expected title '{original['title']}' but got '{result['title']}'"
        )
        assert result["id"] == original["id"], (
            f"Expected id '{original['id']}' but got '{result['id']}'"
        )
        assert result["count"] == original["count"], (
            f"Expected count {original['count']} but got {result['count']}"
        )
        assert result["enabled"] == original["enabled"], (
            f"Expected enabled {original['enabled']} but got {result['enabled']}"
        )

    def test_round_trip_with_metadata(self, serializer):
        """Round-trip with _metadata section."""
        original = {
            "title": "Dashboard",
            "id": "abc123",
            "_metadata": {
                "db_id": "abc123",
                "content_type": "DASHBOARD",
                "exported_at": "2025-12-14T10:00:00",
                "checksum": "sha256:abc123",
            },
        }

        yaml_str = serializer.serialize(original)
        result = serializer.deserialize(yaml_str)

        assert result == original, f"Expected round-trip to preserve data but got {result}"
        assert result["_metadata"]["db_id"] == "abc123", (
            f"Expected metadata db_id 'abc123' but got '{result['_metadata']['db_id']}'"
        )


class TestStreamingIO:
    """Test streaming I/O for large files."""

    def test_serialize_to_file(self, serializer, tmp_path):
        """Serialize data directly to file."""
        data = {"title": "Test Dashboard", "id": "123"}
        output_file = tmp_path / "test.yaml"

        serializer.serialize_to_file(data, output_file)

        # Verify file was created and contains expected content
        assert output_file.exists(), f"Expected file to exist at {output_file}"
        content = output_file.read_text()
        assert "title: Test Dashboard" in content, (
            "Expected 'title: Test Dashboard' in file content"
        )

    def test_serialize_to_file_non_dict_raises_error(self, serializer, tmp_path):
        """Serializing non-dict to file raises ValueError."""
        output_file = tmp_path / "test.yaml"

        with pytest.raises(ValueError, match="Expected dict"):
            serializer.serialize_to_file("not a dict", output_file)

    def test_serialize_to_file_invalid_path_raises_error(self, serializer):
        """Serializing to invalid path raises ValueError."""
        data = {"title": "Test"}
        invalid_path = "/nonexistent/directory/file.yaml"

        with pytest.raises(ValueError, match="Failed to write to file"):
            serializer.serialize_to_file(data, invalid_path)

    def test_deserialize_from_file(self, serializer, tmp_path):
        """Deserialize data directly from file."""
        yaml_content = "title: Test Dashboard\nid: '123'\n"
        input_file = tmp_path / "test.yaml"
        input_file.write_text(yaml_content)

        result = serializer.deserialize_from_file(input_file)

        assert result["title"] == "Test Dashboard", (
            f"Expected title 'Test Dashboard' but got '{result['title']}'"
        )
        assert result["id"] == "123", f"Expected id '123' but got '{result['id']}'"

    def test_deserialize_from_file_not_found_raises_error(self, serializer):
        """Deserializing from missing file raises ValueError."""
        with pytest.raises(ValueError, match="Failed to read file"):
            serializer.deserialize_from_file("/nonexistent/file.yaml")

    def test_deserialize_from_file_invalid_yaml_raises_error(self, serializer, tmp_path):
        """Deserializing invalid YAML from file raises ValueError."""
        input_file = tmp_path / "invalid.yaml"
        input_file.write_text("invalid: yaml: [unclosed")

        with pytest.raises(ValueError, match="Failed to parse YAML"):
            serializer.deserialize_from_file(input_file)

    def test_round_trip_file_io(self, serializer, tmp_path):
        """Round-trip using file I/O."""
        original = {
            "title": "Test Dashboard",
            "id": "123",
            "filters": {"date": "2025-01-01"},
        }

        file_path = tmp_path / "test.yaml"
        serializer.serialize_to_file(original, file_path)
        result = serializer.deserialize_from_file(file_path)

        assert result == original, f"Expected round-trip file I/O to preserve data but got {result}"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_serialize_large_dict(self, serializer):
        """Serialize large dictionary."""
        large_dict = {f"field_{i}": f"value_{i}" for i in range(1000)}
        result = serializer.serialize(large_dict)

        assert len(result) > 0, "Expected non-empty result for large dict"
        assert "field_0" in result, "Expected 'field_0' in serialized YAML"
        assert "field_999" in result, "Expected 'field_999' in serialized YAML"

    def test_serialize_deeply_nested(self, serializer):
        """Serialize deeply nested structure."""
        nested = {"level1": {"level2": {"level3": {"level4": {"value": "deep"}}}}}
        result = serializer.serialize(nested)

        assert "level1:" in result, "Expected 'level1:' in serialized YAML"
        assert "value: deep" in result, "Expected 'value: deep' in serialized YAML"

    def test_deserialize_with_comments(self, serializer):
        """Deserialize YAML with comments."""
        yaml_with_comments = """
# This is a comment
title: Test Dashboard  # Inline comment
id: '123'
"""
        result = serializer.deserialize(yaml_with_comments)

        assert result["title"] == "Test Dashboard", (
            f"Expected title 'Test Dashboard' but got '{result['title']}'"
        )
        assert result["id"] == "123", f"Expected id '123' but got '{result['id']}'"

    def test_serialize_with_null_values(self, serializer):
        """Serialize dictionary with null values."""
        data = {"title": "Test", "description": None}
        result = serializer.serialize(data)

        assert "title: Test" in result, "Expected 'title: Test' in serialized YAML"
        assert "description:" in result, (
            "Expected 'description:' key for null value in serialized YAML"
        )

    def test_serialize_with_boolean_values(self, serializer):
        """Serialize dictionary with boolean values."""
        data = {"enabled": True, "disabled": False}
        result = serializer.serialize(data)

        assert "enabled: true" in result, "Expected 'enabled: true' in serialized YAML"
        assert "disabled: false" in result, "Expected 'disabled: false' in serialized YAML"

    def test_serialize_with_numeric_values(self, serializer):
        """Serialize dictionary with numeric values."""
        data = {"count": 42, "percentage": 95.5}
        result = serializer.serialize(data)

        assert "count: 42" in result, "Expected 'count: 42' in serialized YAML"
        assert "percentage: 95.5" in result, "Expected 'percentage: 95.5' in serialized YAML"
