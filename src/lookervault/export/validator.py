from __future__ import annotations

from pathlib import Path
from typing import Any

from looker_sdk import models40 as looker_models
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from lookervault.exceptions import ValidationError


class YamlValidator:
    """Multi-stage validator for YAML content.

    Provides validation pipeline:
    1. Syntax validation (YAML parsing)
    2. Schema validation (future: Pydantic models)
    3. SDK conversion validation (future: Looker SDK types)
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
        """Validate _metadata section in YAML content.

        Args:
            data: Parsed YAML dictionary

        Returns:
            Metadata section dictionary

        Raises:
            ValidationError: If _metadata section is missing or invalid
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
        """Validate individual fields with Looker SDK type hints.

        Args:
            field_name: Name of the field being validated
            field_value: Value to validate
            file_path: Optional file path for detailed error reporting
            content_type: Optional content type for more specific validation

        Returns:
            List of error messages (empty if no validation errors)
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
        """Enhanced content structure validation with detailed error reporting.

        Args:
            data: Parsed YAML dictionary
            content_type: Expected content type (e.g., "DASHBOARD", "LOOK")
            file_path: Optional file path for error reporting

        Returns:
            Dictionary of validation errors, keyed by error type
            Empty dictionary if no errors found

        Raises:
            ValidationError: If critical structural validation fails
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
