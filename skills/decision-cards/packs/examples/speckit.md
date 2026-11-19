# Spec Kit: a feature through GitHub Spec Kit, asked as cards

Runs one feature through GitHub Spec Kit's own skills, with every question and review gate
as a card. For a project where Spec Kit is installed (`specify init --integration claude`).
A method: every world started with it is one feature. `changelog:` none. `kind:` method.

## Fixed facts (one info card, option "OK")

- Spec Kit does the writing: each stage runs one of its skills (`speckit-specify`,
  `speckit-clarify`, `speckit-plan`, `speckit-tasks`, `speckit-implement`) exactly as the
  skill says, with its scripts and templates. This pack changes only how it talks to you.
- Wherever a skill tells you to print a question, a table of options or a batch of
  questions and wait, ask through the card tool instead: one question per card, the
  skill's options as the card's options, its recommendation first, its "why it matters"
  as the short line. Never print the table. A batch ("Q1, Q2, Q3 together") becomes that
  many cards in a row.
- Do not paste a document the skill wrote into the chat. After a skill writes one, the
  stage's review card names it as an output, with three to five lines of what it says in
  the explanation; the file itself is one click away on the card and the board.
- Unlike other packs, documents are written stage by stage, because each Spec Kit skill
  reads the one before. Code is written only at the boss.
- The card counts below are the most a stage can have; a skill that has nothing to ask
  skips its question cards.
- The project's facts stand: give its language, framework and conventions to
  `speckit-plan` as its arguments instead of asking for them. Where the project has no
  facts and `.specify/memory/constitution.md` is still the empty template, say so on this
  card and run `speckit-constitution` from the facts or the files before the first stage.

## Level 1-1 · Specify (5 cards)

Inputs to read first: `.claude/skills/speckit-specify/SKILL.md`,
`.specify/memory/constitution.md`, `README.md`, this pack. Inputs that may apply:
`.specify/templates/spec-template.md`. Outputs: `specs/<feature>/spec.md` (new), a git
branch for the feature when the skill makes one.

Ask `feature` first, then run speckit-specify with the answer as its arguments.

| id | title | options (recommended first) |
|---|---|---|
| `feature` | What to build | the user types it under Other · the idea you read in the README · a narrower first version of it |
| `need-1` | The first point the spec could not settle | the skill's options for its first NEEDS CLARIFICATION marker |
| `need-2` | The second point the spec could not settle | the skill's options for its second marker |
| `need-3` | The third point the spec could not settle | the skill's options for its third marker |
| `review-spec` | Review the specification | approve it · change one thing, typed under Other · reject and stop |

## Level 1-2 · Clarify (5 cards)

Inputs to read first: `.claude/skills/speckit-clarify/SKILL.md`, the spec just written.
Inputs that may apply: `.specify/memory/constitution.md`. Outputs: `specs/<feature>/spec.md`.

Run speckit-clarify. Each of its questions, at most five, is one card, in its order, and
each answer is written into the spec as the skill says before the next card.

| id | title | options (recommended first) |
|---|---|---|
| `clarify-1` | The skill's first question | its recommended option · its other options |
| `clarify-2` | The skill's second question | its recommended option · its other options |
| `clarify-3` | The skill's third question | its recommended option · its other options |
| `clarify-4` | The skill's fourth question | its recommended option · its other options |
| `clarify-5` | The skill's fifth question | its recommended option · its other options |

## Level 1-3 · Plan (2 cards)

Inputs to read first: `.claude/skills/speckit-plan/SKILL.md`, the spec. Inputs that may
apply: the project's manifest and layout, `.specify/templates/plan-template.md`. Outputs:
`specs/<feature>/plan.md` (new) and the design files the skill adds beside it.

Run speckit-plan with the project's facts as its arguments; ask `stack` only when the
project has no facts and the files do not show one.

| id | title | options (recommended first) |
|---|---|---|
| `stack` | The technology to plan with | what the project already uses, as you read it · the simplest stack that fits the spec · the user types it |
| `review-plan` | Review the plan | approve it · change one thing, typed under Other · reject and stop |

## Level 1-4 · Tasks (2 cards)

Inputs to read first: `.claude/skills/speckit-tasks/SKILL.md`, the plan. Inputs that may
apply: `.claude/skills/speckit-analyze/SKILL.md`. Outputs: `specs/<feature>/tasks.md` (new).

Run speckit-tasks, then ask `review-tasks`; on "analyze first", run speckit-analyze and
put its findings, most serious first, in the explanation of the same card asked again.

| id | title | options (recommended first) |
|---|---|---|
| `review-tasks` | Review the tasks | approve them · analyze first: check spec, plan and tasks against each other · change one thing, typed under Other |
| `build-how` | How to build | everything in one go at the boss · the first user story only · stop here: the documents are the result |

## Level 1-5 · Boss

One card: every answer of the world, one line per level, and the documents written;
options "Apply", "Change one", "Stop". On Apply: run speckit-implement as `build-how`
said, with no commentary, dropping a bug, a problem or a save point on the map as they
come; then finish the world.
