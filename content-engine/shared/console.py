"""
Windows console safety.

Python on Windows defaults stdout to the legacy cp1252 code page, which raises
UnicodeEncodeError on arrows, checkmarks and em dashes. Every CLI entry point
calls init() first so the pipeline never dies on a log line.
"""
from __future__ import annotations

import sys


def init() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
