"""Homepage routing checks without personal database writes or provider calls."""

import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from search import SearchResponse


def shell():
    from components.ui_shell import render_app
    render_app({})


class MinimalHomeTests(unittest.TestCase):
    def setUp(self):
        self.stack = []
        videos = [
            {"video_id": "failed00001", "title": "Failed video", "status": "failed"},
            {"video_id": "donevideo01", "title": "A useful idea", "status": "done",
             "processed_at": "2026-09-12", "channel_name": "Example channel"},
        ]
        for target, value in [
            ("components.ui_shell.dbcache.list_videos_light", videos),
            ("components.knowledge_pages.dbcache.list_playlists", []),
            ("components.knowledge_pages.knowledge_store.list_collections", []),
            ("components.knowledge_pages.knowledge_store.list_saved_items", []),
        ]:
            p = patch(target, return_value=value)
            p.start()
            self.stack.append(p)

    def tearDown(self):
        for p in reversed(self.stack):
            p.stop()

    def test_home_does_not_fetch_details_or_start_work(self):
        with patch("components.ui_shell.dbcache.get_video") as details, \
             patch("components.knowledge_pages.search_insights_response") as search, \
             patch("components.ui_shell.is_worker_running") as worker:
            app = AppTest.from_function(shell).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["active_page"], "home")
            self.assertEqual(app.session_state["selected_id"], "donevideo01")
            markup = " ".join(m.value for m in app.markdown)
            self.assertIn("A useful idea", markup)
            self.assertNotIn("Failed video", markup)
            self.assertEqual(len(app.text_input), 1)
            details.assert_not_called()
            search.assert_not_called()
            worker.assert_not_called()

    def test_home_search_submits_once_and_survives_rerun(self):
        with patch("components.knowledge_pages.search_insights_response",
                   return_value=SearchResponse(status="empty")) as search:
            app = AppTest.from_function(shell).run()
            app.text_input[0].set_value("a useful idea")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["active_page"], "search")
            self.assertEqual(app.session_state["search_query"], "a useful idea")
            search.assert_called_once_with("a useful idea", 10)
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(search.call_count, 1)

    def test_saved_page_no_longer_contains_profile_form(self):
        with patch("components.knowledge_pages.db.get_profile") as profile:
            app = AppTest.from_function(shell)
            app.query_params["page"] = "saved"
            app.run()
            self.assertFalse(app.exception)
            profile.assert_not_called()
            self.assertFalse(app.text_area)


if __name__ == "__main__":
    unittest.main()
