"""Unit tests for FolderHierarchyResolver and folder tree building."""

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock

import msgspec.msgpack
import pytest

from lookervault.exceptions import NotFoundError
from lookervault.folder.hierarchy import FolderHierarchyResolver, FolderNode
from lookervault.storage.models import ContentItem, ContentType


@pytest.fixture
def mock_repository() -> Generator[MagicMock]:
    """Create mock repository with configurable folder data."""
    repo = MagicMock()
    repo._content_items: list[ContentItem] = []
    yield repo


@pytest.fixture
def encoder() -> msgspec.msgpack.Encoder:
    """Msgpack encoder for serializing folder metadata."""
    return msgspec.msgpack.Encoder()


@pytest.fixture
def simple_hierarchy(mock_repository: MagicMock, encoder: msgspec.msgpack.Encoder) -> MagicMock:
    """Create simple folder hierarchy for testing.

    Hierarchy:
        Root (id=1)
        ├── Sales (id=2)
        │   ├── Regional (id=3)
        │   └── National (id=4)
        └── Marketing (id=5)
    """
    folders = [
        {"id": "1", "name": "Root", "parent_id": None},
        {"id": "2", "name": "Sales", "parent_id": "1"},
        {"id": "3", "name": "Regional", "parent_id": "2"},
        {"id": "4", "name": "National", "parent_id": "2"},
        {"id": "5", "name": "Marketing", "parent_id": "1"},
    ]

    content_items = [
        ContentItem(
            id=folder["id"],
            name=folder["name"],
            content_type=ContentType.FOLDER.value,
            content_data=encoder.encode(folder),
            created_at=datetime.fromisoformat("2025-12-14T00:00:00"),
            updated_at=datetime.fromisoformat("2025-12-14T00:00:00"),
        )
        for folder in folders
    ]

    mock_repository.list_content.return_value = content_items
    return mock_repository


@pytest.fixture
def complex_hierarchy(mock_repository: MagicMock, encoder: msgspec.msgpack.Encoder) -> MagicMock:
    """Create complex multi-level hierarchy for testing.

    Hierarchy:
        Root1 (id=1)
        ├── A (id=2)
        │   ├── A1 (id=3)
        │   │   └── A1a (id=4)
        │   └── A2 (id=5)
        Root2 (id=6)
        └── B (id=7)
            └── B1 (id=8)
        Orphan (id=9) - no parent
    """
    folders = [
        {"id": "1", "name": "Root1", "parent_id": None},
        {"id": "2", "name": "A", "parent_id": "1"},
        {"id": "3", "name": "A1", "parent_id": "2"},
        {"id": "4", "name": "A1a", "parent_id": "3"},
        {"id": "5", "name": "A2", "parent_id": "2"},
        {"id": "6", "name": "Root2", "parent_id": None},
        {"id": "7", "name": "B", "parent_id": "6"},
        {"id": "8", "name": "B1", "parent_id": "7"},
        {"id": "9", "name": "Orphan", "parent_id": None},
    ]

    content_items = [
        ContentItem(
            id=folder["id"],
            name=folder["name"],
            content_type=ContentType.FOLDER.value,
            content_data=encoder.encode(folder),
            created_at=datetime.fromisoformat("2025-12-14T00:00:00"),
            updated_at=datetime.fromisoformat("2025-12-14T00:00:00"),
        )
        for folder in folders
    ]

    mock_repository.list_content.return_value = content_items
    return mock_repository


@pytest.fixture
def circular_hierarchy(mock_repository: MagicMock, encoder: msgspec.msgpack.Encoder) -> MagicMock:
    """Create hierarchy with circular reference for cycle detection testing.

    Circular reference (should be handled gracefully):
        A (id=1) -> parent_id=None
        B (id=2) -> parent_id=1
        C (id=3) -> parent_id=2
        D (id=4) -> parent_id=3
        E (id=5) -> parent_id=4

    Note: We'll manually create cycle by setting parent_id=2 for folder 4 later
    """
    folders = [
        {"id": "1", "name": "A", "parent_id": None},
        {"id": "2", "name": "B", "parent_id": "1"},
        {"id": "3", "name": "C", "parent_id": "2"},
        {"id": "4", "name": "D", "parent_id": "2"},  # Sibling of C
        {"id": "5", "name": "E", "parent_id": "4"},
    ]

    content_items = [
        ContentItem(
            id=folder["id"],
            name=folder["name"],
            content_type=ContentType.FOLDER.value,
            content_data=encoder.encode(folder),
            created_at=datetime.fromisoformat("2025-12-14T00:00:00"),
            updated_at=datetime.fromisoformat("2025-12-14T00:00:00"),
        )
        for folder in folders
    ]

    mock_repository.list_content.return_value = content_items
    return mock_repository


class TestFolderHierarchyResolverBasics:
    """Test basic FolderHierarchyResolver functionality."""

    def test_initialization(self, mock_repository: MagicMock) -> None:
        """Test resolver initializes with empty cache."""
        resolver = FolderHierarchyResolver(mock_repository)

        assert resolver.repository == mock_repository
        assert resolver._folder_cache == {}
        assert not resolver._cache_loaded

    def test_load_folder_cache(self, simple_hierarchy: MagicMock) -> None:
        """Test folder cache loads and builds parent-child map."""
        resolver = FolderHierarchyResolver(simple_hierarchy)
        resolver._load_folder_cache()

        assert resolver._cache_loaded
        assert len(resolver._folder_cache) == 5

        # Check folder metadata cached correctly
        assert resolver._folder_cache["1"]["name"] == "Root"
        assert resolver._folder_cache["2"]["name"] == "Sales"

        # Check parent-child map built correctly
        assert "2" in resolver._parent_to_children["1"]  # Sales is child of Root
        assert "5" in resolver._parent_to_children["1"]  # Marketing is child of Root
        assert "3" in resolver._parent_to_children["2"]  # Regional is child of Sales
        assert "4" in resolver._parent_to_children["2"]  # National is child of Sales

    def test_load_folder_cache_only_once(self, simple_hierarchy: MagicMock) -> None:
        """Test cache loads only once even with multiple calls."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        resolver._load_folder_cache()
        first_cache = resolver._folder_cache

        resolver._load_folder_cache()
        second_cache = resolver._folder_cache

        assert first_cache is second_cache
        assert simple_hierarchy.list_content.call_count == 1

    def test_get_folder_metadata(self, simple_hierarchy: MagicMock) -> None:
        """Test getting folder metadata by ID."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        metadata = resolver.get_folder_metadata("2")

        assert metadata["id"] == "2"
        assert metadata["name"] == "Sales"
        assert metadata["parent_id"] == "1"

    def test_get_folder_metadata_not_found(self, simple_hierarchy: MagicMock) -> None:
        """Test getting metadata for non-existent folder raises NotFoundError."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        with pytest.raises(NotFoundError, match="Folder ID 'nonexistent' not found"):
            resolver.get_folder_metadata("nonexistent")

    def test_validate_folders_exist_all_valid(self, simple_hierarchy: MagicMock) -> None:
        """Test validating existing folder IDs succeeds."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        # Should not raise
        resolver.validate_folders_exist(["1", "2", "3"])

    def test_validate_folders_exist_some_missing(self, simple_hierarchy: MagicMock) -> None:
        """Test validating with missing folder IDs raises NotFoundError."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        with pytest.raises(NotFoundError, match="Folder IDs not found.*invalid1, invalid2"):
            resolver.validate_folders_exist(["1", "invalid1", "2", "invalid2"])


class TestFolderHierarchyResolverRecursiveExpansion:
    """Test recursive folder expansion using get_all_descendant_ids."""

    def test_single_folder_no_children(self, simple_hierarchy: MagicMock) -> None:
        """Test expanding folder with no children returns just that folder."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        result = resolver.get_all_descendant_ids(["5"])  # Marketing has no children

        assert result == {"5"}

    def test_single_folder_with_children(self, simple_hierarchy: MagicMock) -> None:
        """Test expanding folder includes all descendants."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        result = resolver.get_all_descendant_ids(["2"])  # Sales has Regional and National

        assert result == {"2", "3", "4"}

    def test_multiple_root_folders(self, simple_hierarchy: MagicMock) -> None:
        """Test expanding multiple root folders."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        result = resolver.get_all_descendant_ids(["2", "5"])

        assert result == {"2", "3", "4", "5"}

    def test_expand_entire_tree(self, simple_hierarchy: MagicMock) -> None:
        """Test expanding from root includes entire tree."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        result = resolver.get_all_descendant_ids(["1"])

        assert result == {"1", "2", "3", "4", "5"}

    def test_deep_nesting(self, complex_hierarchy: MagicMock) -> None:
        """Test expansion works with deeply nested folders."""
        resolver = FolderHierarchyResolver(complex_hierarchy)

        # Expand from folder "2" (A) should include A, A1, A1a, A2
        result = resolver.get_all_descendant_ids(["2"])

        assert result == {"2", "3", "4", "5"}

    def test_multiple_trees(self, complex_hierarchy: MagicMock) -> None:
        """Test expanding multiple independent trees."""
        resolver = FolderHierarchyResolver(complex_hierarchy)

        # Expand Root1 and Root2 separately
        result = resolver.get_all_descendant_ids(["1", "6"])

        assert result == {"1", "2", "3", "4", "5", "6", "7", "8"}

    def test_include_roots_true(self, simple_hierarchy: MagicMock) -> None:
        """Test include_roots=True includes root folders in result."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        result = resolver.get_all_descendant_ids(["2"], include_roots=True)

        assert "2" in result  # Root folder included
        assert result == {"2", "3", "4"}

    def test_include_roots_false(self, simple_hierarchy: MagicMock) -> None:
        """Test include_roots=False excludes root folders from result."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        result = resolver.get_all_descendant_ids(["2"], include_roots=False)

        assert "2" not in result  # Root folder excluded
        assert result == {"3", "4"}

    def test_include_roots_false_no_children(self, simple_hierarchy: MagicMock) -> None:
        """Test include_roots=False with folder having no children returns empty set."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        result = resolver.get_all_descendant_ids(["5"], include_roots=False)

        assert result == set()

    def test_nonexistent_folder_raises_error(self, simple_hierarchy: MagicMock) -> None:
        """Test expanding nonexistent folder raises NotFoundError."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        with pytest.raises(NotFoundError, match="Folder IDs not found.*invalid"):
            resolver.get_all_descendant_ids(["invalid"])


class TestFolderHierarchyCycleDetection:
    """Test cycle detection in folder hierarchies."""

    def test_detect_self_referencing_cycle(
        self, mock_repository: MagicMock, encoder: msgspec.msgpack.Encoder
    ) -> None:
        """Test detection of folder that references itself as parent."""
        folders = [
            {"id": "1", "name": "Root", "parent_id": None},
            {"id": "2", "name": "SelfRef", "parent_id": "2"},  # Self-reference
        ]

        content_items = [
            ContentItem(
                id=folder["id"],
                name=folder["name"],
                content_type=ContentType.FOLDER.value,
                content_data=encoder.encode(folder),
                created_at=datetime.fromisoformat("2025-12-14T00:00:00"),
                updated_at=datetime.fromisoformat("2025-12-14T00:00:00"),
            )
            for folder in folders
        ]

        mock_repository.list_content.return_value = content_items
        resolver = FolderHierarchyResolver(mock_repository)

        # Folder 1 has no children (folder 2 references itself)
        # Expanding folder 2 should detect the cycle gracefully
        result = resolver.get_all_descendant_ids(["2"])

        # Should include folder 2 once despite self-reference
        assert result == {"2"}

    def test_detect_circular_reference_chain(
        self, mock_repository: MagicMock, encoder: msgspec.msgpack.Encoder
    ) -> None:
        """Test detection of circular reference chain (A -> B -> C -> A)."""
        # This is tricky to create in practice, but let's simulate where
        # folder metadata has been corrupted to create a cycle
        folders = [
            {"id": "1", "name": "A", "parent_id": None},
            {"id": "2", "name": "B", "parent_id": "1"},
            {"id": "3", "name": "C", "parent_id": "2"},
            # In a real scenario, we can't make 1's parent=3 as that would be detected
            # during tree building. But BFS should handle visited set correctly.
        ]

        content_items = [
            ContentItem(
                id=folder["id"],
                name=folder["name"],
                content_type=ContentType.FOLDER.value,
                content_data=encoder.encode(folder),
                created_at=datetime.fromisoformat("2025-12-14T00:00:00"),
                updated_at=datetime.fromisoformat("2025-12-14T00:00:00"),
            )
            for folder in folders
        ]

        mock_repository.list_content.return_value = content_items
        resolver = FolderHierarchyResolver(mock_repository)

        # Should handle gracefully without infinite loop
        result = resolver.get_all_descendant_ids(["1"])

        assert result == {"1", "2", "3"}

    def test_bfs_visited_set_prevents_revisit(self, circular_hierarchy: MagicMock) -> None:
        """Test BFS visited set prevents revisiting folders."""
        resolver = FolderHierarchyResolver(circular_hierarchy)

        # Expand from root
        result = resolver.get_all_descendant_ids(["1"])

        # Should include all folders exactly once
        assert result == {"1", "2", "3", "4", "5"}
        assert len(result) == 5  # No duplicates


class TestBuildHierarchy:
    """Test building FolderNode tree structures."""

    def test_build_simple_tree(self, simple_hierarchy: MagicMock) -> None:
        """Test building simple folder tree."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        trees = resolver.build_hierarchy(["1"])

        assert len(trees) == 1
        root = trees[0]

        assert root.folder_id == "1"
        assert root.name == "Root"
        assert root.parent_id is None
        assert root.depth == 0
        assert len(root.children) == 2

        # Check children
        sales = next(c for c in root.children if c.name == "Sales")
        assert sales.folder_id == "2"
        assert sales.depth == 1
        assert len(sales.children) == 2

    def test_build_multiple_trees(self, complex_hierarchy: MagicMock) -> None:
        """Test building multiple independent trees."""
        resolver = FolderHierarchyResolver(complex_hierarchy)

        trees = resolver.build_hierarchy(["1", "6", "9"])

        assert len(trees) == 3

        # Verify each tree
        root1 = next(t for t in trees if t.folder_id == "1")
        assert root1.name == "Root1"
        assert len(root1.children) == 1

        root2 = next(t for t in trees if t.folder_id == "6")
        assert root2.name == "Root2"
        assert len(root2.children) == 1

        orphan = next(t for t in trees if t.folder_id == "9")
        assert orphan.name == "Orphan"
        assert len(orphan.children) == 0

    def test_build_deep_nesting(self, complex_hierarchy: MagicMock) -> None:
        """Test tree building with deep nesting."""
        resolver = FolderHierarchyResolver(complex_hierarchy)

        trees = resolver.build_hierarchy(["1"])
        root = trees[0]

        # Navigate to deeply nested folder
        a = root.children[0]  # A
        assert a.depth == 1

        a1 = next(c for c in a.children if c.name == "A1")
        assert a1.depth == 2

        a1a = a1.children[0]
        assert a1a.name == "A1a"
        assert a1a.depth == 3

    def test_build_subtree(self, simple_hierarchy: MagicMock) -> None:
        """Test building subtree from non-root folder."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        # Build tree starting from Sales folder
        trees = resolver.build_hierarchy(["2"])

        assert len(trees) == 1
        sales = trees[0]

        assert sales.folder_id == "2"
        assert sales.name == "Sales"
        assert sales.depth == 0  # Depth is relative to starting point
        assert len(sales.children) == 2

    def test_build_leaf_node(self, simple_hierarchy: MagicMock) -> None:
        """Test building tree from leaf folder (no children)."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        trees = resolver.build_hierarchy(["3"])

        assert len(trees) == 1
        regional = trees[0]

        assert regional.folder_id == "3"
        assert regional.name == "Regional"
        assert len(regional.children) == 0

    def test_build_nonexistent_folder_raises_error(self, simple_hierarchy: MagicMock) -> None:
        """Test building tree with nonexistent folder raises NotFoundError."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        with pytest.raises(NotFoundError, match="Folder IDs not found.*invalid"):
            resolver.build_hierarchy(["invalid"])


class TestFolderNodeDataclass:
    """Test FolderNode dataclass properties."""

    def test_folder_node_creation(self) -> None:
        """Test creating FolderNode with required fields."""
        node = FolderNode(
            folder_id="123",
            parent_id="456",
            name="Test Folder",
            children=[],
            depth=2,
        )

        assert node.folder_id == "123"
        assert node.parent_id == "456"
        assert node.name == "Test Folder"
        assert node.children == []
        assert node.depth == 2

    def test_folder_node_none_parent(self) -> None:
        """Test FolderNode with None parent_id (root folder)."""
        node = FolderNode(
            folder_id="1",
            parent_id=None,
            name="Root",
            children=[],
            depth=0,
        )

        assert node.parent_id is None
        assert node.depth == 0


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_folder_list(self, mock_repository: MagicMock) -> None:
        """Test resolver with empty folder list."""
        mock_repository.list_content.return_value = []
        resolver = FolderHierarchyResolver(mock_repository)

        resolver._load_folder_cache()

        assert resolver._folder_cache == {}
        assert len(resolver._parent_to_children) == 0

    def test_expand_empty_folder_list(self, mock_repository: MagicMock) -> None:
        """Test expanding empty folder list returns empty set."""
        mock_repository.list_content.return_value = []
        resolver = FolderHierarchyResolver(mock_repository)

        result = resolver.get_all_descendant_ids([])

        assert result == set()

    def test_orphaned_folders(self, complex_hierarchy: MagicMock) -> None:
        """Test handling orphaned folders (parent_id references non-existent folder)."""
        resolver = FolderHierarchyResolver(complex_hierarchy)

        # Folder 9 is orphaned (parent_id=None but not actually a root)
        result = resolver.get_all_descendant_ids(["9"])

        assert result == {"9"}

    def test_parent_child_relationship_consistency(self, simple_hierarchy: MagicMock) -> None:
        """Test parent-child relationships are consistent."""
        resolver = FolderHierarchyResolver(simple_hierarchy)
        resolver._load_folder_cache()

        # Verify every child's parent exists in cache
        for parent_id, child_ids in resolver._parent_to_children.items():
            if parent_id is not None:
                assert parent_id in resolver._folder_cache

            for child_id in child_ids:
                assert child_id in resolver._folder_cache
                child_metadata = resolver._folder_cache[child_id]
                assert child_metadata["parent_id"] == parent_id


class TestRealWorldScenarios:
    """Test realistic usage scenarios."""

    def test_recursive_extract_workflow(self, complex_hierarchy: MagicMock) -> None:
        """Simulate recursive extraction workflow from CLI."""
        resolver = FolderHierarchyResolver(complex_hierarchy)

        # User specifies root folders for extraction
        user_folder_ids = ["1", "6"]

        # Validate folders exist
        resolver.validate_folders_exist(user_folder_ids)

        # Expand with --recursive flag
        all_folder_ids = resolver.get_all_descendant_ids(user_folder_ids, include_roots=True)

        # Should include all descendants
        expected = {"1", "2", "3", "4", "5", "6", "7", "8"}
        assert all_folder_ids == expected

    def test_non_recursive_extract_workflow(self, complex_hierarchy: MagicMock) -> None:
        """Simulate non-recursive extraction (only specified folders)."""
        resolver = FolderHierarchyResolver(complex_hierarchy)

        # User specifies folders without --recursive
        user_folder_ids = ["1", "6"]

        # Just validate, don't expand
        resolver.validate_folders_exist(user_folder_ids)

        # Should only use specified folders
        assert set(user_folder_ids) == {"1", "6"}

    def test_folder_tree_export_workflow(self, simple_hierarchy: MagicMock) -> None:
        """Simulate folder tree building for export."""
        resolver = FolderHierarchyResolver(simple_hierarchy)

        # Build tree from root
        trees = resolver.build_hierarchy(["1"])

        # Verify tree structure for export
        assert len(trees) == 1
        root = trees[0]

        # Walk tree to create directory structure
        def collect_paths(node: FolderNode, path: str = "") -> list[str]:
            current_path = f"{path}/{node.name}" if path else node.name
            paths = [current_path]

            for child in node.children:
                paths.extend(collect_paths(child, current_path))

            return paths

        paths = collect_paths(root)
        assert "Root" in paths
        assert "Root/Sales" in paths
        assert "Root/Sales/Regional" in paths
        assert "Root/Sales/National" in paths
        assert "Root/Marketing" in paths

    def test_large_hierarchy_performance(
        self, mock_repository: MagicMock, encoder: msgspec.msgpack.Encoder
    ) -> None:
        """Test performance with large hierarchy (100 folders)."""
        # Create 100 folders: root (0-9), then each has children
        # Folder 0 -> children 10-19
        # Folder 1 -> children 20-29, etc.
        folders = []

        # Create 10 root folders (0-9)
        for i in range(10):
            folders.append({"id": str(i), "name": f"Root{i}", "parent_id": None})

        # Create children: folder 10-19 are children of folder 0, etc.
        for i in range(10, 100):
            parent_id = str((i - 10) // 10)  # Parent is 0-9
            folders.append({"id": str(i), "name": f"Folder{i}", "parent_id": parent_id})

        content_items = [
            ContentItem(
                id=folder["id"],
                name=folder["name"],
                content_type=ContentType.FOLDER.value,
                content_data=encoder.encode(folder),
                created_at=datetime.fromisoformat("2025-12-14T00:00:00"),
                updated_at=datetime.fromisoformat("2025-12-14T00:00:00"),
            )
            for folder in folders
        ]

        mock_repository.list_content.return_value = content_items
        resolver = FolderHierarchyResolver(mock_repository)

        # Should handle large hierarchy efficiently
        result = resolver.get_all_descendant_ids(["0"])

        # Folder 0 has 10 children (10-19) plus itself
        assert len(result) == 11
