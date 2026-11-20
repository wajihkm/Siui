// The chat log: one line per turn of the conversation, with the user's words,
// the model's answer cut short, and the level that was current, so the board
// shows what was said around each step. Kept in the project beside the
// record, as JSON lines, appended by the `turn.complete` hook while game mode
// is on, and ignored by git through a `.gitignore` written beside it.

import { join } from './paths'
import type { EngineInterface } from 'claude-code'

export const CHAT_PATH = '.claude/chat-log.jsonl'
const USER_MAX = 2000
const ANSWER_MAX = 4000
/** Past this size the live log is archived under a dated name and a fresh one starts. */
const ROLL_BYTES = 2 * 1024 * 1024

export type ChatTurn = { at: string; world: number | null; level: string; user: string; assistant: string }

export function chatPath(root: string, relative: string = CHAT_PATH): string {
  return join(root, relative.replace(/^\.?\//, ''))
}

function cutText(text: string, max: number): string {
  const flat = text.replace(/\r/g, '').trim()

  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat
}

const IGNORE_MARK = '# Siui: files of this machine, not of the repository'

/**
 * Keeps the chat log, the exports and the record's leftovers out of git: a
 * `.gitignore` beside the log. The log holds the person's own prompts and the
 * answers; their own `git add -A` must not take it (a save point never does,
 * whatever this file says). The lines are made sure of once per project on
 * this machine, remembered by `doneMark`, a file of the run folder: a mark a
 * cloned repository ships in the file does not count as done. After that the
 * file is its owner's: deleting a line under the mark opts that file back in.
 */
export async function ignoreLocalFiles($: EngineInterface, root: string, relative: string = CHAT_PATH, doneMark?: string): Promise<void> {
  const log = chatPath(root, relative)
  const cut = Math.max(log.lastIndexOf('/'), log.lastIndexOf('\\'))
  if (cut <= 0) return
  const folder = log.slice(0, cut)
  const name = log.slice(cut + 1)
  const path = `${folder}/.gitignore`
  // The log by its own name, whatever it ends in, and its dated archives.
  const lines = [`/${name}`, `/${name.replace(/\.jsonl$/, '')}-*.jsonl`, 'exports/', 'decisions.json.tmp-*', 'decisions.json.broken-*']
  try {
    if (doneMark !== undefined && (await $.fs.exists(doneMark))) return
    const had = (await $.fs.exists(path)) ? await $.fs.read(path) : ''
    if (doneMark === undefined && had.includes(IGNORE_MARK)) return
    const has = new Set(had.split('\n').map(one => one.trim()))
    const missing = lines.filter(one => !has.has(one))
    if (missing.length > 0) {
      const head = has.has(IGNORE_MARK) ? [] : [IGNORE_MARK]
      await $.fs.write(path, `${had}${had !== '' && !had.endsWith('\n') ? '\n' : ''}${[...head, ...missing].join('\n')}\n`)
    }
    if (doneMark !== undefined) await $.fs.write(doneMark, `${new Date().toISOString()}\n`)
  } catch {
    // a folder that cannot be written keeps no log either
  }
}

/** Appends one turn; a turn with nothing said on either side is not written. */
export async function appendChat(
  $: EngineInterface,
  root: string,
  relative: string,
  turn: { world: number | null; level: string; user: string; assistant: string },
  doneMark?: string,
): Promise<boolean> {
  const user = cutText(turn.user, USER_MAX)
  const assistant = cutText(turn.assistant, ANSWER_MAX)
  if (user === '' && assistant === '') return false
  const path = chatPath(root, relative)
  await ignoreLocalFiles($, root, relative, doneMark)
  const line = JSON.stringify({ at: new Date().toISOString(), world: turn.world, level: turn.level, user, assistant })
  let had = ''
  if (await $.fs.exists(path)) {
    try {
      had = await $.fs.read(path)
    } catch {
      had = ''
    }
  }
  if (had.length > ROLL_BYTES) {
    // Roll: the live file goes to an archive beside it, named by the day, and starts over.
    const stamp = new Date().toISOString().slice(0, 10)
    const archive = path.replace(/\.jsonl$/, '') + `-${stamp}.jsonl`
    try {
      const earlier = (await $.fs.exists(archive)) ? await $.fs.read(archive) : ''
      await $.fs.write(archive, `${earlier}${earlier !== '' && !earlier.endsWith('\n') ? '\n' : ''}${had}`)
      had = ''
    } catch {
      // the roll failed: the live file keeps growing until the next try
    }
  }
  await $.fs.write(path, `${had}${had !== '' && !had.endsWith('\n') ? '\n' : ''}${line}\n`)

  return true
}
