// The HTML board: a local page served by board/server.py, started detached
// once per project and opened in the browser by `/siui board`. While the page
// is open (it polls the server every second, which touches a liveness mark),
// the live card is answered there: the card hook writes the card to the run
// folder and waits in board/wait.py, a host command whose time costs the hook
// nothing. Prompts typed on the page come back through an inbox the plugin
// drains on a timer. Runtime files live in the user's cache folder,
// ~/.cache/siui/<project slug>, owned by them alone; never in the
// project.

import type { EngineInterface } from 'claude-code'

import type { GameCard } from '../types'
import { homeOf, isWindows, join, launch, python, trimEnd } from './paths'

const DEFAULT_PORT = 5131
const RUN_FOLDER = 'siui'

/** What the wait returns when the page dismissed the card instead of answering it. */
export const BOARD_DISMISSED = '\u0000dismissed'
const ALIVE_MS = 12_000
const WAIT_SECONDS = '590'

export type BoardPaths = {
  run: string
  card: string
  alive: string
  heartbeat: string
  prompts: string
  stop: string
  server: string
  status: string
  /** Auto-pilot's switch, shared with the page: `{ "on": true }`. */
  auto: string
  /** The chat-first switch, shared with the page: `{ "on": true }` keeps cards in the chat dialog while the page is open. */
  chatFirst: string
  /** The board's key, written by its server: every call of the page carries it. */
  key: string
  /** How save points treat new files, as the person chose once: `{ "mode": "all" | "tracked" }`; the server reads it too. */
  saveMode: string
}

/** What the chat is doing, as the board's header shows it. */
export type ChatStatus = 'idle' | 'working' | 'waiting' | 'ended'

/**
 * The runtime files of a project's board: under `$HOME/.cache/siui/<slug>`,
 * on Windows under `%LOCALAPPDATA%\siui\<slug>`, or under /tmp when no home
 * is known. The board's server is given the same folder.
 */
export async function boardPaths($: EngineInterface, root: string): Promise<BoardPaths> {
  const slug = root.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(-80) || 'project'
  const home = (await homeOf($)) ?? ''
  const local = (await isWindows($)) ? trimEnd((await $.env.get('LOCALAPPDATA')) ?? '') : ''
  const run = local ? join(local, RUN_FOLDER, slug) : home ? join(home, '.cache', RUN_FOLDER, slug) : `/tmp/${RUN_FOLDER}/${slug}`

  return {
    run,
    card: `${run}/card.json`,
    alive: `${run}/alive`,
    heartbeat: `${run}/heartbeat`,
    prompts: `${run}/inbox-prompts.jsonl`,
    stop: `${run}/stop`,
    server: `${run}/server.json`,
    status: `${run}/status.json`,
    auto: `${run}/auto.json`,
    chatFirst: `${run}/chat-first.json`,
    key: `${run}/key`,
    saveMode: `${run}/save-points.json`,
  }
}

/** Whether cards stay in the chat dialog while the board page is open: the page's ⌨ switch. */
export async function isChatFirst($: EngineInterface, paths: BoardPaths): Promise<boolean> {
  if (!(await $.fs.exists(paths.chatFirst))) return false
  try {
    return (JSON.parse(await $.fs.read(paths.chatFirst)) as { on?: unknown }).on === true
  } catch {
    return false
  }
}

/** Whether auto-pilot is on, from the switch file the page and the chat both write. */
export async function isAutoOn($: EngineInterface, paths: BoardPaths): Promise<boolean> {
  if (!(await $.fs.exists(paths.auto))) return false
  try {
    return (JSON.parse(await $.fs.read(paths.auto)) as { on?: unknown }).on === true
  } catch {
    return false
  }
}

export async function setAuto($: EngineInterface, paths: BoardPaths, on: boolean): Promise<void> {
  await $.fs.write(paths.auto, `${JSON.stringify({ on, at: Date.now() })}\n`)
}

/**
 * Auto-pilot's countdown on a card: waits `seconds` for the person's own
 * answer on the board. Resolves their answer, `'auto'` when the time ran out
 * and auto-pilot is still on (the pick is the caller's), or undefined when it
 * was switched off meanwhile.
 */
export async function countdownOnBoard(
  $: EngineInterface,
  paths: BoardPaths,
  cardId: string,
  seconds: number,
): Promise<string | 'auto' | undefined> {
  const script = join($.plugin.root, 'board', 'wait.py')
  let ran
  try {
    ran = await $.process.run([...(await python($)), '-I', script, paths.run, cardId, String(seconds), 'auto'], { timeoutMs: 60_000 })
  } catch {
    return undefined
  }
  if (ran.exitCode === 0) {
    try {
      const parsed = JSON.parse(ran.stdout.trim()) as { answer?: unknown; dismissed?: unknown }
      if (parsed.dismissed === true) return BOARD_DISMISSED
      if (typeof parsed.answer === 'string' && parsed.answer.trim() !== '') return parsed.answer.trim()
    } catch {
      return undefined
    }
  }
  if (ran.exitCode === 3) return 'auto'

  return undefined
}

/** Whether game mode is on, as the hooks last said: the board shows Off or On by it. */
let modeOn = false
export function setMode(on: boolean): void {
  modeOn = on
}

/** Tells the board what the chat is doing; a tool's name or a card's title as the detail. */
export async function writeStatus($: EngineInterface, paths: BoardPaths, state: ChatStatus, detail = ''): Promise<void> {
  try {
    // The model the main loop runs, as /model shows it: the board names it beside the chat's state.
    let model = ''
    try {
      model = await $.session.model()
    } catch {
      // an engine without the call: the board shows no model
    }
    // What the session has used, as the status line counts it: its cost, the context window, the rate-limit windows.
    let usage: { usd?: number; context?: number; limits?: Array<{ kind: string; percent: number; resetsAt?: string }> } | undefined
    try {
      const used = await $.session.usage()
      usage = {
        ...(used.cost ? { usd: Math.round(used.cost.usd * 100) / 100 } : {}),
        ...(typeof used.context.percent === 'number' ? { context: Math.round(used.context.percent) } : {}),
        limits: used.rateLimits.map(one => ({ kind: one.kind, percent: Math.round(one.percentUsed), ...(one.resetsAt ? { resetsAt: one.resetsAt } : {}) })),
      }
    } catch {
      // an engine without the call: the board shows no usage
    }
    await $.fs.write(paths.status, `${JSON.stringify({ state, detail, at: Date.now(), mode: modeOn ? 'on' : 'off', ...(model ? { model } : {}), ...(usage ? { usage } : {}) })}\n`)
  } catch {
    // the board is a mirror; a missed status costs nothing
  }
}

/** Whether the page polled the server within the last few seconds. */
export async function isBoardLive($: EngineInterface, paths: BoardPaths): Promise<boolean> {
  if (!(await $.fs.exists(paths.alive))) return false
  try {
    const { mtimeMs } = await $.fs.stat(paths.alive)

    return (await $.clock.now()) - mtimeMs < ALIVE_MS
  } catch {
    return false
  }
}

/** The port the server took, from the file it writes; undefined when it is not running. */
export async function serverPort($: EngineInterface, paths: BoardPaths): Promise<number | undefined> {
  if (!(await $.fs.exists(paths.server))) return undefined
  try {
    const parsed = JSON.parse(await $.fs.read(paths.server)) as { port?: unknown }

    return typeof parsed.port === 'number' ? parsed.port : undefined
  } catch {
    return undefined
  }
}

/**
 * Makes the run folder, readable by the user alone, and refuses one that
 * somebody else owns (a folder planted under a shared path could feed the
 * board another's files). Resolves false when the folder cannot be used.
 */
async function ensureRunFolder($: EngineInterface, paths: BoardPaths): Promise<boolean> {
  return (await launch($, ['folder', paths.run])).exitCode === 0
}

/**
 * Starts the server detached unless this project's own answers already, and
 * returns its port. The server on the port the run folder names is this
 * project's when it proves it holds the folder's key. One that answers
 * without that proof (a board from before the key, or another program on a
 * stale port) is asked to end; when it stays, a fresh server starts on the
 * next port. The launcher starts it detached, so the command returns at once
 * and the server lives on; the server exits by itself when the heartbeat
 * stops.
 */
export async function ensureServer(
  $: EngineInterface,
  paths: BoardPaths,
  root: string,
  record: string,
  port: number = DEFAULT_PORT,
  chatLog: string = '.claude/chat-log.jsonl',
): Promise<number | undefined> {
  if (!(await ensureRunFolder($, paths))) {
    $.ui.toast(`The board's folder ${paths.run} is not yours; the board did not start.`)

    return undefined
  }
  await $.fs.write(paths.heartbeat, String(Date.now()))
  // A stop file left by `board off` would end the server we are about to reuse or start.
  if (await $.fs.exists(paths.stop)) await launch($, ['remove', paths.stop])
  const running = await serverPort($, paths)
  let startAt = port
  if (running !== undefined) {
    let there = await whoServes($, paths, running)
    if (there === 'ours') return running
    if (there === 'other') {
      // What the port file names answers but cannot prove it holds the key: a board from before the key, still
      // running, or another program on its port. It is asked to end, so no board without a key is left up.
      await $.fs.write(paths.stop, '')
      for (let i = 0; i < 24 && there === 'other'; i += 1) {
        await $.clock.sleep(250)
        there = await whoServes($, paths, running)
      }
      await launch($, ['remove', paths.stop])
      if (there === 'other') startAt = running + 1
    }
  }
  const ipc = (await $.env.get('VSCODE_IPC_HOOK_CLI')) ?? ''
  const startedAt = Date.now()
  await launch($, [
    'start',
    ...(ipc ? ['--ipc', ipc] : []),
    '--root',
    root,
    '--run',
    paths.run,
    '--record',
    record,
    '--chat',
    chatLog,
    '--port',
    String(startAt),
  ])
  for (let i = 0; i < 20; i += 1) {
    await $.clock.sleep(250)
    const made = await serverPort($, paths)
    // The port file must be the new server's, not the stale one read above.
    if (made !== undefined && (running === undefined || (await isPortFileFresh($, paths, startedAt)))) return made
  }

  return undefined
}

/** Whether the server's port file was written after `since`: a fresh server's, not a stale one. */
async function isPortFileFresh($: EngineInterface, paths: BoardPaths, since: number): Promise<boolean> {
  try {
    const { mtimeMs } = await $.fs.stat(paths.server)

    return mtimeMs >= since - 1_000
  } catch {
    return false
  }
}

/**
 * What answers on `port`: this project's board, which proves it holds the run
 * folder's key ('ours'); another program or another project's board
 * ('other'); or nothing. The launcher asks with a nonce and checks the answer
 * against the key file, so the key itself is never sent to the port.
 */
async function whoServes($: EngineInterface, paths: BoardPaths, port: number): Promise<'ours' | 'other' | 'nothing'> {
  const probe = await launch($, ['probe', String(port), paths.run], 5_000)

  return probe.exitCode === 0 ? 'ours' : probe.exitCode === 3 ? 'other' : 'nothing'
}

/**
 * A one-time pass for the page, written into the run folder by the launcher.
 * The address the browser is opened with holds the pass, not the key: an
 * address is seen for a moment by whoever lists this machine's processes,
 * and a pass works once.
 */
async function makePass($: EngineInterface, paths: BoardPaths): Promise<string> {
  try {
    const made = await launch($, ['pass', paths.run], 5_000)
    const pass = made.stdout.trim()

    return made.exitCode === 0 && /^[A-Za-z0-9_-]{32,128}$/.test(pass) ? pass : ''
  } catch {
    return ''
  }
}

/** The address that holds the board's key itself, for a bookmark or the editor's own browser; '' when the key is not there. */
export async function keyLink($: EngineInterface, paths: BoardPaths, port: number): Promise<string> {
  try {
    const key = (await $.fs.read(paths.key)).trim()

    return /^[A-Za-z0-9_-]{32,128}$/.test(key) ? `http://127.0.0.1:${port}/?k=${key}` : ''
  } catch {
    return ''
  }
}

/** Opens the page in the user's browser, with a one-time pass for the board's key: Windows' default from WSL, else the desktop's. */
export async function openBrowser($: EngineInterface, paths: BoardPaths, port: number): Promise<boolean> {
  const pass = await makePass($, paths)
  const url = `http://127.0.0.1:${port}/${pass ? `?p=${pass}` : ''}`
  const tries: string[][] = [
    ['wslview', url],
    ['powershell.exe', '-NoProfile', '-Command', `Start-Process '${url}'`],
    ['xdg-open', url],
    ['open', url],
  ]
  for (const argv of tries) {
    try {
      const ran = await $.process.run(argv, { timeoutMs: 15_000 })
      if (ran.exitCode === 0) return true
    } catch {
      // the next opener
    }
  }

  return false
}

/** Publishes the live card for the page, or clears it. */
export async function publishCard($: EngineInterface, paths: BoardPaths, card: GameCard | null): Promise<void> {
  await $.fs.write(paths.card, `${JSON.stringify(card ?? {})}\n`)
}

/**
 * Waits for the page's answer to `card`: a host command polls the inbox, so
 * the hook's budget does not run. Resolves the answer, or undefined when the
 * page went away (the card then goes to the chat dialog).
 */
export async function waitOnBoard($: EngineInterface, paths: BoardPaths, cardId: string): Promise<string | undefined> {
  const script = join($.plugin.root, 'board', 'wait.py')
  const command = await python($)
  for (let round = 0; round < 24; round += 1) {
    let ran
    try {
      ran = await $.process.run([...command, '-I', script, paths.run, cardId, WAIT_SECONDS], { timeoutMs: 600_000 })
    } catch {
      return undefined
    }
    if (ran.exitCode === 0) {
      try {
        const parsed = JSON.parse(ran.stdout.trim()) as { answer?: unknown; dismissed?: unknown }
        if (parsed.dismissed === true) return BOARD_DISMISSED
        if (typeof parsed.answer === 'string' && parsed.answer.trim() !== '') return parsed.answer.trim()
      } catch {
        return undefined
      }
      return undefined
    }
    if (ran.exitCode !== 3) return undefined
  }

  return undefined
}

/**
 * The prompts the page sent since the last drain, oldest first. The inbox is
 * moved aside before it is read, so a line the server appends meanwhile lands
 * in a fresh inbox and is never lost; the aside file is removed after reading.
 */
export async function drainPrompts($: EngineInterface, paths: BoardPaths): Promise<string[]> {
  if (!(await $.fs.exists(paths.prompts))) return []
  const aside = `${paths.prompts}.draining-${Date.now()}`
  let text = ''
  try {
    const moved = await launch($, ['move', paths.prompts, aside], 5_000)
    if (moved.exitCode !== 0) return []
    text = await $.fs.read(aside)
  } catch {
    return []
  } finally {
    void launch($, ['remove', aside], 5_000)
  }
  if (text.trim() === '') return []
  const found: string[] = []
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue
    try {
      const parsed = JSON.parse(line) as { text?: unknown }
      if (typeof parsed.text === 'string' && parsed.text.trim() !== '') found.push(parsed.text.trim())
    } catch {
      // a half-written line is skipped
    }
  }

  return found
}
