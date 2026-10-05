"""The engine's contract.

Stdlib unittest, no network, no write outside a temp dir.

    python3 -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sudoku import engine, generator, grid as G, techniques as T
from sudoku.solver import solution, solve_count

#: A position the engine produced itself: `generator.make(rng=random.Random(4))`
#: (v0.11.4), then its singles played forward up to the first elimination (a
#: pointing). Unique solution; grades « Diabolique » (a skyscraper further on).
GRID = ("23.89.154894...762.5124.893.8.91.5261297654385...82917"
        "9.2.7.385.15..8.79.78..9.41")


class TestTheOtherVerdicts(unittest.TestCase):
    def test_an_unreadable_claim_says_what_it_could_not_read(self):
        r = engine.verify_claim(G.parse(GRID), "y'a un truc là")
        assert r["verdict"] == "unknown"
        assert any("aucune case" in n.lower() for n in r["notes"])

    def test_an_ambiguous_grid_refuses_to_prove_anything(self):
        # ⚠ every verdict stands on the unique solution. Without one there is no
        # ground truth, and a verifier that answers anyway is the failure it exists to catch.
        r = engine.verify_claim(G.parse("." * 81),
                                "naked pair R1C1 R1C2, retirez 7 de R1C3")
        assert r["verdict"] == "unknown"
        assert any("solution unique" in n for n in r["notes"])


class TestGradingAndHints(unittest.TestCase):
    def test_next_step_serves_the_EASIEST_step_not_the_flashiest(self):
        st = engine.next_step(G.parse(GRID))
        assert st["tier"] <= 1, "a tier-3 wing while a pointing pair is on the table"

    def test_eliminations_are_state_so_a_hint_does_not_repeat(self):
        cells = G.parse(GRID)
        first = engine.next_step(cells)
        assert first["targets"], "this position starts with an elimination"
        again = engine.next_step(cells, elims=first["targets"])
        assert again["targets"] != first["targets"] or again["placements"]

    def test_a_grid_it_cannot_finish_is_reported_honestly(self):
        # tier capped below what the puzzle needs → grade None, never a shrug
        g, label, used = engine.grade(G.parse(GRID), max_tier=0)
        assert g is None and label == "Extrême"


class TestPencilAudit(unittest.TestCase):
    def test_perfect_marks_audit_clean(self):
        cells = G.parse(GRID)
        cand = G.candidates(cells)
        pencil = {i: cand[i] for i in range(81) if not cells[i]}
        assert engine.audit_pencil(cells, pencil)["total"] == 0


class TestWWingIsSound(unittest.TestCase):
    """The W-Wing has no defensive guards left in it — two were written, both
    survived every mutation, both were deleted (see the comment in
    `find_w_wing`). This class is what replaces them."""

    def test_two_wings_that_see_each_other_are_never_a_w_wing(self):
        # they would be a naked pair, and naming it wrongly teaches the wrong
        # reflex even when the elimination happens to hold
        import random
        from sudoku import generator
        rng = random.Random(9001)
        for _ in range(6):
            rec = generator.make(rng)
            cells = G.parse(rec["puzzle"])
            work, cand = list(cells), G.candidates(cells)
            for _ in range(120):
                ctx = T.Ctx(work, cand)
                for s in T.find_w_wing(ctx):
                    x, y = s["cells"][0], s["cells"][1]
                    self.assertNotIn(y, G.PEERS[x], f"{G.name(x)}/{G.name(y)}")
                st = engine.next_step(work)
                if st is None or not engine._apply(work, cand, st):
                    break

    def test_every_w_wing_found_in_a_corpus_agrees_with_the_solution(self):
        import random
        from sudoku import generator
        rng = random.Random(5150)
        seen = 0
        for _ in range(8):
            rec = generator.make(rng)
            cells = G.parse(rec["puzzle"])
            sol = solution(cells)
            work, cand = list(cells), G.candidates(cells)
            for _ in range(150):
                ctx = T.Ctx(work, cand)
                for s in T.find_w_wing(ctx):
                    seen += 1
                    for i, d in s["targets"]:
                        self.assertNotEqual(sol[i], d,
                                            f"W-Wing removes the true {d} from {G.name(i)}")
                st = engine.next_step(work)
                if st is None or not engine._apply(work, cand, st):
                    break
        self.assertGreater(seen, 20, "the corpus stopped exercising W-Wings")


class TestTheSafetyNetActuallyCatches(unittest.TestCase):
    """`next_step(safe=True)` re-checks its own answer against brute force. In a
    healthy build it never fires — which means nothing tests it. So: hand the
    engine a detector that lies, and demand the net catch it."""

    def test_a_lying_detector_is_dropped_and_recorded(self):
        cells = G.parse(GRID)
        sol = solution(cells)
        victim = next(i for i in range(81) if not cells[i])

        def liar(ctx):
            yield T.step("liar", 0, "je mens", cells=[victim],
                         targets=[(victim, sol[victim])])

        engine.ALERTS.clear()
        saved = list(T.CATALOGUE)
        T.CATALOGUE.insert(0, (0, liar))
        try:
            st = engine.next_step(cells, safe=True)
        finally:
            T.CATALOGUE[:] = saved
        self.assertIsNotNone(st)
        self.assertNotEqual(st["technique"], "liar", "the net let a lie through")
        self.assertTrue(engine.ALERTS, "the net swallowed it silently")
        engine.ALERTS.clear()

    def test_a_detector_that_PLACES_a_wrong_digit_is_caught_too(self):
        # ⚠ the net has two halves — eliminations and placements — and a test
        # that only lies one way leaves the other half untested. A mutation
        # proved exactly that on 2026-09-14.
        cells = G.parse(GRID)
        sol = solution(cells)
        victim = next(i for i in range(81) if not cells[i])
        wrong = next(d for d in range(1, 10) if d != sol[victim])

        def liar(ctx):
            yield T.step("liar", 0, "je mens", cells=[victim],
                         placements=[(victim, wrong)])

        engine.ALERTS.clear()
        saved = list(T.CATALOGUE)
        T.CATALOGUE.insert(0, (0, liar))
        try:
            st = engine.next_step(cells, safe=True)
        finally:
            T.CATALOGUE[:] = saved
        self.assertNotEqual(st["technique"], "liar")
        self.assertTrue(engine.ALERTS)
        engine.ALERTS.clear()

    def test_without_the_net_the_same_lie_WOULD_reach_the_page(self):
        # proves the previous test is measuring the net, not the detector order
        cells = G.parse(GRID)
        sol = solution(cells)
        victim = next(i for i in range(81) if not cells[i])

        def liar(ctx):
            yield T.step("liar", 0, "je mens", cells=[victim],
                         targets=[(victim, sol[victim])])

        saved = list(T.CATALOGUE)
        T.CATALOGUE.insert(0, (0, liar))
        try:
            st = engine.next_step(cells, safe=False)
        finally:
            T.CATALOGUE[:] = saved
        self.assertEqual(st["technique"], "liar")


class TestCompactNotation(unittest.TestCase):
    """Players write "45", not "R4C5". A verifier you have to translate for is a
    verifier nobody uses — but a compact reading must never fire when a proper
    R#C# is present, and must never eat a candidate set."""

    def test_two_digits_are_read_as_line_column(self):
        c = engine.parse_claim("w-wing 45 - 46, retirer 6 du 63")
        self.assertEqual(c["notation"], "compact")
        self.assertEqual([G.name(i) for i in c["cells"]], ["R4C5", "R4C6", "R6C3"])
        self.assertEqual(c["drop"], 6)
        self.assertEqual([G.name(i) for i in c["targets"]], ["R6C3"])

    def test_the_eliminated_digit_is_not_swallowed_into_a_coordinate(self):
        # "retirer 6 du 63" — the 6 is the digit, 63 is the cell
        c = engine.parse_claim("retirer 6 du 63")
        self.assertEqual(c["drop"], 6)
        self.assertEqual([G.name(i) for i in c["targets"]], ["R6C3"])

    def test_a_candidate_set_in_braces_is_not_a_cell(self):
        c = engine.parse_claim("w-wing 25 - 79 {3,6}, retirer 3 de 29")
        self.assertNotIn(G.parse_cell("R3C6"), c["cells"])
        self.assertEqual([G.name(i) for i in c["pattern"]], ["R2C5", "R7C9"])

    def test_a_proper_RxCy_claim_never_falls_into_compact_reading(self):
        c = engine.parse_claim("W-Wing R2C3 et R6C8, retirez 6 de R2C8")
        self.assertEqual(c["notation"], "rc")
        self.assertEqual([G.name(i) for i in c["cells"]],
                         ["R2C3", "R6C8", "R2C8"])

    def test_a_spelled_out_technique_is_never_marked_as_guessed(self):
        c = engine.parse_claim("W-Wing R2C3 et R6C8, retirez 6 de R2C8")
        self.assertFalse(c["guessed"])


if __name__ == "__main__":
    unittest.main()


class TestTheRatingScale(unittest.TestCase):
    """`tier` is a FAMILY of technique, not a difficulty: a skyscraper is a
    single-digit CHAIN (tier 2, rated 6.6) while an XY-wing looks at three cells
    (tier 3, rated 4.2). `T.RATING` is the difficulty axis; `tier` teaches the fiches."""

    def test_every_technique_the_catalogue_can_yield_is_rated(self):
        """A new detector without a rating would raise KeyError mid-grade, on a
        real grid, in front of him. Set equality, so it cannot be forgotten."""
        self.assertEqual(set(T.RATING), set(T.LABELS_FR))

    def test_the_bands_are_strictly_increasing(self):
        ceilings = [c for c, _ in engine.BANDS]
        self.assertEqual(ceilings, sorted(set(ceilings)))
        self.assertEqual([b for _, b in engine.BANDS], [0, 1, 2])


