// The universe's words: what a world, a stage, a step, a card and the boss are
// called in the chat's card header and world map. The configuration's theme
// block names the universe; its set file (board/universes/<name>.json, or the
// project's own .claude/universes/<name>.json) carries the words. Neutral
// words when none is set.

export type Words = { world: string; stage: string; step: string; card: string; boss: string }

export const DEFAULT_WORDS: Words = { world: 'world', stage: 'stage', step: 'step', card: 'card', boss: 'boss' }

let current: Words = { ...DEFAULT_WORDS }

export function words(): Words {
  return current
}

export function setWords(next: Partial<Words> | undefined): void {
  current = { ...DEFAULT_WORDS }
  for (const key of Object.keys(DEFAULT_WORDS) as Array<keyof Words>) {
    const value = next?.[key]
    if (typeof value === 'string' && value.trim() !== '') current[key] = value.trim().slice(0, 24)
  }
}

export function cap(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
