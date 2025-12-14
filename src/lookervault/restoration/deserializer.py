"""Content deserialization for restoration from SQLite binary blobs."""

from typing import Any

import msgspec
from looker_sdk import models40 as looker_models

from lookervault.exceptions import DeserializationError
from lookervault.storage.models import ContentType


class ContentDeserializer:
    """Deserializes content_data blobs to Looker SDK Write* models or dicts.

    Uses msgspec msgpack format to deserialize binary blobs stored in SQLite
    back into Python dictionaries or Looker SDK model instances for restoration.
    """

    # Read-only fields that should be filtered before Write* model instantiation
    # These fields are returned by Looker API but not accepted by Write* models
    # NOTE: 'id' is NOT included here because:
    #   - It's required for check_exists() to verify content in destination
    #   - It's required for update operations (PATCH) to specify target item
    #   - The restorer removes it before CREATE operations with content_dict.pop("id", None)
    READ_ONLY_FIELDS: set[str] = {
        # Common metadata fields
        "can",
        "created_at",
        "updated_at",
        "deleted_at",
        "creator_id",
        "deleter_id",
        "last_updater_id",
        "last_updater_name",
        "user_id",
        "user_name",
        # Content metadata
        "content_metadata_id",
        "content_favorite_id",
        "favorite_count",
        "view_count",
        "last_viewed_at",
        "last_accessed_at",
        # URLs and links
        "url",
        "short_url",
        "public_url",
        "public_slug",
        "embed_url",
        "excel_file_url",
        "edit_uri",
        "image_embed_url",
        "google_spreadsheet_formula",
        # Dashboard-specific
        "dashboard_elements",
        "dashboard_filters",
        "dashboard_layouts",
        "refresh_interval_to_i",
        # Look-specific
        "model",
        "explore",
        # Folder-specific
        "child_count",
        "is_embed",
        "is_embed_shared_root",
        "is_embed_users_root",
        "is_personal",
        "is_personal_descendant",
        "is_shared_root",
        "is_users_root",
        "has_content",
        "embed_group_folder_id",
        "embed_group_space_id",
        "dashboards",
        "looks",
        # User-specific
        "credentials_api3",
        "credentials_embed",
        "credentials_email",
        "credentials_google",
        "credentials_ldap",
        "credentials_looker_openid",
        "credentials_oidc",
        "credentials_saml",
        "credentials_totp",
        "sessions",
        "roles_externally_managed",
        "presumed_looker_employee",
        "verified_looker_employee",
        "is_iam_admin",
        "is_service_account",
        "service_account_name",
        "avatar_url",
        "avatar_url_without_sizing",
        "display_name",
        "email",
        "personal_folder_id",
        "primary_homepage",
        "users_url",
        # Group-specific
        "contains_current_user",
        "external_group_id",
        "externally_managed",
        "include_by_default",
        "user_count",
        "allow_direct_roles",
        "allow_normal_group_membership",
        "allow_roles_from_normal_groups",
        # Role-specific
        "group_ids",
        "role_ids",
        # Board-specific
        "board_sections",
        # Scheduled plan-specific
        "last_run_at",
        "next_run_at",
        # LookML model-specific
        "explores",
        "label",
        "looker_versions",
        # Permission/model set-specific
        "all_access",
        "built_in",
        "readonly",
        "user",
        "external_id",
    }

    # Mapping of ContentType to Looker SDK Write* model classes
    _WRITE_MODEL_MAP: dict[ContentType, type[Any]] = {
        ContentType.DASHBOARD: looker_models.WriteDashboard,
        ContentType.LOOK: looker_models.WriteLookWithQuery,
        ContentType.FOLDER: looker_models.UpdateFolder,
        ContentType.USER: looker_models.WriteUser,
        ContentType.GROUP: looker_models.WriteGroup,
        ContentType.ROLE: looker_models.WriteRole,
        ContentType.BOARD: looker_models.WriteBoard,
        ContentType.SCHEDULED_PLAN: looker_models.WriteScheduledPlan,
        ContentType.LOOKML_MODEL: looker_models.WriteLookmlModel,
        ContentType.PERMISSION_SET: looker_models.WritePermissionSet,
        ContentType.MODEL_SET: looker_models.WriteModelSet,
        ContentType.EXPLORE: looker_models.WriteQuery,  # Explores are queries
    }

    def _filter_read_only_fields(self, content_dict: dict[str, Any]) -> dict[str, Any]:
        """Remove read-only fields that Write* models don't accept.

        Args:
            content_dict: Dictionary with all fields from API response

        Returns:
            Filtered dictionary with only write-able fields
        """
        return {k: v for k, v in content_dict.items() if k not in self.READ_ONLY_FIELDS}

    def deserialize(
        self,
        content_data: bytes,
        content_type: ContentType,
        as_dict: bool = True,
    ) -> dict[str, Any] | Any:
        """Deserialize binary content data to SDK model or dict.

        Args:
            content_data: Binary blob from SQLite content_items.content_data
            content_type: ContentType enum value
            as_dict: If True, return plain dict; if False, return SDK Write* model instance

        Returns:
            Deserialized content as dict or SDK model instance

        Raises:
            DeserializationError: If content_data is corrupted or invalid format
            ValueError: If content_type is not supported
        """
        # Validate content_type is supported
        if content_type not in self._WRITE_MODEL_MAP:
            raise ValueError(
                f"Unsupported content type: {content_type}. "
                f"Supported types: {list(self._WRITE_MODEL_MAP.keys())}"
            )

        # Deserialize binary blob to Python dict
        try:
            content_dict = msgspec.msgpack.decode(content_data)  # type: ignore[attr-defined]
        except Exception as e:
            raise DeserializationError(
                f"Failed to deserialize {content_type.name} content: {e}"
            ) from e

        # Validate deserialized data is a dictionary
        if not isinstance(content_dict, dict):
            raise DeserializationError(
                f"Deserialized content for {content_type.name} is not a dictionary. "
                f"Got type: {type(content_dict)}"
            )

        # Filter read-only fields before returning
        filtered_dict = self._filter_read_only_fields(content_dict)

        # Return as dict if requested (lighter-weight, no validation)
        if as_dict:
            return filtered_dict

        # Convert dict to SDK Write* model for type safety and validation
        model_class = self._WRITE_MODEL_MAP[content_type]
        try:
            # Looker SDK models accept **kwargs for initialization
            return model_class(**filtered_dict)
        except Exception as e:
            raise DeserializationError(
                f"Failed to convert {content_type.name} dict to SDK model {model_class.__name__}: {e}"
            ) from e

    def validate_schema(
        self,
        content_dict: dict[str, Any],
        content_type: ContentType,
    ) -> list[str]:
        """Validate content against SDK model schema.

        Args:
            content_dict: Deserialized content dictionary
            content_type: ContentType enum value

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: list[str] = []

        # Check content_type is supported
        if content_type not in self._WRITE_MODEL_MAP:
            errors.append(
                f"Unsupported content type: {content_type}. "
                f"Supported types: {list(self._WRITE_MODEL_MAP.keys())}"
            )
            return errors

        # Validate content_dict is a dictionary
        if not isinstance(content_dict, dict):
            errors.append(f"Content is not a dictionary. Got type: {type(content_dict)}")
            return errors

        # Filter read-only fields before validation
        filtered_dict = self._filter_read_only_fields(content_dict)

        # Also filter 'id' for validation (Write* models don't accept it in constructor)
        # but keep it in the original dict for check_exists() and update operations
        validation_dict = {k: v for k, v in filtered_dict.items() if k != "id"}

        # Attempt to instantiate SDK model to validate schema
        model_class = self._WRITE_MODEL_MAP[content_type]
        try:
            # Try to create model instance - this validates required fields and types
            model_class(**validation_dict)
        except TypeError as e:
            # TypeError indicates missing required fields or wrong types
            errors.append(f"Schema validation failed: {e}")
        except ValueError as e:
            # ValueError indicates constraint violations
            errors.append(f"Value validation failed: {e}")
        except Exception as e:
            # Catch-all for other validation issues
            errors.append(f"Unexpected validation error: {e}")

        return errors
