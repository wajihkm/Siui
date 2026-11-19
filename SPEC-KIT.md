# Siui and GitHub Spec Kit

[Spec Kit](https://github.com/github/spec-kit) and Siui both put structure between an idea
and the code an assistant writes. They do it from opposite ends, and they work together.
This page says how they differ, when to use which, and how to use them, alone or paired.

## The short version

- **Spec Kit** is a process and its documents. It gives the assistant commands that write a
  specification, a plan and a task list, which you review before it builds.
- **Siui** is a way of asking and of keeping track. The assistant asks one decision at a
  time on a card, and every answer lands on a map of the project.
- **Together**: Spec Kit decides what gets written; Siui decides how you are asked and
  where you see it.

## How they differ

| | Spec Kit | Siui |
|---|---|---|
| Unit of work | A feature, as a folder of documents | A world, as stages of cards |
| What you read | The documents each command writes | A card; the explanation stays folded |
| How it asks | Questions as tables in the chat, some in batches | One card per question, the recommended option first |
| Review | You read the spec, then the plan, then the tasks | One review at the boss, with every answer listed |
| Where the result lives | `specs/<feature>/` and `.specify/` | `.claude/decisions.json`, drawn on a board |
| What you see of the project | The files | A roadmap of worlds, each stage, the files and chat of every step |
| Cost | Not tracked | Per decision, stage and world |
| Project-wide rules | A constitution file | Project facts: the setup world's answers, never asked twice |
| Assistants | Many, through integrations | Claude Code |
| Needs | Python 3.11+, `uv`, the `specify` CLI | The plugin, and Python 3 for the board |

Spec Kit's side of this table comes from its repository page and from the skills its
installer adds, as of its version 1.2.2.

## Which to use

- **Siui alone** when the reading is the problem: you want decisions, not documents, and
  one place to see what was decided, why, what it touched and what it cost.
- **Spec Kit alone** when the documents are the point: a team reviews specifications in
  pull requests, or you work across several assistants.
- **Siui's spec-driven method** when you want Spec Kit's discipline, a feature specified
  before it is built, with one page per document and nothing to install.
- **Both** when a project already uses Spec Kit and you want its questions and review
  gates as cards, and its runs on the board.

## Using Siui's spec-driven method

This needs only the Siui plugin. It follows the same order as Spec Kit, in Siui's terms.

1. Set the project up once, so its facts exist: `/siui on scaffold`. The language, the
   framework, the layout and the test conventions are decided here and never asked again.
2. Open the board: `/siui board`.
3. Press **+ New world**, give the feature a title, and under "How it runs" pick
   **Spec-driven**.
4. Answer the cards. The stages are:

   | Stage | What is decided |
   |---|---|
   | Specify | The feature in one sentence, who it is for, what it will not do |
   | Clarify | The biggest ambiguities the assistant finds, and how success is checked |
   | Plan | How it is built, what it stores, where the code goes |
   | Tasks | How the work is cut and what comes first |

5. At the boss, choose **Apply** to write `spec.md`, `plan.md` and `tasks.md` under
   `specs/<feature>/` and build the tasks, or **Documents only** to stop after writing.

Every feature is its own world, so the roadmap reads as the list of features, each
specified and built the same way.

Differences from Spec Kit to expect: the documents are short, written once at the end
from your answers, not drafted first and corrected; there is no constitution file, the
project facts stand in for it; nothing is written before the boss.

## Using Siui with Spec Kit itself

Here Spec Kit does the writing with its own skills, templates and scripts, and Siui
changes only the conversation.

1. Install Spec Kit in the project for Claude:

   ```
   uvx --from specify-cli specify init --here --integration claude
   ```

2. Copy the example method into the project's packs:

   ```
   mkdir -p .claude/skills/decision-cards/packs
   cp <siui repo>/skills/decision-cards/packs/examples/speckit.md .claude/skills/decision-cards/packs/
   ```

3. Open the board, press **+ New world**, and pick **Spec Kit** under "How it runs".

What the method does:

- Runs `speckit-specify`, `speckit-clarify`, `speckit-plan` and `speckit-tasks` as they
  are, one per stage, and `speckit-implement` at the boss.
- Turns every question a skill would print as a table into one card, and every "review
  before going on" into a review card: approve, change one thing, reject.
- Keeps the documents out of the chat: a review card carries a few lines of what was
  written, with the file one click away.
- Hands the project's facts to `speckit-plan`, so the stack is not asked again.

One difference from other Siui methods: Spec Kit's documents are written stage by stage,
because each of its skills reads the one before. Only the code waits for the boss.

**Status.** The spec-driven method ships with the plugin. The Spec Kit method is an
example file with little use behind it so far: the board reads its pack correctly, but it
rests on the assistant following the method's rule over a skill's own instruction to
print a table. If a table appears in the chat, that is the place it slipped; tightening
the pack's fixed facts for that skill is the fix.

## Moving between them

- **From Spec Kit to Siui.** Nothing to convert. Existing `specs/` folders stay; new
  features go through a world. A constitution you already wrote can be read once as the
  setup world's inputs.
- **From Siui to Spec Kit.** The spec-driven method writes `spec.md`, `plan.md` and
  `tasks.md` in a `specs/<feature>/` folder, the same three documents Spec Kit works
  with. Their content is shorter than its templates, and Spec Kit names its folders and
  branches by its own scripts, so expect to move or re-create a feature, not to resume it.
