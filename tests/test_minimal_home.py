"""Landing, navigation and the deferred-feature boundary.

The app opens on the library: the point is to read insights, not to search.
Search / Saved / Ask are intentionally out of the navigation but must stay
reachable and working, because the next iteration builds on them.
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
    "structured_insights": '{"insights":[{"topic":"Test topic","points":["Useful detail"]}]}',
}


class LibraryLandingTests(unittest.TestCase):
    def setUp(self):
        self.stack = []
        videos = [
            {"video_id": "failed00001", "title": "Failed video", "status": "failed"},
            {k: v for k, v in DONE_VIDEO.items() if k != "structured_insights"},
        ]
        for target, value in [
            ("components.ui_shell.dbcache.list_videos_light", videos),
            ("components.baseline_pages.dbcache.get_video", DONE_VIDEO),
        ]:
            p = patch(target, return_value=value)
            p.start()
            self.stack.append(p)

    def tearDown(self):
        for p in reversed(self.stack):
            p.stop()

    def test_opens_on_library_with_insights_already_visible(self):
        app = AppTest.from_function(shell).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["active_page"], "library")
        # The insight point is on the page without opening an expander.
        self.assertIn("Useful detail", " ".join(m.value for m in app.markdown))

    def test_every_video_is_listed_not_hidden_in_a_dropdown(self):
        app = AppTest.from_function(shell).run()
        keys = [b.key for b in app.button]
        self.assertIn("lib_pick_donevideo01", keys)
        self.assertIn("lib_pick_failed00001", keys)
        self.assertEqual(len(app.selectbox), 0)

    def test_navigation_offers_only_the_core_loop(self):
        app = AppTest.from_function(shell).run()
        nav = {b.key for b in app.button if (b.key or "").startswith("nav_")}
        self.assertEqual(nav, {"nav_library", "nav_playlists", "nav_add",
                               "nav_queue", "nav_settings"})
        for deferred in ("nav_search", "nav_saved", "nav_chat"):
            self.assertNotIn(deferred, nav)

    def test_deferred_pages_are_kept_and_still_reachable(self):
        with patch("components.future_pages.search_insights_response"):
            app = AppTest.from_function(shell)
            app.query_params["page"] = "search"
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["active_page"], "search")

    def test_add_page_does_not_read_the_library(self):
        app = AppTest.from_function(shell).run()
        app.session_state["scratch"] = "keep me"
        with patch("components.ui_shell.dbcache.list_videos_light") as listing:
            app.button(key="nav_add").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["active_page"], "add")
            self.assertEqual(app.session_state["scratch"], "keep me")
            listing.assert_not_called()

    def test_legacy_home_url_lands_on_the_library(self):
        app = AppTest.from_function(shell)
        app.query_params["page"] = "home"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["active_page"], "library")


if __name__ == "__main__":
    unittest.main()
