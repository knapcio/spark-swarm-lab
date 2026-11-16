#!/usr/bin/env python3
"""POSTHOC completed-trace replay only; no program/model/SSH execution or timing estimates."""
import csv, hashlib, io, json
from pathlib import Path
from csp_tasks import verify_assignment
from program_search import penalty, compact_feedback
from run_program_confirmation import validate_report

ROOT=Path.cwd();OUT=Path(__file__).resolve().parent;MASTER=ROOT/'runs/program-search-v1'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text())
def require(value,message):
    if not value:raise ValueError(message)

def replay():
    require(not any((OUT/n).exists()for n in ('summary.csv','audit.json','NOTES.md')),'Refuse overwrite')
    meta=read(MASTER/'metadata.json');episodes=read(MASTER/'results.json');tasks=read(MASTER/'development-inputs.json')
    require(meta.get('complete')is True and meta.get('verified')is True and not meta.get('faults')and meta['source']==meta['source_after'],'Incomplete/changed original master')
    require(len(episodes)==8 and {(e['arm'],e['seed'])for e in episodes}=={(a,s)for a in ('independent4','sequential16')for s in range(1,5)},'Episode grid')
    require(sha(ROOT/'program_search.py')==meta['source']['sha256']['program_search.py'],'Batch policy source differs')
    inputs={str(p.relative_to(ROOT)):sha(p)for p in [MASTER/'metadata.json',MASTER/'results.json',MASTER/'development-inputs.json']};rows=[]
    for episode in sorted(episodes,key=lambda e:(e['arm'],e['seed'])):
        arm,seed=episode['arm'],episode['seed'];width=1 if arm=='sequential16'else 4;folder=MASTER/f'seed-{seed}-{arm}'
        for name in ('events.jsonl','selection.json','selected.py'):inputs[str((folder/name).relative_to(ROOT))]=sha(folder/name)
        events=[json.loads(line)for line in(folder/'events.jsonl').read_text().splitlines()if line.strip()]
        require(all(a['event_id']<b['event_id']for a,b in zip(events,events[1:])),'Event order')
        pick=lambda kind:[e for e in events if e['type']==kind]
        starts,ends=pick('request_start'),pick('request_end');candidates={e['index']:e for e in pick('program_candidate')};scores={e['candidate_index']:e for e in pick('development_candidate_scored')}
        require(len(starts)==len(ends)==len(candidates)==len(scores)==16 and set(candidates)==set(scores)==set(range(16)),'Full sixteen proposals required')
        require({e['request_id']for e in starts}=={e['request_id']for e in ends}and len({e['request_id']for e in starts})==16,'Request IDs')
        for end in ends:
            start=next(s for s in starts if s['request_id']==end['request_id'])
            require(all(start[k]==end[k]for k in ('candidate_index','stage','chain'))and start['event_id']<end['event_id']and end.get('error')is None,'Bound complete response required')
            usage=end['usage'];require(usage.get('estimated')is False and all(type(usage.get(k))is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens')),'Observed client usage required')
        grades=[e for e in events if e['type']in ('program_grade_end','program_grade_skipped')and e['phase']=='development']
        for index in range(16):
            candidate=candidates[index];scored=scores[index];bound=[e for e in grades if e['candidate_index']==index]
            require(len(bound)==4 and {e['task_id']for e in bound}=={t['id']for t in tasks}and all(candidate['event_id']<e['event_id']<scored['event_id']for e in bound),'Four complete dev grades before score required')
            require(hashlib.sha256(candidate['code'].encode()).hexdigest()==candidate['code_sha256'],'Candidate source identity')
            reports=[]
            for task in tasks:
                grade=next(e for e in bound if e['task_id']==task['id']);require(grade['code_sha256']==candidate['code_sha256'],'Grade source binding')
                if grade['type']=='program_grade_skipped':
                    require(candidate['parse_error']and grade['reason']=='candidate_parse','Unexpected skipped grade');report=dict(status='error',solved=False,proof=None,failure_kind='candidate_parse',error=candidate['parse_error'],grading_performed=False)
                else:
                    report=grade['report'];validate_report(task,report)
                    began=[e for e in pick('program_grade_start')if e['phase']=='development'and e['candidate_index']==index and e['task_id']==task['id']]
                    require(len(began)==1 and candidate['event_id']<began[0]['event_id']<grade['event_id'],'CPU grade start/end barrier')
                reports.append(report)
            require(scored['solved']==sum(r['solved']for r in reports)and scored['penalty']==sum(penalty(t,r)for t,r in zip(tasks,reports))and scored['feedback']==[compact_feedback(t,r)for t,r in zip(tasks,reports)],'Dev score/feedback not bound to grades')
        cutoff=16;previous=0
        for offset in range(0,16,width):
            indices=set(range(offset,offset+width));ss=[e for e in starts if e['candidate_index']in indices];ee=[e for e in ends if e['candidate_index']in indices]
            require(len(ss)==len(ee)==width and min(e['event_id']for e in ss)>previous and max(e['event_id']for e in ee)<min(candidates[i]['event_id']for i in indices),'Batch response/previous score barrier')
            previous=max(scores[i]['event_id']for i in indices)
            require(all(e['event_id']>previous for e in starts if e['candidate_index']>=offset+width),'Already-dispatched next batch')
            if cutoff==16 and any(scores[i]['solved']==4 for i in indices):cutoff=offset+width
        chosen=min(range(cutoff),key=lambda i:(-scores[i]['solved'],scores[i]['penalty'],i));actual=read(folder/'selection.json')
        require(candidates[chosen]['code_sha256']==actual['code_sha256']==sha(folder/'selected.py')==episode['selected_sha256'],'BLOCKED: early-stop source differs')
        prefix=[e for e in ends if e['candidate_index']<cutoff];retained=[e for e in grades if e['candidate_index']<cutoff]
        rows.append(dict(arm=arm,seed=seed,observed_model_calls=16,counterfactual_retained_calls=cutoff,counterfactual_calls_not_dispatched=16-cutoff,selected_candidate=chosen,actual_selected_candidate=actual['candidate_index'],same_selected_source=True,selected_sha256=actual['code_sha256'],observed_prefix_client_prompt_tokens=sum(e['usage']['prompt_tokens']for e in prefix),observed_prefix_client_completion_tokens=sum(e['usage']['completion_tokens']for e in prefix),observed_prefix_cpu_dev_grades=sum(e['type']=='program_grade_end'for e in retained),observed_prefix_parse_skips=sum(e['type']=='program_grade_skipped'for e in retained),observed_all_cpu_dev_grades=sum(e['type']=='program_grade_end'for e in grades)))
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows);(OUT/'summary.csv').write_text(stream.getvalue())
    notes=['# Posthoc early-stop trace replay','', 'This counterfactual was specified after seeing original and fresh-confirmation outcomes. It was not executed as an early-stop run and is not new independent quality evidence. Sequential stops after a fully scored proposal; independent4 stops only after all four model responses and all sixteen development assessments in the batch complete. No already-dispatched sibling is counted as saved. If no 4/4 development success occurs, all sixteen calls and the actual best source are retained.','', '| Arm | Seed | Calls retained | Calls prospectively not dispatched | Same frozen source | Observed prefix client input / output | Actual prefix CPU development grades |','|---|---:|---:|---:|---|---:|---:|']
    for r in rows:notes.append(f"| {r['arm']} | {r['seed']} | {r['counterfactual_retained_calls']} | {r['counterfactual_calls_not_dispatched']} | yes | {r['observed_prefix_client_prompt_tokens']} / {r['observed_prefix_client_completion_tokens']} | {r['observed_prefix_cpu_dev_grades']} |")
    notes+=['',f"All eight frozen selected-source SHA values are identical. Across the original128 model calls, this rule retains {sum(r['counterfactual_retained_calls']for r in rows)} and prospectively avoids dispatching {sum(r['counterfactual_calls_not_dispatched']for r in rows)}. Existing fresh96 outcomes apply to these same source bytes, not to a newly sampled training run. A shared seed does not guarantee a new run reproduces the observed trajectory.", '', 'Prefix client tokens are measurements from the already executed full traces, not prospective server-token savings. CPU counts include only actual development grader calls, excluding parse skips; the unchanged evaluation grades are separate. No server-token savings, GPU-time savings, latency, billed cost or new-run quality is estimated. Observed all-development CPU grade counts are retained in the CSV.','']
    (OUT/'NOTES.md').write_text('\n'.join(notes));audit=dict(verified=True,posthoc=True,episodes=8,observed_model_calls=128,early_stop_episodes=sum(r['counterfactual_retained_calls']<16 for r in rows),counterfactual_retained_calls=sum(r['counterfactual_retained_calls']for r in rows),counterfactual_calls_not_dispatched=sum(r['counterfactual_calls_not_dispatched']for r in rows),all_selected_sources_identical=True,input_sha256=inputs,source_sha256=sha(__file__),output_sha256={name:sha(OUT/name)for name in ('summary.csv','NOTES.md')},inference_executed=False,programs_executed=False,raw_inputs_modified=False)
    require(all(sha(ROOT/name)==h for name,h in inputs.items()),'Raw input changed');(OUT/'audit.json').write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps({k:v for k,v in audit.items()if k not in ('input_sha256','output_sha256')}))

if __name__=='__main__':replay()
