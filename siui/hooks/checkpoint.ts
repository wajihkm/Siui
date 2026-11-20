// Checkpoints: save points on a stage. A checkpoint is a git commit of the
// project's folder on the current branch; the board's server returns the
// tree to one on its own (it commits and tags what is there first, so nothing
// is lost). Forks make two branches from a checkpoint, roads a and b, one on
// disk at a time; the castle merges the road kept and tags the other.
//
// What such a commit takes is bounded: the project's folder alone, though the
// repository may be larger; the files git tracks, and new ones only when the
// person agreed (`all`); never a file whose name looks like a secret; nothing
// at all in the middle of a merge or a rebase.

import type { EngineInterface } from 'claude-code'

import { CHAT_PATH } from './chat'
import { join } from './paths'
import { timeSuffix } from './record'

/** How a save point treats files git does not know yet: all of them, or only the files it tracks. */
export type SaveMode = 'all' | 'tracked'

/** Names that look like secrets: a save point never adds one; `git add` it by hand when it belongs in the repository. */
const SECRET_LIKE = new RegExp(
  [
    '(^|/)\\.env($|[._-](?!(example|sample|template|dist|defaults?)$))|(^|/)\\.envrc$|\\.env$',
    '\\.(pem|key|p12|pfx|jks|keystore|kdbx|ppk|tfvars|tfstate|kubeconfig)$|\\.tfstate\\.backup$',
    '(^|/)id_(rsa|dsa|ecdsa|ed25519)(?![^/]*\\.pub$)[^/]*$',
    '(^|/)\\.(npmrc|pypirc|netrc|git-credentials|htpasswd|pgpass|dockercfg)$|(^|/)\\.docker/config\\.json$|(^|/)kubeconfig$',
    '(^|/)(credentials?|secrets?|client[-_]secret[^/]*|service[-_]?account[^/]*)(\\.[a-z0-9]+)?$',
  ].join('|'),
  'i',
)

export function looksSecret(path: string): boolean {
  return SECRET_LIKE.test(path)
}

export type GitResult = { exitCode: number; stdout: string; stderr: string }

/**
 * Whether the person has a git identity of their own, read once per module
 * load: the fallback identity is added only when `git config user.name` is
 * empty, so their commits stay theirs. A hot reload reads it again.
 */
let hasOwnIdentity: boolean | undefined

async function identityArguments($: EngineInterface, root: string): Promise<string[]> {
  if (hasOwnIdentity === undefined) {
    try {
      const ran = await $.process.run(['git', 'config', 'user.name'], { cwd: root, timeoutMs: 10_000 })
      hasOwnIdentity = ran.exitCode === 0 && ran.stdout.trim() !== ''
    } catch {
      hasOwnIdentity = false
    }
  }

  return hasOwnIdentity ? [] : ['-c', 'user.name=siui', '-c', 'user.email=siui@local']
}

/** Runs git in the project; signing is off so a checkpoint never waits on a key or a passphrase. */
export async function git($: EngineInterface, root: string, args: readonly string[]): Promise<GitResult> {
  try {
    const identity = await identityArguments($, root)
    const ran = await $.process.run(['git', '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', ...identity, ...args], {
      cwd: root,
      timeoutMs: 60_000,
    })

    return { exitCode: ran.exitCode, stdout: ran.stdout.trim(), stderr: ran.stderr.trim() }
  } catch (error) {
    return { exitCode: 1, stdout: '', stderr: String(error) }
  }
}

/** The files a save point would add: not tracked, not ignored, under the project's folder; secret-looking names first. */
export async function newFiles($: EngineInterface, root: string): Promise<string[]> {
  const listed = await git($, root, ['ls-files', '--others', '--exclude-standard', '-z', '--', '.'])
  if (listed.exitCode !== 0) return []
  const paths = listed.stdout.split('\0').filter(one => one !== '')

  return [...paths.filter(looksSecret), ...paths.filter(one => !looksSecret(one))]
}

/** What git is in the middle of, which a commit now would end wrongly: a merge, a rebase, a pick, a revert; '' when nothing. */
export async function busyWith($: EngineInterface, root: string): Promise<string> {
  const dir = await git($, root, ['rev-parse', '--absolute-git-dir'])
  if (dir.exitCode !== 0 || dir.stdout === '') return ''
  const marks: Array<[string, string]> = [
    ['MERGE_HEAD', 'a merge'],
    ['rebase-merge', 'a rebase'],
    ['rebase-apply', 'a rebase'],
    ['CHERRY_PICK_HEAD', 'a cherry-pick'],
    ['REVERT_HEAD', 'a revert'],
    ['BISECT_LOG', 'a bisect'],
  ]
  for (const [name, what] of marks) {
    if (await $.fs.exists(join(dir.stdout, name))) return what
  }

  return ''
}

/**
 * Commits the project's folder: the files git tracks, and with `all` the new
 * ones too, except any whose name looks like a secret; never the chat log.
 * The commit is of this folder alone: in a larger repository the other
 * folders, and what is staged there, stay as they are. Refused in the middle
 * of a merge or a rebase, which such a commit would conclude. Resolves the
 * secret-looking files left out, or an error line; nothing to commit is no
 * error.
 */
export async function commitFolder(
  $: EngineInterface,
  root: string,
  message: string,
  mode: SaveMode,
): Promise<{ leftOut: string[] } | { error: string }> {
  const busy = await busyWith($, root)
  if (busy !== '') return { error: `git is in the middle of ${busy}; finish it first` }
  // A folder with nothing git tracks has nothing for these to match: that is no error.
  const nothing = /nothing to commit|nothing added|no changes added|did not match any file/i
  let leftOut: string[] = []
  let add = ['add', '-u', '--', '.', ...keptOut]
  if (mode === 'all') {
    leftOut = (await newFiles($, root)).filter(looksSecret)
    // Past forty such files they are no longer a few keys to step around: only tracked files are taken.
    if (leftOut.length <= 40) add = ['add', '-A', '--', '.', ...keptOut, ...leftOut.map(one => `:(exclude,literal)${one}`)]
  }
  const added = await git($, root, add)
  if (added.exitCode !== 0 && !nothing.test(`${added.stdout}\n${added.stderr}`)) return { error: added.stderr.split('\n')[0] || 'git add failed' }
  const committed = await git($, root, ['commit', '-q', '-m', message, '--', '.', ...keptOut])
  if (committed.exitCode !== 0 && !nothing.test(`${committed.stdout}\n${committed.stderr}`)) {
    return { error: committed.stderr.split('\n')[0] || 'the commit failed' }
  }

  return { leftOut }
}

/**
 * The pathspecs that keep the chat log and its dated archives out of every
 * commit made here, whether git tracks them or not: the log holds the
 * person's prompts, and a repository can ship one already tracked. Set from
 * the configuration when it is read.
 */
let keptOut: string[] = []

export function keepOutOfCommits(chatLog: string): void {
  const log = chatLog.replace(/^\.?\//, '')
  const stem = log.replace(/\.jsonl$/, '')
  keptOut = [`:(exclude,literal)${log}`, `:(exclude,glob)${stem.replace(/[*?[\]\\]/g, '\\$&')}-*.jsonl`]
}
keepOutOfCommits(CHAT_PATH)

/** Whether a name read from the record is a plain branch name, never an option: `main`, `feature/x`, `fork/2-2-a`. */
export function isBranchName(name: unknown): name is string {
  return typeof name === 'string' && /^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/.test(name) && !name.includes('..')
}

/** Whether a fork read from the record names its own two roads and a plain base: what goes to git is checked first. */
function isSoundFork(fork: RunFork): boolean {
  return (
    /^\d+-\d+$/.test(fork.level) &&
    isBranchName(fork.base) &&
    fork.branches?.a === `fork/${fork.level}-a` &&
    fork.branches?.b === `fork/${fork.level}-b` &&
    (fork.onDisk === 'a' || fork.onDisk === 'b')
  )
}
const UNSOUND = 'the record names this fork with a branch that is not one of its own'


/** Commits the project's folder as a checkpoint; resolves the commit, the branch and the files left out, or an error line. */
export async function saveCheckpoint(
  $: EngineInterface,
  root: string,
  title: string,
  mode: SaveMode,
): Promise<{ commit: string; branch: string; leftOut: string[] } | { error: string }> {
  const inside = await git($, root, ['rev-parse', '--is-inside-work-tree'])
  if (inside.exitCode !== 0) return { error: 'not a git repository' }
  const committed = await commitFolder($, root, `Checkpoint: ${title}`, mode)
  if ('error' in committed) return committed
  const sha = await git($, root, ['rev-parse', 'HEAD'])
  const branch = await git($, root, ['rev-parse', '--abbrev-ref', 'HEAD'])
  if (sha.exitCode !== 0) return { error: 'no commit to point at' }

  return { commit: sha.stdout, branch: branch.stdout || 'HEAD', leftOut: committed.leftOut }
}

/** A fork at a stage: two roads, a and b, each a branch from one checkpoint; one on disk at a time. */
export type RunFork = {
  level: string
  at: string
  base: string
  checkpoint: string
  branches: { a: string; b: string }
  onDisk: 'a' | 'b'
  /** Set by the castle: the road merged into the base, or both kept. */
  merged?: 'a' | 'b' | 'both'
  /** The tag that keeps the road not taken. */
  tag?: string
}

/** The branch checked out, or 'HEAD' when the tree is detached (or git says nothing). */
export async function currentBranch($: EngineInterface, root: string): Promise<string> {
  const branch = await git($, root, ['rev-parse', '--abbrev-ref', 'HEAD'])

  return branch.exitCode === 0 && branch.stdout !== '' ? branch.stdout : 'HEAD'
}

/** Forks a stage: a checkpoint, then branches fork/<level>-a and -b at it; road a goes on disk. */
export async function forkRoads($: EngineInterface, root: string, level: string, mode: SaveMode): Promise<RunFork | { error: string }> {
  const base = await currentBranch($, root)
  // A detached tree has no base to merge back into: the fork would have nowhere to end.
  if (base === 'HEAD') return { error: 'the tree is detached (no branch checked out); check out a branch first' }
  if (/^fork\//.test(base)) return { error: `already on a road (${base}); merge it first` }
  const saved = await saveCheckpoint($, root, `Fork at ${level}`, mode)
  if ('error' in saved) return saved
  const branches = { a: `fork/${level}-a`, b: `fork/${level}-b` }
  for (const name of [branches.a, branches.b]) {
    const made = await git($, root, ['branch', name, saved.commit])
    if (made.exitCode !== 0) return { error: made.stderr.split('\n')[0] || `could not make ${name}` }
  }
  const switched = await git($, root, ['switch', '-q', branches.a])
  if (switched.exitCode !== 0) return { error: switched.stderr.split('\n')[0] || 'could not switch to road a' }

  return { level, at: new Date().toISOString(), base, checkpoint: saved.commit, branches, onDisk: 'a' }
}

/** Switches to the other road: what is on disk is committed on the current road first. */
export async function switchRoad($: EngineInterface, root: string, fork: RunFork, road: 'a' | 'b', mode: SaveMode): Promise<{ error: string } | { ok: true }> {
  if (!isSoundFork(fork)) return { error: UNSOUND }
  const kept = await commitFolder($, root, `Road ${fork.onDisk} of ${fork.level}: before switching`, mode)
  if ('error' in kept) return kept
  const switched = await git($, root, ['switch', '-q', fork.branches[road]])
  if (switched.exitCode !== 0) return { error: switched.stderr.split('\n')[0] || `could not switch to road ${road}` }

  return { ok: true }
}

/** The tag that keeps a road not taken, dated so a second fork of the stage never overwrites an earlier one's. */
function roadTag(level: string, road: 'a' | 'b', iso: string): string {
  return `forks/${level}-${road}-${iso.slice(0, 10).replace(/-/g, '')}-${timeSuffix(iso)}`
}

/**
 * Merges the kept road into the base with a merge commit; the other road is
 * tagged forks/<level>-<road>-<date-time> and its branch deleted. With `both`,
 * road a is merged and road b kept as a branch and a tag.
 */
export async function mergeRoads(
  $: EngineInterface,
  root: string,
  fork: RunFork,
  keep: 'a' | 'b' | 'both',
  mode: SaveMode,
): Promise<{ tag: string; merged: 'a' | 'b' | 'both' } | { error: string }> {
  if (!isSoundFork(fork)) return { error: UNSOUND }
  const before = await commitFolder($, root, `Road ${fork.onDisk} of ${fork.level}: before the merge`, mode)
  if ('error' in before) return before
  const kept: 'a' | 'b' = keep === 'b' ? 'b' : 'a'
  const other: 'a' | 'b' = kept === 'a' ? 'b' : 'a'
  const toBase = await git($, root, ['switch', '-q', fork.base])
  if (toBase.exitCode !== 0) return { error: toBase.stderr.split('\n')[0] || `could not switch to ${fork.base}` }
  const merged = await git($, root, ['merge', '--no-ff', '-q', '-m', `Merged road ${kept} of ${fork.level}`, fork.branches[kept]])
  if (merged.exitCode !== 0) {
    await git($, root, ['merge', '--abort'])
    await git($, root, ['switch', '-q', fork.branches[fork.onDisk]])
    return { error: merged.stderr.split('\n')[0] || merged.stdout.split('\n')[0] || 'the merge failed' }
  }
  const tag = roadTag(fork.level, other, new Date().toISOString())
  const tagged = await git($, root, ['tag', tag, fork.branches[other]])
  // The merge is done either way; when the tag failed the other road's branch stays, so nothing is lost.
  const keptAs = tagged.exitCode === 0 ? tag : fork.branches[other]
  await git($, root, ['branch', '-D', fork.branches[kept]])
  if (keep !== 'both' && tagged.exitCode === 0) await git($, root, ['branch', '-D', fork.branches[other]])

  return { tag: keptAs, merged: keep }
}
