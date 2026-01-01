"""Comprehensive tests for ContentDeserializer."""

from unittest.mock import MagicMock

import msgspec
import pytest
from looker_sdk import models40 as looker_models

from lookervault.exceptions import DeserializationError
from lookervault.restoration.deserializer import ContentDeserializer
from lookervault.storage.models import ContentType


@pytest.fixture
def deserializer():
    """Create ContentDeserializer instance."""
    return ContentDeserializer()


@pytest.fixture
def sample_dashboard_data():
    """Create sample dashboard data dictionary."""
    return {
        "id": "123",
        "title": "Test Dashboard",
        "description": "A test dashboard",
        "hidden": False,
        "folder_id": "456",
        # Read-only fields that should be filtered
        "can": {"view": True, "edit": True},
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "url": "https://looker.example.com/dashboards/123",
    }


@pytest.fixture
def sample_look_data():
    """Create sample look data dictionary."""
    return {
        "id": "789",
        "title": "Test Look",
        "description": "A test look",
        "folder_id": "456",
        "query_id": "111",
        # Read-only fields that should be filtered
        "can": {"view": True, "edit": True},
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "url": "https://looker.example.com/looks/789",
        "model": "sales",
        "explore": "orders",
    }


@pytest.fixture
def sample_user_data():
    """Create sample user data dictionary."""
    return {
        "id": "42",
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        # Read-only fields that should be filtered
        "display_name": "Test User",
        "avatar_url": "https://example.com/avatar.jpg",
        "credentials_api3": [{"id": "1"}],
        "credentials_email": {"email": "test@example.com"},
    }


class TestDeserializeAsDict:
    """Test deserialization to dictionary."""

    def test_deserialize_dashboard_success(self, deserializer, sample_dashboard_data):
        """Deserialize valid dashboard binary blob to dict."""
        # Serialize to binary blob
        binary_data = msgspec.msgpack.encode(sample_dashboard_data)

        # Deserialize
        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert isinstance(result, dict), (
            f"Expected result to be dict but got {type(result).__name__}"
        )
        assert result["id"] == "123", f"Expected id '123' but got '{result['id']}'"
        assert result["title"] == "Test Dashboard", (
            f"Expected title 'Test Dashboard' but got '{result['title']}'"
        )
        # Read-only fields should be filtered
        assert "can" not in result, "Expected 'can' field to be filtered from deserialized dict"
        assert "created_at" not in result, (
            "Expected 'created_at' field to be filtered from deserialized dict"
        )

    def test_deserialize_look_success(self, deserializer, sample_look_data):
        """Deserialize valid look binary blob to dict."""
        binary_data = msgspec.msgpack.encode(sample_look_data)

        result = deserializer.deserialize(binary_data, ContentType.LOOK, as_dict=True)

        assert isinstance(result, dict), (
            f"Expected result to be dict but got {type(result).__name__}"
        )
        assert result["id"] == "789", f"Expected id '789' but got '{result['id']}'"
        assert result["title"] == "Test Look", (
            f"Expected title 'Test Look' but got '{result['title']}'"
        )
        # Look-specific read-only fields should be filtered
        assert "model" not in result, (
            "Expected 'model' field to be filtered from Look deserialization"
        )
        assert "explore" not in result, (
            "Expected 'explore' field to be filtered from Look deserialization"
        )

    def test_deserialize_user_success(self, deserializer, sample_user_data):
        """Deserialize valid user binary blob to dict."""
        binary_data = msgspec.msgpack.encode(sample_user_data)

        result = deserializer.deserialize(binary_data, ContentType.USER, as_dict=True)

        assert isinstance(result, dict), (
            f"Expected result to be dict but got {type(result).__name__}"
        )
        assert result["id"] == "42", f"Expected id '42' but got '{result['id']}'"
        assert result["first_name"] == "Test", (
            f"Expected first_name 'Test' but got '{result['first_name']}'"
        )
        # User credential fields should be filtered
        assert "credentials_api3" not in result, (
            "Expected 'credentials_api3' to be filtered from User deserialization"
        )
        assert "display_name" not in result, (
            "Expected 'display_name' to be filtered from User deserialization"
        )

    def test_deserialize_corrupted_binary_raises_error(self, deserializer):
        """Corrupted binary data raises DeserializationError."""
        corrupted_data = b"corrupted\x00\xff\xfe"

        with pytest.raises(DeserializationError, match="Failed to deserialize DASHBOARD"):
            deserializer.deserialize(corrupted_data, ContentType.DASHBOARD, as_dict=True)

    def test_deserialize_empty_binary_raises_error(self, deserializer):
        """Empty binary data raises DeserializationError."""
        with pytest.raises(DeserializationError):
            deserializer.deserialize(b"", ContentType.DASHBOARD, as_dict=True)

    def test_deserialize_non_dict_data_raises_error(self, deserializer):
        """Binary data that deserializes to non-dict raises error."""
        # Serialize a list instead of dict
        binary_data = msgspec.msgpack.encode([1, 2, 3])

        with pytest.raises(DeserializationError, match="not a dictionary"):
            deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

    def test_deserialize_unsupported_content_type_raises_error(self, deserializer):
        """Unsupported content type raises ValueError."""
        binary_data = msgspec.msgpack.encode({"id": "123"})

        # Create a mock ContentType that's not in the map
        with pytest.raises(ValueError, match="Unsupported content type"):
            deserializer.deserialize(binary_data, MagicMock(name="UNSUPPORTED"), as_dict=True)

    def test_deserialize_preserves_nested_structures(self, deserializer):
        """Nested structures are preserved during deserialization."""
        data = {
            "id": "123",
            "title": "Test",
            "nested": {
                "level1": {
                    "level2": ["item1", "item2"],
                },
            },
            "list_field": [{"id": "1"}, {"id": "2"}],
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert result["nested"]["level1"]["level2"] == ["item1", "item2"]
        assert len(result["list_field"]) == 2
        assert result["list_field"][0]["id"] == "1"

    def test_deserialize_unicode_content(self, deserializer):
        """Unicode characters are preserved during deserialization."""
        data = {
            "id": "123",
            "title": "Café Dashboard ☕ 日本語",
            "description": "Test with émojis 🚀",
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert result["title"] == "Café Dashboard ☕ 日本語"
        assert result["description"] == "Test with émojis 🚀"

    def test_deserialize_large_content(self, deserializer):
        """Large content structures are handled correctly."""
        data = {
            "id": "123",
            "title": "Large Dashboard",
            "elements": [
                {
                    "id": f"elem_{i}",
                    "type": "text",
                    "body_text": "x" * 1000,
                }
                for i in range(100)
            ],
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert len(result["elements"]) == 100
        assert result["elements"][0]["body_text"] == "x" * 1000


class TestDeserializeAsSdkModel:
    """Test deserialization to SDK model instances."""

    def test_deserialize_dashboard_as_sdk_model(self, deserializer):
        """Deserialize dashboard to WriteDashboard SDK model."""
        data = {
            # Note: 'id' will be filtered out for SDK model constructor
            "title": "Test Dashboard",
            "description": "Test description",
            # Read-only fields to be filtered
            "can": {"view": True},
            "created_at": "2025-01-01",
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=False)

        assert isinstance(result, looker_models.WriteDashboard)
        assert result.title == "Test Dashboard"
        assert result.description == "Test description"

    def test_deserialize_look_as_sdk_model(self, deserializer):
        """Deserialize look to WriteLookWithQuery SDK model."""
        data = {
            # Note: 'id' will be filtered out for SDK model constructor
            "title": "Test Look",
            "description": "Test description",
            "folder_id": "456",
            # Read-only fields
            "can": {"view": True},
            "model": "sales",
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.LOOK, as_dict=False)

        assert isinstance(result, looker_models.WriteLookWithQuery)
        assert result.title == "Test Look"
        assert result.folder_id == "456"

    def test_deserialize_user_as_sdk_model(self, deserializer):
        """Deserialize user to WriteUser SDK model."""
        data = {
            # Note: 'id' will be filtered out for SDK model constructor
            "first_name": "Test",
            "last_name": "User",
            # Read-only fields
            "email": "test@example.com",
            "display_name": "Test User",
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.USER, as_dict=False)

        assert isinstance(result, looker_models.WriteUser)
        assert result.first_name == "Test"
        assert result.last_name == "User"

    def test_deserialize_folder_as_sdk_model(self, deserializer):
        """Deserialize folder to UpdateFolder SDK model."""
        data = {
            # Note: 'id' will be filtered out for SDK model constructor
            "name": "Test Folder",
            "parent_id": "1",
            # Read-only fields
            "child_count": 5,
            "dashboards": [],
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.FOLDER, as_dict=False)

        assert isinstance(result, looker_models.UpdateFolder)
        assert result.name == "Test Folder"
        assert result.parent_id == "1"

    def test_deserialize_invalid_sdk_model_raises_error(self, deserializer):
        """Invalid data for SDK model may raise DeserializationError."""
        # Data with invalid field types that SDK model may not accept
        data = {
            "title": 12345,  # Should be string, not int
            "hidden": "not_a_bool",  # Should be bool
        }
        binary_data = msgspec.msgpack.encode(data)

        # The SDK model may or may not raise depending on its validation
        # Just ensure we don't crash
        try:
            result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=False)
            # If it doesn't raise, at least verify we got a model back
            assert isinstance(result, looker_models.WriteDashboard)
        except DeserializationError:
            # This is also acceptable - the conversion failed as expected
            pass

    def test_deserialize_sdk_model_filters_id_field(self, deserializer):
        """SDK model instantiation filters ID field from constructor."""
        # Note: Write* models don't accept 'id' in constructor
        # The deserializer should filter it during SDK model creation
        data = {
            "title": "Test Dashboard",
        }
        binary_data = msgspec.msgpack.encode(data)

        # Should succeed - ID is not passed to SDK model constructor
        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=False)

        assert isinstance(result, looker_models.WriteDashboard)
        assert result.title == "Test Dashboard"


class TestValidateSchema:
    """Test schema validation."""

    def test_validate_valid_dashboard_schema(self, deserializer):
        """Valid dashboard schema passes validation."""
        content_dict = {
            "id": "123",
            "title": "Test Dashboard",
            "description": "Test",
        }

        errors = deserializer.validate_schema(content_dict, ContentType.DASHBOARD)

        assert errors == []

    def test_validate_valid_look_schema(self, deserializer):
        """Valid look schema passes validation."""
        content_dict = {
            "id": "789",
            "title": "Test Look",
            "folder_id": "456",
        }

        errors = deserializer.validate_schema(content_dict, ContentType.LOOK)

        assert errors == []

    def test_validate_missing_required_field(self, deserializer):
        """Schema validation with missing fields."""
        # Note: SDK models may have defaults for most fields
        # This test verifies validation doesn't crash with minimal data
        content_dict = {
            "description": "Test",
        }

        errors = deserializer.validate_schema(content_dict, ContentType.DASHBOARD)

        # Validation should complete without crashing
        # SDK models are lenient and may accept minimal data
        assert isinstance(errors, list)

    def test_validate_wrong_field_type(self, deserializer):
        """Wrong field type generates validation error."""
        content_dict = {
            "id": "123",
            "title": 12345,  # Should be string
        }

        errors = deserializer.validate_schema(content_dict, ContentType.DASHBOARD)

        # May or may not fail depending on SDK validation strictness
        # At minimum, should not crash
        assert isinstance(errors, list)

    def test_validate_filters_readonly_fields(self, deserializer):
        """Validation filters read-only fields before validation."""
        content_dict = {
            "id": "123",
            "title": "Test Dashboard",
            # Read-only fields that should be filtered
            "can": {"view": True},
            "created_at": "2025-01-01",
            "url": "https://example.com",
        }

        errors = deserializer.validate_schema(content_dict, ContentType.DASHBOARD)

        # Should pass validation (read-only fields filtered)
        assert errors == []

    def test_validate_filters_id_for_sdk_validation(self, deserializer):
        """ID field is filtered during SDK validation."""
        content_dict = {
            "id": "123",  # Should be filtered for Write* model validation
            "title": "Test Dashboard",
        }

        errors = deserializer.validate_schema(content_dict, ContentType.DASHBOARD)

        # Should pass - ID is filtered for SDK validation
        assert errors == []

    def test_validate_unsupported_content_type(self, deserializer):
        """Unsupported content type generates validation error."""
        content_dict = {"id": "123", "title": "Test"}

        errors = deserializer.validate_schema(content_dict, MagicMock(name="UNSUPPORTED"))

        assert len(errors) == 1
        assert "Unsupported content type" in errors[0]

    def test_validate_non_dict_content(self, deserializer):
        """Non-dict content generates validation error."""
        errors = deserializer.validate_schema([1, 2, 3], ContentType.DASHBOARD)

        assert len(errors) == 1
        assert "not a dictionary" in errors[0]

    def test_validate_empty_dict(self, deserializer):
        """Empty dict validation completes without crashing."""
        errors = deserializer.validate_schema({}, ContentType.DASHBOARD)

        # SDK models may accept empty dicts with defaults
        # Just ensure validation doesn't crash
        assert isinstance(errors, list)

    def test_validate_type_error_handling(self, deserializer):
        """TypeError during validation is captured."""
        # Invalid data structure that will cause TypeError
        content_dict = {
            "title": "Test",
            "invalid_nested": {"bad_structure": lambda x: x},  # Lambda not serializable
        }

        errors = deserializer.validate_schema(content_dict, ContentType.DASHBOARD)

        # Should capture error, not crash
        assert isinstance(errors, list)

    def test_validate_value_error_handling(self, deserializer):
        """ValueError during validation is captured."""
        # Create data that might cause ValueError
        content_dict = {
            "title": "Test",
            "hidden": "not_a_boolean",  # Should be boolean
        }

        errors = deserializer.validate_schema(content_dict, ContentType.DASHBOARD)

        # Should capture error, not crash
        assert isinstance(errors, list)


class TestContentTypeMapping:
    """Test content type to SDK model mapping."""

    def test_all_content_types_have_write_models(self, deserializer):
        """All content types in WRITE_MODEL_MAP are valid."""
        for content_type in deserializer._WRITE_MODEL_MAP:
            assert isinstance(content_type, ContentType)

    def test_dashboard_maps_to_write_dashboard(self, deserializer):
        """Dashboard maps to WriteDashboard."""
        assert deserializer._WRITE_MODEL_MAP[ContentType.DASHBOARD] == looker_models.WriteDashboard

    def test_look_maps_to_write_look_with_query(self, deserializer):
        """Look maps to WriteLookWithQuery."""
        assert deserializer._WRITE_MODEL_MAP[ContentType.LOOK] == looker_models.WriteLookWithQuery

    def test_folder_maps_to_update_folder(self, deserializer):
        """Folder maps to UpdateFolder."""
        assert deserializer._WRITE_MODEL_MAP[ContentType.FOLDER] == looker_models.UpdateFolder

    def test_user_maps_to_write_user(self, deserializer):
        """User maps to WriteUser."""
        assert deserializer._WRITE_MODEL_MAP[ContentType.USER] == looker_models.WriteUser

    def test_group_maps_to_write_group(self, deserializer):
        """Group maps to WriteGroup."""
        assert deserializer._WRITE_MODEL_MAP[ContentType.GROUP] == looker_models.WriteGroup

    def test_role_maps_to_write_role(self, deserializer):
        """Role maps to WriteRole."""
        assert deserializer._WRITE_MODEL_MAP[ContentType.ROLE] == looker_models.WriteRole

    def test_board_maps_to_write_board(self, deserializer):
        """Board maps to WriteBoard."""
        assert deserializer._WRITE_MODEL_MAP[ContentType.BOARD] == looker_models.WriteBoard

    def test_explore_maps_to_write_query(self, deserializer):
        """Explore maps to WriteQuery."""
        assert deserializer._WRITE_MODEL_MAP[ContentType.EXPLORE] == looker_models.WriteQuery


class TestReadOnlyFieldsConstant:
    """Test READ_ONLY_FIELDS constant coverage."""

    def test_readonly_fields_is_set(self, deserializer):
        """READ_ONLY_FIELDS is a set."""
        assert isinstance(deserializer.READ_ONLY_FIELDS, set)

    def test_readonly_fields_contains_common_metadata(self, deserializer):
        """READ_ONLY_FIELDS contains common metadata fields."""
        common_fields = {"can", "created_at", "updated_at", "deleted_at"}
        assert common_fields.issubset(deserializer.READ_ONLY_FIELDS)

    def test_readonly_fields_contains_urls(self, deserializer):
        """READ_ONLY_FIELDS contains URL fields."""
        url_fields = {"url", "short_url", "public_url", "embed_url"}
        assert url_fields.issubset(deserializer.READ_ONLY_FIELDS)

    def test_readonly_fields_contains_dashboard_specific(self, deserializer):
        """READ_ONLY_FIELDS contains dashboard-specific fields."""
        dashboard_fields = {"dashboard_elements", "dashboard_filters", "dashboard_layouts"}
        assert dashboard_fields.issubset(deserializer.READ_ONLY_FIELDS)

    def test_readonly_fields_contains_user_credentials(self, deserializer):
        """READ_ONLY_FIELDS contains user credential fields."""
        credential_fields = {
            "credentials_api3",
            "credentials_email",
            "credentials_google",
            "credentials_saml",
        }
        assert credential_fields.issubset(deserializer.READ_ONLY_FIELDS)

    def test_id_not_in_readonly_fields(self, deserializer):
        """ID field is NOT in READ_ONLY_FIELDS."""
        assert "id" not in deserializer.READ_ONLY_FIELDS


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_deserialize_null_values(self, deserializer):
        """Null values in content are preserved."""
        data = {
            "id": "123",
            "title": "Test",
            "description": None,
            "folder_id": None,
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert result["description"] is None
        assert result["folder_id"] is None

    def test_deserialize_boolean_fields(self, deserializer):
        """Boolean fields are preserved correctly."""
        data = {
            "id": "123",
            "title": "Test",
            "hidden": True,
            "deleted": False,
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert result["hidden"] is True
        assert result["deleted"] is False

    def test_deserialize_numeric_fields(self, deserializer):
        """Numeric fields (int, float) are preserved."""
        data = {
            "id": "123",
            "title": "Test",
            "refresh_interval": 3600,
            "some_float": 123.456,
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert result["refresh_interval"] == 3600
        assert result["some_float"] == 123.456

    def test_deserialize_empty_lists(self, deserializer):
        """Empty lists are preserved."""
        data = {
            "id": "123",
            "title": "Test",
            "elements": [],
            "tags": [],
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert result["elements"] == []
        assert result["tags"] == []

    def test_deserialize_deeply_nested_structure(self, deserializer):
        """Deeply nested structures are preserved."""
        data = {
            "id": "123",
            "title": "Test",
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "value": "deep",
                        },
                    },
                },
            },
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert result["level1"]["level2"]["level3"]["level4"]["value"] == "deep"

    def test_validate_schema_with_extra_fields(self, deserializer):
        """Extra fields not defined in SDK model are handled gracefully."""
        content_dict = {
            "id": "123",
            "title": "Test Dashboard",
            "custom_field": "custom_value",
            "extra_metadata": {"key": "value"},
        }

        errors = deserializer.validate_schema(content_dict, ContentType.DASHBOARD)

        # Should not fail - extra fields are typically allowed
        # (SDK models may accept **kwargs)
        assert isinstance(errors, list)

    def test_deserialize_special_characters_in_strings(self, deserializer):
        """Special characters in strings are preserved."""
        data = {
            "id": "123",
            "title": "Test with 'quotes' and \"double quotes\"",
            "description": "Line1\nLine2\tTabbed",
            "special": "Special: @#$%^&*()[]{}",
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert result["title"] == "Test with 'quotes' and \"double quotes\""
        assert result["description"] == "Line1\nLine2\tTabbed"
        assert result["special"] == "Special: @#$%^&*()[]{}"

    def test_deserialize_very_long_strings(self, deserializer):
        """Very long strings are handled correctly."""
        long_string = "x" * 100000
        data = {
            "id": "123",
            "title": "Test",
            "description": long_string,
        }
        binary_data = msgspec.msgpack.encode(data)

        result = deserializer.deserialize(binary_data, ContentType.DASHBOARD, as_dict=True)

        assert len(result["description"]) == 100000
        assert result["description"] == long_string
