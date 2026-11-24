"""Offline tests for relay.py, relay_replay.py and inkling/report_relay.py (mocked workers/judges; no network)."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import relay
import relay_replay
import run_variants as v

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_relay  # noqa: E402

TASK = dict(id='t0', numbers=[1, 2, 3, 4, 5, 6], target=99)


def trace(path, reasoning, response=None):
    path.write_text(json.dumps(dict(type='run_start')) + '\n' +
                    json.dumps(dict(type='request_end', reasoning=reasoning, response=response)) + '\n')


def agent(slot, verdict=None, started=True, cancelled=False):
    return dict(slot=slot, verdict=verdict, started=started, cancelled=cancelled, plan=None, tokens=5)


class ArtifactTests(unittest.TestCase):
    def case(self, root, texts):
        """texts: {slot: reasoning or None (no trace)}"""
        (root / 'agents').mkdir(exist_ok=True)
        row = dict(task_id='t0', seed=1, policy='roll12cancel', agents=[agent(s) for s in texts])
        for s, text in texts.items():
            if text is not None:
                trace(root / 'agents' / f't0-s1-roll12cancel-a{s}.jsonl', text, 'ANSWER' if s == 1 else None)
        return row

    def test_artifact_is_thinking_then_answer_and_truncation_keeps_the_tail(self):
        with tempfile.TemporaryDirectory() as d:
            row = self.case(Path(d), {1: 'think think'})
            self.assertEqual(relay.artifact(Path(d) / 'agents' / 't0-s1-roll12cancel-a1.jsonl'), 'think think\nANSWER')
        self.assertEqual(relay.truncate('abcdef', 4), 'cdef')
        self.assertEqual(relay.truncate('abc', 4), 'abc')
        extra = relay.relay_extra('x' * 10 + 'TAIL', 6)
        self.assertEqual(extra, relay.PROTOCOL + '\n\nxxTAIL')
        self.assertNotIn('arithmetic', relay.PROTOCOL.lower())

    def test_candidates_distinct_nonempty_with_traces_only(self):
        with tempfile.TemporaryDirectory() as d:
            row = self.case(Path(d), {0: 'same', 2: 'same', 3: '   ', 4: None, 5: 'other'})
            row['agents'].append(agent(6, verdict=True))  # accepted agents are not failed
            cands = relay.candidates(Path(d), row)
        self.assertEqual([c['slot'] for c in cands], [0, 5])

    def test_seeded_uniform_selection(self):
        cands = [dict(slot=s, text=f'a{s}') for s in range(12)]
        pick = lambda seed, task: [c['slot'] for c in relay.select(cands, 4, relay.selection_rng(seed, task, 1))]
        self.assertEqual(pick('relay-v1', 't0'), pick('relay-v1', 't0'))  # frozen by plan seed + case
        self.assertNotEqual(pick('relay-v1', 't0'), pick('relay-v1', 't1'))
        self.assertEqual(len(set(pick('relay-v1', 't0'))), 4)
        self.assertEqual(len(relay.select(cands[:2], 4, relay.selection_rng('s', 't', 1))), 2)
        # uniform: over many cases every slot is picked about equally often (no ranking)
        counts = [0] * 12
        for i in range(3000):
            for slot in pick('relay-v1', f'case{i}'):
                counts[slot] += 1
        self.assertLess(max(counts) - min(counts), 0.15 * 1000)

    def test_settings_from_plan(self):
        s = relay.settings(dict(relay=dict(k=2, max_chars=50, selection_seed='z'), seed_offsets=dict(relay=1, replace=2)))
        self.assertEqual((s['k'], s['max_chars'], s['selection_seed'], s['seed_offsets']), (2, 50, 'z', dict(relay=1, replace=2)))
        self.assertEqual(relay.settings({})['k'], 4)


class RunArmTests(unittest.TestCase):
    CP = dict(failed_agents=12, candidates=3, selected=[dict(source_slot=s, chars=100, chars_used=60, text=f'work of {s}')
                                                       for s in (7, 2, 9)])

    def run_arm(self, arm, fast, accept, solved=()):
        seen = {}

        def execute(job, deadline_seconds, cancel=None):
            slot = int(job['events'].rsplit('-a', 1)[1].split('.')[0])
            c = job['command']
            seen[slot] = dict(extra=Path(c[c.index('--extra-file') + 1]).read_text() if '--extra-file' in c else '',
                              seed=int(c[c.index('--seed') + 1]), variant=c[c.index('--variant') + 1])
            if slot in fast:
                return dict(deadline=False, cancelled=False, returncode=0)
            for _ in range(200):
                if cancel.is_set():
                    return dict(deadline=False, cancelled=True, returncode=-15)
                time.sleep(.01)
            return dict(deadline=False, cancelled=False, returncode=0)

        def plan_of(path):
            slot = int(str(path).rsplit('-a', 1)[1].split('.')[0])
            return dict(plan={'moves': [1]}, verifier_solved=slot in solved, tokens=10, infra=0)

        def judge(cand, endpoint, events_path, seed):
            slot = int(str(events_path).rsplit('-a', 1)[1].split('.')[0])
            return dict(verdict=slot in accept, reason='', infra=0, tokens=2)
        s = relay.settings(dict(seed_offsets=dict(relay=19000, replace=19500)))
        plan = dict(agent_variant='xl_forced_original', agent_wall_deadline_seconds=60)
        with tempfile.TemporaryDirectory() as d, patch.object(v, 'execute_cancellable', execute), \
                patch.object(v, 'plan_of', plan_of), patch.object(v, 'judge_with_reason', judge):
            out = Path(d)
            for sub in ('agents', 'judges', 'extra'):
                (out / sub).mkdir()
            rec = relay.run_arm(arm, plan, Path('/src'), out, TASK, 2, 5, self.CP, relay.closers.EndpointSlots(v.ENDPOINTS, 8),
                                v.ENDPOINTS, s)
        return rec, seen

    def test_relay_workers_get_protocol_plus_artifact(self):
        rec, seen = self.run_arm('relay', fast={200, 201, 202}, accept=set())
        self.assertEqual(sorted(seen), [200, 201, 202])
        self.assertEqual(seen[200]['extra'], relay.PROTOCOL + '\n\nwork of 7')
        self.assertEqual(seen[201]['extra'], relay.PROTOCOL + '\n\nwork of 2')
        self.assertEqual([seen[s]['seed'] for s in (200, 201, 202)], [2000 + 19000 + s for s in (200, 201, 202)])
        self.assertEqual([w['source_slot'] for w in rec['workers']], [7, 2, 9])
        self.assertEqual((rec['rescued'], rec['wrong'], rec['artifact_chars_used'], rec['client_tokens']), (False, False, 180, 36))

    def test_replace_workers_equal_count_no_artifact(self):
        rec, seen = self.run_arm('replace', fast={300, 301, 302}, accept=set())
        self.assertEqual(sorted(seen), [300, 301, 302])
        self.assertTrue(all(x['extra'] == '' for x in seen.values()))
        self.assertEqual([seen[s]['seed'] for s in (300, 301, 302)], [2000 + 19500 + s for s in (300, 301, 302)])
        self.assertEqual(rec['artifact_chars_used'], 0)

    def test_first_accept_wins_and_cancels_within_the_arm(self):
        rec, seen = self.run_arm('relay', fast={201}, accept={201}, solved={201})
        self.assertEqual((rec['selected_slot'], rec['rescued'], rec['wrong']), (201, True, False))
        self.assertEqual(rec['cancelled_workers'] + rec['unstarted_workers'], 2)
        rec, _ = self.run_arm('replace', fast={300, 301, 302}, accept={302}, solved=())
        self.assertEqual((rec['selected_slot'], rec['rescued'], rec['wrong']), (302, False, True))


def write_recorded_run(root):
    """A recorded roll12cancel arm: t0 abstained (3 failed agents with traces), t1 answered."""
    tasks = [dict(id=f't{i}', split='evaluation', numbers=[1, 2, 3, 4, 5, 6], target=99) for i in range(2)]
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=tasks)))
    run = root / 'runs' / 'base'
    (run / 'agents').mkdir(parents=True)
    plan = dict(dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=2, seeds=[1],
                agent_variant='xl_forced_original', policies=['roll12cancel'])
    (run / 'metadata.json').write_text(json.dumps(dict(protocol=plan, policies=['roll12cancel'], resume=None)))
    rows = [dict(task_id='t0', seed=1, policy='roll12cancel', answered=False, infra=0, agents=[agent(s) for s in range(3)]),
            dict(task_id='t1', seed=1, policy='roll12cancel', answered=True, infra=0, agents=[agent(0, True)])]
    (run / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    for s in range(3):
        trace(run / 'agents' / f't0-s1-roll12cancel-a{s}.jsonl', f'work {s} ' * 10)
    return run


class DriverTests(unittest.TestCase):
    def test_plan_only_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = write_recorded_run(root)
            (root / 'plan.json').write_text(json.dumps(dict(relay=dict(k=2, max_chars=20))))
            buf = io.StringIO()
            with patch.object(relay_replay.closer_replay, 'HERE', root), contextlib.redirect_stdout(buf):
                relay_replay.main(['--runs', str(run), '--plan-only', '--plan', str(root / 'plan.json')])
        lines = [json.loads(x) for x in buf.getvalue().splitlines()]
        self.assertEqual(lines[0]['failed_agents'], 3)
        self.assertEqual(len(lines[0]['selected_slots']), 2)
        self.assertEqual(lines[-1]['total'], dict(cases=1, failed_agents=3, candidates=3, selected=2, cases_with_workers=1,
                                                  relay_workers=2, replace_workers=2))
        self.assertEqual(lines[-2]['summary']['chars_used_max'], 20)

    def test_run_requires_arm_and_admission(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = write_recorded_run(root)
            with patch.object(relay_replay.closer_replay, 'HERE', root), self.assertRaisesRegex(Exception, 'required for a run'):
                relay_replay.main(['--runs', str(run)])

    def test_both_arms_end_to_end_with_mocks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = write_recorded_run(root)
            (root / 'plan.json').write_text(json.dumps(dict(relay=dict(k=2), source_revision='x', agent_wall_deadline_seconds=60,
                                                            seed_offsets=dict(relay=19000, replace=19500))))
            (root / 'adm.json').write_text(json.dumps(dict(verified=True, verified_utc=datetime.now(timezone.utc).isoformat(),
                                                           nodes=[dict(node=f'0{i}', ok=True) for i in range(1, 5)])))
            seen = []

            def execute(job, deadline_seconds, cancel=None):
                seen.append(job['command'])
                return dict(deadline=False, cancelled=False, returncode=0)
            for arm in ('relay', 'replace'):
                with patch.object(relay_replay.closer_replay, 'HERE', root), patch.object(relay_replay, 'validate_source', lambda *a: None), \
                        patch.object(v, 'execute_cancellable', execute), \
                        patch.object(v, 'plan_of', lambda p: dict(plan={'moves': [1]}, verifier_solved=True, tokens=7, infra=0)), \
                        patch.object(v, 'judge_with_reason', lambda *a: dict(verdict=arm == 'relay', reason='', infra=0, tokens=1)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    code = relay_replay.main(['--runs', str(run), '--arm', arm, '--plan', str(root / 'plan.json'),
                                              '--admission', str(root / 'adm.json'), '--output', str(root / 'runs' / arm),
                                              '--source', d])
                self.assertEqual(code, 0, arm)
            recs = {arm: json.loads((root / 'runs' / arm / 'cases.jsonl').read_text()) for arm in ('relay', 'replace')}
            meta = json.loads((root / 'runs' / 'relay' / 'metadata.json').read_text())
        arms_seen = [next(x for x in c if x.endswith('.jsonl')) for c in seen]
        self.assertEqual(sum('-replace-a' in x for x in arms_seen), 2)  # replace: 2 workers, no accept
        self.assertIn(sum('-relay-a' in x for x in arms_seen), (1, 2))  # relay: the first accept may cancel the second
        self.assertEqual(recs['relay']['selected_source_slots'], recs['replace']['selected_source_slots'])
        self.assertTrue(recs['relay']['rescued'])
        self.assertFalse(recs['replace']['answered'])
        self.assertEqual(meta['protocol_sentence'], relay.PROTOCOL)


def arm_dir(root, arm, plan_file, rows, tokens=100, **meta_changes):
    d = root / arm
    d.mkdir()
    cohort = [[r['run'], r['task_id'], r['seed']] for r in rows]
    meta = dict(arm=arm, plan_sha256=hashlib.sha256(plan_file.read_bytes()).hexdigest(), relay_settings=dict(k=4),
                cohort=dict(cases=cohort), completed_utc='2026-11-24T01:00:00+00:00', stopped=False)
    meta.update(meta_changes)
    (d / 'metadata.json').write_text(json.dumps(meta))
    (d / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    nodes = ('01', '02', '03', '04')
    start = datetime(2026, 11, 24, tzinfo=timezone.utc)
    (d / 'arm_accounting.json').write_text(json.dumps(dict(
        protocol='swarm-arm-accounting-v1', runner_exit=0, idle_after=True, command=['python3', 'relay_replay.py'],
        runner_wall_seconds=60, before=dict(utc=start.isoformat(), nodes={n: dict(generation_tokens=0.0) for n in nodes}),
        after=dict(utc=(start + timedelta(seconds=60)).isoformat(), nodes={n: dict(generation_tokens=tokens / 4) for n in nodes}),
        server=dict(total=dict(generation_tokens=tokens),
                    per_node={n: dict(generation_tokens=tokens / 4, decode_tokens=tokens / 4, requests=2) for n in nodes}),
        energy=dict(total_wh=0.5))))
    return d


def case_row(task, rescued=False, wrong=False, faults=0, slots=(1, 2)):
    return dict(run='base', task_id=task, seed=1, arm='x', rescued=rescued, wrong=wrong, answered=rescued or wrong,
                faults=faults, workers=[{}] * len(slots), selected_source_slots=list(slots), client_tokens=10,
                artifact_chars_used=50)


class ReportTests(unittest.TestCase):
    def build(self, relay_rows, replace_rows, relay_meta=None, plan_text='{"decision_rule": "rule"}'):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            plan = root / 'plan.json'
            plan.write_text(plan_text)
            r = arm_dir(root, 'relay', plan, relay_rows, tokens=120, **(relay_meta or {}))
            p = arm_dir(root, 'replace', plan, replace_rows, tokens=100)
            s = report_relay.build(r, p, plan)
            with contextlib.redirect_stdout(io.StringIO()):
                code = report_relay.main(['--relay', str(r), '--replace', str(p), '--plan', str(plan), '--out', str(root / 'out')])
            md = (root / 'out' / 'REPORT.md').read_text()
        return s, code, md

    def test_complete_paired_mcnemar(self):
        relay_rows = [case_row('t0', rescued=True), case_row('t1', rescued=True), case_row('t2')]
        replace_rows = [case_row('t0'), case_row('t1', rescued=True), case_row('t2', wrong=True)]
        s, code, md = self.build(relay_rows, replace_rows)
        self.assertEqual((s['status'], code), ('complete', 0))
        self.assertEqual(s['mcnemar'], dict(cases=3, relay_only=1, replace_only=0, exact_p=1.0))
        self.assertEqual((s['facts']['relay_rescued'], s['facts']['replace_wrong']), (2, 1))
        self.assertEqual(s['facts']['server_token_ratio_relay_over_replace'], 1.2)
        self.assertEqual(s['decision_rule'], 'rule')
        self.assertIn('exact McNemar', md)

    def test_incomplete_inputs(self):
        ok = [case_row('t0'), case_row('t1')]
        for relay_rows, replace_rows, meta, msg in (
                ([case_row('t0', faults=1), case_row('t1')], ok, None, 'faulted'),
                (ok[:1], ok, None, 'different cohorts'),
                ([case_row('t0', slots=(3,)), case_row('t1')], ok, None, 'different selections'),
                (ok, ok, dict(plan_sha256='0' * 64), 'different plan'),
                (ok, ok, dict(stopped=True), 'stopped'),
                (ok, ok, dict(relay_settings=dict(k=2)), 'different relay settings')):
            s, code, md = self.build(relay_rows, replace_rows, meta)
            self.assertEqual((s['status'], code), ('incomplete', 3), msg)
            self.assertIn(msg, json.dumps(s), msg)
            self.assertNotIn('mcnemar', s, msg)


if __name__ == '__main__':
    unittest.main()
