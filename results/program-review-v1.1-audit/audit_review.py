"""Independent offline proof/trace replay. Reads generated source as data; never executes it."""
from pathlib import Path
from collections import Counter
import ast,hashlib,json,datetime,sys
R=Path(__file__).resolve().parents[2];O=R/'runs/program-review-elites4-v1.1';F=R/'.runtime/program-review-elites4-v1.1-source';OUT=Path(__file__).resolve().parent
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

def feedback(t,q):
 v=q.get('proof')or{}
 return dict(task_id=t['id'],solved=q.get('solved')is True,conflicts=v.get('conflicts'),valid_assignment=v.get('valid_schema')is True,conflicting_edge_indices=v.get('violating_edges',[])[:16],status=q.get('status'),failure_kind=q.get('failure_kind'),error=str(q.get('error')or v.get('error')or'')[:300])
def penalty(t,q):
 if q.get('solved')is True:return 0
 v=q.get('proof')or{}
 return v['conflicts']if v.get('valid_schema')is True and type(v.get('conflicts'))is int and q.get('input_unchanged')is True and q.get('status')=='failed'else len(t['edges'])+1

pin=read(R/'.runtime/PROGRAM_REVIEW_FROZEN_SOURCE_V1_1.json');m=read(O/'metadata.json');launch=read(R/'.runtime/PROGRAM_REVIEW_LAUNCH_V1_1.json');ap=R/'.runtime/program-review-admission-v1.1/manual-admission.json';ad=read(ap)
ck(pin['revision']==launch['source_revision']==m['source']['revision']=='41bd752371847b5ee6d22c59d9f22662c09797fe','frozen revision')
ck(m['source']['sha256']==pin['source_sha256']and len(pin['source_sha256'])==14 and m['source']['tracked_clean']and m['source']['source_files_tracked'],'source map')
for n,d in pin['source_sha256'].items():ck(sha(F/n)==d,('source drift',n))
ck(sha(ap)==launch['admission_sha256']and sha(R/'.runtime/PROGRAM_REVIEW_FROZEN_SOURCE_V1_1.json')==ad['producer_source_receipt_sha256'],'admission pins')
ck(ad['verified']and ad['workloads_drained']and ad['optional_time_admitted']and not ad['model_switch_started']and not ad['feature_switch_started'],'exclusive admission')
ck(sha(R/'runs/csp-thinking_on16-evaluation-s1-late/metadata.json')==ad['late_metadata_sha256'],'late run unchanged')
age=(datetime.datetime.fromisoformat(m['started_utc'])-datetime.datetime.fromisoformat(ad['checked_utc'])).total_seconds();ck(0<=age<=900,'stale admission')
ck(len(ad['nodes'])==4 and {n['seed']for n in ad['nodes']}==set(range(1,5)),'four nodes')
rt=read(F/'runtime.json')
for n in ad['nodes']:ck(n['host']==f"Spark_{n['seed']:02d}"and n['endpoint']==f"http://127.0.0.1:{18080+n['seed']}/v1"and n['healthy']and n['idle']and n['owner']=='swarm-lab-20261115'and n['runtime_sha256']==sha(F/'runtime.json')and n['model_revision']==rt['model_revision']and n['draft_revision']==rt['dspark']['draft_revision']and n['image']=='vllm/vllm-openai@'+rt['arm64_manifest_digest'],'node admission')
ck(len(m['initial_idle_checks'])==4 and all(n['idle']and n['metrics']['running']==n['metrics']['waiting']==0 for n in m['initial_idle_checks']),'initial idle')
source_tasks=read(F/'datasets/csp-v1/tasks.json')['tasks'];dev=[{k:v for k,v in t.items()if k!='split'}for t in source_tasks if t['split']=='development'];evaluation=[{k:v for k,v in t.items()if k!='split'}for t in source_tasks if t['split']=='evaluation']
ck(read(O/'development-inputs.json')==dev and read(O/'evaluation-inputs.json')==evaluation,'4/12 inputs')
tasks={t['id']:t for t in dev+evaluation};counts=Counter();dags=[];completed=[];flat=[]
qual=read(O/'program-grader-qualification.json');ck(qual==m['grader_qualification']and qual['verified']and qual['model_calls']==0 and len(qual['rows'])==3,'qualification')
for q in qual['rows']:grade(q['task'],q['report'],q['code']);ck(q['report']['solved']==(q['name']=='valid'),'qualification false pass')
for seed in range(1,5):
 folder=O/f'seed-{seed}-review_elites4';p=folder/'events.jsonl'
 if not p.exists():continue
 text=p.read_text();lines=text.splitlines();lines=lines if text.endswith('\n')else lines[:-1];es=[json.loads(l)for l in lines];ck([e['event_id']for e in es]==list(range(1,len(es)+1)),'event sequence')
 candidates={};scored={};reviews={};starts={};ends={};grade_starts={};reports={};population=[];rounds={};selected=None;dag=[]
 rank=lambda ids:sorted(ids,key=lambda i:(-scored[i]['solved'],scored[i]['penalty'],i))
 for e in es:
  ty=e['type']
  if ty=='request_start':
   ck(e['request_id']not in starts and selected is None,'duplicate or post-selection call');starts[e['request_id']]=e;ck(len(starts)<=16,'call budget')
   if e['stage'].startswith('review-'):
    g=max(rounds);pop=rounds[g];pairs=dict(zip(pop[2:],pop[:2]));a=e['reviewer_candidate_index'];b=e['target_candidate_index'];ck(pairs.get(a)==b and e['agent_id']==a and e['review_id']==f'r{g}-c{a}-t{b}'and e['candidate_index']is None,'review dispatch')
   else:
    i=e['candidate_index'];ck(e['stage']==f'program-{i}','author stage')
    if i<4:ck(e['previous_candidate_index']is None and e['chain']==i,'initial parent')
    else:
     g=1+(i-4)//2;pop=rounds[g];target=pop[(i-4)%2];rid=f'r{g}-c{pop[2+(i-4)%2]}-t{target}'
     ck(e['previous_candidate_index']==e['repair_target_index']==target and e['review_id']==rid and e['chain']==candidates[target]['chain'],'repair ancestry')
     ck(all(f'r{g}-c{a}-t{b}'in reviews for a,b in zip(pop[2:],pop[:2])),'repair before joined reviews')
  elif ty=='request_end':
   ck(e['request_id']in starts and e['request_id']not in ends and not e.get('error'),'request failure/duplicate');ends[e['request_id']]=e
   ck(e['stage']==starts[e['request_id']]['stage']and e['usage']['completion_tokens']<=2048,'request identity/token cap')
  elif ty=='program_candidate':
   i=e['index'];ck(i not in candidates and 0<=i<10,'candidate index');match=[x for x in ends.values()if x['stage']==f'program-{i}'];ck(len(match)==1 and e['raw']==match[0]['response'],'candidate response binding')
   code=(e['raw']or'').strip()
   if code.startswith('```python\n')and code.endswith('```'):code=code[10:-3].strip()
   elif code.startswith('```\n')and code.endswith('```'):code=code[4:-3].strip()
   parse_error=None
   try:
    if len(code.encode())>65536:raise ValueError('source exceeds64KiB')
    tree=ast.parse(code);functions=[x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name=='solve']
    if len(functions)!=1:raise ValueError('exactly one top-level solve function required')
    args=functions[0].args
    if len(args.posonlyargs+args.args)!=3 or args.vararg or args.kwarg or args.kwonlyargs:raise ValueError('solve must accept exactly three positional parameters')
   except (SyntaxError,ValueError,RecursionError,MemoryError)as ex:parse_error=type(ex).__name__+': '+str(ex)[:300]
   ck(e['parse_error']==parse_error,'independent AST-only parse')
   ck(code==e['code']and h(code)==e['code_sha256']==sha(folder/f'candidate-{i:02d}.py'),'candidate bytes')
   ck((folder/f'candidate-{i:02d}.raw.txt').read_text()==(e['raw']or''),'raw bytes')
   request=starts[match[0]['request_id']];ck(e['parent_index']==request['previous_candidate_index']and e['chain']==request['chain'],'candidate lineage')
   candidates[i]=e;dag.append(dict(type='program',index=i,chain=e['chain'],parent=e['parent_index'],review_id=e.get('review_id'),source_sha256=e['code_sha256'],request_id=match[0]['request_id'],event_id=e['event_id']))
  elif ty=='program_grade_start':
   key=e['phase'],e['candidate_index'],e['task_id'];ck(key not in grade_starts,'duplicate grade start');grade_starts[key]=e
   t=tasks[e['task_id']];ck(e['host']==f'Spark_{seed:02d}'and e['timeout_seconds']==10 and e['code_sha256']==candidates[e['candidate_index']]['code_sha256']and e['graph_sha256']==digest(t)and e['input_sha256']==h(canon([t['vertex_count'],t['color_count'],t['edges']])),'grade start binding')
   ck((e['phase']=='development'and t in dev and selected is None)or(e['phase']=='evaluation'and t in evaluation and selected is not None and e['candidate_index']==selected['candidate_index']),'phase leakage')
  elif ty=='program_grade_end':
   key=e['phase'],e['candidate_index'],e['task_id'];ck(key in grade_starts and key not in reports,'grade end identity');t=tasks[e['task_id']];ck(all(e[k]==v for k,v in grade_starts[key].items()if k not in ['type','event_id','timestamp']),'grade start/end identity');q=e['report'];v=grade(t,q,candidates[e['candidate_index']]['code']);reports[key]=q
   counts['grades']+=1;counts['proofs']+=v is not None;counts['cleanup']+=q['cleanup_ok'];counts['negative_'+q['status']]+=not q['solved']
   flat.append(dict(seed=seed,phase=e['phase'],candidate_index=e['candidate_index'],task_id=e['task_id'],solved=q['solved'],status=q['status'],failure_kind=q.get('failure_kind'),valid_schema=v['valid_schema']if v else None,conflicts=v['conflicts']if v else None))
  elif ty=='program_grade_skipped':
   i=e['candidate_index'];ck(e['phase']=='development'and candidates[i]['parse_error']and e['reason']=='candidate_parse','skipped grade');reports['development',i,e['task_id']]=dict(status='error',solved=False,proof=None,failure_kind='candidate_parse',error=candidates[i]['parse_error'],grading_performed=False);counts['parse_skips']+=1
  elif ty=='development_candidate_scored':
   i=e['candidate_index'];rs=[reports['development',i,t['id']]for t in dev];ck(e['solved']==sum(q['solved']for q in rs)and e['penalty']==sum(penalty(t,q)for t,q in zip(dev,rs))and e['feedback']==[feedback(t,q)for t,q in zip(dev,rs)],'dev fitness/feedback');ck(i not in scored,'duplicate fitness');scored[i]=e
  elif ty=='review_population':
   g=e['generation'];population=list(range(4))if g==1 else population;ck(g not in rounds and e['candidate_indices']==rank(population),'ranked review population');rounds[g]=e['candidate_indices']
  elif ty=='program_review':
   g=e['generation'];pop=rounds[g];a=e['reviewer_candidate_index'];b=e['target_candidate_index'];rid=e['review_id'];ck(dict(zip(pop[2:],pop[:2])).get(a)==b and rid==f'r{g}-c{a}-t{b}'and e['reviewer_sha256']==candidates[a]['code_sha256']and e['target_sha256']==candidates[b]['code_sha256']and e['critique_verified']is False,'critic source/target')
   match=[x for x in ends.values()if x['stage']=='review-'+rid];ck(len(match)==1 and e['raw']==match[0]['response']and e['critique']==(e['raw']or'')[:8192]and e['truncated']==(len(e['raw']or'')>8192),'critique content binding');reviews[rid]=e
   dag.append(dict(type='critique',review_id=rid,generation=g,reviewer_candidate=a,target_candidate=b,reviewer_source_sha256=e['reviewer_sha256'],target_source_sha256=e['target_sha256'],critique_sha256=h(e['critique']),critique_verified=False,request_id=match[0]['request_id'],event_id=e['event_id']))
  elif ty=='review_population_selected':
   g=e['generation'];pool=rounds[g]+[4+(g-1)*2,5+(g-1)*2];want=rank(pool)[:4];ck(e['retained_indices']==want and set(e['not_retained_indices'])==set(pool)-set(want),'elitist selection');population=want
  elif ty=='program_selected':
   ck(selected is None and len(starts)==len(ends)==16 and len(scored)==10 and len(reviews)==6,'final fixed allocation');best=rank(list(scored))[0];ck(e['candidate_index']==best and e['code_sha256']==candidates[best]['code_sha256']==sha(folder/'selected.py')and e['evaluation_seen']is False and e['model_calls_at_selection']==16,'final earliest best/freeze');selected=e
 if (folder/'result.json').exists():
  result=read(folder/'result.json');ck(result['complete']and result['status']=='complete'and result['calls']==result['completed_calls']==16 and result['unfinished_calls']==0 and result['server_idle_after']and not result['malformed_lines'],'episode final')
  ck(len(candidates)==10 and len(reviews)==6 and len(scored)==10 and len(starts)==len(ends)==16 and selected is not None and set(rounds)=={1,2,3},'episode allocation')
  ck(result['evaluation_completed']==12 and {k[2]for k in reports if k[0]=='evaluation'}=={t['id']for t in evaluation},'evaluation12 coverage')
  choice=read(folder/'selection.json');ck(all(selected[k]==v for k,v in choice.items()),'selection receipt')
  for t in evaluation:
   old=read(folder/f"evaluation-{t['id']}.json");ck(old['report']==reports['evaluation',selected['candidate_index'],t['id']]and old['selected_sha256']==selected['code_sha256']and old['graph_sha256']==digest(t),'evaluation output binding')
  ck(result['evaluation_solved']==sum(q['solved']for k,q in reports.items()if k[0]=='evaluation'),'evaluation total')
  ck(result['grading_calls']==len([k for k in grade_starts])and result['training_candidates_scored']==10,'grade cost accounting')
  for token,counter in [('prompt_tokens','prompt'),('completion_tokens','completion')]:
   total=sum(e['usage'][token]for e in ends.values());ck(result[token]==total,'client token sum');before=result['server_metrics_before'];after=result['server_metrics_after'];ck(before['running']==before['waiting']==after['running']==after['waiting']==0,'counter idle');ck(result['server_cost_known']and result['server_'+token]==after[counter]-before[counter]and result['server_'+token]>=total,'server token delta')
  ck(result['completion_tokens']<=32768,'episode token cap');completed.append(result)
 dags.append(dict(seed=seed,nodes=dag));counts['observed_model_calls']+=len(starts);counts['observed_reviews']+=len(reviews);counts['observed_programs']+=len(candidates)
for n,d in pin['source_sha256'].items():ck(sha(F/n)==d,'final source drift')
if not m.get('complete'):
 print(json.dumps(dict(status='running',verified_completed_programs=len(completed),observed_model_calls=counts['observed_model_calls'],checked_grade_reports=counts['grades'],partial_scores_published=False)));sys.exit(0)
ck(m['verified']and m['source_after']==m['source']and not m['faults']and m['completed_programs']==m['recorded_episodes']==len(completed)==4,'final master')
ck(read(O/'results.json')==[read(O/f"seed-{x['seed']}-review_elites4/result.json")for x in read(O/'results.json')],'master results')
inputs={str(p.relative_to(R)):sha(p)for p in O.rglob('*')if p.is_file()}
for p in [R/'.runtime/PROGRAM_REVIEW_LAUNCH_V1_1.json',R/'.runtime/PROGRAM_REVIEW_FROZEN_SOURCE_V1_1.json',ap,R/'runs/csp-thinking_on16-evaluation-s1-late/metadata.json']+[F/n for n in pin['source_sha256']]:inputs[str(p.relative_to(R))]=sha(p)
report=dict(verified=True,complete=True,completed_programs=4,completed_original_evaluation_grades=48,classification='Late exploratory review-context variant; original12 evaluation and optional known96 followup remain separate',created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),counts=dict(counts),results=[dict(seed=x['seed'],solved=x['evaluation_solved'],graphs=12)for x in completed],costs={k:sum(x[k]for x in completed)for k in ['calls','prompt_tokens','completion_tokens','server_prompt_tokens','server_completion_tokens','grading_calls']},fleet_wall_seconds=m['wall_seconds'],source_revision=pin['revision'],input_sha256=inputs,auditor_sha256=sha(Path(__file__)),scope=['Independent exact full-edge/domain proof and purity/resource-negative replay; no candidate code execution.','Typed program/critique DAG reconstructed from captured responses, indices, source hashes, feedback, and sealed prompt-building code; HTTP prompts/bodies were not wire-captured.','All4 seeds used dev-only fitness and fixed16calls=10authors+6critics; no early success stopping or holdout repair.','Equal calls does not equal author count/realized tokens; review, elitism and richer contexts are bundled. Candidate contexts are stateless.','Optional known96 corpus is operator-known late exploratory, all4 programs eligible irrespective of original12 outcomes.'])
for name,value in [('AUDIT.json',report),('typed-lineage.json',dags),('proof-replay.json',flat)]:
 with(OUT/name).open('x')as f:json.dump(value,f,indent=2);f.write('\n')
print(json.dumps({k:v for k,v in report.items()if k not in ['input_sha256','scope']}))
