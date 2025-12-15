"""YAML serialization for Looker content export/import.

This module provides YAML serialization using ruamel.yaml for round-trip preservation
of comments, formatting, and content structure.
"""

from __future__ import annotations

import io
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class YamlSerializer:
    """Serializer for converting between Python dicts and YAML format.

    Uses ruamel.yaml for YAML 1.2 compliance and round-trip preservation of
    comments, formatting, and structure.
    """

    def __init__(self) -> None:
        """Initialize YAML serializer with ruamel.yaml configuration."""
        self.yaml = YAML()
        self.yaml.preserve_quotes = True  # Keep original quote style
        self.yaml.default_flow_style = False  # Use block style (readable)
        self.yaml.indent(mapping=2, sequence=2, offset=2)  # Consistent indentation
        self.yaml.width = 100  # Line wrapping (matches ruff config)

    def serialize(self, data: dict[str, Any]) -> str:
        """Convert Python dict to YAML string.

        Args:
            data: Python dictionary to serialize

        Returns:
            YAML string representation

        Raises:
            ValueError: If data cannot be serialized to YAML
        """
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")

        try:
            stream = io.StringIO()
            self.yaml.dump(data, stream)
            return stream.getvalue()
        except YAMLError as e:
            raise ValueError(f"Failed to serialize data to YAML: {e}") from e

    def deserialize(self, yaml_str: str) -> dict[str, Any]:
        """Convert YAML string to Python dict.

        Args:
            yaml_str: YAML string to deserialize

        Returns:
            Python dictionary

        Raises:
            ValueError: If YAML string is invalid or cannot be parsed
        """
        if not isinstance(yaml_str, str):
            raise ValueError(f"Expected str, got {type(yaml_str).__name__}")

        try:
            data = self.yaml.load(yaml_str)
            if not isinstance(data, dict):
                raise ValueError(f"YAML must deserialize to dict, got {type(data).__name__}")
            return data
        except YAMLError as e:
            raise ValueError(f"Failed to parse YAML: {e}") from e

    def validate(self, yaml_str: str) -> bool:
        """Validate YAML syntax without full parsing.

        Args:
            yaml_str: YAML string to validate

        Returns:
            True if valid YAML syntax, False otherwise
        """
        try:
            self.yaml.load(yaml_str)
            return True
        except YAMLError:
            return False

    def serialize_to_file(self, data: dict[str, Any], file_path: str | Any) -> None:
        """Serialize data directly to file (streaming I/O for large files - T068).

        Args:
            data: Python dictionary to serialize
            file_path: Path to output file

        Raises:
            ValueError: If data cannot be serialized to YAML
        """
        from pathlib import Path

        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")

        try:
            # Stream directly to file without intermediate string
            path = Path(file_path)
            with path.open("w", encoding="utf-8") as f:
                self.yaml.dump(data, f)
        except YAMLError as e:
            raise ValueError(f"Failed to serialize data to YAML: {e}") from e
        except OSError as e:
            raise ValueError(f"Failed to write to file {file_path}: {e}") from e

    def deserialize_from_file(self, file_path: str | Any) -> dict[str, Any]:
        """Deserialize YAML directly from file (streaming I/O for large files - T068).

        Args:
            file_path: Path to YAML file

        Returns:
            Python dictionary

        Raises:
            ValueError: If YAML file is invalid or cannot be parsed
        """
        from pathlib import Path

        try:
            # Stream directly from file without loading entire contents
            path = Path(file_path)
            with path.open(encoding="utf-8") as f:
                data = self.yaml.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"YAML must deserialize to dict, got {type(data).__name__}")
            return data
        except YAMLError as e:
            raise ValueError(f"Failed to parse YAML from {file_path}: {e}") from e
        except OSError as e:
            raise ValueError(f"Failed to read file {file_path}: {e}") from e
