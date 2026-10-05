"""Making puzzles — and knowing how hard they are.

Three steps, in this order and no other:

1. a random **complete** grid,
2. **dig** holes while the grid stays uniquely solvable,
3. **grade** what's left by running the technique engine on it.

⚠ The grade is *measured, never chosen*. A generator that digs to a clue count
and calls 24 clues "hard" is lying: clue count and difficulty are only loosely
related, and the player would get "diabolique" puzzles that fall to two singles. So
we dig, we grade, and the puzzle goes in whichever bucket it actually landed
in. That's why generation is opportunistic (`make_batch`) and the app serves
from a pre-filled pool: you cannot order a diabolique, you can only keep the
ones that came out diabolique.

⚠ Uniqueness is checked after **every** removal, not once at the end. A grid
that lost uniqueness three digs ago and got it back is not a thing — once
ambiguous, always ambiguous under further removal — but the check is cheap
(~0.5 ms) and the invariant is worth more than the microseconds.
"""

import random

from .engine import GRADE_LABELS, grade
from .grid import candidates, bits, to_string
from .solver import solve_all, solve_count


def full_grid(rng=None):
    """A random completed grid — a solved sudoku with no givens bias."""
    rng = rng or random.Random()
    cells = [0] * 81
    # seed the first row + first column randomly, then let the solver finish;
    # cheaper and better-distributed than shuffling candidates at every node.
    order = list(range(1, 10))
    rng.shuffle(order)
    for c in range(9):
        cells[c] = order[c]
    sols = []
    _rand_fill(cells, candidates(cells), rng, sols)
    return sols[0]


def _rand_fill(cells, cand, rng, out):
    best, best_n = -1, 10
    for i in range(81):
        if not cells[i]:
            n = bin(cand[i]).count("1")
            if n == 0:
                return False
            if n < best_n:
                best, best_n = i, n
    if best < 0:
        out.append(cells[:])
        return True
    ds = bits(cand[best])
    rng.shuffle(ds)
    from .grid import PEERS, bit
    for d in ds:
        b = bit(d)
        nc = cand[:]
        nc[best] = b
        ok = True
        for j in PEERS[best]:
            if not cells[j] and nc[j] & b:
                nc[j] &= ~b
                if nc[j] == 0:
                    ok = False
                    break
        if ok:
            cells[best] = d
            if _rand_fill(cells, nc, rng, out):
                return True
            cells[best] = 0
    return False


def dig(full, rng=None, symmetric=True, min_clues=22):
    """Remove clues from a solved grid while it stays uniquely solvable."""
    rng = rng or random.Random()
    cells = list(full)
    idx = list(range(81))
    rng.shuffle(idx)
    clues = 81
    for i in idx:
        if clues <= min_clues:
            break
        group = [i, 80 - i] if symmetric and i != 40 else [i]
        group = [j for j in group if cells[j]]
        if not group:
            continue
        saved = [(j, cells[j]) for j in group]
        for j, _ in saved:
            cells[j] = 0
        if solve_count(cells, 2) == 1:
            clues -= len(saved)
        else:
            for j, v in saved:
                cells[j] = v
    return cells


def make(rng=None, max_tier=3, symmetric=True, min_clues=22):
    """One puzzle, graded. Returns the record the pool stores."""
    rng = rng or random.Random()
    full = full_grid(rng)
    puzzle = dig(full, rng, symmetric, min_clues)
    g, label, used = grade(puzzle, max_tier)
    return {"puzzle": to_string(puzzle), "solution": to_string(full),
            "grade": g, "label": label, "techniques": used,
            "clues": sum(1 for v in puzzle if v)}


def make_batch(n, rng=None, **kw):
    rng = rng or random.Random()
    return [make(rng, **kw) for _ in range(n)]


def make_targeted(want_grade, rng=None, tries=60, **kw):
    """Keep generating until one lands in the wanted bucket, or give up.

    Gives up honestly rather than relaxing the target: a "diabolique" that is
    really a "moyen" is worse than no puzzle at all.
    """
    rng = rng or random.Random()
    for _ in range(tries):
        rec = make(rng, **kw)
        if rec["grade"] == want_grade:
            return rec
    return None
