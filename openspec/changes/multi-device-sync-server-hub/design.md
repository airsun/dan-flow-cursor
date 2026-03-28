## Context

Dan Flow Cursor currently runs as a local Python HTTP server (`session-hub.py`) that polls JSONL transcript files from `~/.cursor/projects/` and `~/.claude/projects/`, infers session state, and serves a web dashboard at `localhost:7890`. This works for single-device use but has fundamental limitations: closing the laptop kills the hub, and sessions from other devices are invisible. The codebase is 4 files totaling ~65KB — zero external dependencies, pure Python + single HTML file.

The user works across multiple macOS devices, has 48+ projects and 323 JSONL files (136 MB), and needs a unified view of all AI interactions regardless of which machine generated them. This change establishes the server-side foundation that future Meta-Intelligence features will build upon.

**Key architectural constraint**: The local hub is not a legacy artifact to be replaced. It is a first-class experience that always works — offline, serverless, zero-config. The server is an optional superset. Users choose their deployment mode; both must deliver a consistent session reading and operation experience. The server adds multi-device aggregation and administration, nothing else changes in the core UX.

## Goals / Non-Goals

**Goals:**
- Dual-mode architecture: local hub (`python3 session-hub.py`) and server hub (`docker compose up`) with consistent core UX
- Multi-device JSONL sync with append-only incremental protocol
- Server-side session parsing, project resolution, and state inference
- Unified frontend: single `session-hub.html` serves both modes via capabilities probe
- Token-based identity system with LLM-generated call signs (server mode only)
- Deployable as a single `docker compose up` command

**Non-Goals:**
- Meta-Intelligence engine (LLM analysis, briefs, sparks, cross-project pattern detection) — Phase 2
- Bidirectional shuttle links between sessions — Phase 2
- Interactive Meta chat — Phase 2
- Real-time WebSocket push (polling is sufficient at 2s interval for current scale)
- Mobile or responsive layout optimization
- Multi-tenant user management

## Decisions

### D1: Monorepo structure with shared frontend

The server (FastAPI app) and sync agent are separate deployables but live in the same repository. The frontend is a single `session-hub.html` at the repo root — the same file serves both local mode (via `session-hub.py`) and server mode (via Nginx).

```
dan-flow-cursor/
├── session-hub.py              # Local hub backend (always works, zero deps)
├── session-hub.html            # THE frontend — serves both modes
├── server/                     # Docker-deployable server
│   ├── app/                    # FastAPI application
│   │   ├── main.py             # App entrypoint, lifespan, middleware
│   │   ├── config.py           # Settings from env vars
│   │   ├── database.py         # SQLAlchemy engine + session factory
│   │   ├── models.py           # SQLAlchemy ORM models
│   │   ├── auth.py             # Token auth dependency
│   │   ├── routers/
│   │   │   ├── sync.py         # /sync/handshake, /sync/push, /sync/status
│   │   │   ├── sessions.py     # /api/sessions, /api/session/{id}, /api/projects
│   │   │   ├── identities.py   # /api/identities, setup flow
│   │   │   └── health.py       # /health
│   │   ├── services/
│   │   │   ├── parser.py       # JSONL parsing (Cursor + Claude formats)
│   │   │   ├── project_resolver.py  # Multi-tier project identity resolution
│   │   │   ├── state_engine.py      # Session state inference
│   │   │   └── callsign.py         # LLM call sign generation
│   │   └── migrations/        # Alembic migrations
│   ├── nginx/
│   │   └── nginx.conf          # Reverse proxy + static, mounts ../session-hub.html
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── requirements.txt
├── agent/                      # Sync agent (runs on each device)
│   ├── danflow_sync.py         # Single-file sync agent (stdlib only)
│   └── launchd/
│       └── com.danflow.sync.plist  # macOS launchd config
└── README.md
```

**Why shared frontend**: The local hub and server hub must deliver identical session reading/operation experience. Maintaining two frontends leads to drift. One file, capabilities-driven.

**Why session-hub.html at root**: The local hub (`session-hub.py`) serves it from the same directory. The server's Nginx mounts it from the repo root or copies it at build time. Single source of truth.

### D2: SQLAlchemy + Alembic for database layer

Using SQLAlchemy ORM with Alembic migrations rather than raw SQL or a lighter ORM.

**Why over raw SQL**: The data model has foreign keys, joins (sessions→projects→identities), and will grow with Phase 2 (annotations, knowledge store). ORM makes this manageable.

**Why over Tortoise/Peewee**: SQLAlchemy is the FastAPI ecosystem standard, best documented, and handles async via `asyncpg` if needed later.

**Migration strategy**: Alembic auto-generates migrations from model changes. Server runs `alembic upgrade head` on startup before accepting requests.

### D3: Sync agent as single-file stdlib-only Python, independent of local hub

The sync agent uses only Python standard library (`http.client`, `json`, `pathlib`, `threading`, `hashlib`, `signal`, `time`). No pip install needed.

**Independence**: The sync agent and local hub are completely independent processes. Both read local JSONL files but do not communicate with each other. The sync agent pushes data to the remote server; the local hub serves it locally. Either can run without the other. If the remote server or sync agent is down, the local hub is unaffected.

**Why no dependencies**: The agent runs on user machines that may have varying Python environments. Zero deps means `python3 danflow_sync.py` works everywhere.

**Config format**: `~/.dan-flow/config.json` (stdlib json, no YAML dep).

```json
{
  "server_url": "https://your-server.example.com",
  "token": "df_xxxxxxxx",
  "device_name": "MBP-office",
  "poll_interval": 5,
  "batch_size": 65536,
  "sources": [
    {"type": "cursor", "path": "~/.cursor/projects"},
    {"type": "claude", "path": "~/.claude/projects"}
  ]
}
```

### D4: Polling over fswatch/watchdog for file change detection

The sync agent uses time-based polling (default 5s) rather than filesystem event APIs.

**Why over fswatch/kqueue/watchdog**: Filesystem event libraries are either platform-specific or require pip packages. Polling at 5s intervals across ~300 files is negligible CPU cost. The current `session-hub.py` already uses 2s polling successfully. fswatch can be added later as an optimization without protocol changes.

### D5: Token auth with SHA-256 hashing, no JWT for API

API authentication uses raw token comparison (hash lookup) rather than JWT.

**Why no JWT for API calls**: JWT is useful for distributed systems where services need to verify tokens without a database call. This is a single-server system — every request already hits the database for session data. Looking up `token_hash` in the identities table adds zero meaningful overhead. JWT would add complexity (expiry, refresh, secret rotation) for no benefit.

**Token format**: `df_` + 40 chars from `secrets.token_urlsafe(30)`. The `df_` prefix makes tokens recognizable in config files and logs. SHA-256 hash stored in DB.

**Browser flow**: Token stored in `localStorage` under key `danflow_token`. Included as `Authorization: Bearer df_xxx` on all fetch requests. On 401, frontend shows token input. No cookies, no sessions.

### D6: JSONL parsing reuses existing logic from session-hub.py

The server's `parser.py` adapts the parsing functions from the current `session-hub.py` (`parse_cursor_line`, `parse_claude_line`, `is_thinking_content`) rather than writing from scratch.

**Why**: These parsers handle the real-world quirks of both JSONL formats. They've been battle-tested against the user's actual data (323 files, both Cursor and Claude). Rewriting risks regressions.

**Adaptation**: The parsers are refactored into stateless functions that return structured dicts. The server adds: tool use extraction, hard input detection with question text, and timestamp normalization.

### D7: Project resolution executed on push, cached in DB

Project identity resolution runs during `/sync/push` processing, not as a batch job.

**Resolution order**:
1. `git_remote` → exact match on `projects.git_remote`
2. `git_remote` → new project (extract name from remote URL: `git@github.com:user/repo.git` → `repo`)
3. `project_hint` → case-insensitive match on `projects.canonical_name`
4. `project_hint` → glob match against `project_aliases.pattern`
5. Fallback → create new project with `project_hint` as `canonical_name`

Once a session is associated with a project, the association is permanent. Project merging (recognizing two projects are actually one) is a manual admin action in Phase 2.

### D8: Unified frontend with capabilities probe

One `session-hub.html` serves both local and server mode. On page load, it calls `GET /api/capabilities` to detect the backend:

```
Local returns:   {mode: "local"}
Server returns:  {mode: "server", identity: {name, callSign, isAdmin}}
```

**Progressive enhancement by field presence**: The frontend never uses if/else branching on mode. Instead, it renders based on what the API response contains. If a session has an `identity` field, show the callsign badge. If capabilities has `isAdmin: true`, show the admin panel entry. If neither exists, the core experience is unchanged.

**Core experience (identical in both modes):**
- Workbench card grid with status dots
- Needs-input zone with hard/soft distinction
- Sub-agent dot matrix and overlay
- Conversation view with markdown rendering
- Sidebar with collapse and project navigation
- Tab filtering and dismiss

**Server-only features (conditionally shown):**
- Identity/device filter dropdown in header
- Callsign emoji badges on session cards
- Admin panel (slide-in): identity CRUD, sync health, device status
- Setup flow and token entry as modal overlays
- Token auth header on all fetch requests (when `danflow_token` exists in localStorage)

**Why no build step**: The file is ~45KB and fully functional. Adding React/Vue/Vite would increase complexity for a single-user tool. The server-only features add ~200 lines of JS.

**Auth in frontend**: If `localStorage.danflow_token` exists, all fetch calls include `Authorization: Bearer <token>`. On 401, show token input overlay. In local mode, no token exists, no header sent, local backend doesn't check.

### D9: Docker Compose with 3 services

```yaml
services:
  db:
    image: postgres:16-alpine
    volumes: [pgdata:/var/lib/postgresql/data]
    environment:
      POSTGRES_DB: danflow
      POSTGRES_USER: danflow
      POSTGRES_PASSWORD: ${DANFLOW_DB_PASSWORD}

  api:
    build: .
    depends_on: [db]
    environment:
      DATABASE_URL: postgresql://danflow:${DANFLOW_DB_PASSWORD}@db:5432/danflow
      DANFLOW_CLAUDE_API_KEY: ${DANFLOW_CLAUDE_API_KEY}
    expose: ["8000"]

  nginx:
    image: nginx:alpine
    ports: ["443:443", "80:80"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf
      - ./frontend:/usr/share/nginx/html
      - ./certs:/etc/nginx/certs  # user provides TLS certs
    depends_on: [api]
```

**Why Nginx in front**: Serves static frontend without hitting Python. Handles TLS termination. Simple rate limiting. The API is upstream at `http://api:8000`.

**TLS**: User provides their own certs (Let's Encrypt or self-signed) mounted at `./certs/`. Nginx config expects `cert.pem` and `key.pem`.

### D10: Call sign generation prompt design

The Claude API call for call sign generation uses a focused prompt that emphasizes **associative connection** to the identity name:

```
Generate 3 call signs for the identity "{name}".

Each call sign: exactly 1 emoji + 1-3 English words (max 30 chars total).

Requirements:
- The call sign MUST have a perceptible link to the name
  (sound, meaning, visual pun, word decomposition, cultural reference)
- It should be memorable and fun
- No generic/random combinations

Examples of good associations:
- "gunegg" → 🥚 Egg Cannon (word decomposition: gun + egg)
- "nightowl-dev" → 🦉 Midnight Code (semantic: night owl → midnight)
- "storm-mac" → ⛈️ Thunder Drive (semantic: storm → thunder)

Return exactly 3 options as JSON array:
[{"emoji": "🥚", "words": "Egg Cannon"}, ...]
```

The prompt is called once per identity creation. Cost: ~$0.001 per call. Fallback if API unavailable: deterministic hash-based selection from a built-in word list (degraded quality but functional).

### D11: API contract — local is a strict subset of server

The local hub's API endpoints are a strict subset of the server's. Response shapes are compatible: the server may include additional fields (identity, device, gitRemote) that the local hub omits. The frontend handles missing fields gracefully via progressive enhancement.

**Shared endpoints (local + server):**

| Endpoint | Local | Server |
|----------|-------|--------|
| `GET /api/capabilities` | `{mode: "local"}` | `{mode: "server", identity: {...}, isAdmin: bool}` |
| `GET /api/sessions` | Sessions from local JSONL | Sessions from all devices, with identity/device fields |
| `GET /api/session/:key` | Full message list | Same, with identity metadata |
| `GET /api/projects` | Aggregated from sessions (group by project name) | DB-backed with git remotes, aliases, per-identity counts |
| `POST /api/dismiss/:key` | In-memory dismiss | DB-persisted dismiss |

**Server-only endpoints:**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/identities` | Admin: list identities with sync stats |
| `POST /api/setup` | First-access identity creation |
| `POST /api/identities` | Admin: create new identity |
| `POST /sync/handshake` | Sync agent: file offset negotiation |
| `POST /sync/push` | Sync agent: incremental data push |
| `GET /sync/status` | Admin: per-identity sync health |
| `GET /health` | Unauthenticated health check |

**Response shape compatibility**: For `GET /api/sessions`, both modes return the same base fields (`id`, `key`, `source`, `project`, `state`, `snippet`, `inputType`, `children`, `subCount`, `turns`, `msgCount`, `ageSec`, `active`, `lastModified`). Server adds optional fields: `identity` (object with `name`, `callSign`), `device` (string). Frontend shows these when present, ignores when absent.

**`/api/projects` in local mode**: The local hub derives projects by grouping sessions on the `project` string field. Returns `[{name, sessionCount, activeCount, lastActivity}]`. Server returns the same base shape plus `gitRemote`, `aliases`, `identities[]`. No DB needed locally — it's a computed view over existing session data.

## Risks / Trade-offs

**[Privacy: conversations transit to server]** → Require HTTPS (TLS). Document that users should use self-hosted or trusted infrastructure. No data leaves the server to third parties (except the one Claude API call per identity for call sign generation, which sends only the identity name).

**[Sync agent adds a background process to user machines]** → Keep it extremely lightweight (no deps, <10MB RSS, <1% CPU). Provide launchd plist for macOS so it's managed by the OS, not manually. Clear uninstall instructions.

**[PostgreSQL adds operational complexity vs SQLite]** → PostgreSQL is necessary for Phase 2 (concurrent writes from Meta-Intelligence analysis pipeline). Starting with it avoids a migration later. Docker Compose abstracts the ops burden.

**[Single HTML file serves two modes — complexity risk]** → Capabilities probe keeps the branching minimal. Server-only features are additive blocks guarded by `if (caps.mode === 'server')`, not interwoven with core logic. Current file is ~45KB; server features add ~15KB. If it passes ~80KB, extract JS into a separate file. No build step needed.

**[Polling at 2s creates N API calls per open browser tab]** → At current scale (single user, 1-2 tabs), this is negligible. If needed later, upgrade to Server-Sent Events (SSE) for push updates. The API response is small (~5KB for session list).

## Open Questions

1. **Domain / hosting**: Where will the server be deployed? This affects TLS setup (Let's Encrypt vs self-signed), network accessibility, and data residency.

2. **Backup strategy**: PostgreSQL data should be backed up. `pg_dump` on cron? Volume snapshots? Deferred to deployment time.

3. **Sync agent for Linux/Windows**: Current design targets macOS (launchd). If other OS devices are used, systemd unit or Windows service configs would be needed. Defer until needed.
