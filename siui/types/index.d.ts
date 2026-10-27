// The siui plugin's state contract: every value the hooks module keeps in
// `$.state`, under the plugin's name. `claude plugin validate` holds the module's
// `$.state` keys to this file. Self-contained: no imports.

/** One option of a card: its button label, the one-line consequence of picking it, and a drawing of it when the choice is visual. */
export type GameOption = { label: string; effect?: string; picture?: string }

/**
 * One source behind a card. `role` says which way it flows: `in` drives the
 * decision (a file the card's facts come from), `out` will change because of
 * the answer, `both` does both and appears on both sides of the graph.
 *
 * An in-edge draws solid only when the model read the file this session
 * (`isRead`); an out-edge draws solid when `use` is `used` (it will change) and
 * dashed when `maybe` (it might). `path` is what the model gave
 * (project-relative, `~/...` or absolute); `href` is the `file:` URL the card
 * links to; `isMissing` when the path is not there (for an output: a new file).
 */
export type GameSource = {
  path: string
  name: string
  role: 'in' | 'out' | 'both'
  use: 'used' | 'maybe'
  why?: string
  href?: string
  isRead?: true
  isMissing?: true
  /** The file's size on disk, when it exists: the node grows with it, up to a limit. */
  bytes?: number
}

/** A decision card as the hooks module keeps it while the dialog is up. */
export type GameCard = {
  kind: 'decision' | 'info' | 'boss'
  world: number
  /** The pack the world runs, when the model names it. */
  pack?: string
  /** What this card carries onto the map: it was raised by a discovery, a requirement or a check. */
  mark?: 'bug' | 'feature' | 'problem' | 'check'
  level: string
  levelTitle?: string
  index?: number
  count?: number
  id: string
  title: string
  short: string
  explain?: string
  options: GameOption[]
  recommended?: string
  remaining?: string
  note?: string
  /** The first six sources, drawn as nodes. */
  sources: GameSource[]
  /** Sources past the sixth, drawn as icons with a tooltip. */
  extraSources?: GameSource[]
  /** The whole text of every field that was cut to its cap, for tooltips. */
  full?: Partial<Record<'title' | 'short' | 'explain' | 'remaining' | 'note', string>>
  /** What the engine's dialog asks: the title, ending in a question mark. */
  question: string
  /** When auto-pilot will take the recommendation, as a time in ms; set only while it counts down. */
  autoUntil?: number
}

/**
 * One decision, as the history and `.claude/decisions.json` keep it: an
 * answered card (`via` absent or `card`), or a decision taken in the chat and
 * recorded by the model with the `note` tool (`via: 'chat'`), which counts
 * toward no level's cards, or a card the user dismissed (`via: 'skipped'`,
 * answer "skipped"), which counts toward none either and is presented again
 * when the run goes on or the board asks.
 */
export type GameDecision = {
  level: string
  id: string
  title: string
  answer: string
  isOther: boolean
  at: string
  sources: Array<{ path: string; role: 'in' | 'out' | 'both'; use: 'used' | 'maybe' }>
  via?: 'card' | 'chat' | 'auto' | 'skipped'
  /** Why, in the model's words, for a chat decision. */
  why?: string
  /** The latest note the user typed on the board. */
  note?: string
  /** Every note the user typed on the board, oldest first. */
  notes?: Array<{ at: string; text: string }>
  /** Decided but not started: the board queues it; a themed mark hangs under the stage's line. */
  queued?: true
  /** Taken out of the queue by the board: started; the queue button is gone for good. */
  started?: true
  /** Work followed the answer in the same turn: built; the board offers no queue for it. */
  built?: true
}

/**
 * Something that popped up on the map while building. In plain words: a bug
 * or risk (`enemy`), a feature (`powerup`), a problem (`challenge`), a check
 * the user asked for (`check`), a jump to another stage or world (`pipe`), a
 * save point (`checkpoint`). It lands on the stage where it appeared and stays
 * open until fixed, built, cleared, passed, taken or returned to.
 */
export type GameEvent = {
  id: string
  kind: 'enemy' | 'powerup' | 'challenge' | 'check' | 'pipe' | 'checkpoint'
  title: string
  text?: string
  world: number
  level: string
  at: string
  status: 'open' | 'done'
  doneAt?: string
  /** How big the work is, 1 (tiny) to 5 (huge); 2 when unsaid. The icon grows with it, up to a limit. */
  size?: number
  /** Where a pipe leads. */
  to?: { world: number; level?: string }
  /** A checkpoint's commit and branch: the state to return to. */
  commit?: string
  branch?: string
}

/** Where the run stands: the status line reads it. */
export type GameProgress = {
  target: string
  world: number
  level: string
  decided: number
  count: number
}

declare module 'claude-code' {
  interface PluginState {
    'siui': {
      /** The card the dialog shows now; null between cards. */
      card: GameCard | null
      /** Whether the Explain section is open on the current card. */
      isExplainOpen: boolean
      /** Whether the graph is shown on cards; kept as the user left it. */
      isGraphOpen: boolean
      /** Whether game mode is on for this session. */
      isOn: boolean
      progress: GameProgress | null
      history: GameDecision[]
      /** Files the model read this session (absolute paths), which earn solid links. */
      readPaths: string[]
    }
  }
}
