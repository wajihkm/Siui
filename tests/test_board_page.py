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
import time
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


def browse(browser, address, budget, accept, before_retry=None, size="1500,1000"):
    """The final markup of the page at `address`, from a headless browser. A browser started while the one before it
    is still closing may answer with nothing: it is tried once more, a little later, until `accept(markup)`."""
    command = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--window-size={size}",
               f"--virtual-time-budget={budget}", "--dump-dom", address]
    if hasattr(os, "geteuid") and os.geteuid() == 0 or os.environ.get("CI"):
        command.insert(1, "--no-sandbox")
    dom = ""
    for pause in (0, 1.5):
        if pause:
            time.sleep(pause)
            if before_retry:
                before_retry()
        try:
            dom = subprocess.run(command, capture_output=True, timeout=300).stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            dom = ""
        if accept(dom):
            break
    return dom


def on_a_port_that_answers(make, visit, accept, close):
    """Runs `visit(server)` on a server from `make()`, and on a new one when the browser gets nothing from it: a
    browser of another system (Windows' from WSL) cannot reach every port a test server may be given. Returns
    (the markup, the server), the server still running for the caller to read and close."""
    dom, server = "", None
    for _ in range(4):
        server = make()
        dom = visit(server)
        if accept(dom):
            break
        close(server)
        server = None
    return dom, server


class Board:
    """The test's own board server: the real page with the driver added, and whatever state it is given."""

    KEY = "k" * 43

    def __init__(self, state, universe, page=None, driver=None):
        with open(page or PAGE, encoding="utf-8") as handle:
            text = handle.read()
        if driver is None:
            with open(os.path.join(HERE, "page_driver.js"), encoding="utf-8") as handle:
                driver = handle.read()
        at = text.rindex("</body>")
        self.page = (text[:at] + "<script>" + driver + "</script>" + text[at:]).encode("utf-8")
        self.state, self.universe, self.exports, self.posts = state, universe, {}, []
        self.served = []  # every data call that carried the key, in order: (method, path)
        self.refused = []  # every data call that did not
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

            def keyed(self, path):
                """Like the real server: data is for the holder of the key."""
                if self.headers.get("X-Siui-Key") == board.KEY:
                    board.served.append((self.command, path))
                    return True
                board.refused.append((self.command, path))
                self.send({"ok": False, "error": "no key"}, status=401)
                return False

            def do_GET(self):
                path = urllib.parse.urlparse(self.path).path
                if path == "/":
                    self.send(board.page, "text/html; charset=utf-8")
                elif path in ("/icon.svg", "/icon.png"):
                    self.send(b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml")
                elif not self.keyed(path):
                    return
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
                if not self.keyed(path):
                    return
                board.posts.append((path, body))
                if path == "/export":
                    board.exports[str(body.get("kind"))] = str(body.get("text"))
                    self.send({"ok": True, "path": hostile.payload("p.export.path")})
                elif path == "/prompt":
                    self.send({"ok": True})
                elif path == "/checkpoint" and "newFiles" not in body:
                    # The question about new files: their names are the project's own.
                    self.send({"ok": False, "ask": "newFiles", "files": [hostile.payload("p.new.1"), hostile.payload("p.new.2")],
                               "count": hostile.payload("p.new.count"), "error": hostile.payload("p.new.error")})
                else:
                    # An error's words come from the server; a hostile one must stay words too.
                    self.send({"ok": False, "error": hostile.payload("p.error")})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def walk_page(browser, state, universe, page=None, budget=90000, driver=None, address="/?k=" + Board.KEY):
    """Opens the page on the given state, lets the driver walk it, and returns (the driver's notes, the board)."""
    result = re.compile(r'<pre id="hostile-result"[^>]*>(.*?)</pre>', re.S)

    def visit(board):
        def afresh():
            board.exports.clear()
            del board.posts[:], board.served[:], board.refused[:]
        return browse(browser, f"http://127.0.0.1:{board.port}{address}", budget, result.search, afresh)

    dom, board = on_a_port_that_answers(lambda: Board(state, universe, page, driver), visit, result.search, lambda one: one.close())
    if board is None:
        raise AssertionError("the page gave no result: " + dom[:300])
    board.close()
    found = result.search(dom)
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

    def make():
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def close(server):
        server.shutdown()
        server.server_close()

    has_result = lambda dom: "<pre" in dom  # noqa: E731
    dom, server = on_a_port_that_answers(make, lambda server: browse(browser, f"http://127.0.0.1:{server.server_address[1]}/", budget, has_result), has_result, close)
    if server is not None:
        close(server)
    return dom


# A driver that only waits and reports what is drawn: for the tests about the key, which walk nothing.
WAIT_ONLY = """
  (async () => {
    const pre = document.createElement('pre'); pre.id = 'hostile-result'; pre.hidden = true; document.body.appendChild(pre);
    await new Promise(done => setTimeout(done, 3000));
    pre.textContent = JSON.stringify({ done: true, tiles: document.querySelectorAll('#roadmap .tile[data-run]').length, nokey: !document.getElementById('nokey').hidden });
  })();
"""

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
                self.assertNotRegex(str(body.get("text")), r"PLANTED_|Ignore the pack|<|onerror|javascript:|__pwn", "a prompt to the chat carries a text of the project's files")

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
        self.assertTrue(notes["asked"], "the question about a save point's new files was not shown")
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

    def test_every_call_of_the_page_carries_the_key(self):
        notes, board = walk_page(BROWSER, hostile.base_state(), hostile.payload("u.none"), budget=20000)
        self.assertTrue(notes["done"], notes)
        # The one call without it is the page trying the key it was given.
        self.assertEqual(board.refused, [])
        self.assertGreater(len([one for one in board.served if one == ("GET", "/state")]), 0)

    def test_a_page_without_a_key_asks_nothing(self):
        notes, board = walk_page(BROWSER, hostile.base_state(), hostile.payload("u.none"), budget=8000, address="/", driver=WAIT_ONLY)
        self.assertEqual((board.served, board.refused, notes["tiles"], notes["nokey"]), ([], [], 0, True))

    def test_a_link_from_anywhere_cannot_replace_or_erase_the_key(self):
        """First the page is opened with its key; then, as a link on another site would, with a key that is not one.
        The browser must still hold the first and draw the board with it."""
        driver = """
          (async () => {
            const pre = document.createElement('pre'); pre.id = 'hostile-result'; pre.hidden = true; document.body.appendChild(pre);
            const sleep = ms => new Promise(done => setTimeout(done, ms));
            await sleep(1500);
            if (!sessionStorage.getItem('second')) { sessionStorage.setItem('second', '1'); location.href = '/?k=' + 'j'.repeat(43) + '#export=md'; return; }
            pre.textContent = JSON.stringify({ done: true, tiles: document.querySelectorAll('#roadmap .tile[data-run]').length, nokey: !document.getElementById('nokey').hidden, address: location.search + location.hash });
          })();
        """
        notes, board = walk_page(BROWSER, hostile.base_state(), hostile.payload("u.none"), budget=12000, driver=driver)
        self.assertEqual(notes["nokey"], False, "a link with a wrong key made the browser lose the right one")
        self.assertGreater(notes["tiles"], 3)
        self.assertEqual(notes["address"], "", "the key or the export order stayed in the address bar")
        # The wrong key was tried once and refused; nothing else went out without the right one.
        self.assertEqual(board.refused, [("GET", "/head")])
        # An export by address is for the address that brings the key itself: this one did not.
        self.assertEqual(board.exports, {})

    def test_an_export_by_address_needs_the_key_in_the_address(self):
        _, board = walk_page(BROWSER, hostile.base_state(), hostile.payload("u.none"), budget=12000, driver=WAIT_ONLY, address="/?k=" + Board.KEY + "#export=md")
        self.assertEqual(sorted(board.exports), ["md"])

    def test_a_board_framed_by_another_site_takes_no_key(self):
        """A page on another port of this machine shares the browser's storage with the board. Framed there, the
        board must not use a key, whether it comes in the address or was kept before."""
        def attempt():
            board = Board(hostile.base_state(), hostile.payload("u.none"), driver="")
            try:
                first = f"http://127.0.0.1:{board.port}/?k={Board.KEY}"
                # The stranger's page first sends the browser to the board, so the key is kept; then frames the board.
                stranger = ("<!doctype html><body><script>"
                            "if (!sessionStorage.getItem('back')) { sessionStorage.setItem('back', '1'); location.href = %s + '#then=' + encodeURIComponent(location.href); }"
                            "else { const f = document.createElement('iframe'); f.src = %s; document.body.appendChild(f); const g = document.createElement('iframe'); g.src = %s; document.body.appendChild(g);"
                            " setTimeout(() => { const p = document.createElement('pre'); p.id = 'hostile-result'; p.textContent = 'framed'; document.body.appendChild(p); }, 4000); }"
                            "</script>") % (json.dumps(first), json.dumps(f"http://127.0.0.1:{board.port}/"), json.dumps(first))
                # The board's page, top-level, comes back to the stranger once it holds its key.
                at = board.page.rindex(b"</body>")
                board.page = (board.page[:at] + b"<script>setTimeout(() => { const m = /^#then=(.+)$/.exec(location.hash); if (m) location.href = decodeURIComponent(m[1]); }, 2500);</script>"
                              + board.page[at:])
                dom = dump_page(BROWSER, stranger, budget=14000)
            finally:
                board.close()
            return dom, board

        # A port the browser cannot reach leaves the board without its key and proves nothing: another is taken.
        for _ in range(4):
            dom, board = attempt()
            states = [one for one in board.served if one == ("GET", "/state")]
            if "framed" in dom and states:
                break
        self.assertIn("framed", dom, "the stranger's page did not get to frame the board: " + dom[:200])
        # A page reads the state once when it is drawn. The board in its own tab did; the two framed copies, one
        # at the plain address (the key kept by the browser) and one with the key in its address, must not have.
        self.assertGreater(len(states), 0, "the board never held its key, so the frames proved nothing")
        self.assertEqual(len(states), 1, "a board framed by another site read the state with the key")
        self.assertEqual(board.refused, [])

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
        # A pack in a place the plugin knows is named with its path, the only way the assistant can find one the
        # plugin ships; a pack in a folder the configuration names is named by its slug alone.
        asked = [str(body.get("text")) for path, body in board.posts if path == "/prompt"]
        self.assertTrue([one for one in asked if "Start the pack release as world 5: read the pack at /tmp/home/.claude/skills/decision-cards/packs/release.md," in one], asked)
        self.assertTrue([one for one in asked if "Start the pack world-4-page as world 4: read the pack, read" in one], asked)
        # A world started with a method names the method by its slug, with its path when the plugin ships it.
        self.assertTrue([one for one in asked if 'titled "login page"' in one and "Run it with the method spec-driven: read the pack at /tmp/plugin/packs/spec-driven.md and" in one
                         and 'with pack "spec-driven"' in one], asked)
        for kind in ("html", "md"):
            self.assertIn("Project name", board.exports[kind])
            self.assertIn("A status page", board.exports[kind])
        self.assertIn("<svg", board.exports["svg"])


if __name__ == "__main__":
    unittest.main()
