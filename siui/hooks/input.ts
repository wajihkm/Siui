// What the model sends to the `card` tool: its schema, the caps, and the
// normalisation that turns a loose input into a GameCard or an error line.

import type { GameCard, GameOption, GameSource } from '../types'

/** The built-in caps on each field, in characters or entries; a project may lower them. */
export const CAPS = {
  levelTitle: 40,
  title: 60,
  short: 120,
  explain: 480,
  label: 30,
  effect: 80,
  remaining: 80,
  note: 200,
  name: 30,
  why: 60,
  options: 4,
  sources: 6,
} as const

export type Caps = { -readonly [K in keyof typeof CAPS]: number }

export const SOLID = '━━'
export const DASHED = '┄┄'

export const CARD_DESCRIPTION = [
  'Show the user ONE decision as a card with 2-4 option buttons and wait for the answer.',
  'While game mode is on this is the only way to ask the user anything: never AskUserQuestion,',
  'never several questions or option lists in text. Returns the chosen label, or the user\'s own',
  'text (isOther), or dismissed. Keep fields short: title ≤ 8 words, short ≤ 20 words, each',
  'option effect ≤ 14 words, explain ≤ 80 words (hidden until the user opens it), remaining',
  '≤ 12 words. Put the recommended option first and name it in `recommended`. List the card\'s',
  'sources with a role: "in" = a file whose facts drive the decision, "out" = a file the answer',
  'will change, "both" = both. For an "in" source use "used" only when you read the file in this',
  'session (the tool downgrades a "used" file you never read), "maybe" otherwise. For an "out"',
  'source "used" means it will change, "maybe" that it might; a path that does not exist yet is',
  'a new file. The answer is recorded in the project\'s decisions file for you. After a world',
  'is applied, a decision that belongs to one of its stages names that world and level; any other',
  'names world 0 and level "0-1": the side quests, kept by month, apart on the roadmap. An info',
  'card gets a second option "Stop" by itself: that answer ends the turn.',
].join(' ')

/** Whether a text is a level id: world-stage, with a road letter on a forked stage ("3-3b"). */
export function isLevel(text: unknown): text is string {
  return typeof text === 'string' && /^[0-9]+-[0-9]+[ab]?$/.test(text)
}

export const CARD_SCHEMA = {
  type: 'object',
  required: ['world', 'level', 'id', 'title', 'short', 'options'],
  properties: {
    kind: {
      type: 'string',
      enum: ['decision', 'info', 'boss'],
      description: 'decision (default); info = fixed facts, one option "OK"; boss = the level review',
    },
    world: { type: 'integer', minimum: 0, description: '0 = the side quests: a decision after a boss that belongs to no stage of a world' },
    pack: { type: 'string', pattern: '^[a-z0-9-]{2,60}$', description: 'The pack this world runs, e.g. "world-4-theme"; names the plan when the first card starts a new world' },
    mark: {
      type: 'string',
      enum: ['bug', 'feature', 'problem', 'check'],
      description: 'Set when this card is not from the pack but raised by something you discovered (bug, problem) or the user added (feature, check): it lands on the map when answered',
    },
    level: { type: 'string', pattern: '^[0-9]+-[0-9]+[ab]?$', description: 'Level id, e.g. "1-2"; on a forked stage the road letter follows, "3-3a"' },
    levelTitle: { type: 'string', maxLength: CAPS.levelTitle },
    index: { type: 'integer', minimum: 1, description: "This card's number within the level" },
    count: { type: 'integer', minimum: 1, description: 'How many cards the level has' },
    id: { type: 'string', pattern: '^[a-z0-9-]{2,40}$', description: 'Stable slug of the decision' },
    title: { type: 'string', maxLength: CAPS.title },
    short: { type: 'string', maxLength: CAPS.short, description: 'One line: what is decided and why now' },
    explain: {
      type: 'string',
      maxLength: CAPS.explain,
      description: 'Background, hidden until the user presses Explain; plain sentences, no headings',
    },
    options: {
      type: 'array',
      minItems: 1,
      maxItems: CAPS.options,
      items: {
        type: 'object',
        required: ['label'],
        properties: {
          label: { type: 'string', maxLength: CAPS.label },
          effect: { type: 'string', maxLength: CAPS.effect, description: 'Consequence of picking it, one line' },
          picture: { type: 'string', maxLength: 4000, description: 'An SVG drawing of this option (one <svg> with a viewBox, no scripts, no links), only when the choice is visual: layout, shape, colour; shown as a thumbnail beside the option on the board and under Show graph in the chat' },
        },
      },
    },
    recommended: { type: 'string', description: 'The label you recommend; marked on the card' },
    remaining: { type: 'string', maxLength: CAPS.remaining, description: 'What is left in this level after this card' },
    note: {
      type: 'string',
      maxLength: CAPS.note,
      description: "Your answer to the user's last question, when re-presenting a card",
    },
    sources: {
      type: 'array',
      maxItems: CAPS.sources,
      items: {
        type: 'object',
        required: ['path'],
        properties: {
          path: { type: 'string', description: 'Project-relative path, ~/... or absolute' },
          name: { type: 'string', maxLength: CAPS.name, description: 'Short label; default: the file name' },
          role: {
            type: 'string',
            enum: ['in', 'out', 'both'],
            description: 'in = drives the decision (default); out = will change because of the answer; both',
          },
          use: {
            type: 'string',
            enum: ['used', 'maybe'],
            description: 'in: used = read this session and relied on; out: used = will change, maybe = might',
          },
          why: { type: 'string', maxLength: CAPS.why },
        },
      },
    },
  },
} as const

/** Trims and cuts a text to `max` characters, ending a cut text with an ellipsis. */
export function cut(value: unknown, max: number): string {
  const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : ''

  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text
}

/** The text as given, trimmed, when `cut` would shorten it; else undefined. */
function whole(value: unknown, max: number): string | undefined {
  const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : ''

  return text.length > max ? text.slice(0, 4000) : undefined
}

/** How many sources past the first six are kept as icons. */
const EXTRA_SOURCES = 24

/**
 * An option's drawing: one <svg> with a viewBox, at most 4000 characters,
 * nothing that runs or loads: no script, handler, style sheet, external
 * reference (`url(`, `@import`, `<use`, `xlink:`, `data:`) or link; else nothing.
 */
function cleanPicture(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const text = value.trim()
  if (text.length === 0 || text.length > 4000 || !/^<svg[\s>]/i.test(text) || !/<\/svg>\s*$/i.test(text)) return undefined
  if (/<script|javascript:|\son[a-z]+\s*=|<foreignObject|<iframe|href\s*=\s*["']?(?!#)/i.test(text)) return undefined
  if (/<style|url\(|@import|<use|xlink:|data:/i.test(text)) return undefined

  return text
}

function asInt(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 ? value : undefined
}

function slug(value: unknown): string {
  const text = typeof value === 'string' ? value.trim().toLowerCase() : ''
  const made = text.replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)

  return made.length >= 2 ? made : ''
}

function nameOf(path: string, max: number): string {
  const last = path.split(/[\\/]/).filter(Boolean).pop() ?? path

  return cut(last.replace(/\.(md|json|ya?ml|txt)$/i, ''), max)
}

const DEFAULT_CAPS: Caps = { ...CAPS }

/**
 * Turns the tool's input into a GameCard, or returns one line saying what is
 * wrong with it. Everything is trimmed and cut to the caps; the question is the
 * title ending in a question mark; options are made distinct and at least two
 * (the engine's dialog pads a single option with Yes/No otherwise).
 */
export function normaliseCard(input: Record<string, unknown>, caps: Caps = DEFAULT_CAPS): GameCard | string {
  const level = typeof input.level === 'string' && isLevel(input.level.trim()) ? input.level.trim() : ''
  if (level === '') return 'level must look like "1-2"'
  const world = (typeof input.world === 'number' && Number.isInteger(input.world) && input.world >= 0 ? input.world : undefined) ?? Number(level.split('-')[0])
  const id = slug(input.id)
  if (id === '') return 'id must be a slug of 2-40 characters: letters, digits, dashes'
  const title = cut(input.title, caps.title)
  if (title === '') return 'title is required'
  const short = cut(input.short, caps.short)
  if (short === '') return 'short is required'

  const rawOptions = Array.isArray(input.options) ? input.options : []
  const options: GameOption[] = []
  for (const raw of rawOptions) {
    if (options.length >= caps.options) break
    const one = (raw ?? {}) as Record<string, unknown>
    const label = cut(one.label, caps.label)
    if (label === '' || options.some(o => o.label === label)) continue
    const effect = cut(one.effect, caps.effect)
    const picture = cleanPicture(one.picture)
    options.push({ label, ...(effect ? { effect } : {}), ...(picture ? { picture } : {}) })
  }
  if (options.length === 0) return 'options must hold 1-4 entries with a label each'
  const kindText = typeof input.kind === 'string' ? input.kind : 'decision'
  const kind = kindText === 'info' || kindText === 'boss' ? kindText : 'decision'
  if (options.length === 1) options.push({ label: 'Stop', effect: 'Leave the game here' })

  const recommendedText = cut(input.recommended, caps.label)
  const recommended = options.some(o => o.label === recommendedText) ? recommendedText : undefined

  // Past the cap the used sources stay on the card and the maybe ones go to the extras: sort is stable.
  const isUsed = (raw: unknown): boolean => ((raw ?? {}) as Record<string, unknown>).use === 'used'
  const rawSources = (Array.isArray(input.sources) ? [...input.sources] : []).sort((a, b) => Number(isUsed(b)) - Number(isUsed(a)))
  const sources: GameSource[] = []
  const extraSources: GameSource[] = []
  for (const raw of rawSources) {
    if (sources.length + extraSources.length >= caps.sources + EXTRA_SOURCES) break
    const one = (raw ?? {}) as Record<string, unknown>
    const path = typeof one.path === 'string' ? one.path.trim() : ''
    if (path === '' || sources.some(s => s.path === path) || extraSources.some(s => s.path === path)) continue
    const name = cut(one.name, caps.name) || nameOf(path, caps.name)
    const why = cut(one.why, caps.why)
    const role = one.role === 'out' || one.role === 'both' ? one.role : 'in'
    const made: GameSource = { path, name, role, use: one.use === 'used' ? 'used' : 'maybe', ...(why ? { why } : {}) }
    if (sources.length < caps.sources) sources.push(made)
    else extraSources.push(made)
  }

  const trimmedTitle = title.replace(/[?:.!]+$/, '')
  const card: GameCard = {
    kind,
    world,
    level,
    id,
    title,
    short,
    options,
    sources,
    question: `${trimmedTitle}?`,
  }
  if (extraSources.length > 0) card.extraSources = extraSources
  const pack = typeof input.pack === 'string' && /^[a-z0-9-]{2,60}$/.test(input.pack.trim()) ? input.pack.trim() : ''
  if (pack) card.pack = pack
  const mark = input.mark === 'bug' || input.mark === 'feature' || input.mark === 'problem' || input.mark === 'check' ? input.mark : undefined
  if (mark) card.mark = mark
  const levelTitle = cut(input.levelTitle, caps.levelTitle)
  if (levelTitle) card.levelTitle = levelTitle
  const index = asInt(input.index)
  if (index) card.index = index
  const count = asInt(input.count)
  if (count) card.count = count
  const explain = cut(input.explain, caps.explain)
  if (explain) card.explain = explain
  if (recommended) card.recommended = recommended
  const remaining = cut(input.remaining, caps.remaining)
  if (remaining) card.remaining = remaining
  const note = cut(input.note, caps.note)
  if (note) card.note = note

  // A field cut to its cap keeps its whole text, for a tooltip where one can be drawn.
  const full: NonNullable<GameCard['full']> = {}
  const fullTitle = whole(input.title, caps.title)
  if (fullTitle) full.title = fullTitle
  const fullShort = whole(input.short, caps.short)
  if (fullShort) full.short = fullShort
  const fullExplain = whole(input.explain, caps.explain)
  if (fullExplain) full.explain = fullExplain
  const fullRemaining = whole(input.remaining, caps.remaining)
  if (fullRemaining) full.remaining = fullRemaining
  const fullNote = whole(input.note, caps.note)
  if (fullNote) full.note = fullNote
  if (Object.keys(full).length > 0) card.full = full

  return card
}

/** The status-line text while a card is up: `Game · 1-2 Structure · 2/4`. */
export function statusLine(card: GameCard): string {
  const where = card.levelTitle ? `${card.level} ${card.levelTitle}` : card.level
  const step = card.index && card.count ? ` · ${card.index}/${card.count}` : ''

  return `Game · ${where}${step}`
}

/** The dialog's chip beside the question, 12 characters at most. */
export function headerOf(card: GameCard): string {
  const text = card.kind === 'boss' ? `${card.level} boss` : card.index ? `${card.level} #${card.index}` : card.level

  return text.slice(0, 12)
}
