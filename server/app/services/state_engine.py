"""Session state inference — ported from session-hub.py _session_state()."""

from __future__ import annotations

import re
import time
from datetime import datetime

ACTIVE_THRESHOLD = 600
SOFT_INPUT_THRESHOLD = 180


def _clean_snippet(text: str, max_len: int = 80) -> str:
    t = text
    idx = t.find("</cursor_commands>")
    if idx > -1:
        t = t[idx + 18:]
    for tag in (
        "user_query", "system_reminder", "attached_files",
        "open_and_recently_viewed_files", "agent_transcripts",
        "user_info", "rules", "agent_skills",
    ):
        t = re.sub(rf"<{tag}>[\s\S]*?</{tag}>", "", t)
    t = t.strip().replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    return (t[:max_len] + "…") if len(t) > max_len else t


def compute_session_state(
    messages: list[dict],
    last_updated: datetime | None,
) -> dict:
    now = time.time()
    if last_updated:
        age_sec = int(now - last_updated.timestamp())
    else:
        age_sec = 999999

    active = age_sec < ACTIVE_THRESHOLD

    if not active or not messages:
        return {"state": "idle", "snippet": "", "phase": None, "inputType": None}

    last_conv_role = None
    last_conv_text = ""
    last_phase = None
    has_hard_input = False

    for m in reversed(messages):
        role = m.get("role", "")
        if role in ("thinking", "progress") and last_phase is None:
            last_phase = role
        if role in ("user", "assistant") and last_conv_role is None:
            last_conv_role = role
            last_conv_text = m.get("text", m.get("content", ""))
            has_hard_input = m.get("has_hard_input", False)
            break

    if last_conv_role == "assistant":
        if has_hard_input:
            return {
                "state": "waiting_input",
                "snippet": _clean_snippet(last_conv_text),
                "phase": None,
                "inputType": "hard",
            }
        if age_sec > SOFT_INPUT_THRESHOLD:
            return {"state": "idle", "snippet": "", "phase": None, "inputType": None}
        return {
            "state": "waiting_input",
            "snippet": _clean_snippet(last_conv_text),
            "phase": None,
            "inputType": "soft",
        }
    elif last_conv_role == "user":
        return {
            "state": "executing",
            "snippet": _clean_snippet(last_conv_text),
            "phase": last_phase,
            "inputType": None,
        }

    return {"state": "idle", "snippet": "", "phase": None, "inputType": None}
