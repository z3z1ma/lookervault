"""Content validation for restoration operations.

Provides pre-flight, content, and dependency validation to ensure successful
restoration operations. Validates database integrity, API connectivity,
content schema compliance, and dependency availability.
"""

import sqlite3
from pathlib import Path
from typing import Any

from looker_sdk import error as looker_error

from lookervault.looker.client import LookerClient
from lookervault.storage.models import ContentType
from lookervault.storage.schema import SCHEMA_VERSION


class RestorationValidator:
    """Validates content and environment before restoration operations.

    Performs three types of validation:
    1. Pre-flight: Database and API readiness checks
    2. Content: Individual item schema and field validation
    3. Dependencies: Verify required resources exist in destination

    Examples:
        >>> validator = RestorationValidator()
        >>> errors = validator.validate_pre_flight(db_path, client)
        >>> if errors:
        ...     print(f"Pre-flight checks failed: {errors}")
        >>> content_errors = validator.validate_content(content_dict, ContentType.DASHBOARD)
        >>> if content_errors:
        ...     print(f"Content validation failed: {content_errors}")
    """

    # Required fields by content type
    # Based on Looker SDK Write* model requirements
    REQUIRED_FIELDS = {
        ContentType.DASHBOARD: ["title"],
        ContentType.LOOK: ["title", "query"],
        ContentType.FOLDER: ["name"],
        ContentType.USER: ["first_name", "last_name"],
        ContentType.GROUP: ["name"],
        ContentType.ROLE: ["name"],
        ContentType.BOARD: ["title"],
        ContentType.SCHEDULED_PLAN: ["name"],
        ContentType.LOOKML_MODEL: ["name"],
        ContentType.EXPLORE: ["name"],
        ContentType.PERMISSION_SET: ["name"],
        ContentType.MODEL_SET: ["name"],
    }

    # Foreign key fields by content type
    # Used to identify dependencies that must exist in destination
    FK_FIELDS = {
        ContentType.DASHBOARD: ["folder_id", "user_id"],
        ContentType.LOOK: ["folder_id", "user_id"],
        ContentType.FOLDER: ["parent_id"],
        ContentType.BOARD: [],  # Boards reference content through sections, not direct FKs
        ContentType.SCHEDULED_PLAN: ["dashboard_id", "look_id", "user_id"],
        ContentType.USER: [],
        ContentType.GROUP: [],
        ContentType.ROLE: [],
        ContentType.LOOKML_MODEL: [],
        ContentType.EXPLORE: ["model_name"],
        ContentType.PERMISSION_SET: [],
        ContentType.MODEL_SET: ["models"],
    }

    def validate_pre_flight(self, db_path: Path, client: LookerClient) -> list[str]:
        """Run pre-flight validation checks before restoration.

        Validates:
        - SQLite file exists and is readable
        - SQLite schema version is compatible
        - Looker API is reachable and authenticated
        - Looker API version is compatible

        Args:
            db_path: Path to SQLite backup database
            client: LookerClient instance for API validation

        Returns:
            List of validation error messages (empty if all checks pass)

        Examples:
            >>> validator = RestorationValidator()
            >>> errors = validator.validate_pre_flight(Path("backup.db"), client)
            >>> if not errors:
            ...     print("Pre-flight checks passed")
        """
        errors: list[str] = []

        # Check 1: SQLite file exists and is readable
        if not db_path.exists():
            errors.append(f"SQLite database file does not exist: {db_path}")
            return errors  # Fatal - can't proceed with other checks

        if not db_path.is_file():
            errors.append(f"Path is not a file: {db_path}")
            return errors

        # Check 2: SQLite file is readable and has valid schema
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Verify schema_version table exists
            cursor.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='schema_version'
            """
            )
            if not cursor.fetchone():
                errors.append(
                    "Database missing schema_version table - not a valid LookerVault backup"
                )
                conn.close()
                return errors

            # Verify schema version compatibility
            cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            result = cursor.fetchone()
            if not result:
                errors.append("Database schema_version table is empty")
            else:
                db_version = result[0]
                if db_version != SCHEMA_VERSION:
                    errors.append(
                        f"Database schema version mismatch: found {db_version}, expected {SCHEMA_VERSION}"
                    )

            # Verify content_items table exists and has data
            cursor.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='content_items'
            """
            )
            if not cursor.fetchone():
                errors.append(
                    "Database missing content_items table - not a valid LookerVault backup"
                )
            else:
                # Check if database has any content to restore
                cursor.execute("SELECT COUNT(*) FROM content_items WHERE deleted_at IS NULL")
                count_result = cursor.fetchone()
                if count_result and count_result[0] == 0:
                    errors.append("Database contains no active content items to restore")

            conn.close()

        except sqlite3.Error as e:
            errors.append(f"SQLite database error: {e}")
            return errors

        # Check 3: Looker API connectivity and authentication
        connection_status = client.test_connection()

        if not connection_status.connected:
            errors.append(f"Cannot connect to Looker API: {connection_status.error_message}")
            return errors  # Fatal - can't proceed with API version check

        if not connection_status.authenticated:
            errors.append(f"Looker API authentication failed: {connection_status.error_message}")
            return errors

        # Check 4: Looker API version compatibility (informational)
        # Note: We don't fail on version mismatch, just warn
        if connection_status.api_version:
            # All modern Looker instances support API 4.0
            # Add version-specific warnings here if needed in future
            pass

        return errors

    def validate_content(
        self, content_dict: dict[str, Any], content_type: ContentType
    ) -> list[str]:
        """Validate individual content item structure and fields.

        Validates:
        - Required fields are present
        - Field types are correct (basic type checking)
        - Content structure matches expected schema

        Note: This performs basic client-side validation. The Looker API
        will perform authoritative validation and may reject content
        that passes these checks.

        Args:
            content_dict: Deserialized content data
            content_type: Type of content being validated

        Returns:
            List of validation error messages (empty if valid)

        Examples:
            >>> validator = RestorationValidator()
            >>> content = {"title": "My Dashboard", "folder_id": "123"}
            >>> errors = validator.validate_content(content, ContentType.DASHBOARD)
            >>> if errors:
            ...     print(f"Invalid content: {errors}")
        """
        errors: list[str] = []

        # Validate content_dict is a dictionary
        if not isinstance(content_dict, dict):
            errors.append(f"Content must be a dictionary, got {type(content_dict).__name__}")
            return errors

        # Check required fields for this content type
        required_fields = self.REQUIRED_FIELDS.get(content_type, [])
        for field_name in required_fields:
            if field_name not in content_dict:
                errors.append(f"Missing required field: {field_name}")
            elif content_dict[field_name] is None:
                errors.append(f"Required field cannot be null: {field_name}")
            elif isinstance(content_dict[field_name], str) and not content_dict[field_name].strip():
                errors.append(f"Required field cannot be empty: {field_name}")

        # Type validation for common fields
        if "id" in content_dict and content_dict["id"] is not None:
            if not isinstance(content_dict["id"], (str, int)):
                errors.append(
                    f"Field 'id' must be string or integer, got {type(content_dict['id']).__name__}"
                )

        # Validate FK fields are correct type (string/int) if present
        fk_fields = self.FK_FIELDS.get(content_type, [])
        for fk_field in fk_fields:
            if fk_field in content_dict and content_dict[fk_field] is not None:
                # Most FKs are strings or integers
                if not isinstance(content_dict[fk_field], (str, int, list)):
                    errors.append(
                        f"Foreign key field '{fk_field}' must be string, integer, or list, "
                        f"got {type(content_dict[fk_field]).__name__}"
                    )

        # Content-type specific validations
        if content_type == ContentType.LOOK:
            # Look requires query object/dict
            if "query" in content_dict:
                if not isinstance(content_dict["query"], dict):
                    errors.append(
                        f"Field 'query' must be a dictionary, got {type(content_dict['query']).__name__}"
                    )

        if content_type == ContentType.USER:
            # User requires valid email format (basic check)
            if "email" in content_dict and content_dict["email"]:
                email = content_dict["email"]
                if "@" not in email:
                    errors.append(f"Invalid email format: {email}")

        return errors

    def validate_dependencies(
        self, content_dict: dict[str, Any], content_type: ContentType, client: LookerClient
    ) -> list[str]:
        """Validate that content dependencies exist in destination instance.

        Checks foreign key references to ensure referenced content exists
        in the destination Looker instance. This helps identify missing
        dependencies before attempting restoration.

        Note: This performs API calls and may be slow for content with
        many dependencies. Consider using sparingly or with caching.

        Args:
            content_dict: Content data with potential FK references
            content_type: Type of content being validated
            client: LookerClient for checking existence in destination

        Returns:
            List of missing dependency error messages (empty if all exist)

        Examples:
            >>> validator = RestorationValidator()
            >>> dashboard = {"title": "My Dashboard", "folder_id": "123"}
            >>> errors = validator.validate_dependencies(dashboard, ContentType.DASHBOARD, client)
            >>> if errors:
            ...     print(f"Missing dependencies: {errors}")
        """
        errors: list[str] = []

        # Get FK fields for this content type
        fk_fields = self.FK_FIELDS.get(content_type, [])

        for fk_field in fk_fields:
            # Skip if FK field not present or is None (optional reference)
            if fk_field not in content_dict or content_dict[fk_field] is None:
                continue

            fk_value = content_dict[fk_field]

            # Handle list of FKs (e.g., model_set.models)
            if isinstance(fk_value, list):
                for fk_id in fk_value:
                    if not self._check_dependency_exists(fk_field, fk_id, content_type, client):
                        errors.append(f"Dependency not found: {fk_field}={fk_id}")
            else:
                # Single FK reference
                if not self._check_dependency_exists(fk_field, fk_value, content_type, client):
                    errors.append(f"Dependency not found: {fk_field}={fk_value}")

        return errors

    def _check_dependency_exists(
        self, fk_field: str, fk_id: str | int, content_type: ContentType, client: LookerClient
    ) -> bool:
        """Check if a dependency exists in destination instance.

        Args:
            fk_field: Name of the foreign key field
            fk_id: ID value to check
            content_type: Parent content type (for context)
            client: LookerClient for API calls

        Returns:
            True if dependency exists, False otherwise
        """
        try:
            # Map FK field to appropriate API check
            # Note: This is a simplified implementation - full implementation
            # would need comprehensive mapping of all FK relationships

            if fk_field == "folder_id":
                client.sdk.folder(str(fk_id))
                return True
            elif fk_field == "user_id":
                client.sdk.user(str(fk_id))
                return True
            elif fk_field == "parent_id" and content_type == ContentType.FOLDER:
                client.sdk.folder(str(fk_id))
                return True
            elif fk_field == "dashboard_id":
                client.sdk.dashboard(str(fk_id))
                return True
            elif fk_field == "look_id":
                client.sdk.look(str(fk_id))
                return True
            elif fk_field == "model_name":
                # Model names are strings, check model exists
                models = client.sdk.all_lookml_models()
                return any(m.name == fk_id for m in models)
            else:
                # Unknown FK field type - assume exists (permissive)
                # Better to let API validation catch issues
                return True

        except looker_error.SDKError as e:
            # 404 means not found
            if "404" in str(e):
                return False
            # Other errors (401, 403, 500) - assume exists to avoid false negatives
            # The actual restoration will fail with proper error if access denied
            return True
        except Exception:
            # Unexpected error - assume exists to avoid blocking restoration
            return True
