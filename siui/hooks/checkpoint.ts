// Checkpoints: save points on a stage. A checkpoint is a git commit of the
// whole working tree; the board's server returns the tree to one on its own
// (it commits and tags what is there first, so nothing is lost). Forks make
// two branches from a checkpoint, roads a and b, one on disk at a time; the
// castle merges the road kept and tags the other.

import type { EngineInterface } from 'claude-code'

import { timeSuffix } from './record'

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

/** Commits everything as a checkpoint; resolves the commit and branch, or an error line. */
export async function saveCheckpoint(
  $: EngineInterface,
  root: string,
  title: string,
): Promise<{ commit: string; branch: string } | { error: string }> {
  const inside = await git($, root, ['rev-parse', '--is-inside-work-tree'])
  if (inside.exitCode !== 0) return { error: 'not a git repository' }
  await git($, root, ['add', '-A'])
  const committed = await git($, root, ['commit', '-q', '-m', `Checkpoint: ${title}`])
  if (committed.exitCode !== 0 && !/nothing to commit|nothing added/i.test(`${committed.stdout}\n${committed.stderr}`)) {
    return { error: committed.stderr.split('\n')[0] || 'the commit failed' }
  }
  const sha = await git($, root, ['rev-parse', 'HEAD'])
  const branch = await git($, root, ['rev-parse', '--abbrev-ref', 'HEAD'])
  if (sha.exitCode !== 0) return { error: 'no commit to point at' }

  return { commit: sha.stdout, branch: branch.stdout || 'HEAD' }
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
export async function forkRoads($: EngineInterface, root: string, level: string): Promise<RunFork | { error: string }> {
  const base = await currentBranch($, root)
  // A detached tree has no base to merge back into: the fork would have nowhere to end.
  if (base === 'HEAD') return { error: 'the tree is detached (no branch checked out); check out a branch first' }
  if (/^fork\//.test(base)) return { error: `already on a road (${base}); merge it first` }
  const saved = await saveCheckpoint($, root, `Fork at ${level}`)
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
export async function switchRoad($: EngineInterface, root: string, fork: RunFork, road: 'a' | 'b'): Promise<{ error: string } | { ok: true }> {
  await git($, root, ['add', '-A'])
  await git($, root, ['commit', '-q', '-m', `Road ${fork.onDisk} of ${fork.level}: before switching`])
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
): Promise<{ tag: string; merged: 'a' | 'b' | 'both' } | { error: string }> {
  await git($, root, ['add', '-A'])
  await git($, root, ['commit', '-q', '-m', `Road ${fork.onDisk} of ${fork.level}: before the merge`])
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
