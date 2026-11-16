"""Offline tests for the generic agent replay runner; no inference."""
import unittest
from pathlib import Path
import run_agents72 as s


class SwarmTests(unittest.TestCase):
    def plan(self, tasks):
        return dict(agent_variants=['scribe_full'] * 8, workers={'scribe_full': 'followup72_worker.py'},
                    matrix=dict(seeds=[1, 2, 3], expected_task_ids_in_stored_order=[t['id'] for t in tasks]))

    def tasks(self):
        return [dict(id=f't{i}', numbers=[1, 2, 3, 4], target=10) for i in range(24)]

    def jobs(self):
        tasks = self.tasks()
        return s.make_jobs(tasks, Path('/o'), ['e1', 'e2', 'e3', 'e4'], Path('/src'), self.plan(tasks))

    def test_matrix_seeds_and_balanced_placement(self):
        jobs = self.jobs()
        self.assertEqual(len(jobs), 576)
        self.assertEqual(len({j['events'] for j in jobs}), 576)
        self.assertTrue(all(j['agent_seed'] not in (1, 2, 3) for j in jobs))
        self.assertEqual(len({(j['seed'], j['agent_seed']) for j in jobs}), 24)
        for case in range(72):
            slots = [j['slot'] for j in jobs if j['case_index'] == case]
            self.assertEqual(sorted(slots), [0, 0, 1, 1, 2, 2, 3, 3])
        self.assertEqual({sum(j['slot'] == n for j in jobs) for n in range(4)}, {144})
        self.assertTrue(all(j['command'][1] == '/src/followup72_worker.py' and not j['stop_on_solution'] and '--timeout' not in j['command'] for j in jobs))

    def test_wrong_tasks_or_endpoints_rejected(self):
        tasks = self.tasks()
        plan = self.plan(tasks)
        with self.assertRaises(ValueError):
            s.make_jobs(tasks[::-1], Path('/o'), ['a', 'b', 'c', 'd'], Path('/s'), plan)
        with self.assertRaises(ValueError):
            s.make_jobs(tasks, Path('/o'), ['a'] * 4, Path('/s'), plan)

    def test_swarm_curve_uses_fixed_agent_prefix(self):
        rows = [dict(task_id='a', seed=1, agent=i, solved=i == 2) for i in range(4)]
        rows += [dict(task_id='b', seed=1, agent=i, solved=False) for i in range(4)]
        rows += [dict(task_id='c', seed=1, agent=0, solved=True)]  # incomplete case only counts for k=1
        self.assertEqual(s.prefix_curve(rows, [0, 1, 2, 3]),
                         {1: dict(cases=3, solved=1), 2: dict(cases=2, solved=0),
                          3: dict(cases=2, solved=1), 4: dict(cases=2, solved=1)})

    def test_mixed_and_per_variant_summary(self):
        variants = ['x', 'y', 'x', 'y']
        rows = [dict(task_id='a', seed=1, agent=i, arm=variants[i], solved=i == 1, completion_tokens=10) for i in range(4)]
        rows += [dict(task_id='b', seed=1, agent=i, arm=variants[i], solved=i == 2, completion_tokens=10) for i in range(4)]
        out = s.summarize(rows, variants)
        self.assertEqual(out['mixed'][1], dict(cases=2, solved=0))
        self.assertEqual(out['mixed'][4], dict(cases=2, solved=2))
        self.assertEqual(out['per_variant']['x'], {1: dict(cases=2, solved=0), 2: dict(cases=2, solved=1)})
        self.assertEqual(out['per_variant']['y'], {1: dict(cases=2, solved=1), 2: dict(cases=2, solved=1)})
        self.assertEqual(out['per_agent_success'], {'x': dict(runs=4, solved=1), 'y': dict(runs=4, solved=1)})
        self.assertEqual(out['completion_tokens_per_solved_case'], 40)

    def test_mixed_variants_use_their_own_worker(self):
        tasks = self.tasks()
        plan = dict(agent_variants=['scribe_full', 'scribe_explicit'] * 4,
                    workers={'scribe_full': 'followup72_worker.py', 'scribe_explicit': 'followup72b_worker.py'},
                    matrix=dict(seeds=[1, 2, 3], expected_task_ids_in_stored_order=[t['id'] for t in tasks]))
        jobs = s.make_jobs(tasks, Path('/o'), ['e1', 'e2', 'e3', 'e4'], Path('/src'), plan)
        for j in jobs:
            self.assertEqual(j['command'][1], '/src/' + plan['workers'][j['arm']])
            self.assertEqual(j['command'][j['command'].index('--variant') + 1], j['arm'])
            self.assertEqual(j['arm'], plan['agent_variants'][j['agent']])

    def test_faults(self):
        ok = dict(controller_error=None, malformed_lines=0, infrastructure_failures=0, returncode=0,
                  controller_stop=False, deadline=False, calls=2, unfinished_calls=0, status='complete')
        self.assertIsNone(s.operational_fault(ok))
        self.assertIsNone(s.operational_fault(dict(ok, deadline=True, controller_stop=True, returncode=-15,
                                                   unfinished_calls=1, status='deadline')))
        self.assertEqual(s.operational_fault(dict(ok, infrastructure_failures=1)), 'controller_or_transport_failure')
        self.assertEqual(s.operational_fault(dict(ok, returncode=1)), 'process_failure')


if __name__ == '__main__':
    unittest.main()
