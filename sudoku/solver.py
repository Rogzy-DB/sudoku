"""Brute force — the ground truth everything else is checked against.

Two jobs, and they are different:

* `solve_count` answers **"how many solutions?"** and is the uniqueness gate the
  generator and the importer both stand on.
* `solution` answers **"what is the answer?"** and is used for one thing only:
  proving that a step the technique engine is about to show is not a lie
  (`techniques.next_step(..., safe=True)`). It must NEVER reach the page — the
  whole point of the app is that the player derives the digits.

Deliberately not clever: MRV heuristic + bitmask propagation is ~50 µs on a
human puzzle, and a clever solver you don't fully trust is worse than a plain
one you do.
"""

from .grid import ALL, PEERS, UNITS, bit, bits, count, candidates


def _search(cells, cand, cap, found):
    # pick the most constrained empty cell (MRV) — the whole speed of the thing
    best, best_n = -1, 10
    for i in range(81):
        if not cells[i]:
            n = count(cand[i])
            if n == 0:
                return          # dead end: an empty cell with no candidate
            if n < best_n:
                best, best_n = i, n
                if n == 1:
                    break
    if best < 0:                # nothing empty left → a full, valid grid
        found.append(cells[:])
        return
    for d in bits(cand[best]):
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
            _search(cells, nc, cap, found)
            cells[best] = 0
        if len(found) >= cap:
            return


def solve_all(cells, cap=2):
    """Up to `cap` solutions. `cap=2` is the uniqueness test — stop at two."""
    found = []
    _search(cells[:], candidates(cells), cap, found)
    return found


def solve_count(cells, cap=2):
    return len(solve_all(cells, cap))


def solution(cells):
    """The unique solution, or None if there are zero or several.

    Returning None for *several* rather than "the first one" is deliberate: an
    ambiguous grid has no ground truth, so every safety check downstream must
    degrade honestly rather than validate against an arbitrary branch.
    """
    s = solve_all(cells, 2)
    return s[0] if len(s) == 1 else None


def is_uniquely_solvable(cells):
    return solve_count(cells, 2) == 1
