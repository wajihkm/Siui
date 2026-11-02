---
description: "Siui: start a world from a pack, or turn the next task into decision cards"
---
Game mode is on: the user has eye strain and wants decisions, not prose. Load the decision-cards skill; its rules apply. Ask everything through the Siui `card` tool, one decision per call, and write nothing between cards.

Pack: ${input:pack:the pack's name, for example scaffold; leave empty to turn the next task into levels}

With a pack: read it (the project's `.claude/skills/decision-cards/packs/<pack>.md`, else the plugin's `packs/<pack>.md`) and the inputs its first level lists, then present its fixed-facts card and the first card of its first level, with no text before them. Without one: turn the task the user describes next into levels of 3-4 decisions each, a boss level last, and present the first card.
