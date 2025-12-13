"""Content extraction from Looker API."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any, Protocol

from looker_sdk import error as looker_error

from lookervault.exceptions import ExtractionError, RateLimitError
from lookervault.extraction.retry import retry_on_rate_limit
from lookervault.looker.client import LookerClient
from lookervault.storage.models import ContentType


class ContentExtractor(Protocol):
    """Protocol for extracting content from Looker API."""

    def extract_all(
        self,
        content_type: ContentType,
        fields: str | None = None,
        batch_size: int = 100,
        updated_after: datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Extract all content of given type.

        Args:
            content_type: Type of content to extract
            fields: Comma-separated field list (Looker API format)
            batch_size: Items per batch for paginated endpoints
            updated_after: Only return items updated after this timestamp (for incremental)

        Yields:
            Individual content items as dicts

        Raises:
            ExtractionError: If extraction fails
            RateLimitError: If rate limited (will be retried)
        """
        ...

    def extract_one(self, content_type: ContentType, content_id: str) -> dict[str, Any]:
        """Extract single content item.

        Args:
            content_type: Type of content
            content_id: Looker ID

        Returns:
            Content item as dict

        Raises:
            NotFoundError: If content doesn't exist
            ExtractionError: If extraction fails
        """
        ...

    def test_connection(self) -> bool:
        """Test Looker API connection.

        Returns:
            True if connected, False otherwise
        """
        ...


class LookerContentExtractor:
    """Looker API-based content extractor implementation."""

    def __init__(self, client: LookerClient):
        """Initialize extractor with Looker client.

        Args:
            client: LookerClient instance
        """
        self.client = client

    @retry_on_rate_limit
    def _call_api(self, method_name: str, *args, **kwargs) -> Any:
        """Call Looker SDK method with retry logic.

        Args:
            method_name: Name of SDK method to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            API response

        Raises:
            RateLimitError: If rate limited
            ExtractionError: For other API errors
        """
        try:
            method = getattr(self.client.sdk, method_name)
            return method(*args, **kwargs)
        except looker_error.SDKError as e:
            error_str = str(e)
            if "429" in error_str or "rate limit" in error_str.lower():
                raise RateLimitError(f"Rate limit exceeded: {error_str}") from e
            raise ExtractionError(f"API error calling {method_name}: {error_str}") from e

    def extract_all(
        self,
        content_type: ContentType,
        fields: str | None = None,
        batch_size: int = 100,
        updated_after: datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Extract all content of given type.

        Args:
            content_type: Type of content to extract
            fields: Comma-separated field list
            batch_size: Items per batch for paginated endpoints
            updated_after: Only return items updated after this timestamp (for incremental)

        Yields:
            Individual content items as dicts

        Raises:
            ExtractionError: If extraction fails
            RateLimitError: If rate limited
        """
        try:
            if content_type == ContentType.DASHBOARD:
                dashboards = self._call_api("all_dashboards", fields=fields)
                for dashboard in dashboards:
                    item_dict = self._sdk_object_to_dict(dashboard)
                    if self._should_include(item_dict, updated_after):
                        yield item_dict

            elif content_type == ContentType.LOOK:
                looks = self._call_api("all_looks", fields=fields)
                for look in looks:
                    item_dict = self._sdk_object_to_dict(look)
                    if self._should_include(item_dict, updated_after):
                        yield item_dict

            elif content_type == ContentType.LOOKML_MODEL:
                models = self._call_api("all_lookml_models", fields=fields)
                for model in models:
                    item_dict = self._sdk_object_to_dict(model)
                    if self._should_include(item_dict, updated_after):
                        yield item_dict

            elif content_type == ContentType.FOLDER:
                folders = self._call_api("all_folders", fields=fields)
                for folder in folders:
                    item_dict = self._sdk_object_to_dict(folder)
                    if self._should_include(item_dict, updated_after):
                        yield item_dict

            elif content_type == ContentType.BOARD:
                boards = self._call_api("all_boards", fields=fields)
                for board in boards:
                    item_dict = self._sdk_object_to_dict(board)
                    if self._should_include(item_dict, updated_after):
                        yield item_dict

            elif content_type == ContentType.USER:
                # Users require pagination
                yield from self._paginate_users(fields, batch_size, updated_after)

            elif content_type == ContentType.GROUP:
                # Groups require pagination
                yield from self._paginate_groups(fields, batch_size, updated_after)

            elif content_type == ContentType.ROLE:
                # Roles require pagination
                yield from self._paginate_roles(fields, batch_size, updated_after)

            elif content_type == ContentType.PERMISSION_SET:
                permission_sets = self._call_api("all_permission_sets", fields=fields)
                for perm_set in permission_sets:
                    item_dict = self._sdk_object_to_dict(perm_set)
                    if self._should_include(item_dict, updated_after):
                        yield item_dict

            elif content_type == ContentType.MODEL_SET:
                model_sets = self._call_api("all_model_sets", fields=fields)
                for model_set in model_sets:
                    item_dict = self._sdk_object_to_dict(model_set)
                    if self._should_include(item_dict, updated_after):
                        yield item_dict

            elif content_type == ContentType.SCHEDULED_PLAN:
                schedules = self._call_api("all_scheduled_plans", all_users=True)
                for schedule in schedules:
                    item_dict = self._sdk_object_to_dict(schedule)
                    if self._should_include(item_dict, updated_after):
                        yield item_dict

            else:
                raise ExtractionError(f"Unsupported content type: {content_type}")

        except (ExtractionError, RateLimitError):
            raise
        except Exception as e:
            raise ExtractionError(f"Failed to extract content type {content_type}: {e}") from e

    def _paginate_users(
        self, fields: str | None, batch_size: int, updated_after: datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        """Paginate through all users.

        Args:
            fields: Field filter
            batch_size: Items per page
            updated_after: Only return items updated after this timestamp

        Yields:
            User dicts
        """
        offset = 0
        while True:
            users = self._call_api("search_users", fields=fields, limit=batch_size, offset=offset)
            if not users or len(users) == 0:
                break

            for user in users:
                item_dict = self._sdk_object_to_dict(user)
                if self._should_include(item_dict, updated_after):
                    yield item_dict

            if len(users) < batch_size:
                break

            offset += batch_size

    def _paginate_groups(
        self, fields: str | None, batch_size: int, updated_after: datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        """Paginate through all groups.

        Args:
            fields: Field filter
            batch_size: Items per page
            updated_after: Only return items updated after this timestamp

        Yields:
            Group dicts
        """
        offset = 0
        while True:
            groups = self._call_api("search_groups", fields=fields, limit=batch_size, offset=offset)
            if not groups or len(groups) == 0:
                break

            for group in groups:
                item_dict = self._sdk_object_to_dict(group)
                if self._should_include(item_dict, updated_after):
                    yield item_dict

            if len(groups) < batch_size:
                break

            offset += batch_size

    def _paginate_roles(
        self, fields: str | None, batch_size: int, updated_after: datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        """Paginate through all roles.

        Args:
            fields: Field filter
            batch_size: Items per page
            updated_after: Only return items updated after this timestamp

        Yields:
            Role dicts
        """
        offset = 0
        while True:
            roles = self._call_api("search_roles", fields=fields, limit=batch_size, offset=offset)
            if not roles or len(roles) == 0:
                break

            for role in roles:
                item_dict = self._sdk_object_to_dict(role)
                if self._should_include(item_dict, updated_after):
                    yield item_dict

            if len(roles) < batch_size:
                break

            offset += batch_size

    def extract_one(self, content_type: ContentType, content_id: str) -> dict[str, Any]:
        """Extract single content item.

        Args:
            content_type: Type of content
            content_id: Looker ID

        Returns:
            Content item as dict

        Raises:
            ExtractionError: If extraction fails
        """
        try:
            if content_type == ContentType.DASHBOARD:
                item = self._call_api("dashboard", dashboard_id=content_id)
            elif content_type == ContentType.LOOK:
                item = self._call_api("look", look_id=content_id)
            elif content_type == ContentType.LOOKML_MODEL:
                item = self._call_api("lookml_model", lookml_model_name=content_id)
            elif content_type == ContentType.USER:
                item = self._call_api("user", user_id=content_id)
            elif content_type == ContentType.GROUP:
                item = self._call_api("group", group_id=content_id)
            elif content_type == ContentType.ROLE:
                item = self._call_api("role", role_id=content_id)
            else:
                raise ExtractionError(f"extract_one not supported for {content_type}")

            return self._sdk_object_to_dict(item)
        except Exception as e:
            raise ExtractionError(f"Failed to extract {content_type} {content_id}: {e}") from e

    def test_connection(self) -> bool:
        """Test Looker API connection.

        Returns:
            True if connected, False otherwise
        """
        try:
            status = self.client.test_connection()
            return status.connected and status.authenticated
        except Exception:
            return False

    @staticmethod
    def _sdk_object_to_dict(obj: Any) -> dict[str, Any]:
        """Convert SDK object to dictionary.

        Args:
            obj: SDK model object

        Returns:
            Dictionary representation
        """
        # Looker SDK objects have __dict__ attribute
        # Filter out None values and private attributes
        return {k: v for k, v in obj.__dict__.items() if v is not None and not k.startswith("_")}

    @staticmethod
    def _should_include(item_dict: dict[str, Any], updated_after: datetime | None) -> bool:
        """Check if item should be included based on updated_after timestamp.

        Args:
            item_dict: Item dictionary from Looker API
            updated_after: Timestamp filter (None means include all)

        Returns:
            True if item should be included, False otherwise
        """
        if updated_after is None:
            return True

        # Check if item has updated_at field
        updated_at_str = item_dict.get("updated_at")
        if not updated_at_str:
            # If no updated_at, include the item
            return True

        try:
            updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            return updated_at > updated_after
        except (ValueError, AttributeError):
            # If parsing fails, include the item to be safe
            return True
