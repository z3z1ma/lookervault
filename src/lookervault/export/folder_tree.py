"""Folder tree construction for YAML export with folder hierarchy strategy.

This module builds filesystem directory structures from Looker folder relationships
using BFS traversal with cycle detection.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lookervault.export.path_utils import sanitize_folder_name

logger = logging.getLogger(__name__)


@dataclass
class FolderTreeNode:
    """Tree node for folder hierarchy construction.

    Represents a single folder in the hierarchy with its position,
    children, and sanitized filesystem path.
    """

    id: str  # Folder ID
    name: str  # Folder name
    parent_id: str | None  # Parent folder ID (None for root)
    sanitized_name: str  # Filesystem-safe name
    depth: int  # Nesting level (0 = root)

    # Tree structure
    children: list[FolderTreeNode] = field(default_factory=list)
    parent: FolderTreeNode | None = None

    # Content tracking
    dashboard_count: int = 0
    look_count: int = 0

    @property
    def filesystem_path(self) -> str:
        """Construct full filesystem path from root to this node.

        Returns:
            Slash-separated path like "Sales/Regional/West"
        """
        if self.parent is None:
            return self.sanitized_name

        return f"{self.parent.filesystem_path}/{self.sanitized_name}"

    @property
    def is_root(self) -> bool:
        """Check if this is a root folder (no parent).

        Returns:
            True if parent_id is None
        """
        return self.parent_id is None


class FolderTreeBuilder:
    """Builds folder hierarchy tree from flat folder list with cycle detection.

    Uses BFS traversal to detect circular references and construct tree structure
    suitable for creating nested filesystem directories.
    """

    def __init__(self) -> None:
        """Initialize tree builder with empty caches."""
        self._folder_cache: dict[str, dict[str, Any]] = {}
        self._parent_to_children: dict[str | None, list[str]] = defaultdict(list)
        self._nodes: dict[str, FolderTreeNode] = {}

    def build_from_folders(self, folders: list[dict[str, Any]]) -> list[FolderTreeNode]:
        """Build folder tree from list of folder metadata dicts.

        Args:
            folders: List of folder metadata dicts with id, name, parent_id fields

        Returns:
            List of root FolderTreeNode objects (parent_id is None)

        Raises:
            ValueError: If circular reference detected in folder hierarchy
        """
        # Phase 1: Cache folder metadata and build adjacency map
        for folder in folders:
            folder_id = folder["id"]
            parent_id = folder.get("parent_id")

            self._folder_cache[folder_id] = folder
            self._parent_to_children[parent_id].append(folder_id)

        # Phase 2: Build tree nodes using BFS
        root_ids = self._parent_to_children[None]
        roots = []

        for root_id in root_ids:
            root_node = self._build_subtree(root_id, parent_node=None, depth=0)
            roots.append(root_node)

        return roots

    def _build_subtree(
        self, folder_id: str, parent_node: FolderTreeNode | None, depth: int
    ) -> FolderTreeNode:
        """Recursively build subtree starting from folder_id.

        Args:
            folder_id: Folder ID to build node for
            parent_node: Parent FolderTreeNode (None for roots)
            depth: Current depth in tree (0 for roots)

        Returns:
            FolderTreeNode with children populated

        Raises:
            ValueError: If folder_id not found in cache or cycle detected
        """
        if folder_id not in self._folder_cache:
            raise ValueError(f"Folder {folder_id} not found in metadata")

        # Check for cycles by detecting if we've already visited this node
        # in the current path (would mean circular parent reference)
        if folder_id in self._nodes:
            # This node was already created - potential cycle!
            existing_node = self._nodes[folder_id]
            if existing_node.depth < depth:
                # We're trying to add it again deeper in tree = cycle
                raise ValueError(
                    f"Circular reference detected: folder {folder_id} appears "
                    f"at depths {existing_node.depth} and {depth}"
                )
            # If depths match or new depth is shallower, we're seeing same
            # node via different path - return existing
            return existing_node

        folder = self._folder_cache[folder_id]

        # Sanitize folder name for filesystem
        try:
            sanitized = sanitize_folder_name(folder["name"])
        except ValueError:
            logger.warning(f"Folder {folder_id} has invalid name, using ID as fallback")
            sanitized = f"folder_{folder_id}"

        # Create node
        node = FolderTreeNode(
            id=folder_id,
            name=folder["name"],
            parent_id=folder.get("parent_id"),
            sanitized_name=sanitized,
            depth=depth,
            parent=parent_node,
        )

        # Cache node to detect cycles
        self._nodes[folder_id] = node

        # Build children recursively
        child_ids = self._parent_to_children.get(folder_id, [])
        for child_id in child_ids:
            try:
                child_node = self._build_subtree(child_id, parent_node=node, depth=depth + 1)
                node.children.append(child_node)
            except ValueError as e:
                # Cycle detected in child subtree
                logger.error(f"Skipping child {child_id} of {folder_id}: {e}")
                # Continue with other children rather than failing entire tree

        return node

    def get_all_descendant_ids(self, root_ids: list[str]) -> set[str]:
        """Expand root folders to include all descendants using BFS.

        Args:
            root_ids: List of root folder IDs to expand

        Returns:
            Set of all folder IDs (roots + all descendants)
        """
        visited = set()
        queue = deque(root_ids)
        all_ids = set(root_ids)

        while queue:
            current_id = queue.popleft()

            # Cycle detection
            if current_id in visited:
                logger.warning(f"Cycle detected at folder {current_id} - skipping")
                continue

            visited.add(current_id)

            # Add children to queue
            child_ids = self._parent_to_children.get(current_id, [])
            for child_id in child_ids:
                all_ids.add(child_id)
                if child_id not in visited:
                    queue.append(child_id)

        return all_ids

    def create_directory_hierarchy(self, root_nodes: list[FolderTreeNode], base_path: Path) -> None:
        """Create nested filesystem directories from folder tree.

        Args:
            root_nodes: Root FolderTreeNode objects
            base_path: Base directory path for exports

        Creates directories recursively with sanitized names.
        """
        for root in root_nodes:
            self._create_directory_recursive(root, base_path)

    def _create_directory_recursive(self, node: FolderTreeNode, base_path: Path) -> None:
        """Recursively create directory for node and all children.

        Args:
            node: FolderTreeNode to create directory for
            base_path: Base directory path
        """
        # Construct full path for this node
        if node.parent is None:
            # Root node - create directly under base_path
            dir_path = base_path / node.sanitized_name
        else:
            # Child node - create under parent's path
            parent_path = base_path / Path(node.parent.filesystem_path)
            dir_path = parent_path / node.sanitized_name

        # Create directory (parents=True handles intermediate dirs)
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created directory: {dir_path}")

        # Recursively create children
        for child in node.children:
            self._create_directory_recursive(child, base_path)

    def get_all_nodes(self, root_nodes: list[FolderTreeNode]) -> dict[str, FolderTreeNode]:
        """Get all nodes in the tree as a flat dict keyed by node ID.

        Args:
            root_nodes: Root FolderTreeNode objects

        Returns:
            Dictionary mapping node ID to FolderTreeNode for all nodes in tree
        """
        all_nodes: dict[str, FolderTreeNode] = {}

        def collect_nodes(node: FolderTreeNode) -> None:
            """Recursively collect all nodes from a subtree."""
            all_nodes[node.id] = node
            for child in node.children:
                collect_nodes(child)

        for root in root_nodes:
            collect_nodes(root)

        return all_nodes
