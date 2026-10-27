#!/usr/bin/env python3
"""The siui board: a local page that shows the world map, the live card and
the record, and takes input back.

Started by the plugin, detached, once per project. Serves index.html beside this
file; GET /state answers the record, the live card and the configuration, GET
/head a stamp that moves whenever /state would (the page polls that and fetches
/state on a change); POST /answer, /note, /prompt and /open take the page's
input. Only the page may call the routes beyond /, /icon.svg and /icon.png: a local Origin
or Host, and JSON for a POST; anything else is refused. Everything runtime lives
in the run folder the plugin names: the live card, the answer inbox, the prompt
inbox, the page's liveness mark and the plugin's heartbeat. The server exits by
itself when the plugin's heartbeat stops or a stop file appears.

Binds 127.0.0.1 only. Standard library only.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import socket
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


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


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


def find_code():
    """The VS Code CLI of the running server, newest first; else `code` on PATH."""
    home = os.path.expanduser("~")
    found = glob.glob(os.path.join(home, ".vscode-server", "bin", "*", "bin", "remote-cli", "code"))
    if found:
        return max(found, key=os.path.getmtime)
    return shutil.which("code")


def live_sockets(preferred):
    """The IPC sockets of the VS Code windows alive now, the preferred one first, newest next.

    The CLI needs one in VSCODE_IPC_HOOK_CLI; the one this server was started with may belong
    to a window since closed, so every candidate is tried for a connection."""
    paths = []
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
    def __init__(self, args):
        self.root = os.path.abspath(args.root)
        self.run = os.path.abspath(args.run)
        self.record = args.record
        self.chat = args.chat
        self.ipc = args.ipc or ""
        self.started = time.time()
        self.ports = range(args.port, args.port + PORT_SPAN)
        self.lock = threading.Lock()  # held around every read-modify-write of the record and the configuration
        self.last_record = None  # the text of the last record that parsed, for a poll that lands on a half-written file
        self.record_missing_since = None  # when the record file vanished, for the grace that covers a git reset
        self._git_identity = None  # the -c identity options, found once
        os.makedirs(self.run, exist_ok=True)

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
        plugin's bundled packs ("plugin"), the home folder's skill ("home")."""
        folders = [
            (os.path.join(self.root, ".claude", "skills", "decision-cards", "packs"), "project"),
            (os.path.join(HERE, "..", "packs"), "plugin"),
        ]
        config = read_json(os.path.join(self.root, ".claude", "siui.json"), {})
        for extra in config.get("packs", []) if isinstance(config, dict) else []:
            if isinstance(extra, str) and extra and ".." not in extra:
                folders.append((extra if os.path.isabs(extra) else os.path.join(self.root, extra), "project"))
        home = os.path.expanduser("~")
        if home and home != "~":
            folders.append((os.path.join(home, ".claude", "skills", "decision-cards", "packs"), "home"))
        seen, out = set(), []
        for folder, source in folders:
            real = os.path.realpath(folder)
            if real in seen or not os.path.isdir(real):
                continue
            seen.add(real)
            out.append((real, source))
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
        path = os.path.join(self.root, ".claude", "siui.json")
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
        path = os.path.join(self.root, ".claude", "siui.json")
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
        if pack["source"] != "project":
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
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d-%H%M", time.localtime())
        name = f"roadmap-{stamp}.{self.EXPORT_EXT[kind]}"
        path = os.path.join(folder, name)
        try:
            with open(path, "w", encoding="utf-8") as handle:
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
        for folder, source in self.pack_folders():
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
                        "source": source, "hidden": name in hidden}
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

    def record_path(self):
        return os.path.join(self.root, self.record)

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
        for run in record.get("runs", []):
            for one in run.get("decisions", []):
                for source in one.get("sources", []) or []:
                    path = source.get("path") if isinstance(source, dict) else None
                    if isinstance(path, str) and path.strip():
                        paths.add(path.strip())
        return paths

    def files_of(self, record):
        """What is on disk for every file the record's decisions name: exists, size, last change."""
        files = {}
        for path in self.source_paths(record):
            try:
                stat = os.stat(self.resolve(path))
                files[path] = {"exists": True, "size": stat.st_size, "mtime": stat.st_mtime, "isDir": os.path.isdir(self.resolve(path))}
            except OSError:
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
            "project": name.strip() if isinstance(name, str) and name.strip() else (os.path.basename(self.root.rstrip("/")) or self.root),
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
            self.prompt({"text": f"On the board, my note on {level}/{decision_id} ({title}): {note}"})
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

    def git(self, *args, timeout=60):
        try:
            out = subprocess.run(["git", *self.git_options(), *args],
                                 cwd=self.root, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            return 1, "", str(error)
        return out.returncode, out.stdout.strip(), out.stderr.strip()

    def checkpoint(self, body):
        """Commits the whole tree as a save point and records it on the stage."""
        title = str(body.get("title") or "").strip()[:60] or "Checkpoint"
        code, _, _ = self.git("rev-parse", "--is-inside-work-tree")
        if code != 0:
            return {"ok": False, "error": "not a git repository"}
        with self.lock:
            self.git("add", "-A")
            code, out, err = self.git("commit", "-q", "-m", f"Checkpoint: {title}")
            if code != 0 and not re.search(r"nothing to commit|nothing added", out + err, re.I):
                return {"ok": False, "error": (err or out).split("\n")[0] or "the commit failed"}
            _, sha, _ = self.git("rev-parse", "HEAD")
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
        return {"ok": True, "id": made["id"], "commit": sha}

    def revert(self, body):
        """Returns the tree to a checkpoint. What is there now is committed and tagged first, so nothing is lost."""
        event_id = str(body.get("id") or "").strip()
        with self.lock:
            record = self.read_record(fresh=True)
            if not isinstance(record, dict):
                return {"ok": False, "error": "the record cannot be read now; nothing was changed"}
            target = next((one for one in record.get("events", []) if one.get("id") == event_id and one.get("kind") == "checkpoint"), None)
            if not target or not target.get("commit"):
                return {"ok": False, "error": "no such checkpoint"}
            code, _, _ = self.git("cat-file", "-e", f"{target['commit']}^{{commit}}")
            if code != 0:
                return {"ok": False, "error": f"commit {target['commit'][:7]} is not in this repository"}
            chat_path = os.path.join(self.root, self.chat)
            chat_text = None
            try:
                with open(chat_path, encoding="utf-8") as handle:
                    chat_text = handle.read()
            except OSError:
                pass
            self.git("add", "-A")
            self.git("commit", "-q", "-m", f"Before returning to checkpoint: {target['title']}")
            stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
            kept = f"checkpoints/before-{stamp}"
            code, _, err = self.git("tag", kept, "HEAD")
            if code != 0:
                return {"ok": False, "error": err.split("\n")[0] or "could not keep the current state"}
            code, _, err = self.git("reset", "--hard", target["commit"])
            if code != 0:
                return {"ok": False, "error": err.split("\n")[0] or "the reset failed"}
            # The record and the chat log live in the tree: put the present ones back, with the return on the map.
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                world = int(body.get("world"))
            except (TypeError, ValueError):
                world = target["world"]
            level = str(body.get("level") or "").strip() or target["level"]
            record.setdefault("events", []).append({
                "id": f"pipe-return-{stamp.replace('T', '-')}", "kind": "pipe", "title": f"Returned to {target['title']}",
                "text": f"The state left behind is kept as the tag {kept}.", "world": world, "level": level, "at": now,
                "status": "done", "doneAt": now, "to": {"world": target["world"], "level": target["level"]},
            })
            write_json(self.record_path(), record)
            if chat_text is not None:
                try:
                    with open(chat_path, "w", encoding="utf-8") as handle:
                        handle.write(chat_text)
                except OSError:
                    pass
        self.prompt({"text": f"I returned the project to the checkpoint \"{target['title']}\" ({target['commit'][:7]}) from the board; the state before is kept as the git tag {kept}. Re-read the files you rely on before going on."})
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
        self.prompt({"text": f"Present the card {dropped.get('level', '')}/{dropped.get('id', '')} ({dropped.get('title', '')}) again, with no text before it."})
        return {"ok": True, "level": dropped.get("level"), "id": dropped.get("id")}

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
        absolute = self.resolve(given)
        root = os.path.realpath(self.root)
        if not absolute.startswith(root + os.sep):
            record = self.read_record({})
            named = {self.resolve(path) for path in self.source_paths(record)} if isinstance(record, dict) else set()
            if absolute not in named:
                return {"ok": False, "error": "outside the project and not a source the record names"}
        if not os.path.exists(absolute):
            return {"ok": False, "error": "not there yet"}
        code = find_code()
        if not code:
            return {"ok": False, "error": "no VS Code command found"}
        sockets = live_sockets(self.ipc or os.environ.get("VSCODE_IPC_HOOK_CLI"))
        if not sockets:
            return {"ok": False, "error": "no VS Code window is reachable"}
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

        def send_json(self, data, status=200):
            payload = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def allowed(self):
            """Whether the call is the page's own: an Origin on one of this server's ports, or none and a local Host.
            Another local site's page would send its own Origin; a stray tool would send neither name."""
            origin = self.headers.get("Origin")
            if origin is not None:
                return board.local_origin(origin)
            return board.local_host(self.headers.get("Host") or "")

        def forbid(self):
            self.send_json({"ok": False, "error": "forbidden"}, 403)

        def do_GET(self):
            route = urlparse(self.path).path
            if route in ("/state", "/head", "/universes", "/universe") and not self.allowed():
                self.forbid()
                return
            if route in ("/", "/index.html"):
                try:
                    with open(os.path.join(HERE, "index.html"), "rb") as handle:
                        page = handle.read()
                except OSError:
                    self.send_json({"error": "index.html is missing"}, 500)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(page)
            elif route in ("/icon.svg", "/icon.png"):
                try:
                    with open(os.path.join(HERE, "..", route.lstrip("/")), "rb") as handle:
                        icon = handle.read()
                except OSError:
                    self.send_json({"error": "the icon is missing"}, 404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png" if route.endswith(".png") else "image/svg+xml")
                self.send_header("Content-Length", str(len(icon)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(icon)
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
            if not isinstance(body, dict):
                body = {}
            routes = {
                "/answer": board.answer,
                "/note": board.note,
                "/prompt": board.prompt,
                "/event": board.event,
                "/checkpoint": board.checkpoint,
                "/back": board.back,
                "/auto": board.auto,
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
            server = ThreadingHTTPServer(("127.0.0.1", candidate), make_handler(board))
            port = candidate
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

    def watchdog():
        while True:
            time.sleep(5)
            if board.should_stop():
                try:
                    os.remove(board.path("server.json"))
                except OSError:
                    pass
                os._exit(0)

    threading.Thread(target=watchdog, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
