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

ENV_PROVIDER = {env_name: provider for provider, env_name in PROVIDER_ENV.items()}
ENV_PROVIDER["GOOGLE_API_KEY"] = "gemini"


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _parse_provider_lines(raw: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        normalized_name = name.strip().upper()
        provider = ENV_PROVIDER.get(normalized_name) or normalized_name.lower()
        if provider in PROVIDER_ENV:
            cleaned = _strip_wrapping_quotes(value)
            if cleaned:
                parsed[provider] = cleaned
    return parsed


def _normalize_provider_updates(updates: dict[str, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}

    for bulk_key in ("bulk", "env", "provider_keys", "providerKeys"):
        raw_bulk = updates.get(bulk_key)
        if isinstance(raw_bulk, str) and raw_bulk.strip():
            stripped = raw_bulk.strip()
            if stripped.startswith("{"):
                try:
                    decoded = json.loads(stripped)
                except Exception:
                    decoded = None
                if isinstance(decoded, dict):
                    normalized.update(_normalize_provider_updates(decoded))
            normalized.update(_parse_provider_lines(stripped))

    for key, raw in updates.items():
        if raw is None:
            continue
        provider = ENV_PROVIDER.get(str(key).strip().upper()) or str(key).strip().lower()
        if provider not in PROVIDER_ENV:
            continue

        value = str(raw).strip()
        if not value:
            continue
        parsed_lines = _parse_provider_lines(value)
        if provider in parsed_lines:
            normalized[provider] = parsed_lines[provider]
        elif len(parsed_lines) == 1:
            normalized[provider] = next(iter(parsed_lines.values()))
        else:
            normalized[provider] = _strip_wrapping_quotes(value)
    return normalized


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
    normalized = _normalize_provider_updates(updates)
    for provider, value in normalized.items():
        current[provider] = value
        os.environ[PROVIDER_ENV[provider]] = value
        if provider == "gemini":
            os.environ["GOOGLE_API_KEY"] = value
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PROVIDER_KEYS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return provider_status()
