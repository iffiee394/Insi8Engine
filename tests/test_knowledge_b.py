"""Export, citation, and rerun tests on disposable SQLite."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import config
import db
import export
import knowledge_chat
import knowledge_store
from tests.support import IsolatedSQLite


class ExportTests(unittest.TestCase):
    def test_extracted_date_uses_processed_at(self) -> None:
        md = export.export_video_markdown(
            {
                "title": "T",
                "channel_name": "C",
                "video_id": "abcdefghijk",
                "playlist_type": "general",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "processed_at": "2026-02-03T10:00:00+00:00",
                "summary": "S",
                "structured_insights": json.dumps(
                    {"insights": [{"topic": "X", "content": "Y", "timestamp_seconds": 0}]}
                ),
            }
        )
        self.assertIn("**Extracted:** 2026-02-03", md)
        self.assertIn("t=0s", md)

    def test_unknown_timing_has_no_offset(self) -> None:
        md = export.export_video_markdown(
            {
                "title": "T",
                "video_id": "abcdefghijk",
                "processed_at": "",
                "structured_insights": json.dumps(
                    {"insights": [{"topic": "X", "content": "Y"}]}
                ),
            }
        )
        self.assertIn("**Extracted:** unknown", md)
        self.assertNotIn("&t=", md)


class ChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.iso = IsolatedSQLite(Path(self.tmp.name))
        self.iso.__enter__()
        self._gemini = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = ""
        db.init_db(force=True)
        db.upsert_video(
            "abcdefghijk",
            title="Only this video",
            status=db.STATUS_DONE,
            structured_insights=json.dumps(
                {"insights": [{"topic": "Widgets", "content": "widgets cost twenty"}]}
            ),
        )
        knowledge_store.upsert_transcript(
            "abcdefghijk",
            plain_text="The late passage says widgets cost twenty dollars.",
            timed_segments=[{"start": 400, "end": 420, "text": "widgets cost twenty dollars"}],
            source="fixture",
            timing_quality="exact",
        )
        self.convo = knowledge_store.create_conversation(
            title="Q", scope_type="video", scope_id="abcdefghijk"
        )

    def tearDown(self) -> None:
        config.GEMINI_API_KEY = self._gemini
        self.iso.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_unknown_citation_dropped_and_rerun_reuses_request(self) -> None:
        def fake_llm(_prompt: str) -> str:
            return json.dumps(
                {
                    "answer": 'They cost twenty. "missing quote that is invented"',
                    "citations": ["E1", "E99"],
                    "disagreements": "",
                    "suggestions": "try a checklist",
                }
            )

        first = knowledge_chat.ask(
            conversation_id=self.convo["id"],
            request_id="req-1",
            question="How much do widgets cost?",
            insights_only=True,
            llm_fn=fake_llm,
        )
        self.assertEqual(first["status"], "ok")
        sources = json.loads(first["sources_json"])
        self.assertTrue(all(s["id"] != "E99" for s in sources))
        self.assertIn("Suggestion (not from the sources)", first["content"])

        calls = {"n": 0}

        def boom(_prompt: str) -> str:
            calls["n"] += 1
            raise AssertionError("should not call again")

        second = knowledge_chat.ask(
            conversation_id=self.convo["id"],
            request_id="req-1",
            question="How much do widgets cost?",
            insights_only=True,
            llm_fn=boom,
        )
        self.assertEqual(calls["n"], 0)
        self.assertEqual(second["id"], first["id"])

    def test_video_scope_rejects_other_video_hits(self) -> None:
        evidence = knowledge_chat._collect_evidence(
            question="widgets",
            scope_type="video",
            scope_id="abcdefghijk",
            insights_only=True,
        )
        self.assertTrue(all(item["video_id"] == "abcdefghijk" for item in evidence))

    def test_youtube_url_validation(self) -> None:
        self.assertEqual(knowledge_chat.youtube_watch_url("bad id"), "")
        self.assertEqual(
            knowledge_chat.youtube_watch_url("abcdefghijk", 0),
            "https://www.youtube.com/watch?v=abcdefghijk&t=0s",
        )
        self.assertEqual(knowledge_chat.safe_http_url("javascript:alert(1)"), "")


if __name__ == "__main__":
    unittest.main()
