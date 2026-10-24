"""Offline tests: dataset integrity and solver behaviour (no MCP calls)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mcd_swap import planner   # noqa: E402


class DatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.combos = planner.load()

    def test_combos_parsed(self):
        self.assertGreaterEqual(len(self.combos), 40)

    def test_every_option_has_nutrition(self):
        for c in self.combos:
            for opts in c.rounds:
                for o in opts:
                    self.assertIsNotNone(o.nut, o.name)

    def test_space_is_large(self):
        total = sum(max(1, __import__("math").prod(len(r) for r in c.rounds)) for c in self.combos)
        self.assertGreater(total, 1000)


class SolverTest(unittest.TestCase):
    def test_constraints_respected(self):
        args = planner.argparse.Namespace(kcal=500, protein=20, budget=30,
                                          objective="lean", top=3, check=False)
        rows = planner.search(args)[:5]
        self.assertTrue(rows)
        for r in rows:
            self.assertLessEqual(r["nut"]["kcal"], 500)
            self.assertGreaterEqual(r["nut"]["protein"], 20)
            self.assertLessEqual(r["price"], 30)


if __name__ == "__main__":
    unittest.main()
