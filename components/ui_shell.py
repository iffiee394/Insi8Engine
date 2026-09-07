"""InsightEngine shell — routes to Stitch iframe pages (Option D)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

import config
import db
import dbcache
from background_jobs import is_worker_running, start_process_one_background
from components.stitch_pages import (
    render_library_page,
    render_playlists_page,
    render_queue_page,
    render_settings_page,
)
from export import export_video_markdown
from ingest import ingest_pasted_url


def _read_query_params() -> None:
    """Sync Streamlit session state from URL query params written by the iframe."""
    params = st.query_params
    valid_pages = {"library", "queue", "playlists", "settings"}

    page = params.get("page", "")
    if page in valid_pages:
        st.session_state.active_page = page

    vid = params.get("vid", "")
    if vid:
        st.session_state.selected_id = vid

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
        video = db.get_video(params.get("vid", ""))
        st.query_params.clear()
        if video:
            out_dir = Path("exports")
            out_dir.mkdir(exist_ok=True)
            path = out_dir / f"{video['video_id']}.md"
            path.write_text(export_video_markdown(video), encoding="utf-8")
            st.session_state.selected_id = video["video_id"]
            st.toast(f"Exported to {path}")
        else:
            st.toast("Nothing to export.")
        return

    # Settings save action
    if params.get("action") == "save" and page == "settings":
        profile = db.get_profile()
        if params.get("display_name"):
            profile["display_name"] = params["display_name"]
        if params.get("email"):
            profile["email"] = params["email"]
        if "bio" in params:
            profile["about_me"] = params["bio"]
        if "personalize" in params:
            profile["personalize_extractions"] = params["personalize"] == "1"
        db.set_profile(profile)
        dbcache.invalidate()
        # Clear the action param so it doesn't re-fire on next rerun
        st.query_params.clear()
        st.toast("Settings saved")


def render_app(ctx: dict) -> None:
    # ── Apply query param navigation from iframe clicks ──
    _read_query_params()

    # ── Session state defaults ──
    defaults = {
        "active_page": "library",
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
        st.session_state.selected_id = all_videos[0]["video_id"]

    page = st.session_state.active_page
    ingest_notice = st.session_state.pop("ingest_notice", "")

    # ── Background queue tick (hidden fragment, runs every 3s) ──
    @st.fragment(run_every=3)
    def _queue_tick() -> None:
        running = is_worker_running()
        if running:
            st.session_state.was_worker_running = True
        elif st.session_state.was_worker_running:
            st.session_state.was_worker_running = False
            # The worker wrote to the database from another process; drop the
            # cached reads so the finished video shows up on this rerun.
            dbcache.invalidate()
            st.rerun()

    _queue_tick()

    # ── Route to the correct Stitch page ──
    if page == "settings":
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
