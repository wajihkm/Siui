// The world map `/game status` draws, as SVG: the levels of the run along a
// winding path, each a stop with its id, title and progress; stops done are
// filled, the current one carries a "you are here" marker, the ones ahead are
// dashed; the boss is a star. Under each stop, its answers so far. Mid greys
// and one accent per state, for dark and light themes.

import type { GameRun } from './record'
import { overviewOf } from './record'
import { cap, words } from './words'

const WIDTH = 680
const TEXT = '#8b8b8b'
const ACCENT = '#3b82f6'
const HERE = '#10b981'
const DASH = '#9ca3af'
const FONT = 12

function esc(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function fit(text: string, max: number): string {
  const flat = text.replace(/\s+/g, ' ').trim()

  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

function star(cx: number, cy: number, r: number): string {
  const points: string[] = []
  for (let i = 0; i < 10; i += 1) {
    const radius = i % 2 === 0 ? r : r / 2.2
    const angle = -Math.PI / 2 + (i * Math.PI) / 5
    points.push(`${(cx + radius * Math.cos(angle)).toFixed(1)},${(cy + radius * Math.sin(angle)).toFixed(1)}`)
  }

  return points.join(' ')
}

/** The SVG of a run's map, with its alt text. */
export function mapSvg(run: GameRun): { source: string; alt: string } {
  const views = overviewOf(run)
  const n = views.length
  const parts: string[] = []
  const columnW = n > 0 ? Math.min(170, Math.floor((WIDTH - 40) / n)) : WIDTH - 40
  const chars = Math.max(10, Math.floor((columnW - 12) / 6.2))
  const maxLines = views.reduce((most, one) => Math.max(most, one.decisions.length), 0)
  const pathTop = 44
  // The stops wave 12 up or down; their three lines of text end 63 below.
  const listTop = pathTop + 22 + 12 + 63 + 20
  const height = listTop + Math.max(maxLines, 1) * 15 + 18

  // Header.
  const state = run.finishedAt ? `finished ${esc(String(run.finishedAt))}` : 'in progress'
  parts.push(
    `<text x="10" y="18" font-size="${FONT + 2}" font-weight="bold" fill="${TEXT}">${run.pack === 'side' ? 'Side quests' : `${esc(cap(words().world))} ${esc(String(run.world))}`}</text>`,
    `<text x="${10 + 70}" y="18" font-size="${FONT}" fill="${DASH}">${esc(run.pack)} · ${state} · ${run.decisions.length} decisions</text>`,
  )
  if (n === 0) {
    parts.push(`<text x="10" y="${pathTop + 20}" font-size="${FONT}" fill="${DASH}">No ${esc(words().stage)} started yet.</text>`)
  }

  // The stops along a wave, left to right.
  const x0 = 20 + columnW / 2
  const stops = views.map((view, i) => ({
    view,
    x: x0 + i * columnW,
    y: pathTop + 22 + 12 * Math.sin(i * 1.1),
  }))

  // The path between stops: solid up to the current stop, dashed beyond.
  stops.forEach((stop, i) => {
    const next = stops[i + 1]
    if (!next) return
    const isWalked = stop.view.state === 'done'
    const style = isWalked
      ? `stroke="${ACCENT}" stroke-width="3"`
      : `stroke="${DASH}" stroke-width="2" stroke-dasharray="6 5"`
    const midX = (stop.x + next.x) / 2
    // Named `tip`, not `words`: `words()` is the universe's vocabulary, imported above.
    const tip = isWalked
      ? `${stop.view.level} is done; the path to ${next.view.level} is walked`
      : `${stop.view.level} is not done yet; the path to ${next.view.level} lies ahead`
    parts.push(
      `<path d="M${stop.x},${stop.y} C${midX},${stop.y} ${midX},${next.y} ${next.x},${next.y}" fill="none" ${style}><title>${esc(tip)}</title></path>`,
    )
  })

  // The stops themselves.
  for (const { view, x, y } of stops) {
    const colour = view.state === 'done' ? ACCENT : view.state === 'current' ? HERE : DASH
    const fill = view.state === 'done' ? ACCENT : view.state === 'current' ? HERE : 'none'
    const dash = view.state === 'ahead' ? ' stroke-dasharray="4 3"' : ''
    const tip = `${view.level}${view.title ? ` ${view.title}` : ''}: ${view.state === 'done' ? 'done' : view.state === 'current' ? 'you are here' : view.state === 'open' ? 'started' : 'ahead'}, ${view.decided}${view.count ? ` of ${view.count}` : ''} decided${view.chat.length ? `, ${view.chat.length} in the chat` : ''}`
    parts.push(`<g><title>${esc(tip)}</title>`)
    if (view.isBoss) {
      parts.push(`<polygon points="${star(x, y, 17)}" fill="${fill}" fill-opacity="${fill === 'none' ? 1 : 0.9}" stroke="${colour}" stroke-width="2"${dash}/>`)
    } else {
      parts.push(`<circle cx="${x}" cy="${y}" r="14" fill="${fill}" fill-opacity="${fill === 'none' ? 1 : 0.9}" stroke="${colour}" stroke-width="2"${dash}/>`)
    }
    if (view.state === 'done') {
      parts.push(`<text x="${x}" y="${y + 4.5}" font-size="12" font-weight="bold" fill="#ffffff" text-anchor="middle">✓</text>`)
    }
    parts.push('</g>')
    if (view.state === 'current') {
      parts.push(
        `<polygon points="${x - 7},${y - 30} ${x + 7},${y - 30} ${x},${y - 20}" fill="${HERE}"/>`,
        `<text x="${x}" y="${y - 34}" font-size="${FONT - 2}" fill="${HERE}" text-anchor="middle">you are here</text>`,
      )
    }
    const progress = view.isBoss
      ? view.state === 'done'
        ? 'applied'
        : view.state === 'current'
          ? 'now'
          : 'ahead'
      : view.count !== undefined
        ? `${view.decided} of ${view.count}`
        : `${view.decided} decided`
    parts.push(
      `<text x="${x}" y="${y + 34}" font-size="${FONT}" font-weight="bold" fill="${TEXT}" text-anchor="middle">${esc(view.level)}${view.isBoss ? ` ${esc(words().boss)}` : ''}</text>`,
      `<text x="${x}" y="${y + 49}" font-size="${FONT - 1}" fill="${TEXT}" text-anchor="middle">${esc(fit(view.title || '—', chars))}</text>`,
      `<text x="${x}" y="${y + 63}" font-size="${FONT - 2}" fill="${DASH}" text-anchor="middle">${esc(progress)}</text>`,
    )
  }

  // The answers under each stop.
  for (const { view, x } of stops) {
    view.decisions.forEach((one, i) => {
      const y = listTop + i * 15
      parts.push(
        `<text x="${x}" y="${y}" font-size="${FONT - 2}" fill="${TEXT}" text-anchor="middle">${esc(fit(`${one.title}: ${one.answer}`, chars + 4))}</text>`,
      )
    })
  }

  const source = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${WIDTH} ${height}" font-family="system-ui, sans-serif">${parts.join('')}</svg>`
  const alt = views
    .map(view => `${view.level} ${view.title} ${view.state} ${view.decided}${view.count ? ` of ${view.count}` : ''}`)
    .join('; ')

  return { source, alt: `${cap(words().world)} ${run.world} map: ${alt || 'no level yet'}` }
}
