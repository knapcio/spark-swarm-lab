"""Independent local provenance/constraint replay; never executes candidate code."""
import collections,csv,datetime,hashlib,itertools,json,pathlib,shutil,sys
R=pathlib.Path('/Users/zbizbi/Projects/sparks/apps/swarm-lab');F=R/'.runtime/program-confirmation-source';O=R/'runs/program-confirmation-v1'
read=lambda p:json.loads(pathlib.Path(p).read_text())
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def check(value,message):
 if not value:raise AssertionError(message)
def digest(t):return hashlib.sha256(json.dumps({k:t[k]for k in ['vertex_count','color_count','edges']},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def proof(t,p):
 valid=isinstance(p,dict)and set(p)=={'assignment'}and isinstance(p['assignment'],list)and len(p['assignment'])==t['vertex_count']and all(type(v)is int and 0<=v<t['color_count']for v in p['assignment'])
 bad=[i for i,(u,v)in enumerate(t['edges'])if p['assignment'][u]==p['assignment'][v]]if valid else []
 return dict(solved=valid and not bad,valid_schema=valid,conflicts=len(bad)if valid else None,violating_edges=bad,fitness=[1,-len(bad)]if valid else[0,0])
def check_report(t,q):
 check(q.get('cleanup_ok')is True and q.get('provenance')=='candidate'and q.get('grading_authority')=='outer_parent'and q.get('oracle_sent_to_child')is False,'authority/cleanup')
 check(q.get('graph_sha256')==digest(t)and type(q.get('solved'))is bool,'report graph/outcome')
 check(q['status']in('passed','failed','error','timeout')and not str(q.get('failure_kind','')).endswith('_infrastructure'),'candidate outcome classification')
 if q.get('container_state')is not None:check(q['container_state'].get('Running')is False,'container still running')
 v=None
 if q.get('proof')is not None:
  check('candidate_output'in q,'missing output');v=proof(t,q['candidate_output'])
  for key,value in v.items():check(q['proof'][key]==value and (type(q['proof'][key])is bool if key in('solved','valid_schema')else True),('proof mismatch',t['id'],key))
  check((q['proof']['error']is None)==v['valid_schema'],'schema error state')
  check(q['graph_verifier_calls']==1 and q['graph_edge_checks']==(len(t['edges'])if v['valid_schema']else 0),'graph work counters')
 else:check(q.get('graph_verifier_calls',0)==0,'unexpected verifier count')
 check(q['status']not in('passed','failed')or v is not None,'assignment status without proof')
 check((q['status']=='passed')==q['solved'],'pass/solved consistency')
 if q['solved']:check(v is not None and v['solved']and q.get('input_unchanged')is True and q.get('failure_kind')is None,'unproven success')
 if q['status']=='failed':check(v is not None and (not v['solved']or q.get('input_unchanged')is not True),'unexplained negative assignment')
 check(q.get('remote_cpu_seconds')is None,'remote CPU improperly known')
 return v
plan=read(F/'PROGRAM_CONFIRMATION_SELECTION.json');cfg=read(F/'PROGRAM_CONFIRMATION_EXECUTION.json');pin=read(R/'.runtime/PROGRAM_CONFIRMATION_EXECUTION_FROZEN.json');launch=read(R/'.runtime/PROGRAM_CONFIRMATION_LAUNCH.json');m=read(O/'metadata.json')
check(pin['revision']==launch['source_revision']==m['runner_source']['revision']=='66de0f195101f31d394f2d869c01538e79a2f7d8','execution revision')
check(m['runner_source']['tracked_clean']and m['runner_source']['source_files_tracked'],'unclean runner')
for name,h in pin['source_sha256'].items():check(sha(F/name)==h,('execution pin',name))
check(sha(F/'PROGRAM_CONFIRMATION_EXECUTION.json')==pin['execution_sha256']==m['configuration_sha256'],'config pin')
check(sha(F/'PROGRAM_CONFIRMATION_SELECTION.json')==pin['upstream_plan_sha256']==m['upstream_plan_sha256']=='4b25b675ace76ecfd15863241cd28178d9b3f5e4ad0171f5cbc945451eaf9061','prospective plan')
check(sha(O/'corpus.json')==sha(F/plan['dataset'])==m['corpus_sha256']==m['dataset_sha256']==plan['dataset_sha256']=='b1267cbd9f371383402ff116a9139c22515c046d924d6b6f6b6df2cee8fda85e','corpus pin')
check(m['image']==cfg['image']==plan['execution']['image']=='python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd','CPU image')
check(cfg['source_sha256']==pin['source_sha256'],'exact runner source map')
check(pin['source_sha256']['independent_code_grader.py']=='c4324123bb75a8712150adb3e06e1da4e1e44a7d91516597d9a35caa372c2726'and pin['source_sha256']['csp_program_grader.py']=='7fa45db50bfbef04c868b35ddb3aab67fceab4818ca5820bba2427f14ff6873a','qualified exact grader pins')
for p,h in m['source_before'].items():check(sha(p)==h,('bound input changed',p))
check(sha(R/'.runtime/PROGRAM_CONFIRMATION_EXECUTION_FROZEN.json')==launch['source_receipt_sha256'],'launch source receipt')
admission_path=R/'.runtime/program-confirmation-admission-v1/owner-admission.json';ad=read(admission_path)
check(sha(admission_path)==launch['admission_sha256']==m['gate']['owner_receipt_sha256'],'admission hash')
check(ad['verified']and ad['workloads_drained']and ad['optional_time_admitted']and ad['model_switch_started']is False,'owner admission')
age=(datetime.datetime.fromisoformat(m['started_utc'])-datetime.datetime.fromisoformat(ad['checked_utc'])).total_seconds();check(-60<=age<=900,'stale admission')
check(len(ad['nodes'])==4 and {n['seed']for n in ad['nodes']}=={1,2,3,4},'four owners')
for n in ad['nodes']:check(n['host']==f"Spark_{n['seed']:02d}"and n['endpoint']==f"http://127.0.0.1:{18080+n['seed']}/v1"and n['idle']and n['healthy']and n['owner']=='swarm-lab-20261115','owner fields')
runtime=read(F/'runtime.json')
for n in ad['nodes']:check(n['runtime_sha256']==sha(F/'runtime.json')and n['image']=='vllm/vllm-openai@'+runtime['arm64_manifest_digest']and n['model_revision']==runtime['model_revision']and n['draft_revision']==runtime['dspark']['draft_revision'],'admitted runtime identity')
check(len(m['gate']['observed'])==4 and all(n['idle']and n['healthy']for n in m['gate']['observed']),'fresh idle boundary')
for p,h in m['gate']['program_inputs_sha256'].items():check(sha(p)==h,('original program input hash',p))
corpus=read(O/'corpus.json');tasks={t['id']:t for t in corpus['tasks']};original=read(F/'datasets/csp-v1/tasks.json')['tasks'];original_hashes={digest(t)for t in original};cells=collections.Counter()
check(len(tasks)==len(corpus['tasks'])==96 and len({digest(t)for t in tasks.values()})==96,'unique corpus')
for t in tasks.values():
 check(set(t)=={'id','split','vertex_count','color_count','edges'}and t['split']=='evaluation'and digest(t)not in original_hashes,'fresh public graph')
 n,k,d=corpus['generator']['evaluation_cells'][t['id']];check((n,k)==(t['vertex_count'],t['color_count']),'factorial label');cells[n,k,d]+=1
 sizes=[n//k+(i<n%k)for i in range(k)];eligible=(n*n-sum(x*x for x in sizes))//2;check(len(t['edges'])==(eligible*d+50)//100,'density count')
 check(len({tuple(e)for e in t['edges']})==len(t['edges'])and all(len(e)==2 and all(type(v)is int for v in e)and 0<=e[0]<e[1]<n for e in t['edges']),'edge domains/simple graph')
 seen={0}
 while True:
  nxt=seen|{v for u,v in t['edges']if u in seen}|{u for u,v in t['edges']if v in seen}
  if nxt==seen:break
  seen=nxt
 check(len(seen)==n,'connected graph')
check(set(cells)==set(itertools.product([24,40,64],[3,4],[20,40]))and set(cells.values())=={8},'balanced factorial96')
bindings=read(O/'bindings.json');check(sha(O/'bindings.json')==m['bindings_sha256'],'binding hash');check(len(bindings)==8 and {(b['seed'],b['arm'])for b in bindings}==set(itertools.product(range(1,5),['sequential16','independent4'])),'all8 programs')
master=R/'runs/program-search-v1';pm=read(master/'metadata.json');check(pm['complete']and pm['verified']and pm['completed_programs']==8,'original program master')
check(plan['prepared_utc']<pm['started_utc']<pm['completed_utc']<m['started_utc'],'prospective chronological separation')
selection_events=[];bybinding={};original_counts=collections.Counter()
for b in bindings:
 key=b['seed'],b['arm'];bybinding[key]=b;check(b['host']==f"Spark_{b['seed']:02d}",'bound host');cp=O/f"selected-s{b['seed']}-{b['arm']}.py";check(sha(cp)==sha(b['source_path'])==b['code_sha256'],'selected source copy')
 s=read(b['selection_path']);check(s['code_sha256']==b['code_sha256']and s['evaluation_seen']is False and s['model_calls_at_selection']==16,'original selection binding')
 ep=pathlib.Path(b['selection_path']).parent;events=[json.loads(x)for x in(ep/'events.jsonl').read_text().splitlines()];scored=[e for e in events if e['type']=='development_candidate_scored'];selected=[e for e in events if e['type']=='program_selected'];check(len(scored)==16 and len(selected)==1,'selection coverage')
 best=min(scored,key=lambda e:(-e['solved'],e['penalty'],e['candidate_index']));chosen=selected[0];check(best['candidate_index']==s['candidate_index']==chosen['candidate_index']and chosen['code_sha256']==b['code_sha256'],'development fitness selection')
 check(max(e['event_id']for e in scored)<chosen['event_id'],'selection before training finished')
 evals=[e for e in events if e['type']=='program_grade_start'and e['phase']=='evaluation'];check(len(evals)==12 and all(e['event_id']>chosen['event_id']and e['code_sha256']==b['code_sha256']for e in evals),'original holdout after freeze')
 check({e['task_id']for e in evals}=={t['id']for t in original if t['split']=='evaluation'},'original12 coverage');selection_events.append(s['selected_utc'])
 check(sum(e['type']=='request_start'for e in events)==sum(e['type']=='request_end'for e in events)==16,'original16 calls')
 for t in original:
  if t['split']!='evaluation':continue
  old=read(ep/f"evaluation-{t['id']}.json");check(old['selected_sha256']==b['code_sha256']and old['graph_sha256']==digest(t),'original grade binding');check_report(t,old['report']);original_counts[b['arm']+'/cases']+=1;original_counts[b['arm']+'/solved']+=old['report']['solved']
check(max(selection_events)<m['started_utc'],'allselected before confirmation')
raw=(O/'grades.jsonl').read_text();lines=raw.splitlines();rows=[json.loads(line)for line in lines if line.strip()];check(len(rows)==len({r['job_id']for r in rows}),'duplicate jobs')
counts=collections.Counter();flat=[]
for r in rows:
 b=bybinding[r['seed'],r['arm']];t=tasks[r['task_id']];check(r['host']==b['host']and r['code_sha256']==b['code_sha256']and r['graph_sha256']==digest(t),'job binding')
 fields={k:r[k]for k in ['seed','arm','host','task_id','graph_sha256','code_sha256']};check(hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()==r['job_id'],'job hash')
 check(r['infrastructure']is False and type(r['solved'])is bool,'infrastructure/unknown job');q=r['report'];v=check_report(t,q);check(r['solved']==q['solved'],'row/report outcome')
 code=pathlib.Path(b['source_path']).read_text();payload=json.dumps(dict(code=code,function_name='solve',calls=[dict(args=[t['vertex_count'],t['color_count'],t['edges']],kwargs={})],timeout=10),allow_nan=False)
 check(hashlib.sha256(payload.encode()).hexdigest()==q['child_payload_sha256'],'bound child payload')
 counts[r['arm']+'/solved']+=r['solved'];counts['proofs_replayed']+=v is not None;counts['negative_status/'+q['status']]+=not r['solved'];counts['cleanup_verified']+=q['cleanup_ok']
 flat.append(dict(seed=r['seed'],arm=r['arm'],task_id=r['task_id'],vertex_count=t['vertex_count'],color_count=t['color_count'],edges=len(t['edges']),solved=r['solved'],status=q['status'],failure_kind=q.get('failure_kind'),valid_schema=v['valid_schema']if v is not None else None,conflicts=v['conflicts']if v is not None else None,cleanup_ok=q['cleanup_ok'],wall_seconds=q['wall_seconds'],remote_cpu_seconds=q['remote_cpu_seconds']))
for p,h in m['source_before'].items():check(sha(p)==h,('end bound input changed',p))
complete=m.get('complete')is True
if not complete:
 print(json.dumps(dict(admission_and_bindings_pass=True,observed_jobs_checked=len(rows),published_outcome_summary=False,status='running')));sys.exit(0)
check(m['verified']and not m['incomplete']and not m['faults']and not m['source_changed_during_run']and m['source_after']==m['source_before']and m['runner_source_after']==m['runner_source'],'final source/status')
check(len(rows)==m['completed_jobs']==768 and {(r['seed'],r['arm'],r['task_id'])for r in rows}==set(itertools.product(range(1,5),['sequential16','independent4'],tasks)),'complete768 grid')
check(all(n['idle']and n['healthy']for n in m['final_idle_health'])and len(m['final_idle_health'])==4,'final idle health')
sumry=read(O/'summary.json')
for arm in ['sequential16','independent4']:
 a=sumry['arms'][arm];check(a['recorded_jobs']==384 and a['unknown_outcomes']==0 and a['known_solved']==counts[arm+'/solved']and a['known_unsolved']==384-a['known_solved'],'summary totals')
report=dict(verified=True,complete=True,completed_jobs=768,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),execution_revision=pin['revision'],prospective_plan_sha256=m['upstream_plan_sha256'],dataset_sha256=m['dataset_sha256'],graphs=96,programs=8,grades=768,model_calls=0,counts=dict(counts),original12_separate_validation=dict(original_counts),factorial_cells=12,graphs_per_cell=8,selected_sources={f"s{b['seed']}-{b['arm']}":b['code_sha256']for b in bindings},checks=['frozen source and exact qualified grader/image pins','prospective corpus before original program calls','all8 original selected sources and development-only earliest-best selection','all96 original holdout grades occurred after source selection','fresh96 simple connected graphs,12factorialcells, no labeled duplicates','all768 child payload hashes bind originalgraph+selectedsource+10second timeout','independent full vertex/domain/edge proof replay','candidate negatives preserved, no source replacement/retries','all cleanup receipts and finalfour idle health','source_before/source_after identity'],limitations=['Only original outer graph assignments independently verified; no candidate source was executed by auditor.','Returned child observations are unauthenticated; positive acceptance depends on exact original graph proof and unchanged-input flag. Negative exception/timeout classifications rely on retained qualified transport reports.','No per-grade start timestamp or container identifier is retained; immutable runner order establishes binding-before-first-grade and one serial worker perhost, not independent process tracing.','768 grades share96 graphs and8 selected programs from4paired training episodes; not768 independent tasks. No universal correctness or100% guarantee.','Original12 evaluation results remain separate. Remote CPU time is unknown; local parent CPU intervals overlap.'],input_sha256={str(p.relative_to(R)):sha(p)for p in [O/'metadata.json',O/'grades.jsonl',O/'summary.json',O/'bindings.json',O/'corpus.json',R/'.runtime/PROGRAM_CONFIRMATION_LAUNCH.json',R/'.runtime/PROGRAM_CONFIRMATION_EXECUTION_FROZEN.json',admission_path]},auditor_sha256=sha(__file__))
out=R/'results/program-confirmation-v1-audit';out.mkdir(exist_ok=False);(out/'AUDIT.json').write_text(json.dumps(report,indent=2)+'\n')
with(out/'proof-replay.csv').open('w')as f:w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
shutil.copyfile(__file__,out/'audit_program_confirmation.py');(out/'source-manifest.json').write_text(json.dumps(dict(sha256={'audit_program_confirmation.py':sha(__file__)},scope='Exact executed local observer, retaining original absolute paths; provenance snapshot, not portable command. No candidate execution or external calls.'),indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items()if k in ['verified','graphs','programs','grades','model_calls','counts']}))
