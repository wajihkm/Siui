# Demo 1: a new project

For an empty or young folder that will hold one project. Four levels; the boss applies.
`changelog:` none.

## Fixed facts (one info card, option "OK")

- One folder, one project, one main language; git from the start.
- Nothing is generated before the boss level, and the boss generates only what the cards
  decided: no extra documents, no samples, no placeholders.
- Every card draws its facts from the files that exist; where none exists the card says so
  in its short line and recommends the plainest option.

## Level 1-1 · Identity (4 cards)

Inputs to read first: `README.md`, `CLAUDE.md` or `AGENTS.md` (those that exist), this
pack. Inputs that may apply: `package.json`, `composer.json`, `pyproject.toml`,
`Cargo.toml`, `go.mod` (whichever exists), `.gitignore`. Outputs: `README.md` (name and
purpose line), `LICENSE` (new), the manifest's name and version fields.

| id | title | options (recommended first) |
|---|---|---|
| `name` | Project name | the folder's name · a short brand name · a scoped package name |
| `purpose` | One-line purpose | the line you infer from the files · a line the user types |
| `license` | License | MIT · Apache-2.0 · proprietary (no file) |
| `versioning` | Versioning | semver with git tags · date-based · none yet |

## Level 1-2 · Structure (4 cards)

Inputs to read first: the answers of 1-1, the folder listing. Inputs that may apply:
`README.md`, the manifest found in 1-1, any existing `src/`, `lib/`, `app/` or `tests/`
folder. Outputs: the folders of the layout (new), the entry-point file (new), the
configuration file if chosen (new), `README.md` (the layout section).

| id | title | options (recommended first) |
|---|---|---|
| `layout` | Folder layout | flat (code at the root) · `src/` + `tests/` · one folder per component |
| `entry-points` | Entry points | one main file · a CLI plus a library · several named commands |
| `config-format` | Configuration format | none (constants) · one JSON file · environment variables |
| `docs-policy` | How much documentation | README only · README plus one page per component · none until release |

## Level 1-3 · Quality (4 cards)

Inputs to read first: the answers of 1-1 and 1-2. Inputs that may apply: an existing CI
file under `.github/workflows/`, `.editorconfig`, a lint or format config, `Makefile`.
Outputs: the test config (new), the lint or format config (new), the CI file if chosen
(new), `.gitignore`.

| id | title | options (recommended first) |
|---|---|---|
| `tests` | Tests | the language's standard runner · none yet · a named framework |
| `lint-format` | Lint and format | the language's standard tool with defaults · none · a named tool |
| `ci` | Continuous integration | none yet · GitHub Actions running the tests · a named service |
| `commit-style` | Commit messages | short imperative subject line · conventional commits · free form |

## Level 1-4 · Boss

One card: every decision of the world, one line per level; options "Apply", "Change one",
"Stop". Its outputs are every output of the three levels. On Apply: create only the files
the answers call for (a README with the purpose line, the license file, the folders of the
layout, the test and lint config chosen, the CI file if chosen), then finish the world.
Then one closing info card: "World 1 complete" with the options "Stop" and "Next:
hardening". The next pack is `demo-2-hardening`; the run takes the project's next world
number whatever the pack's name says.
