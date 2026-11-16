"""Authored/fake CPU-only fixtures; no model/SSH/container or real producer outcomes."""
from contextlib import redirect_stdout
from datetime import datetime,timezone,timedelta
import copy,io,json
from pathlib import Path
import tempfile,threading
import unittest
from unittest.mock import patch
import run_program_review_confirmation as r
from test_run_program_confirmation import TASK,report,bindings as original_bindings


def bindings(root):
    rows=[b for b in original_bindings(root)if b['arm']=='sequential16']
    for b in rows:
        b['arm']='review_elites4';p=Path(b['source_path']);p.write_bytes(p.read_bytes().replace(b'\n',b'\r\n'));b['code_sha256']=r.sha(p)
    return rows


class ReviewConfirmationTests(unittest.TestCase):
    def test_v11_producer_identity_and_configuration_pins_agree(self):
        cfg=json.loads((r.HERE/r.CONFIG).read_text())
        self.assertEqual(cfg['protocol'],'late-review-program-confirmation-v1.1')
        self.assertEqual(cfg['producer_revision'],r.PRODUCER)
        self.assertEqual(cfg['producer_selection_sha256'],r.SELECTION)
        self.assertEqual(cfg['prospective_identity_amendment']['prior_helper_revision'],'94edb757975f392173410cb2f5e7d34e81a75e0d')
        self.assertTrue(all(r.sha(r.HERE/name)==expected for name,expected in cfg['source_sha256'].items()))

    def test_default_plan_reads_no_outcomes_calls_no_network_and_writes_nothing(self):
        with tempfile.TemporaryDirectory()as d,patch.object(r,'read')as read,patch.object(r,'admit')as admit,patch.object(r,'execute')as execute,redirect_stdout(io.StringIO())as out:
            self.assertEqual(r.main(['--gate-root',d]),0)
            self.assertEqual(json.loads(out.getvalue())['cpu_grades'],384)
            read.assert_not_called();admit.assert_not_called();execute.assert_not_called();self.assertEqual(list(Path(d).iterdir()),[])

    def test_positive_negative_payload_cleanup_and_oracle_checks(self):
        code='AUTHORED fixture never executed'
        for case in ('valid','negative','mutation','timeout','resource','missingmutation','falsepositive','falsenegative','payload','cleanup','oracle'):
            value=report(code,TASK,'Spark_01',solved=case!='negative')
            if case=='falsepositive':value=report(code,TASK,'Spark_01',solved=False);value.update(solved=True,status='passed')
            if case=='falsenegative':value.update(solved=False,status='failed')
            if case=='payload':value['child_payload_sha256']='wrong'
            if case=='cleanup':value['cleanup_ok']=False
            if case=='oracle':value['oracle_sent_to_child']=True
            if case=='mutation':value.update(solved=False,status='failed',input_unchanged=False,failure_kind='candidate_input_mutation')
            if case=='timeout':value.update(solved=False,status='timeout',failure_kind='candidate_timeout')
            if case=='resource':value.update(solved=False,status='error',failure_kind='candidate_oom')
            if case=='missingmutation':value=report(code,TASK,'Spark_01',solved=False);value.pop('input_unchanged')
            with self.subTest(case=case):
                if case in ('valid','negative','mutation','timeout','resource'):r.grade_check(TASK,value,code)
                else:
                    with self.assertRaises(RuntimeError):r.grade_check(TASK,value,code)

    def test_copied_binding_names_actual_execution_bytes_and_preserves_producer_path(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);original=bindings(root);saved=copy.deepcopy(original);out=root/'out';out.mkdir();corpus=root/'corpus.json';corpus.write_bytes(b'{"authored":"fixture"}\r\n')
            actual,files=r.copy_inputs(original,out,corpus)
            self.assertEqual(original,saved);self.assertEqual(r.read(out/'bindings.json'),actual);self.assertEqual(len(files),6)
            self.assertEqual((out/'corpus.json').read_bytes(),corpus.read_bytes())
            for before,after in zip(original,actual):
                self.assertEqual(after['producer_source_path'],before['source_path']);self.assertEqual(Path(after['source_path']).parent,out)
                self.assertEqual(Path(after['source_path']).read_bytes(),Path(before['source_path']).read_bytes())
                self.assertEqual(r.sha(after['source_path']),after['code_sha256'])

    def test_all_four_hosts_all_graphs_even_negative_no_cache_and_source_bytes_exact(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);b=bindings(root);out=root/'output';out.mkdir();tasks=[dict(TASK,id='tiny-'+str(i))for i in range(3)];seen=[];lock=threading.Lock()
            def evaluate(code,task,host,timeout):
                self.assertIn('\r\n',code)
                with lock:seen.append((host,task['id']))
                return report(code,task,host,timeout,solved=False)
            rows,faults=r.execute(b,tasks,out,{},evaluate,lambda:{})
            self.assertEqual(faults,[]);self.assertEqual(len(rows),12);self.assertEqual(len(set(seen)),12)
            self.assertTrue(all(x['infrastructure']is False and x['solved']is False for x in rows))
            for seed in range(1,5):self.assertEqual([t for h,t in seen if h==f'Spark_{seed:02d}'],[t['id']for t in tasks])

    def test_changed_input_and_cleanup_fault_stop_new_dispatch_wait_for_owned_work(self):
        for bad in ('source','cleanup'):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory()as d:
                root=Path(d);b=bindings(root);out=root/'output';out.mkdir();tasks=[dict(TASK,id='tiny-'+str(i))for i in range(96)]
                def evaluate(code,task,host,timeout):
                    value=report(code,task,host,timeout)
                    if bad=='cleanup':value['cleanup_ok']=False
                    return value
                rows,faults=r.execute(b,tasks,out,{},evaluate,lambda:{'changed':True}if bad=='source'else{})
                self.assertTrue(faults);self.assertLessEqual(len(rows),4);self.assertTrue(all(x['infrastructure']is True and x['solved']is None for x in rows))

    def test_admission_rejects_stale_or_feature_switched_or_foreign_owner(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);runtime=dict(arm64_manifest_digest='SYNTHETIC',model_revision='TARGET',dspark={'draft_revision':'DRAFT'});(root/'runtime.json').write_text(json.dumps(runtime))
            receipt=dict(checked_utc=datetime.now(timezone.utc).isoformat(),verified=True,model_switch_started=False,feature_switch_started=False,workloads_drained=True,optional_time_admitted=True,nodes=[dict(seed=s,host=f'Spark_{s:02d}',endpoint=f'http://127.0.0.1:{18080+s}/v1',healthy=True,idle=True,owner='swarm-lab-20261115',image='vllm/vllm-openai@SYNTHETIC',model_revision='TARGET',draft_revision='DRAFT',runtime_sha256='RUNTIME')for s in range(1,5)])
            for case in ('valid','stale','feature','owner','missingflag'):
                value=copy.deepcopy(receipt)
                if case=='stale':value['checked_utc']=(datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat()
                if case=='feature':value['feature_switch_started']=True
                if case=='owner':value['nodes'][0]['owner']='foreign'
                if case=='missingflag':value.pop('feature_switch_started')
                p=root/'admission.json';p.write_text(json.dumps(value))
                with self.subTest(case=case),patch.object(r,'HERE',root),patch.object(r,'followup_gate',return_value={'verified':True}),patch.object(r,'idle_health',return_value={'idle':True,'healthy':True})as health:
                    if case=='valid':self.assertEqual(len(r.admit(root,p,{'source_sha256':{'runtime.json':'RUNTIME'}})[0]),4)
                    else:
                        with self.assertRaises(RuntimeError):r.admit(root,p,{'source_sha256':{'runtime.json':'RUNTIME'}})
                        health.assert_not_called()


if __name__=='__main__':unittest.main()
