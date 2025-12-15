# YAML Export/Import - User Guide

Transform your Looker content backups into editable YAML files for bulk modifications, then pack them back into the database for restoration.

## Quick Start

```bash
# 1. Export your database to YAML files
lookervault unpack --db-path looker.db --output-dir export/

# 2. Modify YAML files using your favorite tools
sed -i 's/old_model/new_model/g' export/dashboards/*.yaml

# 3. Pack modified YAML back to database
lookervault pack --input-dir export/ --db-path looker_modified.db

# 4. Restore to Looker
lookervault restore bulk dashboards --workers 8
```

## Why Use YAML Export/Import?

**Problem**: Making the same modification to hundreds of dashboards in Looker's UI is tedious and error-prone.

**Solution**: Export to YAML → Modify with scripts (sed, awk, Python) → Reimport → Restore

**Use Cases**:
- Change model references across all dashboards (`old_model` → `new_model`)
- Update filter values (30 days → 90 days)
- Standardize naming conventions
- Batch updates to dashboard titles, descriptions, or tags
- Find and replace API endpoints, connection strings, etc.

## Export Strategies

### Full Strategy (Recommended for Bulk Modifications)

Organizes content by type in flat directories:

```
export/
├── metadata.json
├── dashboards/
│   ├── 123.yaml
│   ├── 456.yaml
│   └── 789.yaml
├── looks/
│   ├── 111.yaml
│   └── 222.yaml
└── users/
    └── 333.yaml
```

**When to use**:
- Applying same modification to all content of a type
- Simple bulk operations (find/replace, filter updates)
- Don't need to preserve folder organization

**Command**:
```bash
lookervault unpack --strategy full --output-dir export/
```

### Folder Strategy (Preserves Hierarchy)

Mirrors Looker's folder structure:

```
export/
├── metadata.json
├── Sales/
│   ├── Regional/
│   │   ├── West/
│   │   │   └── 123.yaml  # Dashboard
│   │   └── East/
│   │       └── 456.yaml
│   └── Executive/
│       └── 789.yaml
├── Marketing/
│   └── Campaigns/
│       └── 111.yaml  # Look
└── _orphaned/
    └── 999.yaml  # Content without valid folder
```

**When to use**:
- Folder-scoped modifications (only modify Sales/Regional content)
- Preserving organizational structure
- Easier navigation when folder hierarchy matters

**Command**:
```bash
lookervault unpack --strategy folder --output-dir export/
```

## Common Workflows

### 1. Update Model References

Replace `sales_old` with `sales_new` across all dashboards:

```bash
# Export
lookervault unpack --content-types dashboards --output-dir export/

# Modify
find export/dashboards -name "*.yaml" -exec \
  sed -i '' 's/model: sales_old/model: sales_new/g' {} +

# Pack
lookervault pack --input-dir export/ --db-path looker_new.db

# Validate changes (dry run first!)
lookervault pack --input-dir export/ --dry-run --verbose

# Restore
lookervault restore bulk dashboards
```

### 2. Update Filter Time Periods

Change all "30 days" filters to "90 days":

```bash
# Export
lookervault unpack --content-types dashboards --output-dir export/

# Use Python script for safer modifications
python update_filters.py export/dashboards/

# Pack with validation
lookervault pack --input-dir export/ --dry-run  # Check for errors
lookervault pack --input-dir export/  # Apply changes

# Restore
lookervault restore bulk dashboards
```

**Example script** (`update_filters.py`):
```python
#!/usr/bin/env python3
import yaml
from pathlib import Path

def update_filter_periods(dashboard_dir):
    for yaml_file in Path(dashboard_dir).glob("*.yaml"):
        with yaml_file.open() as f:
            dashboard = yaml.safe_load(f)

        modified = False
        for element in dashboard.get('dashboard_elements', []):
            query = element.get('query', {})
            filters = query.get('filters', {})

            for key, value in filters.items():
                if value == "30 days":
                    filters[key] = "90 days"
                    modified = True

        if modified:
            with yaml_file.open('w') as f:
                yaml.dump(dashboard, f, default_flow_style=False)
            print(f"✓ Updated {yaml_file.name}")

if __name__ == "__main__":
    import sys
    update_filter_periods(sys.argv[1])
```

### 3. Standardize Dashboard Titles

Add prefix to all dashboard titles in a folder:

```bash
# Export with folder strategy
lookervault unpack --strategy folder --output-dir export/

# Update titles in specific folder
for f in export/Sales/Regional/West/*.yaml; do
  sed -i '' 's/^title: "/title: "[West] /g' "$f"
done

# Pack and restore
lookervault pack --input-dir export/
lookervault restore bulk dashboards
```

### 4. Find Dashboards Using Specific Fields

Search for dashboards using specific dimension or measure:

```bash
# Export
lookervault unpack --content-types dashboards --output-dir export/

# Find dashboards using specific field
grep -l "revenue_total" export/dashboards/*.yaml

# Or use more complex search
find export/dashboards -name "*.yaml" -exec \
  grep -l "fields:.*revenue" {} +
```

## CLI Reference

### Unpack Command

Export SQLite content to YAML files.

**Basic syntax**:
```bash
lookervault unpack [OPTIONS]
```

**Options**:
- `--db-path PATH` - Path to SQLite database (default: `looker.db`)
- `--output-dir PATH` - Output directory for YAML files (required)
- `--strategy {full|folder}` - Export strategy (default: `full`)
- `--content-types LIST` - Comma-separated content types to export
- `--overwrite` - Overwrite existing output directory
- `--json` - Output results in JSON format
- `--verbose` / `-v` - Enable verbose logging
- `--debug` - Enable debug logging

**Examples**:
```bash
# Full export (all content types)
lookervault unpack --output-dir export/

# Export only dashboards and looks
lookervault unpack --content-types dashboards,looks --output-dir export/

# Folder strategy with verbose output
lookervault unpack --strategy folder --output-dir export/ --verbose

# Overwrite existing export directory
lookervault unpack --output-dir export/ --overwrite

# JSON output for scripting
lookervault unpack --output-dir export/ --json
```

**Exit codes**:
- `0` - Success
- `1` - General error
- `2` - Output directory already exists (use `--overwrite`)
- `4` - Circular folder reference detected

### Pack Command

Import YAML files back into SQLite database.

**Basic syntax**:
```bash
lookervault pack [OPTIONS]
```

**Options**:
- `--input-dir PATH` - Directory containing YAML files (required)
- `--db-path PATH` - Path to SQLite database to write (default: `looker.db`)
- `--dry-run` - Validate without making database changes
- `--force` - Delete database items for missing YAML files
- `--json` - Output results in JSON format
- `--verbose` / `-v` - Enable verbose logging
- `--debug` - Enable debug logging

**Examples**:
```bash
# Basic pack
lookervault pack --input-dir export/

# Dry run (validation only)
lookervault pack --input-dir export/ --dry-run

# Force mode (delete items for missing YAML files)
lookervault pack --input-dir export/ --force

# Pack to specific database
lookervault pack --input-dir export/ --db-path looker_modified.db

# JSON output
lookervault pack --input-dir export/ --json
```

**Exit codes**:
- `0` - Success
- `1` - General error
- `3` - Schema version mismatch
- `5` - Database transaction failed

## YAML File Format

Each YAML file represents one content item (dashboard, look, user, etc.).

**Structure**:
```yaml
# Content data (dashboard definition)
id: "123"
title: "Sales Dashboard"
description: "Q4 sales metrics"
dashboard_elements:
  - id: "elem1"
    title: "Total Revenue"
    query:
      model: "sales"
      view: "orders"
      fields: ["orders.total_revenue", "orders.created_date"]
      filters:
        orders.created_date: "30 days"
      sorts: ["orders.created_date desc"]

# Metadata (DO NOT modify this section)
_metadata:
  db_id: "123"
  content_type: "DASHBOARD"
  exported_at: "2025-12-14T12:00:00.123456"
  content_size: 5432
  checksum: "sha256:abc123def456..."
  folder_path: "Sales/Regional"  # Only for folder strategy
```

**Important Notes**:
- **DO** modify content data (title, description, query definitions, etc.)
- **DO NOT** modify `_metadata` section (required for round-trip fidelity)
- **DO NOT** change file names (they match content IDs)
- **DO** preserve YAML formatting for readability

## Metadata File

The `metadata.json` file contains export summary and validation data.

**Location**: `<output-dir>/metadata.json`

**Structure**:
```json
{
  "version": "1.0",
  "exported_at": "2025-12-14T12:00:00.123456",
  "strategy": "full",
  "database_schema_version": "2",
  "source_database": "/path/to/looker.db",
  "total_items": 1500,
  "content_counts": {
    "DASHBOARD": 500,
    "LOOK": 300,
    "USER": 50,
    "FOLDER": 100,
    "BOARD": 25,
    "GROUP": 10,
    "ROLE": 5
  },
  "checksum": "sha256:abc123...",
  "folder_map": {
    "folder_123": {
      "id": "123",
      "name": "Sales",
      "parent_id": null,
      "path": "Sales",
      "depth": 0,
      "child_count": 3
    }
  }
}
```

**Fields**:
- `version` - Metadata format version
- `exported_at` - Export timestamp
- `strategy` - Export strategy used (`full` or `folder`)
- `database_schema_version` - SQLite schema version (for compatibility)
- `total_items` - Total content items exported
- `content_counts` - Count per content type
- `checksum` - SHA-256 checksum of entire export
- `folder_map` - Folder hierarchy (only if `strategy=folder`)

**Purpose**:
- Pack operation validates against this metadata
- Detects missing files, schema mismatches
- Ensures round-trip fidelity

## Validation & Error Handling

### Validation Pipeline

Pack operation validates YAML files through multiple stages:

1. **Syntax Validation** - Valid YAML syntax
2. **Schema Validation** - Required fields present
3. **SDK Conversion** - Looker SDK model compatibility
4. **Business Rules** - Field-level constraints

**Example validation errors**:
```
[Structure] DASHBOARD missing required 'elements' field
  File: dashboards/123.yaml

[Field] Field 'title' cannot be empty
  File: dashboards/456.yaml:5

[Query] Missing required query fields: model, view
  File: dashboards/789.yaml:15
  Expected: model (string), view (string), fields (array)
  Got: model (missing), view (string), fields (array)
```

### Common Errors

**Schema version mismatch**:
```
Error: Database schema version mismatch.
Expected: 2, Got: 1
```
**Fix**: Use same database version as original export

**Circular folder reference**:
```
Error: Circular reference detected in folder hierarchy
Cycle: Folder A → Folder B → Folder C → Folder A
```
**Fix**: Fix folder parent relationships in source database

**Validation failure**:
```
Error: Validation failed for dashboards/123.yaml:
[Field] Field 'model' must be a string, got NoneType
```
**Fix**: Ensure all required fields are present and correct type

**Missing files** (with `--force`):
```
Warning: 5 files missing from export directory
Deleted 5 database items
```
**Fix**: Review missing files list before using `--force`

### Dry Run Mode

Always validate modifications before applying:

```bash
# Validate without changes
lookervault pack --input-dir export/ --dry-run --verbose

# Check output for validation errors
# Only proceed if no errors reported
lookervault pack --input-dir export/
```

## Best Practices

### 1. Always Use Version Control

Track YAML files in git for change history:

```bash
# Export to git-tracked directory
lookervault unpack --output-dir export/
cd export/
git init
git add .
git commit -m "Initial export"

# Make modifications
sed -i 's/old/new/g' dashboards/*.yaml
git diff  # Review changes
git commit -am "Update model references"

# Pack changes
lookervault pack --input-dir .
```

### 2. Test with Dry Run

Always validate before applying changes:

```bash
# Validate first
lookervault pack --dry-run --verbose

# Apply only if validation passes
lookervault pack
```

### 3. Use Selective Export

Export only content types you need to modify:

```bash
# Export only dashboards
lookervault unpack --content-types dashboards --output-dir export/

# Faster and less clutter
```

### 4. Backup Before Bulk Changes

Create snapshots before major modifications:

```bash
# Backup to cloud
lookervault snapshot upload --name "pre-bulk-update"

# Make modifications
lookervault unpack --output-dir export/
# ... modify YAML files ...
lookervault pack --input-dir export/

# Backup modified version
lookervault snapshot upload --name "post-bulk-update"

# Restore if needed
lookervault snapshot download --name "pre-bulk-update"
```

### 5. Use Scripts for Complex Modifications

Write Python scripts for complex modifications:

```python
#!/usr/bin/env python3
"""
Update dashboard queries to use new field names.
"""
import yaml
from pathlib import Path

# Field mapping
FIELD_MAPPING = {
    "old_field_1": "new_field_1",
    "old_field_2": "new_field_2",
}

def update_dashboard_fields(dashboard_dir):
    for yaml_file in Path(dashboard_dir).glob("*.yaml"):
        with yaml_file.open() as f:
            dashboard = yaml.safe_load(f)

        modified = False
        for element in dashboard.get('dashboard_elements', []):
            query = element.get('query', {})
            fields = query.get('fields', [])

            # Update field references
            for i, field in enumerate(fields):
                if field in FIELD_MAPPING:
                    fields[i] = FIELD_MAPPING[field]
                    modified = True

        if modified:
            with yaml_file.open('w') as f:
                yaml.dump(dashboard, f, default_flow_style=False)
            print(f"✓ Updated {yaml_file.name}")

if __name__ == "__main__":
    import sys
    update_dashboard_fields(sys.argv[1])
```

## Troubleshooting

### Slow Unpack Performance

**Symptom**: Unpack takes >5 minutes for 10,000 items

**Cause**: Already optimized (2-3x faster after v1.0)

**Expected**: ~3 minutes for 10,000 items

### Pack Validation Errors

**Symptom**: Multiple validation errors after modifications

**Solution**:
1. Run `--dry-run` to see all errors
2. Check file path and line number in error messages
3. Fix errors in YAML files
4. Re-run `--dry-run` until all errors resolved

### Disk Space Errors

**Symptom**: "Insufficient disk space" error during unpack

**Cause**: Export requires ~3.5x database size

**Solution**:
1. Free up disk space
2. Export to different drive with more space
3. Use `--content-types` to export selectively

### Missing Files Warning

**Symptom**: "5 files missing from export directory"

**Cause**: YAML files deleted but still in metadata

**Solution**:
- If intentional: Use `--force` to delete from database
- If unintentional: Restore YAML files before packing

## Support & Resources

**Documentation**:
- Feature Spec: `specs/006-yaml-export-import/spec.md`
- Quickstart: `specs/006-yaml-export-import/quickstart.md`
- Data Model: `specs/006-yaml-export-import/data-model.md`
- CLAUDE.md: See "YAML Export/Import" section

**Example Scripts**:
- `tests/fixtures/scripts/update_filters.py` - Filter modifications
- `tests/fixtures/scripts/update_titles.sh` - Title updates
- `tests/fixtures/scripts/replace_models.sh` - Model replacements

**Related Features**:
- `lookervault extract` - Extract content from Looker to SQLite
- `lookervault restore` - Restore content from SQLite to Looker
- `lookervault snapshot` - Cloud backup to GCS

**Reporting Issues**:
- File issues in project repository
- Include error messages and validation output
- Attach sample YAML files if possible (redact sensitive data)
