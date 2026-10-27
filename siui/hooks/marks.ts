// The things that land on the map, in plain words first and game words behind:
// a bug or risk is an enemy, a feature a power-up, a problem a challenge, a
// check a coin to collect, a jump a warp pipe, a save point a checkpoint.

import type { GameEvent } from '../types'

export type MarkKind = GameEvent['kind']

export const MARKS: Record<MarkKind, { name: string; game: string; done: string }> = {
  enemy: { name: 'bug or risk', game: 'enemy', done: 'fixed' },
  powerup: { name: 'feature', game: 'power-up', done: 'built' },
  challenge: { name: 'problem', game: 'challenge', done: 'cleared' },
  check: { name: 'check', game: 'coin', done: 'passed' },
  pipe: { name: 'jump', game: 'warp pipe', done: 'taken' },
  checkpoint: { name: 'save point', game: 'checkpoint', done: 'returned to' },
}

/** The kind behind a plain or a game word; undefined for anything else. */
export function kindOf(word: unknown): MarkKind | undefined {
  if (typeof word !== 'string') return undefined
  const text = word.trim().toLowerCase()
  const aliases: Record<string, MarkKind> = {
    enemy: 'enemy',
    bug: 'enemy',
    risk: 'enemy',
    security: 'enemy',
    powerup: 'powerup',
    'power-up': 'powerup',
    feature: 'powerup',
    requirement: 'powerup',
    challenge: 'challenge',
    problem: 'challenge',
    check: 'check',
    coin: 'check',
    test: 'check',
    pipe: 'pipe',
    jump: 'pipe',
    checkpoint: 'checkpoint',
    save: 'checkpoint',
    'save point': 'checkpoint',
  }

  return aliases[text]
}
