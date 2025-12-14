"""Dependency graph management for content restoration ordering."""

from lookervault.exceptions import DependencyError
from lookervault.storage.models import ContentType, DependencyOrder


class DependencyGraph:
    """Manages content type dependency ordering for restoration.

    This class provides dependency-aware ordering of content types based on
    Looker's resource relationships. Content with dependencies on other content
    must be restored after their dependencies (e.g., dashboards depend on looks,
    so looks are restored first).

    The dependency relationships are hardcoded based on Looker's schema:
    - Users and Groups have no dependencies
    - Roles depend on Groups, Permission Sets, and Model Sets
    - Folders depend on Users (owner) and other Folders (parent)
    - Dashboards depend on Looks, Folders, and Users
    - And so on...

    The restoration order follows the DependencyOrder enum which assigns priority
    values to each content type (lower values = restore first).
    """

    # Hardcoded dependency relationships based on Looker schema
    # Key: ContentType, Value: List of ContentTypes that must be restored first
    DEPENDENCIES: dict[ContentType, list[ContentType]] = {
        ContentType.USER: [],
        ContentType.GROUP: [],
        ContentType.PERMISSION_SET: [],
        ContentType.MODEL_SET: [ContentType.LOOKML_MODEL],
        ContentType.ROLE: [
            ContentType.GROUP,
            ContentType.PERMISSION_SET,
            ContentType.MODEL_SET,
        ],
        ContentType.FOLDER: [
            ContentType.USER,  # owner
            # Note: parent folder dependency is within same type, handled separately
        ],
        ContentType.LOOKML_MODEL: [],
        # EXPLORE is read-only via API, not included in restoration
        ContentType.LOOK: [
            ContentType.EXPLORE,  # references explore
            ContentType.FOLDER,  # belongs to folder
        ],
        ContentType.DASHBOARD: [
            ContentType.LOOK,  # may embed looks
            ContentType.FOLDER,  # belongs to folder
            ContentType.USER,  # owner
        ],
        ContentType.BOARD: [
            ContentType.DASHBOARD,  # collections of dashboards
            ContentType.LOOK,  # collections of looks
        ],
        ContentType.SCHEDULED_PLAN: [
            ContentType.DASHBOARD,  # schedules dashboards
            ContentType.LOOK,  # schedules looks
            ContentType.USER,  # owner/recipient
        ],
    }

    # Mapping from ContentType to DependencyOrder priority
    CONTENT_TYPE_TO_ORDER: dict[ContentType, DependencyOrder] = {
        ContentType.USER: DependencyOrder.USERS,
        ContentType.GROUP: DependencyOrder.GROUPS,
        ContentType.PERMISSION_SET: DependencyOrder.PERMISSION_SETS,
        ContentType.MODEL_SET: DependencyOrder.MODEL_SETS,
        ContentType.ROLE: DependencyOrder.ROLES,
        ContentType.FOLDER: DependencyOrder.FOLDERS,
        ContentType.LOOKML_MODEL: DependencyOrder.LOOKML_MODELS,
        ContentType.LOOK: DependencyOrder.LOOKS,
        ContentType.DASHBOARD: DependencyOrder.DASHBOARDS,
        ContentType.BOARD: DependencyOrder.BOARDS,
        ContentType.SCHEDULED_PLAN: DependencyOrder.SCHEDULED_PLANS,
    }

    def get_restoration_order(
        self, content_types: list[ContentType] | None = None
    ) -> list[ContentType]:
        """Get content types in dependency order (dependencies first).

        This method returns content types sorted such that each type appears
        after all of its dependencies. For example, DASHBOARD depends on LOOK,
        so LOOK will appear before DASHBOARD in the returned list.

        Args:
            content_types: Specific types to order. If None, returns all supported
                          types in dependency order.

        Returns:
            Content types sorted by dependency order (dependencies restored first).
            Types with lower DependencyOrder values appear first.

        Example:
            >>> graph = DependencyGraph()
            >>> graph.get_restoration_order([ContentType.DASHBOARD, ContentType.FOLDER])
            [ContentType.FOLDER, ContentType.DASHBOARD]

            >>> graph.get_restoration_order()
            [ContentType.USER, ContentType.GROUP, ..., ContentType.SCHEDULED_PLAN]
        """
        # If no specific types requested, use all types with defined ordering
        if content_types is None:
            content_types = list(self.CONTENT_TYPE_TO_ORDER.keys())

        # Filter out any types that don't have a defined dependency order
        # (e.g., EXPLORE is read-only and not restorable via API)
        orderable_types = [ct for ct in content_types if ct in self.CONTENT_TYPE_TO_ORDER]

        # Sort by DependencyOrder priority (lower values first)
        return sorted(orderable_types, key=lambda ct: self.CONTENT_TYPE_TO_ORDER[ct])

    def validate_no_cycles(self) -> bool:
        """Validate dependency graph has no circular dependencies.

        Uses depth-first search to detect cycles in the dependency graph.
        A cycle would indicate invalid dependency relationships (e.g., A depends
        on B, B depends on C, C depends on A), which would make it impossible
        to determine a valid restoration order.

        Returns:
            True if the graph is acyclic (no cycles detected).

        Raises:
            DependencyError: If a circular dependency is detected, with details
                           about the cycle path.

        Note:
            This validation is performed on the hardcoded DEPENDENCIES mapping.
            Since dependencies are static and defined at module level, cycles
            should never occur in practice unless the mapping is incorrectly
            modified.
        """
        # Track visiting state for cycle detection
        # States: white (unvisited), gray (visiting), black (visited)
        white, gray, black = 0, 1, 2
        state: dict[ContentType, int] = dict.fromkeys(self.DEPENDENCIES, white)
        path: list[ContentType] = []

        def visit(content_type: ContentType) -> None:
            """Depth-first search visit function.

            Args:
                content_type: Current content type being visited.

            Raises:
                DependencyError: If a cycle is detected during traversal.
            """
            if state[content_type] == black:
                # Already fully processed
                return

            if state[content_type] == gray:
                # Currently visiting - cycle detected!
                cycle_start = path.index(content_type)
                cycle_path = " -> ".join(str(ct.name) for ct in path[cycle_start:])
                cycle_path += f" -> {content_type.name}"
                raise DependencyError(
                    f"Circular dependency detected: {cycle_path}. "
                    "Content types form a cycle and cannot be restored in valid order."
                )

            # Mark as visiting
            state[content_type] = gray
            path.append(content_type)

            # Visit all dependencies
            for dependency in self.DEPENDENCIES.get(content_type, []):
                if dependency in self.DEPENDENCIES:
                    visit(dependency)

            # Mark as fully visited
            path.pop()
            state[content_type] = black

        # Visit all nodes to check for cycles
        for content_type in self.DEPENDENCIES:
            if state[content_type] == white:
                visit(content_type)

        return True

    def get_dependencies(self, content_type: ContentType) -> list[ContentType]:
        """Get direct dependencies for a content type.

        Returns the list of content types that must be restored before the
        specified content type. This returns only direct dependencies, not
        transitive dependencies.

        Args:
            content_type: ContentType to query for dependencies.

        Returns:
            List of content types that must be restored first (direct dependencies).
            Returns empty list if the content type has no dependencies.

        Example:
            >>> graph = DependencyGraph()
            >>> graph.get_dependencies(ContentType.DASHBOARD)
            [ContentType.LOOK, ContentType.FOLDER, ContentType.USER]

            >>> graph.get_dependencies(ContentType.USER)
            []
        """
        return self.DEPENDENCIES.get(content_type, []).copy()
