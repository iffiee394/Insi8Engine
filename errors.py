"""Map technical errors to user-friendly messages."""

from __future__ import annotations

ERROR_MAP = {
    "429": {
        "gemini": {
            "title": "Gemini free tier exhausted",
            "message": "Google's daily free quota has been reached.",
            "fix": "Wait until tomorrow, or set LLM_PRIMARY=anthropic in .env to use paid fallback.",
        },
        "groq": {
            "title": "Groq rate limit hit",
            "message": "Too many requests to Groq in a short period.",
            "fix": "Wait a few minutes and retry. The app will automatically try Gemini/Anthropic as fallback.",
        },
    },
    "no_captions": {
        "title": "No transcript available",
        "message": "This video has no captions, and audio transcription couldn't process it.",
        "fix": "Check that ffmpeg is installed and on PATH. Some videos may not have captions yet.",
    },
    "private_video": {
        "title": "Video is unavailable",
        "message": "This video is private, age-restricted, or has been removed.",
        "fix": "Check if the video is still publicly accessible on YouTube.",
    },
    "json_parse": {
        "title": "AI response couldn't be parsed",
        "message": "The LLM returned malformed output that couldn't be processed.",
        "fix": "Click Retry — this is usually a one-time issue. If it persists, try Re-process.",
    },
    "anthropic_credit": {
        "title": "Anthropic billing issue",
        "message": "No Anthropic credits available for the fallback model.",
        "fix": "Add billing at console.anthropic.com, or ensure Gemini is configured as primary.",
    },
}


def classify_error(error_message: str, provider: str = "") -> dict:
    """Classify a raw error message into a user-friendly error dict."""
    msg = str(error_message or "")
    lower = msg.lower()

    if "429" in lower or "rate limit" in lower or "quota" in lower:
        if "groq" in lower or provider == "groq":
            return {**ERROR_MAP["429"]["groq"], "raw": error_message}
        return {**ERROR_MAP["429"]["gemini"], "raw": error_message}

    if "empty transcript" in lower or "no transcript" in lower or "captions" in lower:
        return {**ERROR_MAP["no_captions"], "raw": error_message}

    if "private" in lower or "unavailable" in lower or "age" in lower:
        return {**ERROR_MAP["private_video"], "raw": error_message}

    if "json" in lower and ("parse" in lower or "decode" in lower or "could not parse" in lower):
        return {**ERROR_MAP["json_parse"], "raw": error_message}

    if "anthropic" in lower and ("credit" in lower or "billing" in lower or "balance" in lower):
        return {**ERROR_MAP["anthropic_credit"], "raw": error_message}

    return {
        "title": "Processing failed",
        "message": msg[:300] if msg else "An unexpected error occurred during processing.",
        "fix": "Click Retry. If the issue persists, check poll_worker.log for details.",
        "raw": error_message,
    }
