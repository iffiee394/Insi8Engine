"""A1/A2 persistence and atomic index tests on disposable SQLite."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import db
import knowledge_store
from search import insights_to_chunks, source_hash_for_chunks
from tests.support import IsolatedSQLite


class PersonalKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.iso = IsolatedSQLite(Path(self.tmp.name))
        self.iso.__enter__()
        Path(self.iso.tmp / "profile.json").write_text(
            json.dumps({"about_me": "researcher", "custom_key": "keep-me"}),
            encoding="utf-8",
        )
        db.init_db(force=True)

    def tearDown(self) -> None:
        self.iso.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_migrations_are_idempotent(self) -> None:
        from migrations import LATEST_SCHEMA_VERSION, run_migrations

        with db._connect() as conn:
            again = run_migrations(conn)
            conn.commit()
        self.assertEqual(again, LATEST_SCHEMA_VERSION)
        profile = db.get_profile()
        self.assertEqual(profile.get("about_me"), "researcher")
        self.assertEqual(profile.get("custom_key"), "keep-me")

    def test_stale_file_does_not_overwrite_db(self) -> None:
        db.set_profile({**db.get_profile(), "about_me": "from-db"})
        Path(self.iso.tmp / "profile.json").write_text(
            json.dumps({"about_me": "stale-file"}),
            encoding="utf-8",
        )
        db._SCHEMA_READY = False
        db.init_db(force=True)
        self.assertEqual(db.get_profile().get("about_me"), "from-db")

    def test_save_dedup_and_two_collections(self) -> None:
        a = knowledge_store.create_collection("Alpha")
        b = knowledge_store.create_collection("Beta")
        first = knowledge_store.save_item(
            kind=knowledge_store.KIND_INSIGHT,
            title="Idea",
            body_snapshot="same body",
            sources=[{"video_id": "vid1"}],
            personal_note="mine",
            collection_ids=[a["id"]],
        )
        second = knowledge_store.save_item(
            kind=knowledge_store.KIND_INSIGHT,
            title="Idea",
            body_snapshot="same body",
            sources=[{"video_id": "vid1"}],
            collection_ids=[b["id"]],
        )
        self.assertEqual(first["id"], second["id"])
        items = knowledge_store.list_saved_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(set(items[0]["collection_ids"]), {a["id"], b["id"]})
        knowledge_store.remove_item_from_collection(first["id"], a["id"])
        leftover = knowledge_store.list_saved_items()[0]
        self.assertEqual(leftover["collection_ids"], [b["id"]])
        self.assertEqual(leftover["personal_note"], "mine")
        self.assertEqual(knowledge_store.list_saved_items(collection_id=a["id"]), [])


class AtomicIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.iso = IsolatedSQLite(Path(self.tmp.name))
        self.iso.__enter__()
        db.init_db(force=True)
        db.upsert_video("vid1", title="T", status=db.STATUS_DONE, structured_insights=json.dumps({
            "insights": [{"topic": "One", "content": "first idea"}]
        }))

    def tearDown(self) -> None:
        self.iso.__exit__(None, None, None)
        self.tmp.cleanup()

    def _chunk(self, text="first idea", vector=None):
        vec = vector or [1.0] + [0.0] * 7
        return {
            "chunk_index": 0,
            "chunk_text": text,
            "chunk_title": "One",
            "timestamp_seconds": 0,
            "embedding": vec,
        }

    def test_failed_replace_keeps_old_generation(self) -> None:
        chunks = [self._chunk()]
        db.replace_auto_index("vid1", chunks, model="test", source_hash="aaa", vector_dim=8)
        before = db.get_all_embeddings(video_id="vid1")
        self.assertEqual(len(before), 1)
        with mock.patch.object(db, "encode_embedding", side_effect=RuntimeError("injected insert fail")):
            with self.assertRaises(RuntimeError):
                db.replace_auto_index(
                    "vid1",
                    [self._chunk("replacement")],
                    model="test",
                    source_hash="bbb",
                    vector_dim=8,
                )
        after = db.get_all_embeddings(video_id="vid1")
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["chunk_text"], "first idea")
        state = db.get_index_state("vid1")
        self.assertEqual(state["generation"], 1)
        self.assertEqual(state["source_hash"], "aaa")

    def test_stale_generation_rejected(self) -> None:
        db.replace_auto_index("vid1", [self._chunk()], model="test", source_hash="aaa", vector_dim=8)
        with self.assertRaises(db.IndexConflict):
            db.replace_auto_index(
                "vid1",
                [self._chunk("newer")],
                model="test",
                source_hash="bbb",
                vector_dim=8,
                expected_generation=0,
            )

    def test_insights_to_chunks_skips_empty(self) -> None:
        chunks, reason = insights_to_chunks(
            {"insights": [{"topic": "", "content": ""}, {"topic": "Keep", "content": "body"}]}
        )
        self.assertIsNone(reason)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_index"], 0)
        self.assertTrue(source_hash_for_chunks(chunks))


if __name__ == "__main__":
    unittest.main()
