#!/usr/bin/env python3
"""Session Hub Watcher - 实时监控所有 AI 编码工具的活跃会话"""

import os, json, time, sys
from pathlib import Path
from datetime import datetime, timezone

CURSOR_BASE = Path.home() / ".cursor" / "projects"
CLAUDE_BASE = Path.home() / ".claude" / "projects"

COLORS = {
    "reset":    "\033[0m",
    "bold":     "\033[1m",
    "dim":      "\033[2m",
    "cursor":   "\033[38;5;39m",   # blue
    "claude":   "\033[38;5;208m",  # orange
    "claude-sub": "\033[38;5;178m",# gold
    "user":     "\033[38;5;114m",  # green
    "assistant":"\033[38;5;183m",  # purple
    "progress": "\033[38;5;245m",  # gray
    "separator":"\033[38;5;240m",  # dark gray
    "header":   "\033[38;5;255m",  # white
}

C = COLORS

file_positions: dict[str, int] = {}
known_sessions: dict[str, dict] = {}
POLL_INTERVAL = 1.0
ACTIVE_THRESHOLD = 300  # 5 min


def session_id_from_path(path: Path, source: str) -> str:
    if source == "cursor":
        return path.stem
    elif source == "claude-sub":
        return f"{path.parent.parent.name}→{path.stem}"
    else:
        return path.stem


def project_name_from_path(path: Path, source: str) -> str:
    if source == "cursor":
        raw = path.parent.parent.parent.name
    else:
        raw = path.parent.name
    return raw.replace("Users-gunegg-Works-", "").replace("Users-gunegg-", "~/")\
              .replace("-", "/", 2).replace("-", " ", 1) if raw.startswith("Users") else raw


def discover_sessions():
    found = []
    if CURSOR_BASE.exists():
        for jsonl in CURSOR_BASE.glob("*/agent-transcripts/**/*.jsonl"):
            found.append(("cursor", jsonl))

    if CLAUDE_BASE.exists():
        for proj_dir in CLAUDE_BASE.iterdir():
            if not proj_dir.is_dir():
                continue
            for jsonl in proj_dir.glob("*.jsonl"):
                found.append(("claude", jsonl))
            for jsonl in proj_dir.glob("*/subagents/agent-*.jsonl"):
                found.append(("claude-sub", jsonl))
    return found


def is_active(path: Path) -> bool:
    try:
        mtime = os.path.getmtime(path)
        return (time.time() - mtime) < ACTIVE_THRESHOLD
    except:
        return False


def truncate(text: str, max_len: int = 200) -> str:
    text = text.replace("\n", " ").strip()
    if text.startswith("<cursor_commands>"):
        idx = text.find("</cursor_commands>")
        if idx > 0:
            text = text[idx + len("</cursor_commands>"):].strip()
    if text.startswith("<user_query>"):
        text = text.replace("<user_query>", "").replace("</user_query>", "").strip()
    return text[:max_len] + "…" if len(text) > max_len else text


def parse_cursor_line(raw: str):
    obj = json.loads(raw)
    role = obj.get("role", "unknown")
    parts = obj.get("message", {}).get("content", [])
    text = ""
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            text = p["text"]
            break
    return {"role": role, "text": text, "ts": None}


def parse_claude_line(raw: str):
    obj = json.loads(raw)
    t = obj.get("type", "")
    ts = obj.get("timestamp", "")

    if t in ("user", "assistant"):
        msg = obj.get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        elif isinstance(content, str):
            text = content
        else:
            text = str(content)
        return {"role": t, "text": text, "ts": ts}
    elif t == "progress":
        data = obj.get("data", {})
        hook = data.get("hookName", data.get("type", ""))
        return {"role": "progress", "text": f"[{hook}]", "ts": ts}
    elif t == "file-history-snapshot":
        return None
    return None


def tail_file(path: Path, source: str):
    key = str(path)
    pos = file_positions.get(key, 0)
    try:
        size = os.path.getsize(path)
        if size <= pos:
            return []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(pos)
            new_data = f.read()
            file_positions[key] = f.tell()

        results = []
        for line in new_data.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = parse_cursor_line(line) if source == "cursor" else parse_claude_line(line)
                if parsed and parsed.get("text"):
                    results.append(parsed)
            except (json.JSONDecodeError, KeyError):
                pass
        return results
    except Exception:
        return []


def fmt_time(ts_str=None):
    if ts_str:
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%H:%M:%S")
        except:
            pass
    return datetime.now().strftime("%H:%M:%S")


def print_msg(source: str, session_id: str, project: str, msg: dict):
    ts = fmt_time(msg.get("ts"))
    role = msg["role"]
    text = truncate(msg["text"])

    if not text or len(text) < 3:
        return

    src_color = C.get(source, C["reset"])
    role_color = C.get(role, C["reset"])
    src_tag = {"cursor": "CUR", "claude": "CC", "claude-sub": "CC↓"}.get(source, "?")

    print(
        f"{C['dim']}{ts}{C['reset']} "
        f"{src_color}{C['bold']}[{src_tag}]{C['reset']} "
        f"{C['dim']}{project[:30]:30s}{C['reset']} "
        f"{role_color}{role:10s}{C['reset']} "
        f"{text}"
    )


def print_header():
    print(f"\n{C['bold']}{C['header']}{'═' * 90}{C['reset']}")
    print(f"{C['bold']}{C['header']}  Session Hub Watcher  —  实时监控 Cursor + Claude Code 会话{C['reset']}")
    print(f"{C['bold']}{C['header']}{'═' * 90}{C['reset']}")
    print(f"{C['dim']}  Cursor:  {CURSOR_BASE}{C['reset']}")
    print(f"{C['dim']}  Claude:  {CLAUDE_BASE}{C['reset']}")
    print(f"{C['dim']}  Poll:    {POLL_INTERVAL}s  |  Active threshold: {ACTIVE_THRESHOLD}s{C['reset']}")
    print(f"{C['separator']}{'─' * 90}{C['reset']}\n")


def print_status(active_count: int, total_count: int):
    now = datetime.now().strftime("%H:%M:%S")
    sys.stdout.write(
        f"\r{C['dim']}[{now}] 活跃: {active_count}  |  总计: {total_count}  |  Ctrl+C 退出{C['reset']}"
    )
    sys.stdout.flush()


def main():
    print_header()

    init = True
    last_status = 0

    while True:
        try:
            sessions = discover_sessions()
            active_sessions = [(s, p) for s, p in sessions if is_active(p)]

            for source, path in active_sessions:
                sid = session_id_from_path(path, source)
                proj = project_name_from_path(path, source)
                key = str(path)

                if key not in known_sessions:
                    known_sessions[key] = {"source": source, "sid": sid, "project": proj}
                    if not init:
                        print(f"\n{C['bold']}  ▶ 新会话: [{source}] {proj} ({sid[:8]}…){C['reset']}")

                if init:
                    # 首次运行: 跳到文件末尾，只显示新内容
                    try:
                        file_positions[key] = os.path.getsize(path)
                    except:
                        pass
                    continue

                new_msgs = tail_file(path, source)
                for msg in new_msgs:
                    print_msg(source, sid, proj, msg)

            if init:
                init = False
                active_count = len(active_sessions)
                print(f"{C['bold']}  ✓ 已发现 {active_count} 个活跃会话，开始监听…{C['reset']}\n")
                for source, path in active_sessions:
                    sid = session_id_from_path(path, source)
                    proj = project_name_from_path(path, source)
                    src_color = C.get(source, C["reset"])
                    src_tag = {"cursor": "CUR", "claude": "CC", "claude-sub": "CC↓"}.get(source, "?")
                    print(f"  {src_color}[{src_tag}]{C['reset']} {proj[:40]:40s} {C['dim']}{sid[:12]}…{C['reset']}")
                print(f"\n{C['separator']}{'─' * 90}{C['reset']}\n")

            now = time.time()
            if now - last_status > 10:
                print_status(len(active_sessions), len(sessions))
                last_status = now

            time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print(f"\n\n{C['bold']}  Session Hub 已停止。{C['reset']}\n")
            break


if __name__ == "__main__":
    main()
