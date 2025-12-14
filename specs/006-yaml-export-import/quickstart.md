# Quickstart Guide: YAML Export/Import

**Feature**: YAML Export/Import for Looker Content
**Branch**: `006-yaml-export-import`
**Date**: 2025-12-14

## Overview

This guide provides practical examples for using LookerVault's YAML export/import feature to perform bulk modifications on Looker content. The typical workflow is:

1. **Extract**: Download Looker content to SQLite database
2. **Unpack**: Export database to human-editable YAML files
3. **Modify**: Edit YAML files using scripts (sed, awk, Python, etc.)
4. **Pack**: Import modified YAML back to database
5. **Restore**: Upload changes to Looker

## Prerequisites

- LookerVault CLI installed and configured
- SQLite database with Looker content (created via `lookervault extract`)
- Basic familiarity with command-line tools (sed, awk, Python)

## Basic Workflow

### 1. Extract Looker Content

```bash
# Extract all content from Looker to local database
lookervault extract dashboards looks users folders groups --workers 8

# Database created at: looker.db
```

### 2. Unpack to YAML

```bash
# Export all content to YAML files (full strategy)
lookervault unpack --output-dir ./looker-export

# Output:
# ./looker-export/
# ├── metadata.json
# ├── dashboards/
# │   ├── 1.yaml
# │   ├── 2.yaml
# │   └── ...
# ├── looks/
# │   ├── 100.yaml
# │   ├── 101.yaml
# │   └── ...
# └── ... (users, folders, groups, etc.)
```

### 3. Modify YAML Files

```bash
# Example: Change all dashboard titles from "2024" to "2025"
sed -i '' 's/title: "\(.*\)2024\(.*\)"/title: "\12025\2"/g' ./looker-export/dashboards/*.yaml

# Or use Python for more complex modifications (see examples below)
```

### 4. Pack Modified YAML

```bash
# Validate changes first (dry run)
lookervault pack --input-dir ./looker-export --db-path ./modified.db --dry-run

# If validation passes, pack for real
lookervault pack --input-dir ./looker-export --db-path ./modified.db

# Database created at: ./modified.db with your changes
```

### 5. Restore to Looker

```bash
# Restore modified dashboards to Looker
lookervault restore bulk dashboards --db-path ./modified.db --workers 8

# Changes are now live in Looker!
```

## Common Use Cases

### Example 1: Update Dashboard Titles (sed)

**Scenario**: Rename all dashboards to include "FY2025" prefix.

```bash
# 1. Export dashboards to YAML
lookervault unpack --output-dir ./export --content-types DASHBOARD

# 2. Add "FY2025 - " prefix to all dashboard titles
sed -i '' 's/^title: "\(.*\)"/title: "FY2025 - \1"/g' ./export/dashboards/*.yaml

# Example:
# Before: title: "Sales Performance"
# After:  title: "FY2025 - Sales Performance"

# 3. Pack and restore
lookervault pack --input-dir ./export --db-path ./modified.db
lookervault restore bulk dashboards --db-path ./modified.db
```

### Example 2: Update Query Filters (Python)

**Scenario**: Change all dashboard query filters from "last 30 days" to "last 90 days".

```python
#!/usr/bin/env python3
"""Update query filters in dashboard YAMLs."""

import yaml
from pathlib import Path

# Load all dashboard YAML files
dashboard_dir = Path("./export/dashboards")
for yaml_file in dashboard_dir.glob("*.yaml"):
    with open(yaml_file, 'r') as f:
        dashboard = yaml.safe_load(f)

    # Update filters in dashboard elements
    modified = False
    for element in dashboard.get('dashboard_elements', []):
        query = element.get('query', {})
        filters = query.get('filters', {})

        for filter_name, filter_value in filters.items():
            if filter_value == "30 days":
                filters[filter_name] = "90 days"
                modified = True

    # Save if modified
    if modified:
        with open(yaml_file, 'w') as f:
            yaml.dump(dashboard, f, default_flow_style=False, sort_keys=False)
        print(f"Updated {yaml_file.name}")
```

```bash
# Run the script
python update_filters.py

# Pack and restore
lookervault pack --input-dir ./export --db-path ./modified.db
lookervault restore bulk dashboards --db-path ./modified.db
```

### Example 3: Replace LookML Model References (awk)

**Scenario**: Change all references from `old_model` to `new_model` across all dashboards.

```bash
# 1. Export dashboards
lookervault unpack --output-dir ./export --content-types DASHBOARD

# 2. Replace model references using awk
for file in ./export/dashboards/*.yaml; do
  awk '{gsub(/model: "old_model"/, "model: \"new_model\""); print}' "$file" > "$file.tmp"
  mv "$file.tmp" "$file"
done

# 3. Pack and restore
lookervault pack --input-dir ./export --db-path ./modified.db
lookervault restore bulk dashboards --db-path ./modified.db
```

### Example 4: Folder-Based Export and Selective Modification

**Scenario**: Modify only dashboards in "Sales/Regional/West" folder.

```bash
# 1. Export with folder hierarchy
lookervault unpack --output-dir ./export --strategy folder

# Output structure mirrors Looker folders:
# ./export/
# ├── metadata.json
# ├── Sales/
# │   ├── Regional/
# │   │   ├── West/
# │   │   │   ├── 42.yaml
# │   │   │   └── 43.yaml
# │   │   └── East/
# │   │       └── 44.yaml
# │   └── Products/
# │       └── 100.yaml

# 2. Modify only West region dashboards
sed -i '' 's/description: "\(.*\)"/description: "\1 (West Region)"/g' \
  ./export/Sales/Regional/West/*.yaml

# 3. Pack and restore (only modified dashboards will be updated)
lookervault pack --input-dir ./export --db-path ./modified.db
lookervault restore bulk dashboards --db-path ./modified.db --folder-ids 791
```

### Example 5: Add Tags to All Dashboards (Python)

**Scenario**: Add "reviewed:true" tag to all dashboards for audit tracking.

```python
#!/usr/bin/env python3
"""Add audit tags to all dashboards."""

import yaml
from pathlib import Path
from datetime import datetime

dashboard_dir = Path("./export/dashboards")
for yaml_file in dashboard_dir.glob("*.yaml"):
    with open(yaml_file, 'r') as f:
        dashboard = yaml.safe_load(f)

    # Add or update tags
    if 'tags' not in dashboard:
        dashboard['tags'] = []

    # Add review tag with timestamp
    review_tag = f"reviewed:{datetime.now().strftime('%Y-%m-%d')}"
    if review_tag not in dashboard['tags']:
        dashboard['tags'].append(review_tag)

    # Save
    with open(yaml_file, 'w') as f:
        yaml.dump(dashboard, f, default_flow_style=False, sort_keys=False)
    print(f"Tagged {yaml_file.name}")
```

```bash
# Run the script
python add_audit_tags.py

# Pack and restore
lookervault pack --input-dir ./export --db-path ./modified.db
lookervault restore bulk dashboards --db-path ./modified.db
```

### Example 6: Query Modification with Automatic Remapping

**Scenario**: Add a new dimension to all dashboard query definitions.

```python
#!/usr/bin/env python3
"""Add 'users.city' dimension to all dashboard queries."""

import yaml
from pathlib import Path

dashboard_dir = Path("./export/dashboards")
for yaml_file in dashboard_dir.glob("*.yaml"):
    with open(yaml_file, 'r') as f:
        dashboard = yaml.safe_load(f)

    modified = False
    for element in dashboard.get('dashboard_elements', []):
        query = element.get('query', {})
        if query and 'fields' in query:
            # Add new dimension if not already present
            if 'users.city' not in query['fields']:
                query['fields'].append('users.city')
                modified = True

    if modified:
        with open(yaml_file, 'w') as f:
            yaml.dump(dashboard, f, default_flow_style=False, sort_keys=False)
        print(f"Updated {yaml_file.name}")
```

```bash
# Run the script
python add_dimension.py

# Pack will automatically:
# 1. Detect modified queries (SHA-256 hash changed)
# 2. Create new query objects in database
# 3. Update dashboard_element.query_id references
# 4. Deduplicate shared queries (same hash → same new query ID)

lookervault pack --input-dir ./export --db-path ./modified.db

# Output will show:
# Detected modifications:
#   Modified dashboards: 127 files
#   Modified queries: 43 new queries required
#   Unchanged items: 2,278 files

lookervault restore bulk dashboards --db-path ./modified.db
```

## Advanced Patterns

### Backup Before Pack (Safety Net)

```bash
# Always backup the original database before packing modifications
cp looker.db looker-backup-$(date +%Y%m%d).db

# Unpack, modify, pack
lookervault unpack --output-dir ./export --db-path looker.db
# ... make modifications ...
lookervault pack --input-dir ./export --db-path looker-modified.db

# Compare before and after
diff <(sqlite3 looker.db "SELECT id, title FROM content_items WHERE content_type=1 ORDER BY id") \
     <(sqlite3 looker-modified.db "SELECT id, title FROM content_items WHERE content_type=1 ORDER BY id")
```

### Dry-Run Validation

```bash
# Always validate before packing
lookervault pack --input-dir ./export --db-path ./modified.db --dry-run

# Output shows validation errors if any:
# ✗ YAML syntax error in dashboards/123.yaml:
#     Line 42: mapping values are not allowed here
# ✗ Schema validation failed for dashboards/456.yaml:
#     Missing required field 'title'

# Fix errors and re-run dry-run until clean
```

### Folder Filtering for Large Datasets

```bash
# For large Looker instances, export specific folders only
lookervault extract --folder-ids "789,790,791" dashboards looks

# Unpack with folder strategy
lookervault unpack --output-dir ./export --strategy folder

# Modify only what you need
# ... make changes ...

# Pack and restore to specific folders
lookervault pack --input-dir ./export --db-path ./modified.db
lookervault restore bulk dashboards --db-path ./modified.db --folder-ids "789,790,791"
```

### Incremental Modifications (Multi-Stage Workflow)

```bash
# Stage 1: Update titles
lookervault unpack --output-dir ./export1
sed -i '' 's/2024/2025/g' ./export1/dashboards/*.yaml
lookervault pack --input-dir ./export1 --db-path looker.db

# Stage 2: Update queries (uses updated database from Stage 1)
lookervault unpack --output-dir ./export2 --db-path looker.db
python update_queries.py
lookervault pack --input-dir ./export2 --db-path looker.db

# Final restore
lookervault restore bulk dashboards --db-path looker.db
```

### Checksum Validation

```bash
# Unpack creates checksum in metadata.json
lookervault unpack --output-dir ./export

# metadata.json contains:
# {
#   "checksum": "a1b2c3d4e5f6...",
#   ...
# }

# After modifications, pack compares checksums
lookervault pack --input-dir ./export --db-path ./modified.db

# Output warns if checksums differ (expected after edits):
# ⚠ Checksum mismatch detected (manual modifications present)
#   Original: a1b2c3d4e5f6...
#   Current:  b2c3d4e5f6a7...
#   This is expected if you edited YAML files.
```

## Troubleshooting

### Common Errors and Solutions

#### Error: YAML Syntax Error

```text
✗ YAML syntax error in dashboards/123.yaml:
    Line 42: mapping values are not allowed here
```

**Solution**: Fix YAML syntax using a validator or linter.

```bash
# Use yamllint to check syntax
yamllint ./export/dashboards/123.yaml

# Fix indentation, quotes, or special characters
```

#### Error: Schema Validation Failed

```text
✗ Schema validation failed for dashboards/456.yaml:
    Missing required field 'title'
```

**Solution**: Ensure all required fields are present in YAML.

```bash
# Check the YAML file
cat ./export/dashboards/456.yaml

# Add missing field
echo "title: \"My Dashboard\"" >> ./export/dashboards/456.yaml
```

#### Error: Query Creation Failed

```text
✗ Failed to create new query for dashboard element elem_123:
    Looker API error: Invalid model reference
```

**Solution**: Verify query definitions are valid for Looker's API.

```bash
# Check query syntax in YAML
grep -A 10 "query:" ./export/dashboards/456.yaml

# Ensure model, view, fields are correct
# Fix or revert to original query_id-only reference
```

#### Warning: Orphaned Content

```text
⚠ Found 3 orphaned items (missing folder_id or invalid parent_id)
  - 999.yaml
  - 998.yaml
  - 997.yaml
  Placed in _orphaned/ directory
```

**Solution**: Review orphaned items and assign to correct folders.

```bash
# Inspect orphaned items
cat ./export/_orphaned/999.yaml

# Either:
# 1. Move to correct folder directory
# 2. Update folder_id in YAML
# 3. Leave in _orphaned/ (will be imported without folder association)
```

## Best Practices

1. **Always Backup First**: Copy database before packing modifications
2. **Use Dry-Run**: Validate with `--dry-run` before actual pack
3. **Version Control YAML**: Commit export directory to git for change tracking
4. **Test on Dev First**: Apply modifications to dev Looker instance before production
5. **Incremental Changes**: Make small, focused modifications rather than large bulk changes
6. **Review Logs**: Check pack output for warnings about modified queries, orphaned items, etc.
7. **Folder Strategy for Navigation**: Use folder strategy when working with specific business units/departments
8. **Full Strategy for Global Changes**: Use full strategy for cross-cutting changes (e.g., model renames)

## Performance Tips

- **Parallel Restore**: Use `--workers 8` for faster restoration to Looker
- **Content Type Filtering**: Export only needed content types with `--content-types`
- **Folder Filtering**: Use `--folder-ids` for extract/restore to limit scope
- **Batch Processing**: Process large datasets in chunks (e.g., 1000 dashboards at a time)

## Next Steps

- Read [data-model.md](./data-model.md) for detailed schema information
- Review [contracts/](./contracts/) for CLI options and YAML structure
- Check [research.md](./research.md) for technical design decisions

## Support

For issues or questions:
- Check [plan.md](./plan.md) for implementation details
- Review [spec.md](./spec.md) for feature requirements
- Report bugs via GitHub issues
