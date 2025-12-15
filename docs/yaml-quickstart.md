# YAML Modification Workflow - Quick Start Guide

**Goal**: Make bulk modifications to hundreds of Looker dashboards in minutes using YAML files and scripts.

## The 5-Step Workflow

```bash
# 1. Extract content from Looker
lookervault extract dashboards --workers 8

# 2. Unpack SQLite database to YAML files
lookervault unpack --output-dir export/

# 3. Modify YAML files with scripts
sed -i 's/old_model/new_model/g' export/dashboards/*.yaml

# 4. Pack modified YAML back to database
lookervault pack --input-dir export/ --db-path modified.db

# 5. Restore changes to Looker
lookervault restore bulk dashboards --db-path modified.db --workers 8
```

## Step-by-Step Tutorial

### Step 1: Extract Dashboards from Looker

Extract content from Looker into a local SQLite database:

```bash
# Extract all dashboards (creates looker.db)
lookervault extract dashboards --workers 8

# Verify extraction
lookervault snapshot list
```

**Expected output**:
```
✓ Extracted 500 dashboards to looker.db (12.3 MB)
```

### Step 2: Unpack to YAML Files

Convert the SQLite database into human-readable YAML files:

```bash
# Create export directory with YAML files
lookervault unpack --output-dir export/

# Examine the structure
ls export/
```

**Directory structure**:
```
export/
├── metadata.json          # Export metadata
├── dashboards/
│   ├── 1.yaml            # Dashboard ID 1
│   ├── 2.yaml            # Dashboard ID 2
│   └── ...               # More dashboards
```

**Example YAML file** (`export/dashboards/42.yaml`):
```yaml
id: "42"
title: "Sales Dashboard 2024"
description: "Q4 sales metrics"
dashboard_elements:
  - id: "elem1"
    title: "Total Revenue"
    query:
      model: "sales_old"
      view: "transactions"
      fields: ["transactions.total_revenue"]
      filters:
        transactions.date: "30 days"

_metadata:
  db_id: "42"
  content_type: "DASHBOARD"
  exported_at: "2025-12-14T12:00:00"
```

### Step 3: Modify YAML Files

Use command-line tools or scripts to make bulk modifications.

#### Example A: Update Model References (sed)

Change `sales_old` to `sales_new` across all dashboards:

```bash
# Replace model references
sed -i 's/model: "sales_old"/model: "sales_new"/g' export/dashboards/*.yaml

# Verify changes
grep "model:" export/dashboards/42.yaml
# Output: model: "sales_new"
```

#### Example B: Update Dashboard Titles (sed)

Change "2024" to "2025" in all dashboard titles:

```bash
# Update year in titles
sed -i 's/title: "\(.*\)2024\(.*\)"/title: "\12025\2"/g' export/dashboards/*.yaml

# Verify changes
grep "^title:" export/dashboards/42.yaml
# Output: title: "Sales Dashboard 2025"
```

#### Example C: Update Query Filters (Python)

Change filter time periods from "30 days" to "90 days":

**Script** (`update_filters.py`):
```python
#!/usr/bin/env python3
import yaml
from pathlib import Path

# Process all dashboard YAML files
for yaml_file in Path("export/dashboards").glob("*.yaml"):
    with open(yaml_file) as f:
        dashboard = yaml.safe_load(f)

    modified = False
    for element in dashboard.get('dashboard_elements', []):
        query = element.get('query', {})
        filters = query.get('filters', {})

        # Update time period filters
        for key, value in filters.items():
            if value == "30 days":
                filters[key] = "90 days"
                modified = True

    if modified:
        with open(yaml_file, 'w') as f:
            yaml.dump(dashboard, f, default_flow_style=False)
        print(f"✓ Updated {yaml_file.name}")
```

**Run the script**:
```bash
python update_filters.py
# Output:
# ✓ Updated 1.yaml
# ✓ Updated 2.yaml
# ✓ Updated 42.yaml
# ...
```

### Step 4: Pack Modified YAML

Convert the modified YAML files back into a SQLite database.

**IMPORTANT**: Always validate with `--dry-run` first!

```bash
# Validate modifications (no database changes)
lookervault pack --input-dir export/ --db-path modified.db --dry-run

# If validation passes, pack for real
lookervault pack --input-dir export/ --db-path modified.db
```

**Expected output**:
```
✓ Validation passed
✓ Packed 500 dashboards to modified.db
  Modified: 500 dashboards
  Unchanged: 0 dashboards
  New queries created: 0
```

### Step 5: Restore to Looker

Upload the modified dashboards back to Looker:

```bash
# Restore dashboards with 8 parallel workers
lookervault restore bulk dashboards --db-path modified.db --workers 8
```

**Expected output**:
```
✓ Restored 500 dashboards
  Created: 0
  Updated: 500
  Failed: 0
  Duration: 45 seconds
```

**Verify in Looker UI**: Check that your dashboards now have the updated values.

## Common Use Cases

### Use Case 1: Change Model References

**Scenario**: Migrate all dashboards from `old_model` to `new_model`.

```bash
# Extract dashboards
lookervault extract dashboards --workers 8

# Unpack to YAML
lookervault unpack --output-dir export/

# Replace model references
sed -i 's/model: "old_model"/model: "new_model"/g' export/dashboards/*.yaml

# Pack and restore
lookervault pack --input-dir export/ --db-path modified.db --dry-run  # Validate first!
lookervault pack --input-dir export/ --db-path modified.db
lookervault restore bulk dashboards --db-path modified.db --workers 8
```

### Use Case 2: Update Filter Time Periods

**Scenario**: Change all dashboard filters from "7 days" to "30 days".

```bash
# Extract and unpack
lookervault extract dashboards --workers 8
lookervault unpack --output-dir export/

# Update filters using Python script (see Step 3C above)
python update_filters.py

# Pack and restore
lookervault pack --input-dir export/ --db-path modified.db --dry-run
lookervault pack --input-dir export/ --db-path modified.db
lookervault restore bulk dashboards --db-path modified.db --workers 8
```

### Use Case 3: Standardize Dashboard Naming

**Scenario**: Add "FY2025 - " prefix to all dashboard titles.

```bash
# Extract and unpack
lookervault extract dashboards --workers 8
lookervault unpack --output-dir export/

# Add prefix to titles
sed -i 's/^title: "\(.*\)"/title: "FY2025 - \1"/g' export/dashboards/*.yaml

# Pack and restore
lookervault pack --input-dir export/ --db-path modified.db --dry-run
lookervault pack --input-dir export/ --db-path modified.db
lookervault restore bulk dashboards --db-path modified.db --workers 8
```

### Use Case 4: Folder-Based Modifications

**Scenario**: Modify only dashboards in "Sales/Regional/West" folder.

```bash
# Extract specific folder
lookervault extract --folder-ids "791" dashboards --workers 8

# Unpack with folder hierarchy
lookervault unpack --output-dir export/ --strategy folder

# Directory structure preserves folders:
# export/
# ├── Sales/
# │   ├── Regional/
# │   │   ├── West/
# │   │   │   ├── 42.yaml
# │   │   │   └── 43.yaml

# Modify only West region dashboards
sed -i 's/description: "\(.*\)"/description: "\1 (West Region)"/g' \
  export/Sales/Regional/West/*.yaml

# Pack and restore
lookervault pack --input-dir export/ --db-path modified.db
lookervault restore bulk dashboards --db-path modified.db --folder-ids "791"
```

## Common Pitfalls & Warnings

### ⚠️ PITFALL 1: Forgetting Dry-Run Validation

**Problem**: Packing invalid YAML files creates corrupted database.

**Solution**: ALWAYS run `--dry-run` first!

```bash
# ❌ BAD: Pack without validation
lookervault pack --input-dir export/ --db-path modified.db

# ✅ GOOD: Validate first, then pack
lookervault pack --input-dir export/ --db-path modified.db --dry-run
lookervault pack --input-dir export/ --db-path modified.db
```

### ⚠️ PITFALL 2: Modifying _metadata Section

**Problem**: The `_metadata` section is required for round-trip fidelity.

**Solution**: NEVER modify `_metadata` fields!

```yaml
# ✅ SAFE: Modify content data
title: "New Title"
description: "Updated description"

# ❌ DANGEROUS: Do NOT modify metadata
_metadata:
  db_id: "42"           # DO NOT CHANGE
  content_type: "DASHBOARD"  # DO NOT CHANGE
  exported_at: "..."    # DO NOT CHANGE
```

### ⚠️ PITFALL 3: Using sed on macOS Without Backup Suffix

**Problem**: macOS `sed -i` requires a backup suffix.

**Solution**: Use `sed -i '' ...` on macOS or `sed -i ...` on Linux.

```bash
# ❌ FAILS on macOS
sed -i 's/old/new/g' export/dashboards/*.yaml

# ✅ WORKS on macOS
sed -i '' 's/old/new/g' export/dashboards/*.yaml

# ✅ WORKS on Linux
sed -i 's/old/new/g' export/dashboards/*.yaml
```

### ⚠️ PITFALL 4: Breaking YAML Syntax with sed

**Problem**: sed can create invalid YAML if not careful with quotes/indentation.

**Solution**: Test on a single file first, or use Python for complex modifications.

```bash
# ❌ RISKY: May break YAML syntax
sed -i '' 's/title: \(.*\)/title: "\1"/g' export/dashboards/*.yaml

# ✅ SAFER: Test on one file first
sed 's/title: \(.*\)/title: "\1"/g' export/dashboards/1.yaml > test.yaml
yamllint test.yaml  # Validate syntax

# ✅ SAFEST: Use Python for complex changes
python update_dashboards.py
```

### ⚠️ PITFALL 5: Not Backing Up Original Database

**Problem**: No way to revert if modifications break dashboards.

**Solution**: Always backup before packing modifications.

```bash
# ✅ SAFE: Backup first
cp looker.db looker-backup-$(date +%Y%m%d).db

# Make modifications
lookervault unpack --output-dir export/
# ... modify YAML files ...
lookervault pack --input-dir export/ --db-path modified.db

# If something goes wrong, restore from backup:
cp looker-backup-20251214.db looker.db
```

### ⚠️ PITFALL 6: Insufficient Disk Space

**Problem**: Export requires ~3.5x database size on disk.

**Solution**: Check available disk space before unpacking.

```bash
# Check database size
ls -lh looker.db
# Output: 12M looker.db

# Estimate export size: 12M × 3.5 = 42M minimum
df -h .
# Ensure >50M available before unpacking
```

### ⚠️ PITFALL 7: Deleting YAML Files Without --force

**Problem**: Deleted YAML files don't delete corresponding database items.

**Solution**: Use `--force` flag to delete items for missing files.

```bash
# Scenario: You deleted export/dashboards/42.yaml

# ❌ WITHOUT --force: Item 42 remains in database
lookervault pack --input-dir export/ --db-path modified.db
# Warning: 1 file missing from export directory

# ✅ WITH --force: Item 42 deleted from database
lookervault pack --input-dir export/ --db-path modified.db --force
# Deleted 1 database item for missing YAML file
```

### ⚠️ PITFALL 8: Ignoring Validation Errors

**Problem**: Proceeding despite validation errors creates corrupted content.

**Solution**: Fix ALL validation errors before packing.

```bash
# Dry-run shows validation errors
lookervault pack --input-dir export/ --dry-run

# Example errors:
# ✗ YAML syntax error in dashboards/123.yaml:
#     Line 42: mapping values are not allowed here
# ✗ Schema validation failed for dashboards/456.yaml:
#     Missing required field 'title'

# ❌ BAD: Ignoring errors and packing anyway
lookervault pack --input-dir export/ --db-path modified.db  # CORRUPTED!

# ✅ GOOD: Fix errors first
vim export/dashboards/123.yaml  # Fix syntax
vim export/dashboards/456.yaml  # Add missing field
lookervault pack --input-dir export/ --dry-run  # Verify clean
lookervault pack --input-dir export/ --db-path modified.db  # Now safe
```

## Troubleshooting

### Error: YAML Syntax Error

```
✗ YAML syntax error in dashboards/123.yaml:
    Line 42: mapping values are not allowed here
```

**Fix**: Check YAML syntax with a validator or linter.

```bash
# Install yamllint
pip install yamllint

# Validate YAML syntax
yamllint export/dashboards/123.yaml

# Fix indentation, quotes, or special characters
```

### Error: Schema Validation Failed

```
✗ Schema validation failed for dashboards/456.yaml:
    Missing required field 'title'
```

**Fix**: Ensure all required fields are present.

```bash
# Check the YAML file
cat export/dashboards/456.yaml

# Add missing field
# Edit file to include: title: "My Dashboard"
```

### Error: Insufficient Disk Space

```
✗ Insufficient disk space for export
  Required: 42 MB
  Available: 15 MB
```

**Fix**: Free up disk space or export to a different location.

```bash
# Option 1: Free up space
rm -rf old_exports/

# Option 2: Export to external drive
lookervault unpack --output-dir /Volumes/External/export/

# Option 3: Export only specific content types
lookervault unpack --content-types dashboards --output-dir export/
```

### Warning: Orphaned Content

```
⚠ Found 3 orphaned items (missing folder_id or invalid parent_id)
  - 999.yaml
  - 998.yaml
  - 997.yaml
  Placed in _orphaned/ directory
```

**Fix**: Review orphaned items and assign to correct folders.

```bash
# Inspect orphaned items
cat export/_orphaned/999.yaml

# Option 1: Move to correct folder directory
mv export/_orphaned/999.yaml export/Sales/

# Option 2: Update folder_id in YAML metadata

# Option 3: Leave in _orphaned/ (will be imported without folder)
```

## Best Practices

### 1. Always Use Dry-Run First

```bash
# Validate before packing
lookervault pack --input-dir export/ --dry-run --verbose

# Only proceed if validation passes
lookervault pack --input-dir export/
```

### 2. Backup Original Database

```bash
# Backup before modifications
cp looker.db looker-backup-$(date +%Y%m%d).db

# Make changes
# ...

# Revert if needed
cp looker-backup-20251214.db looker.db
```

### 3. Version Control YAML Files

```bash
# Initialize git repository
cd export/
git init
git add .
git commit -m "Initial export"

# Make modifications
sed -i '' 's/old/new/g' dashboards/*.yaml
git diff  # Review changes
git commit -am "Update model references"
```

### 4. Test on Small Sample First

```bash
# Test modification script on one file
python update_filters.py export/dashboards/1.yaml

# Verify result
lookervault pack --input-dir export/ --dry-run

# If successful, run on all files
python update_filters.py export/dashboards/
```

### 5. Use Folder Strategy for Navigation

```bash
# For folder-scoped changes, use folder strategy
lookervault unpack --strategy folder --output-dir export/

# Easier to navigate and modify specific business units
ls export/Sales/Regional/West/
```

## Advanced Examples

### Replace Field References

Change all references from `old_field` to `new_field`:

```bash
lookervault unpack --output-dir export/

# Replace field references in queries
find export/dashboards -name "*.yaml" -exec \
  sed -i '' 's/"old_field"/"new_field"/g' {} +

lookervault pack --input-dir export/ --db-path modified.db --dry-run
lookervault pack --input-dir export/ --db-path modified.db
```

### Add Tags to All Dashboards

Add audit tags for compliance tracking:

```python
#!/usr/bin/env python3
import yaml
from pathlib import Path
from datetime import datetime

for yaml_file in Path("export/dashboards").glob("*.yaml"):
    with open(yaml_file) as f:
        dashboard = yaml.safe_load(f)

    if 'tags' not in dashboard:
        dashboard['tags'] = []

    review_tag = f"reviewed:{datetime.now().strftime('%Y-%m-%d')}"
    if review_tag not in dashboard['tags']:
        dashboard['tags'].append(review_tag)

    with open(yaml_file, 'w') as f:
        yaml.dump(dashboard, f, default_flow_style=False)
    print(f"✓ Tagged {yaml_file.name}")
```

### Multi-Stage Workflow

Make incremental modifications with validation between stages:

```bash
# Stage 1: Update titles
lookervault unpack --output-dir export1/
sed -i '' 's/2024/2025/g' export1/dashboards/*.yaml
lookervault pack --input-dir export1/ --db-path looker.db --dry-run
lookervault pack --input-dir export1/ --db-path looker.db

# Stage 2: Update queries (uses updated database from Stage 1)
lookervault unpack --output-dir export2/
python update_queries.py export2/dashboards/
lookervault pack --input-dir export2/ --db-path looker.db --dry-run
lookervault pack --input-dir export2/ --db-path looker.db

# Final restore
lookervault restore bulk dashboards --workers 8
```

## Next Steps

- **Full Documentation**: See [yaml-export-import.md](./yaml-export-import.md) for complete CLI reference
- **Data Model**: See `specs/006-yaml-export-import/data-model.md` for YAML schema details
- **Advanced Patterns**: See `specs/006-yaml-export-import/quickstart.md` for query remapping, checksum validation, etc.

## Quick Reference

### Essential Commands

```bash
# Extract → Unpack → Modify → Pack → Restore
lookervault extract dashboards --workers 8
lookervault unpack --output-dir export/
# ... modify YAML files ...
lookervault pack --input-dir export/ --db-path modified.db --dry-run
lookervault pack --input-dir export/ --db-path modified.db
lookervault restore bulk dashboards --db-path modified.db --workers 8

# Folder-based workflow
lookervault extract --folder-ids "791" dashboards
lookervault unpack --strategy folder --output-dir export/
# ... modify YAML files ...
lookervault pack --input-dir export/ --db-path modified.db
lookervault restore bulk dashboards --folder-ids "791"
```

### Validation Commands

```bash
# Always validate first
lookervault pack --dry-run --verbose

# Check YAML syntax
yamllint export/dashboards/*.yaml

# Preview changes with git
cd export/
git diff
```

### Safety Commands

```bash
# Backup database
cp looker.db looker-backup-$(date +%Y%m%d).db

# Delete items for missing YAML files
lookervault pack --force

# Restore from backup
cp looker-backup-20251214.db looker.db
```

---

**Need Help?** Check [yaml-export-import.md](./yaml-export-import.md) for full documentation or report issues in the project repository.
