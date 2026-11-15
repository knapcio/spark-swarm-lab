from pathlib import Path
from fractions import Fraction as F
from collections import Counter
import json,math,statistics,hashlib,sys
base=Path(sys.argv[1]);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
bench=base/'serving-v032-comparison';measurements=[]
for mode in ('old','new'):
 for repeat in range(1,4):
  name=f'{mode}-c25-{repeat}.json';x=json.loads((bench/name).read_text());cfg=x['configuration'];s=x['summary'];rows=x['results'];assert cfg['concurrency']==25 and cfg['requests']==100 and cfg['max_tokens']==256 and cfg['temperature']==0 and cfg['enable_thinking']is False
  assert len(rows)==100 and s['requests']==100 and s['errors']==0 and all(not r['error']and r['http_status']==200 for r in rows)
  assert sum(r['usage']['completion_tokens']for r in rows)==s['completion_tokens'];assert sum(r['usage']['prompt_tokens']for r in rows)==s['prompt_tokens'];assert math.isclose(s['completion_tokens']/s['wall_seconds'],s['output_tokens_per_second'])
  assert s['finish_reasons']==dict(Counter(r['finish_reason']for r in rows))
  checks=[r['json_arithmetic_check']for r in rows if r['json_arithmetic_check']is not None];assert len(checks)==s['json_arithmetic_checks']['checked']==37 and sum(r['passed']for r in checks)==s['json_arithmetic_checks']['passed']==13
  measurements.append(dict(runtime=mode,repeat=repeat,file=name,**s))
old=statistics.median(r['output_tokens_per_second']for r in measurements if r['runtime']=='old');new=statistics.median(r['output_tokens_per_second']for r in measurements if r['runtime']=='new');comparison=json.loads((bench/'comparison.json').read_text());assert old==comparison['old_median']and new==comparison['new_median']and math.isclose(new/old,comparison['ratio'])
replays=[]
for name in ('serving-repro-v1-spark02','serving-repro-v032-spark02'):
 p=base/name;m=json.loads((p/'metadata.json').read_text());rows=json.loads((p/'summary.json').read_text());assert m['completed_cases']==len(rows)==20 and m['completed_utc'];errors=Counter();request_ids=set();calls=0
 for r in rows:
  events=[json.loads(l)for l in(p/Path(r['events']).name).read_text().splitlines()];starts=[e for e in events if e['type']=='request_start'];ends=[e for e in events if e['type']=='request_end'];ids={e['request_id']for e in starts};assert len(ids)==len(starts)and not ids&request_ids;request_ids|=ids
  assert len(starts)==r['calls']and len(ends)==r['completed_calls']and len(starts)-len(ends)==r['unfinished_calls'];calls+=len(starts)
  assert all(sum(e.get('usage',{}).get(k,0)for e in ends)==r[k]for k in ('prompt_tokens','completion_tokens'))
  assert not r['controller_error']and(r['returncode']==0 or r['returncode']<0 and r['controller_stop'])
  for e in ends:
   if e.get('error'):errors[e['error'].split(':',1)[0]]+=1
  assert r['infrastructure_failures']in(None,0)
  before,after=r['server_metrics_before'],r['server_metrics_after'];assert r['server_cost_known']and r['server_idle_after']and before['running']==before['waiting']==after['running']==after['waiting']==0
  assert all(after[k]-before[k]==r['server_'+k+'_tokens']>=r[k+'_tokens']for k in ('prompt','completion'))
 assert set(errors)<={'JSONDecodeError','ValueError'}
 replays.append(dict(directory=name,cases=20,calls=calls,controller_errors=0,recorded_transport_errors=0,model_parse_error_categories=dict(errors),known_final_worker_infrastructure_counts=sum(r['infrastructure_failures']is not None for r in rows),unknown_final_worker_infrastructure_counts=sum(r['infrastructure_failures']is None for r in rows),server_cost_known_cases=20,purpose='Serving diagnostic; model parse errors are preserved, no task-quality ranking or crash-fix claim'))
probes=[]
for temp in ('0','0.8'):
 name=f'new-short100-t{temp}.json';x=json.loads((bench/name).read_text());assert len(x['results'])==x['requests']==x['correct']==100 and all(r['ok']for r in x['results']);assert len(set(x['endpoints']))==1 and x['client_concurrency']==100
 probes.append(dict(file=name,correct=100,requests=100,distinct_endpoints=1,http_clients=100,engine_max_sequences=25,temperature=x['temperature']))
tool=json.loads((bench/'new-tool.json').read_text());assert tool['passed'];first=tool['first']['choices'][0]['message']['tool_calls'][0]['function'];assert first['name']=='add'and json.loads(first['arguments'])=={'a':17,'b':25};assert json.loads(tool['second']['choices'][0]['message']['content'])=={'result':42}
p=base/'v032-thinking-smoke';row=json.loads((p/'summary.json').read_text())[0];events=[json.loads(l)for l in(p/'ensemble4-sum10.jsonl').read_text().splitlines()];nodes={};legal=set();proofs=[]
for i,e in enumerate(events):
 if e['type']=='node':nodes[e['node_id']]=e;assert e['parent_id']is not None or tuple(map(F,e['state']))==(F(1),F(2),F(3),F(4))
 if e['type']=='proposal'and e['legal']:
  parent=tuple(map(F,nodes[e['parent_id']]['state']));a=e['action'];i1,j=a['i'],a['j'];assert type(i1)is int and type(j)is int and i1!=j and 0<=i1<len(parent)and 0<=j<len(parent)
  value={'+':lambda:parent[i1]+parent[j],'-':lambda:parent[i1]-parent[j],'*':lambda:parent[i1]*parent[j],'/':lambda:parent[i1]/parent[j]}[a['op']]();assert value>0 and value.denominator==1
  child=tuple(v for k,v in enumerate(parent)if k not in(i1,j))+(value,);assert child==tuple(map(F,e['child_state']))==tuple(map(F,nodes[e['child_node_id']]['state']));legal.add(e['child_node_id'])
 if e['type']=='reward'and e['solved']:
  assert F(10)in tuple(map(F,nodes[e['node_id']]['state']));proofs.append(i)
 if e['type']=='controller_stop':assert proofs and max(proofs)<i
for event in (e for e in events if e['type']=='reward'and e['solved']):
 node=event['node_id']
 while nodes[node]['parent_id']is not None:
  assert node in legal;node=nodes[node]['parent_id']
starts=[e for e in events if e['type']=='request_start'];assert len(starts)==len({e['request_id']for e in starts})==4
assert proofs and row['solved']and row['calls']==4 and row['completed_calls']==1 and row['unfinished_calls']==3 and row['infrastructure_failures']is None
ends=[e for e in events if e['type']=='request_end'];assert len(ends)==1 and ends[0]['request_id']in{e['request_id']for e in starts}and ends[0].get('reasoning')and row['completion_tokens']==ends[0]['usage']['completion_tokens']==7931
before,after=row['server_metrics_before'],row['server_metrics_after'];assert row['server_cost_known']and row['server_idle_after']and before['running']==before['waiting']==after['running']==after['waiting']==0;assert all(after[k]-before[k]==row['server_'+k+'_tokens']>=row[k+'_tokens']for k in('prompt','completion'))
launch=json.loads((base/'canary-launch.json').read_text());assert launch['architecture']=='arm64'and '6ff5ff0d' in launch['image']
audit=dict(schema_version=1,scope='Single-node finite serving qualification only; excluded from primary evaluation',valid_for_primary_aggregation=False,comparison=dict(old_median_output_tokens_per_full_wall_second=old,new_median_output_tokens_per_full_wall_second=new,observed_change_percent=(new/old-1)*100,measurements=measurements,limitations='All old repeats before new; three finite repeats, warmed c25 mixed100/cap256/T0. No robust speedup, sustained-decode, universal quality or proven crash-fix inference.'),diagnostic_replays=replays,short_json_probes=probes,tool_roundtrip=dict(passed=True,operation='add17and25→result42'),thinking_smoke=dict(proof_verified_with_Fraction=True,wall_seconds=row['wall_seconds'],first_verified_proof_seconds=row['time_to_verified_solution_seconds'],calls=4,completed_calls=1,unfinished_calls=3,completed_response_has_reasoning=True,client_prompt_tokens=row['prompt_tokens'],client_completion_tokens=row['completion_tokens'],client_cost_is_lower_bound=True,server_cost_known=True,server_prompt_tokens=row['server_prompt_tokens'],server_completion_tokens=row['server_completion_tokens'],final_worker_infrastructure_failures=None,notes='Expected-15 controller stop after producer proof; final infrastructure count unknown, not zero. Known idle server deltas include stopped sibling work.'),launch=dict(image=launch['image'],architecture=launch['architecture'],scope='Spark02 canary only; fleet deployment readiness not covered'),manifest_sha256=sha(base/'manifest.json'),audit_script_sha256=sha(Path(__file__)))
(base/'qualification-audit.json').write_text(json.dumps(audit,indent=2)+'\n');print('QualificationauditPASS:6benchmarkreports,40diagnosticreplays,200shortJSONs,tool,1reasoningproof')
