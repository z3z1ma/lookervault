#!/bin/bash

# Script to update dashboard titles with a prefix
# Demonstrates using sed to modify YAML file titles

# Validate export directory
if [ ! -d "./export/dashboards" ]; then
    echo "Error: Dashboard export directory not found."
    echo "Usage: Run this script from the directory containing the 'export' folder."
    exit 1
fi

# Add "FY2025 - " prefix to all dashboard titles
# Uses sed with in-place editing, works on macOS and Linux with slightly different syntax
sed -i '' 's/^title: "\(.*\)"/title: "FY2025 - \1"/g' ./export/dashboards/*.yaml

echo "Successfully updated dashboard titles with FY2025 prefix."