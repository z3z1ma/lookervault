# Feature Specification: Cloud Snapshot Storage & Management

**Feature Branch**: `005-cloud-snapshot-storage`
**Created**: 2025-12-13
**Status**: Draft
**Input**: User description: "Now we need to be able to take the looker.db sqlite file that we're generating and push it to cloud storage under a file name with a date or time stamp embedded in the file name. We need to be able to set a retention policy (sort of an implicit janitor or garbage collector) that collects old snapshots beyond a certain date during runtime. We need to be able to list these snapshots by their date, possibly give them a sequential index to make it easy to pick or a cool terminal UI interface. Most importantly, we need to be able to pull one of those snapshots to local to be a local looker.db or in your restore command, you need to be able to pass a --from-snapshot flag in order to perform a targeted restoration from a specific snapshot in LTS."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Upload Snapshot to Cloud Storage (Priority: P1)

As an administrator, I need to upload my local Looker database snapshot to cloud storage with a timestamped filename so that I have a persistent backup in long-term storage.

**Why this priority**: This is the foundational capability - without the ability to upload snapshots, all other features cannot function. This delivers immediate value by enabling off-site backup storage.

**Independent Test**: Can be fully tested by running a single upload command and verifying the snapshot appears in cloud storage with the correct timestamp format. Delivers value as a standalone backup solution.

**Acceptance Scenarios**:

1. **Given** I have a local `looker.db` file, **When** I run the upload snapshot command, **Then** the file is uploaded to cloud storage with a timestamped filename (e.g., `looker-2025-12-13T14-30-00.db`)
2. **Given** I run the upload command multiple times, **When** each upload completes, **Then** each snapshot has a unique timestamp and all files coexist in cloud storage
3. **Given** the upload is in progress, **When** a network error occurs, **Then** the system retries the upload and provides clear error messages if upload ultimately fails
4. **Given** I have no cloud credentials configured, **When** I attempt to upload, **Then** the system displays a clear error message indicating missing credentials

---

### User Story 2 - List Available Snapshots (Priority: P1)

As an administrator, I need to list all available snapshots in cloud storage sorted by date with sequential indices so that I can easily identify and select snapshots for restoration.

**Why this priority**: This is essential for usability - users need to discover what snapshots exist before they can download or restore them. Without this, the snapshot system is effectively unusable.

**Independent Test**: Can be tested independently by uploading 2-3 snapshots and then running the list command. Delivers value by enabling snapshot discovery and selection.

**Acceptance Scenarios**:

1. **Given** multiple snapshots exist in cloud storage, **When** I run the list snapshots command, **Then** I see all snapshots sorted by date (newest first) with sequential indices (1, 2, 3...)
2. **Given** I want detailed information, **When** I list snapshots in verbose mode, **Then** I see additional metadata including file size, upload timestamp, and cloud storage path
3. **Given** there are many snapshots, **When** I list snapshots with a limit parameter, **Then** I see only the most recent N snapshots
4. **Given** no snapshots exist in cloud storage, **When** I run the list command, **Then** I see a message indicating no snapshots are available

---

### User Story 3 - Download Snapshot to Local (Priority: P2)

As an administrator, I need to download a specific snapshot from cloud storage to my local machine as `looker.db` so that I can restore from a specific point in time.

**Why this priority**: This enables local restoration workflows and disaster recovery. While important, it depends on P1 features (upload and list) being functional first.

**Independent Test**: Can be tested by uploading a snapshot, listing it, then downloading it by index or timestamp. Delivers value by enabling point-in-time recovery to local environment.

**Acceptance Scenarios**:

1. **Given** I know a snapshot's sequential index from listing, **When** I run the download command with that index, **Then** the snapshot is downloaded and saved as `looker.db` in the current directory
2. **Given** I want to download to a specific location, **When** I specify a custom output path, **Then** the snapshot is downloaded to that path
3. **Given** a `looker.db` file already exists locally, **When** I download a snapshot, **Then** the system prompts for confirmation before overwriting or fails with a clear error message
4. **Given** I specify an invalid snapshot index or timestamp, **When** I attempt to download, **Then** the system displays a clear error message and suggests running the list command

---

### User Story 4 - Restore Directly from Cloud Snapshot (Priority: P2)

As an administrator, I need to restore Looker content directly from a cloud snapshot without downloading it first so that I can perform disaster recovery efficiently.

**Why this priority**: This streamlines the restoration workflow by eliminating the intermediate download step. However, it depends on existing restoration functionality and cloud storage integration.

**Independent Test**: Can be tested by uploading a snapshot and then running the restore command with the `--from-snapshot` flag. Delivers value by reducing restore time and simplifying disaster recovery procedures.

**Acceptance Scenarios**:

1. **Given** I know a snapshot's sequential index, **When** I run `restore --from-snapshot 3`, **Then** the system downloads the snapshot to a temporary location and performs the restoration
2. **Given** I want to restore specific content types, **When** I run `restore --from-snapshot 2 dashboards looks`, **Then** only dashboards and looks are restored from that snapshot
3. **Given** the snapshot download fails during restore, **When** the error occurs, **Then** the system reports the error clearly and does not attempt restoration from incomplete data
4. **Given** I use the `--dry-run` flag with `--from-snapshot`, **When** the command runs, **Then** the snapshot is temporarily downloaded and validated but no actual restoration occurs

---

### User Story 5 - Automatic Retention Policy Enforcement (Priority: P3)

As an administrator, I need snapshots older than a configured retention period to be automatically deleted during snapshot operations so that storage costs are controlled without manual intervention.

**Why this priority**: This is a convenience and cost-optimization feature. While valuable for long-term operational efficiency, it's not essential for core backup/restore functionality.

**Independent Test**: Can be tested by setting a short retention period (e.g., 7 days), uploading old and new snapshots, and verifying old snapshots are cleaned up during the next upload or list operation. Delivers value by automating storage management.

**Acceptance Scenarios**:

1. **Given** I have configured a retention policy of 30 days, **When** I upload a new snapshot, **Then** any snapshots older than 30 days are automatically deleted from cloud storage
2. **Given** I have configured a retention policy, **When** I list snapshots, **Then** the retention policy check runs in the background and old snapshots are removed
3. **Given** I have not configured a retention policy, **When** I upload snapshots, **Then** no automatic deletion occurs (retention is disabled by default)
4. **Given** a snapshot is protected or locked, **When** the retention policy runs, **Then** protected snapshots are not deleted regardless of age
5. **Given** deletion of old snapshots fails, **When** the retention policy runs, **Then** the system logs the error but continues with the primary operation (upload/list)

---

### User Story 6 - Interactive Snapshot Selection UI (Priority: P3)

As an administrator, I need an interactive terminal UI to browse and select snapshots so that I can easily choose the right snapshot without memorizing indices or timestamps.

**Why this priority**: This is a user experience enhancement that improves usability but is not essential for core functionality. Users can accomplish all tasks using command-line flags with sequential indices.

**Independent Test**: Can be tested by running the interactive mode and verifying keyboard navigation, selection, and preview functionality work correctly. Delivers value through improved user experience.

**Acceptance Scenarios**:

1. **Given** I run the snapshot command in interactive mode, **When** the UI loads, **Then** I see a navigable list of snapshots with arrow key navigation
2. **Given** I am browsing snapshots in the UI, **When** I highlight a snapshot, **Then** I see a preview panel showing metadata (timestamp, size, content summary)
3. **Given** I have selected a snapshot in the UI, **When** I press Enter, **Then** the system prompts me to choose an action (download, restore, delete)
4. **Given** there are many snapshots, **When** I use the search/filter feature, **Then** the list is filtered to show only matching snapshots by date or keyword

---

### Edge Cases

- What happens when cloud storage credentials expire during an upload operation?
- How does the system handle partial uploads if the network connection is interrupted?
- What happens when two users upload snapshots simultaneously with the same timestamp?
- How does the system handle cloud storage quota exceeded errors?
- What happens when a snapshot file in cloud storage is corrupted or incomplete?
- How does the system handle extremely large database files (>10GB)?
- What happens when the retention policy would delete all snapshots?
- How does the system handle timezone differences in snapshot timestamps?
- What happens when attempting to download a snapshot that was deleted by the retention policy between listing and downloading?
- How does the system handle cloud storage service outages or degraded performance?

## Requirements *(mandatory)*

### Functional Requirements

#### Upload & Storage

- **FR-001**: System MUST upload local `looker.db` file to cloud storage with a filename format of `looker-YYYY-MM-DDTHH-MM-SS.db` using UTC timezone
- **FR-002**: System MUST support Google Cloud Storage (GCS) as the cloud storage provider, with architecture designed to allow additional providers in future iterations
- **FR-003**: System MUST verify file integrity after upload using checksums or cloud storage ETags
- **FR-004**: System MUST retry failed uploads with exponential backoff (max 5 retries)
- **FR-005**: System MUST provide upload progress feedback for files larger than 10MB

#### Listing & Discovery

- **FR-006**: System MUST list all snapshots in cloud storage sorted by timestamp (newest first)
- **FR-007**: System MUST assign sequential indices (1, 2, 3...) to snapshots when listing, with index 1 always representing the most recent snapshot
- **FR-008**: System MUST display snapshot metadata including filename, timestamp, file size, and cloud storage path
- **FR-009**: System MUST support filtering snapshots by date range (e.g., last 7 days, last 30 days)
- **FR-010**: System MUST cache snapshot listings for 5 minutes to reduce cloud storage API calls

#### Download & Local Restore

- **FR-011**: System MUST allow downloading snapshots by sequential index or exact timestamp
- **FR-012**: System MUST download snapshots to a configurable local path (default: `./looker.db`)
- **FR-013**: System MUST verify downloaded file integrity using checksums
- **FR-014**: System MUST prompt for confirmation before overwriting existing `looker.db` files
- **FR-015**: System MUST provide download progress feedback for files larger than 10MB

#### Cloud-Based Restore

- **FR-016**: System MUST support `--from-snapshot` flag in restore commands to restore directly from cloud storage
- **FR-017**: System MUST accept snapshot references by sequential index (e.g., `--from-snapshot 3`) or timestamp (e.g., `--from-snapshot 2025-12-13T14-30-00`)
- **FR-018**: System MUST download snapshot to temporary location during cloud-based restore and clean up after completion
- **FR-019**: System MUST support all existing restore command options (content types, workers, dry-run) when using `--from-snapshot`
- **FR-020**: System MUST validate snapshot exists and is accessible before beginning restore operation

#### Retention Policy & Cleanup

- **FR-021**: System MUST support configurable retention policies specified as number of days (e.g., 30 days)
- **FR-022**: System MUST automatically delete snapshots older than the retention period during upload or list operations
- **FR-023**: System MUST retain at minimum the 5 most recent snapshots regardless of retention policy (safety mechanism)
- **FR-024**: System MUST log all automatic deletion operations with timestamp and reason
- **FR-025**: System MUST allow disabling automatic retention policy (default: disabled)

#### Interactive UI

- **FR-026**: System MUST provide an interactive terminal UI mode for snapshot browsing (optional feature)
- **FR-027**: Interactive UI MUST support keyboard navigation (arrow keys, Enter, Escape)
- **FR-028**: Interactive UI MUST display snapshot metadata in a preview panel
- **FR-029**: Interactive UI MUST allow selecting snapshots for download, restore, or deletion actions

#### Configuration & Security

- **FR-030**: System MUST load GCS credentials from environment variables (GOOGLE_APPLICATION_CREDENTIALS) or service account key file
- **FR-031**: System MUST support configurable GCS bucket names
- **FR-032**: System MUST support configurable snapshot filename prefix (default: `looker`)
- **FR-033**: System MUST encrypt snapshots at rest using cloud provider's encryption features
- **FR-034**: System MUST validate cloud storage permissions before attempting operations

### Key Entities *(include if feature involves data)*

- **Snapshot**: A timestamped backup of the Looker database stored in cloud storage
  - Attributes: filename, timestamp (UTC), file size, cloud storage path, checksum/ETag
  - Relationships: Stored in a cloud storage bucket/container

- **SnapshotMetadata**: Cached information about available snapshots
  - Attributes: sequential index, filename, timestamp, size, GCS bucket name
  - Relationships: Derived from GCS bucket listings

- **RetentionPolicy**: Configuration defining how long snapshots are retained
  - Attributes: retention period (days), minimum snapshots to keep, enabled/disabled status
  - Relationships: Applied during snapshot upload and listing operations

- **GCSStorageProvider**: Google Cloud Storage integration for snapshot management
  - Attributes: bucket name, credentials path, project ID, region/location
  - Relationships: Manages snapshot upload, download, listing, and deletion operations in GCS

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can upload a 100MB database snapshot to cloud storage in under 30 seconds on standard broadband connections
- **SC-002**: Users can list all available snapshots in under 3 seconds, even with 100+ snapshots in storage
- **SC-003**: Users can download and restore from a specific snapshot in under 5 minutes for 100MB database files
- **SC-004**: The retention policy automatically maintains storage costs by deleting 90% of snapshots older than the configured period within 24 hours
- **SC-005**: 95% of snapshot upload and download operations complete successfully without manual retry
- **SC-006**: Users can identify and select the correct snapshot for restoration in under 60 seconds using either the list command or interactive UI
- **SC-007**: The system handles network interruptions gracefully with automatic retry for at least 80% of transient failures
- **SC-008**: Storage costs remain predictable and controlled, with no runaway snapshot accumulation beyond retention policy limits
