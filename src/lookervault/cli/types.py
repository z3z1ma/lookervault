"""Shared type definitions and parsing utilities for CLI."""

# type: ignore[unreachable-undefined]
from enum import StrEnum

import typer

from lookervault.storage.models import ContentType


class ExtractableContentType(StrEnum):
    """CLI-friendly enumeration of extractable Looker content types.

    This enum provides string-based content type values for CLI validation.
    Unlike the backend ContentType IntEnum, this uses lowercase strings for
    better user experience in command-line arguments.

    Special value 'all' extracts all available content types.
    """

    ALL = "all"
    DASHBOARD = "dashboard"
    LOOK = "look"
    LOOKML_MODEL = "lookml_model"
    EXPLORE = "explore"
    FOLDER = "folder"
    BOARD = "board"
    USER = "user"
    GROUP = "group"
    ROLE = "role"
    PERMISSION_SET = "permission_set"
    MODEL_SET = "model_set"
    SCHEDULED_PLAN = "scheduled_plan"


# Mapping from ExtractableContentType to backend ContentType IntEnum
_TYPE_MAPPING = {
    ExtractableContentType.DASHBOARD: ContentType.DASHBOARD,
    ExtractableContentType.LOOK: ContentType.LOOK,
    ExtractableContentType.LOOKML_MODEL: ContentType.LOOKML_MODEL,
    ExtractableContentType.EXPLORE: ContentType.EXPLORE,
    ExtractableContentType.FOLDER: ContentType.FOLDER,
    ExtractableContentType.BOARD: ContentType.BOARD,
    ExtractableContentType.USER: ContentType.USER,
    ExtractableContentType.GROUP: ContentType.GROUP,
    ExtractableContentType.ROLE: ContentType.ROLE,
    ExtractableContentType.PERMISSION_SET: ContentType.PERMISSION_SET,
    ExtractableContentType.MODEL_SET: ContentType.MODEL_SET,
    ExtractableContentType.SCHEDULED_PLAN: ContentType.SCHEDULED_PLAN,
}


def parse_content_type(type_str: str) -> int:
    """Parse a single content type string to backend ContentType value.

    Args:
        type_str: Content type name (e.g., "dashboard", "dashboards", "DASHBOARD")

    Returns:
        ContentType enum integer value for backend use

    Raises:
        typer.BadParameter: If invalid content type specified
    """
    # Normalize input: lowercase and strip whitespace
    normalized = type_str.strip().lower()

    # Normalize: remove plural 's' if present (dashboards -> dashboard)
    if normalized.endswith("s"):
        normalized = normalized.rstrip("s")

    # Special case: "schedule" or "schedules" should become "scheduled_plan"
    if normalized == "schedule":
        normalized = "scheduled_plan"

    # Try to match against ExtractableContentType enum
    try:
        # Find matching enum member by value
        extractable_type = next(
            (
                et
                for et in ExtractableContentType
                if et.value == normalized and et != ExtractableContentType.ALL
            ),
            None,
        )

        if extractable_type is None:
            raise ValueError(f"No match found for {type_str}")

        # Map to backend ContentType and return
        return _TYPE_MAPPING[extractable_type].value

    except (ValueError, KeyError, StopIteration):
        # Build helpful error message with available types
        available = ", ".join(
            et.value for et in ExtractableContentType if et != ExtractableContentType.ALL
        )
        raise typer.BadParameter(
            f"Invalid content type: '{type_str}'. Available types: {available}"
        ) from None


def parse_content_types(types_str: str | None) -> list[int]:
    """Parse comma-separated content types string to backend ContentType values.

    Args:
        types_str: Comma-separated content type names (e.g., "dashboards,looks") or "all"
                  If None, defaults to all content types

    Returns:
        List of ContentType enum integer values for backend use

    Raises:
        typer.BadParameter: If invalid content type specified
    """
    if not types_str:
        # Default to all content types
        return [ct.value for ct in ContentType]

    # Split by comma and process each type
    type_names = [t.strip() for t in types_str.split(",")]
    content_types = []

    for type_name in type_names:
        # Handle special "all" case
        if type_name.lower() == ExtractableContentType.ALL.value:
            return [ct.value for ct in ContentType]

        # Parse individual type
        content_types.append(parse_content_type(type_name))

    return content_types
