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
outputs=[];inputs={str(data.relative_to(ROOT)):sha(data)};completed=[];counts=collections.Counter()
for folder in sorted((ROOT/'runs').glob('csp-*-s*')):
 mp=folder/'metadata.json'
 if not mp.exists():continue
 m=read(mp)
 if m.get('verified')is not True:continue
 check(not m['incomplete']and not m['faults']and not m['source_changed_during_run'],'cohort flags')
 for s in ['source_before','source_after']:
  check(m[s]['revision']==pin['revision']and m[s]['sha256']==expected and m[s]['tracked_clean']and m[s]['source_files_tracked'],'source receipt')
 check(m['dataset_sha256']==sha(data)and m['selection_sha256']==pin['selection_sha256'],'cohort data pin')
 rows=read(folder/'summary.json');ts={i for i,t in tasks.items()if t['split']==m['split']};arms=m['recipe']['arms'];limit=m['recipe']['max_calls']
 check(len(rows)==m['completed_cases']==m['planned_cases']==len(ts)*len(arms),'cohort count')
 check({(r['task_id'],r['arm'],r['seed'])for r in rows}==set(itertools.product(ts,arms,[m['seed']])),'cohort grid')
 for r in rows:
  check(r['case_valid']and r['server_idle_after']and not r['source_changed_after_case']and not r['controller_error'],'case/drain')
  path=pathlib.Path(r['events']);events=[json.loads(s)for s in path.read_text().splitlines()];inputs[str(path.relative_to(ROOT))]=sha(path)
  check([e['event_id']for e in events]==list(range(1,len(events)+1)),'event ordering')
  start=events[0];t=tasks[r['task_id']];check(start['task']=={k:t[k]for k in ['id','vertex_count','color_count','edges']},'worker graph identity')
  check(start['max_calls']==limit and start['max_tokens']==m['recipe']['max_tokens'],'event budget')
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
  check(len(requests)==len(ends)==r['calls']==ct['candidate']+ct['review']<=limit,'call accounting')
  check(ct['candidate']==r['candidate_count']and ct['derived_candidate']==r['derived_count']and ct['review']==r['review_count'],'summary counts')
  check(r['solved']==any(c['verification']['solved']for c in nodes.values()),'summary proof')
  if not r['solved']:check(len(requests)==limit or r['deadline'],'premature stop')
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
for name,digest in inputs.items():check(sha(ROOT/name)==digest,('input drift',name))
report=dict(verified=True,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),revision=pin['revision'],dataset_sha256=sha(data),completed_cohorts=sorted({x['cohort']for x in outputs}),cases=len(outputs),counts=dict(counts),checks=['17 frozen source pins before/after','exact public graph identity','full vertex/domain/edge proof replay','boolean rejection fixtures','reward and ancestry precedence','request/review/derived accounting','brute permutation alignment and exact rational consensus','elite rankings','balanced cohort matrix','drain receipts'],input_sha256=inputs,auditor_sha256=sha(__file__),scope='Completed verified cohorts only. Independent local proof replay, no model advice or runtime modifications. No candidate program executed; no bootstrap or plots.')
out=ROOT/'results/csp-independent-audit-20261116';out.mkdir(exist_ok=True);suffix='-'.join(sorted({x['cohort'].removeprefix('csp-')for x in outputs}))
for ext in ['json','csv']:check(not(out/(suffix+'.'+ext)).exists(),'no overwrite')
(out/(suffix+'.json')).write_text(json.dumps(report,indent=2)+'\n')
with(out/(suffix+'.csv')).open('w')as f:
 w=csv.DictWriter(f,fieldnames=list(outputs[0]));w.writeheader();w.writerows(outputs)
print(json.dumps({k:v for k,v in report.items()if k not in ['input_sha256','checks']}))
