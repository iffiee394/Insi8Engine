"""Start poll / single-video processing in a background subprocess."""

from __future__ import annotations

import subprocess
import sys

import config
import db

LOG_PATH = config.LOG_PATH
PROJECT_ROOT = config.PROJECT_ROOT


def is_worker_running() -> bool:
    db.init_db()
    return db.get_meta("poll_worker_running", "") == "1"


def _spawn(args: list[str]) -> tuple[bool, str]:
    if is_worker_running():
        return False, "Background processing is already running."

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_PATH, "a", encoding="utf-8")
    log_file.write("\n--- worker started ---\n")
    log_file.flush()

    kwargs: dict = {
        "cwd": str(PROJECT_ROOT),
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    subprocess.Popen([sys.executable, *args], **kwargs)
    return True, "Started in background — browse done videos while the queue runs."


def start_poll_background() -> tuple[bool, str]:
    return _spawn([str(PROJECT_ROOT / "poll.py")])


def start_process_one_background(video_id: str, *, manual: bool = False) -> tuple[bool, str]:
    cmd = [str(PROJECT_ROOT / "poll.py"), "--one", video_id]
    if manual:
        cmd.append("--manual")
    return _spawn(cmd)
