# Siui: why it exists, what it gives you, what it does

This page grows with the plugin. Each release adds to the two lists below; nothing here
describes a feature that is not in the code.

## Why it exists

Siui was started by a developer who spends the working day in an AI chat and developed
eye strain from it. An assistant answers in long text: plans, summaries, option lists
buried in paragraphs, markdown files written to explain other markdown files. The work was
to read all of it, find the one question inside, and answer it.

The second problem was keeping track. The output of the assistant ended up spread over
several tools: the chat's scrollback, notes in another app, a task list somewhere else, git
for what actually changed. Working on several plugins and apps at once made it worse:
what was decided in which project, why, and what it touched, lived nowhere in one piece.

Siui is one tool for both: the assistant asks one decision at a time, as a short card,
and every answer lands on a map of the project that keeps the decision, the reason, the
files, the chat around it and the cost.

## Benefits

**Easier on the eyes**

- You read a card, not a wall of text: a title, one line, two to four options with their
  consequences. The explanation stays folded until you ask for it.
- The assistant writes nothing between cards while the mode is on, and creates no file
  to explain or summarise.
- The board is a page in your browser, so the browser's zoom and your own reading
  settings apply. The page adds a text size, a light or dark scheme (or the system's),
  reduced motion, and twelve visual sets to pick the colours and shapes you find calm.
- A waiting card calls you without being read: a dot in the tab's title, a colour on
  the page, an optional short chime.

**Nothing gets lost**

- Every decision is recorded with its answer, its time, whether you or auto-pilot took
  it, and the files it rested on and changed.
- The chat around each step is kept beside it: your words and the assistant's answer,
  per stage, searchable. Long answers are kept up to a length limit, so this is the
  thread of the work, not a full transcript.
- A decision you took in the chat, in plain words, is recorded too, next to the cards.
- A run resumes after a restart: the map says where you stopped and which card is next.

**The history of the project in one place**

- The record is one JSON file inside the project, so it travels with the code and can be
  committed with it.
- The roadmap shows every piece of work as a world: finished, in progress, abandoned,
  planned.
- An export writes the whole history as a standalone HTML page, a Markdown report or an
  SVG poster.

**Fewer tools to keep open**

- Notes go where they belong: on the decision they are about, saved in the record, and
  sent to the chat as your words when you want the assistant to act on them.
- Bugs, feature ideas, problems, checks and jumps to other work are dropped on the map at
  the moment they come up, and marked done later. For work driven through the assistant,
  this replaces a separate task list and a separate notes app. It is not a general
  notebook: everything on it hangs from a decision, a stage or a world.

**You stay in control of the work**

- Nothing is generated before the last stage of a world, the boss, where every answer is
  reviewed and applied at once. You can change one answer first.
- Queue a decision: it is decided, but the work waits until you press Start.
- Skip a card: it is kept, counted nowhere, and comes back later.
- Take the last answer back and get its card again.
- Before you answer, you see which files the question rests on and which files your
  answer will change. A file the assistant claims to have used is drawn as sure only when
  the plugin saw it being read in this session.
- Save points are git commits you can return to; what is on disk at that moment is tagged
  first, so a return loses nothing.
- When two answers both deserve a try, a stage forks into two roads, each a git branch,
  and the boss keeps the better one.

**You know what it cost**

- Each decision carries what the session spent from that answer to the next; the board
  sums it per stage and per world, and the exports carry it.
- The board shows the model the chat runs on, the session's cost so far, how full the
  context window is, and the rate-limit windows with their resets.
- The figures are the session's own ledger at API prices, split by time, not by cause;
  they are a guide to where the effort went, not an invoice.

**It stays on your machine**

- The board is served from your own computer, to your own browser, and accepts requests
  from that page only. Nothing is uploaded; there is no account and no service.
- The plugin needs Python 3 and nothing else to install. Git is optional and only
  needed for save points and forks.

## Features

**The card**

- One decision per card: title, one line, two to four options, each with its consequence,
  the recommended one marked.
- Explain, folded by default; typing `?` opens it.
- The files graph: inputs that drive the decision, outputs the answer will change; solid
  when sure, dashed when it might apply, dotted for a file not there yet.
- A drawing per option when the choice is visual: a layout, a shape, a colour.
- Your own words instead of an option; a question ending in `?` is answered on the card.
- A full card in VS Code and the desktop app, a compact one in the terminal.
- Three kinds: a decision, the fixed facts of a world, the boss review.

**Worlds, stages and packs**

- A world is one piece of work; its stages hold three or four cards; the last is the boss.
- A pack is a markdown file that lays a world out in advance. One ships with the plugin,
  `scaffold`, which sets up a new project; a project writes its own.
- A world without a pack: describe the task and the assistant turns it into stages.
- Side quests: decisions that belong to no world, kept by month.
- A world can be abandoned and stays readable.

**The board**

- A roadmap of every world, with the roads between them and the jumps across.
- A map of the world shown, and each stage drawn as a side-scrolling level: a block per
  card, with what came up placed where it happened.
- A step panel per stage: decisions, notes, files as a tree, the chat that followed.
- Cards answered on the board while it is open, or in the chat; one switch chooses.
- Keyboard: 1 to 4 answer, j and k walk the steps, / the send box, f the search.
- Search over decisions, marks, stages, worlds and chat turns.
- A send box that speaks to the chat as you.
- New world, Start a planned world, Abandon, Move a decision, Present a card again,
  Delete a skipped card, all from the page.
- A legend of every icon, line and status.

**What lands on the map**

- Bug or risk, feature, problem, check, jump, save point; each with a size, each open
  until marked done.
- Raised by the assistant when it discovers something, by you from the page, or by a card.

**Flow**

- Auto-pilot: a card with a recommendation is answered after a countdown; a boss, a bug,
  a problem or a card without advice waits for you.
- Queue, Start, Skip, Back.
- A Ready notice when something was built, which opens the output.

**Git**

- Save points with a Return that tags the present first.
- Forks: two roads, a switch between them, a merge of one or both at the boss.

**Cost and status**

- Cost per decision, stage and world; a total in the exports.
- The model, the session's cost, the context window and the rate limits on the board.
- The chat's state: working, idle, waiting for you, ended, not running; and the agents
  still running in the background.

**Look**

- Twelve universes that change the words, icons, colours and shapes: classic, mario,
  mountain, sea, cloud, space, fire, software, kitchen, railway, garden, zoo. A project
  can add its own.
- Light and dark, text size, corner style, motion on, reduced or off.
- The project's name in the header and the tab.

**Exports**

- HTML, Markdown and SVG, written into the project; one address runs an export for a
  script.

**Where it runs**

- Claude Code in VS Code, the desktop app and the terminal.
- Linux, WSL and Windows: run in full sessions in VS Code on WSL and in the Claude desktop
  app on Windows; macOS is expected to work and is untried.
- The decision-cards skill gives the same rules, as text cards, to an assistant without
  the plugin.

## Known limits

- The plugin API it builds on is early-access; an update of Claude Code may change it.
- The font family is not a setting of the board yet; the browser's own setting applies.
- The chat kept beside a step is cut at a length limit and exists only for turns taken
  while the plugin was loaded.
- Costs exist from version 1.1.0 on; older worlds have none.
- GitHub Copilot support is in progress on its own branch and is not part of a release.

## Adding to this page

A benefit names what the reader gains and, in the same breath, the feature that delivers
it. A feature goes under its group in a line or two. A limit that a reader would trip on
goes under Known limits until it is lifted.
