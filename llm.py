"""LLM layer — Gemini first (free daily credits), Anthropic Haiku fallback + optional batch."""

from __future__ import annotations

import time

import config
import usage_tracker
from logutil import get_logger

logger = get_logger(__name__)

LLM_MAX_RETRIES = 3
LLM_RETRY_BASE_SEC = 2.0
BATCH_POLL_SEC = config.BATCH_POLL_SEC
BATCH_TIMEOUT_SEC = config.BATCH_TIMEOUT_SEC

_last_provider: str = ""
_gemini_quota_exhausted: bool = False


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
    return bool(config.GEMINI_API_KEY)


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


def _call_gemini(prompt: str, *, json_mode: bool = True) -> str:
    from google import genai
    from google.genai import types as genai_types

    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    last_error: Exception | None = None

    for model in _gemini_model_chain():
        for attempt in range(LLM_MAX_RETRIES):
            try:
                kwargs: dict = {"model": model, "contents": prompt}
                if json_mode:
                    kwargs["config"] = genai_types.GenerateContentConfig(
                        response_mime_type="application/json",
                    )
                response = client.models.generate_content(**kwargs)
                text = (response.text or "").strip()
                if text:
                    if model != _gemini_model():
                        logger.info("[llm] Gemini fallback model succeeded: %s", model)
                    return text
                raise ValueError("Empty Gemini response")
            except Exception as exc:
                last_error = exc
                if _is_invalid_model_error(exc):
                    logger.info("[llm] Gemini model %s unavailable, trying next", model)
                    break
                if _is_retryable(exc) and attempt < LLM_MAX_RETRIES - 1:
                    wait = LLM_RETRY_BASE_SEC * (2 ** attempt)
                    logger.info("[llm] Gemini %s retry in %.0fs (%s)", model, wait, str(exc)[:80])
                    time.sleep(wait)
                    continue
                if _is_retryable(exc):
                    logger.info("[llm] Gemini %s exhausted, trying next model", model)
                    break
                raise

    err = last_error or RuntimeError("Gemini failed")
    raise RuntimeError(str(err)) from err


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
    global _last_provider, _gemini_quota_exhausted
    primary = _llm_primary()
    errors: list[str] = []

    skip_gemini = _gemini_quota_exhausted and _has_anthropic() and _fallback_to_anthropic()
    if skip_gemini:
        logger.info("[llm] Gemini quota exhausted this run — using Anthropic directly")

    if primary == "gemini" and _has_gemini() and not skip_gemini:
        try:
            text = _call_gemini(prompt, json_mode=json_mode)
            _last_provider = "gemini"
            usage_tracker.record_llm(
                provider="gemini",
                model=_gemini_model(),
                operation=operation,
                prompt=prompt,
                response=text,
            )
            return text
        except Exception as exc:
            if _is_quota_error(exc):
                _gemini_quota_exhausted = True
            errors.append(f"Gemini: {exc}")
            logger.warning("[llm] Gemini failed — %s", str(exc)[:120])
            if _fallback_to_anthropic() and _has_anthropic():
                logger.info("[llm] Falling back to Anthropic Haiku")
            elif not _has_anthropic():
                raise RuntimeError(friendly_llm_error(exc)) from exc
            else:
                logger.info("[llm] Anthropic fallback disabled (FALLBACK_TO_ANTHROPIC=false)")

    if _has_anthropic() and (
        primary == "anthropic" or _fallback_to_anthropic() or not _has_gemini()
    ):
        try:
            text = _call_anthropic(prompt, json_mode=json_mode)
            _last_provider = "anthropic"
            usage_tracker.record_llm(
                provider="anthropic",
                model=_deep_model(),
                operation=operation,
                prompt=prompt,
                response=text,
            )
            logger.info("[llm] Anthropic fallback succeeded")
            return text
        except Exception as exc:
            errors.append(f"Anthropic: {exc}")
            logger.warning("[llm] Anthropic failed — %s", str(exc)[:200])
            if primary == "anthropic" and _has_gemini() and _fallback_to_anthropic():
                logger.info("[llm] Anthropic failed — trying Gemini")
                try:
                    text = _call_gemini(prompt, json_mode=json_mode)
                    _last_provider = "gemini"
                    usage_tracker.record_llm(
                        provider="gemini",
                        model=_gemini_model(),
                        operation=operation,
                        prompt=prompt,
                        response=text,
                    )
                    return text
                except Exception as exc2:
                    errors.append(f"Gemini: {exc2}")

    if not _has_gemini() and not _has_anthropic():
        raise RuntimeError(
            "No LLM configured. Set GEMINI_API_KEY and/or ANTHROPIC_API_KEY in .env."
        )

    raise RuntimeError(
        friendly_llm_error(RuntimeError(" | ".join(errors) or "All LLM providers failed"))
    )


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
