#!/usr/bin/env python3
"""Local authored minimal risk repros against the frozen grader; no SSH/model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import correctness_audit as a

def reproduce():
 s=a.load('repro_frozen_grader',a.SOURCE/'sandbox_code.py')
 tests=[dict(args=[[1,2]],expected=3),dict(args=[[]],expected=0),dict(args=[[-3,7]],expected=4)]
 frame='def solve(values):\n import sys\n return sys._getframe(1).f_locals["case"]["expected"]\n'
 forged='import os\nos.write(3,b\'{"status":"passed","passed":3,"failed":0,"tests_run":3,"total":3}\')\nos._exit(0)\n'
 results=[]
 for label,code in [('frame_expected_read',frame),('protocol_grade_forgery',forged)]:
  payload=dict(code=code,function_name='solve',tests=tests,timeout=2)
  process=subprocess.run([sys.executable,'-I','-S','-c',s.RUNNER],input=json.dumps(payload),text=True,capture_output=True,timeout=4)
  report=json.loads(process.stdout);assert process.returncode==0 and report['status']=='passed'and report['passed']==3
  results.append(dict(name=label,authored_source=code,returncode=process.returncode,observed_report=report,incorrect_acceptance=True))
 public=json.loads((a.HERE/'datasets/coding-v1/tasks.json').read_bytes());task=next(t for t in public['tasks']if t['id']=='eva-balanced_brackets');private=json.loads((a.HERE/'datasets/coding-v1/hidden-tests.json').read_bytes())['references'][task['id']]
 bad=lambda text:all(text.count(u)==text.count(v)for u,v in [('(',')'),('[',']'),('{','}')])
 coverage={phase:s._run_cases(bad,cases)for phase,cases in [('feedback',private['feedback_tests']),('holdout',private['holdout_tests']),('public_examples',task['examples'])]}
 assert coverage['feedback']['status']==coverage['holdout']['status']=='passed'and coverage['public_examples']['status']=='failed'
 def transient(values):values.append(999);values.pop();return sum(values)
 purity=s._run_cases(transient,[dict(args=[[1,2]],expected=3)]);assert purity['status']=='passed'
 return dict(protocol='frozen-grader-risk-reproductions-v1',source_revision=a.REVISION,grader_sha256=a.sha(a.SOURCE/'sandbox_code.py'),runner_sha256=hashlib.sha256(s.RUNNER.encode()).hexdigest(),script_sha256=a.sha(Path(__file__)),local_python=sys.version,remote_or_model_execution=False,same_interpreter_false_passes=results,ordinary_corpus_blind_spot=dict(task_id=task['id'],authored_source="def balanced_brackets(text): return all(text.count(a)==text.count(b) for a,b in [('(',')'),('[',']'),('{','}')])",grades=coverage,counterexample=dict(input='([)]',spec_expected=False,mutant_actual=bad('([)]'))),input_purity_limit=dict(authored_source='def solve(values): values.append(999); values.pop(); return sum(values)',observed_report=purity,scope='Final-state equality cannot detect temporary mutation restored before return.'),limits='Local Python3.14 reproduction of the exact frozen trusted RUNNER; not a remote container repeat. No retained model code executed; these intentionally authored candidates demonstrate capability, not observed historical exploitation.')

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 if args.output.exists():raise SystemExit('Refuses overwrite')
 result=reproduce();args.output.write_text(json.dumps(result,indent=2)+'\n');print('REPRODUCED: two adversarial false passes, one ordinary test-coverage blind spot, final-state purity limitation; no API')
