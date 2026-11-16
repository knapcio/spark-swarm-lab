#!/usr/bin/env python3
"""Plan-first 72-case replay on a previously seen, development-tuned arithmetic suite."""
import argparse,csv,hashlib,json,subprocess,sys,threading,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from run_benchmark import FIELDS,execute
HERE=Path(__file__).resolve().parent
PLAN=HERE/'NEMOTRON72_KNOWN_SINGLE_PLAN.json'
REVISION='638b9f335a7aa7011a9b7d122abcaa04f45e17a5'
SOLVER=('run_followup72.py','followup72_worker.py','followup72.py','followup72_client.py','harness.py','direct_solver.py','run_benchmark.py','runtime.json','FOLLOWUP72_DEVELOPMENT_PLAN.json','datasets/arithmetic-v1/tasks.json')
LOCAL=('run_nemotron72_known.py','test_run_nemotron72_known.py','NEMOTRON72_KNOWN_SINGLE_PLAN.json','run_benchmark.py','runtime.json')
def require(ok,message):
    if not ok:raise ValueError(message)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def write(p,value):
    temporary=p.with_suffix(p.suffix+'.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(p)
def hashes(source):return {**{'solver/'+n:sha(source/n)for n in SOLVER},**{'runner/'+n:sha(HERE/n)for n in LOCAL}}
def validate_source(source):
    require(source.is_absolute()and source.is_dir(),'Absolute existing frozen source required')
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==REVISION,'Wrong frozen solver revision')
    for n in SOLVER:
        require(sha(source/n)==hashlib.sha256(subprocess.check_output(['git','show',REVISION+':'+n],cwd=source)).hexdigest(),'Frozen solver modified: '+n)
    require(sha(source/'runtime.json')==sha(HERE/'runtime.json'),'Runner and solver runtime differ')
def make_cases(dataset,output,endpoints,source,plan):
    require(len(endpoints)==len(set(endpoints))==4,'Four distinct endpoints required')
    tasks=[t for t in dataset['tasks']if t['split']=='evaluation']
    require(len(tasks)==24 and [t['id']for t in tasks]==plan['matrix']['expected_task_ids_in_stored_order'],'Wrong stored evaluation task IDs')
    require([len(t['numbers'])for t in tasks]==[4,6]*12,'Preserve balanced stored task order')
    cases=[]
    for si,seed in enumerate((1,2,3)):
        for ti,task in enumerate(tasks):
            slot=(ti//2+2*(ti%2)+si)%4;stem=f"{task['id']}-scribe_full-s{seed}";events=output/(stem+'.jsonl')
            command=[sys.executable,str(source/'followup72_worker.py'),'--run','--variant','scribe_full','--puzzle',','.join(map(str,task['numbers']))+':'+str(task['target']),'--endpoint',endpoints[slot],'--seed',str(seed),'--events',str(events),'--timeout','210','--model','nemotron-lightning']
            cases.append(dict(task_id=task['id'],split='evaluation',arm='scribe_full',seed=seed,slot=slot,endpoint=endpoints[slot],command=command,events=str(events),stdout=str(output/(stem+'.stdout.log')),stderr=str(output/(stem+'.stderr.log')),server_metrics=True,stop_on_solution=False))
    return cases

def operational_fault(row):
    if row['controller_error']or row['malformed_lines']or row['infrastructure_failures']or(row['returncode']!=0 and not row['controller_stop']):return'controller_or_transport_failure'
    if not(0<=row['completed_calls']<=row['calls']<=2 and row['unfinished_calls']==row['calls']-row['completed_calls']):return'inconsistent_request_lifecycle'
    if not row['deadline']and(row['calls']<1 or row['unfinished_calls']or row['infrastructure_failures']is None or row['status']not in('complete','budget_limited')):return'unexpected_completion_state'
    if row['server_idle_after']is not True:return'endpoint_not_confirmed_drained'
    if row['server_cost_known']is not True:return'counter_accounting_fault_or_unknown'
    return None

def run_queue(cases,before,source,output,rows,errors,attempted,lock,stop,execute_case=execute):
    for case in cases:
        try:
            with lock:
                if stop.is_set():return
                if hashes(source)!=before:
                    stop.set();errors.append(dict(reason='source_changed_before_case',events=case['events']));return
                attempted.append(case['events'])
            row=execute_case(case,deadline_seconds=180)
            with lock:
                rows.append(row);write(output/'summary.json',rows)
                with(output/'summary.csv').open('w',newline='')as stream:
                    writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows({k:json.dumps(v)if isinstance(v,dict)else v for k,v in r.items()}for r in rows)
                reason=operational_fault(row)
                if reason:stop.set();errors.append(dict(events=case['events'],reason=reason))
                print(json.dumps(dict(completed=len(rows),total=72,task_id=case['task_id'],seed=case['seed'],status=row['status'])),flush=True)
        except Exception as exc:
            stop.set()
            with lock:errors.append(dict(events=case['events'],reason='controller_exception',detail=f'{type(exc).__name__}: {exc}'))
            return

def admission_check(admission,before,endpoints):
    stamp=datetime.fromisoformat(admission['verified_utc']);age=(datetime.now(timezone.utc)-stamp).total_seconds()
    require(stamp.utcoffset() is not None and stamp.utcoffset().total_seconds()==0 and admission.get('verified')is True and 0<=age<=900,'Fresh UTC runtime admission required')
    require(admission.get('source_sha256')==before and admission.get('endpoints')==endpoints,'Admission source/endpoints differ')
    require(admission.get('runtime_identical_to_study_v032')is True and admission.get('all_four_owned_healthy_idle')is True,'Qualified four-node runtime/idle admission required')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--source',type=Path,default=HERE/'.runtime/nemotron72-followup-source');p.add_argument('--endpoint',action='append');p.add_argument('--admission',type=Path);p.add_argument('--plan-file',type=Path);p.add_argument('--run',action='store_true');a=p.parse_args(argv)
    plan=read(PLAN);source=a.source.expanduser().resolve();output=a.output.resolve();endpoints=a.endpoint or[f'http://127.0.0.1:{port}/v1'for port in range(18081,18085)]
    require(plan['protocol']=='nemotron72-known-single-v1'and plan['selected_variant']=='scribe_full','Wrong protocol/recipe');validate_source(source);before=hashes(source)
    dataset=source/'datasets/arithmetic-v1/tasks.json';require(sha(dataset)==plan['matrix']['dataset_sha256'],'Corpus hash differs')
    for path,key in((plan['development_selection']['path'],'sha256'),(plan['development_selection']['audit_path'],'audit_sha256')):require(sha(HERE/path)==plan['development_selection'][key],'Development selection/audit changed')
    cases=make_cases(read(dataset),output,endpoints,source,plan)
    meta=dict(protocol=plan,mode='run'if a.run else'plan',cases=cases,attempts=72,source_sha256=before,solver_source_revision=REVISION,solver_source=str(source),controller_deadline_seconds=180,request_timeout_seconds=210,maximum_calls_per_case=2,global_completion_cap_per_case=8192,output=str(output),scope=plan['scope'])
    if not a.run:
        if a.plan_file:require(not a.plan_file.exists(),'Plan file exists');write(a.plan_file,meta)
        print(json.dumps(dict(mode='plan',cases=72,variant='scribe_full',model_calls=0,scope=plan['scope'])));return 0
    require(plan['status']=='FROZEN'and not output.exists()and a.admission,'Frozen protocol, new output, and admission required');admission=read(a.admission);admission_check(admission,before,endpoints)
    output.mkdir(parents=True);start=time.monotonic();meta.update(started_utc=datetime.now(timezone.utc).isoformat(),admission=admission,admission_sha256=sha(a.admission));write(output/'metadata.json',meta)
    rows,errors,attempted,lock,stop=[],[],[],threading.Lock(),threading.Event()
    try:
        with ThreadPoolExecutor(max_workers=4)as pool:
            futures=[pool.submit(run_queue,[c for c in cases if c['slot']==slot],before,source,output,rows,errors,attempted,lock,stop)for slot in range(4)]
            for future in futures:future.result()
    except Exception as exc:stop.set();errors.append(dict(reason='controller_exception',detail=f'{type(exc).__name__}: {exc}'))
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(),batch_wall_seconds=time.monotonic()-start,completed_cases=len(rows),incomplete=len(rows)!=72,errors=errors,attempted_case_events=attempted,final_source_sha256=hashes(source));meta['source_changed_during_run']=before!=meta['final_source_sha256'];meta['output_sha256']={p.name:sha(p)for p in output.iterdir()if p.is_file()and p.name!='metadata.json'};write(output/'metadata.json',meta)
    return int(bool(errors)or meta['incomplete']or meta['source_changed_during_run'])
if __name__=='__main__':raise SystemExit(main())
