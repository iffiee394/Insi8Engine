"""Centralized configuration — single source of truth for all settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

# On Streamlit Community Cloud there is no .env file — secrets are entered in
# the app's dashboard and exposed via st.secrets instead. Bridge them into
# os.environ (without overriding any real env var / .env value) so the rest
# of this module keeps reading plain os.getenv() either way.
try:
    import streamlit as st

    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass

# ── Paths (OS-agnostic) ──
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
DB_PATH = DATA_DIR / "insights.db"
PROFILE_PATH = DATA_DIR / "profile.json"
KB_PATH = DATA_DIR / "knowledge_base.txt"
LOG_PATH = Path(os.getenv("LOG_PATH", str(PROJECT_ROOT / "poll_worker.log")))
FIXTURES_DIR = DATA_DIR / "fixtures"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

# ── API Keys ──
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

# ── Legacy playlist IDs (fallback when no DB playlists) ──
PLAYLIST_ID = os.getenv("PLAYLIST_ID", "").strip()
PODCASTS_PLAYLIST_ID = os.getenv("PODCASTS_PLAYLIST_ID", "").strip()

# ── LLM Strategy ──
LLM_PRIMARY = os.getenv("LLM_PRIMARY", "gemini").strip().lower()
FALLBACK_TO_ANTHROPIC = os.getenv("FALLBACK_TO_ANTHROPIC", "true").strip().lower() in (
    "1", "true", "yes",
)
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash").strip()
GEMINI_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.0-flash,gemini-2.5-flash-lite").split(",")
    if m.strip()
]
DEEP_MODEL = os.getenv("DEEP_MODEL", "claude-haiku-4-5-20251001").strip()
DEEP_MAX_OUTPUT_TOKENS = int(os.getenv("DEEP_MAX_OUTPUT_TOKENS", "16384"))

# ── Research ──
TAVILY_CREDITS_PER_SEARCH = int(os.getenv("TAVILY_CREDITS_PER_SEARCH", "2"))
MAX_RESEARCH_TARGETS = int(os.getenv("MAX_RESEARCH_TARGETS", "6"))

# ── Models ──
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-20b").strip()

# ── Batch / Poll ──
BATCH_USE_ANTHROPIC = os.getenv("BATCH_USE_ANTHROPIC", "true").strip().lower() in ("1", "true", "yes")
BATCH_POLL_SEC = int(os.getenv("BATCH_POLL_SEC", "30"))
BATCH_TIMEOUT_SEC = int(os.getenv("BATCH_TIMEOUT_SEC", "86400"))
POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "15"))

# ── Embeddings ──
# text-embedding-004 was removed from Gemini API v1beta (404).
# gemini-embedding-001 is the current text-only model:
# https://ai.google.dev/gemini-api/docs/embeddings
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_OUTPUT_DIM = int(os.getenv("EMBEDDING_OUTPUT_DIM", "768"))


def validate() -> dict:
    """Check config completeness."""
    required = {
        "GROQ_API_KEY": GROQ_API_KEY,
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
    }
    recommended = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    }
    optional = {
        "TAVILY_API_KEY": TAVILY_API_KEY,
    }

    missing_required = [k for k, v in required.items() if not v]
    missing_recommended = [k for k, v in recommended.items() if not v]
    missing_optional = [k for k, v in optional.items() if not v]

    warnings: list[str] = []
    if not GEMINI_API_KEY and not ANTHROPIC_API_KEY:
        warnings.append(
            "No deep LLM configured — need at least GEMINI_API_KEY or ANTHROPIC_API_KEY"
        )
    if LLM_PRIMARY == "gemini" and not GEMINI_API_KEY:
        warnings.append("LLM_PRIMARY=gemini but GEMINI_API_KEY is missing")
    if FALLBACK_TO_ANTHROPIC and not ANTHROPIC_API_KEY:
        warnings.append("FALLBACK_TO_ANTHROPIC=true but ANTHROPIC_API_KEY is missing")

    return {
        "ok": len(missing_required) == 0 and len(warnings) == 0,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "missing_optional": missing_optional,
        "warnings": warnings,
    }
