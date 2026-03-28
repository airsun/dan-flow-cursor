import hashlib
import json
import logging

import httpx

from ..config import settings

logger = logging.getLogger("danflow.callsign")

PROMPT_TEMPLATE = """Generate 3 call signs for the identity "{name}".

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
[{{"emoji": "🥚", "words": "Egg Cannon"}}, ...]"""

FALLBACK_EMOJIS = ["🔮", "⚡", "🌀", "🎯", "🦊", "🌊", "🔥", "💎", "🚀", "🌿"]
FALLBACK_WORDS = [
    "Spark", "Drift", "Pulse", "Orbit", "Flux",
    "Echo", "Nova", "Shade", "Bolt", "Prism",
]


async def generate_callsign_suggestions(name: str) -> list[dict]:
    if settings.DANFLOW_CLAUDE_API_KEY:
        try:
            return await _call_claude(name)
        except Exception as e:
            logger.warning("Claude API call failed, using fallback: %s", e)

    return _deterministic_fallback(name)


async def _call_claude(name: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.DANFLOW_CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": PROMPT_TEMPLATE.format(name=name)}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"]
        start = text.index("[")
        end = text.rindex("]") + 1
        return json.loads(text[start:end])


def _deterministic_fallback(name: str) -> list[dict]:
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    results = []
    for i in range(3):
        idx = (h + i * 7) % len(FALLBACK_EMOJIS)
        widx = (h + i * 13) % len(FALLBACK_WORDS)
        widx2 = (h + i * 17 + 3) % len(FALLBACK_WORDS)
        results.append({
            "emoji": FALLBACK_EMOJIS[idx],
            "words": FALLBACK_WORDS[widx] + " " + FALLBACK_WORDS[widx2],
        })
    return results
