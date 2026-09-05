"""Timeline density map — per docs/dev_handoff/developer_handoff.md."""

from __future__ import annotations

import html

import streamlit as st


def render_timeline(video_id: str, duration_seconds: int, insights: list[dict]) -> None:
    """Render 8px flex density bar with violet segments."""
    if not duration_seconds or not insights:
        return

    spans: list[tuple[float, float]] = []
    for ins in insights:
        start = ins.get("timestamp_seconds")
        if start is None:
            continue
        end = ins.get("timestamp_range_end") or (int(start) + 60)
        start_pct = max(0.0, (start / duration_seconds) * 100)
        end_pct = min(100.0, (end / duration_seconds) * 100)
        if end_pct > start_pct:
            spans.append((start_pct, end_pct - start_pct))

    if not spans:
        return

    spans.sort(key=lambda x: x[0])
    parts: list[str] = []
    cursor = 0.0
    for start_pct, width_pct in spans:
        gap = start_pct - cursor
        if gap > 0.05:
            parts.append(f'<div class="timeline-gap" style="width:{gap:.2f}%"></div>')
        parts.append(f'<div class="timeline-seg" style="width:{width_pct:.2f}%"></div>')
        cursor = start_pct + width_pct
    if cursor < 99.95:
        parts.append(f'<div class="timeline-gap" style="width:{100 - cursor:.2f}%"></div>')

    bar = f'<div class="timeline-density">{"".join(parts)}</div>'
    st.markdown(bar, unsafe_allow_html=True)
