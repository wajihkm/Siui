#!/usr/bin/env python3
"""The board's launcher: the steps the plugin's hooks once ran through a Unix shell,
done here the right way on every platform, Windows included.

    launch.py folder <run>                    makes the run folder, the user's alone; exit 1 when it is not theirs
    launch.py start --root R --run F --record P --chat C --port N [--ipc S]
                                              clears a stop file and starts server.py detached, its output in server.log
    launch.py probe <port>                    prints the project root the server on that port serves; exit 1 when none
    launch.py move <from> <to>                renames one file over another in one step
    launch.py remove <path>...                removes files; a missing one is fine

Standard library only.
"""

import json
import os
import subprocess
import sys
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


def probe(port):
    try:
        state = json.load(urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/state", timeout=2))
    except Exception:  # noqa: BLE001 - nothing answers, or it is not the board
        return 1
    print(str(state.get("root") or ""))
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
    if verb == "probe" and len(args) == 2:
        return probe(args[1])
    if verb == "move" and len(args) == 3:
        return move(args[1], args[2])
    if verb == "remove":
        return remove(args[1:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
