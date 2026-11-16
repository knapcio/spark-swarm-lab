import collections,csv,datetime,hashlib,itertools,json,pathlib,sys
from fractions import Fraction
ROOT=pathlib.Path('/Users/zbizbi/Projects/sparks/apps/swarm-lab')
read=lambda p:json.loads(pathlib.Path(p).read_text())
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
canon=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'))
def check(ok,msg):
 if not ok:raise AssertionError(msg)
def proof(t,p):
 valid=isinstance(p,dict) and set(p)=={'assignment'} and isinstance(p['assignment'],list) and len(p['assignment'])==t['vertex_count'] and all(type(v)is int and 0<=v<t['color_count'] for v in p['assignment'])
 bad=[i for i,(u,v) in enumerate(t['edges']) if p['assignment'][u]==p['assignment'][v]] if valid else []
 return dict(valid_schema=valid,solved=valid and not bad,conflicts=len(bad) if valid else None,violating_edges=bad,fitness=[1,-len(bad)] if valid else [0,0])
def assertproof(t,p,q):
 v=proof(t,p)
 for k,x in v.items():check(q[k]==x and (type(q[k])is bool if k in ('solved','valid_schema') else True),('proof',t['id'],k,x,q[k]))
 check((q['error']is None)==v['valid_schema'],'error state');return v
rank=lambda rs:sorted(rs,key=lambda r:(-r['verification']['fitness'][0],-r['verification']['fitness'][1],r['index']))
def ballot(t,e,nodes):
 b=e['ballot'];src=[nodes[i]for i in b['source_ids']];check(src==rank(src),'ballot ranking');check(src and b['anchor_id']==src[0]['id'],'anchor')
 anchor=src[0]['payload']['assignment'];k=t['color_count'];votes=[[Fraction(0)for _ in range(k)]for _ in anchor]
 for c,a in zip(src,b['alignments']):
  check(c['verification']['valid_schema'],'invalid ballot input');vals=c['payload']['assignment']
  options=[(sum(p[v]==anchor[i]for i,v in enumerate(vals)),p)for p in itertools.permutations(range(k))]
  score=max(x[0]for x in options);perm=min(p for s,p in options if s==score);aligned=[perm[v]for v in vals]
  w=Fraction(1,1+c['verification']['conflicts'])if b['weighted']else Fraction(1)
  check(a==dict(candidate_id=c['id'],agreement=score,permutation=list(perm),assignment=aligned,weight=[w.numerator,w.denominator]),'alignment')
  for i,v in enumerate(aligned):votes[i][v]+=w
 check(len(src)==len(b['alignments']),'alignment count')
 out=[]
 for i,vs in enumerate(votes):
  tied=[j for j,v in enumerate(vs)if v==max(vs)];out.append(anchor[i]if anchor[i]in tied else min(tied))
 check(b['votes']==[[[v.numerator,v.denominator]for v in vs]for vs in votes],'rational tally')
 check(e['payload']==b['payload']=={'assignment':out} and e['parents']==b['source_ids']and e['model_calls']==0 and e['origin']=='derived','derived payload')
 check(b['weighted']==(e['method']=='weighted_democracy4'),'weighted policy')

def audit_accounting(row,events,started,ended,emitted,limit):
 check(started==row['calls']<=limit and ended==row['completed_calls'] and started-ended==row['unfinished_calls'] and 0<=emitted<=ended<=started,'request accounting')
 if row['deadline']:
  check(row['controller_stop']is True and row['status']=='deadline' and row['returncode']in(0,-15,-9,143,137) and any(e['type']=='controller_stop' and e.get('deadline')is True and e.get('returncode')==row['returncode']for e in events),'controlled deadline receipt')
 else:check(started==ended==emitted,'complete request/candidate/review accounting')

pin=read(ROOT/'.runtime/CSP_FROZEN_SOURCE.json');frozen=ROOT/'.runtime/csp-search-source';expected={**pin['source_sha256'],'SEARCH_SELECTION.json':pin['selection_sha256']}
check(pin['revision']=='dadba8c29cd5b11bd71e49b4c8ba4e6ee5adaab5'and len(expected)==17,'pin identity')
for name,digest in expected.items():check(sha(frozen/name)==digest,('source pin',name))
data=ROOT/'datasets/csp-v1/tasks.json';check(sha(data)=='29d659bbc7b4b819ea7d572db073459eb30d6c19f7fda2114e7c174c375de960','dataset hash');tasks={t['id']:t for t in read(data)['tasks']}
check(len(tasks)==16,'task ids')
for t in tasks.values():
 check(all(type(v)is int and 0<=v<t['vertex_count']for ed in t['edges']for v in ed),'edge domains')
 check(all(len(ed)==2 and ed[0]<ed[1]for ed in t['edges'])and len({tuple(ed)for ed in t['edges']})==len(t['edges']),'simple graph')
# Independent schema negative controls, including bool-as-int rejection.
tiny={'id':'authored','vertex_count':2,'color_count':3,'edges':[[0,1]]}
for x in [None,{}, {'assignment':[False,1]}, {'assignment':[0]}, {'assignment':[0,3]}, {'assignment':[0,1],'extra':1}]:check(not proof(tiny,x)['valid_schema'],'negative fixture')
check(proof(tiny,{'assignment':[0,1]})['solved']and not proof(tiny,{'assignment':[0,0]})['solved'],'edge fixture')
# Separate late admission; no original receipt or runtime mutation.
late=ROOT/'runs/csp-thinking_on16-evaluation-s1-late';lm=read(late/'metadata.json')
admission_path=ROOT/'.runtime/late-reasoning-admission-v1/manual-admission.json';admission=read(admission_path);launch=read(ROOT/'.runtime/LATE_REASONING_LAUNCH.json');plan_path=ROOT/'.runtime/LATE_REASONING_EXTENSION_PLAN.json';plan=read(plan_path)
check(sha(admission_path)==launch['admission_sha256']and sha(plan_path)==admission['late_plan_sha256'],'late admission hashes')
check(admission['manually_admitted']and admission['no_owned_graders']and admission['source_revision']==launch['source_revision']==pin['revision'],'late admission/source')
check(plan['source_receipt_sha256']==sha(ROOT/'.runtime/CSP_FROZEN_SOURCE.json')and plan['source_or_budget_changes']is False and plan['automatic_launch']is False,'late prospective conditions')
check(sha(ROOT/'.runtime/post-throughput-overnight-v1/state.json')==admission['original_poststate_sha256']=='115a8621c97009e61971d1df406f0dc2a8a2ba1236efd1911ee2fec0b28f9cea','original closed poststate changed')
check(sha(ROOT/'.runtime/post-throughput-overnight-v1/ledger.json')==admission['original_skip_ledger_sha256']=='14ef21e58533682b7d86ad9e8a63d29d9004c6dd2c5688bfe4ddc78101ce6433','original closed ledger changed')
old=read(ROOT/'.runtime/post-throughput-overnight-v1/ledger.json');check(next(r for r in old if r['name']=='csp-thinking_on16-evaluation-s1')['status']=='skipped_time_cutoff','original ON skip')
check(sha(ROOT/'runs/program-confirmation-v1/metadata.json')==admission['fresh_confirmation_metadata_sha256'],'fresh confirmation receipt changed')
fc=read(ROOT/'runs/program-confirmation-v1/metadata.json');check(fc['verified']and fc['complete']and fc['completed_jobs']==768,'fresh confirmation incomplete')
check(plan['prepared_utc']<admission['checked_utc']<=launch['started_utc']<=lm['started_utc']and fc['completed_utc']<admission['checked_utc'],'late admission chronology')
check(len(admission['fleet'])==4 and len({n['host']for n in admission['fleet']})==4,'four admission nodes')
for n in admission['fleet']:
 c=n['container'];check(n['verified']and n['idle']and n['health']=='200'and n['metrics']['running']==n['metrics']['waiting']==0 and c['owner']=='swarm-lab-20261115'and c['image']=='vllm/vllm-openai@sha256:6ff5ff0ddf3658d2c2d677dac5ca2d4726ce0156b4371166d918181b210bd4bc'and c['running']and not c['oom']and c['restart_count']==0 and not c['state_error']and c['speculation']=='dspark','admission health/owner/image')
recipe=lm['recipe'];check(lm['profile']=='thinking_on16'and lm['split']=='evaluation'and lm['seed']==1 and lm['planned_cases']==96,'late profile/grid')
check(recipe['thinking']is True and recipe['max_calls']==16 and recipe['max_tokens']==4096 and recipe['max_completion_tokens']==65536 and recipe['deadline_seconds']==900 and recipe['request_timeout_seconds']==930,'late recipe')
for case in lm['cases']:
 cmd=case['command'];check('--thinking'in cmd and cmd[cmd.index('--max-tokens')+1]=='4096'and cmd[cmd.index('--max-calls')+1]=='16'and cmd[cmd.index('--timeout')+1]=='930','worker CLI')
for side in ['source_before']+(['source_after']if 'source_after'in lm else []):check(lm[side]['revision']==pin['revision']and lm[side]['sha256']==expected and lm[side]['tracked_clean'],'source identity')
check(not lm.get('faults')and not lm.get('source_changed_during_run'),'operational cohort fault')
if lm.get('verified')is not True:
 partial=read(late/'summary.json')if(late/'summary.json').exists()else []
 check(all(r.get('case_valid')is True and not r.get('controller_error')and r.get('server_idle_after')is True for r in partial),'operational completed-case fault')
 # Continue independent replay of completed rows; no outcome summary/artifacts until full cohort.

outputs=[];inputs={str(data.relative_to(ROOT)):sha(data)};completed=[];counts=collections.Counter()
for folder in [ROOT/'runs/csp-thinking_on16-evaluation-s1-late']:
 mp=folder/'metadata.json'
 if not mp.exists():continue
 m=read(mp)
 if m.get('verified')is True:check(not m['incomplete']and not m['faults']and not m['source_changed_during_run'],'cohort flags')
 else:check(not m.get('faults')and not m.get('source_changed_during_run'),'running cohort faults')
 for s in ['source_before']+(['source_after']if 'source_after'in m else []):
  check(m[s]['revision']==pin['revision']and m[s]['sha256']==expected and m[s]['tracked_clean']and m[s]['source_files_tracked'],'source receipt')
 check(m['dataset_sha256']==sha(data)and m['selection_sha256']==pin['selection_sha256'],'cohort data pin')
 rows=read(folder/'summary.json');ts={i for i,t in tasks.items()if t['split']==m['split']};arms=m['recipe']['arms'];limit=m['recipe']['max_calls']
 identity={(r['task_id'],r['arm'],r['seed'])for r in rows};planned=set(itertools.product(ts,arms,[m['seed']]))
 check(len(identity)==len(rows)and identity<=planned and m['planned_cases']==len(planned),'observed cohort grid')
 if m.get('verified')is True:check(len(rows)==m['completed_cases']==m['planned_cases']and identity==planned,'complete cohort count/grid')
 for r in rows:
  check(r['case_valid']and r['server_idle_after']and not r['source_changed_after_case']and not r['controller_error'],'case/drain')
  path=pathlib.Path(r['events']);events=[json.loads(s)for s in path.read_text().splitlines()];inputs[str(path.relative_to(ROOT))]=sha(path)
  check([e['event_id']for e in events]==list(range(1,len(events)+1)),'event ordering')
  start=events[0];t=tasks[r['task_id']];check(start['task']=={k:t[k]for k in ['id','vertex_count','color_count','edges']},'worker graph identity')
  check(start['max_calls']==limit and start['max_tokens']==m['recipe']['max_tokens'] and start['thinking']is True,'event budget/thinking')
  nodes={};reviews={};requests={};ends={};rewarded=set();pop=[];pending=[];ct=collections.Counter()
  for e in events:
   typ=e['type'];ct[typ]+=1
   if typ=='request_start':
    check(e['request_id']not in requests,'duplicate request');requests[e['request_id']]=e
    check(all(p in nodes for p in e.get('parent_ids',[]))and all(i in reviews for i in e.get('review_ids',[])),'request ancestry')
   elif typ=='request_end':check(e['request_id']in requests and e['request_id']not in ends,'request end');ends[e['request_id']]=e
   elif typ in ('candidate','derived_candidate'):
    check(e['id']not in nodes and all(i in nodes for i in e['parents'])and all(i in reviews for i in e.get('review_ids',[])),'candidate ancestry')
    v=assertproof(t,e['payload'],e['verification']);counts['verified_assignment_events']+=1;counts['positive_assignment_events']+=v['solved'];counts['malformed_assignment_events']+=not v['valid_schema']
    if typ=='candidate':
     completed=[q for q in ends.values()if q['stage']==e['id']];check(len(completed)==1,'candidate completed request');check(completed[0].get('parent_ids',[])==e['parents'],'request parents match');pending.append(e)
     if len(nodes)<4 and r['arm']!='sequential':pop.append(e)
    else:ballot(t,e,nodes);check(e['parents']==[c['id']for c in rank([c for c in pop if c['verification']['valid_schema']])],'ballot complete electorate')
    nodes[e['id']]=e
   elif typ=='reward':
    check(e['node_id']in nodes and e['node_id']not in rewarded,'reward precedence');v=nodes[e['node_id']]['verification'];check(e['solved']is v['solved']and e['reward']==int(v['solved']),'reward proof');rewarded.add(e['node_id'])
   elif typ=='review_delegation':
    ordered=rank(pop);check(e['elite_ids']==[x['id']for x in ordered[:2]]and e['reviewer_candidate_ids']==[x['id']for x in ordered[2:]],'review ranks')
   elif typ=='review':
    check(e['reviewer_candidate_id']in nodes and all(x in nodes for x in e['target_ids'])and e['verified_fact']is False,'review ancestry')
    q=e['payload'];valid=isinstance(q,dict)and set(q)=={'critique'}and isinstance(q['critique'],str)and 0<len(q['critique'])<=4000
    check(e['valid_schema']==valid and len([x for x in ends.values()if x['stage']==e['id']])==1,'review accounting');reviews[e['id']]=e
   elif typ=='selection':
    ids=e['survivor_ids']+e['pruned_ids'];check(len(ids)==len(set(ids))and all(i in nodes for i in ids),'selection membership')
    if r['arm']in ('review_elites4','evolution4','evolution_mutation4'):check(e['survivor_ids']==[x['id']for x in rank([nodes[i]for i in ids])[:4]],'elite selection')
    pop=[nodes[i]for i in e['survivor_ids']]
  check(set(nodes)==rewarded,'reward count')
  audit_accounting(r,events,len(requests),len(ends),ct['candidate']+ct['review'],limit)
  for token in ['prompt_tokens','completion_tokens']:
   completed_total=sum(q.get('usage',{}).get(token,0) for q in ends.values())
   check(r[token]==completed_total,('client token sum',token))
   field='server_'+token
   if r['server_cost_known']:
    before=r['server_metrics_before'];after=r['server_metrics_after'];counter='prompt' if token=='prompt_tokens' else 'completion'
    check(before['running']==before['waiting']==after['running']==after['waiting']==0,'counter idle')
    check(r[field]==after[counter]-before[counter] and r[field]>=completed_total,('server counter delta/floor',token))
   else:check(r[field]is None,('unknown cost not null',field))
  counts['controlled_deadline_cases']+=bool(r['deadline']);counts['unfinished_requests']+=r['unfinished_calls'];counts['known_server_cost_cases']+=bool(r['server_cost_known'])
  check(ct['candidate']==r['candidate_count']and ct['derived_candidate']==r['derived_count']and ct['review']==r['review_count'],'summary counts')
  check(r['solved']==any(c['verification']['solved']for c in nodes.values()),'summary proof')
  if not r['solved']:check(len(requests)==limit or r['deadline'],'premature stop')
  if not r['deadline']:
   if r['arm']=='review_elites4':check(ct['review']%2==0 and ct['candidate']==4+ct['review']and len(requests)%4==0,'review allocation')
   elif r['arm']!='sequential':check(len(requests)%4==0,'full batch charged')
  for e in events:
   if e['type']in ('search_end','run_end'):
    best=rank(list(nodes.values()))[0];check(e['best_candidate_id']==best['id']and e['best_payload']==best['payload']and e['best_verification']==best['verification'],'best selection')
  counts.update({k:ct[k]for k in ['candidate','derived_candidate','review','request_start']})
  outputs.append(dict(cohort=folder.name,task_id=r['task_id'],arm=r['arm'],seed=r['seed'],solved=r['solved'],calls=r['calls'],candidates=ct['candidate'],reviews=ct['review'],derived=ct['derived_candidate'],audit_pass=True))
 for p in [mp,folder/'summary.json']:inputs[str(p.relative_to(ROOT))]=sha(p)
 completed.append(folder.name)
# Recheck source and all observed files, catching concurrent mutations without trusting mutable state.
for name,digest in expected.items():check(sha(frozen/name)==digest,('final source',name))
for name,digest in inputs.items():
 if lm.get('verified')is not True and name.endswith(('/metadata.json','/summary.json')):continue
 check(sha(ROOT/name)==digest,('input drift',name))
if lm.get('verified')is not True:
 print(json.dumps(dict(status='running',admission_source_proof_policy_cost_checked=True,completed_cases_observed=len(outputs),partial_scores_published=False)));sys.exit(0)
report=dict(verified=True,complete=True,completed_cases=96,classification='Late exploratory execution of the unchanged preplanned thinking_on16 profile; original skip remains unchanged',admission_sha256=sha(admission_path),late_plan_sha256=sha(plan_path),original_poststate_sha256=admission['original_poststate_sha256'],original_skip_ledger_sha256=admission['original_skip_ledger_sha256'],created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),revision=pin['revision'],dataset_sha256=sha(data),completed_cohorts=sorted({x['cohort']for x in outputs}),cases=len(outputs),counts=dict(counts),checks=['17 frozen source pins before/after','exact public graph identity','full vertex/domain/edge proof replay','boolean rejection fixtures','reward and ancestry precedence','request/review/derived accounting, controlled deadlines retain unfinished costs','client token sums and idle counter deltas/floors','brute permutation alignment and exact rational consensus','elite rankings','balanced cohort matrix','drain receipts'],input_sha256=inputs,auditor_sha256=sha(__file__),scope='Only the late exploratory96-case thinking_on16 cohort; never pooled with original OFF cohorts or the original ON skip. Completed verified cohorts only. Independent local proof replay, no model advice or runtime modifications. No candidate program executed; no bootstrap or plots.')
out=ROOT/'results/csp-thinking-on16-late-audit-20261116';out.mkdir(exist_ok=True);cohort_names=sorted({x['cohort']for x in outputs});suffix=f"snapshot-{len(cohort_names):02d}-"+hashlib.sha256(canon(cohort_names).encode()).hexdigest()[:12]
for ext in ['json','csv']:check(not(out/(suffix+'.'+ext)).exists(),'no overwrite')
(out/(suffix+'.json')).write_text(json.dumps(report,indent=2)+'\n')
with(out/(suffix+'.csv')).open('w')as f:
 w=csv.DictWriter(f,fieldnames=list(outputs[0]));w.writeheader();w.writerows(outputs)
print(json.dumps({k:v for k,v in report.items()if k not in ['input_sha256','checks']}))
