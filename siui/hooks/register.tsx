// siui: decisions as cards. The model calls the `card` tool once per
// decision; the hook draws the card in the question dialog, waits for the
// answer, records it in the project's decisions file and hands it back as the
// tool's result, so the model presents the next card in the same turn with no
// prose in between. `/siui` (and `/game`) turns the mode on and off, opens the board;
// while the mode is on, a system-prompt section holds the model to the
// protocol and AskUserQuestion is closed to it. The project may lower the
// caps, move the record and add pack folders in .claude/siui.json.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderInput } from 'claude-code'

import type { GameCard, GameDecision, GameEvent } from '../types'
import type { BoardPaths } from './board'
import {
  boardPaths,
  countdownOnBoard,
  BOARD_DISMISSED,
  drainPrompts,
  isChatFirst,
  ensureServer,
  isAutoOn,
  isBoardLive,
  openBrowser,
  publishCard,
  setAuto,
  waitOnBoard,
  writeStatus,
  setMode,
} from './board'
import { drawCard } from './card'
import { appendChat } from './chat'
import { forkRoads, mergeRoads, saveCheckpoint, switchRoad } from './checkpoint'
import type { RunFork } from './checkpoint'
import { MARKS, kindOf } from './marks'
import { defaultConfig, readConfig } from './config'
import { setWords } from './words'
import { homeOf, launch } from './paths'
import { claimPending, resetCost, setCostTarget, settleCost } from './cost'
import type { GameConfig } from './config'
import { CARD_DESCRIPTION, CARD_SCHEMA, cut, headerOf, isLevel, normaliseCard, statusLine } from './input'
import { mapSvg } from './map'
import { findPack, readPlan } from './pack'
import {
  ASK_REPLACED,
  DONE_DESCRIPTION,
  DONE_SCHEMA,
  EVENT_DESCRIPTION,
  EVENT_SCHEMA,
  FORK_DESCRIPTION,
  FORK_SCHEMA,
  NOTE_DESCRIPTION,
  NOTE_SCHEMA,
  PROTOCOL_SECTION,
  startPrompt,
} from './protocol'
import {
  addDecision,
  dropLast,
  ensureRun,
  hasCastle,
  hasWorld,
  lastWorldRun,
  monthLevel,
  openFork,
  openRun,
  parseLevel,
  putEvent,
  routeDecision,
  readRecord,
  resumeContext,
  statusText,
  summaryLines,
  targetOf,
  timeSuffix,
  writeRecord,
} from './record'
import type { GameRecord, Routed } from './record'
import { resolveSources, skillPaths } from './sources'

const TOOL_CARD = 'mcp__siui__card'
const TOOL_DONE = 'mcp__siui__done'
const TOOL_NOTE = 'mcp__siui__note'
const TOOL_EVENT = 'mcp__siui__event'
const TOOL_FORK = 'mcp__siui__fork'

/** The stage a level id names, without its road letter: "3-3b" → "3-3". */
function stageOf(level: string): string {
  const [w, l] = parseLevel(level)

  return `${w}-${l}`
}

/** Whether a card opens a new world: it names its pack and a world number not in the record. */
function opensWorld(record: GameRecord, current: GameCard): boolean {
  return current.pack !== undefined && current.world > 0 && !hasWorld(record, current.world)
}

/** Forks a stage of the open run: a checkpoint, two branches, road a on disk; the record remembers. */
async function doFork($: EngineInterface, root: string, recordRel: string, levelGiven: string): Promise<{ text: string; fork?: RunFork }> {
  const record = await readRecord($, root, recordRel)
  const run = openRun(record)
  if (!run) return { text: 'No world is open; nothing to fork.' }
  const level = stageOf(levelGiven)
  if (!/^\d+-\d+$/.test(level) || level === '0-0') return { text: 'Say which stage to fork, like 3-3.' }
  if (openFork(run)) return { text: `A fork is already open at ${openFork(run)?.level}; merge it first.` }
  const made = await forkRoads($, root, level)
  if ('error' in made) return { text: `No fork: ${made.error}.` }
  run.roads = { ...(run.roads ?? {}), [level]: made }
  run.levels[`${level}a`] = 'open'
  putEvent(record, {
    id: `checkpoint-fork-${level}-${timeSuffix(made.at)}`,
    kind: 'checkpoint',
    title: `Fork at ${level}`,
    text: `Roads a and b from here; road a on disk`,
    world: run.world,
    level,
    at: made.at,
    status: 'open',
    commit: made.checkpoint,
    branch: made.base,
  })
  await writeRecord($, root, record, recordRel)

  return { text: `Forked ${level}: roads a and b from checkpoint ${made.checkpoint.slice(0, 7)}; road a (${made.branches.a}) is on disk.`, fork: made }
}

/** Puts the other road on disk; the records of both roads are joined so each knows the other's answers. */
async function doRoad($: EngineInterface, root: string, recordRel: string, road: 'a' | 'b', levelGiven = ''): Promise<{ text: string; ok: boolean }> {
  const before = await readRecord($, root, recordRel)
  const run = openRun(before)
  if (!run) return { text: 'No world is open.', ok: false }
  const fork = levelGiven ? run.roads?.[stageOf(levelGiven)] : openFork(run)
  if (!fork || fork.merged !== undefined) return { text: 'No open fork to switch.', ok: false }
  if (fork.onDisk === road) return { text: `Road ${road} of ${fork.level} is on disk already.`, ok: true }
  const switched = await switchRoad($, root, fork, road)
  if ('error' in switched) return { text: `No switch: ${switched.error}.`, ok: false }
  // The tree now holds the other road's record: join what this road knew into it.
  const after = await readRecord($, root, recordRel)
  const target = after.runs.find(one => one.id === run.id)
  if (target) {
    for (const one of run.decisions) {
      if (!target.decisions.some(had => had.level === one.level && had.id === one.id)) target.decisions.push(one)
    }
    for (const level of Object.keys(run.levels)) if (target.levels[level] === undefined) target.levels[level] = run.levels[level]
    target.levelTitles = { ...(run.levelTitles ?? {}), ...(target.levelTitles ?? {}) }
    target.levelCounts = { ...(run.levelCounts ?? {}), ...(target.levelCounts ?? {}) }
    target.roads = { ...(run.roads ?? {}), ...(target.roads ?? {}), [fork.level]: { ...fork, onDisk: road } }
    target.levels[`${fork.level}${road}`] = target.levels[`${fork.level}${road}`] ?? 'open'
  }
  for (const one of before.events ?? []) {
    if (!(after.events ?? []).some(had => had.id === one.id)) putEvent(after, one)
  }
  await writeRecord($, root, after, recordRel)

  return { text: `Road ${road} of ${fork.level} is on disk now (${fork.branches[road]}).`, ok: true }
}

/** The castle's merge: the kept road into the base, the other tagged; the fork closes. */
async function doMerge($: EngineInterface, root: string, recordRel: string, keep: 'a' | 'b' | 'both', levelGiven = ''): Promise<{ text: string; ok: boolean }> {
  const record = await readRecord($, root, recordRel)
  const run = openRun(record)
  if (!run) return { text: 'No world is open.', ok: false }
  const fork = levelGiven ? run.roads?.[stageOf(levelGiven)] : openFork(run)
  if (!fork || fork.merged !== undefined) return { text: 'No open fork to merge.', ok: false }
  const merged = await mergeRoads($, root, fork, keep)
  if ('error' in merged) return { text: `No merge: ${merged.error}.`, ok: false }
  const kept: 'a' | 'b' = keep === 'b' ? 'b' : 'a'
  run.roads = { ...(run.roads ?? {}), [fork.level]: { ...fork, onDisk: kept, merged: keep, tag: merged.tag } }
  run.levels[`${fork.level}${kept}`] = 'done'
  if (keep !== 'both') run.levels[`${fork.level}${kept === 'a' ? 'b' : 'a'}`] = 'done'
  await writeRecord($, root, record, recordRel)

  return { text: `Merged road ${keep === 'both' ? 'a (road b kept as a branch)' : kept} of ${fork.level} into ${fork.base}; the other road is tagged ${merged.tag}.`, ok: true }
}
const EXPLAIN_WORDS = new Set(['?', 'explain', 'help', 'why', 'more'])
const SECTION_ID = 'siui:protocol'
/** Every verb of /game, once: the command's description and hint and the usage line all read it. */
const USAGE =
  'on [pack] | off | status | board [off] | pane [off] | auto [on|off] | checkpoint [title] | fork [level] | road a|b | merge a|b|both | back | reset'
const PANE = 'game-board'

const card = atom({ plugin: 'siui', key: 'card' } as const, null)
const isExplainOpen = atom({ plugin: 'siui', key: 'isExplainOpen' } as const, false)
const isGraphOpen = atom({ plugin: 'siui', key: 'isGraphOpen' } as const, false)
const isOn = atom({ plugin: 'siui', key: 'isOn' } as const, false)
const progress = atom({ plugin: 'siui', key: 'progress' } as const, null)
const history = atom({ plugin: 'siui', key: 'history' } as const, [])
const readPaths = atom({ plugin: 'siui', key: 'readPaths' } as const, [])

function storeKey(root: string): string {
  return `on:${root}`
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

/** A tool's stored output as a record: the JSON string the card tool answers, or a plain object. */
function parseOutput(output: unknown): Record<string, unknown> {
  if (typeof output === 'string') {
    try {
      const parsed = JSON.parse(output) as unknown

      return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {}
    } catch {
      return {}
    }
  }

  return output && typeof output === 'object' ? (output as Record<string, unknown>) : {}
}

// The user's words of the turn in flight, kept for the chat log until the turn
// completes with the model's answer.
let pendingUser = ''
/** True while the plugin itself asks through the dialog (a reset's confirmation): the guard lets it through. */
let ownAsk = false
/** Whether this turn ran a tool that does work (an edit, a command), not just a read or a siui tool. */
let turnHadWork = false
/** The main loop's running turn, for `/siui off` to end while a card waits. */
let heldTurn: string | undefined
/** Set by `/siui off` while a card waits: the card ends as switched off, not as skipped. */
let offRequested = false
/** The subagents seen at work lately, by id, with the time of their last tool call: the board says they run. */
const liveAgents = new Map<string, number>()
const AGENT_QUIET_MS = 120_000
function agentsRunning(): number {
  const now = Date.now()
  for (const [id, seen] of liveAgents) if (now - seen > AGENT_QUIET_MS) liveAgents.delete(id)

  return liveAgents.size
}
const READ_ONLY_TOOLS = new Set(['Read', 'Glob', 'Grep', 'Skill', 'ToolSearch', 'WebSearch', 'WebFetch', 'ListAgents', 'TodoWrite', 'AskUserQuestion', 'EnterPlanMode', 'ExitPlanMode', 'Monitor', 'TaskStop'])

/** A slug for a chat decision's title. */
function slugOf(title: string): string {
  const made = title.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40)

  return made.length >= 2 ? made : `chat-${Date.now().toString(36)}`
}

// The board's timers: a heartbeat the server lives by, and the prompt inbox
// drain. A hot reload cancels them with the old environment; `session.start`
// runs again after one and starts them anew where the board was on.
let stopBoardTimers: (() => void) | undefined

/** Starts the board's server when needed, the timers, and opens the page: `/siui board` and the card's Board button. */
async function openBoard($: EngineInterface, root: string): Promise<string> {
  const paths = await boardPaths($, root)
  // The configuration is read afresh here: this function stands outside the hooks' closure.
  const made = await readConfig($, root)
  const port = await ensureServer($, paths, root, made.record, made.boardPort, made.chatLog)
  if (port === undefined) return `The board server did not start; see ${paths.run}/server.log.`
  await $.store.set(`board:${root}`, true)
  startBoardTimers($, paths)
  const isOpened = await openBrowser($, port)
  const url = `http://127.0.0.1:${port}/`

  return isOpened
    ? `Board at ${url}: cards are answered there while the page is open; close the tab to answer in the chat.`
    : `Board at ${url}; open it in a browser. Cards are answered there while the page is open.`
}

/**
 * Leaves game mode. A card still waiting, on the board or in the chat's dialog, is let go first: the board's
 * wait is answered with a dismissal, the card leaves the page, and the turn that asked it is ended.
 */
async function switchOff($: EngineInterface, root: string): Promise<void> {
  const waiting = await read($, card)
  await $.store.set(storeKey(root), false)
  await update($, isOn, () => false)
  setMode(false)
  if (waiting) {
    offRequested = true
    try {
      const paths = await boardPaths($, root)
      await $.fs.write(`${paths.run}/inbox-answer.json`, `${JSON.stringify({ id: waiting.id, answer: '', dismiss: true, at: Date.now() / 1000 })}\n`)
      await publishCard($, paths, null)
      await writeStatus($, paths, 'idle')
    } catch {
      // no board folder: only the chat's dialog holds the card
    }
    if (heldTurn !== undefined) {
      try {
        await $.turn.abort({ turnId: heldTurn })
      } catch {
        // the turn ended meanwhile
      }
    }
  }
  await update($, card, () => null)
  $.ui.invalidate('tool.describe')
  $.ui.status(undefined)
  if (!waiting) {
    try {
      await writeStatus($, await boardPaths($, root), 'idle')
    } catch {
      // the board is a mirror
    }
  }
}

/** Turns game mode on from the board's button: the mode only; the person speaks next, or presses Continue. */
async function switchOn($: EngineInterface, root: string): Promise<void> {
  await $.store.set(storeKey(root), true)
  await update($, isOn, () => true)
  setMode(true)
  $.ui.invalidate('tool.describe')
  await writeStatus($, await boardPaths($, root), 'idle')
}

function startBoardTimers($: EngineInterface, paths: BoardPaths): void {
  if (stopBoardTimers) return
  const beat = $.clock.every(30_000, () => {
    void $.fs.write(paths.heartbeat, String(Date.now()))
  })
  const drain = $.clock.every(2_000, () => {
    // The board's Off button leaves a mark in the run folder: a slash command typed while a card waits is
    // held until the turn ends, a timer is not.
    void $.fs.exists(`${paths.run}/off`).then(async asked => {
      if (!asked) return
      await launch($, ['remove', `${paths.run}/off`])
      await switchOff($, await $.session.root())
      $.ui.toast('Game mode off, from the board')
    }).catch(() => undefined)
    void $.fs.exists(`${paths.run}/on`).then(async asked => {
      if (!asked) return
      await launch($, ['remove', `${paths.run}/on`])
      await switchOn($, await $.session.root())
      $.ui.toast('Game mode on, from the board')
    }).catch(() => undefined)
    void drainPrompts($, paths).then(prompts => {
      for (const text of prompts) void $.prompt.submit({ text, asUser: true })
    })
  })
  stopBoardTimers = () => {
    // The timers are handles with a cancel, not functions.
    beat.cancel()
    drain.cancel()
    stopBoardTimers = undefined
  }
}

async function runCommand($: EngineInterface, e: { args: string }) {
  const [verb = '', ...rest] = e.args.trim().split(/\s+/)
  const root = await $.session.root()
  // Bare, the command opens the board: the one thing most often wanted.
  const word = verb.toLowerCase() || 'board'

  if (word === 'on') {
    const pack = rest[0]
    config = await readConfig($, root)
    setWords(config.words)
    let packPath: string | undefined
    if (pack) {
      const record = await readRecord($, root, config.record)
      // A pack starts a new world; an open one is never overwritten with another plan.
      const open = openRun(record)
      if (open) return { text: `World ${open.world} is open; finish it or /siui reset first` }
      // A new run takes the project's next world number, whatever the pack's name says.
      const nextWorld = record.runs.reduce((most, one) => Math.max(most, one.world), 0) + 1
      const run = ensureRun(record, targetOf(root), pack, nextWorld, new Date().toISOString())
      const plan = await readPlan($, pack, root, config.packs)
      packPath = await findPack($, pack, root, config.packs)
      if (plan.length > 0) run.plan = plan
      await writeRecord($, root, record, config.record)
    }
    await $.store.set(storeKey(root), true)
    await update($, isOn, () => true)
    setMode(true)
    $.ui.invalidate('tool.describe')
    await writeStatus($, await boardPaths($, root), 'working', 'thinking')
    void $.prompt.submit({ text: startPrompt(pack, packPath) })

    return { text: pack ? `Game mode on, pack ${pack}. The first card is coming.` : 'Game mode on. Describe the task.' }
  }

  if (word === 'auto') {
    const paths = await boardPaths($, root)
    const wanted = (rest[0] ?? '').toLowerCase()
    const isWanted = wanted === 'on' ? true : wanted === 'off' ? false : !(await isAutoOn($, paths))
    await setAuto($, paths, isWanted)

    return {
      text: isWanted
        ? 'Auto-pilot on: a card with a recommendation is answered with it after eight seconds; a boss, a bug, a problem or a card without advice waits for you. /siui auto off stops it.'
        : 'Auto-pilot off.',
    }
  }

  if (word === 'off') {
    await switchOff($, root)

    return { text: 'Game mode off.' }
  }

  if (word === 'status') {
    const record = await readRecord($, root, config.record)
    const run = openRun(record)
    // A run that started before its pack was read, or before plans listed
    // their cards, learns the plan now.
    if (run && run.pack !== 'ad-hoc' && (run.plan === undefined || run.plan.some(level => level.cards === undefined))) {
      const plan = await readPlan($, run.pack, root, config.packs)
      if (plan.length > 0) {
        run.plan = plan
        await writeRecord($, root, record, config.record)
      }
    }

    return { text: statusText(record), context: [resumeContext(record)] }
  }

  if (word === 'board') {
    const paths = await boardPaths($, root)
    if ((rest[0] ?? '').toLowerCase() === 'off') {
      await $.fs.write(paths.stop, '')
      await $.store.set(`board:${root}`, false)
      stopBoardTimers?.()

      return { text: 'Board stopped; close its browser tab.' }
    }

    return { text: await openBoard($, root) }
  }

  if (word === 'fork') {
    const made = await doFork($, root, config.record, rest[0] ?? (await read($, progress))?.level ?? '')
    if (made.fork) await update($, progress, p => (p ? { ...p, level: `${made.fork?.level}a` } : p))

    return { text: made.text, context: made.fork ? [`Present the next card of the stage as level ${made.fork.level}a, with no text before it.`] : undefined }
  }

  if (word === 'road') {
    const road = (rest[0] ?? '').toLowerCase()
    if (road !== 'a' && road !== 'b') return { text: 'Usage: /siui road a|b' }
    const done = await doRoad($, root, config.record, road, rest[1] ?? '')
    if (done.ok) await update($, progress, p => (p && /^\d+-\d+[ab]$/.test(p.level) ? { ...p, level: `${stageOf(p.level)}${road}` } : p))

    return { text: done.text }
  }

  if (word === 'merge') {
    const keep = (rest[0] ?? '').toLowerCase()
    if (keep !== 'a' && keep !== 'b' && keep !== 'both') return { text: 'Usage: /siui merge a|b|both' }
    const done = await doMerge($, root, config.record, keep, rest[1] ?? '')

    return { text: done.text }
  }

  if (word === 'checkpoint') {
    const title = rest.join(' ').trim() || `Checkpoint ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`
    const saved = await saveCheckpoint($, root, title)
    if ('error' in saved) return { text: `No checkpoint: ${saved.error}.` }
    const record = await readRecord($, root, config.record)
    const run = openRun(record) ?? lastWorldRun(record)
    const where = await read($, progress)
    const levels = run ? Object.keys(run.levels) : []
    const now = new Date().toISOString()
    // On the side quests (the last card was one of world 0) the save point goes on this month's stage.
    const isSide = where?.world === 0
    const world = isSide ? 0 : run?.world ?? where?.world ?? 1
    putEvent(record, {
      id: `checkpoint-${slugOf(title)}-${timeSuffix(now)}`,
      kind: 'checkpoint',
      title,
      world,
      level: isSide ? monthLevel(now) : where?.level || levels[levels.length - 1] || `${world}-1`,
      at: now,
      status: 'open',
      commit: saved.commit,
      branch: saved.branch,
    })
    await writeRecord($, root, record, config.record)
    await update($, history, list => [...list].slice(-200))

    return { text: `Checkpoint saved: ${title} (${saved.commit.slice(0, 7)} on ${saved.branch}). Return to it from the board.` }
  }

  if (word === 'pane') {
    if ((rest[0] ?? '').toLowerCase() === 'off') {
      await $.ui.close({ id: PANE })

      return { text: 'Pane closed.' }
    }
    const opened = await $.ui.open({ id: PANE, title: 'Siui board' })
    if (opened.isPlaced) return { text: 'Pane open beside the chat; it follows every decision.' }

    return { text: `The pane is open but this surface does not place it: ${opened.reason}. \`/siui status\` draws the map instead.` }
  }

  if (word === 'back') {
    const record = await readRecord($, root, config.record)
    const run = openRun(record)
    // Never past a boss: an applied world is closed, and what it changed stays.
    if (!run) {
      const last = lastWorldRun(record)

      return { text: last ? `World ${last.world} was applied and closed; nothing to take back. \`/siui on\` starts a new world.` : 'Nothing to take back.' }
    }
    const dropped = dropLast(run)
    if (!dropped) return { text: 'Nothing to take back in this world yet.' }
    await writeRecord($, root, record, config.record)
    await update($, history, list => list.filter(one => !(one.level === dropped.level && one.id === dropped.id)))
    void $.prompt.submit({ text: `Present the card ${dropped.level}/${dropped.id} (${dropped.title}) again, with no text before it.` })

    return { text: `Took back ${dropped.level}/${dropped.id}.` }
  }

  if (word === 'reset') {
    const record = await readRecord($, root, config.record)
    const run = openRun(record)
    if (!run) return { text: 'No open run to reset.' }
    ownAsk = true
    let choice = ''
    try {
      choice = await $.ui.ask(`Abandon world ${run.world}? Its answers stay in the record.`, ['Keep', 'Abandon'])
    } catch {
      choice = ''
    } finally {
      ownAsk = false
    }
    if (choice !== 'Abandon') return { text: 'Kept.' }
    run.finishedAt = today()
    run.abandonedAt = today()
    await writeRecord($, root, record, config.record)
    await update($, history, () => [])
    await update($, progress, () => null)
    $.ui.status(undefined)

    return { text: `Run ${run.id} closed. \`/siui on <pack>\` starts a new one.` }
  }

  return { text: `Usage: /siui ${USAGE} (also /game). Packs: the plugin's scaffold, or the project's .claude/skills/decision-cards/packs.` }
}
// The project's configuration, read at the session's start and on `/siui on`; module-level so the
// command handler, a top-level function, can read it (a hot reload resets it; session.start re-reads).
let config: GameConfig = defaultConfig()

export const register: Register = on => {

  on('session.start', async ($, e, next) => {
    await resetCost($)
    await $.tool.register({
      name: 'card',
      description: CARD_DESCRIPTION,
      inputSchema: CARD_SCHEMA,
      isDeferred: false,
    })
    await $.tool.register({
      name: 'done',
      description: DONE_DESCRIPTION,
      inputSchema: DONE_SCHEMA,
      isDeferred: false,
    })
    await $.tool.register({
      name: 'note',
      description: NOTE_DESCRIPTION,
      inputSchema: NOTE_SCHEMA,
      isDeferred: false,
    })
    await $.tool.register({
      name: 'event',
      description: EVENT_DESCRIPTION,
      inputSchema: EVENT_SCHEMA,
      isDeferred: false,
    })
    await $.tool.register({
      name: 'fork',
      description: FORK_DESCRIPTION,
      inputSchema: FORK_SCHEMA,
      isDeferred: false,
    })
    for (const name of ['siui', 'game']) await $.command.register({
      name,
      description: `Game mode: decisions as cards. Bare, it opens the board. ${USAGE}`,
      argumentHint: USAGE,
    })
    await $.command.register({ name: 'siui-board', description: 'Opens the Siui board in the browser (the same as /siui board)', argumentHint: '[off]' })
    // The project root, not the directory the process started in: the store keys and the record go by it.
    const root = await $.session.root()
    config = await readConfig($, root)
    setWords(config.words)
    const wasOn = (await $.store.get(storeKey(root))) === true
    await update($, isOn, () => wasOn)
    setMode(wasOn)
    if (wasOn) $.ui.invalidate('tool.describe')
    // A card left over from an interrupted turn (the start runs again after a reload) would let
    // AskUserQuestion through the guard: no card is up when a start runs.
    await update($, card, () => null)
    const paths = await boardPaths($, root)
    // The board's leftovers of an interrupted session go too: a ghost card, a stale answer, auto-pilot on.
    await publishCard($, paths, null)
    try {
      if (await $.fs.exists(`${paths.run}/inbox-answer.json`)) await $.fs.write(`${paths.run}/inbox-answer.json`, '')
      if (await isAutoOn($, paths)) await setAuto($, paths, false)
    } catch {
      // the board is a mirror; a stale file costs nothing
    }
    if ((await $.store.get(`board:${root}`)) === true) startBoardTimers($, paths)
    await writeStatus($, paths, 'idle')

    return next(e)
  })

  // What the chat is doing, for the board's header: working through a turn
  // and its tools, idle between turns, waiting on a card, or ended.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) heldTurn = e.turnId
    if (e.agentId === undefined) await writeStatus($, await boardPaths($, await $.session.root()), 'working', 'thinking')

    return next(e)
  }).catch(($, e, next) => next(e))

  on('tool.call', async ($, e, next) => {
    const isMain = e.agentId === undefined
    const paths = await boardPaths($, await $.session.root())
    if (isMain && !String(e.tool).startsWith('mcp__siui__') && !READ_ONLY_TOOLS.has(String(e.tool))) turnHadWork = true
    if (!isMain) {
      // A subagent at work: the board shows it, even between the main chat's turns.
      liveAgents.set(String(e.agentId), Date.now())
      if ((await read($, card)) === null) await writeStatus($, paths, 'working', `${agentsRunning()} agent${agentsRunning() > 1 ? 's' : ''} running · ${String(e.tool)}`)
      return next(e)
    }
    if (e.tool !== TOOL_CARD) await writeStatus($, paths, 'working', String(e.tool))
    const ran = await next(e)
    if (e.tool !== TOOL_CARD) await writeStatus($, paths, 'working', 'thinking')

    return ran
  }).catch(($, e, next) => next(e))

  on('session.end', async ($, e, next) => {
    await writeStatus($, await boardPaths($, await $.session.root()), 'ended')

    return next(e)
  }).catch(($, e, next) => next(e))

  // What the model reads this session earns a solid source link on a card.
  on('tool.call', { tool: 'Read' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && ran.isError !== true && typeof e.file_path === 'string') {
      const path = e.file_path
      await update($, readPaths, list => (list.includes(path) ? list : [...list, path].slice(-500)))
    }

    return ran
  }).catch(($, e, next) => next(e))

  on('tool.call', { tool: 'Skill' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && ran.isError !== true && typeof e.skill === 'string') {
      const root = await $.session.root()
      const home = await homeOf($)
      const found: string[] = []
      for (const path of skillPaths(e.skill, root, home)) {
        if (await $.fs.exists(path)) found.push(path)
      }
      if (found.length > 0) {
        await update($, readPaths, list => [...list, ...found.filter(p => !list.includes(p))].slice(-500))
      }
    }

    return ran
  }).catch(($, e, next) => next(e))

  // The chat log: the user's words at submit, the model's answer at the turn's
  // end, with the level current at the time, so the board shows the chat
  // around each step.
  on('prompt.submit', async ($, e, next) => {
    // The person's own words come from the composer in a terminal and over a
    // bridge from an editor or app; the board's prompts come as this plugin's,
    // submitted as the person's own (`asUser`). A plugin's framed prompt (the
    // start prompt, a card to present again), another plugin's, a task's or a
    // peer's message is not theirs.
    const origin = e.origin as { kind: string; name?: string; asUser?: true }
    const isTheirs =
      origin.kind === 'plugin'
        ? origin.name === 'siui' && origin.asUser === true
        : ['composer', 'bridge', 'sdk'].includes(origin.kind)
    if (isTheirs && e.command === undefined && e.isMeta !== true) pendingUser = e.text

    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    if (e.agentId === undefined) {
      const user = pendingUser
      pendingUser = ''
      const where = await read($, progress)
      const root = await $.session.root()
      // Nothing is written into a project while game mode is off: no chat log, no mark, no cost.
      const isPlaying = await read($, isOn)
      if (isPlaying) {
        await appendChat($, root, config.chatLog, {
          world: where?.world ?? null,
          level: where?.level ?? '',
          user,
          assistant: e.reason === 'refusal' ? '' : e.answer,
        })
      }
      // A turn that did work after an answer marks that answer built: the board then offers no queue for it.
      if (isPlaying && turnHadWork && (await read($, card)) === null) {
        const record = await readRecord($, root, config.record)
        let latest: GameDecision | undefined
        for (const run of record.runs) for (const one of run.decisions) {
          if (one.via === 'chat' || one.via === 'skipped' || one.queued || one.built) continue
          if (!latest || Date.parse(one.at) > Date.parse(latest.at)) latest = one
        }
        if (latest && Date.now() - Date.parse(latest.at) < 60 * 60 * 1000) {
          latest.built = true
          await writeRecord($, root, record, config.record)
        }
      }
      turnHadWork = false
      heldTurn = undefined
      offRequested = false
      // The turn's cost goes to the decision that was current.
      try {
        if (isPlaying) {
          const costs = await readRecord($, root, config.record)
          if (await settleCost($, costs)) await writeRecord($, root, costs, config.record)
        }
      } catch {
        // the cost is a mirror of the session's ledger; a missed reading is caught up at the next
      }
      // Subagents still at work keep the board on "working" after the main turn ends.
      const running = agentsRunning()
      await writeStatus($, await boardPaths($, root), running > 0 ? 'working' : 'idle', running > 0 ? `${running} agent${running > 1 ? 's' : ''} running` : '')
    } else if (e.agentId !== undefined) {
      // A subagent finished: forget it; when none is left and the main chat is idle, say idle.
      liveAgents.delete(String(e.agentId))
      const root = await $.session.root()
      const running = agentsRunning()
      if (running === 0 && (await read($, card)) === null) await writeStatus($, await boardPaths($, root), 'idle')
      else if (running > 0) await writeStatus($, await boardPaths($, root), 'working', `${running} agent${running > 1 ? 's' : ''} running`)
    }

    return next(e)
  }).catch(($, e, next) => next(e))

  // A decision the user took in the chat, recorded by the model.
  on('tool.call', { tool: TOOL_NOTE }, async ($, e) => {
    const input = e as unknown as Record<string, unknown>
    const title = cut(input.title, 60)
    const answer = cut(input.decision, 240)
    if (title === '' || answer === '') return { deny: 'note: title and decision are required' }
    const root = await $.session.root()
    const where = await read($, progress)
    const record = await readRecord($, root, config.record)
    // A chat decision goes by topic: the open world when it names it (or names nothing),
    // a finished world when it names one of its stages, else the side world's month; a
    // world not in the record goes to the side world too, never opened by a note.
    const now = new Date().toISOString()
    const open = openRun(record)
    const given = typeof input.level === 'string' && isLevel(input.level.trim()) ? input.level.trim() : ''
    const wanted = given || (open ? where?.level ?? '' : '')
    const worldOf = wanted ? Number(wanted.split('-')[0]) : open?.world ?? lastWorldRun(record)?.world ?? 1
    const routed = routeDecision(record, targetOf(root), worldOf, wanted, now)
    const run = routed.run
    const level = routed.level || `${run.world}-0`
    const why = cut(input.why, 240)
    const rawSources = Array.isArray(input.sources) ? input.sources : []
    const sources: GameDecision['sources'] = []
    for (const raw of rawSources.slice(0, 6)) {
      const one = (raw ?? {}) as Record<string, unknown>
      if (typeof one.path !== 'string' || one.path.trim() === '') continue
      sources.push({
        path: one.path.trim(),
        role: one.role === 'out' || one.role === 'both' ? one.role : 'in',
        use: one.use === 'used' ? 'used' : 'maybe',
      })
    }
    const decision: GameDecision = {
      level,
      id: slugOf(title),
      title,
      answer,
      isOther: false,
      at: new Date().toISOString(),
      sources,
      via: 'chat',
      ...(why ? { why } : {}),
    }
    addDecision(run, decision, routed.levelTitle)
    const markKind = kindOf(input.mark)
    if (markKind) {
      putEvent(record, {
        id: `${markKind}-${decision.id}-${timeSuffix(decision.at)}`,
        kind: markKind,
        title,
        text: answer,
        world: run.world,
        level,
        at: decision.at,
        status: 'open',
      })
    }
    await writeRecord($, root, record, config.record)
    await update($, history, list => [...list, decision].slice(-200))

    return {
      result: JSON.stringify({ recorded: true, level, id: decision.id, ...(markKind ? { onTheMap: markKind } : {}) }),
      context: ['Recorded as a chat decision. Go on; no text about the record is needed.'],
    }
  }).catch(($, e, next) =>
    next.called ? next(e) : { result: JSON.stringify({ recorded: false, error: 'the note failed' }) },
  )

  // Something that popped up while building, dropped on the map or marked done.
  // Forks, road switches and merges, asked by the board or decided on a card.
  on('tool.call', { tool: TOOL_FORK }, async ($, e) => {
    const input = e as unknown as Record<string, unknown>
    const root = await $.session.root()
    const where = await read($, progress)
    const level = typeof input.level === 'string' ? input.level.trim() : where?.level ?? ''
    const road = input.road === 'a' || input.road === 'b' || input.road === 'both' ? input.road : undefined
    if (input.action === 'fork') {
      const made = await doFork($, root, config.record, level)
      if (made.fork) await update($, progress, p => (p ? { ...p, level: `${made.fork?.level}a` } : p))
      return { result: JSON.stringify({ ok: !!made.fork, text: made.text }), context: made.fork ? [`${made.text} Present the next card of the stage as level ${made.fork.level}a, with no text before it.`] : [made.text] }
    }
    if (input.action === 'road') {
      if (road === undefined || road === 'both') return { deny: 'road: give "a" or "b"' }
      const done = await doRoad($, root, config.record, road, level)
      if (!done.ok) return { result: JSON.stringify({ ok: false, text: done.text }), context: [done.text] }
      await update($, progress, p => (p && /^\d+-\d+[ab]$/.test(p.level) ? { ...p, level: `${stageOf(p.level)}${road}` } : p))
      return { result: JSON.stringify({ ok: true, text: done.text }), context: [`${done.text} Go on with that road's cards, level ${stageOf(level || where?.level || '')}${road}.`] }
    }
    if (input.action === 'merge') {
      if (road === undefined) return { deny: 'merge: give the road kept, "a", "b" or "both"' }
      const done = await doMerge($, root, config.record, road, level)
      return { result: JSON.stringify({ ok: done.ok, text: done.text }), context: [done.text] }
    }

    return { deny: 'fork: action must be fork, road or merge' }
  }).catch(($, e, next) => (next.called ? next(e) : { result: JSON.stringify({ ok: false, error: 'the fork tool failed' }) }))

  on('tool.call', { tool: TOOL_EVENT }, async ($, e) => {
    const input = e as unknown as Record<string, unknown>
    const kind = kindOf(input.kind)
    const title = cut(input.title, 60)
    if (!kind || title === '') return { deny: 'event: kind (bug, feature, problem, check, jump, save) and title are required' }
    const root = await $.session.root()
    const where = await read($, progress)
    const record = await readRecord($, root, config.record)
    const run = openRun(record) ?? lastWorldRun(record)
    const given = typeof input.level === 'string' && isLevel(input.level.trim()) ? input.level.trim() : ''
    const now = new Date().toISOString()
    // The side quests (world 0, or a level written "0-…") keep their marks by month, like their decisions.
    const worldGiven = typeof input.world === 'number' && Number.isInteger(input.world) && input.world >= 0 ? input.world : undefined
    const isSide = worldGiven === 0 || given.startsWith('0-') || (worldGiven === undefined && given === '' && where?.world === 0)
    const world = isSide ? 0 : worldGiven ?? run?.world ?? where?.world ?? 1
    const levels = run ? Object.keys(run.levels) : []
    const level = isSide ? monthLevel(now) : given || where?.level || levels[levels.length - 1] || `${world}-1`
    // The event named: by its exact id, else by its slug (the id without the kind prefix and the time suffix), the open one first.
    const keyOf = (id: string) => id.replace(/^(enemy|powerup|challenge|check|pipe|checkpoint)-/, '').replace(/-\d{6}$/, '')
    const wantedId = typeof input.id === 'string' ? input.id.trim() : ''
    const existing = wantedId === ''
      ? undefined
      : (record.events ?? []).find(one => one.id === wantedId) ??
        [...(record.events ?? [])].reverse().sort((a, b) => (a.status === 'open' ? 0 : 1) - (b.status === 'open' ? 0 : 1)).find(one => keyOf(one.id) === keyOf(wantedId))
    const status = input.status === 'done' ? 'done' : existing?.status ?? 'open'
    const event: GameEvent = {
      id: existing?.id ?? `${kind}-${slugOf(title)}-${timeSuffix(now)}`,
      kind,
      title,
      world: existing?.world ?? world,
      level: existing?.level ?? level,
      at: existing?.at ?? now,
      status,
      ...(status === 'done' ? { doneAt: existing?.doneAt ?? now } : {}),
    }
    const text = cut(input.text, 240)
    if (text) event.text = text
    else if (existing?.text) event.text = existing.text
    const size = typeof input.size === 'number' && Number.isInteger(input.size) ? Math.min(5, Math.max(1, input.size)) : existing?.size
    if (size) event.size = size
    const to = input.to && typeof input.to === 'object' ? (input.to as Record<string, unknown>) : undefined
    if (to && typeof to.world === 'number' && to.world >= 1) {
      event.to = { world: to.world, ...(isLevel(to.level) ? { level: to.level } : {}) }
    } else if (existing?.to) event.to = existing.to
    if (kind === 'checkpoint' && !existing) {
      const saved = await saveCheckpoint($, root, title)
      if ('error' in saved) return { result: JSON.stringify({ recorded: false, error: saved.error }) }
      event.commit = saved.commit
      event.branch = saved.branch
    } else if (existing?.commit) {
      event.commit = existing.commit
      event.branch = existing.branch
    }
    putEvent(record, event)
    await writeRecord($, root, record, config.record)
    await update($, history, list => [...list].slice(-200))
    $.ui.toast(
      kind === 'checkpoint' && !existing
        ? `Save point: ${title} (${(event.commit ?? '').slice(0, 7)})`
        : status === 'done'
          ? `${MARKS[kind].name} ${MARKS[kind].done}: ${title}`
          : `${MARKS[kind].name} on the map: ${title}`,
    )

    return {
      result: JSON.stringify({ recorded: true, id: event.id, world: event.world, level: event.level, status }),
      context: ['Dropped on the map. Go on; no text about it is needed.'],
    }
  }).catch(($, e, next) =>
    next.called ? next(e) : { result: JSON.stringify({ recorded: false, error: 'the event failed' }) },
  )

  // While the mode is on, the model's own AskUserQuestion is closed; the
  // plugin's `$.ui.ask` passes, since the card atom is set while it asks.
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    if (!ownAsk && (await read($, isOn)) && (await read($, card)) === null) {
      return { deny: 'game mode is on: ask through mcp__siui__card, one decision per call.' }
    }

    return next(e)
  }).catch(($, e, next) => next(e))

  on('tool.describe', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const made = await next(e)

    return (await read($, isOn)) ? { ...made, description: ASK_REPLACED } : made
  })

  on('prompt.compose', async ($, e, next) => {
    const made = await next(e)
    if (!(await read($, isOn))) return made

    return {
      sections: [
        ...made.sections.filter(section => section.id !== SECTION_ID),
        { id: SECTION_ID, text: PROTOCOL_SECTION, scope: 'session' },
      ],
    }
  })

  on('tool.call', { tool: TOOL_CARD }, async ($, e) => {
    const root = await $.session.root()
    // The configuration is read afresh on every card: the board may have switched the universe meanwhile.
    config = await readConfig($, root)
    setWords(config.words)
    const made = normaliseCard(e as unknown as Record<string, unknown>, config.caps)
    if (typeof made === 'string') return { deny: `card: ${made}` }

    const home = await homeOf($)
    const seen = await read($, readPaths)
    const { sources, downgraded } = await resolveSources($, made.sources, root, home, seen)
    const current: GameCard = { ...made, sources }

    await update($, isExplainOpen, () => false)
    await update($, card, () => current)
    $.ui.status(statusLine(current))

    const labels = current.options.map(option => option.label)
    const paths = await boardPaths($, root)
    let answer: string | undefined
    let isAuto = false

    // Auto-pilot: a decision card with a recommendation, not a bug or a problem, is
    // answered with the recommendation after a countdown, unless a hand or a switch-off
    // comes first. A boss, an info card, a marked bug or problem, or no advice hands back.
    const mayAuto =
      current.kind === 'decision' && current.recommended !== undefined && current.mark !== 'bug' && current.mark !== 'problem'
    if (mayAuto && (await isAutoOn($, paths)) && !(await isChatFirst($, paths))) {
      const seconds = 8
      await publishCard($, paths, { ...current, autoUntil: Date.now() + seconds * 1000 } as GameCard)
      await writeStatus($, paths, 'waiting', `${current.title} · auto in ${seconds}s`)
      $.ui.status(`${statusLine(current)} · auto in ${seconds}s`)
      const got = await countdownOnBoard($, paths, current.id, seconds)
      if (got === 'auto') {
        answer = current.recommended
        isAuto = true
      } else if (got !== undefined) {
        answer = got
      }
    }

    if (answer === undefined) {
      await publishCard($, paths, current)
      await writeStatus($, paths, 'waiting', current.title)
    }

    // The board answers while its page is open; the chat dialog otherwise.
    if (answer === undefined && !(await isChatFirst($, paths)) && (await isBoardLive($, paths))) {
      $.ui.status(`${statusLine(current)} · on the board`)
      $.ui.toast('The card is waiting on the board')
      answer = await waitOnBoard($, paths, current.id)
      if (answer === undefined) {
        // The page went away: the chat dialog takes the card, and the published card is cleared so a
        // page opened again does not answer into an inbox nobody reads.
        $.ui.status(statusLine(current))
        await publishCard($, paths, null)
      }
    }

    // A dismissal, from the chat dialog or the board's Dismiss button: the card is cleared and, when
    // it is a decision, kept as skipped: counted nowhere, presented again when the run goes on or
    // the board asks; an answer already given is never overwritten.
    const dismissed = async () => {
        await update($, card, () => null)
        await publishCard($, paths, null)
        $.ui.status(undefined)
        // `/siui off` let the card go: it is not a skipped card, the mode simply ended.
        if (offRequested) {
          offRequested = false

          return {
            result: JSON.stringify({ id: current.id, level: current.level, dismissed: true, off: true }),
            context: ['The user turned game mode off while this card waited. End the turn with one short line; ask nothing more.'],
          }
        }
        if (current.kind === 'decision') {
          const record = await readRecord($, root, config.record)
          const at = new Date().toISOString()
          // A skipped first card of a world not opened yet is kept nowhere: there is no world to keep it in.
          if (!opensWorld(record, current)) {
            const routed = routeDecision(record, targetOf(root), current.world, current.level, at)
            const run = routed.run
            const level = routed.level
            const had = run.decisions.find(one => one.level === level && one.id === current.id)
            if (!had || had.via === 'skipped') {
              addDecision(run, {
                level,
                id: current.id,
                title: current.title,
                answer: 'skipped',
                isOther: false,
                at,
                sources: [...current.sources, ...(current.extraSources ?? [])].map(source => ({ path: source.path, role: source.role, use: source.use })),
                via: 'skipped',
              }, routed.levelTitle ?? current.levelTitle, routed.levelTitle ? undefined : current.count)
              await writeRecord($, root, record, config.record)
            }
          }
        }

        return {
          result: JSON.stringify({ id: current.id, level: current.level, dismissed: true }),
          context: ['The user dismissed the card; it is kept as skipped and comes again later. End the turn with one short line and wait.'],
        }
    }
    if (answer === BOARD_DISMISSED) return dismissed()
    if (answer !== undefined && /^fork here$/i.test(answer.trim()) && current.kind === 'decision') {
      await update($, card, () => null)
      await publishCard($, paths, null)
      await writeStatus($, paths, 'working', 'forking')
      const made = await doFork($, root, config.record, current.level)
      if (made.fork) await update($, progress, p => (p ? { ...p, level: `${made.fork?.level}a` } : p))
      return {
        result: JSON.stringify({ id: current.id, level: current.level, forked: !!made.fork, text: made.text }),
        context: [made.fork ? `${made.text} Present this card again as level ${made.fork.level}a, with no text before it.` : made.text],
      }
    }

    if (answer === undefined) {
      try {
        for (;;) {
          answer = await $.ui.ask(current.question, { options: labels, header: headerOf(current) })
          if (EXPLAIN_WORDS.has(answer.trim().toLowerCase()) && current.explain) {
            await update($, isExplainOpen, () => true)
            continue
          }
          break
        }
      } catch {
        return dismissed()
      }
    }

    await update($, card, () => null)
    await publishCard($, paths, null)
    await writeStatus($, paths, 'working', 'thinking')
    const isOther = !labels.includes(answer)
    const decision: GameDecision = {
      level: current.level,
      id: current.id,
      title: current.title,
      answer,
      isOther,
      at: new Date().toISOString(),
      sources: [...current.sources, ...(current.extraSources ?? [])].map(source => ({ path: source.path, role: source.role, use: source.use })),
      ...(isAuto ? { via: 'auto' as const } : {}),
    }

    if (current.kind === 'decision') {
      const record = await readRecord($, root, config.record)
      // A card that names its pack and a world number not in the record opens that world (the
      // first card after /siui on, or the board's "New world"). Any other goes by topic: the
      // open world when named, a world (even finished) when the card names one of its stages,
      // the side world's month otherwise, a world number never seen included.
      const isNewWorld = opensWorld(record, current)
      const routed: Routed = isNewWorld
        ? { run: ensureRun(record, targetOf(root), current.pack ?? 'ad-hoc', current.world, decision.at), level: current.level }
        : routeDecision(record, targetOf(root), current.world, current.level, decision.at)
      const run = routed.run
      if (routed.level !== decision.level) decision.level = routed.level
      if (current.mark) {
        // The card was raised by a discovery or a requirement: it lands on the stage.
        const markKind = kindOf(current.mark) ?? 'challenge'
        putEvent(record, {
          id: `${markKind}-${current.id}-${timeSuffix(decision.at)}`,
          kind: markKind,
          title: current.title,
          text: `Answer: ${answer}`,
          world: run.world,
          level: decision.level,
          at: decision.at,
          status: 'open',
        })
      }
      if (isNewWorld && current.pack && run.plan === undefined) {
        // The first card of a new world names its pack: the run takes the plan.
        const plan = await readPlan($, current.pack, root, config.packs)
        if (plan.length > 0) run.plan = plan
      }
      // What was spent up to this answer belongs to the decision before; from here on, to this one.
      await settleCost($, record)
      const hadCost = run.decisions.find(one => one.level === decision.level && one.id === decision.id)?.cost ?? 0
      const ownCost = hadCost + claimPending()
      if (ownCost > 0) decision.cost = Math.round(ownCost * 10000) / 10000
      addDecision(run, decision, routed.levelTitle ?? current.levelTitle, routed.levelTitle ? undefined : current.count)
      setCostTarget(run.id, decision.level, decision.id)
      await writeRecord($, root, record, config.record)
      await update($, history, list => [...list.filter(one => !(one.level === decision.level && one.id === decision.id)), decision].slice(-200))
      const decided = run.decisions.filter(one => one.level === decision.level).length
      await update($, progress, () => ({
        target: run.target,
        world: run.world,
        level: decision.level,
        decided,
        count: current.count ?? decided,
      }))
    } else if (current.kind === 'boss') {
      // A boss card is not a decision, but its level is the castle: the run remembers it, so the world ends in one.
      const record = await readRecord($, root, config.record)
      const run = openRun(record)
      if (run) {
        if (run.levels[current.level] === undefined) run.levels[current.level] = 'open'
        if (current.levelTitle) run.levelTitles = { ...(run.levelTitles ?? {}), [current.level]: current.levelTitle }
        await writeRecord($, root, record, config.record)
      }
    }

    const notes = [
      `Answer to ${current.level}/${current.id}: "${answer}"${isOther ? " (the user's own words)" : isAuto ? ' (auto-pilot took the recommendation)' : ''}.`,
      'Present the next card now, with no text before it.',
    ]
    if (downgraded.length > 0) {
      notes.push(
        `These inputs were marked used but you never read them this session, so they were drawn dashed: ${downgraded.join(', ')}. Read an input before marking it used.`,
      )
    }

    return {
      result: JSON.stringify({
        id: current.id,
        level: current.level,
        answer,
        isOther,
        ...(isAuto ? { isAuto: true } : {}),
        sources: decision.sources,
      }),
      context: [notes.join(' ')],
    }
  }).catch(async ($, e, next) => {
    await update($, card, () => null)
    try {
      const paths = await boardPaths($, await $.session.root())
      await publishCard($, paths, null)
      await writeStatus($, paths, 'idle')
    } catch {
      // the board is a mirror
    }
    $.ui.status(undefined)
    if (next.called) return next(e)

    return {
      result: JSON.stringify({ dismissed: true, error: 'the card failed' }),
      context: ['The card could not be shown. End the turn with one short line.'],
    }
  })

  on('tool.call', { tool: TOOL_DONE }, async ($, e) => {
    const root = await $.session.root()
    const record = await readRecord($, root, config.record)
    const run = openRun(record)
    if (!run) return { result: JSON.stringify({ lines: [], file: config.record, error: 'no open run' }) }
    // No castle answered on the last level: not refused, but asked first, politely, with one card.
    if ((e as unknown as { confirm?: unknown }).confirm !== true && !hasCastle(run)) {
      return {
        result: JSON.stringify({ closed: false, askFirst: true, file: config.record }),
        context: [
          `World ${run.world} has no castle: no boss card was answered on its last level. Ask the user politely with one card`,
          'whether to close the world without a castle (options "Close anyway" and "The castle first"). On "Close anyway",',
          'call done again with confirm: true; otherwise present the boss card.',
        ],
      }
    }
    const fork = openFork(run)
    if (fork) {
      const keep = (e as unknown as { merge?: unknown }).merge
      if (keep !== 'a' && keep !== 'b' && keep !== 'both') {
        return { result: JSON.stringify({ lines: [], file: config.record, error: `the stage ${fork.level} is forked; give merge: "a", "b" or "both"` }) }
      }
      const merged = await doMerge($, root, config.record, keep)
      if (!merged.ok) return { result: JSON.stringify({ lines: [], file: config.record, error: merged.text }) }
      Object.assign(record, await readRecord($, root, config.record))
    }
    // After a merge the record was read again: `run2` is the run as it stands now, `run` a stale copy.
    const run2 = openRun(record) ?? run
    run2.finishedAt = today()
    for (const level of Object.keys(run2.levels)) run2.levels[level] = 'done'
    for (const level of run2.plan ?? []) run2.levels[level.level] = 'done'
    await writeRecord($, root, record, config.record)
    $.ui.status(undefined)
    await update($, progress, () => null)
    $.ui.toast(`World ${run2.world} complete`)
    // The applied world is a save point: a checkpoint at the commit the model just made.
    const saved = await saveCheckpoint($, root, `World ${run2.world} applied`)
    if (!('error' in saved)) {
      const now = new Date().toISOString()
      const bossLevel = (run2.plan ?? []).map(one => one.level).pop() ?? Object.keys(run2.levels).pop() ?? `${run2.world}-4`
      putEvent(record, {
        id: `checkpoint-world-${run2.world}-applied`,
        kind: 'checkpoint',
        title: `World ${run2.world} applied`,
        world: run2.world,
        level: bossLevel,
        at: now,
        status: 'open',
        commit: saved.commit,
        branch: saved.branch,
      })
      await writeRecord($, root, record, config.record)
    }

    return {
      result: JSON.stringify({ lines: summaryLines(run2, today(), config.record), file: config.record }),
      context: ['Append the lines where the pack says, or nowhere when it says nothing. Write no other file.'],
    }
  }).catch(($, e, next) =>
    next.called ? next(e) : { result: JSON.stringify({ lines: [], file: config.record, error: 'done failed' }) },
  )

  // One handler, two names: /siui and /game do the same.
  on('command.run', { command: 'siui' }, async ($, e) => runCommand($, e)).catch(($, e, next) => (next.called ? next(e) : { text: `siui: ${next.error.message ?? next.error.kind}` }))
  on('command.run', { command: 'siui-board' }, async ($, e) => runCommand($, { args: `board ${e.args}` })).catch(($, e, next) => (next.called ? next(e) : { text: `siui: ${next.error.message ?? next.error.kind}` }))
  on('command.run', { command: 'game' }, async ($, e) => runCommand($, e)).catch(($, e, next) => (next.called ? next(e) : { text: `siui: ${next.error.message ?? next.error.kind}` }))

  on('ui.render', { component: 'AskUserQuestion' }, async ($, e, next) => {
    const current = await read($, card)
    if (current === null) return next(e)
    const root = await $.session.root()
    const toggles = {
      isExplainOpen: await read($, isExplainOpen),
      isGraphOpen: await read($, isGraphOpen),
      toggleExplain: () => {
        void update($, isExplainOpen, open => !open)
      },
      toggleGraph: () => {
        void update($, isGraphOpen, open => !open)
      },
      // The Board button: its press is served by the ui.press hook below, a hook of its own.
      openBoard: () => {},
    }
    const engine = await next(e)

    return drawCard($, e, current, toggles, engine)
  })

  // The card's Board button: the same as /siui board, in a hook of its own (the press's closure
  // runs in the drawing's environment; a hook has its own budget and a sure `$`). A log line per
  // press lands in the run folder, for when nothing seems to happen.
  on('ui.press', { plugin: 'siui', element: 'board' }, async ($, e) => {
    const root = await $.session.root()
    const paths = await boardPaths($, root)
    const log = async (line: string) => {
      try {
        const had = (await $.fs.exists(`${paths.run}/board-button.log`)) ? await $.fs.read(`${paths.run}/board-button.log`) : ''
        await $.fs.write(`${paths.run}/board-button.log`, `${had.slice(-4000)}${new Date().toISOString()} ${line}\n`)
      } catch {
        // the log is a courtesy
      }
    }
    await log(`pressed on ${e.surface}`)
    try {
      const text = await openBoard($, root)
      await log(text)
      $.ui.toast(`${text} This card is answered here.`)
    } catch (error) {
      await log(`failed: ${String(error)}`)
      $.ui.toast(`The board did not open: ${String(error)}`)
    }

    return { element: e.element }
  })

  // The board: a pane beside the chat with the world map, redrawn after every
  // decision (reading the history atom subscribes the drawing to it).
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Markdown } = $.ui.resolve(e)
    await read($, history)
    const root = await $.session.root()
    const record = await readRecord($, root, config.record)
    const run = openRun(record) ?? lastWorldRun(record)
    if (!run) return <Text dimColor>No run yet. /siui on [pack] starts one.</Text>
    if (e.surface === 'terminal') return <Markdown text={statusText(record)} />
    const { Svg } = $.ui.resolve(e as RenderInput<'Pane', 'vscode'>)
    const map = mapSvg(run)

    return (
      <Box flexDirection="column">
        <Svg source={map.source} alt={map.alt} isInteractive />
        <Markdown text={statusText(record)} dimColor />
      </Box>
    )
  })

  // `/siui status` draws the world map where the surface draws pictures; the
  // text stands where it does not (the terminal).
  for (const name of ['siui', 'game', 'siui-board']) on('ui.render', { component: 'CommandOutput', props: { command: name } }, async ($, e, next) => {
    if (e.surface === 'terminal' || !/^status\b/i.test(e.props.args.trim()) || e.props.isErrored) return next(e)
    const root = await $.session.root()
    const record = await readRecord($, root, config.record)
    const run = openRun(record) ?? lastWorldRun(record)
    if (!run) return next(e)
    const { Box, Svg, Markdown } = $.ui.resolve(e)
    const map = mapSvg(run)

    return (
      <Box flexDirection="column">
        <Svg source={map.source} alt={map.alt} isInteractive />
        <Markdown text={e.props.text} dimColor />
      </Box>
    )
  })

  // A decided card leaves one dim line in the transcript, not a tool dump.
  on('ui.render', { component: 'ToolUse', props: { tool: TOOL_CARD } }, async ($, e, next) => {
    if (e.props.isExpanded === true) return next(e)
    const { Box, Text, Button } = $.ui.resolve(e)
    const input = (e.props.input ?? {}) as Record<string, unknown>
    const output = parseOutput(e.props.output)
    const level = typeof input.level === 'string' ? input.level : '?'
    const title = typeof input.title === 'string' ? input.title : 'card'
    const end = e.props.isRunning
      ? '… waiting'
      : output.dismissed === true
        ? '→ dismissed'
        : typeof output.answer === 'string'
          ? `→ ${output.answer}`
          : e.props.isErrored
            ? '→ refused'
            : ''

    // The row ends in a Board button, served by the same ui.press hook as the card's.
    return (
      <Box flexDirection="row" gap={1}>
        <Text dimColor>
          {level} · {title} {end}
        </Text>
        <Button key="board" plain dimColor label="Board" onPress={() => {}} />
      </Box>
    )
  })

  on('ui.render', { component: 'ToolResult', props: { tool: TOOL_CARD } }, async ($, e, next) => {
    if (e.props.isExpanded === true) return next(e)
    const { Text } = $.ui.resolve(e)
    const output = parseOutput(e.props.output)

    return <Text dimColor>{output.dismissed === true ? 'dismissed' : 'recorded'}</Text>
  })
}
