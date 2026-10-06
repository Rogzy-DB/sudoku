"""The web surface: what it refuses, what it reaches, and what it must never leak.

Every test runs against a temp data dir — nothing here ever touches a real data dir.

    python3 -m unittest discover tests
"""

import json
import os
import re
import sys
import tempfile
import unittest
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

os.environ["SUDOKU_POOL_FILL"] = "0"   # no background generator in tests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sudoku import engine, examples, grid as G, store
from sudoku.solver import solution

import app

#: A position the engine produced itself: `generator.make(rng=random.Random(4))`
#: (v0.11.4), then its singles played forward up to the first elimination (a
#: pointing). Unique solution; grades « Diabolique » (a skyscraper further on).
GRID = ("23.89.154894...762.5124.893.8.91.5261297654385...82917"
        "9.2.7.385.15..8.79.78..9.41")


def _isolate(d):
    """⚠ Repoint EVERY path constant, not just DATA_DIR. A half-isolated store
    writes the game into the temp dir and the pool into the real one."""
    store.DATA_DIR = d
    store.GAMES_DIR = os.path.join(d, "games")
    store.POOL_DIR = os.path.join(d, "pool")
    store.ensure_dirs()


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _isolate(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestImportRefusesBadGrids(Isolated):
    def test_wrong_length(self):
        ok, why, _ = app.import_puzzle(GRID[:-3])
        self.assertFalse(ok)
        self.assertIn("81 cases", why)

    def test_a_digit_twice_in_a_unit(self):
        bad = GRID[0] * 2 + GRID[2:]   # the first digit twice in row 1
        ok, why, _ = app.import_puzzle(bad)
        self.assertFalse(ok)
        self.assertIn("double", why)

    def test_a_grid_with_several_solutions_is_refused_UP_FRONT(self):
        # ⚠ the whole point: nothing is worse than two hours on a grid that
        # never had one answer
        ok, why, _ = app.import_puzzle("." * 81)
        self.assertFalse(ok)
        self.assertIn("plusieurs solutions", why)

    def test_a_good_grid_is_accepted_and_graded(self):
        ok, why, game = app.import_puzzle(GRID)
        self.assertTrue(ok, why)
        self.assertEqual(game["label"], "Diabolique")   # chaîne : voir test_engine
        self.assertEqual(game["cells"], GRID)


class TestTheExerciseChipsFillTheirRows(Isolated):
    """Rogzy 2026-09-29: *« idem sur le spacing du bouton et les 20 choix ici, et en
    desktop ça rend mal »*.

    ⚠ En `flex-wrap`, 20 pastilles tombaient 6/6/6/2 à 390 px et **16/4** à 1440 :
    une dernière rangée orpheline, différente à chaque largeur. 5 puis 10 colonnes
    divisent 20 exactement. C'est le NOMBRE d'exercices qui choisit la grille.

    ⚠ Verrou de style : la suite ne calcule pas de mise en page. Il empêche le retour
    du `flex-wrap`, il ne prouve pas le rendu — ça, c'est la capture."""

    def test_the_chips_are_a_grid_that_divides_twenty(self):
        html = app.fiche_page("x_wing")
        self.assertIn(".exos { display:grid; grid-template-columns:repeat(5,1fr);", html)
        self.assertIn("@media (min-width:640px){ .exos { grid-template-columns:repeat(10,1fr); } }",
                      html)
        self.assertNotIn(".exos { display:flex", html)

    def test_the_chips_are_spaced_off_the_start_button(self):
        self.assertIn("margin-top:var(--sp-4); }", app.fiche_page("x_wing"))

    def test_there_really_are_twenty_of_them_to_lay_out(self):
        """La mise en page 5×10 n'a de sens que si le compte est bien 20 : si un jour
        le moissonneur en livre 18, cette grille remet une rangée orpheline."""
        self.assertEqual(app.drill_count("x_wing"), 20)


class TestTheBoardHeaderHasNoClock(Isolated):
    """Rogzy 2026-09-29: *« what is the 10:00 ? is it a back timer ? remove this »*.

    ⚠ Sa question EST le diagnostic : ce n'était pas un compte à rebours mais le temps
    écoulé, rendu **une fois au chargement** — un cadran figé qu'on lit comme vivant.
    Les deux sens sont épinglés : plus d'horloge sur une partie en cours, mais le temps
    final reste sur une partie terminée (c'est un résultat, pas un cadran)."""

    def _game(self, seconds, done=False):
        _ok, _why, g = app.import_puzzle(GRID)
        g["seconds"], g["done"] = seconds, done
        store.save_game(g)
        return g

    def test_a_live_game_shows_no_elapsed_time(self):
        html = app.board_page(self._game(600))
        self.assertNotIn("10:00", html)
        self.assertIn("indice(s)", html)          # le reste de l'en-tête est là

    def test_a_finished_game_still_says_how_long_it_took(self):
        html = app.board_page(self._game(600, done=True))
        self.assertIn("10:00", html)
        self.assertIn("bouclée", html)

    def test_the_header_is_spaced_off_the_board(self):
        """Verrou de style : l'en-tête est un `div` nu, rien ne lui donne d'air."""
        html = app.board_page(self._game(0))
        self.assertIn('class="spread gamehd"', html)
        self.assertIn(".gamehd { margin-bottom:", html)


class TestTheJudgeIsGone(Isolated):
    """Le juge ne servait plus. La prémisse du juge — « un autre solveur t'a
    servi un indice » — a disparu le jour où cette app est née.

    ⚠ Les DEUX moitiés, parce qu'une suppression ratée ressemble exactement à une
    suppression réussie : la porte doit être fermée **et** la capacité doit survivre.
    `engine.verify_claim` reste joignable par `/act`, c'est par là qu'un agent peut
    encore faire juger une réclamation."""

    def test_no_tab_no_page_no_route(self):
        self.assertNotIn("verify", [t[2] for t in app.TABS])
        self.assertFalse(hasattr(app, "verify_page"))
        self.assertFalse(app.route_exists("/verify", "GET"))
        self.assertFalse(app.route_exists("/verify", "POST"))
        _ok, _why, game = app.import_puzzle(GRID)
        self.assertNotIn("../../verify/", app.board_page(game))

    def test_the_helper_that_only_it_used_went_with_it(self):
        """Une page supprimée qui laisse ses helpers derrière n'est pas supprimée,
        elle est cachée — et du code mort ressemble à du code."""
        self.assertFalse(hasattr(app, "_md"))

    def test_but_the_engine_can_still_judge_a_claim_through_act(self):
        r = app.do_act({"action": "verify_claim",
                        "payload": {"grid": GRID, "text": "naked single R1C1 = 5"}})
        self.assertTrue(r.get("ok"), r)
        self.assertIn("verdict", r)


class TestJouerOpensOnABoard(Isolated):
    """Rogzy 2026-09-29: *« jouer on voit une grille très difficile par défaut, avec
    les 4 options, importé, facile, moyen »*, après *« assemble jouer et importé »*.

    Trois revendications, et il faut les trois, parce que chacune casse seule :
    l'onglet ouvre un plateau, il REPREND la partie en cours au lieu d'en empiler
    une à chaque visite, et le choix (réservoir + grille tapée) est sur ce plateau.
    """

    def _pool(self, grade, n=1):
        rec = {"puzzle": GRID, "grade": grade,
               "label": engine.GRADE_LABELS[grade], "techniques": []}
        for _ in range(n):
            store.pool_push(rec)

    def test_it_reuses_the_unfinished_game_instead_of_stacking_a_new_one(self):
        """⚠ La moitié qui compte. Sans ça, chaque rechargement de l'onglet crée une
        partie — un compteur qui monte tout seul — et il perd celle d'avant à chaque
        fois. C'est AUSSI le chemin de reprise : la v0.7.0 a retiré la liste des
        parties traînantes, pas les parties."""
        self._pool(3, 3)
        first = app.current_game()
        self.assertIsNotNone(first)
        for _ in range(3):
            self.assertEqual(app.current_game()["id"], first["id"])
        self.assertEqual(len(store.list_games(40)), 1)

    def test_a_cold_start_serves_the_hardest_grid_the_pool_has(self):
        self._pool(3)
        self._pool(0)
        self.assertEqual(app.current_game()["grade"], 3)

    def test_it_falls_back_down_the_grades_rather_than_serving_nothing(self):
        self._pool(1)
        self.assertEqual(app.current_game()["grade"], 1)

    def test_an_empty_pool_gets_a_page_and_not_a_redirect_into_the_void(self):
        self.assertIsNone(app.current_game())
        html = app.empty_pool_page()
        self.assertIn("Nouvelle grille", html)
        self.assertEqual(html.count('name="grade"'), 4)

    def test_the_board_carries_the_choice_that_used_to_be_a_tab(self):
        """Les quatre difficultés ET la grille tapée, sur le plateau — et l'onglet
        Importer disparu de la barre."""
        _ok, _why, game = app.import_puzzle(GRID)
        html = app.board_page(game)
        self.assertIn("Changer de grille", html)
        self.assertEqual(html.count('name="grade"'), 4)
        self.assertIn('action="../../import"', html)
        self.assertNotIn("📥 Importer", html, "the Importer tab is back")
        self.assertNotIn("import", [t[2] for t in app.TABS])

    def test_the_board_keyboard_lets_go_of_the_typed_grid(self):
        """⚠ Depuis que la saisie d'une grille vit SOUS le plateau, le `keydown`
        global du plateau et les cases de saisie se disputent chaque frappe : taper
        un 7 dans une case le POSAIT sur la partie en cours, et le `preventDefault`
        empêchait la case de le recevoir. Deux bugs d'une seule ligne manquante.

        ⚠ **C'est un verrou de chaîne de caractères, pas un test de comportement** :
        la suite est en Python et n'exécute pas ce JS. Il ne prouve pas que ça marche,
        il empêche le garde de disparaître sans que personne ne le remarque — seul un
        vrai navigateur prouverait le reste."""
        self.assertIn("e.target.tagName === 'INPUT'", app.BOARD_JS)
        self.assertIn("e.target.tagName === 'TEXTAREA'", app.BOARD_JS)

    def test_the_board_links_to_the_assistant_on_this_very_grid(self):
        """*« si je suis bloqué faudra bien me débloquer avec l'assistant »*. Un lien
        nu vers l'assistant lui redemanderait de retaper les 81 cases."""
        _ok, _why, game = app.import_puzzle(GRID)
        self.assertIn(f'href="../../assistant/?g={game["id"]}"', app.board_page(game))


class TestTheBoardNeverLeaksTheAnswer(Isolated):
    def test_the_solution_string_is_nowhere_in_the_page(self):
        """The one thing that would make the whole app pointless."""
        _ok, _why, game = app.import_puzzle(GRID)
        html = app.board_page(game)
        sol = G.to_string(solution(G.parse(GRID)))
        self.assertNotIn(sol, html)
        for n in range(9, 30):          # nor any long run of it
            self.assertNotIn(sol[:n] if n <= 81 else sol, html)

    def test_the_page_carries_the_board_the_pad_and_the_state(self):
        _ok, _why, game = app.import_puzzle(GRID)
        html = app.board_page(game)
        self.assertEqual(html.count('class="cell"'), 81)
        self.assertIn('id="state"', html)
        self.assertIn('onclick="put(1)"', html)
        self.assertIn('id="rungs"', html)

    def test_where_did_i_go_wrong_gives_the_place_not_the_digit(self):
        _ok, _why, game = app.import_puzzle(GRID)
        sol = solution(G.parse(GRID))
        i = next(k for k in range(81) if not G.parse(GRID)[k])
        wrong = next(d for d in range(1, 10) if d != sol[i])
        cells = G.parse(GRID)
        cells[i] = wrong
        game["cells"] = G.to_string(cells)
        r = app.check_payload(game)
        self.assertEqual(r["cell"], i)
        self.assertIn(G.name(i), r["message"])
        self.assertNotIn(f"= {sol[i]}", r["message"])


class TestTheHintLadder(Isolated):
    def setUp(self):
        super().setUp()
        _ok, _why, self.game = app.import_puzzle(GRID)

    def test_each_rung_reveals_exactly_one_more_thing(self):
        for level in (1, 2, 3, 4):
            p = app.hint_payload(self.game, level)
            self.assertEqual(len(p["rungs"]), level)

    def test_rung_one_names_a_place_and_NOT_the_technique(self):
        p = app.hint_payload(self.game, 1)
        self.assertIn("Il y a quelque chose dans", p["rungs"][0][1])
        self.assertIsNone(p["show"])
        body = " ".join(r[1] for r in p["rungs"])
        self.assertNotIn(p["technique"], body)

    def test_the_cells_only_light_up_from_rung_three(self):
        self.assertIsNone(app.hint_payload(self.game, 2)["show"])
        self.assertTrue(app.hint_payload(self.game, 3)["show"]["cells"])

    def test_only_the_last_rung_can_be_applied(self):
        self.assertFalse(app.hint_payload(self.game, 3)["can_apply"])
        self.assertTrue(app.hint_payload(self.game, 4)["can_apply"])

    def test_applying_a_hint_advances_the_position(self):
        before = self.game["cells"], list(self.game["elims"])
        r = app.apply_hint(self.game)
        self.assertTrue(r["ok"])
        self.assertNotEqual((self.game["cells"], self.game["elims"]), before)

    def test_when_it_cannot_see_a_step_it_SAYS_so(self):
        # ⚠ never a guess dressed as a hint
        self.game["cells"] = "." * 81
        p = app.hint_payload(self.game, 4)
        self.assertTrue(p.get("none"))
        self.assertIn("je préfère te le dire", p["message"].lower())


class TestStateIsNotTheClientsToDictate(Isolated):
    def test_a_given_cannot_be_overwritten_by_the_browser(self):
        _ok, _why, game = app.import_puzzle(GRID)
        tampered = list("9" * 81)
        app.save_state(game, {"cells": "".join(tampered)})
        givens = G.parse(GRID)
        got = G.parse(game["cells"])
        for i in range(81):
            if givens[i]:
                self.assertEqual(got[i], givens[i], G.name(i))

    def test_the_move_journal_is_written_by_diffing_not_by_trusting(self):
        _ok, _why, game = app.import_puzzle(GRID)
        i = next(k for k in range(81) if not G.parse(GRID)[k])
        cells = G.parse(GRID)
        cells[i] = 4
        app.save_state(game, {"cells": G.to_string(cells), "moves": ["nonsense"]})
        self.assertEqual(len(game["moves"]), 1)
        self.assertEqual(game["moves"][0]["i"], i)
        self.assertEqual(game["moves"][0]["to"], 4)


class TestTheHeader(Isolated):
    """Rogzy 2026-09-15: *"first move the app into tabs, right now it's confusing
    how it navigate. hamronize the header to othe rapp"*.

    So the claim under test is not "there are tabs" but "the header does not
    MOVE": the same bar, the same four destinations, the same `‹ Home` on the
    left, on every page of the app — including the deep ones that used to swap in
    a second-level header of their own and strand you."""

    def _pages(self):
        _ok, _why, game = app.import_puzzle(GRID)
        return [("/", app.empty_pool_page()),
                ("/assistant/", app.assistant_page()),
                # ⚠ servie SANS slash, et seulement en réponse à un POST refusé
                ("/import", app.import_refused_page()),
                ("/techniques/", app.techniques_page()),
                ("/techniques/x_wing", app.fiche_page("x_wing")),
                ("/entrainement/x_wing/1", app.drill_page("x_wing", 1)),
                (f"/g/{game['id']}/", app.board_page(game))]

    def test_every_page_carries_the_same_four_tabs(self):
        for base, html in self._pages():
            labels = re.findall(r'class="tab[^"]*"[^>]*>([^<]+)</a>', html)
            self.assertEqual([t[1] for t in app.TABS], labels, base)

    def test_exactly_one_tab_is_active_on_every_page(self):
        for base, html in self._pages():
            self.assertEqual(html.count('class="tab active"'), 1, base)

    def test_no_page_carries_a_second_level_back_link(self):
        """One home control, and it always says the same thing."""
        for base, html in self._pages():
            backs = re.findall(r'class="back" href="([^"]*)">([^<]*)</a>', html)
            self.assertEqual(backs, [("/", "‹ Home")], base)
            # the chip lives INSIDE the topbar; the footer has its own `.home`
            # link on every page and is not what this is about
            bar = html.split("</header>")[0]
            self.assertNotIn('class="home"', bar, base)

    def test_every_tab_resolves_from_the_url_its_page_is_served_at(self):
        """A tab strip is the one thing that must work from EVERY page, so a
        wrong `base` is a nav that 404s from exactly one of them."""
        for base, html in self._pages():
            hrefs = re.findall(r'class="tab[^"]*" href="([^"]*)"', html)
            self.assertEqual(len(hrefs), len(app.TABS), base)
            for href in hrefs:
                path = urllib.parse.urlparse(urllib.parse.urljoin(
                    "http://localhost/sudoku" + base, href)).path
                inner = path[len("/sudoku"):] or "/"
                self.assertTrue(app.route_exists(inner),
                                f"{base} → {href} lands on {inner}")

    def test_the_jouer_tab_really_lands_on_the_home_page(self):
        """Resolving to *a* route is not enough: `../` from a game page and `./`
        from the root must both be the app root, not `/g/` and not the page
        itself."""
        _ok, _why, game = app.import_puzzle(GRID)
        for base, html in (("/", app.empty_pool_page()),
                           (f"/g/{game['id']}/", app.board_page(game)),
                           ("/entrainement/x_wing/1",
                            app.drill_page("x_wing", 1))):
            href = re.search(r'class="tab active" href="([^"]*)"', html)
            if base != "/":
                href = re.search(r'class="tab" href="([^"]*)"', html)
            target = urllib.parse.urljoin("http://localhost/sudoku" + base,
                                          re.findall(r'class="tab[^"]*" href="([^"]*)"',
                                                     html)[0])
            self.assertEqual(urllib.parse.urlparse(target).path, "/sudoku/",
                             base)


class TestRoutes(Isolated):
    """⚠ Rendering a page and being able to REACH it are different claims.
    Resolve every href and form action against the URL the page is really served
    at, and assert each one is a route this app answers."""

    #: ⚠ The URL each page is really SERVED at, which is not the URL it is
    #: linked from. A fiche and a drill have NO trailing slash, so `../` there
    #: means one level higher than it does on `/techniques/` — the bug that hid
    #: for a day behind a test that joined against `/techniques/` instead.
    PAGES = [("/", lambda: app.empty_pool_page()),
             ("/assistant/", lambda: app.assistant_page()),
             ("/import", lambda: app.import_refused_page()),
             ("/techniques/", lambda: app.techniques_page()),
             ("/techniques/x_wing", lambda: app.fiche_page("x_wing")),
             ("/entrainement/x_wing/1", lambda: app.drill_page("x_wing", 1)),
             ("/entrainement/x_wing/2",
              lambda: app.drill_page("x_wing", 2, True))]

    def _links(self, html):
        out = []
        for m in re.finditer(r'(?:href|action)="([^"]*)"', html):
            out.append(("GET" if m.group(0).startswith("href") else "POST",
                        m.group(1)))
        return out

    def test_every_link_on_every_page_resolves_to_a_real_route(self):
        pages = list(self.PAGES)
        _ok, _why, game = app.import_puzzle(GRID)
        pages.append((f"/g/{game['id']}/", lambda: app.board_page(game)))
        for base, render in pages:
            for method, href in self._links(render()):
                if href.startswith(("http", "mailto:", "#")) or not href:
                    continue
                target = urllib.parse.urljoin("http://localhost/sudoku" + base, href)
                path = urllib.parse.urlparse(target).path
                if not path.startswith("/sudoku"):
                    continue     # outside the app: home, the shared stylesheet
                inner = path[len("/sudoku"):] or "/"
                self.assertTrue(app.route_exists(inner, method),
                                f"{base} → {href} lands on {inner} ({method})")

    def test_every_page_has_exactly_one_spelling(self):
        """Two families, opposite needs, one rule. A page whose links point at its
        own siblings must be served WITH a trailing slash; one whose links point
        up must be served WITHOUT. Answering both spellings means answering one of
        them with a nav strip a level off — and `/sudoku/verify` did: `../` there
        eats the `/sudoku` prefix, so every tab pointed clean out of the app."""
        for served, want in (
                ("/assistant", "assistant/"),
                ("/techniques", "techniques/"),
                ("/g/abc123", "abc123/"),
                ("/techniques/x_wing/", "../x_wing"),
                ("/entrainement/x_wing/3/", "../3")):
            self.assertEqual(app.canonical(served), want, served)
        for fine in ("/", "/assistant/", "/import", "/techniques/",
                     "/g/abc123/", "/techniques/x_wing", "/entrainement/x_wing/3",
                     "/status.json", "/healthz", "/capabilities",
                     "/g/abc123/state", "/g/abc123/hint"):
            self.assertEqual(app.canonical(fine), "", fine)

    def test_the_redirect_lands_on_the_page_and_nowhere_else(self):
        """Each one goes to its OWN canonical spelling — slash added for the pages
        that link sideways, removed for the ones that link up — and lands on the
        page itself, not one level inside it."""
        for served, canon in (("/assistant", "/sudoku/assistant/"),
                              ("/techniques", "/sudoku/techniques/"),
                              ("/g/abc123", "/sudoku/g/abc123/"),
                              ("/techniques/x_wing/", "/sudoku/techniques/x_wing"),
                              ("/entrainement/x_wing/3/",
                               "/sudoku/entrainement/x_wing/3")):
            target = urllib.parse.urlparse(urllib.parse.urljoin(
                "http://localhost/sudoku" + served, app.canonical(served))).path
            self.assertEqual(target, canon, served)
            self.assertEqual(app.canonical(target[len("/sudoku"):]), "",
                             f"{served} redirects to something that redirects")

    def test_a_form_sends_him_to_the_game_not_inside_the_page_he_posted_from(self):
        """Le MÊME endpoint est posté depuis deux pages, donc aucune constante ne
        peut être juste pour les deux : la page porte son propre `back` et
        `game_url` s'en sert. Chaque base doit résoudre sur la partie.

        ⚠ Et `back` vient du client : une valeur hors liste blanche ne doit PAS
        sortir de l'app — c'est une redirection ouverte, pas un détail."""
        for base, back in (("http://localhost/sudoku/g/old123/", "../../"),
                           ("http://localhost/sudoku/import", "")):
            path = urllib.parse.urlparse(
                urllib.parse.urljoin(base, app.game_url(back, "abc123"))).path
            self.assertEqual(path, "/sudoku/g/abc123/", base)
            self.assertTrue(app.route_exists(path[len("/sudoku"):]), base)

    def test_a_back_the_client_invented_cannot_steer_the_redirect(self):
        for evil in ("../../../../", "//evil.example.com/", "https://evil/", "x"):
            self.assertEqual(app.game_url(evil, "abc123"), "g/abc123/", evil)

    def test_a_tab_from_the_slashless_spelling_would_have_left_the_app(self):
        """The measurement that found it: this is what the old behaviour did, and
        it is why the redirect is not cosmetic."""
        escaped = urllib.parse.urljoin("http://localhost/sudoku/assistant", "../techniques/")
        self.assertEqual(escaped, "http://localhost/techniques/")
        fixed = urllib.parse.urljoin("http://localhost/sudoku/assistant/", "../techniques/")
        self.assertEqual(fixed, "http://localhost/sudoku/techniques/")

    def test_the_back_link_on_a_fiche_goes_to_the_fiche_index(self):
        """It used to read "‹ Les techniques" and land on the home page: at
        `/techniques/x_wing` the base directory is `/techniques/`, so `../` is
        `/`. A back link that lies about where it goes is worse than none."""
        html = app.fiche_page("x_wing")
        tabs = re.findall(r'class="tab[^"]*" href="([^"]*)"', html)
        self.assertIn("../techniques/", tabs)
        self.assertEqual(
            urllib.parse.urljoin("http://localhost/sudoku/techniques/x_wing",
                                 "../techniques/").replace("http://localhost", ""),
            "/sudoku/techniques/")

    def test_the_relative_links_from_a_game_page_do_not_nest(self):
        # the classic: "../../assistant/" from /g/<id>/ must reach /assistant/,
        # not /g/assistant/ — the bug every prefixed app ships once
        _ok, _why, game = app.import_puzzle(GRID)
        html = app.board_page(game)
        self.assertIn('href="../../assistant/', html)
        t = urllib.parse.urljoin(f"http://localhost/sudoku/g/{game['id']}/",
                                 "../../assistant/")
        self.assertEqual(urllib.parse.urlparse(t).path, "/sudoku/assistant/")

    def test_status_json_has_the_contract_shape(self):
        s = app.status_json()
        self.assertIn("summary", s)
        self.assertIsInstance(s["rev"], int)

    def test_unknown_paths_are_refused_before_dispatch(self):
        self.assertFalse(app.route_exists("/g/zzzz/", "GET"))
        # ⚠ v0.8.0 : `/import` est un POST SEUL — son formulaire vit sous le
        # plateau. Une page qu'on ne peut plus visiter doit aussi cesser d'être
        # une route GET, sinon elle reste joignable et la nav ment.
        self.assertFalse(app.route_exists("/import", "GET"))
        self.assertTrue(app.route_exists("/import", "POST"))


class TestAct(Isolated):
    def test_the_payload_goes_under_payload(self):
        r = app.do_act({"action": "grade_puzzle", "payload": {"text": GRID}})
        self.assertTrue(r["ok"])
        self.assertEqual(r["label"], "Diabolique")      # chaîne : voir test_engine
        self.assertTrue(r["unique"])

    def test_an_unknown_action_is_named_back(self):
        r = app.do_act({"action": "frobnicate", "payload": {}})
        self.assertFalse(r["ok"])
        self.assertIn("frobnicate", r["error"])


if __name__ == "__main__":
    unittest.main()


class TestItIsActuallyServed(Isolated):
    """⚠ A page function that renders and a route that exists are TWO claims; a
    third is that the dispatcher joins them. A mutation proved the gap: deleting
    the two lines of `do_GET` that answer `/import` left every other test green —
    `import_page()` still rendered, `route_exists("/import")` was still true, and
    the tab was a 404.

    So this one talks to a real socket, the same `ThreadingHTTPServer` the unit
    runs, and asks for every page the way a browser does — trailing slashes,
    redirects and all. It is the only test here that would notice a route wired
    to nothing.
    """

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.SudokuHandler)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path, redirect=True):
        url = f"http://127.0.0.1:{self.port}{path}"
        opener = urllib.request.build_opener(
            *([] if redirect else [_NoRedirect()]))
        try:
            r = opener.open(url, timeout=10)
            return r.status, r.read().decode("utf-8"), r.headers.get("Location")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e.headers.get("Location")

    PAGES = ["/", "/techniques/", "/techniques/x_wing",
             "/entrainement/x_wing/1", "/entrainement/x_wing/1?voir=1",
             "/assistant/"]

    def test_every_page_answers_200_and_carries_the_tab_strip(self):
        for path in self.PAGES:
            code, body, _ = self.get(path)
            self.assertEqual(code, 200, path)
            self.assertIn('class="tabs"', body, path)
            for _href, label, _key in app.TABS:
                self.assertIn(label, body, f"{path} is missing tab {label}")

    def test_the_other_spelling_redirects_instead_of_rendering(self):
        for path, to in (("/assistant", "assistant/"),
                         ("/techniques", "techniques/"),
                         ("/techniques/x_wing/", "../x_wing"),
                         ("/entrainement/x_wing/3/", "../3")):
            code, _body, loc = self.get(path, redirect=False)
            self.assertEqual(code, 302, path)
            self.assertEqual(loc, to, path)

    def test_following_the_redirect_arrives_at_a_real_page(self):
        for path in ("/assistant", "/techniques", "/techniques/x_wing/",
                     "/entrainement/x_wing/3/"):
            code, body, _ = self.get(path)
            self.assertEqual(code, 200, path)
            self.assertIn('class="tabs"', body, path)

    def post(self, path, fields, redirect=False):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=data, method="POST")
        opener = urllib.request.build_opener(
            *([] if redirect else [_NoRedirect()]))
        try:
            r = opener.open(req, timeout=10)
            return r.status, r.read().decode("utf-8"), r.headers.get("Location")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e.headers.get("Location")

    def test_the_jouer_tab_really_redirects_onto_a_board(self):
        """⚠ `current_game()` peut être parfait et le répartiteur ne pas l'appeler.
        On parle donc à une vraie socket : `/` doit répondre 302 vers une partie,
        et cette partie doit servir un plateau."""
        rec = {"puzzle": GRID, "grade": 3, "label": "Diabolique", "techniques": []}
        store.pool_push(rec)
        code, _body, loc = self.get("/", redirect=False)
        self.assertEqual(code, 302)
        target = urllib.parse.urlparse(urllib.parse.urljoin(
            f"http://127.0.0.1:{self.port}/", loc)).path
        self.assertRegex(target, r"^/g/[0-9a-f]+/$", f"{loc} → {target}")
        code, body, _ = self.get(target)
        self.assertEqual(code, 200)
        self.assertIn('id="board"', body)
        self.assertIn("Changer de grille", body)

    def test_the_assistant_opens_prefilled_from_a_game(self):
        """Le lien du plateau porte `?g=<id>` : l'assistant doit arriver AVEC la
        position, pas avec un plateau vide à retaper."""
        _ok, _why, game = app.import_puzzle(GRID)
        code, body, _ = self.get(f"/assistant/?g={game['id']}")
        self.assertEqual(code, 200)
        self.assertIn('name="cells"', body)
        self.assertIn(game["cells"], body)
        self.assertNotIn("Ta grille", body, "it fell back to the empty page")
        # Rogzy 06/10 : la position vient de SA partie — ✏️ Corriger n'a rien à
        # rattraper, et `played` doit voyager pour que 👁 Montrer ne la ramène pas
        self.assertNotIn('<details class="fix"', body)
        self.assertIn('name="played" value="1"', body)

    def test_a_typed_grid_posted_to_the_import_tab_opens_the_game(self):
        """The whole reason the redirect target had to change. Posted from
        `/import/`, so a bare `g/<id>/` would have landed on `/import/g/<id>/` —
        a 404 after a successful import, which is the worst place to put one."""
        fields = {f"c{i}": (GRID[i] if GRID[i] != "." else "")
                  for i in range(81)}
        fields["back"] = "../../"          # comme le formulaire sous le plateau
        # le formulaire vit sous le plateau : action `../../import` depuis
        # `/g/<id>/`, donc le serveur reçoit `/import` et le navigateur résout la
        # Location contre `/g/<id>/`. Le test fait les deux moitiés.
        code, _body, loc = self.post("/import", fields)
        self.assertEqual(code, 303)
        target = urllib.parse.urlparse(urllib.parse.urljoin(
            f"http://127.0.0.1:{self.port}/g/old123/", loc)).path
        self.assertRegex(target, r"^/g/[0-9a-f]+/$", f"{loc} → {target}")
        code, body, _ = self.get(target)
        self.assertEqual(code, 200, target)
        self.assertIn('id="board"', body)

    def test_playing_a_step_answers_with_the_NEW_position_and_no_banner(self):
        """Rogzy 2026-09-17: *« no need for the "pas jouer, voila ce qui reste"
        quand on joue un coup »*. The banner is gone — and the thing it was
        narrating must still be true without it, which is the half worth pinning:
        the answer carries the position AFTER the move, not a sentence about it.

        ⚠ Asserted over a real POST, because the banner lived in the dispatcher
        (`do_POST` passed `flash=`), not in `assistant_page` — a unit test on the
        page function never saw it and would not see it come back either."""
        grid = examples.EXAMPLES["hidden_single"][0]
        cells = G.parse(grid)
        steps = list(engine.all_steps(cells))
        i = next(n for n, st in enumerate(steps) if st["placements"])
        cell, digit = steps[i]["placements"][0]

        code, body, _ = self.post(
            "/assistant/", {"cells": grid, "elims": "", "pick": str(i),
                            "op": "apply"}, redirect=True)
        self.assertEqual(code, 200)
        for banner in ("Pas joué", "Voilà ce qui reste"):
            self.assertNotIn(banner, body, "the played-a-move banner is back")
        # the move really landed: the grid the page now carries holds the digit
        posted = re.search(r'name="cells" value="([.0-9]{81})"', body)
        self.assertIsNotNone(posted, "the page lost the position it just played")
        self.assertEqual(posted.group(1)[cell], str(digit))

    def test_the_empty_assistant_is_the_tool_and_nothing_else(self):
        """Rogzy 2026-09-29: *« just remove the small teste and the a quoi ca sert.
        i know how ot use. we keep ta grlle and the proper tool »*. Both halves are
        pinned here, because deleting prose is exactly the change a later « the page
        should explain itself » puts back: the onboarding copy is gone, AND the
        thing it was describing — 81 real boxes and the button that analyses them
        — is still served."""
        code, body, _ = self.get("/assistant/")
        self.assertEqual(code, 200)
        for prose in ("\u00c0 quoi \u00e7a sert", "Tape les chiffres",
                      "L'assistant ne finit pas ta grille"):
            self.assertNotIn(prose, body, f"onboarding prose is back: {prose}")
        self.assertIn("\U0001f91d Ta grille", body)
        # ⚠ prefix, not the exact class: the 3×9 wall rows carry `r3`/`r6` too,
        # so an `== 'cell ent'` count reads 63 and looks like a broken board.
        self.assertEqual(body.count('class="cell ent'), 81,
                         "the grid he types into is gone")
        self.assertIn('value="analyse"', body)

    def test_a_refused_import_comes_back_with_the_digits_still_in_the_boxes(self):
        """A dead-end « Import refusé » page throws away 81 keystrokes over one
        of them."""
        fields = {f"c{i}": "" for i in range(81)}
        fields["c0"] = fields["c1"] = "5"          # two 5s in row 1
        code, body, loc = self.post("/import/", fields)
        self.assertEqual(code, 200, loc)
        self.assertIn("double", body)
        self.assertIn('name="c0" type="text"', body)
        self.assertIn('value="5"', body)
        self.assertIn('class="tab active"', body)

    def test_what_is_not_a_route_is_a_404_and_not_a_page(self):
        for path in ("/entrainement/x_wing/0", "/entrainement/x_wing/999",
                     "/techniques/xyzzy", "/nope", "/import/nope"):
            code, _body, _ = self.get(path)
            self.assertEqual(code, 404, path)

    def test_a_dead_url_is_REFUSED_not_redirected_to_another_dead_url(self):
        """This is the one thing the `route_exists` gate at the top of `do_GET`
        does that nothing downstream does. Every dead path 404s eventually — but
        `canonical()` runs before the page is built, so without that gate the
        slashed spelling of a dead URL would earn a 302 to a 404: two round trips
        to say no, and a Location header pointing at nothing. A mutation caught
        the gate doing nothing until this existed."""
        for path in ("/entrainement/x_wing/0/", "/entrainement/x_wing/999/",
                     "/techniques/xyzzy/"):
            code, _body, loc = self.get(path, redirect=False)
            self.assertEqual(code, 404, f"{path} → {loc}")
            self.assertIsNone(loc, path)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None
