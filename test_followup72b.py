"""Authored fixtures only; no model calls."""
from fractions import Fraction as F
import unittest
import followup72 as f
import followup72b as b
from test_followup72 import FakeClient, engine

STATE = (F(2), F(3), F(7))


class ScribeExplicitTests(unittest.TestCase):
    def test_prompt_is_index_explicit_and_caps(self):
        for variant, cap in (('scribe_explicit', 7936), ('scribe_explicit_short', 3840)):
            c = FakeClient(reasoning='own notes')
            result = b.run_agent(engine(c), STATE, 'p', variant)
            self.assertEqual(c.calls[0]['prompt'], f.prompt_for(engine(FakeClient()), STATE, 'index_explicit'))
            self.assertEqual((c.calls[0]['max_tokens'], c.calls[0]['thinking']), (cap, True))
            self.assertEqual((c.calls[1]['max_tokens'], c.calls[1]['thinking']), (256, False))
            self.assertEqual(c.calls[1]['prompt'], c.calls[0]['prompt'] + f.COMMIT + f.NOTES + 'own notes')
            self.assertTrue(result['solved'] and result['scribe_triggered'])
            self.assertEqual(result['variant'], variant)

    def test_trigger_matches_frozen_scribe_rule(self):
        cases = [(None, 'length', 'notes', True, True), ({}, 'length', 'notes', True, False),
                 (None, 'stop', 'notes', True, False), (None, 'length', 'notes', False, False),
                 (None, 'length', '  ', True, False), (None, 'length', None, True, False)]
        for parsed, finish, reasoning, received, eligible in cases:
            with self.subTest(parsed=parsed, finish=finish, reasoning=reasoning, received=received):
                c = FakeClient(parsed, finish, reasoning, received)
                result = b.run_agent(engine(c), STATE, 'p', 'scribe_explicit')
                frozen = FakeClient(parsed, finish, reasoning, received)
                expected = f.run_followup(engine(frozen), STATE, 'p', 'scribe_full')
                self.assertEqual(len(c.calls), 2 if eligible else 1)
                self.assertEqual(result['scribe_skip_reason'], expected['scribe_skip_reason'])
                self.assertEqual(result['solved'], expected['solved'])

    def test_unknown_variant_rejected(self):
        with self.assertRaises(ValueError):
            b.run_agent(engine(FakeClient()), STATE, 'p', 'scribe_full')


if __name__ == '__main__':
    unittest.main()
