"""Confirmation runner offline tests: fake evaluator only; never remote/model calls."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import confirm_coding as c

class ConfirmationTests(unittest.TestCase):
 def job(self,i=0):return dict(job_id=str(i),code_sha256='a'*64,code='def f(x): return x',function_name='f',phase='original_holdout',test_sha256='b'*64,tests=[dict(args=[1],expected=1)],chunk_start=0)
 def report(self,**kw):
  r=dict(status='passed',passed=1,failed=0,total=1,tests_run=1,provenance='candidate',cleanup_ok=True,grading_authority='outer_parent',oracle_sent_to_child=False);r.update(kw);return r
 def test_plan_validates_all_frozen_cases_without_grading_or_gate(self):
  with patch.object(c.grader,'evaluate_code')as remote,patch.object(c,'verify_gate')as gate,contextlib.redirect_stdout(io.StringIO())as output:
   self.assertEqual(c.main([]),0)
  plan=json.loads(output.getvalue());self.assertEqual((plan['selected_cases'],plan['selected_artifacts']),(324,323));self.assertEqual(plan['mode'],'plan');remote.assert_not_called();gate.assert_not_called()
 def test_run_is_fail_closed_before_any_remote_evaluation(self):
  with patch.object(c,'verify_gate',side_effect=RuntimeError('45 cohorts not verified')),patch.object(c.grader,'evaluate_code')as remote:
   with self.assertRaisesRegex(RuntimeError,'45'):c.main(['--run','--output','/tmp/NEVER-CREATED'])
  remote.assert_not_called()
 def test_cache_references_keep_named_phases_separate(self):
  cases,jobs,probes=c.prepare(c.HERE,c.HERE/'results/correctness-audit-20261115/selected-primary-scan-index.json',c.HERE/'datasets/coding-v1/tasks.json',c.HERE/'datasets/coding-v1/hidden-tests.json')
  self.assertEqual(len(cases),324);self.assertLess(len(jobs),323*4);self.assertEqual(len({j['job_id']for j in jobs}),len(jobs));self.assertTrue(all(len(j['tests'])<=128 for j in jobs));self.assertEqual(set(j['phase']for j in jobs),set(c.PHASES));self.assertEqual(probes['eva-balanced_brackets'][0]['expected'],False)
  missing=[r for r in c.summarize(cases,{})if r['selected_code_sha256']is None];self.assertEqual(len(missing),1);self.assertIsNone(missing[0]['phases']['original_holdout']['passed'])
 def test_fixed_slots_record_full_report_and_stop_on_infrastructure(self):
  calls=[]
  def fake(code,name,tests,host,timeout):calls.append(host);return self.report(provenance='infrastructure',failure_kind='inspection_infrastructure',cleanup_ok=False)
  with tempfile.TemporaryDirectory()as folder:
   results,status=c.execute([self.job(i)for i in range(12)],['h1','h2','h3','h4'],10,Path(folder)/'records.jsonl',fake)
   self.assertTrue(status['halted_on_infrastructure']);self.assertFalse(status['complete']);self.assertTrue(all(r['infrastructure']for r in results.values()));self.assertLess(len(calls),12)
 def test_candidate_failure_is_preserved_and_does_not_halt(self):
  with tempfile.TemporaryDirectory()as folder:
   result,status=c.execute([self.job()],['h1','h2','h3','h4'],10,Path(folder)/'r',lambda*a:self.report(status='error',passed=0,failed=0,tests_run=0,failure_kind='candidate_oom'))
  self.assertTrue(status['complete']);self.assertFalse(status['halted_on_infrastructure']);self.assertEqual(result['0']['report']['failure_kind'],'candidate_oom')
 def test_impossible_passing_count_halts_as_instrumentation(self):
  with tempfile.TemporaryDirectory()as folder:
   result,status=c.execute([self.job()],['h1','h2','h3','h4'],10,Path(folder)/'r',lambda*a:self.report(total=0,passed=0,tests_run=0))
  self.assertTrue(status['halted_on_infrastructure']);self.assertEqual(result['0']['report']['failure_kind'],'invalid_grade_infrastructure')
 def test_malformed_grader_return_fails_closed(self):
  with tempfile.TemporaryDirectory()as folder:
   result,status=c.execute([self.job()],['h1','h2','h3','h4'],10,Path(folder)/'r',lambda*a:None)
  self.assertTrue(status['halted_on_infrastructure']);self.assertTrue(result['0']['infrastructure'])
 def test_full_run_output_is_separate_and_hash_pinned_with_fake_gate_only(self):
  case=dict(task_id='fixture',arm='direct_off',seed=1,selected_code_sha256='a'*64,phases={phase:dict(job_ids=['0'],total=1)for phase in c.PHASES})
  result={'0':dict(report=self.report(),infrastructure=False)};status=dict(complete=True,halted_on_infrastructure=False,completed_jobs=1,planned_jobs=1,batch_wall_seconds=.1)
  with tempfile.TemporaryDirectory()as folder,patch.object(c,'verify_gate',return_value={'fixture':'verified45'}),patch.object(c,'prepare',return_value=([case],[self.job()],{})),patch.object(c,'execute',return_value=(result,status)),patch.object(c.grader,'evaluate_code')as remote,contextlib.redirect_stdout(io.StringIO()):
   out=Path(folder)/'new';self.assertEqual(c.main(['--run','--output',str(out)]),0);metadata=json.loads((out/'metadata.json').read_text());self.assertTrue(metadata['complete']);self.assertFalse(metadata['source_changed_during_run']);self.assertEqual(metadata['source_hashes'],metadata['final_source_hashes']);self.assertIn('original_holdout_status',(out/'summary.csv').read_text());remote.assert_not_called()
 def test_original_and_curated_trace_hashes_fail_closed(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);rel=Path('runs/evaluation-v2-coding-s1/t.jsonl');raw=root/rel;raw.parent.mkdir(parents=True);raw.write_bytes(b'original')
   row=dict(trace=str(rel),trace_sha256=hashlib.sha256(b'original').hexdigest());self.assertEqual(c.trace_bytes(root,row),b'original')
   raw.write_bytes(b'tampered')
   with self.assertRaisesRegex(ValueError,'changed'):c.trace_bytes(root,row)
   raw.unlink();curated=root/'results/evaluation-v2/coding-s1';curated.mkdir(parents=True);target=curated/'t.jsonl';target.write_bytes(b'normalized')
   (curated/'manifest.json').write_text(json.dumps(dict(files=[dict(export=str(target.relative_to(root)),original_sha256=row['trace_sha256'],export_sha256=hashlib.sha256(b'normalized').hexdigest())])))
   self.assertEqual(c.trace_bytes(root,row),b'normalized');target.write_bytes(b'tampered')
   with self.assertRaisesRegex(ValueError,'changed'):c.trace_bytes(root,row)

if __name__=='__main__':unittest.main()
