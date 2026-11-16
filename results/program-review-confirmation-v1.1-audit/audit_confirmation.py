"""Independent offline proof/trace replay. Reads generated source as data; never executes it."""
from pathlib import Path
from collections import Counter
import ast,hashlib,json,datetime,sys
R=Path(__file__).resolve().parents[2];O=R/'runs/program-review-confirmation-v1.1';F=R/'.runtime/program-review-confirmation-source-v1.1';OUT=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
h=lambda s:hashlib.sha256(s.encode()).hexdigest()
canon=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def ck(v,m):
 if not v:raise AssertionError(m)
def digest(t):return h(canon({k:t[k]for k in ['vertex_count','color_count','edges']}))
def proof(t,p):
 valid=isinstance(p,dict)and set(p)=={'assignment'}and isinstance(p['assignment'],list)and len(p['assignment'])==t['vertex_count']and all(type(v)is int and 0<=v<t['color_count']for v in p['assignment'])
 bad=[i for i,(u,v)in enumerate(t['edges'])if p['assignment'][u]==p['assignment'][v]]if valid else[]
 return dict(solved=valid and not bad,valid_schema=valid,conflicts=len(bad)if valid else None,violating_edges=bad,fitness=[1,-len(bad)]if valid else[0,0])
def grade(t,q,code):
 ck(q.get('cleanup_ok')is True and q.get('provenance')=='candidate'and q.get('grading_authority')=='outer_parent'and q.get('oracle_sent_to_child')is False,'grader authority/cleanup')
 ck(q.get('graph_sha256')==digest(t)and type(q.get('solved'))is bool,'grade identity')
 ck(q['status']in('passed','failed','error','timeout')and not str(q.get('failure_kind','')).endswith('_infrastructure'),'grade infrastructure')
 if q.get('container_state')is not None:ck(q['container_state'].get('Running')is False,'container running')
 v=None
 if q.get('proof')is not None:
  ck('candidate_output'in q,'proof output absent');v=proof(t,q['candidate_output'])
  for k,x in v.items():ck(q['proof'][k]==x and (type(q['proof'][k])is bool if k in ('solved','valid_schema')else True),('proof',t['id'],k))
  ck((q['proof']['error']is None)==v['valid_schema'],'schema error flag')
  ck(q['graph_verifier_calls']==1 and q['graph_edge_checks']==(len(t['edges'])if v['valid_schema']else 0),'verifier counters')
 else:ck(q.get('graph_verifier_calls',0)==0,'unexpected verifier work')
 ck(q['status']not in('passed','failed')or v is not None,'assignment without proof')
 ck((q['status']=='passed')==q['solved'],'status/solved')
 if q['solved']:ck(v is not None and v['solved']and q.get('input_unchanged')is True and q.get('failure_kind')is None,'false success')
 if q['status']=='failed':ck(v is not None and(not v['solved']or q.get('input_unchanged')is not True),'unexplained negative')
 payload=json.dumps(dict(code=code,function_name='solve',calls=[dict(args=[t['vertex_count'],t['color_count'],t['edges']],kwargs={})],timeout=10),allow_nan=False)
 ck(h(payload)==q['child_payload_sha256'],'code/graph child payload')
 ck(q.get('remote_cpu_seconds')is None,'fabricated CPU cost')
 return v

P=R/'runs/program-review-elites4-v1.1';ap=R/'.runtime/program-review-confirmation-admission-v1.1/manual-admission.json'
pin=read(R/'.runtime/PROGRAM_REVIEW_CONFIRMATION_FROZEN_V1_1.json');cfg=read(F/'PROGRAM_REVIEW_CONFIRMATION_EXECUTION.json');launch=read(R/'.runtime/PROGRAM_REVIEW_CONFIRMATION_LAUNCH_V1_1.json');m=read(O/'metadata.json');ad=read(ap)
ck(pin['revision']==launch['source_revision']==m['runner_source']['revision']=='9dda2a9659e06bce37bec02d3a0c990041c2be91','runner revision')
ck(m['runner_source']['tracked_clean']and m['runner_source']['source_files_tracked'],'clean tracked runner')
ck(cfg['source_sha256']==pin['source_sha256']and len(cfg['source_sha256'])==13,'runner source map')
ck(sha(F/'PROGRAM_REVIEW_CONFIRMATION_EXECUTION.json')==pin['configuration_sha256'],'runner config pin')
for n,v in cfg['source_sha256'].items():ck(sha(F/n)==v,('runner pin',n))
ck(m['producer_revision']==cfg['producer_revision']==pin['producer_revision']=='41bd752371847b5ee6d22c59d9f22662c09797fe','producer revision')
ck(m['producer_selection_sha256']==cfg['producer_selection_sha256']==pin['producer_selection_sha256']=='a01a1f13b146c04c4435221fea38ff3c0c5e2b53d198ac0d11bd7b79481db0bf','producer selection')
ck(m['image']==cfg['image']=='python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd','qualified CPU image')
ck(sha(O/'corpus.json')==sha(F/'datasets/program-confirmation-v1/tasks.json')==m['corpus_sha256']==cfg['corpus_sha256']=='b1267cbd9f371383402ff116a9139c22515c046d924d6b6f6b6df2cee8fda85e','exact known96 corpus')
ck(m['programs']==4 and m['graphs']==96 and m['planned_jobs']==launch['planned_jobs']==384 and m['model_calls']==launch['model_calls']==0,'fixed384 zero-model allocation')
ck(sha(ap)==launch['admission_sha256']and ad==m['gate']['admission'],'admission binding')
ck(ad['verified']and ad['workloads_drained']and ad['optional_time_admitted']and not ad['model_switch_started']and not ad['feature_switch_started'],'exclusive admission')
ck(sha(P/'metadata.json')==ad['producer_metadata_sha256'],'producer metadata binding')
producer_audit_path=R/'results/program-review-v1.1-audit/FINAL_AUDIT.json';pa=read(producer_audit_path)
ck(sha(producer_audit_path)==ad['producer_independent_audit_sha256']=='397ec67bba4d8b41875de4a46a32403e3c207ca6ac4e6431e5e59bbfc48cd1c9'and pa['verified']and pa['complete'],'independent producer audit')
for n,v in pa['input_sha256'].items():ck(sha(R/n)==v,('producer inputs changed',n))
for n,v in m['source_before'].items():ck(sha(Path(n))==v,('bound input changed',n))
ck(read(P/'metadata.json')['gate']==m['gate']['original_gate'],'original stage gate preserved')
age=(datetime.datetime.fromisoformat(m['started_utc'])-datetime.datetime.fromisoformat(ad['checked_utc'])).total_seconds();ck(0<=age<=900,'fresh admission age')
ck(len(ad['nodes'])==4 and {n['seed']for n in ad['nodes']}==set(range(1,5)),'four admitted nodes')
rt=read(F/'runtime.json')
for n in ad['nodes']:ck(n['host']==f"Spark_{n['seed']:02d}"and n['endpoint']==f"http://127.0.0.1:{18080+n['seed']}/v1"and n['healthy']and n['idle']and n['owner']=='swarm-lab-20261115'and n['runtime_sha256']==sha(F/'runtime.json')and n['model_revision']==rt['model_revision']and n['draft_revision']==rt['dspark']['draft_revision']and n['image']=='vllm/vllm-openai@'+rt['arm64_manifest_digest'],'node admission')
ck(len(m['gate']['observed'])==4 and all(n['idle']and n['healthy']for n in m['gate']['observed']),'observed idle/health')
corpus=read(O/'corpus.json');tasks={t['id']:t for t in corpus['tasks']};ck(len(tasks)==len(corpus['tasks'])==len({digest(t)for t in tasks.values()})==96 and all(t['split']=='evaluation'for t in tasks.values()),'unique96 evaluation graphs')
for t in tasks.values():ck(len({tuple(e)for e in t['edges']})==len(t['edges'])and all(len(e)==2 and all(type(v)is int for v in e)and 0<=e[0]<e[1]<t['vertex_count']for e in t['edges']),'graph domain/simple edges')
bindings=read(O/'bindings.json');ck(len(bindings)==4 and {b['seed']for b in bindings}==set(range(1,5)),'all4 bindings')
bs={};same=[];original=R/'runs/program-search-v1'
for b in bindings:
 seed=b['seed'];bs[seed]=b;ck(b['arm']=='review_elites4'and b['host']==f'Spark_{seed:02d}','binding host/arm')
 origin=P/f'seed-{seed}-review_elites4/selected.py';copy=O/f'selected-s{seed}.py';choice=read(origin.parent/'selection.json')
 ck(b['source_path']==str(copy)and b['producer_source_path']==str(origin)and sha(copy)==sha(origin)==b['code_sha256']==choice['code_sha256'],'execution/origin/selection binding')
 ck(str(copy)in m['source_before']and str(origin)in m['source_before'],'both code paths bound')
 ck(choice['evaluation_seen']is False and choice['model_calls_at_selection']==16 and choice['selected_utc']<m['started_utc'],'source frozen before confirmation')
 for prior in original.glob('seed-*/selected.py'):
  if sha(prior)==b['code_sha256']:same.append(dict(review_seed=seed,prior_selected_path=str(prior.relative_to(R)),code_sha256=b['code_sha256'],scope='Postselection identical-source observation; not independent new solver-quality evidence and never used to skip any grade'))
raw=(O/'grades.jsonl').read_text();lines=raw.splitlines();lines=lines if raw.endswith('\n')else lines[:-1];rows=[json.loads(x)for x in lines];ck(len(rows)==len({r['job_id']for r in rows}),'unique jobs')
counts=Counter();flat=[];perseed={s:[]for s in bs}
for row in rows:
 b=bs[row['seed']];t=tasks[row['task_id']];ck(row['host']==b['host']and row['arm']=='review_elites4'and row['code_sha256']==b['code_sha256']and row['graph_sha256']==digest(t),'job binding')
 identity={k:row[k]for k in ['seed','arm','host','task_id','graph_sha256','code_sha256']};ck(h(json.dumps(identity,sort_keys=True))==row['job_id'],'job ID')
 ck(row['infrastructure']is False and type(row['solved'])is bool,'infrastructure/unknown grade')
 q=row['report'];v=grade(t,q,Path(b['source_path']).read_text());ck(row['solved']==q['solved'],'row outcome');perseed[row['seed']].append(row['task_id'])
 counts['proofs_replayed']+=v is not None;counts['cleanup_verified']+=q['cleanup_ok'];counts['status_'+q['status']]+=1;counts['solved']+=row['solved']
 flat.append(dict(seed=row['seed'],task_id=t['id'],solved=row['solved'],status=q['status'],failure_kind=q.get('failure_kind'),valid_schema=v['valid_schema']if v else None,conflicts=v['conflicts']if v else None,controller_wall_seconds=row['controller_wall_seconds'],remote_cpu_seconds=q.get('remote_cpu_seconds')))
for seed,order in perseed.items():ck(order==list(tasks)[:len(order)],'per-host96 taskorder/no skip/retry')
for n,v in m['source_before'].items():ck(sha(Path(n))==v,('end bound input changed',n))
if not m.get('complete'):
 print(json.dumps(dict(status='running',checked_jobs=len(rows),infrastructure_faults=0,partial_scores_published=False)));sys.exit(0)
ck(m['verified']and not m['incomplete']and not m['faults']and not m['source_changed_during_run']and m['source_before']==m['source_after']and m['runner_source_after']==m['runner_source'],'final integrity')
ck(m['completed_jobs']==len(rows)==384 and m['missing_jobs']==0 and all(len(x)==96 for x in perseed.values()),'complete384 coverage')
ck(len(m['final_idle_health'])==4 and all(n['idle']and n['healthy']for n in m['final_idle_health']),'final drain/health')
summary=read(O/'summary.json');ck(summary['status']==m and summary['solved']==counts['solved']and summary['unknown']==0,'summary reconciliation')
inputs={str(p.relative_to(R)):sha(p)for p in O.rglob('*')if p.is_file()}
for p in [ap,R/'.runtime/PROGRAM_REVIEW_CONFIRMATION_LAUNCH_V1_1.json',R/'.runtime/PROGRAM_REVIEW_CONFIRMATION_FROZEN_V1_1.json',producer_audit_path]+[F/n for n in cfg['source_sha256']]+[F/'PROGRAM_REVIEW_CONFIRMATION_EXECUTION.json']:inputs[str(p.relative_to(R))]=sha(p)
results=[dict(seed=s,solved=sum(r['solved']for r in rows if r['seed']==s),graphs=96)for s in sorted(bs)]
report=dict(verified=True,complete=True,completed_jobs=384,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),classification='Late exploratory all4 review-program replay on operator-known96 graphs; not a fresh untouched confirmation',model_calls=0,source_revision=pin['revision'],producer_revision=m['producer_revision'],corpus_sha256=m['corpus_sha256'],counts=dict(counts),results=results,same_source_observations=same,wall_seconds=m['wall_seconds'],wall_scope=m['wall_scope'],remote_cpu_seconds=None,input_sha256=inputs,bound_input_sha256=m['source_before'],auditor_sha256=sha(Path(__file__)),limits=['All384 evaluations retained, no cache or source-hash duplicate skipping. All4 programs admitted before outcomes.','Same-source pairs are a postselection observation, not independent new quality evidence.','Candidate Python never executed locally; exact original host-side graph proof replayed from retained outputs.','Negative timeout/OOM/input-purity results remain quality failures even when a returned assignment itself solves the graph.','Per-host order/count/source enforce sealed execution design; no independent process tracing or per-job remote CPU instrumentation.','Graphs/programs/seeds are crossed and dependent;384 grades are not384 independent solver samples.'])
for name,value in [('AUDIT.json',report),('proof-replay.json',flat)]:
 with(OUT/name).open('x')as f:json.dump(value,f,indent=2);f.write('\n')
with(OUT/'ARTIFACT_MANIFEST.json').open('x')as f:json.dump({str(p.relative_to(OUT)):sha(p)for p in OUT.rglob('*')if p.is_file()and p.name!='ARTIFACT_MANIFEST.json'},f,indent=2);f.write('\n')
print(json.dumps({k:v for k,v in report.items()if k not in ['input_sha256','bound_input_sha256','limits','same_source_observations']}));print('AUDIT_SHA256',sha(OUT/'AUDIT.json'))
