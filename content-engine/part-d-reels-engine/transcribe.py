"""Part D transcription — now lives in shared/ so Part E uses the same code.

Kept as a shim so `from transcribe import transcribe` keeps working here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared.transcribe import (  # noqa: F401,E402
    AUDIO_DIR,
    CACHE_DIR,
    download_audio,
    to_srt,
    transcribe,
    via_whisper,
    via_youtube_api,
    youtube_id,
)
