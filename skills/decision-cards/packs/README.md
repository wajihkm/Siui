# Packs

A pack is one markdown file here: a world of levels, each level a few decisions. The
assistant reads the pack at `game on <pack>` and turns each row into a card, writing the
short line, the effects and the explanation from what it reads in the project. The pack
gives the skeleton, not the words.

## Format

```
# World 1: a new project            the world's title; one line on who it is for
`changelog:` none                   or a file path: where the summary lines go at the boss

## Fixed facts (one info card, option "OK")
- facts the user must accept once, not decide

## Level 1-1 · Identity (4 cards)   parsed: id, title, card count; drawn on the map
Inputs to read first: ...           read before the level's first card: solid links
Inputs that may apply: ...          listed dashed until read
Outputs: ...                        the files the level's answers will change

| id | title | options (recommended first) |
|---|---|---|
| `name` | Project name | the folder's name · a short brand name · a scoped package name |

## Level 1-4 · Boss
One card listing every decision, options "Apply", "Change one", "Stop"; what Apply does.
```

The level headings must read `## Level <n>-<m> · <title> (<k> cards)`; the map and the
status read the levels ahead from them. The last level is the boss.

Two marks, written like `changelog:` in the opening lines, say what kind of pack it is:

- `` `kind:` method ``: a way any world runs, not a piece of work. Its levels are the
  stages of every world started with it, numbered for that world; it is never a planned
  world of its own. Write it for one feature, bug or change at a time, and leave out
  whatever the whole project decides once.
- `` `facts:` project ``: the answers of this pack are the project's facts. They are
  decided once, every later world reads them, and no card asks them again.

## Where packs live

This folder holds the format; the packs themselves are the plugin's `scaffold` in
`siui/packs/`, which sets up a new project, and the ones a project writes: in its `.claude/skills/decision-cards/packs/`, in its `skills/decision-cards/packs/`,
in the folders its `.claude/siui.json` names under `packs`, or in
`~/.claude/skills/decision-cards/packs/`. The number in a pack's name is a suggestion; a run
takes the project's next world number.
