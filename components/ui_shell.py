"""InsightEngine shell — routes to Stitch iframe pages (Option D)."""

from __future__ import annotations

import streamlit as st

import config
import db
import dbcache
from background_jobs import is_worker_running, start_process_one_background
from components.knowledge_pages import (
    render_home_page,
    render_add_page,
    render_profile_settings_page,
    render_chat_page,
    render_export_page,
    render_saved_page,
    render_search_page,
)
from components.stitch_pages import (
    render_library_page,
    render_playlists_page,
    render_queue_page,
    render_settings_page,
)
from ingest import ingest_pasted_url


def _read_query_params() -> None:
    """Sync Streamlit session state from URL query params written by the iframe."""
    params = st.query_params
    valid_pages = {
        "home",
        "add",
        "system",
        "library",
        "queue",
        "playlists",
        "settings",
        "search",
        "saved",
        "chat",
        "export",
    }

    page = params.get("page", "")
    if page in valid_pages:
        st.session_state.active_page = page

    vid = params.get("vid", "")
    if vid:
        st.session_state.selected_id = vid
        if page == "chat":
            st.session_state.chat_scope_type = "video"
            st.session_state.chat_scope_id = vid
            st.session_state.chat_conversation_id = None

    if params.get("action") == "ingest":
        result = ingest_pasted_url(params.get("url", ""), params.get("folder", "video"))
        dbcache.invalidate()
        st.query_params.clear()
        if result.ok and result.video_id:
            st.session_state.selected_id = result.video_id
        st.session_state.active_page = "library"
        st.session_state.ingest_notice = result.message
        if result.ok and result.queued:
            ok, msg = start_process_one_background(result.video_id)
            if not ok:
                st.session_state.ingest_notice = f"{result.message} {msg}"
            st.toast(st.session_state.ingest_notice)
        elif result.ok:
            st.toast(result.message)
        else:
            st.error(result.message)
        return

    if params.get("action") == "retry":
        vid = params.get("vid", "")
        st.query_params.clear()
        if vid:
            db.upsert_video(vid, status=db.STATUS_PENDING, error_message="")
            dbcache.invalidate()
            ok, msg = start_process_one_background(vid)
            st.session_state.selected_id = vid
            st.toast(msg)
        return

    if params.get("action") == "export":
        vid = params.get("vid", "")
        st.query_params.clear()
        if vid:
            st.session_state.selected_id = vid
            st.session_state.export_kind = "video"
            st.session_state.export_id = vid
            st.session_state.active_page = "export"
        return

    # Legacy iframe settings save — ignore personal fields in the URL.
    if params.get("action") == "save" and page == "settings":
        st.query_params.clear()
        st.session_state.active_page = "settings"
        st.toast("Edit your profile in Settings.")


def render_app(ctx: dict) -> None:
    # ── Apply query param navigation from iframe clicks ──
    _read_query_params()

    # ── Session state defaults ──
    defaults = {
        "active_page": "home",
        "selected_id": None,
        "selected_playlist_id": None,
        "was_worker_running": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Light rows: the list/queue views never touch the big JSON columns, and
    # pulling them for all videos cost ~3MB and several seconds per render.
    # Cached, so a rerun costs no round-trip (see dbcache for invalidation).
    all_videos = dbcache.list_videos_light()
    if st.session_state.selected_id is None and all_videos:
        first = next((v for v in all_videos if v.get("status") == db.STATUS_DONE), all_videos[0])
        st.session_state.selected_id = first["video_id"]

    page = st.session_state.active_page
    ingest_notice = st.session_state.pop("ingest_notice", "")

    # Keep the 3s worker tick off native pages so Search/Saved/Chat can scroll
    # and so AppTest/acceptance runs are not blocked by a repeating fragment.
    if page in {"library", "queue", "playlists", "system"}:

        @st.fragment(run_every=3)
        def _queue_tick() -> None:
            running = is_worker_running()
            if running:
                st.session_state.was_worker_running = True
            elif st.session_state.was_worker_running:
                st.session_state.was_worker_running = False
                dbcache.invalidate()
                st.rerun()

        _queue_tick()

    # ── Route to the correct page ──
    if page == "home":
        render_home_page(all_videos)
        return
    if page == "add":
        render_add_page()
        return
    if page == "settings":
        render_profile_settings_page()
        return
    if page == "search":
        render_search_page()
        return
    if page == "saved":
        render_saved_page()
        return
    if page == "chat":
        if not st.session_state.get("chat_scope_type"):
            st.session_state.chat_scope_type = "library"
            st.session_state.chat_scope_id = ""
        render_chat_page()
        return
    if page == "export":
        render_export_page()
        return

    if page == "system":
        render_settings_page()

    elif page == "playlists":
        playlists = dbcache.list_playlists()
        render_playlists_page(playlists, all_videos)

    elif page == "queue":
        render_queue_page(all_videos, ingest_notice=ingest_notice)

    else:  # library (default)
        render_library_page(
            all_videos,
            selected_id=st.session_state.get("selected_id"),
            active_tab="library",
            ingest_notice=ingest_notice,
        )
