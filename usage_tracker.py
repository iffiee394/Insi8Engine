"""Track API calls and estimated credits per processing run."""

from __future__ import annotations

import json
import threading
from contextvars import ContextVar
from typing import Any

import config

TAVILY_CREDITS_PER_SEARCH = float(config.TAVILY_CREDITS_PER_SEARCH)

# Rough $/1M tokens for display only (batch = 50% for Anthropic)
COST_PER_M = {
    "gemini-2.5-flash": {"in": 0.0, "out": 0.0, "note": "free tier"},
    "gemini-2.0-flash": {"in": 0.0, "out": 0.0, "note": "free tier"},
    "gemini-2.5-flash-lite": {"in": 0.0, "out": 0.0, "note": "free tier"},
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0, "note": "paid"},
    "claude-haiku-4-5-20251001-batch": {"in": 0.5, "out": 2.5, "note": "batch 50% off"},
}

_run: ContextVar[dict[str, Any] | None] = ContextVar("usage_run", default=None)
_lock = threading.Lock()


def _est_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def begin_run(video_id: str = "", title: str = "") -> None:
    _run.set({
        "video_id": video_id,
        "title": title,
        "calls": [],
    })


def _active() -> dict[str, Any] | None:
    return _run.get()


def record_llm(
    *,
    provider: str,
    model: str,
    operation: str,
    prompt: str,
    response: str,
    batch: bool = False,
) -> None:
    run = _active()
    if not run:
        return
    in_t = _est_tokens(prompt)
    out_t = _est_tokens(response)
    rate_key = f"{model}-batch" if batch and provider == "anthropic" else model
    rates = COST_PER_M.get(rate_key) or COST_PER_M.get(model) or {"in": 0, "out": 0}
    cost = (in_t * rates.get("in", 0) + out_t * rates.get("out", 0)) / 1_000_000
    run["calls"].append({
        "provider": provider,
        "model": model,
        "operation": operation,
        "batch": batch,
        "input_tokens_est": in_t,
        "output_tokens_est": out_t,
        "cost_usd_est": round(cost, 5),
    })


def record_groq(*, model: str, operation: str, prompt: str, response: str) -> None:
    run = _active()
    if not run:
        return
    run["calls"].append({
        "provider": "groq",
        "model": model,
        "operation": operation,
        "input_tokens_est": _est_tokens(prompt),
        "output_tokens_est": _est_tokens(response),
        "cost_usd_est": 0.0,
        "note": "free tier",
    })


def record_tavily(query: str, *, operation: str = "search") -> None:
    run = _active()
    if not run:
        return
    run["calls"].append({
        "provider": "tavily",
        "operation": operation,
        "query": (query or "")[:120],
        "credits_est": TAVILY_CREDITS_PER_SEARCH,
    })


def record_youtube(*, operation: str = "video_metadata") -> None:
    run = _active()
    if not run:
        return
    run["calls"].append({
        "provider": "youtube",
        "operation": operation,
        "units": 1,
    })


def _summarize(calls: list[dict]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "gemini_calls": 0,
        "anthropic_calls": 0,
        "anthropic_batch_calls": 0,
        "groq_calls": 0,
        "tavily_searches": 0,
        "tavily_credits_est": 0.0,
        "youtube_api_calls": 0,
        "total_input_tokens_est": 0,
        "total_output_tokens_est": 0,
        "cost_usd_est": 0.0,
    }
    for c in calls:
        p = c.get("provider", "")
        if p == "gemini":
            summary["gemini_calls"] += 1
        elif p == "anthropic":
            if c.get("batch"):
                summary["anthropic_batch_calls"] += 1
            else:
                summary["anthropic_calls"] += 1
        elif p == "groq":
            summary["groq_calls"] += 1
        elif p == "tavily":
            summary["tavily_searches"] += 1
            summary["tavily_credits_est"] += c.get("credits_est", 0)
        elif p == "youtube":
            summary["youtube_api_calls"] += 1
        summary["total_input_tokens_est"] += c.get("input_tokens_est", 0)
        summary["total_output_tokens_est"] += c.get("output_tokens_est", 0)
        summary["cost_usd_est"] += c.get("cost_usd_est", 0)
    summary["cost_usd_est"] = round(summary["cost_usd_est"], 4)
    summary["tavily_credits_est"] = round(summary["tavily_credits_est"], 1)
    return summary


def extend_calls(calls: list[dict]) -> None:
    """Append prior call records (e.g. research stashed before batch LLM phases)."""
    run = _active()
    if run and calls:
        run["calls"].extend(calls)


def finish_run() -> dict[str, Any]:
    run = _active()
    if not run:
        return {}
    calls = run.get("calls", [])
    result = {
        "video_id": run.get("video_id", ""),
        "title": run.get("title", ""),
        "calls": calls,
        "summary": _summarize(calls),
    }
    _run.set(None)
    return result


def stash_run() -> list[dict]:
    """Save call list and clear the active run (batch pipeline helper)."""
    run = _active()
    if not run:
        return []
    calls = list(run.get("calls", []))
    _run.set(None)
    return calls


def merge_summaries(a: dict, b: dict) -> dict:
    """Merge two summary dicts (lifetime totals)."""
    if not a:
        return dict(b)
    if not b:
        return dict(a)
    out = dict(a)
    for key in (
        "gemini_calls", "anthropic_calls", "anthropic_batch_calls", "groq_calls",
        "tavily_searches", "youtube_api_calls",
        "total_input_tokens_est", "total_output_tokens_est",
    ):
        out[key] = a.get(key, 0) + b.get(key, 0)
    out["tavily_credits_est"] = round(
        a.get("tavily_credits_est", 0) + b.get("tavily_credits_est", 0), 1
    )
    out["cost_usd_est"] = round(a.get("cost_usd_est", 0) + b.get("cost_usd_est", 0), 4)
    out["videos_processed"] = a.get("videos_processed", 0) + b.get("videos_processed", 0)
    return out


def add_to_lifetime(usage: dict) -> dict:
    """Persist lifetime totals via db meta. Returns updated lifetime summary."""
    import db

    summary = usage.get("summary", {})
    if not summary:
        return {}
    summary = dict(summary)
    summary["videos_processed"] = 1

    with _lock:
        raw = db.get_meta("usage_lifetime", "{}")
        try:
            lifetime = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            lifetime = {}
        prev = lifetime.get("summary", {})
        lifetime["summary"] = merge_summaries(prev, summary)
        lifetime["last"] = {
            "video_id": usage.get("video_id", ""),
            "title": usage.get("title", ""),
            "summary": summary,
            "calls": usage.get("calls", []),
        }
        db.set_meta("usage_lifetime", json.dumps(lifetime, ensure_ascii=False))
        return lifetime["summary"]


def get_lifetime() -> dict:
    import db

    raw = db.get_meta("usage_lifetime", "{}")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def get_last_run() -> dict:
    """Most recently processed video usage (summary + call log)."""
    return get_lifetime().get("last", {})


def parse_usage(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
