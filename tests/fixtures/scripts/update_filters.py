#!/usr/bin/env python3
"""
Example script to update query filters in dashboard YAMLs.

This script demonstrates how to modify dashboard query filters,
changing the time period from '30 days' to '90 days' across all
dashboard YAML files in the specified directory.
"""

import yaml
from pathlib import Path

def update_dashboard_filters(dashboard_dir: Path):
    """
    Update filters in all dashboard YAML files.

    Args:
        dashboard_dir (Path): Directory containing dashboard YAML files
    """
    for yaml_file in dashboard_dir.glob("*.yaml"):
        # Load the dashboard YAML
        with open(yaml_file, 'r') as f:
            dashboard = yaml.safe_load(f)

        # Track whether any changes were made
        modified = False

        # Iterate through dashboard elements
        for element in dashboard.get('dashboard_elements', []):
            query = element.get('query', {})
            filters = query.get('filters', {})

            # Update filters where the period is '30 days'
            for filter_name, filter_value in list(filters.items()):
                if filter_value == "30 days":
                    filters[filter_name] = "90 days"
                    modified = True

        # Save the modified dashboard if changes were made
        if modified:
            with open(yaml_file, 'w') as f:
                yaml.dump(dashboard, f, default_flow_style=False, sort_keys=False)
            print(f"Updated filter periods in {yaml_file.name}")

def main():
    # Default export directory (same as in example)
    dashboard_dir = Path("./export/dashboards")

    # Validate directory exists
    if not dashboard_dir.exists():
        print(f"Error: Directory {dashboard_dir} does not exist.")
        print("Usage: Run this script from the directory containing the 'export' folder.")
        return

    # Run the filter update
    update_dashboard_filters(dashboard_dir)

if __name__ == "__main__":
    main()