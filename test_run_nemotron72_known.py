"""Offline matrix, deadline, admission, and fail-stop tests; no inference."""
from contextlib import redirect_stdout
from datetime import datetime,timedelta,timezone
import io,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import run_nemotron72_known as r

class KnownSingleTests(unittest.TestCase):
    def fixture(self):
        tasks=[dict(id='authored-'+str(i),split='evaluation',numbers=[1]*(4 if i%2==0 else 6),target=2)for i in range(24)]
        plan={'matrix':{'expected_task_ids_in_stored_order':[t['id']for t in tasks]}}
        return {'tasks':tasks},plan
    def cases(self):
        data,plan=self.fixture();return r.make_cases(data,Path('/output'),['e1','e2','e3','e4'],Path('/frozen'),plan)
    def row(self):
        row={k:None for k in r.FIELDS};row.update(task_id='toy',split='evaluation',arm='scribe_full',seed=1,events='/toy',controller_error=None,malformed_lines=0,infrastructure_failures=0,returncode=0,controller_stop=False,calls=1,completed_calls=1,unfinished_calls=0,deadline=False,status='complete',server_idle_after=True,server_cost_known=True);return row
    def test_exact_matrix_balanced_per_node_seed_and_pinned_worker(self):
        cases=self.cases();self.assertEqual(len(cases),72);self.assertEqual(len({(c['task_id'],c['seed'])for c in cases}),72)
        for seed in (1,2,3):
            for slot in range(4):
                group=[c for c in cases if c['seed']==seed and c['slot']==slot];self.assertEqual(len(group),6)
                sizes=[len(c['command'][c['command'].index('--puzzle')+1].split(':')[0].split(','))for c in group];self.assertEqual(sorted(sizes),[4,4,4,6,6,6])
        self.assertTrue(all(c['command'][1]=='/frozen/followup72_worker.py'and c['arm']=='scribe_full'and c['command'][-3:]==['210','--model','nemotron-lightning']for c in cases))
    def test_wrong_tasks_or_duplicate_endpoints_rejected(self):
        data,plan=self.fixture();data['tasks'][0]['id']='wrong'
        with self.assertRaises(ValueError):r.make_cases(data,Path('/o'),['a','b','c','d'],Path('/s'),plan)
        data,plan=self.fixture()
        with self.assertRaises(ValueError):r.make_cases(data,Path('/o'),['a']*4,Path('/s'),plan)
    def test_controlled_deadline_retains_partial_usage_without_becoming_transport_fault(self):
        row=self.row();row.update(deadline=True,controller_stop=True,returncode=-15,completed_calls=0,unfinished_calls=1,infrastructure_failures=None,status='deadline')
        self.assertIsNone(r.operational_fault(row));self.assertEqual(row['unfinished_calls'],1)
        row['server_cost_known']=False;self.assertEqual(r.operational_fault(row),'counter_accounting_fault_or_unknown');self.assertEqual(row['unfinished_calls'],1)
        row=self.row();row['infrastructure_failures']=1;self.assertEqual(r.operational_fault(row),'controller_or_transport_failure')
    def test_local_exception_sets_stop_and_never_admits_next_case(self):
        stop=threading.Event();errors=[];attempted=[];call=Mock(side_effect=RuntimeError('authored'))
        with tempfile.TemporaryDirectory()as directory,patch.object(r,'hashes',return_value={'x':'y'}):
            r.run_queue(self.cases()[:2],{'x':'y'},Path('/s'),Path(directory),[],errors,attempted,threading.Lock(),stop,call)
        self.assertTrue(stop.is_set());self.assertEqual(call.call_count,1);self.assertEqual(len(attempted),1);self.assertEqual(errors[0]['reason'],'controller_exception')
    def test_source_change_or_positive_fault_stops_before_next_case(self):
        for changed in (True,False):
            stop=threading.Event();errors=[];rows=[];attempted=[];row=self.row();row['controller_error']='authored';call=Mock(return_value=row)
            with tempfile.TemporaryDirectory()as directory,patch.object(r,'hashes',return_value={'x':'new'if changed else'old'}),redirect_stdout(io.StringIO()):
                r.run_queue(self.cases()[:2],{'x':'old'},Path('/s'),Path(directory),rows,errors,attempted,threading.Lock(),stop,call)
            self.assertTrue(stop.is_set());self.assertEqual(call.call_count,0 if changed else 1)
    def test_default_plan_cannot_invoke_execute_or_create_output(self):
        plan=r.read(r.PLAN);data,_=self.fixture();plan['matrix']['expected_task_ids_in_stored_order']=[t['id']for t in data['tasks']]
        with patch.object(r,'read',side_effect=[plan,data]),patch.object(r,'validate_source'),patch.object(r,'hashes',return_value={}),patch.object(r,'sha',return_value='authored'),patch.object(r,'execute')as execute,patch.object(r,'write')as write,redirect_stdout(io.StringIO())as out:
            plan['matrix']['dataset_sha256']='authored';plan['development_selection']['sha256']=plan['development_selection']['audit_sha256']='authored'
            self.assertEqual(r.main(['--output','/does-not-exist']),0);self.assertEqual(json.loads(out.getvalue())['model_calls'],0);execute.assert_not_called();write.assert_not_called()
    def test_admission_age_identity_and_utc_are_checked(self):
        a=dict(verified=True,verified_utc=datetime.now(timezone.utc).isoformat(),source_sha256={'x':'y'},endpoints=['a'],runtime_identical_to_study_v032=True,all_four_owned_healthy_idle=True)
        r.admission_check(a,{'x':'y'},['a'])
        for seconds in(-1,901):
            bad=dict(a,verified_utc=(datetime.now(timezone.utc)-timedelta(seconds=seconds)).isoformat())
            with self.assertRaises(ValueError):r.admission_check(bad,{'x':'y'},['a'])
        with self.assertRaises(ValueError):r.admission_check(a,{'x':'changed'},['a'])
if __name__=='__main__':unittest.main()
