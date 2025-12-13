"""Content serialization using msgpack format."""

from typing import Any, Protocol

import msgspec

from lookervault.exceptions import SerializationError


class ContentSerializer(Protocol):
    """Protocol for serializing/deserializing Looker content."""

    def serialize(self, data: dict[str, Any] | list[Any]) -> bytes:
        """Serialize Python object to bytes.

        Args:
            data: Python dict/list from Looker API

        Returns:
            Serialized bytes for BLOB storage

        Raises:
            SerializationError: If serialization fails
        """
        ...

    def deserialize(self, blob: bytes) -> dict[str, Any] | list[Any]:
        """Deserialize bytes to Python object.

        Args:
            blob: Binary data from storage

        Returns:
            Original Python dict/list

        Raises:
            SerializationError: If deserialization fails
        """
        ...

    def validate(self, blob: bytes) -> bool:
        """Validate that blob can be deserialized.

        Args:
            blob: Binary data to validate

        Returns:
            True if valid, False otherwise
        """
        ...


class MsgpackSerializer:
    """MessagePack-based content serializer using msgspec library."""

    def serialize(self, data: dict[str, Any] | list[Any]) -> bytes:
        """Serialize Python object to msgpack bytes.

        Args:
            data: Python dict/list from Looker API

        Returns:
            Serialized msgpack bytes

        Raises:
            SerializationError: If serialization fails
        """
        try:
            return msgspec.msgpack.encode(data)
        except Exception as e:
            raise SerializationError(f"Failed to serialize content: {e}") from e

    def deserialize(self, blob: bytes) -> dict[str, Any] | list[Any]:
        """Deserialize msgpack bytes to Python object.

        Args:
            blob: Binary msgpack data

        Returns:
            Deserialized Python dict/list

        Raises:
            SerializationError: If deserialization fails
        """
        try:
            return msgspec.msgpack.decode(blob)
        except Exception as e:
            raise SerializationError(f"Failed to deserialize content: {e}") from e

    def validate(self, blob: bytes) -> bool:
        """Validate that blob can be deserialized.

        Args:
            blob: Binary data to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            msgspec.msgpack.decode(blob)
            return True
        except Exception:
            return False
