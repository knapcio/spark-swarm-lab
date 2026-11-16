"""Independent saved-trace/reference audit. No network, model, tests or candidate execution."""
from pathlib import Path
from fractions import Fraction
from collections import Counter,defaultdict
import json,hashlib,datetime,sys
D=Path(__file__).resolve().parent;R=D.parents[1];O=R/'runs/reference-deepseek-v1';F=R/'.runtime/evaluation-v2-source'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();h=lambda s:hashlib.sha256(s.encode()).hexdigest()
def ck(v,m):
 if not v:raise AssertionError(m)
def parse(s):
 if not isinstance(s,str):raise ValueError('not text')
 s=s.strip()
 if s.startswith('```'):
  lines=s.splitlines()
  if lines[-1].strip()!='```':raise ValueError('incomplete fence')
  s='\n'.join(lines[1:-1])
 v=json.loads(s)
 if not isinstance(v,dict):raise ValueError('not object')
 return v
def move(state,a):
 if not isinstance(a,dict)or set(a)!={'i','j','op'}:raise ValueError('keys')
 i,j,op=a['i'],a['j'],a['op']
 if type(i)is not int or type(j)is not int or i==j or not(0<=i<len(state)and 0<=j<len(state))or op not in ['+','-','*','/']:raise ValueError('domain')
 x,y=state[i],state[j]
 if op=='/'and not y:raise ValueError('zero')
 z=x+y if op=='+'else x-y if op=='-'else x*y if op=='*'else x/y
 if z<=0 or z.denominator!=1:raise ValueError('positive integer')
 return [v for k,v in enumerate(state)if k not in [i,j]]+[z]
def python_source(s):
 if not isinstance(s,str):raise ValueError('not text')
 s=s.strip()
 if s.startswith('```'):
  lines=s.splitlines(keepends=True)
  if len(lines)<3 or lines[0].strip().lower()not in ['```','```python']or lines[-1].strip()!='```':raise ValueError('fence')
  s=''.join(lines[1:-1]).strip()
 if not s:raise ValueError('empty')
 return s
m=read(O/'metadata.json');planpath=R/'.runtime/DEEPSEEK_REFERENCE_EVALUATION_PLAN.json';plan=read(planpath);pinpath=R/'.runtime/DEEPSEEK_REFERENCE_EVALUATION_FROZEN.json';pin=read(pinpath);launch=read(R/'.runtime/DEEPSEEK_REFERENCE_EVALUATION_LAUNCH.json');adpath=R/'.runtime/DEEPSEEK_REFERENCE_RUNTIME_ADMITTED.json';ad=read(adpath)
ck(sha(pinpath)==launch['frozen_receipt_sha256']and sha(planpath)==pin['plan_sha256']and sha(adpath)==pin['runtime_admission_sha256'],'freeze/launch/admission hashes')
ck(pin['source_revision']=='630701211036c4e1f8b369cfc3b36d39ce181732'and pin['evaluation_cases_before_freeze']==0 and pin['planned_cases']==126,'prospective source freeze')
ck(m['adapter_sha256']==pin['adapter_sha256']and len(pin['adapter_sha256'])==5,'adapter five pins')
for n,v in pin['adapter_sha256'].items():ck(sha(R/n)==v,('adapter drift',n))
ck(m['source_pin']['revision']==pin['frozen_harness_revision']=='cbcde299716b7842536b008880a089590e9816f8','CBC harness')
critical=['harness.py','direct_solver.py','coding_harness.py','sandbox_code.py','run_benchmark.py','run_coding_benchmark.py','datasets/arithmetic-v1/tasks.json','datasets/coding-v1/tasks.json','datasets/coding-v1/hidden-tests.json','runtime.json']
for n in critical:ck(sha(F/n)==m['source_pin']['sha256'][n],('active harness pin',n))
ck(all(m[k]==v for k,v in plan.items()if k!='mode'),'exact evaluation plan')
ck(ad['verified']and ad['head_guards_retained']and ad['checkpoint']=='mrfakename/DeepSeek-V4.1-Flash-1017-abliterated@517efab9ccfef7f714dbd7d679f181a86f43ccf9','runtime checkpoint admission')
ck(m['provider']=='deepseek'and m['model']==ad['model']=='deepseek-v4.1-flash'and m['endpoint']==ad['endpoint']=='http://127.0.0.1:18889/v1','endpoint/model alias')
qp=R.parents[1]/'diagnostics/swarm-prototype-20261115/deepseek-reference-restored-qualification-20261116.json';q=read(qp)
ck(sha(qp)==ad['native_qualification_sha256']==pin['native_qualification_sha256']and q['verified']and q['serving_verified'],'native qualification')
interop=R/'runs/reference-deepseek-interop-v1/metadata.json';devmeta=read(interop);ck(sha(interop)==pin['development_metadata_sha256']and devmeta['completed_utc']<pin['frozen_utc']<m['started_utc'],'development before frozen evaluation')
math={t['id']:t for t in read(F/'datasets/arithmetic-v1/tasks.json')['tasks']if t['split']=='evaluation'};code={t['id']:t for t in read(F/'datasets/coding-v1/tasks.json')['tasks']if t['split']=='evaluation'};private=read(F/'datasets/coding-v1/hidden-tests.json')['references']
expected={(domain,t,s)for domain,ts in [('arithmetic',math),('coding',code)]for t in ts for s in [1,2,3]};cases={(c['domain'],c['task_id'],c['seed']):c for c in m['cases']}
ck(len(math)==24 and len(code)==18 and len(cases)==len(m['cases'])==126 and set(cases)==expected,'126 task/seed matrix')
ck(m['replicates']==[1,2,3]and m['distinct_tasks']=={'arithmetic':24,'coding':18}and m['task_deadline_seconds']==180 and not m['server_metrics']and not m['stop_on_solution'],'reference allocation')
for n,v in m['template_sha256'].items():ck(sha(R/n)==v,'original direct template')
rows=read(O/'summary.json');keys=[(r['domain'],r['task_id'],r['seed'])for r in rows];ck(len(keys)==len(set(keys))and set(keys)<=expected,'completed grid unique')
counts=Counter();flat=[];intervals=defaultdict(list)
for row in rows:
 key=(row['domain'],row['task_id'],row['seed']);case=cases[key];ep=Path(row['events']);es=[json.loads(l)for l in ep.read_text().splitlines()];starts=[e for e in es if e['type']=='request_start'];ends=[e for e in es if e['type']=='request_end'];deadline=row['deadline']is True
 ck(row['reference_operational_halt_reason']is None and not row['controller_error']and not row['malformed_lines']and not row['infrastructure_failures'],'operational fault')
 ck(row['calls']==len(starts)==1 and row['completed_calls']==len(ends)<=1 and row['unfinished_calls']==1-len(ends),'single dispatch accounting')
 ck(all(e['request_id']==starts[0]['request_id']for e in ends),'request completion identity')
 if deadline:
  ck(row['status']=='deadline'and row['controller_stop']and row['returncode']in [0,-15,-9,143,137]and any(e['type']=='controller_stop'and e.get('deadline')and e.get('returncode')==row['returncode']for e in es),'controlled deadline')
 else:ck(row['status']=='complete'and row['returncode']==0 and len(ends)==1 and row['infrastructure_failures']==0,'complete process')
 ck(row['reference_attempt_status']==('task_budget_exhausted'if deadline else'completed')and row['reference_infrastructure_count_unknown']==(row['infrastructure_failures']is None),'attempt classification')
 ck(row['reference_usage_complete']==(not row['unfinished_calls']and not row['missing_prompt_usage']and not row['missing_completion_usage']),'usage status')
 ck(row['server_cost_known']is False and row['server_prompt_tokens']is None and row['server_completion_tokens']is None and row['server_metrics_before']is None and row['server_metrics_after']is None,'unknown server cost')
 for token in ['prompt_tokens','completion_tokens']:ck(row[token]==sum(e.get('usage',{}).get(token,0)for e in ends),'completed usage sum')
 ck(row['charged_completion_tokens']==sum(e['completion_tokens_charged']for e in ends),'charged end usage')
 if ends:ck(not(ends[0].get('error')and ends[0].get('response')is None and ends[0].get('finish_reason')!='length'),'transport failure')
 stem=ep.with_suffix('');ctx=read(Path(str(stem)+'.transport.context.json'));ck(ctx['source']==m['source_pin']and ctx['worker_sha256']==pin['adapter_sha256']['reference_worker.py']and ctx['provider']=='deepseek'and ctx['model']==m['model']and ctx['request_timeout_seconds']==210 and ctx['task_deadline_seconds']==180,'context pins/limits')
 cmd=case['command'];forwarded=cmd[cmd.index('--')+1:];ck(ctx['argv']==forwarded and forwarded[forwarded.index('--method')+1]=='direct'and forwarded[forwarded.index('--max-tokens')+1]=='8192'and forwarded[forwarded.index('--seed')+1]==str(row['seed']),'frozen forwarded arguments')
 trpath=Path(str(stem)+'.transport.jsonl');tr=[json.loads(l)for l in trpath.read_text().splitlines()]if trpath.exists()else[]
 ck(len(tr)==len(ends)or deadline and len(tr)<=1,'transport receipt count')
 if tr:
  v=tr[0];ck(v['provider']=='deepseek_openai'and'failure_classification'not in v,'transport provider/failure');body=v['request'];raw=v['raw_response'];start=starts[0]
  ck(v['request_sha256']==h(json.dumps(body)),'request body digest')
  ck(any(v['response_sha256']==h(json.dumps(raw,separators=(',',':'),ensure_ascii=a))for a in [True,False]),'raw response digest reconstruction')
  ck(body['model']==raw['model']==m['model']and body['max_tokens']==8192 and body['temperature']==0.8 and body['stream']is False and body['chat_template_kwargs']=={'enable_thinking':True},'request/response identity/settings')
  material=f"{row['seed']}:{start['agent_id']}:{start['stage']}:{body['messages'][1]['content']}";ck(body['seed']==int.from_bytes(hashlib.sha256(material.encode()).digest()[:4],'big'),'derived request seed')
  choice=raw['choices'][0];msg=choice['message'];usage=raw['usage'];ck(len(raw['choices'])==1 and usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens']and 0<=usage['completion_tokens']<=8192,'provider usage')
  if ends:
   end=ends[0];ck(end['response']==msg.get('content')and end['reasoning']==msg.get('reasoning_content',msg.get('reasoning'))and end['finish_reason']==choice['finish_reason'],'response field preservation')
   for token in ['prompt_tokens','completion_tokens','total_tokens']:ck(end['usage'][token]==usage[token],'provider/client usage')
  counts['reasoning_tokens']+=usage.get('completion_tokens_details',{}).get('reasoning_tokens',0)
  counts['response_alias_checked']+=1
 if row['domain']=='arithmetic':
  t=math[row['task_id']];state=list(map(Fraction,t['numbers']));target=Fraction(t['target']);pstart=next(e for e in es if e['type']=='puzzle_start');ck(pstart['state']==list(map(str,state))and pstart['target']==t['target'],'math task identity')
  if tr:
   prompt=(f"Target {t['target']}. Current indexed numbers: {dict(enumerate(map(str,state)))}. Give one complete plan to reach the target using any subset of numbers. Each move consumes two different indexed numbers and appends their result; remaining numbers keep their order and are reindexed from zero. Use +,-,*,/. Every intermediate result must be positive integer. Use at most {min(5,len(state)-1)} moves. Return only a JSON object with key moves, an array of objects with integer indices i,j and single-character operator op.")
   ck(body['messages']==[{'role':'system','content':'Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.'},{'role':'user','content':prompt}],'exact math prompt')
  try:parsed=parse(ends[0]['response'])if ends else{};moves=parsed.get('moves')if set(parsed)=={'moves'}else None
  except(ValueError,TypeError):moves=None
  if not isinstance(moves,list)or not 1<=len(moves)<=min(5,len(state)-1):moves=[]
  props=[e for e in es if e['type']=='proposal'];nodes={e['node_id']:e for e in es if e['type']=='node'};used=0
  for depth,action in enumerate(moves):
   if used>=len(props):ck(deadline,'missing plan step');break
   e=props[used];used+=1;ck(e['action']==action and e['depth']==depth and nodes[e['node_id']]['state']==list(map(str,state)),'plan action/parent')
   try:child=move(state,action)
   except(ValueError,TypeError):ck(e['legal']is False,'invalid move marked legal');break
   ck(e['legal']is True and e['child_state']==list(map(str,child))and nodes[e['child_node_id']]['parent_id']==e['node_id']and nodes[e['child_node_id']]['state']==e['child_state'],'exact Fraction child')
   counts['math_legal_steps']+=1;state=child
   if target in state:break
  ck(used==len(props),'extra unproposed steps');rewards=[e for e in es if e['type']=='reward']
  for e in rewards:ck(e['solved']==(target in state)and e['reward']==int(target in state)and e['distance']==str(min(abs(target-x)for x in state))and nodes[e['node_id']]['state']==list(map(str,state)),'math reward proof')
  if not deadline:ck(len(rewards)==1,'missing final arithmetic proof')
  ck(row['solved']==bool(rewards and rewards[-1]['solved']),'math summary proof');counts['math_proofs']+=len(rewards)
 else:
  t=code[row['task_id']];private_task=private[t['id']];gc=read(Path(str(stem)+'.transport.grader-context.json'))
  ck(gc['outer_grader_sha256']==pin['adapter_sha256']['independent_code_grader.py']=='c4324123bb75a8712150adb3e06e1da4e1e44a7d91516597d9a35caa372c2726'and gc['wrapper_sha256']==pin['adapter_sha256']['reference_grade_worker.py']and gc['grading_authority']=='outer_parent'and gc['oracle_sent_to_child']is False,'coding qualified wrapper')
  ck(gc['source_revision']==m['source_pin']['revision']and gc['frozen_module_sha256']=={n:m['source_pin']['sha256'][n]for n in ['coding_harness.py','harness.py','sandbox_code.py']},'frozen coding module identities')
  runstart=next(e for e in es if e['type']=='run_start');ck(runstart['task_id']==t['id']and runstart['public_sha256']==sha(F/'datasets/coding-v1/tasks.json')and runstart['private_sha256']==sha(F/'datasets/coding-v1/hidden-tests.json'),'public/private coding corpus identity')
  ck(gc['image']=='python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd','coding CPU image')
  cands=[e for e in es if e['type']=='code_candidate'];ck(len(cands)<=1,'direct single source')
  cp=[e for e in es if e['type']=='code_prompt'];ck(len(cp)==1,'coding prompt count')
  expected_prompt=('Implement this pure Python 3 function using only the standard library. Do not mutate any input, do external I/O, or rely on external packages. Return exact JSON-compatible values: arrays must be Python lists; bool and int are distinct; floats are outside this corpus; preserve every ordering required by the specification.\n'+json.dumps({k:t[k]for k in ['id','function_name','spec','examples']},ensure_ascii=False)+'\nReturn complete Python function source only. Do not wrap it in JSON or include explanations.')
  ck(cp[0]['prompt']==expected_prompt,'public-only code prompt')
  if tr:ck(body['messages']==[{'role':'system','content':'Implement or review the specified pure Python function. Return complete Python source for code proposals and the requested JSON for voting. Do not explain or use tools.'},{'role':'user','content':expected_prompt}],'exact coding wire prompt')
  selections=[e for e in es if e['type']=='candidate_selected'];gs={e['evaluation_id']:e for e in es if e['type']=='evaluation_start'};ge=[e for e in es if e['type']=='evaluation_end'];ck(set(gs)=={e['evaluation_id']for e in ge},'active coding grade requires cleanup review')
  if cands:
   candidate=cands[0];ck(h(candidate['code'])==candidate['candidate_id']and python_source(ends[0]['response'])==candidate['code'],'code response/source hash')
  for e in ge:
   phase=e['phase'];tests=private_task[phase+'_tests'];q=e['report'];ck(phase in ['feedback','holdout']and e['candidate_id']==candidate['candidate_id']and not e['infrastructure_error'],'coding phase/candidate')
   ck(q['cleanup_ok']is True and q['provenance']=='candidate'and q['grading_authority']=='outer_parent'and q['oracle_sent_to_child']is False and not str(q.get('failure_kind','')).endswith('_infrastructure'),'coding grade authority/cleanup')
   if q.get('container_state'):ck(q['container_state']['Running']is False,'grading container running')
   payload=json.dumps(dict(code=candidate['code'],function_name=t['function_name'],calls=[dict(args=x['args'],kwargs=x.get('kwargs',{}))for x in tests],timeout=10),allow_nan=False);ck(h(payload)==q['child_payload_sha256'],'expected-free code/test input payload')
   ck(q['total']==len(tests)and all(type(q[k])is int for k in ['passed','failed','tests_run'])and 0<=q['passed']<=q['tests_run']<=q['total']and q['failed']==q['tests_run']-q['passed'],'grade counts')
   if q['status']=='passed':ck(q['passed']==q['total']and q.get('first_failure')is None and q.get('failure_kind')is None,'positive code grade')
   ck(q['status']in ['passed','failed','error','timeout'],'grade status')
   if phase=='holdout':ck(len(selections)==1 and selections[0]['holdout_seen']is False and selections[0]['candidate_id']==candidate['candidate_id']and selections[0]['event_id']<gs[e['evaluation_id']]['event_id']and ends[0]['event_id']<selections[0]['event_id'],'freeze before holdout')
   counts['coding_grade_cleanup']+=1;counts['coding_'+q['status']]+=1
  holdouts=[e for e in ge if e['phase']=='holdout'];ck(len(holdouts)<=1 and len([e for e in ge if e['phase']=='feedback'])<=1,'single direct feedback/holdout')
  if not deadline:ck(len(selections)==1 and len(ge)==(2 if cands else 0),'complete coding phases')
  success=bool(holdouts and holdouts[0]['report']['status']=='passed');ck(row['solved']==success,'coding final holdout')
 counts['completed_cases']+=1;counts['deadlines']+=deadline;counts['unfinished_requests']+=row['unfinished_calls'];counts['usage_incomplete']+=not row['reference_usage_complete'];counts['unknown_server_cost']+=not row['server_cost_known']
 for token in ['prompt_tokens','completion_tokens']:counts[token]+=row[token]
 intervals[case['slot']].append((min(e['timestamp']for e in es if 'timestamp'in e),max(e['timestamp']for e in es if 'timestamp'in e)))
 flat.append(dict(domain=row['domain'],task_id=row['task_id'],seed=row['seed'],solved=row['solved'],deadline=deadline,usage_complete=row['reference_usage_complete'],prompt_tokens=row['prompt_tokens'],completion_tokens=row['completion_tokens'],server_cost_known=False))
 for n,v in pin['adapter_sha256'].items():ck(sha(R/n)==v,'adapter changed during audit')
for values in intervals.values():
 ordered=sorted(values);ck(all(a[1]<=b[0]for a,b in zip(ordered,ordered[1:])),'persistent case slot overlap')
if 'completed_utc'not in m:
 print(json.dumps(dict(status='running',checked_cases=len(rows),infrastructure_faults=0,partial_scores_published=False)));sys.exit(0)
ck(len(rows)==m['completed_cases']==126 and not m['incomplete']and not m['errors']and not m['source_changed_during_run']and m['final_source_pin']==m['source_pin']and m['final_adapter_sha256']==pin['adapter_sha256'],'complete master/source')
for n,v in m['source_pin']['sha256'].items():ck(sha(F/n)==v,('all final CBC pins',n))
for n,v in m['output_sha256'].items():ck(sha(O/n)==v,('output hash',n))
ck(m['task_budget_exhausted_cases']==counts['deadlines']and m['usage_incomplete_cases']==counts['usage_incomplete'],'final accounting')
inputs={str(p.relative_to(R)):sha(p)for p in O.iterdir()if p.is_file()}
for p in [planpath,pinpath,adpath,interop,R/'.runtime/DEEPSEEK_REFERENCE_EVALUATION_LAUNCH.json']+[R/n for n in pin['adapter_sha256']]+[F/n for n in critical]:inputs[str(p.relative_to(R))]=sha(p)
report=dict(verified=True,complete=True,completed_cases=126,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),counts=dict(counts),results={domain:dict(cases=sum(r['domain']==domain for r in rows),solved=sum(r['solved']for r in rows if r['domain']==domain))for domain in ['arithmetic','coding']},source_revision=pin['source_revision'],frozen_harness_revision=pin['frozen_harness_revision'],batch_wall_seconds=m['batch_wall_seconds'],input_sha256=inputs,external_input_sha256={str(qp):sha(qp)},auditor_sha256=sha(Path(__file__)),limits=['Separate custom abliterated native DeepSeek quality reference; no equivalent compute/effort or fleet-throughput claim.','Configured request/response alias corroborated by admitted runtime/checkpoint receipt; fullweights hash and fullsource-to-binary identity remain unknown.','Exact arithmetic Fraction proof replay. Coding verifies qualified outergrader authority, expected-free payload identity, phase/selection/counts/cleanup; fullraw child observations are not retained, so no independent code reexecution or positive-observation replay is claimed.','Controlled deadlines retain missing output/usage and unknown infrastructure count where recorded; server/global cost always unknown.','42tasks repeated across3seeds, not126 independent tasks. Native reasoning effort75/defaulttop_p0.95 differ from Nemotron.'])
for name,value in [('AUDIT.json',report),('case-replay.json',flat)]:
 with(D/name).open('x')as f:json.dump(value,f,indent=2);f.write('\n')
with(D/'ARTIFACT_MANIFEST.json').open('x')as f:json.dump({str(p.relative_to(D)):sha(p)for p in D.iterdir()if p.is_file()and p.name!='ARTIFACT_MANIFEST.json'},f,indent=2);f.write('\n')
print(json.dumps({k:v for k,v in report.items()if k not in ['input_sha256','external_input_sha256','limits']}));print('AUDIT_SHA256',sha(D/'AUDIT.json'))
