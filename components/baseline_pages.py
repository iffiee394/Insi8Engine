"""Library, queue and settings without iframe navigation or full-page reloads."""
from __future__ import annotations

import json

import streamlit as st

import db
import dbcache
import knowledge_store
from background_jobs import start_poll_background, start_process_one_background
from components.knowledge_pages import native_page_css, render_native_nav
from components.navigation import navigate, page_button
from errors import classify_error
from export import export_video_markdown
from knowledge_chat import safe_http_url, youtube_watch_url


# The reading layout needs more room than the single-column pages, and the
# video list should read as a list rather than a column of buttons.
_LIBRARY_CSS = """
<style>
[data-testid="stMainBlockContainer"], .block-container { max-width: 1180px !important; }
[class*="st-key-lib_pick_"] button {
    justify-content: flex-start !important; text-align: left !important;
    padding: 6px 10px !important; min-height: 0 !important; border: 0 !important;
    border-radius: 6px !important; font-size: 13px !important; font-weight: 400 !important;
    line-height: 1.35 !important;
}
/* Streamlit centres the label inside a full-width flex wrapper. */
[class*="st-key-lib_pick_"] button > div { justify-content: flex-start !important; width: 100% !important; }
[class*="st-key-lib_pick_"] button p { text-align: left !important; margin: 0 !important; }
[class*="st-key-lib_pick_"] { margin-bottom: 2px !important; }
</style>
"""


def _header(page: str, title: str) -> None:
    st.markdown(native_page_css(), unsafe_allow_html=True)
    if page == "library":
        st.markdown(_LIBRARY_CSS, unsafe_allow_html=True)
    render_native_nav(page)
    st.title(title)


def _refresh() -> None:
    dbcache.invalidate()


def _start(video_id: str) -> None:
    # Keep a failed job failed if another worker prevents this start.
    ok, message = start_process_one_background(video_id)
    st.toast(message)
    if ok:
        dbcache.invalidate()


def _transcript_recovery(video: dict) -> None:
    with st.expander("Use a transcript instead"):
        st.caption("On YouTube, open the video description → Show transcript. Copy the text here. "
                   "This skips the blocked download. Use text you are allowed to process.")
        with st.form(f"transcript_{video['video_id']}"):
            transcript = st.text_area("Transcript", height=180)
            save = st.form_submit_button("Save transcript")
        if save:
            if len(transcript.strip()) < 100:
                st.error("Paste the full transcript (at least 100 characters).")
            elif len(transcript) > 2_000_000:
                st.error("This transcript is too large. Use fewer than 2 million characters.")
            else:
                knowledge_store.upsert_transcript(
                    video["video_id"], plain_text=transcript.strip(), timed_segments=[],
                    source="user_transcript", timing_quality="unknown",
                )
                st.success("Transcript saved. Click Process video to extract insights.")


def _fmt_ts(seconds) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _select(video_id: str) -> None:
    st.session_state.selected_id = video_id


def _render_insights(video: dict, video_id: str) -> None:
    """Read the insights, without a click per topic.

    These are the reason the video was processed, so they render open. The
    supporting material stays folded away.
    """
    structured = db.parse_structured_insights(video.get("structured_insights") or "{}")
    summary = video.get("summary") or structured.get("summary") or ""
    if summary:
        st.markdown(summary)

    insights = [i for i in (structured.get("insights") or []) if isinstance(i, dict)]
    for item in insights:
        topic = item.get("topic") or item.get("title") or "Insight"
        seconds = item.get("timestamp_seconds")
        stamp = ""
        if isinstance(seconds, (int, float)) and seconds >= 0:
            stamp = f"  [{_fmt_ts(seconds)}]({youtube_watch_url(video_id, seconds)})"
        st.markdown(f"**{topic}**{stamp}")
        body = item.get("content") or item.get("insight") or ""
        if body:
            st.markdown(body)
        for point in item.get("points") or item.get("key_points") or []:
            st.markdown(f"- {point}")

    if not insights:
        points = db.parse_key_points(video.get("key_points") or "[]")
        for point in points:
            st.markdown(f"- {point}")
        if not points:
            st.caption("No insights were extracted for this video.")

    resources = structured.get("resources") or []
    links = structured.get("links") or {}
    if resources or links:
        with st.expander("Resources mentioned"):
            for resource in resources:
                url = safe_http_url(resource.get("url"))
                name = resource.get("name", "Resource")
                detail = resource.get("detail", "")
                st.markdown(f"[{name}]({url})" if url else f"**{name}**")
                if detail:
                    st.caption(detail)
            if isinstance(links, dict):
                for group in links.values():
                    for link in group if isinstance(group, list) else []:
                        url = safe_http_url(link.get("url"))
                        if url:
                            st.markdown(f"[{link.get('title') or url}]({url})")


def render_library_page(videos: list[dict], *, selected_id=None, **_kwargs) -> None:
    _header("library", "Library")
    if not videos:
        st.info("Add a video to start your library.")
        return

    playlist_id = st.session_state.get("library_playlist", "")
    query = st.text_input("Filter videos", placeholder="Find a title…",
                          key="library_filter", label_visibility="collapsed")
    if playlist_id:
        if st.button("Showing one playlist — show all", type="tertiary"):
            st.session_state.pop("library_playlist", None)
            st.rerun()

    filtered = [v for v in videos
                if query.lower() in (v.get("title") or "").lower()
                and (not playlist_id or v.get("playlist_id") == playlist_id)]
    if not filtered:
        st.info("No videos match this filter.")
        return

    by_id = {v["video_id"]: v for v in filtered}
    chosen = selected_id if selected_id in by_id else next(iter(by_id))
    st.session_state.selected_id = chosen

    picker, reader = st.columns([1, 2], gap="medium")

    with picker:
        st.caption(f"{len(filtered)} of {len(videos)} videos")
        # Fixed height keeps a long library scrollable instead of pushing the
        # reading pane off the page.
        with st.container(height=620, border=False):
            for video in filtered:
                vid = video["video_id"]
                status = video.get("status")
                label = video.get("title") or vid
                # Only abnormal states are worth the extra glyph; "done" is the norm.
                if status == db.STATUS_FAILED:
                    label = f"⚠ {label}"
                elif status == db.STATUS_PROCESSING:
                    label = f"● {label}"
                st.button(label, key=f"lib_pick_{vid}", on_click=_select, args=(vid,),
                          type="primary" if vid == chosen else "tertiary",
                          use_container_width=True)

    with reader:
        video = dbcache.get_video(chosen)
        if not video:
            st.info("This video is no longer available. Refresh the library.")
            return

        st.subheader(video.get("title") or chosen)
        meta = " · ".join(p for p in [video.get("channel_name") or "", _when(video)] if p)
        if meta:
            st.caption(meta)

        status = video.get("status")
        if status == db.STATUS_FAILED:
            error = classify_error(video.get("error_message", ""))
            st.error(f"{error['title']}. {error['message']}")
            st.caption(error["fix"])
            st.button("Try again", key=f"retry_{chosen}", on_click=_start, args=(chosen,),
                      type="primary")
            with st.expander("Technical details"):
                st.code(video.get("error_message") or "No details recorded", language=None)
                _transcript_recovery(video)
            return

        if status != db.STATUS_DONE:
            if status == db.STATUS_PROCESSING:
                st.info("Processing in the background. You can keep browsing.")
            else:
                st.button("Process video", key=f"start_{chosen}", on_click=_start, args=(chosen,),
                          type="primary")
                _transcript_recovery(video)
            return

        _render_insights(video, chosen)

        with st.container(horizontal=True):
            st.link_button("Watch on YouTube", youtube_watch_url(chosen))
            st.download_button("Download notes", export_video_markdown(video),
                               file_name=f"{chosen}.md", mime="text/markdown",
                               on_click="ignore")
            st.button("Re-process", key=f"reproc_{chosen}", on_click=_start, args=(chosen,),
                      type="tertiary")


def _when(video: dict) -> str:
    stamp = (video.get("processed_at") or video.get("added_at") or "")[:10]
    return stamp


def render_queue_page(videos: list[dict], ingest_notice: str = "") -> None:
    _header("queue", "Queue")
    if ingest_notice:
        st.info(ingest_notice)
    st.button("Refresh status", on_click=_refresh, type="tertiary")
    pending = [v for v in videos if v.get("status") != db.STATUS_DONE]
    if not pending:
        st.caption("Everything is processed.")
    for video in pending:
        with st.container(horizontal=True, vertical_alignment="center"):
            page_button(video.get("title") or video["video_id"], "library",
                        video_id=video["video_id"])
            st.caption(video.get("status", "pending").replace("_", " "))
    st.caption("Processing runs in the background. Refresh to see progress.")


def render_playlists_page(playlists: list[dict], all_videos: list[dict]) -> None:
    _header("playlists", "Playlists")
    for playlist in playlists:
        pid = playlist["playlist_id"]
        count = sum(v.get("playlist_id") == pid for v in all_videos)
        with st.expander(f"{playlist.get('name') or pid} · {count} videos"):
            st.caption(playlist.get("description") or "")
            if st.button("View videos", key=f"playlist_view_{pid}"):
                st.session_state.library_playlist = pid
                st.session_state.pop("library_video", None)
                navigate("library")
                st.rerun()
            st.caption(playlist.get("extraction_focus") or "No extraction focus set.")
    if st.button("Sync playlists"):
        _, message = start_poll_background()
        st.info(message)


def render_settings_page() -> None:
    import importlib.util
    from transcriber import youtube_runtime_options
    from usage_tracker import get_lifetime
    _header("system", "System")
    page_button("Profile and API settings", "settings")
    st.caption("YouTube downloader")
    st.write("Challenge solver installed" if importlib.util.find_spec("yt_dlp_ejs")
             else "Challenge solver missing — reinstall requirements.txt")
    runtimes = youtube_runtime_options()
    st.write("JavaScript runtimes: " + (", ".join(runtimes) or "none installed"))
    st.caption("Recorded lifetime usage")
    st.json(get_lifetime(), expanded=False)
