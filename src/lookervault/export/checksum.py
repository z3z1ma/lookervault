"""Checksum utilities for export integrity validation.

This module provides SHA-256 checksum calculation for YAML exports to detect
modifications and ensure integrity.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from lookervault.constants import CHUNK_SIZE_SMALL


def compute_file_checksum(file_path: Path) -> str:
    """Compute SHA-256 checksum of a single file.

    Args:
        file_path: Path to file

    Returns:
        SHA-256 hexadecimal digest

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        # Read in chunks to handle large files
        while chunk := f.read(CHUNK_SIZE_SMALL):
            hasher.update(chunk)

    return hasher.hexdigest()


def compute_export_checksum(output_dir: Path) -> str:
    """Compute SHA-256 hash of all YAML files in export directory.

    Processes files in sorted order for deterministic results.

    Args:
        output_dir: Root directory of export

    Returns:
        SHA-256 hexadecimal digest of all YAML files combined

    Raises:
        FileNotFoundError: If output_dir doesn't exist
    """
    if not output_dir.exists():
        raise FileNotFoundError(f"Export directory not found: {output_dir}")

    hasher = hashlib.sha256()

    # Collect all YAML file paths in sorted order for determinism
    yaml_files = sorted(output_dir.rglob("*.yaml"))

    for yaml_file in yaml_files:
        # Hash relative path (for directory structure verification)
        rel_path = yaml_file.relative_to(output_dir)
        hasher.update(str(rel_path).encode("utf-8"))

        # Hash file contents
        with yaml_file.open("rb") as f:
            while chunk := f.read(CHUNK_SIZE_SMALL):
                hasher.update(chunk)

    return hasher.hexdigest()


def compute_content_checksum(data: bytes) -> str:
    """Compute SHA-256 checksum of raw content data.

    Args:
        data: Raw bytes to hash

    Returns:
        SHA-256 hexadecimal digest
    """
    return hashlib.sha256(data).hexdigest()


def verify_checksum(expected: str, actual: str) -> bool:
    """Verify checksum matches expected value.

    Args:
        expected: Expected checksum
        actual: Actual checksum

    Returns:
        True if checksums match, False otherwise
    """
    return expected.lower() == actual.lower()
