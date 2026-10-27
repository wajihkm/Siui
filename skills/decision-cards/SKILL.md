---
name: decision-cards
description: Run work as one decision at a time, as a short card with 2-4 options, grouped in levels and worlds like a game, recorded in .claude/decisions.json. Use when the user says game mode, step by step, decision cards, levels or worlds, or wants to scaffold or re-plan a project without reading long text. Keywords: game mode, decision card, level, world, boss, pack, scaffold, step by step.
---

# Decision cards

The user has eye strain. They want decisions, not prose: one short card at a time, with
2-4 options, and nothing to read between cards. A world is a set of levels; a level is
3-4 decisions; the last level of a world is the boss, where everything decided is reviewed
and applied. Nothing is generated before the boss.

## The rules

1. Ask everything through your card mechanism if you have one, else print the text card
   below. One decision per card. Never a list of questions, never options in prose.
2. Write nothing between cards: no preamble, recap, headings or bullet lists. At most one
   short sentence per turn, only to report an error.
3. Caps: title ≤ 8 words, short ≤ 20 words, each option effect ≤ 14 words, explain ≤ 80
   words, remaining ≤ 12 words, 2-4 options with labels ≤ 4 words. The recommended option
   comes first and is marked.
   When a choice is visual (a layout, a shape, a colour, a place on a map), each option may
   carry a small drawing, an SVG under 4000 characters with a viewBox and nothing that runs;
   a card mechanism shows it beside the option, a text card names it.
4. Follow the pack's levels in order, all cards of a level before the next. Every card
   names its world, level, level title, index and count. After a world is applied, a
   decision that belongs to one of its stages names that world and stage; any other names
   world 0 and level 0-1: the side quests, kept by month and drawn apart on the roadmap.
5. A pack's fixed facts are not decisions: show them once as an info card with the single
   option "OK".
6. Boss level: one card listing every decision of the world, one line per level, with the
   options "Apply", "Change one" and "Stop". On Apply, make the edits with no commentary,
   then write one summary line per level where the pack says (nowhere when it says
   nothing). On "Change one", ask which, then present that decision again.
7. When the user's answer is their own text ending in "?", answer it in the next card's
   note (≤ 40 words) and present the same card again.
8. When the user dismisses a card, end the turn with one short line and wait.
9. Never create a file to explain, plan or summarise. The record is `.claude/decisions.json`.
10. Every card lists its sources in two directions. Inputs drive the decision: files whose
    facts the card relies on. Outputs will change because of the answer. An input is
    "used" only when you read it in this session, "maybe" otherwise; an output is "used"
    when it will change, "maybe" when it might, and a path that does not exist yet is a
    new file. Read a level's inputs before its first card.
11. When the user decides something in the chat rather than on a card (a change of plan,
    a preference, a correction, a yes to a proposal), record it at once: the title, the
    decision in their words, why, and the level it belongs to. In the record it carries
    `"via": "chat"` and counts toward no level's cards.
12. The map records what pops up while building, on the stage where it appeared: when
    you discover something and ask the user about it, when the user adds a requirement
    or a check, when a bug, a risk or a hard problem appears, or when the work jumps
    elsewhere. In plain words: a **bug or risk**, a **feature**, a **problem**, a
    **check**, a **jump**; in the game: an enemy, a power-up, a challenge, a coin, a warp
    pipe. A card or a note that carries one of these says so (`mark`) and it lands by
    itself; mark it done when it is fixed, built, cleared, passed or taken. In the record
    these are `events`.
13. Before a change that is hard to undo, and after a boss is applied, save a
    **checkpoint**: a commit of the whole tree, recorded on the stage as a save point the
    user can return to. Returning keeps what is there now under a git tag first.
14. A stage may **fork**: when two answers both deserve a try, a card offers "Fork here";
    the stage splits into roads a and b, each a git branch from a checkpoint, and the
    remaining cards are asked on the road on disk as level `<level>a` or `<level>b`. A
    forked world's boss lists both roads and offers "Merge a", "Merge b" and "Keep both"
    beside Apply; the merge is a merge commit into the base and the other road is tagged,
    kept grey on the maps and readable.

## The roadmap

Worlds sit on a roadmap. The road from one world to the next is solid when the first
was finished and the next started straight after, dashed when the first was abandoned
or still open, and dotted toward the predicted next world, the first pack not run yet.
The boss stage is a castle; a finished world flies a flag.

## The text card

Print this when you have no card mechanism. The user answers with a digit or their own
words; "explain" shows the hidden explanation.

```
[1-1 · 2/4] License
One line: what is decided and why now.
Explain: say "explain" to see it.
Consequences:
  1 MIT — anyone may use it; no patent clause
  2 Apache-2.0 — adds a patent grant; longer file
Remaining in 1-1: versioning, purpose line
In: ━ README.md · ┄ packs/demo-1-scaffold.md  |  Out: ━ LICENSE (new) · ┄ README.md
Answer 1-2, or type your own.
```

`━` means sure: an input read and used, an output that will change. `┄` means it may
apply: an input not read, an output that might change. With a graphical card mechanism
the same facts draw as a graph, top to bottom: the inputs in a row, the decision as a
cloud, the outputs in a row, with solid or dashed edges.

## The record

`.claude/decisions.json` in the project, one file for every run:

```json
{ "format": 1, "runs": [ { "id": "<project>/world-1", "target": "<project>",
  "pack": "demo-1-scaffold", "world": 1, "startedAt": "2026-10-21", "finishedAt": null,
  "levels": { "1-1": "done", "1-2": "open" },
  "decisions": [ { "level": "1-1", "id": "license", "title": "License", "answer": "MIT",
    "isOther": false, "at": "2026-10-21T12:00:00Z",
    "sources": [ { "path": "README.md", "role": "in", "use": "used" },
                 { "path": "LICENSE", "role": "out", "use": "used" } ] } ] } ],
  "events": [] }
```

A card mechanism writes it for you. Without one, write it yourself after each answer: a
re-answer of the same level and id replaces the entry. The summary line per level has the
form `- <date> [decision] World <n> level <level>: <id>=<answer>; … Record: .claude/decisions.json`.

## Packs

A pack is one markdown file under `packs/`: a world, its fixed facts, its levels and each
level's cards and sources; the format and the table of the packs are in
[packs/README.md](packs/README.md).

## In words

"game on <pack>" starts a world. "status" shows the map and the answers so far. "back"
takes the last decision back. "off" leaves the mode. A card mechanism maps these to its
own commands.
