"""Read-only saved-evidence audit; no API, SSH, candidate execution or new probes."""
from pathlib import Path
import json,hashlib,datetime,subprocess
D=Path(__file__).resolve().parent;R=D.parents[1];O=R/'.runtime/guided-schema-qualification-v1'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();h=lambda s:hashlib.sha256(s.encode()).hexdigest()
p=read(R/'.runtime/GUIDED_SCHEMA_PROBE_PLAN.json');pin=read(R/'.runtime/CSP_GUIDED_FROZEN_SOURCE.json');F=Path(pin['source_worktree']);a=read(O/'admission.json');r=read(O/'result.json')
assert sha(R/'.runtime/GUIDED_SCHEMA_PROBE_PLAN.json')==a['plan_sha256']==r['plan_sha256']=='1638edfe5dea9f2f8c77867fb38df0c69a6ab6c5f708417215959c0b3fbf2e92'
assert sha(R/'.runtime/CSP_GUIDED_FROZEN_SOURCE.json')==p['source_receipt_sha256']
assert p['source_revision']==pin['revision']==a['source_revision']==r['source_revision']=='4b7258ee9c660659ad04fa3baddee9535da214fd'
assert p['source_selection_sha256']==pin['selection_sha256']==sha(F/'SEARCH_SELECTION.json')
assert subprocess.check_output(['git','-C',str(F),'rev-parse','HEAD'],text=True).strip()==pin['revision']
assert not subprocess.check_output(['git','-C',str(F),'status','--porcelain','--untracked-files=no'],text=True).strip()
assert len(r['source_sha256'])==19 and r['source_sha256']==a['source_sha256']==pin['source_identity']['sha256']
for n,v in r['source_sha256'].items():assert sha(F/n)==v
assert sha(R/'.runtime/qualify_guided_schema_v1.py')==r['driver_sha256']==a['driver_sha256']=='7135a70f7af213fba65c0e711b15dec4cc469239a6f3dcc48878bcb0dd5e685c'
assert sha(R/'.runtime/post_throughput_overnight.py')=='a850fb38f2fe9579863f8d41bdfae8aa045d9300cc736dd1394fcc4dcd3c8e6e'
prior_path=R/'.runtime/program-review-confirmation-admission-v1.1/manual-admission.json';prior=read(prior_path)
assert sha(prior_path)==a['prior_admission_sha256']==r['prior_admission_sha256']
assert prior['verified']and not prior['model_switch_started']and not prior['feature_switch_started']
age=(datetime.datetime.fromisoformat(a['started_utc'])-datetime.datetime.fromisoformat(prior['checked_utc'])).total_seconds();assert 0<=age<=900
upstream=['runs/csp-thinking_on16-evaluation-s1-late/metadata.json','runs/program-review-elites4-v1.1/metadata.json','runs/program-review-confirmation-v1.1/metadata.json','runs/program-search-v1/metadata.json']
for n in upstream:
 v=read(R/n);assert v['verified']and not v.get('incomplete')and not v.get('faults')and v['completed_utc']<a['started_utc']
assert p['prepared_utc']<a['started_utc']<r['completed_utc']
assert p['endpoint']=='http://127.0.0.1:18083/v1'and p['max_tokens']==512 and p['request_timeout_seconds']==210 and p['thinking']is False and p['temperature']==0.8 and p['exact_total_model_calls']==r['maximum_calls']==3
assert all(r[k]==v for k,v in a.items())
assert r['executed_calls']==len(r['rows'])==2 and r['qualified']is False and r['source_unchanged']is True
assert [x['id']for x in r['rows']]==['cardinality-24','cardinality-64']and r['errors']==[dict(probe='cardinality-64',classification='JSONDecodeError')]
assert not(O/'critique.json').exists()and not list((R/'runs').glob('*guided*'))
probes=[]
for i,row in enumerate(r['rows']):
 q=p['probes'][i];assert row==read(O/(q['id']+'.json'))
 n,k=[(24,3),(64,4)][i]
 schema=dict(type='object',properties=dict(assignment=dict(type='array',minItems=n,maxItems=n,items=dict(type='integer',enum=list(range(k))))),required=['assignment'],additionalProperties=False)
 assert q['schema']==schema and 'exactly ONE integer zero' in q['prompt']
 material=f"{p['seed_label']}:{q['agent_id']}:{q['stage']}:{q['prompt']}"
 seed=int.from_bytes(hashlib.sha256(material.encode()).digest()[:4],'big')
 body=dict(model=p['model'],messages=[dict(role='system',content=p['system_prompt']),dict(role='user',content=q['prompt'])],max_tokens=512,temperature=0.8,seed=seed,stream=False,chat_template_kwargs=dict(enable_thinking=False),structured_outputs=dict(json=schema))
 assert row['request']==body and row['request_sha256']==h(json.dumps(body))
 assert row['http_status']==200 and row['response_sha256']==h(json.dumps(row['response'],separators=(',',':')))
 data=row['response'];choice=data['choices'][0];message=choice['message'];content=message['content'];usage=data['usage']
 assert data['model']==p['model']and len(data['choices'])==1 and data['system_fingerprint']=='vllm-0.32.0-d4cc5b20'
 assert usage['prompt_tokens']==52 and usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens']and usage['completion_tokens_details']['reasoning_tokens']==0 and message['reasoning']is None
 if i==0:
  payload=json.loads(content);assert payload==row['payload']=={'assignment':[0]*24}and all(type(x)is int for x in payload['assignment'])
  assert choice['finish_reason']=='stop'and usage['completion_tokens']==110 and row['schema_valid']is True and 'error_classification'not in row
 else:
  assert type(content)is str and len(content)==523 and content.startswith('{\n  "assignment":')and content[len('{\n  "assignment":'):].isspace()
  try:json.loads(content)
  except json.JSONDecodeError:pass
  else:raise AssertionError('Incomplete prefix unexpectedly valid JSON')
  assert choice['finish_reason']=='length'and usage['completion_tokens']==512 and row['schema_valid']is False and row['error_classification']=='JSONDecodeError'and'payload'not in row
 probes.append(dict(id=row['id'],seed=seed,http_status=200,schema_valid=row['schema_valid'],finish_reason=choice['finish_reason'],content_characters=len(content),prompt_tokens=52,completion_tokens=usage['completion_tokens'],reasoning_tokens=0,request_sha256=row['request_sha256'],response_sha256=row['response_sha256']))
# Independent basic shape fixtures, including bool rejection, without any model execution.
valid=lambda x: type(x)is dict and set(x)=={'assignment'}and type(x['assignment'])is list and len(x['assignment'])==24 and all(type(v)is int and 0<=v<3 for v in x['assignment'])
fixtures=[({'assignment':[0]*24},True),({'assignment':[0]*23},False),({'assignment':[0]*25},False),({'assignment':[True]*24},False),({'assignment':[3]*24},False),({'assignment':[0]*24,'extra':0},False)]
assert all(valid(x)is expected for x,expected in fixtures)
for stage in ['before','after']:
 fleet=r['fleet_'+stage];saved=read(O/f'fleet-{stage}-probes.json');assert saved['complete']and saved['rows']==fleet and len(fleet)==4
 for i,n in enumerate(fleet,1):
  c=n['container'];assert n['host']==f'Spark_{i:02d}'and n['hostname']==f'spark-{i:02d}'and n['endpoint']==f'http://127.0.0.1:{18080+i}/v1'
  assert n['verified']and n['idle']and n['health']=='200'and n['metrics']['running']==n['metrics']['waiting']==0
  assert c==dict(owner='swarm-lab-20261115',image='vllm/vllm-openai@sha256:6ff5ff0ddf3658d2c2d677dac5ca2d4726ce0156b4371166d918181b210bd4bc',running=True,oom=False,restart_count=0,state_error='',speculation='dspark')
  assert(n['metrics']['timestamp_utc']<r['started_utc'])if stage=='before'else(n['metrics']['timestamp_utc']<r['completed_utc']and n['metrics']['timestamp_utc']>r['started_utc'])
for i,(before,after)in enumerate(zip(r['fleet_before'],r['fleet_after']),1):
 assert after['metrics']['prompt']-before['metrics']['prompt']==(104 if i==3 else 0)
 assert after['metrics']['completion']-before['metrics']['completion']==(622 if i==3 else 0)
files=[p for p in O.iterdir()if p.is_file()]+[R/'.runtime/GUIDED_SCHEMA_PROBE_PLAN.json',R/'.runtime/CSP_GUIDED_FROZEN_SOURCE.json',R/'.runtime/qualify_guided_schema_v1.py',R/'.runtime/post_throughput_overnight.py',prior_path]+[R/n for n in upstream]+[F/n for n in r['source_sha256']]
report=dict(verified=True,complete=True,qualification_passed=False,executed_model_calls=2,maximum_planned_probes=3,unexecuted_probe='critique',quality_cases_executed=0,planned_quality_cases_deferred=84,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_revision=pin['revision'],source_pins=19,probes=probes,costs=dict(prompt_tokens=104,completion_tokens=622,server_counters_match=True),fleet_final_healthy_idle=True,source_unchanged=True,offline_shape_fixtures=6,input_sha256={str(p.relative_to(R)):sha(p)for p in files},auditor_sha256=sha(Path(__file__)),interpretation=['Qualification failed the frozen stop rule at second adversarial cardinality probe; no third probe or84quality cases executed.','Prompt requests ONE item while schemas require24/64. This is a frozen adversarial format qualification, not a normal graph prompt.','24-item schema passed;64-item request returned HTTP200 nonempty523-character incomplete JSON prefix plus whitespace, finish length at512tokens, reasoning_tokens0.','No proof that structured-output backend is unsupported or normal CSP generation would fail. No graph quality outcome is inferred.','Parsed full response objects reconstruct recorded raw-response SHA256 through compact JSON encoding; full request bodies and derived seeds match frozen plan.','Owned-grader-leftover check passed in bounddriver before admission; no individual command-output receipt was retained for that check. Fleet snapshots/counter receipts are retained.','No audit network/model/SSH/candidate execution; original frozen source/protocol and runtime untouched.'])
with(D/'AUDIT.json').open('x')as f:json.dump(report,f,indent=2);f.write('\n')
with(D/'ARTIFACT_MANIFEST.json').open('x')as f:json.dump({str(p.relative_to(D)):sha(p)for p in D.iterdir()if p.is_file()and p.name!='ARTIFACT_MANIFEST.json'},f,indent=2);f.write('\n')
print(json.dumps(dict(path=str((D/'AUDIT.json').relative_to(R)),sha256=sha(D/'AUDIT.json'),verified=True,qualification_passed=False,executed_calls=2,quality_cases=0)))
