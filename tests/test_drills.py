"""The practice exercises behind every fiche.

Rogzy 2026-09-15: *"i'd like for the exeplaination to have also practice
exercice. like pre load 20 of each with basically the crayon (small number)
alreayd in"*, and, asked what the exercise then does: *"bah il me propose la
solution si je demande"*.

Two claims the page makes, and both are checkable here rather than by eye:

  • **The crayon is fully in.** Not the fiche's filtered picture — all nine
    candidates, because deciding which ones matter IS the exercise.
  • **The answer only comes if he asks.** Before he does, the step's sentence,
    its highlight and its struck victims must be absent from the HTML — not
    hidden by CSS, absent. A solution you can read in View Source is a solution
    that was given.

And the same bargain `examples.py` signs: the bank stores POSITIONS and nothing
else, so a grid whose technique has stopped firing has to fail LOUDLY here —
nobody would ever notice a silent exercise on the page.
"""
import os
import re
import sys
import unittest
import urllib.parse

os.environ["SUDOKU_POOL_FILL"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sudoku import drills, engine, examples, grid as G, techniques as T
from sudoku.solver import solution

import app

WANT = 20          # what the harvester is asked for, per technique


class TestTheBankIsHonest(unittest.TestCase):
    def test_every_technique_has_exercises(self):
        for k in T.LABELS_FR:
            self.assertTrue(drills.DRILLS.get(k),
                            f"{k} has no practice positions at all")

    def test_every_technique_reaches_twenty(self):
        """The shipped bank is complete — 23 × 20. Pinned rather than given a
        tolerance on purpose: `bug_plus_one` is rare enough that a 90-second
        harvest stops at 8 and an 1100-second one reaches 20, so a short bank
        means the harvest was cut short — a decision for whoever re-ran it, not
        something a lenient test should absorb in silence."""
        self.assertEqual({k: len(v) for k, v in drills.DRILLS.items()
                          if len(v) != WANT}, {})
        self.assertEqual(sum(len(v) for v in drills.DRILLS.values()),
                         WANT * len(T.LABELS_FR))

    def test_every_position_still_yields_its_technique(self):
        for k, grids in drills.DRILLS.items():
            for g in grids:
                cells = G.parse(g)
                found = {st["technique"] for st in engine.all_steps(cells)}
                self.assertIn(k, found, f"{k}: {g} no longer yields it")

    def test_an_exercise_is_never_one_of_the_worked_examples(self):
        """Repeating the position explained three paragraphs above is a reading
        test, not practice."""
        for k, grids in drills.DRILLS.items():
            overlap = set(grids) & set(examples.EXAMPLES.get(k, ()))
            self.assertFalse(overlap, f"{k} reuses its own example: {overlap}")

    def test_no_position_is_served_twice_inside_a_technique(self):
        for k, grids in drills.DRILLS.items():
            self.assertEqual(len(grids), len(set(grids)), k)

    def test_every_position_is_a_legal_grid(self):
        for k, grids in drills.DRILLS.items():
            for g in grids:
                self.assertEqual(len(g), 81, f"{k}: {g}")
                self.assertTrue(G.is_valid(G.parse(g)), f"{k}: {g}")


class TestTheDrillPage(unittest.TestCase):
    KEY = "x_wing"

    def page(self, n=1, reveal=False):
        return app.drill_page(self.KEY, n, reveal)

    def test_the_count_it_prints_is_the_count_it_holds(self):
        total = len(drills.DRILLS[self.KEY])
        self.assertEqual(app.drill_count(self.KEY), total)
        self.assertIn(f"exercice 1 / {total}", self.page())

    def test_the_crayon_is_all_nine_not_the_fiche_s_selection(self):
        """The fiche's picture pencils only the digits its argument is about. An
        exercise must pencil everything, or it has already done the looking."""
        g = drills.DRILLS[self.KEY][0]
        cells = G.parse(g)
        cand = G.candidates(cells)
        expected = sum(len(G.bits(cand[i])) for i in range(81) if not cells[i])
        self.assertEqual(len(re.findall(r'class="mine', self.page())), expected)
        # and the fiche's own picture really is narrower, or this proves nothing
        st = next(s for s in engine.all_steps(cells)
                  if s["technique"] == self.KEY)
        self.assertLess(len(re.findall(r'class="mine', app.mini_board(cells, st))),
                        expected)

    def test_the_answer_is_absent_until_he_asks(self):
        g = drills.DRILLS[self.KEY][0]
        cells = G.parse(g)
        st = next(s for s in engine.all_steps(cells)
                  if s["technique"] == self.KEY)
        before, after = self.page(), self.page(reveal=True)
        self.assertNotIn(st["why_fr"], before)
        self.assertIn(st["why_fr"], after)
        # ⚠ on the RENDERED cells, not on the word: `.pm .cut` and `.cell.hl`
        # are in the inline stylesheet of every page in the app, so a bare
        # `assertNotIn("cut", html)` is a test that can only ever fail.
        for name in ("hl", "tgt"):
            self.assertIsNone(re.search(rf'class="cell[^"]*\b{name}\b', before),
                              f"{name} is painted before he asked")
            self.assertIsNotNone(re.search(rf'class="cell[^"]*\b{name}\b', after),
                                 f"{name} is missing from the answer")
        self.assertNotIn('class="mine cut"', before)
        self.assertIn('class="mine cut"', after)

    def test_the_reveal_button_is_the_only_way_in(self):
        self.assertIn("?voir=1", self.page())
        self.assertNotIn("?voir=1", self.page(reveal=True))
        self.assertIn("Recacher", self.page(reveal=True))

    def test_the_solved_grid_never_reaches_the_page(self):
        for reveal in (False, True):
            g = drills.DRILLS[self.KEY][0]
            sol = G.to_string(solution(G.parse(g)))
            self.assertNotIn(sol, self.page(reveal=reveal))

    def test_it_says_when_the_engine_would_have_played_something_simpler(self):
        """A drill the engine would not itself pick is a fair exercise — but only
        if the reveal admits it. Told before, it would be a hint."""
        said = 0
        for k, grids in drills.DRILLS.items():
            for n, g in enumerate(grids, 1):
                if app._would_play(G.parse(g), k) is None:
                    continue
                html = app.drill_page(k, n, True)
                self.assertIn("aurait commencé par", html, f"{k}#{n}")
                self.assertNotIn("aurait commencé par", app.drill_page(k, n))
                said += 1
                break
            if said >= 3:
                break
        self.assertTrue(said, "no drill needed the admission — suspicious")

    def test_the_answer_names_every_cell_it_touches_and_its_colours(self):
        """The sentence argues the pattern; this is what the pattern COSTS — which
        cell loses which digit, which cell gets which digit — plus the key that
        makes the colours on the board mean something. A reveal without them is a
        pretty picture. Both branches are walked, and the test says so: a suite
        that only ever sees eliminations would not notice placements going mute.
        """
        saw_targets = saw_placements = False
        for k in T.LABELS_FR:
            g = drills.DRILLS[k][0]
            cells = G.parse(g)
            st = next(s for s in engine.all_steps(G.parse(g))
                      if s["technique"] == k)
            html = app.drill_page(k, 1, True)
            for i, d in st["targets"]:
                self.assertIn(f"{d} de {G.name(i)}", html, f"{k}: {i}/{d}")
                saw_targets = True
            for i, d in st["placements"]:
                self.assertIn(f"{G.name(i)} = {d}", html, f"{k}: {i}/{d}")
                saw_placements = True
            self.assertIn("le motif", html, f"{k}: no colour key")
            if st["targets"]:
                self.assertIn("ce qui tombe", html, k)
            if st["placements"]:
                self.assertIn("ce qui se pose", html, k)
        self.assertTrue(saw_targets, "no elimination was ever checked")
        self.assertTrue(saw_placements, "no placement was ever checked")

    def test_the_neighbours_stop_at_the_ends(self):
        total = len(drills.DRILLS[self.KEY])
        first, last = self.page(1), self.page(total)
        self.assertIn(f'href="2"', first)
        self.assertNotIn("‹ 0", first)
        self.assertNotIn(f'href="{total + 1}"', last)
        self.assertIn(f'href="{total - 1}"', last)

    def test_an_exercise_outside_the_bank_has_no_page(self):
        total = len(drills.DRILLS[self.KEY])
        self.assertIsNone(app.drill_page(self.KEY, 0))
        self.assertIsNone(app.drill_page(self.KEY, total + 1))
        self.assertIsNone(app.drill_page("xyzzy_wing", 1))

    def test_every_technique_renders_its_first_and_last_exercise(self):
        for k in T.LABELS_FR:
            total = app.drill_count(k)
            for n in (1, total):
                html = app.drill_page(k, n, True)
                self.assertIsNotNone(html, f"{k}#{n}")
                self.assertIn("La réponse", html, f"{k}#{n}")
                self.assertNotIn("l'exercice est cassé", html, f"{k}#{n}")


class TestTheDrillRoutes(unittest.TestCase):
    KEY = "x_wing"

    def test_only_positions_the_bank_holds_are_routes(self):
        total = app.drill_count(self.KEY)
        self.assertTrue(app.route_exists(f"/entrainement/{self.KEY}/1"))
        self.assertTrue(app.route_exists(f"/entrainement/{self.KEY}/{total}"))
        self.assertFalse(app.route_exists(f"/entrainement/{self.KEY}/0"))
        self.assertFalse(app.route_exists(f"/entrainement/{self.KEY}/{total + 1}"))
        self.assertFalse(app.route_exists("/entrainement/xyzzy/1"))
        self.assertFalse(app.route_exists(f"/entrainement/{self.KEY}/1", "POST"))

    def test_the_fiche_sends_him_to_the_first_exercise_and_it_resolves(self):
        html = app.fiche_page(self.KEY)
        href = f"../entrainement/{self.KEY}/1"
        self.assertIn(f'href="{href}"', html)
        # resolved from the URL the FICHE is served at — no trailing slash
        path = urllib.parse.urlparse(urllib.parse.urljoin(
            f"http://localhost/sudoku/techniques/{self.KEY}", href)).path
        self.assertEqual(path, f"/sudoku/entrainement/{self.KEY}/1")
        self.assertTrue(app.route_exists(path[len("/sudoku"):]))

    def test_the_trailing_slash_spelling_is_redirected_not_rendered(self):
        """Serving both spellings means serving one of them with a nav strip one
        level off — and only ever finding out by typing it by hand."""
        self.assertEqual(app.canonical(f"/entrainement/{self.KEY}/3/"), "../3")
        self.assertEqual(app.canonical("/techniques/x_wing/"), "../x_wing")
        for stay in (f"/entrainement/{self.KEY}/3", "/techniques/x_wing",
                     "/techniques/", "/", "/assistant/"):
            self.assertEqual(app.canonical(stay), "", stay)

    def test_the_redirect_target_lands_back_on_the_page_itself(self):
        served = f"/entrainement/{self.KEY}/3/"
        target = urllib.parse.urlparse(urllib.parse.urljoin(
            "http://localhost/sudoku" + served, app.canonical(served))).path
        self.assertEqual(target, f"/sudoku/entrainement/{self.KEY}/3")

    def test_a_technique_with_no_exercises_says_so_instead_of_linking(self):
        real = drills.DRILLS.get(self.KEY)
        drills.DRILLS[self.KEY] = []
        try:
            html = app.fiche_page(self.KEY)
            self.assertIn("Pas encore d'exercices", html)
            self.assertNotIn("entrainement", html)
            self.assertFalse(app.route_exists(f"/entrainement/{self.KEY}/1"))
        finally:
            drills.DRILLS[self.KEY] = real


if __name__ == "__main__":
    unittest.main()
