"""InsightEngine — YouTube insight extraction dashboard."""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone

import streamlit as st

import config
from components.ui_shell import render_app
from components.ui_styles import global_css
from components import stitch_components as stitch
import db
from background_jobs import is_worker_running, start_poll_background, start_process_one_background
from batch_process import queue_pending_for_batch, run_batch
from components.timeline import render_timeline
from errors import classify_error
from export import export_video_markdown
from poll import process_one
from search import search_insights
from usage_tracker import get_last_run, get_lifetime, parse_usage

db.init_db()

AGENDA_EXAMPLE = """• Focus mainly on the tech stack discussed
• How to get a remote job in this field
• Best sources and platforms for remote jobs
• What salary or pay range they mention"""

STATUS_META = {
    db.STATUS_AWAITING_AGENDA: ("Needs agenda", "agenda"),
    db.STATUS_PROCESSING: ("Processing", "processing"),
    db.STATUS_DONE: ("Done", "done"),
    db.STATUS_FAILED: ("Failed", "failed"),
    db.STATUS_PENDING: ("Pending", "pending"),
    db.STATUS_BATCH_QUEUED: ("Batch queued", "batch"),
}

PIPELINE_STEPS = [
    "Transcription",
    "Knowledge graph",
    "Web research",
    "Holistic extraction",
]

PLAYLIST_META = {
    db.PLAYLIST_GENERAL: ("General", "#6366f1"),
    db.PLAYLIST_PODCAST: ("Podcast", "#a855f7"),
}


def _usage_summary_lines(summary: dict) -> list[str]:
    if not summary:
        return ["No usage recorded yet."]
    lines = [
        f"**Tavily:** {summary.get('tavily_searches', 0)} searches "
        f"(~{summary.get('tavily_credits_est', 0)} credits)",
        f"**Gemini:** {summary.get('gemini_calls', 0)} calls",
        f"**Anthropic:** {summary.get('anthropic_calls', 0)} live · "
        f"{summary.get('anthropic_batch_calls', 0)} batch",
        f"**Groq:** {summary.get('groq_calls', 0)} calls",
        f"**YouTube API:** {summary.get('youtube_api_calls', 0)} units",
    ]
    cost = summary.get("cost_usd_est", 0)
    if cost:
        lines.append(f"**Est. cost:** ${cost:.4f} (Anthropic only)")
    else:
        lines.append("**Est. cost:** $0 (Gemini/Groq free tier)")
    return lines


def _render_usage_sidebar_metrics(summary: dict) -> None:
    if not summary:
        st.caption("Process a video to see usage here.")
        return
    c1, c2 = st.columns(2)
    c1.metric("Tavily", summary.get("tavily_searches", 0))
    c2.metric("Credits (est.)", summary.get("tavily_credits_est", 0))
    c3, c4 = st.columns(2)
    c3.metric("Gemini", summary.get("gemini_calls", 0))
    c4.metric("Groq", summary.get("groq_calls", 0))
    c5, c6 = st.columns(2)
    c5.metric("Anthropic", summary.get("anthropic_calls", 0) + summary.get("anthropic_batch_calls", 0))
    c6.metric("YouTube", summary.get("youtube_api_calls", 0))


def _render_usage_main_panel(video: dict) -> None:
    """Full API usage block at the bottom of a done video page."""
    video_usage = parse_usage(video.get("usage_data", ""))
    usage_summary = video_usage.get("summary", {})
    st.markdown('<div class="section-head">API usage</div>', unsafe_allow_html=True)
    if not usage_summary:
        st.markdown(
            '<div class="usage-panel empty">'
            '<p class="usage-empty">No usage recorded for this video yet. '
            "<strong>Re-process</strong> once to capture Tavily, LLM, and YouTube stats.</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    cost = usage_summary.get("cost_usd_est", 0)
    cost_label = f"${cost:.4f} est." if cost else "Free tier"
    st.markdown(
        f'<div class="usage-panel">'
        f'<div class="usage-sub">This run · {cost_label}</div></div>',
        unsafe_allow_html=True,
    )
    u1, u2, u3, u4 = st.columns(4)
    u1.metric("Tavily searches", usage_summary.get("tavily_searches", 0))
    u2.metric("Tavily credits (est.)", usage_summary.get("tavily_credits_est", 0))
    u3.metric("Gemini calls", usage_summary.get("gemini_calls", 0))
    u4.metric("Groq calls", usage_summary.get("groq_calls", 0))
    a1, a2, a3 = st.columns(3)
    a1.metric("Anthropic live", usage_summary.get("anthropic_calls", 0))
    a2.metric("Anthropic batch", usage_summary.get("anthropic_batch_calls", 0))
    a3.metric("YouTube API units", usage_summary.get("youtube_api_calls", 0))

    calls = video_usage.get("calls", [])
    if calls:
        guest = sum(1 for c in calls if c.get("provider") == "tavily" and c.get("operation") == "guest")
        topic = sum(1 for c in calls if c.get("provider") == "tavily" and c.get("operation") == "topic")
        entity = sum(1 for c in calls if c.get("provider") == "tavily" and c.get("operation") == "entity")
        if guest or topic or entity:
            st.caption(f"Tavily breakdown · guest {guest} · topics {topic} · entities {entity}")

    with st.expander("Call log", expanded=False):
        _render_usage_call_log(calls)


def _render_usage_call_log(calls: list[dict]) -> None:
    if not calls:
        st.caption("No call log for this run.")
        return
    for i, call in enumerate(calls, 1):
        provider = call.get("provider", "?")
        op = call.get("operation", "")
        if provider == "tavily":
            st.caption(f'{i}. Tavily · {op} · "{call.get("query", "")[:60]}" · ~{call.get("credits_est", 2)} cr')
        elif provider == "youtube":
            st.caption(f"{i}. YouTube · {call.get('operation', 'api')}")
        else:
            model = call.get("model", "")
            batch = " (batch)" if call.get("batch") else ""
            in_t = call.get("input_tokens_est", 0)
            out_t = call.get("output_tokens_est", 0)
            st.caption(f"{i}. {provider}/{model}{batch} · {op} · ~{in_t}+{out_t} tok")


def _format_time(iso_str: str) -> str:
    if not iso_str:
        return "never"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%b %d, %H:%M")
    except ValueError:
        return iso_str


def _thumbnail(video_id: str) -> str:
    return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"


def _esc(text: str) -> str:
    return html.escape(text or "")


def _status_pill(status: str) -> str:
    label, css_class = STATUS_META.get(status, ("Unknown", "pending"))
    return f'<span class="status-pill {css_class}">{_esc(label)}</span>'


def _type_pill(playlist_type: str) -> str:
    label, color = PLAYLIST_META.get(playlist_type, ("Video", "#64748b"))
    return f'<span class="status-pill" style="background:rgba(99,102,241,0.15);color:{color}">{_esc(label)}</span>'


def _parse_research_data(video: dict) -> dict:
    research_raw = video.get("research_data", "")
    if not research_raw:
        return {}
    try:
        return json.loads(research_raw) if isinstance(research_raw, str) else research_raw
    except (json.JSONDecodeError, TypeError):
        return {}


def _render_bullets(items: list[str]) -> None:
    if not items:
        return
    rows = "".join(
        f'<li class="simple-bullet">{_esc(item)}</li>' for item in items if item.strip()
    )
    st.markdown(f'<ul class="simple-list">{rows}</ul>', unsafe_allow_html=True)


def _get_links_bundle(video: dict) -> dict:
    structured = db.parse_structured_insights(video.get("structured_insights", "{}"))
    links = structured.get("links")
    if links and any(links.get(k) for k in ("from_video", "from_description", "from_research")):
        return links
    research = _parse_research_data(video)
    legacy = research.get("links")
    if isinstance(legacy, dict):
        return legacy
    flat = _collect_research_links(research)
    return {"from_video": [], "from_description": [], "from_research": flat}


def _get_resources(video: dict) -> list[dict]:
    structured = db.parse_structured_insights(video.get("structured_insights", "{}"))
    resources = structured.get("resources", [])
    return resources if isinstance(resources, list) else []


def _render_links_grouped(links: dict) -> None:
    groups = [
        ("from_video", "From video"),
        ("from_description", "From description"),
        ("from_research", "From web research"),
    ]
    total = sum(len(links.get(key, [])) for key, _ in groups)
    st.markdown('<div class="section-head">Links</div>', unsafe_allow_html=True)
    if total == 0:
        st.caption("No links found. Re-process after setting YOUTUBE_API_KEY (description links need one API call).")
        return

    for key, label in groups:
        items = links.get(key, [])
        if not items:
            continue
        st.markdown(f"**{label}**")
        for link in items[:20]:
            title = link.get("title") or link.get("url", "Link")
            url = link.get("url", "")
            confidence = link.get("confidence", "")
            badge = ""
            if confidence == "likely":
                badge = ' <span class="likely-badge">Likely match</span>'
            if url:
                st.markdown(
                    f'<a class="link-row" href="{_esc(url)}" target="_blank" rel="noopener">'
                    f'{_esc(title)}</a>{badge}',
                    unsafe_allow_html=True,
                )


def _render_resources(resources: list[dict]) -> None:
    st.markdown('<div class="section-head">Resources</div>', unsafe_allow_html=True)
    if not resources:
        st.caption("Books, tools, companies, and people mentioned will appear here after processing.")
        return
    for res in resources[:40]:
        name = res.get("name", "Unknown")
        rtype = res.get("type", "")
        detail = res.get("detail", "")
        source = res.get("source", "")
        url = res.get("url")
        meta = " · ".join(x for x in [rtype, source] if x)
        line = f"<strong>{_esc(name)}</strong>"
        if meta:
            line += f' <span class="res-meta">({_esc(meta)})</span>'
        if detail:
            line += f"<br><span class='res-detail'>{_esc(detail)}</span>"
        if url:
            line += f'<br><a class="res-link" href="{_esc(url)}" target="_blank">{_esc(url)}</a>'
        st.markdown(f'<div class="resource-row">{line}</div>', unsafe_allow_html=True)


def _collect_research_links(research_data: dict) -> list[dict]:
    links = research_data.get("links", [])
    if isinstance(links, dict):
        flat = []
        for group in links.values():
            flat.extend(group)
        return flat
    if links:
        return links
    seen: set[str] = set()
    collected: list[dict] = []
    for block in [research_data.get("guest", {})] + research_data.get("topics", []):
        for src in block.get("sources", []):
            url = src.get("url", "")
            if url and url not in seen:
                seen.add(url)
                collected.append(src)
    return collected


def _render_web_research(research_data: dict) -> None:
    guest = research_data.get("guest", {})
    topics = research_data.get("topics", [])
    has_guest = bool(guest.get("bio") or guest.get("viral_things") or guest.get("discussions"))
    has_topics = any(
        t.get("what_it_is") or t.get("notable") or t.get("hot_takes") for t in topics
    )
    if not has_guest and not has_topics:
        return

    with st.expander("Web research (optional background)", expanded=False):
        st.caption("Extra context from the web — not part of the video transcript.")
        if guest.get("bio"):
            st.markdown(
                f"""<div class="guest-card">
                    <div class="name">{_esc(guest.get('name', 'Guest'))}</div>
                    <p class="bio">{_esc(guest.get('bio', ''))}</p>
                </div>""",
                unsafe_allow_html=True,
            )
            extra = (guest.get("viral_things") or []) + (guest.get("discussions") or [])
            _render_bullets(extra)

        for td in topics:
            topic_name = td.get("topic", "")
            bullets = (td.get("notable") or []) + (td.get("hot_takes") or [])
            if not topic_name and not bullets:
                continue
            what = td.get("what_it_is", "")
            st.markdown(
                f"""<div class="topic-card">
                    <div class="name">{_esc(topic_name)}</div>
                    {f'<p class="desc">{_esc(what)}</p>' if what else ''}
                </div>""",
                unsafe_allow_html=True,
            )
            _render_bullets(bullets)


def _render_description_notes(research_data: dict) -> None:
    """General videos: description context without Tavily."""
    if not research_data or research_data.get("tavily_used") is True:
        return
    if research_data.get("guest", {}).get("bio") or research_data.get("topics"):
        return
    excerpt = research_data.get("description_excerpt") or research_data.get("combined_summary", "")
    if not excerpt.strip():
        return
    with st.expander("Description notes", expanded=False):
        st.caption("Parsed from the YouTube description — no Tavily credits used.")
        st.markdown(f'<div class="summary-card">{_esc(excerpt[:3000])}</div>', unsafe_allow_html=True)


def _channel_name(video: dict) -> str:
    name = (video.get("channel_name") or "").strip()
    if name:
        return name
    research = _parse_research_data(video)
    name = (research.get("channel_title") or "").strip()
    if name:
        return name
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if api_key and video.get("video_id"):
        try:
            from video_metadata import fetch_video_snippet
            return fetch_video_snippet(video["video_id"]).get("channel_title", "")
        except Exception:
            pass
    return ""


def _render_insights(summary: str, points: list[str], *, podcast: bool = False) -> None:
    if summary:
        card = "summary-card podcast" if podcast else "summary-card"
        st.markdown(f'<div class="{card}">{_esc(summary)}</div>', unsafe_allow_html=True)
    if not points:
        st.caption("No insights extracted.")
        return
    kp_class = "insight-point podcast" if podcast else "insight-point"
    point_num = 0
    for point in points:
        if point.startswith("==") or point.startswith("--"):
            is_priority = point.startswith("==")
            st.markdown(
                f'<div class="cluster-head {"priority" if is_priority else ""}">'
                f'{_esc(point[3:].strip())}</div>',
                unsafe_allow_html=True,
            )
        elif point.startswith("\U0001f4cc") or point.startswith("\U0001f4a1"):
            st.markdown(
                f'<div class="cluster-head {"priority" if point.startswith("\U0001f4cc") else ""}">'
                f'{_esc(point)}</div>',
                unsafe_allow_html=True,
            )
        else:
            point_num += 1
            st.markdown(
                f'<div class="{kp_class}">'
                f'<span class="point-num">{point_num}</span>'
                f'<span class="point-text">{_esc(point)}</span></div>',
                unsafe_allow_html=True,
            )


def _format_timestamp_label(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    sec = int(seconds)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _timestamp_url(video_id: str, seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    return f"https://www.youtube.com/watch?v={video_id}&t={int(seconds)}s"


def _render_insight_cards(video_id: str, structured: dict, *, podcast: bool = False) -> None:
    summary = structured.get("summary", "")
    if summary:
        st.markdown(f'<div class="summary-card">{_esc(summary)}</div>', unsafe_allow_html=True)
    insights = structured.get("insights") or []
    if not insights:
        st.caption("No insight clusters yet.")
        return
    for idx, cluster in enumerate(insights, 1):
        topic = cluster.get("topic") or cluster.get("title") or "Insight"
        if cluster.get("is_agenda_item"):
            topic = f"📌 {topic}"
        points = [str(p) for p in (cluster.get("points") or []) if str(p).strip()]
        body = " ".join(points) if points else topic
        tags = cluster.get("tags") or stitch.infer_tags(topic.replace("📌 ", ""))
        ts_label = _format_timestamp_label(cluster.get("timestamp_seconds"))
        ts_url = _timestamp_url(video_id, cluster.get("timestamp_seconds"))
        st.markdown(
            stitch.insight_card_stitch(
                index=idx,
                title=topic,
                body=body,
                timestamp_label=ts_label,
                timestamp_url=ts_url,
                tags=tags if isinstance(tags, list) else [],
            ),
            unsafe_allow_html=True,
        )


def _render_structured_insights(
    video_id: str,
    structured: dict,
    *,
    podcast: bool = False,
    show_timeline: bool = True,
) -> None:
    """Unified Insights tab: timeline map + tag-less cards."""
    insights = structured.get("insights") or []
    duration = int(structured.get("duration_seconds") or 0)
    if show_timeline and insights and duration:
        render_timeline(video_id, duration, insights)
    _render_insight_cards(video_id, structured, podcast=podcast)


def _video_duration_label(video: dict) -> str:
    structured = db.parse_structured_insights(video.get("structured_insights", "{}"))
    duration = int(structured.get("duration_seconds") or 0)
    if duration:
        return _format_timestamp_label(duration)
    return ""


def _filter_library_videos(videos: list[dict]) -> list[dict]:
    filtered = videos
    vf = st.session_state.get("view_filter", "all")
    if vf != "all":
        filtered = [v for v in filtered if v.get("playlist_type") == vf]
    sf = st.session_state.get("status_filter", "all")
    if sf != "all":
        filtered = [v for v in filtered if v.get("status") == sf]
    sort_order = st.session_state.get("sort_order", "newest")
    if sort_order == "oldest":
        filtered = sorted(filtered, key=lambda v: v.get("added_at") or "")
    elif sort_order == "title":
        filtered = sorted(filtered, key=lambda v: (v.get("title") or "").lower())
    else:
        filtered = sorted(filtered, key=lambda v: v.get("added_at") or "", reverse=True)
    return filtered


def _empty_state(title: str, body: str) -> None:
    st.markdown(
        f'<div class="empty-state"><h3>{_esc(title)}</h3><p>{_esc(body)}</p></div>',
        unsafe_allow_html=True,
    )


def _step_pills(active_step: int = 1) -> str:
    pills = []
    for i, name in enumerate(PIPELINE_STEPS):
        if i < active_step:
            suffix, color, border = " (done)", "#2ECC71", "rgba(46,204,113,0.4)"
        elif i == active_step:
            suffix, color, border = " ...", "#6C5CE7", "#6C5CE7"
        else:
            suffix, color, border = "", "#94A3B8", "#2A2A42"
        pills.append(
            f'<span style="padding:6px 12px;border-radius:999px;font-size:12px;margin-right:8px;'
            f'border:1px solid {border};color:{color};display:inline-block">'
            f'{_esc(name)}{suffix}</span>'
        )
    return '<div style="margin:1rem 0">' + "".join(pills) + "</div>"



def _has_manual_insights(video: dict) -> bool:
    manual_pts = db.parse_key_points(video.get("manual_key_points", "[]"))
    return bool(video.get("manual_summary", "").strip() or manual_pts)


def _status_stitch_key(status: str) -> tuple[str, str]:
    mapping = {
        db.STATUS_DONE: ("done", "Done"),
        db.STATUS_PROCESSING: ("processing", "Researching..."),
        db.STATUS_PENDING: ("pending", "Pending"),
        db.STATUS_FAILED: ("failed", "Failed"),
        db.STATUS_AWAITING_AGENDA: ("pending", "Needs agenda"),
        db.STATUS_BATCH_QUEUED: ("pending", "Batch queued"),
    }
    return mapping.get(status, ("pending", "Unknown"))


def _render_video_list_card(v: dict, *, key_prefix: str = "lib") -> None:
    selected = v["video_id"] == st.session_state.get("selected_id")
    channel = _channel_name(v) or "Unknown"
    duration = _video_duration_label(v)
    meta = f"{channel} · {duration}" if duration else channel
    sk, slabel = _status_stitch_key(v["status"])
    row_html = stitch.library_row(
        title=v["title"],
        meta=meta,
        thumb_url=_thumbnail(v["video_id"]),
        status=sk,
        status_label=slabel,
        selected=selected,
        processing=v["status"] == db.STATUS_PROCESSING,
    )
    st.markdown(
        f'<div class="stitch-lib-wrap">{row_html}</div>',
        unsafe_allow_html=True,
    )
    if st.button(
        "\u200b",
        key=f"{key_prefix}_{v['video_id']}",
        use_container_width=True,
        type="secondary",
    ):
        st.session_state.selected_id = v["video_id"]
        if st.session_state.get("active_page") == "queue":
            st.session_state.active_page = "library"
            st.session_state.top_nav = "library"
        st.rerun()


def _playlist_display_name(video: dict) -> str:
    pid = video.get("playlist_id")
    if pid:
        pl = db.get_playlist(pid)
        if pl and pl.get("name"):
            return pl["name"]
    return _channel_name(video) or "Library"


def _stitch_token_panel_html(video: dict) -> str:
    video_usage = parse_usage(video.get("usage_data", ""))
    summary = video_usage.get("summary", {})
    cost = summary.get("cost_usd_est", 0) or 0
    cost_str = f"${cost:.2f}"
    rows: list[tuple[str, str]] = []
    groq = summary.get("groq_calls", 0)
    gemini = summary.get("gemini_calls", 0)
    anthropic = summary.get("anthropic_calls", 0) + summary.get("anthropic_batch_calls", 0)
    tavily = summary.get("tavily_searches", 0)
    if groq:
        rows.append(("Transcription", f"~{groq * 4}k tokens"))
    if gemini:
        rows.append(("Entity Extraction", f"{gemini} Gemini calls"))
    if anthropic:
        rows.append(("Insight Generation", f"{anthropic} Anthropic calls"))
    if tavily:
        rows.append(("Web Research", f"{tavily} Tavily searches"))
    if not rows:
        rows.append(("Pipeline", "Re-process to capture usage"))
    return stitch.token_usage_panel(cost_str, rows)


def _insight_tab_count(video: dict, structured: dict) -> int:
    insights = structured.get("insights") or []
    if insights:
        return len(insights)
    pts = db.parse_key_points(video.get("key_points", "[]"))
    return len(pts) + (1 if video.get("summary", "").strip() else 0)


def _render_detail_header(video: dict) -> None:
    channel = _channel_name(video)
    pl_label = _playlist_display_name(video)
    eyebrow = _esc(pl_label)
    if channel and channel != pl_label:
        eyebrow += f" &bull; {_esc(channel)}"
    st.markdown(
        f'<div class="stitch-detail-header">'
        f'<div class="stitch-detail-eyebrow">{eyebrow}</div>'
        f'<h2 class="stitch-detail-title">{_esc(video["title"])}</h2></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="stitch-action-row">'
        f'<a class="stitch-action-watch" href="{_esc(video["url"])}" target="_blank" rel="noopener">'
        f'<span class="material-symbols-outlined play-icon">play_circle</span>'
        f'Watch on YouTube</a>'
        f'<a class="stitch-action-export" href="#" onclick="return false;">'
        f'<span class="material-symbols-outlined" style="font-size:18px">share</span>'
        f'Export</a></div>',
        unsafe_allow_html=True,
    )
    a1, a2 = st.columns([1, 1])
    with a1:
        if video["status"] == db.STATUS_DONE:
            md_content = export_video_markdown(video)
            safe_title = "".join(
                c if c.isalnum() or c in " -_" else "_" for c in video["title"]
            )[:50].strip()
            st.download_button(
                "Download .md",
                data=md_content,
                file_name=f"{safe_title or video['video_id']}_insights.md",
                mime="text/markdown",
                key=f"export_{video['video_id']}",
                use_container_width=True,
            )
    with a2:
        _render_video_actions_secondary(video)


def _render_video_actions_secondary(video: dict) -> None:
    """Process / retry controls shown beside Watch & Export."""
    if video["status"] == db.STATUS_DONE:
        if st.button("Re-process", key=f"reprocess_{video['video_id']}"):
            db.upsert_video(video["video_id"], status=db.STATUS_PENDING, error_message="")
            ok, msg = start_process_one_background(video["video_id"])
            st.toast(msg)
            st.rerun()
    elif video["status"] == db.STATUS_PENDING:
        if st.button("Process now", type="primary", key=f"process_{video['video_id']}"):
            ok, msg = start_process_one_background(video["video_id"])
            st.toast(msg)
            st.rerun()
    elif video["status"] in (db.STATUS_AWAITING_AGENDA, db.STATUS_FAILED):
        label = "Process now" if video["status"] == db.STATUS_AWAITING_AGENDA else "Retry"
        if st.button(label, type="primary", key=f"retry_{video['video_id']}"):
            db.upsert_video(video["video_id"], status=db.STATUS_PENDING, error_message="")
            ok, msg = start_process_one_background(video["video_id"])
            st.toast(msg)
            st.rerun()
    elif video["status"] == db.STATUS_PROCESSING:
        if st.button("Reset stuck", key=f"reset_{video['video_id']}"):
            db.upsert_video(video["video_id"], status=db.STATUS_PENDING, error_message="")
            st.rerun()


def _render_video_actions(video: dict) -> None:
    """Podcast-only extras; Watch/Export live in _render_detail_header."""
    is_podcast = video.get("playlist_type") == db.PLAYLIST_PODCAST
    if is_podcast and video["status"] == db.STATUS_DONE:
        with st.expander("Custom agenda override", expanded=False):
            agenda_key = f"agenda_{video['video_id']}"
            if agenda_key not in st.session_state:
                st.session_state[agenda_key] = video.get("user_agenda") or ""
            agenda = st.text_area(
                "Custom agenda",
                height=120,
                placeholder=AGENDA_EXAMPLE,
                label_visibility="collapsed",
                key=agenda_key,
            )
            c_a, c_b = st.columns(2)
            with c_b:
                if st.button("Use example", key=f"ex_{video['video_id']}"):
                    st.session_state[agenda_key] = AGENDA_EXAMPLE
                    st.rerun()
            with c_a:
                if st.button("Generate custom insights", type="primary", key=f"custom_{video['video_id']}"):
                    if not agenda.strip():
                        st.warning("Write your custom agenda first.")
                    else:
                        db.upsert_video(
                            video["video_id"],
                            user_agenda=agenda.strip(),
                            status=db.STATUS_PENDING,
                            error_message="",
                        )
                        ok, msg = start_process_one_background(video["video_id"], manual=True)
                        st.toast(msg)
                        st.rerun()


def _render_video_detail(video: dict) -> None:
    is_podcast = video.get("playlist_type") == db.PLAYLIST_PODCAST
    _render_detail_header(video)

    if video["status"] == db.STATUS_FAILED:
        err = classify_error(video.get("error_message", ""))
        st.markdown(
            f'<div style="background:rgba(231,76,60,0.08);border:1px solid rgba(231,76,60,0.25);'
            f'border-radius:8px;padding:1rem 1.25rem;margin-bottom:1rem">'
            f'<h4 style="color:#E74C3C;margin:0 0 6px">{_esc(err["title"])}</h4>'
            f'<p>{_esc(err["message"])}</p>'
            f'<p style="margin-top:8px">Tip: {_esc(err["fix"])}</p></div>',
            unsafe_allow_html=True,
        )
        with st.expander("Raw error"):
            st.code(err.get("raw", "No details"))
        return

    if video["status"] == db.STATUS_PROCESSING:
        st.caption("Processing in background — step pills update when the worker runs.")
        st.markdown(_step_pills(active_step=1), unsafe_allow_html=True)
        return

    if video["status"] == db.STATUS_AWAITING_AGENDA:
        st.info("Click **Process now** to auto-generate insights from your profile.")
        return

    if video["status"] == db.STATUS_PENDING:
        st.info("Queued for processing. Click **Process now** or poll the queue.")
        return

    if video["status"] != db.STATUS_DONE:
        return

    structured = db.parse_structured_insights(video.get("structured_insights", "{}"))
    has_manual = _has_manual_insights(video)
    general_summary = video.get("summary", "")
    general_points = db.parse_key_points(video.get("key_points", "[]"))
    manual_summary = video.get("manual_summary", "")
    manual_points = db.parse_key_points(video.get("manual_key_points", "[]"))
    insight_n = _insight_tab_count(video, structured)

    st.markdown(_stitch_token_panel_html(video), unsafe_allow_html=True)
    _render_video_actions(video)

    auto_agenda = video.get("auto_agenda", "")
    if auto_agenda:
        label = "Auto-generated focus" if is_podcast else "Auto-generated agenda"
        st.markdown(f'<div class="section-head">{label}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="agenda-display">{_esc(auto_agenda)}</div>', unsafe_allow_html=True)

    tab_insights, tab_timeline, tab_research, tab_resources, tab_chat = st.tabs(
        [
            f"Insights ({insight_n})" if insight_n else "Insights",
            "Timeline",
            "Research",
            "Resources",
            "Chat",
        ]
    )

    with tab_insights:
        if is_podcast and has_manual:
            sub_general, sub_custom = st.tabs(["General", "Custom agenda"])
            with sub_general:
                if structured.get("insights"):
                    _render_insight_cards(video["video_id"], structured, podcast=True)
                else:
                    _render_insights(general_summary, general_points, podcast=True)
            with sub_custom:
                _render_insights(manual_summary, manual_points, podcast=True)
        elif structured.get("insights"):
            _render_insight_cards(video["video_id"], structured, podcast=is_podcast)
        else:
            _render_insights(general_summary, general_points, podcast=is_podcast)
        src = video.get("transcript_source") or "—"
        st.caption(f"Transcript source: {src}")

    with tab_timeline:
        insights = structured.get("insights") or []
        duration = int(structured.get("duration_seconds") or 0)
        if insights and duration:
            render_timeline(video["video_id"], duration, insights)
        else:
            st.caption("Timeline appears after structured insights are generated.")

    with tab_research:
        if is_podcast:
            research_data = _parse_research_data(video)
            guest = research_data.get("guest", {})
            topics = research_data.get("topics", [])
            if guest.get("bio"):
                st.markdown(
                    f'<div class="guest-card"><div class="name">{_esc(guest.get("name", "Guest"))}</div>'
                    f'<p class="bio">{_esc(guest.get("bio", ""))}</p></div>',
                    unsafe_allow_html=True,
                )
                _render_bullets((guest.get("viral_things") or []) + (guest.get("discussions") or []))
            for td in topics:
                topic_name = td.get("topic", "")
                if not topic_name:
                    continue
                what = td.get("what_it_is", "")
                desc = f'<p class="desc">{_esc(what)}</p>' if what else ""
                st.markdown(
                    f'<div class="topic-card"><div class="name">{_esc(topic_name)}</div>{desc}</div>',
                    unsafe_allow_html=True,
                )
                _render_bullets((td.get("notable") or []) + (td.get("hot_takes") or []))
            if not guest.get("bio") and not topics:
                st.caption("No web research for this video.")
        else:
            rd = _parse_research_data(video)
            excerpt = rd.get("description_excerpt") or rd.get("combined_summary", "")
            if excerpt.strip():
                st.caption("Parsed from the YouTube description — no Tavily credits used.")
                st.markdown(f'<div class="summary-card">{_esc(excerpt[:3000])}</div>', unsafe_allow_html=True)
            else:
                st.caption("No description notes for this video.")

    with tab_resources:
        _render_resources(_get_resources(video))
        _render_links_grouped(_get_links_bundle(video))

    with tab_chat:
        st.markdown('<div class="stitch-chat-footer">', unsafe_allow_html=True)
        st.caption("Ask anything — the full transcript is used as context.")
        chat_key = f"chat_{video['video_id']}"
        if chat_key not in st.session_state:
            st.session_state[chat_key] = []
        for msg in st.session_state[chat_key]:
            if msg["role"] == "user":
                st.markdown(
                    f'<div class="kp" style="border-left:3px solid var(--accent)">'
                    f'<span>{_esc(msg["content"])}</span></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f'<div class="summary-card">{_esc(msg["content"])}</div>', unsafe_allow_html=True)
        user_q = st.text_input(
            "Ask",
            placeholder="What did they say about…?",
            key=f"chat_input_{video['video_id']}",
            label_visibility="collapsed",
        )
        c1, c2 = st.columns([1, 4])
        with c1:
            send = st.button("Ask", key=f"chat_send_{video['video_id']}", type="primary")
        with c2:
            if st.session_state[chat_key] and st.button("Clear", key=f"chat_clear_{video['video_id']}"):
                st.session_state[chat_key] = []
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        if send and user_q.strip():
            st.session_state[chat_key].append({"role": "user", "content": user_q.strip()})
            with st.spinner("Thinking…"):
                from pipeline import chat_with_video

                answer = chat_with_video(
                    video["video_id"],
                    user_q.strip(),
                    chat_history=st.session_state[chat_key][:-1],
                )
            st.session_state[chat_key].append({"role": "assistant", "content": answer})
            st.rerun()


def _render_search_panel(all_videos: list[dict]) -> None:
    search_query = st.session_state.get("global_search", "")
    if not search_query.strip():
        st.caption("Search insight text across all processed videos.")
        return
    min_score = st.session_state.get("search_min_score", 0.0)
    results = search_insights(search_query.strip())
    results = [r for r in results if r["score"] >= min_score]
    if st.session_state.get("search_playlist_only") and st.session_state.get("selected_id"):
        sel_pl = next(
            (v.get("playlist_id") for v in all_videos if v["video_id"] == st.session_state.selected_id),
            None,
        )
        if sel_pl:
            allowed = {v["video_id"] for v in all_videos if v.get("playlist_id") == sel_pl}
            results = [r for r in results if r["video_id"] in allowed]
    if not results:
        st.caption("No matching insights found.")
        return
    for r in results[:20]:
        vid_row = db.get_video(r["video_id"])
        vtitle = vid_row["title"] if vid_row else "Unknown"
        score_pct = int(r["score"] * 100)
        ts = r.get("timestamp_seconds")
        ts_str = f" · {_format_timestamp_label(ts)}" if ts is not None else ""
        preview = r["chunk_text"]
        if len(preview) > 180:
            preview = preview[:180] + "…"
        st.markdown(
            f'<div class="ie-search-result">'
            f'<div class="ie-search-score">{score_pct}% match</div>'
            f'<strong style="color:var(--text)">{_esc(vtitle)}</strong> — {_esc(r["chunk_title"])}{ts_str}'
            f'<p style="color:var(--text-muted);font-size:13px;margin:6px 0 0">{_esc(preview)}</p></div>',
            unsafe_allow_html=True,
        )
        if st.button("Open in Library", key=f"sr_{r['video_id']}_{r.get('chunk_index', 0)}"):
            st.session_state.selected_id = r["video_id"]
            st.session_state.active_page = "library"
            st.session_state.show_search_panel = False
            st.rerun()


def _playlist_video_count(playlist_id: str, all_videos: list[dict]) -> int:
    return sum(1 for v in all_videos if v.get("playlist_id") == playlist_id)


def _render_playlists_page() -> None:
    all_videos = db.list_videos()
    hdr_left, hdr_right = st.columns([3, 1])
    with hdr_left:
        st.markdown(
            '<div style="margin-bottom:24px"><h2 style="font-size:20px;font-weight:600;margin:0 0 4px">Curation Engine</h2>'
            '<p style="color:#94A3B8;font-size:14px;margin:0">Manage your video collections and customize extraction logic per-playlist.</p></div>',
            unsafe_allow_html=True,
        )
    with hdr_right:
        st.markdown(
            '<div style="display:flex;justify-content:flex-end;padding-top:8px">'
            '<div class="stitch-view-toggle">'
            '<span class="stitch-view-btn active">Grid</span>'
            '<span class="stitch-view-btn">List</span>'
            '</div></div>',
            unsafe_allow_html=True,
        )
    if st.button("+ Add Playlist", type="primary", key="pl_add_top"):
        st.session_state.show_add_playlist = True

    playlists = db.list_playlists()
    sel = st.session_state.get("selected_playlist_id")
    if not sel and playlists:
        sel = playlists[0]["playlist_id"]
        st.session_state.selected_playlist_id = sel

    cols = st.columns(3)
    for i, pl in enumerate(playlists):
        pid = pl["playlist_id"]
        active = pid == sel
        count = _playlist_video_count(pid, all_videos)
        focus = pl.get("extraction_focus") or ""
        gradients = [
            "linear-gradient(135deg,#4029ba 0%,#1A1A2E 100%)",
            "linear-gradient(135deg,#6C5CE7 0%,#22223A 100%)",
            "linear-gradient(135deg,#2ECC71 0%,#1A1A2E 100%)",
            "linear-gradient(135deg,#F5A623 0%,#1A1A2E 100%)",
        ]
        updated = ""
        if not focus.strip():
            last_done = [v for v in all_videos if v.get("playlist_id") == pid and v.get("status") == db.STATUS_DONE]
            if last_done:
                updated = "Last updated recently"
        with cols[i % 3]:
            st.markdown(
                stitch.playlist_card(
                    name=pl.get("name", pid),
                    video_count=count,
                    focus=focus,
                    active=active,
                    thumb_gradient=gradients[i % len(gradients)],
                    updated_label=updated,
                ),
                unsafe_allow_html=True,
            )
            if st.button("Open", key=f"pl_pick_{pid}", use_container_width=True):
                st.session_state.selected_playlist_id = pid
                st.rerun()
            focus_key = f"pl_focus_{pid}"
            if focus_key not in st.session_state:
                st.session_state[focus_key] = focus
            if pid == sel:
                focus_val = st.text_area(
                    "Extraction focus",
                    key=focus_key,
                    height=100,
                    placeholder="Focus on technical architecture, schema discussions...",
                    label_visibility="collapsed",
                )
                if st.button("Save focus", key=f"save_pl_{pid}", type="primary", use_container_width=True):
                    db.upsert_playlist(pid, extraction_focus=focus_val)
                    st.toast("Saved")
                    st.rerun()

    st.markdown(
        '<div class="stitch-pl-add" style="margin-top:16px">'
        '<div style="width:56px;height:56px;border-radius:50%;background:rgba(42,42,66,0.6);'
        'display:flex;align-items:center;justify-content:center;margin-bottom:12px">'
        '<span class="material-symbols-outlined" style="font-size:28px;color:#5C5C70">add_box</span></div>'
        '<div style="font-weight:600;font-size:15px;color:#E8E8F0">Create New Playlist</div>'
        '<div style="font-size:13px;color:#94A3B8;margin-top:4px">Group related videos and set shared extraction rules.</div></div>',
        unsafe_allow_html=True,
    )
    if st.button("New playlist", key="pl_add_card"):
        st.session_state.show_add_playlist = True
        st.rerun()

    if st.session_state.get("show_add_playlist"):
        st.markdown("---")
        st.markdown("**Add playlist**")
        new_id = st.text_input("YouTube playlist ID", key="new_pl_id", placeholder="PLxxxx...")
        new_name = st.text_input("Display name", key="new_pl_name")
        new_kind = st.selectbox(
            "Type",
            [db.PLAYLIST_GENERAL, db.PLAYLIST_PODCAST],
            format_func=lambda k: "General" if k == db.PLAYLIST_GENERAL else "Podcast",
            key="new_pl_kind",
        )
        if st.button("Create", type="primary"):
            if new_id.strip():
                db.upsert_playlist(new_id.strip(), name=new_name.strip() or new_id.strip(), kind=new_kind)
                st.session_state.show_add_playlist = False
                st.session_state.selected_playlist_id = new_id.strip()
                st.toast("Playlist added")
                st.rerun()
            else:
                st.warning("Enter a playlist ID")


def _render_settings_page() -> None:
    profile = db.get_profile()
    lt = get_lifetime().get("summary", {})
    last_run = get_last_run()
    total_tokens = (
        lt.get("gemini_calls", 0) * 8000
        + lt.get("anthropic_calls", 0) * 12000
        + lt.get("groq_calls", 0) * 4000
    )
    used_label = f"{total_tokens // 1000}k" if total_tokens else "0"
    cost = lt.get("cost_usd_est", 0) or last_run.get("summary", {}).get("cost_usd_est", 0)
    cost_str = f"${cost:.2f}" if cost else "$0.00"

    left, right = st.columns(2, gap="large")
    gemini_calls = lt.get("gemini_calls", 0)
    groq_calls = lt.get("groq_calls", 0)

    with left:
        st.markdown('<h2 class="stitch-section-title">Profile</h2>', unsafe_allow_html=True)
        display_name = profile.get("display_name", "") or "InsightEngine User"
        st.markdown(
            f'<div class="stitch-profile-card">'
            f'<div class="stitch-avatar">'
            f'<span class="material-symbols-outlined" style="font-size:32px">person</span></div>'
            f'<div><div style="font-weight:600;font-size:16px;color:#E8E8F0">{_esc(display_name)}</div>'
            f'<div style="color:#94A3B8;font-size:13px;margin-top:2px">Researcher &bull; Free Tier</div>'
            f'<div style="margin-top:8px"><span style="padding:4px 14px;font-size:11px;font-weight:600;'
            f'background:#6C5CE7;color:#fff;border-radius:6px;cursor:pointer">Change Avatar</span></div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<p class="stitch-field-label">Full Name</p>', unsafe_allow_html=True)
        full_name = st.text_input(
            "Full Name",
            value=profile.get("display_name", ""),
            placeholder="Your name",
            key="settings_name",
            label_visibility="collapsed",
        )
        st.markdown('<p class="stitch-field-label">Email Address</p>', unsafe_allow_html=True)
        email_val = st.text_input(
            "Email",
            value=profile.get("email", ""),
            placeholder="you@example.com",
            key="settings_email",
            label_visibility="collapsed",
        )
        st.markdown('<p class="stitch-field-label">User Bio &amp; Global Extraction Interests</p>', unsafe_allow_html=True)
        bio = st.text_area(
            "Bio",
            value=profile.get("about_me", "") or profile.get("interests", ""),
            height=100,
            placeholder="e.g., Focus on market trends, competitive analysis, and emerging tech in the SaaS space...",
            key="settings_bio",
            label_visibility="collapsed",
        )
        st.markdown(
            '<div class="stitch-personalize-card">'
            '<div class="title">Personalize extractions using Profile Bio</div>'
            '<div class="desc">AI insights will prioritize topics matching these interests alongside core content.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        personalize = st.toggle(
            "Personalize extractions using Profile Bio",
            value=profile.get("personalize_extractions", True),
            key="settings_personalize",
        )

        st.markdown('<h2 class="stitch-section-title">API Configuration</h2>', unsafe_allow_html=True)
        st.markdown(
            '<p style="color:#94A3B8;font-size:13px;margin-bottom:16px">'
            'Connect your own provider keys to enable higher processing limits and specialized model access.</p>',
            unsafe_allow_html=True,
        )
        gemini_ok = bool(os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip())
        anthropic_ok = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
        groq_ok = bool(os.environ.get("GROQ_API_KEY", "").strip())
        tavily_ok = bool(os.environ.get("TAVILY_API_KEY", "").strip())
        providers = [
            ("Gemini API", gemini_ok),
            ("Anthropic API", anthropic_ok),
            ("Groq API", groq_ok),
            ("Tavily API", tavily_ok),
        ]
        for pname, pok in providers:
            badge_cls = "stitch-api-badge-ok" if pok else "stitch-api-badge-missing"
            badge_text = "CONNECTED" if pok else "NOT SET"
            mask_row = ""
            if pok:
                mask_row = (
                    '<div class="stitch-api-key-mask">'
                    '<span>••••••••••••••••••••</span>'
                    '<span class="material-symbols-outlined eye-icon">visibility_off</span></div>'
                )
            st.markdown(
                f'<div class="stitch-api-row">'
                f'<div class="stitch-api-icon"><span class="material-symbols-outlined">settings</span></div>'
                f'<span class="stitch-api-name">{_esc(pname)}</span>'
                f'<span class="{badge_cls}">{badge_text}</span></div>'
                f'{mask_row}',
                unsafe_allow_html=True,
            )
        if st.button("Save Changes", type="primary", key="save_settings"):
            db.set_profile({
                "display_name": full_name,
                "email": email_val,
                "about_me": bio,
                "interests": profile.get("interests", ""),
                "insight_style": profile.get("insight_style", ""),
                "known_topics": profile.get("known_topics", ""),
                "personalize_extractions": personalize,
            })
            st.toast("Profile saved")

    with right:
        st.markdown('<h2 class="stitch-section-title">Usage &amp; Tokens</h2>', unsafe_allow_html=True)
        pct = min(95, max(5, int(total_tokens / 25000 * 100))) if total_tokens else 8
        st.markdown(
            stitch.usage_meter(used_label, "2.5M", pct, cost_str),
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="stitch-cost-row">'
            f'<div class="label"><span class="material-symbols-outlined" style="font-size:18px">paid</span>'
            f' Estimated Month-to-Date Cost:</div>'
            f'<span class="stitch-cost-badge">{cost_str}</span></div>',
            unsafe_allow_html=True,
        )
        g1, g2 = st.columns(2)
        with g1:
            st.markdown(
                f'<div class="stitch-stat-box"><p class="stitch-label-caps">Gemini &mdash; Primary</p>'
                f'<div class="stitch-stat-val">{gemini_calls}</div>'
                f'<span class="stitch-stat-change up">calls this month</span></div>',
                unsafe_allow_html=True,
            )
        with g2:
            st.markdown(
                f'<div class="stitch-stat-box"><p class="stitch-label-caps">Groq &mdash; Fast Stream</p>'
                f'<div class="stitch-stat-val">{groq_calls}</div>'
                f'<span class="stitch-stat-change down">calls this month</span></div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:24px">'
            '<h2 class="stitch-section-title" style="margin:0;border:none;padding:0">Recent Activity Log</h2>'
            '<a class="stitch-log-export-link" href="#">'
            '<span class="material-symbols-outlined" style="font-size:14px">download</span> Export CSV</a></div>',
            unsafe_allow_html=True,
        )
        rows_html = ""
        for v in db.list_videos(status=db.STATUS_DONE)[:8]:
            vu = parse_usage(v.get("usage_data", ""))
            s = vu.get("summary", {})
            tok = s.get("gemini_calls", 0) * 800 + s.get("anthropic_calls", 0) * 1200
            cost_v = s.get("cost_usd_est", 0)
            ok_icon = '<span class="status-icon ok material-symbols-outlined" style="font-size:14px;color:#2ECC71;vertical-align:middle;margin-right:4px">check_circle</span>'
            rows_html += (
                f'<div class="stitch-log-row">'
                f'<span class="stitch-mono">{_esc(_format_time(v.get("processed_at","")))}</span>'
                f'<span class="stitch-mono">{ok_icon}VID-{_esc(v["video_id"][:8].upper())}</span>'
                f'<span class="stitch-mono">{tok:,}</span>'
                f'<span class="stitch-mono" style="text-align:right">${cost_v:.2f}</span></div>'
            )
        for v in db.list_videos(status=db.STATUS_FAILED)[:3]:
            fail_icon = '<span class="material-symbols-outlined" style="font-size:14px;color:#EF4444;vertical-align:middle;margin-right:4px">error</span>'
            rows_html += (
                f'<div class="stitch-log-row">'
                f'<span class="stitch-mono">{_esc(_format_time(v.get("processed_at","")))}</span>'
                f'<span class="stitch-mono">{fail_icon}VID-{_esc(v["video_id"][:8].upper())}</span>'
                f'<span class="stitch-mono">0</span>'
                f'<span class="stitch-mono" style="text-align:right">$0.00</span></div>'
            )
        st.markdown(
            f'<div class="stitch-log-table"><div class="stitch-log-head">'
            f'<span>Timestamp</span><span>Batch ID</span><span>Tokens</span><span style="text-align:right">Cost</span></div>'
            f"{rows_html or '<div class="stitch-log-row"><span>No activity yet</span></div>'}</div>",
            unsafe_allow_html=True,
        )
        with st.expander("Batch & advanced", expanded=False):
            if st.button("Queue pending for batch"):
                n = queue_pending_for_batch()
                st.toast(f"Queued {n}")
                st.rerun()
            if st.button("Run batch now"):
                result = run_batch()
                st.toast(result.get("message", "Done"))
                st.rerun()
            _render_usage_call_log(last_run.get("calls", []))


st.set_page_config(
    page_title="InsightEngine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(global_css(), unsafe_allow_html=True)

config_status = config.validate()
if not config_status["ok"]:
    with st.expander("Configuration issues detected", expanded=True):
        if config_status["missing_required"]:
            st.error(f"**Required keys missing:** {', '.join(config_status['missing_required'])}")
            st.caption("Add them to your `.env` file and restart the app.")
        for w in config_status.get("warnings", []):
            st.warning(w)
        if config_status["missing_recommended"]:
            st.info(
                f"**Recommended:** {', '.join(config_status['missing_recommended'])} — "
                "some features will be limited without these."
            )
        if config_status["missing_optional"]:
            st.caption(
                f"Optional: {', '.join(config_status['missing_optional'])} (podcast web research)"
            )

render_app({
    "esc": _esc,
    "status_pill": _status_pill,
    "type_pill": _type_pill,
    "thumbnail": _thumbnail,
    "channel_name": _channel_name,
    "format_time": _format_time,
    "format_timestamp_label": _format_timestamp_label,
    "video_duration_label": _video_duration_label,
    "filter_library_videos": _filter_library_videos,
    "empty_state": _empty_state,
    "step_pills": _step_pills,
    "render_video_list_card": _render_video_list_card,
    "render_video_detail": _render_video_detail,
    "render_search_panel": _render_search_panel,
    "render_playlists_page": _render_playlists_page,
    "render_settings_page": _render_settings_page,
    "agenda_example": AGENDA_EXAMPLE,
    "status_meta": STATUS_META,
    "pipeline_steps": PIPELINE_STEPS,
})
