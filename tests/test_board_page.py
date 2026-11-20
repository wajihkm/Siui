"""The board's page against hostile data: nothing a project's files say may become markup, a handler, a link that runs
or a style on the page, in its dialogs or in its exports.

The test serves the real page from a small server of its own, with a record, a card, a status, a chat log and a
universe built by `hostile.py`, opens it in a headless browser, walks it with `page_driver.js` and reads what came
alive. It needs Chrome, Chromium or Edge: `SIUI_TEST_BROWSER` names one, else the usual places are tried; with none the
test is skipped.

    python3 -m unittest discover -s tests -v
"""
import html
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "..", "siui", "board", "index.html")


def find_browser():
    named = os.environ.get("SIUI_TEST_BROWSER", "").strip()
    if named:
        return named if os.path.exists(named) or shutil.which(named) else None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "microsoft-edge", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    for path in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
                 "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe", "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if os.path.exists(path):
            return path
    return None


class Board:
    """The test's own board server: the real page with the driver added, and whatever state it is given."""

    def __init__(self, state, universe, page=None):
        with open(page or PAGE, encoding="utf-8") as handle:
            text = handle.read()
        with open(os.path.join(HERE, "page_driver.js"), encoding="utf-8") as handle:
            driver = handle.read()
        at = text.rindex("</body>")
        self.page = (text[:at] + "<script>" + driver + "</script>" + text[at:]).encode("utf-8")
        self.state, self.universe, self.exports, self.posts = state, universe, {}, []
        board = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, body, kind="application/json", status=200):
                data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                if path == "/":
                    self.send(board.page, "text/html; charset=utf-8")
                elif path == "/state":
                    self.send(board.state)
                elif path == "/head":
                    status = board.state.get("status") if isinstance(board.state, dict) else None
                    self.send({"v": "1", "status": status, "alive": True})
                elif path == "/universe":
                    self.send(board.universe)
                elif path == "/universes":
                    self.send(board.state.get("universes") if isinstance(board.state, dict) else [])
                else:
                    self.send({"error": "not found"}, status=404)

            def do_POST(self):
                path = urllib.parse.urlparse(self.path).path
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                board.posts.append((path, body))
                if path == "/export":
                    board.exports[str(body.get("kind"))] = str(body.get("text"))
                    self.send({"ok": True, "path": hostile.payload("p.export.path")})
                elif path == "/prompt":
                    self.send({"ok": True})
                else:
                    # An error's words come from the server; a hostile one must stay words too.
                    self.send({"ok": False, "error": hostile.payload("p.error")})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def walk_page(browser, state, universe, page=None, budget=90000):
    """Opens the page on the given state, lets the driver walk it, and returns (the driver's notes, the board)."""
    board = Board(state, universe, page)
    try:
        command = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--window-size=1500,1000",
                   f"--virtual-time-budget={budget}", "--dump-dom", f"http://127.0.0.1:{board.port}/"]
        if hasattr(os, "geteuid") and os.geteuid() == 0 or os.environ.get("CI"):
            command.insert(1, "--no-sandbox")
        # A browser that was just closed may answer with nothing once: the walk is tried again before it counts.
        for _ in range(3):
            done = subprocess.run(command, capture_output=True, timeout=300)
            dom = done.stdout.decode("utf-8", "replace")
            found = re.search(r'<pre id="hostile-result"[^>]*>(.*?)</pre>', dom, re.S)
            if found:
                break
            board.exports.clear()
            del board.posts[:]
    finally:
        board.close()
    if not found:
        raise AssertionError("the page gave no result: " + (dom[:300] or done.stderr.decode("utf-8", "replace")[:300]))
    return json.loads(html.unescape(found.group(1))), board


def dump_page(browser, page_html, budget=4000):
    """The final markup of a page of the test's own, served once."""
    data = page_html.encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        command = [browser, "--headless=new", "--disable-gpu", "--no-first-run", f"--virtual-time-budget={budget}", "--dump-dom", f"http://127.0.0.1:{server.server_address[1]}/"]
        if hasattr(os, "geteuid") and os.geteuid() == 0 or os.environ.get("CI"):
            command.insert(1, "--no-sandbox")
        for _ in range(3):
            dom = subprocess.run(command, capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
            if "<pre" in dom:
                return dom
        return dom
    finally:
        server.shutdown()
        server.server_close()


BROWSER = find_browser()


@unittest.skipUnless(BROWSER, "no Chrome, Chromium or Edge found; set SIUI_TEST_BROWSER")
class HostilePage(unittest.TestCase):
    maxDiff = None

    def check(self, notes, board, drawn):
        self.assertTrue(notes["control"] and notes["controlFired"], "the control payload was not seen: the test proves nothing")
        self.assertTrue(notes["done"], f"the walk did not finish: {notes['error'] or notes}")
        self.assertEqual(notes["error"], "")
        self.assertEqual(notes["live"], [], "a value from the project's files became part of the page")
        self.assertEqual(notes["links"], [], "a value from the project's files became a link that runs")
        self.assertEqual(notes["pwn"], 0, "a value from the project's files ran as script")
        self.assertNotRegex(notes["style"], r"url\(|expression|display:\s*none", "a palette value left its rule")
        if drawn:
            self.assertGreater(notes["tiles"], 3, "the roadmap was not drawn, so nothing was tested")
            self.assertGreater(notes["stops"], 3, "no stage was drawn, so nothing was tested")
        for kind, text in board.exports.items():
            found = hostile.live_in_markdown(text) if kind == "md" else hostile.live_in_markup(text)
            self.assertEqual(found, [], f"the {kind} export carries something alive")
        for path, body in board.posts:
            if path == "/prompt":
                self.assertNotRegex(str(body.get("text")), r"<|onerror|javascript:|__pwn", "a prompt to the chat carries a value from the project's files")

    def test_checkers_see_a_live_export(self):
        bad = '<p>x</p><img src="x:" onerror="1" data-pwn="k"><a href="javascript:1">l</a><script>1</script>'
        self.assertGreaterEqual(len(hostile.live_in_markup(bad)), 4)
        self.assertEqual(hostile.live_in_markup('<p title="&lt;img data-pwn=1&gt;">&lt;img src=x onerror=1&gt; data-pwn="k"</p>'), [])
        self.assertEqual(len(hostile.live_in_markdown("a <img src=x> and [l](javascript:1)")), 2)
        self.assertEqual(hostile.live_in_markdown("a &lt;img src=x&gt; and [l]\\(javascript:1)"), [])

    def test_every_free_text_is_a_payload(self):
        notes, board = walk_page(BROWSER, hostile.text_state(), hostile.hostile_universe())
        self.check(notes, board, drawn=True)
        self.assertGreater(notes["good"], 0, "an honest drawing of the universe was not drawn")
        self.assertEqual(sorted(board.exports), ["html", "md", "svg"], "the three exports did not all run")

    def test_wrong_types_where_numbers_and_dates_belong(self):
        notes, board = walk_page(BROWSER, hostile.type_state(), hostile.hostile_universe())
        self.check(notes, board, drawn=True)

    def test_everything_a_payload(self):
        notes, board = walk_page(BROWSER, hostile.wild_state(), hostile.hostile_universe(), budget=40000)
        self.check(notes, board, drawn=False)

    def test_nothing_where_everything_belongs(self):
        notes, board = walk_page(BROWSER, hostile.empty_state(), hostile.payload("u.whole"), budget=30000)
        self.check(notes, board, drawn=False)

    def test_shipped_universes_keep_every_drawing(self):
        """The allowlist for a universe's drawings must pass everything the plugin's own sets draw, unchanged in what
        it shows: a new set that needs another shape or attribute fails here, not silently on the board."""
        with open(PAGE, encoding="utf-8") as handle:
            page = handle.read()
        code = re.search(r"\n  const SVG_SHAPES = .*?\n  function safeSvg\(text\) \{.*?\n  \}\n", page, re.S)
        self.assertTrue(code, "safeSvg was not found in the page")
        drawings = {}
        folder = os.path.join(hostile.BOARD, "universes")
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                one = json.load(handle)
            for key, value in (one.get("glyphs") or {}).items():
                drawings[f"{name} glyph {key}"] = value
            for key, value in (one.get("worlds") or {}).items():
                drawings[f"{name} world {key}"] = (value or {}).get("svg")
            for key in ("tileMotif", "linkMotif"):
                if (one.get("shapes") or {}).get(key):
                    drawings[f"{name} shape {key}"] = one["shapes"][key]
            if (one.get("toggle") or {}).get("svg"):
                drawings[f"{name} toggle"] = one["toggle"]["svg"]
        self.assertGreater(len(drawings), 100)
        bad = dict(enumerate(hostile.bad_drawings("k")))
        script = (code.group(0) + "\nconst given = " + json.dumps(drawings).replace("</", "<\\/") + ", bad = " + json.dumps(bad).replace("</", "<\\/") + ";\n"
                  "const shapes = s => (s.match(/<[a-z]+/g) || []).length;\n"
                  "const out = { dropped: Object.keys(given).filter(k => !safeSvg(given[k])), thinner: Object.keys(given).filter(k => safeSvg(given[k]) && shapes(safeSvg(given[k])) !== shapes(given[k])),\n"
                  "  kept: Object.keys(bad).filter(k => safeSvg(bad[k])) };\n"
                  "const pre = document.createElement('pre'); pre.id = 'hostile-result'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);")
        dom = dump_page(BROWSER, "<!doctype html><meta charset=utf-8><body><script>" + script + "</script>")
        found = re.search(r'<pre id="hostile-result"[^>]*>(.*?)</pre>', dom, re.S)
        self.assertTrue(found, "the page gave no result: " + dom[:300])
        result = json.loads(html.unescape(found.group(1)))
        self.assertEqual(result["dropped"], [], "a shipped drawing no longer passes")
        self.assertEqual(result["thinner"], [], "a shipped drawing lost a shape")
        self.assertEqual(result["kept"], [], "a hostile drawing passed")

    def test_an_honest_state_still_draws(self):
        with open(os.path.join(hostile.BOARD, "universes", "classic.json"), encoding="utf-8") as handle:
            classic = json.load(handle)
        state = hostile.base_state()
        state["config"]["theme"]["universe"] = "classic"
        notes, board = walk_page(BROWSER, state, classic)
        self.check(notes, board, drawn=True)
        self.assertEqual(notes["pageError"], "")
        self.assertEqual(sorted(board.exports), ["html", "md", "svg"])
        for kind in ("html", "md"):
            self.assertIn("Project name", board.exports[kind])
            self.assertIn("A status page", board.exports[kind])
        self.assertIn("<svg", board.exports["svg"])


if __name__ == "__main__":
    unittest.main()
