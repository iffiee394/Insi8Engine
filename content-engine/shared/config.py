"""
Shared configuration for the Chairside Content Engine.

Loads credentials from the project-root .env (reused from the parent project so
there is exactly one place to manage keys) and resolves all filesystem paths.

Design note: nothing client-specific lives here. Client data lives in
shared/clients/<slug>/. That separation is what makes client #2 cheap.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is in requirements
    load_dotenv = None

# ---------------------------------------------------------------- paths

ENGINE_ROOT = Path(__file__).resolve().parent.parent          # content-engine/
PROJECT_ROOT = ENGINE_ROOT.parent                              # CursorP1/
SHARED_DIR = ENGINE_ROOT / "shared"
CLIENTS_DIR = SHARED_DIR / "clients"
DATA_DIR = ENGINE_ROOT / "data"
ARCHIVE_DIR = DATA_DIR / "archive"
PART_C_DIR = ENGINE_ROOT / "part-c-carousel-factory"
PART_D_DIR = ENGINE_ROOT / "part-d-reels-engine"
PART_E_DIR = ENGINE_ROOT / "part-e-pillar-repurposer"

for _d in (DATA_DIR, ARCHIVE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "engine.db"

# Load .env from the project root (shared with the parent Streamlit app).
if load_dotenv is not None:
    for _candidate in (PROJECT_ROOT / ".env", ENGINE_ROOT / ".env"):
        if _candidate.exists():
            load_dotenv(_candidate, override=False)


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


# ---------------------------------------------------------------- models
# Provider order is deliberate: Gemini first because the free daily tier covers
# this workload, Anthropic second for quality on the steps that matter most
# (clinical claim extraction), Groq for audio because whisper-large-v3 there is
# effectively free and very fast. See DECISIONS.md D-04.

LLM_PRIMARY = env("LLM_PRIMARY", "gemini").lower()
GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in env("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash-lite").split(",") if m.strip()
]
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env("DEEP_MODEL", "claude-sonnet-5")
GROQ_API_KEY = env("GROQ_API_KEY")
GROQ_WHISPER_MODEL = env("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
TAVILY_API_KEY = env("TAVILY_API_KEY")

# Browsers used for HTML -> PNG rendering. Checked in order.
BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# Instagram portrait. 4:5 is the tallest ratio the feed renders without cropping.
CANVAS_W, CANVAS_H = 1080, 1350
REEL_W, REEL_H = 1080, 1920


# ---------------------------------------------------------------- client


@dataclass
class ClientProfile:
    """Everything that differs between clients. Nothing else should."""

    slug: str
    name: str
    root: Path
    brand: dict[str, Any] = field(default_factory=dict)
    identification: dict[str, Any] = field(default_factory=dict)
    compliance: dict[str, Any] = field(default_factory=dict)
    voice: dict[str, Any] = field(default_factory=dict)
    channels: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def knowledge_base(self) -> str:
        kb = self.root / "knowledge_base.md"
        return kb.read_text(encoding="utf-8") if kb.exists() else ""

    @property
    def watchlist_path(self) -> Path:
        return self.root / "watchlist.json"

    @property
    def identification_block(self) -> str:
        i = self.identification
        parts = [i.get("practice_name", self.name)]
        if i.get("designation"):
            parts.append(i["designation"])
        if i.get("address"):
            parts.append(i["address"])
        if i.get("phone"):
            parts.append(i["phone"])
        return " · ".join(p for p in parts if p)

    @property
    def banned_phrases(self) -> list[str]:
        return [p.lower() for p in self.compliance.get("banned_phrases", [])]

    @property
    def banned_formats(self) -> list[str]:
        return self.compliance.get("banned_formats", [])


def load_client(slug: str) -> ClientProfile:
    root = CLIENTS_DIR / slug
    cfg = root / "client.json"
    if not cfg.exists():
        available = sorted(p.name for p in CLIENTS_DIR.iterdir() if p.is_dir())
        raise FileNotFoundError(
            f"No client profile at {cfg}. Available clients: {available or '(none)'}"
        )
    data = json.loads(cfg.read_text(encoding="utf-8"))
    return ClientProfile(
        slug=slug,
        name=data.get("name", slug),
        root=root,
        brand=data.get("brand", {}),
        identification=data.get("identification", {}),
        compliance=data.get("compliance", {}),
        voice=data.get("voice", {}),
        channels=data.get("channels", {}),
        raw=data,
    )


def default_client() -> str:
    return env("ENGINE_CLIENT", "northfield-dental")
