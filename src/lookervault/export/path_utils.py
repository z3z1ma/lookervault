"""Path sanitization utilities for cross-platform filesystem compatibility.

This module provides utilities for sanitizing Looker content names for safe
filesystem usage, handling invalid characters, path length limits, and collisions.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from pathlib import Path

from pathvalidate import Platform, sanitize_filename


def sanitize_folder_name(name: str, max_length: int = 255) -> str:
    """Sanitize folder name for filesystem use.

    Args:
        name: Original folder name from Looker
        max_length: Maximum length in bytes (default: 255 for most filesystems)

    Returns:
        Sanitized folder name safe for cross-platform use

    Raises:
        ValueError: If name is empty after sanitization
    """
    # Unicode normalization (NFC - canonical composition)
    normalized = unicodedata.normalize("NFC", name)

    # Platform sanitization (most restrictive - Windows)
    safe_name = sanitize_filename(
        normalized,
        platform=Platform.WINDOWS,  # Most restrictive for max compatibility
        max_len=max_length,
        replacement_text="_",  # Replace invalid chars with underscore
    )

    if not safe_name or not safe_name.strip():
        raise ValueError(f"Folder name '{name}' resulted in empty string after sanitization")

    return safe_name


class PathCollisionResolver:
    """Resolves filename collisions with numeric suffixes.

    When multiple items have names that sanitize to the same filename,
    this resolver appends numeric suffixes like (2), (3), etc.
    """

    def __init__(self) -> None:
        """Initialize collision resolver with empty usage tracking."""
        # Track usage count per (directory, base_name)
        # Use lowercase keys for case-insensitive filesystems
        self.usage_counts: dict[tuple[str, str], int] = defaultdict(int)

    def resolve(self, directory: Path, filename: str) -> Path:
        """Resolve collision by appending numeric suffix if needed.

        Args:
            directory: Parent directory path
            filename: Desired filename (may collide with existing)

        Returns:
            Full path with numeric suffix if collision detected

        Example:
            First call:  resolve(/export, "dashboard.yaml") -> /export/dashboard.yaml
            Second call: resolve(/export, "dashboard.yaml") -> /export/dashboard (2).yaml
            Third call:  resolve(/export, "dashboard.yaml") -> /export/dashboard (3).yaml
        """
        # Normalize directory to string for dict key
        dir_key = str(directory)

        # Use lowercase filename for case-insensitive comparison
        # (Windows and macOS filesystems are case-insensitive)
        filename_key = filename.lower()

        # Track usage
        self.usage_counts[(dir_key, filename_key)] += 1
        count = self.usage_counts[(dir_key, filename_key)]

        if count == 1:
            # First occurrence - no suffix needed
            return directory / filename

        # Collision detected - add numeric suffix
        stem = Path(filename).stem  # Filename without extension
        suffix = Path(filename).suffix  # Extension (e.g., ".yaml")

        # Append suffix: "name (2).yaml"
        suffixed_name = f"{stem} ({count}){suffix}"
        return directory / suffixed_name

    def reset(self) -> None:
        """Reset collision tracking (useful for testing)."""
        self.usage_counts.clear()


def truncate_path_component(name: str, max_bytes: int = 255) -> str:
    """Truncate path component to maximum byte length.

    Handles UTF-8 encoding properly to avoid cutting in middle of multi-byte characters.

    Args:
        name: Path component to truncate
        max_bytes: Maximum byte length (default: 255)

    Returns:
        Truncated name within byte limit
    """
    # Check if already within limit
    if len(name.encode("utf-8")) <= max_bytes:
        return name

    # Truncate respecting UTF-8 boundaries
    # Decode with 'ignore' to drop incomplete multi-byte sequences
    truncated_bytes = name.encode("utf-8")[:max_bytes]
    truncated = truncated_bytes.decode("utf-8", errors="ignore")

    return truncated


def validate_path_length(full_path: Path, max_path_length: int = 260) -> bool:
    """Validate total path length doesn't exceed platform limit.

    Args:
        full_path: Complete path to validate
        max_path_length: Maximum total path length (default: 260 for Windows MAX_PATH)

    Returns:
        True if path is within limit, False otherwise
    """
    path_str = str(full_path)
    return len(path_str) <= max_path_length
