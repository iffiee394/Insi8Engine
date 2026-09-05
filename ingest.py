"""Paste a YouTube URL into a Video or Podcast folder and queue processing."""

from __future__ import annotations

from dataclasses import dataclass

import db
from youtube_monitor import fetch_video, parse_video_id

FOLDER_VIDEO = "video"
FOLDER_PODCAST = "podcast"

_KIND_BY_FOLDER = {
    FOLDER_VIDEO: db.PLAYLIST_GENERAL,
    "general": db.PLAYLIST_GENERAL,
    FOLDER_PODCAST: db.PLAYLIST_PODCAST,
}


@dataclass
class IngestResult:
    ok: bool
    message: str
    video_id: str = ""
    already_done: bool = False
    queued: bool = False


def _normalize_folder(folder: str) -> str:
    key = (folder or FOLDER_VIDEO).strip().lower()
    if key not in _KIND_BY_FOLDER:
        raise ValueError("Folder must be Video or Podcast.")
    return FOLDER_PODCAST if key == FOLDER_PODCAST else FOLDER_VIDEO


def playlist_for_folder(folder: str) -> dict | None:
    kind = _KIND_BY_FOLDER[_normalize_folder(folder)]
    matches = [p for p in db.list_playlists(enabled_only=True) if p.get("kind") == kind]
    return matches[0] if matches else None


def ingest_pasted_url(url: str, folder: str = FOLDER_VIDEO) -> IngestResult:
    """Register a pasted YouTube URL on the Video or Podcast folder.

    Does not start the worker — callers queue process_one / background job.
    Already-done videos are left as-is (idempotent).
    """
    db.init_db()
    try:
        folder = _normalize_folder(folder)
    except ValueError as exc:
        return IngestResult(ok=False, message=str(exc))

    video_id = parse_video_id(url)
    if not video_id:
        return IngestResult(
            ok=False,
            message="Paste a YouTube video link (watch, youtu.be, shorts) or an 11-character video id.",
        )

    try:
        item = fetch_video(video_id)
    except Exception as exc:
        return IngestResult(ok=False, message=str(exc), video_id=video_id)

    kind = _KIND_BY_FOLDER[folder]
    playlist = playlist_for_folder(folder)
    playlist_id = playlist["playlist_id"] if playlist else ""
    folder_label = "Podcast" if kind == db.PLAYLIST_PODCAST else "Video"

    existing = db.get_video(video_id)
    db.upsert_video(
        video_id,
        title=item.title,
        url=item.url,
        playlist_type=kind,
        playlist_id=playlist_id,
        channel_name=item.channel_name,
        status=None if existing else db.STATUS_PENDING,
    )

    if existing and existing.get("status") == db.STATUS_DONE:
        return IngestResult(
            ok=True,
            message=f"Already in the library — opened in {folder_label}. Re-process from the video if you want a fresh extract.",
            video_id=video_id,
            already_done=True,
        )

    if existing and existing.get("status") == db.STATUS_PROCESSING:
        return IngestResult(
            ok=True,
            message="This video is already processing.",
            video_id=video_id,
            queued=True,
        )

    db.upsert_video(video_id, status=db.STATUS_PENDING, error_message="")
    return IngestResult(
        ok=True,
        message=f"Queued in {folder_label}: {item.title}",
        video_id=video_id,
        queued=True,
    )
