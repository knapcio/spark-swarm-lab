#!/usr/bin/env python3
"""Optional late exploratory four-program/96-graph CPU replay; default plan reads no outcomes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib,json
from pathlib import Path
import subprocess,threading,time
from csp_program_grader import evaluate_program
from csp_tasks import graph_digest,load_tasks
from program_search import followup_gate
from run_program_confirmation import idle_health,pins,read,require,sha,validate_report,write,now

HERE=Path(__file__).resolve().parent
CONFIG='PROGRAM_REVIEW_CONFIRMATION_EXECUTION.json'
PRODUCER='d704ae12ad5f78606090d3cb1e151ffbee28eebd'
SELECTION='4ead89b088c11f8d39bd052c7d9a9a2ff5f1849639de3a66f96ed0ad919dad68'
CORPUS='b1267cbd9f371383402ff116a9139c22515c046d924d6b6f6b6df2cee8fda85e'
IMAGE='python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd'
QUALIFIED={'csp_program_grader.py':'7fa45db50bfbef04c868b35ddb3aab67fceab4818ca5820bba2427f14ff6873a','independent_code_grader.py':'c4324123bb75a8712150adb3e06e1da4e1e44a7d91516597d9a35caa372c2726','runtime.json':'072b628126f36aa559fa864372118c7e0497e44d1b37d29be99ea3c7f8cf6ec5'}

def identity(cfg):
    call=lambda *a:subprocess.check_output(['git','-C',str(HERE),*a],text=True).strip()
    require(not call('status','--porcelain','--untracked-files=no')and set(cfg['source_sha256'])|{CONFIG}<=set(call('ls-files').splitlines()),'Clean committed runner required')
    return dict(revision=call('rev-parse','HEAD'),tracked_clean=True,source_files_tracked=True)

def grade_check(task,report,code):
    validate_report(task,report)
    if report.get('proof')is not None and report['status']in ('passed','failed'):
        require(type(report.get('input_unchanged'))is bool,'Missing mutation observation')
        require(report['solved']is(report['proof']['solved']and report.get('input_unchanged')is True),'Negative proof/mutation mismatch')
    payload=json.dumps(dict(code=code,function_name='solve',calls=[dict(args=[task['vertex_count'],task['color_count'],task['edges']],kwargs={})],timeout=10),allow_nan=False)
    require(report.get('child_payload_sha256')==hashlib.sha256(payload.encode()).hexdigest(),'Source/input payload mismatch')

def producer_bindings(source,directory):
    require(subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==PRODUCER,'Wrong producer Git')
    selection=source/'PROGRAM_REVIEW_ELITES_SELECTION.json';require(sha(selection)==SELECTION,'Wrong producer selection')
    expected=dict(read(selection)['source_sha256'],**{selection.name:SELECTION})
    require(len(expected)==14 and all(sha(source/n)==h for n,h in expected.items()),'Producer14 source pins')
    meta=read(directory/'metadata.json');source_id=meta.get('source',{})
    require(meta.get('complete')is True and meta.get('verified')is True and not meta.get('faults')and meta.get('selection_sha256')==SELECTION,'Producer incomplete')
    require(source_id==meta.get('source_after')and source_id.get('revision')==PRODUCER and source_id.get('sha256')==expected
        and source_id.get('tracked_clean')is True and source_id.get('source_files_tracked')is True,'Producer source identity')
    dev=load_tasks(source/'datasets/csp-v1/tasks.json','development');evaluation=load_tasks(source/'datasets/csp-v1/tasks.json','evaluation')
    require(len(dev)==4 and len(evaluation)==12 and read(directory/'development-inputs.json')==dev and read(directory/'evaluation-inputs.json')==evaluation,'Original4/12 corpus mismatch')
    qual=read(directory/'program-grader-qualification.json');require(qual==meta.get('grader_qualification')and qual.get('verified')is True and qual.get('model_calls')==0,'Three-smoke qualification')
    require({q['name']for q in qual['rows']}=={'valid','wrong','forged_grade'}and len(qual['rows'])==3,'Smoke grid')
    for q in qual['rows']:
        grade_check(q['task'],q['report'],q['code']);want={'valid':('passed',None),'wrong':('failed','candidate_graph_failure'),'forged_grade':('error','candidate_protocol')}[q['name']]
        require((q['report']['status'],q['report'].get('failure_kind'))==want and q['report']['solved']is(q['name']=='valid'),'Smoke classification')
    episodes=read(directory/'results.json');require(len(episodes)==meta.get('completed_programs')==meta.get('recorded_episodes')==meta.get('planned_selected_programs')==4 and {(e['arm'],e['seed'])for e in episodes}=={('review_elites4',s)for s in range(1,5)},'All four programs required')
    bindings=[]
    for episode in sorted(episodes,key=lambda e:e['seed']):
        seed=episode['seed'];folder=directory/f'seed-{seed}-review_elites4';choice=read(folder/'selection.json');code=(folder/'selected.py').read_bytes().decode('utf-8')
        events=[json.loads(x)for x in(folder/'events.jsonl').read_text().splitlines()if x.strip()];starts=[e for e in events if e['type']=='request_start'];ends=[e for e in events if e['type']=='request_end'];selected=[e for e in events if e['type']=='program_selected']
        require(episode.get('host')==f'Spark_{seed:02d}'and episode.get('complete')is True and episode.get('status')=='complete'and episode.get('calls')==episode.get('completed_calls')==16 and episode.get('unfinished_calls')==0 and episode.get('training_candidates_scored')==10 and episode.get('evaluation_completed')==12,'Episode allocation')
        require(len(starts)==len(ends)==16 and len({e['request_id']for e in starts})==16 and {e['request_id']for e in starts}=={e['request_id']for e in ends}and all(not e.get('error')for e in ends),'Sixteen complete requests')
        require(len([e for e in events if e['type']=='program_candidate'])==len([e for e in events if e['type']=='development_candidate_scored'])==10 and {e['index']for e in events if e['type']=='program_candidate'}==set(range(10)) and len([e for e in events if e['type']=='program_review'])==6 and len([e for e in starts if e['stage'].startswith('review-')])==6 and len([e for e in starts if e['stage'].startswith('program-')])==10,'Ten candidate/six review trace')
        require(len(selected)==1 and selected[0]['candidate_index']==choice['candidate_index']and selected[0]['code_sha256']==choice['code_sha256']==sha(folder/'selected.py')==episode['selected_sha256']and choice.get('evaluation_seen')is False and choice.get('model_calls_at_selection')==16 and choice.get('seed')==seed and choice.get('arm')=='review_elites4','Selection/source binding')
        require(max(e['event_id']for e in ends)<selected[0]['event_id']and all(e['event_id']>selected[0]['event_id']for e in events if e.get('phase')=='evaluation'),'Selection must precede evaluation; no later calls')
        grades=[e for e in events if e['type']=='program_grade_end'and e['phase']=='evaluation'];require(len(grades)==12 and {e['task_id']for e in grades}=={t['id']for t in evaluation},'Original twelve grade trace')
        for task in evaluation:
            old=read(folder/f"evaluation-{task['id']}.json");require(old['task_id']==task['id']and old['graph_sha256']==graph_digest(task)and old['selected_sha256']==choice['code_sha256']and old['report']==next(e['report']for e in grades if e['task_id']==task['id']),'Original evaluation identity');grade_check(task,old['report'],code)
        bindings.append(dict(seed=seed,arm='review_elites4',host=f'Spark_{seed:02d}',code_sha256=choice['code_sha256'],source_path=str(folder/'selected.py')))
    return bindings,[p for p in directory.rglob('*')if p.is_file()]+[source/n for n in expected]

def admit(root,path,cfg):
    gate=followup_gate(root);receipt=read(path);age=(datetime.now(timezone.utc)-datetime.fromisoformat(receipt['checked_utc'].replace('Z','+00:00'))).total_seconds()
    require(receipt.get('verified')is True and receipt.get('model_switch_started')is False and receipt.get('feature_switch_started')is False and receipt.get('workloads_drained')is True and receipt.get('optional_time_admitted')is True and -60<=age<=900,'Fresh exclusive pre-feature admission required')
    nodes=receipt.get('nodes',[]);runtime=read(HERE/'runtime.json');require(len(nodes)==4 and {n.get('seed')for n in nodes}=={1,2,3,4},'Four admitted nodes')
    for n in nodes:require(n.get('host')==f"Spark_{n['seed']:02d}"and n.get('endpoint')==f"http://127.0.0.1:{18080+n['seed']}/v1"and n.get('healthy')is True and n.get('idle')is True and n.get('owner')=='swarm-lab-20261115'and n.get('image')=='vllm/vllm-openai@'+runtime['arm64_manifest_digest']and n.get('model_revision')==runtime['model_revision']and n.get('draft_revision')==runtime['dspark']['draft_revision']and n.get('runtime_sha256')==cfg['source_sha256']['runtime.json'],'Wrong node/runtime/owner')
    with ThreadPoolExecutor(4)as pool:observed=list(pool.map(idle_health,nodes))
    require(all(n['idle']and n['healthy']for n in observed),'Initial current health/drain')
    return nodes,dict(original_gate=gate,admission=receipt,observed=observed)

def copy_inputs(bindings,directory,corpus):
    executed=[];copies=[]
    for b in bindings:
        target=directory/f"selected-s{b['seed']}.py";target.write_bytes(Path(b['source_path']).read_bytes());require(sha(target)==b['code_sha256'],'Copied source mismatch')
        executed.append(dict(b,producer_source_path=b['source_path'],source_path=str(target)));copies.append(target)
    (directory/'corpus.json').write_bytes(corpus.read_bytes());require(sha(directory/'corpus.json')==sha(corpus),'Copied corpus mismatch');write(directory/'bindings.json',executed)
    return executed,copies+[directory/'bindings.json',directory/'corpus.json']

def execute(bindings,tasks,directory,before,evaluator=evaluate_program,pinner=None):
    pinner=pinner or(lambda:pins([Path(p)for p in before]));stop=threading.Event();lock=threading.Lock();rows=[];faults=[]
    def worker(binding):
        for task in tasks:
            if stop.is_set():return
            row=dict(seed=binding['seed'],arm='review_elites4',host=binding['host'],task_id=task['id'],graph_sha256=graph_digest(task),code_sha256=binding['code_sha256']);row['job_id']=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest();began=time.monotonic()
            try:
                require(pinner()==before,'Bound inputs changed');code=Path(binding['source_path']).read_bytes().decode('utf-8');require(hashlib.sha256(code.encode()).hexdigest()==binding['code_sha256'],'Source changed')
                report=evaluator(code,task,binding['host'],timeout=10);row['report']=report;grade_check(task,report,code);require(pinner()==before,'Bound inputs changed');row.update(infrastructure=False,solved=report['solved'])
            except Exception as exc:
                stop.set();row.update(infrastructure=True,solved=None,error=str(exc)[:300])
                with lock:faults.append(dict(job_id=row['job_id'],error=row['error']))
            row['controller_wall_seconds']=time.monotonic()-began
            with lock:
                rows.append(row)
                with(directory/'grades.jsonl').open('a')as stream:stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    with ThreadPoolExecutor(4)as pool:list(pool.map(worker,bindings))
    return rows,faults

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--gate-root',type=Path,default=HERE);p.add_argument('--producer-source',type=Path);p.add_argument('--program-run',type=Path);p.add_argument('--admission',type=Path);p.add_argument('--output',type=Path);args=p.parse_args(argv)
    if not args.run:print(json.dumps(dict(mode='plan',programs=4,graphs=96,cpu_grades=384,model_calls=0,scope='Late exploratory on operator-known fresh96; all4 selected programs, no filtering/repair, original12 separate')));return 0
    require(args.output and args.admission,'New output and fresh owner admission required');root=args.gate_root.resolve();directory=args.output.resolve();source=(args.producer_source or root/'.runtime/program-review-elites4-source').resolve();master=(args.program_run or root/'runs/program-review-elites4-v1').resolve()
    require(not directory.exists()and directory.is_relative_to(root/'runs'),'New output under gate-root/runs required');cfg=read(HERE/CONFIG);require(cfg['producer_revision']==PRODUCER and cfg['producer_selection_sha256']==SELECTION and cfg['corpus_sha256']==CORPUS and cfg['image']==IMAGE and all(cfg['source_sha256'].get(n)==h for n,h in QUALIFIED.items())and all(sha(HERE/n)==h for n,h in cfg['source_sha256'].items()),'Runner configuration pins')
    ident=identity(cfg);tasks=load_tasks(HERE/'datasets/program-confirmation-v1/tasks.json','evaluation');require(sha(HERE/'datasets/program-confirmation-v1/tasks.json')==CORPUS and len(tasks)==len({graph_digest(t)for t in tasks})==96,'Exact existing96 corpus')
    late=root/'runs/csp-thinking_on16-evaluation-s1-late/metadata.json';late_meta=read(late);require(late_meta.get('verified')is True and late_meta.get('incomplete')is False and not late_meta.get('faults')and late_meta.get('source_changed_during_run')is False,'Late reasoning must finish first')
    bindings,paths=producer_bindings(source,master);paths += [root/n for n in ('runs/evaluation-v2-ledger.json','runs/solo-control-v2-ledger.json','runs/throughput-development-v2-ledger.json','runs/throughput-followup-v2-ledger.json','runs/throughput-development-v2-recovery.json','runs/throughput-followup-v2-selection.json','runs/throughput-followup-v2-complete.json','.runtime/post-throughput-overnight-v1/state.json','.runtime/post-throughput-overnight-v1/ledger.json')]
    paths += [args.admission.resolve(),late]+[HERE/n for n in list(cfg['source_sha256'])+[CONFIG]];before=pins(paths);require(all(h is not None for h in before.values()),'Bound inputs missing');nodes,gate=admit(root,args.admission,cfg);require(pins(paths)==before and read(master/'metadata.json')['gate']==gate['original_gate'],'Admission inputs/original gate changed')
    began=time.monotonic();started=now();directory.mkdir(parents=True);bindings,copies=copy_inputs(bindings,directory,HERE/'datasets/program-confirmation-v1/tasks.json')
    before.update(pins(copies));require(pins(paths)=={k:v for k,v in before.items()if k in set(map(str,paths))},'Inputs changed before first grade');meta=dict(protocol='late-review-program-confirmation-v1',started_utc=started,programs=4,graphs=96,planned_jobs=384,model_calls=0,image=IMAGE,producer_revision=PRODUCER,producer_selection_sha256=SELECTION,corpus_sha256=CORPUS,runner_source=ident,source_before=before,gate=gate,scope='Late exploratory same-generator operator-known96; no new training, model calls, source repairs or filtering; original12 separate; remote CPU unknown');write(directory/'metadata.json',meta)
    rows,faults=execute(bindings,tasks,directory,before);finished=None;final_ident=None
    try:
        with ThreadPoolExecutor(4)as pool:finished=list(pool.map(idle_health,nodes))
        require(all(n['idle']and n['healthy']for n in finished),'Final current health/drain');final_ident=identity(cfg);require(final_ident==ident,'Runner identity changed')
    except Exception as exc:faults.append(dict(boundary='final',error=str(exc)[:300]))
    after=pins([Path(p)for p in before]);expected={(b['seed'],t['id'])for b in bindings for t in tasks};actual={(r['seed'],r['task_id'])for r in rows};complete=len(rows)==len(actual)==384 and actual==expected and not faults and before==after
    meta.update(complete=complete,verified=complete,incomplete=not complete,completed_jobs=len(rows),missing_jobs=384-len(actual),faults=faults,source_after=after,source_changed_during_run=before!=after,runner_source_after=final_ident,final_idle_health=finished,completed_utc=now(),remote_cpu_seconds=None,wall_seconds=time.monotonic()-began,wall_scope='After admitted health/idle boundary through input-copy setup, CPU workers and final owned cleanup/health/drain/source checks; excludes admission qualification and historical training');write(directory/'summary.json',dict(status=meta,solved=sum(r.get('solved')is True for r in rows),unknown=sum(r.get('solved')is None for r in rows)));(directory/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n');return 0 if complete else 1

if __name__=='__main__':raise SystemExit(main())
