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
SOFT_INPUT_THRESHOLD = 180  # 3 min: soft waiting_input → idle
POLL_INTERVAL = 2.0

HARD_INPUT_TOOLS = {"AskUserQuestion", "AskQuestion"}

sessions_lock = threading.Lock()
sessions_data: Dict[str, dict] = {}
dismissed_keys: set[str] = set()

# ═══════════════════════════════════════════════════════════════
#  Session Discovery & Parsing
# ═══════════════════════════════════════════════════════════════

def discover_files():
    """Return list of (source, path, parent_key_or_None)."""
    found = []
    if CURSOR_BASE.exists():
        for proj_dir in CURSOR_BASE.iterdir():
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
                    found.append(("cursor", main_file, None))
                for sub in sess_dir.glob("subagents/*.jsonl"):
                    parent_key = str(main_file) if main_file.exists() else None
                    found.append(("cursor-sub", sub, parent_key))
    if CLAUDE_BASE.exists():
        for proj in CLAUDE_BASE.iterdir():
            if not proj.is_dir():
                continue
            for p in proj.glob("*.jsonl"):
                found.append(("claude", p, None))
            for p in proj.glob("*/subagents/agent-*.jsonl"):
                parent_name = p.parent.parent.name
                parent_file = proj / (parent_name + ".jsonl")
                parent_key = str(parent_file) if parent_file.exists() else None
                found.append(("claude-sub", p, parent_key))
    return found


def session_id(path: Path, source: str) -> str:
    if source in ("cursor", "cursor-sub"):
        return path.stem
    elif source == "claude-sub":
        return f"{path.parent.parent.name[:8]}>{path.stem[:12]}"
    return path.stem


def _extract_project_name(raw: str) -> str:
    for prefix in ("Users-gunegg-Works-", "Users-gunegg-", "-Users-gunegg-Works-", "-Users-gunegg-"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return raw.replace("-", "/", 2).replace("-", " ") if "/" not in raw else raw


def project_name(path: Path, source: str) -> str:
    if source == "cursor":
        raw = path.parent.parent.parent.name
    elif source == "cursor-sub":
        raw = path.parent.parent.parent.parent.name
    else:
        raw = path.parent.name
    return _extract_project_name(raw)


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
        hard_input = False
        hard_question = ""
        if isinstance(content, list):
            text = " ".join(
                c.get("text", "") for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
            if t == "assistant":
                for c in content:
                    if (isinstance(c, dict) and c.get("type") == "tool_use"
                            and c.get("name") in HARD_INPUT_TOOLS):
                        hard_input = True
                        inp = c.get("input", {})
                        qs = inp.get("questions", inp.get("question", ""))
                        if isinstance(qs, list) and qs:
                            hard_question = qs[0].get("question", "")
                        elif isinstance(qs, str):
                            hard_question = qs
                        break
        else:
            text = str(content)
        if not text and not hard_input:
            return None
        role = t
        if role == "assistant":
            role = "thinking" if is_thinking_content(text) else "assistant"
        result = {"role": role, "text": text or hard_question, "ts": ts}
        if hard_input:
            result["hard_input"] = True
            if hard_question:
                result["hard_question"] = hard_question
        return result
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
        new_count = 0
        for line in new_data.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = (parse_cursor_line(line) if source == "cursor"
                          else parse_claude_line(line))
                if parsed:
                    sess["messages"].append(parsed)
                    new_count += 1
            except (json.JSONDecodeError, KeyError):
                pass
        if new_count > 0:
            undismiss_on_activity(str(path))
    except Exception:
        pass


def watcher_loop():
    while True:
        try:
            found = discover_files()
            with sessions_lock:
                for source, path, parent_key in found:
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
                            "parentKey": parent_key,
                            "children": [],
                        }
                    s = sessions_data[key]
                    if parent_key and s["parentKey"] != parent_key:
                        s["parentKey"] = parent_key
                    update_session(s, path, source)
                # rebuild children lists
                for s in sessions_data.values():
                    s["children"] = []
                for key, s in sessions_data.items():
                    pk = s.get("parentKey")
                    if pk and pk in sessions_data:
                        sessions_data[pk]["children"].append(key)
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


def _session_state(messages: list, active: bool, age_sec: int
                    ) -> tuple[str, str, str | None, str | None]:
    """Return (state, snippet, phase, inputType) by scanning messages in reverse.
    inputType: 'hard' (AskQuestion/approval) | 'soft' (just assistant replied) | None
    """
    if not active:
        return "idle", "", None, None

    last_conv_role = None
    last_conv_text = ""
    last_phase = None
    has_hard_input = False

    for m in reversed(messages):
        role = m["role"]
        if role in ("thinking", "progress") and last_phase is None:
            last_phase = role
        if role in ("user", "assistant") and last_conv_role is None:
            last_conv_role = role
            last_conv_text = m.get("text", "")
            has_hard_input = m.get("hard_input", False)
            break

    if last_conv_role == "assistant":
        if has_hard_input:
            return "waiting_input", _clean_snippet(last_conv_text), None, "hard"
        if age_sec > SOFT_INPUT_THRESHOLD:
            return "idle", "", None, None
        return "waiting_input", _clean_snippet(last_conv_text), None, "soft"
    elif last_conv_role == "user":
        return "executing", _clean_snippet(last_conv_text), last_phase, None
    return "idle", "", None, None


def _build_session_entry(key, s, now):
    active = (now - s["last_modified"]) < ACTIVE_THRESHOLD
    age_sec = int(now - s["last_modified"])
    user_turns = sum(1 for m in s["messages"] if m["role"] == "user")
    src = s["source"]
    parse_src = "cursor" if src.startswith("cursor") else "claude"
    state, snippet, phase, input_type = _session_state(
        s["messages"], active, age_sec)
    if state == "waiting_input" and key in dismissed_keys:
        state = "idle"
        input_type = None
    return {
        "id": s["id"],
        "key": key,
        "source": src,
        "project": s["project"],
        "turns": user_turns,
        "msgCount": len(s["messages"]),
        "active": active,
        "lastModified": s["last_modified"],
        "ageSec": age_sec,
        "state": state,
        "snippet": snippet,
        "phase": phase,
        "inputType": input_type,
    }


def get_sessions_api():
    now = time.time()
    result = []
    with sessions_lock:
        for key, s in sessions_data.items():
            if not s["messages"]:
                continue
            if s.get("parentKey"):
                continue
            entry = _build_session_entry(key, s, now)
            children_entries = []
            for ck in s.get("children", []):
                cs = sessions_data.get(ck)
                if cs and cs["messages"]:
                    children_entries.append(_build_session_entry(ck, cs, now))
            children_entries.sort(key=lambda x: -x["lastModified"])
            entry["children"] = children_entries
            entry["subCount"] = len(children_entries)
            result.append(entry)
    result.sort(key=lambda x: (not x["active"], -x["lastModified"]))
    return result


def dismiss_session(session_key: str):
    dismissed_keys.add(session_key)
    return {"ok": True}


def undismiss_on_activity(key: str):
    """Auto-undismiss when a session gets new user activity."""
    dismissed_keys.discard(key)


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


def get_capabilities_api():
    return {"mode": "local"}


def get_projects_api():
    now = time.time()
    projects: Dict[str, dict] = {}
    with sessions_lock:
        for key, s in sessions_data.items():
            if not s["messages"] or s.get("parentKey"):
                continue
            name = s["project"]
            if name not in projects:
                projects[name] = {
                    "name": name,
                    "sessionCount": 0,
                    "activeCount": 0,
                    "lastActivity": 0.0,
                }
            p = projects[name]
            p["sessionCount"] += 1
            if (now - s["last_modified"]) < ACTIVE_THRESHOLD:
                p["activeCount"] += 1
            if s["last_modified"] > p["lastActivity"]:
                p["lastActivity"] = s["last_modified"]
    result = sorted(projects.values(), key=lambda x: -x["lastActivity"])
    return result


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
        elif path == "/api/capabilities":
            self._json(get_capabilities_api())
        elif path == "/api/sessions":
            self._json(get_sessions_api())
        elif path == "/api/projects":
            self._json(get_projects_api())
        elif path.startswith("/api/session/"):
            key = unquote(self.path[len("/api/session/"):])
            self._json(get_session_messages_api(key))
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/dismiss/"):
            key = unquote(self.path[len("/api/dismiss/"):])
            self._json(dismiss_session(key))
        else:
            self.send_error(404)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _html(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
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
