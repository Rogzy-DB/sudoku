"""Public mode (SUDOKU_PUBLIC=1): friends, no accounts.

What it must hold: every browser sees ONLY its own games, the private-only
doors are closed, and a stranger cannot fill the disk or burn the CPU.

Every test runs against a temp data dir with the WHOLE store repointed, and
flips `store.PUBLIC` back off in tearDown so the rest of the suite never notices.

    SUDOKU_DIR=$(mktemp -d) SUDOKU_POOL_FILL=0 python3 -m unittest tests.test_public
"""

import http.client
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

os.environ["SUDOKU_POOL_FILL"] = "0"   # no background generator in tests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sudoku import store

import app

#: A position the engine produced itself: `generator.make(rng=random.Random(4))`
#: (v0.11.4), then its singles played forward up to the first elimination (a
#: pointing). Unique solution; grades « Diabolique » (a skyscraper further on).
GRID = ("23.89.154894...762.5124.893.8.91.5261297654385...82917"
        "9.2.7.385.15..8.79.78..9.41")
SID_A = "A" * 23 + "a"
SID_B = "B" * 23 + "b"


def _isolate(d):
    """⚠ Repoint EVERY path constant, not just DATA_DIR."""
    store.DATA_DIR = d
    store.GAMES_DIR = os.path.join(d, "games")
    store.POOL_DIR = os.path.join(d, "pool")
    store.ensure_dirs()


def _fill_pool(n=8):
    for g in range(4):
        for _ in range(n):
            store.pool_push({"puzzle": GRID, "grade": g, "label": f"G{g}",
                             "techniques": []})


class Public(unittest.TestCase):
    public = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _isolate(self.tmp.name)
        self._saved = (store.PUBLIC, store.MAX_VISITORS)
        store.PUBLIC = self.public
        _fill_pool()

    def tearDown(self):
        store.PUBLIC, store.MAX_VISITORS = self._saved
        store.bind_visitor(None)
        self.tmp.cleanup()

    def visitor_dirs(self):
        return sorted(os.listdir(store.GAMES_DIR))


class Served(Public):
    """A real socket — the same ThreadingHTTPServer the unit runs."""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.SudokuHandler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, sid=None, body=None, cookie=None, ctype=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        h = {}
        if cookie is not None:
            h["Cookie"] = cookie
        elif sid:
            h["Cookie"] = f"sdk={sid}"
        if body is not None:
            h["Content-Type"] = ctype or "application/x-www-form-urlencoded"
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        out = (r.status, r.headers, r.read().decode("utf-8", "replace"))
        c.close()
        return out

    def game_of(self, sid):
        code, h, _ = self.req("GET", "/", sid)
        self.assertEqual(code, 302)
        m = re.match(r"^g/([0-9a-f]+)/$", h["Location"] or "")
        self.assertTrue(m, h["Location"])
        return m.group(1)


class TestVisitorsAreIsolated(Served):
    def test_two_cookies_see_two_different_games_and_never_each_other(self):
        ga, gb = self.game_of(SID_A), self.game_of(SID_B)
        self.assertNotEqual(ga, gb)
        # each resumes its OWN game on the next visit
        self.assertEqual(self.game_of(SID_A), ga)
        self.assertEqual(self.game_of(SID_B), gb)
        # on disk, under its own drawer
        self.assertTrue(os.path.exists(os.path.join(store.GAMES_DIR, SID_A, f"{ga}.json")))
        self.assertTrue(os.path.exists(os.path.join(store.GAMES_DIR, SID_B, f"{gb}.json")))
        self.assertEqual(self.req("GET", f"/g/{ga}/", SID_A)[0], 200)

    def test_b_asking_for_a_game_of_a_gets_404_everywhere(self):
        ga = self.game_of(SID_A)
        self.game_of(SID_B)
        for path in (f"/g/{ga}/", f"/g/{ga}/hint?level=1", f"/g/{ga}/check",
                     f"/g/{ga}/audit", f"/g/{ga}/state"):
            code, h, _ = self.req("GET", path, SID_B)
            self.assertEqual(code, 404, path)
            self.assertIsNone(h["Location"], path)
        for path, body in ((f"/g/{ga}/state", json.dumps({"cells": GRID})),
                           (f"/g/{ga}/tick", ""), (f"/g/{ga}/apply-hint", "")):
            code, _, _ = self.req("POST", path, SID_B, body=body,
                                  ctype="application/json")
            self.assertEqual(code, 404, path)
        # and the assistant does not pre-fill from someone else's game
        _, _, mine = self.req("GET", "/assistant/", SID_B)
        _, _, theirs = self.req("GET", f"/assistant/?g={ga}", SID_B)
        self.assertEqual(mine, theirs)
        # A's game untouched by B's attempts
        store.bind_visitor(SID_A)
        self.assertEqual(store.load_game(ga)["hints"], [])

    def test_an_unknown_game_is_404_not_a_redirect(self):
        self.game_of(SID_A)
        code, h, _ = self.req("GET", "/g/0123456789/", SID_A)
        self.assertEqual((code, h["Location"]), (404, None))

    def test_a_traversal_game_id_in_the_assistant_query_is_ignored(self):
        self.game_of(SID_A)
        code, _, body = self.req("GET", "/assistant/?g=../" + SID_B + "/x", SID_A)
        self.assertEqual(code, 200)
        store.bind_visitor(SID_A)
        self.assertIsNone(store.load_game("../x"))
        self.assertIsNone(store.load_game("../../etc/passwd"))


class TestTheCookie(Served):
    FLAGS = ("HttpOnly", "Secure", "SameSite=Lax", "Path=/", "Max-Age=31536000")

    def _fresh(self, h):
        sc = h["Set-Cookie"]
        self.assertTrue(sc, "no Set-Cookie")
        m = re.match(r"^sdk=([^;]+);", sc)
        self.assertTrue(m, sc)
        self.assertTrue(store.RE_SID.match(m.group(1)), sc)
        for flag in self.FLAGS:
            self.assertIn(flag, sc)
        return m.group(1)

    def test_first_visit_gets_a_cookie_with_every_flag(self):
        code, h, _ = self.req("GET", "/techniques/")
        self.assertEqual(code, 200)
        self._fresh(h)

    def test_a_valid_cookie_is_not_reissued(self):
        _, h, _ = self.req("GET", "/techniques/", SID_A)
        self.assertIsNone(h["Set-Cookie"])

    def test_a_cookieless_root_creates_nothing_and_never_loops(self):
        code, h, _ = self.req("GET", "/")
        self.assertEqual(code, 302)
        self.assertEqual(h["Location"], "./?c=1")
        self._fresh(h)
        code, _, body = self.req("GET", "/?c=1")
        self.assertEqual(code, 200)
        self.assertIn("cookie", body)
        self.assertEqual(self.visitor_dirs(), [])
        # nor does a cookieless POST /new
        code, _, _ = self.req("POST", "/new", body="grade=3&back=")
        self.assertEqual(code, 403)
        self.assertEqual(self.visitor_dirs(), [])

    def test_a_tampered_cookie_is_ignored_and_replaced(self):
        bad = ["../x", "../../../../../../etc/pas", "." * 24, "A" * 25, "A" * 23,
               "AAAAAAAAAAAA/AAAAAAAAAAA", "AAAAAAAAAAAA%2FAAAAAAAAAA", "", "A" * 23 + " "]
        for v in bad:
            code, h, _ = self.req("GET", "/", cookie=f"sdk={v}")
            self.assertEqual(code, 302, v)
            new = self._fresh(h)
            self.assertNotEqual(new, v)
            self.assertEqual(h["Location"], "./?c=1", v)   # treated as ABSENT
        self.assertEqual(self.visitor_dirs(), [])
        # and with the real one, only regex-valid drawers ever appear
        self.game_of(SID_A)
        for d in self.visitor_dirs():
            self.assertTrue(store.RE_SID.match(d), d)

    def test_strict_parse(self):
        self.assertEqual(app.read_sid(f"x=1; sdk={SID_A}; y=2"), SID_A)
        self.assertIsNone(app.read_sid("sdk=../x"))
        self.assertIsNone(app.read_sid(None))
        self.assertIsNone(app.read_sid(f"sdk={SID_A}x"))


class TestThePublicSurface(Served):
    def test_private_only_doors_are_closed(self):
        self.assertEqual(self.req("POST", "/act", SID_A, body=json.dumps(
            {"action": "grade_puzzle", "payload": {"text": GRID}}),
            ctype="application/json")[0], 404)
        self.assertEqual(self.req("POST", "/import", SID_A,
                                  body=f"text={GRID}&back=")[0], 404)
        for path in ("/status.json", "/capabilities", "/import", "/import/"):
            self.assertEqual(self.req("GET", path, SID_A)[0], 404, path)
        self.assertEqual(self.req("GET", "/healthz")[0], 200)

    def test_rendered_pages_carry_only_the_credit(self):
        ga = self.game_of(SID_A)
        pages = {}
        for path in ("/techniques/", "/techniques/x_wing", "/entrainement/x_wing/1",
                     "/entrainement/x_wing/1?voir=1", "/assistant/", f"/g/{ga}/",
                     f"/assistant/?g={ga}", "/?c=1"):
            code, _, body = self.req("GET", path, SID_A if path != "/?c=1" else None)
            self.assertEqual(code, 200, path)
            pages[path] = body
        for path in (f"/g/{ga}/hint?level=3", f"/g/{ga}/check", f"/g/{ga}/audit"):
            pages[path] = self.req("GET", path, SID_A)[2]
        pages["POST /assistant"] = self.req("POST", "/assistant/", SID_A,
                                            body=f"cells={GRID}&op=analyse")[2]
        pages["empty pool"] = app.empty_pool_page()
        for path, body in pages.items():
            # « Rogzy &amp; Luna » is the credit — a NAME, never a link; nothing else.
            text = body.replace('href="/static/luna-ui.css"', "").replace("</a> &amp; Luna ·", "")
            self.assertNotIn("luna", text.lower(), path)
            self.assertNotIn('class="home"', text, path)
            self.assertNotIn("import", text, path)
        board = pages[f"/g/{ga}/"]
        self.assertIn('class="board"', board)
        self.assertIn('href="/static/luna-ui.css"', board)

    def test_the_stylesheet_is_served_here_and_only_here(self):
        code, h, css = self.req("GET", "/static/luna-ui.css")
        self.assertEqual(code, 200)
        self.assertTrue(h["Content-Type"].startswith("text/css"))
        self.assertIn("max-age", h["Cache-Control"])
        self.assertIn(".topbar", css)
        self.assertNotIn("/*", css)           # comments name internal paths
        self.assertIsNone(h["Set-Cookie"])


class TestAbuseLimits(Served):
    def test_a_body_over_16k_is_413(self):
        big = "cells=" + "1" * (17 * 1024)
        self.assertEqual(self.req("POST", "/assistant/", SID_A, body=big)[0], 413)
        self.assertEqual(self.req("POST", "/assistant/", SID_A,
                                  body=f"cells={GRID}")[0], 200)

    def test_per_visitor_cap_drops_the_oldest_finished_first(self):
        store.bind_visitor(SID_A)
        rec = {"puzzle": GRID, "grade": 3, "label": "x"}
        made = []
        for i in range(store.MAX_GAMES_PER_VISITOR):
            g = store.new_game(rec)
            g["created"] = 1000 + i
            g["done"] = i in (5, 9)
            store.save_game(g)
            made.append(g["id"])
        self.assertEqual(len(store.list_games(10**6)), 30)
        store.new_game(rec)
        ids = {g["id"] for g in store.list_games(10**6)}
        self.assertEqual(len(ids), 30)
        self.assertNotIn(made[5], ids)        # oldest FINISHED goes first
        self.assertIn(made[0], ids)
        store.new_game(rec)
        ids = {g["id"] for g in store.list_games(10**6)}
        self.assertNotIn(made[9], ids)
        self.assertIn(made[0], ids)
        store.new_game(rec)                   # no finished left → oldest
        ids = {g["id"] for g in store.list_games(10**6)}
        self.assertEqual(len(ids), 30)
        self.assertNotIn(made[0], ids)
        self.assertIn(made[1], ids)

    def test_over_the_visitor_cap_a_newcomer_gets_a_polite_page(self):
        self.game_of(SID_A)
        store.MAX_VISITORS = 1
        code, _, body = self.req("GET", "/", SID_B)
        self.assertEqual(code, 503)
        self.assertIn("complet", body)
        self.assertEqual(self.visitor_dirs(), [SID_A])
        code, _, _ = self.req("POST", "/new", SID_B, body="grade=2&back=")
        self.assertEqual(code, 503)
        # the existing visitor is unaffected, and pages still render for B
        self.assertEqual(self.req("POST", "/new", SID_A, body="grade=2&back=")[0], 303)
        self.assertEqual(self.req("GET", "/techniques/", SID_B)[0], 200)

    def test_idle_visitor_dirs_are_pruned_and_fresh_ones_kept(self):
        for sid in (SID_A, SID_B):
            store.bind_visitor(sid)
            store.new_game({"puzzle": GRID, "grade": 1, "label": "x"})
        store.bind_visitor(None)
        old = time.time() - 181 * 86400
        os.utime(os.path.join(store.GAMES_DIR, SID_A), (old, old))
        stray = os.path.join(store.GAMES_DIR, "not-a-visitor")
        os.makedirs(stray)
        os.utime(stray, (old, old))
        self.assertEqual(store.prune_visitors(), 1)
        self.assertEqual(self.visitor_dirs(), sorted([SID_B, "not-a-visitor"]))

    def test_the_prune_loop_cannot_crash(self):
        def boom(*a, **k):
            raise RuntimeError("disk on fire")
        orig, store.prune_visitors = store.prune_visitors, boom
        calls = []
        orig_sleep = time.sleep

        def stop(_s):
            calls.append(1)
            raise SystemExit
        try:
            store.time.sleep = stop
            with self.assertRaises(SystemExit):
                store.prune_loop()
        finally:
            store.prune_visitors = orig
            store.time.sleep = orig_sleep
        self.assertEqual(calls, [1])          # survived the error, reached the sleep

    def test_the_shared_pool_is_never_emptied_by_strangers(self):
        for _ in range(50):
            self.assertIsNotNone(store.pool_take(3))
        self.assertEqual(store.pool_counts()[3], store.PUBLIC_POOL_KEEP)

    def test_no_visitor_bound_fails_closed(self):
        store.bind_visitor(None)
        with self.assertRaises(RuntimeError):
            store.list_games()


class TestPrivateModeIsUntouched(Served):
    public = False

    def test_act_still_works_and_public_only_routes_do_not_exist(self):
        code, _, body = self.req("POST", "/act", body=json.dumps(
            {"action": "grade_puzzle", "payload": {"text": GRID}}),
            ctype="application/json")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(self.req("GET", "/static/luna-ui.css")[0], 404)
        code, h, _ = self.req("GET", "/")
        self.assertEqual(code, 302)
        self.assertIsNone(h["Set-Cookie"])
        self.assertTrue(h["Location"].startswith("g/"))

    def test_private_still_takes_a_large_body(self):
        big = "cells=" + "1" * (17 * 1024)
        self.assertEqual(self.req("POST", "/assistant/", body=big)[0], 200)


if __name__ == "__main__":
    unittest.main()


class TestFicheFootnoteRemoved(unittest.TestCase):
    """The 'Positions réelles…' note under the examples is gone —
    and the examples themselves are still served (pin BOTH directions)."""

    def test_note_gone_examples_still_there(self):
        import app
        html = app.fiche_page("x_wing")
        self.assertNotIn("Positions réelles", html)
        self.assertIn("Exemple 1", html)


class TestPublicCredits(unittest.TestCase):
    """Every public page credits its makers, links the code and
    rogzy.org, and states copyright + licence. Private pages keep their own footer."""

    def test_public_footer_has_credits(self):
        import app
        foot = app.PUBLIC_FOOT
        for must in ("Rogzy", "</a> &amp; Luna", "https://rogzy.org/", "https://github.com/", "©", "MIT"):
            self.assertIn(must, foot)

    def test_license_file_is_mit(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "LICENSE")) as f:
            self.assertIn("MIT License", f.read())
