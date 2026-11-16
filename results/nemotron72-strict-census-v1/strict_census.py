"""Narrow offline extraction of stated numbered equations; no search or correction."""
import csv,hashlib,importlib.util,json,re
from collections import Counter,defaultdict
from fractions import Fraction
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
FROZEN=ROOT/'.runtime/evaluation-v2-source/harness.py'
FROZEN_SHA='f5607b0a55a45c263f043d92f6ed9dca13b04d9056224e72dfae3c4f6455b0b1'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
text_sha=lambda s:hashlib.sha256(s.encode()).hexdigest()
assert sha(FROZEN)==FROZEN_SHA
spec=importlib.util.spec_from_file_location('frozen_census_verifier',FROZEN)
verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
HEADER=re.compile(r'^[ \t]*(Move|Step)[ \t]+[0-9]+\b',re.I)
NUM=r'[+-]?[0-9]+(?:/[0-9]+)?'
LINE=re.compile(rf'^[ \t]*(Move|Step)[ \t]+([0-9]+)[ \t]*:[ \t]*({NUM})[ \t]*([+*/-])[ \t]*({NUM})[ \t]*=[ \t]*({NUM})[ \t]*$',re.I)

def inspect_block(text,start,end,lines,numbers,target):
    result=dict(start_character=start,end_character=end,text=text[start:end],status='unsupported_format',solved=False,steps=[])
    parsed=[LINE.fullmatch(line.rstrip('\r\n'))for line in lines]
    if not all(parsed):return result
    result['status']='rejected'
    if [int(m[2])for m in parsed]!=list(range(1,len(parsed)+1))or len({m[1].lower()for m in parsed})!=1:
        result['reason']='noncontiguous_or_mixed_numbering';return result
    if len(parsed)>min(5,len(numbers)-1):result['reason']='too_many_steps';return result
    state=tuple(map(Fraction,numbers));first_target=None;offset=start
    for m,line in zip(parsed,lines):
        before=[str(x)for x in state]
        try:
            a,b,c=map(Fraction,[m[3],m[5],m[6]])
            i=next((k for k,x in enumerate(state)if x==a),None)
            j=next((k for k,x in enumerate(state)if x==b and k!=i),None)
            if i is None or j is None:raise ValueError('operand_not_available_with_required_multiplicity')
            action=dict(i=i,j=j,op=m[4]);after=verifier.apply_action(state,action,False)
            if after[-1]!=c:raise ValueError('claimed_equation_is_false')
            result['steps'].append(dict(number=int(m[2]),start_character=offset,end_character=offset+len(line),literal=line,action=action,state_before=before,state_after=[str(x)for x in after]))
            state=after
            if Fraction(target)in state and first_target is None:first_target=offset+len(line)
        except(ValueError,ZeroDivisionError)as exc:
            result.update(reason=str(exc),rejected_step=int(m[2]));return result
        offset+=len(line)
    result.update(status='verified_solution'if first_target is not None else'verified_non_solution',solved=first_target is not None,first_target_equation_end_character=first_target,final_state=[str(x)for x in state])
    return result

def extract(text,numbers,target):
    if not isinstance(text,str):return []
    lines=text.splitlines(keepends=True);blocks=[];i=0;offset=0
    while i<len(lines):
        if not HEADER.match(lines[i]):offset+=len(lines[i]);i+=1;continue
        start=offset;j=i
        while j<len(lines)and HEADER.match(lines[j]):offset+=len(lines[j]);j+=1
        blocks.append(inspect_block(text,start,offset,lines[i:j],numbers,target));i=j
    return blocks

def accepted_content(content,numbers,target):
    state=tuple(map(Fraction,numbers))
    try:
        result=verifier.parse_json_response(content)
        moves=result.get('moves')if set(result)=={'moves'}else None
        if not isinstance(moves,list)or not 1<=len(moves)<=min(5,len(state)-1):return Fraction(target)in state
        for action in moves:
            state=verifier.apply_action(state,action,False)
            if Fraction(target)in state:return True
    except(ValueError,TypeError):pass
    return Fraction(target)in state

def main():
    protocol=json.loads((HERE/'GRAMMAR.json').read_text())
    assert protocol['parser_sha256']==sha(Path(__file__))and protocol['frozen_apply_action_source_sha256']==sha(FROZEN)
    source=ROOT/'results/nemotron72-diagnostic-v1';diagnostic=json.loads((source/'DIAGNOSTIC.json').read_text())
    tasks={t['id']:t for t in json.loads((ROOT/'.runtime/evaluation-v2-source/datasets/arithmetic-v1/tasks.json').read_text())['tasks']}
    perplan=list(csv.DictReader((source/'per-plan.csv').open()));expected={r['request_id']:r for r in perplan if r['request_end_retained']=='True'}
    paths=sorted({ROOT/n for n in diagnostic['input_sha256']if n.endswith('.jsonl')})
    evidence=[];counts=defaultdict(Counter);inputs={};blocks_total=Counter()
    for path in paths:
        assert sha(path)==diagnostic['input_sha256'][str(path.relative_to(ROOT))];inputs[str(path.relative_to(ROOT))]=sha(path)
        starts={}
        for line_number,line in enumerate(path.read_text().splitlines(keepends=True),1):
            event=json.loads(line)
            if event['type']=='request_start':starts[event['request_id']]=(event,line_number,text_sha(line))
            if event['type']!='request_end':continue
            rid=event['request_id'];p=expected[rid];task=tasks[p['task_id']];start,start_line,request_hash=starts[rid]
            baseline=accepted_content(event.get('response'),task['numbers'],task['target']);assert baseline==(p['verified_success']=='True')
            reasoning=event.get('reasoning');blocks=extract(reasoning,task['numbers'],task['target']);solutions=[b for b in blocks if b['solved']]
            outcome='verified_solution'if solutions else'no_verified_supported_block'if blocks else'not_detected'
            record=dict(task_id=p['task_id'],seed=int(p['seed']),method=p['method'],request_id=rid,agent_id=start['agent_id'],plan_revision=start.get('plan_revision'),node_id=start['node_id'],trace=str(path.relative_to(ROOT)),request_start_line=start_line,response_line=line_number,request_sha256=request_hash,request_sha256_scope='Exact retained request_start JSONL UTF-8 bytes including newline; NOT HTTP body, which was not captured',response_record_sha256=text_sha(line),reasoning_sha256=text_sha(reasoning)if isinstance(reasoning,str)else None,reasoning_characters=len(reasoning)if isinstance(reasoning,str)else None,finish_reason=event.get('finish_reason'),case_solved=p['case_status']=='success_early',accepted_content_solved=baseline,strict_census=outcome,first_solution_character_offset=solutions[0]['start_character']if solutions else None,blocks=blocks)
            evidence.append(record)
            for group in [p['method']+'/all',p['method']+'/'+str(event.get('finish_reason')),'all/'+str(event.get('finish_reason'))]:
                c=counts[group];c['responses']+=1;c['baseline_solved']+=baseline;c[outcome]+=1;c['recognized_blocks']+=len(blocks);c['verified_blocks']+=len(solutions)
            blocks_total.update(b['status']for b in blocks)
    assert len(evidence)==len(expected)==449 and counts['all/length']['responses']==292
    assert sha(FROZEN)==FROZEN_SHA
    coverage={}
    for arm in sorted({r['method']for r in evidence}):
        rr=[r for r in evidence if r['method']==arm];base={(r['task_id'],r['seed'])for r in rr if r['case_solved']};found={(r['task_id'],r['seed'])for r in rr if r['strict_census']=='verified_solution'}
        coverage[arm]=dict(original_case_successes=len(base),strict_solution_cases=len(found),already_seen_posthoc_additional_cases=len(found-base),original_failed_truncated_responses=sum(r['finish_reason']=='length'and not r['case_solved']for r in rr),original_failed_truncated_with_strict_solution=sum(r['finish_reason']=='length'and not r['case_solved']and r['strict_census']=='verified_solution'for r in rr))
    report=dict(scope='Already-seen strict mechanical census; no model call, graph search, equation correction or original score change',grammar=protocol,retained_responses=len(evidence),baseline_agreement=449,counts={k:dict(v)for k,v in counts.items()},block_counts=dict(blocks_total),case_coverage=coverage,input_sha256=inputs,diagnostic_sha256=sha(source/'DIAGNOSTIC.json'),perplan_sha256=sha(source/'per-plan.csv'),recommendation_sha256=sha(ROOT/'.runtime/fable52-review-fullrepo-20261116/RECOMMENDATIONS.md'),limitations=['Unsupported/notdetected does not mean no solution in reasoning. Only standalone contiguous numbered Move/Step colon-equation lines are recognized.','Every equation in a block must validate; later invalid equations reject the whole block even if an earlier prefix reached target.','Offsets are zero-based Python string characters, never token offsets. No unobserved/censored responses can be recovered.','Request digest binds retained request_start metadata, not uncaptured HTTP request body.','Extracted evaluation solutions are audit evidence only and must not be copied into future Nemotron prompts.'])
    for name,value in [('CENSUS.json',report),('BLOCK_EVIDENCE.json',evidence)]:
        with(HERE/name).open('x')as f:json.dump(value,f,indent=2);f.write('\n')
    print(json.dumps(dict(counts=report['counts'],blocks=report['block_counts'],case_coverage=coverage),indent=2))
if __name__=='__main__':main()
