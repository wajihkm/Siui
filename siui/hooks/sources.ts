// Source links: where a card's sources are on disk, whether they exist, and
// whether the model has really read them this session. An input claimed
// `used` that the model never read is downgraded to `maybe`, so a solid
// in-edge is earned, never claimed. An output is what the answer will change:
// its `use` is the model's own forecast, and a missing output is a new file.

import type { EngineInterface } from 'claude-code'

import type { GameSource } from '../types'
import { baseName as lastPart, fileUrl, isAbsolute, isNetwork, join, normalise } from './paths'

/** Files every session is given, so they count as read without a Read call. */
const ALWAYS_READ = new Set(['CLAUDE.md', 'AGENTS.md'])

/** An absolute path for `path` as the model wrote it: project-relative, `~/...` or absolute. */
export function absolutePath(path: string, root: string, home: string | undefined): string {
  if (isAbsolute(path)) return path
  if (path === '~' || path.startsWith('~/') || path.startsWith('~\\')) return `${home ?? ''}${path.slice(1)}`

  return join(root, path)
}

/** The `file:` URL a card links to. */
export function hrefOf(absolute: string): string {
  return fileUrl(absolute)
}

function baseName(absolute: string): string {
  return lastPart(absolute)
}

export function isInput(source: GameSource): boolean {
  return source.role !== 'out'
}

export function isOutput(source: GameSource): boolean {
  return source.role !== 'in'
}

/** Whether the in-edge of a source draws solid: the file is there and was read. */
export function isSolidInput(source: GameSource): boolean {
  return source.isRead === true && !source.isMissing
}

/** Whether the out-edge of a source draws solid: the model says it will change. */
export function isSolidOutput(source: GameSource): boolean {
  return source.use === 'used'
}

/**
 * Checks each source and settles its final state: `href`, `isMissing` when
 * the path is not there, `isRead` when the model read it this session. An
 * input claimed `used` but never read becomes `maybe` and its path is returned
 * in `downgraded`, for the model to hear about; an output keeps its `use`.
 */
export async function resolveSources(
  $: EngineInterface,
  sources: readonly GameSource[],
  root: string,
  home: string | undefined,
  readPaths: readonly string[],
): Promise<{ sources: GameSource[]; downgraded: string[] }> {
  const read = new Set(readPaths.map(normalise))
  const settled: GameSource[] = []
  const downgraded: string[] = []

  for (const source of sources) {
    const absolute = absolutePath(source.path, root, home)
    // A path on another machine is not even asked about: on Windows that alone signs in there. It shows as missing.
    const isRemote = isNetwork(source.path) || isNetwork(absolute)
    const exists = !isRemote && (await $.fs.exists(absolute))
    const one: GameSource = isRemote ? { ...source } : { ...source, href: hrefOf(absolute) }
    if (!exists) one.isMissing = true
    if (exists) {
      try {
        const { size, kind } = await $.fs.stat(absolute)
        if (kind === 'file') one.bytes = size
      } catch {
        // no size: the node keeps its base size
      }
    }
    if (exists && (read.has(normalise(absolute)) || ALWAYS_READ.has(baseName(absolute)))) one.isRead = true
    if (source.role === 'in' && one.use === 'used' && !one.isRead) {
      one.use = 'maybe'
      downgraded.push(source.path)
    }
    settled.push(one)
  }

  return { sources: settled, downgraded }
}

/** The paths a Skill call reads: the project's skill folder first, then the plugin's bundled one, then the user's. */
export function skillPaths(skill: string, root: string, home: string | undefined): string[] {
  const name = skill.replace(/^.*:/, '').trim()
  if (name === '' || /[\\/]/.test(name) || name.includes('..')) return []
  const paths = [join(root, '.claude', 'skills', name, 'SKILL.md'), join(root, 'skills', name, 'SKILL.md')]
  if (home) paths.push(`${home}/.claude/skills/${name}/SKILL.md`)

  return paths
}
