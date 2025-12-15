"""Timestamp parsing utilities for handling various datetime formats from Looker API."""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def parse_timestamp(
    timestamp_value: Any,
    field_name: str,
    item_id: str | None = None,
    default: datetime | None = None,
) -> datetime:
    """Parse timestamp from various formats.

    Handles:
    - ISO format strings (with or without 'Z')
    - datetime objects (pass-through)
    - Unix timestamps (int/float)
    - Invalid/missing values (returns default or current time)

    Args:
        timestamp_value: The timestamp value to parse (can be str, datetime, int, float, or None)
        field_name: Name of the field being parsed (for logging)
        item_id: Optional ID of the item being processed (for logging)
        default: Default datetime to return if parsing fails or value is missing.
                If None, uses current UTC time.

    Returns:
        Parsed datetime object with UTC timezone

    Examples:
        >>> parse_timestamp("2024-01-01T12:00:00Z", "created_at")
        datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)

        >>> parse_timestamp(1704110400, "updated_at")
        datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)

        >>> parse_timestamp(None, "created_at")
        datetime.datetime(...)  # Current UTC time
    """
    if default is None:
        default = datetime.now(UTC)

    if not timestamp_value:
        return default

    try:
        if isinstance(timestamp_value, str):
            return datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
        elif isinstance(timestamp_value, datetime):
            return timestamp_value
        elif isinstance(timestamp_value, int | float):
            return datetime.fromtimestamp(timestamp_value, tz=UTC)
        else:
            logger.warning(
                f"Unexpected type for {field_name}: {type(timestamp_value).__name__} = {timestamp_value}"
            )
            return default
    except (ValueError, AttributeError, TypeError) as e:
        context = f" (item: {item_id})" if item_id else ""
        logger.warning(
            f"Could not parse {field_name} (type: {type(timestamp_value).__name__}) "
            f"'{timestamp_value}'{context}: {e}"
        )
        return default
