# Scaffold: a new project

For an empty or young folder that will hold one project. Five levels; the boss applies.
`changelog:` none.

## Fixed facts (one info card, option "OK")

- One folder, one project; git from the start. The stack is decided in level 1-2 from what
  the folder holds and from the purpose line, and the structure follows the stack.
- Nothing is generated or installed before the boss level, and the boss generates only
  what the cards decided: no extra documents, no samples, no placeholders.
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

## Level 1-2 · Stack (3 cards)

Inputs to read first: the answers of 1-1, the folder listing, the manifest found in 1-1
when one exists. Inputs that may apply: `.tool-versions`, `.nvmrc`, `.python-version`,
`Dockerfile`, `docker-compose.yml` (whichever exists). Outputs: the manifest (new, or its
runtime fields), the lock file (new), `.gitignore` (the stack's entries).

| id | title | options (recommended first) |
|---|---|---|
| `language` | Language and runtime | the one the files already use, else the one the purpose suggests · a language the user names · two: one for the core, one for the interface |
| `framework` | Framework | none, the standard library · the language's usual framework for the purpose · a named framework |
| `tooling` | Package manager and build | the language's standard tool · a named tool · none (plain files) |

## Level 1-3 · Structure (4 cards)

Inputs to read first: the answers of 1-1 and 1-2, the folder listing. Inputs that may
apply: `README.md`, the manifest, any existing `src/`, `lib/`, `app/` or `tests/` folder.
Outputs: the folders of the layout (new), the entry-point file (new), the configuration
file if chosen (new), `README.md` (the layout section).

| id | title | options (recommended first) |
|---|---|---|
| `layout` | Folder layout | the stack's convention · `src/` + `tests/` · flat (code at the root) · one folder per component |
| `entry-points` | Entry points | one main file · a CLI plus a library · several named commands |
| `config-format` | Configuration format | none (constants) · the stack's usual file · environment variables |
| `docs-policy` | How much documentation | README only · README plus one page per component · none until release |

## Level 1-4 · Quality (4 cards)

Inputs to read first: the answers of 1-2 and 1-3. Inputs that may apply: an existing CI
file under `.github/workflows/`, `.editorconfig`, a lint or format config, `Makefile`.
Outputs: the test config (new), the lint or format config (new), the CI file if chosen
(new), `.gitignore`.

| id | title | options (recommended first) |
|---|---|---|
| `tests` | Tests | the stack's standard runner · none yet · a named framework |
| `lint-format` | Lint and format | the stack's standard tool with defaults · none · a named tool |
| `ci` | Continuous integration | none yet · GitHub Actions running the tests · a named service |
| `commit-style` | Commit messages | short imperative subject line · conventional commits · free form |

## Level 1-5 · Boss

One card: every decision of the world, one line per level; options "Apply", "Change one",
"Stop". Its outputs are every output of the four levels. On Apply: create only the files
the answers call for (a README with the purpose line, the license file, the manifest and
lock file of the stack, the folders of the layout, the entry point, the test and lint
config chosen, the CI file if chosen), then finish the world. Then one closing info card:
"World complete" with the option "OK". The run takes the project's next world number; the
project's own packs carry on from there.
