#!/usr/bin/env python3
"""Dan Flow Sync Agent — pushes local JSONL sessions to remote server.

Zero external dependencies. Uses only Python 3.10+ standard library.
Config: ~/.dan-flow/config.json
State:  ~/.dan-flow/sync-state.json
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".dan-flow"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = CONFIG_DIR / "sync-state.json"

DEFAULT_SOURCES = [
    {"type": "cursor", "path": str(Path.home() / ".cursor" / "projects")},
    {"type": "claude", "path": str(Path.home() / ".claude" / "projects")},
]

log = logging.getLogger("danflow-sync")


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config not found: %s", CONFIG_FILE)
        log.error("Create it with: {\"server_url\": \"https://...\", \"token\": \"df_...\"}")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    cfg.setdefault("poll_interval", 5)
    cfg.setdefault("batch_size", 65536)
    cfg.setdefault("device_name", os.uname().nodename)
    cfg.setdefault("sources", DEFAULT_SOURCES)
    return cfg


# ── State persistence ───────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt state file, starting fresh")
    return {"offsets": {}}


def save_state(state: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f)
    tmp.replace(STATE_FILE)


# ── File discovery ──────────────────────────────────────────────

def discover_files(sources: list[dict]) -> list[dict]:
    found = []
    for src in sources:
        base = Path(src["path"]).expanduser()
        stype = src["type"]
        if not base.exists():
            continue

        if stype == "cursor":
            for proj_dir in base.iterdir():
                if not proj_dir.is_dir():
                    continue
                at_dir = proj_dir / "agent-transcripts"
                if not at_dir.exists():
                    continue
                for sess_dir in at_dir.iterdir():
                    if not sess_dir.is_dir():
                        continue
                    main_file = sess_dir / (sess_dir.name + ".jsonl")
                    if main_file.exists():
                        found.append(_file_entry(main_file, "cursor", proj_dir, None))
                    for sub in sess_dir.glob("subagents/*.jsonl"):
                        parent = str(main_file) if main_file.exists() else None
                        found.append(_file_entry(sub, "cursor-sub", proj_dir, parent))

        elif stype == "claude":
            for proj_dir in base.iterdir():
                if not proj_dir.is_dir():
                    continue
                for p in proj_dir.glob("*.jsonl"):
                    found.append(_file_entry(p, "claude", proj_dir, None))
                for p in proj_dir.glob("*/subagents/agent-*.jsonl"):
                    parent_name = p.parent.parent.name
                    parent_file = proj_dir / (parent_name + ".jsonl")
                    parent = str(parent_file) if parent_file.exists() else None
                    found.append(_file_entry(p, "claude-sub", proj_dir, parent))

    return found


def _file_entry(path: Path, source: str, proj_dir: Path, parent_path: str | None) -> dict:
    return {
        "path": str(path),
        "source": source,
        "size": path.stat().st_size,
        "project_dir": str(proj_dir),
        "parent_path": parent_path,
    }


# ── Project metadata ────────────────────────────────────────────

_git_cache: dict[str, str | None] = {}


def get_git_remote(proj_dir: str) -> str | None:
    if proj_dir in _git_cache:
        return _git_cache[proj_dir]
    try:
        result = subprocess.run(
            ["git", "-C", proj_dir, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=3,
        )
        remote = result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        remote = None
    _git_cache[proj_dir] = remote
    return remote


def get_project_hint(proj_dir: str) -> str:
    raw = Path(proj_dir).name
    for prefix in ("Users-gunegg-Works-", "Users-gunegg-", "-Users-gunegg-Works-", "-Users-gunegg-"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return raw.replace("-", "/", 2).replace("-", " ") if "/" not in raw else raw


# ── HTTP client ─────────────────────────────────────────────────

class SyncClient:
    def __init__(self, server_url: str, token: str):
        parsed = urllib.parse.urlparse(server_url)
        self.scheme = parsed.scheme
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or (443 if self.scheme == "https" else 80)
        self.base_path = parsed.path.rstrip("/")
        self.token = token
        self._backoff = 1

    def _conn(self):
        if self.scheme == "https":
            import ssl
            ctx = ssl.create_default_context()
            return http.client.HTTPSConnection(self.host, self.port, context=ctx, timeout=30)
        return http.client.HTTPConnection(self.host, self.port, timeout=30)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        url = self.base_path + path
        data = json.dumps(body).encode() if body else None

        while True:
            try:
                conn = self._conn()
                conn.request(method, url, body=data, headers=self._headers())
                resp = conn.getresponse()
                status = resp.status
                raw = resp.read().decode()
                conn.close()

                self._backoff = 1

                if status == 401:
                    log.error("Authentication failed (401). Check your token.")
                    sys.exit(1)

                try:
                    return status, json.loads(raw)
                except json.JSONDecodeError:
                    return status, {"raw": raw}

            except (OSError, http.client.HTTPException) as e:
                log.warning("Network error: %s, retry in %ds", e, self._backoff)
                time.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, 60)

    def handshake(self, files: list[dict]) -> dict:
        payload = {"files": [{"path": f["path"], "size": f["size"], "source": f["source"]} for f in files]}
        status, data = self.request("POST", "/sync/handshake", payload)
        if status != 200:
            log.error("Handshake failed: %d %s", status, data)
            return {"offsets": {}}
        return data

    def push(self, file_path: str, source: str, project_hint: str | None,
             git_remote: str | None, parent_path: str | None,
             offset: int, data: str) -> dict | None:
        payload = {
            "file_path": file_path,
            "source": source,
            "project_hint": project_hint,
            "git_remote": git_remote,
            "parent_path": parent_path,
            "offset": offset,
            "data": data,
        }
        status, resp = self.request("POST", "/sync/push", payload)
        if status == 200:
            return resp
        elif status == 409:
            server_offset = resp.get("detail", {}).get("serverOffset", 0)
            log.warning("Offset mismatch for %s, trusting server offset %d", file_path, server_offset)
            return {"ack_offset": server_offset, "conflict": True}
        else:
            log.error("Push failed: %d %s", status, resp)
            return None


# ── Main sync loop ──────────────────────────────────────────────

class SyncAgent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = SyncClient(cfg["server_url"], cfg["token"])
        self.state = load_state()
        self.running = True
        self.last_poll_time = time.time()

    def run(self):
        log.info("Dan Flow Sync Agent starting")
        log.info("  Device: %s", self.cfg["device_name"])
        log.info("  Server: %s", self.cfg["server_url"])

        files = discover_files(self.cfg["sources"])
        log.info("  Tracking %d files", len(files))

        self._do_handshake(files)

        while self.running:
            now = time.time()
            if now - self.last_poll_time > 300:
                log.info("Detected time gap (sleep/wake?), re-handshaking")
                files = discover_files(self.cfg["sources"])
                self._do_handshake(files)

            self.last_poll_time = now
            files = discover_files(self.cfg["sources"])
            pushed = 0

            for f in files:
                if not self.running:
                    break
                local_offset = self.state["offsets"].get(f["path"], 0)
                if f["size"] <= local_offset:
                    continue

                git_remote = get_git_remote(f["project_dir"])
                project_hint = get_project_hint(f["project_dir"])

                try:
                    with open(f["path"], "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(local_offset)
                        remaining = f["size"] - local_offset
                        batch = self.cfg["batch_size"]

                        while remaining > 0 and self.running:
                            chunk = fh.read(min(batch, remaining))
                            if not chunk:
                                break

                            result = self.client.push(
                                f["path"], f["source"], project_hint,
                                git_remote, f.get("parent_path"),
                                local_offset, chunk,
                            )
                            if result and "ack_offset" in result:
                                local_offset = result["ack_offset"]
                                self.state["offsets"][f["path"]] = local_offset
                                remaining = f["size"] - local_offset
                                pushed += 1
                            else:
                                break
                except OSError as e:
                    log.warning("Cannot read %s: %s", f["path"], e)

            if pushed > 0:
                save_state(self.state)
                log.debug("Pushed %d chunks", pushed)

            time.sleep(self.cfg["poll_interval"])

    def _do_handshake(self, files: list[dict]):
        resp = self.client.handshake(files)
        server_offsets = resp.get("offsets", {})
        for path, server_off in server_offsets.items():
            local_off = self.state["offsets"].get(path, 0)
            if server_off < local_off:
                log.info("Server behind for %s (%d < %d), trusting server", path, server_off, local_off)
            self.state["offsets"][path] = server_off
        save_state(self.state)

    def stop(self):
        self.running = False
        save_state(self.state)
        log.info("Agent stopped, state saved")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    cfg = load_config()
    agent = SyncAgent(cfg)

    def sig_handler(signum, frame):
        log.info("Signal %d received, shutting down...", signum)
        agent.stop()

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    try:
        agent.run()
    except KeyboardInterrupt:
        agent.stop()


if __name__ == "__main__":
    main()
