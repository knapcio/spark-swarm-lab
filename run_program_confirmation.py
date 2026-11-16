#!/usr/bin/env python3
"""Optional frozen-program confirmation; plan-only unless --run is explicit."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.request

from csp_program_grader import evaluate_program
from csp_tasks import graph_digest, load_tasks, verify_assignment
from program_search import followup_gate, infrastructure
from run_benchmark import drain

HERE=Path(__file__).resolve().parent
CONFIG='PROGRAM_CONFIRMATION_EXECUTION.json'
PLAN_SHA='4b25b675ace76ecfd15863241cd28178d9b3f5e4ad0171f5cbc945451eaf9061'
PROGRAM_REVISION='c5ed1190ac380cf1ed1193b0bd7971dcc0eb1bae'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def require(ok,message):
    if not ok:raise RuntimeError(message)
def now():return datetime.now(timezone.utc).isoformat()
def write(path,value):
    with Path(path).open('x')as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False)
def pins(paths):return {str(p):sha(p)if p.is_file()else None for p in paths}
def git_identity(cfg):
    call=lambda *a:subprocess.check_output(['git','-C',str(HERE),*a],text=True).strip()
    tracked=set(call('ls-files').splitlines())
    require(not call('status','--porcelain','--untracked-files=no')and set(cfg['source_sha256'])|{CONFIG}<=tracked,'Clean committed confirmation source required')
    return dict(revision=call('rev-parse','HEAD'),source_files_tracked=True,tracked_clean=True)

def configuration():
    cfg=read(HERE/CONFIG)
    require(cfg['upstream_plan_sha256']==PLAN_SHA==sha(HERE/'PROGRAM_CONFIRMATION_SELECTION.json'),'Confirmation plan changed')
    upstream=read(HERE/'PROGRAM_CONFIRMATION_SELECTION.json')
    require(cfg['dataset']==upstream['dataset']and sha(HERE/cfg['dataset'])==upstream['dataset_sha256']and all(sha(HERE/n)==h for n,h in upstream['source_sha256'].items()),'Prospective corpus/grader pins changed')
    require(cfg['arms']==upstream['program_population']['arms'],'All original program arms required')
    require(cfg['program_source_revision']==PROGRAM_REVISION and cfg['image']=='python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd','Wrong frozen producer/image')
    require(all(sha(HERE/n)==h for n,h in cfg['source_sha256'].items()),'Confirmation source/data changed')
    tasks=load_tasks(HERE/cfg['dataset'],'evaluation')
    require(len(tasks)==96 and len({graph_digest(t)for t in tasks})==96,'Expected exact96 unique public graphs')
    return cfg,tasks

def validate_report(task,report):
    require(not infrastructure(report),'Grade infrastructure or cleanup failure')
    require(report.get('provenance')=='candidate'and report.get('grading_authority')=='outer_parent'and report.get('oracle_sent_to_child')is False,'Unqualified grading authority')
    require(report.get('graph_sha256')==graph_digest(task)and type(report.get('solved'))is bool,'Wrong graph or missing outcome')
    require(report.get('status')in ('passed','failed','error','timeout'),'Unknown candidate grade status')
    if report.get('proof')is not None:
        require('candidate_output'in report and verify_assignment(task,report['candidate_output'])==report['proof'],'Graph proof cannot be replayed')
    require(report['status']not in ('passed','failed')or report.get('proof')is not None,'Assignment grade lacks exact proof')
    if report['solved']:
        require(report.get('status')=='passed'and report.get('input_unchanged')is True and (report.get('proof')or{}).get('solved')is True,'Unproven positive grade')
    require((report['status']=='passed')==report['solved'],'Inconsistent pass/solved outcome')

def completed_programs(directory,cfg):
    meta=read(directory/'metadata.json');rows=read(directory/'results.json');selection=read(HERE/'PROGRAM_SEARCH_SELECTION.json')
    expected=dict(selection['source_sha256'],**{'PROGRAM_SEARCH_SELECTION.json':sha(HERE/'PROGRAM_SEARCH_SELECTION.json')})
    source=meta.get('source',{})
    require(meta.get('mode')=='run'and meta.get('complete')is True and meta.get('verified')is True and not meta.get('faults'),'Program master incomplete')
    require(source.get('revision')==PROGRAM_REVISION and source.get('tracked_clean')is True and source.get('source_files_tracked')is True
            and source.get('sha256')==expected and meta.get('source_after')==source,'Frozen program source identity changed')
    require(meta.get('completed_programs')==meta.get('recorded_episodes')==8 and len(rows)==8,'Expected all8 programs')
    require(meta.get('selection_sha256')==sha(HERE/'PROGRAM_SEARCH_SELECTION.json')and meta.get('dataset_sha256')==sha(HERE/'datasets/csp-v1/tasks.json'),'Original program selection/data changed')
    qualification=directory/'program-grader-qualification.json';qual=read(qualification)
    require(qual==meta.get('grader_qualification')and qual.get('verified')is True and qual.get('model_calls')==0,'Original3live-smoke receipt invalid')
    require(len(qual.get('rows',[]))==3 and {r.get('name')for r in qual['rows']}=={'valid','wrong','forged_grade'},'Original3smoke identities missing')
    for r in qual['rows']:
        validate_report(r['task'],r['report'])
        require(r['report']['solved']is(r['name']=='valid'),'Smoke outcome mismatch')
        expected_smoke={'valid':('passed',None),'wrong':('failed','candidate_graph_failure'),'forged_grade':('error','candidate_protocol')}[r['name']]
        require((r['report']['status'],r['report'].get('failure_kind'))==expected_smoke,'Original smoke classification differs')
    evaluation=load_tasks(HERE/'datasets/csp-v1/tasks.json','evaluation');bindings=[];paths=[directory/'metadata.json',directory/'results.json',qualification,directory/'development-inputs.json',directory/'evaluation-inputs.json']
    require(read(paths[-2])==load_tasks(HERE/'datasets/csp-v1/tasks.json','development')and read(paths[-1])==evaluation,'Original4/12 graph inputs changed')
    expected_keys={(s,a)for s in range(1,5)for a in cfg['arms']}
    require({(r['seed'],r['arm'])for r in rows}==expected_keys,'Program episode grid differs')
    for r in sorted(rows,key=lambda r:(r['seed'],cfg['arms'].index(r['arm']))):
        seed,arm=r['seed'],r['arm'];episode=directory/f'seed-{seed}-{arm}';selected=episode/'selected.py';choice_path=episode/'selection.json';choice=read(choice_path)
        require(r.get('host')==f'Spark_{seed:02d}'and r.get('complete')is True and r.get('status')=='complete'and r.get('training_candidates_scored')==16
                and r.get('calls')==16 and r.get('model_budget',{}).get('calls')==16 and r.get('evaluation_completed')==r.get('evaluation_graphs')==12,'Original episode budget/coverage incomplete')
        require(choice.get('evaluation_seen')is False and choice.get('model_calls_at_selection')==16 and choice.get('seed')==seed and choice.get('arm')==arm,'Selection did not freeze before evaluation')
        require(sha(selected)==choice.get('code_sha256')==r.get('selected_sha256'),'Selected program SHA changed')
        for task in evaluation:
            path=episode/f"evaluation-{task['id']}.json";old=read(path);paths.append(path)
            require(old['task_id']==task['id']and old['selected_sha256']==sha(selected)and old['graph_sha256']==graph_digest(task),'Original evaluation identity differs')
            validate_report(task,old['report'])
        paths.extend([selected,choice_path])
        bindings.append(dict(seed=seed,arm=arm,host=f'Spark_{seed:02d}',code_sha256=sha(selected),source_path=str(selected),selection_path=str(choice_path)))
    return bindings,paths

def admission(root,directory,receipt,cfg):
    gate=followup_gate(root)  # Exact45 plus exact10 completed/eligible-skipped post stages.
    bindings,paths=completed_programs(directory,cfg)
    meta=read(directory/'metadata.json');require(meta.get('gate')==gate,'Original program gate differs')
    evidence=read(receipt);age=(datetime.now(timezone.utc)-datetime.fromisoformat(evidence['checked_utc'].replace('Z','+00:00'))).total_seconds()
    require(evidence.get('verified')is True and evidence.get('model_switch_started')is False and evidence.get('workloads_drained')is True and evidence.get('optional_time_admitted')is True and -60<=age<=900,'Fresh pre-switch owner admission required')
    nodes=evidence.get('nodes',[])
    require(len(nodes)==4 and {n.get('seed')for n in nodes}=={1,2,3,4},'Four distinct owner-qualified nodes required')
    runtime=read(HERE/'runtime.json')
    for node in nodes:
        seed=node['seed'];require(node.get('host')==f'Spark_{seed:02d}'and node.get('endpoint')==f'http://127.0.0.1:{18080+seed}/v1'
          and node.get('healthy')is True and node.get('idle')is True and node.get('owner')=='swarm-lab-20261115'
          and node.get('runtime_sha256')==cfg['source_sha256']['runtime.json']and node.get('image')=='vllm/vllm-openai@'+runtime['arm64_manifest_digest']
          and node.get('model_revision')==runtime['model_revision']and node.get('draft_revision')==runtime['dspark']['draft_revision'],'Wrong endpoint/owner/runtime admission')
    input_pins=pins(paths+[receipt])
    with ThreadPoolExecutor(4)as pool:observed=list(pool.map(idle_health,nodes))
    require(all(x['idle']and x['healthy']for x in observed),'Allfour Nemotron replicas must currently be healthy and idle')
    require(pins(paths+[receipt])==input_pins,'Original program/admission changed during health checks')
    paths.extend([receipt,root/'.runtime/post-throughput-overnight-v1/state.json',root/'.runtime/post-throughput-overnight-v1/ledger.json'])
    return bindings,paths,dict(gate=gate,owner_receipt_sha256=sha(receipt),program_inputs_sha256=input_pins,observed=observed)

def idle_health(node):
    _,idle,seconds=drain(node['endpoint'])
    with urllib.request.urlopen(node['endpoint'].removesuffix('/v1')+'/health',timeout=3)as response:healthy=response.status==200
    return dict(endpoint=node['endpoint'],idle=idle is True,healthy=healthy,drain_seconds=seconds)

def execute(bindings,tasks,directory,before,evaluator=evaluate_program,pinner=None):
    pinner=pinner or(lambda:pins([Path(p)for p in before]));stop=threading.Event();lock=threading.Lock();rows=[];faults=[];began=time.monotonic()
    def unchanged():require(pinner()==before,'Bound source/data/program changed during confirmation')
    def worker(seed):
        programs=[b for b in bindings if b['seed']==seed]
        if seed%2==0:programs.reverse()
        for binding in programs:
            for task in tasks:
                if stop.is_set():return
                job=dict(seed=seed,arm=binding['arm'],host=binding['host'],task_id=task['id'],graph_sha256=graph_digest(task),code_sha256=binding['code_sha256'])
                job['job_id']=hashlib.sha256(json.dumps(job,sort_keys=True).encode()).hexdigest();start=time.monotonic()
                try:
                    unchanged();code=Path(binding['source_path']).read_bytes().decode('utf-8');require(hashlib.sha256(code.encode()).hexdigest()==binding['code_sha256'],'Selected source changed')
                    report=evaluator(code,task,binding['host'],timeout=10);job['report']=report
                    unchanged();validate_report(task,report)
                    payload=json.dumps(dict(code=code,function_name='solve',calls=[dict(args=[task['vertex_count'],task['color_count'],task['edges']],kwargs={})],timeout=10),allow_nan=False)
                    require(report.get('child_payload_sha256')==hashlib.sha256(payload.encode()).hexdigest(),'Grade payload/source identity mismatch')
                    job.update(infrastructure=False,solved=report['solved'])
                except Exception as exc:
                    stop.set();job.update(infrastructure=True,solved=None,error_classification=type(exc).__name__,error=str(exc)[:300])
                    with lock:faults.append(dict(job_id=job['job_id'],error=job['error']))
                job['controller_wall_seconds']=time.monotonic()-start
                with lock:
                    rows.append(job)
                    with(directory/'grades.jsonl').open('a')as stream:stream.write(json.dumps(job,ensure_ascii=False,allow_nan=False)+'\n');stream.flush()
                if stop.is_set():return
    with ThreadPoolExecutor(4)as pool:list(pool.map(worker,range(1,5)))  # Wait for every owned cleanup before returning.
    after=pinner();changed=after!=before
    expected={(b['seed'],b['arm'],t['id'])for b in bindings for t in tasks};actual={(r['seed'],r['arm'],r['task_id'])for r in rows}
    complete=len(rows)==len(actual)==len(expected)==768 and actual==expected and not faults and not changed
    return rows,dict(verified=complete,complete=complete,incomplete=not complete,completed_jobs=len(rows),planned_jobs=768,
        missing_jobs=768-len(actual),faults=faults,source_after=after,source_changed_during_run=changed,
        wall_seconds=time.monotonic()-began,model_calls=0,remote_cpu_seconds=None,
        cost_scope='Fresh CPU grades; full wall includes container/SSH/cleanup. Remote CPU not measured; no model-call equivalence.')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gate-root',type=Path,default=HERE);p.add_argument('--program-run',type=Path);p.add_argument('--admission',type=Path);p.add_argument('--output',type=Path);p.add_argument('--run',action='store_true');args=p.parse_args(argv)
    cfg,tasks=configuration();root=args.gate_root.resolve();master=(args.program_run or root/'runs/program-search-v1').resolve()
    plan=dict(protocol=cfg['protocol'],mode='run'if args.run else'plan',programs=8,graphs=96,planned_jobs=768,model_calls=0,program_run=str(master),dataset_sha256=sha(HERE/cfg['dataset']),upstream_plan_sha256=PLAN_SHA)
    if not args.run:print(json.dumps(plan,indent=2));return 0
    require(args.output is not None and args.admission is not None,'--run requires new --output and fresh --admission receipt')
    directory=args.output.resolve();require(not directory.exists()and directory.is_relative_to(root/'runs'),'New output under gate-root/runs required')
    identity=git_identity(cfg);bindings,paths,gate=admission(root,master,args.admission.resolve(),cfg)
    paths.extend(HERE/n for n in list(cfg['source_sha256'])+[CONFIG]);before=pins(paths)
    directory.mkdir(parents=True);write(directory/'bindings.json',bindings);(directory/'corpus.json').write_bytes((HERE/cfg['dataset']).read_bytes());copies=[directory/'bindings.json',directory/'corpus.json']
    require(sha(copies[-1])==cfg['source_sha256'][cfg['dataset']],'Copied corpus differs from frozen data')
    for b in bindings:
        target=directory/f"selected-s{b['seed']}-{b['arm']}.py";target.write_bytes(Path(b['source_path']).read_bytes());copies.append(target);require(sha(target)==b['code_sha256'],'Evidence copy differs')
    require(pins(paths)==before,'Admission sources changed before binding freeze');before.update(pins(copies))
    meta=dict(plan,started_utc=now(),gate=gate,image=cfg['image'],runner_source=identity,source_before=before,bindings_sha256=sha(directory/'bindings.json'),corpus_sha256=sha(directory/'corpus.json'),configuration_sha256=sha(HERE/CONFIG),upstream_qualification_sha256=sha(master/'program-grader-qualification.json'))
    write(directory/'metadata.json',meta)  # All8 immutable bindings/evidence precede FIRST grade.
    rows,status=execute(bindings,tasks,directory,before)
    try:
        with ThreadPoolExecutor(4)as pool:status['final_idle_health']=list(pool.map(idle_health,gate['observed']))
        require(all(x['idle']and x['healthy']for x in status['final_idle_health']),'Final idle boundary changed')
    except Exception as exc:
        status.update(complete=False,verified=False,incomplete=True);status['faults'].append(dict(boundary='final_idle_health',error_classification=type(exc).__name__))
    status['source_after']=pins([Path(p)for p in before]);status['source_changed_during_run']=status['source_after']!=before
    try:status['runner_source_after']=git_identity(cfg)
    except Exception:status['runner_source_after']=None
    if status['source_changed_during_run']or status['runner_source_after']!=identity:
        status.update(complete=False,verified=False,incomplete=True);status['faults'].append(dict(boundary='final_bound_source',error_classification='source_integrity'))
    final={k:dict(planned_jobs=384,recorded_jobs=sum(r['arm']==k for r in rows),known_solved=sum(r.get('solved')is True for r in rows if r['arm']==k),known_unsolved=sum(r.get('solved')is False for r in rows if r['arm']==k),unknown_outcomes=384-sum(r.get('solved')is not None for r in rows if r['arm']==k))for k in cfg['arms']}
    meta.update(status,completed_utc=now());write(directory/'summary.json',dict(arms=final,status=status))
    temporary=directory/'metadata.final.json';write(temporary,meta);temporary.replace(directory/'metadata.json')
    print(json.dumps(status));return 0 if status['complete']else 1

if __name__=='__main__':raise SystemExit(main())
