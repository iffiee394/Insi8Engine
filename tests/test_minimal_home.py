"""Landing, the simple fallback view, and the deferred-feature boundary.

The app opens on the full Stitch dashboard: video list beside a detail pane
with Insights / Timeline / Research / Resources. The stripped-back native
library stays available at ?page=simple, and Search / Saved / Ask remain
reachable though they are not in the navigation.
"""

import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def shell():
    from components.ui_shell import render_app
    render_app({})


DONE_VIDEO = {
    "video_id": "donevideo01",
    "title": "A useful idea",
    "status": "done",
    "processed_at": "2026-09-12",
    "channel_name": "Example channel",
    "url": "https://www.youtube.com/watch?v=donevideo01",
    "structured_insights": '{"insights":[{"topic":"Test topic","points":["Useful detail"]}]}',
}
LIGHT = [
    {"video_id": "failed00001", "title": "Failed video", "status": "failed"},
    {k: v for k, v in DONE_VIDEO.items() if k != "structured_insights"},
]


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.stack = []
        for target, value in [
            ("components.ui_shell.dbcache.list_videos_light", LIGHT),
            ("components.stitch_pages.dbcache.get_video", DONE_VIDEO),
            ("components.baseline_pages.dbcache.get_video", DONE_VIDEO),
        ]:
            p = patch(target, return_value=value)
            p.start()
            self.stack.append(p)

    def tearDown(self):
        for p in reversed(self.stack):
            p.stop()

    def test_opens_on_the_full_dashboard(self):
        app = AppTest.from_function(shell).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["active_page"], "library")
        self.assertEqual(app.session_state["selected_id"], "donevideo01")

    def test_legacy_home_url_lands_on_the_library(self):
        app = AppTest.from_function(shell)
        app.query_params["page"] = "home"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["active_page"], "library")

    def test_simple_view_is_still_available_and_shows_insights(self):
        app = AppTest.from_function(shell)
        app.query_params["page"] = "simple"
        app.run()
        self.assertFalse(app.exception)
        keys = [b.key for b in app.button]
        self.assertIn("lib_pick_donevideo01", keys)
        # Insight point is on the page without opening an expander.
        self.assertIn("Useful detail", " ".join(m.value for m in app.markdown))

    def test_add_page_does_not_read_the_library(self):
        with patch("components.ui_shell.dbcache.list_videos_light") as listing:
            app = AppTest.from_function(shell)
            app.query_params["page"] = "add"
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["active_page"], "add")
            listing.assert_not_called()

    def test_deferred_pages_are_kept_and_still_reachable(self):
        with patch("components.future_pages.search_insights_response"), \
             patch("components.future_pages.dbcache.list_playlists", return_value=[]), \
             patch("components.future_pages.knowledge_store.list_collections", return_value=[]), \
             patch("components.future_pages.knowledge_store.list_saved_items", return_value=[]):
            for page in ("search", "saved"):
                app = AppTest.from_function(shell)
                app.query_params["page"] = page
                app.run()
                self.assertFalse(app.exception, f"{page} raised")
                self.assertEqual(app.session_state["active_page"], page)


if __name__ == "__main__":
    unittest.main()
