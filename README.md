# Sudoku 🔢

**A sudoku that explains itself.** Play, pencil, ask for a hint — and every hint is
a step the engine has *proven*, shown on the board with the sentence that justifies it.

Live: **https://sudoku.rogzy.org** · The interface is in **French**.

## Why it exists

A web solver once served a "W-Wing" hint whose elimination broke a perfectly valid
grid — delivered with a specialist's confidence, and nothing told the player it was
wrong. This engine was built so that cannot happen here:

- **Deterministic engine, no AI in the solving loop.** 23 techniques, from singles
  to wings, fish, chains and uniqueness patterns, each a detector that returns the
  exact cells it reasoned on. Sudoku logic is decidable; a solver written once is
  right forever.
- **Every hint is a proven step.** Before a step is shown it is checked against the
  unique solution; a detector bug becomes an internal alert, never a confident lie.
- **Difficulty is measured, not chosen.** Generated puzzles are graded on the
  cheapest solving path (Sudoku Explainer-style ratings) and filed where they land.

## What's inside

- **Play** — generated puzzles in four bands, three pencil layers, a four-rung hint
  ladder served by the server (the solution never reaches the page).
- **Techniques** — one page per technique: the rule, how to spot it, the trap,
  worked examples re-derived from the engine, and **20 drills** each.
- **Assistant** — type in any grid and see every available step, grouped by
  technique, with the argument for each.

## Run it

Python 3.11+, standard library only.

```sh
SUDOKU_PUBLIC=1 python3 app.py        # http://127.0.0.1:8801
```

| Variable | Default | |
|---|---|---|
| `SUDOKU_DIR` | `./data` | where games and the puzzle pool live |
| `PORT` | `8801` | listen port |
| `LUNA_APP_HOST` | `127.0.0.1` | listen address (`0.0.0.0` in a container) |
| `SUDOKU_PUBLIC` | unset | `1` = multi-visitor mode: one cookie per browser, the stylesheet served by the app, private-only routes closed |

Without `SUDOKU_PUBLIC=1` the app runs in single-user mode and expects a reverse
proxy to serve the stylesheet at `/static/luna-ui.css` (it is in `public/static/`).
The visitor cookie is `Secure`: serve it over HTTPS (browsers accept it on `localhost`).

### Docker

```sh
git archive --format=tar <tag> | docker build -t sudoku -f deploy/public/Dockerfile -
docker run -d -p 127.0.0.1:8801:8801 --read-only --tmpfs /tmp -v sudoku-data:/data sudoku
```

See `deploy/public/README.md`.

## Tests

```sh
SUDOKU_DIR=$(mktemp -d) SUDOKU_POOL_FILL=0 python3 -m unittest discover tests
```

## Credits

Made by [Rogzy](https://rogzy.org) & Luna.

## Licence

MIT — see `LICENSE`. © 2026 Rogzy.
