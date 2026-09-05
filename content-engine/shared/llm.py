"""
LLM access for the content engine.

Provider chain (see DECISIONS.md D-04):
    gemini  -> free daily tier covers this workload; default for every step
    claude  -> used explicitly for clinical claim work, and as automatic fallback
    groq    -> whisper-large-v3-turbo for audio transcription (effectively free)

Everything returns text; ask_json() enforces a parsed dict/list so callers never
hand-roll JSON extraction.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from . import config

MAX_RETRIES = 3
RETRY_BASE_SEC = 4


class LLMError(RuntimeError):
    pass


# ---------------------------------------------------------------- helpers


def _is_retryable(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(
        k in s
        for k in ("429", "rate", "quota", "overload", "timeout", "503", "500", "unavailable")
    )


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def extract_json(text: str) -> Any:
    """Parse JSON out of a model response, tolerating prose and code fences."""
    t = _strip_fences(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost balanced {...} or [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(t)):
            ch = t[i]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise LLMError(f"Could not parse JSON from model response: {text[:400]}")


# ---------------------------------------------------------------- providers


def _call_gemini(prompt: str, *, json_mode: bool, system: str | None) -> str:
    from google import genai
    from google.genai import types as genai_types

    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    chain = [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]
    last: Exception | None = None

    for model in chain:
        for attempt in range(MAX_RETRIES):
            try:
                cfg_kwargs: dict[str, Any] = {}
                if json_mode:
                    cfg_kwargs["response_mime_type"] = "application/json"
                if system:
                    cfg_kwargs["system_instruction"] = system
                kwargs: dict[str, Any] = {"model": model, "contents": prompt}
                if cfg_kwargs:
                    kwargs["config"] = genai_types.GenerateContentConfig(**cfg_kwargs)
                resp = client.models.generate_content(**kwargs)
                text = (resp.text or "").strip()
                if text:
                    return text
                raise ValueError("Empty Gemini response")
            except Exception as exc:  # noqa: BLE001
                last = exc
                if "not found" in str(exc).lower() or "invalid" in str(exc).lower():
                    break
                if _is_retryable(exc) and attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BASE_SEC * (2**attempt))
                    continue
                break
    raise LLMError(f"Gemini failed: {last}")


def _call_anthropic(prompt: str, *, json_mode: bool, system: str | None) -> str:
    from anthropic import Anthropic

    if not config.ANTHROPIC_API_KEY:
        raise LLMError("ANTHROPIC_API_KEY is not set.")

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    sys_prompt = system or ""
    if json_mode:
        sys_prompt = (sys_prompt + "\n\nRespond with valid JSON only. No prose, no code fences.").strip()

    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            kwargs: dict[str, Any] = {
                "model": config.ANTHROPIC_MODEL,
                "max_tokens": 8000,
                "messages": [{"role": "user", "content": prompt}],
            }
            if sys_prompt:
                kwargs["system"] = sys_prompt
            resp = client.messages.create(**kwargs)
            text = "".join(getattr(b, "text", "") or "" for b in resp.content).strip()
            if text:
                return text
            raise ValueError("Empty Claude response")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _is_retryable(exc) and attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BASE_SEC * (2**attempt))
                continue
            break
    raise LLMError(f"Anthropic failed: {last}")


# ---------------------------------------------------------------- public API


def ask(
    prompt: str,
    *,
    json_mode: bool = False,
    system: str | None = None,
    prefer: str | None = None,
) -> str:
    """Call the LLM with automatic provider fallback.

    prefer="claude" pins the first attempt to Anthropic. Used for clinical claim
    extraction, where being wrong is a regulatory problem rather than a style one.
    """
    order = ["gemini", "claude"]
    first = (prefer or config.LLM_PRIMARY or "gemini").lower()
    if first in ("claude", "anthropic"):
        order = ["claude", "gemini"]

    errors: list[str] = []
    for provider in order:
        try:
            if provider == "gemini":
                return _call_gemini(prompt, json_mode=json_mode, system=system)
            return _call_anthropic(prompt, json_mode=json_mode, system=system)
        except LLMError as exc:
            errors.append(f"{provider}: {exc}")
            continue
    raise LLMError("All providers failed -> " + " | ".join(errors))


def ask_json(
    prompt: str,
    *,
    system: str | None = None,
    prefer: str | None = None,
) -> Any:
    raw = ask(prompt, json_mode=True, system=system, prefer=prefer)
    return extract_json(raw)


def ask_json_with_images(
    prompt: str,
    image_paths: list[str],
    *,
    system: str | None = None,
) -> Any:
    """Ask a question about one or more local images. Gemini first, Claude second.

    Used by Part E to let the model look at rendered cover variants and pick the
    strongest one, which is the step reference video 1 does by eye.
    """
    import base64
    import mimetypes

    errors: list[str] = []

    # --- Gemini -----------------------------------------------------------
    if config.GEMINI_API_KEY:
        try:
            from google import genai
            from google.genai import types as genai_types

            client = genai.Client(api_key=config.GEMINI_API_KEY)
            parts: list[Any] = [prompt]
            for p in image_paths:
                path = Path(p)
                mime = mimetypes.guess_type(path.name)[0] or "image/png"
                parts.append(
                    genai_types.Part.from_bytes(data=path.read_bytes(), mime_type=mime)
                )
            cfg: dict[str, Any] = {"response_mime_type": "application/json"}
            if system:
                cfg["system_instruction"] = system
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=parts,
                config=genai_types.GenerateContentConfig(**cfg),
            )
            text = (resp.text or "").strip()
            if text:
                return extract_json(text)
            errors.append("gemini: empty response")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"gemini: {exc}")

    # --- Claude -----------------------------------------------------------
    if config.ANTHROPIC_API_KEY:
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
            content: list[dict[str, Any]] = []
            for p in image_paths:
                path = Path(p)
                mime = mimetypes.guess_type(path.name)[0] or "image/png"
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                    },
                })
            content.append({"type": "text", "text": prompt})
            resp = client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=2000,
                system=(system or "") + "\n\nRespond with valid JSON only.",
                messages=[{"role": "user", "content": content}],
            )
            text = "".join(getattr(b, "text", "") or "" for b in resp.content).strip()
            if text:
                return extract_json(text)
            errors.append("claude: empty response")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"claude: {exc}")

    raise LLMError("Vision call failed -> " + " | ".join(errors))


def transcribe_audio(path: str) -> dict[str, Any]:
    """Transcribe a local audio/video file with Groq whisper-large-v3-turbo.

    Returns {"text": str, "segments": [{"start","end","text"}, ...]}.
    Word/segment timings are what the caption burner in Part D needs.
    """
    from groq import Groq

    if not config.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set.")

    client = Groq(api_key=config.GROQ_API_KEY)
    with open(path, "rb") as fh:
        resp = client.audio.transcriptions.create(
            file=(str(path), fh.read()),
            model=config.GROQ_WHISPER_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    data = resp if isinstance(resp, dict) else resp.model_dump()
    segments = [
        {
            "start": float(s.get("start", 0.0)),
            "end": float(s.get("end", 0.0)),
            "text": (s.get("text") or "").strip(),
        }
        for s in (data.get("segments") or [])
    ]
    return {"text": (data.get("text") or "").strip(), "segments": segments}


def available_providers() -> dict[str, bool]:
    return {
        "gemini": bool(config.GEMINI_API_KEY),
        "anthropic": bool(config.ANTHROPIC_API_KEY),
        "groq": bool(config.GROQ_API_KEY),
        "tavily": bool(config.TAVILY_API_KEY),
    }
