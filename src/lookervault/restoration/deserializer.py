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

    Key functionality - Read-only field filtering:
        This class automatically filters out server-managed metadata fields that
        are present in Looker API GET responses but cannot be passed to CREATE/UPDATE
        operations. See the READ_ONLY_FIELDS documentation for a complete list and
        rationale for why each field is filtered.

    Typical usage:
        >>> deserializer = ContentDeserializer()
        >>> # Deserialize to dict (most common)
        >>> content = deserializer.deserialize(blob, ContentType.DASHBOARD, as_dict=True)
        >>> # Or deserialize to SDK model for validation
        >>> model = deserializer.deserialize(blob, ContentType.DASHBOARD, as_dict=False)
    """

    # Read-only fields that should be filtered before Write* model instantiation.
    #
    # These fields are returned by Looker's GET/READ API endpoints but are NOT
    # accepted by Write* model constructors (used for CREATE/UPDATE operations).
    #
    # Why filtering is necessary:
    # - Read* models (from GET responses) include server-managed metadata fields
    # - Write* models (for CREATE/UPDATE) reject these fields during instantiation
    # - Attempting to pass read-only fields to Write* models causes TypeError
    #
    # Data integrity implications:
    # - These fields are automatically computed by Looker on CREATE/UPDATE
    # - They reflect server state (timestamps, URLs, counts, computed relationships)
    # - Preserving them from backups would be meaningless or cause conflicts
    # - Filtering ensures clean restoration without stale metadata
    #
    # NOTE: 'id' is NOT included here because:
    #   - It's required for check_exists() to verify content in destination
    #   - It's required for update operations (PATCH) to specify target item
    #   - The restorer removes it before CREATE operations with content_dict.pop("id", None)
    #
    # Categories of read-only fields:
    # 1. Timestamps: Server-generated creation/update/deletion times
    # 2. User references: IDs/names of users who created/modified content
    # 3. Computed metadata: Counts, URLs, slugs (derived from other fields)
    # 4. Relationship fields: Child objects loaded by API (dashboard_elements, etc.)
    # 5. External system IDs: LDAP, SAML, Google credential references
    READ_ONLY_FIELDS: set[str] = {
        # ===== Common metadata fields =====
        # Server-generated timestamps for lifecycle tracking
        "can",  # User permissions (computed from user's role)
        "created_at",  # Auto-set on creation
        "updated_at",  # Auto-updated on modification
        "deleted_at",  # Auto-set on soft delete
        "creator_id",  # Auto-set to current user on creation
        "deleter_id",  # Auto-set to current user on deletion
        "last_updater_id",  # Auto-updated on modification
        "last_updater_name",  # Derived from last_updater_id
        "user_id",  # Owner reference (auto-set or managed separately)
        "user_name",  # Derived from user_id
        # ===== Content metadata =====
        # Usage tracking and relationship fields computed by Looker
        "content_metadata_id",  # Reference to content metadata (managed separately)
        "content_favorite_id",  # Reference to favorite (managed separately)
        "favorite_count",  # Computed from favorites table
        "view_count",  # Usage analytics (computed)
        "last_viewed_at",  # Usage analytics (computed)
        "last_accessed_at",  # Usage analytics (computed)
        # ===== URLs and links =====
        # All URLs are computed from content ID and Looker base URL
        "url",  # Full URL to content (computed)
        "short_url",  # Shortened URL (computed)
        "public_url",  # Public access URL (computed)
        "public_slug",  # URL slug component (computed)
        "embed_url",  # Embeddable URL (computed)
        "excel_file_url",  # Excel export URL (computed)
        "edit_uri",  # Edit endpoint URI (computed)
        "image_embed_url",  # Image embed URL (computed)
        "google_spreadsheet_formula",  # Google Sheets integration (computed)
        # ===== Dashboard-specific =====
        # Nested child objects loaded by API (not part of create payload)
        "dashboard_elements",  # Child elements (managed separately)
        "dashboard_filters",  # Child filters (managed separately)
        "dashboard_layouts",  # Child layouts (managed separately)
        "refresh_interval_to_i",  # Internal interval representation
        # ===== Look-specific =====
        # Model/explore references are auto-populated from query definition
        "model",  # Auto-populated from query.model_id
        "explore",  # Auto-populated from query.view_name
        # ===== Folder-specific =====
        # Computed state and relationship fields
        "child_count",  # Count of child items (computed)
        "is_embed",  # Folder type flag (computed)
        "is_embed_shared_root",  # Special folder flag (computed)
        "is_embed_users_root",  # Special folder flag (computed)
        "is_personal",  # Folder type flag (computed)
        "is_personal_descendant",  # Ancestry flag (computed)
        "is_shared_root",  # Special folder flag (computed)
        "is_users_root",  # Special folder flag (computed)
        "has_content",  # Boolean flag (computed from children)
        "embed_group_folder_id",  # Embed group reference (computed)
        "embed_group_space_id",  # Embed space reference (computed)
        "dashboards",  # Child dashboards (loaded by API, not part of create)
        "looks",  # Child looks (loaded by API, not part of create)
        # ===== User-specific =====
        # External authentication credentials and computed profile fields
        "credentials_api3",  # API3 credential hash (managed externally)
        "credentials_embed",  # Embed credential (managed externally)
        "credentials_email",  # Email credential (managed externally)
        "credentials_google",  # Google OAuth credential (managed externally)
        "credentials_ldap",  # LDAP credential (managed externally)
        "credentials_looker_openid",  # OpenID credential (managed externally)
        "credentials_oidc",  # OIDC credential (managed externally)
        "credentials_saml",  # SAML credential (managed externally)
        "credentials_totp",  # TOTP 2FA credential (managed externally)
        "sessions",  # Active sessions (computed)
        "roles_externally_managed",  # External auth flag (computed)
        "presumed_looker_employee",  # Looker internal flag (computed)
        "verified_looker_employee",  # Looker internal flag (computed)
        "is_iam_admin",  # Admin flag (computed from permissions)
        "is_service_account",  # Service account flag (computed)
        "service_account_name",  # Service account identifier (computed)
        "avatar_url",  # Avatar URL (computed)
        "avatar_url_without_sizing",  # Avatar URL (computed)
        "display_name",  # Profile field (may be managed separately)
        "email",  # Primary email (may be managed separately)
        "personal_folder_id",  # Auto-created personal folder (computed)
        "primary_homepage",  # User preference (managed separately)
        "users_url",  # API endpoint URL (computed)
        # ===== Group-specific =====
        # Membership and external sync fields
        "contains_current_user",  # Flag for current user (computed)
        "external_group_id",  # External group mapping (managed externally)
        "externally_managed",  # External sync flag (computed)
        "include_by_default",  # Default membership (computed)
        "user_count",  # Member count (computed)
        "allow_direct_roles",  # Permission setting (computed)
        "allow_normal_group_membership",  # Permission setting (computed)
        "allow_roles_from_normal_groups",  # Permission setting (computed)
        # ===== Role-specific =====
        # Many-to-many relationship fields (managed separately)
        "group_ids",  # Assigned groups (managed via role_groups endpoint)
        "role_ids",  # Sub-roles (managed via role_roles endpoint)
        # ===== Board-specific =====
        # Nested child objects
        "board_sections",  # Child sections (managed separately)
        # ===== Scheduled plan-specific =====
        # Computed schedule fields
        "last_run_at",  # Execution history (computed)
        "next_run_at",  # Next scheduled run (computed from cron)
        # ===== LookML model-specific =====
        # Parsed LookML metadata (computed from model file)
        "explores",  # Parsed explores (computed)
        "label",  # Model label (from LookML file)
        "looker_versions",  # Supported Looker versions (from LookML)
        # ===== Permission/model set-specific =====
        # System-managed flags and references
        "all_access",  # Permission flag (computed from permissions)
        "built_in",  # Built-in flag (computed)
        "readonly",  # Read-only flag (computed)
        "user",  # User reference for model sets (computed)
        "external_id",  # External ID mapping (managed externally)
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

        This method filters out server-managed metadata fields that are present
        in Looker API GET responses but cannot be passed to CREATE/UPDATE operations.

        Why filtering is necessary:
        - Looker's GET endpoints return rich metadata including timestamps, URLs,
          computed fields, and nested child objects
        - Looker's Write* model constructors (for CREATE/UPDATE) reject these
          fields because they are managed server-side
        - Attempting to pass read-only fields causes TypeError: "got an unexpected
          keyword argument '<field_name>'"

        Filtering logic:
        1. Iterates through all key-value pairs in the input dictionary
        2. Excludes any key that exists in READ_ONLY_FIELDS
        3. Preserves all other fields including custom fields and user-defined content

        Data integrity considerations:
        - Read-only fields are auto-computed by Looker on restore
        - Filtering ensures clean restoration without stale metadata conflicts
        - The restored content will have fresh timestamps, URLs, and computed values

        Args:
            content_dict: Dictionary with all fields from API response or SQLite backup

        Returns:
            Filtered dictionary containing only fields that can be passed to
            Write* model constructors for CREATE/UPDATE operations

        Example:
            Input:  {'id': 1, 'title': 'My Dashboard', 'created_at': '2024-01-01', 'url': '...'}
            Output: {'id': 1, 'title': 'My Dashboard'}  # created_at and url filtered out
        """
        # Dictionary comprehension filters out any keys in READ_ONLY_FIELDS
        # This is more efficient than modifying the dict in-place
        return {k: v for k, v in content_dict.items() if k not in self.READ_ONLY_FIELDS}

    def deserialize(
        self,
        content_data: bytes,
        content_type: ContentType,
        as_dict: bool = True,
    ) -> dict[str, Any] | Any:
        """Deserialize binary content data to SDK model or dict.

        This is the main entry point for converting stored content back into a format
        suitable for restoration. The process includes:
        1. Deserialize msgpack binary blob to Python dict
        2. Filter out read-only fields (server-managed metadata)
        3. Optionally convert to SDK Write* model for validation

        Read-only field filtering:
        - Removes fields like created_at, updated_at, URLs, counts, etc.
        - These fields are returned by GET endpoints but rejected by Write* constructors
        - See READ_ONLY_FIELDS documentation for complete list and rationale

        Args:
            content_data: Binary blob from SQLite content_items.content_data
                         (stored as msgpack format)
            content_type: ContentType enum value (determines which Write* model to use)
            as_dict: If True, return plain dict; if False, return SDK Write* model instance

        Returns:
            Deserialized content as dict or SDK model instance.
            Dicts are lighter-weight and suitable for most operations.
            SDK models provide type validation and IDE autocomplete support.

        Raises:
            DeserializationError: If content_data is corrupted or invalid format
            ValueError: If content_type is not supported

        Example:
            >>> deserializer = ContentDeserializer()
            >>> data = b"\x81\xa3id\x01\xa5title\xa9My Dashboard"
            >>> result = deserializer.deserialize(data, ContentType.DASHBOARD)
            >>> result["title"]
            'My Dashboard'
        """
        # Validate content_type is supported
        if content_type not in self._WRITE_MODEL_MAP:
            raise ValueError(
                f"Unsupported content type: {content_type}. "
                f"Supported types: {list(self._WRITE_MODEL_MAP.keys())}"
            )

        # Deserialize binary blob to Python dict using msgspec msgpack format
        try:
            content_dict = msgspec.msgpack.decode(content_data)
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
        # This is critical: Write* models will reject these fields
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

        This method validates that a content dictionary can be successfully converted
        to a Looker SDK Write* model instance. It's used to detect schema issues
        before attempting restoration.

        Validation process:
        1. Filter read-only fields (same as deserialize)
        2. Filter 'id' field (Write* constructors reject it, though it's kept for other ops)
        3. Attempt to instantiate the Write* model
        4. Catch and report any validation errors

        Read-only field filtering in validation:
        - Uses the same READ_ONLY_FIELDS set as deserialize
        - Ensures validation accurately reflects what will be accepted by Write* models
        - Prevents false positives from read-only fields that would cause restoration to fail

        Args:
            content_dict: Deserialized content dictionary
            content_type: ContentType enum value

        Returns:
            List of validation error messages (empty if valid). Errors include:
            - Schema validation failures (missing required fields, wrong types)
            - Value validation failures (constraint violations)
            - Unsupported content type errors

        Example:
            >>> deserializer = ContentDeserializer()
            >>> content = {"title": "My Dashboard"}  # Missing required 'space_id'
            >>> errors = deserializer.validate_schema(content, ContentType.DASHBOARD)
            >>> # errors will contain messages about missing required fields
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
        # This ensures validation matches what deserialize() will produce
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
