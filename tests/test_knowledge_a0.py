"""A0: read-only health and fixture restore. Uses disposable SQLite only."""

from __future__ import annotations

import json
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import db
import knowledge_health


def _vec(values):
    return struct.pack(f"{len(values)}f", *values)


class HealthReadOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fixture.db"
        from tests.support import seed_min_schema

        seed_min_schema(self.path)
        conn = sqlite3.connect(self.path)
        conn.execute(
            "INSERT INTO videos (video_id, title, status, structured_insights, error_message, added_at) "
            "VALUES ('ok1', 'Good', 'done', ?, '', '2026-01-01')",
            (json.dumps({"insights": [{"topic": "A", "content": "alpha idea"}]}),),
        )
        conn.execute(
            "INSERT INTO videos (video_id, title, status, structured_insights, error_message, added_at) "
            "VALUES ('empty1', 'Empty', 'done', '{}', '', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO videos (video_id, title, status, structured_insights, error_message, added_at) "
            "VALUES ('bad1', 'Bad', 'done', '{not-json', '', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO videos (video_id, title, status, structured_insights, error_message, added_at) "
            "VALUES ('fail1', 'Gone', 'failed', '{}', 'This video is private', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO embeddings (video_id, chunk_index, chunk_text, chunk_title, timestamp_seconds, embedding) "
            "VALUES ('ok1', 0, 'A: alpha idea', 'A', 0, ?)",
            (_vec([1.0, 0.0, 0.0]),),
        )
        conn.execute("INSERT INTO playlists (playlist_id, name) VALUES ('pl1', 'General')")
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_health_does_not_call_init_db(self) -> None:
        with mock.patch.object(db, "init_db", side_effect=AssertionError("init_db called")):
            conn = knowledge_health.connect_readonly(sqlite_path=self.path)
            try:
                report = knowledge_health.collect_health(conn)
            finally:
                conn.close()
        self.assertEqual(report["video_status"]["done"], 3)
        self.assertEqual(report["video_status"]["failed"], 1)
        self.assertEqual(report["insights"]["ok"], 1)
        self.assertEqual(report["insights"]["empty"], 2)
        self.assertEqual(report["insights"]["malformed"], 1)
        self.assertEqual(report["index"]["missing"], 0)
        self.assertEqual(report["failures"]["private_or_deleted"], 1)
        self.assertTrue(report["read_only"])

    def test_health_does_not_create_tables(self) -> None:
        before = sqlite3.connect(self.path)
        names_before = {
            r[0]
            for r in before.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        before.close()
        conn = knowledge_health.connect_readonly(sqlite_path=self.path)
        knowledge_health.collect_health(conn)
        conn.close()
        after = sqlite3.connect(self.path)
        names_after = {
            r[0]
            for r in after.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        after.close()
        self.assertEqual(names_before, names_after)

    def test_restore_sqlite_counts_match(self) -> None:
        dest = Path(self.tmp.name) / "restored.db"
        knowledge_health.restore_sqlite_file(self.path, dest)
        cmp = knowledge_health.compare_sqlite_counts(self.path, dest)
        self.assertTrue(cmp["match"])
        self.assertEqual(cmp["left"]["videos"], 4)


if __name__ == "__main__":
    unittest.main()
