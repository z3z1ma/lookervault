# Data Model: YAML Export/Import

**Feature**: YAML Export/Import for Looker Content
**Branch**: `006-yaml-export-import`
**Date**: 2025-12-14
**Prerequisites**: [research.md](./research.md) - Library choices and algorithm decisions

## Overview

This document defines the data structures for YAML export/import operations in LookerVault. The design supports two export strategies (full and folder-based) with round-trip fidelity guarantees.

## Core Entities

### 1. Export Metadata

**Purpose**: Manifest file at root of export directory containing essential context for repacking.

**File Location**: `<output_dir>/metadata.json`

**Schema**:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class ExportStrategy(str, Enum):
    """Export organization strategy."""
    FULL = "full"      # Content organized by type
    FOLDER = "folder"  # Dashboards/looks in folder hierarchy

@dataclass
class ExportMetadata:
    """Export manifest metadata."""

    # Required fields
    version: str                          # Metadata format version (e.g., "1.0.0")
    export_timestamp: datetime            # When export was created
    strategy: ExportStrategy              # Export strategy used
    database_schema_version: int          # SQLite schema version (from schema.py)

    # Content summary
    content_type_counts: dict[str, int]   # ContentType.name → count
    total_items: int                      # Total content items exported

    # Optional fields (strategy-dependent)
    folder_map: dict[str, FolderInfo] | None = None  # Only for folder strategy

    # Export configuration
    content_type_filter: list[str] | None = None  # If --content-types was used
    source_database: str | None = None    # Original database path

    # Checksum for integrity validation
    checksum: str | None = None           # SHA-256 of all YAML files combined
```

**JSON Representation**:

```json
{
  "version": "1.0.0",
  "export_timestamp": "2025-12-14T10:30:00Z",
  "strategy": "full",
  "database_schema_version": 3,
  "content_type_counts": {
    "DASHBOARD": 1250,
    "LOOK": 834,
    "USER": 156,
    "FOLDER": 47,
    "GROUP": 23,
    "ROLE": 12,
    "BOARD": 8,
    "LOOKML_MODEL": 5,
    "EXPLORE": 42,
    "PERMISSION_SET": 7,
    "MODEL_SET": 3,
    "SCHEDULED_PLAN": 18
  },
  "total_items": 2405,
  "folder_map": null,
  "content_type_filter": null,
  "source_database": "/path/to/looker.db",
  "checksum": "a1b2c3d4e5f6..."
}
```

### 2. Folder Information

**Purpose**: Metadata for reconstructing folder hierarchy (folder strategy only).

**Schema**:

```python
@dataclass
class FolderInfo:
    """Folder metadata for hierarchy reconstruction."""

    id: str                    # Looker folder ID
    name: str                  # Folder display name
    parent_id: str | None      # Parent folder ID (None for root folders)
    path: str                  # Sanitized filesystem path (e.g., "Sales/Regional/West")
    depth: int                 # Nesting level (0 = root)
    child_count: int           # Number of direct children (folders + content)

    # Sanitization metadata
    original_name: str | None  # If name was sanitized, store original
    sanitized: bool = False    # True if path was modified for filesystem safety
```

**JSON Representation** (in metadata.json):

```json
{
  "folder_map": {
    "789": {
      "id": "789",
      "name": "Sales",
      "parent_id": null,
      "path": "Sales",
      "depth": 0,
      "child_count": 2,
      "original_name": null,
      "sanitized": false
    },
    "790": {
      "id": "790",
      "name": "Regional",
      "parent_id": "789",
      "path": "Sales/Regional",
      "depth": 1,
      "child_count": 2,
      "original_name": null,
      "sanitized": false
    },
    "791": {
      "id": "791",
      "name": "West",
      "parent_id": "790",
      "path": "Sales/Regional/West",
      "depth": 2,
      "child_count": 5,
      "original_name": null,
      "sanitized": false
    }
  }
}
```

### 3. YAML Content Item

**Purpose**: Individual content item serialized to YAML with internal metadata for round-trip fidelity.

**File Location**:
- **Full strategy**: `<output_dir>/<content_type>/<item_id>.yaml`
- **Folder strategy**: `<output_dir>/<folder_path>/<item_id>.yaml`

**Structure**:

```yaml
# Internal metadata section (prefixed with _)
_metadata:
  db_id: "abc123def456"              # Original SQLite row ID
  content_type: "DASHBOARD"          # ContentType enum name
  exported_at: "2025-12-14T10:30:15Z"
  folder_path: "Sales/Regional/West" # Only for folder strategy
  content_size: 12845                # Original blob size in bytes
  checksum: "sha256:a1b2c3..."       # SHA-256 of original msgpack blob

# Looker SDK fields (from Dashboard, Look, User, etc.)
id: "42"
title: "Sales Performance Dashboard"
description: "Q4 sales metrics by region"
user_id: "123"
dashboard_filters: []
dashboard_elements:
  - id: "elem_1"
    title: "Total Revenue"
    type: "vis"
    query_id: "456"
    # Embedded query definition (if present)
    query:
      model: "sales_model"
      view: "orders"
      fields:
        - "orders.count"
        - "orders.total_revenue"
      filters:
        orders.created_date: "30 days"
      sorts:
        - "orders.total_revenue desc"
      limit: "100"
  - id: "elem_2"
    title: "Revenue by Region"
    type: "vis"
    query_id: "457"
created_at: "2024-01-15T08:00:00Z"
updated_at: "2025-12-10T14:22:00Z"
folder_id: "791"
view_count: 1247
```

**Python Schema**:

```python
@dataclass
class YamlContentMetadata:
    """Internal metadata embedded in YAML files."""

    db_id: str                    # Original database row ID
    content_type: str             # ContentType enum name
    exported_at: datetime         # Export timestamp
    content_size: int             # Original msgpack blob size
    checksum: str                 # SHA-256 of original blob
    folder_path: str | None = None  # Only for folder strategy

@dataclass
class YamlContentItem:
    """Complete YAML content item structure."""

    _metadata: YamlContentMetadata  # Internal metadata
    # All other fields are dynamic based on ContentType
    # (Dashboard, Look, User, etc. from Looker SDK models)
```

### 4. Query Remapping Table

**Purpose**: Track modified queries during pack operations to update dashboard element references.

**Scope**: In-memory during pack; optionally persisted to `<input_dir>/.pack_state/query_remapping.json`

**Schema**:

```python
from dataclasses import dataclass, field

@dataclass
class QueryRemapEntry:
    """Single query remapping record."""

    original_query_id: str        # Old query ID from YAML
    new_query_id: str             # New query ID created in database
    query_hash: str               # SHA-256 hash of query definition
    dashboard_element_ids: list[str]  # Elements referencing this query
    created_at: datetime          # When new query was created

@dataclass
class QueryRemappingTable:
    """In-memory table for query ID remapping."""

    entries: dict[str, QueryRemapEntry] = field(default_factory=dict)  # query_hash → entry
    hash_index: dict[str, str] = field(default_factory=dict)  # query_hash → new_query_id

    def get_or_create(self, query_def: dict, original_id: str) -> str:
        """Get existing new_query_id for hash or mark for creation."""
        query_hash = self._hash_query(query_def)

        if query_hash in self.hash_index:
            # Reuse existing new query (shared query deduplication)
            return self.hash_index[query_hash]

        # Mark for creation
        new_query_id = self._generate_new_id()
        entry = QueryRemapEntry(
            original_query_id=original_id,
            new_query_id=new_query_id,
            query_hash=query_hash,
            dashboard_element_ids=[],
            created_at=datetime.now()
        )
        self.entries[query_hash] = entry
        self.hash_index[query_hash] = new_query_id
        return new_query_id

    def _hash_query(self, query_def: dict) -> str:
        """Generate SHA-256 hash of normalized query definition."""
        # Normalize: sort keys, canonical JSON
        normalized = json.dumps(query_def, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
```

**Persistence Format** (optional):

```json
{
  "query_remapping": {
    "a1b2c3d4...": {
      "original_query_id": "456",
      "new_query_id": "789",
      "query_hash": "a1b2c3d4...",
      "dashboard_element_ids": ["elem_1", "elem_5", "elem_12"],
      "created_at": "2025-12-14T10:35:22Z"
    }
  }
}
```

### 5. Folder Tree Node

**Purpose**: Internal data structure for constructing nested directory structure from flat folder relationships.

**Scope**: In-memory during unpack (folder strategy)

**Schema**:

```python
@dataclass
class FolderTreeNode:
    """Tree node for folder hierarchy construction."""

    id: str                           # Folder ID
    name: str                         # Folder name
    parent_id: str | None             # Parent folder ID
    sanitized_name: str               # Filesystem-safe name
    depth: int                        # Nesting level (0 = root)

    # Tree structure
    children: list['FolderTreeNode'] = field(default_factory=list)
    parent: 'FolderTreeNode | None' = None

    # Content tracking
    dashboard_count: int = 0
    look_count: int = 0

    # Path construction
    @property
    def filesystem_path(self) -> str:
        """Construct full filesystem path from root to this node."""
        if self.parent is None:
            return self.sanitized_name
        return f"{self.parent.filesystem_path}/{self.sanitized_name}"

    @property
    def is_root(self) -> bool:
        """Check if this is a root folder."""
        return self.parent_id is None
```

**Example Tree**:

```text
FolderTreeNode(id="1", name="Sales", depth=0)
├── FolderTreeNode(id="2", name="Regional", depth=1)
│   ├── FolderTreeNode(id="3", name="West", depth=2, dashboard_count=5)
│   └── FolderTreeNode(id="4", name="East", depth=2, dashboard_count=3)
└── FolderTreeNode(id="5", name="Products", depth=1, look_count=12)
```

### 6. Export Directory Structure

**Full Strategy Layout**:

```text
<output_dir>/
├── metadata.json                 # Export manifest
├── dashboards/                   # All dashboards
│   ├── 42.yaml
│   ├── 43.yaml
│   └── ...
├── looks/                        # All looks
│   ├── 100.yaml
│   ├── 101.yaml
│   └── ...
├── users/                        # All users
│   ├── 1.yaml
│   ├── 2.yaml
│   └── ...
├── folders/                      # All folders
│   ├── 789.yaml
│   ├── 790.yaml
│   └── ...
├── groups/
├── roles/
├── boards/
├── lookml_models/
├── explores/
├── permission_sets/
├── model_sets/
└── scheduled_plans/
```

**Folder Strategy Layout**:

```text
<output_dir>/
├── metadata.json                 # Export manifest with folder_map
├── Sales/                        # Root folder "Sales" (id=789)
│   ├── Regional/                 # Subfolder "Regional" (id=790)
│   │   ├── West/                 # Subfolder "West" (id=791)
│   │   │   ├── 42.yaml           # Dashboard in West folder
│   │   │   ├── 43.yaml
│   │   │   └── 100.yaml          # Look in West folder
│   │   └── East/                 # Subfolder "East" (id=792)
│   │       ├── 44.yaml
│   │       └── 45.yaml
│   └── Products/                 # Subfolder "Products" (id=793)
│       ├── 101.yaml              # Looks only
│       └── 102.yaml
└── _orphaned/                    # Items with missing folder_id or invalid parent_id
    ├── 999.yaml
    └── 998.yaml
```

## Validation Rules

### Metadata Validation

1. **Required Fields**: version, export_timestamp, strategy, database_schema_version must be present
2. **Version Format**: Semantic versioning (e.g., "1.0.0")
3. **Strategy Enum**: Must be "full" or "folder"
4. **Counts**: content_type_counts must match actual YAML file counts
5. **Folder Map**: Required for folder strategy, must be null for full strategy
6. **Checksum**: If present, must match recomputed SHA-256 of all YAML files

### YAML Content Validation

1. **Syntax**: Valid YAML 1.2 syntax (ruamel.yaml parsing)
2. **Metadata Section**: `_metadata` key must be present with all required fields
3. **Content Type**: Must match ContentType enum values
4. **Looker SDK Schema**: Fields must match Looker SDK model for content_type
5. **ID Consistency**: `id` field must match filename (e.g., `42.yaml` → `id: "42"`)
6. **Timestamp Format**: ISO 8601 format for all datetime fields
7. **Folder References**: folder_id must exist in folder_map (folder strategy)

### Folder Hierarchy Validation

1. **No Cycles**: parent_id relationships must form a valid tree (no circular references)
2. **Valid Parents**: All parent_id values must reference existing folders
3. **Depth Limits**: Maximum 50 nesting levels
4. **Path Limits**: Filesystem paths must not exceed 255 characters per component
5. **Name Uniqueness**: Sanitized folder names at same level must be unique

## Data Flow Diagrams

### Unpack Flow (Full Strategy)

```text
SQLite Database
    ↓
[ContentRepository.list_content()] → ContentItem objects
    ↓
[MsgpackSerializer.deserialize()] → Python dicts
    ↓
[Add _metadata section] → Enriched dicts
    ↓
[YamlSerializer.serialize()] → YAML strings
    ↓
[Write to <content_type>/<id>.yaml] → Filesystem
    ↓
[Generate metadata.json] → Export complete
```

### Unpack Flow (Folder Strategy)

```text
SQLite Database
    ↓
[Load all folders] → Build FolderTree
    ↓
[ContentRepository.list_content(ContentType.DASHBOARD | LOOK)]
    ↓
[For each item: lookup folder_path in tree]
    ↓
[MsgpackSerializer.deserialize()] → Python dicts
    ↓
[Add _metadata with folder_path]
    ↓
[YamlSerializer.serialize()] → YAML strings
    ↓
[Write to <folder_path>/<id>.yaml] → Nested directories
    ↓
[Generate metadata.json with folder_map]
```

### Pack Flow

```text
Export Directory
    ↓
[Load metadata.json] → ExportMetadata
    ↓
[Discover YAML files] → File paths
    ↓
[For each YAML file]
    ↓
[YamlSerializer.deserialize()] → Python dicts
    ↓
[Validate against Looker SDK schema]
    ↓
[Extract _metadata section]
    ↓
[Detect query modifications] → QueryRemappingTable
    ↓
[Create new queries if needed] → New query IDs
    ↓
[Update dashboard_element.query_id references]
    ↓
[MsgpackSerializer.serialize()] → Binary blobs
    ↓
[ContentRepository.save_content()] → SQLite Database
    ↓
[Commit transaction] → Pack complete
```

## Performance Considerations

### Memory Usage

- **Streaming I/O**: Process one YAML file at a time (no full directory in memory)
- **Folder Tree**: O(n) memory for n folders (~50 bytes per node)
- **Query Remapping Table**: O(m) memory for m modified queries (~200 bytes per entry)
- **Target**: <500MB constant memory usage regardless of dataset size

### Disk I/O

- **Sequential Reads**: Iterate through database rows without loading all into memory
- **Buffered Writes**: Use buffered file I/O (default 8KB buffer)
- **Batch Commits**: For pack, commit every 100 items to balance performance and atomicity

### Computation

- **YAML Parsing**: ruamel.yaml is ~1.6x faster than PyYAML for comment-heavy files
- **Hashing**: SHA-256 hashing for 1KB query ~0.4ms (acceptable for batch operations)
- **Path Sanitization**: pathvalidate ~0.06ms per filename (negligible overhead)

## Error Handling

### Unpack Errors

| Error | Cause | Recovery |
|-------|-------|----------|
| `DatabaseNotFound` | db_path does not exist | Abort with clear error message |
| `OutputDirExists` | output_dir already exists without --overwrite | Prompt user or abort |
| `FolderCycleDetected` | Circular parent_id reference | Abort with cycle path details |
| `OrphanedContent` | folder_id references missing folder | Warn and place in _orphaned/ directory |
| `PathTooLong` | Sanitized path exceeds 255 chars | Truncate with hash suffix, warn user |

### Pack Errors

| Error | Cause | Recovery |
|-------|-------|----------|
| `MetadataMissing` | metadata.json not found | Abort with clear error |
| `InvalidYAMLSyntax` | YAML parsing error | Abort with file path and line number |
| `SchemaValidationFailed` | Fields don't match Looker SDK model | Abort with specific validation errors |
| `DatabaseLocked` | Concurrent modification detected | Abort and suggest retry |
| `QueryCreationFailed` | New query creation via Looker API failed | Add to DLQ for manual review |

## Integration with Existing Models

### Reused from storage/models.py

```python
class ContentType(IntEnum):
    """Existing enum - no changes needed."""
    DASHBOARD = 1
    LOOK = 2
    # ... (all 12 types)

@dataclass
class ContentItem:
    """Existing model - no changes needed."""
    id: str
    content_type: int
    # ... (existing fields)
```

### Reused from folder/hierarchy.py

```python
class FolderHierarchyResolver:
    """Existing class for building folder trees."""

    def resolve_hierarchy(self, folders: list[dict]) -> FolderTreeNode:
        """Build tree from flat folder list with parent_id references."""
        # Existing implementation + circular reference detection
```

## Checksum Strategy

### Purpose
- Validate export integrity before pack
- Detect manual YAML modifications
- Support incremental pack (future enhancement)

### Algorithm

```python
def compute_export_checksum(output_dir: Path) -> str:
    """Compute SHA-256 hash of all YAML files in sorted order."""
    hasher = hashlib.sha256()

    # Collect all YAML file paths in sorted order
    yaml_files = sorted(output_dir.rglob("*.yaml"))

    for yaml_file in yaml_files:
        # Hash filename relative to output_dir
        rel_path = yaml_file.relative_to(output_dir)
        hasher.update(str(rel_path).encode('utf-8'))

        # Hash file contents
        with open(yaml_file, 'rb') as f:
            hasher.update(f.read())

    return hasher.hexdigest()
```

### Usage

- **Unpack**: Compute checksum after all YAML files written, store in metadata.json
- **Pack**: Recompute checksum from directory, compare with metadata.json value
- **Mismatch**: Warn user that manual modifications detected (expected for bulk edits)

## Summary

This data model provides:
- ✅ Complete round-trip fidelity through metadata embedding
- ✅ Support for both full and folder-based export strategies
- ✅ Robust validation at multiple stages (syntax, schema, business rules)
- ✅ Efficient query remapping with deduplication
- ✅ Cross-platform filesystem safety with sanitization
- ✅ Clear error handling and recovery strategies
- ✅ Performance-optimized with streaming I/O and caching

All schemas are implemented as Python dataclasses with Pydantic validation for type safety and business rule enforcement.
