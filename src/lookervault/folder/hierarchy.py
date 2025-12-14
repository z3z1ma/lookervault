"""Folder hierarchy resolution for recursive folder filtering."""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import msgspec.json

from lookervault.exceptions import NotFoundError
from lookervault.storage.models import ContentType
from lookervault.storage.repository import ContentRepository

logger = logging.getLogger(__name__)


@dataclass
class FolderNode:
    """Represents a folder in the hierarchy tree."""

    folder_id: str
    parent_id: str | None
    name: str
    children: list["FolderNode"]
    depth: int


class FolderHierarchyResolver:
    """Resolves folder hierarchies and builds folder trees from repository data.

    This class provides methods to:
    - Build folder trees from root folder IDs
    - Recursively expand folder IDs to include all descendants
    - Validate that folder IDs exist in the repository

    The resolver works by loading folder metadata from the repository's serialized
    content_data BLOBs and building parent-child relationship maps.
    """

    def __init__(self, repository: ContentRepository):
        """Initialize the resolver with a content repository.

        Args:
            repository: Content repository to load folder metadata from
        """
        self.repository = repository
        self._folder_cache: dict[str, dict[str, Any]] = {}
        self._parent_to_children: dict[str | None, list[str]] = defaultdict(list)
        self._cache_loaded = False

    def _load_folder_cache(self) -> None:
        """Load all folder metadata into cache and build parent-child map.

        This method:
        1. Queries all FOLDER content from repository
        2. Deserializes content_data BLOB using msgspec
        3. Builds folder_id -> metadata dict
        4. Builds parent_id -> [child_ids] adjacency map
        """
        if self._cache_loaded:
            return

        logger.debug("Loading folder metadata from repository")

        # Load all folder content items
        folders = self.repository.list_content(
            content_type=ContentType.FOLDER.value, include_deleted=False
        )

        logger.debug(f"Loaded {len(folders)} folders from repository")

        # Deserialize and cache
        decoder = msgspec.json.Decoder()
        for folder_item in folders:
            # Deserialize content_data BLOB
            folder_metadata = decoder.decode(folder_item.content_data)

            # Cache metadata
            self._folder_cache[folder_item.id] = folder_metadata

            # Build parent -> children map
            parent_id = folder_metadata.get("parent_id")
            self._parent_to_children[parent_id].append(folder_item.id)

        self._cache_loaded = True
        logger.debug(
            f"Folder cache loaded: {len(self._folder_cache)} folders, "
            f"{len(self._parent_to_children)} unique parents"
        )

    def get_folder_metadata(self, folder_id: str) -> dict[str, Any]:
        """Get folder metadata from serialized content_data.

        Args:
            folder_id: Folder ID

        Returns:
            Deserialized folder metadata dict with parent_id, name, etc.

        Raises:
            NotFoundError: If folder ID not found in repository
        """
        self._load_folder_cache()

        if folder_id not in self._folder_cache:
            raise NotFoundError(f"Folder ID '{folder_id}' not found in repository")

        return self._folder_cache[folder_id]

    def validate_folders_exist(self, folder_ids: list[str]) -> None:
        """Validate all folder IDs exist in repository.

        Args:
            folder_ids: List of folder IDs to validate

        Raises:
            NotFoundError: If any folder ID not found
        """
        self._load_folder_cache()

        missing_ids = [fid for fid in folder_ids if fid not in self._folder_cache]

        if missing_ids:
            raise NotFoundError(f"Folder IDs not found in repository: {', '.join(missing_ids)}")

    def get_all_descendant_ids(self, folder_ids: list[str], include_roots: bool = True) -> set[str]:
        """Get all folder IDs in subtree (recursive).

        Uses BFS traversal to expand folder IDs to include all descendants.
        Handles cycles gracefully using a visited set.

        Args:
            folder_ids: Root folder IDs to expand
            include_roots: Include root folders in result (default: True)

        Returns:
            Set of all folder IDs (roots + all descendants if include_roots=True,
            otherwise just descendants)

        Raises:
            NotFoundError: If any root folder ID not found in repository
        """
        self._load_folder_cache()

        # Validate root folders exist
        self.validate_folders_exist(folder_ids)

        # BFS traversal
        visited: set[str] = set()
        queue: deque[str] = deque(folder_ids)
        all_folder_ids: set[str] = set(folder_ids) if include_roots else set()

        while queue:
            current_id = queue.popleft()

            # Skip if already visited (handles cycles)
            if current_id in visited:
                logger.warning(
                    f"Detected cycle in folder hierarchy at folder '{current_id}' - skipping"
                )
                continue

            visited.add(current_id)

            # Get children from parent -> children map
            children = self._parent_to_children.get(current_id, [])

            for child_id in children:
                # Add child to result set
                all_folder_ids.add(child_id)

                # Queue child for traversal if not visited
                if child_id not in visited:
                    queue.append(child_id)

        logger.info(
            f"Expanded {len(folder_ids)} root folder(s) to {len(all_folder_ids)} total folder(s)"
        )

        return all_folder_ids

    def build_hierarchy(self, root_folder_ids: list[str]) -> list[FolderNode]:
        """Build folder tree from root folder IDs.

        Args:
            root_folder_ids: Starting folder IDs

        Returns:
            List of FolderNode trees with populated children

        Raises:
            NotFoundError: If folder ID not found in repository
        """
        self._load_folder_cache()
        self.validate_folders_exist(root_folder_ids)

        def build_node(folder_id: str, depth: int) -> FolderNode:
            """Recursively build FolderNode tree."""
            metadata = self._folder_cache[folder_id]

            # Build children recursively
            child_ids = self._parent_to_children.get(folder_id, [])
            children = [build_node(child_id, depth + 1) for child_id in child_ids]

            return FolderNode(
                folder_id=folder_id,
                parent_id=metadata.get("parent_id"),
                name=metadata.get("name", "Unknown"),
                children=children,
                depth=depth,
            )

        # Build trees for each root
        trees = [build_node(root_id, 0) for root_id in root_folder_ids]

        return trees
