# Multi-Device Sync + Server-Side Session Hub

## Problem

Dan Flow Cursor's Session Hub runs locally, tied to one machine. Reality: multiple devices (MBP-office, Mac-home, etc.) all generate Cursor and Claude Code sessions. No single device sees the full picture. Closing a laptop kills the hub. The local-only architecture blocks the path to Meta-Intelligence (cross-project insights, pattern detection, strategic briefing).

## Proposal

Move Session Hub to a server. Build a multi-device sync system that continuously aggregates JSONL session data from all devices into a central store. The server runs 24/7, devices come and go freely.

This is the foundation layer. Meta-Intelligence (Phase 2) will build on the unified session store and server-side processing pipeline established here.

## Architecture

### Three components

1. **Sync Agent** (local, per-device) — lightweight Python daemon that watches `~/.cursor/projects/` and `~/.claude/projects/` for JSONL changes and uploads incremental data to the server. Survives sleep/restart via persisted offset state. One agent per device.

2. **dan-flow-server** (server, FastAPI + PostgreSQL + Docker) — receives sync data, parses JSONL into structured session/message records, serves the Hub API. Runs as Docker Compose stack.

3. **Session Hub Web** (server, static SPA served by Nginx) — upgraded version of current `session-hub.html` with multi-device unified view, project aggregation, device filtering, and identity-aware display.

### Sync protocol

JSONL files are append-only. This makes sync trivial:

- **Handshake**: Agent sends file list + local sizes. Server responds with known offsets per file. Delta = what to upload.
- **Push**: Agent reads bytes from known offset to current size, POSTs to server. Server appends, parses, acks.
- **Resume**: On restart, agent loads persisted state, handshakes, catches up. No data loss possible — append-only means no conflicts, no merge, no rebase.

Estimated sync volume: ~2 MB/day per active device.

### Project identity resolution

Same project on different devices needs to be recognized as one:

1. **git remote URL** (highest confidence) — if project dir has `.git` with a remote, use the remote URL as canonical identifier.
2. **Path normalization** — strip user-specific prefixes (`Users-gunegg-Works-`, `-Users-gunegg-Works-`) to extract project name. Cursor and Claude Code use slightly different prefix patterns but map to the same project.
3. **Manual aliases** — server-side config for edge cases where automated resolution fails.

### Identity system

No user accounts. No passwords. Token-based identity:

- **First access** — server detects zero identities, enters setup flow. User provides an identity name → server generates a token (shown once, user must save it) and a call sign. This identity becomes admin.
- **Call sign** — LLM-generated emoji + short English phrase with a perceptible association to the identity name. User picks from 3 suggestions or customizes. Examples: "gunegg-mbp" → "🥚 Egg Cannon". Stored permanently with the identity.
- **Name collision** — if identity name already exists, server suggests alternatives and blocks creation until a unique name is provided.
- **Token usage** — single token serves all purposes: browser access (stored in localStorage), sync agent auth (stored in config file), API calls (Bearer header). One token = one identity.
- **Admin powers** — first identity is admin. Admin can: create new identities (generates token + call sign), enable/disable any identity, view sync status per device.
- **No login page** — browser checks localStorage for token. Has it → in. Doesn't have it → paste token → in.

### Data model (PostgreSQL)

```
identities
  id (uuid), name (unique), token_hash, call_sign, is_admin, enabled, created_at

projects
  id (uuid), canonical_name, git_remote (nullable, unique), created_at

project_aliases
  project_id (FK), pattern, source (cursor/claude)

sessions
  id (uuid), identity_id (FK), project_id (FK), source (cursor/claude/cursor-sub/claude-sub),
  file_path, parent_session_id (nullable FK), first_seen, last_updated, msg_count

messages
  session_id (FK), seq, role, content, timestamp, tool_name, tool_input_summary,
  has_hard_input, hard_question

sync_offsets
  identity_id (FK), file_path, offset, synced_at
```

### Hub unified view

The server-side Hub displays all sessions across all devices in a unified view:

- **Project aggregation** — sessions grouped by project regardless of which device they came from. Each project card shows contributing identities with their call signs.
- **Identity filtering** — filter by device/identity to see one machine's activity.
- **Timeline** — cross-device chronological view of all session activity.
- **Status inference** — same executing/waiting_input/idle logic as current hub, applied server-side during message parsing.
- **Sub-agent hierarchy** — parent/child relationships preserved per-device.

## Non-goals (this change)

- Meta-Intelligence engine (analysis, briefs, sparks) — Phase 2
- Bidirectional shuttle links between sessions — Phase 2
- Interactive Meta chat — Phase 2
- Cross-session knowledge extraction — Phase 2
- Push notifications — future

## Tech stack

- **Server**: Python 3.12+, FastAPI, PostgreSQL 16, Nginx, Docker Compose
- **Sync Agent**: Python 3.10+, zero external deps (stdlib only: http.client, json, pathlib, threading)
- **Frontend**: Single HTML file (current style), vanilla JS, CSS — no build step
- **LLM for call signs**: Claude API (called once per identity creation)

## Risks

- **Privacy**: JSONL contains full AI conversations including code and potentially secrets. Mitigation: TLS for transport, server should be self-hosted or trusted VPS, no third-party services.
- **Storage growth**: 101 MB current, ~2 MB/day. At this rate, years before it matters. PostgreSQL handles this trivially.
- **Sync agent reliability**: Must handle network interruptions, sleep/wake, and file system edge cases gracefully. Mitigation: append-only protocol means correctness doesn't depend on continuous operation.
