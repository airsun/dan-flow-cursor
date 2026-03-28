## ADDED Requirements

### Requirement: File discovery
The sync agent SHALL discover all JSONL files under `~/.cursor/projects/` and `~/.claude/projects/`, including subagent files under `subagents/` subdirectories. The agent SHALL classify each file by source type: `cursor`, `cursor-sub`, `claude`, `claude-sub`.

#### Scenario: Initial scan on startup
- **WHEN** the sync agent starts
- **THEN** it SHALL scan both base directories recursively for `*.jsonl` files and record each file's path, source type, and current size

#### Scenario: New file appears during runtime
- **WHEN** a new JSONL file is created in a watched directory
- **THEN** the agent SHALL detect it within the configured poll interval and add it to the tracked file set with offset 0

#### Scenario: Subagent file detection
- **WHEN** a JSONL file exists under a `subagents/` subdirectory
- **THEN** the agent SHALL classify it as `cursor-sub` or `claude-sub` and record its parent session path based on directory structure

### Requirement: Incremental upload
The sync agent SHALL upload only new bytes appended to each JSONL file since the last acknowledged offset. The agent SHALL NOT re-upload already-acknowledged data.

#### Scenario: File has grown since last sync
- **WHEN** a tracked JSONL file's size exceeds the last acknowledged offset
- **THEN** the agent SHALL read bytes from the acknowledged offset to current size and POST them to the server's sync push endpoint

#### Scenario: File has not changed
- **WHEN** a tracked JSONL file's size and mtime are unchanged since last check
- **THEN** the agent SHALL skip that file and perform no upload

#### Scenario: Large accumulated delta after offline period
- **WHEN** the agent reconnects after an offline period with >64KB of unsynced data per file
- **THEN** the agent SHALL split the upload into chunks of at most `batch_size` bytes (default 65536) and upload sequentially, awaiting ack between each chunk

### Requirement: Handshake protocol
The sync agent SHALL perform a handshake with the server on startup and on reconnection to reconcile file offsets.

#### Scenario: Startup handshake
- **WHEN** the agent starts or reconnects after network loss
- **THEN** the agent SHALL POST its full file list with local sizes to `/sync/handshake` and receive the server's known offsets per file

#### Scenario: Server has lower offset than local state
- **WHEN** the server reports an offset lower than the agent's persisted offset for a file
- **THEN** the agent SHALL trust the server's offset and re-upload from the server's offset (the agent's local state may be ahead due to a failed ack)

#### Scenario: Server has unknown file
- **WHEN** the server responds with offset 0 for a file
- **THEN** the agent SHALL upload the entire file contents starting from offset 0

### Requirement: Offset state persistence
The sync agent SHALL persist its file tracking state to a local JSON file so it can resume after restart without re-scanning all file contents.

#### Scenario: Clean shutdown
- **WHEN** the agent receives SIGTERM or SIGINT
- **THEN** it SHALL write current file offsets to `~/.dan-flow/sync-state.json` before exiting

#### Scenario: Startup with existing state
- **WHEN** the agent starts and `~/.dan-flow/sync-state.json` exists
- **THEN** it SHALL load persisted offsets as the starting point, then handshake with server to reconcile

#### Scenario: State file missing or corrupt
- **WHEN** the state file is missing or unparseable
- **THEN** the agent SHALL treat all files as having offset 0 and rely on handshake to avoid redundant uploads

### Requirement: Project metadata extraction
The sync agent SHALL extract project metadata for each JSONL file to help the server resolve project identity.

#### Scenario: Project has git remote
- **WHEN** the JSONL file belongs to a project directory that contains a `.git` directory with a configured remote
- **THEN** the agent SHALL include the git remote URL in the sync push payload as `git_remote`

#### Scenario: Project without git
- **WHEN** the project directory has no `.git` or no remote configured
- **THEN** the agent SHALL include a `project_hint` derived from the directory name with user-specific prefixes stripped

### Requirement: Network resilience
The sync agent SHALL handle network failures gracefully without data loss or corruption.

#### Scenario: Server unreachable during push
- **WHEN** a push request fails due to network error or server error (5xx)
- **THEN** the agent SHALL retry with exponential backoff (1s, 2s, 4s, 8s, max 60s) and SHALL NOT advance the local offset until ack is received

#### Scenario: Server returns 401
- **WHEN** a sync request returns HTTP 401
- **THEN** the agent SHALL log an authentication error and stop retrying until the token is updated in config

#### Scenario: Laptop sleep/wake cycle
- **WHEN** the system resumes from sleep
- **THEN** the agent SHALL detect the time gap, re-scan all files for changes, and perform a handshake before resuming normal sync

### Requirement: Configuration
The sync agent SHALL be configured via a YAML file at `~/.dan-flow/config.yaml`.

#### Scenario: Minimal configuration
- **WHEN** the config file contains only `server.url` and `server.token`
- **THEN** the agent SHALL use defaults for all other settings: poll interval 5s, batch size 65536, include subagents true, standard Cursor and Claude base paths

#### Scenario: Custom base paths
- **WHEN** the config file specifies custom paths under `sources`
- **THEN** the agent SHALL watch those paths instead of the defaults

### Requirement: Daemon lifecycle
The sync agent SHALL run as a background daemon suitable for management by macOS launchd or systemd.

#### Scenario: Foreground execution
- **WHEN** started with no flags
- **THEN** the agent SHALL run in the foreground with log output to stderr

#### Scenario: Startup logging
- **WHEN** the agent starts successfully
- **THEN** it SHALL log: device name, server URL, number of tracked files, and initial sync status
