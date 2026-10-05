"""Geometry and parsing — the layer every other bug hides behind.

    python3 -m unittest discover tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sudoku import grid as G


class TestGeometry(unittest.TestCase):
    def test_every_cell_has_exactly_twenty_peers(self):
        self.assertTrue(all(len(p) == 20 for p in G.PEERS))

    def test_there_are_twenty_seven_units_of_nine(self):
        self.assertEqual(len(G.UNITS), 27)
        self.assertTrue(all(len(set(u)) == 9 for u in G.UNITS))

    def test_a_cell_is_never_its_own_peer(self):
        self.assertTrue(all(i not in G.PEERS[i] for i in range(81)))

    def test_names_round_trip_for_all_eighty_one_cells(self):
        # the ONE off-by-one that matters: 0-based index ↔ 1-based R#C#
        for i in range(81):
            self.assertEqual(G.parse_cell(G.name(i)), i)

    def test_the_corners_are_where_a_human_expects_them(self):
        self.assertEqual(G.name(0), "R1C1")
        self.assertEqual(G.name(80), "R9C9")
        self.assertEqual(G.parse_cell("R5C7"), 4 * 9 + 6)

    def test_common_peers_of_two_cells_excludes_the_two(self):
        a, b = G.parse_cell("R2C3"), G.parse_cell("R5C7")
        cp = G.common_peers([a, b])
        self.assertNotIn(a, cp)
        self.assertNotIn(b, cp)
        self.assertIn(G.parse_cell("R5C3"), cp)


class TestParsing(unittest.TestCase):
    #: generator output (see tests/test_engine.py GRID)
    LINE = "23.89.154894...762.5124.893.8.91.5261297654385...829179.2.7.385.15..8.79.78..9.41"

    def test_it_accepts_dots_zeroes_and_line_noise(self):
        a = G.parse(self.LINE)
        b = G.parse(self.LINE.replace(".", "0"))
        c = G.parse("\n".join(self.LINE[i:i + 9] for i in range(0, 81, 9)))
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_a_wrong_length_is_REFUSED_not_padded(self):
        # ⚠ silently padding 79 chars to 81 shifts every cell and yields a
        # plausible, wrong puzzle — the worst possible failure for this app
        with self.assertRaises(ValueError) as e:
            G.parse(self.LINE[:-2])
        self.assertIn("79", str(e.exception))
        with self.assertRaises(ValueError):
            G.parse(self.LINE + "5")

    def test_round_trip(self):
        self.assertEqual(G.to_string(G.parse(self.LINE)), self.LINE)


class TestCandidates(unittest.TestCase):
    def test_a_filled_cell_carries_its_OWN_digit_as_its_mask(self):
        # not 0 — "holds d" and "can hold d" must be the same test downstream,
        # or a solved cell silently drops out of a fish's base set
        cells = G.parse(TestParsing.LINE)
        cand = G.candidates(cells)
        for i in range(81):
            if cells[i]:
                self.assertEqual(cand[i], G.bit(cells[i]), G.name(i))

    def test_positions_counts_only_UNDECIDED_places(self):
        cells = G.parse(TestParsing.LINE)
        cand = G.candidates(cells)
        for u in range(27):
            for d in range(1, 10):
                for i in G.positions(cand, cells, u, d):
                    self.assertFalse(cells[i])

    def test_the_true_solution_is_always_among_the_candidates(self):
        from sudoku.solver import solution
        cells = G.parse(TestParsing.LINE)
        sol = solution(cells)
        cand = G.candidates(cells)
        for i in range(81):
            self.assertTrue(cand[i] & G.bit(sol[i]), G.name(i))


if __name__ == "__main__":
    unittest.main()
