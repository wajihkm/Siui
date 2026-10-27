// The texts the model reads while game mode is on: the system-prompt section
// with the rules, and the description that replaces AskUserQuestion's.

export const PROTOCOL_SECTION = [
  'GAME MODE is on: the user has eye strain and wants decisions, not prose.',
  '(1) Ask everything through the tool mcp__siui__card, one decision per call; never',
  'AskUserQuestion, never a list of questions or options in text.',
  '(2) Write nothing between cards: no preamble, recap, headings or bullet lists. At most one',
  'short sentence of plain text per turn, and only to report an error.',
  '(3) Caps: title ≤ 8 words, short ≤ 20 words, each option effect ≤ 14 words, explain ≤ 80',
  'words, remaining ≤ 12 words, 2-4 options with labels ≤ 4 words; the recommended option first',
  'and named in `recommended`.',
  "(4) Follow the pack's levels in order, all cards of a level before the next; set world, level,",
  'levelTitle, index and count on every card. After a world is applied, a decision that belongs',
  'to one of its stages names that world and stage; any other names world 0 and level 0-1: the',
  'side quests, kept by month and drawn apart on the roadmap.',
  "(5) A pack's fixed facts are not decisions: show them once as kind 'info' with the single",
  "option 'OK'. The tool adds a second option 'Stop' by itself: that answer ends the turn.",
  '(3b) When a choice is visual (a layout, a shape, a colour, a place on a map), give each option a',
  'small SVG drawing in `picture` (one <svg> with a viewBox, under 4000 characters, no scripts or',
  'links): the board shows it beside the option, the chat under Show graph.',
  "(6b) A card may offer the option 'Fork here' when two answers both deserve a try: the stage",
  'forks into roads a and b, each a git branch, and the remaining cards are asked on the road on',
  "disk as level '<level>a' or '<level>b'. A forked world's boss lists both roads and offers",
  "'Merge a', 'Merge b' and 'Keep both' beside Apply; the done tool takes the choice as `merge`.",
  "(6) Boss level: one kind 'boss' card listing every decision of the world, one line per level,",
  "with the options 'Apply', 'Change one' and 'Stop'. On Apply: make the edits with no commentary,",
  'then call mcp__siui__done and append the lines it returns where the pack says (nowhere',
  "when it says nothing). On 'Change one': one card asking which, then re-present that decision.",
  "(7) When the user's answer is their own text ending in '?', answer it in the next card's",
  '`note` (≤ 40 words) and present the same card again.',
  '(8) When a card was dismissed, end the turn with one short line and wait.',
  '(9) Never create a file to explain, plan or summarise; the record is .claude/decisions.json,',
  'written by the tool.',
  "(10) Every card lists its `sources` with a role: 'in' for a file whose facts drive the",
  "decision, 'out' for a file the answer will change, 'both' for both. An 'in' source is 'used'",
  "only when you read it in this session, 'maybe' otherwise; an 'out' source is 'used' when it",
  "will change, 'maybe' when it might. Read a level's 'in' sources before its first card.",
  '(11) When the user decides something in the chat rather than on a card (a change of plan, a',
  'preference, a correction, a yes to a proposal), record it at once with mcp__siui__note:',
  'the title, the decision in their words, why, and the level it belongs to. The board shows',
  'these beside the cards.',
  '(12) The map records what pops up while building: when you discover something and ask the',
  'user about it, when the user adds a requirement or a check, when a bug, a risk or a hard',
  'problem appears, or when the work jumps elsewhere. Drop it with mcp__siui__event, kind',
  "'bug', 'feature', 'problem', 'check' or 'jump', or set `mark` on the card or the note that",
  'carries it, so it lands on the stage by itself. Mark it done with the event tool when it is',
  'fixed, built, cleared, passed or taken.',
  "(13) Before a change that is hard to undo, and after a boss is applied, save a 'checkpoint'",
  'with mcp__siui__event: a commit of the whole tree the user can return to from the board.',
  '(14) Answers marked [auto-pilot] in the status were taken by auto-pilot, not the user: the',
  "boss card lists them under 'taken by auto-pilot' so the user can change one before applying.",
].join(' ')

export const EVENT_DESCRIPTION = [
  'Drop something on the world map, or mark it done. Kinds: "enemy" = a security issue, a bug or',
  'a risk found while building; "powerup" = a gain or a new feature idea; "challenge" = a hard',
  'problem to clear; "pipe" = a jump from the current stage to another stage or world (give',
  '"to"). Give a short title and one line of text; the level defaults to the current one. To',
  'mark one done, pass its id and status "done". The board shows them on the stage where they',
  'popped up and on the roadmap.',
].join(' ')

export const EVENT_SCHEMA = {
  type: 'object',
  required: ['kind', 'title'],
  properties: {
    id: { type: 'string', description: 'The id of an event to update; left out, a new one' },
    kind: { type: 'string', enum: ['bug', 'feature', 'problem', 'check', 'jump', 'save', 'enemy', 'powerup', 'challenge', 'pipe', 'checkpoint'] },
    title: { type: 'string', maxLength: 60 },
    text: { type: 'string', maxLength: 240, description: 'One line: what it is and what it means' },
    world: { type: 'integer', minimum: 0, description: 'Default: the open world, else the last; 0 = the side quests' },
    level: { type: 'string', pattern: '^[0-9]+-[0-9]+[ab]?$', description: 'Default: the current level' },
    status: { type: 'string', enum: ['open', 'done'] },
    size: { type: 'integer', minimum: 1, maximum: 5, description: 'How big the work is: 1 tiny, 2 small (default), 3 medium, 4 big, 5 huge' },
    to: {
      type: 'object',
      description: 'Where a pipe leads',
      properties: { world: { type: 'integer', minimum: 1 }, level: { type: 'string', pattern: '^[0-9]+-[0-9]+[ab]?$' } },
    },
  },
} as const

export const NOTE_DESCRIPTION = [
  'Record a decision the user took in the chat rather than on a card: a change of plan, a',
  'preference, a correction, a yes or no to a proposal. Call it at once, in the same turn.',
  'Give a short title, the decision in the user\'s words, why, and the level it belongs to',
  '(the current level when left out). It counts toward no level\'s cards; the board shows it',
  'beside them, collapsed.',
].join(' ')

export const NOTE_SCHEMA = {
  type: 'object',
  required: ['title', 'decision'],
  properties: {
    mark: {
      type: 'string',
      enum: ['bug', 'feature', 'problem', 'check'],
      description: 'Set when the decision carries something onto the map: a requirement (feature), a check, a bug or risk, a problem',
    },
    title: { type: 'string', maxLength: 60, description: 'What was decided, in a few words' },
    decision: { type: 'string', maxLength: 240, description: "The decision, in the user's words" },
    why: { type: 'string', maxLength: 240, description: 'The reason, when the user gave one' },
    level: { type: 'string', pattern: '^[0-9]+-[0-9]+[ab]?$', description: 'The level it belongs to; default: the current one' },
    sources: {
      type: 'array',
      maxItems: 6,
      items: {
        type: 'object',
        required: ['path'],
        properties: {
          path: { type: 'string' },
          role: { type: 'string', enum: ['in', 'out', 'both'] },
          use: { type: 'string', enum: ['used', 'maybe'] },
        },
      },
    },
  },
} as const

export const ASK_REPLACED =
  'Disabled while game mode is on: ask the user through mcp__siui__card instead, one decision per call.'

export const DONE_DESCRIPTION = [
  'Finish the current world of game mode after the boss card was applied. Marks the run',
  'finished, clears the status line, and returns one summary line per level for you to append',
  'where the pack says (nowhere when it says nothing). Write no other file. When the world has',
  'a forked stage still open, give `merge`: the road the boss kept ("a" or "b"), or "both". With no',
  'boss card answered on the last level the tool asks you to check with the user first; call it',
  'again with confirm: true when they agree to close without a castle.',
].join(' ')

export const FORK_DESCRIPTION = [
  'Forks, switches or merges the roads of a stage. action "fork": a checkpoint, then two git',
  'branches fork/<level>-a and -b; road a goes on disk and the remaining cards of the stage are',
  'asked on it as level "<level>a". action "road": switches the disk to road "a" or "b"; the',
  'record follows. action "merge": the castle keeps road "a", "b" or "both": a merge commit into',
  'the base, the other road tagged. Call it when the board asks (Fork, the road switch) or a',
  'card was answered "Fork here".',
].join(' ')

export const FORK_SCHEMA = {
  type: 'object',
  required: ['action'],
  properties: {
    action: { type: 'string', enum: ['fork', 'road', 'merge'] },
    level: { type: 'string', pattern: '^[0-9]+-[0-9]+$', description: 'The stage; default: the current one' },
    road: { type: 'string', enum: ['a', 'b', 'both'], description: 'For road: the road to put on disk; for merge: the road kept' },
  },
} as const

export const DONE_SCHEMA = {
  type: 'object',
  properties: {
    world: { type: 'integer', minimum: 1 },
    merge: { type: 'string', enum: ['a', 'b', 'both'], description: 'A forked world: the road the boss kept, or both' },
    confirm: { type: 'boolean', description: 'true after the user agreed to close a world that has no castle answered' },
  },
} as const

/** The prompt `/game on <pack>` submits to start the first card. */
export function startPrompt(pack: string | undefined, path?: string): string {
  if (!pack) {
    return [
      'Game mode is on. Turn the task I describe next into levels of 3-4 decisions each, with a',
      'boss level last, and present the first card with no text before it. Do nothing until I',
      'describe the task.',
    ].join(' ')
  }

  return [
    `Game mode is on. Read the pack ${pack}${path ? ` at ${path}` : ''} (a world of levels, each a few cards) and the`,
    "inputs its first level lists. Then present the pack's fixed-facts card, then the first card of its first level,",
    'with no text before them.',
    'If a skill named decision-cards exists in this project, its rules apply as well.',
  ].join(' ')
}
