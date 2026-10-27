// The record of decisions: one JSON file in the project that runs the mode,
// `.claude/decisions.json`, holding every run (one per world) with its levels
// and the answers. Read-modify-write on every answer; a re-answer of the same
// level/id replaces the entry. The board's server writes the same file (queue
// marks, notes, events), so a write merges over what is on disk first and
// lands through a rename, never half-written.

import type { EngineInterface } from 'claude-code'

import type { GameDecision, GameEvent } from '../types'
import type { RunFork } from './checkpoint'
import type { PlanLevel } from './pack'
import { nextCardOf } from './pack'
import { words } from './words'

export const RECORD_PATH = '.claude/decisions.json'

/** The time part of an ISO stamp as an id suffix: "2026-10-26T14:05:09.123Z" → "140509". */
export function timeSuffix(iso: string): string {
  return iso.slice(11, 19).replace(/:/g, '')
}

export type GameRun = {
  id: string
  target: string
  pack: string
  world: number
  startedAt: string
  finishedAt: string | null
  /** Set when the run was closed by a reset, not by a boss: the world shows as abandoned. */
  abandonedAt?: string
  levels: Record<string, 'open' | 'done'>
  /** Level titles and card counts, as the cards named them. */
  levelTitles?: Record<string, string>
  levelCounts?: Record<string, number>
  /** The pack's levels in order, read when the run started. */
  plan?: PlanLevel[]
  decisions: GameDecision[]
  /** The stages forked, by level: two roads each, a and b, one on disk until the castle merges. */
  roads?: Record<string, RunFork>
}

/** The fork still open on a run, if any: not merged yet. */
export function openFork(run: GameRun): RunFork | undefined {
  return Object.values(run.roads ?? {}).find(one => one.merged === undefined)
}

/** A level id split into its numbers and its road letter: "3-3b" → [3, 3, "b"]. */
export function parseLevel(level: string): [number, number, string] {
  const m = /^(\d+)-(\d+)([ab])?$/.exec(level)

  return m ? [Number(m[1]), Number(m[2]), m[3] ?? ''] : [0, 0, '']
}

export type GameRecord = { format: 1; runs: GameRun[]; events?: GameEvent[] }

/** One level as the map and the status show it. */
export type LevelView = {
  level: string
  title: string
  count: number | undefined
  /** Cards answered; chat decisions count toward no level. */
  decided: number
  state: 'done' | 'current' | 'open' | 'ahead'
  isBoss: boolean
  /** The answered cards. */
  decisions: GameDecision[]
  /** The decisions taken in the chat and recorded with the `note` tool. */
  chat: GameDecision[]
  /** The cards dismissed: kept as skipped, counted nowhere, presented again later. */
  skipped: GameDecision[]
}

export function isSkipped(one: GameDecision): boolean {
  return one.via === 'skipped'
}

export function isChatDecision(one: GameDecision): boolean {
  return one.via === 'chat'
}

export function emptyRecord(): GameRecord {
  return { format: 1, runs: [], events: [] }
}

/** Adds an event, or updates the one with its id (title, text, status, where it leads). */
export function putEvent(record: GameRecord, event: GameEvent): GameEvent {
  const events = record.events ?? []
  const at = events.findIndex(one => one.id === event.id)
  if (at >= 0) events[at] = { ...events[at], ...event }
  else events.push(event)
  record.events = events

  return events[at >= 0 ? at : events.length - 1] as GameEvent
}

export function recordPath(root: string, relative: string = RECORD_PATH): string {
  return `${root.replace(/\/$/, '')}/${relative.replace(/^\.?\//, '')}`
}

export function targetOf(root: string): string {
  return root.split('/').filter(Boolean).pop() ?? 'project'
}

function asText(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

/** A run as the file holds it, made whole: every list present, the world a number, the strings strings. */
function normaliseRun(raw: unknown): GameRun | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const given = raw as Record<string, unknown>
  const world = typeof given.world === 'number' ? given.world : Number(given.world)
  const levels: GameRun['levels'] = {}
  if (given.levels && typeof given.levels === 'object') {
    for (const [level, state] of Object.entries(given.levels as Record<string, unknown>)) {
      if (state === 'done' || state === 'open') levels[level] = state
    }
  }
  const decisions = (Array.isArray(given.decisions) ? given.decisions : []).filter(
    (one): one is GameDecision => !!one && typeof one === 'object' && typeof (one as GameDecision).id === 'string' && typeof (one as GameDecision).level === 'string',
  )
  const run: GameRun = {
    ...(given as Partial<GameRun>),
    id: asText(given.id, `run-${Number.isFinite(world) ? world : 0}`),
    target: asText(given.target, 'project'),
    pack: asText(given.pack, 'ad-hoc'),
    world: Number.isFinite(world) ? world : 0,
    startedAt: asText(given.startedAt),
    finishedAt: typeof given.finishedAt === 'string' ? given.finishedAt : null,
    levels,
    decisions,
  }
  if (typeof given.abandonedAt !== 'string') delete run.abandonedAt

  return run
}

/** An event as the file holds it, made whole; one without an id, a kind or a level is dropped. */
function normaliseEvent(raw: unknown): GameEvent | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const given = raw as Record<string, unknown>
  if (typeof given.id !== 'string' || typeof given.kind !== 'string') return undefined
  const world = typeof given.world === 'number' ? given.world : Number(given.world)

  return {
    ...(given as unknown as GameEvent),
    id: given.id,
    title: asText(given.title, given.id),
    world: Number.isFinite(world) ? world : 0,
    level: asText(given.level, '0-0'),
    at: asText(given.at),
    status: given.status === 'done' ? 'done' : 'open',
  }
}

/** The record a JSON text holds, every run and event normalised; undefined when the text is not a record. */
function parseRecord(text: string): GameRecord | undefined {
  try {
    const parsed = JSON.parse(text) as Partial<GameRecord>
    if (!parsed || !Array.isArray(parsed.runs)) return undefined
    const runs: GameRun[] = []
    for (const raw of parsed.runs) {
      const run = normaliseRun(raw)
      if (run) runs.push(run)
    }
    const events: GameEvent[] = []
    for (const raw of Array.isArray(parsed.events) ? parsed.events : []) {
      const event = normaliseEvent(raw)
      if (event) events.push(event)
    }

    return { format: 1, runs, events }
  } catch {
    return undefined
  }
}

/**
 * Reads the record. A file that is not a record (not JSON, or not its shape)
 * is kept aside under a dated name, the person is told in one line, and a
 * fresh record starts; no answer is ever overwritten in silence.
 */
export async function readRecord($: EngineInterface, root: string, relative: string = RECORD_PATH): Promise<GameRecord> {
  const path = recordPath(root, relative)
  if (!(await $.fs.exists(path))) return emptyRecord()
  let text = ''
  try {
    text = await $.fs.read(path)
  } catch {
    return emptyRecord()
  }
  if (text.trim() === '') return emptyRecord()
  const parsed = parseRecord(text)
  if (parsed) return parsed
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  const aside = `${path}.broken-${stamp}`
  try {
    await $.fs.write(aside, text)
    await $.fs.write(path, `${JSON.stringify(emptyRecord(), null, 2)}\n`)
    $.ui.toast(`The decisions file was unreadable; kept aside as ${aside.split('/').pop()}`)
  } catch {
    // nothing more to do: the fresh record below is returned either way
  }

  return emptyRecord()
}

/** The fields the board writes on a decision; kept from the file when the copy in memory lacks them. */
const BOARD_FIELDS = ['queued', 'started', 'built', 'notes', 'note'] as const

/**
 * Lays the record in memory over the one on disk, in place, so every run and
 * decision the caller holds stays the same object. A run in both keeps
 * memory's decisions, levels, titles, counts, roads and end dates (so a
 * decision taken back stays taken back), each decision taking what the board
 * wrote on the file's copy when memory lacks it. A run or an event only the
 * file has is added; an event in both is memory's.
 */
function mergeInto(memory: GameRecord, disk: GameRecord): void {
  for (const theirs of disk.runs) {
    const mine = memory.runs.find(one => one.id === theirs.id)
    if (!mine) {
      memory.runs.push(theirs)
      continue
    }
    for (const had of theirs.decisions) {
      const kept = mine.decisions.find(one => one.level === had.level && one.id === had.id)
      if (!kept) continue
      for (const field of BOARD_FIELDS) {
        if (kept[field] === undefined && had[field] !== undefined) (kept as Record<string, unknown>)[field] = had[field]
      }
    }
  }
  const events = memory.events ?? []
  for (const theirs of disk.events ?? []) {
    if (!events.some(one => one.id === theirs.id)) events.push(theirs)
  }
  memory.events = events
}

/**
 * Writes the record: what is on disk is read again and the record in memory
 * laid over it, so a mark the board wrote meanwhile survives; the text goes
 * to a temporary file beside the record and is renamed over it, so a reader
 * never sees half a file.
 */
export async function writeRecord(
  $: EngineInterface,
  root: string,
  record: GameRecord,
  relative: string = RECORD_PATH,
): Promise<void> {
  const path = recordPath(root, relative)
  if (await $.fs.exists(path)) {
    try {
      const disk = parseRecord(await $.fs.read(path))
      if (disk) mergeInto(record, disk)
    } catch {
      // the file could not be read: memory alone is written
    }
  }
  const text = `${JSON.stringify(record, null, 2)}\n`
  const temporary = `${path}.tmp-${Date.now()}`
  try {
    await $.fs.write(temporary, text)
    const moved = await $.process.run(['mv', '-f', temporary, path], { timeoutMs: 10_000 })
    if (moved.exitCode === 0) return
  } catch {
    // no temporary file or no rename: the plain write below stands in
  }
  await $.fs.write(path, text)
  void $.process.run(['rm', '-f', temporary], { timeoutMs: 10_000 }).catch(() => undefined)
}

export const SIDE_PACK = 'side'

/** The side world: world 0, never finished, where decisions that belong to no stage of a world go, kept by month. */
export function isSideRun(run: GameRun): boolean {
  return run.pack === SIDE_PACK || run.world === 0
}

/** The run in progress: the last world not finished, if any; the side world never counts as open. */
export function openRun(record: GameRecord): GameRun | undefined {
  for (let i = record.runs.length - 1; i >= 0; i -= 1) {
    const run = record.runs[i]
    if (run && run.finishedAt === null && !isSideRun(run)) return run
  }

  return undefined
}

/** The last world run, finished or not; never the side world. */
export function lastWorldRun(record: GameRecord): GameRun | undefined {
  for (let i = record.runs.length - 1; i >= 0; i -= 1) {
    const run = record.runs[i]
    if (run && !isSideRun(run)) return run
  }

  return undefined
}

/** The side world, made on first use. */
export function sideRun(record: GameRecord, target: string, now: string): GameRun {
  const had = record.runs.find(isSideRun)
  if (had) return had
  const run: GameRun = {
    id: `${target}/side`,
    target,
    pack: SIDE_PACK,
    world: 0,
    startedAt: now.slice(0, 10),
    finishedAt: null,
    levels: {},
    decisions: [],
  }
  record.runs.push(run)

  return run
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

/** The side world's stage for a time: one per month, `0-YYYYMM`. */
export function monthLevel(at: string): string {
  return `0-${at.slice(0, 4)}${at.slice(5, 7)}`
}

export function monthTitle(at: string): string {
  return `${MONTHS[Number(at.slice(5, 7)) - 1] ?? at.slice(5, 7)} ${at.slice(0, 4)}`
}

function hasStage(run: GameRun, level: string): boolean {
  return level !== '' && ((run.plan ?? []).some(one => one.level === level) || run.levels[level] !== undefined)
}

export type Routed = { run: GameRun; level: string; levelTitle?: string }

/** Whether a world of that number is in the record (finished or not); the side world never counts. */
export function hasWorld(record: GameRecord, world: number): boolean {
  return world > 0 && record.runs.some(one => !isSideRun(one) && one.world === world)
}

/** The side world's stage for now: where a decision goes that belongs to no stage of a world. */
export function sideRoute(record: GameRecord, target: string, now: string): Routed {
  return { run: sideRun(record, target, now), level: monthLevel(now), levelTitle: monthTitle(now) }
}

/**
 * Where a decision named for `world` and `level` goes, by topic: the open world
 * when it is the one named; a world (even finished) when the decision names one
 * of its stages; the side world otherwise, on this month's stage. A world not
 * in the record goes to the side world too: a card never opens a world by
 * naming a number (only `/game on` and a first card that names its pack do).
 */
export function routeDecision(record: GameRecord, target: string, world: number, level: string, now: string): Routed {
  if (world > 0) {
    const open = openRun(record)
    if (open && open.world === world) return { run: open, level }
    const named = record.runs.find(one => !isSideRun(one) && one.world === world)
    if (named && hasStage(named, level)) return { run: named, level }
  }

  return sideRoute(record, target, now)
}

/** The open run when it is `world`; else a new run for `world`, appended to the record. */
export function ensureRun(record: GameRecord, target: string, pack: string, world: number, now: string): GameRun {
  const open = openRun(record)
  if (open && open.world === world) return open
  const taken = new Set(record.runs.map(one => one.id))
  let id = `${target}/world-${world}`
  for (let n = 2; taken.has(id); n += 1) id = `${target}/world-${world}-${n}`
  const run: GameRun = {
    id,
    target,
    pack,
    world,
    startedAt: now.slice(0, 10),
    finishedAt: null,
    levels: {},
    decisions: [],
  }
  record.runs.push(run)

  return run
}

export function addDecision(run: GameRun, decision: GameDecision, levelTitle?: string, count?: number): void {
  const at = run.decisions.findIndex(one => one.level === decision.level && one.id === decision.id)
  if (at >= 0) run.decisions[at] = decision
  else run.decisions.push(decision)
  // A decision that lands after the world was applied joins it without reopening a level.
  if (run.levels[decision.level] !== 'done') run.levels[decision.level] = run.finishedAt !== null ? 'done' : 'open'
  if (levelTitle) run.levelTitles = { ...(run.levelTitles ?? {}), [decision.level]: levelTitle }
  if (count) run.levelCounts = { ...(run.levelCounts ?? {}), [decision.level]: count }
}

/**
 * Takes back the last card answered (by hand or by auto-pilot; never a chat
 * decision or a skipped card) and returns it, or undefined when there is none.
 * The level's open flag goes only when no decision of that level remains.
 */
export function dropLast(run: GameRun): GameDecision | undefined {
  for (let i = run.decisions.length - 1; i >= 0; i -= 1) {
    const one = run.decisions[i]
    if (!one || isChatDecision(one) || isSkipped(one)) continue
    run.decisions.splice(i, 1)
    if (run.levels[one.level] === 'open' && !run.decisions.some(left => left.level === one.level)) delete run.levels[one.level]

    return one
  }

  return undefined
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Whether a level's title names the boss: the word "boss", or the universe's own word for it. */
function isBossTitle(title: string): boolean {
  if (/\bboss\b/i.test(title)) return true
  const own = words().boss.trim()

  return own !== '' && own.toLowerCase() !== 'boss' && new RegExp(`\\b${escapeRegExp(own)}\\b`, 'i').test(title)
}

function levelOrder(a: string, b: string): number {
  const [aw, al, ar] = parseLevel(a)
  const [bw, bl, br] = parseLevel(b)

  return aw - bw || al - bl || ar.localeCompare(br)
}

/**
 * Every level of a run in order: the pack's plan first, then any level the
 * cards added, each with its title, count, answers and state. The current
 * level is the first not done with cards still to answer, or the first ahead.
 */
export function overviewOf(run: GameRun): LevelView[] {
  const ids = new Set<string>()
  for (const one of run.plan ?? []) ids.add(one.level)
  for (const level of Object.keys(run.levels)) ids.add(level)
  for (const one of run.decisions) ids.add(one.level)
  const ordered = [...ids].sort(levelOrder)
  const last = ordered[ordered.length - 1]

  const views: LevelView[] = ordered.map(level => {
    const planned = (run.plan ?? []).find(one => one.level === level)
    const title = run.levelTitles?.[level] ?? planned?.title ?? ''
    const count = run.levelCounts?.[level] ?? planned?.count
    const decisions = run.decisions.filter(one => one.level === level && !isChatDecision(one) && !isSkipped(one))
    const chat = run.decisions.filter(one => one.level === level && isChatDecision(one))
    const skipped = run.decisions.filter(one => one.level === level && isSkipped(one))
    const isBoss = isBossTitle(title) || (run.plan !== undefined && run.plan.length > 0 && level === last)
    const isDone = isSideRun(run)
      ? level !== monthLevel(new Date().toISOString())
      : run.finishedAt !== null || run.levels[level] === 'done' || (count !== undefined && decisions.length >= count)
    const state: LevelView['state'] = isDone ? 'done' : decisions.length > 0 ? 'open' : 'ahead'

    return { level, title, count, decided: decisions.length, state, isBoss, decisions, chat, skipped }
  })

  const current = views.find(one => one.state === 'open') ?? views.find(one => one.state === 'ahead')
  if (current && run.finishedAt === null && !isSideRun(run)) current.state = 'current'

  return views
}

/** Whether the run ends in a castle: its last level is the boss (boss cards themselves are not recorded). */
export function hasCastle(run: GameRun): boolean {
  const views = overviewOf(run)
  const last = views[views.length - 1]

  return last !== undefined && last.isBoss
}

/** One summary line per level, the form a changelog takes. */
export function summaryLines(run: GameRun, date: string, relative: string = RECORD_PATH): string[] {
  return overviewOf(run)
    .filter(one => one.decisions.length > 0 || one.chat.length > 0)
    .map(({ level, title, decisions, chat }) => {
      const answers = [
        ...decisions.map(one => `${one.id}=${one.answer}`),
        ...chat.map(one => `${one.id}=${one.answer} (chat)`),
      ].join('; ')
      const name = title ? ` (${title.toLowerCase()})` : ''

      return `- ${date} [decision] World ${run.world} level ${level}${name}: ${answers}. Record: ${relative}`
    })
}

function fitText(text: string, max: number): string {
  const flat = text.replace(/\s+/g, ' ').trim()

  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

/** The status as text: one line per level, the answers under the levels played. */
export function statusText(record: GameRecord): string {
  const run = openRun(record) ?? lastWorldRun(record)
  if (!run) return 'No run yet. Start one with `/game on <pack>`.'
  const views = overviewOf(run)
  const state = run.finishedAt ? `finished ${run.finishedAt}` : 'in progress'
  const lines = [`**World ${run.world}** · ${run.pack} · ${state} · ${run.decisions.length} decisions`]
  if (views.length === 0) lines.push('No level started yet.')
  for (const view of views) {
    const mark = view.state === 'done' ? '●' : view.state === 'current' ? '▶' : view.state === 'open' ? '◐' : '○'
    const progress = view.count !== undefined ? `${view.decided}/${Math.max(view.count, view.decided)}` : `${view.decided}`
    const name = view.title ? ` ${view.title}` : ''
    lines.push(`${mark} **${view.level}**${name} · ${progress}${view.isBoss ? ' · boss' : ''}`)
    for (const one of view.decisions) lines.push(`    ${fitText(one.title, 32)} → ${fitText(one.answer, 48)}${one.via === 'auto' ? ' _(auto)_' : ''}`)
    for (const one of view.chat) lines.push(`    ${fitText(one.title, 32)} → ${fitText(one.answer, 48)} _(chat)_`)
    for (const one of view.skipped) lines.push(`    ${fitText(one.title, 32)} → skipped, to present again`)
  }
  if (run.finishedAt === null) {
    const next = nextCardOf(run)
    const ahead = views.find(one => one.state !== 'done')
    lines.push(next ? `Next: ${next.level} ${next.title}` : ahead ? `Next: level ${ahead.level}${ahead.title ? ` ${ahead.title}` : ''}` : 'Next: the boss review')
  }

  return lines.join('\n')
}

/** What the model reads to resume: every answer of the run, one per line. */
export function resumeContext(record: GameRecord): string {
  const run = openRun(record)
  if (!run) return 'No open run.'
  const lines = run.decisions.map(one => `${one.level}/${one.id} (${one.title}): ${one.answer}${one.via === 'auto' ? ' [auto-pilot]' : ''}`)
  const ahead = overviewOf(run)
    .filter(one => one.state !== 'done')
    .map(one => `${one.level}${one.title ? ` ${one.title}` : ''}${one.count ? ` (${one.count} cards)` : ''}`)

  const next = nextCardOf(run)

  return [
    `Open run: world ${run.world}, pack ${run.pack}, target ${run.target}.`,
    ...lines,
    ahead.length > 0 ? `Levels not done: ${ahead.join(', ')}.` : 'Every level is done.',
    next ? `Next: present card ${next.level}/${next.id} (${next.title}), with no text before it.` : ahead.length > 0 ? `Next: the first card of level ${ahead[0]}.` : 'Next: the boss review, or /game on for a new world.',
  ].join('\n')
}
