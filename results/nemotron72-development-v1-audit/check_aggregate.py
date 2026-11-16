"""Independent arithmetic/selection/bootstrap/hash QA; no model or candidate execution."""
import csv,hashlib,itertools,json,math,random,statistics
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
REPORT=ROOT/'results/nemotron72-development-v1-analysis';RUN=ROOT/'runs/nemotron72-development-v1'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def close(a,b):assert math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-10),(a,b)
def quantile(values,p):
    x=sorted(values);position=(len(x)-1)*p;left=math.floor(position);right=math.ceil(position)
    return x[left]*(right-position)+x[right]*(position-left)if left!=right else x[left]
def parse(text):
    if not isinstance(text,str):return None
    text=text.strip()
    if text.startswith('```'):
        lines=text.splitlines()
        if lines[-1].strip()!='```':return None
        text='\n'.join(lines[1:-1])
    try:value=json.loads(text)
    except ValueError:return None
    return value if isinstance(value,dict)else None
manifest=read(REPORT/'manifest.json');final=read(OUT/'FINAL_AUDIT.json');metadata=read(RUN/'metadata.json');rows=read(RUN/'summary.json');analysis=read(REPORT/'development/analysis.json');selection=read(REPORT/'selection.json');idlepath=ROOT/'.runtime/NEMOTRON72_DEVELOPMENT_IDLE_VERIFIED_V1.json';idle=read(idlepath)
assert final['verified']and final['complete']and final['completed_cases']==168 and not final['faults']
assert idle['verified']and idle['all_controlled_model_timing_idle']and idle['driver_pid24340_absent']and idle['final_audit_sha256']==sha(OUT/'FINAL_AUDIT.json')and idle['cohort_metadata_sha256']==sha(RUN/'metadata.json')
for path,digest in manifest['input_sha256'].items():assert sha(ROOT/path)==digest
for path,digest in manifest['source_sha256'].items():assert sha(ROOT/path)==digest
for path,digest in manifest['files'].items():assert sha(REPORT/path)==digest
assert manifest['source_revision']==final['source_revision']==metadata['source_revision']=='638b9f335a7aa7011a9b7d122abcaa04f45e17a5'
assert metadata['source_sha256']==metadata['final_source_sha256']==final['source_sha256']and len(final['source_sha256'])==10
for path,digest in metadata['output_sha256'].items():assert sha(RUN/path)==digest
for path,digest in final['input_sha256'].items():assert sha(ROOT/path)==digest
order=metadata['protocol']['matrix']['variants'];tasks=sorted({r['task_id']for r in rows})
assert len(rows)==168 and len(tasks)==8 and {(r['task_id'],r['arm'],r['seed'])for r in rows}==set(itertools.product(tasks,order,[1,2,3]))
data=read(ROOT/'.runtime/nemotron72-followup-source/datasets/arithmetic-v1/tasks.json')['tasks'];assert set(tasks)=={t['id']for t in data if t['split']=='development'};assert not set(tasks)&{t['id']for t in data if t['split']=='evaluation'}
server_tier=all(r['server_cost_known']is True and r['server_idle_after']is True and r['server_completion_tokens']>=r['completion_tokens']and r['server_prompt_tokens']>=r['prompt_tokens']for r in rows)
prompt_tier=all(r['missing_prompt_usage']==r['unfinished_calls']==0 and r['completed_calls']==r['calls']for r in rows)
counts={a:sum(r['solved']for r in rows if r['arm']==a)for a in order}
server={a:sum(r['server_completion_tokens']for r in rows if r['arm']==a)for a in order};prompt={a:sum(r['prompt_tokens']for r in rows if r['arm']==a)for a in order}
rank=lambda arm:(-counts[arm],*([server[arm]]if server_tier else[]),*([prompt[arm]]if prompt_tier else[]),order.index(arm))
better=[a for a in order if counts[a]>counts['index_original']];selected=min(better,key=rank)if better else'index_original'
assert counts==selection['successes']and selected==selection['selected_variant']=='scribe_full'
assert selection['baseline_successes']==counts['index_original']==9 and selection['strict_improvement']is bool(better)
assert selection['global_server_completion_tier_used']==server_tier and selection['global_client_input_tier_used']==prompt_tier
assert selection['server_completion_totals']==server and selection['client_input_totals']==prompt and selection['ranked_variants']==sorted(order,key=rank)
assert analysis['selection']==selection==manifest['selection']and analysis['split']=='development'and analysis['tasks']==8 and analysis['seeds']==[1,2,3]
assert analysis['bootstrap']==dict(unit='task cluster, all seeds retained',repetitions=5000,seed=20261115,interval='percentile 95%')
rng=random.Random(20261115);draws=[[rng.randrange(8)for _ in range(8)]for _ in range(5000)]
means={a:[sum(r['solved']for r in rows if r['arm']==a and r['task_id']==t)/3 for t in tasks]for a in order}
def interval(values):
    samples=[sum(values[i]for i in indices)/8 for indices in draws]
    return quantile(samples,.025),quantile(samples,.975)
for a in analysis['arms']:
    arm=a['arm'];group=[r for r in rows if r['arm']==arm];assert a['cases']==24 and a['tasks']==8 and a['solved']==counts[arm]
    close(a['accuracy'],counts[arm]/24);low,high=interval(means[arm]);close(a['cluster95_low'],low);close(a['cluster95_high'],high)
    for key in('calls','prompt_tokens','completion_tokens','unfinished_calls','length_finishes','budget_denials','missing_prompt_usage','missing_completion_usage'):assert a[key]==sum(r[key]for r in group)
    assert a['server_cost_known_cases']==24 and a['server_cost_unknown_cases']==0 and a['server_completion_tokens_known']==server[arm]and a['server_prompt_tokens_known']==sum(r['server_prompt_tokens']for r in group)
    close(a['median_occupied_case_wall_seconds'],statistics.median(r['wall_seconds']for r in group));close(a['p95_occupied_case_wall_seconds'],quantile([r['wall_seconds']for r in group],.95))
assert len(analysis['paired_deltas'])==21
for pair in analysis['paired_deltas']:
    assert pair['direction']=='a_minus_b'and pair['tasks']==8 and pair['matched_task_seed_pairs']==24
    values=[a-b for a,b in zip(means[pair['arm_a']],means[pair['arm_b']])];lo,hi=interval(values)
    close(pair['accuracy_delta'],sum(values)/8);close(pair['cluster95_low'],lo);close(pair['cluster95_high'],hi)
lookup={(r['task_id'],r['seed'],r['arm']):r['solved']for r in rows}
assert len(analysis['paired_cases'])==24
for pair in analysis['paired_cases']:
    for arm in order:assert pair[arm]==lookup[pair['task_id'],pair['seed'],arm]
for curve in analysis['success_by_time']:
    n=sum(r['solved']and r['time_to_verified_solution_seconds']<=curve['seconds']for r in rows if r['arm']==curve['arm']);assert curve['cases']==24 and curve['solved_by_time']==n;close(curve['fraction'],n/24)
secondary={a:dict(arm=a,cases=24,first_observed=0,first_length=0,first_parser_none=0,first_empty_content=0,eligible_cases=0,eligibility_unknown=0,commit_dispatched=0,commit_completed=0,commit_length=0,verified_conversions=0,conversion_denominator=0,final_format_invalid=0,final_illegal=0,verified_miss=0)for a in order};eligible_keys={a:set()for a in order}
for row in rows:
    events=[json.loads(s)for s in Path(row['events']).read_text().splitlines()];ends=[e for e in events if e['type']=='request_end'];first=next(e for e in ends if e['stage']=='plan');commit=next((e for e in ends if e['stage']=='scribe'),None);reasoning=first.get('reasoning');a=secondary[row['arm']]
    eligible=row['arm'].startswith('scribe_')and parse(first.get('response'))is None and first['response_received']is True and first['finish_reason']=='length'and isinstance(reasoning,str)and bool(reasoning.strip())
    dispatched=any(e['type']=='request_start'and e['stage']=='scribe'for e in events);invalid=any(e['type']=='plan_invalid'for e in events);illegal=any(e['type']=='proposal'and e['legal']is False for e in events)
    values=dict(first_observed=1,first_length=first['finish_reason']=='length',first_parser_none=parse(first.get('response'))is None,first_empty_content=not isinstance(first.get('response'),str)or not first['response'].strip(),eligible_cases=eligible,commit_dispatched=dispatched,commit_completed=commit is not None,commit_length=bool(commit and commit['finish_reason']=='length'),verified_conversions=eligible and dispatched and row['solved'],conversion_denominator=eligible,final_format_invalid=invalid,final_illegal=illegal,verified_miss=not row['solved']and not invalid and not illegal)
    for key,value in values.items():a[key]+=int(value)
    if eligible:eligible_keys[row['arm']].add((row['task_id'],row['seed']))
for actual in csv.DictReader((REPORT/'secondary.csv').open()):
    assert {k:(v if k=='arm'else int(v))for k,v in actual.items()}==secondary[actual['arm']]
assert analysis['secondary']==list(secondary.values())
assert secondary['scribe_full']['verified_conversions']==9 and secondary['scribe_full']['conversion_denominator']==13 and secondary['scribe_empty']['verified_conversions']==0 and secondary['scribe_empty']['conversion_denominator']==13
text=(REPORT/'REPORT.md').read_text();assert all(s in text for s in ['Winner-biased development','not fresh generalization','all repetitions','pointwise/unadjusted','Empty-notes still receives the full task','No GPU-equivalent cost'])
# The report performs no fit or causal mediation analysis: conditional rates are descriptive.
full_delta=[x-y for x,y in zip(means['scribe_full'],means['index_original'])];ci=interval(full_delta)
for path,digest in manifest['input_sha256'].items():assert sha(ROOT/path)==digest
for path,digest in manifest['files'].items():assert sha(REPORT/path)==digest
result=dict(verified=True,complete=True,status='PASS',checked_utc=datetime.now(timezone.utc).isoformat(),completed_cases=168,source_revision=final['source_revision'],selected_variant=selected,successes_per_24=counts,global_server_tier_eligible=server_tier,global_client_input_tier_eligible=prompt_tier,selection_has_unique_highest_success_count=True,cost_tiers_did_not_break_a_success_tie=True,secondary=secondary,scribe_full_minus_baseline=dict(delta=sum(full_delta)/8,cluster95_low=ci[0],cluster95_high=ci[1],scope='Unadjusted pointwise descriptive interval on the same development data used for selection'),eligible_full_empty_overlap=len(eligible_keys['scribe_full']&eligible_keys['scribe_empty']),bootstrap=dict(independently_recomputed=True,task_clusters=8,all_three_repetitions_retained=True,repetitions=5000,seed=20261115,accuracy_intervals_checked=7,paired_intervals_checked=21),hash_checks=dict(report_sources=len(manifest['source_sha256']),report_inputs=len(manifest['input_sha256']),report_outputs=len(manifest['files']),independent_audit_inputs=len(final['input_sha256']),all_match=True,raw_immutable=True),scope_review=['No original24 evaluation task included; all8 original development tasks present exactly3 times pervariant.','Recipe selected on reused development outcomes; no fresh generalization, universal100%, or fleet throughput claim.','Full9/13 and empty0/13 are conditional descriptive conversions; equal denominators do not establish identical notes or causal mediation.','Server/client cost tiers are globally eligible but selection is already determined by unique best20successes; common caps do not imply equal realized input or GPU work.','Root performed actualPNG visualQA; this independent check verifies their exact file hashes/source labels and numeric data, not another visual render.'],input_sha256={str(REPORT.relative_to(ROOT))+'/manifest.json':sha(REPORT/'manifest.json'),str((OUT/'FINAL_AUDIT.json').relative_to(ROOT)):sha(OUT/'FINAL_AUDIT.json'),str(idlepath.relative_to(ROOT)):sha(idlepath)},qa_source_sha256=sha(Path(__file__)),audit_directory_freeze='No further writes after this receipt and final directory inventory; notify root before any later amendment.')
with(OUT/'AGGREGATE_CHECK.json').open('x')as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps(dict(status='PASS',selected=selected,successes=counts,full_delta= result['scribe_full_minus_baseline'],eligible_overlap=result['eligible_full_empty_overlap'],aggregate_check_sha256=sha(OUT/'AGGREGATE_CHECK.json')),indent=2))
