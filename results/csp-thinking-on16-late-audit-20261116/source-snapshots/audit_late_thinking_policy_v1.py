import json,pathlib,collections,hashlib
R=pathlib.Path('runs');count=0;slots=collections.defaultdict(list);checks=collections.Counter()
rank=lambda rows:sorted(rows,key=lambda x:(-x['verification']['fitness'][0],-x['verification']['fitness'][1],x['index']))
for p in [R/'csp-thinking_on16-evaluation-s1-late/metadata.json']:
 m=json.loads(p.read_text())
 if not m.get('verified'):continue
 assert all(x['idle']and x['snapshot']['running']==x['snapshot']['waiting']==0 for x in m['initial_idle_checks'])
 for row in json.loads((p.parent/'summary.json').read_text()):
  es=[json.loads(x)for x in pathlib.Path(row['events']).read_text().splitlines()];cand={};pop=[];reviewround=None;reviews={};seen={};arm=row['arm'];slots[row['endpoint']].append((row['server_metrics_before']['timestamp_utc'],row['server_metrics_after']['timestamp_utc']))
  for e in es:
   if e['type']=='review_delegation':reviewround=e
   if e['type']=='review':
    assert e['reviewer_candidate_id']in reviewround['reviewer_candidate_ids']and e['target_ids']==reviewround['elite_ids'];reviews[e['id']]=e
   if e['type']=='candidate':
    idx=e['index'];parents=e['parents'];op=e['operation'];h=hashlib.sha256(json.dumps(e['payload'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();assert h==e['sha256']and e['duplicate_of']==seen.get(h);seen.setdefault(h,e['id'])
    if idx<(1 if arm=='sequential' else 4):assert not parents and op=='fresh'
    elif arm=='resample':assert not parents and op=='fresh'
    elif arm=='sequential':assert parents==[f'candidate-{idx-1}']and op=='repair'
    elif arm=='parallel_repair4':assert parents==[f'candidate-{idx-4}']and op=='repair'
    elif arm in ('evolution4','evolution_mutation4'):
     valid=[x for x in rank(pop)if x['verification']['valid_schema']];distinct=[]
     for x in valid:
      if x['sha256']not in {v['sha256']for v in distinct}:distinct.append(x)
     first=valid[:1];second=valid[1:2]or first;cross=distinct[:2]if len(distinct)>1 and arm=='evolution4' else first
     expected=[first,second,cross,[]][idx%4];assert parents==[x['id']for x in expected]
     expectedop='immigrant' if idx%4==3 else 'crossover' if len(expected)==2 else 'mutation' if expected else 'fresh';assert op==expectedop
    elif arm=='review_elites4':
     elite=reviewround['elite_ids'][(idx-4)%2];assert parents==[elite]and op=='review_guided_repair';rr=[x for x in reviews.values()if x['target_ids']==reviewround['elite_ids']and x['reviewer_candidate_id']in reviewround['reviewer_candidate_ids']][-2:];assert e['review_ids']==[x['id']for x in rr if x['valid_schema']]
    elif arm in ('democracy4','weighted_democracy4'):
     if parents:assert parents[0]==f'candidate-{idx-4}'and parents[1].startswith('derived-consensus-')and op=='consensus_guided_repair'
     else:assert op=='fresh'
    cand[e['id']]=e
    if idx<4:pop.append(e)
    checks['candidate_policy_and_dedup']+=1
   if e['type']=='selection':pop=[cand[i]for i in e['survivor_ids']]
  count+=1
for endpoint,intervals in slots.items():
 intervals.sort()
 for old,new in zip(intervals,intervals[1:]):assert old[1]<=new[0],('endpoint overlap',endpoint,old,new)
print('PASS',count,'completed cases,',dict(checks),'exact core/social parent policies and endpoint intervals no overlap')
