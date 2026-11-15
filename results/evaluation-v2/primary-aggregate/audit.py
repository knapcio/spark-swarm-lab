from pathlib import Path
import csv,hashlib,io,json,math,statistics,sys
app=Path(sys.argv[1]).resolve();root=app/'results/evaluation-v2';sha=lambda b:hashlib.sha256(b).hexdigest()
def reverse(obj,edits):
 for e in reversed(edits):
  p=obj
  for k in e['path'][:-1]:p=p[k]
  assert p[e['path'][-1]]==e['export'];p[e['path'][-1]]=e['original']
 return obj
checks={}
for name in ['coding-s3','primary-aggregate']:
 manifest=json.loads((root/name/'manifest.json').read_bytes());count=0
 for e in manifest['files']:
  raw=Path(e['source']).read_bytes();export=(app/e['export']).read_bytes()
  assert sha(raw)==e['original_sha256'] and sha(export)==e['export_sha256']
  if not e['normalizations']:assert raw==export
  elif e['export'].endswith('.csv'):
   assert reverse(list(csv.reader(io.StringIO(export.decode(),newline=''))),e['normalizations'])==list(csv.reader(io.StringIO(raw.decode(),newline='')))
  elif e['export'].endswith(('.jsonl','.stdout.log')):
   before=raw.splitlines();after=export.splitlines();assert len(before)==len(after)
   by={}
   for edit in e['normalizations']:by.setdefault(edit['record'],[]).append(edit)
   for i,(a,b) in enumerate(zip(before,after),1):
    if i in by:assert reverse(json.loads(b),by[i])==json.loads(a)
    else:assert a==b
  else:assert reverse(json.loads(export),e['normalizations'])==json.loads(raw)
  count+=1
 checks[name+'_manifest_files']=count
m=json.loads((root/'primary-aggregate/manifest.json').read_bytes());assert sha((root/'primary-aggregate/curate.py').read_bytes())==m['curator_sha256']
p=root/'coding-s3/analysis';audit=json.loads((p/'protocol-cost-audit.json').read_bytes());assert sha((p/'protocol-cost-audit.py').read_bytes())==audit['audit_script_sha256']
normal=json.loads((p/'verified-ledger-entry-normalizations.json').read_bytes());entry=json.loads((p/'verified-ledger-entry.json').read_bytes());original=reverse(entry,normal['normalizations']);assert sha(json.dumps(original,ensure_ascii=False).encode())==audit['ledger_completed_entry_sha256']
ledger=json.loads((root/'primary-aggregate/verified-ledger.json').read_bytes());assert len(ledger)==6 and all(e['verified'] is True and e['valid_for_aggregation'] is True and e['fresh_v2'] is True and e['returncode']==0 for e in ledger)
checks['primary_verified_cases']=sum(e['completed_cases']for e in ledger);assert checks['primary_verified_cases']==900
for domain,tasks,n in [('arithmetic',24,72),('coding',18,54)]:
 report=json.loads((root/f'primary-aggregate/{domain}/analysis.json').read_bytes());rows=sum([json.loads((root/f'{domain}-s{s}/summary.json').read_bytes())for s in(1,2,3)],[])
 assert report['tasks']==tasks and report['seeds']==[1,2,3] and report['bootstrap']['unit']=='task cluster, all seeds retained'
 assert report['script_sha256']==sha((app/'aggregate_evaluation.py').read_bytes())=='4c552a40115b9eef23c48814bebaf900ba83646e41f41b1f03c13594855ebe84'
 lookup={}
 for a in report['arms']:
  rr=[r for r in rows if r['arm']==a['arm']];assert len(rr)==n and len({(r['task_id'],r['seed'])for r in rr})==n
  assert sum(r['solved']for r in rr)==a['solved'] and math.isclose(a['accuracy'],sum(r['solved']for r in rr)/n)
  for key in ['calls','prompt_tokens','completion_tokens','unfinished_calls','length_finishes','budget_denials']:assert sum(r.get(key,0)or 0 for r in rr)==a[key]
  assert all(r['server_cost_known']is True and r['server_idle_after']is True for r in rr)
  for key in ['prompt_tokens','completion_tokens']:assert sum(r['server_'+key]for r in rr)==a['server_'+key+'_known'] and all(r['server_'+key]>=r[key]for r in rr)
  assert a['server_cost_known_cases']==n and a['server_cost_unknown_cases']==0
  assert statistics.median(r['wall_seconds']for r in rr)==a['median_occupied_case_wall_seconds']
  lookup[a['arm']]={(r['task_id'],r['seed']):r for r in rr}
 for pair in report['paired_deltas']:
  a,b=lookup[pair['arm_a']],lookup[pair['arm_b']];assert a.keys()==b.keys() and pair['matched_task_seed_pairs']==n
  assert math.isclose(pair['accuracy_delta'],sum(int(a[k]['solved'])-int(b[k]['solved'])for k in a)/n,abs_tol=1e-12)
 for curve in report['success_by_time']:
  rr=lookup[curve['arm']].values();solved=sum(r['solved']and isinstance(r.get('time_to_verified_solution_seconds'),(int,float))and r['time_to_verified_solution_seconds']<=curve['seconds']for r in rr)
  assert solved==curve['solved_by_time'] and curve['cases']==n and math.isclose(solved/n,curve['fraction'])
 for source in report['source_cohorts']:
  path=app/source['directory'];assert sha((path/'metadata.json').read_bytes())==source['metadata_sha256'] and sha((path/'summary.json').read_bytes())==source['summary_sha256']
  assert source['source_commit']=='cbcde299716b7842536b008880a089590e9816f8' and source['source_hashes']==source['final_source_hashes']
 checks[domain]=dict(cases=len(rows),task_clusters=tasks,paired_contrasts=len(report['paired_deltas']),known_server_cases=len(rows),unfinished_calls=sum(r['unfinished_calls']for r in rows),unknown_final_worker_infrastructure_cases=sum(r['infrastructure_failures']is None for r in rows))
configs=json.loads((root/'primary-aggregate/source-configurations.json').read_bytes());checks['provided_configuration_document_sha256']=sha((root/'primary-aggregate/source-configurations.json').read_bytes())
result=dict(status='PASS',scope='Independent complete-primary point/cost/paired/time/source/export audit; bootstrap algorithm verified separately by frozen helper tests; no model code or API executed.',checks=checks,audit_script_sha256=sha(Path(__file__).read_bytes()))
(root/'primary-aggregate/aggregation-audit.json').write_text(json.dumps(result,indent=2)+'\n');(root/'primary-aggregate/audit.py').write_bytes(Path(__file__).read_bytes());print(json.dumps(result,indent=2))
