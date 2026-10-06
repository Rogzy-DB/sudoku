# Changelog

## 0.11.7 — 2026-10-06

- Assistant opened from a game: no « Corriger la grille » card, even on a broken position (fixing it there would not reach the game); the note points back to the board.

## 0.11.6 — 2026-10-06

- Assistant: the « Corriger la grille » card disappears once a step has been played (it comes back if the grid turns out broken).
- Space under every card header (the counters were touching the grid and the move menu).

## 0.11.5 — 2026-10-05

- The footer's GitHub link points to this repository.

## 0.11.4 — 2026-10-05 — first public release

- A playable sudoku with generated puzzles in four measured difficulty bands, pencil
  marks, and a hint ladder whose every step is proven by a deterministic engine.
- 23 solving techniques, each with a page (rule, how to spot it, trap, worked
  examples) and 20 practice drills.
- An assistant that lists every available step on a grid you type in.
- A multi-visitor public mode (`SUDOKU_PUBLIC=1`): one cookie per browser, no account.
