"""The generator's promises — and the invariant that guards the whole engine.

    python3 -m unittest discover tests
"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sudoku import engine, generator, grid as G, techniques as T
from sudoku.solver import solve_count, solution

#: small enough to run on every commit, large enough to have caught things
CORPUS_N = 14
RNG_SEED = 20260914


def _corpus(n=CORPUS_N, seed=RNG_SEED):
    rng = random.Random(seed)
    return [generator.make(rng) for _ in range(n)]


class TestGeneratedPuzzles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = _corpus()

    def test_every_generated_puzzle_has_exactly_one_solution(self):
        for r in self.recs:
            self.assertEqual(solve_count(G.parse(r["puzzle"]), 2), 1, r["puzzle"])

    def test_the_stated_solution_is_the_real_one(self):
        for r in self.recs:
            self.assertEqual(G.to_string(solution(G.parse(r["puzzle"]))),
                             r["solution"])

    def test_the_grade_is_reproducible(self):
        # a difficulty that moves between two reads is a difficulty that means
        # nothing — the learning journal is built on these buckets
        for r in self.recs:
            again = engine.grade(G.parse(r["puzzle"]))
            self.assertEqual(again[0], r["grade"], r["puzzle"])

    def test_a_graded_puzzle_is_a_puzzle_the_engine_can_finish(self):
        for r in self.recs:
            if r["grade"] is None:
                continue
            steps, solved, cells = engine.solve_path(G.parse(r["puzzle"]))
            self.assertTrue(solved, f"graded {r['label']} but cannot finish it")

    def test_clue_counts_stay_in_a_human_range(self):
        for r in self.recs:
            self.assertTrue(17 <= r["clues"] <= 40, r["clues"])

    def test_targeted_generation_never_returns_the_WRONG_grade(self):
        # it is allowed to fail; it is not allowed to lie. A "diabolique" that
        # falls to two singles is worse than no puzzle at all.
        rng = random.Random(7)
        for want in (0, 1):
            rec = generator.make_targeted(want, rng, tries=25)
            if rec is not None:
                self.assertEqual(rec["grade"], want)


class TestTheSafetyNet(unittest.TestCase):
    """The one test that subsumes the others: walk every generated puzzle to the
    end and check every single deduction against brute force."""

    def test_no_step_in_any_solve_path_ever_contradicts_the_solution(self):
        for r in _corpus(10, 777):
            cells = G.parse(r["puzzle"])
            sol = solution(cells)
            work = list(cells)
            cand = G.candidates(work)
            for _ in range(400):
                ctx = T.Ctx(work, cand)
                st = None
                for tier, fn in T.CATALOGUE:
                    for s in fn(ctx):
                        st = s
                        break
                    if st:
                        break
                if st is None:
                    break
                for i, d in st["targets"]:
                    self.assertNotEqual(
                        sol[i], d,
                        f"{st['technique']} removes the true {d} from {G.name(i)}")
                for i, d in st["placements"]:
                    self.assertEqual(
                        sol[i], d,
                        f"{st['technique']} places a wrong {d} in {G.name(i)}")
                if not engine._apply(work, cand, st):
                    break

    def test_the_safety_net_never_had_to_fire(self):
        """`next_step(safe=True)` drops any step that would break the grid and
        records it in ALERTS. In a healthy build ALERTS stays empty — a non-empty
        one means a detector is wrong and the net caught it."""
        engine.ALERTS.clear()
        for r in _corpus(8, 31337):
            cells = G.parse(r["puzzle"])
            for _ in range(60):
                st = engine.next_step(cells, safe=True)
                if st is None:
                    break
                for i, d in st["placements"]:
                    cells[i] = d
                if not st["placements"]:
                    break
        self.assertEqual(engine.ALERTS, [],
                         "a detector proposed a step that breaks the grid")


if __name__ == "__main__":
    unittest.main()
