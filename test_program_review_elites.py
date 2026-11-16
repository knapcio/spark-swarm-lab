"""Authored offline fixtures only; no generated source is executed locally."""
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

import program_search as p
from harness import Budget
from test_program_search import DEV, EVAL, CODE, Events, report


class Client:
    def __init__(self, fail_review=False, empty_review=False):
        self.budget, self.calls, self.finished = Budget(16, 32768), [], []
        self.lock = threading.Lock()
        self.system_prompt = p.SYSTEM
        self.infra_failures = self.budget_failures = 0
        self.fail_review, self.empty_review = fail_review, empty_review
    def call(self, agent, stage, prompt, **context):
        assert self.budget.reserve(2048)
        with self.lock:
            self.calls.append(dict(agent=agent, stage=stage, prompt=prompt, system=self.system_prompt,
                                   previous_finished=list(self.finished), **context))
        if stage.startswith('review-'):
            if self.fail_review: self.infra_failures += 1
            value = p.parse_program(None if self.empty_review else 'Unverified suggestion: try a different ordering.', stage)
        else:
            value = p.parse_program(CODE + f"# candidate {context['candidate_index']}\n", stage)
        self.budget.settle(2048, 10)
        with self.lock: self.finished.append(stage)
        return value


class ReviewElitesTests(unittest.TestCase):
    def episode(self, directory, client=None, evaluator=None):
        client, events = client or Client(), Events()
        grades = []
        def evaluate(code, task, host, timeout):
            grades.append((task['id'], code))
            if task['id'].startswith('eval_'):
                self.assertEqual(len(client.finished), 16)
                selection = json.loads((Path(directory)/'selection.json').read_text())
                self.assertFalse(selection['evaluation_seen'])
            return evaluator(code, task) if evaluator else report(task)
        result = p.run_episode(DEV, EVAL, p.REVIEW_ARM, 1, 'Spark_01', client, events, directory, evaluate)
        return result, client, events, grades

    def test_allocation_barriers_and_no_early_success_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            result, client, events, grades = self.episode(directory)
            self.assertTrue(result['complete'])
            authors = [c for c in client.calls if c['stage'].startswith('program-')]
            reviews = [c for c in client.calls if c['stage'].startswith('review-')]
            self.assertEqual((len(authors), len(reviews), len(grades)), (10, 6, 52))
            self.assertEqual(result['model_budget']['calls'], 16)
            self.assertEqual(result['selected_candidate_index'], 0)
            self.assertEqual(result['training_candidates_scored'], 10)
            for call in reviews:
                self.assertEqual(call['system'], p.REVIEW_SYSTEM)
                self.assertEqual(call['candidate_index'], None)
            for call in authors:
                self.assertEqual(call['system'], p.SYSTEM)
                if call['candidate_index'] >= 4:
                    generation = (call['candidate_index']-4)//2 + 1
                    required = [r['stage'] for r in reviews if r['review_id'].startswith(f'r{generation}-')]
                    self.assertTrue(set(required) <= set(call['previous_finished']))
            selected = next(i for i,r in enumerate(events.rows) if r['type']=='program_selected')
            self.assertTrue(all(i>selected for i,r in enumerate(events.rows)
                                if r['type']=='program_grade_start' and r['phase']=='evaluation'))
            self.assertEqual(client.system_prompt, p.SYSTEM)

    def test_bottom_context_reviews_top_candidate_then_target_repairs(self):
        def evaluate(code, task):
            index = int(re.search(r'# candidate (\d+)', code).group(1))
            return report(task, solved=index in [1,3,5,7,9])
        with tempfile.TemporaryDirectory() as directory:
            result, client, events, _ = self.episode(directory, evaluator=evaluate)
            self.assertTrue(result['complete'])
            self.assertEqual(result['selected_candidate_index'], 1)  # Earliest best development tie.
            reviews = [c for c in client.calls if c['stage'].startswith('review-')]
            self.assertEqual([(c['reviewer_candidate_index'],c['target_candidate_index']) for c in reviews[:2]], [(0,1),(2,3)])
            for review in reviews:
                codes = re.findall(r'# candidate (\d+)', review['prompt'])
                self.assertEqual(codes, [str(review['reviewer_candidate_index']), str(review['target_candidate_index'])])
                repair = next(c for c in client.calls if c.get('review_id')==review['review_id'] and c['stage'].startswith('program-'))
                self.assertEqual(repair['previous_candidate_index'], review['target_candidate_index'])
                self.assertEqual(re.findall(r'# candidate (\d+)',repair['prompt']), [str(review['target_candidate_index'])])
                self.assertIn('Unverified peer critique', repair['prompt'])
            self.assertTrue(all(r['critique_verified'] is False for r in events.rows if r['type']=='program_review'))
            for call in client.calls:
                for task in EVAL: self.assertNotIn(task['id'],call['prompt'])
            populations=[r for r in events.rows if r['type']=='review_population_selected']
            self.assertEqual(len(populations),3)
            self.assertTrue(all(len(r['retained_indices'])==4 and len(r['not_retained_indices'])==2 for r in populations))

    def test_review_error_halts_before_repair_or_final_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            result, client, _, grades = self.episode(directory, client=Client(True))
            self.assertFalse(result['complete'])
            self.assertEqual(len(client.calls),6)
            self.assertEqual(result['evaluation_completed'],0)
            self.assertEqual(len(grades),16)
            self.assertFalse((Path(directory)/'selection.json').exists())
            self.assertEqual(client.system_prompt,p.SYSTEM)

    def test_shared_stop_during_joined_critics_prevents_all_repairs(self):
        stop, critics_started = threading.Event(), threading.Barrier(2)
        class PeerFaultClient(Client):
            def call(self, agent, stage, prompt, **context):
                result = super().call(agent, stage, prompt, **context)
                if stage.startswith('review-'):
                    critics_started.wait(timeout=2)
                    stop.set()  # Another episode faults while this review batch is in flight.
                return result
        with tempfile.TemporaryDirectory() as directory:
            client, events, grades = PeerFaultClient(), Events(), []
            def evaluate(code, task, host, timeout):
                grades.append(task['id']); return report(task)
            result = p.run_episode(DEV,EVAL,p.REVIEW_ARM,1,'Spark_01',client,events,
                                   directory,evaluate,stop)
            self.assertTrue(stop.is_set())
            self.assertFalse(result['complete'])
            self.assertEqual(len(client.calls),6)
            self.assertEqual(sum(c['stage'].startswith('program-') for c in client.calls),4)
            self.assertEqual(sum(c['stage'].startswith('review-') for c in client.calls),2)
            self.assertEqual(len(grades),16)
            self.assertEqual(result['evaluation_completed'],0)
            self.assertFalse((Path(directory)/'selection.json').exists())
            self.assertFalse((Path(directory)/'selected.py').exists())
            self.assertEqual(client.system_prompt,p.SYSTEM)

    def test_empty_critiques_are_spent_without_retries_or_extra_authors(self):
        with tempfile.TemporaryDirectory() as directory:
            result, client, events, _ = self.episode(directory, client=Client(empty_review=True))
            self.assertTrue(result['complete'])
            self.assertEqual(len(client.calls),16)
            self.assertEqual(sum(c['stage'].startswith('program-') for c in client.calls),10)
            reviews=[r for r in events.rows if r['type']=='program_review']
            self.assertEqual(len(reviews),6)
            self.assertTrue(all(r['raw'] is None and r['critique']=='' for r in reviews))

    def test_plaintext_critique_parser_is_bounded_not_code_or_fact_verifier(self):
        value=p.parse_program('not Python! '+ 'x'*9000,'review-fixture')
        self.assertEqual(len(value['critique']),8192)
        self.assertTrue(value['truncated'])
        self.assertNotIn('code',value)
        self.assertIsNotNone(p.parse_program('not Python!','program-0')['parse_error'])

    def test_default_plan_does_not_read_live_gate_or_run_grading(self):
        with patch.object(p,'followup_gate',side_effect=AssertionError('live gate')), \
             patch.object(p,'run_master',side_effect=AssertionError('live grading')), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(p.main([]),0)
        plan=json.loads(out.getvalue())
        self.assertEqual(plan['planned_selected_programs'],4)
        self.assertEqual(plan['planned_evaluation_results'],48)
        self.assertTrue(all(row['arms']==[p.REVIEW_ARM] for row in plan['pairs']))
        self.assertEqual(plan['limits'],p.LIMITS)
        self.assertEqual(plan['mode'],'plan')


if __name__=='__main__': unittest.main()
