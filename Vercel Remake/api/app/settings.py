from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv("DATABASE_URL", "").strip()
        self.allowed_origins = [
            item.strip()
            for item in os.getenv("APP_ALLOWED_ORIGINS", "*").split(",")
            if item.strip()
        ]
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        self.gemini_api_key = (
            os.getenv("GEMINI_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
        )
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.tavily_api_key = os.getenv("TAVILY_API_KEY", "").strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
