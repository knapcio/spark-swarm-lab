"""Offline plan and exact-diff regression for transport timeout separation."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
HERE=Path(__file__).resolve().parent
BASE='47bba9f083653dd32ff91ca22585d4185198f65b'
OLD_COMMAND='"--max-calls","1280","--max-completion-tokens","32768","--timeout","180",'
NEW_COMMAND='"--max-calls","1280","--max-completion-tokens","32768","--timeout","210",'
OLD_META='budgets="1280 calls/32768 completion tokens per case, no input-token cap; request timeout180s and case deadline180s AFTER admission",'
NEW_META='budgets="1280 calls/32768 completion tokens per case, no input-token cap; request timeout210s and case deadline180s AFTER admission",\n                    request_timeout_seconds=210,case_deadline_after_admission_seconds=180,controller_poll_seconds=0.1,\n                    deadline_observation_tolerance="Nominal0.1s controller polling plus scheduling/trace overhead; original completion/proof ordering unchanged. Request timeout adds transport margin only.",'
class TimeoutGuardTests(unittest.TestCase):
 def blob(self,name):return subprocess.check_output(['git','show',BASE+':'+name],cwd=HERE)
 def test_exact_source_diff_and_all_other_frozen_bytes(self):
  old=self.blob('run_throughput.py').decode();self.assertEqual(old.count(OLD_COMMAND),1);self.assertEqual(old.count(OLD_META),1)
  self.assertEqual((HERE/'run_throughput.py').read_text(),old.replace(OLD_COMMAND,NEW_COMMAND,1).replace(OLD_META,NEW_META,1))
  changed=subprocess.check_output(['git','diff','--name-only',BASE],cwd=HERE,text=True).splitlines()
  self.assertLessEqual(set(changed),{'run_throughput.py','test_throughput_timeoutguard.py'})
  subprocess.run(['git','diff','--exit-code',BASE,'--','.',':!run_throughput.py',':!test_throughput_timeoutguard.py'],cwd=HERE,check=True,capture_output=True)
  self.assertEqual(hashlib.sha256((HERE/'runtime.json').read_bytes()).hexdigest(),'072b628126f36aa559fa864372118c7e0497e44d1b37d29be99ea3c7f8cf6ec5')
 def test_nine_arm_plans_keep180_case_budget_and210_transport_margin(self):
  original=json.loads((HERE/'THROUGHPUT_DEVELOPMENT.json').read_text())
  arms=original['arms']+['independent32','independent100','democracy32','shared8'];self.assertEqual(len(arms),9)
  for arm in arms:
   completed=subprocess.run([sys.executable,str(HERE/'run_throughput.py'),'--dataset',str(HERE/'datasets/arithmetic-v1/tasks.json'),'--split','development','--arm',arm,'--jobs-per-node','8'],cwd=HERE,text=True,capture_output=True,check=True);meta=json.loads(completed.stdout)
   self.assertEqual(meta['mode'],'dry_run');self.assertEqual(meta['request_timeout_seconds'],210);self.assertEqual(meta['case_deadline_after_admission_seconds'],180);self.assertEqual(meta['controller_poll_seconds'],.1);self.assertEqual(len(meta['cases']),32)
   for case in meta['cases']:
    args=case['command'];self.assertEqual(args[args.index('--timeout')+1],'210');self.assertEqual(args[args.index('--max-calls')+1],'1280');self.assertEqual(args[args.index('--max-completion-tokens')+1],'32768');self.assertTrue(case['shared_endpoint'])
  self.assertIn('row = execute(case,180)',(HERE/'run_throughput.py').read_text());self.assertEqual((HERE/'run_benchmark.py').read_bytes(),self.blob('run_benchmark.py'))
if __name__=='__main__':unittest.main()
