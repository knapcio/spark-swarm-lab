"""Independent offline follow-up audit. Never calls serving endpoints or executes proposals."""
import argparse,hashlib,json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
SOURCE=ROOT/'.runtime/nemotron72-followup-source';RUN=ROOT/'runs/nemotron72-development-v1'
REV='638b9f335a7aa7011a9b7d122abcaa04f45e17a5'
SYSTEM='Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.'
COMMIT='\n\nWrite the requested complete JSON plan now. Do not explain or start over. Return only the JSON object, without commentary.'
NOTES='\nYour own unfinished notes from the immediately preceding request (unverified):\n'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
textsha=lambda t:hashlib.sha256(t.encode()).hexdigest()
read=lambda p:json.loads(p.read_text())
def need(condition,message):
    if not condition:raise ValueError(message)
def canonical(state):return [str(Fraction(x))for x in state]
def parse(content):
    if not isinstance(content,str):return None
    text=content.strip()
    if text.startswith('```'):
        lines=text.splitlines()
        if lines[-1].strip()!='```':return None
        text='\n'.join(lines[1:-1])
    try:value=json.loads(text)
    except ValueError:return None
    return value if isinstance(value,dict)else None

def action(state,move,value_mode=False):
    need(isinstance(move,dict),'action not object')
    if value_mode:
        need(set(move)=={'a','b','op'}and type(move['a'])is int and type(move['b'])is int,'value schema')
        i=next((i for i,x in enumerate(state)if x==move['a']),None)
        j=next((j for j,x in enumerate(state)if j!=i and x==move['b']),None)
        need(i is not None and j is not None,'unavailable value occurrence');compiled=dict(i=i,j=j,op=move['op'])
    else:compiled=move
    need(set(compiled)=={'i','j','op'},'index schema');i,j,op=compiled['i'],compiled['j'],compiled['op']
    need(type(i)is int and type(j)is int and i!=j and 0<=i<len(state)and 0<=j<len(state),'invalid indices')
    need(op in ('+','-','*','/'),'operator');a,b=Fraction(state[i]),Fraction(state[j]);need(op!='/'or b!=0,'division by zero')
    result=a+b if op=='+'else a-b if op=='-'else a*b if op=='*'else a/b
    need(result>0 and result.denominator==1,'nonpositive or fractional result')
    return tuple(x for k,x in enumerate(state)if k not in(i,j))+(result,),compiled

def prompt(task,arm):
    values=arm.startswith('value_');state=canonical(task['numbers']);target=task['target'];maximum=min(5,len(state)-1)
    head=f'Current numbers: {state}.'if values else f'Current indexed numbers: {dict(enumerate(state))}.'
    addressing=('Each move consumes two different available occurrences of the stated values and appends their result; remaining numbers keep their order.'if values else 'Each move consumes two different indexed numbers and appends their result; remaining numbers keep their order and are reindexed from zero.')
    schema='integer operand values a,b'if values else'integer indices i,j'
    result=f'Target {target}. {head} Give one complete plan to reach the target using any subset of numbers. {addressing} Use +,-,*,/. Every intermediate result must be positive integer. Use at most {maximum} moves. Return only a JSON object with key moves, an array of objects with {schema} and single-character operator op.'
    if arm in ('index_explicit','value_explicit'):
        operands='a op b'if values else'the value at i op the value at j'
        result+=f' Leftover numbers are allowed. Stop as soon as the target appears anywhere among the remaining numbers; it need not be the only remaining number. Compute {operands} literally in that order; do not swap operands.'
    return result

def body(seed,stage,text,cap,thinking):
    derived=int.from_bytes(hashlib.sha256(f'{seed}:0:{stage}:{text}'.encode()).digest()[:4],'big')
    return dict(model='nemotron-lightning',messages=[dict(role='system',content=SYSTEM),dict(role='user',content=text)],max_tokens=cap,temperature=.8,seed=derived,stream=False,chat_template_kwargs=dict(enable_thinking=thinking))

def check_case(case,row,task):
    trace=Path(case['events']);events=[json.loads(line)for line in trace.read_text().splitlines()]
    need(events and [e['event_id']for e in events]==list(range(1,len(events)+1)),'event ID order')
    puzzle_id='p0-'+textsha(json.dumps([sorted(canonical(task['numbers'])),task['target']]))[:10]
    need(all(e.get('puzzle_id',puzzle_id)==puzzle_id for e in events),'puzzle identity')
    configs=[e['config']for e in events if e['type']=='run_start'];need(len(configs)==1,'run-start cardinality')
    need(configs[0]['variant']==case['arm']and configs[0]['seed']==case['seed']and configs[0]['target']==task['target']and configs[0]['endpoint']==case['endpoint'],'worker config identity')
    need(len({e['run_id']for e in events})==1,'run identity');need(all(e['method']==case['arm']for e in events),'arm identity')
    starts=[e for e in events if e['type']=='request_start'];ends=[e for e in events if e['type']=='request_end'];byend={e['request_id']:e for e in ends}
    need(len(byend)==len(ends)and len({s['request_id']for s in starts})==len(starts),'duplicate request identity')
    need(1<=len(starts)<=2 and set(byend)<={s['request_id']for s in starts},'request lifecycle')
    need(row['calls']==len(starts)and row['completed_calls']==len(ends)and row['unfinished_calls']==len(starts)-len(ends),'summary request counts')
    need(not row['controller_error']and row['malformed_lines']==0 and not row['infrastructure_failures'],'controller/transport fault')
    need((not row['deadline'])or row['controller_stop'],'deadline without controller stop')
    need(row['deadline']or(len(starts)==len(ends)and row['status']in('complete','budget_limited')and row['returncode']==0),'non-deadline incomplete case')
    arm=case['arm'];scribe=arm.startswith('scribe_');first=starts[0];firstend=byend.get(first['request_id']);parsed=parse(firstend.get('response'))if firstend else None
    reasoning=firstend.get('reasoning')if firstend else None
    eligible=bool(scribe and parsed is None and firstend and firstend.get('response_received')is True and firstend.get('finish_reason')=='length'and isinstance(reasoning,str)and reasoning.strip())
    skip_reason=(None if eligible else 'not_scribe_variant'if not scribe else 'parsed_result_non_none'if parsed is not None else 'response_not_received'if not firstend or firstend.get('response_received')is not True else 'finish_reason_not_length'if firstend.get('finish_reason')!='length'else 'reasoning_empty_or_missing')
    mode=arm.removeprefix('scribe_');notes=reasoning if eligible and mode=='full'else reasoning[-4096:]if eligible and mode=='tail'else''
    lineage=dict(parent_request_id=first['request_id'],full_reasoning_sha256=textsha(reasoning),selected_notes_sha256=textsha(notes),note_char_length=len(notes),notes_mode=mode)if eligible else{}
    base=prompt(task,arm);missing_usage=Counter();tokens=Counter();charged=0
    for index,start in enumerate(starts):
        need(start['agent_id']==0 and start['endpoint_index']==0 and start['variant']==arm,'request owner')
        stage='plan'if index==0 else'scribe';cap=(7936 if scribe else 8192)if index==0 else 256;thinking=index==0
        text=base if index==0 else base+COMMIT+(NOTES+notes if notes else'')
        need(start['stage']==stage and start['followup_phase']==('draft'if index==0 else'commit'),'request phase')
        if index:
            need(eligible and firstend['event_id']<start['event_id'],'ineligible or premature scribe')
            need(all(start.get(k)==v for k,v in lineage.items()),'commit notes lineage')
        expected=body(case['seed'],stage,text,cap,thinking)
        need(start['request_body']==expected and start['request_body_sha256']==textsha(json.dumps(expected)),'wire body/template/seed/SHA')
        need(start['request_max_tokens']==cap and start['request_thinking']is thinking,'cap/thinking telemetry')
        end=byend.get(start['request_id'])
        if not end:continue
        need(end['event_id']>start['event_id']and end['request_body_sha256']==start['request_body_sha256'],'response precedes dispatch/body drift')
        need(end.get('response_received')is True or(end.get('cancelled')and row['deadline']),'observed response/transport failure')
        if end.get('response_received'):need(end.get('response_model')=='nemotron-lightning','response model alias')
        usage=end['usage'];raw=end.get('raw_usage')or{}
        need(isinstance(raw,dict),'raw usage schema')
        for name in ('prompt_tokens','completion_tokens','total_tokens'):
            value=raw.get(name);accepted=type(value)is int and value>=0
            need((usage.get(name)==value)if accepted else name not in usage,'raw/normalized usage mismatch')
            if name!='total_tokens':
                if accepted:tokens[name]+=value
                else:missing_usage[name]+=1
        completion=usage.get('completion_tokens')
        need(completion is None or completion<=cap,'POSITIVE_PROTOCOL_VIOLATION: reported completion exceeds requested cap')
        need(end['completion_tokens_charged']==(cap if completion is None else completion),'completion settlement')
        charged+=end['completion_tokens_charged']
        if all(k in usage for k in ('prompt_tokens','completion_tokens','total_tokens')):need(usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens'],'usage total mismatch')
        need(usage['estimated']is(completion is None),'usage unknown marker')
    commits=[e for e in events if e['type']=='scribe_commit'];need(len(commits)<=1,'multiple commits')
    for commit in commits:need(eligible and all(commit.get(k)==v for k,v in lineage.items()),'scribe event lineage')
    if len(starts)==2:need(len(commits)==1,'missing scribe commitment event')
    if eligible and not row['deadline']:need(len(starts)==2 or any(e['type']=='budget_exhausted'for e in events),'eligible commit silently omitted')
    need(sum(s['request_max_tokens']for s in starts)<=8192,'aggregate requested cap exceeded')
    for key in ('prompt_tokens','completion_tokens'):need(row[key]==tokens[key],'client token sum')
    need(row['charged_completion_tokens']==charged and row['missing_prompt_usage']==missing_usage['prompt_tokens']and row['missing_completion_usage']==missing_usage['completion_tokens'],'client charge/unknown count')
    nodes={};rootnodes=[];reachable={};state=tuple(map(Fraction,task['numbers']));target=Fraction(task['target']);lastnode=None
    proposals=[e for e in events if e['type']=='proposal'];finalend=byend.get(starts[-1]['request_id']);plan=parse(finalend.get('response'))if finalend else None
    moves=plan.get('moves')if isinstance(plan,dict)and set(plan)=={'moves'}else None
    bounded=isinstance(moves,list)and 1<=len(moves)<=min(5,len(state)-1)
    need(not proposals or bounded,'proposal from invalid plan schema')
    expected_steps=[];working=state
    if bounded:
        for move in moves:
            try:child,compiled=action(working,move,arm.startswith('value_'));legal=True
            except(ValueError,TypeError):child,compiled,legal=None,None,False
            expected_steps.append((move,compiled,child,legal))
            if not legal:break
            working=child
            if target in working:break
    need(len(proposals)<=len(expected_steps),'extra/reordered proposal steps')
    for index,proposal in enumerate(proposals):
        move,compiled,child,legal=expected_steps[index];need(proposal['legal']is legal,'proposal legality falsehood')
        need(proposal.get('model_action',proposal['action'])==move,'proposal detached from sampled plan')
        if legal:need(proposal['action']==compiled and proposal['child_state']==canonical(child),'compiler or result drift')
    for event in events:
        kind=event['type']
        if kind=='node':
            need(event['node_id']not in nodes,'duplicate node');nodes[event['node_id']]=event
            if event['parent_id']is None:
                need(event['state']==canonical(state)and event['depth']==0,'root state identity');rootnodes.append(event['node_id']);reachable[event['node_id']]=state
        elif kind=='proposal'and event['legal']:
            need(event['node_id']in reachable,'proposal lacks root ancestry');parent=reachable[event['node_id']]
            child,_=action(parent,event['action']);need(event['child_node_id']in nodes,'child node not recorded')
            node=nodes[event['child_node_id']];need(node['parent_id']==event['node_id']and node['state']==canonical(child),'child ancestry/state')
            reachable[event['child_node_id']]=child
        elif kind=='chosen':need(event['node_id']in reachable,'chosen unverified node')
        elif kind=='reward':need(event['node_id']in reachable and event['solved']is(target in reachable[event['node_id']])and event['reward']==int(event['solved']),'reward lacks exact root proof')
    need(len(rootnodes)==1,'root multiplicity')
    rewards=[e for e in events if e['type']=='reward'];need(len(rewards)<=1,'multiple rewards');proof=any(e['solved']for e in rewards)
    need(not row['solved']or proof,'summary false success');need(row['deadline']or row['solved']==proof,'summary/reward disagreement')
    for end in [e for e in events if e['type']=='puzzle_end']:
        need(end['plan']==plan and end['first_parsed_result']==parsed and end['scribe_triggered']is eligible and end['scribe_skip_reason']==skip_reason,'final plan/eligibility telemetry')
        need(end['first_request_id']==first['request_id']and end['first_finish_reason']==firstend.get('finish_reason')and end['first_response_received']==firstend.get('response_received'),'first request telemetry')
        need(end['commit_request_id']==(starts[1]['request_id']if len(starts)==2 else None),'commit request telemetry')
        need(end['solved']==proof and end['node_id']in reachable and end['final_state']==canonical(reachable[end['node_id']]),'final state/proof')
        need(end['commit_dispatched']is(len(starts)==2),'commit dispatch marker')
        if eligible:need(all(end.get(k)==v for k,v in lineage.items()),'final notes lineage')
    run_ends=[e for e in events if e['type']=='run_end'];need(len(run_ends)<=1 and(row['deadline']or len(run_ends)==1),'run-end cardinality')
    for end in run_ends:
        need(end['solved']==int(proof)and end['puzzles']==1,'run-end proof count')
        budget=end['budget'];need(budget['calls']==len(starts)and budget['completion_tokens_charged']==charged and budget['completion_tokens_reserved']==0 and budget['max_calls']==2 and budget['max_completion_tokens']==8192,'final budget accounting')
    before,after=row['server_metrics_before'],row['server_metrics_after']
    need(row['server_idle_after']is True and row['server_cost_known']is True,'drain/counter unknown')
    need(before and after and not before.get('error')and not after.get('error'),'metrics unavailable')
    need(all(m.get('running')==m.get('waiting')==0 for m in(before,after)),'endpoint not idle at accounting boundaries')
    for key in('prompt','completion'):
        delta=after[key]-before[key];need(delta>=tokens[key+'_tokens']and row['server_'+key+'_tokens']==int(delta),'server counter delta')
    return dict(task_id=case['task_id'],variant=arm,seed=case['seed'],block=case.get('block',0),position=case.get('position',0),calls=len(starts),completed_calls=len(ends),unfinished_calls=len(starts)-len(ends),client_usage_complete=len(starts)==len(ends)and not any(missing_usage.values()),deadline=row['deadline'],solved=bool(row['solved']),strict_observed_proof=proof,eligible=eligible,commit_dispatched=len(starts)==2,legal_steps=sum(p['legal']for p in proposals),trace_sha256=sha(trace),before=before['timestamp_utc'],after=after['timestamp_utc'],endpoint=case['endpoint'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',action='store_true');p.add_argument('--final',action='store_true');p.add_argument('--launch',type=Path);args=p.parse_args()
    if not args.audit:print(json.dumps(dict(mode='plan',model_calls=0,requires='Existing root launch receipt; completed-case records only')));return
    need(args.launch and args.launch.is_file(),'Launch receipt required before live audit')
    frozen=read(ROOT/'.runtime/NEMOTRON72_FROZEN_SOURCE_V1.json');planpath=ROOT/'.runtime/nemotron72-development-frozen-plan-v1.json';plan=read(planpath);metadata=read(RUN/'metadata.json');rows=read(RUN/'summary.json')if(RUN/'summary.json').exists()else[]
    launch=read(args.launch)
    need(launch['source_revision']==REV and launch['quality_attempts_planned']==168 and Path(launch['output'])==RUN,'launch identity')
    for name in('frozen_source_receipt','frozen_plan','runtime_admission','precall_audit'):
        need(sha(Path(launch[name]))==launch[name+'_sha256'],'launch binding '+name)
    admissionpath=Path(launch['runtime_admission']);admission=read(admissionpath)
    need(admission['verified']is True and admission['runtime_identical_to_study_v032']is True,'runtime admission rejected')
    need(metadata['admission']==admission and metadata['admission_sha256']==sha(admissionpath),'metadata admission binding')
    age=(datetime.fromisoformat(metadata['started_utc'])-datetime.fromisoformat(admission['verified_utc'])).total_seconds()
    need(0<=age<=900,'admission stale at launch')
    need(admission['source_sha256']==frozen['source_sha256']and admission['test_sha256']==frozen['test_sha256'],'admission source/test drift')
    need(metadata['protocol']==plan['protocol']and plan['protocol']['status']=='FROZEN','protocol drift')
    for name in('qualification_receipt','constant_smoke_receipt'):
        digestname='qualification_sha256'if name=='qualification_receipt'else'constant_smoke_sha256'
        need(sha(Path(admission[name]))==admission[digestname],'qualification receipt binding')
        need(read(Path(admission[name]))['verified']is True,'qualification not verified')
    qualification=read(Path(admission['constant_smoke_receipt']))
    need(qualification['model_calls']==qualification['all_passed']==8,'constant qualification count')
    need(sha(Path(qualification['raw_requests_responses_file']))==qualification['raw_requests_responses_sha256'],'qualification raw binding')
    need(frozen['revision']==REV==metadata['source_revision']==plan['source_revision'],'revision identity')
    for name,digest in {**frozen['source_sha256'],**frozen['test_sha256']}.items():need(sha(SOURCE/name)==digest,'source drift '+name)
    need(metadata['source_sha256']==plan['source_sha256']==frozen['source_sha256'],'source binding')
    need(metadata['cases']==plan['cases']and len(plan['cases'])==168,'case plan drift')
    cases={c['events']:c for c in plan['cases']};need(len(cases)==168 and len({(c['task_id'],c['arm'],c['seed'])for c in cases.values()})==168,'matrix uniqueness')
    tasks={t['id']:t for t in read(SOURCE/'datasets/arithmetic-v1/tasks.json')['tasks']if t['split']=='development'}
    need(len(tasks)==8 and {c['task_id']for c in cases.values()}==set(tasks),'development split identity')
    need(len({r['events']for r in rows})==len(rows),'duplicate summary case');proofs=[];faults=[]
    for row in rows:
        try:
            need(row['events']in cases,'unknown case');case=cases[row['events']]
            need(all(row[k]==case[k]for k in('task_id','split','arm','seed','endpoint')),'case identity')
            proofs.append(check_case(case,row,tasks[case['task_id']]))
        except Exception as exc:faults.append(dict(events=row.get('events'),error=f'{type(exc).__name__}: {exc}'))
    for endpoint in {x['endpoint']for x in proofs}:
        ordered=sorted((x for x in proofs if x['endpoint']==endpoint),key=lambda x:x['before'])
        need(all(a['after']<=b['before']for a,b in zip(ordered,ordered[1:])),'overlapping endpoint cases')
    for block in {x['block']for x in proofs}:
        if block:
            for previous in range(block):
                prior=[x for x in proofs if x['block']==previous];current=[x for x in proofs if x['block']==block]
                need(len(prior)==7,'next block before previous complete audited block')
                need(max(x['after']for x in prior)<=min(x['before']for x in current),'global block accounting overlap')
    if args.final:
        need(len(rows)==metadata['completed_cases']==168 and metadata['incomplete']is False and not metadata['errors']and metadata['source_changed_during_run']is False,'incomplete/faulted final cohort')
        need(metadata['final_source_sha256']==frozen['source_sha256'],'final source mismatch')
        for name,digest in metadata['output_sha256'].items():need(sha(RUN/name)==digest,'final raw hash mismatch '+name)
    result=dict(verified=not faults,complete=args.final and len(rows)==168,completed_cases=len(rows),faults=faults,source_revision=REV,source_sha256=frozen['source_sha256'],input_sha256={str(path.relative_to(ROOT))if path.is_relative_to(ROOT)else str(path):sha(path)for path in[args.launch,planpath,ROOT/'.runtime/NEMOTRON72_FROZEN_SOURCE_V1.json',admissionpath,Path(admission['qualification_receipt']),Path(admission['constant_smoke_receipt']),Path(qualification['raw_requests_responses_file']),RUN/'metadata.json']+([RUN/'summary.json']if rows else[])},case_checks=proofs,scope='Independent body/lineage/Fraction replay and cost audit; known development recipe selection, no new heldout claim; no runtime advice.')
    name='FINAL_AUDIT.json'if args.final else'SNAPSHOT_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.json'
    with(HERE/name).open('x')as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps(dict(audit=name,verified=result['verified'],complete=result['complete'],completed_cases=len(rows),faults=faults)))
if __name__=='__main__':main()
