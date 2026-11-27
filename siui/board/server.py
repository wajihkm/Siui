#!/usr/bin/env python3
"""The siui board: a local page that shows the world map, the live card and
the record, and takes input back.

Started by the plugin, detached, once per project. Serves index.html beside this
file; GET /state answers the record, the live card and the configuration, GET
/head a stamp that moves whenever /state would (the page polls that and fetches
/state on a change); POST /answer, /note, /prompt and /open take the page's
input. Only the page may call the routes beyond /, /icon.svg and /icon.png: a local Origin
or Host, JSON for a POST, and the board's key in a header; anything else is
refused. The key is a file in the run folder, the user's alone: another program
or another person on this machine reaches the port but not the file. It is made
anew at every start, so nothing a browser kept outlives the server that guards
the port. The page gets it once, from a one-time pass in the address `/siui
board` opens (POST /enter) or from a link that holds the key itself, and keeps
it in the browser. On Linux a call from another user of the machine is refused
whatever it carries: the kernel names the owner of the other end.
Everything runtime lives in the run folder the plugin names: the live card, the
answer inbox, the prompt inbox, the page's liveness mark and the plugin's
heartbeat. The server exits by itself when the plugin's heartbeat stops or a
stop file appears.

Binds 127.0.0.1 only. Standard library only.
"""

import argparse
import base64
import glob
import hashlib
import hmac
import json
import os
import re
import secrets
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PORT_SPAN = 10  # the ports tried from --port up; an Origin on any of them is the page's own
MAX_BODY = 1 << 20  # a POST body is at most 1 MB; an export may be 24 MB
MAX_EXPORT_BODY = 24 << 20
LOCAL_NAMES = ("127.0.0.1", "localhost")
KEY_HEADER = "X-Siui-Key"
KEY_SHAPE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
PASS_SECONDS = 120  # how long a one-time pass may wait for its page


def new_key(path):
    """Writes a fresh key to its file, the user's alone, in one step, and returns it."""
    key = secrets.token_urlsafe(32)
    handle = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="ascii") as out:
        out.write(key + "\n")
    os.replace(path + ".new", path)
    return key


def start_key(path):
    """The board's key for this run of the server: a new one at every start. A port on this machine is nobody's for
    good: when the server ends, another program may take it and be handed whatever a browser still holds for that
    address. So nothing a browser keeps, and no link, outlives the server that guards the port.

    `SIUI_KEEP_KEY=1` in the person's own environment (never a project's file) keeps one key across starts, so a
    bookmark keeps working: for a machine that is theirs alone."""
    if os.environ.get("SIUI_KEEP_KEY", "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            with open(path, encoding="ascii") as handle:
                key = handle.read().strip()
            if KEY_SHAPE.match(key):
                return key
        except (OSError, ValueError):
            pass
    return new_key(path)


def peer_row(client, server_port):
    """The other end of a connection from this machine, as the kernel's table of connections on Linux shows it: (the
    user who owns it, whether it is still connected). None when there is no row for it (another system, a relay
    from outside this system's own network, a caller already gone).

    The second part matters as much as the first: once a caller closes its end, its row stays for a moment and is
    nobody's, which the kernel writes as the system's own user."""
    host, port = client[0], client[1]

    def written(address, family):
        """An address as the kernel's table writes it: each 32-bit word in this machine's byte order, in hex."""
        packed = socket.inet_pton(family, address)
        return "".join("%08X" % struct.unpack("=I", packed[i:i + 4])[0] for i in range(0, len(packed), 4))

    try:
        # The caller's own socket may be an IPv4 one or an IPv6 one that reaches this address as ::ffff:127.0.0.1;
        # the kernel lists the two in tables of their own.
        tables = (("/proc/net/tcp", socket.AF_INET, host, "127.0.0.1"), ("/proc/net/tcp6", socket.AF_INET6, "::ffff:" + host, "::ffff:127.0.0.1"))
        for table, family, here, there in tables:
            local = "%s:%04X" % (written(here, family), port)
            remote = "%s:%04X" % (written(there, family), server_port)
            try:
                with open(table, encoding="ascii") as handle:
                    for row in handle:
                        parts = row.split()
                        if len(parts) > 7 and parts[1] == local and parts[2] == remote:
                            return int(parts[7]), parts[3] == "01"
            except FileNotFoundError:
                continue
    except (OSError, ValueError, struct.error):
        return None
    return None


def is_foreign(uid, mine):
    """Whether a call is known to come from another user of this machine. The system's own user (0) is not held
    apart: it reads every file here anyway, and a relay such as WSL's runs as it. A server run as that user holds
    nobody apart: there the key alone decides."""
    return uid is not None and mine not in (None, 0) and uid not in (mine, 0)


def has_hung_up(connection):
    """Whether the caller has already closed its end. A browser waits for its answer; a caller that hangs up at once
    leaves no row in the kernel's table for `peer_row` to read, and is treated as one that meant to. The kernel is
    asked directly where it can be (it says so whatever is still unread on the connection); elsewhere one byte is
    looked at."""
    gone = getattr(select, "POLLRDHUP", 0)
    if gone and hasattr(select, "poll"):
        try:
            watch = select.poll()
            watch.register(connection.fileno(), gone | select.POLLHUP | select.POLLERR)
            return any(flags & (gone | select.POLLHUP | select.POLLERR | select.POLLNVAL) for _, flags in watch.poll(0))
        except (OSError, ValueError):
            return True
    try:
        connection.setblocking(False)
        try:
            return connection.recv(1, socket.MSG_PEEK) == b""
        finally:
            connection.setblocking(True)
    except (BlockingIOError, InterruptedError):
        return False  # nothing more to read, and still there
    except OSError:
        return True  # reset


def foreign_caller(handler, port):
    """Whether a call is to be refused as another user's, on a system that names the owner of a connection (Linux).
    A caller still connected has a row, and the row's owner decides. A caller that has closed its end is refused
    whoever it was: its row is nobody's by then, or gone, and a browser never leaves before its answer. With no row
    and the caller still there, it is a relay from outside this system's own network (WSL's, a forwarded port).
    So the check cannot be passed by not being looked at."""
    mine = os.getuid() if hasattr(os, "getuid") else None
    if mine in (None, 0) or not os.path.exists("/proc/net/tcp"):
        return False
    row = peer_row(handler.client_address, port)
    if row is not None:
        uid, connected = row
        return not connected or is_foreign(uid, mine)
    # No row: give a reset on its way the moment to land, then see whether anyone is still there.
    time.sleep(0.02)
    return has_hung_up(handler.connection)


def page_policy(page):
    """The page's content security policy: its own two scripts by their hashes and nothing else that runs, no
    address but this server's to call or load from. A value that slipped through as markup would find no way to act.
    No frame rule: the editor's own browser shows the board in a frame, and a copy framed by another site has no key
    (the browser keeps each site's storage apart), so there is nothing in it to click."""
    hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(script).digest()).decode("ascii") + "'"
                      for script in re.findall(rb"<script>(.*?)</script>", page, re.S))
    return ("default-src 'none'; script-src " + hashes + "; style-src 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'")
# What a prompt to the chat may carry from the record: ids of a fixed shape. A prompt is read as the person's own
# words, and the record is a file a cloned repository brings with it: a title could hold a sentence for the assistant.
LEVEL_ID = re.compile(r"^\d+-\d+[ab]?$")
SLUG_ID = re.compile(r"^[a-z0-9-]{1,60}$")
COMMIT_ID = re.compile(r"^[0-9a-f]{7,64}$")
# Names that look like secrets: a save point never adds one (the hooks hold the same list).
SECRET_LIKE = re.compile(
    r"(^|/)\.env($|[._-])|(^|/)\.envrc$|\.env$"
    r"|\.(pem|key|p12|pfx|jks|keystore|kdbx|ppk|tfvars|tfstate|kubeconfig)$|\.tfstate\.backup$|\.tfvars\.json$"
    r"|(^|/)id_(rsa|dsa|ecdsa|ed25519)[^/]*$"
    r"|(^|/)\.(npmrc|pypirc|netrc|git-credentials|htpasswd|pgpass|dockercfg)$|(^|/)\.docker/config\.json$|(^|/)kubeconfig$"
    r"|(^|/)\.?(credentials?|secrets?)(\.(json|ya?ml|toml|ini|env|txt|xml|properties|cfg|conf|csv))?$"
    r"|(^|/)client[-_]secret[^/]*\.(json|ya?ml|p12|pem|key|txt)$|(^|/)[^/]*service[-_]?account[^/]*\.(json|p12|pem|key)$", re.I)
# What the list above would take but is made to be shared: a sample of an env file, a public key.
SHARED_LIKE = re.compile(r"(^|/)\.env[._-](example|sample|template|dist|defaults?)$|(^|/)(example|sample|template)[^/]*\.env$|\.pub$", re.I)


# A save point that took no new file says so in its commit: a return to it leaves the folder's other files alone.
TRACKED_ONLY = "Siui: tracked files only"


def looks_secret(path):
    """Whether a file's name looks like a secret's: a save point never adds such a file."""
    return bool(SECRET_LIKE.search(path)) and not SHARED_LIKE.search(path)


def card_ref(level, key):
    """A decision named for a prompt, "2-1/timeout"; '' when its level or id is not of the fixed shape."""
    if isinstance(level, str) and isinstance(key, str) and LEVEL_ID.match(level) and SLUG_ID.match(key):
        return f"{level}/{key}"
    return ""


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def open_new(path):
    """Opens a file that must not be there yet, for writing: never an existing one, never through a link."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(path, flags, 0o644), "w", encoding="utf-8")


def write_json(path, data):
    """Writes the file whole: a temp file of its own beside it, then one rename, so a reader never sees half of it."""
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}-{time.time_ns()}.tmp"
    done = False
    try:
        with open(tmp, "x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
        done = True
    finally:
        if not done:
            try:
                os.remove(tmp)
            except OSError:
                pass


PACK_NAME = re.compile(r"^[a-z0-9-]{2,60}$")


def stamp_of(path):
    """A file's change mark for /head: its mtime in ns and its size; 0 when it is not there."""
    try:
        stat = os.stat(path)
    except OSError:
        return "0"
    return f"{stat.st_mtime_ns}.{stat.st_size}"


def touch(path):
    with open(path, "a", encoding="utf-8"):
        pass
    os.utime(path, None)


def find_remote_code():
    """The VS Code CLI of a remote or WSL server on this machine, newest first; None on a plain desktop."""
    home = os.path.expanduser("~")
    found = glob.glob(os.path.join(home, ".vscode-server", "bin", "*", "bin", "remote-cli", "code"))
    return max(found, key=os.path.getmtime) if found else None


def is_network_path(path):
    """Whether a path names another machine or a device: \\\\host\\share, //host/share, \\\\?\\, \\\\.\\. Even asking whether such
    a file exists makes Windows sign in to that machine, so a path from a project's files is never followed there."""
    return str(path).strip().replace("/", "\\").startswith("\\\\")


# What a command line of cmd.exe gives a meaning to. VS Code's `code` on Windows is a batch file, and a batch file's
# arguments pass through cmd.exe whatever the caller quotes: a file named `a&calc.txt` would run calc.
CMD_SPECIAL = set('&|<>^%!"\r\n')


def open_locally(absolute):
    """Opens a file on a plain desktop (native Windows, macOS, Linux) in an editor: `code` on PATH, in the window
    last used. With no editor the file is shown in its folder. It is never handed to the system to "open": that
    would run a script or a program by its file type, and the path comes from the project's own files. Returns
    (an error line or '', how it was opened: "editor" or "folder")."""
    code = shutil.which("code")
    if code:
        if os.name == "nt" and code.lower().endswith((".cmd", ".bat")) and CMD_SPECIAL & set(absolute):
            return "this file's name holds a character the editor's command cannot take safely; open it from the editor", ""
        try:
            if subprocess.run([code, "-r", absolute], capture_output=True, text=True, timeout=20).returncode == 0:
                return "", "editor"
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        if os.name == "nt":
            # Explorer with the file selected: it shows, it does not run.
            subprocess.Popen(["explorer.exe", "/select," + absolute])
            return "", "folder"
        if sys.platform == "darwin":
            if subprocess.run(["open", "-R", absolute], capture_output=True, timeout=20).returncode == 0:
                return "", "folder"
        else:
            opener = shutil.which("xdg-open")
            folder = absolute if os.path.isdir(absolute) else os.path.dirname(absolute)
            if opener and subprocess.run([opener, folder], capture_output=True, timeout=20).returncode == 0:
                return "", "folder"
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error), ""
    return "no editor command found: put VS Code's `code` on the PATH to open files from the board", ""


def live_sockets(preferred):
    """The IPC sockets of the VS Code windows alive now, the preferred one first, newest next.

    The CLI needs one in VSCODE_IPC_HOOK_CLI; the one this server was started with may belong
    to a window since closed, so every candidate is tried for a connection."""
    paths = []
    if os.name == "nt" or not hasattr(socket, "AF_UNIX"):
        return []
    if preferred:
        paths.append(preferred)
    for pattern in ("/mnt/wslg/runtime-dir/vscode-ipc-*.sock", "/run/user/%d/vscode-ipc-*.sock" % os.getuid(),
                    "/tmp/vscode-ipc-*.sock"):
        paths.extend(sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True))
    alive, seen = [], set()
    for path in paths:
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect(path)
            alive.append(path)
        except OSError:
            pass
        finally:
            probe.close()
    return alive


class Board:
    def __init__(self, args, serving=True):
        """`serving` False is the launcher's use: the project's git side only, with no key made (a key belongs to
        the server that is running, and making one here would leave its page without)."""
        self.root = os.path.abspath(args.root)
        self.run = os.path.abspath(args.run)
        self.record = args.record
        # The chat log is one file whose name ends in .jsonl. Its path is kept out of every commit, so a path the
        # configuration could aim at a folder of sources would leave that folder out of every save point.
        self.chat = args.chat if isinstance(args.chat, str) and args.chat.endswith(".jsonl") and ".." not in args.chat else ".claude/chat-log.jsonl"
        self.ipc = args.ipc or ""
        self.started = time.time()
        self.ports = range(args.port, args.port + PORT_SPAN)
        self.lock = threading.Lock()  # held around every read-modify-write of the record and the configuration
        self.last_record = None  # the text of the last record that parsed, for a poll that lands on a half-written file
        self.record_missing_since = None  # when the record file vanished, for the grace that covers a git reset
        self._git_identity = None  # the -c identity options, found once
        os.makedirs(self.run, exist_ok=True)
        self.key = start_key(self.path("key")) if serving else ""
        self.port = args.port  # the port held, set once bound: the launcher's proof names it
        self.spent_pass = None  # the last pass traded for the key: a second try at it means two programs held it

    def proof(self, nonce):
        """An answer only this board can give: the launcher asks with a fresh nonce and checks the answer against the
        key file, so it knows the server on a port is this project's without sending the key to whatever listens
        there. The port is part of it, so another program cannot pass the question on to the real board."""
        return hmac.new(self.key.encode("ascii"), f"{nonce}:{self.port}".encode("ascii"), hashlib.sha256).hexdigest()

    def enter(self, body):
        """Trades a one-time pass for the key. `/siui board` writes the pass into the run folder and opens the page
        with it in the address: it works once, for two minutes. The pass is seen for a moment by whoever can list
        this machine's processes, so a second try at a spent pass is taken as two programs holding it: the key is
        changed, and every page asks to be opened from the chat again."""
        given = str(body.get("pass") or "")
        if not KEY_SHAPE.match(given):
            return {"ok": False, "error": "no pass"}
        with self.lock:
            digest = hashlib.sha256(given.encode("ascii")).hexdigest()
            if self.spent_pass is not None and hmac.compare_digest(digest, self.spent_pass):
                self.key = new_key(self.path("key"))
                self.spent_pass = None
                return {"ok": False, "error": "this pass was used already; the board's key was changed: run /siui board in the chat"}
            made = read_json(self.path("pass"), None)
            wanted = made.get("pass") if isinstance(made, dict) else None
            at = made.get("at") if isinstance(made, dict) else None
            if not isinstance(wanted, str) or not isinstance(at, (int, float)) or not hmac.compare_digest(given.encode("ascii"), wanted.encode("utf-8", "replace")):
                return {"ok": False, "error": "no such pass: run /siui board in the chat"}
            try:
                os.remove(self.path("pass"))
            except OSError:
                pass
            if time.time() - at > PASS_SECONDS:
                return {"ok": False, "error": "this pass is too old: run /siui board in the chat"}
            self.spent_pass = digest
            return {"ok": True, "key": self.key}

    def local_origin(self, origin):
        """Whether an Origin header names this server: http, a local name and a port of its range."""
        match = re.match(r"^http://(127\.0\.0\.1|localhost):(\d+)$", origin.strip().lower())
        return bool(match) and int(match.group(2)) in self.ports

    @staticmethod
    def local_host(host):
        """Whether a Host header is a local name, with any port."""
        name, _, _ = host.strip().lower().partition(":")
        return name in LOCAL_NAMES

    def pack_folders(self):
        """Where packs may be, each with whose it is: the project's skill and its configured folders ("project"), the
        plugin's bundled packs ("plugin"), the home folder's skill ("home"). The third part says whether the place
        is one the plugin knows by itself; a folder the configuration names is not, and its name is the project's
        own text."""
        folders = [
            (os.path.join(self.root, ".claude", "skills", "decision-cards", "packs"), "project", True),
            (os.path.join(HERE, "..", "packs"), "plugin", True),
        ]
        config = read_json(os.path.join(self.root, ".claude", "siui.json"), {})
        # A folder the project's configuration names holds the project's own packs: it lies in the project. Packs
        # shared between projects belong in the home folder's skill.
        given = config.get("packs") if isinstance(config, dict) else None
        for extra in given if isinstance(given, list) else []:
            if isinstance(extra, str) and extra and ".." not in extra and "\0" not in extra and not is_network_path(extra) and not os.path.isabs(extra):
                folders.append((os.path.join(self.root, extra), "project", False))
        home = os.path.expanduser("~")
        if home and home != "~":
            folders.append((os.path.join(home, ".claude", "skills", "decision-cards", "packs"), "home", True))
        seen, out = set(), []
        for folder, source, known in folders:
            # A folder of the project's own packs lies in the project, links followed: the skill's folder as well.
            if source == "project" and not self.inside(folder):
                continue
            real = os.path.realpath(folder)
            if real in seen or not os.path.isdir(real):
                continue
            seen.add(real)
            out.append((real, source, known))
        return out

    UNIVERSE_NAME = re.compile(r"^[a-z0-9-]{1,40}$")

    def universe_folders(self):
        """Where a universe's set file may be: the project's own first, then the plugin's bundled ones."""
        return [(os.path.join(self.root, ".claude", "universes"), "project"), (os.path.join(HERE, "universes"), "plugin")]

    def universes(self):
        """The sets a project may choose: name, title and where it comes from; classic first."""
        out, seen = [], set()
        for folder, source in self.universe_folders():
            if not os.path.isdir(folder):
                continue
            for entry in sorted(os.listdir(folder)):
                if not entry.endswith(".json"):
                    continue
                name = entry[:-5]
                if name in seen or not self.UNIVERSE_NAME.match(name):
                    continue
                data = read_json(os.path.join(folder, entry), None)
                if not isinstance(data, dict):
                    continue
                seen.add(name)
                out.append({"name": name, "title": str(data.get("title") or name), "about": str(data.get("about") or ""), "source": source})
        out.sort(key=lambda one: (one["name"] != "classic", one["title"].lower()))
        return out

    def universe(self, name):
        """One set, the project's copy before the plugin's; None when there is none."""
        if not isinstance(name, str) or not self.UNIVERSE_NAME.match(name):
            return None
        for folder, _ in self.universe_folders():
            data = read_json(os.path.join(folder, name + ".json"), None)
            if isinstance(data, dict):
                data.setdefault("name", name)
                return data
        return None

    def set_universe(self, body):
        """Writes the chosen set into the configuration's theme block, keeping the rest."""
        name = str(body.get("name") or "").strip()
        if self.universe(name) is None:
            return {"ok": False, "error": "no such universe"}
        path = self.config_path()
        if path is None:
            return {"ok": False, "error": "the configuration's file leads out of the project"}
        with self.lock:
            config = read_json(path, {})
            if not isinstance(config, dict):
                config = {}
            theme = config.get("theme") if isinstance(config.get("theme"), dict) else {}
            theme["universe"] = name
            config["theme"] = theme
            try:
                write_json(path, config)
            except OSError as error:
                return {"ok": False, "error": str(error)}
        return {"ok": True, "name": name}

    def hide_pack(self, body):
        """Keeps a pack off the roadmap, or shows it again: `hiddenPacks` in the configuration. /siui on still runs it."""
        name = str(body.get("name") or "").strip()
        if not PACK_NAME.match(name):
            return {"ok": False, "error": "a pack name is required"}
        hide = bool(body.get("hidden", True))
        path = self.config_path()
        if path is None:
            return {"ok": False, "error": "the configuration's file leads out of the project"}
        with self.lock:
            config = read_json(path, {})
            if not isinstance(config, dict):
                config = {}
            given = config.get("hiddenPacks") if isinstance(config.get("hiddenPacks"), list) else []
            names = [one for one in given if isinstance(one, str) and one != name]
            if hide:
                names.append(name)
            if names:
                config["hiddenPacks"] = names
            else:
                config.pop("hiddenPacks", None)
            try:
                write_json(path, config)
            except OSError as error:
                return {"ok": False, "error": str(error)}
        return {"ok": True, "name": name, "hidden": hide}

    def delete_pack(self, body):
        """Deletes a pack file of the project's own; the plugin's and the home folder's packs are not touched."""
        name = str(body.get("name") or "").strip()
        if not PACK_NAME.match(name):
            return {"ok": False, "error": "a pack name is required"}
        pack = next((one for one in self.packs() if one["name"] == name), None)
        if pack is None:
            return {"ok": False, "error": "no such pack"}
        if pack["source"] != "project" or not self.inside(pack["path"]) or os.path.islink(pack["path"]):
            return {"ok": False, "error": "not the project's pack: hide it instead"}
        with self.lock:
            try:
                os.remove(pack["path"])
            except OSError as error:
                return {"ok": False, "error": str(error)}
        return {"ok": True, "name": name, "path": pack["path"]}

    def move(self, body):
        """Moves a mark, or a chat, skipped or side-quest decision, to another world and stage: the step's Move buttons."""
        try:
            world = int(body.get("toWorld"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "a world is required"}
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            runs = record.get("runs", [])
            target = next((r for r in runs if r.get("world") == world), None)
            if target is None:
                return {"ok": False, "error": "no such world"}
            level = str(body.get("toLevel") or "").strip() or f"{world}-1"
            if body.get("kind") == "event":
                for one in record.get("events", []):
                    if one.get("id") == body.get("id"):
                        one["world"], one["level"] = world, level
                        write_json(self.record_path(), record)
                        return {"ok": True}
                return {"ok": False, "error": "no such mark"}
            from_level, decision_id = str(body.get("level") or ""), str(body.get("id") or "")
            for run in runs:
                decisions = run.get("decisions", [])
                for index, one in enumerate(decisions):
                    if one.get("level") == from_level and one.get("id") == decision_id:
                        if one.get("via") not in ("chat", "skipped") and not (run.get("pack") == "side" or run.get("world") == 0):
                            return {"ok": False, "error": "only a chat, skipped or side-quest decision can be moved"}
                        if run is target and from_level == level:
                            return {"ok": True}
                        del decisions[index]
                        one["level"] = level
                        target.setdefault("decisions", []).append(one)
                        if run.get("finishedAt") is None and not any(d.get("level") == from_level for d in decisions):
                            run.get("levels", {}).pop(from_level, None)
                        target.setdefault("levels", {}).setdefault(level, "done" if target.get("finishedAt") else "open")
                        write_json(self.record_path(), record)
                        return {"ok": True}
        return {"ok": False, "error": "no such decision"}

    def queue(self, body):
        """Marks a decision queued (decided, not started) or not: the step's Queue button."""
        level, decision_id = str(body.get("level") or ""), str(body.get("id") or "")
        if not level or not decision_id:
            return {"ok": False, "error": "level and id are required"}
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            for run in record.get("runs", []):
                for one in run.get("decisions", []):
                    if one.get("level") == level and one.get("id") == decision_id:
                        if body.get("queued"):
                            one["queued"] = True
                            one.pop("started", None)
                        else:
                            one.pop("queued", None)
                            one["started"] = True
                        write_json(self.record_path(), record)
                        return {"ok": True, "queued": bool(one.get("queued"))}
        return {"ok": False, "error": "no such decision"}

    EXPORT_EXT = {"html": "html", "md": "md", "svg": "svg"}

    def export(self, body):
        """Writes an export the page built into the project, under .claude/exports/, with a dated name."""
        kind = str(body.get("kind") or "").strip().lower()
        text = body.get("text")
        if kind not in self.EXPORT_EXT or not isinstance(text, str) or not text.strip():
            return {"ok": False, "error": "kind (html, md, svg) and text are required"}
        if len(text) > 20_000_000:
            return {"ok": False, "error": "the export is too big"}
        folder = os.path.join(self.root, ".claude", "exports")
        if not self.inside(folder):
            return {"ok": False, "error": "the exports folder leads out of the project; nothing was written"}
        os.makedirs(folder, exist_ok=True)
        # An export holds the whole record and the chat beside it: it is this machine's file, kept out of git by an
        # ignore file of the folder's own, written once. Deleting that file is how one chooses to commit exports.
        ignore = os.path.join(folder, ".gitignore")
        if not os.path.lexists(ignore):
            try:
                with open_new(ignore) as handle:
                    handle.write("# Siui: exports are files of this machine, not of the repository. Delete this file to commit them.\n*\n")
            except OSError:
                pass
        stamp = time.strftime("%Y-%m-%d-%H%M", time.localtime())
        name = f"roadmap-{stamp}.{self.EXPORT_EXT[kind]}"
        path = os.path.join(folder, name)
        if os.path.islink(path) or not self.inside(path):
            return {"ok": False, "error": "the export's file leads out of the project; nothing was written"}
        try:
            if os.path.lexists(path):
                os.remove(path)
            with open_new(path) as handle:
                handle.write(text)
        except OSError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "path": os.path.relpath(path, self.root)}

    def abandon(self, body):
        """Closes the open world as abandoned: the board's Abandon button. Its answers stay."""
        try:
            world = int(body.get("world"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "a world is required"}
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            closed = False
            for run in record.get("runs", []):
                if run.get("world") == world and run.get("finishedAt") is None and run.get("pack") != "side" and world != 0:
                    today = time.strftime("%Y-%m-%d", time.gmtime())
                    run["finishedAt"] = today
                    run["abandonedAt"] = today
                    write_json(self.record_path(), record)
                    closed = True
                    break
        if not closed:
            return {"ok": False, "error": "no open world of that number"}
        self.prompt({"text": f"On the board I abandoned world {world}: it is closed as abandoned; its answers stay. Clear the status line and do not go on with its cards."})
        return {"ok": True}

    def hidden_packs(self):
        """The packs the configuration keeps off the roadmap: `hiddenPacks` in .claude/siui.json."""
        config = read_json(os.path.join(self.root, ".claude", "siui.json"), {})
        given = config.get("hiddenPacks") if isinstance(config, dict) else None
        return {one for one in given if isinstance(one, str)} if isinstance(given, list) else set()

    def packs(self):
        """Every pack found, with its title, suggested world, plan (levels and cards), whose folder it is in and
        whether the roadmap hides it."""
        heading = re.compile(r"^##\s+Level\s+(\d+-\d+)\s*[·:-]\s*(.+?)(?:\s*\((\d+)\s+cards?\))?\s*$")
        card_row = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|\s*([^|]+?)\s*\|")
        title_line = re.compile(r"^#\s+(?:World\s+(\d+)\s*:\s*)?(.+?)\s*$")
        hidden = self.hidden_packs()
        found, names = [], set()
        for folder, source, known in self.pack_folders():
            for path in sorted(glob.glob(os.path.join(folder, "*.md"))):
                name = os.path.basename(path)[:-3]
                if name == "README" or name in names:
                    continue
                try:
                    with open(path, encoding="utf-8") as handle:
                        lines = handle.read().split("\n")
                except OSError:
                    continue
                pack = {"name": name, "title": name, "world": None, "levels": [], "path": path,
                        "source": source, "hidden": name in hidden,
                        # Whether its place is one the plugin knows by itself: only then may a prompt to the chat name its path.
                        "known": known}
                current = None
                for line in lines:
                    first = title_line.match(line) if pack["title"] == name and line.startswith("# ") else None
                    if first:
                        pack["title"] = first.group(2)
                        pack["world"] = int(first.group(1)) if first.group(1) else None
                        continue
                    head = heading.match(line)
                    if head:
                        current = {"level": head.group(1), "title": head.group(2).strip(), "cards": []}
                        if head.group(3):
                            current["count"] = int(head.group(3))
                        pack["levels"].append(current)
                        continue
                    if line.startswith("## "):
                        current = None
                    row = card_row.match(line) if current else None
                    if row:
                        current["cards"].append({"id": row.group(1), "title": row.group(2).strip()})
                names.add(name)
                found.append(pack)
        return found

    def chat_turns(self, limit=400):
        """The last `limit` turns of the chat log, oldest first."""
        path = os.path.join(self.root, self.chat)
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return []
        turns = []
        for line in lines[-limit:]:
            try:
                one = json.loads(line)
            except ValueError:
                continue
            if isinstance(one, dict):
                turns.append(one)
        return turns

    def path(self, name):
        return os.path.join(self.run, name)

    def inside(self, path):
        """Whether a path, every link on the way followed, still lies in the project. A cloned repository can ship a
        folder that is a link to anywhere: nothing is written or removed through one."""
        root = os.path.realpath(self.root)
        real = os.path.realpath(path)
        return real == root or real.startswith(root + os.sep)

    def record_path(self):
        """The record's file. One that leads out of the project is not read or written: the board shows no record
        then, and what it would have written goes to a file of the run folder that nothing reads."""
        path = os.path.join(self.root, self.record)
        return path if self.inside(path) else self.path("record-outside-the-project.json")

    def config_path(self):
        """The configuration's file for a write; None when it leads out of the project."""
        path = os.path.join(self.root, ".claude", "siui.json")
        return path if self.inside(path) else None

    RECORD_GRACE = 2.0  # seconds a vanished record is still shown: the time git takes to reset the tree

    def record_gone(self):
        """Whether the record file is missing for longer than the grace: deleted, not just being replaced. Keeps the
        time it vanished; past the grace the last copy is dropped, so a record written later starts from the file."""
        if os.path.exists(self.record_path()):
            self.record_missing_since = None
            return False
        now = time.monotonic()
        if self.record_missing_since is None:
            self.record_missing_since = now
        if now - self.record_missing_since < self.RECORD_GRACE:
            return False
        self.last_record = None
        return True

    def read_record(self, default=None, fresh=False):
        """The record; when the file is unreadable or not JSON (half-written, or gone for a moment while git resets
        the tree), the last one that parsed, so one poll does not blank the page. The default only before any did,
        and once the file has been gone past the grace: a deleted record is an empty board, not the last one shown.
        An edit asks for a fresh one: None then, so a stale copy is never written over the file."""
        try:
            with open(self.record_path(), encoding="utf-8") as handle:
                text = handle.read()
            record = json.loads(text)
        except (OSError, ValueError):
            if fresh:
                return None
            if self.record_gone():
                return default
            return json.loads(self.last_record) if self.last_record is not None else default
        self.record_missing_since = None
        if isinstance(record, dict):
            self.last_record = text
        return record

    def touch_alive(self):
        """Marks the page alive for wait.py: the mark's mtime is enough, so it is touched at most once a second."""
        alive = self.path("alive")
        try:
            if time.time() - os.path.getmtime(alive) > 1:
                touch(alive)
        except OSError:
            touch(alive)

    def session_alive(self):
        """Whether the plugin's heartbeat is fresh: less than 90 seconds old."""
        try:
            return time.time() - os.path.getmtime(self.path("heartbeat")) < 90
        except OSError:
            return False

    def head(self):
        """A stamp that moves whenever /state would: the change marks of everything it reads and whether the session is
        alive. Stat calls only, no parsing: the page polls this and fetches /state when the stamp moves."""
        self.touch_alive()
        paths = [self.record_path(), self.path("card.json"), self.path("auto.json"),
                 self.path("chat-first.json"), os.path.join(self.root, self.chat),
                 os.path.join(self.root, ".claude", "siui.json")]
        for folder, _ in self.universe_folders():
            paths.append(folder)
            if os.path.isdir(folder):
                paths.extend(os.path.join(folder, name) for name in sorted(os.listdir(folder)) if name.endswith(".json"))
        parts = [stamp_of(path) for path in paths] + ["1" if self.session_alive() else "0"]
        # A record that vanished moves the stamp once more when its grace runs out, so the page fetches the empty board.
        if not os.path.exists(self.record_path()):
            parts.append("gone" if self.record_gone() else "grace")
        status = read_json(self.path("status.json"), None)
        return {"v": hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()[:16],
                "status": status if isinstance(status, dict) else None, "alive": self.session_alive()}

    def resolve(self, given):
        """The absolute path of a source as the record spells it: project-relative, ~/... or absolute."""
        if given.startswith("~"):
            given = os.path.expanduser(given)
        return os.path.realpath(given if os.path.isabs(given) else os.path.join(self.root, given))

    @staticmethod
    def source_paths(record):
        """Every path the record's decisions name as a source, as spelled there."""
        paths = set()
        runs = record.get("runs") if isinstance(record, dict) else None
        for run in runs if isinstance(runs, list) else []:
            decisions = run.get("decisions") if isinstance(run, dict) else None
            for one in decisions if isinstance(decisions, list) else []:
                sources = one.get("sources") if isinstance(one, dict) else None
                for source in sources if isinstance(sources, list) else []:
                    path = source.get("path") if isinstance(source, dict) else None
                    if isinstance(path, str) and path.strip() and "\0" not in path:
                        paths.add(path.strip())
        return paths

    def files_of(self, record):
        """What is on disk for every file the record's decisions name: exists, size, last change."""
        files = {}
        for path in self.source_paths(record):
            if is_network_path(path):
                files[path] = {"exists": False}
                continue
            try:
                stat = os.stat(self.resolve(path))
                files[path] = {"exists": True, "size": stat.st_size, "mtime": stat.st_mtime, "isDir": os.path.isdir(self.resolve(path))}
            except (OSError, ValueError):
                files[path] = {"exists": False}
        return files

    def state(self):
        self.touch_alive()
        card = read_json(self.path("card.json"), None)
        record = self.read_record({"format": 1, "runs": []})
        status = read_json(self.path("status.json"), None)
        config = read_json(os.path.join(self.root, ".claude", "siui.json"), {})
        name = config.get("name") if isinstance(config, dict) else None
        return {
            "root": self.root,
            # The project's name in the header: `name` in the configuration, else the folder's.
            "project": name.strip() if isinstance(name, str) and name.strip() else (os.path.basename(self.root.rstrip("/\\")) or self.root),
            "record": record,
            "status": status if isinstance(status, dict) else None,
            "auto": bool((read_json(self.path("auto.json"), {}) or {}).get("on")),
            "chatFirst": bool((read_json(self.path("chat-first.json"), {}) or {}).get("on")),
            "sessionAlive": self.session_alive(),
            "files": self.files_of(record) if isinstance(record, dict) else {},
            "card": card if isinstance(card, dict) and card.get("id") else None,
            "chat": self.chat_turns(),
            "packs": self.packs(),
            "universes": self.universes(),
            "config": config if isinstance(config, dict) else {},
            "git": self.has_git(),
            "now": time.time(),
        }

    def answer(self, body):
        """The page's answer to the live card; with `dismiss`, the card is skipped instead."""
        card_id = str(body.get("id") or "").strip()
        answer = str(body.get("answer") or "").strip()
        dismiss = bool(body.get("dismiss"))
        if not card_id or (not answer and not dismiss):
            return {"ok": False, "error": "id and answer are required"}
        write_json(self.path("inbox-answer.json"), {"id": card_id, "answer": answer, "dismiss": dismiss, "at": time.time()})
        return {"ok": True}

    def forget(self, body):
        """Drops a skipped card from the record: the step's Delete button. Only a skipped one, never an answer."""
        level = str(body.get("level") or "").strip()
        decision_id = str(body.get("id") or "").strip()
        if not level or not decision_id:
            return {"ok": False, "error": "level and id are required"}
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            for run in record.get("runs", []):
                decisions = run.get("decisions", [])
                for index, one in enumerate(decisions):
                    if one.get("level") == level and one.get("id") == decision_id:
                        if one.get("via") != "skipped":
                            return {"ok": False, "error": "only a skipped card can be deleted"}
                        del decisions[index]
                        if not any(d.get("level") == level for d in decisions) and run.get("finishedAt") is None:
                            run.get("levels", {}).pop(level, None)
                        write_json(self.record_path(), record)
                        return {"ok": True}
        return {"ok": False, "error": "no such card"}

    def note(self, body):
        """Saves a note on a decision; with `notify`, also sends it to the chat as the person's words."""
        level = str(body.get("level") or "")
        decision_id = str(body.get("id") or "")
        note = str(body.get("note") or "").strip()
        notify = bool(body.get("notify"))
        if not note:
            return {"ok": False, "error": "the note is empty"}
        title = None
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            for run in record.get("runs", []):
                for one in run.get("decisions", []):
                    if one.get("level") == level and one.get("id") == decision_id:
                        notes = one.get("notes")
                        if not isinstance(notes, list):
                            # a note saved before notes were a list becomes the first entry
                            notes = [{"at": one.get("at", ""), "text": one["note"]}] if one.get("note") else []
                        notes.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "text": note})
                        one["notes"] = notes
                        one["note"] = note
                        write_json(self.record_path(), record)
                        title = str(one.get("title", ""))
                        break
                if title is not None:
                    break
        if title is None:
            return {"ok": False, "error": "no such decision"}
        if notify:
            # The note is the person's own words; the decision is named by its id, its title stays in the record.
            where = card_ref(level, decision_id) or "a decision in the record"
            self.prompt({"text": f"On the board, my note on {where}: {note}"})
        return {"ok": True, "notified": notify}

    def event(self, body):
        """Adds something to the map, or marks it done: the page's form and its Done buttons."""
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            made = self.put_event(record, body)
            if made.get("ok"):
                write_json(self.record_path(), record)
        return made

    @staticmethod
    def put_event(record, body):
        """Adds a mark to the record given, or updates one, and answers as /event does; writes nothing. Called with the
        lock held, by event and by checkpoint, which adds its commit before the one write."""
        events = record.get("events")
        if not isinstance(events, list):
            events = []
            record["events"] = events
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        event_id = str(body.get("id") or "").strip()
        if event_id:
            for one in events:
                if one.get("id") == event_id:
                    if body.get("status") in ("open", "done"):
                        one["status"] = body["status"]
                        if body["status"] == "done":
                            one["doneAt"] = now
                        else:
                            one.pop("doneAt", None)
                    for key in ("title", "text"):
                        if isinstance(body.get(key), str) and body[key].strip():
                            one[key] = body[key].strip()[:240]
                    return {"ok": True, "id": event_id}
            return {"ok": False, "error": "no such event"}
        aliases = {"bug": "enemy", "risk": "enemy", "feature": "powerup", "requirement": "powerup", "problem": "challenge",
                   "coin": "check", "jump": "pipe", "save": "checkpoint"}
        kind = str(body.get("kind") or "").strip().lower()
        kind = aliases.get(kind, kind)
        title = str(body.get("title") or "").strip()[:60]
        if kind not in ("enemy", "powerup", "challenge", "check", "pipe", "checkpoint") or not title:
            return {"ok": False, "error": "kind and title are required"}
        try:
            world = int(body.get("world"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "world is required"}
        level = str(body.get("level") or "").strip() or f"{world}-1"
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30] or "event"
        one = {"id": f"{kind}-{slug}-{now[11:19].replace(':', '')}", "kind": kind, "title": title,
               "world": world, "level": level, "at": now, "status": "open"}
        text = str(body.get("text") or "").strip()[:240]
        if text:
            one["text"] = text
        try:
            size = int(body.get("size"))
            if 1 <= size <= 5:
                one["size"] = size
        except (TypeError, ValueError):
            pass
        to = body.get("to")
        if isinstance(to, dict):
            try:
                target = {"world": int(to.get("world"))}
                if isinstance(to.get("level"), str) and to["level"].strip():
                    target["level"] = to["level"].strip()
                one["to"] = target
            except (TypeError, ValueError):
                pass
        events.append(one)
        return {"ok": True, "id": one["id"]}

    def git_options(self):
        """Git's -c settings for every call: no signing; an identity only when the person has none (`git config
        user.name` empty), found once."""
        if self._git_identity is None:
            try:
                ran = subprocess.run(["git", "config", "user.name"], cwd=self.root, capture_output=True, text=True, timeout=15)
                named = ran.returncode == 0 and bool(ran.stdout.strip())
            except (OSError, subprocess.TimeoutExpired):
                named = False
            self._git_identity = [] if named else ["-c", "user.name=siui", "-c", "user.email=siui@local"]
        return [*self._git_identity, "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]

    _has_git = None

    def has_git(self):
        """Whether git runs here and the project is a repository; checked once."""
        if self._has_git is None:
            code, out, _ = self.git("rev-parse", "--is-inside-work-tree", timeout=10)
            self._has_git = code == 0 and out.strip() == "true"
        return self._has_git

    def git(self, *args, timeout=60, cwd=None, index=None, given=None, raw=False):
        """Runs git in the project. `index` names a scratch index to work on in place of the person's own; `given`
        is the command's input; `raw` keeps the output exactly as it is. A file's name need not be UTF-8: its bytes
        pass through unchanged, in and out."""
        try:
            # In English, whatever the person's language: what git says is read here ("nothing to commit").
            env = dict(os.environ, LANGUAGE="en", LC_MESSAGES="C")
            if index:
                env["GIT_INDEX_FILE"] = index
            out = subprocess.run(["git", *self.git_options(), *args], cwd=cwd or self.root, capture_output=True, timeout=timeout,
                                 env=env, input=given, encoding="utf-8", errors="surrogateescape")
        except (OSError, subprocess.TimeoutExpired) as error:
            return 1, "", str(error)
        return out.returncode, out.stdout if raw else out.stdout.strip(), out.stderr.strip()

    def names(self, *args, cwd=None, index=None):
        """The names a git command lists with -z, each exactly as it is (a name may begin or end with a space):
        (the exit code, the names, the error text)."""
        code, out, err = self.git(*args, cwd=cwd, index=index, raw=True)
        return code, [one for one in out.split("\0") if one], err

    def new_files(self, cwd=None):
        """The files a save point would add: not tracked, not ignored, under the project's folder (or `cwd`). A
        name ending in a slash is a repository of its own inside the folder, which git lists as one thing."""
        code, found, _ = self.names("ls-files", "--others", "--exclude-standard", "-z", "--", ".", cwd=cwd)
        return found if code == 0 else []

    def chat_files(self):
        """The chat log and its dated archives, as they are on disk: this machine's files, never a commit's."""
        log = os.path.join(self.root, self.chat)
        return [one for one in [log, *sorted(glob.glob(glob.escape(log[:-6]) + "-*.jsonl"))] if os.path.isfile(one)]

    def keep_out(self, cwd):
        """The pathspecs that keep the chat log and its archives out of a commit, whether git tracks them or not: the
        log holds the person's prompts, and a repository can ship one already tracked."""
        full = os.path.join(self.root, self.chat)
        if os.path.isdir(full) or not self.inside(full):
            return []
        # Both ends with their links followed: git names the top that way, and the project may be opened through one.
        log = os.path.relpath(os.path.realpath(full), os.path.realpath(cwd)).replace(os.sep, "/")
        # git refuses an add that names something it ignores, even to leave it out: the log by its path, and the
        # archives' pattern when their whole folder is ignored (any name in it then is, a made-up one too). What git
        # ignores it cannot take, so each is named only while git could take it.
        specs = []
        if self.git("check-ignore", "-q", "--", log, cwd=cwd)[0] != 0:
            specs.append(f":(exclude,literal){log}")
        folder = os.path.dirname(log)
        if self.git("check-ignore", "-q", "--", (folder + "/" if folder else "") + ".siui-no-such-file", cwd=cwd)[0] != 0:
            specs.append(":(exclude,glob)" + re.sub(r"([*?\[\]\\])", r"\\\1", log[:-6]) + "-*.jsonl")
        return specs

    def git_busy(self):
        """What git is in the middle of, which a commit now would end wrongly; '' when nothing."""
        code, folder, _ = self.git("rev-parse", "--absolute-git-dir")
        if code != 0 or not folder:
            return ""
        for name, what in (("MERGE_HEAD", "a merge"), ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase"),
                           ("CHERRY_PICK_HEAD", "a cherry-pick"), ("REVERT_HEAD", "a revert"), ("BISECT_LOG", "a bisect")):
            if os.path.exists(os.path.join(folder, name)):
                return what
        return ""

    def save_mode(self):
        """How save points treat new files, as the person chose once ("all" or "tracked"); None when not chosen.
        Kept in the run folder, theirs alone and outside the project, where the plugin reads and writes it too."""
        made = read_json(self.path("save-points.json"), None)
        mode = made.get("mode") if isinstance(made, dict) else None
        return mode if mode in ("all", "tracked") else None

    def scratch_index(self, start=None):
        """An index of this route's own, in the run folder: the person's index, and with it what VS Code lists as
        staged, is never touched. With `start`, a commit, it begins as that commit's files; else empty."""
        path = self.path(f"index-{os.getpid()}-{threading.get_ident()}-{time.time_ns()}")
        if start:
            self.git("read-tree", start, index=path)
        return path

    def staged_away(self, own):
        """What the person took out of the index in this folder since the branch's commit (git rm, the old name of
        a git mv): gone from the folder as they see it, though the branch still has it."""
        if not self.branch_commit():
            return []
        # A move counts as its old name gone and its new one come: git is asked not to pair them up.
        code, gone, _ = self.names("diff", "--cached", "--no-renames", "--name-only", "--diff-filter=D", "-z", "--", ".")
        return [one for one in gone if not own(one)] if code == 0 else []

    def folder_index(self, top, leave=()):
        """A scratch index holding the project's folder as it is on disk, for the files git tracks there, and the
        rest of the repository as the branch has it: what is staged or changed in the folders beside the project
        is not this project's to take. A file the person has staged counts as tracked, and one they took out of
        the index is gone. A file a sparse checkout leaves off the disk stays as the branch has it; so does the
        chat log when git tracks it, and every path in `leave`. Returns (the index's path, an error line or '')."""
        index = self.scratch_index(self.branch_commit() or None)
        try:
            kept_apart = {os.path.realpath(one) for one in self.chat_files()} | set(leave)

            def own(one):
                return os.path.realpath(os.path.join(top, one)) in kept_apart

            # Each name of the person's index with its mark: S is a file left off the disk on purpose.
            code, marked, err = self.names("ls-files", "-t", "-z", "--full-name", "--", ".")
            if code != 0:
                return index, err.split("\n")[0] or "git could not list the folder's files"
            paths = list(dict.fromkeys(one[2:] for one in marked if len(one) > 2 and not one.startswith("S ") and not own(one[2:])))
            sparse = list(dict.fromkeys(one[2:] for one in marked if one.startswith("S ")))
            if sparse:
                # Marked here as they are in the person's index, so that nothing done to this index next takes their
                # absence from the disk for a deletion.
                self.git("update-index", "-z", "--skip-worktree", "--stdin", index=index, cwd=top, given="\0".join(sparse) + "\0")
            gone = self.staged_away(own)
            if gone:
                self.git("update-index", "-z", "--force-remove", "--stdin", index=index, cwd=top, given="\0".join(gone) + "\0")
            if paths:
                code, out, err = self.git("update-index", "-z", "--add", "--remove", "--stdin", index=index, cwd=top, given="\0".join(paths) + "\0")
                if code != 0:
                    return index, (err or out).split("\n")[0] or "git could not read the folder's files"
            return index, ""
        except Exception:
            self.drop_index(index)
            raise

    def staged_tree(self, top, head, leave=()):
        """The files of the branch's commit with this folder as the person has staged it: the second commit of a
        stash entry, from which `git stash apply --index` brings the staging back. '' when it cannot be made."""
        index = self.scratch_index(head)
        try:
            kept_apart = {os.path.realpath(one) for one in self.chat_files()} | set(leave)

            def own(one):
                return os.path.realpath(os.path.join(top, one)) in kept_apart

            gone = self.staged_away(own)
            if gone:
                self.git("update-index", "-z", "--force-remove", "--stdin", index=index, cwd=top, given="\0".join(gone) + "\0")
            # "<mode> <object> <stage>\t<name>": the settled entries only; one a merge left open has no single content.
            code, entries, _ = self.names("ls-files", "-s", "-z", "--full-name", "--", ".")
            settled = [one for one in entries if "\t" in one and one.split("\t", 1)[0].split(" ")[-1] == "0" and not own(one.split("\t", 1)[1])]
            if code == 0 and settled:
                self.git("update-index", "-z", "--index-info", index=index, cwd=top, given="\0".join(settled) + "\0")
            code, tree, _ = self.git("write-tree", index=index)
            return tree if code == 0 and COMMIT_ID.match(tree) else ""
        finally:
            self.drop_index(index)

    def top(self):
        """The repository's top folder; the project's own when git does not say."""
        code, top, _ = self.git("rev-parse", "--show-toplevel")
        return top if code == 0 and top else self.root

    @staticmethod
    def drop_index(path):
        for one in (path, path + ".lock"):
            try:
                os.remove(one)
            except OSError:
                pass

    def branch_commit(self):
        """The commit the branch is at; '' in a repository with no commit yet."""
        code, sha, _ = self.git("rev-parse", "--verify", "-q", "HEAD^{commit}")
        return sha if code == 0 and COMMIT_ID.match(sha) else ""

    def snapshot(self, message, mode, also=()):
        """A save point aside from the branch: a commit of the project's folder as it is on disk, kept under a ref
        of Siui's own (refs/siui/save-points/), built through a scratch index. The branch does not move, nothing is
        staged or unstaged, and VS Code's list of changes stays as it is. What it takes is what a commit of the
        folder would: the files git tracks, and with "all" the new ones too, except any whose name looks like a
        secret and any repository of its own inside the folder; never the chat log. `also` names files, from the
        repository's top, to take whatever the mode. Returns (an error line or '', the commit, the secret-looking
        files left out)."""
        busy = self.git_busy()
        if busy:
            return f"git is in the middle of {busy}; finish it first", "", []
        top = self.top()
        index = ""
        try:
            index, error = self.folder_index(top)
            if error:
                return error, "", []
            left_out, took_new = [], False
            if mode == "all":
                fresh = self.new_files()
                left_out = [one for one in fresh if looks_secret(one)]
                apart = left_out + [one.rstrip("/") for one in fresh if one.endswith("/")]
                # Past forty such files they are no longer a few keys to step around: only tracked files are taken.
                if len(left_out) <= 40:
                    code, out, err = self.git("add", "-A", "--", ".", *self.keep_out(self.root), *[f":(exclude,literal){one}" for one in apart], index=index)
                    if code != 0 and not re.search(r"nothing to commit|nothing added|no changes added|did not match any file", out + err, re.I):
                        return (err or out).split("\n")[0] or "git add failed", "", []
                    took_new = True
            if also:
                code, out, err = self.git("update-index", "-z", "--add", "--stdin", index=index, cwd=top, given="\0".join(also) + "\0")
                if code != 0:
                    return (err or out).split("\n")[0] or "git could not take the new files", "", []
            code, tree, err = self.git("write-tree", index=index)
            if code != 0 or not COMMIT_ID.match(tree):
                return (err or tree).split("\n")[0] or "git could not write the save point", "", []
            head = self.branch_commit()
            said = ["-m", message] + ([] if took_new else ["-m", TRACKED_ONLY])
            code, sha, err = self.git("commit-tree", tree, *(["-p", head] if head else []), *said)
            if code != 0 or not COMMIT_ID.match(sha):
                return (err or sha).split("\n")[0] or "git could not make the save point", "", []
            code, _, err = self.git("update-ref", f"refs/siui/save-points/{sha}", sha)
            if code != 0:
                return err.split("\n")[0] or "git could not keep the save point", "", []
            return "", sha, left_out
        finally:
            if index:
                self.drop_index(index)

    def stash_before(self, title, fresh, top):
        """Keeps what a return is about to change or remove as a git stash entry, built by hand so that nothing on
        disk moves yet: the tracked files of this folder as they are, what is staged there, and the new files the
        return will take away or write over (`fresh`, paths from the repository's top). It shows in `git stash
        list` and under Stashes in VS Code, and "apply" brings it back. It holds this folder alone: what is staged
        or changed beside the project is not in it. Returns (an error line or '', how it is kept, in words; '' when
        the folder held nothing to keep)."""
        head = self.branch_commit()
        if not head:
            # No commit yet, so git has nothing to hang a stash on: a save point of Siui's own keeps it, the new
            # files named one by one so that none is left to the rule about many secret-looking files.
            error, sha, _ = self.snapshot(f"Before returning to {title}", "tracked", also=fresh)
            return error, ("" if error else f"the save point {sha[:7]}")
        _, branch, _ = self.git("rev-parse", "--abbrev-ref", "HEAD")
        branch = branch if branch and branch != "HEAD" else "(no branch)"
        subject = f"Siui: before returning to {title}"
        # The record is the present's and is put back after every return: kept out, so the entry can be applied
        # later over a record that has moved on.
        leave = {os.path.realpath(self.record_path())}
        index = ""
        try:
            index, error = self.folder_index(top, leave=leave)
            if error:
                return error, ""
            code, worked, err = self.git("write-tree", index=index)
            if code != 0 or not COMMIT_ID.match(worked):
                return (err or worked).split("\n")[0] or "git could not keep the folder's files", ""
        finally:
            if index:
                self.drop_index(index)
        _, head_tree, _ = self.git("rev-parse", f"{head}^{{tree}}")
        staged = self.staged_tree(top, head, leave) or head_tree
        if worked == head_tree and staged == head_tree and not fresh:
            return "", ""
        parents = ["-p", head]
        code, staged_commit, err = self.git("commit-tree", staged, "-p", head, "-m", f"index on {branch}: {subject}")
        if code != 0 or not COMMIT_ID.match(staged_commit):
            return err.split("\n")[0] or "git could not keep the index", ""
        parents += ["-p", staged_commit]
        if fresh:
            index = self.scratch_index()
            try:
                code, out, err = self.git("update-index", "-z", "--add", "--stdin", index=index, cwd=top, given="\0".join(fresh) + "\0")
                if code != 0:
                    return (err or out).split("\n")[0] or "git could not keep the new files", ""
                code, new_tree, err = self.git("write-tree", index=index)
            finally:
                self.drop_index(index)
            code_made, new_commit, err_made = self.git("commit-tree", new_tree, "-m", f"untracked files on {branch}: {subject}") if code == 0 else (1, "", err)
            if code_made != 0 or not COMMIT_ID.match(new_commit):
                return (err_made or err).split("\n")[0] or "git could not keep the new files", ""
            parents += ["-p", new_commit]
        code, kept, err = self.git("commit-tree", worked, *parents, "-m", f"On {branch}: {subject}")
        if code != 0 or not COMMIT_ID.match(kept):
            return err.split("\n")[0] or "git could not keep the state before", ""
        code, _, err = self.git("stash", "store", "-m", f"On {branch}: {subject}", kept)
        if code != 0:
            return err.split("\n")[0] or "git could not store the stash entry", ""
        return "", f'the git stash entry "{subject}"'

    def commit_folder(self, message, mode):
        """Commits the project's folder to the branch, as the end of a world does (the launcher's `save … commit`):
        the files git tracks, and with "all" the new ones too, except any whose name looks like a secret; never the
        chat log. The commit is of this folder alone: in a larger repository the other folders, and what is staged
        there, stay as they are. Refused in the middle of a merge or a rebase, which such a commit would conclude.
        Returns (an error line or '', the secret-looking files left out)."""
        busy = self.git_busy()
        if busy:
            return f"git is in the middle of {busy}; finish it first", []
        cwd = self.root
        aside = self.keep_out(cwd)
        # A folder with nothing git tracks has nothing for these to match: that is no error.
        nothing = r"nothing to commit|nothing added|no changes added|did not match any file"
        left_out, add, took_new = [], ["add", "-u", "--", ".", *aside], False
        if mode == "all":
            fresh = self.new_files(cwd)
            left_out = [one for one in fresh if looks_secret(one)]
            apart = left_out + [one.rstrip("/") for one in fresh if one.endswith("/")]
            # Past forty such files they are no longer a few keys to step around: only tracked files are taken.
            if len(left_out) <= 40:
                add, took_new = ["add", "-A", "--", ".", *aside, *[f":(exclude,literal){one}" for one in apart]], True
        code, out, err = self.git(*add, cwd=cwd)
        if code != 0 and not re.search(nothing, out + err, re.I):
            return (err or out).split("\n")[0] or "git add failed", []
        said = ["-m", message] + ([] if took_new else ["-m", TRACKED_ONLY])
        code, out, err = self.git("commit", "-q", *said, "--", ".", *aside, cwd=cwd)
        if code != 0 and not re.search(nothing, out + err, re.I):
            return (err or out).split("\n")[0] or "the commit failed", []
        return "", left_out

    def checkpoint(self, body):
        """Takes a save point of the project's folder, aside from the branch, and records it on the stage. New files
        are taken only when the person agreed: while they have not chosen and there are some, the answer names them
        and asks."""
        title = str(body.get("title") or "").strip()[:60] or "Checkpoint"
        code, _, _ = self.git("rev-parse", "--is-inside-work-tree")
        if code != 0:
            return {"ok": False, "error": "not a git repository"}
        if body.get("newFiles") in ("all", "tracked"):
            write_json(self.path("save-points.json"), {"mode": body["newFiles"], "at": time.time()})
        mode = self.save_mode()
        if mode is None:
            fresh = [one for one in self.new_files() if not looks_secret(one)]
            if fresh:
                return {"ok": False, "ask": "newFiles", "files": fresh[:6], "count": len(fresh), "error": "choose how save points treat new files"}
            mode = "all"
        with self.lock:
            error, sha, left_out = self.snapshot(f"Save point: {title}", mode)
            if error:
                return {"ok": False, "error": error}
            _, branch, _ = self.git("rev-parse", "--abbrev-ref", "HEAD")
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            made = self.put_event(record, {"kind": "checkpoint", "title": title, "world": body.get("world"),
                                           "level": body.get("level"), "text": body.get("text") or ""})
            if not made.get("ok"):
                return made
            for one in record.get("events", []):
                if one.get("id") == made["id"]:
                    one["commit"] = sha
                    one["branch"] = branch or "HEAD"
            write_json(self.record_path(), record)
        return {"ok": True, "id": made["id"], "commit": sha, "leftOut": left_out[:6]}

    def revert(self, body):
        """Returns the project's files to a save point. The branch stays where it is: the files of this folder become
        what they were, files made since are taken away, and whatever then differs from the branch shows as a
        change. What the return changes or removes is kept first, as a git stash entry, so nothing is lost. A file
        git would not keep (an ignored one, one whose name looks like a secret) is never touched; when the save
        point holds something at such a file's path, the return waits until the file is moved away."""
        event_id = str(body.get("id") or "").strip()
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            target = next((one for one in record.get("events", []) if isinstance(one, dict) and one.get("id") == event_id and one.get("kind") == "checkpoint"), None)
            if not target or not target.get("commit"):
                return {"ok": False, "error": "no such checkpoint"}
            # The commit is read from the record: nothing but a commit id goes to git or into a prompt.
            if not isinstance(target["commit"], str) or not COMMIT_ID.match(target["commit"]):
                return {"ok": False, "error": "this save point's commit is not a commit id"}
            target = dict(target, title=" ".join(str(target.get("title") or "a save point").split())[:60],
                          world=target.get("world") if isinstance(target.get("world"), int) else 0, level=str(target.get("level") or ""))
            code, _, _ = self.git("cat-file", "-e", f"{target['commit']}^{{commit}}")
            if code != 0:
                return {"ok": False, "error": f"commit {target['commit'][:7]} is not in this repository"}
            busy = self.git_busy()
            if busy:
                return {"ok": False, "error": f"git is in the middle of {busy}; finish it first"}
            # The chat log and its archives are this machine's: read now, written back after.
            chat_kept = {}
            for one in self.chat_files():
                try:
                    with open(one, encoding="utf-8") as handle:
                        chat_kept[one] = handle.read()
                except (OSError, ValueError):
                    pass
            code, top, _ = self.git("rev-parse", "--show-toplevel")
            top = top if code == 0 and top else self.root
            # A save point that took no new file (the person chose tracked files only) knows nothing of the folder's
            # other files: a return to it leaves them where they are.
            _, said, _ = self.git("log", "-1", "--format=%B", target["commit"])
            took_new = TRACKED_ONLY not in said
            # Every path below is from the repository's top; only this folder's are looked at.
            code, held, _ = self.names("ls-tree", "-r", "--name-only", "-z", "--full-tree", target["commit"])
            code_tracked, marked, _ = self.names("ls-files", "-t", "-z", "--full-name", "--", ".")
            code_fresh, fresh, _ = self.names("ls-files", "--others", "--exclude-standard", "-z", "--full-name", "--", ".")
            if code != 0 or code_tracked != 0 or code_fresh != 0:
                return {"ok": False, "error": "git could not list the files; nothing was changed"}
            own = {os.path.realpath(self.record_path()), *[os.path.realpath(one) for one in chat_kept]}
            folder = os.path.relpath(os.path.realpath(self.root), os.path.realpath(top)).replace(os.sep, "/")
            under = "" if folder == "." else folder + "/"
            held = [one for one in held if one.startswith(under)]
            wanted = set(held)
            tracked = {one[2:] for one in marked if len(one) > 2}
            # A file a sparse checkout leaves off the disk is neither written nor taken away.
            sparse = {one[2:] for one in marked if one.startswith("S ")}
            # New files the stash entry can take: not ignored, not secret-looking, not the chat log or the record, not
            # a repository of its own. All of them when the save point took new files; else only those it holds a
            # file for, which the return writes over. The others stay where they are.
            fresh = [one for one in fresh if not one.endswith("/") and not looks_secret(one) and os.path.realpath(os.path.join(top, one)) not in own]
            stashed = fresh if took_new else [one for one in fresh if one in wanted]
            kept_paths = tracked | set(stashed)
            at_risk, seen = [], {}

            def in_the_way(path):
                """A file or a link on disk at this path, which the stash entry will not keep."""
                if path not in seen:
                    full = os.path.join(top, path)
                    seen[path] = (path not in kept_paths and os.path.lexists(full) and (os.path.islink(full) or not os.path.isdir(full))
                                  and os.path.realpath(full) not in own)
                return seen[path]

            def loose_in(path):
                """A file in the folder at this path that the stash entry will not keep; '' when there is none.
                Writing a file where a folder is takes the whole folder away, whatever git knows of it."""
                for here, folders, files in os.walk(os.path.join(top, path)):
                    for name in files + [one for one in folders if os.path.islink(os.path.join(here, one))]:
                        inside = os.path.relpath(os.path.join(here, name), top).replace(os.sep, "/")
                        if inside not in kept_paths and os.path.realpath(os.path.join(here, name)) not in own:
                            return inside
                return ""

            for one in held:
                if one in sparse:
                    continue
                parts = one.split("/")
                full = os.path.join(top, one)
                if in_the_way(one):
                    at_risk.append(one)
                elif os.path.isdir(full) and not os.path.islink(full):
                    # A folder where the save point has a file: fine only when everything in it is kept.
                    loose = loose_in(one)
                    if loose:
                        at_risk.append(loose)
                else:
                    # A file where the save point has a folder.
                    blocked = next(("/".join(parts[:i]) for i in range(1, len(parts)) if in_the_way("/".join(parts[:i]))), None)
                    if blocked:
                        at_risk.append(blocked)
            at_risk = sorted(set(at_risk))
            if at_risk:
                names = ", ".join(at_risk[:3]) + (" and more" if len(at_risk) > 3 else "")
                return {"ok": False, "error": f"the save point would write over files git does not hold now ({names}); move them away first"}
            error, kept = self.stash_before(target["title"], stashed, top)
            if error:
                return {"ok": False, "error": error}
            # Files made since the save point leave the folder; each is in the stash entry, or as the branch has it.
            for one in sorted(kept_paths - wanted, key=len, reverse=True):
                full = os.path.join(top, one)
                if one in sparse or not os.path.lexists(full) or os.path.realpath(full) in own:
                    continue
                try:
                    os.remove(full)
                except OSError:
                    continue
                parent = os.path.dirname(full)
                while parent.startswith(os.path.realpath(self.root) + os.sep) or parent.startswith(self.root + os.sep):
                    try:
                        os.rmdir(parent)
                    except OSError:
                        break
                    parent = os.path.dirname(parent)
            # The save point's files are written over what is there, through a scratch index.
            written = [one for one in held if one not in sparse]
            index = self.scratch_index(target["commit"])
            try:
                code, out, err = self.git("checkout-index", "-f", "-z", "--stdin", index=index, cwd=top, given="\0".join(written) + "\0") if written else (0, "", "")
            finally:
                self.drop_index(index)
            if code != 0:
                return {"ok": False, "error": f"{(err or out).splitlines()[0] if (err or out) else 'git could not write the files'}" + (f"; what was there is kept as {kept}" if kept else "")}
            # The person's index goes back to the branch's for this folder, so that everything that now differs from
            # the branch shows as a change, none of it staged.
            if self.branch_commit():
                self.git("reset", "-q", "--", ".")
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
            try:
                world = int(body.get("world"))
            except (TypeError, ValueError):
                world = target["world"]
            level = str(body.get("level") or "").strip() or target["level"]
            record.setdefault("events", []).append({
                "id": f"pipe-return-{stamp.replace('T', '-')}", "kind": "pipe", "title": f"Returned to {target['title']}",
                "text": (f"The branch did not move. What was there is kept as {kept}." if kept
                         else "The branch did not move. Nothing in the folder had changed, so there was nothing to keep.")[:240],
                "world": world, "level": level, "at": now,
                "status": "done", "doneAt": now, "to": {"world": target["world"], "level": target["level"]},
            })
            # The record and the chat log are the present's, whatever the save point held: they are put back.
            write_json(self.record_path(), record)
            for one, text in chat_kept.items():
                if not self.inside(one):
                    continue
                try:
                    with open(one, "w", encoding="utf-8") as handle:
                        handle.write(text)
                except OSError:
                    pass
        # The chat is told what happened in fixed words: the entry's name holds the save point's title, the record's text.
        how = ("what was there before is kept as a git stash entry" if kept.startswith("the git stash entry")
               else "what was there before is kept as a save point" if kept
               else "nothing in the folder had changed since, so there was nothing to keep")
        self.prompt({"text": f"I returned the project's files to a save point (commit {target['commit'][:7]}) from the board. My branch did not move; {how}. Re-read the files you rely on before going on."})
        return {"ok": True, "keptAs": kept}

    def back(self, body):
        """Takes the last card answer of the open world back and asks the chat for its card again. Never an applied
        world, never the side quests; a chat note or a skipped card is left where it is."""
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            run = next((r for r in reversed(record.get("runs", []))
                        if r.get("finishedAt") is None and r.get("pack") != "side" and r.get("world") != 0), None)
            if not run:
                return {"ok": False, "error": "the last world was applied and closed; nothing to take back"}
            decisions = run.get("decisions") if isinstance(run.get("decisions"), list) else []
            index = next((i for i in range(len(decisions) - 1, -1, -1) if decisions[i].get("via") in (None, "card", "auto")), None)
            if index is None:
                return {"ok": False, "error": "no card answer to take back in this world yet"}
            dropped = decisions.pop(index)
            level = dropped.get("level")
            levels = run.get("levels")
            if isinstance(levels, dict) and levels.get(level) == "open" and not any(d.get("level") == level for d in decisions):
                levels.pop(level, None)
            write_json(self.record_path(), record)
        where = card_ref(dropped.get("level"), dropped.get("id"))
        self.prompt({"text": f"Present the card {where} again, with no text before it." if where
                     else "On the board I took back the last card I answered: present it again, with no text before it."})
        return {"ok": True, "level": dropped.get("level"), "id": dropped.get("id")}

    def off(self, body):
        """The page's Off button: leaves a mark the plugin's timer acts on within two seconds (it lets a waiting card
        go, ends its turn and leaves game mode). Typed in the chat, /siui off waits for the turn a card holds open."""
        touch(self.path("off"))
        return {"ok": True}

    def on(self, body):
        """The page's On button: a mark the plugin's timer acts on; it turns game mode on and waits for the person."""
        touch(self.path("on"))
        return {"ok": True}

    def auto(self, body):
        """Auto-pilot's switch, shared with the plugin through one file in the run folder."""
        on = bool(body.get("on"))
        write_json(self.path("auto.json"), {"on": on, "at": time.time()})
        return {"ok": True, "on": on}

    def chat_first(self, body):
        """The chat-first switch: cards stay in the chat dialog while this page is open; the page only mirrors them."""
        on = bool(body.get("on"))
        write_json(self.path("chat-first.json"), {"on": on, "at": time.time()})
        return {"ok": True, "on": on}

    def prompt(self, body):
        text = str(body.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "text is required"}
        with open(self.path("inbox-prompts.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"text": text, "at": time.time()}) + "\n")
        return {"ok": True}

    def open_file(self, body):
        """Opens a file in VS Code: one under the project, or one the record names as a source of some decision."""
        given = str(body.get("path") or "").strip()
        if not given:
            return {"ok": False, "error": "path is required"}
        if is_network_path(given):
            return {"ok": False, "error": "a path on another machine is not opened from the board"}
        absolute = self.resolve(given)
        if is_network_path(absolute):
            return {"ok": False, "error": "a path on another machine is not opened from the board"}
        root = os.path.realpath(self.root)
        if not absolute.startswith(root + os.sep):
            record = self.read_record({})
            named = {self.resolve(path) for path in self.source_paths(record)} if isinstance(record, dict) else set()
            if absolute not in named:
                return {"ok": False, "error": "outside the project and not a source the record names"}
        if not os.path.exists(absolute):
            return {"ok": False, "error": "not there yet"}
        code = find_remote_code()
        sockets = live_sockets(self.ipc or os.environ.get("VSCODE_IPC_HOOK_CLI")) if code else []
        if not code or not sockets:
            # No remote window to reach: a plain desktop, where `code` opens the file or its folder shows it.
            error, how = open_locally(absolute)
            return {"ok": True, "how": how} if not error else {"ok": False, "error": error}
        last = ""
        for sock in sockets:
            env = dict(os.environ, VSCODE_IPC_HOOK_CLI=sock)
            try:
                ran = subprocess.run([code, "-r", absolute], env=env, capture_output=True, text=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired) as error:
                last = str(error)
                continue
            if ran.returncode == 0:
                return {"ok": True}
            last = (ran.stderr or ran.stdout).strip().split("\n")[0] or "the editor refused"
        return {"ok": False, "error": last or "could not open it"}

    def should_stop(self):
        if os.path.exists(self.path("stop")):
            return True
        heartbeat = self.path("heartbeat")
        if not os.path.exists(heartbeat):
            return time.time() - self.started > 180
        return time.time() - os.path.getmtime(heartbeat) > 180


def make_handler(board):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_bytes(self, payload, kind, status=200, headers=()):
            try:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                # The caller left before its answer: nothing to send, and nothing worth a line in the log.
                self.close_connection = True

        def send_json(self, data, status=200):
            # Data is for the page alone: no other site may load it as a script or a picture.
            self.send_bytes(json.dumps(data).encode("utf-8"), "application/json; charset=utf-8", status,
                            (("Cross-Origin-Resource-Policy", "same-origin"),))

        def allowed(self):
            """Whether the call may be the page's own: an Origin on one of this server's ports, or none and a local
            Host; never a request a browser marks as coming from another site. Another local site's page would send
            its own Origin; a stray tool would send neither name."""
            if (self.headers.get("Sec-Fetch-Site") or "").strip().lower() == "cross-site":
                return False
            # Another user of this machine, known as such, is refused whatever the call carries: a pass read off a
            # command line, or a key come by some other way, is of no use to them.
            if foreign_caller(self, board.port):
                return False
            origin = self.headers.get("Origin")
            if origin is not None:
                return board.local_origin(origin)
            return board.local_host(self.headers.get("Host") or "")

        def keyed(self):
            """Whether the call carries the board's key."""
            given = self.headers.get(KEY_HEADER) or ""
            return hmac.compare_digest(given.encode("utf-8", "replace"), board.key.encode("ascii"))

        def forbid(self):
            self.send_json({"ok": False, "error": "forbidden"}, 403)

        def no_key(self):
            self.send_json({"ok": False, "error": "the board's key is missing or not this board's"}, 401)

        def do_GET(self):
            try:
                self.answer_get()
            except Exception as error:  # noqa: BLE001 - a file of an odd shape is one answer, never a dead connection
                try:
                    self.send_json({"ok": False, "error": f"{type(error).__name__}: {error}"}, 500)
                except OSError:
                    pass

        def answer_get(self):
            route = urlparse(self.path).path
            # The page and its icon are the same for everyone and may be reached from a link or a frame on another
            # site (the editor's own browser is one): a local Host is all they ask. The rest is the page's own calls.
            if route in ("/", "/index.html", "/icon.svg", "/icon.png"):
                if not board.local_host(self.headers.get("Host") or ""):
                    self.forbid()
                    return
            elif not self.allowed():
                self.forbid()
                return
            if route in ("/state", "/head", "/universes", "/universe") and not self.keyed():
                self.no_key()
                return
            if route in ("/", "/index.html"):
                try:
                    with open(os.path.join(HERE, "index.html"), "rb") as handle:
                        page = handle.read()
                except OSError:
                    self.send_json({"error": "index.html is missing"}, 500)
                    return
                # One kind of line end, so the scripts the browser reads are the bytes the policy's hashes were made of.
                page = page.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                self.send_bytes(page, "text/html; charset=utf-8", 200, (("Content-Security-Policy", page_policy(page)),))
            elif route in ("/icon.svg", "/icon.png"):
                try:
                    with open(os.path.join(HERE, "..", route.lstrip("/")), "rb") as handle:
                        icon = handle.read()
                except OSError:
                    self.send_json({"error": "the icon is missing"}, 404)
                    return
                self.send_bytes(icon, "image/png" if route.endswith(".png") else "image/svg+xml")
            elif route == "/id":
                nonce = (parse_qs(urlparse(self.path).query).get("n") or [""])[0]
                if not re.match(r"^[A-Za-z0-9_-]{16,64}$", nonce):
                    self.send_json({"error": "a nonce is required"}, 400)
                else:
                    self.send_json({"siui": True, "proof": board.proof(nonce)})
            elif route == "/state":
                self.send_json(board.state())
            elif route == "/head":
                self.send_json(board.head())
            elif route == "/universes":
                self.send_json({"sets": board.universes()})
            elif route == "/universe":
                name = (parse_qs(urlparse(self.path).query).get("name") or [""])[0]
                data = board.universe(name)
                if data is None:
                    self.send_json({"error": "no such universe"}, 404)
                else:
                    self.send_json(data)
            else:
                self.send_json({"error": "not found"}, 404)

        def do_POST(self):
            route = urlparse(self.path).path
            if not self.allowed() or not (self.headers.get("Content-Type") or "").strip().lower().startswith("application/json"):
                self.forbid()
                return
            if route != "/enter" and not self.keyed():
                self.no_key()
                return
            try:
                length = int(self.headers.get("Content-Length"))
            except (TypeError, ValueError):
                self.send_json({"ok": False, "error": "a Content-Length is required"}, 400)
                return
            if length < 0 or length > (MAX_EXPORT_BODY if route == "/export" else MAX_BODY):
                self.send_json({"ok": False, "error": "the body is too large"}, 400)
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self.send_json({"ok": False, "error": "bad JSON"}, 400)
                return
            except OSError:
                # The caller left in the middle of what it was sending.
                self.close_connection = True
                return
            if not isinstance(body, dict):
                body = {}
            routes = {
                "/enter": board.enter,
                "/answer": board.answer,
                "/note": board.note,
                "/prompt": board.prompt,
                "/event": board.event,
                "/checkpoint": board.checkpoint,
                "/back": board.back,
                "/auto": board.auto,
                "/off": board.off,
                "/on": board.on,
                "/chatfirst": board.chat_first,
                "/revert": board.revert,
                "/open": board.open_file,
                "/universe": board.set_universe,
                "/forget": board.forget,
                "/move": board.move,
                "/queue": board.queue,
                "/abandon": board.abandon,
                "/pack-hide": board.hide_pack,
                "/pack-delete": board.delete_pack,
                "/export": board.export,
            }
            action = routes.get(route)
            if action is None:
                self.send_json({"error": "not found"}, 404)
                return
            try:
                self.send_json(action(body))
            except Exception as error:  # noqa: BLE001 - one route's failure is one answer, never a dead connection
                self.send_json({"ok": False, "error": f"{type(error).__name__}: {error}"}, 500)

    return Handler


def code_stamp():
    """The change mark of this program's own file; 0 when it cannot be read."""
    try:
        return os.stat(os.path.abspath(__file__)).st_mtime_ns
    except OSError:
        return 0


def code_stamp_after(seconds):
    """The stamp once more after a pause: a file still being written keeps moving, a finished one does not."""
    time.sleep(seconds)
    return code_stamp()


def restart_self(server, board, port):
    """Frees the port, starts this program again through the launcher with the same arguments and the port it
    holds, and exits; when the launcher is not there or fails, goes on serving as it is."""
    launcher = os.path.join(HERE, "launch.py")
    if not os.path.exists(launcher):
        return
    args = list(sys.argv[1:])
    if "--port" in args and args.index("--port") + 1 < len(args):
        args[args.index("--port") + 1] = str(port)
    else:
        args += ["--port", str(port)]
    print(f"the server's code changed; restarting on port {port}", file=sys.stderr, flush=True)
    try:
        os.remove(board.path("server.json"))
    except OSError:
        pass
    try:
        server.socket.close()
    except OSError:
        pass
    try:
        subprocess.run([sys.executable, "-I", launcher, "start", *args], timeout=30)
    finally:
        os._exit(0)


def port_answers(port):
    """Whether something already listens on the port. Windows lets two programs bind one port, and WSL relays its
    own listeners onto Windows' localhost: a board bound there would sit behind another, unreachable."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        probe.close()


class BoardServer(ThreadingHTTPServer):
    """On Windows the address is taken for this server alone, never shared with another listener."""

    if os.name == "nt":
        allow_reuse_address = False

        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="the project root")
    parser.add_argument("--run", required=True, help="the runtime folder")
    parser.add_argument("--record", default=".claude/decisions.json", help="the record, relative to the root")
    parser.add_argument("--chat", default=".claude/chat-log.jsonl", help="the chat log, relative to the root")
    parser.add_argument("--port", type=int, default=5131)
    parser.add_argument("--ipc", default="", help="the VS Code window's IPC socket, tried first when opening a file")
    args = parser.parse_args()

    board = Board(args)
    server = None
    port = args.port
    for candidate in board.ports:
        try:
            if port_answers(candidate):
                continue
            server = BoardServer(("127.0.0.1", candidate), make_handler(board))
            port = candidate
            board.port = candidate
            break
        except OSError:
            continue
    if server is None:
        print(f"no free port from {args.port}", file=sys.stderr)
        sys.exit(2)

    for stale in ("stop",):
        try:
            os.remove(board.path(stale))
        except OSError:
            pass
    write_json(board.path("server.json"), {"pid": os.getpid(), "port": port, "startedAt": board.started})

    code_at_start = code_stamp()

    def watchdog():
        while True:
            time.sleep(5)
            if board.should_stop():
                try:
                    os.remove(board.path("server.json"))
                except OSError:
                    pass
                os._exit(0)
            # The page is read from disk on every load, this program once: when its own file changed (an update of
            # the plugin, an edit while developing), a page newer than its server would meet routes that are not
            # there. So the server starts its successor on the same port and leaves.
            now = code_stamp()
            if now != code_at_start and now == code_stamp_after(1.0):
                restart_self(server, board, port)

    threading.Thread(target=watchdog, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
