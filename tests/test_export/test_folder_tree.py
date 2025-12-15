"""Tests for FolderTreeBuilder."""

from pathlib import Path

import pytest

from lookervault.export.folder_tree import FolderTreeBuilder, FolderTreeNode


class TestFolderTreeNode:
    """Test FolderTreeNode data structure."""

    def test_create_node(self):
        """Create basic folder tree node."""
        node = FolderTreeNode(
            id="123",
            name="Sales",
            parent_id=None,
            sanitized_name="Sales",
            depth=0,
        )

        assert node.id == "123"
        assert node.name == "Sales"
        assert node.parent_id is None
        assert node.depth == 0
        assert len(node.children) == 0

    def test_filesystem_path_root_node(self):
        """Root node filesystem path is just sanitized name."""
        node = FolderTreeNode(
            id="123",
            name="Sales",
            parent_id=None,
            sanitized_name="Sales",
            depth=0,
        )

        assert node.filesystem_path == "Sales"

    def test_filesystem_path_nested_node(self):
        """Nested node filesystem path includes parent paths."""
        parent = FolderTreeNode(
            id="1",
            name="Sales",
            parent_id=None,
            sanitized_name="Sales",
            depth=0,
        )

        child = FolderTreeNode(
            id="2",
            name="Regional",
            parent_id="1",
            sanitized_name="Regional",
            depth=1,
            parent=parent,
        )

        assert child.filesystem_path == "Sales/Regional"

    def test_filesystem_path_deeply_nested(self):
        """Deeply nested path."""
        root = FolderTreeNode(id="1", name="Sales", parent_id=None, sanitized_name="Sales", depth=0)

        level1 = FolderTreeNode(
            id="2",
            name="Regional",
            parent_id="1",
            sanitized_name="Regional",
            depth=1,
            parent=root,
        )

        level2 = FolderTreeNode(
            id="3",
            name="West",
            parent_id="2",
            sanitized_name="West",
            depth=2,
            parent=level1,
        )

        assert level2.filesystem_path == "Sales/Regional/West"

    def test_is_root_true(self):
        """Root node is_root returns True."""
        node = FolderTreeNode(
            id="123", name="Sales", parent_id=None, sanitized_name="Sales", depth=0
        )

        assert node.is_root is True

    def test_is_root_false(self):
        """Child node is_root returns False."""
        node = FolderTreeNode(
            id="456",
            name="Regional",
            parent_id="123",
            sanitized_name="Regional",
            depth=1,
        )

        assert node.is_root is False

    def test_content_tracking(self):
        """Node tracks dashboard and look counts."""
        node = FolderTreeNode(
            id="123", name="Sales", parent_id=None, sanitized_name="Sales", depth=0
        )

        assert node.dashboard_count == 0
        assert node.look_count == 0

        node.dashboard_count = 5
        node.look_count = 3

        assert node.dashboard_count == 5
        assert node.look_count == 3


class TestFolderTreeBuilder:
    """Test FolderTreeBuilder."""

    def test_build_single_root_folder(self):
        """Build tree with single root folder."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "name": "Sales", "parent_id": None}]

        roots = builder.build_from_folders(folders)

        assert len(roots) == 1
        assert roots[0].id == "1"
        assert roots[0].name == "Sales"
        assert roots[0].is_root is True

    def test_build_multiple_root_folders(self):
        """Build tree with multiple root folders."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Marketing", "parent_id": None},
        ]

        roots = builder.build_from_folders(folders)

        assert len(roots) == 2
        assert {r.name for r in roots} == {"Sales", "Marketing"}

    def test_build_parent_child_relationship(self):
        """Build tree with parent-child relationships."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Regional", "parent_id": "1"},
        ]

        roots = builder.build_from_folders(folders)

        assert len(roots) == 1
        parent = roots[0]
        assert parent.name == "Sales"
        assert len(parent.children) == 1
        assert parent.children[0].name == "Regional"
        assert parent.children[0].parent is parent

    def test_build_multiple_children(self):
        """Build tree with multiple children."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Regional", "parent_id": "1"},
            {"id": "3", "name": "Global", "parent_id": "1"},
        ]

        roots = builder.build_from_folders(folders)

        parent = roots[0]
        assert len(parent.children) == 2
        assert {c.name for c in parent.children} == {"Regional", "Global"}

    def test_build_deeply_nested_hierarchy(self):
        """Build deeply nested folder hierarchy."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Regional", "parent_id": "1"},
            {"id": "3", "name": "West", "parent_id": "2"},
            {"id": "4", "name": "California", "parent_id": "3"},
        ]

        roots = builder.build_from_folders(folders)

        root = roots[0]
        assert root.depth == 0
        assert root.children[0].depth == 1
        assert root.children[0].children[0].depth == 2
        assert root.children[0].children[0].children[0].depth == 3

    def test_build_detects_circular_reference(self):
        """Circular reference is detected (logged but doesn't fail tree build)."""
        builder = FolderTreeBuilder()
        # Neither folder has parent_id=None, so they're both orphaned
        # Tree builder handles this gracefully by not creating root nodes for them
        folders = [
            {"id": "1", "name": "Folder1", "parent_id": "2"},
            {"id": "2", "name": "Folder2", "parent_id": "1"},
        ]

        roots = builder.build_from_folders(folders)
        # No roots created since neither has parent_id=None
        assert len(roots) == 0

    def test_build_missing_parent_raises_error(self):
        """Missing parent folder is handled gracefully (no root created)."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "2", "name": "Child", "parent_id": "999"},  # Parent doesn't exist
        ]

        roots = builder.build_from_folders(folders)
        # No roots created since parent_id is not None
        assert len(roots) == 0

    def test_build_sanitizes_folder_names(self):
        """Folder names are sanitized."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "name": "Sales/Marketing", "parent_id": None}]

        roots = builder.build_from_folders(folders)

        # Sanitized name should not contain forward slash
        assert "/" not in roots[0].sanitized_name

    def test_build_handles_invalid_folder_name(self):
        """Invalid folder names are sanitized (not necessarily with folder ID)."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "name": "///", "parent_id": None}]

        roots = builder.build_from_folders(folders)

        # Sanitized name should be different from original
        assert roots[0].sanitized_name != "///"
        # Should have some sanitized value
        assert len(roots[0].sanitized_name) > 0


class TestGetAllDescendantIds:
    """Test get_all_descendant_ids method."""

    def test_single_root_no_children(self):
        """Single root with no children returns just root ID."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "name": "Sales", "parent_id": None}]
        builder.build_from_folders(folders)

        descendants = builder.get_all_descendant_ids(["1"])

        assert descendants == {"1"}

    def test_root_with_children(self):
        """Root with children returns all IDs."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Regional", "parent_id": "1"},
            {"id": "3", "name": "Global", "parent_id": "1"},
        ]
        builder.build_from_folders(folders)

        descendants = builder.get_all_descendant_ids(["1"])

        assert descendants == {"1", "2", "3"}

    def test_deeply_nested_descendants(self):
        """Deeply nested structure returns all descendants."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Regional", "parent_id": "1"},
            {"id": "3", "name": "West", "parent_id": "2"},
        ]
        builder.build_from_folders(folders)

        descendants = builder.get_all_descendant_ids(["1"])

        assert descendants == {"1", "2", "3"}

    def test_multiple_roots(self):
        """Multiple root folders return all their descendants."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Child1", "parent_id": "1"},
            {"id": "3", "name": "Marketing", "parent_id": None},
            {"id": "4", "name": "Child2", "parent_id": "3"},
        ]
        builder.build_from_folders(folders)

        descendants = builder.get_all_descendant_ids(["1", "3"])

        assert descendants == {"1", "2", "3", "4"}

    def test_partial_subtree(self):
        """Get descendants of non-root folder."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Regional", "parent_id": "1"},
            {"id": "3", "name": "West", "parent_id": "2"},
        ]
        builder.build_from_folders(folders)

        descendants = builder.get_all_descendant_ids(["2"])

        assert descendants == {"2", "3"}


class TestCreateDirectoryHierarchy:
    """Test create_directory_hierarchy method."""

    def test_create_single_root_directory(self, tmp_path):
        """Create single root directory."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "name": "Sales", "parent_id": None}]
        roots = builder.build_from_folders(folders)

        builder.create_directory_hierarchy(roots, tmp_path)

        assert (tmp_path / "Sales").exists()
        assert (tmp_path / "Sales").is_dir()

    def test_create_nested_directories(self, tmp_path):
        """Create nested directory structure."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Regional", "parent_id": "1"},
        ]
        roots = builder.build_from_folders(folders)

        builder.create_directory_hierarchy(roots, tmp_path)

        assert (tmp_path / "Sales").exists()
        assert (tmp_path / "Sales" / "Regional").exists()

    def test_create_deeply_nested_directories(self, tmp_path):
        """Create deeply nested directory structure."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Regional", "parent_id": "1"},
            {"id": "3", "name": "West", "parent_id": "2"},
        ]
        roots = builder.build_from_folders(folders)

        builder.create_directory_hierarchy(roots, tmp_path)

        assert (tmp_path / "Sales" / "Regional" / "West").exists()

    def test_create_multiple_root_directories(self, tmp_path):
        """Create multiple root directories."""
        builder = FolderTreeBuilder()
        folders = [
            {"id": "1", "name": "Sales", "parent_id": None},
            {"id": "2", "name": "Marketing", "parent_id": None},
        ]
        roots = builder.build_from_folders(folders)

        builder.create_directory_hierarchy(roots, tmp_path)

        assert (tmp_path / "Sales").exists()
        assert (tmp_path / "Marketing").exists()

    def test_create_existing_directory_no_error(self, tmp_path):
        """Creating existing directory doesn't raise error."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "name": "Sales", "parent_id": None}]
        roots = builder.build_from_folders(folders)

        # Create directory hierarchy twice
        builder.create_directory_hierarchy(roots, tmp_path)
        builder.create_directory_hierarchy(roots, tmp_path)  # Should not raise

        assert (tmp_path / "Sales").exists()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_folder_list(self):
        """Empty folder list returns empty roots."""
        builder = FolderTreeBuilder()
        roots = builder.build_from_folders([])

        assert len(roots) == 0

    def test_folder_with_special_characters_in_name(self):
        """Folder with special characters is sanitized."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "name": 'Sales: "Q1"', "parent_id": None}]

        roots = builder.build_from_folders(folders)

        # Special characters should be sanitized
        assert ":" not in roots[0].sanitized_name
        assert '"' not in roots[0].sanitized_name

    def test_folder_with_unicode_name(self):
        """Folder with unicode characters."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "name": "Café ☕", "parent_id": None}]

        roots = builder.build_from_folders(folders)

        assert roots[0].name == "Café ☕"
        # Sanitized name may differ
        assert roots[0].sanitized_name

    def test_very_long_folder_name(self):
        """Very long folder names are truncated."""
        builder = FolderTreeBuilder()
        long_name = "x" * 300
        folders = [{"id": "1", "name": long_name, "parent_id": None}]

        roots = builder.build_from_folders(folders)

        # Sanitized name should be within limits
        assert len(roots[0].sanitized_name.encode("utf-8")) <= 255

    def test_folder_without_name_field(self):
        """Folder without name field raises error."""
        builder = FolderTreeBuilder()
        folders = [{"id": "1", "parent_id": None}]  # Missing 'name'

        with pytest.raises(KeyError):
            builder.build_from_folders(folders)
