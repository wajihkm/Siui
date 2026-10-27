// Packs: where a pack file is, and the plan it declares (its levels, their
// titles and card counts), read off its `## Level 1-2 · Structure (4 cards)`
// headings. The plan lets the map show the levels ahead before they start.

import type { EngineInterface } from 'claude-code'

export type PlanCard = { id: string; title: string }
export type PlanLevel = { level: string; title: string; count?: number; cards?: PlanCard[] }

const HEADING = /^##\s+Level\s+(\d+-\d+)\s*[·:-]\s*(.+?)(?:\s*\((\d+)\s+cards?\))?\s*$/
const CARD_ROW = /^\|\s*`([a-z0-9-]+)`\s*\|\s*([^|]+?)\s*\|/

/**
 * The levels a pack declares, in the order written, each with the cards its
 * table lists (`| \`id\` | title | options |`), so the status can name the
 * next card to present.
 */
export function parsePack(text: string): PlanLevel[] {
  const plan: PlanLevel[] = []
  let current: PlanLevel | undefined
  for (const line of text.split('\n')) {
    const heading = HEADING.exec(line)
    if (heading) {
      const [, level = '', title = '', count] = heading
      if (level === '' || plan.some(one => one.level === level)) {
        current = undefined
        continue
      }
      current = { level, title: title.trim() }
      if (count) current.count = Number(count)
      plan.push(current)
      continue
    }
    if (line.startsWith('## ')) current = undefined
    const row = current ? CARD_ROW.exec(line) : null
    if (row && current) {
      const [, id = '', title = ''] = row
      if (id !== '' && !(current.cards ?? []).some(one => one.id === id)) {
        current.cards = [...(current.cards ?? []), { id, title: title.trim() }]
      }
    }
  }

  return plan
}

/**
 * The next card to present in a run, from its plan: the first card of the
 * first level not done that has no answer yet. Undefined without a plan with
 * cards, or when every planned card is answered.
 */
export function nextCardOf(run: {
  plan?: PlanLevel[]
  levels: Record<string, 'open' | 'done'>
  decisions: Array<{ level: string; id: string; via?: string }>
  roads?: Record<string, { onDisk: 'a' | 'b'; merged?: string }>
}): { level: string; id: string; title: string } | undefined {
  for (const level of run.plan ?? []) {
    if (run.levels[level.level] === 'done') continue
    // A forked stage: the cards answered before the fork are shared; the rest are asked on the road on disk.
    const fork = run.roads?.[level.level]
    const road = fork && fork.merged === undefined ? `${level.level}${fork.onDisk}` : ''
    if (road && run.levels[road] === 'done') continue
    for (const card of level.cards ?? []) {
      const answeredAt = (at: string) => run.decisions.some(one => one.level === at && one.id === card.id && one.via !== 'chat' && one.via !== 'skipped')
      if (answeredAt(level.level) || (road !== '' && answeredAt(road))) continue
      return { level: road || level.level, id: card.id, title: card.title }
    }
  }

  return undefined
}

/**
 * Where a pack named `pack` may be, in the order tried: the project's own
 * skill folder, the folders the project's configuration names, the plugin's
 * bundled skill, the user's skill folder.
 */
export function packCandidates(
  pack: string,
  root: string,
  home: string | undefined,
  pluginRoot: string,
  extra: readonly string[] = [],
): string[] {
  const name = pack.replace(/\.md$/, '')
  if (name === '' || name.includes('/') || name.includes('..')) return []
  const base = root.replace(/\/$/, '')
  const paths = [`${base}/.claude/skills/decision-cards/packs/${name}.md`]
  for (const folder of extra) {
    const absolute = folder.startsWith('/') ? folder : `${base}/${folder}`
    paths.push(`${absolute.replace(/\/$/, '')}/${name}.md`)
  }
  paths.push(`${pluginRoot.replace(/\/$/, '')}/demo/packs/${name}.md`)
  if (home) paths.push(`${home}/.claude/skills/decision-cards/packs/${name}.md`)

  return paths
}

/** The plan of a pack, read from the first candidate that exists; empty when none. */
/** The first place the pack is found, or undefined. */
export async function findPack($: EngineInterface, pack: string, root: string, extra: string[]): Promise<string | undefined> {
  const home = (await $.env.get('HOME')) ?? ''
  for (const path of packCandidates(pack, root, home, $.plugin.root, extra)) {
    if (await $.fs.exists(path)) return path
  }

  return undefined
}

export async function readPlan(
  $: EngineInterface,
  pack: string,
  root: string,
  extra: readonly string[] = [],
): Promise<PlanLevel[]> {
  const home = await $.env.get('HOME')
  for (const path of packCandidates(pack, root, home, $.plugin.root, extra)) {
    if (await $.fs.exists(path)) {
      try {
        return parsePack(await $.fs.read(path))
      } catch {
        return []
      }
    }
  }

  return []
}
