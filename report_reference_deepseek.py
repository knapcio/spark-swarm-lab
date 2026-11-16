#!/usr/bin/env python3
"""Completed native DeepSeek reference only; default plan reads no partial outcomes."""
import argparse,hashlib,json,shutil,subprocess,sys
from fractions import Fraction
from pathlib import Path
import aggregate_evaluation as ag
from harness import apply_action,canonical
from report_completed_studies import save_report
from run_references import assess_attempt
from reference_worker import verify_gate

HERE=Path(__file__).resolve().parent
ADAPTER='6307012';CBC='cbcde299716b7842536b008880a089590e9816f8';ALIAS='deepseek-v4.1-flash'
OUTER='c4324123bb75a8712150adb3e06e1da4e1e44a7d91516597d9a35caa372c2726'
IMAGE='python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd'
read=lambda p:json.loads(Path(p).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
def records(path):return [json.loads(x)for x in Path(path).read_text().splitlines()if x.strip()]
def audit_bound(path,audit):
    keys=[str(path),str(path.resolve())]
    if path.resolve().is_relative_to(HERE):keys.append(str(path.resolve().relative_to(HERE)))
    require(any(audit.get('input_sha256',{}).get(k)==sha(path)for k in keys),'Independent audit input hash missing/changed: '+str(path))

def arithmetic(case,row,events):
    puzzle=case['command'][case['command'].index('--puzzle')+1];numbers,target=puzzle.split(':');initial=tuple(Fraction(x)for x in numbers.split(','));nodes={};legal=set()
    for e in events:
        if e['type']=='node':
            require(e['node_id']not in nodes,'Duplicate arithmetic node');nodes[e['node_id']]=e
            require(e.get('parent_id')in nodes if e.get('parent_id')else e['state']==canonical(initial),'Root/ancestry differs')
        elif e['type']=='proposal'and e.get('legal'):
            child=apply_action(tuple(Fraction(x)for x in nodes[e['parent_id']]['state']),e['action'],'--allow-fractions'in case['command'])
            require(nodes[e['child_node_id']]['parent_id']==e['parent_id']and canonical(child)==e['child_state']==nodes[e['child_node_id']]['state'],'Illegal arithmetic transition');legal.add(e['child_node_id'])
        elif e['type']=='reward'and e.get('solved'):require(Fraction(target)in tuple(Fraction(x)for x in nodes[e['node_id']]['state']),'False arithmetic reward')
    require(all(not n.get('parent_id')or k in legal for k,n in nodes.items()),'Unverified arithmetic child')
    require(row['solved']is any(e['type']=='reward'and e.get('solved')is True for e in events),'Summary arithmetic proof mismatch')

def coding(case,row,events,context,private,public):
    require(context.get('source_revision')==CBC and context.get('outer_grader_sha256')==OUTER and context.get('image')==IMAGE and context.get('grading_authority')=='outer_parent'and context.get('oracle_sent_to_child')is False,'Coding wrapper qualification mismatch')
    selected=[e for e in events if e['type']=='candidate_selected'];holdouts=[e for e in events if e['type']=='evaluation_end'and e['phase']=='holdout'];candidates={e['candidate_id']:e for e in events if e['type']=='code_candidate'}
    require(len(selected)<=1 and len(holdouts)<=1 and(selected or row.get('deadline')),'Single frozen selection required')
    if selected:require(selected[0].get('holdout_seen')is False and all(e['event_id']<selected[0]['event_id']for e in events if e['type']=='request_start'),'Holdout-driven retry')
    for e in events:
        if e['type']!='evaluation_end':continue
        report=e['report'];candidate=candidates[e['candidate_id']];require(hashlib.sha256(candidate['code'].encode()).hexdigest()==e['candidate_id'],'Candidate code SHA mismatch')
        require(report.get('grading_authority')=='outer_parent'and report.get('oracle_sent_to_child')is False and report.get('cleanup_ok')is True and report.get('provenance')=='candidate'and e.get('infrastructure_error')is False,'Unqualified coding grade')
        tests=private[case['task_id']][e['phase']+'_tests'];payload=json.dumps(dict(code=candidate['code'],function_name=public[case['task_id']]['function_name'],calls=[dict(args=t['args'],kwargs=t.get('kwargs',{}))for t in tests],timeout=10),allow_nan=False)
        require(report.get('child_payload_sha256')==hashlib.sha256(payload.encode()).hexdigest(),'Coding source/test payload mismatch')
        if e['phase']=='holdout':require(selected and selected[0]['candidate_id']==e['candidate_id']and e['event_id']>selected[0]['event_id'],'Holdout before selection or changed source')
    proof=any(e['type']=='reward'and e.get('solved')is True for e in events);require(row['solved']is proof,'Coding summary proof mismatch')
    if proof:require(len(holdouts)==1 and holdouts[0]['report']['status']=='passed','Solved without qualified holdout')

def validate(directory,audit_path):
    meta=read(directory/'metadata.json');audit=read(audit_path)
    require(meta.get('completed_cases')==126 and meta.get('attempts')==126 and meta.get('incomplete')is False and meta.get('errors')==[] and meta.get('completed_utc')and meta.get('source_changed_during_run')is False,'Native cohort incomplete/faulty')
    require(audit.get('verified')is True and audit.get('complete')is True and audit.get('completed_cases')==126,'Final independent audit PASS required')
    for name in ('metadata.json','summary.json'):audit_bound(directory/name,audit)
    require(meta.get('provider')=='deepseek'and meta.get('model')==ALIAS and meta.get('server_metrics')is False and meta.get('task_deadline_seconds')==180,'Wrong provider/alias/cost/deadline protocol')
    require(meta['source_pin']==meta['final_source_pin']and meta['source_pin']['revision']==CBC and meta['adapter_sha256']==meta['final_adapter_sha256']and len(meta['adapter_sha256'])==5,'Frozen adapter/source changed')
    for name,h in meta['adapter_sha256'].items():require(hashlib.sha256(subprocess.check_output(['git','show',ADAPTER+':'+name],cwd=HERE)).hexdigest()==h,'Adapter differs from native reference tag')
    for name,h in meta['output_sha256'].items():require(Path(name).name==name and sha(directory/name)==h,'Changed native case output')
    require(meta['completion_gate']==verify_gate(HERE),'Original final45 gate changed')
    rows=read(directory/'summary.json');cases={(c['domain'],c['task_id'],c['seed']):c for c in meta['cases']};require(len(cases)==len(rows)==126 and set(cases)=={(r['domain'],r['task_id'],r['seed'])for r in rows},'Incomplete/duplicate126 grid')
    private=read(HERE/'datasets/coding-v1/hidden-tests.json')['references'];public={t['id']:t for t in read(HERE/'datasets/coding-v1/tasks.json')['tasks']}
    for domain,n in [('arithmetic',24),('coding',18)]:
        ids={t['id']for t in read(HERE/f'datasets/{"arithmetic"if domain=="arithmetic"else"coding"}-v1/tasks.json')['tasks']if t['split']=='evaluation'}
        require(len(ids)==n and {(k[1],k[2])for k in cases if k[0]==domain}=={(t,s)for t in ids for s in (1,2,3)},'Wrong frozen task/seed grid')
    for row in rows:
        case=cases[row['domain'],row['task_id'],row['seed']];events=records(directory/Path(case['events']).name);require(assess_attempt(row,events)['reference_operational_halt_reason']is None,'Operational fault/deadline semantics')
        ends=[e for e in events if e['type']=='request_end'];starts=[e for e in events if e['type']=='request_start'];transport=records(directory/Path(case['command'][case['command'].index('--transport-record')+1]).name)
        if ends:
            require(len(transport)==1 and transport[0].get('raw_response',{}).get('model')==ALIAS,'Missing/wrong actual model alias');t=transport[0];body=t['request'];raw=t['raw_response'];choice=raw['choices'][0];message=choice['message']
            require(body['model']==ALIAS and body['max_tokens']==8192 and body['temperature']==.8 and body['chat_template_kwargs']=={'enable_thinking':True}and t['request_sha256']==hashlib.sha256(json.dumps(body).encode()).hexdigest(),'Wrong native request')
            material=f"{case['seed']}:{starts[0]['agent_id']}:{starts[0]['stage']}:{body['messages'][1]['content']}";require(body['seed']==int.from_bytes(hashlib.sha256(material.encode()).digest()[:4],'big'),'Request seed binding')
            require(message.get('content')==ends[0].get('response')and message.get('reasoning_content',message.get('reasoning'))==ends[0].get('reasoning')and choice['finish_reason']==ends[0]['finish_reason']and all(ends[0]['usage'].get(k)==raw['usage'].get(k)for k in ('prompt_tokens','completion_tokens','total_tokens')),'Response/usage/trace mismatch')
        else:require(row.get('deadline')is True,'Missing completed response without controlled deadline')
        if row['domain']=='arithmetic':arithmetic(case,row,events)
        else:
            context=read((directory/Path(case['command'][case['command'].index('--transport-record')+1]).name).with_suffix('.grader-context.json'));coding(case,row,events,context,private,public)
        require(row.get('server_cost_known')is not True,'Native server cost must remain unknown')
    return meta,rows,audit

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--audit',type=Path);p.add_argument('--output',type=Path);p.add_argument('--run',action='store_true');p.add_argument('--plot',action='store_true');args=p.parse_args(argv)
    if not args.run:print(json.dumps(dict(mode='plan',cases=126,domains={'arithmetic':'24tasks x3seeds','coding':'18tasks x3seeds'},bootstrap=5000,required='Full126 complete/errors[]/unchanged source + AstraPASS + RootGO CPUwindow',models_executed=0)));return 0
    require(args.audit and args.output and not args.output.exists(),'Final audit and new output required');source_names=('report_reference_deepseek.py','test_report_reference_deepseek.py','aggregate_evaluation.py','report_completed_studies.py','run_references.py','reference_worker.py','harness.py');before={n:sha(HERE/n)for n in source_names};meta,native,audit=validate(args.input,args.audit);reports={};inputs={str(args.input/'metadata.json'):sha(args.input/'metadata.json'),str(args.audit):sha(args.audit)}
    confirmation=HERE/'runs/coding-confirmation-v1';cm=read(confirmation/'metadata.json');require(cm.get('complete')is True and cm.get('source_changed_during_run')is False,'Nemo independent confirmation incomplete');confirmed={(r['task_id'],r['arm'],r['seed']):r for r in read(confirmation/'summary.json')}
    for domain,n in [('arithmetic',24),('coding',18)]:
        primary=[HERE/f'results/evaluation-v2/{domain}-s{s}'for s in (1,2,3)];rows,cohorts,dataset=ag.load_cohorts(primary,domain,expected_tasks=n,ledger=read(HERE/'runs/evaluation-v2-ledger.json'))
        keep={'direct_thinking_8k':'Nemotron single full plan 8K','ensemble4_thinking_8k':'Nemotron four full plans'}if domain=='arithmetic'else{'direct_thinking':'Nemotron direct thinking'}
        rows=[dict(r,arm=keep[r['arm']])for r in rows if r['arm']in keep]
        if domain=='arithmetic':
            solo,sc,sd=ag.load_cohorts([HERE/f'results/solo-control-v2/evaluation-s{s}'for s in (1,2,3)],domain,expected_tasks=24,ledger=read(HERE/'runs/solo-control-v2-ledger.json'));require(sd==dataset,'Different solo dataset');rows += [dict(r,arm='Nemotron sequential refinement')for r in solo];cohorts+=sc
            for s in (1,2,3):
                for name in ('metadata.json','summary.json'):inputs[str(HERE/f'results/solo-control-v2/evaluation-s{s}'/name)]=sha(HERE/f'results/solo-control-v2/evaluation-s{s}'/name)
        else:
            for r in rows:require(r['solved']is(confirmed[r['task_id'],r['original_arm'],r['seed']]['phases']['original_holdout']['status']=='passed'),'Nemo original holdout differs from independent confirmation')
        for r in native:
            if r['domain']==domain:rows.append(dict(r,arm='Native DeepSeek direct 8K',cohort=str(args.input),server_cost_known=False,server_prompt_tokens=None,server_completion_tokens=None))
        require(meta['source_pin']['sha256'][f'datasets/{domain}-v1/tasks.json']==dataset,'Native/Nemo dataset differs')
        d=ag.report_for(rows,cohorts+[dict(directory=str(args.input),source_commit=ADAPTER,provider='native DeepSeek TP4',source=meta['source_pin'],adapter_sha256=meta['adapter_sha256'])],dataset,domain,5000,20261115)
        d['scope']='Separate fixed-suite quality reference: custom abliterated DeepSeek517efa TP4/native effort75/defaulttop_p.95 vs single-replica Nemotron/variousrecipes. Not equal reasoning/compute, not causal headcount/model isolation; task-cluster intervals retain3seeds, pointwise paired contrasts do not assume identical sampling. Empirical all-pass intervals may collapse and do not imply general100% correctness. Native client usage/case wall only; global/server cost unknown, no fleet-throughput/billed-cost claim. Opus unavailable and GLM notrun are missing providers, never zero scores. Coding uses independently confirmed ORIGINAL holdout outcomes, never posthoc robustness substitution.';reports[domain]=d
        for folder in primary:
            for name in ('metadata.json','summary.json'):inputs[str(folder/name)]=sha(folder/name)
    args.output.mkdir(parents=True)
    for domain,d in reports.items():save_report(args.output/domain,d,args.plot)
    evidence=args.output/'evidence';evidence.mkdir()
    for source,name in [(args.input/'metadata.json','metadata.json'),(args.input/'summary.json','summary.json'),(args.audit,'independent-audit.json')]:shutil.copyfile(source,evidence/name)
    inputs.update({str(args.input/n):h for n,h in meta['output_sha256'].items()});inputs.update({str(confirmation/n):sha(confirmation/n)for n in ('metadata.json','summary.json')})
    for p in [HERE/'runs/evaluation-v2-ledger.json',HERE/'runs/solo-control-v2-ledger.json',HERE/'datasets/coding-v1/tasks.json',HERE/'datasets/coding-v1/hidden-tests.json',HERE/'datasets/arithmetic-v1/tasks.json']:inputs[str(p)]=sha(p)
    require(before=={n:sha(HERE/n)for n in source_names}and all(sha(Path(p))==h for p,h in inputs.items()),'Report source/raw inputs changed')
    manifest=dict(input_sha256=inputs,source_sha256=before,command=['python3','report_reference_deepseek.py',*sys.argv[1:]],native_metadata_has_no_verified_flag=True,validated='Full126 and independent audit PASS; original raw outputs/source untouched; no candidate execution',files={str(p.relative_to(args.output)):sha(p)for p in args.output.rglob('*')if p.is_file()});(args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Wrote',args.output);return 0

if __name__=='__main__':raise SystemExit(main())
