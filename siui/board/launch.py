#!/usr/bin/env python3
"""The board's launcher: the steps the plugin's hooks once ran through a Unix shell,
done here the right way on every platform, Windows included.

    launch.py folder <run>                    makes the run folder, the user's alone; exit 1 when it is not theirs
    launch.py start --root R --run F --record P --chat C --port N [--ipc S]
                                              clears a stop file and starts server.py detached, its output in server.log
    launch.py probe <port> <run>              whether the server on that port is this run folder's board: exit 0 when
                                              it proves it holds the folder's key, 3 when something else answers
                                              there, 1 when nothing does
    launch.py pass <run>                      writes a one-time pass into the run folder and prints it: the page
                                              opened with it in its address trades it for the board's key
    launch.py open <run> <port>               opens the board in the person's browser with a fresh pass; exit 1
                                              when no browser could be opened (the pass is then removed)
    launch.py move <from> <to>                renames one file over another in one step
    launch.py remove <path>...                removes files; a missing one is fine

Standard library only.
"""

import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
IS_WINDOWS = os.name == "nt"


def folder(run):
    """Makes the run folder. On Unix it is readable by the user alone and refused when somebody else owns it (a
    folder planted under a shared path could feed the board another's files); on Windows the user's own
    LOCALAPPDATA gives the same privacy."""
    try:
        os.makedirs(run, mode=0o700, exist_ok=True)
        if not IS_WINDOWS:
            os.chmod(run, 0o700)
            return 0 if os.stat(run).st_uid == os.getuid() else 1
        return 0
    except OSError:
        return 1


def start(argv):
    """Starts the server detached: it outlives this command and ends by itself when the chat's heartbeat stops."""
    run = argv[argv.index("--run") + 1] if "--run" in argv and argv.index("--run") + 1 < len(argv) else ""
    if not run or folder(run) != 0:
        return 1
    try:
        os.remove(os.path.join(run, "stop"))
    except OSError:
        pass
    command = [sys.executable, "-I", os.path.join(HERE, "server.py"), *argv]
    with open(os.path.join(run, "server.log"), "ab") as log:
        if not IS_WINDOWS:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            return 0
        detached = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        # A host may run its commands inside a job that ends its children with it: break away when allowed.
        for flags in (detached | subprocess.CREATE_BREAKAWAY_FROM_JOB, detached):
            try:
                subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags, close_fds=True)
                return 0
            except OSError:
                continue
    return 1


def probe(port, run):
    """Asks the server on the port to prove it holds this run folder's key: a fresh nonce goes out, and the answer
    is checked here against the key file. The key itself is never sent, so a program that took the port learns
    nothing; and the port is part of the answer, so it cannot pass the question on to the real board."""
    try:
        port = int(port)
        with open(os.path.join(run, "key"), encoding="ascii") as handle:
            key = handle.read().strip()
    except (OSError, ValueError):
        key = ""
    nonce = secrets.token_urlsafe(24)
    try:
        # No proxy: the call is to this machine.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        answer = json.load(opener.open(f"http://127.0.0.1:{port}/id?n={nonce}", timeout=2))
    except Exception:  # noqa: BLE001 - nothing answers, or not in JSON
        # A listener that is not a board (or an older board) still holds the port.
        return 3 if port_taken(port) else 1
    wanted = hmac.new(key.encode("ascii", "replace"), f"{nonce}:{port}".encode("ascii"), hashlib.sha256).hexdigest()
    proof = answer.get("proof") if isinstance(answer, dict) else None
    return 0 if key and isinstance(proof, str) and hmac.compare_digest(proof, wanted) else 3


def port_taken(port):
    """Whether anything listens on the port."""
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe_socket.settimeout(0.5)
    try:
        return probe_socket.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        probe_socket.close()


def make_pass(run):
    """A one-time pass for the page: written into the run folder, the user's alone, and printed for the address."""
    if folder(run) != 0:
        return 1
    made = secrets.token_urlsafe(32)
    path = os.path.join(run, "pass")
    try:
        handle = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w", encoding="ascii") as out:
            json.dump({"pass": made, "at": time.time()}, out)
        os.replace(path + ".new", path)
    except OSError:
        return 1
    print(made)
    return 0


def is_wsl():
    try:
        with open("/proc/version", encoding="utf-8") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def open_board(run, port):
    """Opens the board with a one-time pass. An address given to a program is seen, for a moment, by whoever can
    list this machine's processes, so the pass travels the way each system keeps it private:

    - Windows, and Windows' browser from WSL: in the address; a command line there is its own user's to see.
    - macOS: in a small page of the run folder (the user's alone) that sends the browser on; only the page's path
      is on a command line.
    - Linux: in the address, since a browser packed as a snap cannot read the run folder; the server refuses a pass
      or a key from another user there, whom the kernel names.

    When nothing could be opened the pass is removed, so none is left waiting for whoever finds it."""
    try:
        port = int(port)
    except ValueError:
        return 1
    if folder(run) != 0:
        return 1
    made = secrets.token_urlsafe(32)
    waiting = os.path.join(run, "pass")
    try:
        handle = os.open(waiting + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w", encoding="ascii") as out:
            json.dump({"pass": made, "at": time.time()}, out)
        os.replace(waiting + ".new", waiting)
    except OSError:
        return 1
    url = f"http://127.0.0.1:{port}/?p={made}"

    def ran(command):
        try:
            return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    opened = False
    if IS_WINDOWS:
        try:
            os.startfile(url)  # noqa: S606 - an address of this machine, handed to the user's own browser
            opened = True
        except OSError:
            opened = False
    elif is_wsl():
        opened = ran(["wslview", url]) or ran(["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{url}'"]) or ran(["xdg-open", url])
    elif sys.platform == "darwin":
        page = os.path.join(run, "open.html")
        try:
            handle = os.open(page, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                out.write(f'<!doctype html><meta charset="utf-8"><title>Siui</title><meta http-equiv="refresh" content="0;url={url}">'
                          f'<p><a href="{url}">Open the board</a></p>\n')
            opened = ran(["open", page])
        except OSError:
            opened = False
    else:
        opened = ran(["xdg-open", url])
    if not opened:
        remove([waiting, os.path.join(run, "open.html")])
        return 1
    return 0


def move(source, target):
    try:
        os.replace(source, target)
        return 0
    except OSError:
        return 1


def remove(paths):
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass
    return 0


def main():
    args = sys.argv[1:]
    verb = args[0] if args else ""
    if verb == "folder" and len(args) == 2:
        return folder(args[1])
    if verb == "start":
        return start(args[1:])
    if verb == "probe" and len(args) == 3:
        return probe(args[1], args[2])
    if verb == "pass" and len(args) == 2:
        return make_pass(args[1])
    if verb == "open" and len(args) == 3:
        return open_board(args[1], args[2])
    if verb == "move" and len(args) == 3:
        return move(args[1], args[2])
    if verb == "remove":
        return remove(args[1:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
