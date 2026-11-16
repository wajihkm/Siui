// The chat log: one line per turn of the conversation, with the user's words,
// the model's answer cut short, and the level that was current, so the board
// shows what was said around each step. Kept in the project beside the
// record, as JSON lines, appended by the `turn.complete` hook.

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

/** Appends one turn; a turn with nothing said on either side is not written. */
export async function appendChat(
  $: EngineInterface,
  root: string,
  relative: string,
  turn: { world: number | null; level: string; user: string; assistant: string },
): Promise<boolean> {
  const user = cutText(turn.user, USER_MAX)
  const assistant = cutText(turn.assistant, ANSWER_MAX)
  if (user === '' && assistant === '') return false
  const path = chatPath(root, relative)
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
