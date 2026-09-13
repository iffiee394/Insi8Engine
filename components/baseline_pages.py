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


def _header(page: str, title: str) -> None:
    st.markdown(native_page_css(), unsafe_allow_html=True)
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


def render_library_page(videos: list[dict], *, selected_id=None, **_kwargs) -> None:
    _header("library", "Library")
    if not videos:
        st.info("Add a video to start your library.")
        return
    with st.container(horizontal=True, vertical_alignment="center"):
        query = st.text_input("Filter videos", placeholder="Find a title…", key="library_filter")
        st.button("Refresh", on_click=_refresh, type="tertiary")
    playlist_id = st.session_state.get("library_playlist", "")
    if playlist_id:
        st.caption("Showing the selected playlist")
        if st.button("Show all playlists", type="tertiary"):
            st.session_state.pop("library_playlist", None)
            st.rerun()
    filtered = [v for v in videos if query.lower() in (v.get("title") or "").lower()
                and (not playlist_id or v.get("playlist_id") == playlist_id)]
    if not filtered:
        st.info("No videos match this filter.")
        return
    by_id = {v["video_id"]: v for v in filtered}
    ids = list(by_id)
    selected = selected_id if selected_id in by_id else ids[0]
    chosen = st.selectbox("Video", ids, index=ids.index(selected),
                          format_func=lambda vid: by_id[vid].get("title") or vid,
                          key="library_video")
    st.session_state.selected_id = chosen
    video = dbcache.get_video(chosen)
    if not video:
        st.info("This video is no longer available. Refresh the library.")
        return
    st.subheader(video.get("title") or chosen)
    st.caption(" · ".join(str(video.get(k) or "") for k in ("channel_name", "status")))
    with st.container(horizontal=True):
        st.link_button("Watch on YouTube", youtube_watch_url(chosen))
        st.download_button("Download notes", export_video_markdown(video),
                           file_name=f"{chosen}.md", mime="text/markdown", on_click="ignore")
    status = video.get("status")
    if status == db.STATUS_FAILED:
        error = classify_error(video.get("error_message", ""))
        st.error(f"{error['title']}. {error['message']}")
        st.caption(error["fix"])
        with st.expander("Technical details"):
            st.code(video.get("error_message") or "No details recorded", language=None)
    if status != db.STATUS_DONE:
        if status == db.STATUS_PROCESSING:
            st.info("Processing in the background. You can continue browsing.")
        else:
            st.button("Process video", on_click=_start, args=(chosen,))
            _transcript_recovery(video)
        return
    structured = db.parse_structured_insights(video.get("structured_insights") or "{}")
    summary = video.get("summary") or structured.get("summary") or ""
    if summary:
        st.markdown(summary)
    insights = structured.get("insights") or []
    for item in insights:
        if not isinstance(item, dict):
            continue
        with st.expander(item.get("topic") or item.get("title") or "Insight"):
            st.markdown(item.get("content") or item.get("insight") or "")
            for point in item.get("points") or item.get("key_points") or []:
                st.markdown(f"- {point}")
            seconds = item.get("timestamp_seconds")
            if isinstance(seconds, (int, float)) and seconds >= 0:
                st.link_button("Watch this moment", youtube_watch_url(chosen, seconds))
    if not insights:
        for point in db.parse_key_points(video.get("key_points") or "[]"):
            st.markdown(f"- {point}")
    with st.expander("Resources and research"):
        for resource in structured.get("resources") or []:
            st.markdown(f"**{resource.get('name', 'Resource')}** — {resource.get('detail', '')}")
            url = safe_http_url(resource.get("url"))
            if url:
                st.link_button("Open resource", url)
        links = structured.get("links") or {}
        if isinstance(links, dict):
            for group in links.values():
                for link in group if isinstance(group, list) else []:
                    url = safe_http_url(link.get("url"))
                    if url:
                        st.link_button(link.get("title") or url, url)
        try:
            research = json.loads(video.get("research_data") or "{}")
        except (ValueError, TypeError):
            research = {}
        if research:
            st.json(research, expanded=False)
    with st.expander("More actions"):
        page_button("Ask about this video", "chat", video_id=chosen)
        st.button("Re-process video", on_click=_start, args=(chosen,))


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
