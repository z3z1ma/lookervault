# LookerVault

**Ever wish you could hit "Undo" on a Looker disaster? With LookerVault, you can.**

LookerVault is a CLI tool that backs up your entire Looker content (models, dashboards, and more) into compressed snapshots, securely uploaded to cloud storage. Whether you're migrating Looker instances or need a safety net, LookerVault makes it easy.

## Current Status: Baseline CLI (v0.1.0)

This release provides the foundational CLI with Looker connectivity verification. Full backup/restore functionality is coming in future releases.

### Available Commands

- `lookervault --help` - Display help information
- `lookervault --version` - Show version information
- `lookervault check` - Verify installation and configuration readiness
- `lookervault info` - Display Looker instance information and test connectivity

## Installation

### Prerequisites

- Python 3.11 or later
- Access to a Looker instance with API credentials

### Install from Source

```bash
# Clone the repository
git clone https://github.com/yourusername/lookervault.git
cd lookervault

# Create virtual environment with uv
uv venv

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode
uv sync --all-extras --dev
```

## Configuration

### 1. Create Configuration File

Create `~/.lookervault/config.toml`:

```toml
[lookervault]
config_version = "1.0"

[lookervault.looker]
api_url = "https://your-looker-instance.com:19999"
client_id = ""  # Set via LOOKERVAULT_CLIENT_ID env var
client_secret = ""  # Set via LOOKERVAULT_CLIENT_SECRET env var
timeout = 30
verify_ssl = true

[lookervault.output]
default_format = "table"  # or "json"
color_enabled = true
```

See `tests/fixtures/sample_config.toml` for a complete example.

### 2. Set Environment Variables

```bash
export LOOKERVAULT_CLIENT_ID="your_client_id"
export LOOKERVAULT_CLIENT_SECRET="your_client_secret"
```

For permanent configuration, add these to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.).

## Usage

### Verify Installation

```bash
# Check that everything is configured correctly
lookervault check

# Get JSON output for scripting
lookervault check --output json
```

### Test Looker Connection

```bash
# Display Looker instance information
lookervault info

# Get JSON output
lookervault info --output json

# Use custom config file
lookervault info --config /path/to/config.toml
```

## Development

### Running Tests

```bash
# Run all tests with coverage
pytest tests/ -v --cov

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/
```

### Code Quality

```bash
# Type checking
mypy src/lookervault

# Linting
ruff check src/

# Formatting
ruff format src/
```

### Project Structure

```
src/lookervault/
├── cli/                 # CLI commands and output formatting
│   ├── commands/        # Individual command implementations
│   ├── main.py          # Typer app definition
│   └── output.py        # Output formatting utilities
├── config/              # Configuration management
│   ├── models.py        # Pydantic data models
│   ├── loader.py        # Config file loading
│   └── validator.py     # Readiness checks
└── looker/              # Looker SDK integration
    ├── client.py        # SDK wrapper
    └── connection.py    # Connection testing
```

## Roadmap

### Future Features (Not Yet Implemented)

- 🗃 **Backup Operations:** Create compressed SQLite snapshots of Looker content
- 🌩 **Cloud Storage:** Upload backups to S3, GCS, or Azure Blob Storage
- 🔄 **Restore Operations:** Restore from snapshots with conflict resolution
- 📊 **Backup Management:** List, compare, and manage backup snapshots
- 🛡 **Disaster Recovery:** Automated recovery workflows

See the project roadmap for detailed feature planning.

## Exit Codes

LookerVault uses standard exit codes:

- `0` - Success
- `1` - General error
- `2` - Configuration error
- `3` - Connection error
- `130` - Interrupted by user (Ctrl+C)

## Contributing

Contributions are welcome! Please see CONTRIBUTING.md for guidelines.

## License

See LICENSE file for details.

## Support

- Report issues: [GitHub Issues](https://github.com/yourusername/lookervault/issues)
- Documentation: [Wiki](https://github.com/yourusername/lookervault/wiki)
