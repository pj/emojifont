"""Integration tests for emojifont.webui.server — a real HTTP server on a real
socket, hitting the actual endpoints the browser would call.

The unit tests in test_webui_db.py cover the store's logic in isolation; this
file exists because the lesson from this project so far is that the bugs that
actually bite live in the wiring between layers (a stale cache, a case
mismatch, a route that never gets exercised) rather than in either layer
alone. The one true end-to-end case — select memes, POST /api/generate, open
the resulting font with fontTools — is the test that would catch a mistake
in how selection order becomes code point order in the real font.
"""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont
from PIL import Image

from emojifont.webui.db import Store
from emojifont.webui.server import default_scan_dirs, make_handler
from http.server import ThreadingHTTPServer

FONT_BUILD_DIR = Path(__file__).parents[1] / "font_build"
BASE_FONT = FONT_BUILD_DIR / "MonacoNerdFontMono-Regular.ttf"


def make_image(path, size=(40, 40), color=(255, 0, 0, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color).save(path, "PNG")
    return path


class LiveServer:
    """A running instance of the webui server on an ephemeral port."""

    def __init__(self, tmp_path, scan_dirs):
        self.tmp_path = tmp_path
        self.store = Store(tmp_path / "picker.sqlite3")
        self.store.scan(scan_dirs)
        config = {
            "scan_dirs": scan_dirs,
            "default_base_font": str(BASE_FONT),
            "default_output": str(tmp_path / "out.ttf"),
        }
        handler = make_handler(self.store, config)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.store.close()

    def request(self, method, path, body=None, expect_status=200):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status, payload = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, payload = e.code, e.read()
        assert status == expect_status, f"{method} {path} -> {status}: {payload[:300]}"
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body, **kw)


@pytest.fixture
def image_root(tmp_path):
    root = tmp_path / "memes"
    make_image(root / "pepe.png", color=(0, 255, 0, 255))
    make_image(root / "shark.png", color=(0, 0, 255, 255))
    make_image(root / "dance.gif")  # written as PNG bytes but .gif extension is what matters here
    return root


@pytest.fixture
def server(tmp_path, image_root):
    s = LiveServer(tmp_path, [image_root])
    yield s
    s.close()


# ---------------------------------------------------------------------------
# browsing
# ---------------------------------------------------------------------------

class TestBrowse:
    def test_index_page_served(self, server):
        req = urllib.request.Request(server.base_url + "/")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            assert b"<html" in resp.read()[:200].lower()

    def test_list_memes(self, server):
        data = server.get("/api/memes")
        assert data["total"] == 3
        assert {m["name"] for m in data["items"]} == {"pepe", "shark", "dance"}

    def test_search_filter(self, server):
        data = server.get("/api/memes?search=pep")
        assert [m["name"] for m in data["items"]] == ["pepe"]

    def test_sources_endpoint(self, server):
        data = server.get("/api/sources")
        assert any(s["source"] == "memes" and s["n"] == 3 for s in data["sources"])

    def test_serves_image_bytes(self, server):
        memes = server.get("/api/memes")["items"]
        meme_id = next(m["id"] for m in memes if m["name"] == "pepe")
        req = urllib.request.Request(server.base_url + f"/images/{meme_id}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "image/png"
            assert resp.read()[:4] == b"\x89PNG"

    def test_image_404_for_unknown_id(self, server):
        server.get("/images/999999", expect_status=404)

    def test_unknown_api_route_is_404_json(self, server):
        data = server.get("/api/nope", expect_status=404)
        assert "error" in data

    def test_config_endpoint(self, server):
        data = server.get("/api/config")
        assert data["default_base_font"] == str(BASE_FONT)


# ---------------------------------------------------------------------------
# star / select
# ---------------------------------------------------------------------------

class TestStarAndSelect:
    def _id_for(self, server, name):
        return next(m["id"] for m in server.get("/api/memes")["items"] if m["name"] == name)

    def test_star_toggle_round_trips(self, server):
        mid = self._id_for(server, "pepe")
        server.post(f"/api/memes/{mid}/star", {"starred": True})
        data = server.get("/api/memes?starred=1")
        assert [m["name"] for m in data["items"]] == ["pepe"]
        server.post(f"/api/memes/{mid}/star", {"starred": False})
        data = server.get("/api/memes?starred=1")
        assert data["items"] == []

    def test_select_toggle_populates_selection_endpoint(self, server):
        mid = self._id_for(server, "shark")
        server.post(f"/api/memes/{mid}/select", {"selected": True})
        data = server.get("/api/selection")
        assert [m["name"] for m in data["items"]] == ["shark"]

    def test_animated_cannot_be_selected(self, server):
        mid = self._id_for(server, "dance")
        resp = server.post(f"/api/memes/{mid}/select", {"selected": True}, expect_status=400)
        assert "animated" in resp["error"].lower()

    def test_star_and_select_are_independent_over_http(self, server):
        mid = self._id_for(server, "pepe")
        server.post(f"/api/memes/{mid}/star", {"starred": True})
        assert server.get("/api/selection")["items"] == []

    def test_star_unknown_id_404s(self, server):
        server.post("/api/memes/999999/star", {"starred": True}, expect_status=404)

    def test_reorder_and_clear(self, server):
        pepe, shark = self._id_for(server, "pepe"), self._id_for(server, "shark")
        server.post(f"/api/memes/{shark}/select", {"selected": True})
        server.post(f"/api/memes/{pepe}/select", {"selected": True})
        server.post("/api/selection/reorder", {"id": pepe, "direction": "up"})
        assert [m["name"] for m in server.get("/api/selection")["items"]] == ["pepe", "shark"]
        server.post("/api/selection/clear")
        assert server.get("/api/selection")["items"] == []

    def test_rescan_finds_newly_added_file(self, server, image_root):
        make_image(image_root / "newone.png")
        data = server.post("/api/rescan", {})
        assert data["added"] == 1
        assert any(m["name"] == "newone" for m in server.get("/api/memes")["items"])


# ---------------------------------------------------------------------------
# generate — the real end-to-end path
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not BASE_FONT.exists(), reason="base font not synced into font_build/")
class TestGenerate:
    def _select(self, server, *names):
        ids = []
        for name in names:
            mid = next(m["id"] for m in server.get("/api/memes")["items"] if m["name"] == name)
            server.post(f"/api/memes/{mid}/select", {"selected": True})
            ids.append(mid)
        return ids

    def test_no_selection_is_rejected(self, server, tmp_path):
        resp = server.post("/api/generate", {
            "base_font": str(BASE_FONT), "output_path": str(tmp_path / "out.ttf"),
        }, expect_status=400)
        assert "no memes selected" in resp["error"]

    def test_missing_base_font_is_rejected(self, server, tmp_path):
        self._select(server, "pepe")
        resp = server.post("/api/generate", {
            "base_font": str(tmp_path / "nope.ttf"), "output_path": str(tmp_path / "out.ttf"),
        }, expect_status=400)
        assert "not found" in resp["error"]

    def test_generates_real_font_with_selection_order_as_codepoint_order(self, server, tmp_path):
        """The core promise of the whole feature: what you selected, in the
        order you selected it, is what ends up in the font at consecutive
        code points starting from F900."""
        self._select(server, "shark", "pepe")
        out = tmp_path / "generated.ttf"
        data = server.post("/api/generate", {
            "base_font": str(BASE_FONT), "output_path": str(out), "font_name": "TestGenFont",
        })
        assert data["count"] == 2
        assert data["mapping"] == [
            {"codepoint": "U+F900", "name": "shark"},
            {"codepoint": "U+F901", "name": "pepe"},
        ]
        assert out.exists()

        font = TTFont(str(out))
        assert "sbix" in font
        cmap = font.getBestCmap()
        assert 0xF900 in cmap and 0xF901 in cmap
        font.close()

    def test_custom_start_codepoint_honoured(self, server, tmp_path):
        self._select(server, "pepe")
        out = tmp_path / "out2.ttf"
        data = server.post("/api/generate", {
            "base_font": str(BASE_FONT), "output_path": str(out), "start_codepoint": "F950",
        })
        assert data["mapping"][0]["codepoint"] == "U+F950"

    def test_same_path_for_input_and_output_rejected(self, server):
        self._select(server, "pepe")
        resp = server.post("/api/generate", {
            "base_font": str(BASE_FONT), "output_path": str(BASE_FONT),
        }, expect_status=400)
        assert "differ" in resp["error"]

    def test_animated_in_selection_blocked_at_generate_too(self, server, tmp_path):
        """Belt and suspenders: even if something animated got selected
        through some other path, generate must still refuse it rather than
        silently baking in whatever single frame PIL happens to decode."""
        mid = next(m["id"] for m in server.get("/api/memes")["items"] if m["name"] == "dance")
        server.store.set_selected(mid, True)  # bypass the API's own guard
        resp = server.post("/api/generate", {
            "base_font": str(BASE_FONT), "output_path": str(tmp_path / "out.ttf"),
        }, expect_status=400)
        assert "animated" in resp["error"].lower()


# ---------------------------------------------------------------------------
# default_scan_dirs
# ---------------------------------------------------------------------------

class TestDefaultScanDirs:
    def test_only_existing_dirs_returned(self, tmp_path):
        (tmp_path / "font_build" / "memes").mkdir(parents=True)
        got = default_scan_dirs(tmp_path)
        assert got == [tmp_path / "font_build" / "memes"]

    def test_empty_when_nothing_exists(self, tmp_path):
        assert default_scan_dirs(tmp_path) == []
