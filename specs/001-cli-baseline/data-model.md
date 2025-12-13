# Data Model: Base CLI with Looker Connectivity

**Feature**: 001-cli-baseline
**Date**: 2025-12-13

This document defines the data entities and their relationships for the CLI baseline feature.

---

## Core Entities

### 1. Configuration

Represents the complete LookerVault configuration loaded from TOML file and environment variables.

**Fields**:
- `config_version` (string): Version of the configuration schema (e.g., "1.0")
- `looker` (LookerConfig): Looker-specific configuration
- `output` (OutputConfig): Output formatting preferences

**Validation Rules**:
- `config_version` MUST match supported schema version
- `looker` section MUST be present
- `output` section MAY be omitted (defaults applied)

**State Transitions**:
- UNLOADED → LOADED (after successful file read or env var parsing)
- LOADED → VALIDATED (after Pydantic validation passes)
- VALIDATED → INVALID (if validation fails)

---

### 2. LookerConfig

Looker API connection configuration.

**Fields**:
- `api_url` (string, required): Base URL for Looker API (e.g., "https://looker.example.com:19999")
- `client_id` (string, optional): OAuth client ID (typically from env var)
- `client_secret` (string, optional): OAuth client secret (typically from env var)
- `timeout` (integer, default=30): API request timeout in seconds
- `verify_ssl` (boolean, default=true): Whether to verify SSL certificates

**Validation Rules**:
- `api_url` MUST be valid HTTPS URL
- `api_url` MUST NOT include `/api/*` path
- `timeout` MUST be between 5 and 300 seconds
- `client_id` and `client_secret` MUST both be set (from file or env vars) for operations requiring authentication
- If `client_id` or `client_secret` are empty strings in config, they MUST be provided via environment variables

**Environment Variable Mapping**:
- `LOOKERVAULT_CLIENT_ID` → `client_id`
- `LOOKERVAULT_CLIENT_SECRET` → `client_secret`
- `LOOKERVAULT_API_URL` → `api_url` (overrides config file)

---

### 3. OutputConfig

Output formatting preferences for CLI commands.

**Fields**:
- `default_format` (string, default="table"): Default output format ("table" or "json")
- `color_enabled` (boolean, default=true): Whether to use colored output

**Validation Rules**:
- `default_format` MUST be either "table" or "json"
- `color_enabled` is ignored when `default_format` is "json"

---

### 4. ConnectionStatus

Represents the current state of connectivity to a Looker instance.

**Fields**:
- `connected` (boolean): Whether connection is currently active
- `authenticated` (boolean): Whether authentication succeeded
- `instance_url` (string, optional): Looker instance URL
- `looker_version` (string, optional): Looker release version
- `api_version` (string, optional): Current API version
- `user_id` (integer, optional): Authenticated user ID
- `user_email` (string, optional): Authenticated user email
- `error_message` (string, optional): Error message if connection failed

**State Transitions**:
- DISCONNECTED → CONNECTING (when connection attempt starts)
- CONNECTING → AUTHENTICATED (when authentication succeeds)
- CONNECTING → FAILED (when connection or auth fails)
- AUTHENTICATED → DISCONNECTED (when session ends)

**Validation Rules**:
- If `connected` is true, `authenticated` MUST also be true
- If `connected` is true, `instance_url`, `looker_version`, `api_version`, `user_id`, and `user_email` MUST be populated
- If `connected` is false and `error_message` is present, connection failed
- If `connected` is false and `error_message` is null, not yet attempted

---

### 5. LookerInstance

Metadata about a Looker instance retrieved from the API.

**Fields**:
- `looker_release_version` (string): Looker instance version (e.g., "24.4.12")
- `api_server_url` (string): API base URL
- `web_server_url` (string): Web UI base URL
- `current_api_version` (string): Current API version (e.g., "4.0")
- `supported_api_versions` (list[string]): All supported API versions

**Validation Rules**:
- All fields are required and populated from `sdk.versions()` response
- `current_api_version` MUST be in `supported_api_versions` list

---

### 6. ReadinessCheckResult

Result of a system readiness check.

**Fields**:
- `ready` (boolean): Overall readiness status
- `checks` (list[CheckItem]): Individual check results
- `timestamp` (datetime): When the check was performed

**CheckItem Fields**:
- `name` (string): Name of the check (e.g., "Configuration Valid")
- `status` (string): "pass", "fail", or "warning"
- `message` (string): Detailed status message

**Example Check Items**:
- "Configuration File Found" - PASS/FAIL
- "Configuration Valid" - PASS/FAIL
- "Credentials Configured" - PASS/FAIL/WARNING
- "Python Version" - PASS/WARNING
- "Required Dependencies" - PASS/FAIL

**Validation Rules**:
- `ready` is true only if ALL checks have status "pass" (warnings allowed)
- At least one check MUST be present
- `timestamp` MUST be in ISO 8601 format

---

## Entity Relationships

```
Configuration
├── looker: LookerConfig
│   └── used to create → ConnectionStatus
└── output: OutputConfig
    └── controls formatting of → ReadinessCheckResult, LookerInstance

ConnectionStatus
└── derived from → LookerInstance (via SDK calls)

ReadinessCheckResult
└── validates → Configuration, ConnectionStatus
```

---

## Configuration File Example

```toml
[lookervault]
config_version = "1.0"

[lookervault.looker]
api_url = "https://looker.example.com:19999"
client_id = ""  # Set via LOOKERVAULT_CLIENT_ID env var
client_secret = ""  # Set via LOOKERVAULT_CLIENT_SECRET env var
timeout = 30
verify_ssl = true

[lookervault.output]
default_format = "table"
color_enabled = true
```

---

## Pydantic Models Structure

The data models will be implemented using Pydantic for validation:

```python
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Literal
from datetime import datetime

class LookerConfig(BaseModel):
    api_url: HttpUrl
    client_id: Optional[str] = ""
    client_secret: Optional[str] = ""
    timeout: int = Field(default=30, ge=5, le=300)
    verify_ssl: bool = True

class OutputConfig(BaseModel):
    default_format: Literal["table", "json"] = "table"
    color_enabled: bool = True

class Configuration(BaseModel):
    config_version: str
    looker: LookerConfig
    output: OutputConfig = OutputConfig()

class ConnectionStatus(BaseModel):
    connected: bool
    authenticated: bool
    instance_url: Optional[str] = None
    looker_version: Optional[str] = None
    api_version: Optional[str] = None
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    error_message: Optional[str] = None

class LookerInstance(BaseModel):
    looker_release_version: str
    api_server_url: str
    web_server_url: str
    current_api_version: str
    supported_api_versions: list[str]

class CheckItem(BaseModel):
    name: str
    status: Literal["pass", "fail", "warning"]
    message: str

class ReadinessCheckResult(BaseModel):
    ready: bool
    checks: list[CheckItem]
    timestamp: datetime
```

---

## Notes

- Configuration is immutable once loaded (reload required for changes)
- Credentials (client_id, client_secret) should preferably come from environment variables
- ConnectionStatus is ephemeral - not persisted to disk
- ReadinessCheckResult is generated on-demand, not persisted
