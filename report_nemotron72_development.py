#!/usr/bin/env python3
"""Plan-first completed 168-case development report; never inspect partial outcomes."""
import argparse
import hashlib,json,math,subprocess,sys
from pathlib import Path
import aggregate_evaluation as ag
from harness import parse_json_response
from report_completed_studies import save_report

HERE=Path(__file__).resolve().parent
REVISION='638b9f335a7aa7011a9b7d122abcaa04f45e17a5'
VARIANTS=('index_original','index_explicit','value_original','value_explicit','scribe_full','scribe_tail','scribe_empty')
SOURCES=('run_followup72.py','followup72_worker.py','followup72.py','followup72_client.py','harness.py','direct_solver.py','run_benchmark.py','runtime.json','FOLLOWUP72_DEVELOPMENT_PLAN.json','datasets/arithmetic-v1/tasks.json')
read=lambda p:json.loads(Path(p).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
def numeric(x):return type(x)in (int,float)and math.isfinite(x)and x>=0

def select(rows,order=VARIANTS):
    require(len(rows)==168 and len(order)==7 and len(set(order))==7,'Complete168 seven-variant matrix required')
    keys={(r['task_id'],r['seed'],r['arm'])for r in rows};tasks={r['task_id']for r in rows}
    require(len(keys)==168 and len(tasks)==8 and keys=={(t,s,a)for t in tasks for s in (1,2,3)for a in order}and all(type(r.get('solved'))is bool for r in rows),'Incomplete/duplicate task/seed/variant matrix')
    server=all(r.get('server_cost_known')is True and r.get('server_idle_after')is True and all(numeric(r.get('server_'+k+'_tokens'))and(not numeric(r.get(k+'_tokens'))or r['server_'+k+'_tokens']>=r[k+'_tokens'])for k in ('prompt','completion'))for r in rows)
    prompt=all(numeric(r.get('prompt_tokens'))and r.get('missing_prompt_usage')==0 and r.get('unfinished_calls')==0 and r.get('completed_calls')==r.get('calls')for r in rows)
    counts={a:sum(r['solved']for r in rows if r['arm']==a)for a in order}
    server_totals={a:sum(r['server_completion_tokens']for r in rows if r['arm']==a)if server else None for a in order}
    prompt_totals={a:sum(r['prompt_tokens']for r in rows if r['arm']==a)if prompt else None for a in order}
    def rank(a):return tuple([-counts[a]]+([server_totals[a]]if server else[])+([prompt_totals[a]]if prompt else[])+[order.index(a)])
    better=[a for a in order if counts[a]>counts['index_original']];chosen=min(better,key=rank)if better else'index_original'
    return dict(selected_variant=chosen,strict_improvement=bool(better),baseline_successes=counts['index_original'],successes=counts,global_server_completion_tier_used=server,global_client_input_tier_used=prompt,server_completion_totals=server_totals,client_input_totals=prompt_totals,ranked_variants=sorted(order,key=rank),reason='Strict development success improvement'if better else'No strict success improvement; retain baseline',scope='Winner-biased development selection on 8 reused tasks x 3 seeds; not fresh generalization or fleet throughput')

def secondary(row,events):
    ends=[e for e in events if e.get('type')=='request_end'];first=next((e for e in ends if e.get('stage')=='plan'),None);commit=next((e for e in ends if e.get('stage')=='scribe'),None)
    parsed=None
    if first:
        try:parsed=parse_json_response(first.get('response'))
        except (ValueError,TypeError):pass
    reasoning=first.get('reasoning')if first else None
    eligible=(parsed is None and first.get('response_received')is True and first.get('finish_reason')=='length'and isinstance(reasoning,str)and bool(reasoning.strip()))if first and row['arm'].startswith('scribe_')else None if first is None else False
    started=any(e.get('type')=='request_start'and e.get('stage')=='scribe'for e in events);finished=any(e.get('type')=='puzzle_end'for e in events)
    return dict(task_id=row['task_id'],seed=row['seed'],arm=row['arm'],solved=row['solved'],deadline=row.get('deadline'),first_observed=first is not None,first_finish=first.get('finish_reason')if first else None,first_parser_none=parsed is None if first else None,first_content_empty=(not isinstance(first.get('response'),str)or not first['response'].strip())if first else None,eligible_commit=eligible,commit_dispatched=started,commit_completed=commit is not None,commit_finish=commit.get('finish_reason')if commit else None,eligible_verified_conversion=bool(eligible and started and row['solved']),final_format_invalid=any(e.get('type')=='plan_invalid'for e in events),final_illegal=any(e.get('type')=='proposal'and e.get('legal')is False for e in events),verification_finished=finished)

def validate(directory,audit_path):
    meta,audit=read(directory/'metadata.json'),read(audit_path)
    require(meta.get('completed_cases')==meta.get('attempts')==168 and meta.get('incomplete')is False and meta.get('errors')==[] and meta.get('source_changed_during_run')is False and meta.get('completed_utc'),'Complete168/error-free source-stable cohort required')
    require(audit.get('verified')is True and audit.get('complete')is True and audit.get('completed_cases')==168 and audit.get('faults')==[] and audit.get('source_revision')==REVISION,'Independent final audit PASS required')
    for p in (directory/'metadata.json',directory/'summary.json'):
        keys=[str(p),str(p.resolve())]
        if p.resolve().is_relative_to(HERE):keys.append(str(p.resolve().relative_to(HERE)))
        require(any(audit['input_sha256'].get(k)==sha(p)for k in keys),'Audit input hash missing/changed')
    require(meta.get('source_revision')==REVISION and set(meta['source_sha256'])==set(SOURCES)and meta['source_sha256']==meta['final_source_sha256']==audit['source_sha256'],'Exact unchanged10-source pins required')
    for n,h in meta['source_sha256'].items():require(hashlib.sha256(subprocess.check_output(['git','show',REVISION+':'+n],cwd=HERE)).hexdigest()==h,'Source differs from frozen638')
    require(meta['source_sha256']['harness.py']==sha(HERE/'harness.py'),'Exact frozen parser unavailable')
    plan=meta['protocol'];require(plan['status']=='FROZEN'and plan['protocol']=='nemotron72-development-v1'and plan['matrix']['variants']==list(VARIANTS),'Wrong frozen protocol/order')
    require(plan==json.loads(subprocess.check_output(['git','show',REVISION+':FOLLOWUP72_DEVELOPMENT_PLAN.json'],cwd=HERE)),'Protocol differs from frozen638')
    rows=read(directory/'summary.json');select(rows)
    require({r['task_id']for r in rows}==set(plan['matrix']['development_task_ids_in_stored_order']),'Wrong development task IDs')
    cases={(c['task_id'],c['seed'],c['arm'])for c in meta['cases']};require(len(cases)==168 and cases=={(r['task_id'],r['seed'],r['arm'])for r in rows},'Planned/observed grid mismatch')
    for name,h in meta['output_sha256'].items():require(Path(name).name==name and sha(directory/name)==h,'Raw output changed')
    return meta,rows,audit

def plot(report,output):
    import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    for kind in ('accuracy','latency','client-cost'):
        fig,ax=plt.subplots(figsize=(11,5));arms=report['arms']
        for i,r in enumerate(arms):
            if kind=='accuracy':ax.errorbar(100*r['accuracy'],i,xerr=[[100*(r['accuracy']-r['cluster95_low'])],[100*(r['cluster95_high']-r['accuracy'])]],fmt='o',capsize=3)
            elif kind=='latency':ax.plot([r['median_occupied_case_wall_seconds'],r['p95_occupied_case_wall_seconds']],[i,i],marker='o')
            else:ax.scatter(r['prompt_tokens']/r['cases'],r['completion_tokens']/r['cases'],label=r['arm']+(' *'if r['client_cost_is_lower_bound']else''))
        if kind!='client-cost':ax.set(yticks=range(len(arms)),yticklabels=[r['arm']for r in arms]);ax.invert_yaxis()
        else:ax.legend(fontsize=8);ax.set(ylabel='Observed client completion tokens/case')
        ax.set(xlabel={'accuracy':'Verified success (%), task-cluster empirical 95% interval','latency':'Occupied case wall: median and p95 seconds (not confidence intervals)','client-cost':'Observed client input tokens/case; *usage lower bound'}[kind],title='DEVELOPMENT — 8 reused tasks x 3 repetitions; '+kind)
        fig.text(.02,.01,'Recipe selected on these outcomes: winner-biased development, not fresh generalization. Tokens are not GPU-equivalent cost.',fontsize=8);fig.tight_layout(rect=(0,.05,1,.96))
        for ext in ('png','svg'):fig.savefig(output/(kind+'.'+ext),dpi=180,bbox_inches='tight',pad_inches=.2)
        plt.close(fig)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--audit',type=Path);p.add_argument('--output',type=Path);p.add_argument('--run',action='store_true');p.add_argument('--plot',action='store_true');args=p.parse_args(argv)
    if not args.run:print(json.dumps(dict(mode='plan',variants=list(VARIANTS),cases=168,tasks=8,reps=3,bootstrap=5000,requires='Complete168+unchanged10pins+AstraPASS+rootGO/allmodeltimingidle',outcomes_read=False)));return 0
    require(args.audit and args.output and not args.output.exists(),'Final audit and new output required');sources=('report_nemotron72_development.py','test_report_nemotron72_development.py','aggregate_evaluation.py','report_completed_studies.py','harness.py');before={n:sha(HERE/n)for n in sources};meta,rows,audit=validate(args.input,args.audit);decision=select(rows);metrics=[]
    for row in rows:
        events=[json.loads(x)for x in(args.input/Path(row['events']).name).read_text().splitlines()if x.strip()];metrics.append(secondary(row,events));row.update(cohort=str(args.input))
    dataset=meta['protocol']['matrix']['dataset_sha256'];report=ag.report_for(rows,[dict(directory=str(args.input),source_commit=REVISION,source_hashes=meta['source_sha256'],configuration=meta['protocol'],mixed_arm_queue_wall_seconds=meta['batch_wall_seconds'])],dataset,'arithmetic',5000,20261115);report.update(split='development',selection=decision,scope=decision['scope'])
    secondary_totals=[]
    for arm in VARIANTS:
        group=[r for r in metrics if r['arm']==arm];eligible=[r for r in group if r['eligible_commit']is True]
        secondary_totals.append(dict(arm=arm,cases=24,first_observed=sum(r['first_observed']for r in group),first_length=sum(r['first_finish']=='length'for r in group),first_parser_none=sum(r['first_parser_none']is True for r in group),first_empty_content=sum(r['first_content_empty']is True for r in group),eligible_cases=len(eligible),eligibility_unknown=sum(r['eligible_commit']is None for r in group),commit_dispatched=sum(r['commit_dispatched']for r in group),commit_completed=sum(r['commit_completed']for r in group),commit_length=sum(r['commit_finish']=='length'for r in group),verified_conversions=sum(r['eligible_verified_conversion']for r in eligible),conversion_denominator=len(eligible),final_format_invalid=sum(r['final_format_invalid']for r in group),final_illegal=sum(r['final_illegal']for r in group),verified_miss=sum(r['verification_finished']and not r['solved']and not r['final_format_invalid']and not r['final_illegal']for r in group)))
    report['secondary']=secondary_totals;args.output.mkdir(parents=True);save_report(args.output/'development',report,False);ag.csv_out(args.output/'case-telemetry.csv',metrics);ag.csv_out(args.output/'secondary.csv',secondary_totals);(args.output/'selection.json').write_text(json.dumps(decision,indent=2)+'\n')
    if args.plot:plot(report,args.output/'development')
    notes=['# DEVELOPMENT recipe selection','',decision['scope']+'.','',f"Selected: **{decision['selected_variant']}**. {decision['reason']}.",'', 'The frozen rule requires strictly more successes than index_original. Cost tiers apply globally only when all168 cases have the required complete measurement coverage; skipped-tier totals remain null, never zero. Final ties use listed variant order. No selection occurs on an incomplete matrix.','', 'Eight reused development tasks, three repetitions each;5000 task-cluster replicates retain all repetitions. Paired contrasts are pointwise/unadjusted, not new independent evidence after choosing the variant on these same outcomes. All-pass/all-fail empirical intervals may degenerate and do not imply a true population guarantee.','', 'Conditional conversion is verified within the case budget divided by all observed eligible cases, including denied/unfinished/deadline commits. Unknown first responses are counted separately; do not treat an unobserved response as zero eligibility. Empty-notes still receives the full task and is a control, not a chance-only impossibility. Finish rate or zero-denial counts do not establish quality.','', 'Measured input/output, client lower bounds, server coverage, case wall/deadlines and lifecycle counts remain separate. No GPU-equivalent cost or mixed-queue fleet throughput is inferred. All raw benchmark inputs/source remain unchanged.','', '[Detailed report](development/REPORT.md), [statistics](development/analysis.json), [CSV](development/summary.csv), [paired contrasts](development/paired-deltas.csv), [secondary denominators](secondary.csv), [case telemetry](case-telemetry.csv), [selection](selection.json), [manifest](manifest.json).']
    (args.output/'REPORT.md').write_text('\n'.join(notes)+'\n');inputs={str(args.input/'metadata.json'):sha(args.input/'metadata.json'),str(args.audit):sha(args.audit),**{str(args.input/n):h for n,h in meta['output_sha256'].items()}}
    require(before=={n:sha(HERE/n)for n in sources}and all(sha(n)==h for n,h in inputs.items()),'Source/raw inputs changed while reporting')
    manifest=dict(source_sha256=before,input_sha256=inputs,source_revision=REVISION,command=['python3','report_nemotron72_development.py',*sys.argv[1:]],selection=decision,raw_inputs_modified=False,files={str(p.relative_to(args.output)):sha(p)for p in args.output.rglob('*')if p.is_file()});(args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Wrote',args.output);return 0

if __name__=='__main__':raise SystemExit(main())
