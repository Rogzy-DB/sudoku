"""Orchestration — pick the next step, solve a path, grade a puzzle, and judge
somebody else's claim.

The three public entry points:

* `next_step(cells, elims)`  — the easiest available step, **checked against the
  brute-force solution before it is returned**. This is what the hint ladder
  serves.
* `solve_path(cells)`        — the whole chain of steps, in the order the hint
  ladder teaches them (by family). NOT the grade: see `grade`.
* `verify_claim(cells, text)`— tier 5: is a hint from elsewhere true, mislabelled,
  degenerate, or plain false?

⚠ **Eliminations are state.** A step that only removes candidates changes
nothing in `cells`, so an engine that recomputes candidates from `cells` alone
hands out the same hint forever. The caller therefore carries `elims` — the set
of (cell, digit) eliminations already *proven* — and the engine subtracts them.
The player's own pencil crossings are deliberately NOT in that set: they are
their working, they may be wrong, and the engine must never reason on them
(`audit_pencil` grades them instead).
"""

import re

from . import techniques as T
from .grid import (ALL, PEERS, UNITS, bit, bits, candidates, common_peers,
                   count, name, parse_cell, single, unit_name_fr)
from .solver import solution, solve_count

MAX_TIER = 3

GRADE_LABELS = {0: "Facile", 1: "Moyen", 2: "Difficile", 3: "Diabolique",
                4: "Extrême"}


def _cand_with(cells, elims):
    cand = candidates(cells)
    for i, d in elims or ():
        if not cells[i]:
            cand[i] &= ~bit(d)
    return cand


def _apply(cells, cand, st):
    """Fold a step into (cells, cand) in place. Returns True if anything moved."""
    moved = False
    for i, d in st["placements"]:
        if not cells[i]:
            cells[i] = d
            cand[i] = bit(d)
            for j in PEERS[i]:
                if not cells[j]:
                    cand[j] &= ~bit(d)
            moved = True
    for i, d in st["targets"]:
        if not cells[i] and cand[i] & bit(d):
            cand[i] &= ~bit(d)
            moved = True
    return moved


def _contradicts(st, sol):
    """Would this step remove a TRUE candidate or place a wrong digit?"""
    if sol is None:
        return False
    for i, d in st["targets"]:
        if sol[i] == d:
            return True
    for i, d in st["placements"]:
        if sol[i] != d:
            return True
    return False


def all_steps(cells, elims=(), max_tier=MAX_TIER, unique=None):
    """Every step the catalogue can see from this position, easiest tier first."""
    ctx = T.Ctx(cells, _cand_with(cells, elims))
    if unique is None:
        unique = solve_count(cells, 2) == 1
    for tier, finder in T.CATALOGUE:
        if tier > max_tier:
            continue
        for st in finder(ctx):
            if st["technique"] in T.UNIQUENESS_DEPENDENT and not unique:
                continue          # a uniqueness argument on an ambiguous grid is a lie
            yield st


def next_step(cells, elims=(), max_tier=MAX_TIER, safe=True):
    """The easiest step available, or None.

    `safe=True` re-checks the answer against the brute-force solution. A step
    that would break the grid is dropped and reported through `ALERTS` rather
    than shown — a detector bug must never reach the player as a confident hint.
    """
    sol = solution(cells) if safe else None
    for st in all_steps(cells, elims, max_tier, unique=sol is not None):
        if safe and _contradicts(st, sol):
            ALERTS.append((T.LABELS_FR.get(st["technique"]), st))
            continue
        return st
    return None


#: detector bugs caught by the safety net. Empty in a healthy build; a test
#: asserts it stays empty across the whole generated corpus.
ALERTS = []


def solve_path(cells, max_tier=MAX_TIER, limit=400):
    """Solve by technique. Returns (steps, solved, final_cells)."""
    cells = list(cells)
    cand = candidates(cells)
    unique = solve_count(cells, 2) == 1
    steps = []
    for _ in range(limit):
        ctx = T.Ctx(cells, cand)
        found = None
        for tier, finder in T.CATALOGUE:
            if tier > max_tier:
                continue
            for st in finder(ctx):
                if st["technique"] in T.UNIQUENESS_DEPENDENT and not unique:
                    continue
                found = st
                break
            if found:
                break
        if not found or not _apply(cells, cand, found):
            break
        steps.append(found)
        if all(cells):
            return steps, True, cells
    return steps, all(cells), cells


#: The four labels, as cuts on `T.RATING`. `(ceiling, grade)`, ordered; anything
#: above the last ceiling is grade 3.
#:
#: Past the whole catalogue a grid is « Extrême », which is the honest answer
#: and not a shrug.
#:
#: ⚠ The gap that matters is 5.6 → 6.5: below it you look at a pattern, above it
#: you follow a chain. That is the only boundary a player actually feels.
BANDS = ((2.3, 0), (3.4, 1), (5.6, 2))


def rated_path(cells, max_tier=MAX_TIER, limit=400):
    """Solve preferring the CHEAPEST technique available at each step.

    This is the path `grade` measures, and it is deliberately NOT `solve_path`.
    `solve_path` walks the catalogue by family, which teaches well but grades
    badly: it will spend a chain (6.6) on a position where a wing (4.2) was
    sitting right there, and the puzzle then scores harder than it plays. SE
    rates the cheapest path for exactly this reason, so we do too.
    """
    cells = list(cells)
    cand = candidates(cells)
    unique = solve_count(cells, 2) == 1
    steps = []
    for _ in range(limit):
        ctx = T.Ctx(cells, cand)
        best = None
        for tier, finder in T.CATALOGUE:
            if tier > max_tier:
                continue
            for st in finder(ctx):
                if st["technique"] in T.UNIQUENESS_DEPENDENT and not unique:
                    continue
                r = T.RATING[st["technique"]]
                if best is None or r < best[0]:
                    best = (r, st)
                break                    # cheapest of THIS finder is its first
        if not best or not _apply(cells, cand, best[1]):
            break
        steps.append(best[1])
        if all(cells):
            return steps, True, cells
    return steps, all(cells), cells


def grade(cells, max_tier=MAX_TIER):
    """(grade_int, label, techniques_used). `grade_int` is None if the
    catalogue cannot finish the puzzle — an honest "harder than what I know",
    never a shrug dressed up as a difficulty."""
    steps, solved, _ = rated_path(cells, max_tier)
    used = sorted({s["technique"] for s in steps})
    if not solved:
        return None, "Extrême", used
    hardest = max((T.RATING[s["technique"]] for s in steps), default=0.0)
    g = next((b for ceiling, b in BANDS if hardest <= ceiling), 3)
    return g, GRADE_LABELS[g], used


# --- tier 5 · judging a claim from elsewhere -----------------------------------

_ALIASES = {
    "w-wing": "w_wing", "wwing": "w_wing", "w wing": "w_wing",
    "xy-wing": "xy_wing", "xywing": "xy_wing", "y-wing": "xy_wing",
    "xyz-wing": "xyz_wing", "x-wing": "x_wing", "xwing": "x_wing",
    "swordfish": "swordfish", "jellyfish": "jellyfish",
    "skyscraper": "skyscraper", "kite": "two_string_kite",
    "paire nue": "naked_pair", "naked pair": "naked_pair",
    "paire cachée": "hidden_pair", "hidden pair": "hidden_pair",
    "pointing": "pointing", "claiming": "claiming",
    "remote pair": "remote_pairs", "paires distantes": "remote_pairs",
    "unique rectangle": "unique_rectangle_1", "rectangle unique": "unique_rectangle_1",
    "coloriage": "simple_colouring", "colouring": "simple_colouring",
    "coloring": "simple_colouring", "bug": "bug_plus_one",
}

_DROP_RE = re.compile(
    r"(?:retire[rz]?|retrait|enlev\w*|élimin\w*|elimin\w*|remove[sd]?|ôte[rz]?)"
    r"[^0-9]{0,20}(\d)", re.I)


#: "R4C5" — the spelling every solver prints
_RC_RE = re.compile(r"[Rr](\d)\s*[Cc](\d)")
#: "45" — the spelling players actually type. A bare two-digit token is only read
#: as a cell when the text contains NO R#C# anywhere, so a claim written properly
#: can never have its digits misread as coordinates. The verdict always announces
#: which cells it settled on, so a misread is visible in one line rather than
#: hidden inside a wrong answer.
_COMPACT_RE = re.compile(r"(?<!\d)([1-9])\s*[,.]?\s*([1-9])(?!\d)")


def _cells_in(fragment, compact=False):
    out = []
    rx = _COMPACT_RE if compact else _RC_RE
    for m in rx.finditer(fragment or ""):
        i = (int(m.group(1)) - 1) * 9 + (int(m.group(2)) - 1)
        if i not in out:
            out.append(i)
    return out


def parse_claim(text):
    """Free text from another solver → the bits we can check.

    The three groups of cells a hint mentions do different jobs and must not be
    mixed: the PATTERN cells, the cells of the STRONG LINK, and the cells the
    elimination TARGETS. Reading them as one flat list is how a verifier ends up
    computing "cases qui voient les quatre" and reporting a hollow ⚪ instead of
    checking the real claim. Each clause is scoped to the text that follows its
    own keyword.

    Deliberately forgiving on spelling, deliberately explicit about what it
    could not read: a verifier that silently guesses is the same failure mode as
    the solver that served the bad hint in the first place.
    """
    text = text or ""
    low = text.lower()
    technique, guessed = None, False
    for k, v in _ALIASES.items():
        if k in low:
            technique = v
            break
    if technique is None and re.search(r"\bw\b", low):
        # He types "w 45 - 46" for a W-Wing. A lone "w" in a sudoku hint is
        # essentially never anything else — and the verdict announces the
        # reading, so a wrong guess costs one visible line, not a wrong answer.
        technique, guessed = "w_wing", True

    m = _DROP_RE.search(text)
    drop = int(m.group(1)) if m else None
    # ⚠ Cut the drop clause BEFORE scanning for cells, or the eliminated digit
    # ("retirer 6 du 63") becomes the first digit of a compact coordinate.
    after_drop = text[m.end():m.end() + 60] if m else ""
    compact = not _RC_RE.search(text)
    if compact:
        # ⚠ A candidate set written "{3,6}" is not the cell R3C6. Blank the
        # braces before scanning, or the verifier silently invents a cell out of
        # the pair the hint was about.
        text = re.sub(r"\{[^}]*\}", " ", text)
        after_drop = re.sub(r"\{[^}]*\}", " ", after_drop)
    targets = _cells_in(after_drop, compact)

    link_cells, link_digit = [], None
    ml = re.search(r"(?:lien fort|strong link|conjugate|lien)", text, re.I)
    if ml:
        tail = text[ml.end():ml.end() + 70]
        link_cells = _cells_in(tail, compact)
        md = re.search(r"\bsur\s+(\d)|\bon\s+(\d)", tail, re.I)
        if md:
            link_digit = int(md.group(1) or md.group(2))

    head = text[:m.start()] if m else text
    all_cells = _cells_in(head, compact) + [i for i in targets + link_cells]
    all_cells = list(dict.fromkeys(all_cells))
    pattern = [i for i in all_cells if i not in link_cells and i not in targets]
    return {"cells": all_cells, "pattern": pattern, "link_cells": link_cells,
            "targets": targets, "technique": technique, "guessed": guessed,
            "drop": drop,
            "link_digit": link_digit, "notation": "compact" if compact else "rc",
            "text": text}


def _forced_equal(ctx, x, y):
    """Are these two cells provably the SAME digit, via a shared neighbour?

    Looks for a cell z with the same pair such that some unit holds only x and z
    as places for BOTH digits (so x ≠ z), and likewise for z and y. Then x = y —
    and a wing that needs "at least one of x, y is the other digit" is dead on
    arrival. This is exactly the shape of the false hint of 2026-09-14: column 3
    had two empty cells, row 5 had two, and R5C3 sat between them.
    """
    mask = ctx.cand[x]
    if ctx.cand[y] != mask:
        return None
    a, b = bits(mask)

    def locked(i, j):
        for u in range(27):
            if i in UNITS[u] and j in UNITS[u]:
                if (set(ctx.pos(u, a)) == {i, j}) and (set(ctx.pos(u, b)) == {i, j}):
                    return u
        return None

    for z in ctx.bivalue():
        if z in (x, y) or ctx.cand[z] != mask:
            continue
        u1, u2 = locked(x, z), locked(z, y)
        if u1 is not None and u2 is not None:
            return (z, u1, u2)
    return None


def diagnose_w_wing(ctx, x, y, keep=None):
    """Why a claimed W-Wing does or does not exist. Returns (ok, notes)."""
    notes = []
    if ctx.cand[x] != ctx.cand[y] or count(ctx.cand[x]) != 2:
        notes.append(f"{name(x)} et {name(y)} n'ont pas la même paire de candidats.")
        return False, notes
    if y in PEERS[x]:
        notes.append(f"{name(x)} et {name(y)} se voient — les deux ailes d'un "
                     f"W-Wing doivent être indépendantes.")
        return False, notes
    fe = _forced_equal(ctx, x, y)
    if fe:
        z, u1, u2 = fe
        notes.append(
            f"🌀 {name(x)} et {name(y)} sont **forcées égales** : {name(z)} est "
            f"seule avec {name(x)} dans {unit_name_fr(u1)} et seule avec "
            f"{name(y)} dans {unit_name_fr(u2)}. Un W-Wing conclut « au moins "
            f"une des deux vaut l'autre chiffre » — ici elles valent la même "
            f"chose. Le motif ne peut pas exister.")
    victims = [i for i in common_peers([x, y]) if not ctx.cells[i]]
    digits = bits(ctx.cand[x]) if keep is None else [keep]
    usable, any_blocked = False, []
    for k in digits:
        blocked = []
        for p, q, u in ctx.strong_links(k):
            for pp, qq in ((p, q), (q, p)):
                if pp in PEERS[x] and qq in PEERS[y]:
                    if pp in (x, y) or qq in (x, y) or pp in victims or qq in victims:
                        blocked.append((pp, qq, u))
                    else:
                        usable = True
        any_blocked += blocked
        if blocked and not usable:
            pp, qq, u = blocked[0]
            through = [name(i) for i in (pp, qq) if i in victims or i in (x, y)]
            notes.append(
                f"Le seul lien fort sur {k} qui relie les deux ailes passe par "
                f"{', '.join(through)} — c'est-à-dire par la case même qu'on "
                f"prétend éliminer. Un lien qui traverse sa propre cible ne "
                f"prouve rien.")
    if not usable and not any_blocked:
        notes.append(f"Aucun lien fort ne relie {name(x)} à {name(y)} sur "
                     f"{' ni '.join(map(str, digits))}.")
    return usable, notes


def blocked_any(ctx, x, y, digits):
    for k in digits:
        for p, q, _u in ctx.strong_links(k):
            for pp, qq in ((p, q), (q, p)):
                if pp in PEERS[x] and qq in PEERS[y]:
                    return True
    return False


def verify_claim(cells, text, elims=()):
    """Judge a hint from another solver. Four verdicts, plus an honest fifth.

    ✅ valid · ⚠️ mislabelled · 🌀 degenerate · ❌ false · ❓ unreadable/unprovable
    """
    claim = parse_claim(text)
    ctx = T.Ctx(cells, _cand_with(cells, elims))
    sol = solution(cells)
    out = {"claim": claim, "verdict": "unknown", "notes": [], "step": None,
           "title": "Je ne sais pas trancher"}

    if sol is None:
        out["notes"].append("⚠ Cette grille n'a pas une solution unique : je ne "
                            "peux rien prouver dessus.")
        return out
    if not claim["cells"]:
        out["notes"].append("Je n'ai trouvé aucune case (format attendu : R2C3).")
        return out

    drop = claim["drop"]
    if drop is None:
        out["notes"].append("Je n'ai pas lu quel chiffre tu élimines "
                            "(« retirez 6 de… »).")
        return out

    # Which cells does the elimination land on? Three readings, most explicit
    # first — and we SAY which one we used, so a misread is visible rather than
    # silently producing a hollow verdict.
    named = claim["pattern"] or claim["cells"]

    # ⚠ If he NAMED a target and it cannot take the elimination, say so. Quietly
    # falling back to "well, what about the common peers then" is the exact
    # failure this tool exists to catch: a guess presented as an answer.
    for i in claim["targets"]:
        if ctx.cells[i]:
            out["notes"].append(
                f"⛔ {name(i)} est déjà remplie ({ctx.cells[i]}) — il n'y a rien "
                f"à y retirer. Vérifie la case que tu vises.")
        elif not ctx.can(i, drop):
            out["notes"].append(
                f"⛔ {name(i)} n'a plus le {drop} en candidat (il lui reste "
                f"{{{','.join(str(d) for d in bits(ctx.cand[i]))}}}) — "
                f"l'élimination ne porte sur rien.")
    if claim["targets"] and not any(ctx.can(i, drop) for i in claim["targets"]):
        out["verdict"] = "empty"
        out["title"] = "⚪ Sans effet"

    readings = []
    if claim["targets"]:
        readings.append(("les cases que tu nommes", list(claim["targets"])))
    if len(named) >= 2:
        readings.append((f"ce qui voit {name(named[0])} et {name(named[1])}",
                         common_peers(named[:2])))
    if len(named) > 2:
        readings.append(("ce qui voit toutes les cases citées",
                         common_peers(named)))
    targets, reading = [], None
    if out["verdict"] == "empty":
        readings = readings[:1]      # he named it; do not silently re-aim
    for label, cand_cells in readings:
        t = [i for i in cand_cells if ctx.can(i, drop)]
        if t:
            targets, reading = t, label
            break
    if reading:
        how = (" — je lis les paires de chiffres comme ligne-colonne"
               if claim["notation"] == "compact" else "")
        out["notes"].append(
            f"Lecture : motif = {', '.join(name(i) for i in named) or '?'} · "
            f"cible du retrait = {', '.join(name(i) for i in targets)} "
            f"({reading}){how}.")

    # 1 — the fact check, before anything else
    liars = [i for i in targets if sol[i] == drop]
    if liars:
        out["verdict"] = "false"
        out["title"] = "❌ Faux"
        out["notes"].append(
            f"L'élimination casse la grille : {name(liars[0])} vaut bel et bien "
            f"{drop} dans la solution unique. Si tu l'appliques, la grille "
            f"devient insoluble.")
    elif not targets:
        out["notes"].append(
            f"Aucune case ne voit toutes les cases citées avec un {drop} à "
            f"retirer — l'élimination ne porte sur rien.")
        out["verdict"] = "empty"
        out["title"] = "⚪ Sans effet"

    # 2 — does the engine actually derive it, and under which name?
    want = {(i, drop) for i in targets}
    support = None
    if want:
        # ⚠ Look for a step of the CLAIMED technique first. Reporting the easiest
        # supporting step instead would tell someone who named the right pattern
        # that they were wrong, just because a simpler one also happens to fit.
        fallback = None
        for st in all_steps(cells, elims, MAX_TIER):
            if not want <= set(st["targets"]):
                continue
            if st["technique"] == claim["technique"]:
                support = st
                break
            if fallback is None:
                fallback = st
        support = support or fallback
    if support and not liars:
        if claim["technique"] and claim["technique"] != support["technique"]:
            out["verdict"] = "mislabelled"
            out["title"] = "⚠️ Vraie, mais pas par cette technique"
            out["notes"].append(
                f"L'élimination tient — mais par un {support['label_fr']}, "
                f"pas un {T.LABELS_FR.get(claim['technique'], claim['technique'])}.")
        else:
            out["verdict"] = "valid"
            out["title"] = "✅ Valide"
        out["step"] = support
        out["notes"].append(support["why_fr"])

    if claim["guessed"]:
        out["notes"].append("J'ai compris « w » comme un W-Wing.")
    elif claim["technique"] is None:
        out["notes"].append(
            "Je n'ai pas reconnu de nom de technique — je juge quand même "
            "l'élimination, mais je ne peux rien dire du motif que tu décris.")

    # 3 — does the claim even cohere with its own technique?
    if claim["technique"] and named and out["verdict"] != "valid":
        union = 0
        for i in named:
            union |= ctx.cand[i]
        if not union & bit(drop):
            out["notes"].append(
                f"Un {T.LABELS_FR.get(claim['technique'], claim['technique'])} sur "
                f"{', '.join(name(i) for i in named)} ne peut pas retirer un "
                f"{drop} : aucune de ces cases n'a le {drop} en candidat.")

    # 4 — degeneracy, when the claim names a wing
    if claim["technique"] == "w_wing" and len(named) >= 2:
        ok, notes = diagnose_w_wing(ctx, named[0], named[1], claim["link_digit"])
        out["notes"] += notes
        if not ok and out["verdict"] in ("unknown", "empty"):
            out["verdict"] = "degenerate"
            out["title"] = "🌀 Motif dégénéré"
        if not ok and out["verdict"] == "false":
            out["title"] = "❌ Faux — et le motif n'existe pas"

    if out["verdict"] == "unknown" and not liars and targets:
        out["notes"].append(
            "L'élimination ne contredit pas la solution, mais je ne sais pas la "
            "prouver avec les techniques que je connais. Je ne la valide pas "
            "pour autant : « vrai » et « démontré » sont deux choses.")
    return out


# --- the pencil audit ----------------------------------------------------------

def audit_pencil(cells, pencil, elims=()):
    """Compare the player's own pencil marks to the real candidates.

    Graded on purpose — the point is to help him find his own slip, not to do
    the marking for him. A SPURIOUS mark (a digit he wrote that is impossible)
    is called out ahead of a missing one: it is the one that will send him down
    a wrong path.
    """
    cand = _cand_with(cells, elims)
    missing, spurious = [], []
    for i in range(81):
        if cells[i] or not pencil.get(i):
            continue
        his = pencil[i] & ALL
        for d in bits(his & ~cand[i]):
            spurious.append((i, d))
        for d in bits(cand[i] & ~his):
            missing.append((i, d))
    units = sorted({unit_name_fr(u) for i, _ in spurious + missing
                    for u in (i // 9, 9 + i % 9)})
    return {"spurious": spurious, "missing": missing,
            "total": len(spurious) + len(missing),
            "units": units,
            "cells": sorted({i for i, _ in spurious + missing})}
