"""Unit tests for DependencyGraph class."""

from lookervault.restoration.dependency_graph import DependencyGraph
from lookervault.storage.models import ContentType, DependencyOrder


class TestDependencyGraph:
    """Test suite for DependencyGraph class."""

    def test_get_restoration_order_all_types(self) -> None:
        """Test getting restoration order for all content types."""
        graph = DependencyGraph()
        order = graph.get_restoration_order()

        # Verify all types are present (excluding EXPLORE which is read-only)
        expected_types = [
            ContentType.USER,
            ContentType.GROUP,
            ContentType.PERMISSION_SET,
            ContentType.MODEL_SET,
            ContentType.ROLE,
            ContentType.FOLDER,
            ContentType.LOOKML_MODEL,
            ContentType.LOOK,
            ContentType.DASHBOARD,
            ContentType.BOARD,
            ContentType.SCHEDULED_PLAN,
        ]
        assert set(order) == set(expected_types)

        # Verify order is correct (users before dashboards, etc.)
        user_idx = order.index(ContentType.USER)
        dashboard_idx = order.index(ContentType.DASHBOARD)
        assert user_idx < dashboard_idx

        folder_idx = order.index(ContentType.FOLDER)
        assert folder_idx < dashboard_idx

        look_idx = order.index(ContentType.LOOK)
        assert look_idx < dashboard_idx

    def test_get_restoration_order_specific_types(self) -> None:
        """Test getting restoration order for specific content types."""
        graph = DependencyGraph()
        types = [ContentType.DASHBOARD, ContentType.FOLDER, ContentType.USER]
        order = graph.get_restoration_order(types)

        # Should return types in dependency order
        assert len(order) == 3
        assert order[0] == ContentType.USER
        assert order[1] == ContentType.FOLDER
        assert order[2] == ContentType.DASHBOARD

    def test_get_restoration_order_respects_dependency_order_enum(self) -> None:
        """Test that restoration order matches DependencyOrder enum values."""
        graph = DependencyGraph()
        order = graph.get_restoration_order()

        # Verify each type appears in order of its DependencyOrder value
        for i in range(len(order) - 1):
            current_priority = graph.CONTENT_TYPE_TO_ORDER[order[i]]
            next_priority = graph.CONTENT_TYPE_TO_ORDER[order[i + 1]]
            assert current_priority <= next_priority

    def test_validate_no_cycles_passes(self) -> None:
        """Test that dependency graph validation passes (no cycles)."""
        graph = DependencyGraph()
        # Should not raise exception
        assert graph.validate_no_cycles() is True

    def test_get_dependencies_dashboard(self) -> None:
        """Test getting dependencies for dashboard content type."""
        graph = DependencyGraph()
        deps = graph.get_dependencies(ContentType.DASHBOARD)

        # Dashboard depends on LOOK, FOLDER, and USER
        assert ContentType.LOOK in deps
        assert ContentType.FOLDER in deps
        assert ContentType.USER in deps

    def test_get_dependencies_user(self) -> None:
        """Test getting dependencies for user content type (no dependencies)."""
        graph = DependencyGraph()
        deps = graph.get_dependencies(ContentType.USER)

        # User has no dependencies
        assert len(deps) == 0

    def test_get_dependencies_role(self) -> None:
        """Test getting dependencies for role content type."""
        graph = DependencyGraph()
        deps = graph.get_dependencies(ContentType.ROLE)

        # Role depends on GROUP, PERMISSION_SET, MODEL_SET
        assert ContentType.GROUP in deps
        assert ContentType.PERMISSION_SET in deps
        assert ContentType.MODEL_SET in deps

    def test_get_dependencies_returns_copy(self) -> None:
        """Test that get_dependencies returns a copy (not reference)."""
        graph = DependencyGraph()
        deps1 = graph.get_dependencies(ContentType.DASHBOARD)
        deps2 = graph.get_dependencies(ContentType.DASHBOARD)

        # Should be equal but not the same object
        assert deps1 == deps2
        assert deps1 is not deps2

    def test_dependency_order_enum_values(self) -> None:
        """Test that DependencyOrder enum has expected values."""
        assert DependencyOrder.USERS == 1
        assert DependencyOrder.GROUPS == 2
        assert DependencyOrder.PERMISSION_SETS == 3
        assert DependencyOrder.MODEL_SETS == 4
        assert DependencyOrder.ROLES == 5
        assert DependencyOrder.FOLDERS == 6
        assert DependencyOrder.LOOKML_MODELS == 7
        assert DependencyOrder.LOOKS == 8
        assert DependencyOrder.DASHBOARDS == 9
        assert DependencyOrder.BOARDS == 10
        assert DependencyOrder.SCHEDULED_PLANS == 11

    def test_content_type_to_order_mapping_complete(self) -> None:
        """Test that all restorable content types have order mappings."""
        graph = DependencyGraph()

        # All content types in DEPENDENCIES should have order mappings
        for content_type in graph.DEPENDENCIES:
            assert content_type in graph.CONTENT_TYPE_TO_ORDER

    def test_get_restoration_order_filters_unorderable_types(self) -> None:
        """Test that get_restoration_order filters out types without ordering."""
        graph = DependencyGraph()

        # EXPLORE is in ContentType enum but not orderable (read-only via API)
        types = [ContentType.USER, ContentType.EXPLORE, ContentType.DASHBOARD]
        order = graph.get_restoration_order(types)

        # EXPLORE should be filtered out
        assert ContentType.EXPLORE not in order
        assert ContentType.USER in order
        assert ContentType.DASHBOARD in order
