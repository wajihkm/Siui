// The project's configuration of the mode: one JSON file, `.claude/siui.json`,
// read when the session starts and again on `/game on`. Every field is optional;
// a missing file means the defaults. Caps can only be lowered: raising one
// would push the card past the rows the question dialog allows.

import type { EngineInterface } from 'claude-code'

import { CHAT_PATH } from './chat'
import type { Caps } from './input'
import { CAPS } from './input'
import { RECORD_PATH } from './record'
import type { Words } from './words'
import { DEFAULT_WORDS } from './words'
import { isAbsolute, isNetwork, join, trimEnd } from './paths'

export const CONFIG_PATH = '.claude/siui.json'

export type GameConfig = {
  /** Where the record lives, relative to the project root. */
  record: string
  /** The field caps, each at most the built-in one. */
  caps: Caps
  /** Extra folders holding packs, relative to the project root. */
  packs: string[]
  /** The port the HTML board's server tries first (then the next nine). */
  boardPort: number
  /** Where the chat log lives, relative to the project root. */
  chatLog: string
  /** The universe named in the theme block: the board's words, icons, colours and shapes. */
  universe: string
  /** The universe's words for the chat's card header and world map. */
  words: Words
}

const UNIVERSE_NAME = /^[a-z0-9-]{1,40}$/

export function defaultConfig(): GameConfig {
  return { record: RECORD_PATH, caps: { ...CAPS }, packs: [], boardPort: 5131, chatLog: CHAT_PATH, universe: 'classic', words: { ...DEFAULT_WORDS } }
}

/** The words of a universe, from the project's own set file or the plugin's bundled one; neutral when neither reads. */
async function readWords($: EngineInterface, root: string, name: string): Promise<Words> {
  const made: Words = { ...DEFAULT_WORDS }
  if (name === 'classic') return made
  for (const path of [`${root}/.claude/universes/${name}.json`, `${$.plugin.root}/board/universes/${name}.json`]) {
    if (!(await $.fs.exists(path))) continue
    try {
      const parsed = JSON.parse(await $.fs.read(path)) as { words?: Record<string, unknown> }
      const given = parsed.words && typeof parsed.words === 'object' ? parsed.words : {}
      for (const key of Object.keys(DEFAULT_WORDS) as Array<keyof Words>) {
        const value = given[key]
        if (typeof value === 'string' && value.trim() !== '') made[key] = value.trim().slice(0, 24)
      }
      return made
    } catch {
      return made
    }
  }

  return made
}

export async function readConfig($: EngineInterface, root: string): Promise<GameConfig> {
  const made = defaultConfig()
  const base = trimEnd(root)
  const path = join(base, CONFIG_PATH)
  if (!(await $.fs.exists(path))) return made
  try {
    const parsed = JSON.parse(await $.fs.read(path)) as Record<string, unknown>
    const theme = parsed.theme && typeof parsed.theme === 'object' ? (parsed.theme as Record<string, unknown>) : {}
    const universe = typeof theme.universe === 'string' ? theme.universe.trim() : ''
    if (universe !== '' && UNIVERSE_NAME.test(universe)) made.universe = universe
    made.words = await readWords($, base, made.universe)
    const record = typeof parsed.record === 'string' ? parsed.record.trim() : ''
    if (record !== '' && !record.includes('..') && !isAbsolute(record)) made.record = record
    const caps = parsed.caps && typeof parsed.caps === 'object' ? (parsed.caps as Record<string, unknown>) : {}
    for (const key of Object.keys(CAPS) as Array<keyof Caps>) {
      const value = caps[key]
      if (typeof value === 'number' && Number.isInteger(value) && value >= 1) {
        made.caps[key] = Math.min(value, CAPS[key])
      }
    }
    const chatLog = typeof parsed.chatLog === 'string' ? parsed.chatLog.trim() : ''
    if (chatLog !== '' && !chatLog.includes('..') && !isAbsolute(chatLog)) made.chatLog = chatLog
    const port = parsed.boardPort
    if (typeof port === 'number' && Number.isInteger(port) && port >= 1024 && port <= 65535) made.boardPort = port
    if (Array.isArray(parsed.packs)) {
      made.packs = parsed.packs
        // A folder of the project's own packs lies in the project; packs shared between projects belong in the home folder's skill.
        .filter((one): one is string => typeof one === 'string' && one.trim() !== '' && !one.includes('..') && !isNetwork(one) && !isAbsolute(one.trim()))
        .map(one => one.trim())
        .slice(0, 8)
    }
  } catch {
    // a file that is not JSON leaves the defaults
  }

  return made
}
