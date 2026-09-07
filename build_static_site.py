"""Build a static, read-only export of the Library / Queue / Playlists views.

The Stitch UI already renders each page as a self-contained HTML document —
every video's detail pane is embedded up front and swapped client-side — so a
static build only has to swap the Streamlit query-param navigation for plain
links and neutralise the actions that need a backend (add / export / retry).

Usage:  python build_static_site.py [output_dir]
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import db
from components import stitch_pages as sp

OUT_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "site")

# Static replacement for the iframe->parent query-param navigation bridge.
_STATIC_NAV = """
<script>
function _nav(params) {
  var page = (params && params.page) || 'library';
  var q = params && params.vid ? ('?vid=' + encodeURIComponent(params.vid)) : '';
  window.location.href = page + '.html' + q;
}
function goPage(p) { _nav({ page: p }); }
function selectVideo(v) { _nav({ page: 'library', vid: v }); }
</script>
"""

# Appended to every generated page: hide/disable everything that needs a server.
_STATIC_SHIM = """
<style>
  /* Backend-only affordances have no meaning in the static export. */
  .btn[onclick*="openAdd"], .pl-new { display: none !important; }
</style>
<script>
(function () {
  function notice(msg) {
    var el = document.getElementById('static-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'static-toast';
      el.style.cssText = 'position:fixed;left:50%;bottom:26px;transform:translateX(-50%);' +
        'background:#1b1b2b;color:#e8e8f0;border:1px solid #2a2a42;border-radius:10px;' +
        'padding:11px 16px;font:13px system-ui,sans-serif;z-index:9999;box-shadow:0 8px 28px rgba(0,0,0,.45)';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.style.opacity = '0'; }, 2600);
  }
  var msg = 'Read-only snapshot — run InsightEngine locally to process videos.';
  window.openAdd = function () { notice(msg); };
  window.closeAdd = function () {};
  window.doIngest = function () { notice(msg); };
  window.exportVideo = function () { notice(msg); };
  window.retryVideo = function () { notice(msg); };
  window.saveProfile = function () { notice(msg); };

  /* Deep link: library.html?vid=<id> selects that video on load. */
  var vid = new URLSearchParams(window.location.search).get('vid');
  if (vid && typeof pickVideo === 'function') {
    document.addEventListener('DOMContentLoaded', function () { pickVideo(vid); });
    if (document.readyState !== 'loading') pickVideo(vid);
  }
})();
</script>
"""

_INDEX = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta http-equiv="refresh" content="0; url=library.html"/>
<title>InsightEngine</title></head>
<body><p>Redirecting to <a href="library.html">the library</a>…</p></body></html>
"""


def main() -> int:
    db.init_db()
    videos = db.list_videos()
    playlists = db.list_playlists()

    captured: dict[str, str] = {}
    current: dict[str, str] = {}

    def capture(html: str) -> None:
        captured[current["name"]] = html.replace("</body>", _STATIC_SHIM + "</body>")

    # Swap the Streamlit-specific pieces before rendering.
    sp._embed = capture          # type: ignore[assignment]
    sp._NAV = _STATIC_NAV        # type: ignore[assignment]

    current["name"] = "library"
    # Full rows + every pane embedded: the published page has no server to ask
    # for a video that was not pre-rendered.
    sp.render_library_page(
        db.list_videos(), selected_id=None, active_tab="library", embed_all_details=True
    )

    current["name"] = "queue"
    sp.render_queue_page(videos)

    current["name"] = "playlists"
    sp.render_playlists_page(playlists, videos)

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    for name, html in captured.items():
        path = OUT_DIR / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        print(f"  {path}  ({len(html) / 1024:.0f} KB)")

    (OUT_DIR / "index.html").write_text(_INDEX, encoding="utf-8")
    print(f"  {OUT_DIR / 'index.html'}")
    print(f"\nBuilt {len(captured) + 1} pages from {len(videos)} videos "
          f"and {len(playlists)} playlists into {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
