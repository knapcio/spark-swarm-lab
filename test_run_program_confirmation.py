"""Authored CPU fixtures/fake evaluators only; no model/SSH/container calls."""
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_program_confirmation as r
from csp_tasks import graph_digest,verify_assignment

TASK=dict(id='authored-path',vertex_count=3,color_count=2,edges=[[0,1],[1,2]])
ARMS=['sequential16','independent4']

def report(code,task,host,timeout=10,solved=True):
    value={'assignment':[0,1,0]if solved else[0,0,0]};proof=verify_assignment(task,value)
    payload=json.dumps(dict(code=code,function_name='solve',calls=[dict(args=[task['vertex_count'],task['color_count'],task['edges']],kwargs={})],timeout=timeout),allow_nan=False)
    return dict(status='passed'if solved else'failed',solved=solved,proof=proof,candidate_output=value,input_unchanged=True,
        failure_kind=None if solved else'candidate_graph_failure',cleanup_ok=True,provenance='candidate',grading_authority='outer_parent',
        oracle_sent_to_child=False,graph_sha256=graph_digest(task),child_payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),remote_cpu_seconds=None)

def bindings(root):
    result=[]
    for seed in range(1,5):
        for arm in ARMS:
            p=root/f'{seed}-{arm}.py';p.write_text(f'# Authored fixture {seed} {arm}; never executed\ndef solve(n,k,edges): pass')
            result.append(dict(seed=seed,arm=arm,host=f'Spark_{seed:02d}',source_path=str(p),code_sha256=r.sha(p)))
    return result

def master_fixture(root):
    dataset=root/'datasets/csp-v1/tasks.json';dataset.parent.mkdir(parents=True);dataset.write_text('SYNTHETIC_DATA_ID')
    selection=root/'PROGRAM_SEARCH_SELECTION.json';r.write(selection,dict(source_sha256={'authored.py':'SYNTHETIC_HASH'}))
    directory=root/'master';directory.mkdir();dev=[dict(TASK,id=f'dev-{i}')for i in range(4)];evaluation=[dict(TASK,id=f'eva-{i}')for i in range(12)]
    source=dict(revision=r.PROGRAM_REVISION,tracked_clean=True,source_files_tracked=True,sha256={'authored.py':'SYNTHETIC_HASH','PROGRAM_SEARCH_SELECTION.json':r.sha(selection)})
    qual=[]
    for name in ['valid','wrong','forged_grade']:
        value=report('SYNTHETIC',TASK,'Spark_04',solved=name=='valid')
        if name=='forged_grade':value.update(status='error',proof=None,solved=False,failure_kind='candidate_protocol');value.pop('candidate_output')
        qual.append(dict(name=name,task=TASK,report=value))
    qualification=dict(verified=True,model_calls=0,rows=qual);r.write(directory/'program-grader-qualification.json',qualification)
    r.write(directory/'development-inputs.json',dev);r.write(directory/'evaluation-inputs.json',evaluation)
    rows=[]
    for b in bindings(root):
        episode=directory/f"seed-{b['seed']}-{b['arm']}";episode.mkdir();code=Path(b['source_path']).read_text();(episode/'selected.py').write_text(code)
        r.write(episode/'selection.json',dict(seed=b['seed'],arm=b['arm'],evaluation_seen=False,model_calls_at_selection=16,code_sha256=b['code_sha256']))
        for task in evaluation:r.write(episode/f"evaluation-{task['id']}.json",dict(task_id=task['id'],selected_sha256=b['code_sha256'],graph_sha256=graph_digest(task),report=report(code,task,b['host'])))
        rows.append(dict(seed=b['seed'],arm=b['arm'],host=b['host'],status='complete',complete=True,training_candidates_scored=16,calls=16,model_budget={'calls':16},evaluation_completed=12,evaluation_graphs=12,selected_sha256=b['code_sha256']))
    meta=dict(mode='run',complete=True,verified=True,faults=[],source=source,source_after=source,completed_programs=8,recorded_episodes=8,selection_sha256=r.sha(selection),dataset_sha256=r.sha(dataset),grader_qualification=qualification)
    r.write(directory/'metadata.json',meta);r.write(directory/'results.json',rows)
    return directory,dev,evaluation


class ConfirmationTests(unittest.TestCase):
    def test_plan_has_no_gate_server_grades_or_writes_before_program_exists(self):
        with tempfile.TemporaryDirectory()as d,patch.object(r,'configuration',return_value=({'protocol':'fixture','dataset':'fixtures'},[TASK])),patch.object(r,'sha',return_value='fixture'),patch.object(r,'admission')as admission,patch.object(r,'execute')as execute,patch.object(r,'idle_health')as health,redirect_stdout(io.StringIO())as output:
            self.assertEqual(r.main(['--gate-root',d]),0)
            self.assertEqual(json.loads(output.getvalue())['planned_jobs'],768)
            admission.assert_not_called();execute.assert_not_called();health.assert_not_called()
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_run_gate_failure_precedes_any_program_grade_or_output(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);out=root/'runs/new'
            with patch.object(r,'configuration',return_value=({'protocol':'fixture','dataset':'fixture'},[TASK])),patch.object(r,'git_identity',return_value={}),patch.object(r,'sha',return_value='fixture'),patch.object(r,'followup_gate',side_effect=RuntimeError('incomplete10stage gate')),patch.object(r,'execute')as execute,patch.object(r,'idle_health')as health:
                with self.assertRaisesRegex(RuntimeError,'10stage'):r.main(['--run','--gate-root',d,'--admission',str(root/'absent'),'--output',str(out)])
                execute.assert_not_called();health.assert_not_called();self.assertFalse(out.exists())

    def test_completed_program_identity_selection_and_budget_tampering_rejected(self):
        for change in ['clean','revision','seen','source','budget','missing_graph']:
            with self.subTest(change=change),tempfile.TemporaryDirectory()as d:
                root=Path(d);directory,dev,evaluation=master_fixture(root)
                if change=='revision':
                    p=directory/'metadata.json';m=r.read(p);m['source']['revision']='wrong';p.write_text(json.dumps(m))
                if change=='seen':
                    p=directory/'seed-1-sequential16/selection.json';m=r.read(p);m['evaluation_seen']=True;p.write_text(json.dumps(m))
                if change=='source':(directory/'seed-1-sequential16/selected.py').write_text('changed')
                if change=='budget':
                    p=directory/'results.json';m=r.read(p);m[0]['calls']=15;p.write_text(json.dumps(m))
                if change=='missing_graph':(directory/f"seed-1-sequential16/evaluation-{evaluation[0]['id']}.json").unlink()
                with patch.object(r,'HERE',root),patch.object(r,'load_tasks',side_effect=lambda p,split:evaluation if split=='evaluation'else dev):
                    if change=='clean':self.assertEqual(len(r.completed_programs(directory,{'arms':ARMS})[0]),8)
                    else:
                        with self.assertRaises((RuntimeError,FileNotFoundError)):r.completed_programs(directory,{'arms':ARMS})

    def test_all_eight_all_96_exact_jobs_despite_candidate_failures_no_cache(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);b=bindings(root);out=root/'out';out.mkdir();calls=[];lock=threading.Lock();active=set()
            tasks=[dict(TASK,id=f'authored-{i}')for i in range(96)]
            def evaluator(code,task,host,timeout):
                with lock:self.assertNotIn(host,active);active.add(host);calls.append((host,code,task['id']))
                value=report(code,task,host,timeout,solved=False)
                with lock:active.remove(host)
                return value
            rows,status=r.execute(b,tasks,out,{},evaluator=evaluator,pinner=lambda:{})
            self.assertTrue(status['complete']);self.assertEqual(len(calls),768)
            self.assertEqual(len({x['job_id']for x in rows}),768)
            self.assertEqual({x['host']for x in rows},{f'Spark_{i:02d}'for i in range(1,5)})
            self.assertTrue(all(x['solved']is False and not x['infrastructure']for x in rows))
            self.assertEqual(len((out/'grades.jsonl').read_text().splitlines()),768)
            self.assertIsNone(status['remote_cpu_seconds']);self.assertEqual(status['model_calls'],0)

    def test_infrastructure_halt_waits_for_all_already_dispatched_cleanup(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);b=bindings(root);out=root/'out';out.mkdir();barrier=threading.Barrier(4);calls=[];finished=[];lock=threading.Lock()
            def evaluator(code,task,host,timeout):
                with lock:calls.append(host)
                if len(calls)<=4:barrier.wait(timeout=3)
                value=report(code,task,host,timeout)
                if host=='Spark_01':value.update(cleanup_ok=False,provenance='infrastructure',failure_kind='cleanup_infrastructure')
                with lock:finished.append(host)
                return value
            rows,status=r.execute(b,[dict(TASK,id=str(i))for i in range(96)],out,{},evaluator=evaluator,pinner=lambda:{})
            self.assertFalse(status['complete']);self.assertLess(len(calls),768)
            self.assertEqual(len(finished),len(calls));self.assertTrue(status['faults'])
            self.assertTrue(any(x.get('solved')is None for x in rows));self.assertGreater(status['missing_jobs'],0)

    def test_bound_sha_drift_halts_before_more_work_and_preserves_unknown(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);b=bindings(root);out=root/'out';out.mkdir();state={'bound':'original'};before=dict(state);barrier=threading.Barrier(4);finished=[]
            def evaluator(code,task,host,timeout):
                barrier.wait(timeout=3);state['bound']='changed';finished.append(host);return report(code,task,host,timeout)
            rows,status=r.execute(b,[dict(TASK,id=str(i))for i in range(96)],out,before,evaluator=evaluator,pinner=lambda:dict(state))
            self.assertEqual(len(finished),4);self.assertEqual(len(rows),4)
            self.assertTrue(status['source_changed_during_run']);self.assertFalse(status['verified'])
            self.assertTrue(all(x['solved']is None for x in rows))

    def test_unproven_pass_forged_proof_and_wrong_graph_rejected(self):
        for change in ['proof','graph','no_output','passed_false']:
            value=report('authored',TASK,'Spark_01')
            if change=='proof':value['proof']['conflicts']=1
            if change=='graph':value['graph_sha256']='wrong'
            if change=='no_output':value.pop('candidate_output')
            if change=='passed_false':value['solved']=False
            with self.subTest(change=change),self.assertRaises(RuntimeError):r.validate_report(TASK,value)

    def test_source_bytes_are_preserved_without_newline_or_backslash_repair(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);b=bindings(root);out=root/'out';out.mkdir()
            code='# authored literal \\n\r\ndef solve(n,k,edges): pass\r\n'
            for item in b:
                Path(item['source_path']).write_bytes(code.encode());item['code_sha256']=hashlib.sha256(code.encode()).hexdigest()
            seen=[]
            def evaluator(actual,task,host,timeout):seen.append(actual);return report(actual,task,host,timeout)
            rows,_=r.execute(b,[TASK],out,{},evaluator=evaluator,pinner=lambda:{})
            self.assertEqual(seen,[code]*8);self.assertTrue(all(x['solved']for x in rows))

    def test_all_bindings_and_evidence_are_frozen_before_execute(self):
        with tempfile.TemporaryDirectory()as d:
            root=Path(d);b=bindings(root);out=root/'runs/new';data=root/'corpus.json';data.write_text('SYNTHETIC_CORPUS')
            master=root/'master';master.mkdir();(master/'program-grader-qualification.json').write_text('{}')
            cfg={'protocol':'fixture','arms':ARMS,'dataset':'corpus.json','image':'SYNTHETIC_IMAGE','source_sha256':{'corpus.json':r.sha(data)}};(root/r.CONFIG).write_text('{}')
            original=r.pins([Path(x['source_path'])for x in b])
            def execute(actual,tasks,directory,before):
                self.assertEqual(len(actual),8);self.assertEqual(len(list(directory.glob('selected-*.py'))),8)
                self.assertTrue((directory/'metadata.json').exists())
                for name in ['bindings.json','corpus.json']+[f"selected-s{x['seed']}-{x['arm']}.py"for x in b]:self.assertEqual(before[str(directory/name)],r.sha(directory/name))
                self.assertTrue(all(before[k]==v for k,v in original.items()))
                return [],dict(complete=False,verified=False,incomplete=True,faults=[],missing_jobs=768)
            with patch.object(r,'HERE',root),patch.object(r,'configuration',return_value=(cfg,[TASK])),patch.object(r,'git_identity',return_value={'fixture':True}),patch.object(r,'admission',return_value=(b,[Path(x)for x in original],{'observed':[]})),patch.object(r,'execute',side_effect=execute),redirect_stdout(io.StringIO()):
                self.assertEqual(r.main(['--run','--gate-root',d,'--program-run',str(master),'--admission',str(root/'unused'),'--output',str(out)]),1)

    def test_admission_rejects_stale_switch_wrong_owner_before_health_or_grade(self):
        from datetime import datetime,timezone,timedelta
        for change in ['clean','stale','switched','owner','runtime']:
            with self.subTest(change=change),tempfile.TemporaryDirectory()as d:
                root=Path(d);runtime={'arm64_manifest_digest':'sha256:fixture','model_revision':'target','dspark':{'draft_revision':'draft'}}
                evidence=dict(verified=True,model_switch_started=False,workloads_drained=True,optional_time_admitted=True,
                    checked_utc=datetime.now(timezone.utc).isoformat(),nodes=[dict(seed=i,host=f'Spark_{i:02d}',endpoint=f'http://127.0.0.1:{18080+i}/v1',healthy=True,idle=True,owner='swarm-lab-20261115',runtime_sha256='runtime',image='vllm/vllm-openai@sha256:fixture',model_revision='target',draft_revision='draft')for i in range(1,5)])
                if change=='stale':evidence['checked_utc']=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
                if change=='switched':evidence['model_switch_started']=True
                if change=='owner':evidence['nodes'][0]['owner']='foreign'
                if change=='runtime':evidence['nodes'][0]['model_revision']='other'
                p=root/'admission.json';p.write_text('{}')
                def read(path):return {'gate':{}}if path.name=='metadata.json'else runtime if path.name=='runtime.json'else evidence
                with patch.object(r,'HERE',root),patch.object(r,'followup_gate',return_value={}),patch.object(r,'completed_programs',return_value=([],[])),patch.object(r,'read',side_effect=read),patch.object(r,'idle_health',return_value={'idle':True,'healthy':True})as health:
                    if change=='clean':r.admission(root,root/'master',p,{'source_sha256':{'runtime.json':'runtime'}});self.assertEqual(health.call_count,4)
                    else:
                        with self.assertRaises(RuntimeError):r.admission(root,root/'master',p,{'source_sha256':{'runtime.json':'runtime'}})
                        health.assert_not_called()


if __name__=='__main__':unittest.main()
