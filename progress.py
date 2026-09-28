"""Lets the pipeline announce its current step; the worker shows it on the dashboard."""

from __future__ import annotations

from typing import Callable

_reporter: Callable[[str], None] | None = None
_last = ""


def set_reporter(fn: Callable[[str], None] | None) -> None:
    global _reporter, _last
    _reporter = fn
    _last = ""


def report(step: str) -> None:
    global _last
    if _reporter is None or step == _last:
        return
    _last = step
    try:
        _reporter(step)
    except Exception:
        pass
