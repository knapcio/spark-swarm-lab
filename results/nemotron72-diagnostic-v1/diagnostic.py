"""Already-seen exploratory trace accounting only; no inference, code execution or puzzle search."""
from pathlib import Path
from collections import Counter,defaultdict
import json,csv,hashlib,itertools,datetime
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1]
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
FOCUS=['direct_thinking_8k','ensemble4_thinking_8k','solo_refine_thinking_8k'];PLANS=['direct_thinking_8k','ensemble2_thinking_8k','ensemble4_thinking_8k','solo_refine_thinking_8k']
inputs={};rows=[]
for seed in [1,2,3]:
 for stem in [f'evaluation-v2-arithmetic-s{seed}',f'solo-control-v2-evaluation-s{seed}']:
  for name in ['summary.json','metadata.json']:
   p=ROOT/'runs'/stem/name;inputs[str(p.relative_to(ROOT))]=sha(p)
  rows+=read(ROOT/'runs'/stem/'summary.json')
taskfile=ROOT/'.runtime/evaluation-v2-source/datasets/arithmetic-v1/tasks.json';inputs[str(taskfile.relative_to(ROOT))]=sha(taskfile);tasks={t['id']:t for t in read(taskfile)['tasks']if t['split']=='evaluation'}
methods=sorted({r['arm']for r in rows});assert len(rows)==648 and len(tasks)==24 and len(methods)==9
bycase={(r['task_id'],r['seed'],r['arm']):r for r in rows};assert len(bycase)==648
for t in tasks:
 for seed in [1,2,3]:
  for arm in methods:assert(t,seed,arm)in bycase
wins={arm:{(r['task_id'],r['seed'])for r in rows if r['arm']==arm and r['solved']}for arm in methods}
assert [len(wins[a])for a in FOCUS]==[18,49,45]
focus_union=set.union(*(wins[a]for a in FOCUS));all_union=set.union(*wins.values());allkeys={(t,s)for t in tasks for s in [1,2,3]}
per_task=[]
for t in tasks.values():
 row=dict(task_id=t['id'],numbers=json.dumps(t['numbers']),number_count=len(t['numbers']),target=t['target'])
 for arm in methods:
  seeds=[s for s in [1,2,3]if(t['id'],s)in wins[arm]];row[arm+'_successes']=len(seeds);row[arm+'_successful_seeds']=','.join(map(str,seeds))
 row.update(focus_union_successes=sum((t['id'],s)in focus_union for s in [1,2,3]),all_methods_union_successes=sum((t['id'],s)in all_union for s in [1,2,3]),focus_any_seed=any((t['id'],s)in focus_union for s in [1,2,3]),all_methods_any_seed=any((t['id'],s)in all_union for s in [1,2,3]))
 per_task.append(row)
pairs=[]
for a,b in itertools.combinations(methods,2):pairs.append(dict(method_a=a,method_b=b,both=len(wins[a]&wins[b]),a_only=len(wins[a]-wins[b]),b_only=len(wins[b]-wins[a]),neither=len(allkeys-(wins[a]|wins[b])),union=len(wins[a]|wins[b])))
plans=[];cases=[]
for row in rows:
 case=dict(task_id=row['task_id'],seed=row['seed'],method=row['arm'],solved=row['solved'],calls=row['calls'],completed_calls=row['completed_calls'],unfinished_calls=row['unfinished_calls'],status=row['status'],stop_reason=row['stop_reason'],deadline=row['deadline'],controller_stop=row['controller_stop'],response_errors=row['response_errors'],length_finishes=row['length_finishes'],prompt_tokens=row['prompt_tokens'],completion_tokens=row['completion_tokens'],server_cost_known=row['server_cost_known'],server_prompt_tokens=row['server_prompt_tokens'],server_completion_tokens=row['server_completion_tokens'],wall_seconds=row['wall_seconds'],events=row['events'])
 cases.append(case)
 if row['arm']not in PLANS:continue
 ep=Path(row['events']);inputs[str(ep.relative_to(ROOT))]=sha(ep);events=[json.loads(l)for l in ep.read_text().splitlines()];requests={};current={};roots={}
 for e in events:
  ty=e['type']
  if ty=='request_start':
   assert e['stage']=='plan';rid=e['request_id'];agent=e['agent_id'];assert rid not in requests
   p=dict(task_id=row['task_id'],seed=row['seed'],method=row['arm'],request_id=rid,agent_id=agent,plan_number=e.get('plan_revision',agent)+1,dispatch_timestamp=e['timestamp'],response_timestamp=None,reward_timestamp=None,request_end_retained=False,reward_retained=False,verified_success=None,finish_reason=None,completion_tokens=None,prompt_tokens=None,response_parse_error=None,plan_invalid_reason=None,invalid_move_error=None,legal_steps=0,illegal_steps=0,response_characters=None,reasoning_characters=None,revision_validation_error=None,case_status=row['status'],case_deadline=row['deadline'],case_stop_reason=row['stop_reason'])
   requests[rid]=p;current[agent]=rid;roots[e['node_id']]=rid
  elif ty=='request_end':
   p=requests[e['request_id']];assert not p['request_end_retained'];p.update(request_end_retained=True,response_timestamp=e['timestamp'],finish_reason=e.get('finish_reason'),completion_tokens=e['usage'].get('completion_tokens'),prompt_tokens=e['usage'].get('prompt_tokens'),response_parse_error=e.get('error'),response_characters=len(e['response'])if isinstance(e.get('response'),str)else None,reasoning_characters=len(e['reasoning'])if isinstance(e.get('reasoning'),str)else None)
  elif ty=='plan_invalid':requests[roots[e['node_id']]]['plan_invalid_reason']=e['reason']
  elif ty=='proposal':
   p=requests[current[e['agent_id']]];p['legal_steps']+=e['legal']is True;p['illegal_steps']+=e['legal']is False
   if not e['legal']:p['invalid_move_error']=e.get('error')
  elif ty=='reward':
   p=requests[current[e['agent_id']]];assert p['request_end_retained']and not p['reward_retained'];p.update(reward_retained=True,verified_success=e['solved'],reward_timestamp=e['timestamp'])
  elif ty=='plan_revision_complete':
   p=requests[current[e['agent_id']]];assert p['plan_number']==e['plan_revision']+1 and p['verified_success']==e['solved'];p['revision_validation_error']=e['validation_error']
 assert len(requests)==row['calls']and sum(p['request_end_retained']for p in requests.values())==row['completed_calls']
 assert sum(not p['request_end_retained']for p in requests.values())==row['unfinished_calls']
 assert row['solved']==any(p['verified_success']is True for p in requests.values())
 for p in requests.values():
  if not p['request_end_retained']:
   p['outcome']='response_not_retained_at_deadline'if row['deadline']else'response_not_retained_after_verified_success_stop'if row['status']=='success_early'else'response_not_retained_other'
  elif not p['reward_retained']:p['outcome']='response_retained_verification_outcome_missing'
  elif p['verified_success']:p['outcome']='verified_success'
  elif p['response_parse_error']:p['outcome']='response_parse_error'
  elif p['plan_invalid_reason']:p['outcome']='invalid_plan_schema'
  elif p['invalid_move_error']:p['outcome']='invalid_move'
  else:p['outcome']='legal_plan_missed_target'
  plans.append(p)
aggregate={}
for arm in methods:
 rr=[r for r in rows if r['arm']==arm];pp=[p for p in plans if p['method']==arm]
 aggregate[arm]=dict(cases=len(rr),solved=len(wins[arm]),tasks_solved_any_seed=len({t for t,s in wins[arm]}),tasks_solved_all_three_seeds=sum(all((t,s)in wins[arm]for s in [1,2,3])for t in tasks),dispatches=sum(r['calls']for r in rr),retained_responses=sum(r['completed_calls']for r in rr),unfinished_trace_requests=sum(r['unfinished_calls']for r in rr),deadline_cases=sum(r['deadline']for r in rr),success_early_cases=sum(r['status']=='success_early'for r in rr),known_server_cost_cases=sum(r['server_cost_known']for r in rr),plan_outcomes=dict(Counter(p['outcome']for p in pp)),finish_reasons=dict(Counter(str(p['finish_reason'])for p in pp if p['request_end_retained'])),invalid_move_errors=dict(Counter(p['invalid_move_error']for p in pp if p['invalid_move_error'])),parse_errors=dict(Counter(p['response_parse_error']for p in pp if p['response_parse_error'])),plan_positions={str(i):dict(dispatched=sum(p['plan_number']==i for p in pp),retained=sum(p['plan_number']==i and p['request_end_retained']for p in pp),verified_success=sum(p['plan_number']==i and p['verified_success']is True for p in pp),verified_failure=sum(p['plan_number']==i and p['verified_success']is False for p in pp),no_verified_outcome=sum(p['plan_number']==i and p['verified_success']is None for p in pp))for i in range(1,5)}if pp else None)
for source in ['.runtime/evaluation-v2-source/direct_solver.py','.runtime/evaluation-v2-source/ensemble_solver.py','.runtime/evaluation-v2-source/harness.py','.runtime/solo-control-v2-source/direct_solver.py','.runtime/solo-control-v2-source/ensemble_solver.py','.runtime/solo-control-v2-source/harness.py']:
 inputs[source]=sha(ROOT/source)
missed_focus=sorted(t for t in tasks if not any((t,s)in focus_union for s in [1,2,3]));missed_all=sorted(t for t in tasks if not any((t,s)in all_union for s in [1,2,3]))
report=dict(protocol='already-seen-nemotron72-diagnostic-v1',created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),scope='Posthoc descriptive diagnostic of original648 arithmetic method/task/seed cases; not a new experiment, heldout analysis or runtimeadvisor. No Fable files read.',verified_existing_scores=True,task_count=24,seeds=[1,2,3],methods=aggregate,complementarity=pairs,headroom=dict(focus_methods=FOCUS,focus_union_successes=len(focus_union),e4_plus_solo_union=len(wins['ensemble4_thinking_8k']|wins['solo_refine_thinking_8k']),all_nine_union_successes=len(all_union),e4_failures_with_existing_other_focus_success=len(focus_union-wins['ensemble4_thinking_8k']),e4_failures_with_existing_any_method_success=len(all_union-wins['ensemble4_thinking_8k']),focus_persistently_missed_tasks=missed_focus,all_methods_persistently_missed_tasks=missed_all,all_methods_unsolved_task_seed_pairs=[dict(task_id=t,seed=s)for t,s in sorted(allkeys-all_union)],tasks_with_any_recorded_success=len({t for t,s in all_union})),input_sha256=inputs,auditor_sha256=sha(Path(__file__)),limits=['Unions are hindsight oracle unions of separate runs; not performance of an implemented router and not matched cost.','Different seeds and methods have different calls, reasoning budgets, timing and observations. Success somewhere on all24already-seen tasks is not72/72fresh performance; reusing answers would leak evaluation solutions.','A missing request_end means no retained client response, not proven cancellation or zero backend work. E4 omissions occur in verified-success-stopped cases; server counters include drained backend work where known.','Sequential control allowed up to4plans but ended after success or180s; longer wall time or adaptive output caps are untested budget/policy extensions, not evidence of a solver bug.','Per-plan success rates among retained E4 responses are selection-biased; successful races censor remaining responses. Sequential later-plan rates are also conditioned on previous failures and deadline survival.','All plan labels come from frozen exact-verifier trace outcomes; no new arithmetic search or candidate code was executed.'])
def csv_write(name,rr):
 with(OUT/name).open('x',newline='')as f:
  w=csv.DictWriter(f,fieldnames=list(rr[0]));w.writeheader();w.writerows({k:'null'if v is None else v for k,v in r.items()}for r in rr)
for name,rr in [('per-task.csv',per_task),('per-case.csv',cases),('per-plan.csv',plans),('method-complementarity.csv',pairs)]:csv_write(name,rr)
with(OUT/'DIAGNOSTIC.json').open('x')as f:json.dump(report,f,indent=2);f.write('\n')
print(json.dumps(dict(scores={a:aggregate[a]['solved']for a in methods},headroom=report['headroom'],plan_details={a:{k:aggregate[a][k]for k in ['plan_outcomes','finish_reasons','invalid_move_errors','plan_positions']}for a in PLANS}),indent=2))
