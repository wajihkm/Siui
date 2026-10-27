# Demo 2: hardening

For a tool that works on the happy path and now meets failure, limits and restarts.
Written for a small tool that works; the questions fit any such tool. `changelog:` none.

## Fixed facts (one info card, option "OK")

- Nothing is changed before the boss level; each card decides a behaviour, the boss
  applies them all.
- A failure must never lose a recorded answer: the record on disk is the truth.
- The user has eye strain: every error shows as one short line, never a stack trace.

## Level 2-1 · Failures (3 cards)

Inputs to read first: the plugin's main module, the board server. Inputs that may apply:
the card hook, the record module. Outputs: the plugin's main module, the board server.

| id | title | options (recommended first) |
|---|---|---|
| `dismissed-card` | A dismissed card | end the turn and wait · present it again once · skip to the next card |
| `board-gone` | The board vanishes mid-card | hand the card to the chat · wait for the board to return · fail the card |
| `bad-record` | The record file is unreadable | keep it aside and start a fresh one · refuse to run · overwrite it |

## Level 2-2 · Limits (3 cards)

Inputs to read first: the caps module, the configuration. Inputs that may apply: the
dialog's row budget, the chat log. Outputs: the caps module, the configuration.

| id | title | options (recommended first) |
|---|---|---|
| `too-long-card` | A card past the dialog's rows | cut the fields silently · refuse the card and tell the model · drop the explanation first |
| `many-sources` | More than six sources | keep the first six · keep the used ones first · refuse the card |
| `log-growth` | The chat log grows for months | cap it at a size and roll · keep it all · one file per month |

## Level 2-3 · Recovery (3 cards)

Inputs to read first: the record module, the command module. Inputs that may apply: the
decisions file. Outputs: the command module.

| id | title | options (recommended first) |
|---|---|---|
| `resume` | Resuming after a restart | the map says where to go on · the model re-reads the record · start over |
| `back-semantics` | What back takes back | the last answer only · the whole current level · nothing after a boss |
| `reset-keeps` | What reset keeps | the record, closed · nothing · the decisions, reopened |

## Level 2-4 · Boss

One card: every decision of the world, one line per level; options "Apply", "Change one",
"Stop". On Apply: change the plugin as decided, validate, commit, then finish the world.
