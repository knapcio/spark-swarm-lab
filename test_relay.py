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
        self.assertEqual(relay.PROTOCOL, 'Another solver worked on this exact task and did not reach an accepted answer. '
                         'Its work is below; it may contain mistakes. Use whatever is correct in it, finish the task, and '
                         'give your answer in the required format.')

    def test_worker_seeds_are_unique_and_arm_independent(self):
        s = relay.settings({})
        seeds = {relay.worker_seed(arm, s, run, task, seed, slot)
                 for arm in relay.ARMS for run in ('a', 'b') for task in ('t0', 't1') for seed in (1, 2) for slot in range(200, 204)}
        self.assertEqual(len(seeds), 2 * 2 * 2 * 2 * 4)
        self.assertEqual(relay.worker_seed('relay', s, 'a', 't0', 1, 200), relay.worker_seed('relay', s, 'a', 't0', 1, 200))
        self.assertTrue(all(0 <= x < 2 ** 31 for x in seeds))

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

    def test_dense_window_skips_a_repetitive_tail(self):
        import random as _r
        rng = _r.Random(7)
        prose = ''.join(rng.choice('abcdefghijklmnopqrstuvwxyz ,.0123456789') for _ in range(30000))
        loop = 'Wait, check again. ' * 2000  # 38,000 chars of a repetition loop at the end
        text = prose + loop
        self.assertLess(relay.zlib_ratio(text[-12000:]), relay.DENSE_MIN_RATIO)
        window, offset = relay.dense_window(text, 12000)
        self.assertEqual(len(window), 12000)
        self.assertGreaterEqual(relay.zlib_ratio(window), relay.DENSE_MIN_RATIO)
        self.assertEqual(offset % relay.DENSE_STEP, 0)
        self.assertEqual(window, text[len(text) - offset - 12000:len(text) - offset])
        self.assertTrue(text.startswith(prose) and offset > 0)
        # latest qualifying window: stepping back stops at the first window that is dense enough
        self.assertLess(relay.zlib_ratio(text[len(text) - offset + relay.DENSE_STEP - 12000:len(text) - offset + relay.DENSE_STEP]),
                        relay.DENSE_MIN_RATIO)
        self.assertEqual(relay.excerpt(text, 12000, 'dense'), window)
        self.assertEqual(relay.excerpt(text, 12000, 'tail'), text[-12000:])

    def test_dense_window_falls_back_to_the_tail(self):
        loop = 'same line again\n' * 5000
        self.assertEqual(relay.dense_window(loop, 12000), (loop[-12000:], 0))  # nothing dense: tail
        self.assertEqual(relay.dense_window('short text', 12000), ('short text', 0))
        prose = 'a dense and varied text with many words 0123 ' * 10
        self.assertEqual(relay.relay_extra(prose, 50, 'dense'), relay.PROTOCOL + '\n\n' + relay.dense_window(prose, 50)[0])

    def test_window_setting(self):
        self.assertEqual(relay.settings({})['window'], 'tail')
        self.assertEqual(relay.settings(dict(relay=dict(window='dense')))['window'], 'dense')
        with self.assertRaisesRegex(ValueError, 'relay.window'):
            relay.settings(dict(relay=dict(window='middle')))

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
                                v.ENDPOINTS, s, run_name='base')
        return rec, seen

    def test_relay_workers_get_protocol_plus_artifact(self):
        rec, seen = self.run_arm('relay', fast={200, 201, 202}, accept=set())
        self.assertEqual(sorted(seen), [200, 201, 202])
        self.assertEqual(seen[200]['extra'], relay.PROTOCOL + '\n\nwork of 7')
        self.assertEqual(seen[201]['extra'], relay.PROTOCOL + '\n\nwork of 2')
        s = relay.settings(dict(seed_offsets=dict(relay=19000, replace=19500)))
        self.assertEqual([seen[x]['seed'] for x in (200, 201, 202)],
                         [relay.worker_seed('relay', s, 'base', 't0', 2, x) for x in (200, 201, 202)])
        self.assertEqual([w['source_slot'] for w in rec['workers']], [7, 2, 9])
        self.assertEqual((rec['rescued'], rec['wrong'], rec['artifact_chars_used'], rec['client_tokens']), (False, False, 180, 36))

    def test_replace_workers_equal_count_no_artifact(self):
        rec, seen = self.run_arm('replace', fast={300, 301, 302}, accept=set())
        self.assertEqual(sorted(seen), [300, 301, 302])
        self.assertTrue(all(x['extra'] == '' for x in seen.values()))
        s = relay.settings(dict(seed_offsets=dict(relay=19000, replace=19500)))
        self.assertEqual([seen[x]['seed'] for x in (300, 301, 302)],
                         [relay.worker_seed('replace', s, 'base', 't0', 2, x) for x in (300, 301, 302)])
        self.assertEqual(rec['artifact_chars_used'], 0)

    def test_first_accept_wins_and_cancels_within_the_arm(self):
        rec, seen = self.run_arm('relay', fast={201}, accept={201}, solved={201})
        self.assertEqual((rec['selected_slot'], rec['rescued'], rec['wrong']), (201, True, False))
        self.assertEqual(rec['cancelled_workers'] + rec['unstarted_workers'], 2)
        rec, _ = self.run_arm('replace', fast={300, 301, 302}, accept={302}, solved=())
        self.assertEqual((rec['selected_slot'], rec['rescued'], rec['wrong']), (302, False, True))


def write_recorded_run(root, name='base', abstain_t1=False):
    """A recorded roll12cancel arm: t0 abstained (3 failed agents with traces), t1 answered (or abstained)."""
    tasks = [dict(id=f't{i}', split='evaluation', numbers=[1, 2, 3, 4, 5, 6], target=99) for i in range(2)]
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=tasks)))
    run = root / 'runs' / name
    (run / 'agents').mkdir(parents=True)
    plan = dict(dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=2, seeds=[1],
                agent_variant='xl_forced_original', policies=['roll12cancel'])
    (run / 'metadata.json').write_text(json.dumps(dict(protocol=plan, policies=['roll12cancel'], resume=None)))
    rows = [dict(task_id='t0', seed=1, policy='roll12cancel', answered=False, infra=0, agents=[agent(s) for s in range(3)]),
            dict(task_id='t1', seed=1, policy='roll12cancel', answered=not abstain_t1, infra=0,
                 agents=[agent(s) for s in range(3)] if abstain_t1 else [agent(0, True)])]
    (run / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    for s in range(3):
        trace(run / 'agents' / f't0-s1-roll12cancel-a{s}.jsonl', f'{name} work {s} ' * 10)
        if abstain_t1:
            trace(run / 'agents' / f't1-s1-roll12cancel-a{s}.jsonl', f'{name} t1 work {s} ' * 10)
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
                                                  dense_window_differs=0, relay_workers=2, replace_workers=2))
        self.assertEqual(lines[-2]['summary']['chars_used_max'], 20)

    def test_dedupe_across_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = write_recorded_run(root, 'first')
            b = write_recorded_run(root, 'second', abstain_t1=True)
            out = {}
            for flags in ([], ['--no-dedupe']):
                buf = io.StringIO()
                with patch.object(relay_replay.closer_replay, 'HERE', root), contextlib.redirect_stdout(buf):
                    relay_replay.main(['--runs', str(a), str(b), '--plan-only'] + flags)
                lines = [json.loads(x) for x in buf.getvalue().splitlines()]
                out[bool(flags)] = lines
        cases = [(x['run'], x['task_id']) for x in out[False] if 'task_id' in x]
        self.assertEqual(cases, [('first', 't0'), ('second', 't1')])  # t0 from the first run listed only
        self.assertEqual((out[False][-1]['dropped_duplicates'], out[False][-1]['distinct_puzzles']), (1, 2))
        self.assertEqual(len([x for x in out[True] if 'task_id' in x]), 3)

    def test_window_override_must_be_frozen_in_the_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = write_recorded_run(root)
            (root / 'plan.json').write_text(json.dumps(dict(relay=dict(k=2))))
            with patch.object(relay_replay.closer_replay, 'HERE', root), self.assertRaisesRegex(Exception, 'not frozen'):
                relay_replay.main(['--runs', str(run), '--plan-only', '--plan', str(root / 'plan.json'), '--window', 'dense'])
            (root / 'plan.json').write_text(json.dumps(dict(relay=dict(k=2, windows=['tail', 'dense']))))
            buf = io.StringIO()
            with patch.object(relay_replay.closer_replay, 'HERE', root), contextlib.redirect_stdout(buf):
                relay_replay.main(['--runs', str(run), '--plan-only', '--plan', str(root / 'plan.json'), '--window', 'dense'])
            self.assertEqual(json.loads(buf.getvalue().splitlines()[-1])['window'], 'dense')

    def test_changed_only_keeps_positions_and_drops_unchanged_cases(self):
        import random as _r
        rng = _r.Random(3)
        prose = ''.join(rng.choice('abcdefghijklmnopqrstuvwxyz ,.0123456789') for _ in range(6000))
        looped = prose + 'loop again. ' * 2000  # long repetitive tail: the dense window moves back
        cp = dict(failed_agents=3, candidates=3,
                  selected=[dict(source_slot=s, chars=len(t), chars_used=100, text=t)
                            for s, t in ((5, prose[:90]), (2, looped), (7, looped + 'x'))])
        out = relay.changed_only(cp, 2000)
        self.assertEqual([(x['source_slot'], x['position']) for x in out['selected']], [(2, 1), (7, 2)])
        self.assertEqual(out['selected_before_changed_only'], 3)
        self.assertTrue(relay.window_changes(looped, 2000))
        self.assertFalse(relay.window_changes(prose[:90], 2000))
        # the worker slot (and so the seed) is its position in the full selection
        rec_full, seen_full = RunArmTests().run_arm('relay', fast={200, 201, 202}, accept=set())
        cp_full = RunArmTests.CP
        positions = [dict(x, position=i) for i, x in enumerate(cp_full['selected'])][1:]
        RunArmTests.CP = dict(cp_full, selected=positions)
        try:
            rec_c, seen_c = RunArmTests().run_arm('relay', fast={201, 202}, accept=set())
        finally:
            RunArmTests.CP = cp_full
        self.assertEqual(sorted(seen_c), [201, 202])
        self.assertEqual({k: v['seed'] for k, v in seen_c.items()}, {k: seen_full[k]['seed'] for k in (201, 202)})

    def test_changed_only_must_be_frozen(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = write_recorded_run(root)
            (root / 'plan.json').write_text(json.dumps(dict(relay=dict(k=2))))
            with patch.object(relay_replay.closer_replay, 'HERE', root), self.assertRaisesRegex(Exception, 'not frozen'):
                relay_replay.main(['--runs', str(run), '--plan-only', '--plan', str(root / 'plan.json'), '--changed-only'])
            (root / 'plan.json').write_text(json.dumps(dict(relay=dict(k=2, max_chars=20, changed_only=True))))
            buf = io.StringIO()
            with patch.object(relay_replay.closer_replay, 'HERE', root), contextlib.redirect_stdout(buf):
                relay_replay.main(['--runs', str(run), '--plan-only', '--plan', str(root / 'plan.json'), '--changed-only'])
            last = json.loads(buf.getvalue().splitlines()[-1])
        # the recorded artifacts ('base work N ' * 10) are not repetitive enough to move: the case is dropped
        self.assertEqual((last['changed_only'], last['dropped_unchanged_cases'], last['total']['cases']), (True, 1, 0))

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
    arm = meta_changes.pop('meta_arm', arm)
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
        server=dict(total=dict(generation_tokens=tokens, prompt_tokens=10 * tokens, prefill_compute_tokens=4 * tokens),
                    per_node={n: dict(generation_tokens=tokens / 4, decode_tokens=tokens / 4, requests=2) for n in nodes}),
        energy=dict(total_wh=0.5))))
    return d


def case_row(task, rescued=False, wrong=False, faults=0, slots=(1, 2), seed=1, workers=None):
    return dict(run='base', task_id=task, seed=seed, arm='x', rescued=rescued, wrong=wrong, answered=rescued or wrong,
                faults=faults, workers=workers if workers is not None else [{}] * len(slots),
                selected_source_slots=list(slots), client_tokens=10, artifact_chars_used=50)


class ReportTests(unittest.TestCase):
    def build(self, relay_rows, replace_rows, relay_meta=None, plan_text='{"decision_rule": "rule"}', frozen=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            plan = root / 'plan.json'
            plan.write_text(plan_text)
            cl = root / 'cases.json'
            cl.write_text(json.dumps(dict(cases=frozen if frozen is not None else
                                          [[r['run'], r['task_id'], r['seed']] for r in replace_rows])))
            r = arm_dir(root, 'relay', plan, relay_rows, tokens=120, **(relay_meta or {}))
            p = arm_dir(root, 'replace', plan, replace_rows, tokens=100)
            s = report_relay.build(r, p, plan, cl)
            with contextlib.redirect_stdout(io.StringIO()):
                code = report_relay.main(['--relay', str(r), '--replace', str(p), '--plan', str(plan), '--case-list', str(cl),
                                          '--out', str(root / 'out')])
            md = (root / 'out' / 'REPORT.md').read_text()
        return s, code, md

    def test_complete_paired_mcnemar(self):
        relay_rows = [case_row('t0', rescued=True), case_row('t1', rescued=True), case_row('t2')]
        replace_rows = [case_row('t0'), case_row('t1', rescued=True), case_row('t2', wrong=True)]
        s, code, md = self.build(relay_rows, replace_rows)
        self.assertEqual((s['status'], code), ('complete', 0))
        self.assertEqual(s['mcnemar'], dict(cases=3, distinct_puzzles=3, relay_only=1, replace_only=0, exact_p=1.0,
                                            note='cases are distinct puzzles'))
        R = s['arms']['relay']
        self.assertEqual((R['generation_tokens'], R['prompt_tokens'], R['prefill_compute_tokens'], R['total_compute_tokens'],
                          R['total_tokens_incl_cached_prompt']), (120, 1200, 480, 600, 1320))
        self.assertEqual(s['facts']['compute_token_ratio_relay_over_replace'], 1.2)
        self.assertEqual((s['facts']['relay_rescued'], s['facts']['replace_wrong']), (2, 1))
        self.assertEqual(s['facts']['server_token_ratio_relay_over_replace'], 1.2)
        self.assertEqual(s['decision_rule'], 'rule')
        self.assertIn('exact McNemar', md)

    def test_repeated_puzzles_make_the_test_descriptive(self):
        rows = [case_row('t0', rescued=True, seed=1), case_row('t0', seed=2)]
        s, code, md = self.build(rows, [case_row('t0', seed=1), case_row('t0', seed=2)])
        self.assertEqual((s['mcnemar']['cases'], s['mcnemar']['distinct_puzzles']), (2, 1))
        self.assertIn('descriptive only', s['mcnemar']['note'])
        self.assertIn('descriptive only', md)

    def test_cohort_must_equal_the_frozen_case_list(self):
        ok = [case_row('t0'), case_row('t1')]
        s, code, _ = self.build(ok, ok, frozen=[['base', 't0', 1], ['base', 't1', 1], ['base', 't2', 1]])
        self.assertEqual((s['status'], code), ('incomplete', 3))
        self.assertIn('frozen case list (1 missing', json.dumps(s))

    def test_window_screen(self):
        tail = [case_row('t0'), case_row('t1', rescued=True), case_row('t2')]
        dense = [case_row('t0', rescued=True), case_row('t1', rescued=True), case_row('t2', rescued=True)]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            plan = root / 'plan.json'
            plan.write_text('{"decision_rule": "dense if >= 5 of 73"}')
            cl = root / 'cases.json'
            cl.write_text(json.dumps(dict(cases=[[r['run'], r['task_id'], r['seed']] for r in tail])))
            t = arm_dir(root, 'tail', plan, tail, relay_settings=dict(k=4, window='tail', changed_only=True), meta_arm='relay')
            x = arm_dir(root, 'dense', plan, dense, relay_settings=dict(k=4, window='dense', changed_only=True), meta_arm='relay')
            s = report_relay.build(t, x, plan, cl, mode='window')
            with contextlib.redirect_stdout(io.StringIO()):
                code = report_relay.main(['--tail', str(t), '--dense', str(x), '--plan', str(plan), '--case-list', str(cl),
                                          '--out', str(root / 'out')])
            md = (root / 'out' / 'REPORT.md').read_text()
            bad = report_relay.build(t, t, plan, cl, mode='window')  # both arms tail
        self.assertEqual((s['status'], code), ('complete', 0))
        self.assertEqual((s['mcnemar']['tail_only'], s['mcnemar']['dense_only']), (0, 2))
        self.assertEqual(s['facts']['rescues_per_window'], dict(tail=1, dense=3))
        self.assertIn('tail window vs dense window', md)
        self.assertEqual(bad['status'], 'incomplete')
        self.assertIn('relay windows are', json.dumps(bad))

    def test_window_screen_changed_subset_counts_and_pairing(self):
        def w(slot, seed, verdict=None, started=True):
            return dict(slot=slot, agent_seed=seed, verdict=verdict, started=started)
        tail = [case_row('t0', workers=[w(200, 11), w(201, 12)]), case_row('t1', rescued=True, workers=[w(200, 21, True), w(201, 22)])]
        dense = [case_row('t0', rescued=True, workers=[w(200, 11, True), w(201, 12, started=False)]),
                 case_row('t1', rescued=True, workers=[w(200, 21, True), w(201, 22)])]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            plan = root / 'plan.json'
            plan.write_text('{}')
            cl = root / 'cases.json'
            cl.write_text(json.dumps(dict(cases=[[r['run'], r['task_id'], r['seed']] for r in tail])))
            st = dict(k=4, changed_only=True)
            t = arm_dir(root, 'tail', plan, tail, relay_settings=dict(st, window='tail'), meta_arm='relay',
                        endpoints=['a'], max_per_endpoint=8)
            x = arm_dir(root, 'dense', plan, dense, relay_settings=dict(st, window='dense'), meta_arm='relay',
                        endpoints=['a'], max_per_endpoint=8)
            s = report_relay.build(t, x, plan, cl, mode='window')
            # mismatched seeds / caps
            dense_bad = [case_row('t0', workers=[w(200, 99), w(201, 12)]), dense[1]]
            xb = arm_dir(root, 'dense_bad', plan, dense_bad, relay_settings=dict(st, window='dense'), meta_arm='relay',
                         endpoints=['a'], max_per_endpoint=4)
            bad = report_relay.build(t, xb, plan, cl, mode='window')
        f = s['facts']
        self.assertEqual(s['status'], 'complete')
        self.assertEqual((f['changed_workers'], f['changed_workers_started_in_both']), (4, 3))
        self.assertEqual(f['accepted_workers'], dict(tail=1, dense=2))
        self.assertEqual(f['accepted_workers_started_in_both'], dict(tail=1, dense=2))
        self.assertEqual(bad['status'], 'incomplete')
        self.assertIn('worker slots or seeds differ', json.dumps(bad))
        self.assertIn('different max_per_endpoint', json.dumps(bad))

    def test_relay_vs_replace_accepts_arms_recorded_before_the_update(self):
        old_rows = [case_row('t0', rescued=True), case_row('t1')]  # no worker_positions (recorded before the update)
        new_rows = [dict(case_row('t0'), worker_positions=[0, 1]), dict(case_row('t1'), worker_positions=[0, 1])]
        s, code, _ = self.build(old_rows, new_rows)
        self.assertEqual((s['status'], code), ('complete', 0))
        moved = [dict(case_row('t0', rescued=True), worker_positions=[0, 2]), dict(case_row('t1'), worker_positions=[0, 1])]
        s, code, _ = self.build(moved, new_rows)  # both recorded the field and it differs: incomplete
        self.assertEqual(s['status'], 'incomplete')

    def test_window_screen_needs_changed_only_and_identical_workers(self):
        rows = [case_row('t0'), case_row('t1')]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            plan = root / 'plan.json'
            plan.write_text('{}')
            cl = root / 'cases.json'
            cl.write_text(json.dumps(dict(cases=[[r['run'], r['task_id'], r['seed']] for r in rows])))
            t = arm_dir(root, 'tail', plan, rows, relay_settings=dict(k=4, window='tail', changed_only=False), meta_arm='relay')
            x = arm_dir(root, 'dense', plan, rows, relay_settings=dict(k=4, window='dense', changed_only=False), meta_arm='relay')
            s = report_relay.build(t, x, plan, cl, mode='window')
            self.assertIn('needs both arms run with relay.changed_only', json.dumps(s))
            moved = [dict(case_row('t0'), worker_positions=[0, 1]), dict(case_row('t1'), worker_positions=[1, 3])]
            same = [dict(case_row('t0'), worker_positions=[0, 1]), dict(case_row('t1'), worker_positions=[1, 2])]
            t2 = arm_dir(root, 'tail2', plan, moved, relay_settings=dict(k=4, window='tail', changed_only=True), meta_arm='relay')
            x2 = arm_dir(root, 'dense2', plan, same, relay_settings=dict(k=4, window='dense', changed_only=True), meta_arm='relay')
            s2 = report_relay.build(t2, x2, plan, cl, mode='window')
        self.assertEqual(s2['status'], 'incomplete')
        self.assertIn('1 case(s) with different selections or worker counts', json.dumps(s2))

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
