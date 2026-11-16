"""Offline tests for the coding agent runner; no model, SSH or Docker."""
import unittest
from pathlib import Path
import run_coding_agents as r


class CodingRunnerTests(unittest.TestCase):
    def test_jobs_pair_endpoint_and_grader_host(self):
        plan = dict(agent_variants=['code_plain'] * 2 + ['code_forced'] * 4, agent_seed_offset=400,
                    matrix=dict(seeds=[1, 2], split='evaluation'))
        tasks = [dict(id=f't{i}') for i in range(3)]
        jobs = r.make_jobs(tasks, Path('/o'), Path('/src'), plan, Path('/t.json'), Path('/h.json'))
        self.assertEqual(len(jobs), 36)
        self.assertEqual(len({j['events'] for j in jobs}), 36)
        for j in jobs:
            c = j['command']
            self.assertEqual(r.HOSTS[j['slot']], c[c.index('--host') + 1])
            self.assertEqual(r.ENDPOINTS[j['slot']], c[c.index('--endpoint') + 1])
            self.assertEqual(c[c.index('--variant') + 1], plan['agent_variants'][j['agent']])
            self.assertGreaterEqual(int(c[c.index('--seed') + 1]), 1400)

    def test_selection_uses_first_feedback_pass_then_holdout(self):
        row = lambda agent, fb, ho, task='a': dict(task_id=task, seed=1, agent=agent, feedback_pass=fb, holdout_pass=ho)
        rows = [row(0, False, False), row(1, True, False), row(2, True, True)]   # first feedback pass is wrong on holdout
        rows += [row(0, False, True, 'b'), row(1, False, False, 'b'), row(2, True, True, 'b')]  # holdout-only pass never selects
        curve = r.selection_curve(rows, [0, 1, 2])
        self.assertEqual(curve, {1: dict(cases=2, solved=0), 2: dict(cases=2, solved=0), 3: dict(cases=2, solved=1)})


if __name__ == '__main__':
    unittest.main()
