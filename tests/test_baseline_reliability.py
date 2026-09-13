"""Provider-free regression tests for blocked downloads and transcript recovery."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline
import transcriber
from errors import classify_error


class TranscriptReliabilityTests(unittest.TestCase):
    def test_blocked_download_does_not_try_second_ai_downloader(self):
        with patch.object(pipeline, "_fetch_caption_segment_dicts", return_value=None), \
             patch.object(pipeline.config, "GEMINI_API_KEY", "test-key"), \
             patch.object(pipeline, "_transcribe_with_gemini", side_effect=transcriber.AudioDownloadError("blocked")), \
             patch.object(transcriber, "transcribe_youtube_audio") as groq:
            with self.assertRaises(transcriber.AudioDownloadError):
                pipeline.fetch_transcript_data("abcdefghijk", persist=False)
            groq.assert_not_called()

    def test_stored_transcript_skips_youtube_and_ai_transcription(self):
        with patch("knowledge_store.get_transcript", return_value={
            "plain_text": "User supplied transcript", "source": "user_transcript",
            "timing_quality": "unknown", "timed_segments_json": "[]",
        }), patch.object(pipeline, "_fetch_caption_segment_dicts") as captions, \
             patch.object(pipeline, "_transcribe_with_gemini") as gemini:
            result = pipeline.fetch_transcript_data("abcdefghijk")
            self.assertEqual(result["source"], "user_transcript")
            captions.assert_not_called()
            gemini.assert_not_called()

    def test_partial_download_is_never_sent_to_transcription(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(transcriber.yt_dlp, "YoutubeDL"):
            (Path(tmp) / "abcdefghijk.webm.part").write_bytes(b"partial")
            with self.assertRaises(transcriber.AudioDownloadError):
                transcriber.download_youtube_audio("abcdefghijk", Path(tmp))

    def test_download_403_has_actionable_non_quota_message(self):
        error = classify_error("ERROR: unable to download video data: HTTP Error 403: Forbidden")
        self.assertEqual(error["title"], "YouTube blocked the download")
        self.assertIn("transcript", error["fix"])
        self.assertNotEqual(classify_error("Gemini API 403 permission denied")["title"], error["title"])

    def test_unrelated_error_is_not_mislabeled_as_age_restriction(self):
        self.assertEqual(classify_error("Storage service failed")["title"], "Processing failed")
