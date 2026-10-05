"""The technique engine — the product.

Every detector returns the same shape, a **Step**, and that uniformity is what
lets one piece of code drive the hint ladder, the SVG diagram, the French
sentence, the learning journal and the claim verifier. Adding a technique means
adding a detector; nothing else in the app changes.

    {"technique": "w_wing", "tier": 3,
     "cells":   [i, ...],              # the pattern, to highlight
     "links":   [(i, j, d), ...],      # strong links, to draw
     "targets": [(i, d), ...],         # candidates eliminated
     "placements": [(i, d), ...],      # digits placed
     "unit": u | None,                 # the unit to point at on hint level 1
     "why_fr": "...",                  # generated FROM the structure, never canned
     "label_fr": "..."}                # the technique's display name

⚠ **`why_fr` is generated, never stored.** A hand-written sentence and the code
that found the pattern drift apart silently, and the user only finds out when
the sentence describes cells the highlight doesn't show. Build the phrase from
the same lists you put in `cells`/`targets` or don't build it at all.

⚠ **`next_step(safe=True)` checks its own answer against the brute-force
solution before handing it over.** That belt-and-braces exists because of the
bug this app was born from (2026-09-14): a *specialist* solver on the web
served a W-Wing whose elimination killed the grid. A detector bug must
surface as a loud internal alert, never as a confident wrong hint.
"""

from itertools import combinations

from .grid import (ALL, BOX_OF, COL_OF, COLS, PEERS, ROWS, ROW_OF, UNITS,
                   UNITS_OF, UNIT_KIND, bit, bits, candidates, common_peers,
                   count, name, single, unit_name_fr)

# The catalogue, by tier. Tier is the difficulty ladder the grader uses, and the
# order inside a tier is the order `next_step` tries — easiest first, always.
TIER_LABELS = {0: "placement", 1: "base", 2: "un seul chiffre",
               3: "plusieurs chiffres", 4: "chaînes"}

LABELS_FR = {
    "full_house": "Dernière case",
    "naked_single": "Single nu",
    "hidden_single": "Single caché",
    "pointing": "Candidats verrouillés (pointing)",
    "claiming": "Candidats verrouillés (claiming)",
    "naked_pair": "Paire nue", "naked_triple": "Triplet nu",
    "naked_quad": "Quadruplet nu",
    "hidden_pair": "Paire cachée", "hidden_triple": "Triplet caché",
    "hidden_quad": "Quadruplet caché",
    "x_wing": "X-Wing", "swordfish": "Swordfish", "jellyfish": "Jellyfish",
    "skyscraper": "Skyscraper", "two_string_kite": "2-String Kite",
    "simple_colouring": "Coloriage simple",
    "xy_wing": "XY-Wing", "xyz_wing": "XYZ-Wing", "w_wing": "W-Wing",
    "remote_pairs": "Paires distantes",
    "unique_rectangle_1": "Rectangle unique (type 1)",
    "bug_plus_one": "BUG+1",
}


def _n(i):
    return name(i)


def _list(cells):
    return ", ".join(_n(i) for i in cells)


def step(technique, tier, why_fr, cells=(), links=(), targets=(),
         placements=(), unit=None):
    return {"technique": technique, "tier": tier, "label_fr":
            LABELS_FR.get(technique, technique), "cells": list(cells),
            "links": [tuple(l) for l in links], "targets": sorted(set(targets)),
            "placements": sorted(set(placements)), "unit": unit,
            "why_fr": why_fr}


class Ctx:
    """Everything a detector needs, computed once per call instead of per rule."""

    def __init__(self, cells, cand=None):
        self.cells = cells
        self.cand = cand if cand is not None else candidates(cells)
        self._pos = {}

    def pos(self, u, d):
        """Empty cells of unit u that can still take d (memoized)."""
        key = (u, d)
        r = self._pos.get(key)
        if r is None:
            b = bit(d)
            r = tuple(i for i in UNITS[u] if not self.cells[i] and self.cand[i] & b)
            self._pos[key] = r
        return r

    def empties(self):
        return [i for i in range(81) if not self.cells[i]]

    def bivalue(self):
        return [i for i in range(81)
                if not self.cells[i] and count(self.cand[i]) == 2]

    def can(self, i, d):
        return not self.cells[i] and bool(self.cand[i] & bit(d))

    def elim(self, cells, d):
        """(cell, digit) pairs that would actually remove something."""
        return [(i, d) for i in cells if self.can(i, d)]

    def strong_links(self, d):
        """Every conjugate pair on d: a unit with exactly two places left.

        ⚠ Yields the SAME pair once per unit that proves it — a pair can be
        conjugate in both a row and a box. Callers that count links must
        deduplicate on the cell pair; callers that explain one should keep the
        unit, because *which* unit makes the link true is half the explanation.
        """
        for u in range(27):
            p = self.pos(u, d)
            if len(p) == 2:
                yield (p[0], p[1], u)


# --- tier 0 · placements -------------------------------------------------------

def find_full_house(ctx):
    for u in range(27):
        empty = [i for i in UNITS[u] if not ctx.cells[i]]
        if len(empty) == 1:
            i = empty[0]
            d = single(ctx.cand[i])
            if d:
                yield step("full_house", 0,
                           f"{unit_name_fr(u)} n'a plus qu'une case vide : "
                           f"{_n(i)} ne peut être que {d}.",
                           cells=[i], placements=[(i, d)], unit=u)


def find_naked_single(ctx):
    for i in ctx.empties():
        d = single(ctx.cand[i])
        if d:
            yield step("naked_single", 0,
                       f"{_n(i)} n'a plus qu'un candidat : {d}.",
                       cells=[i], placements=[(i, d)], unit=UNITS_OF[i][0])


def find_hidden_single(ctx):
    for u in range(27):
        for d in range(1, 10):
            p = ctx.pos(u, d)
            if len(p) == 1 and count(ctx.cand[p[0]]) > 1:
                yield step("hidden_single", 0,
                           f"Dans {unit_name_fr(u)}, le {d} n'a plus qu'une "
                           f"place : {_n(p[0])}.",
                           cells=[p[0]], placements=[(p[0], d)], unit=u)


# --- tier 1 · locked candidates + subsets --------------------------------------

def find_pointing(ctx):
    """A digit confined to one line inside a box leaves the rest of the line."""
    for b in range(9):
        u = 18 + b
        for d in range(1, 10):
            p = ctx.pos(u, d)
            if len(p) < 2:
                continue
            for axis, of, units in (("ligne", ROW_OF, ROWS), ("colonne", COL_OF, COLS)):
                k = of[p[0]]
                if all(of[i] == k for i in p):
                    outside = [i for i in units[k] if BOX_OF[i] != b]
                    t = ctx.elim(outside, d)
                    if t:
                        yield step("pointing", 1,
                                   f"Dans la boîte {b + 1}, le {d} ne tient que sur "
                                   f"la {axis} {k + 1} ({_list(p)}) : il quitte le "
                                   f"reste de la {axis}.",
                                   cells=list(p), targets=t, unit=u)


def find_claiming(ctx):
    """A digit confined to one box inside a line leaves the rest of the box."""
    for u in range(18):
        kind, n = UNIT_KIND[u]
        for d in range(1, 10):
            p = ctx.pos(u, d)
            if len(p) < 2:
                continue
            b = BOX_OF[p[0]]
            if all(BOX_OF[i] == b for i in p):
                outside = [i for i in UNITS[18 + b] if i not in p
                           and (ROW_OF[i] if kind == "row" else COL_OF[i]) != n]
                t = ctx.elim(outside, d)
                if t:
                    yield step("claiming", 1,
                               f"Dans {unit_name_fr(u)}, le {d} ne tient que dans "
                               f"la boîte {b + 1} ({_list(p)}) : il quitte le reste "
                               f"de la boîte.",
                               cells=list(p), targets=t, unit=u)


_SUBSET_NAMES = {2: "pair", 3: "triple", 4: "quad"}
_SUBSET_FR = {2: "Deux", 3: "Trois", 4: "Quatre"}


def find_naked_subset(ctx, size):
    for u in range(27):
        empty = [i for i in UNITS[u] if not ctx.cells[i]]
        cands = [i for i in empty if count(ctx.cand[i]) <= size]
        for combo in combinations(cands, size):
            m = 0
            for i in combo:
                m |= ctx.cand[i]
            if count(m) != size:
                continue
            others = [i for i in empty if i not in combo]
            t = [(i, d) for d in bits(m) for i in others if ctx.can(i, d)]
            if t:
                yield step(f"naked_{_SUBSET_NAMES[size]}", 1,
                           f"{_SUBSET_FR[size]} cases de {unit_name_fr(u)} "
                           f"({_list(combo)}) se partagent {{{','.join(map(str, bits(m)))}}} : "
                           f"ces chiffres quittent le reste de l'unité.",
                           cells=list(combo), targets=t, unit=u)


def find_hidden_subset(ctx, size):
    for u in range(27):
        live = [d for d in range(1, 10) if 1 < len(ctx.pos(u, d)) <= size]
        for combo in combinations(live, size):
            spots = set()
            for d in combo:
                spots |= set(ctx.pos(u, d))
            if len(spots) != size:
                continue
            keep = 0
            for d in combo:
                keep |= bit(d)
            t = [(i, d) for i in spots for d in bits(ctx.cand[i] & ~keep)
                 if ctx.can(i, d)]
            if t:
                yield step(f"hidden_{_SUBSET_NAMES[size]}", 1,
                           f"Dans {unit_name_fr(u)}, "
                           f"{{{','.join(map(str, combo))}}} n'ont que "
                           f"{size} places ({_list(sorted(spots))}) : ces cases ne "
                           f"peuvent rien contenir d'autre.",
                           cells=sorted(spots), targets=t, unit=u)


# --- tier 2 · single-digit patterns --------------------------------------------

_FISH_NAMES = {2: "x_wing", 3: "swordfish", 4: "jellyfish"}


def find_fish(ctx, size):
    """Basic fish: `size` base lines whose places for d span exactly `size`
    cross-lines. The cross-lines are then spoken for, and d leaves them
    everywhere else."""
    for base_rows in (True, False):
        base_units = range(0, 9) if base_rows else range(9, 18)
        cross_of = COL_OF if base_rows else ROW_OF
        cross_units = COLS if base_rows else ROWS
        for d in range(1, 10):
            live = [(u, ctx.pos(u, d)) for u in base_units
                    if 1 < len(ctx.pos(u, d)) <= size]
            for combo in combinations(live, size):
                lines = set()
                for _, p in combo:
                    lines |= {cross_of[i] for i in p}
                if len(lines) != size:
                    continue
                base_cells = [i for _, p in combo for i in p]
                outside = [i for k in lines for i in cross_units[k]
                           if i not in base_cells]
                t = ctx.elim(outside, d)
                if t:
                    axis = "lignes" if base_rows else "colonnes"
                    cross = "colonnes" if base_rows else "lignes"
                    yield step(_FISH_NAMES[size], 2,
                               f"Le {d} des {axis} "
                               f"{', '.join(str(UNIT_KIND[u][1] + 1) for u, _ in combo)} "
                               f"ne tient que sur les {cross} "
                               f"{', '.join(str(k + 1) for k in sorted(lines))} : "
                               f"il quitte ces {cross} ailleurs.",
                               cells=base_cells, targets=t,
                               unit=combo[0][0])


def find_skyscraper(ctx):
    """Two lines with two places each, sharing one cross-line: the two free ends
    cannot both be false, so whatever sees both loses d."""
    for rows in (True, False):
        base = range(0, 9) if rows else range(9, 18)
        cross_of = COL_OF if rows else ROW_OF
        for d in range(1, 10):
            live = [(u, ctx.pos(u, d)) for u in base if len(ctx.pos(u, d)) == 2]
            for (u1, p1), (u2, p2) in combinations(live, 2):
                shared = {cross_of[i] for i in p1} & {cross_of[i] for i in p2}
                if len(shared) != 1:
                    continue
                k = shared.pop()
                a = [i for i in p1 if cross_of[i] != k][0]
                b = [i for i in p2 if cross_of[i] != k][0]
                if cross_of[a] == cross_of[b]:
                    continue
                t = ctx.elim(common_peers([a, b]), d)
                if t:
                    yield step("skyscraper", 2,
                               f"Le {d} de {unit_name_fr(u1)} et de "
                               f"{unit_name_fr(u2)} se rejoint sur une seule "
                               f"{'colonne' if rows else 'ligne'} : l'un des deux bouts "
                               f"{_n(a)}/{_n(b)} est un {d}.",
                               cells=list(p1) + list(p2),
                               links=[(p1[0], p1[1], d), (p2[0], p2[1], d)],
                               targets=t, unit=u1)


def find_two_string_kite(ctx):
    """A row-pair and a column-pair that touch inside one box — same conclusion
    as the skyscraper, different geometry."""
    for d in range(1, 10):
        rows = [(u, ctx.pos(u, d)) for u in range(0, 9) if len(ctx.pos(u, d)) == 2]
        cols = [(u, ctx.pos(u, d)) for u in range(9, 18) if len(ctx.pos(u, d)) == 2]
        for ur, pr in rows:
            for uc, pc in cols:
                if set(pr) & set(pc):
                    continue
                hinge = [(i, j) for i in pr for j in pc if BOX_OF[i] == BOX_OF[j]]
                if len(hinge) != 1:
                    continue
                hi, hj = hinge[0]
                a = [i for i in pr if i != hi][0]
                b = [j for j in pc if j != hj][0]
                if BOX_OF[a] == BOX_OF[b]:
                    continue
                t = ctx.elim(common_peers([a, b]), d)
                if t:
                    yield step("two_string_kite", 2,
                               f"Le {d} tient sur deux places dans "
                               f"{unit_name_fr(ur)} et deux dans {unit_name_fr(uc)}, "
                               f"qui se touchent dans la boîte {BOX_OF[hi] + 1} : "
                               f"{_n(a)} ou {_n(b)} est un {d}.",
                               cells=list(pr) + list(pc),
                               links=[(pr[0], pr[1], d), (pc[0], pc[1], d)],
                               targets=t, unit=ur)


def find_simple_colouring(ctx):
    """Two-colour the conjugate-pair graph of one digit, then look for the two
    contradictions it can produce."""
    for d in range(1, 10):
        adj = {}
        for i, j, _u in ctx.strong_links(d):
            adj.setdefault(i, set()).add(j)
            adj.setdefault(j, set()).add(i)
        seen = set()
        for start in adj:
            if start in seen:
                continue
            colour = {start: 0}
            queue = [start]
            seen.add(start)
            while queue:
                i = queue.pop()
                for j in adj[i]:
                    if j not in colour:
                        colour[j] = 1 - colour[i]
                        seen.add(j)
                        queue.append(j)
            if len(colour) < 4:
                continue
            groups = ([i for i, c in colour.items() if c == 0],
                      [i for i, c in colour.items() if c == 1])
            # rule A — two cells of one colour in the same unit ⇒ that colour is false
            for c, grp in enumerate(groups):
                clash = next(((x, y) for x, y in combinations(grp, 2)
                              if y in PEERS[x]), None)
                if clash:
                    t = ctx.elim(grp, d)
                    if t:
                        yield step("simple_colouring", 2,
                                   f"Sur le {d}, la chaîne colorie {_n(clash[0])} et "
                                   f"{_n(clash[1])} de la même couleur alors qu'elles "
                                   f"se voient : toute cette couleur est fausse.",
                                   cells=sorted(colour),
                                   links=[(i, j, d) for i, j, _ in ctx.strong_links(d)
                                          if i in colour and j in colour],
                                   targets=t)
                        break
            else:
                # rule B — an outside cell seeing both colours cannot hold d
                out = [i for i in ctx.empties() if i not in colour and ctx.can(i, d)
                       and any(j in PEERS[i] for j in groups[0])
                       and any(j in PEERS[i] for j in groups[1])]
                if out:
                    verb = "voit" if len(out) == 1 else "voient"
                    yield step("simple_colouring", 2,
                               f"Sur le {d}, {_list(out)} {verb} les deux couleurs "
                               f"de la chaîne : l'une des deux est vraie, donc le {d} "
                               f"part de là.",
                               cells=sorted(colour),
                               links=[(i, j, d) for i, j, _ in ctx.strong_links(d)
                                      if i in colour and j in colour],
                               targets=[(i, d) for i in out])


# --- tier 3 · multi-digit patterns ---------------------------------------------

def find_xy_wing(ctx):
    """Pivot {a,b} with pincers {a,c} and {b,c}: whichever way the pivot falls,
    one pincer is c."""
    biv = ctx.bivalue()
    for pivot in biv:
        a, b = bits(ctx.cand[pivot])
        wings = [i for i in biv if i in PEERS[pivot]]
        for p1, p2 in combinations(wings, 2):
            s1, s2 = set(bits(ctx.cand[p1])), set(bits(ctx.cand[p2]))
            if a not in s1 or b not in s2:
                s1, s2, p1, p2 = s2, s1, p2, p1
            if a not in s1 or b not in s2:
                continue
            c = (s1 - {a}).pop()
            if c != (s2 - {b}).pop() or c in (a, b):
                continue
            t = ctx.elim(common_peers([p1, p2]), c)
            if t:
                yield step("xy_wing", 3,
                           f"Pivot {_n(pivot)} {{{a},{b}}}, pinces {_n(p1)} "
                           f"{{{a},{c}}} et {_n(p2)} {{{b},{c}}} : quelle que soit "
                           f"la valeur du pivot, une pince vaut {c}.",
                           cells=[pivot, p1, p2], targets=t)


def find_xyz_wing(ctx):
    """Same idea with a three-candidate pivot — the pivot itself may be c, so
    the victims must also see the pivot."""
    for pivot in ctx.empties():
        if count(ctx.cand[pivot]) != 3:
            continue
        pv = set(bits(ctx.cand[pivot]))
        wings = [i for i in PEERS[pivot] if not ctx.cells[i]
                 and count(ctx.cand[i]) == 2
                 and set(bits(ctx.cand[i])) <= pv]
        for p1, p2 in combinations(wings, 2):
            s1, s2 = set(bits(ctx.cand[p1])), set(bits(ctx.cand[p2]))
            shared = s1 & s2
            if len(shared) != 1 or s1 | s2 != pv:
                continue
            c = shared.pop()
            t = ctx.elim(common_peers([pivot, p1, p2]), c)
            if t:
                yield step("xyz_wing", 3,
                           f"Pivot {_n(pivot)} {{{','.join(map(str, sorted(pv)))}}} "
                           f"et ses deux pinces {_n(p1)}/{_n(p2)} : le {c} est "
                           f"forcé dans l'une des trois.",
                           cells=[pivot, p1, p2], targets=t)


def find_w_wing(ctx):
    """Two identical bivalue cells {a,b} that don't see each other, joined by a
    strong link on ONE of the two digits.

    ⚠ The strong link sits on the digit you KEEP, and you eliminate the OTHER —
    the link chases both ends off its own digit. Link on `a` ⇒ at least one end
    is `b` ⇒ `b` leaves every cell that sees both ends.

    ⚠ The two link cells must be **outside** the wing and outside the victims.
    A "link" that runs through the very cell you are eliminating from proves
    nothing — that is the exact shape of the false hint this app exists for
    (2026-09-14). `diagnose_w_wing` names that failure explicitly.
    """
    biv = ctx.bivalue()
    by_pair = {}
    for i in biv:
        by_pair.setdefault(ctx.cand[i], []).append(i)
    for mask, group in by_pair.items():
        a, b = bits(mask)
        for x, y in combinations(group, 2):
            if y in PEERS[x]:
                continue
            victims = [i for i in common_peers([x, y]) if not ctx.cells[i]]
            if not victims:
                continue
            for keep, drop in ((a, b), (b, a)):
                t = ctx.elim(victims, drop)
                if not t:
                    continue
                for p, q, u in ctx.strong_links(keep):
                    for pp, qq in ((p, q), (q, p)):
                        # ⚠ There are deliberately NO guards here beyond the two
                        # membership tests, and that took some proving. Two
                        # plausible-looking ones were written, survived every
                        # mutation, and were deleted (2026-09-14):
                        #   • "pp/qq must not be x or y" — unreachable. `pp in
                        #     PEERS[x]` already forbids pp == x, and the wings
                        #     were required not to see each other, so pp != y.
                        #   • "the link must not pass through a victim" — sound
                        #     but costly. The W-Wing argument never mentions the
                        #     link cells' relation to the victims: one of P, Q is
                        #     `keep`, so one of x, y is `drop`, so anything seeing
                        #     both loses `drop`. Measured over 20 puzzles the
                        #     guard suppressed 27 findings and prevented 0 unsound
                        #     ones.
                        # Dead code in a safety position reads as protection and
                        # gives none. `TestWWingIsSound` is the real guard.
                        if pp in PEERS[x] and qq in PEERS[y]:
                            yield step("w_wing", 3,
                                       f"{_n(x)} et {_n(y)} valent toutes deux "
                                       f"{{{a},{b}}} et ne se voient pas. Le lien fort "
                                       f"sur {keep} ({_n(p)}–{_n(q)} dans "
                                       f"{unit_name_fr(u)}) chasse le {keep} de l'une "
                                       f"des deux : au moins une vaut {drop}.",
                                       cells=[x, y, pp, qq],
                                       links=[(p, q, keep)], targets=t, unit=u)


def find_remote_pairs(ctx):
    """A chain of identical bivalue cells alternates; two cells an odd number of
    steps apart are opposites, so nothing seeing both can hold either digit."""
    biv = ctx.bivalue()
    by_pair = {}
    for i in biv:
        by_pair.setdefault(ctx.cand[i], []).append(i)
    for mask, group in by_pair.items():
        if len(group) < 4:
            continue
        a, b = bits(mask)
        adj = {i: [j for j in group if j != i and j in PEERS[i]] for i in group}
        for start in group:
            dist = {start: 0}
            queue = [start]
            while queue:
                i = queue.pop(0)
                for j in adj[i]:
                    if j not in dist:
                        dist[j] = dist[i] + 1
                        queue.append(j)
            for end, dd in dist.items():
                if dd >= 3 and dd % 2 == 1:
                    victims = [i for i in common_peers([start, end])
                               if not ctx.cells[i]]
                    t = ctx.elim(victims, a) + ctx.elim(victims, b)
                    if t:
                        chain = sorted(i for i in dist if dist[i] <= dd)
                        yield step("remote_pairs", 3,
                                   f"Une chaîne de {{{a},{b}}} relie {_n(start)} à "
                                   f"{_n(end)} en {dd} pas : elles sont forcément "
                                   f"opposées, donc ni {a} ni {b} ne survit à côté "
                                   f"des deux.",
                                   cells=chain, targets=t)
                        return


def find_unique_rectangle_1(ctx):
    """Three corners exactly {a,b} + a fourth with extras, over two boxes: the
    fourth MUST take an extra, or the puzzle would have two solutions.

    ⚠ Only sound on a grid known to have a unique solution. `next_step` refuses
    this tier when the grid is ambiguous — an imported puzzle can be anything.
    """
    biv = ctx.bivalue()
    by_pair = {}
    for i in biv:
        by_pair.setdefault(ctx.cand[i], []).append(i)
    for mask, group in by_pair.items():
        a, b = bits(mask)
        for c1, c2 in combinations(group, 2):
            if ROW_OF[c1] != ROW_OF[c2]:
                continue
            for c3 in group:
                if COL_OF[c3] not in (COL_OF[c1], COL_OF[c2]) or ROW_OF[c3] == ROW_OF[c1]:
                    continue
                other_col = COL_OF[c2] if COL_OF[c3] == COL_OF[c1] else COL_OF[c1]
                c4 = ROW_OF[c3] * 9 + other_col
                if ctx.cells[c4] or ctx.cand[c4] & mask != mask:
                    continue
                if count(ctx.cand[c4]) <= 2:
                    continue
                if len({BOX_OF[c1], BOX_OF[c2], BOX_OF[c3], BOX_OF[c4]}) != 2:
                    continue
                t = ctx.elim([c4], a) + ctx.elim([c4], b)
                if t:
                    yield step("unique_rectangle_1", 3,
                               f"{_n(c1)}, {_n(c2)}, {_n(c3)} valent toutes "
                               f"{{{a},{b}}} sur deux boîtes. Si {_n(c4)} valait "
                               f"{a} ou {b}, la grille aurait deux solutions — "
                               f"elle n'en a qu'une.",
                               cells=[c1, c2, c3, c4], targets=t)


def find_bug_plus_one(ctx):
    """Every unsolved cell bivalue but one: that one takes the digit that would
    otherwise appear three times in its units."""
    empty = ctx.empties()
    odd = [i for i in empty if count(ctx.cand[i]) != 2]
    if len(odd) != 1 or count(ctx.cand[odd[0]]) != 3:
        return
    i = odd[0]
    for d in bits(ctx.cand[i]):
        if all(len(ctx.pos(u, d)) == 3 for u in UNITS_OF[i]):
            yield step("bug_plus_one", 3,
                       f"Toutes les cases libres sont à deux candidats sauf "
                       f"{_n(i)}. Sans le {d} là, la grille aurait deux solutions.",
                       cells=[i], placements=[(i, d)])
            return


# --- the catalogue, in the order `next_step` tries it --------------------------

CATALOGUE = [
    (0, find_full_house), (0, find_naked_single), (0, find_hidden_single),
    (1, find_pointing), (1, find_claiming),
    (1, lambda c: find_naked_subset(c, 2)), (1, lambda c: find_hidden_subset(c, 2)),
    (1, lambda c: find_naked_subset(c, 3)), (1, lambda c: find_hidden_subset(c, 3)),
    (1, lambda c: find_naked_subset(c, 4)), (1, lambda c: find_hidden_subset(c, 4)),
    (2, lambda c: find_fish(c, 2)), (2, find_skyscraper), (2, find_two_string_kite),
    (2, lambda c: find_fish(c, 3)), (2, find_simple_colouring),
    (2, lambda c: find_fish(c, 4)),
    (3, find_xy_wing), (3, find_xyz_wing), (3, find_w_wing),
    (3, find_remote_pairs), (3, find_unique_rectangle_1), (3, find_bug_plus_one),
]

#: techniques whose logic assumes the puzzle has exactly one solution
UNIQUENESS_DEPENDENT = {"unique_rectangle_1", "bug_plus_one"}

#: Difficulty, on the Sudoku Explainer scale (1.0 → ~12), which is the one rating
#: the hobby actually shares. Table: SukakuExplainer wiki, "Difficulty ratings in
#: Sudoku Explainer v1.2.1".
#:
#: ⚠ **This is NOT `tier`.** `tier` is the FAMILY of a technique — it labels the
#: fiches and orders the hint ladder, and it groups by *what you look at* (one
#: digit, several digits). Difficulty is a different axis, and until 2026-09-30
#: the grader used `tier` for both. It gave a scale that was not ordered: a
#: skyscraper (tier 2) is a chain and rates 6.6, an XY-wing (tier 3) rates 4.2,
#: so « Difficile » and « Diabolique » were the same band — measured on our own
#: pool, 9 of 12 « Difficile » grids were really the harder one.
#:
#: Our own single-digit chains have no SE entry of their own: SE reaches those
#: eliminations through X-Chains / Y-Cycles, 6.5–6.9. They get 6.6.
RATING = {
    "full_house": 1.0, "hidden_single": 1.2, "naked_single": 2.3,
    "pointing": 2.6, "claiming": 2.8,
    "naked_pair": 3.0, "x_wing": 3.2, "hidden_pair": 3.4,
    "naked_triple": 3.6, "swordfish": 3.8, "hidden_triple": 4.0,
    "xy_wing": 4.2, "xyz_wing": 4.4, "unique_rectangle_1": 4.5,
    "naked_quad": 5.0, "jellyfish": 5.2, "hidden_quad": 5.4,
    "bug_plus_one": 5.6,
    "skyscraper": 6.6, "two_string_kite": 6.6, "simple_colouring": 6.6,
    "w_wing": 6.6, "remote_pairs": 6.6,
}
