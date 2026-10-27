// The card drawn in the frame above the engine's question dialog: title, the
// one-line description, the Explain toggle, the consequences of each option,
// what remains in the level, the graph of inputs and outputs, the source
// links, then the engine's own question card last (the dialog's tree holds it
// exactly once, at the bottom).
//
// Rows are counted at 40 columns: one per text plus one per 40 characters. The
// frame may take 48 rows on VS Code, the desktop and mobile apps, but only 12
// on the terminal, which gets a compact drawing: labels instead of
// consequences, names instead of links, no graph, the explanation cut short.

import type { EngineInterface, RenderElement, RenderInput } from 'claude-code'

import type { GameCard, GameSource } from '../types'
import { cardGraph } from './graph'
import { DASHED, SOLID, cut } from './input'
import { isInput, isOutput, isSolidInput, isSolidOutput } from './sources'
import { cap, words } from './words'

type AskRender = RenderInput<'AskUserQuestion'>

const TERMINAL_EXPLAIN = 200

function plainName(source: GameSource, side: 'in' | 'out'): string {
  const name = source.name.replace(/[[\]]/g, ' ')
  if (!source.isMissing) return name

  return side === 'in' ? `${name} (missing)` : `${name} (new)`
}

function entry(source: GameSource, side: 'in' | 'out', isLinked: boolean): string {
  const isSolid = side === 'in' ? isSolidInput(source) : isSolidOutput(source)
  const glyph = isSolid ? SOLID : DASHED
  const name = plainName(source, side)

  return isLinked && source.href && !source.isMissing ? `${glyph} [${name}](${source.href})` : `${glyph} ${name}`
}

function sourcesLine(sources: readonly GameSource[], isLinked: boolean, extras: readonly GameSource[] = []): string {
  const ins = sources.filter(isInput).map(source => entry(source, 'in', isLinked))
  const outs = sources.filter(isOutput).map(source => entry(source, 'out', isLinked))
  const moreIn = extras.filter(isInput)
  const moreOut = extras.filter(isOutput)
  const more = (list: readonly GameSource[]): string =>
    list.length > 0 ? ` · +${list.length} more (${cut(list.map(one => one.name).join(', '), 60)})` : ''
  const parts: string[] = []
  if (ins.length > 0 || moreIn.length > 0) parts.push(`In: ${ins.join(' · ')}${more(moreIn)}`)
  if (outs.length > 0 || moreOut.length > 0) parts.push(`Out: ${outs.join(' · ')}${more(moreOut)}`)

  return parts.join('  |  ')
}

/** The sources line as markdown: a `file:` link per source the surface can open. */
export function sourcesMarkdown(sources: readonly GameSource[], extras: readonly GameSource[] = []): string {
  return sourcesLine(sources, true, extras)
}

/** The sources line as plain text, for a surface that draws no markdown in the dialog. */
export function sourcesText(sources: readonly GameSource[], extras: readonly GameSource[] = []): string {
  return sourcesLine(sources, false, extras)
}

const MARK_WORDS: Record<NonNullable<GameCard['mark']>, string> = {
  bug: 'bug or risk',
  feature: 'feature',
  problem: 'problem',
  check: 'check',
}

function headerLine(card: GameCard): string {
  const w = words()
  const world = card.world === 0 ? 'Side quests' : `${cap(w.world)} ${card.world}`
  const where = `${world} › ${card.levelTitle ? `${card.level} ${card.levelTitle}` : `${cap(w.stage)} ${card.level}`}`
  const step = card.index && card.count ? ` · ${w.card} ${card.index} of ${card.count}` : ''
  const kind = card.kind === 'info' ? ' · info' : card.kind === 'boss' ? ` · ${w.boss}` : ''
  const mark = card.mark ? ` · ${MARK_WORDS[card.mark]}` : ''

  return `${where}${step}${kind}${mark}`
}

export type CardToggles = {
  isExplainOpen: boolean
  isGraphOpen: boolean
  toggleExplain: () => void
  toggleGraph: () => void
  /** Opens the HTML board, as /siui board does. */
  openBoard?: () => void
}

export function drawCard(
  $: EngineInterface,
  e: AskRender,
  card: GameCard,
  toggles: CardToggles,
  engine: RenderElement,
): RenderElement {
  const { Box, Text, Button, Markdown } = $.ui.resolve(e)
  const { isExplainOpen, isGraphOpen, toggleExplain, toggleGraph, openBoard } = toggles
  const isOpen = isExplainOpen && card.explain !== undefined

  if (e.surface === 'terminal') {
    // Twelve rows at most: the header and title, then either the short line
    // with the option labels, or the explanation; the source names last.
    const labels = card.options
      .map(option => (option.label === card.recommended ? `★ ${option.label}` : option.label))
      .join(' · ')

    return (
      <Box flexDirection="column">
        <Text dimColor>{headerLine(card)}</Text>
        <Text bold>{card.title}</Text>
        {isOpen ? <Text>{cut(card.explain, TERMINAL_EXPLAIN)}</Text> : <Text>{card.short}</Text>}
        {card.note && !isOpen ? <Text color="yellow">{cut(card.note, 80)}</Text> : null}
        {!isOpen ? <Text dimColor>{labels}</Text> : null}
        {card.sources.length > 0 ? <Text dimColor>{sourcesText(card.sources, card.extraSources)}</Text> : null}
        {engine}
      </Box>
    )
  }

  const { Svg } = $.ui.resolve(e as RenderInput<'AskUserQuestion', 'vscode'>)
  const graph = isGraphOpen ? cardGraph(card) : { source: '', alt: '' }

  return (
    <Box flexDirection="column">
      <Text dimColor>{headerLine(card)}</Text>
      <Text bold size="heading">
        {card.title}
      </Text>
      <Text>{card.short}</Text>
      {card.note ? <Text color="yellow">{card.note}</Text> : null}
      <Box>
        {card.explain ? (
          <Button
            key="explain"
            plain
            label={isOpen ? 'Hide explanation' : 'Explain'}
            onPress={toggleExplain}
          />
        ) : null}
        {card.explain ? <Text dimColor>{'   '}</Text> : null}
        <Button key="graph" plain label={isGraphOpen ? 'Hide graph' : 'Show graph'} onPress={toggleGraph} />
        {openBoard ? <Text dimColor>{'   '}</Text> : null}
        {openBoard ? <Button key="board" plain label="Board" onPress={openBoard} /> : null}
      </Box>
      {isOpen ? <Markdown text={card.explain ?? ''} /> : null}
      {!isOpen ? <Text dimColor>Consequences:</Text> : null}
      {!isOpen
        ? card.options.map(option =>
            option.picture ? (
              // A drawn option: its picture beside its line, so the drawings align with the answers.
              <Box key={`opt-${option.label}`} flexDirection="row" gap={1}>
                <Svg source={option.picture} alt={`${option.label}: its drawing`} width={96} height={64} />
                <Text dimColor>
                  {option.label === card.recommended ? '★ ' : '· '}
                  {option.label}
                  {option.effect ? ` — ${option.effect}` : ''}
                </Text>
              </Box>
            ) : (
              <Text key={`opt-${option.label}`} dimColor>
                {option.label === card.recommended ? '★ ' : '· '}
                {option.label}
                {option.effect ? ` — ${option.effect}` : ''}
              </Text>
            ),
          )
        : null}
      {!isOpen && card.remaining ? <Text dimColor>Remaining in {card.level}: {card.remaining}</Text> : null}
      {isGraphOpen ? <Svg source={graph.source} alt={graph.alt} isInteractive /> : null}
      {card.sources.length > 0 ? <Markdown text={sourcesMarkdown(card.sources, card.extraSources)} dimColor /> : null}
      {engine}
    </Box>
  )
}
