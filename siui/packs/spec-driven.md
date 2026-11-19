# Spec-driven: a feature specified, then built

Takes one feature from an idea to a specification, a plan, a task list and the code. A
method, not a piece of work: every world started with it runs the same four stages and a
boss.
`changelog:` none. `kind:` method.

## Fixed facts (one info card, option "OK")

- One feature per world. The world carries the feature's title; this method only says how
  it runs.
- The project's facts stand: its language, framework, layout, tests and conventions were
  decided in the setup world and are not asked here. Where the project has no facts yet,
  say so on this card and plan with what the files show.
- Nothing is written before the boss. The boss writes three short documents in
  `specs/<feature-slug>/`, `spec.md` (what and why), `plan.md` (how), `tasks.md` (the
  steps), then builds the tasks: lists over prose, no section the cards did not decide.
- The cards never ask what the files can answer: read the project first, and put what you
  found in each card's short line.

## Level 1-1 · Specify (3 cards)

Inputs to read first: `README.md`, the project facts, any file the user names, this pack.
Inputs that may apply: existing `specs/*/spec.md`. Outputs: `specs/<feature-slug>/spec.md` (new).

| id | title | options (recommended first) |
|---|---|---|
| `feature` | The feature, in one sentence | the sentence you infer from the world's title and the user's words · a narrower first version of it · the user types it |
| `users` | Who it is for and what they come to do | the main user and their one job · two kinds of user · the user types it |
| `out-of-scope` | What it will not do | the two or three exclusions you propose · nothing excluded yet · the user types them |

## Level 1-2 · Clarify (3 cards)

Inputs to read first: the answers of the stage before. Inputs that may apply: the code the
feature will touch. Outputs: `specs/<feature-slug>/spec.md` (new).

The biggest ambiguities you find in the feature as answered so far, one card each, the
options being its plausible readings with what each would cost; fewer cards when fewer
exist. The last card of the stage asks how success is checked.

| id | title | options (recommended first) |
|---|---|---|
| `ambiguity-1` | The first open question you find | the reading you recommend · the other plausible reading · leave it open and say so in the spec |
| `ambiguity-2` | The second open question you find | the reading you recommend · the other plausible reading · leave it open and say so in the spec |
| `acceptance` | How success is checked | the three checks you propose, each one a user can do · one end-to-end check · the user types them |

## Level 1-3 · Plan (3 cards)

Inputs to read first: the answers so far, the project facts, the project's manifest and
layout. Inputs that may apply: the files the feature will touch. Outputs:
`specs/<feature-slug>/plan.md` (new).

| id | title | options (recommended first) |
|---|---|---|
| `approach` | How it is built | the simplest design that meets the checks · a design ready for the next feature too · the user names one |
| `data` | What it stores and where | nothing kept, or the plainest store that fits · the project's existing store · a new store |
| `where-it-lives` | Where the code goes | beside the code it extends, as the project's layout says · a module of its own · the user names the place |

## Level 1-4 · Tasks (2 cards)

Inputs to read first: the answers of the plan. Inputs that may apply: the test folder.
Outputs: `specs/<feature-slug>/tasks.md` (new).

| id | title | options (recommended first) |
|---|---|---|
| `slicing` | How the work is cut | slices a user can see, each with its test · by layer: data, logic, interface · one task |
| `order` | What comes first | the riskiest slice · the simplest slice · the slice users see first |

## Level 1-5 · Boss

One card: every decision of the world, one line per stage; options "Apply", "Documents
only", "Change one", "Stop". On Apply: write `spec.md`, `plan.md` and `tasks.md` from the
answers, each under a page, the tasks as a numbered checklist in the order chosen; then
build the tasks in that order, ticking each in `tasks.md` as it is done, dropping a bug, a
problem or a save point on the map as they come; then finish the world. On "Documents
only": write the three documents and finish the world; the building is another world.
