# CLI Commands Contract: Base CLI with Looker Connectivity

**Feature**: 001-cli-baseline
**Date**: 2025-12-13

This document specifies the command-line interface contract for the LookerVault baseline commands.

---

## Global Options

These options are available to all commands:

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--output` | `-o` | string | table | Output format: "table" or "json" |
| `--config` | `-c` | path | ~/.lookervault/config.toml | Path to configuration file |
| `--help` | `-h` | flag | - | Show help message and exit |

---

## Commands

### `lookervault --version`

Display LookerVault version information.

**Usage**:
```bash
lookervault --version
```

**Output (human-readable)**:
```
LookerVault version 0.1.0
```

**Output (JSON)**:
```json
{
  "version": "0.1.0",
  "python_version": "3.11.5"
}
```

**Exit Codes**:
- `0` - Success

---

### `lookervault --help`

Display help information about available commands.

**Usage**:
```bash
lookervault --help
lookervault COMMAND --help
```

**Output**:
```
Usage: lookervault [OPTIONS] COMMAND [ARGS]...

LookerVault - Backup and restore tool for Looker instances

Options:
  --version              Show version and exit
  --help                 Show this message and exit

Commands:
  check  Perform readiness checks
  info   Display Looker instance information
```

**Exit Codes**:
- `0` - Success

---

### `lookervault check`

Perform system readiness checks to validate installation and configuration.

**Usage**:
```bash
lookervault check [OPTIONS]
```

**Options**:
| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--output` | `-o` | string | table | Output format: "table" or "json" |
| `--config` | `-c` | path | ~/.lookervault/config.toml | Path to configuration file |

**Output (human-readable - all checks pass)**:
```
LookerVault Readiness Check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Configuration File Found
✓ Configuration Valid
✓ Credentials Configured
✓ Python Version (3.11.5)
✓ Required Dependencies

Status: READY
Checked: 2025-12-13T10:30:45Z
```

**Output (human-readable - with failures)**:
```
LookerVault Readiness Check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Configuration File Found
✗ Configuration Valid
  Error: Invalid api_url format
⚠ Credentials Configured
  Warning: client_secret not set (required for Looker connection)
✓ Python Version (3.11.5)
✓ Required Dependencies

Status: NOT READY
Checked: 2025-12-13T10:30:45Z
```

**Output (JSON)**:
```json
{
  "ready": false,
  "checks": [
    {
      "name": "Configuration File Found",
      "status": "pass",
      "message": "Found at /Users/user/.lookervault/config.toml"
    },
    {
      "name": "Configuration Valid",
      "status": "fail",
      "message": "Invalid api_url format"
    },
    {
      "name": "Credentials Configured",
      "status": "warning",
      "message": "client_secret not set (required for Looker connection)"
    },
    {
      "name": "Python Version",
      "status": "pass",
      "message": "3.11.5"
    },
    {
      "name": "Required Dependencies",
      "status": "pass",
      "message": "All dependencies available"
    }
  ],
  "timestamp": "2025-12-13T10:30:45Z"
}
```

**Exit Codes**:
- `0` - All checks passed (ready)
- `1` - One or more checks failed (not ready)
- `2` - Configuration file not found or invalid

**Checks Performed**:
1. **Configuration File Found** - Verifies config file exists at specified path
2. **Configuration Valid** - Validates TOML syntax and schema
3. **Credentials Configured** - Checks if client_id and client_secret are set (env vars or config)
4. **Python Version** - Verifies Python 3.11+ is being used
5. **Required Dependencies** - Confirms looker-sdk, typer, pydantic are available

---

### `lookervault info`

Connect to Looker instance and display instance information.

**Usage**:
```bash
lookervault info [OPTIONS]
```

**Options**:
| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--output` | `-o` | string | table | Output format: "table" or "json" |
| `--config` | `-c` | path | ~/.lookervault/config.toml | Path to configuration file |

**Output (human-readable)**:
```
Looker Instance Information
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Instance URL    https://looker.example.com:19999
Looker Version  24.4.12
API Version     4.0
User            admin@example.com (ID: 1)
Status          Connected

Supported API Versions: 3.1, 4.0
```

**Output (JSON)**:
```json
{
  "connected": true,
  "authenticated": true,
  "instance_url": "https://looker.example.com:19999",
  "looker_version": "24.4.12",
  "api_version": "4.0",
  "user_id": 1,
  "user_email": "admin@example.com",
  "supported_api_versions": ["3.1", "4.0"]
}
```

**Error Output (authentication failure)**:
```
Error: Failed to connect to Looker instance

Reason: Authentication failed - invalid client_secret

Troubleshooting:
  - Verify LOOKERVAULT_CLIENT_ID and LOOKERVAULT_CLIENT_SECRET are set
  - Check that credentials have not expired
  - Ensure api_url is correct: https://looker.example.com:19999
```

**Error Output (JSON)**:
```json
{
  "connected": false,
  "authenticated": false,
  "error_message": "Authentication failed - invalid client_secret"
}
```

**Exit Codes**:
- `0` - Successfully connected and retrieved instance info
- `2` - Configuration error (missing credentials, invalid api_url)
- `3` - Connection error (authentication failed, network timeout, API unreachable)

---

## Standard Output Streams

### stdout (Standard Output)
- Primary command output
- Human-readable tables (default)
- JSON output (when `--output json` specified)
- Suitable for piping to other tools

### stderr (Standard Error)
- Error messages
- Warning messages
- Debug/verbose output (future feature)
- Does not interfere with stdout piping

**Example**:
```bash
# Pipe JSON output to jq
lookervault info --output json | jq '.looker_version'

# Errors go to stderr, don't interfere with pipe
lookervault info --output json 2>/dev/null | jq '.'
```

---

## Environment Variables

The following environment variables are recognized:

| Variable | Description | Example |
|----------|-------------|---------|
| `LOOKERVAULT_CLIENT_ID` | Looker OAuth client ID | `abc123` |
| `LOOKERVAULT_CLIENT_SECRET` | Looker OAuth client secret | `secret456` |
| `LOOKERVAULT_API_URL` | Looker API base URL (overrides config) | `https://looker.example.com:19999` |
| `LOOKERVAULT_CONFIG` | Path to config file (overrides default) | `/etc/lookervault/config.toml` |
| `NO_COLOR` | Disable colored output (standard) | `1` |

**Priority** (highest to lowest):
1. Command-line arguments
2. Environment variables
3. Configuration file
4. Built-in defaults

---

## Configuration File Location

Default configuration file locations (checked in order):

1. Path specified via `--config` flag
2. `$LOOKERVAULT_CONFIG` environment variable
3. `~/.lookervault/config.toml` (user home directory)
4. `./lookervault.toml` (current working directory)

If no configuration file is found, environment variables and command-line arguments are used exclusively.

---

## Exit Code Summary

| Code | Meaning | Usage |
|------|---------|-------|
| `0` | Success | All operations completed successfully |
| `1` | General error | Unspecified failure or readiness check failed |
| `2` | Configuration error | Invalid config file, missing credentials, bad api_url |
| `3` | Connection error | Cannot reach Looker, authentication failed, network timeout |
| `130` | Interrupted | User cancelled with Ctrl+C |

---

## Future Commands (Not in Baseline)

The following commands are planned for future features but NOT part of this baseline implementation:

- `lookervault backup` - Create backup snapshot
- `lookervault restore` - Restore from snapshot
- `lookervault list` - List available backups
- `lookervault config` - Manage configuration interactively

---

## Compatibility

- **Shell**: Compatible with bash, zsh, fish, PowerShell
- **Piping**: Supports Unix pipeline conventions (stdout/stderr separation)
- **Exit Codes**: Follows standard Unix conventions
- **Color**: Respects `NO_COLOR` environment variable
- **JSON**: Machine-readable output suitable for automation
