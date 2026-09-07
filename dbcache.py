"""Streamlit-side read caching for the database.

Every page render re-reads the same rows, and against hosted Postgres each of
those reads is a network round-trip. These wrappers keep them in Streamlit's
cache so a rerun costs nothing.

Caching is only safe here because writes are funnelled through invalidate():
anything the app itself changes (retry, ingest, settings) clears the cache, and
the queue tick clears it when a background worker finishes so newly processed
videos appear. The TTLs are a backstop for changes made by other processes —
the poll worker and youtube_monitor write to the same database without going
through this layer.

Import this only from Streamlit code paths; db.py stays importable by the CLI
scripts that run outside a Streamlit runtime.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

import db

# Lists drive what you see at a glance (status pills, counts), so they refresh
# sooner than a single video's fully-processed detail, which rarely changes.
_LIST_TTL = 20
_ITEM_TTL = 90


@st.cache_data(ttl=_LIST_TTL, show_spinner=False)
def list_videos_light() -> list[dict[str, Any]]:
    return db.list_videos(light=True)


@st.cache_data(ttl=_LIST_TTL, show_spinner=False)
def list_playlists() -> list[dict[str, Any]]:
    return db.list_playlists()


@st.cache_data(ttl=_ITEM_TTL, show_spinner=False)
def get_video(video_id: str) -> dict[str, Any] | None:
    return db.get_video(video_id)


def invalidate() -> None:
    """Drop every cached read. Call after any write the app performs."""
    list_videos_light.clear()
    list_playlists.clear()
    get_video.clear()
