# Demo 3: the shape of a page

For a tool whose page or panel works and now gets shaped around how it is used. Written
for a page or panel; the questions fit any small interface. `changelog:` none.

## Fixed facts (one info card, option "OK")

- Nothing changes before the boss; each card decides one behaviour.
- The user has eye strain: fewer things on screen win over more; one place to look for
  what is waiting; nothing that must be read twice.
- Every change keeps the keyboard able to do what the mouse does.

## Level 3-1 · Layout (4 cards)

Inputs to read first: the page, the chat decisions about the board. Inputs that may
apply: the record. Outputs: the page.

| id | title | options (recommended first) |
|---|---|---|
| `columns` | The page's columns | map and step left, card right, as now · one column, card first · tabs: map, step, card |
| `first-thing` | What the eye lands on | the waiting card, else the map · always the map · the current step |
| `header` | What the header holds | title, chat state, liveness as now · add the world tabs · as little as possible |
| `send-box` | Where the send box lives | fixed at the bottom as now · inside the card section · in the header |

## Level 3-2 · Interaction (4 cards)

Inputs to read first: the page, the answers of 3-1. Inputs that may apply: the plugin's
command. Outputs: the page, the plugin's command.

| id | title | options (recommended first) |
|---|---|---|
| `keys` | Keyboard shortcuts | 1 to 4 answer, j and k walk steps, / focuses send · answer keys only · none |
| `undo` | Taking an answer back on the board | a back button next to the card, same as /siui back · none; the chat only · a confirm step before each answer |
| `open-files` | Opening a file | one click opens in the editor as now · a preview on hover, click opens · a click copies the path |
| `expand` | What opens by default in a step | the latest decision open, the rest folded · everything folded · everything open |

## Level 3-3 · Information (4 cards)

Inputs to read first: the page, the answers of 3-1 and 3-2. Inputs that may apply: the
chat log, the record. Outputs: the page.

| id | title | options (recommended first) |
|---|---|---|
| `card-depth` | How much a card shows at first | title, line, options; the rest folded as now · everything · title and options only |
| `chat-turns` | The chat around a step | folded as now · the last three open · hidden unless asked |
| `files-view` | The files touched | grouped by folder as now · a flat list · a tree with folding folders |
| `alerts` | How a waiting card calls you | colour and motion on the page as now · plus a browser notification · plus a short sound |

## Level 3-4 · Boss

One card: every decision of the world, one line per level; options "Apply", "Change one",
"Stop". On Apply: change the page and, where chosen, the plugin's command, validate,
commit, then finish the world.
