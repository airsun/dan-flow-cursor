## 0. Local hub contract alignment (Phase 0)

- [ ] 0.1 Add `GET /api/capabilities` to `session-hub.py` returning `{mode: "local"}`
- [ ] 0.2 Add `GET /api/projects` to `session-hub.py` — group sessions by project name, return `[{name, sessionCount, activeCount, lastActivity}]`
- [ ] 0.3 Add capabilities probe to `session-hub.html` — on load call `/api/capabilities`, store result in global `hubCaps`
- [ ] 0.4 Add conditional rendering skeleton in frontend — guard future server-only UI blocks with `if (hubCaps.mode === 'server')`
- [ ] 0.5 Verify: local hub works exactly as before with the new endpoints and probe

## 1. Project scaffolding

- [ ] 1.1 Create `server/` directory structure: `app/`, `app/routers/`, `app/services/`, `app/migrations/`, `nginx/`
- [ ] 1.2 Create `server/requirements.txt` with FastAPI, uvicorn, SQLAlchemy, asyncpg, alembic, psycopg2-binary, httpx (for Claude API)
- [ ] 1.3 Create `server/Dockerfile` — Python 3.12 slim, install deps, copy app, run uvicorn
- [ ] 1.4 Create `server/docker-compose.yml` with db (postgres:16-alpine), api, nginx services and volume mounts
- [ ] 1.5 Create `server/nginx/nginx.conf` — reverse proxy `/api/` and `/sync/` to api:8000, serve `/` from `../../session-hub.html` (shared frontend), TLS config with cert mount
- [ ] 1.6 Create `agent/` directory with empty `danflow_sync.py`

## 2. Database layer

- [ ] 2.1 Create `server/app/config.py` — Pydantic settings loading DATABASE_URL, DANFLOW_CLAUDE_API_KEY, JWT_SECRET from env
- [ ] 2.2 Create `server/app/database.py` — SQLAlchemy engine, sessionmaker, Base declarative
- [ ] 2.3 Create `server/app/models.py` — ORM models: Identity, Project, ProjectAlias, Session, Message, SyncOffset per design D2 and proposal data model
- [ ] 2.4 Initialize Alembic in `server/app/migrations/`, create initial migration from models
- [ ] 2.5 Create `server/app/main.py` — FastAPI app with lifespan that runs alembic upgrade head on startup

## 3. Identity system

- [ ] 3.1 Create `server/app/auth.py` — `get_current_identity` dependency: extract Bearer token, SHA-256 hash, lookup in identities table, check enabled, return Identity or raise 401/403
- [ ] 3.2 Create `server/app/services/callsign.py` — `generate_callsign_suggestions(name: str) -> list[dict]` calling Claude API with the prompt from design D10, with fallback to deterministic hash-based wordlist
- [ ] 3.3 Create `server/app/routers/identities.py`:
  - `GET /api/setup-status` — returns `{initialized: bool}` (any identities exist?)
  - `POST /api/setup` — first-access flow: accept name, create admin identity, generate token + call signs, return token (plaintext) + call sign suggestions
  - `POST /api/identities` — admin-only: create new identity, return token + call sign suggestions
  - `POST /api/identities/{id}/callsign` — confirm call sign selection
  - `POST /api/identities/{id}/disable` — admin-only, cannot self-disable
  - `POST /api/identities/{id}/enable` — admin-only
  - `GET /api/identities` — admin-only: list all identities with sync stats

## 4. Sync server endpoints

- [ ] 4.1 Create `server/app/services/parser.py` — refactor `parse_cursor_line` and `parse_claude_line` from session-hub.py into stateless functions returning structured dicts with: role, text, timestamp, tool_name, tool_input_summary, has_hard_input, hard_question
- [ ] 4.2 Create `server/app/services/project_resolver.py` — `resolve_project(git_remote, project_hint, source, db) -> Project`: implements the 5-tier resolution from design D7 (git remote exact → git remote new → canonical name match → alias glob → create new)
- [ ] 4.3 Create `server/app/services/state_engine.py` — `compute_session_state(session, messages) -> dict`: port session state inference logic from session-hub.py `_session_state()`, returning state/snippet/phase/input_type
- [ ] 4.4 Create `server/app/routers/sync.py`:
  - `POST /sync/handshake` — accept file list with sizes from identity, return known offsets per file from sync_offsets table
  - `POST /sync/push` — accept file_path, source, project_hint, git_remote, offset, data; validate offset matches expected; parse JSONL lines into messages; resolve project; update session and sync_offset; return ack_offset. Handle 409 on offset mismatch, skip malformed lines
  - `GET /sync/status` — admin-only: per-identity sync health stats

## 5. Hub API endpoints

- [ ] 5.1 Create `server/app/routers/sessions.py`:
  - `GET /api/sessions` — return all sessions grouped by project with computed state, identity call signs, sub-agent counts; support `?identity=` filter; sort active first then by last_modified
  - `GET /api/session/{session_id}` — return full message list for a session
  - `GET /api/projects` — return all projects with per-identity session counts and last activity
- [ ] 5.2 Create `server/app/routers/health.py` — `GET /health` returning db status and version (unauthenticated)
- [ ] 5.3 Wire all routers into `main.py` with appropriate prefixes and auth dependencies

## 6. Sync agent

- [ ] 6.1 Implement file discovery in `agent/danflow_sync.py` — scan cursor and claude base directories for *.jsonl, classify source type, detect subagent files and parent relationships
- [ ] 6.2 Implement project metadata extraction — resolve git remote URL via `git -C <dir> remote get-url origin`, compute project_hint by stripping user-specific path prefixes
- [ ] 6.3 Implement config loading from `~/.dan-flow/config.json` (stdlib json, no YAML dep)
- [ ] 6.4 Implement state persistence — load/save `~/.dan-flow/sync-state.json` with per-file offsets, graceful handling of missing/corrupt state
- [ ] 6.5 Implement handshake — POST file list + local sizes to `/sync/handshake`, receive server offsets, compute deltas
- [ ] 6.6 Implement incremental push — read new bytes from each changed file, POST to `/sync/push` in chunks of batch_size, advance local offset on ack
- [ ] 6.7 Implement main loop — poll interval scanning, detect new files, push changes, handle sleep/wake via time gap detection triggering re-handshake
- [ ] 6.8 Implement network resilience — exponential backoff on 5xx/network errors, stop on 401 with auth error log, handle 409 by trusting server offset
- [ ] 6.9 Implement signal handling — SIGTERM/SIGINT save state and exit cleanly
- [ ] 6.10 Create `agent/launchd/com.danflow.sync.plist` — macOS launchd configuration for auto-start on login

## 7. Session Hub frontend

- [ ] 7.1 Verify `session-hub.html` (shared frontend) works when served by Nginx against the FastAPI backend — capabilities probe returns server mode, core workbench renders
- [ ] 7.2 Implement token entry flow — on page load check localStorage for token, if missing show minimal token input overlay, on submit validate via `/api/sessions` call, store on success
- [ ] 7.3 Implement setup flow — on 401 with `{initialized: false}` from setup-status, show setup overlay: name input → submit → display token + call sign selection → confirm → enter hub
- [ ] 7.4 Implement session list sidebar — fetch `/api/sessions` every 2s, render session items with status dot, project name, identity emoji badge, sub-agent count; selected state; collapsible toggle
- [ ] 7.5 Implement identity filter — dropdown in header populated from identities in session data, filter sessions on change
- [ ] 7.6 Implement session cards in main panel — project-grouped cards with identity call signs, status indicators (green pulse/amber pulse/gray), needs-input sorting, sub-agent dot matrix
- [ ] 7.7 Implement conversation view — on card click load `/api/session/{id}`, render messages with role-based styling, markdown rendering, code highlighting, collapsible thinking blocks
- [ ] 7.8 Implement admin panel — slide-in panel accessible via settings icon (admin only): identity list with call signs and status, create/enable/disable actions, sync health per identity, new identity creation with token display and call sign picker

## 8. Integration testing

- [ ] 8.1 Test end-to-end: start docker compose, create first identity via setup flow, verify token works for API access
- [ ] 8.2 Test sync: run agent against live server, push sample JSONL data, verify sessions appear in Hub API
- [ ] 8.3 Test multi-device: simulate two identities pushing sessions for the same project (by git remote), verify project aggregation in API response
- [ ] 8.4 Test resilience: stop server mid-sync, restart, verify agent catches up via handshake without data loss
- [ ] 8.5 Test identity management: create second identity, verify token works, disable it, verify 403, re-enable, verify access restored
