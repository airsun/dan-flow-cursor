## ADDED Requirements

### Requirement: Sync handshake endpoint
The server SHALL expose `POST /sync/handshake` that accepts a file list from a sync agent and returns the server's known offset for each file.

#### Scenario: Known files with existing offsets
- **WHEN** an authenticated sync agent sends a handshake with files the server has previously received data for
- **THEN** the server SHALL respond with the last acknowledged offset for each file

#### Scenario: Unknown files in handshake
- **WHEN** the handshake includes files the server has never seen
- **THEN** the server SHALL respond with offset 0 for those files, indicating full upload is needed

#### Scenario: Unauthenticated handshake
- **WHEN** a handshake request lacks a valid device token
- **THEN** the server SHALL respond with HTTP 401

### Requirement: Sync push endpoint
The server SHALL expose `POST /sync/push` that receives incremental JSONL data from sync agents, persists it, and parses it into structured records.

#### Scenario: Valid push with new data
- **WHEN** an authenticated agent pushes data for a file at the expected offset
- **THEN** the server SHALL store the raw data, parse each JSONL line into the messages table, update the session record, advance the sync offset, and respond with `{ack_offset: <new_offset>}`

#### Scenario: Push with offset mismatch
- **WHEN** the push offset does not match the server's expected offset for that file
- **THEN** the server SHALL respond with HTTP 409 Conflict including the server's current offset, so the agent can reconcile

#### Scenario: Push with project metadata
- **WHEN** the push payload includes `git_remote` or `project_hint`
- **THEN** the server SHALL resolve or create the project record using the project identity resolution logic

#### Scenario: Push with malformed JSONL lines
- **WHEN** some lines in the pushed data are not valid JSON
- **THEN** the server SHALL skip those lines, continue parsing valid lines, and still acknowledge the full offset (to avoid re-sending bad data)

### Requirement: JSONL parsing
The server SHALL parse both Cursor and Claude Code JSONL formats into a unified message schema.

#### Scenario: Claude Code message
- **WHEN** a JSONL line has `type: "user"` or `type: "assistant"` with `message.content` as a list of content blocks
- **THEN** the server SHALL extract text content, tool use records, hard input detection, and timestamp into the messages table

#### Scenario: Cursor message
- **WHEN** a JSONL line has `role: "user"` or `role: "assistant"` with `message.content` as a list of content parts
- **THEN** the server SHALL extract text content into the messages table

#### Scenario: Tool use extraction
- **WHEN** an assistant message contains `tool_use` content blocks
- **THEN** the server SHALL record the tool name and a summary of tool input (truncated to 200 chars) in the message record

#### Scenario: Hard input detection
- **WHEN** an assistant message contains a `tool_use` block with name `AskUserQuestion` or `AskQuestion`
- **THEN** the server SHALL mark the message with `has_hard_input: true` and extract the question text

#### Scenario: Sub-agent relationship
- **WHEN** a pushed file is classified as `cursor-sub` or `claude-sub` with a `parent_path`
- **THEN** the server SHALL set `parent_session_id` on the session record linking it to the parent session

### Requirement: Project identity resolution
The server SHALL resolve incoming session data to canonical project records using a multi-tier strategy.

#### Scenario: Resolution by git remote
- **WHEN** a sync push includes `git_remote` and a project with that remote already exists
- **THEN** the server SHALL associate the session with that existing project

#### Scenario: New project by git remote
- **WHEN** a sync push includes `git_remote` that matches no existing project
- **THEN** the server SHALL create a new project with that git remote and derive canonical_name from the remote URL

#### Scenario: Resolution by path normalization
- **WHEN** no git remote is provided but `project_hint` matches an existing project's canonical name
- **THEN** the server SHALL associate the session with that project

#### Scenario: Resolution by alias
- **WHEN** neither git remote nor path normalization matches but a `project_aliases` pattern matches the project hint
- **THEN** the server SHALL associate the session with the aliased project

#### Scenario: No match found
- **WHEN** no resolution strategy matches
- **THEN** the server SHALL create a new project using the project_hint as canonical_name

### Requirement: Session state inference
The server SHALL compute session state (executing, waiting_input, idle) from parsed messages, consistent with the logic in the current local session-hub.py.

#### Scenario: Last message is from user
- **WHEN** the most recent non-thinking, non-progress message in a session is from the user and the session was updated within the active threshold
- **THEN** the session state SHALL be `executing`

#### Scenario: Last message is assistant with hard input
- **WHEN** the most recent message is from the assistant with `has_hard_input: true` and the session is within the active threshold
- **THEN** the session state SHALL be `waiting_input` with `input_type: hard`

#### Scenario: Last message is assistant without hard input, within soft threshold
- **WHEN** the most recent message is from the assistant without hard input and the session was updated within the soft threshold (3 minutes)
- **THEN** the session state SHALL be `waiting_input` with `input_type: soft`

#### Scenario: Session inactive
- **WHEN** a session has not been updated within the active threshold (10 minutes)
- **THEN** the session state SHALL be `idle`

### Requirement: Hub sessions API
The server SHALL expose REST endpoints for the Session Hub frontend to query session data.

#### Scenario: List all sessions
- **WHEN** an authenticated request hits `GET /api/sessions`
- **THEN** the server SHALL return all sessions grouped by project, with computed state, identity call signs, sub-agent counts, and sorted by activity (active first, then by last modified)

#### Scenario: Filter by identity
- **WHEN** the request includes query parameter `identity=<name>`
- **THEN** the server SHALL return only sessions belonging to that identity

#### Scenario: Get session messages
- **WHEN** an authenticated request hits `GET /api/session/{session_id}`
- **THEN** the server SHALL return the full message list for that session with role, content, timestamp, and tool metadata

#### Scenario: List projects
- **WHEN** an authenticated request hits `GET /api/projects`
- **THEN** the server SHALL return all projects with session counts per identity, total message counts, and last activity timestamps

### Requirement: Sync status API
The server SHALL expose `GET /sync/status` for monitoring sync health per identity.

#### Scenario: Sync status query
- **WHEN** an admin-authenticated request hits `GET /sync/status`
- **THEN** the server SHALL return per-identity sync stats: files tracked, total bytes synced, last sync time, and any files with stale offsets (not synced in >1 hour while file is known to have grown)

### Requirement: Server deployment
The server SHALL be deployable as a Docker Compose stack with minimal configuration.

#### Scenario: First deployment
- **WHEN** `docker compose up` is run with the required environment variables set
- **THEN** the server SHALL start PostgreSQL, run database migrations, start the FastAPI application, and serve the Hub frontend via Nginx

#### Scenario: Required environment variables
- **WHEN** deploying the server
- **THEN** the following environment variables MUST be set: `DANFLOW_JWT_SECRET` (auto-generated if absent), `DANFLOW_CLAUDE_API_KEY` (for call sign generation)

#### Scenario: Database migrations
- **WHEN** the server starts
- **THEN** it SHALL automatically apply any pending database schema migrations before accepting requests
