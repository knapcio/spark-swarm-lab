from pathlib import Path
from fractions import Fraction as F
from collections import Counter
from datetime import datetime
import hashlib,json,operator,sys
base=Path(sys.argv[1]).resolve();app=Path(sys.argv[2]).resolve()  # Original raw cohort and app source root required.
meta=json.loads((base/'metadata.json').read_text());summary=json.loads((base/'summary.json').read_text());selection=json.loads((app/'EVALUATION_SELECTION.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def check(ok,message):
 if not ok:raise AssertionError(message)
def state(row):return tuple(map(F,row))
def apply(s,a,fractions):
 check(isinstance(a,dict) and set(a)=={'i','j','op'},'invalid action schema')
 i,j,op=a['i'],a['j'],a['op'];check(type(i)is int and type(j)is int and i!=j and 0<=i<len(s) and 0<=j<len(s),'indices')
 check(op in '+-*/' and len(op)==1,'operator');v={'+':operator.add,'-':operator.sub,'*':operator.mul,'/':operator.truediv}[op](s[i],s[j])
 check(v>0 and (fractions or v.denominator==1),'positive integer constraint')
 return tuple(x for k,x in enumerate(s) if k not in(i,j))+(v,)
def parse(content):
 if not isinstance(content,str):return None
 text=content.strip()
 if text.startswith('```'):
  lines=text.splitlines()
  if lines[-1].strip()!='```':return None
  text='\n'.join(lines[1:-1])
 try:return json.loads(text)
 except (json.JSONDecodeError,ValueError):return None
check(meta['split']=='evaluation' and meta['seed']==2 and len(summary)==len(meta['cases'])==192,'cohort completeness')
check(meta['source_changed_during_run'] is False and meta['source_hashes']==meta['final_source_hashes'],'source unchanged')
check(not meta['incomplete'] and not meta['missing_cases'] and not meta['slot_failures'],'cohort incomplete')
check(meta['git_revision']=='736ee1e9ab4a1b1ef534be587fe967c307c485e6','source pin')
check(datetime.fromisoformat(selection['frozen_utc'])<datetime.fromisoformat(meta['started_utc']),'selection timing')
check(set(meta['arms'])==set(selection['arithmetic']['arms']),'frozen arms')
producer=Path(meta['cases'][0]['command'][1]).parent
for name,value in meta['source_hashes'].items():check(sha(producer/name)==value,'captured file hash '+name)
dataset_path=Path(meta['dataset']);check(sha(dataset_path)==meta['dataset_sha256']==selection['arithmetic']['dataset_sha256'],'dataset hash')
dataset=json.loads(dataset_path.read_text());check('witnesses' not in dataset,'public dataset only');tasks={t['id']:t for t in dataset['tasks'] if t['split']=='evaluation'}
check(len(tasks)==24 and all(set(t)=={'id','split','numbers','target'} for t in tasks.values()),'public schema')
planned={(c['task_id'],c['arm'],c['seed']):c for c in meta['cases']};check(len(planned)==192,'unique plan')
check(set(planned)=={(t,a,2) for t in tasks for a in meta['arms']},'balanced plan')
check({(r['task_id'],r['arm'],r['seed']) for r in summary}==set(planned),'planned summary grid')
all_requests=set();counts=Counter();results=[]
for row in summary:
 case=planned[row['task_id'],row['arm'],row['seed']];task=tasks[row['task_id']];events=[json.loads(l) for l in Path(row['events']).read_text().splitlines()]
 check(events and [e['event_id'] for e in events]==list(range(1,len(events)+1)),'event sequence '+row['events'])
 check(len({e['run_id'] for e in events})==1,'run ID');check(all(events[i]['timestamp']<=events[i+1]['timestamp'] for i in range(len(events)-1)),'event time')
 cfg=events[0]['config'];root=state(task['numbers']);target=F(task['target']);check(cfg['target']==target,'target config')
 check(cfg['puzzle']==','.join(map(str,task['numbers']))+':'+str(task['target']),'input puzzle')
 check(cfg['max_calls']==1280 and cfg['max_completion_tokens']==32768 and cfg['rounds']==5 and cfg['seed']==2 and cfg['timeout']==180 and cfg['model']=='nemotron-lightning','frozen limits')
 check(cfg.get('calibration_puzzles')is None and cfg.get('reputation')is None and not cfg['allow_fractions'],'no extra input')
 expected_arm={'direct_thinking_8k':('direct',1,True,8192),'ensemble2_thinking_8k':('ensemble',2,True,8192),'ensemble4_thinking_8k':('ensemble',4,True,8192),'independent32':('independent',32,False,192),'independent100':('independent',100,False,192),'democracy32':('democracy',32,False,192),'shared8':('shared',8,False,192),'cascade32':('cascade',32,False,192)}[row['arm']]
 check(tuple(cfg[k] for k in ('method','agents','thinking','max_tokens'))==expected_arm and cfg['accept_verified_solution']==row['arm'].startswith('democracy'),'frozen arm settings')
 check('--puzzle' in case['command'] and all('witness' not in str(x).lower() for x in case['command']),'no witness command')
 nodes={};legal={};starts={};ends={};proofs=[];plan_requests=[];local=Counter()
 for index,e in enumerate(events):
  typ=e['type']
  if typ=='puzzle_start':check(state(e['state'])==root and F(e['target'])==target,'puzzle_start')
  if typ=='node':
   check(e['node_id'] not in nodes,'duplicate node');nodes[e['node_id']]=e
   if e['parent_id'] is None:check(state(e['state'])==root and e['depth']==0,'root state');local['roots']+=1
   else:
    parent=nodes[e['parent_id']];check(e['depth']==parent['depth']+1 and len(e['state'])==len(parent['state'])-1,'node depth/size')
  if typ=='proposal':
   parent=nodes[e['parent_id']]
   try:child=apply(state(parent['state']),e['action'],cfg['allow_fractions']);valid=True
   except (AssertionError,ZeroDivisionError,TypeError,KeyError):valid=False
   check(valid==e['legal'],'proposal legal flag')
   if valid:
    child_node=nodes[e['child_node_id']];check(child==state(e['child_state'])==state(child_node['state']),'Fraction replay')
    check(child_node['parent_id']==e['parent_id'] and child_node['depth']==parent['depth']+1,'proposal parent');legal[e['child_node_id']]=e;local['legal_transitions']+=1
   else:local['illegal_proposals']+=1
  if typ=='chosen':
   check(e['node_id'] in legal,'chosen legality');check(nodes[e['node_id']]['parent_id']==e['parent_id'],'chosen parent')
  if typ=='request_start':
   rid=e['request_id'];check(rid not in starts and rid not in all_requests,'request ID duplicate');starts[rid]=e;all_requests.add(rid)
   check(e['node_id'] in nodes,'request state')
  if typ=='request_end':
   rid=e['request_id'];check(rid in starts and rid not in ends,'request pairing');ends[rid]=e
   check(all(e.get(k)==starts[rid].get(k) for k in ['agent_id','stage','node_id','puzzle_id','endpoint_index']),'request context')
   check(all(type(v)is int and v>=0 for k,v in e['usage'].items() if k!='estimated'),'usage schema')
   if 'total_tokens' in e['usage']:check(e['usage']['total_tokens']==e['usage'].get('prompt_tokens',0)+e['usage'].get('completion_tokens',0),'usage total')
   if e['stage']=='plan':plan_requests.append(e)
  if typ=='reward':
   success=target in state(nodes[e['node_id']]['state']);check(bool(e['solved'])==success and e['reward']==int(success),'reward proof')
   if success:proofs.append((index,e['node_id']));local['successful_rewards']+=1
  if typ=='puzzle_end' and e.get('solved'):
   check(proofs,'puzzle solved lacks reward proof')
   if 'node_id' in e:check(target in state(nodes[e['node_id']]['state']),'puzzle target')
  if typ=='run_end' and e.get('solved'):check(proofs,'run solved lacks proof')
  if typ=='controller_stop':
   check(index==len(events)-1 and e['source']=='controller','controller final event');check(not e['solved'] or proofs,'controller has prior producer proof')
   check(e['solved']==row['solved'] and e['status']==row['status'],'controller summary')
 for _,node in proofs:
  while nodes[node]['parent_id'] is not None:check(node in legal,'proof ancestry missing replay');node=nodes[node]['parent_id']
 # Plans are verified from their response and own root, never borrowed from another path.
 for e in plan_requests:
  start=starts[e['request_id']];check(nodes[start['node_id']]['parent_id'] is None and state(nodes[start['node_id']]['state'])==root,'plan starts original root')
  value=parse(e.get('response')) if not e.get('error') else None;moves=value.get('moves') if isinstance(value,dict) and set(value)=={'moves'} else None
  bounded=isinstance(moves,list) and 1<=len(moves)<=min(cfg['rounds'],len(root)-1);local['bounded_plan_responses' if bounded else 'invalid_plan_responses']+=1
  actual=[p for p in events if p['type']=='proposal' and p.get('agent_id')==e['agent_id'] and p['event_id']>e['event_id'] and p.get('proposal_id') and p.get('parent_id') in nodes]
  current=start['node_id'];path=[]
  for p in actual:
   if p['parent_id']==current:
    path.append(p)
    if p['legal']:current=p['child_node_id']
    else:break
  check(not path or bounded,'unbounded plan executed')
  check(len(path)<=len(moves or []),'too many plan steps')
  for i,p in enumerate(path):check(p['action']==moves[i],'plan differs from response')
  if row['arm'].startswith(('direct','ensemble')):check(len(path)<=min(cfg['rounds'],len(root)-1),'plan execution bound')
 expected=dict(calls=len(starts),completed_calls=len(ends),unfinished_calls=len(starts)-len(ends),prompt_tokens=sum(e['usage'].get('prompt_tokens',0) for e in ends.values()),completion_tokens=sum(e['usage'].get('completion_tokens',0) for e in ends.values()),charged_completion_tokens=sum(e.get('completion_tokens_charged',0) for e in ends.values()),missing_prompt_usage=sum('prompt_tokens' not in e['usage'] for e in ends.values()),missing_completion_usage=sum('completion_tokens' not in e['usage'] for e in ends.values()),response_errors=sum(bool(e.get('error')) for e in ends.values()),length_finishes=sum(e.get('finish_reason')=='length' for e in ends.values()),budget_denials=sum(e['type']=='budget_exhausted' for e in events))
 for k,v in expected.items():check(row[k]==v,'summary accounting '+k)
 check(len(starts)<=1280 and row['completion_tokens']<=32768,'budget ceiling')
 for end in (e for e in events if e['type']=='run_end'):
  check(end['budget']['calls']==len(starts) and end['budget']['completion_tokens_charged']==expected['charged_completion_tokens'],'run_end budget accounting')
 check(bool(proofs)==row['observed_solved'],'observed proof summary');check(not row['solved'] or proofs,'summary success proof')
 if row['status']=='success_early':check(row['solved'] and row['controller_stop'] and proofs and row['time_to_verified_solution_seconds']<180,'early success')
 before,after=row.get('server_metrics_before'),row.get('server_metrics_after');known=False;delta={}
 if before and after and not before.get('error') and not after.get('error') and row['server_idle_after'] and before.get('running')==before.get('waiting')==0:
  if all(k in before and k in after and after[k]>=before[k] for k in ('prompt','completion')):
   delta={k:after[k]-before[k] for k in ('prompt','completion')};known=all(delta[k]>=row[k+'_tokens'] for k in delta)
 check(known==row['server_cost_known'],'server known recompute')
 for k in ('prompt','completion'):check(row['server_'+k+'_tokens']==(int(delta[k]) if known else None),'server delta')
 counts.update(local);counts['cases']+=1;counts['request_starts']+=len(starts);counts['request_ends']+=len(ends);counts['controller_stops']+=int(row['controller_stop']);counts['known_server_cases']+=int(known)
 results.append(dict(task_id=row['task_id'],arm=row['arm'],trace=Path(row['events']).name,trace_sha256=sha(Path(row['events'])),**local))
audit=dict(valid_for_aggregation=False,diagnostic_scope='Entire original arithmetic seed2 excluded; proof/cost consistency audit is not protocol validity or an accuracy/ranking analysis',protocol='independent-arithmetic-audit-v1',split='evaluation',seed=2,status='PASS',source_commit=meta['git_revision'],source_hashes=meta['source_hashes'],selection_sha256=sha(app/'EVALUATION_SELECTION.json'),selection_frozen_utc=selection['frozen_utc'],cohort_started_utc=meta['started_utc'],dataset_sha256=meta['dataset_sha256'],metadata_sha256=sha(base/'metadata.json'),summary_sha256=sha(base/'summary.json'),audit_script_sha256=sha(Path(__file__)),counts=dict(counts),checks=['All192 planned cases,24tasks8arms seed2; captured source/dataset/selection pins','Independent Fraction replay of every legal proposal, positive integer intermediates, distinct indices, ordered state consumption','Every reward independently checks exact target presence; all successful ancestry edges replayed','Direct/ensemble/cascade plan responses bounded, own-original-root checked, executed moves match response prefix','Unique global request IDs and request contexts; client usage/charge/errors/caps/denials exactly match traces','Every successful controller stop has prior producer reward proof; controller is not its own proof','Server counters independently recomputed; unknown cost remains null','Public task schema only; pinned runner/harness/source inspection, command/config has no witness/reputation inputs; private witness file not opened'],cases=results)
Path(sys.argv[3]).write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps(dict(status='PASS',counts=dict(counts))))
