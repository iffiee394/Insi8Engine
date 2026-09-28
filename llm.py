"""LLM layer — Gemini first (free daily credits), Anthropic Haiku fallback + optional batch."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import config
import progress
import provider_state
import usage_tracker
from logutil import get_logger

logger = get_logger(__name__)

LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_SEC = 2.0
BATCH_POLL_SEC = config.BATCH_POLL_SEC
BATCH_TIMEOUT_SEC = config.BATCH_TIMEOUT_SEC

_last_provider: str = ""


class ProviderChainError(RuntimeError):
    """Every key/provider was tried; the message says what happened to each."""


def _gemini_model() -> str:
    return config.GEMINI_CHAT_MODEL


def _gemini_model_chain() -> list[str]:
    models = [_gemini_model()]
    for m in config.GEMINI_FALLBACK_MODELS:
        if m and m not in models:
            models.append(m)
    return models


def _deep_model() -> str:
    return config.DEEP_MODEL


def _deep_max_tokens() -> int:
    return config.DEEP_MAX_OUTPUT_TOKENS


def _llm_primary() -> str:
    primary = config.LLM_PRIMARY
    return primary if primary in ("gemini", "anthropic") else "gemini"


def _fallback_to_anthropic() -> bool:
    return config.FALLBACK_TO_ANTHROPIC


def _batch_use_anthropic() -> bool:
    return config.BATCH_USE_ANTHROPIC


def last_llm_provider() -> str:
    return _last_provider


def _has_gemini() -> bool:
    return bool(provider_state.gemini_keys())


def _has_anthropic() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def _is_invalid_model_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "404", "not_found", "is not found",
            "not supported for generatecontent", "not supported for",
        )
    )


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "529", "503", "429", "500", "502", "504",
            "unavailable", "high demand", "overloaded",
            "rate limit", "resource exhausted", "quota", "try again",
        )
    )


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("429", "resource exhausted", "quota", "rate limit")
    )


def _is_groq_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "groq" in msg or "llama-" in msg


def friendly_llm_error(exc: Exception) -> str:
    msg = str(exc)
    lower = msg.lower()

    # These already explain each step in plain words; the keyword checks below
    # would otherwise rewrite them (e.g. any mention of "Gemini ... API key").
    if type(exc).__name__ in ("AudioDownloadError", "ProviderChainError", "TranscriptUnavailable"):
        return msg
    if msg.startswith(("All AI providers failed", "No transcript", "No AI provider")):
        return msg

    if "anthropic:" in lower:
        anthropic_part = msg.split("Anthropic:", 1)[-1].strip()
        if "401" in anthropic_part.lower() or "authentication" in anthropic_part.lower():
            return (
                "Gemini quota exceeded. Anthropic fallback failed — "
                "invalid ANTHROPIC_API_KEY. Check .env and restart Streamlit."
            )
        if "credit balance" in anthropic_part.lower() or "billing" in anthropic_part.lower():
            return (
                "Gemini quota exceeded. Anthropic fallback failed — "
                "add credits at console.anthropic.com/settings/billing."
            )
        if "404" in anthropic_part.lower() and "model" in anthropic_part.lower():
            return (
                f"Gemini quota exceeded. Anthropic model not found — "
                f"check DEEP_MODEL in .env ({_deep_model()})."
            )
        return f"Gemini quota exceeded. Anthropic fallback also failed: {anthropic_part[:200]}"

    if _is_groq_error(exc) and (
        "429" in lower or "rate limit" in lower or "quota" in lower or "resource exhausted" in lower
    ):
        return (
            "Groq rate limit hit during research/agenda step. "
            "Retry in a few minutes — the app will fall back to Anthropic on the next attempt."
        )

    if "503" in lower or "unavailable" in lower or "high demand" in lower:
        if "gemini" in lower or "generatecontent" in lower:
            return "Gemini is temporarily overloaded. Retries Anthropic fallback if configured."
        return f"LLM temporarily unavailable: {msg[:200]}"

    if ("429" in lower or "rate limit" in lower or "quota" in lower or "resource exhausted" in lower) and (
        "gemini" in lower or "generatecontent" in lower or "resource_exhausted" in lower
    ):
        if _has_anthropic() and _fallback_to_anthropic():
            return (
                "Gemini daily quota used up — switching to Anthropic for remaining LLM steps. "
                "Click Retry to re-process."
            )
        return (
            "Gemini daily quota used up — set ANTHROPIC_API_KEY in .env "
            "and FALLBACK_TO_ANTHROPIC=true, then re-process."
        )

    if "429" in lower or "rate limit" in lower:
        return f"API rate limit: {msg[:200]}"
    if "404" in lower and "model" in lower:
        return "Gemini model not available. Check GEMINI_CHAT_MODEL or use Anthropic fallback."
    if "gemini" in lower and ("api key" in lower or "invalid" in lower):
        return "Gemini API key missing or invalid. Check GEMINI_API_KEY in .env."
    if "401" in lower or "authentication" in lower or "invalid x-api-key" in lower:
        return "Anthropic API key missing or invalid. Check ANTHROPIC_API_KEY in .env."
    if "credit balance" in lower or "billing" in lower:
        return "Anthropic billing issue — add credits at console.anthropic.com/settings/billing."
    return msg[:500]


def _describe(exc: BaseException) -> str:
    """One readable line from a provider error (Google errors embed a JSON 'message')."""
    msg = str(exc)
    match = re.search(r"""['"]message['"]\s*:\s*['"](.+?)['"]\s*[,}]""", msg)
    text = match.group(1) if match else (msg.splitlines()[0] if msg else type(exc).__name__)
    code = re.match(r"\s*(\d{3})\b", msg)
    if code and not text.startswith(code.group(1)):
        text = f"{code.group(1)} {text}"
    return text.strip()[:200]


def _until_text(until: datetime) -> str:
    minutes = max(1, int((until - datetime.now(timezone.utc)).total_seconds() // 60))
    if minutes < 60:
        return f"retry in {minutes} min"
    return f"resets in about {round(minutes / 60)} h"


def _is_invalid_key_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("api_key_invalid", "api key not valid", "api key expired", "permission_denied", "unauthenticated")
    ) or bool(re.match(r"\s*(401|403)\b", msg))


def _gemini_failure(slot: str, model: str, exc: Exception, attempt: int) -> tuple[str, str]:
    """Classify a Gemini error, update key state, and return (kind, readable reason)."""
    if _is_invalid_model_error(exc):
        reason = f"{model} not offered to this account"
        provider_state.mark_limited(slot, model, reason, datetime.now(timezone.utc) + timedelta(days=7))
        return "model", reason
    if _is_invalid_key_error(exc):
        reason = f"key rejected by Google ({_describe(exc)})"
        provider_state.mark_invalid(slot, reason)
        return "key", reason
    if _is_quota_error(exc):
        reason, until = provider_state.quota_cooldown(str(exc))
        provider_state.mark_limited(slot, model, reason, until)
        return "quota", f"{reason}, {_until_text(until)}"
    if _is_retryable(exc):
        if attempt < LLM_MAX_RETRIES - 1:
            return "retry", ""
        until = datetime.now(timezone.utc) + timedelta(seconds=90)
        provider_state.mark_limited(slot, model, "Google servers overloaded", until)
        return "busy", "Google servers overloaded"
    return "error", _describe(exc)


def _summarize(attempts: list[tuple[str, str, str]]) -> str:
    """[(slot, model, reason)] -> 'Gemini key 1: daily quota used up · Claude: ...'"""
    by_slot: dict[str, list[str]] = {}
    for slot, _model, reason in attempts:
        reasons = by_slot.setdefault(slot, [])
        if reason not in reasons:
            reasons.append(reason)
    for slot, reasons in by_slot.items():
        useful = [r for r in reasons if "not offered to this account" not in r]
        if useful:
            by_slot[slot] = useful
    return " · ".join(
        f"{provider_state.slot_label(slot)}: {'; '.join(reasons)}" for slot, reasons in by_slot.items()
    )


class _NoGeminiAvailable(Exception):
    pass


def _call_gemini(
    prompt: str,
    *,
    json_mode: bool = True,
    attempts: list[tuple[str, str, str]] | None = None,
) -> tuple[str, str, str]:
    """Try each model on each key (best model first). Returns (text, slot, model)."""
    from google import genai
    from google.genai import types as genai_types

    attempts = attempts if attempts is not None else []
    keys = provider_state.gemini_keys()
    if not keys:
        raise _NoGeminiAvailable()

    for model in _gemini_model_chain():
        for slot, key in keys:
            blocked = provider_state.blocked_reason(slot, model)
            if blocked:
                attempts.append((slot, model, blocked))
                continue
            progress.report(f"Writing insights with {provider_state.slot_label(slot)} ({model})")
            client = genai.Client(api_key=key)
            for attempt in range(LLM_MAX_RETRIES):
                try:
                    kwargs: dict = {"model": model, "contents": prompt}
                    if json_mode:
                        kwargs["config"] = genai_types.GenerateContentConfig(
                            response_mime_type="application/json",
                        )
                    response = client.models.generate_content(**kwargs)
                    text = (response.text or "").strip()
                    if not text:
                        raise ValueError("Gemini returned an empty response")
                    meta = getattr(response, "usage_metadata", None)
                    tokens = getattr(meta, "total_token_count", None) or usage_tracker._est_tokens(prompt + text)
                    provider_state.record_success(slot, model, tokens)
                    return text, slot, model
                except Exception as exc:
                    kind, reason = _gemini_failure(slot, model, exc, attempt)
                    if kind == "retry":
                        wait = LLM_RETRY_BASE_SEC * (2 ** attempt)
                        logger.info("[llm] %s %s retry in %.0fs (%s)", slot, model, wait, str(exc)[:80])
                        time.sleep(wait)
                        continue
                    logger.warning("[llm] %s %s failed: %s", slot, model, reason)
                    attempts.append((slot, model, reason))
                    break
    raise _NoGeminiAvailable()


def run_with_gemini(
    fn: Callable[[Any, str], Any],
    *,
    purpose: str,
    models: list[str] | None = None,
) -> Any:
    """Run fn(client, model) on the first usable key/model, moving on after quota, key or model errors."""
    from google import genai

    attempts: list[tuple[str, str, str]] = []
    keys = provider_state.gemini_keys()
    if not keys:
        raise ProviderChainError(f"{purpose} needs a Gemini key (GEMINI_API_KEY is not set)")
    for model in models or _gemini_model_chain():
        for slot, key in keys:
            blocked = provider_state.blocked_reason(slot, model)
            if blocked:
                attempts.append((slot, model, blocked))
                continue
            progress.report(f"{purpose} with {provider_state.slot_label(slot)}")
            client = genai.Client(api_key=key)
            try:
                result = fn(client, model)
            except Exception as exc:
                if type(exc).__name__ == "AudioDownloadError":
                    raise
                kind, reason = _gemini_failure(slot, model, exc, LLM_MAX_RETRIES)
                attempts.append((slot, model, reason))
                if kind == "error":
                    raise ProviderChainError(f"{purpose} failed — {_summarize(attempts)}") from exc
                continue
            meta = getattr(result, "usage_metadata", None)
            provider_state.record_success(slot, model, getattr(meta, "total_token_count", None) or 0)
            return result
    raise ProviderChainError(f"{purpose} failed — {_summarize(attempts)}")


def _call_anthropic(prompt: str, *, json_mode: bool = True) -> str:
    from anthropic import Anthropic

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    last_error: Exception | None = None

    for attempt in range(LLM_MAX_RETRIES):
        try:
            response = client.messages.create(
                model=_deep_model(),
                max_tokens=_deep_max_tokens(),
                messages=[{"role": "user", "content": prompt}],
            )
            parts = []
            for block in response.content:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
            text = "".join(parts).strip()
            if text:
                return text
            raise ValueError("Empty Claude response")
        except Exception as exc:
            last_error = exc
            if _is_retryable(exc) and attempt < LLM_MAX_RETRIES - 1:
                wait = LLM_RETRY_BASE_SEC * (2 ** attempt)
                logger.info("[llm] Anthropic retry in %.0fs", wait)
                time.sleep(wait)
                continue
            raise RuntimeError(friendly_llm_error(exc)) from exc

    raise RuntimeError(friendly_llm_error(last_error or RuntimeError("Anthropic failed")))


def call_deep_llm(prompt: str, *, json_mode: bool = True, operation: str = "llm") -> str:
    """Gemini keys first (each key, best model first), Claude only when none can answer."""
    global _last_provider
    attempts: list[tuple[str, str, str]] = []
    order = ["anthropic", "gemini"] if _llm_primary() == "anthropic" else ["gemini", "anthropic"]

    for position, provider in enumerate(order):
        if provider == "gemini":
            if not _has_gemini():
                continue
            try:
                text, _slot, model = _call_gemini(prompt, json_mode=json_mode, attempts=attempts)
            except _NoGeminiAvailable:
                continue
            _last_provider = "gemini"
            usage_tracker.record_llm(
                provider="gemini", model=model, operation=operation, prompt=prompt, response=text,
            )
            return text

        if not _has_anthropic():
            continue
        if position > 0 and not _fallback_to_anthropic():
            attempts.append(("anthropic", "", "not used (FALLBACK_TO_ANTHROPIC=false)"))
            continue
        blocked = provider_state.blocked_reason("anthropic", "*")
        if blocked:
            attempts.append(("anthropic", "", blocked))
            continue
        progress.report(
            "Writing insights with Claude (no Gemini key available)" if position > 0 else "Writing insights with Claude"
        )
        try:
            text = _call_anthropic(prompt, json_mode=json_mode)
        except Exception as exc:
            reason = _describe(exc)
            lower = reason.lower()
            if "credit" in lower or "billing" in lower:
                provider_state.mark_limited(
                    "anthropic", "*", "no credits left",
                    datetime.now(timezone.utc) + timedelta(hours=6),
                )
                reason = "no credits left"
            attempts.append(("anthropic", "", reason))
            logger.warning("[llm] Claude failed — %s", reason)
            continue
        provider_state.record_success("anthropic", _deep_model(), usage_tracker._est_tokens(prompt + text))
        _last_provider = "anthropic"
        usage_tracker.record_llm(
            provider="anthropic", model=_deep_model(), operation=operation, prompt=prompt, response=text,
        )
        return text

    if not attempts:
        raise ProviderChainError("No AI provider configured — add a Gemini key (GEMINI_API_KEY).")
    raise ProviderChainError(f"All AI providers failed — {_summarize(attempts)}")


def batch_uses_anthropic() -> bool:
    return _batch_use_anthropic() and _has_anthropic()


def _anthropic_client():
    from anthropic import Anthropic

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (required for batch mode).")
    return Anthropic(api_key=config.ANTHROPIC_API_KEY)


def batch_request(custom_id: str, prompt: str) -> dict:
    return {
        "custom_id": custom_id,
        "params": {
            "model": _deep_model(),
            "max_tokens": _deep_max_tokens(),
            "messages": [{"role": "user", "content": prompt}],
        },
    }


def submit_batch(requests: list[dict]) -> str:
    client = _anthropic_client()
    batch = client.messages.batches.create(requests=requests)
    logger.info("[llm] Anthropic batch submitted: %s (%d requests)", batch.id, len(requests))
    return batch.id


def wait_for_batch(batch_id: str) -> None:
    client = _anthropic_client()
    started = time.time()
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        status = batch.processing_status
        logger.info("[llm] Batch %s: %s", batch_id, status)
        if status == "ended":
            return
        if status == "canceling":
            raise RuntimeError(f"Batch {batch_id} was canceled")
        if time.time() - started > BATCH_TIMEOUT_SEC:
            raise RuntimeError(f"Batch {batch_id} timed out")
        time.sleep(BATCH_POLL_SEC)


def collect_batch_results(batch_id: str) -> dict[str, str]:
    client = _anthropic_client()
    results: dict[str, str] = {}
    for entry in client.messages.batches.results(batch_id):
        if entry.result.type != "succeeded":
            logger.warning("[llm] Batch item %s failed: %s", entry.custom_id, entry.result.type)
            continue
        parts = []
        for block in entry.result.message.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        results[entry.custom_id] = "".join(parts).strip()
    return results


def run_batch_phase(label: str, items: list[tuple[str, str]]) -> dict[str, str]:
    if not items:
        return {}

    if _batch_use_anthropic() and _has_anthropic():
        logger.info("[llm] Batch phase '%s': Anthropic Message Batch (%d items)", label, len(items))
        requests = [batch_request(cid, prompt) for cid, prompt in items]
        batch_id = submit_batch(requests)
        wait_for_batch(batch_id)
        results = collect_batch_results(batch_id)
        for custom_id, prompt in items:
            response = results.get(custom_id, "")
            if response:
                usage_tracker.record_llm(
                    provider="anthropic",
                    model=_deep_model(),
                    operation=f"batch:{label}",
                    prompt=prompt,
                    response=response,
                    batch=True,
                )
        return results

    logger.info("[llm] Batch phase '%s': sequential (Gemini → Anthropic) (%d items)", label, len(items))
    results: dict[str, str] = {}
    for custom_id, prompt in items:
        results[custom_id] = call_deep_llm(prompt, operation=f"batch:{label}")
    return results
