"""HTTP server for the meme picker web UI.

Stdlib only (http.server + sqlite3), same reasoning as emojifont.fetch: this
is a small local tool, not worth a framework dependency. One page, a JSON
API, and a route that serves indexed image files back to the browser.

Binds to 127.0.0.1 by default — this exposes filesystem paths (image files,
and the font paths you type into the generate form) with no auth, so it
should not be put on a shared network without adding some.
"""

import argparse
import json
import mimetypes
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from emojifont.fetch import DEFAULT_START_CODEPOINT, assign_codepoints
from emojifont.inject import inject_sbix_memes
from emojifont.webui.db import Store

INDEX_HTML_PATH = Path(__file__).parent / "index.html"

GET_ROUTES = [
    (re.compile(r"^/$"), "serve_index"),
    (re.compile(r"^/api/memes$"), "api_list_memes"),
    (re.compile(r"^/api/sources$"), "api_sources"),
    (re.compile(r"^/api/selection$"), "api_selection"),
    (re.compile(r"^/api/config$"), "api_config"),
    (re.compile(r"^/images/(\d+)$"), "serve_image"),
]
POST_ROUTES = [
    (re.compile(r"^/api/memes/(\d+)/star$"), "api_star"),
    (re.compile(r"^/api/memes/(\d+)/select$"), "api_select"),
    (re.compile(r"^/api/selection/reorder$"), "api_reorder"),
    (re.compile(r"^/api/selection/clear$"), "api_clear_selection"),
    (re.compile(r"^/api/rescan$"), "api_rescan"),
    (re.compile(r"^/api/generate$"), "api_generate"),
]


def _hex_codepoint(s):
    return int(s.removeprefix("U+").removeprefix("u+"), 16)


def make_handler(store, config):
    """Build a request handler class closing over `store` and `config`.

    BaseHTTPRequestHandler is instantiated per-request by the server, so the
    shared Store and config have to reach it as class attributes rather than
    constructor arguments.
    """

    class Handler(BaseHTTPRequestHandler):
        server_version = "emojifont-webui/1"
        store = None
        config = None

        # -- dispatch ---------------------------------------------------------

        def do_GET(self):
            self._dispatch(GET_ROUTES)

        def do_POST(self):
            self._dispatch(POST_ROUTES)

        def _dispatch(self, routes):
            parts = urlsplit(self.path)
            path, query = parts.path, parse_qs(parts.query)
            for pattern, name in routes:
                m = pattern.match(path)
                if m:
                    try:
                        getattr(self, name)(*m.groups(), query=query)
                    except Exception as exc:  # noqa: BLE001 - report, don't crash the server
                        traceback.print_exc(file=sys.stderr)
                        self._json(500, {"error": str(exc)})
                    return
            if path.startswith("/api/"):
                self._json(404, {"error": "not found"})
            else:
                self.send_error(404)

        # -- response helpers ---------------------------------------------------

        def _json(self, status, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}

        # -- pages ---------------------------------------------------------

        def serve_index(self, query):
            body = INDEX_HTML_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def serve_image(self, meme_id, query):
            meme = self.store.get_meme(int(meme_id))
            if not meme:
                self._json(404, {"error": "no such meme"})
                return
            path = Path(meme["root"]) / meme["rel_path"]
            # Defense in depth: the id->path lookup only ever produces paths
            # under an indexed root, but confirm containment before opening
            # anything, in case a future root ever gets misconfigured.
            try:
                path.resolve().relative_to(Path(meme["root"]).resolve())
            except ValueError:
                self._json(400, {"error": "path escapes root"})
                return
            if not path.is_file():
                self._json(404, {"error": "file missing on disk"})
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)

        # -- read API ---------------------------------------------------------

        def api_config(self, query):
            self._json(200, {
                "default_base_font": self.config["default_base_font"],
                "default_output": self.config["default_output"],
                "scan_dirs": [str(d) for d in self.config["scan_dirs"]],
            })

        def api_list_memes(self, query):
            def flag(name):
                v = query.get(name, [None])[0]
                if v is None or v == "":
                    return None
                return v in ("1", "true", "yes")

            limit = min(int(query.get("limit", ["300"])[0]), 1000)
            offset = int(query.get("offset", ["0"])[0])
            memes, total = self.store.list_memes(
                search=query.get("search", [None])[0] or None,
                source=query.get("source", [None])[0] or None,
                starred=flag("starred"),
                selected=flag("selected"),
                limit=limit,
                offset=offset,
            )
            self._json(200, {"items": memes, "total": total, "offset": offset, "limit": limit})

        def api_sources(self, query):
            self._json(200, {"sources": self.store.sources()})

        def api_selection(self, query):
            self._json(200, {"items": self.store.selected_ordered()})

        # -- write API ---------------------------------------------------------

        def api_star(self, meme_id, query):
            body = self._read_json_body()
            ok = self.store.set_starred(int(meme_id), bool(body.get("starred")))
            if not ok:
                self._json(404, {"error": "no such meme"})
                return
            self._json(200, {"ok": True})

        def api_select(self, meme_id, query):
            body = self._read_json_body()
            meme = self.store.get_meme(int(meme_id))
            if not meme:
                self._json(404, {"error": "no such meme"})
                return
            want = bool(body.get("selected"))
            if want and meme["ext"] == ".gif":
                self._json(400, {"error": "animated images can't be used (SBIX shows one still frame)"})
                return
            self.store.set_selected(int(meme_id), want)
            self._json(200, {"ok": True})

        def api_reorder(self, query):
            body = self._read_json_body()
            direction = -1 if body.get("direction") == "up" else 1
            ok = self.store.reorder_selected(int(body.get("id")), direction)
            self._json(200, {"ok": ok})

        def api_clear_selection(self, query):
            n = self.store.clear_selection()
            self._json(200, {"cleared": n})

        def api_rescan(self, query):
            body = self._read_json_body()
            dirs = body.get("dirs") or self.config["scan_dirs"]
            added, missing = self.store.scan(dirs)
            self._json(200, {"added": added, "missing": missing})

        def api_generate(self, query):
            body = self._read_json_body()
            base_font = body.get("base_font") or self.config["default_base_font"]
            output_path = body.get("output_path") or self.config["default_output"]
            font_name = body.get("font_name") or "MemeFont"
            try:
                ppem = int(body.get("ppem") or 160)
            except (TypeError, ValueError):
                self._json(400, {"error": "ppem must be a number"})
                return

            if not base_font or not Path(base_font).is_file():
                self._json(400, {"error": f"base font not found: {base_font}"})
                return
            if not output_path:
                self._json(400, {"error": "output path is required"})
                return
            if Path(base_font).resolve() == Path(output_path).resolve():
                self._json(400, {"error": "output path must differ from the base font"})
                return

            start_raw = body.get("start_codepoint")
            try:
                start_cp = _hex_codepoint(start_raw) if start_raw else DEFAULT_START_CODEPOINT
            except ValueError:
                self._json(400, {"error": f"invalid start codepoint: {start_raw!r}"})
                return

            selected = self.store.selected_ordered()
            if not selected:
                self._json(400, {"error": "no memes selected"})
                return

            animated = [m for m in selected if m["ext"] == ".gif"]
            if animated:
                self._json(400, {
                    "error": "selection contains animated images, which can't be used: "
                             + ", ".join(m["name"] for m in animated)
                })
                return

            try:
                codepoints = assign_codepoints(len(selected), start_cp)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return

            mappings, missing_files = {}, []
            for cp, meme in zip(codepoints, selected):
                path = Path(meme["root"]) / meme["rel_path"]
                if not path.is_file():
                    missing_files.append(meme["name"])
                    continue
                mappings[cp] = str(path)
            if missing_files:
                self._json(400, {
                    "error": "selected file(s) missing on disk: " + ", ".join(missing_files)
                             + " — rescan to refresh."
                })
                return

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            try:
                inject_sbix_memes(base_font, output_path, mappings, ppem=ppem, font_name=font_name)
            except Exception as exc:  # noqa: BLE001 - surface to the UI as a generation error
                self._json(500, {"error": f"font generation failed: {exc}"})
                return

            self._json(200, {
                "output_path": str(Path(output_path).resolve()),
                "count": len(mappings),
                "mapping": [
                    {"codepoint": f"U+{cp:04X}", "name": m["name"]}
                    for cp, m in zip(codepoints, selected)
                ],
            })

        def log_message(self, fmt, *args):
            # Default BaseHTTPRequestHandler logging to stderr is fine for a
            # local dev tool; this override exists only to route it through
            # a single place if that ever needs to change.
            super().log_message(fmt, *args)

    Handler.store = store
    Handler.config = config
    return Handler


def default_scan_dirs(project_root):
    candidates = [
        project_root / "font_build" / "meme-dump",
        project_root / "font_build" / "ffz-dump",
        project_root / "font_build" / "memes",
    ]
    return [d for d in candidates if d.is_dir()]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="emojifont-web",
        description="Local web UI: browse downloaded memes, star/select a subset, generate a font.",
    )
    project_root = Path(__file__).resolve().parents[3]
    parser.add_argument("--host", default="127.0.0.1",
                       help="bind address (default 127.0.0.1 — this server has no auth)")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--db", default=str(project_root / "font_build" / "memepicker.sqlite3"),
                       help="sqlite database path (persists stars/selection across runs)")
    parser.add_argument("--scan-dir", action="append", dest="scan_dirs",
                       help="directory to index for memes (repeatable); default: the "
                            "font_build/*-dump and font_build/memes dirs, if present")
    parser.add_argument("--base-font", default=str(project_root / "font_build" / "MonacoNerdFontMono-Regular.ttf"),
                       help="default base font offered in the generate form")
    parser.add_argument("--output", default=str(project_root / "font_build" / "MemeFont.ttf"),
                       help="default output path offered in the generate form")
    parser.add_argument("--no-scan", action="store_true",
                       help="skip the startup scan (index is built already / rescan from the UI)")
    args = parser.parse_args(argv)

    scan_dirs = [Path(d) for d in args.scan_dirs] if args.scan_dirs else default_scan_dirs(project_root)

    store = Store(args.db)
    if not args.no_scan and scan_dirs:
        print(f"Scanning {len(scan_dirs)} director(y/ies) for memes...")
        added, missing = store.scan(scan_dirs)
        print(f"  {added} new, {missing} newly missing")
    elif not scan_dirs:
        print("No scan directories found or configured — pass --scan-dir, or run "
              "emojifont-fetch dump / ffz-dump first.", file=sys.stderr)

    config = {
        "scan_dirs": scan_dirs,
        "default_base_font": args.base_font,
        "default_output": args.output,
    }
    handler = make_handler(store, config)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"emojifont-web serving at {url}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
