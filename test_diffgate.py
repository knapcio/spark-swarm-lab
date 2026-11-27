"""Differential gate: sandbox runner protocol (its trusted runner exercised on trusted test snippets only, through a
faked ssh), the sandbox step, the report's frozen rule and the generator plan. No fleet, no network, no model code."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import diffgate_exec as de  # noqa: E402
import diffgate_gen_plan as gp  # noqa: E402
import report_diffgate as rep  # noqa: E402
import sandbox_outputs as so  # noqa: E402

GEN = 'def generate_inputs():\n    return [{"args": [1]}, {"args": [2]}, {"args": [0]}, {"args": [3], "kwargs": {}}]'
F_OK = 'def f(x):\n    return 10 // x'
F_OTHER = 'def f(x):\n    return 10 // x if x != 3 else -1'
F_SLOW = 'def f(x):\n    while x == 2:\n        pass\n    return 10 // x'
FAMILY = ('arithmetic', 'number', 'target', 'puzzle', 'countdown', 'shell', 'table', 'path', 'cache')


def local_ssh(host, command, payload=None, timeout=15):
    """Stands in for sandbox_code._ssh in tests: runs the trusted RUNNER locally (only test snippets reach it)."""
    runner = command[-1]
    return subprocess.run([sys.executable, '-I', '-S', '-c', runner], input=payload, capture_output=True, text=True,
                          timeout=timeout)


class Guarded(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('no network in tests'))
        guard.start()
        self.addCleanup(guard.stop)
        for name, value in (('_ssh', local_ssh), ('_inspect_owned', lambda h, n, t: (dict(
                StartedAt='2026-11-27T10:00:00.000000Z', FinishedAt='2026-11-27T10:00:01.500000Z'), None)),
                ('_cleanup', lambda h, n, t: True)):
            p = patch.object(so.sc, name, value)
            p.start()
            self.addCleanup(p.stop)


class SandboxTests(Guarded):
    def test_generate_and_outputs(self):
        gen = so.run('generate', GEN, 'generate_inputs', 'Spark_01', total_timeout=10)
        self.assertEqual((gen['status'], len(gen['inputs'])), ('ok', 4))
        self.assertEqual(gen['container_seconds'], 1.5)
        out = so.run('outputs', F_OK, 'f', 'Spark_01', inputs=gen['inputs'])
        kinds = [o['preview'].split(':')[0] for o in out['outcomes']]
        self.assertEqual(kinds, ['I', 'I', 'exception', 'I'])
        self.assertEqual(out['outcomes'][2]['preview'], 'exception:ZeroDivisionError')
        other = so.run('outputs', F_OTHER, 'f', 'Spark_01', inputs=gen['inputs'])
        self.assertEqual([a['sha256'] == b['sha256'] for a, b in zip(out['outcomes'], other['outcomes'])],
                         [True, True, True, False])

    def test_per_input_timeout_is_an_outcome_and_load_errors_are_unavailable(self):
        inputs = [{'args': [1]}, {'args': [2]}]
        out = so.run('outputs', F_SLOW, 'f', 'Spark_01', inputs=inputs, per_input=0.3, total_timeout=5)
        self.assertEqual([o['preview'] for o in out['outcomes']], ['I:10', 'timeout'])
        self.assertEqual(so.run('outputs', 'def g(): pass', 'f', 'Spark_01', inputs=inputs)['status'], 'error')
        self.assertEqual(so.run('outputs', F_SLOW, 'f', 'Spark_01', inputs=[{'args': [2]}] * 5, per_input=1,
                                total_timeout=1.5)['status'], 'timeout')
        bad = so.run('generate', 'def generate_inputs():\n    return [{"x": 1}]', 'generate_inputs', 'Spark_01')
        self.assertEqual(bad['status'], 'error')

    def test_type_tags_and_never_the_controller_host(self):
        code = ('def f(x):\n    return [True, 1, 1.0, "1", None, {"b": 1, "a": (1,)}][x]')
        out = so.run('outputs', code, 'f', 'Spark_01', inputs=[{'args': [i]} for i in range(6)])
        self.assertEqual([o['preview'] for o in out['outcomes']],
                         ['B:true', 'I:1', 'F:1.0', 'S:"1"', 'N', 'D{S:"a":O:tuple:(1,),S:"b":I:1}'])
        for host in ('localhost', 'user@127.0.0.1', 'bad host'):
            with self.assertRaises(ValueError):
                so.run('outputs', F_OK, 'f', host, inputs=[{'args': [1]}])


def item(kind='wrong', refs=4):
    return dict(item_id='g000', run='r', task_id='t', seed=1, kind=kind, function_name='f',
                passers=[dict(agent=0, code=F_OK, code_sha256='a')],
                references=[dict(run='r2', seed=s, agent=0, code=F_OTHER if s % 2 else F_OK, code_sha256=f'r{s}',
                                 holdout_pass=True) for s in range(refs)])


class ExecTests(Guarded):
    def test_run_item_fence_and_unavailable_paths(self):
        rec, fault = de.run_item(item(), dict(outcome='ok', reply='Here:\n```python\n' + GEN + '\n```\n'), 'Spark_01')
        self.assertIsNone(fault)
        self.assertEqual((rec['inputs_status'], len(rec['programs'])), ('ok', 5))
        self.assertEqual(rec['programs'][0]['role'], 'accepted')
        self.assertEqual(de.run_item(item(), dict(outcome='truncated', reply=GEN), 'Spark_01')[0]['inputs_status'],
                         'no generator reply')
        self.assertTrue(de.run_item(item(), dict(outcome='ok', reply='def nope(): pass'), 'Spark_01')[0]
                        ['inputs_status'].startswith('error'))

    def test_infrastructure_fault_stops_and_resume(self):
        def infra(*a, **k):
            return dict(status='error', infrastructure=True, error='ssh down')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'pop.json').write_text(json.dumps(dict(status='FROZEN', items=[item()])))
            gen = root / 'gen'
            (gen / 'run').mkdir(parents=True)
            (gen / 'summary.json').write_text(json.dumps(dict(complete=True, drain_confirmed=True)))
            (gen / 'run' / 'records.jsonl').write_text(json.dumps(dict(item='g000', outcome='ok', reply=GEN)) + '\n')
            argv = ['--population', str(root / 'pop.json'), '--generations', str(gen), '--hosts', 'Spark_01',
                    '--output', str(root / 'ex')]
            self.assertEqual(de.main(argv, runner=infra), 1)
            self.assertEqual(json.loads((root / 'ex' / 'summary.json').read_text())['faults'][0]['item'], 'g000')
            self.assertEqual(de.main(argv), 0)  # resumed: the item is now recorded
            self.assertTrue(json.loads((root / 'ex' / 'summary.json').read_text())['complete'])
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                de.main(argv[:-4] + ['--hosts', 'localhost', '--output', str(root / 'ex2')])


def record(statuses, accepted_ok=True, agree=(), inputs='ok'):
    """statuses: per reference 'ok' or 'error'; agree: indices of references whose outcomes equal the accepted."""
    acc = dict(role='accepted', status='ok' if accepted_ok else 'timeout', outcomes=['x', 'y'])
    refs = [dict(role='reference', status=s, outcomes=['x', 'y'] if i in agree else ['x', 'z'])
            for i, s in enumerate(statuses)]
    return dict(item='g000', inputs_status=inputs, inputs=[{}, {}], programs=[acc] + refs, sandbox_seconds=2.0)


class ReportTests(unittest.TestCase):
    def test_gate_rule(self):
        self.assertEqual(rep.gate(record(['ok'] * 4, agree=(0, 1)))[:3], ('pass', 2, 4))  # 2 of 4 is not a majority
        self.assertEqual(rep.gate(record(['ok'] * 4, agree=(0,)))[:3], ('flag', 3, 4))
        self.assertTrue(rep.gate(record(['ok'] * 4, agree=(0, 1, 2)))[3])  # any-reference variant
        self.assertEqual(rep.gate(record(['ok', 'ok', 'error', 'error'], agree=(0, 1)))[0], 'unavailable')
        self.assertEqual(rep.gate(record(['ok', 'error', 'ok', 'ok'], agree=(0, 2, 3)))[:3], ('pass', 0, 3))
        self.assertEqual(rep.gate(record(['ok'] * 4, accepted_ok=False))[0], 'flag')
        self.assertEqual(rep.gate(record(['ok'] * 4, inputs='error: x'))[0], 'unavailable')

    def build(self, kinds_and_records, gen_complete=True, exec_complete=True):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            items, recs = [], []
            for n, (kind, rec) in enumerate(kinds_and_records):
                it = dict(item(kind), item_id=f'g{n:03d}')
                items.append(it)
                recs.append(dict(rec, item=it['item_id']))
            (root / 'gen' / 'run').mkdir(parents=True)
            (root / 'gen' / 'summary.json').write_text(json.dumps(dict(complete=gen_complete, drain_confirmed=True)))
            (root / 'gen' / 'run' / 'records.jsonl').write_text(''.join(
                json.dumps(dict(item=i['item_id'], tokens_generated=100)) + '\n' for i in items))
            (root / 'ex').mkdir()
            (root / 'ex' / 'summary.json').write_text(json.dumps(dict(complete=exec_complete)))
            (root / 'ex' / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
            return rep.build(dict(items=items), root / 'gen', root / 'ex')

    def test_kill_rule(self):
        flag, ok = record(['ok'] * 4, agree=()), record(['ok'] * 4, agree=(0, 1, 2, 3))
        r = self.build([('wrong', flag), ('wrong', ok), ('correct', ok)] + [('correct', ok)] * 9)
        self.assertEqual((r['flagged_wrong']['rate'], r['flagged_correct']['rate'], r['decision'][:8]),
                         (0.5, 0.0, 'SURVIVES'))
        r = self.build([('wrong', flag), ('wrong', ok), ('wrong', ok), ('correct', ok)])  # 1 of 3 < 40 %
        self.assertEqual(r['decision'], 'KILL')
        r = self.build([('wrong', flag), ('correct', flag)] + [('correct', ok)] * 8)  # 1 of 9 > 10 %
        self.assertEqual(r['decision'], 'KILL')
        self.assertEqual((r['generator_tokens'], r['sandbox_seconds']), (1000, 20.0))

    def test_incomplete(self):
        ok = record(['ok'] * 4, agree=(0, 1, 2, 3))
        self.assertTrue(self.build([('wrong', ok)], gen_complete=False)['decision'].startswith('INCOMPLETE'))
        self.assertTrue(self.build([('wrong', ok)], exec_complete=False)['decision'].startswith('INCOMPLETE'))


class GenPlanTests(unittest.TestCase):
    def test_plan_is_generic_and_carries_only_the_payload(self):
        root = Path(__file__).resolve().parent
        if not (root / 'DIFFGATE_POPULATION.json').exists():
            self.skipTest('no frozen population in this tree')
        plan = gp.make('0' * 40, root)
        added = (plan['system'] + ' ' + plan['user'].replace('{payload}', '')).lower()
        self.assertEqual([w for w in FAMILY if w in added], [])
        self.assertTrue(all(set(json.loads(i['payload'])) == {'function_name', 'spec'} for i in plan['items']))
        self.assertEqual((plan['per_node'], plan['think_tokens'], plan['total_tokens']), (20, 8192, 10240))
        self.assertEqual(set(plan['judge_code_sha256']), {'inkling/fleet_lease.py', 'inkling/admit.py'})


if __name__ == '__main__':
    unittest.main()
