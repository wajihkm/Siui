#!/usr/bin/env python3
"""Waits for the board's answer to one card.

The plugin's card hook runs this in place of the chat dialog while the board is
open: a host command in flight costs the hook none of its time budget. Polls the
answer inbox until it holds an answer for the card, prints it as JSON and exits 0.
Exits 4 when the page stops polling (its liveness mark goes stale: the card goes
back to the chat), 3 when the wait runs out (the plugin runs it again), 2 on a
bad argument. With a fourth argument "auto" it is auto-pilot's countdown: it
ends 5 when auto-pilot is switched off, and ignores a dead page.
"""

import json
import os
import sys
import time

STALE_SECONDS = 12
POLL_SECONDS = 0.1


USAGE = "usage: wait.py <run folder> <card id> [seconds] [auto]"


def main():
    if len(sys.argv) < 3:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    run, card_id = sys.argv[1], sys.argv[2]
    try:
        seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 590.0
    except ValueError:
        seconds = -1.0
    if not seconds >= 0:  # a word, or NaN, or a negative number
        print(f"{USAGE}\nseconds must be a number of seconds, not {sys.argv[3]!r}", file=sys.stderr)
        sys.exit(2)
    watching_auto = len(sys.argv) > 4 and sys.argv[4] == "auto"
    inbox = os.path.join(run, "inbox-answer.json")
    alive = os.path.join(run, "alive")
    auto = os.path.join(run, "auto.json")
    deadline = time.time() + seconds

    while time.time() < deadline:
        try:
            with open(inbox, encoding="utf-8") as handle:
                found = json.load(handle)
        except (OSError, ValueError):
            found = None
        if isinstance(found, dict):
            if found.get("id") == card_id and (str(found.get("answer") or "").strip() or found.get("dismiss")):
                try:
                    os.remove(inbox)
                except OSError:
                    pass
                print(json.dumps({"dismissed": True} if found.get("dismiss") else {"answer": str(found["answer"]).strip()}))
                sys.exit(0)
            # an answer to another card is stale: drop it, and say so
            try:
                os.remove(inbox)
                print(f"wait.py: dropped an answer to another card ({found.get('id')!r}) while waiting for {card_id!r}", file=sys.stderr)
            except OSError:
                pass
        if watching_auto:
            # The countdown of auto-pilot: a switch-off ends it (5); a dead page does not, the pick still happens.
            try:
                with open(auto, encoding="utf-8") as handle:
                    if not json.load(handle).get("on"):
                        sys.exit(5)
            except (OSError, ValueError):
                sys.exit(5)
        else:
            try:
                if time.time() - os.path.getmtime(alive) > STALE_SECONDS:
                    sys.exit(4)
            except OSError:
                sys.exit(4)
        time.sleep(POLL_SECONDS)
    sys.exit(3)


if __name__ == "__main__":
    main()
