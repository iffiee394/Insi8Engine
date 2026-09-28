"""Which AI keys are usable right now, and how much each was used today.

State lives in the `meta` table so the dashboard API can show it. The worker is
the writer; failures to persist never block an AI call.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo

    PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # tzdata missing
    PACIFIC = timezone(timedelta(hours=-7))

STATE_KEY = "llm_provider_state"
USAGE_KEY = "llm_usage_daily"
KEEP_DAYS = 14

_lock = threading.Lock()
_state: dict[str, Any] | None = None
_usage: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def usage_day() -> str:
    """Gemini free-tier quotas reset at midnight Pacific, so days are counted there."""
    return _now().astimezone(PACIFIC).date().isoformat()


def next_quota_reset() -> datetime:
    local = _now().astimezone(PACIFIC)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc) + timedelta(minutes=2)


def gemini_keys() -> list[tuple[str, str]]:
    """[(slot, key)] in the order they should be tried."""
    raw: list[str] = []
    try:
        import config

        raw.append(getattr(config, "GEMINI_API_KEY", "") or "")
    except Exception:
        pass
    raw.append(os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", ""))
    for n in range(2, 10):
        raw.append(os.getenv(f"GEMINI_API_KEY_{n}", ""))
    raw.extend(os.getenv("GEMINI_API_KEYS", "").split(","))

    keys: list[str] = []
    for key in raw:
        key = key.strip().strip('"').strip("'")
        if key and key not in keys:
            keys.append(key)
    return [(f"gemini_{i + 1}", key) for i, key in enumerate(keys)]


def mask(key: str) -> str:
    return f"…{key[-4:]}" if len(key) >= 8 else "set"


def slot_label(slot: str) -> str:
    if slot.startswith("gemini_"):
        return f"Gemini key {slot.split('_', 1)[1]}"
    return {"anthropic": "Claude", "groq": "Groq"}.get(slot, slot)


def _db():
    import db

    return db


def _load() -> None:
    global _state, _usage
    if _state is not None:
        return
    _state, _usage = {}, {}
    try:
        _state = json.loads(_db().get_meta(STATE_KEY, "{}") or "{}")
        _usage = json.loads(_db().get_meta(USAGE_KEY, "{}") or "{}")
    except Exception:
        pass


def _save() -> None:
    try:
        _db().set_meta(STATE_KEY, json.dumps(_state))
        _db().set_meta(USAGE_KEY, json.dumps(_usage))
    except Exception:
        pass


def _entry(slot: str) -> dict[str, Any]:
    _load()
    assert _state is not None
    return _state.setdefault(slot, {})


def blocked_reason(slot: str, model: str = "") -> str:
    """Why this key (and model) should be skipped right now, or '' if usable."""
    with _lock:
        entry = _entry(slot)
        now = _now()
        invalid_until = entry.get("invalid_until")
        if invalid_until and datetime.fromisoformat(invalid_until) > now:
            return entry.get("invalid_reason") or "key rejected"
        cooling = entry.get("cooldowns", {})
        for scope in (model, "*"):
            if not scope:
                continue
            item = cooling.get(scope)
            if item and datetime.fromisoformat(item["until"]) > now:
                return item.get("reason") or "cooling down"
        return ""


def mark_limited(slot: str, model: str, reason: str, until: datetime) -> None:
    with _lock:
        entry = _entry(slot)
        entry.setdefault("cooldowns", {})[model or "*"] = {"until": until.isoformat(), "reason": reason}
        entry["last_error"] = reason
        entry["last_error_at"] = _now().isoformat()
        _save()


def mark_invalid(slot: str, reason: str, hours: int = 6) -> None:
    with _lock:
        entry = _entry(slot)
        entry["invalid_until"] = (_now() + timedelta(hours=hours)).isoformat()
        entry["invalid_reason"] = reason
        entry["last_error"] = reason
        entry["last_error_at"] = _now().isoformat()
        _save()


def record_success(slot: str, model: str, tokens: int) -> None:
    with _lock:
        entry = _entry(slot)
        entry.pop("invalid_until", None)
        entry.get("cooldowns", {}).pop(model, None)
        entry["last_used_at"] = _now().isoformat()
        entry["last_model"] = model
        assert _usage is not None
        day = _usage.setdefault(usage_day(), {})
        counts = day.setdefault(slot, {"calls": 0, "tokens": 0})
        counts["calls"] += 1
        counts["tokens"] += max(0, int(tokens))
        for old in sorted(_usage)[:-KEEP_DAYS]:
            _usage.pop(old, None)
        _save()


def publish_slots() -> None:
    """Record which keys exist (masked) so the dashboard can list them before first use."""
    with _lock:
        _load()
        assert _state is not None
        slots = [
            {"slot": slot, "label": slot_label(slot), "masked": mask(key)}
            for slot, key in gemini_keys()
        ]
        anthropic = os.getenv("ANTHROPIC_API_KEY", "").strip()
        try:
            import config

            anthropic = anthropic or config.ANTHROPIC_API_KEY
        except Exception:
            pass
        if anthropic:
            slots.append({"slot": "anthropic", "label": "Claude", "masked": mask(anthropic)})
        _state["_slots"] = slots
        _state["_published_at"] = _now().isoformat()
        _save()


_RETRY_DELAY = re.compile(r"retry(?:delay)?['\"]?\s*[:=]?\s*['\"]?(\d+(?:\.\d+)?)s", re.IGNORECASE)


def quota_cooldown(message: str) -> tuple[str, datetime]:
    """Turn a Gemini 429 into (plain reason, retry time)."""
    lower = message.lower()
    if "perday" in lower or "per day" in lower or "requestsperday" in lower:
        return "daily quota used up", next_quota_reset()
    match = _RETRY_DELAY.search(message)
    seconds = float(match.group(1)) if match else 60.0
    return "rate limit (too many requests per minute)", _now() + timedelta(seconds=max(15.0, seconds))
