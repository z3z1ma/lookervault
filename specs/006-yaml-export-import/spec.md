# Feature Specification: YAML Export/Import for Looker Content

**Feature Branch**: `006-yaml-export-import`
**Created**: 2025-12-14
**Status**: Draft
**Input**: User description: "We need to implement two new commands: a command called 'unpack' and a command called 'pack.' The goal of the 'unpack' command is to take an existing SQLite file with content inside of it to extract all the binary message pack data and write it to disk using YAML format in a directory specified by output_dir. There are two ways in which we will unpack a database: (1) full unpack where we're unpacking all content into subfolders named after the content type, and (2) folder-based unpacking where we unpack content which has folder IDs (dashboards and looks) into subfolders and nested subfolders based on their actual hierarchy in Looker. When we do full unpack, we can repack everything back into the existing database or even into a new database. When we do folder-based extraction, we can repack back into the database from whence it came. The most interesting use case this workflow enables is to take a snapshot of Looker information, unpack it onto disk, and then run Python scripts or simple commands like sed/awk to process the files on disk and make bulk changes, and then to repack it and use the Looker vault restore command to apply the changes."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Full Content Export/Import (Priority: P1)

A developer extracts all Looker content from a SQLite backup to YAML files, makes bulk modifications using scripts, and imports the modified content back to verify changes before restoring to Looker.

**Why this priority**: This is the foundation for the entire feature - enabling basic export/import workflows. Without this, no other use cases are possible. It provides complete control over all content types and enables the broadest range of bulk modification scenarios.

**Independent Test**: Can be fully tested by extracting a database with mixed content types (dashboards, looks, users, folders), verifying YAML files are created in the expected structure, modifying one YAML file, repacking to a new database, and confirming the modification is present.

**Acceptance Scenarios**:

1. **Given** a SQLite database with 100 dashboards, 50 looks, 20 users, and 10 folders, **When** user runs `lookervault unpack --strategy full --output-dir ./export`, **Then** the system creates subdirectories `dashboards/`, `looks/`, `users/`, `folders/` each containing YAML files named by content ID, and a `metadata.json` file at the root
2. **Given** an export directory with modified YAML files, **When** user runs `lookervault pack --input-dir ./export --db-path looker-modified.db`, **Then** the system creates a new SQLite database with all content from YAML files, preserving modifications
3. **Given** an export directory with a modified dashboard YAML (title changed), **When** user packs and extracts the dashboard from the new database, **Then** the dashboard title matches the modification made in YAML
4. **Given** a database with 5,000+ content items, **When** user unpacks using full strategy, **Then** the operation completes within 5 minutes and all items are present in YAML format

---

### User Story 2 - Folder Hierarchy Export/Import (Priority: P2)

A developer extracts dashboards and looks organized by their Looker folder hierarchy to YAML files, makes targeted modifications to specific folders, and imports the changes back while preserving folder structure.

**Why this priority**: This enables more intuitive navigation and modification of content that mirrors the Looker UI organization. It's particularly valuable for teams who organize content by department, project, or business unit. While not essential for basic workflows, it significantly improves usability for folder-based content management.

**Independent Test**: Can be fully tested by extracting a database with nested folders (e.g., "Marketing/Campaigns/Q4"), verifying YAML files appear in matching nested directories, modifying a dashboard YAML within a specific folder, repacking, and confirming the change persists.

**Acceptance Scenarios**:

1. **Given** a database with folders "Sales/Regional/West" containing 5 dashboards and "Sales/Regional/East" containing 3 dashboards, **When** user runs `lookervault unpack --strategy folder --output-dir ./export`, **Then** the system creates nested directories matching folder names with YAML files inside each folder
2. **Given** a folder hierarchy export with modified dashboard YAMLs in "Sales/Regional/West", **When** user runs `lookervault pack --input-dir ./export --db-path looker.db`, **Then** the system updates only the modified dashboards in the database
3. **Given** a folder structure with 50 nested levels and 1,000 dashboards distributed across folders, **When** user unpacks using folder strategy, **Then** all dashboards appear in correct nested directories matching Looker folder names
4. **Given** a folder export with a new YAML file added to "Marketing/Campaigns", **When** user packs the directory, **Then** the system creates a new dashboard in the database with correct folder association

---

### User Story 3 - Bulk Content Modification via Scripts (Priority: P1)

A developer exports dashboards to YAML, runs a Python script to update all query filter values, repacks the modified content, and restores it to Looker to apply changes across hundreds of dashboards simultaneously.

**Why this priority**: This is the primary motivation for the feature - enabling bulk modifications that would be tedious or impossible through the Looker UI. It unlocks powerful automation capabilities and is critical for production use cases.

**Independent Test**: Can be fully tested by exporting dashboards, running a script that modifies a specific YAML field (e.g., changing all instances of "2024" to "2025" in titles), repacking, extracting dashboards from the new database, and verifying all titles contain "2025".

**Acceptance Scenarios**:

1. **Given** 200 dashboards exported to YAML with query filters set to "last_30_days", **When** user runs a Python script that modifies all YAML files to change filter to "last_90_days" and repacks, **Then** all dashboards in the new database have "last_90_days" filters
2. **Given** exported dashboard YAMLs with deprecated LookML model references, **When** user runs a sed command to replace old model names with new ones across all files and repacks, **Then** all dashboards reference the new model names
3. **Given** a folder hierarchy export with 50 dashboards, **When** user runs an awk script to add a specific tag to all dashboard YAML files and repacks, **Then** all dashboards in the database include the new tag
4. **Given** dashboards with embedded query definitions in YAML, **When** user modifies query fields (dimensions, measures) in YAML and repacks, **Then** the system correctly handles query updates per Looker API requirements (creating new queries where needed)

---

### User Story 4 - Dashboard Query Modification with ID Remapping (Priority: P3)

A developer modifies query definitions within dashboard element YAMLs, and the pack command automatically creates new query objects and updates dashboard element references with the new query IDs.

**Why this priority**: This addresses a specific edge case in the Looker API where queries cannot be patched - they must be created new. While important for comprehensive dashboard editing, it's less critical than basic export/import workflows and can be addressed after core functionality is stable.

**Independent Test**: Can be fully tested by exporting a dashboard with 3 elements, modifying the query definition in one element's YAML (changing dimensions), repacking, and verifying the dashboard element now references a newly created query ID with the modified definition.

**Acceptance Scenarios**:

1. **Given** a dashboard element YAML with a query definition containing specific dimensions, **When** user modifies the dimensions list in YAML and repacks, **Then** the system creates a new query object, updates the dashboard element to reference the new query ID, and preserves the old query ID in the database
2. **Given** multiple dashboard elements sharing the same query ID in YAML, **When** user modifies the shared query definition and repacks, **Then** the system creates one new query and updates all affected dashboard elements to reference it
3. **Given** a dashboard with 20 elements where 5 have modified queries, **When** user repacks the YAML, **Then** the system creates exactly 5 new queries and updates only those 5 elements, leaving the other 15 unchanged
4. **Given** a modified query YAML that becomes invalid (missing required fields), **When** user attempts to pack, **Then** the system reports a clear error indicating which query definition is invalid and why

---

### Edge Cases

- What happens when a YAML file is manually deleted from the export directory before packing? (System should skip the missing item or optionally delete it from the database if a flag is provided)
- How does the system handle YAML files with invalid syntax or schema violations during pack? (Validation should occur before any database modifications, with clear error messages pointing to the problematic file and line)
- What happens when folder names in a hierarchy contain special characters or exceed filesystem path limits? (System should sanitize folder names for filesystem compatibility while preserving original names in metadata)
- How does the system handle circular folder references or orphaned content during folder-based unpacking? (Orphaned items should appear in a special "Orphaned" directory; circular references should be detected and reported)
- What happens when packing folder-based exports into a database that already has different folder structures? (System should preserve existing folder structures and map content to folders by folder ID, not by name)
- How does the system handle concurrent modifications to the database while packing is in progress? (Use database transactions to ensure atomicity; detect concurrent changes and abort with clear error if conflicts exist)
- What happens when unpacking a database with 100,000+ items to a filesystem with limited inodes or disk space? (Pre-flight check for disk space; provide progress indicators; handle filesystem errors gracefully)
- How does the system handle content items with relationships (dashboard references look, look references query) when only partial content is exported in folder-based mode? (Include relationship metadata in YAML to detect missing dependencies; optionally include referenced items even if outside folder scope)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide an `unpack` command that extracts binary MessagePack data from SQLite database to YAML files in a specified output directory
- **FR-002**: System MUST support two unpacking strategies: `full` (all content types organized by type) and `folder` (dashboards/looks organized by Looker folder hierarchy)
- **FR-003**: System MUST create a metadata file (JSON format) at the root of the export directory containing database schema version, export timestamp, strategy used, and any additional information needed for repacking
- **FR-004**: System MUST name YAML files using content IDs and include internal metadata fields (e.g., `_db_id`, `_content_type`, `_exported_at`) to facilitate accurate repacking
- **FR-005**: System MUST provide a `pack` command that reads YAML files from a directory and writes them as binary MessagePack data into a SQLite database
- **FR-006**: Pack command MUST support creating a new database or updating an existing database specified via `--db-path` parameter
- **FR-007**: For full strategy unpacks, pack command MUST be able to create a complete new database from YAML files alone (fully self-contained export/import)
- **FR-008**: For folder strategy unpacks, pack command MUST support repacking into the source database or a new database with understanding that the new database will be partial
- **FR-009**: System MUST validate YAML schema and content structure before writing to database, reporting clear errors for invalid files
- **FR-010**: System MUST handle dashboard query modifications by creating new query objects when query definitions are changed in YAML, and updating dashboard element references with new query IDs
- **FR-011**: System MUST preserve folder hierarchy structure when using folder strategy, creating nested directories that match Looker folder names
- **FR-012**: System MUST sanitize folder names for filesystem compatibility while preserving original names in metadata
- **FR-013**: System MUST detect and report circular folder references or orphaned content during folder-based unpacking
- **FR-014**: System MUST support dry-run mode for pack command to validate YAML files without modifying the database
- **FR-015**: System MUST provide progress indicators for both unpack and pack operations when processing large datasets
- **FR-016**: System MUST handle content relationships (dashboards referencing looks, looks referencing queries) and include dependency metadata in YAML files
- **FR-017**: System MUST preserve content modification timestamps and metadata when round-tripping through YAML export/import
- **FR-018**: System MUST use database transactions when packing to ensure atomicity (all-or-nothing updates)
- **FR-019**: System MUST detect concurrent database modifications during pack operations and abort with clear error if conflicts are detected
- **FR-020**: System MUST support selective repacking where only modified YAML files trigger database updates (compare timestamps or checksums)

### Key Entities *(include if feature involves data)*

- **Export Directory Structure**: Root directory containing YAML files, subdirectories (by content type or folder hierarchy), and metadata.json file. Represents the on-disk serialization of database content.
- **Metadata File**: JSON file at export root containing export strategy, timestamp, database schema version, content type counts, folder hierarchy map (for folder strategy), and any additional context needed for repacking.
- **YAML Content File**: Individual YAML file representing one content item (dashboard, look, user, etc.) with structure matching Looker SDK object schema plus internal metadata fields (e.g., `_db_id`, `_content_type`, `_folder_path`).
- **Folder Hierarchy Map**: Data structure in metadata file mapping folder IDs to folder names and parent relationships, used to reconstruct nested directory structure during folder-based unpack.
- **Query ID Remapping Table**: Internal tracking structure (stored in metadata or separate file) that maps old query IDs to new query IDs when queries are modified and recreated during pack operations.
- **Content Relationship Graph**: Data structure tracking dependencies between content items (dashboard → look → query) to ensure proper handling of references during partial exports and imports.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can unpack a database with 10,000 content items to YAML files in under 5 minutes using full strategy
- **SC-002**: Users can pack 10,000 YAML files into a new database in under 10 minutes
- **SC-003**: Round-trip fidelity is 100% - content exported and then imported without modifications is byte-for-byte identical to original
- **SC-004**: Users can successfully modify 500+ dashboards using sed/awk scripts and repack with all changes applied correctly
- **SC-005**: Folder hierarchy unpacking produces nested directory structures that match Looker folder organization with 100% accuracy
- **SC-006**: Pack operations with invalid YAML files report specific errors (file name, line number, validation issue) for 100% of validation failures
- **SC-007**: Dashboard query modifications trigger correct new query creation and ID remapping with 100% success rate for valid modifications
- **SC-008**: Users can complete a typical workflow (unpack → modify → pack → restore) in under 30 minutes for datasets with 1,000+ items
- **SC-009**: Partial folder exports (e.g., single department folder) can be repacked without affecting other content in the database
- **SC-010**: System gracefully handles edge cases (missing files, invalid YAML, circular references) with clear error messages in 100% of error scenarios

## Assumptions

1. **Database Format**: Assumes existing SQLite database schema matches the current LookerVault repository pattern with binary MessagePack content in blob columns
2. **Looker API Compatibility**: Assumes Looker SDK object schemas are stable and YAML serialization/deserialization can accurately represent all content types
3. **Query Modification Handling**: Assumes the Looker API requirement that queries cannot be patched (must be created new) is accurately documented and understood
4. **Folder Hierarchy Consistency**: Assumes folder IDs in the database are consistent and folder parent relationships form a valid tree (no cycles unless explicitly handled as edge case)
5. **Filesystem Limits**: Assumes typical filesystem limitations apply (path length ~255 chars, reasonable inode limits, case-sensitive or insensitive handling as needed)
6. **Content Type Support**: Assumes all existing content types (dashboards, looks, users, groups, folders, boards, models, etc.) can be serialized to YAML and deserialized back
7. **Concurrent Access**: Assumes pack operations are single-user/single-process and do not need to handle highly concurrent database access (basic transaction protection is sufficient)
8. **YAML Editing Tools**: Assumes users have access to standard text editors, Python, sed, awk, or similar tools for YAML manipulation
9. **Restore Integration**: Assumes existing `lookervault restore` command can accept the modified database produced by pack operations without requiring changes to the restore workflow
10. **Metadata Completeness**: Assumes metadata file can capture all necessary context for repacking, but specific metadata fields may need refinement based on implementation experience

## Non-Requirements (Out of Scope)

1. **Live Looker API Integration**: This feature only operates on SQLite databases, not directly against Looker instances (use existing extract/restore commands for that)
2. **Version Control Integration**: No built-in git or other VCS integration (users can version control the YAML export directories manually)
3. **Merge Conflict Resolution**: No automatic merging of concurrent YAML modifications (users must manually resolve conflicts if multiple people edit the same export)
4. **YAML Schema Validation Against Live Looker**: No real-time validation against a Looker instance's current schema/API version (validation is against locally known schemas)
5. **Cross-Instance ID Migration**: This feature does not handle remapping content IDs for cross-instance migrations (that's a separate use case, possibly future enhancement)
6. **Binary Format Support**: Only YAML is supported for human-editable export, not JSON, TOML, or other formats
7. **Incremental Exports**: No support for exporting only changed content since last export (always full or folder-scoped exports)
8. **Content Search/Filtering**: No built-in search or filtering within exported YAML files (use standard grep/find tools)
9. **Automated Testing of Modified Content**: No validation that modified dashboards/looks will work correctly in Looker (users must test after restore)
10. **Performance Optimization for Real-Time Use**: Export/import is designed for batch operations, not real-time or interactive use cases
