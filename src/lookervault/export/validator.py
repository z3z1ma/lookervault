from __future__ import annotations

from pathlib import Path
from typing import Any

from looker_sdk import models40 as looker_models
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from lookervault.exceptions import ValidationError


class YamlValidator:
    """Multi-stage validator for YAML content with categorized error reporting.

    The validator performs multiple validation stages and categorizes errors to help
    users understand and fix issues efficiently.

    **Validation Pipeline:**
    1. Syntax validation (YAML parsing)
    2. Schema validation (future: Pydantic models)
    3. SDK conversion validation (future: Looker SDK types)

    **Error Categories:**

    The validator uses two main error categories to help users prioritize fixes:

    1. **Structure Errors** (``structure_errors``):
       Critical structural problems that prevent content from being processed.
       These must be fixed before the content can be imported.

       Examples:
       - Missing required ``_metadata`` section
       - Content type mismatch (e.g., file claims to be DASHBOARD but metadata says LOOK)
       - Missing required fields (e.g., dashboard missing ``id`` or ``title``)
       - Invalid metadata structure (e.g., ``_metadata`` is not a dictionary)

       **User Impact:** High - Content cannot be processed until these are fixed.

    2. **Field Errors** (``field_errors``):
       Issues with individual field values that may prevent proper content display
       or functionality. These are validation failures for specific field values
       rather than structural problems.

       Examples:
       - ``title`` field is empty or exceeds 255 characters
       - Dashboard ``filters`` field is not a dictionary
       - Look ``model`` field is not a string
       - Fields with incorrect data types

       **User Impact:** Medium to High - Content may import but fail to work correctly.

    **Error Categorization Logic:**

    Errors are categorized based on their nature:

    - **Structure Errors**: Missing sections, type mismatches at the section level,
      required fields that are absent, and structural incompatibilities that prevent
      basic processing.

    - **Field Errors**: Individual field validation failures where the structure is
      correct but field values don't meet requirements (type, format, length, etc.).

    **Usage Pattern:**

    The ``validate_content_structure()`` method returns a dictionary with categorized
    errors that can be processed separately::

        errors = validator.validate_content_structure(data, "DASHBOARD")

        # Handle critical structure errors first
        if errors["structure_errors"]:
            print("CRITICAL: Fix these structural issues first:")
            for error in errors["structure_errors"]:
                print(f"  - {error}")

        # Then handle field-level errors
        if errors["field_errors"]:
            print("ISSUES: Fix these field-level problems:")
            for error in errors["field_errors"]:
                print(f"  - {error}")
    """

    def __init__(self) -> None:
        """Initialize validator with YAML parser."""
        self.yaml = YAML()

    def validate_syntax(self, yaml_content: str, file_path: Path | None = None) -> dict[str, Any]:
        """Validate YAML syntax and parse to dict.

        Args:
            yaml_content: YAML string to validate
            file_path: Optional file path for error messages

        Returns:
            Parsed dictionary if valid

        Raises:
            ValidationError: If YAML syntax is invalid
        """
        try:
            data = self.yaml.load(yaml_content)
            if not isinstance(data, dict):
                file_info = f" in {file_path}" if file_path else ""
                raise ValidationError(
                    f"YAML must parse to dictionary, got {type(data).__name__}{file_info}"
                )
            return data
        except YAMLError as e:
            file_info = f" in {file_path}" if file_path else ""
            raise ValidationError(f"Invalid YAML syntax{file_info}: {e}") from e

    def validate_file(self, yaml_file: Path) -> dict[str, Any]:
        """Validate YAML file.

        Args:
            yaml_file: Path to YAML file

        Returns:
            Parsed dictionary if valid

        Raises:
            ValidationError: If file doesn't exist or YAML is invalid
            FileNotFoundError: If file doesn't exist
        """
        if not yaml_file.exists():
            raise FileNotFoundError(f"YAML file not found: {yaml_file}")

        with yaml_file.open("r") as f:
            content = f.read()

        return self.validate_syntax(content, yaml_file)

    def validate_metadata_section(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate the required _metadata section in YAML content.

        The ``_metadata`` section is mandatory for all YAML files exported by LookerVault.
        It contains critical information about the content including database ID,
        content type, export timestamp, size, and checksum.

        **Required Fields:**

        - ``db_id``: Database/unique identifier for the content
        - ``content_type``: Type of content (e.g., "DASHBOARD", "LOOK")
        - ``exported_at``: ISO timestamp of when content was exported
        - ``content_size``: Size in bytes of the original content
        - ``checksum``: Checksum/hash for data integrity verification

        **Error Categorization:**

        Errors from this method (missing or invalid ``_metadata``) are classified as
        ``structure_errors`` because they represent critical structural problems that
        prevent content processing. When called from ``validate_content_structure``,
        exceptions raised here are caught and converted to structure error messages.

        Args:
            data: Parsed YAML dictionary to validate

        Returns:
            The metadata section dictionary if validation succeeds

        Raises:
            ValidationError: If ``_metadata`` section is missing, not a dictionary,
                or missing required fields. These errors are caught by
                ``validate_content_structure`` and converted to structure_errors.

        **Example:**

            >>> data = {
            ...     "title": "My Dashboard",
            ...     "_metadata": {
            ...         "db_id": "123",
            ...         "content_type": "DASHBOARD",
            ...         "exported_at": "2025-12-14T10:00:00",
            ...         "content_size": 1024,
            ...         "checksum": "sha256:abc123",
            ...     },
            ... }
            >>> metadata = validator.validate_metadata_section(data)
            >>> print(metadata["content_type"])
            "DASHBOARD"
        """
        if "_metadata" not in data:
            raise ValidationError("Missing required _metadata section in YAML content")

        metadata = data["_metadata"]
        if not isinstance(metadata, dict):
            raise ValidationError(f"_metadata must be dictionary, got {type(metadata).__name__}")

        # Validate required fields
        required_fields = ["db_id", "content_type", "exported_at", "content_size", "checksum"]
        missing = [field for field in required_fields if field not in metadata]

        if missing:
            raise ValidationError(f"Missing required fields in _metadata: {', '.join(missing)}")

        return metadata

    def validate_field(
        self,
        field_name: str,
        field_value: Any,
        file_path: Path | None = None,
        content_type: str | None = None,
    ) -> list[str]:
        """Validate individual field values with Looker SDK type hints.

        This method performs field-level validation and returns error messages that
        are collected into the ``field_errors`` category by ``validate_content_structure``.
        These errors represent issues with specific field values rather than structural
        problems.

        **Validated Fields:**

        Common fields:
        - ``title``: Must be a non-empty string, max 255 characters

        Dashboard-specific (``content_type="DASHBOARD"``):
        - ``filters``: Must be a dictionary if present

        Look-specific (``content_type="LOOK"``):
        - ``model``: Must be a string

        **Error Messages:**

        Returned error messages include the file path when provided, making it easy
        to locate the source of the problem. Errors are returned as a list to allow
        multiple validation issues for a single field.

        Args:
            field_name: Name of the field being validated (e.g., "title", "model")
            field_value: Value to validate (can be any type)
            file_path: Optional file path to include in error messages for context
            content_type: Optional content type for field-specific validation rules

        Returns:
            List of validation error messages. Empty list if the field value passes
            all validation rules. Each error message includes context about what
            went wrong and the file path (if provided).

        **Example:**

            >>> errors = validator.validate_field("title", "", Path("dashboard.yaml"), "DASHBOARD")
            >>> print(errors)
            ["Field 'title' cannot be empty in dashboard.yaml"]
        """
        errors = []
        file_info = f" in {file_path}" if file_path else ""

        # Common validation rules
        if field_name == "title":
            if not isinstance(field_value, str):
                errors.append(
                    f"Field 'title' must be a string, got {type(field_value).__name__}{file_info}"
                )
            if len(field_value.strip()) == 0:
                errors.append(f"Field 'title' cannot be empty{file_info}")
            if len(field_value) > 255:  # Common reasonable limit
                errors.append(f"Field 'title' exceeds 255 characters{file_info}")

        # Content-type specific validations
        if content_type == "DASHBOARD":
            # Add specific dashboard validations
            if field_name == "filters" and field_value is not None:
                if not isinstance(field_value, dict):
                    errors.append(
                        f"Dashboard filters must be a dictionary, got {type(field_value).__name__}{file_info}"
                    )

        if content_type == "LOOK":
            # Add specific look validations
            if field_name == "model":
                if not isinstance(field_value, str):
                    errors.append(
                        f"Look model must be a string, got {type(field_value).__name__}{file_info}"
                    )

        return errors

    def validate_content_structure(
        self, data: dict[str, Any], content_type: str, file_path: Path | None = None
    ) -> dict[str, list[str]]:
        """Enhanced content structure validation with categorized error reporting.

        This method performs comprehensive validation and categorizes errors into
        two types: structure_errors (critical structural problems) and field_errors
        (individual field value issues). This categorization helps users prioritize
        which errors to fix first.

        **Error Categories Returned:**

        - ``structure_errors``: Critical problems that prevent content processing.
          Examples include missing required sections, content type mismatches, or
          absent required fields. These must be fixed before import.

        - ``field_errors``: Issues with specific field values. Examples include
          empty titles, incorrect data types, or fields exceeding length limits.
          These should be fixed to ensure content works correctly after import.

        **Validation Order:**

        1. Metadata section validation (required fields, structure)
        2. Content type verification (matches expected type)
        3. Required field presence check
        4. Individual field value validation

        Args:
            data: Parsed YAML dictionary to validate
            content_type: Expected content type (e.g., "DASHBOARD", "LOOK")
            file_path: Optional file path for detailed error reporting in messages

        Returns:
            Dictionary with two keys:
            - ``structure_errors``: List of critical structural error messages
            - ``field_errors``: List of field-level validation error messages

            Returns empty lists for both keys if no errors found.

        Raises:
            ValidationError: Not raised directly; all errors are collected and
                returned in the categorized dictionary for caller to handle.

        **Example:**

            >>> validator = YamlValidator()
            >>> errors = validator.validate_content_structure(
            ...     data, "DASHBOARD", Path("/path/to/file.yaml")
            ... )
            >>> if errors["structure_errors"]:
            ...     print(f"Critical: {errors['structure_errors']}")
            >>> if errors["field_errors"]:
            ...     print(f"Fix: {errors['field_errors']}")
        """
        all_errors: dict[str, list[str]] = {
            "structure_errors": [],
            "field_errors": [],
        }

        # Validate metadata section first
        try:
            metadata = self.validate_metadata_section(data)
        except ValidationError as e:
            all_errors["structure_errors"].append(str(e))
            return all_errors

        # Verify content_type matches
        if metadata["content_type"] != content_type:
            all_errors["structure_errors"].append(
                f"Content type mismatch: expected {content_type}, got {metadata['content_type']}"
            )

        # Required field validation
        required_fields = {
            "DASHBOARD": ["id", "title", "elements"],
            "LOOK": ["id", "title", "query"],
        }

        for field in required_fields.get(content_type, ["id", "title"]):
            if field not in data:
                all_errors["structure_errors"].append(
                    f"{content_type} missing required '{field}' field"
                )

        # Detailed field validation
        for field_name, field_value in data.items():
            if field_name not in ["_metadata", "id"]:
                field_errors = self.validate_field(
                    field_name,
                    field_value,
                    file_path=file_path,
                    content_type=content_type,
                )
                all_errors["field_errors"].extend(field_errors)

        return all_errors

    def validate_query(
        self,
        query: dict[str, Any],
        file_path: Path | None = None,
        content_type: str | None = None,
    ) -> list[str]:
        """
        Validate Looker Query definition against SDK requirements.

        Args:
            query: Dictionary representing a Looker query definition
            file_path: Optional file path for error reporting
            content_type: Optional context for more specific validation

        Returns:
            List of validation error messages
        """
        # Required fields for a valid Looker query
        required_query_fields = ["model", "view", "fields"]
        validation_errors: list[str] = []
        file_info = f" in {file_path}" if file_path else ""

        # Check for missing required fields
        missing_fields = [field for field in required_query_fields if field not in query]
        if missing_fields:
            validation_errors.append(
                f"Missing required query fields: {', '.join(missing_fields)}{file_info}"
            )
        else:
            # Only validate structure if required fields are present
            try:
                # Validate query structure using Looker SDK models
                # This will raise an exception for invalid structures
                # Note: We've already verified model and view fields exist above
                looker_models.WriteQuery(**query)  # type: ignore[misc]
            except Exception as e:
                validation_errors.append(f"Query validation failed{file_info}: {str(e)}")

        # Content-type specific query validations
        if content_type == "DASHBOARD":
            # Additional dashboard-specific query validation
            recommended_dashboard_fields = ["pivots", "filters", "sorts"]
            missing_recommended_fields = [
                field for field in recommended_dashboard_fields if field not in query
            ]
            if missing_recommended_fields:
                validation_errors.append(
                    f"Missing recommended dashboard query fields: {', '.join(missing_recommended_fields)}{file_info}"
                )

        return validation_errors
