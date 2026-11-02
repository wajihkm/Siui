---
name: siui-on
description: "Siui: start a world from a pack (/siui-on scaffold), or turn the next task into decision cards (/siui-on alone)"
disable-model-invocation: true
---

Game mode is on: the user has eye strain and wants decisions, not prose. The decision-cards
skill holds the rules; they apply. Ask everything through the Siui `card` tool, one decision
per call, and write nothing between cards.

The words after the command name the pack. With a pack: read it (the project's
`.claude/skills/decision-cards/packs/<pack>.md`, else the Siui plugin's `packs/<pack>.md`)
and the inputs its first level lists, then present its fixed-facts card and the first card
of its first level, with no text before them. Without one: turn the task the user describes
next into levels of 3-4 decisions each, a boss level last, and present the first card.

When nothing is left to present (the world is done, a card was dismissed) and the board's
page is open, call the Siui `listen` tool and wait for the user's next move there; when it
says the page is closed, end the turn and wait in the chat.
