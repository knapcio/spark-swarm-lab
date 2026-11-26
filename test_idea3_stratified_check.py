"""Idea #3 CPU distribution check: exact marginals, the control's power and the coupling's effect (small draws)."""
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import idea3_stratified_check as c  # noqa: E402


class StratifiedCheckTests(unittest.TestCase):
    def test_exact_marginal_and_control(self):
        p = [Fraction(1, 2), Fraction(1, 3), Fraction(1, 6)]
        for n in (2, 3, 4):
            for k in range(n):
                self.assertEqual(c.exact_marginal(p, n, k), p)
        self.assertNotEqual(c.fixed_strata_marginal(p, 3, 0), p)  # the wrong coupling is detected

    def test_exact_sequence_marginal(self):
        import random
        model = c.ToyModel(vocab=3, length=2, rng=random.Random(1))
        exact = c.exact_sequence_marginal(model, 3)
        self.assertTrue(all(exact[s] == model.prob(s) for s in exact))

    def test_run_small(self):
        r = c.run(draws=3000, seed=7)
        self.assertEqual(r['verdict'], 'marginals preserved exactly')
        effect = r['coupling_effect']['duplicate_first_token']
        self.assertLess(effect['coupled'], effect['independent'])
        spec = r['speculative_path']['duplicate_token']
        self.assertLess(spec['inverse_cdf_stratified'], spec['coupled_coins'])


if __name__ == '__main__':
    unittest.main()
