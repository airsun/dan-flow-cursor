#!/usr/bin/env python3
"""Session Hub - Web dashboard for real-time AI session monitoring"""

from __future__ import annotations
import os, json, time, sys, threading, re
from pathlib import Path
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote
from typing import Optional, Dict

PORT = 7890
CURSOR_BASE = Path.home() / ".cursor" / "projects"
CLAUDE_BASE = Path.home() / ".claude" / "projects"
ACTIVE_THRESHOLD = 600
POLL_INTERVAL = 2.0

sessions_lock = threading.Lock()
sessions_data: Dict[str, dict] = {}

# ═══════════════════════════════════════════════════════════════
#  Session Discovery & Parsing
# ═══════════════════════════════════════════════════════════════

def discover_files():
    found = []
    if CURSOR_BASE.exists():
        for p in CURSOR_BASE.glob("*/agent-transcripts/**/*.jsonl"):
            found.append(("cursor", p))
    if CLAUDE_BASE.exists():
        for proj in CLAUDE_BASE.iterdir():
            if not proj.is_dir():
                continue
            for p in proj.glob("*.jsonl"):
                found.append(("claude", p))
            for p in proj.glob("*/subagents/agent-*.jsonl"):
                found.append(("claude-sub", p))
    return found


def session_id(path: Path, source: str) -> str:
    if source == "cursor":
        return path.stem
    elif source == "claude-sub":
        return f"{path.parent.parent.name[:8]}>{path.stem[:12]}"
    return path.stem


def project_name(path: Path, source: str) -> str:
    if source == "cursor":
        raw = path.parent.parent.parent.name
    else:
        raw = path.parent.name
    for prefix in ("Users-gunegg-Works-", "Users-gunegg-", "-Users-gunegg-Works-", "-Users-gunegg-"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return raw.replace("-", "/", 2).replace("-", " ") if "/" not in raw else raw


def is_thinking_content(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 15:
        return False
    if re.search(r'^#{1,3}\s', t, re.MULTILINE):
        return False
    if re.match(r'^[\u4e00-\u9fff]', t):
        return False
    if t.startswith('```') or t.startswith('|'):
        return False
    starts = [
        'The user', 'Let me', "I need", "I'll", "I can", "I should",
        "Now I", "Looking at", "This is", "OK,", "Alright", "Good",
        "Excellent", "Wait", "Actually", "Hmm", "Interesting", "From",
        "I have", "I see", "I want", "I realize", "Now let", "Great",
        "Perfect", "So the", "Based on", "Given", "I already",
        "The watcher", "The key", "Both", "For the", "Now the",
        "Key insight", "This means", "Since", "My plan",
    ]
    for s in starts:
        if t.startswith(s):
            return True
    return False


def parse_cursor_line(raw: str) -> dict | None:
    obj = json.loads(raw)
    role = obj.get("role", "")
    parts = obj.get("message", {}).get("content", [])
    text = ""
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            text = p["text"]
            break
    if not text:
        return None
    if role == "assistant":
        role = "thinking" if is_thinking_content(text) else "assistant"
    return {"role": role, "text": text, "ts": None}


def parse_claude_line(raw: str) -> dict | None:
    obj = json.loads(raw)
    t = obj.get("type", "")
    ts = obj.get("timestamp", "")
    if t in ("user", "assistant"):
        msg = obj.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                c.get("text", "") for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
        else:
            text = str(content)
        if not text:
            return None
        role = t
        if role == "assistant":
            role = "thinking" if is_thinking_content(text) else "assistant"
        return {"role": role, "text": text, "ts": ts}
    elif t == "progress":
        data = obj.get("data", {})
        desc = data.get("hookName", data.get("type", t))
        return {"role": "progress", "text": f"[{desc}]", "ts": ts}
    return None


def update_session(sess: dict, path: Path, source: str):
    try:
        mtime = os.path.getmtime(path)
        size = os.path.getsize(path)
        if size <= sess["file_pos"] and mtime <= sess["last_modified"]:
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(sess["file_pos"])
            new_data = f.read()
            sess["file_pos"] = f.tell()
        sess["last_modified"] = mtime
        for line in new_data.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = (parse_cursor_line(line) if source == "cursor"
                          else parse_claude_line(line))
                if parsed:
                    sess["messages"].append(parsed)
            except (json.JSONDecodeError, KeyError):
                pass
    except Exception:
        pass


def watcher_loop():
    while True:
        try:
            found = discover_files()
            with sessions_lock:
                for source, path in found:
                    key = str(path)
                    if key not in sessions_data:
                        sessions_data[key] = {
                            "id": session_id(path, source),
                            "source": source,
                            "project": project_name(path, source),
                            "messages": [],
                            "file_pos": 0,
                            "last_modified": 0,
                            "path": str(path),
                        }
                    update_session(sessions_data[key], path, source)
        except Exception:
            pass
        time.sleep(POLL_INTERVAL)


# ═══════════════════════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════════════════════

def _clean_snippet(text: str, max_len: int = 80) -> str:
    t = text
    idx = t.find("</cursor_commands>")
    if idx > -1:
        t = t[idx + 18:]
    for tag in ("user_query", "system_reminder", "attached_files",
                "open_and_recently_viewed_files", "agent_transcripts",
                "user_info", "rules", "agent_skills"):
        t = re.sub(rf"<{tag}>[\s\S]*?</{tag}>", "", t)
    t = t.strip().replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    return (t[:max_len] + "…") if len(t) > max_len else t


def _session_state(messages: list, active: bool) -> tuple[str, str, str | None]:
    """Return (state, snippet, phase) by scanning messages in reverse."""
    if not active:
        return "idle", "", None

    last_conv_role = None
    last_conv_text = ""
    last_phase = None

    for m in reversed(messages):
        role = m["role"]
        if role in ("thinking", "progress") and last_phase is None:
            last_phase = role
        if role in ("user", "assistant") and last_conv_role is None:
            last_conv_role = role
            last_conv_text = m.get("text", "")
            break

    if last_conv_role == "assistant":
        return "waiting_input", _clean_snippet(last_conv_text), None
    elif last_conv_role == "user":
        return "executing", _clean_snippet(last_conv_text), last_phase
    return "idle", "", None


def get_sessions_api():
    now = time.time()
    result = []
    with sessions_lock:
        for key, s in sessions_data.items():
            if not s["messages"]:
                continue
            active = (now - s["last_modified"]) < ACTIVE_THRESHOLD
            user_turns = sum(1 for m in s["messages"] if m["role"] == "user")
            state, snippet, phase = _session_state(s["messages"], active)
            result.append({
                "id": s["id"],
                "key": key,
                "source": s["source"],
                "project": s["project"],
                "turns": user_turns,
                "msgCount": len(s["messages"]),
                "active": active,
                "lastModified": s["last_modified"],
                "ageSec": int(now - s["last_modified"]),
                "state": state,
                "snippet": snippet,
                "phase": phase,
            })
    result.sort(key=lambda x: (not x["active"], -x["lastModified"]))
    return result


def get_session_messages_api(session_key: str):
    with sessions_lock:
        s = sessions_data.get(session_key)
        if not s:
            return {"error": "not found"}
        return {
            "id": s["id"],
            "source": s["source"],
            "project": s["project"],
            "messages": s["messages"],
        }


# ═══════════════════════════════════════════════════════════════
#  HTTP Handler
# ═══════════════════════════════════════════════════════════════

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._html(get_html())
        elif path == "/api/sessions":
            self._json(get_sessions_api())
        elif path.startswith("/api/session/"):
            key = unquote(self.path[len("/api/session/"):])
            self._json(get_session_messages_api(key))
        else:
            self.send_error(404)

    def _html(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))


# ═══════════════════════════════════════════════════════════════
#  HTML (loaded from file)
# ═══════════════════════════════════════════════════════════════

def get_html():
    html_path = Path(__file__).parent / "session-hub.html"
    return html_path.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"\n  Session Hub starting...")
    print(f"  Cursor: {CURSOR_BASE}")
    print(f"  Claude: {CLAUDE_BASE}\n")

    watcher = threading.Thread(target=watcher_loop, daemon=True)
    watcher.start()

    time.sleep(1)
    with sessions_lock:
        total = len(sessions_data)
        active = sum(1 for s in sessions_data.values()
                     if (time.time() - s["last_modified"]) < ACTIVE_THRESHOLD)

    print(f"  Found {total} sessions ({active} active)")
    print(f"  Dashboard: http://localhost:{PORT}\n")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
