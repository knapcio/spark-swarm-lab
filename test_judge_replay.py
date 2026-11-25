"""Offline tests for judges.py, judge_replay.py and inkling/report_judge_replay.py (mocked judges; no network)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import judge_replay
import judges
import run_variants as v

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_judge_replay as rep  # noqa: E402

TASK = dict(id='eva-sum_pairs', split='evaluation', function_name='sum_pairs', spec='Return the sum of all pairs.',
            examples=[dict(args=[[1, 2]], expected=3)])


def write_coding_run(root, name='coding-roll-v1-r2'):
    (root / 'datasets').mkdir(exist_ok=True)
    (root / 'datasets' / 'tasks.json').write_text(json.dumps(dict(tasks=[TASK, dict(TASK, id='eva-other')])))
    d = root / 'runs' / name
    d.mkdir(parents=True)
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=dict(matrix=dict(tasks='datasets/tasks.json'),
                                                                   agent_variants=['code_xl'] * 4))))
    rows = [dict(task_id='eva-sum_pairs', seed=1, answered=True, solved=True, winner_agent=2),
            dict(task_id='eva-other', seed=1, answered=True, solved=False, winner_agent=0),
            dict(task_id='eva-sum_pairs', seed=2, answered=False, solved=False, winner_agent=None),
            dict(task_id='eva-other', seed=2, answered=True, solved=True, winner_agent=1)]  # trace missing -> skipped
    (d / 'cases.json').write_text(json.dumps(rows))
    for task, seed, agent, hold, forced in (('eva-sum_pairs', 1, 2, True, False), ('eva-other', 1, 0, False, True)):
        (d / f'{task}-s{seed}-a{agent}-code_xl.jsonl').write_text(json.dumps(dict(
            type='puzzle_end', code=f'def f():\n    return {seed}', feedback_pass=True, holdout_pass=hold,
            budget_forced=forced)) + '\n')
    return d


class CodingCollectionTests(unittest.TestCase):
    def test_winners_and_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = write_coding_run(root)
            cands, skipped = judges.coding_winners(run, root)
        self.assertEqual([(c['task_id'], c['seed'], c['agent'], c['truth'], c['forced']) for c in cands],
                         [('eva-sum_pairs', 1, 2, True, False), ('eva-other', 1, 0, False, True)])
        self.assertEqual(len(skipped), 1)
        self.assertNotEqual(cands[0]['judge_seed'], cands[1]['judge_seed'])
        import coding_harness
        prompt = judges.coding_judge_prompt(TASK, cands[0]['code'])
        self.assertTrue(prompt.startswith('Task statement:\n' + coding_harness.context(TASK)))
        self.assertIn('```python\ndef f():\n    return 1\n```', prompt)
        self.assertIn('It passed the available checks; they are partial.', prompt)
        self.assertTrue(prompt.endswith(judges.CODING_TAIL))
        for text in (judges.GENERIC_SYSTEM, judges.CODING_TAIL):
            self.assertNotIn('arithmetic', text.lower())
            self.assertNotIn('python', text.lower())

    def test_run_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_coding_run(root, 'coding-roll-v1-r2')
            write_coding_run(root, 'coding-roll-smoke')
            (root / 'runs' / 'coding-earlystop-v1-full').mkdir()
            runs, skipped = judges.coding_runs(root / 'runs')
        self.assertEqual([r.name for r in runs], ['coding-roll-v1-r2'])
        self.assertIn('coding-earlystop-v1-full', skipped[0])

    def test_generic_judge_system_prompt(self):
        seen = {}

        class Client:
            def __init__(self, endpoint, model, budget, events, seed):
                self.model = model

            def post(self, path, body, timeout):
                seen['body'] = body
                return contextlib.nullcontext(io.StringIO(json.dumps(dict(tokens=[1]))))

        class Forced:
            ForcedClient = Client
        judges._GENERIC_JUDGE = None
        try:
            with patch.object(judges.run_judge, '_forced72', lambda: Forced):
                judges.GenericJudge('e', 'm', None, None, 1).chat_prompt_ids('hello')
        finally:
            judges._GENERIC_JUDGE = None
        self.assertEqual(seen['body']['messages'][0], dict(role='system', content=judges.GENERIC_SYSTEM))


def write_arith_run(root):
    tasks = [dict(id=f't{i}', split='evaluation', numbers=[1, 2, 3, 4, 5, 6], target=7) for i in range(3)]
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=tasks)))
    d = root / 'runs' / 'swarm-x-roll12cancel'
    (d / 'agents').mkdir(parents=True)
    plan = dict(protocol='swarm-variants-screen-v1', dataset=str(root / 'data.json'), dataset_protocol='p',
                split='evaluation', tasks=3, seeds=[1], policies=['roll12cancel'], serving=dict(model='thinkingmachines/Inkling-2-Mini'))
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=plan, policies=['roll12cancel'], resume=None)))
    (d / 'arm_accounting.json').write_text('{}')
    agent = lambda slot, verdict, solved=True, plan_=True: dict(slot=slot, verdict=verdict, verifier_solved=solved,
                                                                 plan={'moves': [1]} if plan_ else None, judge_tokens=500)
    rows = [dict(task_id='t0', seed=1, policy='roll12cancel', answered=True, infra=0, agents=[agent(0, False, False), agent(1, True)]),
            dict(task_id='t1', seed=1, policy='roll12cancel', answered=True, infra=0, agents=[agent(0, True)]),
            dict(task_id='t2', seed=1, policy='roll12cancel', answered=True, infra=0, agents=[agent(0, True), agent(3, False, False)])]
    (d / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    for task, slot, forced in (('t0', 0, True), ('t0', 1, True), ('t1', 0, False), ('t2', 0, False), ('t2', 3, False)):
        (d / 'agents' / f'{task}-s1-roll12cancel-a{slot}.jsonl').write_text(json.dumps(dict(type='puzzle_end', budget_forced=forced)) + '\n')
    return d


class ArithCollectionTests(unittest.TestCase):
    def test_forced_accepted_control_and_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = write_arith_run(root)
            acc = judges.arith_accepted(run, root)
            both = judges.arith_accepted(run, root, include_rejected_forced=True)
            self.assertEqual([r.name for r in judges.arith_runs(root / 'runs')], ['swarm-x-roll12cancel'])
        self.assertEqual([(c['task_id'], c['slot'], c['forced']) for c in acc], [('t0', 1, True), ('t1', 0, False), ('t2', 0, False)])
        sel = judges.arith_selection(acc)
        self.assertEqual([c['group'] for c in sel], ['forced', 'control'])
        self.assertEqual(sel, judges.arith_selection(acc))  # seeded control sample
        sel2 = judges.arith_selection(both)
        self.assertEqual([(c['group'], c['task_id'], c['slot']) for c in sel2 if c['group'] == 'forced_rejected'], [('forced_rejected', 't0', 0)])
        self.assertTrue(all(c['judge_seed'] != 90000 + 1000 + c['slot'] for c in sel2))


class DriverTests(unittest.TestCase):
    def test_judge_candidate_paths(self):
        calls = []

        def judge(cand, endpoint, path, seed, prompt=None, client_factory=None):
            calls.append((cand, seed, prompt is not None, client_factory))
            if cand is not None and cand['target'] == 99:
                raise v.JudgeFault('boom', dict(verdict=None, reason='', infra=1, tokens=7))
            return dict(verdict=True, reason='', infra=0, tokens=11)
        coding = dict(part='coding', group='winner', run='r', task_id='t', seed=1, agent=0, code='x', statement_task=TASK,
                      truth=False, judge_seed=123, forced=False)
        arith = dict(part='arith', group='forced', run='r', policy='p', task_id='t', seed=1, slot=4, numbers=[1], target=7,
                     plan={'moves': [1]}, truth=True, judge_seed=456, forced=True)
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            (out / 'judges').mkdir()
            slots = judge_replay.closers.EndpointSlots(['e'], 2)
            r1 = judge_replay.judge_candidate(coding, 'e', out, slots)
            r2 = judge_replay.judge_candidate(arith, 'e', out, slots)
            r3_ = judge_replay.judge_candidate(dict(arith, target=99), 'e', out, slots)
        self.assertEqual((calls[0][0], calls[0][1], calls[0][2], calls[0][3]), (None, 123, True, judges.GenericJudge))
        self.assertEqual((calls[1][1], calls[1][2], calls[1][3]), (456, False, None))
        self.assertEqual((r1['verdict'], r1['tokens'], r1['truth']), (True, 11, False))
        self.assertNotIn('code', r1)
        self.assertEqual((r3_['verdict'], r3_['infra'], r3_['tokens']), (None, 1, 7))

    def test_plan_only_and_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_coding_run(root)
            buf = io.StringIO()
            with patch.object(judges, 'HERE', root), contextlib.redirect_stdout(buf):
                judge_replay.main(['--part', 'coding', '--plan-only', '--runs-dir', str(root / 'runs')])
            info = json.loads(buf.getvalue())
            self.assertEqual((info['candidates'], info['truth_by_group'], info['model_calls']),
                             (2, {'winner/correct': 1, 'winner/wrong': 1}, 0))
            (root / 'plan.json').write_text('{}')
            (root / 'adm.json').write_text(json.dumps(dict(verified=True, verified_utc=datetime.now(timezone.utc).isoformat(),
                                                           nodes=[dict(node=f'0{i}', ok=True) for i in range(1, 5)])))
            judge = lambda cand, endpoint, path, seed, prompt=None, client_factory=None: dict(verdict=False, reason='r', infra=0, tokens=5)
            with patch.object(judges, 'HERE', root), patch.object(v, 'judge_with_reason', judge), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = judge_replay.main(['--part', 'coding', '--runs-dir', str(root / 'runs'), '--plan', str(root / 'plan.json'),
                                          '--admission', str(root / 'adm.json'), '--output', str(root / 'out')])
            rows = [json.loads(x) for x in (root / 'out' / 'candidates.jsonl').read_text().splitlines()]
            meta = json.loads((root / 'out' / 'metadata.json').read_text())
        self.assertEqual(code, 0)
        self.assertEqual(len(rows), 2)
        self.assertEqual((meta['judged'], meta['faults'], meta['client_tokens']), (2, 0, 10))


def account(d, tokens=1000):
    nodes = ('01', '02', '03', '04')
    start = datetime(2026, 11, 24, tzinfo=timezone.utc)
    (d / 'arm_accounting.json').write_text(json.dumps(dict(
        protocol='swarm-arm-accounting-v1', runner_exit=0, idle_after=True, command=['python3', 'judge_replay.py'],
        runner_wall_seconds=60, before=dict(utc=start.isoformat(), nodes={n: dict(generation_tokens=0.0) for n in nodes}),
        after=dict(utc=(start + timedelta(seconds=60)).isoformat(), nodes={n: dict(generation_tokens=1.0) for n in nodes}),
        server=dict(total=dict(generation_tokens=tokens, prompt_tokens=5 * tokens, prefill_compute_tokens=2 * tokens),
                    per_node={n: dict(generation_tokens=tokens / 4, decode_tokens=tokens / 4, requests=3) for n in nodes}),
        energy=dict(total_wh=0.4))))


def output_dir(root, name, rows, **meta):
    d = root / name
    d.mkdir()
    (d / 'candidates.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (d / 'metadata.json').write_text(json.dumps(dict(dict(completed_utc='x', candidates=len(rows)), **meta)))
    account(d)
    return d


def cand(group, truth, verdict, i, **extra):
    return dict(dict(part='x', group=group, run='r', task_id=f't{i}', seed=1, agent=i, truth=truth, verdict=verdict,
                     tokens=100, infra=0), **extra)


class ReportTests(unittest.TestCase):
    def test_coding_and_arith_facts(self):
        coding = [cand('winner', False, False, 0), cand('winner', False, True, 1), cand('winner', True, True, 2),
                  cand('winner', True, False, 3), cand('winner', True, None, 4)]
        arith = [cand('forced', True, True, 0), cand('forced', True, False, 1), cand('control', True, True, 2),
                 cand('forced_rejected', False, True, 3), cand('forced_rejected', False, False, 4)]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c = output_dir(root, 'coding', coding)
            a = output_dir(root, 'arith', arith)
            s = rep.build(c, a)
            with contextlib.redirect_stdout(io.StringIO()):
                code = rep.main(['--coding', str(c), '--arith', str(a), '--out', str(root / 'out')])
            md = (root / 'out' / 'REPORT.md').read_text()
        f = s['parts']['coding']['facts']
        self.assertEqual((f['wrong_winners'], f['wrong_rejected'], f['correct_rejected'], f['no_verdict']), (2, 1, 1, 1))
        g = s['parts']['arith']['facts']
        self.assertEqual((g['forced']['valid_rejected'], g['control']['valid_rejected']), (1, 0))
        self.assertEqual(g['forced_rejected']['false_accepts'], 1)
        self.assertEqual(code, 0)
        self.assertEqual(s['parts']['coding']['server']['prefill_compute_tokens'], 2000)
        self.assertIn('wrong winners (hidden tests fail) rejected by the judge: 1 of 2', md)

    def test_incomplete_parts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c = output_dir(root, 'coding', [cand('winner', True, True, 0, infra=1)])
            a = output_dir(root, 'arith', [cand('forced', True, True, 0)], candidates=3)
            s = rep.build(c, a)
        self.assertEqual(s['parts']['coding']['status'], 'incomplete')
        self.assertIn('judge fault', ' '.join(s['parts']['coding']['reasons']))
        self.assertIn('1 judged of 3', ' '.join(s['parts']['arith']['reasons']))
        self.assertIsNone(s['parts']['arith']['facts'])


if __name__ == '__main__':
    unittest.main()
