from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REMAKE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REMAKE_ROOT / "runtime"
PROVIDER_KEYS_PATH = RUNTIME_DIR / "provider_keys.json"

PROVIDER_ENV = {
    "youtube": "YOUTUBE_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "tavily": "TAVILY_API_KEY",
}


def _read_store() -> dict[str, str]:
    if not PROVIDER_KEYS_PATH.exists():
        return {}
    try:
        data = json.loads(PROVIDER_KEYS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v.strip()}


def apply_runtime_provider_keys(*, override: bool = True) -> dict[str, bool]:
    stored = _read_store()
    for provider, env_name in PROVIDER_ENV.items():
        value = stored.get(provider, "").strip()
        if value and (override or not os.getenv(env_name, "").strip()):
            os.environ[env_name] = value
            if provider == "gemini":
                os.environ["GOOGLE_API_KEY"] = value
    return provider_status()


def provider_status() -> dict[str, bool]:
    stored = _read_store()
    status: dict[str, bool] = {}
    for provider, env_name in PROVIDER_ENV.items():
        status[provider] = bool(stored.get(provider, "").strip() or os.getenv(env_name, "").strip())
    return status


def save_provider_keys(updates: dict[str, Any]) -> dict[str, bool]:
    current = _read_store()
    for provider in PROVIDER_ENV:
        if provider not in updates:
            continue
        raw = updates.get(provider)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            current[provider] = value
            os.environ[PROVIDER_ENV[provider]] = value
            if provider == "gemini":
                os.environ["GOOGLE_API_KEY"] = value
        else:
            current.pop(provider, None)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PROVIDER_KEYS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return provider_status()
