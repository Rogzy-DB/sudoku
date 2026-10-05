"""The technique fiches and the assistant.

Rogzy 2026-09-15: *"i'd like to have one page by technique, with clear
explication, 2-5 exemple for each one"* and *"une option / tab assistant, ou je
peux ecrir ma grille actuel, faire indicie, et ca me propose des solution […]
mais en me laissant choisir et donc voire les options des techniques"*.

The bargain these tests enforce: the example bank on disk stores POSITIONS and
nothing else, and the fiche re-derives the step, the drawing and the sentence at
render time — so nothing can drift from what the engine says. The price is that a
pinned grid whose technique stopped firing has to fail LOUDLY here, because
nobody would ever notice it on the page.
"""
import os
import re
import sys
import unittest
import urllib.parse

os.environ["SUDOKU_POOL_FILL"] = "0"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sudoku import engine, examples, fiches, grid as G, techniques as T
from sudoku.solver import solution, solve_count

import app


class TestTheBankIsHonest(unittest.TestCase):
    def test_every_technique_has_a_written_fiche(self):
        self.assertEqual(set(fiches.FICHES), set(T.LABELS_FR))
        for k, f in fiches.FICHES.items():
            for part in ("quoi", "pourquoi", "reperer"):
                self.assertTrue(f.get(part, "").strip(), f"{k}.{part}")
                self.assertGreater(len(f[part]), 40, f"{k}.{part} is a stub")

    def test_every_technique_has_between_2_and_5_examples(self):
        for k in T.LABELS_FR:
            n = len(examples.EXAMPLES.get(k, []))
            self.assertGreaterEqual(n, 2, f"{k}: {n} example(s)")
            self.assertLessEqual(n, 5, f"{k}: {n} examples")

    def test_every_pinned_grid_STILL_yields_its_technique(self):
        """The whole bargain. A detector change that quietly stops matching one of
        these would leave a fiche with a blank example and no other sign."""
        for k, grids in examples.EXAMPLES.items():
            for g in grids:
                cells = G.parse(g)
                found = {st["technique"] for st in engine.all_steps(cells)}
                self.assertIn(k, found, f"{k}: {g}")

    def test_every_pinned_grid_is_a_real_position(self):
        seen = set()
        for k, grids in examples.EXAMPLES.items():
            for g in grids:
                self.assertEqual(len(g), 81, f"{k}: {g}")
                self.assertEqual(solve_count(G.parse(g), 2), 1,
                                 f"{k} has no single solution: {g}")
                self.assertNotIn((k, g), seen)      # no example twice in one fiche
                seen.add((k, g))

    def test_the_examples_inside_one_fiche_are_different_positions(self):
        for k, grids in examples.EXAMPLES.items():
            self.assertEqual(len(set(grids)), len(grids), k)


class TestTheFichePage(unittest.TestCase):
    def test_every_fiche_renders_with_its_prose_and_its_boards(self):
        for k in T.LABELS_FR:
            html = app.fiche_page(k)
            self.assertIsNotNone(html, k)
            self.assertIn(T.LABELS_FR[k], html)
            for part in ("Ce que c", "Pourquoi", "repérer"):
                self.assertIn(part, html, k)
            self.assertIn("Exemple 1", html, k)
            self.assertIn("Exemple 2", html, k)
            self.assertEqual(html.count('class="board"'),
                             len(examples.EXAMPLES[k]), k)

    def test_the_sentence_under_a_board_is_the_ENGINE_S_not_a_typed_one(self):
        # the fiche never hand-writes a word about a particular position
        for k in ("w_wing", "x_wing", "naked_pair"):
            cells = G.parse(examples.EXAMPLES[k][0])
            st = next(s for s in engine.all_steps(cells) if s["technique"] == k)
            self.assertIn(app.la.esc(st["why_fr"]), app.fiche_page(k))

    def test_a_board_marks_the_pattern_what_falls_and_what_is_placed(self):
        html = app.fiche_page("naked_pair")
        self.assertIn("cell hl", html)          # the pattern
        self.assertIn("tgt", html)              # its victims
        self.assertIn("mine cut", html)         # …with the digit struck in place
        self.assertIn("plc", app.fiche_page("hidden_single"))   # a placement

    def test_a_single_digit_technique_draws_only_that_digit(self):
        # nine columns of candidates is a picture of nothing
        cells = G.parse(examples.EXAMPLES["x_wing"][0])
        st = next(s for s in engine.all_steps(cells) if s["technique"] == "x_wing")
        self.assertEqual(app.example_digits(G.candidates(cells), st),
                         {d for _, d in st["targets"]})

    def test_a_wing_draws_the_whole_pair_not_just_the_victim(self):
        # a W-Wing you can only see one digit of is a W-Wing you cannot check
        cells = G.parse(examples.EXAMPLES["w_wing"][0])
        st = next(s for s in engine.all_steps(cells) if s["technique"] == "w_wing")
        self.assertGreaterEqual(len(app.example_digits(G.candidates(cells), st)), 2)

    def test_the_provenance_of_each_example_is_COMPUTED_not_claimed(self):
        # "this is the move the engine would play here" is a claim about a grid;
        # it is derived per example, so it cannot be wrong on any of them
        for k in ("naked_single", "jellyfish"):
            cells = G.parse(examples.EXAMPLES[k][0])
            first = next(engine.all_steps(cells))
            html = app.fiche_page(k)
            # ⚠ la.esc turns every apostrophe into &#x27; — assert on the escaped
            # form or this passes on a page that says nothing of the sort.
            if first["technique"] == k:
                self.assertIn(app.la.esc("c'est exactement le pas que le moteur"), html)
            else:
                self.assertIn("Ici le moteur commencerait par", html)

    def test_the_fiche_never_leaks_the_finished_grid(self):
        for k in ("w_wing", "x_wing"):
            g = examples.EXAMPLES[k][0]
            sol = G.to_string(solution(G.parse(g)))
            self.assertNotIn(sol, app.fiche_page(k))

    def test_an_unknown_technique_has_no_page(self):
        self.assertIsNone(app.fiche_page("xyzzy_wing"))
        self.assertIsNone(app.fiche_page(""))


class TestTheFicheRoutes(unittest.TestCase):
    def test_the_index_links_to_every_fiche_and_the_links_resolve(self):
        html = app.techniques_page()
        for k in T.LABELS_FR:
            self.assertIn(f'href="{k}"', html)
        for m in re.finditer(r'href="([^"]*)"', html):
            href = m.group(1)
            if href.startswith(("http", "#")) or not href:
                continue
            path = urllib.parse.urlparse(urllib.parse.urljoin(
                "http://localhost/sudoku/techniques/", href)).path
            if not path.startswith("/sudoku"):
                continue
            self.assertTrue(app.route_exists(path[len("/sudoku"):] or "/"),
                            f"index → {href} lands on {path}")

    def test_only_real_techniques_are_routes(self):
        self.assertTrue(app.route_exists("/techniques/w_wing"))
        self.assertFalse(app.route_exists("/techniques/xyzzy"))
        self.assertFalse(app.route_exists("/techniques/w_wing", "POST"))


class TestTheAssistant(unittest.TestCase):
    GRID = examples.EXAMPLES["w_wing"][0]

    def test_elims_survive_the_round_trip_and_junk_is_dropped(self):
        self.assertEqual(app.parse_elims("12:3, 45:7"), [(12, 3), (45, 7)])
        self.assertEqual(app.parse_elims("99:3,12:0,x:y,,12:3"), [(12, 3)])
        self.assertEqual(app.fmt_elims([(45, 7), (12, 3), (12, 3)]), "12:3,45:7")

    def test_it_offers_EVERY_move_available_not_just_the_easiest(self):
        """The founding promise of this tab — *all* the moves on the table, not
        one hint. Since 2026-09-17 they live in ONE menu instead of one card each
        (Rogzy: *« toutes les propositions de solution en mode drop down »*), so
        the count to assert moved from the cards to the options — the promise did
        not."""
        cells = G.parse(self.GRID)
        steps = list(engine.all_steps(cells))
        self.assertGreater(len(steps), 1)
        html = app.assistant_page(self.GRID)
        self.assertEqual(len(re.findall(r'<option value="\d+"', html)), len(steps))
        for i in range(len(steps)):
            self.assertIn(f'<option value="{i}"', html)
        # exactly one is selected, and exactly one is explained
        self.assertEqual(html.count(" selected>"), 1)
        self.assertEqual(len(re.findall(r'<div class="move(?: picked)?">', html)), 1)

    def test_the_menu_names_every_TECHNIQUE_and_the_shown_move_links_to_its_fiche(self):
        """Two claims the dropdown has to keep from the card list it replaced:
        every available technique is still NAMED (it is an `<optgroup>` label
        now, with its count — that is where the old « Techniques disponibles »
        chip strip went), and the move on screen is one tap from its rule.

        ⚠ Assert the fiche link INSIDE the move block: `../techniques/` also
        appears in the tab strip at the top of every page, so a page-wide
        assertIn stays green on a detail card that links nothing."""
        steps = list(engine.all_steps(G.parse(self.GRID)))
        counts = {}
        for st in steps:
            counts[st["technique"]] = counts.get(st["technique"], 0) + 1

        for i in range(len(steps)):
            html = app.assistant_page(self.GRID, pick=i)
            for key, n in counts.items():
                label = f'{T.LABELS_FR[key]} · {n} coup{"s" if n > 1 else ""}'
                self.assertIn(f'<optgroup label="{app.la.esc(label)}">', html)
            block = re.search(r'<div class="move(?: picked)?">.*?</div>\s*<div class="tools"',
                              html, re.S)
            self.assertIsNotNone(block, f"no move detail for pick={i}")
            self.assertIn(f'href="../techniques/{steps[i]["technique"]}"',
                          block.group(0))
            self.assertIn(app.la.esc(steps[i]["label_fr"]), block.group(0))

    PLACING = examples.EXAMPLES["hidden_single"][0]

    def test_playing_a_PLACEMENT_fills_the_cell(self):
        cells = G.parse(self.PLACING)
        steps = list(engine.all_steps(cells))
        i = next(n for n, s in enumerate(steps) if s["placements"])
        cell, digit = steps[i]["placements"][0]
        out, _elims, why = app.assistant_apply(self.PLACING, "", i)
        self.assertEqual(why, "")
        self.assertEqual(out[cell], str(digit))

    def test_playing_an_ELIMINATION_is_remembered_and_does_not_come_back(self):
        """The founding lesson: a step that only removes candidates changes
        nothing in `cells`, so an assistant that forgot its eliminations would
        serve the same move forever."""
        cells = G.parse(self.GRID)
        steps = list(engine.all_steps(cells))
        i = next(n for n, s in enumerate(steps)
                 if s["targets"] and not s["placements"])
        was = steps[i]
        out, elims, why = app.assistant_apply(self.GRID, "", i)
        self.assertEqual(why, "")
        self.assertEqual(out, self.GRID)                 # the grid did not move…
        self.assertTrue(elims)                           # …but the state did
        again = list(engine.all_steps(G.parse(out), app.parse_elims(elims)))
        self.assertNotIn((was["technique"], tuple(sorted(was["targets"]))),
                         [(s["technique"], tuple(sorted(s["targets"]))) for s in again])

    def test_an_elimination_about_a_now_filled_cell_is_dropped(self):
        cells = G.parse(self.PLACING)
        steps = list(engine.all_steps(cells))
        i = next(n for n, s in enumerate(steps) if s["placements"])
        cell, _d = steps[i]["placements"][0]
        _out, elims, _why = app.assistant_apply(self.PLACING, f"{cell}:5", i)
        self.assertNotIn(f"{cell}:", elims)

    def test_a_pick_that_no_longer_exists_changes_nothing(self):
        out, elims, why = app.assistant_apply(self.GRID, "", 999)
        self.assertEqual((out, elims), (self.GRID, ""))
        self.assertIn("n'existe plus", why)

    def test_a_grid_with_no_solution_is_refused_not_reasoned_about(self):
        # ⚠ built to BE contradictory, not hoped to be: the first version of this
        # test wrapped its assertions in `if solve_count(...) == 0` and therefore
        # asserted nothing whenever the tweak happened to stay solvable.
        # dense on purpose: an almost-empty contradictory grid is a search, not a
        # test — proving THAT one unsolvable takes longer than the whole suite.
        cells = G.parse(self.GRID)
        i = next(n for n in range(81) if not cells[n])
        row = [cells[j] for j in range(i // 9 * 9, i // 9 * 9 + 9) if cells[j]]
        cells[i] = row[0]                              # a digit already in its row
        bad = G.to_string(cells)
        # ⚠ and `solve_count` says ONE here, not zero: a filled cell carries its
        # own candidate bit, so propagation never sees the clash. `is_valid` is
        # the check that looks — this test exists because the first version of the
        # assistant trusted the solver and reasoned happily about a broken grid.
        self.assertEqual(solve_count(G.parse(bad), 2), 1)
        self.assertFalse(G.is_valid(G.parse(bad)))
        html = app.assistant_page(bad)
        self.assertIn("deux fois dans une même ligne", html)
        self.assertEqual(re.findall(r'<div class="move( picked)?">', html), [])

    def test_a_grid_that_really_has_no_solution_is_refused_too(self):
        cells = G.parse(self.GRID)
        empties = [n for n in range(81) if not cells[n]]
        cand = G.candidates(cells)
        i = empties[0]
        # a digit its peers allow, but which kills the grid further down
        for d in G.bits(cand[i]):
            cells[i] = d
            if solve_count(cells, 2) == 0:
                break
            cells[i] = 0
        if not cells[i]:
            self.skipTest("this position has no single-cell contradiction")
        html = app.assistant_page(G.to_string(cells))
        self.assertIn("aucune solution", html)

    def test_an_ambiguous_grid_keeps_the_moves_but_drops_the_uniqueness_ones(self):
        empty = "." * 81
        html = app.assistant_page(empty)
        self.assertIn("plusieurs", html)
        self.assertNotIn(T.LABELS_FR["unique_rectangle_1"], html)

    def test_a_bad_grid_is_named_back_not_swallowed(self):
        self.assertIn("81 cases", app.assistant_page("123"))

    def test_the_assistant_never_leaks_the_finished_grid(self):
        sol = G.to_string(solution(G.parse(self.GRID)))
        self.assertNotIn(sol, app.assistant_page(self.GRID))

    def test_the_form_carries_the_state_so_the_page_needs_no_storage(self):
        html = app.assistant_page(self.GRID, "12:3")
        self.assertIn('name="cells"', html)
        self.assertIn('name="elims" value="12:3"', html)
        self.assertIn('value="apply"', html)
        self.assertIn('value="show"', html)

    def test_the_menu_opens_on_the_move_the_engine_would_play(self):
        """The card that used to say *« le premier de la liste est celui que le
        moteur jouerait »* is gone (Rogzy 2026-09-17: *« ça sert à rien »*), so the
        MENU has to keep the promise the sentence made: first option, and selected.
        Sorting the groups by name within a tier broke it — the engine's own move
        sat mid-list while the closed box displayed it."""
        steps = list(engine.all_steps(G.parse(self.GRID)))
        self.assertGreater(len(steps), 1)
        html = app.assistant_page(self.GRID)
        opts = re.findall(r'<option value="(\d+)"( selected)?>', html)
        self.assertEqual(opts[0][0], "0", "the engine's move is not the first option")
        self.assertTrue(opts[0][1], "the first option is not the one selected")
        self.assertEqual(sum(1 for _v, sel in opts if sel), 1)

    def test_showing_a_move_puts_it_on_the_BOARD_selecting_it_does_not(self):
        """The two buttons do different things and both have to keep a job: the
        menu always has a selection (so the explanation is there from the first
        render), and 👁 Montrer is what draws it on the grid. If selecting also
        highlighted, Montrer would be furniture."""
        plain = app.assistant_page(self.GRID)
        shown = app.assistant_page(self.GRID, pick=0)
        self.assertGreater(shown.count("cell hl"), plain.count("cell hl"))
        # …and the un-shown page still explains the selected move
        steps = list(engine.all_steps(G.parse(self.GRID)))
        self.assertIn(app.la.esc(steps[0]["why_fr"]), plain)

    def test_the_route_is_reachable_by_GET_and_POST(self):
        self.assertTrue(app.route_exists("/assistant"))
        self.assertTrue(app.route_exists("/assistant", "POST"))

    def test_every_link_and_action_on_the_assistant_resolves(self):
        """⚠ Resolve against the URL the page is REALLY served at — including the
        trailing slash. The first version of this test used `/sudoku/assistant`
        and passed while every form on the live page posted to
        `/sudoku/assistant/assistant` and 404ed. A relative link is only correct
        relative to something; test both spellings so neither can rot."""
        for base in ("http://localhost/sudoku/assistant/", "http://localhost/sudoku/assistant"):
            for html in (app.assistant_page(), app.assistant_page(self.GRID),
                         app.assistant_page(self.GRID, pick=0)):
                for m in re.finditer(r'(?:href|action)="([^"]*)"', html):
                    href = m.group(1)
                    method = "GET" if m.group(0)[0] == "h" else "POST"
                    if href.startswith(("http", "#")):
                        continue
                    if not href:               # action="" — posts to this page
                        self.assertTrue(app.route_exists("/assistant", method))
                        continue
                    path = urllib.parse.urlparse(
                        urllib.parse.urljoin(base, href)).path
                    if not path.startswith("/sudoku"):
                        continue
                    self.assertTrue(
                        app.route_exists(path[len("/sudoku"):] or "/", method),
                        f"{base} → {href} lands on {path} ({method})")


class TestTypingTheGrid(unittest.TestCase):
    """Rogzy 2026-09-15: *« ofc on ne colle pas une grille mais on rentre les
    chiffres sur une grille… je ne vais jamais te donner les 1231564, toujours
    taper les chiffres »*.

    Every surface that asks for a position now hands him nine rows of boxes. The
    81-character string survives as the MACHINE's spelling — the hidden field
    that carries the position from one played step to the next — and folded away
    as a paste box, never as the thing he is handed first.
    """
    GRID = examples.EXAMPLES["w_wing"][0]

    def _boxes(self, html):
        return re.findall(r'<input class="cell ent[^"]*" name="c(\d+)"', html)

    # --- the boxes are there, and there are exactly 81 of them ---------------

    def test_the_assistant_asks_for_boxes_not_for_a_string(self):
        html = app.assistant_page()
        self.assertEqual([int(n) for n in self._boxes(html)], list(range(81)))

    def test_every_door_that_wants_a_grid_asks_for_boxes(self):
        """One fix, every door. The assistant was the one he named, but the same
        « colle 81 caractères » sat on every other door too.

        ⚠ La liste a fondu avec les portes : l'import a quitté l'accueil pour un
        onglet (v0.4.1), puis l'onglet pour le plateau (v0.8.0), et le juge a
        disparu (v0.9.0). La revendication porte sur les portes QUI RESTENT."""
        _ok, _why, game = app.import_puzzle(self.GRID)
        for html in (app.import_refused_page(), app.board_page(game)):
            self.assertEqual([int(n) for n in self._boxes(html)], list(range(81)))

    def test_the_board_carries_exactly_ONE_grid_to_type_in(self):
        """⚠ Le piège d'origine : deux plateaux de saisie sur une page, `ENTRY_JS`
        bindé deux fois, chaque frappe saute deux cases. En v0.8.0 la saisie
        REVIENT sur la page de jeu (« Changer de grille »), donc la revendication
        n'est plus « zéro » mais **exactement un** : 81 cases, une seule fois.

        Le plateau de la partie, lui, est fait de `div` — il ne compte pas, et
        c'est précisément pourquoi la sélection porte sur `input.cell.ent`."""
        _ok, _why, game = app.import_puzzle(self.GRID)
        self.assertEqual([int(n) for n in self._boxes(app.board_page(game))],
                         list(range(81)))
        # et la page de repli, elle, n'en a aucune
        self.assertEqual(self._boxes(app.empty_pool_page()), [])

    def test_an_off_by_one_in_the_box_names_would_shift_the_whole_grid(self):
        """⚠ 80 or 82 boxes is not a cosmetic bug: it is `parse()`'s worst case —
        every cell shifted by one, a plausible and completely wrong puzzle. The
        names are asserted as the exact sequence c0…c80, not merely counted."""
        names = self._boxes(app.assistant_page())
        self.assertEqual(names, [str(i) for i in range(81)])

    # --- what comes back ----------------------------------------------------

    def test_the_boxes_come_back_holding_the_position(self):
        cells = G.parse(self.GRID)
        html = app.entry_board(cells)
        got = re.findall(r'name="c(\d+)" [^>]*value="(\d?)"', html)
        self.assertEqual(len(got), 81)
        for n, v in got:
            self.assertEqual(v, str(cells[int(n)]) if cells[int(n)] else "")

    def test_a_typed_grid_is_read_back_exactly(self):
        cells = G.parse(self.GRID)
        form = {f"c{i}": (str(v) if v else "") for i, v in enumerate(cells)}
        text, bad = app.cells_from_form(form)
        self.assertEqual(bad, "")
        self.assertEqual(text, self.GRID)

    def test_zero_and_dot_typed_in_a_box_mean_empty(self):
        form = {f"c{i}": "" for i in range(81)}
        form["c0"], form["c1"], form["c2"] = "0", ".", "7"
        text, bad = app.cells_from_form(form)
        self.assertEqual(bad, "")
        self.assertEqual(text[:3], "..7")

    def test_an_unreadable_box_is_NAMED_not_quietly_emptied(self):
        """A box whose content is dropped in silence is a different puzzle,
        solved confidently — the exact failure `parse()` refuses a short string
        for. It has to come back with the cell's name on it."""
        form = {f"c{i}": "" for i in range(81)}
        form["c0"], form["c40"] = "x", "12"
        text, bad = app.cells_from_form(form)
        self.assertIn("R1C1", bad)
        self.assertIn("R5C5", bad)
        self.assertEqual(len(text), 81)

    def test_the_hidden_string_still_carries_a_played_step(self):
        """No box is posted when he plays a move — the position travels in the
        hidden field, and that path must not have been broken by the boxes."""
        text, bad = app.cells_from_form({"cells": self.GRID, "op": "apply"})
        self.assertEqual((text, bad), (self.GRID, ""))

    def test_the_paste_box_still_loads_a_string_from_elsewhere(self):
        text, bad = app.cells_from_form({"text": self.GRID}, "text")
        self.assertEqual((text, bad), (self.GRID, ""))

    # --- the page around them -----------------------------------------------

    def test_the_boxes_fold_away_once_the_position_is_in(self):
        self.assertIn('<details class="fix"', app.assistant_page(self.GRID))
        self.assertNotIn('<details class="fix"', app.assistant_page())

    def test_a_broken_grid_RE_OPENS_the_boxes(self):
        """The one moment he needs them is the moment they must not be hidden."""
        cells = G.parse(self.GRID)
        i = next(n for n in range(81) if not cells[n])
        row = [cells[j] for j in range(i // 9 * 9, i // 9 * 9 + 9) if cells[j]]
        cells[i] = row[0]                       # a digit already in its row
        self.assertFalse(G.is_valid(cells))
        html = app.assistant_page(G.to_string(cells))
        self.assertIn('<details class="fix" open>', html)

    def test_a_box_I_could_not_read_re_opens_them_too(self):
        """Naming R1C5 and then folding R1C5 out of sight is half a message.
        Found on the live page, not in a test: the grid still PARSES when an
        unreadable box is blanked, so nothing else re-opened the fold."""
        html = app.assistant_page(self.GRID, err="je n'ai pas lu … en R1C5")
        self.assertIn('<details class="fix" open>', html)

    def test_the_auto_advance_is_attached_exactly_once(self):
        """Bound twice, every keystroke would jump two cells. `page()` is the
        single choke point, so a second board on the page cannot double it."""
        html = app.page("x", app.entry_board() + app.entry_board())
        self.assertEqual(html.count("ArrowRight"), 1)

    def test_a_page_with_no_boxes_ships_no_script_for_them(self):
        self.assertNotIn("ArrowRight", app.techniques_page())

    def test_the_boxes_work_with_scripting_off(self):
        """They are real inputs in a real form that posts to a real route — the
        script only saves him a Tab. This is what makes them safe on e-ink readers."""
        html = app.assistant_page()
        form = re.search(r'<form method="post" action="">.*?</form>', html, re.S)
        self.assertIsNotNone(form)
        self.assertIn('name="c0"', form.group(0))
        self.assertIn('value="analyse"', form.group(0))
        self.assertTrue(app.route_exists("/assistant", "POST"))

    # ⚠ `test_the_verify_paste_box_is_a_one_shot_loader` est SUPPRIMé avec sa page
    # (v0.9.0). Sa leçon — une boîte de collage qui partage le formulaire des 81 cases
    # doit revenir VIDE, sinon elle les surclasse pour toujours et éditer une case ne
    # fait plus rien — ne se transporte pas telle quelle : la boîte de collage de
    # l'assistant est dans un formulaire À PART. Ne pas « restaurer » ce test sur une
    # autre surface sans vérifier d'abord qu'elle partage vraiment son formulaire.


if __name__ == "__main__":
    unittest.main()
