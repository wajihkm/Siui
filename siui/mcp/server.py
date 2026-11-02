#!/usr/bin/env python3
"""Siui for GitHub Copilot: an MCP server over stdio with the card tools.

Copilot (VS Code agent mode, the Copilot CLI, the cloud agent) cannot draw in its
own dialog, so it gets Siui through the Model Context Protocol: this server
offers the tools the Claude Code plugin registers through its hooks, with the
same record (.claude/decisions.json), the same run folder and the same board.

    card    one decision: waits for the answer on the board while its page is open;
            else asks through an elicitation form when the client has one; else
            returns the text card for the chat and takes the answer with `answer`
    answer  the user's answer to a text card
    note    a decision the user took in the chat
    event   a bug, a feature, a problem, a check, a jump or a save point on the map
    done    finishes the world after the boss was applied
    board   starts the board's server and opens its page
    status  the world map as text, and every answer so far

Started by Copilot from the plugin's manifest or from .vscode/mcp.json, with the
project as its working directory (or --root). Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
BOARD = os.path.join(PLUGIN, "board")
PROTOCOL = "2025-06-18"
RECORD_PATH = ".claude/decisions.json"
CONFIG_PATH = ".claude/siui.json"
CHAT_PATH = ".claude/chat-log.jsonl"
SIDE_PACK = "side"
RUN_FOLDER = "siui"
DEFAULT_PORT = 5131
ALIVE_SECONDS = 12
WAIT_SECONDS = 3600
DISMISSED = "\0dismissed"
CAPS = {"levelTitle": 40, "title": 60, "short": 120, "explain": 480, "label": 30, "effect": 80, "remaining": 80,
        "note": 200, "name": 30, "why": 60, "options": 4, "sources": 6}
EXTRA_SOURCES = 24
EXPLAIN_WORDS = {"?", "explain", "help", "why", "more"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
MARKS = {"enemy": ("bug or risk", "fixed"), "powerup": ("feature", "built"), "challenge": ("problem", "cleared"),
         "check": ("check", "passed"), "pipe": ("jump", "taken"), "checkpoint": ("save point", "returned to")}
KIND_ALIASES = {"enemy": "enemy", "bug": "enemy", "risk": "enemy", "security": "enemy", "powerup": "powerup",
                "power-up": "powerup", "feature": "powerup", "requirement": "powerup", "challenge": "challenge",
                "problem": "challenge", "check": "check", "coin": "check", "test": "check", "pipe": "pipe",
                "jump": "pipe", "checkpoint": "checkpoint", "save": "checkpoint", "save point": "checkpoint"}
LEVEL = re.compile(r"^[0-9]+-[0-9]+[ab]?$")
PACK_NAME = re.compile(r"^[a-z0-9-]{2,60}$")
HEADING = re.compile(r"^##\s+Level\s+(\d+-\d+)\s*[·:-]\s*(.+?)(?:\s*\((\d+)\s+cards?\))?\s*$")
CARD_ROW = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|\s*([^|]+?)\s*\|")


# ---------------------------------------------------------------- small helpers

def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"


def today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def cut(value, max_len):
    """Trims and cuts a text to `max_len` characters, ending a cut text with an ellipsis."""
    text = re.sub(r"\s+", " ", value.strip()) if isinstance(value, str) else ""
    return (text[: max_len - 1].rstrip() + "…") if len(text) > max_len else text


def slug_of(title):
    made = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-")[:40]
    return made if len(made) >= 2 else f"chat-{int(time.time()):x}"


def time_suffix(iso):
    return iso[11:19].replace(":", "")


def is_level(text):
    return isinstance(text, str) and bool(LEVEL.match(text))


def kind_of(word):
    return KIND_ALIASES.get(word.strip().lower()) if isinstance(word, str) else None


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Writes the file whole: a temp file beside it, then one rename, so a reader never sees half of it."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.getpid()}-{threading.get_ident()}-{time.time_ns()}.tmp"
    done = False
    try:
        with open(tmp, "x", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
        done = True
    finally:
        if not done:
            try:
                os.remove(tmp)
            except OSError:
                pass


def touch(path):
    with open(path, "a", encoding="utf-8"):
        pass
    os.utime(path, None)


# ---------------------------------------------------------------- the configuration

def read_config(root):
    made = {"record": RECORD_PATH, "caps": dict(CAPS), "packs": [], "boardPort": DEFAULT_PORT, "chatLog": CHAT_PATH}
    given = read_json(os.path.join(root, CONFIG_PATH), {})
    if not isinstance(given, dict):
        return made
    record = given.get("record")
    if isinstance(record, str) and record.strip() and ".." not in record and not record.startswith("/"):
        made["record"] = record.strip()
    caps = given.get("caps") if isinstance(given.get("caps"), dict) else {}
    for key in CAPS:
        value = caps.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            made["caps"][key] = min(value, CAPS[key])
    chat = given.get("chatLog")
    if isinstance(chat, str) and chat.strip() and ".." not in chat and not chat.startswith("/"):
        made["chatLog"] = chat.strip()
    port = given.get("boardPort")
    if isinstance(port, int) and not isinstance(port, bool) and 1024 <= port <= 65535:
        made["boardPort"] = port
    packs = given.get("packs")
    if isinstance(packs, list):
        made["packs"] = [one.strip() for one in packs if isinstance(one, str) and one.strip() and ".." not in one][:8]
    return made


# ---------------------------------------------------------------- the record

def target_of(root):
    return os.path.basename(root.rstrip("/")) or "project"


def record_file(root, relative):
    return os.path.join(root, re.sub(r"^\.?/", "", relative))


def read_record(root, relative):
    """The record, with its lists in place; an empty one when the file is not there."""
    record = read_json(record_file(root, relative), None)
    if not isinstance(record, dict):
        record = {"format": 1, "runs": [], "events": []}
    if not isinstance(record.get("runs"), list):
        record["runs"] = []
    if not isinstance(record.get("events"), list):
        record["events"] = []
    for run in record["runs"]:
        if isinstance(run, dict):
            run.setdefault("levels", {})
            run.setdefault("decisions", [])
    return record


def write_record(root, relative, record):
    write_json(record_file(root, relative), record)


def is_side(run):
    return run.get("pack") == SIDE_PACK or run.get("world") == 0


def open_run(record):
    for run in reversed(record["runs"]):
        if run.get("finishedAt") is None and not is_side(run):
            return run
    return None


def last_world_run(record):
    for run in reversed(record["runs"]):
        if not is_side(run):
            return run
    return None


def side_run(record, target, now):
    for run in record["runs"]:
        if is_side(run):
            return run
    run = {"id": f"{target}/side", "target": target, "pack": SIDE_PACK, "world": 0, "startedAt": now[:10],
           "finishedAt": None, "levels": {}, "decisions": []}
    record["runs"].append(run)
    return run


def month_level(at):
    return f"0-{at[0:4]}{at[5:7]}"


def month_title(at):
    try:
        return f"{MONTHS[int(at[5:7]) - 1]} {at[0:4]}"
    except (ValueError, IndexError):
        return at[:7]


def has_stage(run, level):
    return level != "" and (any(one.get("level") == level for one in run.get("plan") or []) or level in run["levels"])


def has_world(record, world):
    return world > 0 and any(not is_side(run) and run.get("world") == world for run in record["runs"])


def route_decision(record, target, world, level, now):
    """Where a decision named for `world` and `level` goes: the open world when named; a world (even finished)
    when the decision names one of its stages; the side world's month otherwise."""
    if world > 0:
        opened = open_run(record)
        if opened and opened.get("world") == world:
            return opened, level, None
        named = next((run for run in record["runs"] if not is_side(run) and run.get("world") == world), None)
        if named and has_stage(named, level):
            return named, level, None
    return side_run(record, target, now), month_level(now), month_title(now)


def ensure_run(record, target, pack, world, now):
    opened = open_run(record)
    if opened and opened.get("world") == world:
        return opened
    taken = {run.get("id") for run in record["runs"]}
    run_id = f"{target}/world-{world}"
    n = 2
    while run_id in taken:
        run_id = f"{target}/world-{world}-{n}"
        n += 1
    run = {"id": run_id, "target": target, "pack": pack, "world": world, "startedAt": now[:10], "finishedAt": None,
           "levels": {}, "decisions": []}
    record["runs"].append(run)
    return run


def add_decision(run, decision, level_title=None, count=None):
    for index, one in enumerate(run["decisions"]):
        if one.get("level") == decision["level"] and one.get("id") == decision["id"]:
            run["decisions"][index] = decision
            break
    else:
        run["decisions"].append(decision)
    if run["levels"].get(decision["level"]) != "done":
        run["levels"][decision["level"]] = "done" if run.get("finishedAt") is not None else "open"
    if level_title:
        run["levelTitles"] = {**run.get("levelTitles", {}), decision["level"]: level_title}
    if count:
        run["levelCounts"] = {**run.get("levelCounts", {}), decision["level"]: count}


def put_event(record, event):
    for index, one in enumerate(record["events"]):
        if one.get("id") == event["id"]:
            record["events"][index] = event
            return event
    record["events"].append(event)
    return event


def parse_level(level):
    m = re.match(r"^(\d+)-(\d+)([ab])?$", level or "")
    return (int(m.group(1)), int(m.group(2)), m.group(3) or "") if m else (0, 0, "")


def is_boss_title(title):
    return bool(re.search(r"\bboss\b", title or "", re.I))


def overview(run):
    """One view per level: title, count, the decisions, the state; the boss flagged."""
    ids = []
    for one in run.get("plan") or []:
        ids.append(one["level"])
    for level in run["levels"]:
        ids.append(level)
    for one in run["decisions"]:
        ids.append(one["level"])
    ordered = sorted(set(ids), key=parse_level)
    last = ordered[-1] if ordered else None
    views = []
    for level in ordered:
        planned = next((one for one in run.get("plan") or [] if one["level"] == level), None)
        title = run.get("levelTitles", {}).get(level) or (planned or {}).get("title") or ""
        count = run.get("levelCounts", {}).get(level) or (planned or {}).get("count")
        decisions = [one for one in run["decisions"] if one["level"] == level and one.get("via") not in ("chat", "skipped")]
        chat = [one for one in run["decisions"] if one["level"] == level and one.get("via") == "chat"]
        skipped = [one for one in run["decisions"] if one["level"] == level and one.get("via") == "skipped"]
        is_boss = is_boss_title(title) or (bool(run.get("plan")) and level == last)
        if is_side(run):
            is_done = level != month_level(now_iso())
        else:
            is_done = run.get("finishedAt") is not None or run["levels"].get(level) == "done" or (count is not None and len(decisions) >= count)
        state = "done" if is_done else ("open" if decisions else "ahead")
        views.append({"level": level, "title": title, "count": count, "decisions": decisions, "chat": chat,
                      "skipped": skipped, "isBoss": is_boss, "state": state})
    current = next((v for v in views if v["state"] == "open"), None) or next((v for v in views if v["state"] == "ahead"), None)
    if current and run.get("finishedAt") is None and not is_side(run):
        current["state"] = "current"
    return views


def has_castle(run):
    views = overview(run)
    return bool(views) and views[-1]["isBoss"]


def summary_lines(run, date, relative):
    lines = []
    for view in overview(run):
        if not view["decisions"] and not view["chat"]:
            continue
        answers = [f"{one['id']}={one['answer']}" for one in view["decisions"]]
        answers += [f"{one['id']}={one['answer']} (chat)" for one in view["chat"]]
        name = f" ({view['title'].lower()})" if view["title"] else ""
        lines.append(f"- {date} [decision] World {run['world']} level {view['level']}{name}: {'; '.join(answers)}. Record: {relative}")
    return lines


def next_card_of(run):
    for level in run.get("plan") or []:
        if run["levels"].get(level["level"]) == "done":
            continue
        for card in level.get("cards") or []:
            if any(one["level"] == level["level"] and one["id"] == card["id"] and one.get("via") not in ("chat", "skipped")
                   for one in run["decisions"]):
                continue
            return {"level": level["level"], "id": card["id"], "title": card["title"]}
    return None


def fit(text, max_len):
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat[: max_len - 1] + "…" if len(flat) > max_len else flat


def status_text(record):
    run = open_run(record) or last_world_run(record)
    if not run:
        return "No run yet. Start one: read a pack and present its first card."
    views = overview(run)
    state = f"finished {run['finishedAt']}" if run.get("finishedAt") else "in progress"
    lines = [f"World {run['world']} · {run['pack']} · {state} · {len(run['decisions'])} decisions"]
    if not views:
        lines.append("No level started yet.")
    for view in views:
        mark = {"done": "●", "current": "▶", "open": "◐"}.get(view["state"], "○")
        progress = f"{len(view['decisions'])}/{max(view['count'], len(view['decisions']))}" if view["count"] else str(len(view["decisions"]))
        name = f" {view['title']}" if view["title"] else ""
        lines.append(f"{mark} {view['level']}{name} · {progress}{' · boss' if view['isBoss'] else ''}")
        for one in view["decisions"]:
            lines.append(f"    {fit(one['title'], 32)} → {fit(one['answer'], 48)}{' (auto)' if one.get('via') == 'auto' else ''}")
        for one in view["chat"]:
            lines.append(f"    {fit(one['title'], 32)} → {fit(one['answer'], 48)} (chat)")
        for one in view["skipped"]:
            lines.append(f"    {fit(one['title'], 32)} → skipped, to present again")
    if run.get("finishedAt") is None:
        nxt = next_card_of(run)
        ahead = next((v for v in views if v["state"] != "done"), None)
        if nxt:
            lines.append(f"Next: present card {nxt['level']}/{nxt['id']} ({nxt['title']}), with no text before it.")
        elif ahead:
            lines.append(f"Next: the first card of level {ahead['level']}{' ' + ahead['title'] if ahead['title'] else ''}.")
        else:
            lines.append("Next: the boss review.")
    return "\n".join(lines)


# ---------------------------------------------------------------- packs

def parse_pack(text):
    plan, current = [], None
    for line in text.split("\n"):
        heading = HEADING.match(line)
        if heading:
            level, title, count = heading.group(1), heading.group(2).strip(), heading.group(3)
            if any(one["level"] == level for one in plan):
                current = None
                continue
            current = {"level": level, "title": title}
            if count:
                current["count"] = int(count)
            plan.append(current)
            continue
        if line.startswith("## "):
            current = None
        row = CARD_ROW.match(line) if current else None
        if row and current:
            card_id, title = row.group(1), row.group(2).strip()
            if not any(one["id"] == card_id for one in current.get("cards", [])):
                current.setdefault("cards", []).append({"id": card_id, "title": title})
    return plan


def pack_candidates(pack, root, extra):
    name = re.sub(r"\.md$", "", pack)
    if not name or "/" in name or ".." in name:
        return []
    paths = [os.path.join(root, ".claude", "skills", "decision-cards", "packs", f"{name}.md"),
             os.path.join(root, "skills", "decision-cards", "packs", f"{name}.md")]
    for folder in extra:
        paths.append(os.path.join(folder if os.path.isabs(folder) else os.path.join(root, folder), f"{name}.md"))
    paths.append(os.path.join(PLUGIN, "packs", f"{name}.md"))
    home = os.environ.get("HOME")
    if home:
        paths.append(os.path.join(home, ".claude", "skills", "decision-cards", "packs", f"{name}.md"))
    return paths


def find_pack(pack, root, extra):
    return next((path for path in pack_candidates(pack, root, extra) if os.path.isfile(path)), None)


def read_plan(pack, root, extra):
    path = find_pack(pack, root, extra)
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            return parse_pack(handle.read())
    except OSError:
        return []


# ---------------------------------------------------------------- git

def git(root, *args):
    identity = []
    try:
        name = subprocess.run(["git", "config", "user.name"], cwd=root, capture_output=True, text=True, timeout=10)
        if name.returncode != 0 or not name.stdout.strip():
            identity = ["-c", "user.name=Siui", "-c", "user.email=siui@localhost"]
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        ran = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *identity, *args],
                             cwd=root, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, "", str(error)
    return ran.returncode, ran.stdout.strip(), ran.stderr.strip()


def save_checkpoint(root, title):
    """Commits everything as a checkpoint; the commit and branch, or an error line."""
    code, _, _ = git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        return {"error": "not a git repository"}
    git(root, "add", "-A")
    code, out, err = git(root, "commit", "-q", "-m", f"Checkpoint: {title}")
    if code != 0 and not re.search(r"nothing to commit|nothing added", out + "\n" + err, re.I):
        return {"error": (err or out).split("\n")[0] or "the commit failed"}
    code, sha, _ = git(root, "rev-parse", "HEAD")
    _, branch, _ = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return {"error": "no commit to point at"}
    return {"commit": sha, "branch": branch or "HEAD"}


# ---------------------------------------------------------------- the card

def clean_picture(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 4000 or not re.match(r"^<svg[\s>]", text, re.I) or not re.search(r"</svg>\s*$", text, re.I):
        return None
    if re.search(r"<script|javascript:|\son[a-z]+\s*=|<foreignObject|<iframe|href\s*=\s*[\"']?(?!#)", text, re.I):
        return None
    if re.search(r"url\(|@import|<use|xlink:|data:", text, re.I) or "viewBox" not in text:
        return None
    return text


def name_of(path, max_len):
    return cut(path.rstrip("/").split("/")[-1] or path, max_len)


def normalise_card(given, caps):
    """A loose input into a card, or an error line; the same caps and rules as the plugin's hook."""
    level = given.get("level").strip() if isinstance(given.get("level"), str) else ""
    if not is_level(level):
        return 'level must look like "1-2"'
    world = given.get("world")
    if not (isinstance(world, int) and not isinstance(world, bool) and world >= 0):
        world = int(level.split("-")[0])
    card_id = given.get("id").strip() if isinstance(given.get("id"), str) else ""
    if not re.match(r"^[a-z0-9-]{2,40}$", card_id):
        return "id must be a slug of 2-40 characters: letters, digits, dashes"
    title = cut(given.get("title"), caps["title"])
    if not title:
        return "title is required"
    short = cut(given.get("short"), caps["short"])
    if not short:
        return "short is required"
    options = []
    for raw in given.get("options") or []:
        if len(options) >= caps["options"]:
            break
        one = raw if isinstance(raw, dict) else {}
        label = cut(one.get("label"), caps["label"])
        if not label or any(o["label"] == label for o in options):
            continue
        option = {"label": label}
        effect = cut(one.get("effect"), caps["effect"])
        if effect:
            option["effect"] = effect
        picture = clean_picture(one.get("picture"))
        if picture:
            option["picture"] = picture
        options.append(option)
    if not options:
        return "options must hold 1-4 entries with a label each"
    kind = given.get("kind") if given.get("kind") in ("info", "boss") else "decision"
    if len(options) == 1:
        options.append({"label": "Stop", "effect": "Leave the game here"})
    recommended = cut(given.get("recommended"), caps["label"])
    if not any(o["label"] == recommended for o in options):
        recommended = ""
    raw_sources = [one for one in (given.get("sources") or []) if isinstance(one, dict)]
    raw_sources.sort(key=lambda one: 0 if one.get("use") == "used" else 1)
    sources, extra = [], []
    for one in raw_sources:
        if len(sources) + len(extra) >= caps["sources"] + EXTRA_SOURCES:
            break
        path = one.get("path").strip() if isinstance(one.get("path"), str) else ""
        if not path or any(s["path"] == path for s in sources + extra):
            continue
        made = {"path": path, "name": cut(one.get("name"), caps["name"]) or name_of(path, caps["name"]),
                "role": one.get("role") if one.get("role") in ("out", "both") else "in",
                "use": "used" if one.get("use") == "used" else "maybe"}
        why = cut(one.get("why"), caps["why"])
        if why:
            made["why"] = why
        (sources if len(sources) < caps["sources"] else extra).append(made)
    card = {"kind": kind, "world": world, "level": level, "id": card_id, "title": title, "short": short,
            "options": options, "sources": sources, "question": re.sub(r"[?:.!]+$", "", title) + "?"}
    if extra:
        card["extraSources"] = extra
    pack = given.get("pack").strip() if isinstance(given.get("pack"), str) else ""
    if PACK_NAME.match(pack):
        card["pack"] = pack
    if given.get("mark") in ("bug", "feature", "problem", "check"):
        card["mark"] = given["mark"]
    for key, cap in (("levelTitle", caps["levelTitle"]), ("explain", caps["explain"]), ("remaining", caps["remaining"]),
                     ("note", caps["note"])):
        value = cut(given.get(key), cap)
        if value:
            card[key] = value
    for key in ("index", "count"):
        value = given.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            card[key] = value
    if recommended:
        card["recommended"] = recommended
    return card


def absolute_path(path, root):
    if path.startswith("/"):
        return path
    if path == "~" or path.startswith("~/"):
        return os.path.join(os.environ.get("HOME", ""), path[2:]) if path != "~" else os.environ.get("HOME", "")
    return os.path.join(root, re.sub(r"^\./", "", path))


def resolve_sources(card, root):
    """Settles each source: its link, whether it exists, its size. Copilot's reads are not visible here, so an
    input the model says it used draws solid on its word; the hook can verify, this server cannot."""
    for source in card["sources"] + card.get("extraSources", []):
        absolute = absolute_path(source["path"], root)
        source["href"] = "file://" + urllib.request.pathname2url(absolute)
        if os.path.exists(absolute):
            if os.path.isfile(absolute):
                try:
                    source["bytes"] = os.path.getsize(absolute)
                except OSError:
                    pass
            if source["role"] != "out" and source["use"] == "used":
                source["isRead"] = True
        else:
            source["isMissing"] = True


def text_card(card, with_explain=False):
    """The skill's text card, for a chat that draws nothing."""
    head = f"[{card['level']} · {card.get('index', 1)}/{card.get('count', 1)}] {card['title']}"
    if card.get("levelTitle"):
        head = f"World {card['world']} · {card['level']} {card['levelTitle']} · card {card.get('index', 1)} of {card.get('count', 1)}\n{card['title']}"
    lines = [head, card["short"]]
    if card.get("note"):
        lines.append(f"Note: {card['note']}")
    if card.get("explain"):
        lines.append(f"Explain: {card['explain']}" if with_explain else 'Explain: say "explain" to see it.')
    lines.append("Consequences:")
    for index, option in enumerate(card["options"], 1):
        star = " ★" if option["label"] == card.get("recommended") else ""
        lines.append(f"  {index} {option['label']}{star}" + (f" — {option['effect']}" if option.get("effect") else ""))
    if card.get("remaining"):
        lines.append(f"Remaining in {card['level']}: {card['remaining']}")
    ins = [s for s in card["sources"] if s["role"] != "out"]
    outs = [s for s in card["sources"] if s["role"] != "in"]
    mark = lambda s, solid: ("━ " if solid else "┄ ") + s["name"] + (" (new)" if s.get("isMissing") and s["role"] != "in" else " (missing)" if s.get("isMissing") else "")
    parts = []
    if ins:
        parts.append("In: " + " · ".join(mark(s, s.get("isRead")) for s in ins))
    if outs:
        parts.append("Out: " + " · ".join(mark(s, s["use"] == "used") for s in outs))
    if parts:
        lines.append("  |  ".join(parts))
    lines.append(f"Answer 1-{len(card['options'])}, or type your own words.")
    return "\n".join(lines)


# ---------------------------------------------------------------- the board

def board_paths(root):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", root).strip("-")[-80:] or "project"
    home = os.environ.get("HOME", "").rstrip("/")
    run = os.path.join(home, ".cache", RUN_FOLDER, slug) if home else os.path.join("/tmp", RUN_FOLDER, slug)
    names = {"card": "card.json", "alive": "alive", "heartbeat": "heartbeat", "stop": "stop", "server": "server.json",
             "status": "status.json", "auto": "auto.json", "chat_first": "chat-first.json", "inbox": "inbox-answer.json"}
    return {"run": run, **{key: os.path.join(run, name) for key, name in names.items()}}


def ensure_run_folder(paths):
    try:
        os.makedirs(paths["run"], mode=0o700, exist_ok=True)
        os.chmod(paths["run"], 0o700)
        return os.stat(paths["run"]).st_uid == os.getuid()
    except OSError:
        return False


def heartbeat(paths):
    try:
        with open(paths["heartbeat"], "w", encoding="utf-8") as handle:
            handle.write(str(int(time.time() * 1000)))
    except OSError:
        pass


def write_status(paths, state, detail=""):
    try:
        write_json(paths["status"], {"state": state, "detail": detail, "at": int(time.time() * 1000)})
    except OSError:
        pass


def publish_card(paths, card):
    try:
        write_json(paths["card"], card or {})
    except OSError:
        pass


def is_board_live(paths):
    try:
        return time.time() - os.path.getmtime(paths["alive"]) < ALIVE_SECONDS
    except OSError:
        return False


def is_chat_first(paths):
    return bool((read_json(paths["chat_first"], {}) or {}).get("on"))


def served_root(port):
    try:
        state = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/state", timeout=2))
        return str(state.get("root") or "").rstrip("/") or None
    except Exception:  # noqa: BLE001 - nothing answers, or not the board
        return None


def server_port(paths):
    port = (read_json(paths["server"], {}) or {}).get("port")
    return port if isinstance(port, int) else None


def ensure_server(root, paths, record_rel, port, chat_rel):
    """Starts the board's server detached unless one answers already for this project; its port, or None."""
    if not ensure_run_folder(paths):
        return None
    heartbeat(paths)
    try:
        os.remove(paths["stop"])
    except OSError:
        pass
    running = server_port(paths)
    start_at = port
    if running is not None:
        served = served_root(running)
        if served is not None and served == root.rstrip("/"):
            return running
        if served is not None:
            start_at = running + 1
    script = os.path.join(BOARD, "server.py")
    argv = [sys.executable or "python3", "-I", script, "--root", root, "--run", paths["run"], "--record", record_rel,
            "--chat", chat_rel, "--port", str(start_at)]
    ipc = os.environ.get("VSCODE_IPC_HOOK_CLI")
    if ipc:
        argv[3:3] = ["--ipc", ipc]
    started = time.time()
    try:
        with open(os.path.join(paths["run"], "server.log"), "ab") as log:
            subprocess.Popen(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    except OSError:
        return None
    for _ in range(20):
        time.sleep(0.25)
        made = server_port(paths)
        if made is not None:
            try:
                fresh = os.path.getmtime(paths["server"]) >= started - 1
            except OSError:
                fresh = False
            if running is None or fresh:
                return made
    return None


def open_browser(url):
    for argv in (["wslview", url], ["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{url}'"],
                 ["xdg-open", url], ["open", url]):
        try:
            if subprocess.run(argv, capture_output=True, timeout=15).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


# ---------------------------------------------------------------- the protocol

class Rpc:
    """JSON-RPC over stdio: one line per message. Requests are served on threads, so a card can wait while pings
    and the client's answers keep flowing; the server's own requests (an elicitation) wait on an event."""

    def __init__(self, handler):
        self.handler = handler
        self.out_lock = threading.Lock()
        self.pending = {}
        self.pending_lock = threading.Lock()
        self.next_id = 1
        self.client = {}

    def send(self, message):
        line = json.dumps(message, ensure_ascii=False)
        with self.out_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def request(self, method, params, timeout):
        """Sends a request to the client and waits for its answer; None when it never comes."""
        with self.pending_lock:
            req_id = f"siui-{self.next_id}"
            self.next_id += 1
            event = threading.Event()
            self.pending[req_id] = [event, None]
        self.send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        event.wait(timeout)
        with self.pending_lock:
            entry = self.pending.pop(req_id, None)
        return entry[1] if entry and entry[0].is_set() else None

    def serve(self):
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                continue
            if isinstance(message, dict) and "method" not in message and "id" in message:
                with self.pending_lock:
                    entry = self.pending.get(message["id"])
                if entry:
                    entry[1] = message
                    entry[0].set()
                continue
            threading.Thread(target=self.handle, args=(message,), daemon=True).start()

    def handle(self, message):
        if not isinstance(message, dict):
            return
        method, params, req_id = message.get("method"), message.get("params") or {}, message.get("id")
        try:
            result = self.handler.dispatch(method, params)
        except KeyError:
            if req_id is not None:
                self.send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown method {method}"}})
            return
        except Exception as error:  # noqa: BLE001 - one request's failure is one error answer
            if req_id is not None:
                self.send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": f"{type(error).__name__}: {error}"}})
            return
        if req_id is not None:
            self.send({"jsonrpc": "2.0", "id": req_id, "result": result})


CARD_DESCRIPTION = (
    "Show the user ONE decision as a card with 2-4 options and wait for the answer. While game mode is on this is the "
    "only way to ask the user anything: never a list of questions or options in your own text. Returns the chosen "
    "label, or the user's own words (isOther), or dismissed. Keep fields short: title ≤ 8 words, short ≤ 20 words, each "
    "option effect ≤ 14 words, explain ≤ 80 words (hidden until the user opens it), remaining ≤ 12 words. Put the "
    "recommended option first and name it in `recommended`. List the card's sources with a role: \"in\" = a file whose "
    "facts drive the decision, \"out\" = a file the answer will change, \"both\" = both; for an \"in\" source \"used\" only "
    "when you read the file in this session, \"maybe\" otherwise; for an \"out\" source \"used\" means it will change, "
    "\"maybe\" that it might; a path that does not exist yet is a new file. The answer is recorded in the project's "
    "decisions file for you. A first card that names its `pack` and a world not in the record opens that world; after a "
    "world is applied, a decision that belongs to one of its stages names that world and level; any other names world 0 "
    "and level \"0-1\": the side quests. An info card gets a second option \"Stop\" by itself. When the result holds a "
    "text card instead of an answer, show that text to the user as your whole message and wait; record their reply "
    "with the `answer` tool."
)

SOURCE_SCHEMA = {"type": "array", "maxItems": CAPS["sources"], "items": {"type": "object", "required": ["path"], "properties": {
    "path": {"type": "string", "description": "Project-relative path, ~/... or absolute"},
    "name": {"type": "string", "maxLength": CAPS["name"]},
    "role": {"type": "string", "enum": ["in", "out", "both"]},
    "use": {"type": "string", "enum": ["used", "maybe"]},
    "why": {"type": "string", "maxLength": CAPS["why"]}}}}

TOOLS = [
    {"name": "card", "description": CARD_DESCRIPTION, "inputSchema": {
        "type": "object", "required": ["world", "level", "id", "title", "short", "options"], "properties": {
            "kind": {"type": "string", "enum": ["decision", "info", "boss"], "description": "decision (default); info = fixed facts, one option \"OK\"; boss = the level review"},
            "world": {"type": "integer", "minimum": 0},
            "pack": {"type": "string", "pattern": "^[a-z0-9-]{2,60}$", "description": "The pack this world runs; names the plan when the first card starts a new world"},
            "mark": {"type": "string", "enum": ["bug", "feature", "problem", "check"], "description": "Set when the card was raised by something discovered or added, not by the pack: it lands on the map"},
            "level": {"type": "string", "pattern": "^[0-9]+-[0-9]+[ab]?$"},
            "levelTitle": {"type": "string", "maxLength": CAPS["levelTitle"]},
            "index": {"type": "integer", "minimum": 1}, "count": {"type": "integer", "minimum": 1},
            "id": {"type": "string", "pattern": "^[a-z0-9-]{2,40}$"},
            "title": {"type": "string", "maxLength": CAPS["title"]},
            "short": {"type": "string", "maxLength": CAPS["short"], "description": "One line: what is decided and why now"},
            "explain": {"type": "string", "maxLength": CAPS["explain"]},
            "options": {"type": "array", "minItems": 1, "maxItems": CAPS["options"], "items": {"type": "object", "required": ["label"], "properties": {
                "label": {"type": "string", "maxLength": CAPS["label"]},
                "effect": {"type": "string", "maxLength": CAPS["effect"]},
                "picture": {"type": "string", "maxLength": 4000, "description": "An SVG drawing of the option, only when the choice is visual"}}}},
            "recommended": {"type": "string"},
            "remaining": {"type": "string", "maxLength": CAPS["remaining"]},
            "note": {"type": "string", "maxLength": CAPS["note"], "description": "Your answer to the user's last question, when re-presenting a card"},
            "sources": SOURCE_SCHEMA}}},
    {"name": "answer", "description": "Record the user's reply to the text card the last `card` call returned: their words, a digit or an option's label. "
                                      "\"explain\" or \"?\" returns the card with its explanation, to show again; \"skip\" keeps the card as skipped.",
     "inputSchema": {"type": "object", "required": ["answer"], "properties": {
         "level": {"type": "string"}, "id": {"type": "string"}, "answer": {"type": "string", "maxLength": 2000}}}},
    {"name": "note", "description": "Record a decision the user took in the chat rather than on a card: a change of plan, a preference, a correction, "
                                    "a yes or no to a proposal. Call it at once, in the same turn. Give a short title, the decision in the user's words, "
                                    "why, and the level it belongs to (the current level when left out). It counts toward no level's cards; the board "
                                    "shows it beside them.",
     "inputSchema": {"type": "object", "required": ["title", "decision"], "properties": {
         "title": {"type": "string", "maxLength": 60}, "decision": {"type": "string", "maxLength": 240},
         "why": {"type": "string", "maxLength": 240}, "level": {"type": "string", "pattern": "^[0-9]+-[0-9]+[ab]?$"},
         "mark": {"type": "string", "enum": ["bug", "feature", "problem", "check"]}, "sources": SOURCE_SCHEMA}}},
    {"name": "event", "description": "Drop something on the world map, or mark it done. Kinds: bug (or risk), feature, problem, check, jump (give \"to\"), "
                                     "save (a checkpoint: a git commit of the whole tree). Give a short title and one line of text; the level defaults to the "
                                     "current one. To mark one done, pass its id and status \"done\".",
     "inputSchema": {"type": "object", "required": ["kind", "title"], "properties": {
         "id": {"type": "string"}, "kind": {"type": "string", "enum": ["bug", "feature", "problem", "check", "jump", "save", "enemy", "powerup", "challenge", "pipe", "checkpoint"]},
         "title": {"type": "string", "maxLength": 60}, "text": {"type": "string", "maxLength": 240},
         "world": {"type": "integer", "minimum": 0}, "level": {"type": "string", "pattern": "^[0-9]+-[0-9]+[ab]?$"},
         "status": {"type": "string", "enum": ["open", "done"]}, "size": {"type": "integer", "minimum": 1, "maximum": 5},
         "to": {"type": "object", "properties": {"world": {"type": "integer", "minimum": 1}, "level": {"type": "string"}}}}}},
    {"name": "done", "description": "Finish the current world after the boss card was applied: marks the run finished, saves a checkpoint, and returns one "
                                    "summary line per level for you to append where the pack says (nowhere when it says nothing). With no boss card answered "
                                    "on the last level the tool asks you to check with the user first; call it again with confirm: true when they agree.",
     "inputSchema": {"type": "object", "properties": {"world": {"type": "integer", "minimum": 1}, "confirm": {"type": "boolean"}}}},
    {"name": "board", "description": "Start the Siui board's server for this project and open its page in the browser: the roadmap of worlds, the maps, every "
                                     "step with its decisions and files; cards are answered there while the page is open. Returns the page's address.",
     "inputSchema": {"type": "object", "properties": {"open": {"type": "boolean", "description": "false: the address only, no browser"}}}},
    {"name": "status", "description": "The world map as text: the levels of the current world, done, current and ahead, every answer so far, and the next "
                                      "card to present. Call it to resume a run.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class Siui:
    def __init__(self, root, rpc_factory):
        self.root = root.rstrip("/") or "/"
        self.rpc = rpc_factory(self)
        self.config = read_config(self.root)
        self.paths = board_paths(self.root)
        self.pending = None  # the text card waiting for `answer`
        self.progress = None  # {world, level}
        self.lock = threading.Lock()  # one record edit at a time within this process
        self.beating = False

    # --- the protocol
    def dispatch(self, method, params):
        if method == "initialize":
            self.rpc.client = params.get("capabilities") or {}
            self.start_heartbeat()
            return {"protocolVersion": params.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {}},
                    "serverInfo": {"name": "siui", "version": "1.0.0"},
                    "instructions": "GAME MODE: the user has eye strain and wants decisions, not prose. Ask everything through the "
                                    "`card` tool, one decision per call, and write nothing between cards. The decision-cards skill "
                                    "holds the rules; `status` resumes a run; `board` opens the board."}
        if method in ("notifications/initialized", "notifications/cancelled", "notifications/progress"):
            return None
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self.call(params.get("name"), params.get("arguments") or {})
        raise KeyError(method)

    def call(self, name, args):
        handler = {"card": self.tool_card, "answer": self.tool_answer, "note": self.tool_note, "event": self.tool_event,
                   "done": self.tool_done, "board": self.tool_board, "status": self.tool_status}.get(name)
        if handler is None:
            return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
        if not isinstance(args, dict):
            args = {}
        self.config = read_config(self.root)
        try:
            result, notes = handler(args)
        except ValueError as error:
            return {"content": [{"type": "text", "text": str(error)}], "isError": True}
        text = json.dumps(result, ensure_ascii=False)
        if notes:
            text += "\n\n" + " ".join(notes)
        return {"content": [{"type": "text", "text": text}], "structuredContent": result}

    def start_heartbeat(self):
        """Keeps the board's heartbeat fresh while this server lives, so the page shows the chat alive and the
        board's server stays up; it stops by itself when this one exits."""
        if self.beating:
            return
        self.beating = True

        def beat():
            while True:
                if os.path.isdir(self.paths["run"]):
                    heartbeat(self.paths)
                time.sleep(30)
        threading.Thread(target=beat, daemon=True).start()

    # --- the card
    def tool_card(self, args):
        card = normalise_card(args, self.config["caps"])
        if isinstance(card, str):
            raise ValueError(f"card: {card}")
        resolve_sources(card, self.root)
        labels = [option["label"] for option in card["options"]]
        if ensure_run_folder(self.paths):
            heartbeat(self.paths)
        answer = None
        # The board answers while its page is open (and the page's switch does not keep cards in the chat).
        if is_board_live(self.paths) and not is_chat_first(self.paths):
            publish_card(self.paths, card)
            write_status(self.paths, "waiting", card["title"])
            answer = self.wait_on_board(card["id"])
            if answer is None:
                publish_card(self.paths, None)
        # Else an elicitation form, when the client draws one.
        if answer is None and isinstance(self.rpc.client.get("elicitation"), dict):
            publish_card(self.paths, card)
            write_status(self.paths, "waiting", card["title"])
            answer = self.elicit(card, labels)
            publish_card(self.paths, None)
        # Else the text card: the chat shows it, and `answer` brings the reply.
        if answer is None:
            self.pending = card
            publish_card(self.paths, card)
            write_status(self.paths, "waiting", card["title"])
            return ({"id": card["id"], "level": card["level"], "card": text_card(card), "awaiting": "answer"},
                    ["No board page and no form: show the text in `card` to the user as your whole message, with nothing "
                     "else, and stop. When they reply, call `answer` with their words."])
        if answer == DISMISSED:
            return self.dismissed(card)
        return self.settle(card, answer, labels)

    def wait_on_board(self, card_id):
        """Polls the board's inbox for the answer to the card; None when the page goes away or the wait runs out."""
        deadline = time.time() + WAIT_SECONDS
        last_beat = 0
        while time.time() < deadline:
            if time.time() - last_beat > 20:
                heartbeat(self.paths)
                last_beat = time.time()
            found = read_json(self.paths["inbox"], None)
            if isinstance(found, dict):
                if found.get("id") == card_id and (str(found.get("answer") or "").strip() or found.get("dismiss")):
                    try:
                        os.remove(self.paths["inbox"])
                    except OSError:
                        pass
                    return DISMISSED if found.get("dismiss") else str(found["answer"]).strip()
                try:
                    os.remove(self.paths["inbox"])  # an answer to another card is stale
                except OSError:
                    pass
            if not is_board_live(self.paths):
                return None
            time.sleep(0.1)
        return None

    def elicit(self, card, labels):
        """Asks through the client's form: the options as a choice, a field for the user's own words."""
        choices = labels + ["Other"]
        names = [f"{o['label']} ★" if o["label"] == card.get("recommended") else o["label"] for o in card["options"]] + ["Other: my own words"]
        message = text_card(card).rsplit("\n", 1)[0]
        schema = {"type": "object", "required": ["answer"], "properties": {
            "answer": {"type": "string", "title": "Your answer", "enum": choices, "enumNames": names},
            "words": {"type": "string", "title": "Your own words (with Other), or \"explain\"", "maxLength": 2000}}}
        for _ in range(3):
            reply = self.rpc.request("elicitation/create", {"message": message, "requestedSchema": schema}, WAIT_SECONDS)
            if not reply or "result" not in reply:
                return None
            result = reply["result"] or {}
            if result.get("action") != "accept":
                return DISMISSED
            content = result.get("content") or {}
            picked = str(content.get("answer") or "").strip()
            words = str(content.get("words") or "").strip()
            if words.lower() in EXPLAIN_WORDS and card.get("explain"):
                message = text_card(card, with_explain=True).rsplit("\n", 1)[0]
                continue
            if picked == "Other" or picked not in labels:
                return words or picked or None
            return picked
        return None

    def tool_answer(self, args):
        card = self.pending
        if card is None:
            raise ValueError("answer: no text card is waiting; present one with `card` first")
        given = str(args.get("answer") or "").strip()
        if not given:
            raise ValueError("answer: the answer is required")
        if args.get("id") and args.get("id") != card["id"]:
            raise ValueError(f"answer: the card waiting is {card['level']}/{card['id']}, not {args.get('id')}")
        labels = [option["label"] for option in card["options"]]
        if given.lower() in EXPLAIN_WORDS and card.get("explain"):
            return ({"id": card["id"], "level": card["level"], "card": text_card(card, with_explain=True), "awaiting": "answer"},
                    ["Show the card again with its explanation, as your whole message, and wait for the answer."])
        self.pending = None
        publish_card(self.paths, None)
        if given.lower() in ("skip", "dismiss", "dismissed", "later"):
            return self.dismissed(card)
        if given.isdigit() and 1 <= int(given) <= len(labels):
            given = labels[int(given) - 1]
        else:
            match = next((label for label in labels if label.lower() == given.lower()), None)
            given = match or given
        return self.settle(card, given, labels)

    def dismissed(self, card):
        """A dismissed card is kept as skipped: counted nowhere, presented again when the run goes on."""
        write_status(self.paths, "idle")
        if card["kind"] == "decision":
            with self.lock:
                record = read_record(self.root, self.config["record"])
                at = now_iso()
                if not self.opens_world(record, card):
                    run, level, level_title = route_decision(record, target_of(self.root), card["world"], card["level"], at)
                    had = next((one for one in run["decisions"] if one["level"] == level and one["id"] == card["id"]), None)
                    if not had or had.get("via") == "skipped":
                        add_decision(run, {"level": level, "id": card["id"], "title": card["title"], "answer": "skipped",
                                           "isOther": False, "at": at, "sources": self.source_list(card), "via": "skipped"},
                                     level_title or card.get("levelTitle"), None if level_title else card.get("count"))
                        write_record(self.root, self.config["record"], record)
        return ({"id": card["id"], "level": card["level"], "dismissed": True},
                ["The user dismissed the card; it is kept as skipped and comes again later. End the turn with one short line and wait."])

    @staticmethod
    def opens_world(record, card):
        return bool(card.get("pack")) and card["world"] > 0 and not has_world(record, card["world"])

    @staticmethod
    def source_list(card):
        return [{"path": s["path"], "role": s["role"], "use": s["use"]} for s in card["sources"] + card.get("extraSources", [])]

    def settle(self, card, answer, labels):
        """Records the answer as the hook does and tells the model to go on."""
        write_status(self.paths, "working", "thinking")
        is_other = answer not in labels
        at = now_iso()
        decision = {"level": card["level"], "id": card["id"], "title": card["title"], "answer": answer, "isOther": is_other,
                    "at": at, "sources": self.source_list(card)}
        if card["kind"] == "decision":
            with self.lock:
                record = read_record(self.root, self.config["record"])
                target = target_of(self.root)
                if self.opens_world(record, card):
                    run, level, level_title = ensure_run(record, target, card.get("pack") or "ad-hoc", card["world"], at), card["level"], None
                    if card.get("pack") and run.get("plan") is None:
                        plan = read_plan(card["pack"], self.root, self.config["packs"])
                        if plan:
                            run["plan"] = plan
                else:
                    run, level, level_title = route_decision(record, target, card["world"], card["level"], at)
                decision["level"] = level
                if card.get("mark"):
                    kind = kind_of(card["mark"]) or "challenge"
                    put_event(record, {"id": f"{kind}-{card['id']}-{time_suffix(at)}", "kind": kind, "title": card["title"],
                                       "text": f"Answer: {answer}", "world": run["world"], "level": level, "at": at, "status": "open"})
                add_decision(run, decision, level_title or card.get("levelTitle"), None if level_title else card.get("count"))
                write_record(self.root, self.config["record"], record)
                self.progress = {"world": run["world"], "level": level}
        elif card["kind"] == "boss":
            with self.lock:
                record = read_record(self.root, self.config["record"])
                run = open_run(record)
                if run:
                    run["levels"].setdefault(card["level"], "open")
                    if card.get("levelTitle"):
                        run["levelTitles"] = {**run.get("levelTitles", {}), card["level"]: card["levelTitle"]}
                    write_record(self.root, self.config["record"], record)
        own = " (the user's own words)" if is_other else ""
        notes = [f"Answer to {card['level']}/{card['id']}: \"{answer}\"{own}.",
                 "Present the next card now, with no text before it."]
        return ({"id": card["id"], "level": decision["level"], "answer": answer, "isOther": is_other, "sources": decision["sources"]}, notes)

    # --- the rest of the record
    def tool_note(self, args):
        title = cut(args.get("title"), 60)
        answer = cut(args.get("decision"), 240)
        if not title or not answer:
            raise ValueError("note: title and decision are required")
        with self.lock:
            record = read_record(self.root, self.config["record"])
            now = now_iso()
            opened = open_run(record)
            given = args.get("level").strip() if is_level(args.get("level")) else ""
            wanted = given or ((self.progress or {}).get("level", "") if opened else "")
            world = int(wanted.split("-")[0]) if wanted else (opened or last_world_run(record) or {}).get("world", 1)
            run, level, level_title = route_decision(record, target_of(self.root), world, wanted, now)
            level = level or f"{run['world']}-0"
            sources = []
            for one in (args.get("sources") or [])[:6]:
                if isinstance(one, dict) and isinstance(one.get("path"), str) and one["path"].strip():
                    sources.append({"path": one["path"].strip(), "role": one.get("role") if one.get("role") in ("out", "both") else "in",
                                    "use": "used" if one.get("use") == "used" else "maybe"})
            decision = {"level": level, "id": slug_of(title), "title": title, "answer": answer, "isOther": False, "at": now,
                        "sources": sources, "via": "chat"}
            why = cut(args.get("why"), 240)
            if why:
                decision["why"] = why
            add_decision(run, decision, level_title)
            kind = kind_of(args.get("mark"))
            if kind:
                put_event(record, {"id": f"{kind}-{decision['id']}-{time_suffix(now)}", "kind": kind, "title": title, "text": answer,
                                   "world": run["world"], "level": level, "at": now, "status": "open"})
            write_record(self.root, self.config["record"], record)
        result = {"recorded": True, "level": level, "id": decision["id"]}
        if kind:
            result["onTheMap"] = kind
        return result, ["Recorded as a chat decision. Go on; no text about the record is needed."]

    def tool_event(self, args):
        kind = kind_of(args.get("kind"))
        title = cut(args.get("title"), 60)
        if not kind or not title:
            raise ValueError("event: kind (bug, feature, problem, check, jump, save) and title are required")
        with self.lock:
            record = read_record(self.root, self.config["record"])
            run = open_run(record) or last_world_run(record)
            given = args.get("level").strip() if is_level(args.get("level")) else ""
            now = now_iso()
            where = self.progress or {}
            world_given = args.get("world") if isinstance(args.get("world"), int) and not isinstance(args.get("world"), bool) and args.get("world") >= 0 else None
            side = world_given == 0 or given.startswith("0-") or (world_given is None and given == "" and where.get("world") == 0)
            world = 0 if side else (world_given if world_given is not None else (run or {}).get("world") or where.get("world") or 1)
            levels = list(run["levels"]) if run else []
            level = month_level(now) if side else (given or where.get("level") or (levels[-1] if levels else f"{world}-1"))
            key_of = lambda one_id: re.sub(r"-\d{6}$", "", re.sub(r"^(enemy|powerup|challenge|check|pipe|checkpoint)-", "", one_id))
            wanted = str(args.get("id") or "").strip()
            existing = None
            if wanted:
                existing = next((one for one in record["events"] if one.get("id") == wanted), None)
                if existing is None:
                    candidates = sorted(reversed(record["events"]), key=lambda one: 0 if one.get("status") == "open" else 1)
                    existing = next((one for one in candidates if key_of(one.get("id", "")) == key_of(wanted)), None)
            status = "done" if args.get("status") == "done" else (existing or {}).get("status", "open")
            event = {"id": (existing or {}).get("id") or f"{kind}-{slug_of(title)}-{time_suffix(now)}", "kind": kind, "title": title,
                     "world": (existing or {}).get("world", world), "level": (existing or {}).get("level", level),
                     "at": (existing or {}).get("at", now), "status": status}
            if status == "done":
                event["doneAt"] = (existing or {}).get("doneAt") or now
            text = cut(args.get("text"), 240) or (existing or {}).get("text")
            if text:
                event["text"] = text
            size = args.get("size")
            size = min(5, max(1, size)) if isinstance(size, int) and not isinstance(size, bool) else (existing or {}).get("size")
            if size:
                event["size"] = size
            to = args.get("to") if isinstance(args.get("to"), dict) else None
            if to and isinstance(to.get("world"), int) and to["world"] >= 1:
                event["to"] = {"world": to["world"], **({"level": to["level"]} if is_level(to.get("level")) else {})}
            elif (existing or {}).get("to"):
                event["to"] = existing["to"]
            if kind == "checkpoint" and not existing:
                saved = save_checkpoint(self.root, title)
                if "error" in saved:
                    return {"recorded": False, "error": saved["error"]}, []
                event["commit"], event["branch"] = saved["commit"], saved["branch"]
            elif (existing or {}).get("commit"):
                event["commit"], event["branch"] = existing["commit"], existing.get("branch", "HEAD")
            put_event(record, event)
            write_record(self.root, self.config["record"], record)
        return ({"recorded": True, "id": event["id"], "world": event["world"], "level": event["level"], "status": status},
                ["Dropped on the map. Go on; no text about it is needed."])

    def tool_done(self, args):
        with self.lock:
            record = read_record(self.root, self.config["record"])
            run = open_run(record)
            if not run:
                return {"lines": [], "file": self.config["record"], "error": "no open run"}, []
            if args.get("confirm") is not True and not has_castle(run):
                return ({"closed": False, "askFirst": True, "file": self.config["record"]},
                        [f"World {run['world']} has no castle: no boss card was answered on its last level. Ask the user politely with one card",
                         "whether to close the world without a castle (options \"Close anyway\" and \"The castle first\"). On \"Close anyway\",",
                         "call done again with confirm: true; otherwise present the boss card."])
            fork = next((one for one in (run.get("roads") or {}).values() if one.get("merged") is None), None)
            if fork:
                return ({"lines": [], "file": self.config["record"], "error": f"the stage {fork['level']} is forked; merge it on the board first (the castle's buttons)"}, [])
            run["finishedAt"] = today()
            for level in list(run["levels"]):
                run["levels"][level] = "done"
            for level in run.get("plan") or []:
                run["levels"][level["level"]] = "done"
            write_record(self.root, self.config["record"], record)
            self.progress = None
            saved = save_checkpoint(self.root, f"World {run['world']} applied")
            if "error" not in saved:
                plan_levels = [one["level"] for one in run.get("plan") or []]
                boss_level = plan_levels[-1] if plan_levels else (list(run["levels"])[-1] if run["levels"] else f"{run['world']}-4")
                put_event(record, {"id": f"checkpoint-world-{run['world']}-applied", "kind": "checkpoint", "title": f"World {run['world']} applied",
                                   "world": run["world"], "level": boss_level, "at": now_iso(), "status": "open",
                                   "commit": saved["commit"], "branch": saved["branch"]})
                write_record(self.root, self.config["record"], record)
        write_status(self.paths, "idle")
        return ({"lines": summary_lines(run, today(), self.config["record"]), "file": self.config["record"]},
                ["Append the lines where the pack says, or nowhere when it says nothing. Write no other file."])

    def tool_board(self, args):
        port = ensure_server(self.root, self.paths, self.config["record"], self.config["boardPort"], self.config["chatLog"])
        if port is None:
            return {"opened": False, "error": f"the board server did not start; see {self.paths['run']}/server.log"}, []
        url = f"http://127.0.0.1:{port}/"
        opened = open_browser(url) if args.get("open") is not False and not os.environ.get("SIUI_NO_BROWSER") else False
        return ({"url": url, "opened": opened},
                [f"The board is at {url}. Tell the user in one line; cards are answered there while the page is open."])

    def tool_status(self, args):
        record = read_record(self.root, self.config["record"])
        run = open_run(record)
        lines = [status_text(record)]
        if run:
            lines.append("")
            lines += [f"{one['level']}/{one['id']} ({one['title']}): {one['answer']}" for one in run["decisions"]]
        return {"status": "\n".join(lines)}, ["Go on from the next card named, with no text before it."]


def main():
    parser = argparse.ArgumentParser(description="Siui's MCP server for GitHub Copilot, over stdio")
    parser.add_argument("--root", default=os.environ.get("SIUI_ROOT") or os.getcwd(), help="the project (default: the working directory)")
    args = parser.parse_args()
    root = os.path.abspath(args.root)
    siui = Siui(root, Rpc)
    siui.rpc.serve()


if __name__ == "__main__":
    main()
