"""The board — geometry, parsing, candidates. No solving lives here.

A grid is a plain `list[int]` of 81 entries, 0 = empty, index `i = r*9 + c`.
Candidates are a parallel `list[int]` of **9-bit masks** (bit `d-1` = digit d is
possible). Masks rather than sets because the engine compares, intersects and
counts candidates millions of times per generated puzzle, and because two cells
with the same mask are then `==` — which is what makes naked subsets and remote
pairs one-liners instead of loops.

⚠ Cell names are 1-based (`R2C3`), indices are 0-based. Every bug in a sudoku
engine is an off-by-one in that conversion, so there is exactly ONE place that
converts each way: `name()` and `parse_cell()`. Never spell `f"R{r+1}"` inline.
"""

import re

ALL = 0x1FF          # every digit possible — 9 bits set
DIGITS = range(1, 10)


def bit(d):
    """Digit → its mask. `bit(1) == 1`, `bit(9) == 256`."""
    return 1 << (d - 1)


def bits(mask):
    """Mask → the sorted digits in it."""
    return [d for d in DIGITS if mask >> (d - 1) & 1]


def count(mask):
    """How many digits are in the mask."""
    return bin(mask).count("1")


def single(mask):
    """The one digit in a 1-bit mask, else None."""
    return bits(mask)[0] if count(mask) == 1 else None


# --- geometry, computed once at import -----------------------------------------

def _box_of(i):
    return (i // 9 // 3) * 3 + (i % 9) // 3


ROWS = [[r * 9 + c for c in range(9)] for r in range(9)]
COLS = [[r * 9 + c for r in range(9)] for c in range(9)]
BOXES = [[i for i in range(81) if _box_of(i) == b] for b in range(9)]
UNITS = ROWS + COLS + BOXES

#: `UNIT_KIND[u]` — ("row"|"col"|"box", 0-based number) for the unit at that index
UNIT_KIND = ([("row", r) for r in range(9)] + [("col", c) for c in range(9)]
             + [("box", b) for b in range(9)])

#: the three units every cell belongs to, as indices into UNITS
UNITS_OF = [[i // 9, 9 + i % 9, 18 + _box_of(i)] for i in range(81)]

#: the 20 cells that constrain a given cell
PEERS = [frozenset(j for u in UNITS_OF[i] for j in UNITS[u] if j != i)
         for i in range(81)]

ROW_OF = [i // 9 for i in range(81)]
COL_OF = [i % 9 for i in range(81)]
BOX_OF = [_box_of(i) for i in range(81)]


def name(i):
    """Cell index → the human name. The ONLY 0-based → 1-based conversion."""
    return f"R{i // 9 + 1}C{i % 9 + 1}"


def parse_cell(s):
    """`"R2C3"` / `"r2c3"` → index, or None. The ONLY 1-based → 0-based one."""
    m = re.fullmatch(r"\s*[Rr](\d)\s*[Cc](\d)\s*", s or "")
    if not m:
        return None
    r, c = int(m.group(1)), int(m.group(2))
    return (r - 1) * 9 + (c - 1) if 1 <= r <= 9 and 1 <= c <= 9 else None


def unit_name_fr(u):
    """Unit index → the French label used in every hint sentence."""
    kind, n = UNIT_KIND[u]
    return {"row": f"la ligne {n + 1}", "col": f"la colonne {n + 1}",
            "box": f"la boîte {n + 1}"}[kind]


def sees(i, j):
    """Do these two cells constrain each other? (False for i == j.)"""
    return j in PEERS[i]


def common_peers(cells):
    """Every cell that sees ALL of `cells` (and is none of them)."""
    if not cells:
        return frozenset()
    out = PEERS[cells[0]]
    for i in cells[1:]:
        out = out & PEERS[i]
    return out - set(cells)


# --- parsing / printing --------------------------------------------------------

_EMPTY = ".0_-*"


def parse(text):
    """Any reasonable 81-cell spelling → a grid. Raises ValueError otherwise.

    Tolerant on purpose: people paste whatever another solver printed —
    newlines, pipes, spaces, `0` or `.` for blanks. The ONE thing we refuse is
    an ambiguous length, because silently padding a 79-char string to 81 would
    shift every cell and produce a plausible, wrong puzzle.
    """
    kept = [ch for ch in (text or "") if ch.isdigit() or ch in _EMPTY]
    if len(kept) != 81:
        raise ValueError(f"il faut 81 cases, j'en ai lu {len(kept)}")
    return [0 if ch in _EMPTY else int(ch) for ch in kept]


def to_string(cells, empty="."):
    return "".join(empty if v == 0 else str(v) for v in cells)


def pretty(cells, cand=None):
    """A monospace dump for tests and the CLI. Candidates in braces when given."""
    out = []
    for r in range(9):
        row = []
        for c in range(9):
            i = r * 9 + c
            if cells[i]:
                row.append(f"[{cells[i]}]".ljust(11) if cand else str(cells[i]))
            else:
                row.append("".join(map(str, bits(cand[i]))).ljust(11)
                           if cand else ".")
        out.append(" ".join(row))
    return "\n".join(out)


# --- candidates ----------------------------------------------------------------

def candidates(cells):
    """The naive candidate grid: every digit not already taken by a peer.

    Filled cells get the mask of their own digit — not 0 — so that "does this
    cell hold digit d" and "can this cell hold digit d" are the same test
    everywhere downstream. Several classic engine bugs come from filled cells
    carrying an empty mask and quietly dropping out of a fish's base set.
    """
    cand = [0] * 81
    for i in range(81):
        if cells[i]:
            cand[i] = bit(cells[i])
            continue
        used = 0
        for j in PEERS[i]:
            if cells[j]:
                used |= bit(cells[j])
        cand[i] = ALL & ~used
    return cand


def is_valid(cells):
    """No unit repeats a placed digit. Says nothing about solvability."""
    for u in UNITS:
        seen = 0
        for i in u:
            v = cells[i]
            if v:
                if seen & bit(v):
                    return False
                seen |= bit(v)
    return True


def is_complete(cells):
    return all(cells) and is_valid(cells)


def positions(cand, cells, u, d):
    """Where digit d can still go in unit u — EMPTY cells only.

    ⚠ This excludes a cell already holding d. Fish, chains and every "exactly
    two places" test want the *undecided* places; counting a solved cell as a
    place turns a settled unit into a phantom conjugate pair.
    """
    b = bit(d)
    return [i for i in UNITS[u] if not cells[i] and cand[i] & b]
