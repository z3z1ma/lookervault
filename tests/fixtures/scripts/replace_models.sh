#!/bin/bash

# Script to replace LookML model references across dashboard YAML files
# Demonstrates using awk to globally modify model references

# Configuration
OLD_MODEL="old_model"
NEW_MODEL="new_model"

# Validate export directory
if [ ! -d "./export/dashboards" ]; then
    echo "Error: Dashboard export directory not found."
    echo "Usage: Run this script from the directory containing the 'export' folder."
    exit 1
fi

# Iterate through all dashboard YAML files
for file in ./export/dashboards/*.yaml; do
    # Use awk to replace model references
    awk -v old="$OLD_MODEL" -v new="$NEW_MODEL" \
        '{gsub("model: \"" old "\"", "model: \"" new "\""); print}' \
        "$file" > "$file.tmp"

    # Replace original file with modified version
    mv "$file.tmp" "$file"
done

echo "Successfully replaced model references from '$OLD_MODEL' to '$NEW_MODEL'."