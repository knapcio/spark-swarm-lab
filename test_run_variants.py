"""Offline orchestration tests for swarm variants (no model)."""
import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import run_variants as v

PLAN = dict(agent_variant='long_forced_original', agent_wall_deadline_seconds=3600,
            seed_offsets=dict(deep4=1400, strategy4=1500, repair4=1600, board2x2=1700))
TASK = dict(id='t', numbers=[1, 2, 3, 4], target=10)


class VariantTests(unittest.TestCase):
    def run_policy(self, policy, verdicts, plans=True):
        seen = []

        def execute(job, deadline_seconds):
            c = job['command']
            seen.append(Path(c[c.index('--extra-file') + 1]).read_text() if '--extra-file' in c else '')
            return dict(deadline=False)

        def plan_of(path):
            return dict(plan={'moves': [1]} if plans else None, verifier_solved=False, tokens=1, infra=0)

        calls = iter(verdicts)

        def judge(cand, endpoint, events_path, seed):
            return dict(verdict=next(calls), reason='move 2 uses index 5', infra=0, tokens=1)
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute', execute), patch.object(v, 'plan_of', plan_of), \
                patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            (out / 'agents').mkdir(); (out / 'extra').mkdir(); (out / 'judges').mkdir()
            rec = v.run_policy(PLAN, Path('/src'), out, TASK, 1, 0, policy, v.Slots(8))
        return rec, seen

    def test_strategy_hints_are_distinct(self):
        rec, seen = self.run_policy('strategy4', [False] * 4)
        self.assertEqual(sorted(seen), sorted(v.STRATEGIES))

    def test_repair_feeds_critique_and_stops_on_accept(self):
        rec, seen = self.run_policy('repair4', [False, True])
        self.assertEqual(rec['calls'], 2)
        self.assertEqual(seen[0], '')
        self.assertIn('move 2 uses index 5', seen[1])
        self.assertTrue(rec['answered'])

    def test_board_round_two_sees_round_one(self):
        rec, seen = self.run_policy('board2x2', [False, False, False, False])
        self.assertEqual(rec['calls'], 4)
        self.assertTrue(all('Shared board' in s for s in seen[2:]))
        self.assertEqual(seen[:2], ['', ''])

    def test_board_skips_round_two_when_accepted(self):
        rec, _ = self.run_policy('board2x2', [True, False])
        self.assertEqual(rec['calls'], 2)


if __name__ == '__main__':
    unittest.main()
