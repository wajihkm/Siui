// The card's graph, as SVG, top to bottom: the inputs in a row at the top, the
// files whose facts drive the decision; the decision in the middle, drawn as a
// cloud; the outputs in a row at the bottom, the files the answer will change.
// An edge is solid when sure (an input read this session, an output that will
// change), dashed when it only might apply, dotted for a file that is not
// there (a missing input; a new output). A strip at the top shows the card's
// place in its level. Mid greys and one accent per side, for dark and light
// themes. The surface scales the drawing to the slot's width.

import type { GameCard, GameSource } from '../types'
import { isInput, isOutput, isSolidInput, isSolidOutput } from './sources'

const WIDTH = 680
const TEXT = '#8b8b8b'
const ACCENT = '#3b82f6'
const OUT = '#10b981'
const DASH = '#9ca3af'
const NODE_H = 30
const NODE_MAX_W = 190
const NODE_GAP = 12
const FONT = 13
const STRIP_H = 26
const HEADING_H = 18
const EDGE_H = 54 // the vertical room an edge gets
const CLOUD_W = 220
const CLOUD_H = 104

function esc(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function fit(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

function stroke(colour: string, isSolid: boolean, isMissing: boolean): string {
  if (isMissing) return `stroke="${DASH}" stroke-width="1.5" stroke-dasharray="2 4"`
  if (isSolid) return `stroke="${colour}" stroke-width="2.5"`

  return `stroke="${DASH}" stroke-width="1.5" stroke-dasharray="7 5"`
}

/** A vertical S-curve from (x1, y1) down to (x2, y2). */
function edge(x1: number, y1: number, x2: number, y2: number, style: string, title: string): string {
  const bend = (y2 - y1) / 2

  return `<path d="M${x1},${y1} C${x1},${y1 + bend} ${x2},${y2 - bend} ${x2},${y2}" fill="none" ${style}><title>${esc(title)}</title></path>`
}

/** The words behind an edge: an input's certainty, an output's. */
function edgeTitle(source: GameSource, side: 'in' | 'out'): string {
  if (side === 'in') {
    if (source.isMissing) return `${source.name}: drove the decision, but the file is missing`
    return isSolidInput(source)
      ? `${source.name}: drove the decision; read in this session and relied on`
      : `${source.name}: may have driven the decision; not read in this session`
  }
  if (source.isMissing) return `${source.name}: will be created by the answer, a new file`

  return isSolidOutput(source) ? `${source.name}: will change because of the answer` : `${source.name}: might change because of the answer`
}

/** The x of each node of a row of `n`, with the row's node width, centred on the drawing. */
function rowLayout(n: number): { width: number; xs: number[] } {
  const width = Math.min(NODE_MAX_W, Math.floor((WIDTH - 20 - (n - 1) * NODE_GAP) / Math.max(n, 1)))
  const total = n * width + (n - 1) * NODE_GAP
  const x0 = (WIDTH - total) / 2

  return { width, xs: Array.from({ length: n }, (_, i) => x0 + i * (width + NODE_GAP)) }
}

/** How big a file's work is, from its size on disk: 1.0 for a small file to 1.3 for a large one, never more. */
function fileScale(bytes: number | undefined): number {
  if (!bytes) return 1

  return Math.min(1.3, Math.max(0.9, 0.75 + Math.log10(Math.max(bytes, 10)) / 8))
}

function node(
  x: number,
  y: number,
  width: number,
  colour: string,
  isSolid: boolean,
  label: string,
  title: string,
  bytes?: number,
): string {
  const border = isSolid ? colour : DASH
  const k = fileScale(bytes)
  const h = NODE_H * k
  const w = Math.min(width * k, width + 24)
  const xx = x - (w - width) / 2
  const yy = y - (h - NODE_H) / 2
  const chars = Math.max(6, Math.floor((w - 16) / 7))
  const sized = bytes ? ` · ${bytes >= 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes} B`}` : ''

  return (
    `<g><title>${esc(title + sized)}</title>` +
    `<rect x="${xx}" y="${yy}" width="${w}" height="${h}" rx="7" fill="none" stroke="${border}" stroke-width="${(1.3 * k).toFixed(2)}"/>` +
    `<text x="${xx + w / 2}" y="${yy + h / 2 + 5}" font-size="${(FONT * Math.min(k, 1.15)).toFixed(1)}" fill="${TEXT}" text-anchor="middle">${esc(fit(label, chars))}</text>` +
    `</g>`
  )
}

/** A cloud of `CLOUD_W` by `CLOUD_H`, its top-left corner at (x, y). */
function cloud(x: number, y: number): string {
  // Drawn in a 150 by 75 box, then scaled to the cloud's size.
  const path =
    'M20,70 a20,20 0 0 1 0,-40 a25,25 0 0 1 40,-18 a28,28 0 0 1 50,5 a22,22 0 0 1 20,35 a18,18 0 0 1 -10,18 z'
  const sx = CLOUD_W / 150
  const sy = CLOUD_H / 75

  return `<path d="${path}" transform="translate(${x},${y}) scale(${sx.toFixed(3)},${sy.toFixed(3)})" fill="${ACCENT}" fill-opacity="0.12" stroke="${ACCENT}" stroke-width="1.5" stroke-linejoin="round"/>`
}

function titleLines(title: string): string[] {
  const max = 22
  if (title.length <= max) return [title]
  const words = title.split(' ')
  const first: string[] = []
  while (words.length > 0 && `${first.join(' ')} ${words[0]}`.trim().length <= max) first.push(words.shift() as string)
  if (first.length === 0) first.push(words.shift() as string)

  return [fit(first.join(' '), max), fit(words.join(' '), max)].filter(line => line !== '')
}

/** The SVG of a card's graph, with its alt text and size in CSS pixels. */
export function cardGraph(card: GameCard): { source: string; alt: string; width: number; height: number } {
  const inputs = card.sources.filter(isInput)
  const outputs = card.sources.filter(isOutput)
  const parts: string[] = []

  // Vertical plan: strip, inputs heading and row, edges, cloud, edges, outputs row and heading, legend.
  const inHeadY = STRIP_H + HEADING_H
  const inY = inHeadY + 6
  const cloudY = inY + NODE_H + EDGE_H
  const outY = cloudY + CLOUD_H + EDGE_H
  const outHeadY = outY + NODE_H + HEADING_H
  const height = outHeadY + 30
  const midX = WIDTH / 2

  // The strip: level and title on the left, one box per card of the level on the right.
  const where = card.levelTitle ? `Level ${card.level} · ${card.levelTitle}` : `Level ${card.level}`
  parts.push(`<text x="10" y="17" font-size="${FONT}" fill="${TEXT}">${esc(where)}</text>`)
  if (card.count && card.index) {
    const x0 = WIDTH - 10 - card.count * 22
    for (let i = 1; i <= card.count; i += 1) {
      const x = x0 + (i - 1) * 22
      const fill = i <= card.index ? ACCENT : 'none'
      const opacity = i < card.index ? '0.45' : '1'
      const boxTitle = i < card.index ? `card ${i}: decided` : i === card.index ? `card ${i}: this one` : `card ${i}: ahead`
      parts.push(
        `<rect x="${x}" y="7" width="16" height="11" rx="2" fill="${fill}" fill-opacity="${opacity}" stroke="${DASH}" stroke-width="1"><title>${boxTitle}</title></rect>`,
      )
    }
    parts.push(
      `<text x="${x0 - 8}" y="17" font-size="${FONT - 1}" fill="${TEXT}" text-anchor="end">card ${card.index} of ${card.count}</text>`,
    )
  }

  // Inputs: a row at the top, edges down into the cloud's top.
  parts.push(`<text x="${midX}" y="${inHeadY}" font-size="${FONT - 2}" fill="${DASH}" text-anchor="middle">drives the decision</text>`)
  const extras = card.extraSources ?? []
  const extraIn = extras.filter(isInput)
  const extraOut = extras.filter(isOutput)
  const icons = (list: readonly GameSource[], y: number, colour: string, side: 'in' | 'out'): string => {
    if (list.length === 0) return ''
    const made: string[] = []
    const x0 = WIDTH - 10 - list.length * 18
    made.push(`<text x="${x0 - 6}" y="${y + 4}" font-size="${FONT - 2}" fill="${DASH}" text-anchor="end">+${list.length} more</text>`)
    list.forEach((source, i) => {
      const x = x0 + i * 18
      const sure = side === 'in' ? isSolidInput(source) : isSolidOutput(source)
      const stroke = source.isMissing ? DASH : sure ? colour : DASH
      made.push(
        `<g><title>${esc(`${edgeTitle(source, side)}${source.why ? ` (${source.why})` : ''} · ${source.path}`)}</title>` +
          `<path d="M${x},${y - 6} h7 l4,4 v9 a1.5,1.5 0 0 1 -1.5,1.5 h-9.5 a1.5,1.5 0 0 1 -1.5,-1.5 v-11.5 a1.5,1.5 0 0 1 1.5,-1.5 z M${x + 7},${y - 6} v4 h4" fill="none" stroke="${stroke}" stroke-width="1.3" stroke-linejoin="round"${sure ? '' : ' stroke-dasharray="2 2"'}/></g>`,
      )
    })

    return made.join('')
  }
  parts.push(icons(extraIn, inHeadY - 4, ACCENT, 'in'))
  if (inputs.length === 0) {
    parts.push(`<text x="${midX}" y="${inY + NODE_H / 2 + 4}" font-size="${FONT - 1}" fill="${DASH}" text-anchor="middle">no input listed</text>`)
  } else {
    const row = rowLayout(inputs.length)
    inputs.forEach((source, i) => {
      const x = row.xs[i] ?? 10
      const isSolid = isSolidInput(source)
      const label = source.isMissing ? `${source.name} (missing)` : source.name
      const title = `${edgeTitle(source, 'in')}${source.why ? ` (${source.why})` : ''} · ${source.path}`
      parts.push(node(x, inY, row.width, ACCENT, isSolid, label, title, source.bytes))
      parts.push(
        edge(x + row.width / 2, inY + NODE_H, midX, cloudY + 10, stroke(ACCENT, isSolid, source.isMissing === true), title),
      )
    })
  }

  // The decision: a cloud in the middle with the title inside.
  parts.push(`<g><title>${esc(`${card.full?.title ?? card.title}. ${card.full?.short ?? card.short}`)}</title>${cloud(midX - CLOUD_W / 2, cloudY)}</g>`)
  const lines = titleLines(card.title)
  const centreY = cloudY + CLOUD_H / 2 + 6
  const firstY = lines.length === 1 ? centreY + 5 : centreY - 3
  lines.forEach((line, i) => {
    parts.push(
      `<text x="${midX}" y="${firstY + i * 16}" font-size="${FONT}" font-weight="bold" fill="${TEXT}" text-anchor="middle">${esc(line)}</text>`,
    )
  })

  // Outputs: a row at the bottom, edges down from the cloud's bottom.
  if (outputs.length === 0) {
    parts.push(`<text x="${midX}" y="${outY + NODE_H / 2 + 4}" font-size="${FONT - 1}" fill="${DASH}" text-anchor="middle">nothing changes</text>`)
  } else {
    const row = rowLayout(outputs.length)
    outputs.forEach((source, i) => {
      const x = row.xs[i] ?? 10
      const isSolid = isSolidOutput(source)
      const label = source.isMissing ? `${source.name} (new)` : source.name
      const title = `${edgeTitle(source, 'out')}${source.why ? ` (${source.why})` : ''} · ${source.path}`
      parts.push(edge(midX, cloudY + CLOUD_H - 6, x + row.width / 2, outY, stroke(OUT, isSolid, false), title))
      parts.push(node(x, outY, row.width, OUT, isSolid, label, title, source.bytes))
    })
  }
  parts.push(`<text x="${midX}" y="${outHeadY}" font-size="${FONT - 2}" fill="${DASH}" text-anchor="middle">will change</text>`)
  parts.push(icons(extraOut, outHeadY - 4, OUT, 'out'))

  // The legend, one row at the bottom.
  const ly = height - 8
  const legend: Array<[string, string, string]> = [
    [`stroke="${ACCENT}" stroke-width="2.5"`, 'read and used', 'A solid blue line: the file was read in this session and the card relies on it'],
    [`stroke="${OUT}" stroke-width="2.5"`, 'will change', 'A solid green line: the answer will change this file'],
    [`stroke="${DASH}" stroke-width="1.5" stroke-dasharray="7 5"`, 'might', 'A dashed line: it may apply, or might change; not sure'],
    [`stroke="${DASH}" stroke-width="1.5" stroke-dasharray="2 4"`, 'not there yet', 'A dotted line: the file is not on disk; an output to be created, or a missing input'],
  ]
  let lx = 10
  for (const [style, label, words] of legend) {
    parts.push(`<g><title>${esc(words)}</title><line x1="${lx}" y1="${ly - 4}" x2="${lx + 26}" y2="${ly - 4}" ${style}/>`)
    parts.push(`<text x="${lx + 32}" y="${ly}" font-size="${FONT - 2}" fill="${TEXT}">${label}</text></g>`)
    lx += 32 + label.length * 6.5 + 22
  }

  const source = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${WIDTH} ${height}" font-family="system-ui, sans-serif">${parts.join('')}</svg>`
  const inAlt = inputs.map(s => `${isSolidInput(s) ? 'read' : 'maybe'} ${s.name}`).join(', ') || 'none'
  const outAlt = outputs.map(s => `${isSolidOutput(s) ? 'will change' : 'might change'} ${s.name}`).join(', ') || 'none'
  const alt = `${card.title}. In: ${inAlt}. Out: ${outAlt}.`

  return { source, alt, width: WIDTH, height }
}
