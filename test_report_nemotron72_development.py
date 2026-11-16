"""Synthetic selector/telemetry fixtures only; no live cohort outcomes or statistics."""
from contextlib import redirect_stdout
import copy,io,json
from pathlib import Path
import unittest
from unittest.mock import patch
import report_nemotron72_development as r


def matrix(successes=None):
    scores=successes or{};rows=[]
    for arm in r.VARIANTS:
        for task in range(8):
            for seed in (1,2,3):
                index=task*3+seed-1
                rows.append(dict(task_id='authored-'+str(task),seed=seed,arm=arm,solved=index<scores.get(arm,0),calls=1,completed_calls=1,unfinished_calls=0,missing_prompt_usage=0,prompt_tokens=10,completion_tokens=5,server_cost_known=True,server_idle_after=True,server_prompt_tokens=20,server_completion_tokens=100))
    return rows


class DevelopmentReportTests(unittest.TestCase):
    def test_default_plan_never_reads_partial_outcomes_network_or_runs_stats(self):
        with patch.object(r,'read')as read,patch.object(r,'validate')as validate,patch.object(r.ag,'report_for')as stats,redirect_stdout(io.StringIO())as out:
            self.assertEqual(r.main(['/does-not-exist']),0);self.assertFalse(json.loads(out.getvalue())['outcomes_read'])
            read.assert_not_called();validate.assert_not_called();stats.assert_not_called()

    def test_strict_improvement_and_baseline_at_ceiling_or_tied(self):
        for scores in ({},{a:24 for a in r.VARIANTS},{'index_original':3,'scribe_full':3}):
            chosen=r.select(matrix(scores));self.assertEqual(chosen['selected_variant'],'index_original');self.assertFalse(chosen['strict_improvement'])
        chosen=r.select(matrix({'index_original':3,'value_explicit':4}));self.assertEqual(chosen['selected_variant'],'value_explicit');self.assertTrue(chosen['strict_improvement'])

    def test_ties_use_server_then_input_only_with_global_complete_coverage(self):
        rows=matrix({'index_original':2,'index_explicit':4,'value_original':4})
        for row in rows:
            if row['arm']=='value_original':row['server_completion_tokens']=20;row['prompt_tokens']=15
        self.assertEqual(r.select(rows)['selected_variant'],'value_original')
        # One unrelated arm's unknown server cost skips the ENTIRE server tier.
        next(x for x in rows if x['arm']=='scribe_empty')['server_cost_known']=False
        decision=r.select(rows);self.assertEqual(decision['selected_variant'],'index_explicit');self.assertFalse(decision['global_server_completion_tier_used']);self.assertTrue(decision['global_client_input_tier_used']);self.assertTrue(all(v is None for v in decision['server_completion_totals'].values()))
        # Missing input in an unrelated arm skips the ENTIRE input tier too.
        next(x for x in rows if x['arm']=='scribe_tail')['missing_prompt_usage']=1
        decision=r.select(rows);self.assertEqual(decision['selected_variant'],'index_explicit');self.assertFalse(decision['global_client_input_tier_used']);self.assertTrue(all(v is None for v in decision['client_input_totals'].values()))

    def test_nonfinite_stale_counters_or_unfinished_input_are_not_zero_cost(self):
        rows=matrix({'index_original':1,'index_explicit':3,'value_original':3})
        for row in rows:
            if row['arm']=='value_original':row['prompt_tokens']=1
        for value in (None,float('nan'),-1,0):
            changed=copy.deepcopy(rows);changed[-1]['server_completion_tokens']=value
            decision=r.select(changed);self.assertFalse(decision['global_server_completion_tier_used']);self.assertEqual(decision['selected_variant'],'value_original')
        rows[-1]['server_cost_known']=False;rows[-1]['unfinished_calls']=1;rows[-1]['completed_calls']=0
        decision=r.select(rows);self.assertFalse(decision['global_client_input_tier_used']);self.assertEqual(decision['selected_variant'],'index_explicit')

    def test_incomplete_duplicate_foreign_seed_and_unknown_outcome_fail_closed(self):
        good=matrix()
        for kind in ('missing','duplicate','seed','unknown'):
            rows=copy.deepcopy(good)
            if kind=='missing':rows.pop()
            if kind=='duplicate':rows[-1]=rows[0]
            if kind=='seed':rows[-1]['seed']=4
            if kind=='unknown':rows[-1]['solved']=None
            with self.subTest(kind=kind),self.assertRaises(ValueError):r.select(rows)

    def test_complete_and_audit_gate_precedes_any_summary_or_trace_read(self):
        complete=dict(completed_cases=168,attempts=168,incomplete=False,errors=[],source_changed_during_run=False,completed_utc='AUTHORED')
        for metadata,audit in [(dict(complete,completed_cases=167),{}),(dict(complete,errors=['fault']),{}),(complete,dict(verified=False))]:
            with patch.object(r,'read',side_effect=[metadata,audit])as read:
                with self.assertRaises(ValueError):r.validate(Path('/absent'),Path('/audit'))
                self.assertEqual(read.call_count,2)

    def test_scribe_denominator_includes_unfinished_commit_and_distinguishes_parsed_empty(self):
        row=dict(task_id='toy',seed=1,arm='scribe_full',solved=False,deadline=True)
        first=dict(type='request_end',stage='plan',response=None,reasoning='own reasoning',response_received=True,finish_reason='length')
        unfinished=[first,dict(type='request_start',stage='scribe')];metrics=r.secondary(row,unfinished)
        self.assertTrue(metrics['eligible_commit']);self.assertTrue(metrics['commit_dispatched']);self.assertFalse(metrics['commit_completed']);self.assertFalse(metrics['eligible_verified_conversion'])
        parsed=copy.deepcopy(first);parsed['response']='{}';self.assertFalse(r.secondary(row,[parsed])['eligible_commit'])
        absent=r.secondary(row,[]);self.assertIsNone(absent['eligible_commit']);self.assertIsNone(absent['first_parser_none'])
        successful=r.secondary(dict(row,solved=True,deadline=False),unfinished+[dict(type='request_end',stage='scribe',finish_reason='stop'),dict(type='puzzle_end')]);self.assertTrue(successful['eligible_verified_conversion'])

if __name__=='__main__':unittest.main()
