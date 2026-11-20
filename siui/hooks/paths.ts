// Paths and processes that work on every platform: a path may be `/home/x` or
// `C:\Users\x`, the home folder HOME or USERPROFILE, Python `python3`,
// `python` or `py -3`. Every hook that builds a path or starts Python goes
// through here, so no other module assumes a Unix shell.

import type { EngineInterface } from 'claude-code'

/** Whether a path is absolute or rooted: `/…`, `\…`, `C:\…`, `C:/…`, `C:x` or a `\\server\share`. */
export function isAbsolute(path: string): boolean {
  return path.startsWith('/') || path.startsWith('\\') || /^[A-Za-z]:/.test(path)
}

/** A path without its trailing separators. */
export function trimEnd(path: string): string {
  return path.replace(/[\\/]+$/, '')
}

/** The last part of a path, whatever its separators. */
export function baseName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path
}

/** `base` and a relative part, joined with `/`, which every platform's file calls take. */
export function join(base: string, ...parts: string[]): string {
  return [trimEnd(base), ...parts.map(one => one.replace(/^\.[\\/]/, ''))].join('/')
}

/** One spelling of a path, for comparing two: forward slashes, no trailing one, a drive letter in lower case. */
export function normalise(path: string): string {
  const flat = trimEnd(path.replace(/\\/g, '/'))

  return /^[A-Za-z]:/.test(flat) ? flat[0]!.toLowerCase() + flat.slice(1) : flat
}

export function samePath(a: string, b: string): boolean {
  const [x, y] = [normalise(a), normalise(b)]

  return /^[a-z]:/.test(x) ? x.toLowerCase() === y.toLowerCase() : x === y
}

/** The `file:` URL of an absolute path: `file:///home/x` or `file:///C:/Users/x`. */
export function fileUrl(absolute: string): string {
  const flat = absolute.replace(/\\/g, '/')

  return `file://${flat.startsWith('/') ? '' : '/'}${encodeURI(flat)}`
}

/** Whether the session runs on native Windows. */
export async function isWindows($: EngineInterface): Promise<boolean> {
  return (await $.env.get('OS')) === 'Windows_NT'
}

/** The user's home folder: HOME, or USERPROFILE on Windows; undefined when neither is set. */
export async function homeOf($: EngineInterface): Promise<string | undefined> {
  const home = (await $.env.get('HOME')) || (await $.env.get('USERPROFILE')) || ''

  return home === '' ? undefined : trimEnd(home)
}

let pythonFound: string[] | undefined

/**
 * The command that runs Python 3 here, found once per session: the one the
 * person names in their own environment as `SIUI_PYTHON` (a command, its
 * arguments after spaces: `py -3`), then `python3`, `python`, `py -3`, the
 * first that prints a 3. On Windows `python3` is often a shortcut to the Store
 * that prints nothing, which is why the answer is read and not just the exit
 * code. The project's files never name it: a program a repository could name
 * would run on the machine of whoever opened that repository.
 */
export async function python($: EngineInterface): Promise<string[]> {
  if (pythonFound) return pythonFound
  const named = ((await $.env.get('SIUI_PYTHON')) ?? '').trim().split(/\s+/).filter(Boolean)
  const tries: string[][] = [...(named.length > 0 ? [named] : []), ['python3'], ['python'], ['py', '-3']]
  for (const command of tries) {
    try {
      const ran = await $.process.run([...command, '-c', 'import sys; print(sys.version_info[0])'], { timeoutMs: 10_000 })
      if (ran.exitCode === 0 && ran.stdout.trim() === '3') {
        pythonFound = command

        return command
      }
    } catch {
      // the next one
    }
  }

  // None answered: python3 is named so the failure that follows says what is missing.
  return ['python3']
}

/** Runs one verb of board/launch.py, the plugin's stand-in for shell lines. */
export async function launch($: EngineInterface, args: string[], timeoutMs = 10_000): Promise<{ exitCode: number; stdout: string }> {
  try {
    const ran = await $.process.run([...(await python($)), '-I', join($.plugin.root, 'board', 'launch.py'), ...args], { timeoutMs })

    return { exitCode: ran.exitCode, stdout: ran.stdout }
  } catch {
    return { exitCode: 1, stdout: '' }
  }
}
