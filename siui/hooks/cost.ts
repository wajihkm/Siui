// What each decision cost: the session's running cost, read at every answered
// card and at every turn's end, and the difference since the last reading
// added to the decision that was current. A stage's cost is the sum of its
// decisions', a world's the sum of its stages'. Only differences are kept: the
// session's total starts over with a new session or /clear.

import type { EngineInterface } from 'claude-code'

import type { GameRecord } from './record'

let lastUsd: number | undefined
let lastStart: number | undefined
/** Spent while no decision was current: it goes to the next one recorded, whose card it prepared. */
let pending = 0
let target: { run: string; level: string; id: string } | undefined

/** What the session spent since the last reading, in dollars; 0 where the host keeps no cost. */
async function spentSince($: EngineInterface): Promise<number> {
  let usd: number | undefined
  let start: number | undefined
  try {
    const used = await $.session.usage()
    usd = used.cost?.usd
    start = used.startedAt
  } catch {
    return 0
  }
  if (typeof usd !== 'number') return 0
  // A first reading, another session's ledger, or a total that went back: a fresh baseline, nothing to add.
  if (lastUsd === undefined || start !== lastStart || usd < lastUsd) {
    lastUsd = usd
    lastStart = start

    return 0
  }
  const delta = usd - lastUsd
  lastUsd = usd

  return delta > 0 ? delta : 0
}

/** Starts counting from what the session has spent so far: at session start, nothing before is anyone's. */
export async function resetCost($: EngineInterface): Promise<void> {
  lastUsd = undefined
  pending = 0
  target = undefined
  await spentSince($)
}

/** The decision that takes what is spent from now on. */
export function setCostTarget(run: string, level: string, id: string): void {
  target = { run, level, id }
}

/** What was spent with no decision current, handed over once: the new decision's own. */
export function claimPending(): number {
  const had = pending
  pending = 0

  return had
}

/**
 * Adds what was spent since the last reading to the current decision in
 * `record`; true when the record changed and wants writing.
 */
export async function settleCost($: EngineInterface, record: GameRecord): Promise<boolean> {
  const total = pending + (await spentSince($))
  if (total <= 0) return false
  const run = target ? record.runs.find(one => one.id === target?.run) : undefined
  const decision = run?.decisions.find(one => one.level === target?.level && one.id === target?.id)
  if (!decision) {
    pending = total

    return false
  }
  decision.cost = Math.round(((decision.cost ?? 0) + total) * 10000) / 10000
  pending = 0

  return true
}
