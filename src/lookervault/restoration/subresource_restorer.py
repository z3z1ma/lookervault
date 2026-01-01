"""Sub-resource restoration for nested content structures.

This module provides infrastructure for restoring nested sub-resources within
parent content items (e.g., dashboard elements, filters, and layouts within dashboards).

Three-Phase Restoration Strategy
=================================

The restoration follows a three-phase approach to ensure safe, idempotent restoration
of nested sub-resources while preserving data integrity and supporting partial failure recovery.

Phase 1: Discovery (Fetch Existing State)
------------------------------------------
**Purpose**: Establish the current state of sub-resources in the destination instance.

**What happens**:
- Fetch all existing sub-resources of the current type from the destination instance
- Build a mapping by ID for efficient lookup during categorization
- Example: For dashboard filters, call `sdk.dashboard_dashboard_filters(dashboard_id)`

**Why this phase is needed**:
- We cannot determine CREATE/UPDATE/DELETE operations without knowing what exists
- Same-instance restoration matches items by ID (not by name or other attributes)
- Avoids duplicate creation errors and ensures idempotent restores

**Error handling**:
- If the fetch fails, the entire sub-resource type restoration is aborted
- The error is logged and added to the result object for DLQ tracking
- Other sub-resource types (e.g., elements vs filters) are unaffected

Phase 2: Categorization (Determine Operations)
-----------------------------------------------
**Purpose**: Classify each backup sub-resource into CREATE, UPDATE, or DELETE operations.

**What happens**:
- Extract IDs from backup items (e.g., `{f.get("id") for f in backup_filters}`)
- Compare backup IDs against existing destination IDs from Phase 1
- Categorize each item:
  * **CREATE**: Item exists in backup but not in destination (new sub-resource)
  * **UPDATE**: Item exists in both backup and destination (modify existing)
  * **DELETE**: Item exists in destination but not in backup (orphan cleanup)

**Why this phase is needed**:
- Enables precise synchronization between backup and destination
- Prevents accidental data loss by explicitly categorizing operations
- Supports incremental updates (only modified items need API calls)
- Enables cleanup of orphaned items created outside LookerVault

**Error handling**:
- Categorization is deterministic and has no external dependencies
- Errors during categorization indicate data integrity issues (e.g., missing IDs)
- Items with missing IDs are logged and skipped with a warning

Phase 3: Execution (Apply Changes in Dependency Order)
-------------------------------------------------------
**Purpose**: Execute the categorized operations in the correct dependency order.

**What happens**:
- Execute operations sequentially within each sub-resource type
- For dashboard sub-resources, the dependency order is:
  1. Filters (no dependencies)
  2. Elements (may reference filters)
  3. Layouts (reference elements via layout components)
  4. Layout components (positioning for elements within layouts)
- For each operation type (UPDATE/CREATE/DELETE):
  * Call the appropriate SDK method (create/update/delete)
  * Track success/failure in result counters
  * Record ID mappings for CREATE operations (old_id -> new_id)
  * Continue on individual item failures (best-effort strategy)

**Why this phase is needed**:
- Dependency order prevents foreign key constraint violations
- Best-effort error handling maximizes successful restoration
- ID mapping tracks changes when Looker assigns new IDs on CREATE
- Granular error tracking enables DLQ processing for manual review

**Error handling**:
- Individual item failures are logged but do NOT stop the restoration
- Failed items increment `error_count` and append to `errors` list
- Successful operations continue, maximizing restoration completeness
- Rate limit errors (429) trigger automatic retries with exponential backoff
- SDK errors are wrapped in domain-specific exceptions (RestorationError, RateLimitError)

Best-Effort Error Handling
---------------------------
The three-phase strategy uses "best-effort" error handling to maximize successful
restoration:

1. **Phase failures are isolated**: Failure in one sub-resource type (e.g., filters)
   does not prevent restoration of other types (e.g., elements).

2. **Item failures are isolated**: Failure to restore one item (e.g., filter #123)
   does not prevent restoration of other items (e.g., filter #456).

3. **Errors are aggregated**: All errors are collected in the result object
   for comprehensive reporting and DLQ processing.

4. **Partial success is possible**: A restoration with 10 failures out of 100 items
   is considered a partial success, not a total failure.

This approach is particularly important for:
- Large dashboards with hundreds of elements
- Partial corruption in backup data
- Temporary API failures or rate limiting
- Permission issues on specific items only
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from looker_sdk import error as looker_error
from looker_sdk import models40 as looker_models

from lookervault.exceptions import RateLimitError, RestorationError
from lookervault.extraction.rate_limiter import AdaptiveRateLimiter
from lookervault.extraction.retry import retry_on_rate_limit
from lookervault.looker.client import LookerClient
from lookervault.utils import log_and_return_error

logger = logging.getLogger(__name__)


# Read-only field definitions for dashboard sub-resources
# These fields are returned by GET requests but not accepted by Write* models

READ_ONLY_FILTER_FIELDS: set[str] = {
    "can",
    "created_at",
    "updated_at",
    "id",  # ID is handled separately (removed on CREATE, kept on UPDATE)
    "dashboard_id",  # Set explicitly in create/update methods
    "field",  # Read-only field containing computed field info
}

READ_ONLY_ELEMENT_FIELDS: set[str] = {
    "can",
    "created_at",
    "updated_at",
    "id",  # ID is handled separately
    "dashboard_id",  # Set explicitly in create/update methods
    "edit_uri",
    "alert_count",
    "body_text_as_html",
    "note_text_as_html",
    "subtitle_text_as_html",
    "title_text_as_html",
    "refresh_interval_to_i",
}

READ_ONLY_LAYOUT_FIELDS: set[str] = {
    "can",
    "created_at",
    "updated_at",
    "id",  # ID is handled separately
    "dashboard_id",  # Set explicitly in create/update methods
    "dashboard_layout_components",  # Nested components handled separately
}

READ_ONLY_LAYOUT_COMPONENT_FIELDS: set[str] = {
    "can",
    "created_at",
    "updated_at",
    "deleted",
    "element_title",
    "element_title_hidden",
    "vis_type",
}


@dataclass
class SubResourceResult:
    """Results for restoring a single sub-resource type.

    Tracks counts and errors for CREATE/UPDATE/DELETE operations on
    a specific sub-resource type (e.g., dashboard_filter, dashboard_element).
    """

    resource_type: str  # e.g., "dashboard_filter", "dashboard_element"
    created_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)
    id_mappings: dict[str, str] = field(default_factory=dict)  # old_id -> new_id (for CREATE)


@dataclass
class SubResourceRestorationResult:
    """Aggregated results for all sub-resources of a parent item.

    Contains separate SubResourceResult objects for each sub-resource type
    (filters, elements, layouts) and provides aggregate totals.
    """

    parent_id: str
    filters: SubResourceResult = field(
        default_factory=lambda: SubResourceResult("dashboard_filter")
    )
    elements: SubResourceResult = field(
        default_factory=lambda: SubResourceResult("dashboard_element")
    )
    layouts: SubResourceResult = field(
        default_factory=lambda: SubResourceResult("dashboard_layout")
    )

    def merge(self, sub_result: SubResourceResult) -> None:
        """Merge a sub-resource result into the aggregated result.

        Args:
            sub_result: SubResourceResult to merge (filters, elements, or layouts)
        """
        if sub_result.resource_type == "dashboard_filter":
            self.filters = sub_result
        elif sub_result.resource_type == "dashboard_element":
            self.elements = sub_result
        elif sub_result.resource_type == "dashboard_layout":
            self.layouts = sub_result

    @property
    def total_created(self) -> int:
        """Total items created across all sub-resource types."""
        return self.filters.created_count + self.elements.created_count + self.layouts.created_count

    @property
    def total_updated(self) -> int:
        """Total items updated across all sub-resource types."""
        return self.filters.updated_count + self.elements.updated_count + self.layouts.updated_count

    @property
    def total_deleted(self) -> int:
        """Total items deleted across all sub-resource types."""
        return self.filters.deleted_count + self.elements.deleted_count + self.layouts.deleted_count

    @property
    def total_errors(self) -> int:
        """Total errors across all sub-resource types."""
        return self.filters.error_count + self.elements.error_count + self.layouts.error_count

    @property
    def all_errors(self) -> list[str]:
        """Concatenated list of all errors across sub-resource types."""
        return self.filters.errors + self.elements.errors + self.layouts.errors


class SubResourceRestorer(Protocol):
    """Protocol for restoring sub-resources of parent content items.

    Implementations handle content-type-specific sub-resource restoration
    (e.g., DashboardSubResourceRestorer for dashboard elements/filters/layouts).
    """

    def restore_subresources(
        self,
        parent_id: str,
        parent_content: dict[str, Any],
        dry_run: bool = False,
    ) -> SubResourceRestorationResult:
        """Restore all sub-resources for a parent content item.

        Args:
            parent_id: ID of parent content in destination instance
            parent_content: Deserialized parent content from backup (contains nested sub-resources)
            dry_run: If True, validate without making API calls

        Returns:
            SubResourceRestorationResult with counts and errors
        """
        ...


class DashboardSubResourceRestorer:
    """Restores dashboard elements, filters, and layouts.

    This class implements the three-phase restoration strategy for dashboard sub-resources:
    - Dashboard filters (filter controls)
    - Dashboard elements (tiles, visualizations, text boxes)
    - Dashboard layouts (responsive layout definitions)
    - Dashboard layout components (element positioning within layouts)

    Three-Phase Strategy Implementation
    ====================================

    The restoration methods (_restore_dashboard_filters, _restore_dashboard_elements,
    _restore_dashboard_layouts) each implement the three-phase pattern:

    **Phase 1 - Discovery**: Call _fetch_existing_*() to get current state from destination
    **Phase 2 - Categorization**: Compare backup IDs vs. destination IDs to determine operations
    **Phase 3 - Execution**: Call _create_*/_update_*/_delete_* methods in dependency order

    Dependency Order
    ================
    Sub-resources are restored in dependency order to prevent foreign key violations:
    1. Filters (no dependencies)
    2. Elements (may reference filters)
    3. Layouts (reference elements via layout components)
    4. Layout components (positioning for elements within layouts)

    Error Handling
    ===============
    - Best-effort restoration: individual item failures don't stop the process
    - Errors are aggregated in SubResourceResult for DLQ processing
    - Rate limit errors trigger automatic retries via @retry_on_rate_limit decorator
    - Failures in one sub-resource type don't affect other types

    Same-Instance Matching
    ======================
    For same-instance restoration, items are matched by ID (not name or other attributes).
    Each sub-resource is categorized into CREATE/UPDATE/DELETE operations:
    - CREATE: Item in backup but not in destination (assigns new ID)
    - UPDATE: Item exists in both (preserves ID)
    - DELETE: Item in destination but not in backup (orphan cleanup)
    """

    def __init__(
        self,
        client: LookerClient,
        rate_limiter: AdaptiveRateLimiter | None = None,
    ):
        """Initialize DashboardSubResourceRestorer.

        Args:
            client: LookerClient for API calls to destination instance
            rate_limiter: Optional adaptive rate limiter for API throttling
        """
        self.client = client
        self.rate_limiter = rate_limiter

        logger.debug(
            "Initialized DashboardSubResourceRestorer: "
            f"rate_limiter={'enabled' if rate_limiter else 'disabled'}"
        )

    def restore_subresources(
        self,
        parent_id: str,
        parent_content: dict[str, Any],
        dry_run: bool = False,
    ) -> SubResourceRestorationResult:
        """Restore all dashboard sub-resources (filters, elements, layouts).

        Args:
            parent_id: Dashboard ID in destination instance
            parent_content: Deserialized dashboard from backup (contains nested sub-resources)
            dry_run: If True, validate structure without making API calls

        Returns:
            SubResourceRestorationResult with aggregated counts and errors
        """
        result = SubResourceRestorationResult(parent_id=parent_id)

        logger.info(
            f"Starting dashboard sub-resource restoration: dashboard_id={parent_id}, dry_run={dry_run}"
        )

        if dry_run:
            # Dry run: validate sub-resource structure without API calls
            logger.info("Dry run mode - validating sub-resource structure only")
            return self._validate_subresources(parent_content, result)

        # Step 1: Restore filters first (no dependencies)
        logger.info(f"Restoring dashboard filters for dashboard {parent_id}")
        filter_result = self._restore_dashboard_filters(
            parent_id, parent_content.get("dashboard_filters", [])
        )
        result.merge(filter_result)
        logger.info(
            f"Dashboard filters restored: created={filter_result.created_count}, "
            f"updated={filter_result.updated_count}, deleted={filter_result.deleted_count}, "
            f"errors={filter_result.error_count}"
        )

        # Step 2: Restore elements (may depend on filters)
        logger.info(f"Restoring dashboard elements for dashboard {parent_id}")
        element_result = self._restore_dashboard_elements(
            parent_id, parent_content.get("dashboard_elements", [])
        )
        result.merge(element_result)
        logger.info(
            f"Dashboard elements restored: created={element_result.created_count}, "
            f"updated={element_result.updated_count}, deleted={element_result.deleted_count}, "
            f"errors={element_result.error_count}"
        )

        # Step 3: Restore layouts (depend on elements)
        logger.info(f"Restoring dashboard layouts for dashboard {parent_id}")
        layout_result = self._restore_dashboard_layouts(
            parent_id,
            parent_content.get("dashboard_layouts", []),
            parent_content.get("dashboard_elements", []),
        )
        result.merge(layout_result)
        logger.info(
            f"Dashboard layouts restored: created={layout_result.created_count}, "
            f"updated={layout_result.updated_count}, deleted={layout_result.deleted_count}, "
            f"errors={layout_result.error_count}"
        )

        logger.info(
            f"Dashboard sub-resource restoration complete: "
            f"total_created={result.total_created}, total_updated={result.total_updated}, "
            f"total_deleted={result.total_deleted}, total_errors={result.total_errors}"
        )

        return result

    def _validate_subresources(
        self, parent_content: dict[str, Any], result: SubResourceRestorationResult
    ) -> SubResourceRestorationResult:
        """Validate sub-resource structure without API calls (dry run).

        Args:
            parent_content: Deserialized dashboard from backup
            result: SubResourceRestorationResult to populate with validation results

        Returns:
            SubResourceRestorationResult with validation status
        """
        # Validate dashboard_filters structure
        filters = parent_content.get("dashboard_filters", [])
        if not isinstance(filters, list):
            result.filters.error_count += 1
            result.filters.errors.append("dashboard_filters is not a list")
        else:
            logger.debug(f"Validated {len(filters)} dashboard filters")

        # Validate dashboard_elements structure
        elements = parent_content.get("dashboard_elements", [])
        if not isinstance(elements, list):
            result.elements.error_count += 1
            result.elements.errors.append("dashboard_elements is not a list")
        else:
            logger.debug(f"Validated {len(elements)} dashboard elements")

        # Validate dashboard_layouts structure
        layouts = parent_content.get("dashboard_layouts", [])
        if not isinstance(layouts, list):
            result.layouts.error_count += 1
            result.layouts.errors.append("dashboard_layouts is not a list")
        else:
            logger.debug(f"Validated {len(layouts)} dashboard layouts")

        return result

    def _filter_read_only_fields(
        self, content_dict: dict[str, Any], read_only_fields: set[str]
    ) -> dict[str, Any]:
        """Remove read-only fields from content dictionary.

        Args:
            content_dict: Dictionary with all fields from API response
            read_only_fields: Set of read-only field names to remove

        Returns:
            Filtered dictionary with only writable fields
        """
        return {k: v for k, v in content_dict.items() if k not in read_only_fields}

    # ===========================
    # Dashboard Filter Restoration
    # ===========================

    def _restore_dashboard_filters(
        self, dashboard_id: str, backup_filters: list[dict[str, Any]]
    ) -> SubResourceResult:
        """Restore dashboard filters with UPDATE/CREATE/DELETE logic.

        Implements the three-phase restoration strategy:
        1. Discovery: Fetch existing filters from destination
        2. Categorization: Determine CREATE/UPDATE/DELETE operations
        3. Execution: Apply operations with best-effort error handling

        Phase Details
        -------------
        **Phase 1 - Discovery**: Call ``_fetch_existing_filters()`` to get all
        existing dashboard filters from the destination instance. Build a mapping
        by ID for efficient lookup.

        **Phase 2 - Categorization**: Compare backup IDs against destination IDs:
        - Backup ID in destination → UPDATE operation
        - Backup ID not in destination → CREATE operation
        - Destination ID not in backup → DELETE operation (orphan cleanup)

        **Phase 3 - Execution**: Execute operations sequentially with best-effort
        error handling. Failed items are logged but don't stop the restoration.

        Example
        -------
        Given backup filters with IDs ``{1, 2, 3}`` and destination filters
        with IDs ``{2, 3, 4}``:
        - Filter 1: CREATE (exists in backup, not destination)
        - Filter 2: UPDATE (exists in both)
        - Filter 3: UPDATE (exists in both)
        - Filter 4: DELETE (exists in destination, not backup)

        Args:
            dashboard_id: Dashboard ID in destination instance
            backup_filters: List of dashboard filter dicts from backup

        Returns:
            SubResourceResult with counts and errors
        """
        result = SubResourceResult(resource_type="dashboard_filter")

        logger.debug(
            f"Restoring {len(backup_filters)} dashboard filters for dashboard {dashboard_id}"
        )

        # ========== PHASE 1: DISCOVERY ==========
        # Fetch existing filters from destination to establish current state
        try:
            existing_filters = self._fetch_existing_filters(dashboard_id)
            existing_by_id = {f["id"]: f for f in existing_filters}
            logger.debug(f"Found {len(existing_filters)} existing filters in destination")
        except Exception as e:
            log_and_return_error(
                result, f"Failed to fetch existing filters for dashboard {dashboard_id}", e
            )
            return result

        # ========== PHASE 2: CATEGORIZATION ==========
        # Extract backup IDs for categorization (CREATE vs UPDATE vs DELETE)
        backup_ids = {f.get("id") for f in backup_filters if f.get("id")}

        # ========== PHASE 3: EXECUTION ==========
        # Execute operations in order: UPDATE (existing), CREATE (new), DELETE (orphans)
        # Use best-effort error handling: continue on individual failures

        # UPDATE: Filters that exist in both backup and destination
        for backup_filter in backup_filters:
            filter_id = backup_filter.get("id")
            if not filter_id:
                logger.warning("Skipping filter without ID in backup")
                continue

            if filter_id in existing_by_id:
                # UPDATE existing filter
                try:
                    logger.debug(f"Updating dashboard filter {filter_id}")
                    self._update_dashboard_filter(dashboard_id, filter_id, backup_filter)
                    result.updated_count += 1
                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to update dashboard filter {filter_id}", e
                    )
            else:
                # CREATE new filter
                try:
                    logger.debug(f"Creating dashboard filter {filter_id}")
                    new_filter = self._create_dashboard_filter(dashboard_id, backup_filter)
                    result.created_count += 1
                    # Track ID mapping if new ID differs from backup ID
                    new_id = new_filter.get("id")
                    if new_id and new_id != filter_id:
                        result.id_mappings[filter_id] = new_id
                        logger.debug(f"Filter ID mapping: {filter_id} -> {new_id}")
                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to create dashboard filter {filter_id}", e
                    )

        # DELETE: Filters in destination but not in backup
        for existing_id in existing_by_id:
            if existing_id not in backup_ids:
                try:
                    logger.debug(f"Deleting orphaned dashboard filter {existing_id}")
                    self._delete_dashboard_filter(existing_id)
                    result.deleted_count += 1
                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to delete dashboard filter {existing_id}", e
                    )

        return result

    @retry_on_rate_limit
    def _fetch_existing_filters(self, dashboard_id: str) -> list[dict[str, Any]]:
        """Fetch existing dashboard filters from destination.

        Args:
            dashboard_id: Dashboard ID in destination instance

        Returns:
            List of dashboard filter dicts
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        try:
            filters = self.client.sdk.dashboard_dashboard_filters(dashboard_id)

            if self.rate_limiter:
                self.rate_limiter.on_success()

            # Convert SDK models to dicts
            return [dict(f) if hasattr(f, "__dict__") else f for f in filters]

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to fetch filters: {e}") from e

    @retry_on_rate_limit
    def _create_dashboard_filter(
        self, dashboard_id: str, filter_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Create new dashboard filter.

        Args:
            dashboard_id: Dashboard ID in destination instance
            filter_dict: Dashboard filter dict from backup

        Returns:
            Created dashboard filter dict (with new ID)
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Remove read-only fields
        writable_filter = self._filter_read_only_fields(filter_dict, READ_ONLY_FILTER_FIELDS)

        # Remove ID (API assigns new ID on create)
        writable_filter.pop("id", None)
        writable_filter["dashboard_id"] = dashboard_id

        logger.debug(f"CREATE filter payload keys: {list(writable_filter.keys())}")

        try:
            response = self.client.sdk.create_dashboard_filter(
                body=cast(looker_models.WriteCreateDashboardFilter, writable_filter)
            )

            if self.rate_limiter:
                self.rate_limiter.on_success()

            result_dict = dict(response) if hasattr(response, "__dict__") else response
            logger.debug(f"Created filter with ID: {result_dict.get('id')}")
            return result_dict

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to create filter: {e}") from e

    @retry_on_rate_limit
    def _update_dashboard_filter(
        self, dashboard_id: str, filter_id: str, filter_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Update existing dashboard filter.

        Args:
            dashboard_id: Dashboard ID in destination instance
            filter_id: Dashboard filter ID to update
            filter_dict: Dashboard filter dict from backup

        Returns:
            Updated dashboard filter dict
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Remove read-only fields
        writable_filter = self._filter_read_only_fields(filter_dict, READ_ONLY_FILTER_FIELDS)
        writable_filter["dashboard_id"] = dashboard_id

        logger.debug(f"UPDATE filter {filter_id} payload keys: {list(writable_filter.keys())}")

        try:
            response = self.client.sdk.update_dashboard_filter(
                filter_id, body=cast(looker_models.WriteDashboardFilter, writable_filter)
            )

            if self.rate_limiter:
                self.rate_limiter.on_success()

            result_dict = dict(response) if hasattr(response, "__dict__") else response
            logger.debug(f"Updated filter {filter_id}")
            return result_dict

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to update filter: {e}") from e

    @retry_on_rate_limit
    def _delete_dashboard_filter(self, filter_id: str) -> None:
        """Delete dashboard filter not in backup.

        Args:
            filter_id: Dashboard filter ID to delete
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        try:
            self.client.sdk.delete_dashboard_filter(filter_id)

            if self.rate_limiter:
                self.rate_limiter.on_success()

            logger.debug(f"Deleted filter {filter_id}")

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to delete filter: {e}") from e

    # ===========================
    # Dashboard Element Restoration
    # ===========================

    def _restore_dashboard_elements(
        self, dashboard_id: str, backup_elements: list[dict[str, Any]]
    ) -> SubResourceResult:
        """Restore dashboard elements (tiles/visualizations).

        Implements the three-phase restoration strategy:
        1. Discovery: Fetch existing elements from destination
        2. Categorization: Determine CREATE/UPDATE/DELETE operations
        3. Execution: Apply operations with best-effort error handling

        Dashboard elements include:
        - Query visualizations (reference query_id)
        - Look references (reference look_id)
        - Text tiles (contain body_text)
        - Merge results (reference merge_result_id)

        Phase Details
        -------------
        **Phase 1 - Discovery**: Call ``_fetch_existing_elements()`` to get all
        existing dashboard elements from the destination instance. Build a mapping
        by ID for efficient lookup.

        **Phase 2 - Categorization**: Compare backup IDs against destination IDs:
        - Backup ID in destination → UPDATE operation
        - Backup ID not in destination → CREATE operation
        - Destination ID not in backup → DELETE operation (orphan cleanup)

        **Phase 3 - Execution**: Execute operations sequentially with best-effort
        error handling. Track ID mappings for CREATE operations in case Looker
        assigns new IDs.

        Example
        -------
        Given backup elements with IDs ``{101, 102, 103}`` and destination elements
        with IDs ``{102, 103, 104}``:
        - Element 101: CREATE (exists in backup, not destination)
        - Element 102: UPDATE (exists in both)
        - Element 103: UPDATE (exists in both)
        - Element 104: DELETE (exists in destination, not backup)

        Args:
            dashboard_id: Dashboard ID in destination instance
            backup_elements: List of dashboard element dicts from backup

        Returns:
            SubResourceResult with counts and errors
        """
        result = SubResourceResult(resource_type="dashboard_element")

        logger.debug(
            f"Restoring {len(backup_elements)} dashboard elements for dashboard {dashboard_id}"
        )

        # ========== PHASE 1: DISCOVERY ==========
        # Fetch existing elements from destination to establish current state
        try:
            existing_elements = self._fetch_existing_elements(dashboard_id)
            existing_by_id = {e["id"]: e for e in existing_elements}
            logger.debug(f"Found {len(existing_elements)} existing elements in destination")
        except Exception as e:
            log_and_return_error(
                result, f"Failed to fetch existing elements for dashboard {dashboard_id}", e
            )
            return result

        # ========== PHASE 2: CATEGORIZATION ==========
        # Extract backup IDs for categorization (CREATE vs UPDATE vs DELETE)
        backup_ids = {e.get("id") for e in backup_elements if e.get("id")}

        # ========== PHASE 3: EXECUTION ==========
        # Execute operations in order: UPDATE (existing), CREATE (new), DELETE (orphans)
        # Use best-effort error handling: continue on individual failures

        # UPDATE: Elements that exist in both backup and destination
        for backup_element in backup_elements:
            element_id = backup_element.get("id")
            if not element_id:
                logger.warning("Skipping element without ID in backup")
                continue

            if element_id in existing_by_id:
                # UPDATE existing element
                try:
                    logger.debug(f"Updating dashboard element {element_id}")
                    self._update_dashboard_element(dashboard_id, element_id, backup_element)
                    result.updated_count += 1
                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to update dashboard element {element_id}", e
                    )
            else:
                # CREATE new element
                try:
                    logger.debug(f"Creating dashboard element {element_id}")
                    new_element = self._create_dashboard_element(dashboard_id, backup_element)
                    result.created_count += 1
                    # Track ID mapping if new ID differs from backup ID
                    new_id = new_element.get("id")
                    if new_id and new_id != element_id:
                        result.id_mappings[element_id] = new_id
                        logger.debug(f"Element ID mapping: {element_id} -> {new_id}")
                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to create dashboard element {element_id}", e
                    )

        # DELETE: Elements in destination but not in backup
        for existing_id in existing_by_id:
            if existing_id not in backup_ids:
                try:
                    logger.debug(f"Deleting orphaned dashboard element {existing_id}")
                    self._delete_dashboard_element(existing_id)
                    result.deleted_count += 1
                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to delete dashboard element {existing_id}", e
                    )

        return result

    @retry_on_rate_limit
    def _fetch_existing_elements(self, dashboard_id: str) -> list[dict[str, Any]]:
        """Fetch existing dashboard elements from destination.

        Args:
            dashboard_id: Dashboard ID in destination instance

        Returns:
            List of dashboard element dicts
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        try:
            elements = self.client.sdk.dashboard_dashboard_elements(dashboard_id)

            if self.rate_limiter:
                self.rate_limiter.on_success()

            # Convert SDK models to dicts
            return [dict(e) if hasattr(e, "__dict__") else e for e in elements]

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to fetch elements: {e}") from e

    @retry_on_rate_limit
    def _create_dashboard_element(
        self, dashboard_id: str, element_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Create new dashboard element.

        Args:
            dashboard_id: Dashboard ID in destination instance
            element_dict: Dashboard element dict from backup

        Returns:
            Created dashboard element dict (with new ID)
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Remove read-only fields
        writable_element = self._filter_read_only_fields(element_dict, READ_ONLY_ELEMENT_FIELDS)

        # Remove ID (API assigns new ID on create)
        writable_element.pop("id", None)
        writable_element["dashboard_id"] = dashboard_id

        logger.debug(f"CREATE element payload keys: {list(writable_element.keys())}")

        try:
            response = self.client.sdk.create_dashboard_element(
                body=cast(looker_models.WriteDashboardElement, writable_element)
            )

            if self.rate_limiter:
                self.rate_limiter.on_success()

            result_dict = dict(response) if hasattr(response, "__dict__") else response
            logger.debug(f"Created element with ID: {result_dict.get('id')}")
            return result_dict

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to create element: {e}") from e

    @retry_on_rate_limit
    def _update_dashboard_element(
        self, dashboard_id: str, element_id: str, element_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Update existing dashboard element.

        Args:
            dashboard_id: Dashboard ID in destination instance
            element_id: Dashboard element ID to update
            element_dict: Dashboard element dict from backup

        Returns:
            Updated dashboard element dict
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Remove read-only fields
        writable_element = self._filter_read_only_fields(element_dict, READ_ONLY_ELEMENT_FIELDS)
        writable_element["dashboard_id"] = dashboard_id

        logger.debug(f"UPDATE element {element_id} payload keys: {list(writable_element.keys())}")

        try:
            response = self.client.sdk.update_dashboard_element(
                element_id, body=cast(looker_models.WriteDashboardElement, writable_element)
            )

            if self.rate_limiter:
                self.rate_limiter.on_success()

            result_dict = dict(response) if hasattr(response, "__dict__") else response
            logger.debug(f"Updated element {element_id}")
            return result_dict

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to update element: {e}") from e

    @retry_on_rate_limit
    def _delete_dashboard_element(self, element_id: str) -> None:
        """Delete dashboard element not in backup.

        Args:
            element_id: Dashboard element ID to delete
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        try:
            self.client.sdk.delete_dashboard_element(element_id)

            if self.rate_limiter:
                self.rate_limiter.on_success()

            logger.debug(f"Deleted element {element_id}")

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to delete element: {e}") from e

    # ===========================
    # Dashboard Layout Restoration
    # ===========================

    def _restore_dashboard_layouts(
        self,
        dashboard_id: str,
        backup_layouts: list[dict[str, Any]],
        backup_elements: list[dict[str, Any]],
    ) -> SubResourceResult:
        """Restore dashboard layouts and layout components.

        Dashboard layouts define responsive layout behavior and contain layout_components
        that position elements at specific rows/columns with width/height.

        Phase Details
        -------------
        **Phase 1 - Discovery**: Call ``_fetch_existing_layouts()`` to get all
        existing dashboard layouts from the destination instance. Build a mapping
        by ID for efficient lookup.

        **Phase 2 - Categorization**: Compare backup IDs against destination IDs:
        - Backup ID in destination → UPDATE operation (also update components)
        - Backup ID not in destination → CREATE operation (also create components)
        - Destination ID not in backup → DELETE operation (orphan cleanup)

        **Phase 3 - Execution**: Execute operations sequentially with best-effort
        error handling. For each layout, also restore nested layout_components
        which define element positioning.

        Layout Components
        ------------------
        Layout components are nested sub-resources that define row/column positioning
        for dashboard elements. They are updated (not created/deleted) as part of
        the parent layout restoration.

        Example
        -------
        Given backup layouts with IDs ``{201, 202}`` and destination layouts
        with IDs ``{202, 203}``:
        - Layout 201: CREATE (exists in backup, not destination)
        - Layout 202: UPDATE (exists in both)
        - Layout 203: DELETE (exists in destination, not backup)

        Args:
            dashboard_id: Dashboard ID in destination instance
            backup_layouts: List of dashboard layout dicts from backup
            backup_elements: List of dashboard elements (for reference validation)

        Returns:
            SubResourceResult with counts and errors
        """
        result = SubResourceResult(resource_type="dashboard_layout")

        logger.debug(
            f"Restoring {len(backup_layouts)} dashboard layouts for dashboard {dashboard_id}"
        )

        # Fetch existing layouts from destination
        try:
            existing_layouts = self._fetch_existing_layouts(dashboard_id)
            existing_by_id = {layout["id"]: layout for layout in existing_layouts}
            logger.debug(f"Found {len(existing_layouts)} existing layouts in destination")
        except Exception as e:
            log_and_return_error(
                result, f"Failed to fetch existing layouts for dashboard {dashboard_id}", e
            )
            return result

        # Categorize and execute operations
        backup_ids = {layout.get("id") for layout in backup_layouts if layout.get("id")}

        # UPDATE: Layouts that exist in both backup and destination
        for backup_layout in backup_layouts:
            layout_id = backup_layout.get("id")
            if not layout_id:
                logger.warning("Skipping layout without ID in backup")
                continue

            if layout_id in existing_by_id:
                # UPDATE existing layout
                try:
                    logger.debug(f"Updating dashboard layout {layout_id}")
                    self._update_dashboard_layout(dashboard_id, layout_id, backup_layout)
                    result.updated_count += 1

                    # Update layout components (nested within layout)
                    self._restore_layout_components(layout_id, backup_layout, result)

                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to update dashboard layout {layout_id}", e
                    )
            else:
                # CREATE new layout
                try:
                    logger.debug(f"Creating dashboard layout {layout_id}")
                    new_layout = self._create_dashboard_layout(dashboard_id, backup_layout)
                    result.created_count += 1
                    # Track ID mapping if new ID differs from backup ID
                    new_id = new_layout.get("id")
                    if new_id and new_id != layout_id:
                        result.id_mappings[layout_id] = new_id
                        logger.debug(f"Layout ID mapping: {layout_id} -> {new_id}")

                    # Restore layout components for newly created layout
                    self._restore_layout_components(new_id or layout_id, backup_layout, result)

                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to create dashboard layout {layout_id}", e
                    )

        # DELETE: Layouts in destination but not in backup
        for existing_id in existing_by_id:
            if existing_id not in backup_ids:
                try:
                    logger.debug(f"Deleting orphaned dashboard layout {existing_id}")
                    self._delete_dashboard_layout(existing_id)
                    result.deleted_count += 1
                except Exception as e:
                    log_and_return_error(
                        result, f"Failed to delete dashboard layout {existing_id}", e
                    )

        return result

    def _restore_layout_components(
        self,
        layout_id: str,
        backup_layout: dict[str, Any],
        result: SubResourceResult,
    ) -> None:
        """Restore layout components (element positioning) for a layout.

        Layout components define row, column, width, height positioning for
        dashboard elements within a specific layout.

        Args:
            layout_id: Layout ID in destination instance
            backup_layout: Layout dict from backup containing dashboard_layout_components
            result: SubResourceResult to track component restoration errors

        Note: Updates result.errors in place for component restoration failures
        """
        backup_components = backup_layout.get("dashboard_layout_components", [])

        if not backup_components:
            logger.debug(f"No layout components to restore for layout {layout_id}")
            return

        logger.debug(f"Restoring {len(backup_components)} layout components for layout {layout_id}")

        # Fetch existing components for this layout (for validation)
        try:
            existing_components = self._fetch_existing_layout_components(layout_id)
            logger.debug(f"Found {len(existing_components)} existing layout components")
        except Exception as e:
            log_and_return_error(
                result,
                f"Failed to fetch existing layout components for layout {layout_id}",
                e,
            )
            return

        # UPDATE each component (Looker API only supports update for layout components, not create/delete)
        # Note: We update all components from backup without DELETE logic - layout components
        # are automatically created/deleted when parent elements are created/deleted
        for backup_component in backup_components:
            component_id = backup_component.get("id")
            if not component_id:
                logger.warning("Skipping layout component without ID in backup")
                continue

            try:
                logger.debug(f"Updating layout component {component_id}")
                self._update_dashboard_layout_component(component_id, backup_component)
            except Exception as e:
                log_and_return_error(result, f"Failed to update layout component {component_id}", e)

    @retry_on_rate_limit
    def _fetch_existing_layouts(self, dashboard_id: str) -> list[dict[str, Any]]:
        """Fetch existing dashboard layouts from destination.

        Args:
            dashboard_id: Dashboard ID in destination instance

        Returns:
            List of dashboard layout dicts
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        try:
            layouts = self.client.sdk.dashboard_dashboard_layouts(dashboard_id)

            if self.rate_limiter:
                self.rate_limiter.on_success()

            # Convert SDK models to dicts
            return [dict(layout) if hasattr(layout, "__dict__") else layout for layout in layouts]

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to fetch layouts: {e}") from e

    @retry_on_rate_limit
    def _fetch_existing_layout_components(self, layout_id: str) -> list[dict[str, Any]]:
        """Fetch existing layout components for a layout.

        Args:
            layout_id: Layout ID in destination instance

        Returns:
            List of dashboard layout component dicts
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        try:
            components = self.client.sdk.dashboard_layout_dashboard_layout_components(layout_id)

            if self.rate_limiter:
                self.rate_limiter.on_success()

            # Convert SDK models to dicts
            return [dict(comp) if hasattr(comp, "__dict__") else comp for comp in components]

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to fetch layout components: {e}") from e

    @retry_on_rate_limit
    def _create_dashboard_layout(
        self, dashboard_id: str, layout_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Create new dashboard layout.

        Args:
            dashboard_id: Dashboard ID in destination instance
            layout_dict: Dashboard layout dict from backup

        Returns:
            Created dashboard layout dict (with new ID)
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Remove read-only fields
        writable_layout = self._filter_read_only_fields(layout_dict, READ_ONLY_LAYOUT_FIELDS)

        # Remove ID (API assigns new ID on create)
        writable_layout.pop("id", None)
        writable_layout["dashboard_id"] = dashboard_id

        logger.debug(f"CREATE layout payload keys: {list(writable_layout.keys())}")

        try:
            response = self.client.sdk.create_dashboard_layout(
                body=cast(looker_models.WriteDashboardLayout, writable_layout)
            )

            if self.rate_limiter:
                self.rate_limiter.on_success()

            result_dict = dict(response) if hasattr(response, "__dict__") else response
            logger.debug(f"Created layout with ID: {result_dict.get('id')}")
            return result_dict

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to create layout: {e}") from e

    @retry_on_rate_limit
    def _update_dashboard_layout(
        self, dashboard_id: str, layout_id: str, layout_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Update existing dashboard layout.

        Args:
            dashboard_id: Dashboard ID in destination instance
            layout_id: Dashboard layout ID to update
            layout_dict: Dashboard layout dict from backup

        Returns:
            Updated dashboard layout dict
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Remove read-only fields
        writable_layout = self._filter_read_only_fields(layout_dict, READ_ONLY_LAYOUT_FIELDS)
        writable_layout["dashboard_id"] = dashboard_id

        logger.debug(f"UPDATE layout {layout_id} payload keys: {list(writable_layout.keys())}")

        try:
            response = self.client.sdk.update_dashboard_layout(
                layout_id, body=cast(looker_models.WriteDashboardLayout, writable_layout)
            )

            if self.rate_limiter:
                self.rate_limiter.on_success()

            result_dict = dict(response) if hasattr(response, "__dict__") else response
            logger.debug(f"Updated layout {layout_id}")
            return result_dict

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to update layout: {e}") from e

    @retry_on_rate_limit
    def _update_dashboard_layout_component(
        self, component_id: str, component_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Update dashboard layout component positioning.

        Args:
            component_id: Dashboard layout component ID to update
            component_dict: Dashboard layout component dict from backup

        Returns:
            Updated dashboard layout component dict
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        # Remove read-only fields
        writable_component = self._filter_read_only_fields(
            component_dict, READ_ONLY_LAYOUT_COMPONENT_FIELDS
        )

        logger.debug(
            f"UPDATE layout component {component_id} payload keys: {list(writable_component.keys())}"
        )

        try:
            response = self.client.sdk.update_dashboard_layout_component(
                component_id,
                body=cast(looker_models.WriteDashboardLayoutComponent, writable_component),
            )

            if self.rate_limiter:
                self.rate_limiter.on_success()

            result_dict = dict(response) if hasattr(response, "__dict__") else response
            logger.debug(f"Updated layout component {component_id}")
            return result_dict

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to update layout component: {e}") from e

    @retry_on_rate_limit
    def _delete_dashboard_layout(self, layout_id: str) -> None:
        """Delete dashboard layout not in backup.

        Args:
            layout_id: Dashboard layout ID to delete
        """
        if self.rate_limiter:
            self.rate_limiter.acquire()

        try:
            self.client.sdk.delete_dashboard_layout(layout_id)

            if self.rate_limiter:
                self.rate_limiter.on_success()

            logger.debug(f"Deleted layout {layout_id}")

        except looker_error.SDKError as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                if self.rate_limiter:
                    self.rate_limiter.on_429_detected()
                raise RateLimitError(f"Rate limit exceeded: {e}") from e
            raise RestorationError(f"Failed to delete layout: {e}") from e
