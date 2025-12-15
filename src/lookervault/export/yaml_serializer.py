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
