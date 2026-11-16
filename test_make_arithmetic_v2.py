"""Tiny authored datasets and one legacy32 fixture; never create the proposed64 corpus."""
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
import copy,io,json,tempfile,time
from pathlib import Path
import unittest
from unittest.mock import patch
import make_tasks as old
import make_arithmetic_v2 as v2


def put(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

class ArithmeticV2Tests(unittest.TestCase):
    def test_default_plan_does_not_scan_hash_or_generate(self):
        with patch.object(v2,'inventory')as inventory,patch.object(v2,'generate')as generate,patch.object(v2,'read')as read,redirect_stdout(io.StringIO())as out:
            self.assertEqual(v2.main([]),0);self.assertEqual(json.loads(out.getvalue())['tasks_generated'],0)
            inventory.assert_not_called();generate.assert_not_called();read.assert_not_called()

    def test_legacy_counts_bitmatch_exact_original_rng_and_paths(self):
        before=time.monotonic();legacy=old.generate(71,set());new=v2.generate(71,set(),8,24)
        self.assertEqual(new,legacy);v2.verify(*new[:2],set(),8,24)
        self.assertLess(time.monotonic()-before,3)

    def test_toy_determinism_balancing_exclusions_positive_integer_and_witness_mutation(self):
        first=v2.generate(17,set(),2,2);self.assertEqual(first,v2.generate(17,set(),2,2));v2.verify(*first[:2],set(),2,2)
        self.assertEqual(Counter((t['split'],len(t['numbers']))for t in first[0]),{('development',4):1,('development',6):1,('evaluation',4):1,('evaluation',6):1})
        excluded={old.key(first[0][0]['numbers'],first[0][0]['target'])};different=v2.generate(17,excluded,2,2);v2.verify(*different[:2],excluded,2,2)
        self.assertTrue(all(old.key(t['numbers'],t['target'])not in excluded for t in different[0]))
        for seed,dev,evaluation in [(True,2,2),(0,2,2),(-1,2,2),(1,3,2),(1,0,2),(1,2,False)]:
            with self.subTest(seed=seed,dev=dev,evaluation=evaluation),self.assertRaises(ValueError):v2.generate(seed,set(),dev,evaluation)
        task,witness=copy.deepcopy(first[0]),copy.deepcopy(first[1]);witness[task[0]['id']]['actions'][0]['i']=999
        with self.assertRaises(ValueError):v2.verify(task,witness,set(),2,2)
        task=copy.deepcopy(first[0]);task[0]['numbers'][0]=True
        with self.assertRaises(ValueError):v2.verify(task,first[1],set(),2,2)
        task=copy.deepcopy(first[0]);task[1]=task[0]
        with self.assertRaises(ValueError):v2.verify(task,first[1],set(),2,2)

    def test_deferred_scan_includes_unexecuted_outputs_plans_snapshots_initials_not_nodes(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);puzzles=[([2,3,25,50],123),([4,5,25,75],234),([6,7,50,100],345),([1,2,25,100],456)]
            put(root/'datasets/old/tasks.json',dict(protocol=old.PROTOCOL,tasks=[dict(numbers=puzzles[0][0],target=puzzles[0][1])],excluded_prior_fingerprints=[old.key(*puzzles[3])]))
            put(root/'plans/unexecuted.json',dict(cases=[dict(command=['python3','harness.py','--puzzle','4,5,25,75:234'])]))
            put(root/'.runtime/old-source-v1.1/datasets/planned/tasks.json',dict(tasks=[dict(numbers=puzzles[2][0],target=puzzles[2][1])]))
            trace=root/'runs/history/events.jsonl';trace.parent.mkdir(parents=True);trace.write_text('\n'.join(json.dumps(x)for x in [dict(type='puzzle_start',state=[8,9,25,75],target=567),dict(type='node',state=[1,1,25,50],target=678)]))
            plan=dict(exclusion_allowlist=['datasets/**/tasks.json','plans/**/*.json','runs/**/*.jsonl','.runtime/*source*/datasets/**/tasks.json'],historical_initial_puzzles=['2,3,5,9:28'])
            scan=v2.exclusion_scan(root,plan,'TOY_PLAN');self.assertTrue(scan['complete_exclusion_scan']);self.assertEqual(len(scan['inventory']),4)
            for numbers,target in puzzles:self.assertIn(old.key(numbers,target),scan['fingerprints'])
            self.assertIn(old.key([8,9,25,75],567),scan['fingerprints']);self.assertNotIn(old.key([1,1,25,50],678),scan['fingerprints']);self.assertIn(old.key([2,3,5,9],28),scan['fingerprints'])

    def test_generation_gate_fails_proposed_missing_idle_and_stale_source_pins(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);names=['make_arithmetic_v2.py','test_make_arithmetic_v2.py','make_tasks.py','harness.py']
            for name in names:(root/name).write_text('# AUTHORED FIXTURE')
            plan=dict(status='FROZEN',seed=v2.SEED,counts={'development':16,'evaluation':48},source_sha256={n:v2.sha(root/n)for n in names});put(root/v2.PLAN,plan)
            now=datetime.now(timezone.utc)
            receipt=dict(verified=True,verified_utc=now.isoformat(),all_model_timing_idle=True,root_go=True,prospective_plan_frozen=True,plan_sha256=v2.sha(root/v2.PLAN));put(root/'admission.json',receipt)
            with patch.object(v2,'HERE',root):
                v2.gate(plan,root/'admission.json')
                for stamp in [(now-timedelta(seconds=901)).isoformat(),(now+timedelta(seconds=60)).isoformat(),now.replace(tzinfo=None).isoformat(),now.astimezone(timezone(timedelta(hours=1))).isoformat(),'',None,0]:
                    put(root/'admission.json',dict(receipt,verified_utc=stamp))
                    with self.subTest(stamp=stamp),self.assertRaises(ValueError):v2.gate(plan,root/'admission.json')
                put(root/'admission.json',receipt)
                with self.assertRaises(ValueError):v2.gate(dict(plan,status='PROPOSED'),root/'admission.json')
                put(root/'admission.json',dict(receipt,all_model_timing_idle=False))
                with self.assertRaises(ValueError):v2.gate(plan,root/'admission.json')
                put(root/'admission.json',receipt);(root/'harness.py').write_text('# CHANGED')
                with self.assertRaises(ValueError):v2.gate(plan,root/'admission.json')

    def test_public_private_file_separation_and_no_overwrite_without_full64_generation(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);(root/'.runtime').mkdir();out=root/'new';tasks,witnesses,attempts=v2.generate(19,set(),2,2);plan=dict(status='FROZEN',seed=v2.SEED,counts={'development':16,'evaluation':48},source_sha256={},exclusion_allowlist=[],historical_initial_puzzles=[]);put(root/v2.PLAN,plan)
            scan=dict(complete_exclusion_scan=True,plan_sha256=v2.sha(root/v2.PLAN),historical_initial_puzzles=[],fingerprints=[],inventory={});put(root/'.runtime/scan.json',scan)
            with patch.object(v2,'HERE',root),patch.object(v2,'gate'),patch.object(v2,'inventory',return_value={}),patch.object(v2,'generate',return_value=(tasks,witnesses,attempts)),patch.object(v2,'verify',side_effect=lambda t,w,e:v2_verify(t,w,e,2,2)),redirect_stdout(io.StringIO()):
                self.assertEqual(v2.main(['--run','--admission','unused','--exclusion-scan',str(root/'.runtime/scan.json'),'--output',str(out)]),0)
                with self.assertRaises(ValueError):v2.main(['--run','--admission','unused','--exclusion-scan',str(root/'.runtime/scan.json'),'--output',str(out)])
            public,private=json.loads((out/'tasks.json').read_text()),json.loads((out/'reference-witnesses.json').read_text());self.assertEqual(len(public['tasks']),4);self.assertTrue({'witnesses','actions','final_state'}.isdisjoint(public));self.assertTrue(all(set(t)=={'id','split','numbers','target'}for t in public['tasks']));self.assertEqual(private['witnesses'],witnesses);self.assertNotIn('tasks',private)

v2_verify=v2.verify
if __name__=='__main__':unittest.main()
