"""JSONL parsing — ported from session-hub.py, made stateless for server use."""

from __future__ import annotations

import json
import re

HARD_INPUT_TOOLS = {"AskUserQuestion", "AskQuestion"}

_THINKING_STARTS = [
    "The user", "Let me", "I need", "I'll", "I can", "I should",
    "Now I", "Looking at", "This is", "OK,", "Alright", "Good",
    "Excellent", "Wait", "Actually", "Hmm", "Interesting", "From",
    "I have", "I see", "I want", "I realize", "Now let", "Great",
    "Perfect", "So the", "Based on", "Given", "I already",
    "The watcher", "The key", "Both", "For the", "Now the",
    "Key insight", "This means", "Since", "My plan",
]


def is_thinking_content(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 15:
        return False
    if re.search(r"^#{1,3}\s", t, re.MULTILINE):
        return False
    if re.match(r"^[\u4e00-\u9fff]", t):
        return False
    if t.startswith("```") or t.startswith("|"):
        return False
    return any(t.startswith(s) for s in _THINKING_STARTS)


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
    return {
        "role": role, "text": text, "ts": None,
        "tool_name": None, "tool_input_summary": None,
        "has_hard_input": False, "hard_question": None,
    }


def parse_claude_line(raw: str) -> dict | None:
    obj = json.loads(raw)
    t = obj.get("type", "")
    ts = obj.get("timestamp", "")

    if t in ("user", "assistant"):
        msg = obj.get("message", {})
        content = msg.get("content", "")
        hard_input = False
        hard_question = ""
        tool_name = None
        tool_input_summary = None

        if isinstance(content, list):
            text = " ".join(
                c.get("text", "") for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
            if t == "assistant":
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        tname = c.get("name", "")
                        if not tool_name:
                            tool_name = tname
                            inp = c.get("input", {})
                            tool_input_summary = str(inp)[:200]
                        if tname in HARD_INPUT_TOOLS:
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

        return {
            "role": role, "text": text or hard_question, "ts": ts,
            "tool_name": tool_name, "tool_input_summary": tool_input_summary,
            "has_hard_input": hard_input, "hard_question": hard_question or None,
        }

    elif t == "progress":
        data = obj.get("data", {})
        desc = data.get("hookName", data.get("type", t))
        return {
            "role": "progress", "text": f"[{desc}]", "ts": ts,
            "tool_name": None, "tool_input_summary": None,
            "has_hard_input": False, "hard_question": None,
        }

    return None


def parse_line(raw: str, source: str) -> dict | None:
    if source.startswith("cursor"):
        return parse_cursor_line(raw)
    return parse_claude_line(raw)
