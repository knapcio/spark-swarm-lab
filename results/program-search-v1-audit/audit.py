"""Read-only completed-program audit; never execute a generated program."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import csv, hashlib, json, math, subprocess, sys, time

ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import program_search as protocol
from csp_tasks import canonical_json, graph_digest, verify_assignment, worker_task

OUT=Path(__file__).resolve().parent
RAW=ROOT/'runs/program-search-v1'
REV='c5ed1190ac380cf1ed1193b0bd7971dcc0eb1bae'
inputs={};counts=Counter();candidate_rows=[];grade_rows=[];episode_rows=[];intervals={}
sha=lambda b:hashlib.sha256(b).hexdigest()
def data(path):
    raw=Path(path).read_bytes();inputs[str(Path(path).resolve().relative_to(ROOT))]=sha(raw);return raw
def read(path):return json.loads(data(path))
def same(a,b):return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8)
def record_csv(name,rows):
    with(OUT/name).open('w',newline='')as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def proof_check(task,report,code):
    assert report.get('cleanup_ok')is True and report.get('provenance')=='candidate'
    assert report.get('grading_authority')=='outer_parent'and report.get('oracle_sent_to_child')is False
    assert not str(report.get('failure_kind')).endswith('_infrastructure')
    assert report.get('graph_sha256')==graph_digest(task)
    payload=json.dumps(dict(code=code,function_name='solve',calls=[dict(args=[task['vertex_count'],task['color_count'],task['edges']],kwargs={})],timeout=10),allow_nan=False)
    assert sha(payload.encode())==report['child_payload_sha256'];counts['payload_hashes_verified']+=1
    proof=report.get('proof')
    if proof is not None:
        value=report['candidate_output'];assert verify_assignment(task,value)==proof
        # Independent schema and edge checks corroborate the pinned verifier.
        valid=(type(value)is dict and set(value)=={'assignment'}and type(value['assignment'])is list
            and len(value['assignment'])==task['vertex_count']and all(type(x)is int and 0<=x<task['color_count']for x in value['assignment']))
        assert proof['valid_schema']is valid
        if valid:
            bad=[i for i,(a,b)in enumerate(task['edges'])if value['assignment'][a]==value['assignment'][b]]
            assert proof['conflicts']==len(bad)and proof['violating_edges']==bad and proof['solved']is(not bad)
        else:assert proof['solved']is False and proof['conflicts']is None
        counts['exact_proofs_replayed']+=1
    assert type(report.get('solved'))is bool and report['status']in('passed','failed','error','timeout')
    assert (report['status']=='passed')is report['solved']
    if report['solved']:assert proof and proof['solved']is True and report.get('input_unchanged')is True

def feedback(task,report):
    proof=report.get('proof')or{}
    return dict(task_id=task['id'],solved=report.get('solved')is True,conflicts=proof.get('conflicts'),
        valid_assignment=proof.get('valid_schema')is True,conflicting_edge_indices=proof.get('violating_edges',[])[:16],
        status=report.get('status'),failure_kind=report.get('failure_kind'),error=str(report.get('error')or proof.get('error')or'')[:300])
def penalty(task,report):
    if report.get('solved')is True:return 0
    proof=report.get('proof')or{}
    if proof.get('valid_schema')is True and type(proof.get('conflicts'))is int and report.get('input_unchanged')is True and report.get('status')=='failed':return proof['conflicts']
    return len(task['edges'])+1

def audit():
    began=time.monotonic();meta=read(RAW/'metadata.json');rows=read(RAW/'results.json')
    assert meta['verified']is True and meta['complete']is True and not meta['faults']
    assert meta['source']==meta['source_after']and meta['source']['revision']==REV
    assert meta['source']['tracked_clean']is True and meta['source']['source_files_tracked']is True
    assert meta['recorded_episodes']==meta['completed_programs']==len(rows)==8
    assert meta['limits']==dict(max_model_calls=16,per_call_max_tokens=2048,max_completion_tokens=32768,
        request_timeout_seconds=210,graph_timeout_seconds=10,memory_limit_mib=256,cpu_limit_per_container=1,episode_deadline_seconds=None)
    launch=read(ROOT/'.runtime/PROGRAM_SEARCH_LAUNCH.json');freeze=read(ROOT/'.runtime/PROGRAM_FROZEN_SOURCE.json')
    assert launch['source_revision']==REV==freeze['revision']and launch['source_freeze_sha256']==inputs['.runtime/PROGRAM_FROZEN_SOURCE.json']
    assert launch['gate']==meta['gate']==protocol.followup_gate(ROOT)and launch['no_owned_graders_before_launch']is True
    fleet_path=ROOT/'.runtime/program-search-admission-v1/fleet-before-program.json';fleet=read(fleet_path)
    assert inputs[str(fleet_path.relative_to(ROOT))]==launch['fleet_receipt_sha256']and fleet['complete']is True and len(fleet['rows'])==4
    assert {r['host']for r in fleet['rows']}=={f'Spark_{s:02d}'for s in(1,2,3,4)}
    for row in fleet['rows']:
        container=row['container'];assert row['verified']is True and row['idle']is True and str(row['health'])=='200'
        assert container['owner']=='swarm-lab-20261115'and container['running']is True and container['oom']is False and container['restart_count']==0
        assert container['image']=='vllm/vllm-openai@'+meta['runtime']['arm64_manifest_digest']and container['speculation']=='dspark'
        age=(datetime.fromisoformat(launch['started_utc'])-datetime.fromisoformat(row['checked_utc'])).total_seconds();assert -60<=age<=900
    source=Path(freeze['source_worktree'])
    for name,expected in meta['source']['sha256'].items():
        assert sha((source/name).read_bytes())==expected
        blob=subprocess.check_output(['git','-C',str(ROOT),'show',REV+':'+name]);assert sha(blob)==expected
    assert sha(data(ROOT/'program_search.py'))==meta['source']['sha256']['program_search.py']
    selection=read(source/'PROGRAM_SEARCH_SELECTION.json');assert meta['selection_sha256']==sha((source/'PROGRAM_SEARCH_SELECTION.json').read_bytes())
    public=read(source/'datasets/csp-v1/tasks.json');assert meta['dataset_sha256']==sha((source/'datasets/csp-v1/tasks.json').read_bytes())
    development=[worker_task(t)for t in public['tasks']if t['split']=='development']
    evaluation=[worker_task(t)for t in public['tasks']if t['split']=='evaluation']
    assert len(development)==4 and len(evaluation)==12
    assert read(RAW/'development-inputs.json')==development and read(RAW/'evaluation-inputs.json')==evaluation
    tasks={t['id']:t for t in development+evaluation}
    qual=read(RAW/'program-grader-qualification.json');assert qual==meta['grader_qualification']and qual['verified']is True and qual['model_calls']==0
    assert len(qual['rows'])==3 and {r['name']for r in qual['rows']}=={'valid','wrong','forged_grade'}
    for r in qual['rows']:
        proof_check(r['task'],r['report'],r['code'])
        assert r['code_sha256']==sha(r['code'].encode())and r['report']['solved']is(r['name']=='valid')
    assert all(v['idle']is True for v in meta['initial_idle_checks'])and len(meta['initial_idle_checks'])==4
    assert {(r['seed'],r['arm'])for r in rows}=={(s,a)for s in(1,2,3,4)for a in('sequential16','independent4')}
    for result in rows:
        seed,arm=result['seed'],result['arm'];directory=RAW/f'seed-{seed}-{arm}'
        assert result['complete']is True and result['status']=='complete'and result['malformed_lines']==0
        assert result['host']==f'Spark_{seed:02d}'and result['endpoint']==f'http://127.0.0.1:{18080+seed}/v1'
        events=[json.loads(x)for x in data(directory/'events.jsonl').splitlines()]
        assert [e['event_id']for e in events]==list(range(1,len(events)+1))
        assert all(e['method']==arm for e in events)and len({e['run_id']for e in events})==1
        select=lambda kind:[e for e in events if e['type']==kind]
        starts,ends=select('request_start'),select('request_end');assert len(starts)==len(ends)==16
        assert {e['request_id']for e in starts}=={e['request_id']for e in ends}and len({e['request_id']for e in starts})==16
        assert not select('budget_exhausted')
        candidates=select('program_candidate');scored=select('development_candidate_scored');assert len(candidates)==len(scored)==16
        assert {c['index']for c in candidates}=={e['candidate_index']for e in scored}==set(range(16))
        cm={c['index']:c for c in candidates};sm={e['candidate_index']:e for e in scored}
        se={e['candidate_index']:e for e in starts};en={e['candidate_index']:e for e in ends}
        grade_starts=select('program_grade_start');grade_ends=select('program_grade_end');skips=select('program_grade_skipped')
        identity=lambda e:(e['phase'],e['candidate_index'],e['task_id'])
        gs={identity(e):e for e in grade_starts};ge={identity(e):e for e in grade_ends};skip={identity(e):e for e in skips}
        assert len(gs)==len(grade_starts)==len(ge)==len(grade_ends)and gs.keys()==ge.keys()and not(set(gs)&set(skip))
        previous={};width=1 if arm=='sequential16'else 4;fitness={}
        for i in range(16):
            candidate=cm[i];chain=i%width;parent=i-width if i>=width else None
            assert candidate['chain']==chain and candidate['parent_index']==parent
            for e in(se[i],en[i]):
                assert e['candidate_index']==i and e['chain']==e['agent_id']==chain and e['stage']==f'program-{i}'and e['phase']=='development'and e['previous_candidate_index']==parent
            assert se[i]['event_id']<en[i]['event_id']<candidate['event_id']and en[i]['error']is None
            raw=en[i]['response']if isinstance(en[i]['response'],str)else None
            code=raw.strip()if raw is not None else''
            if code.startswith('```python\n')and code.endswith('```'):code=code[len('```python\n'):-3].strip()
            elif code.startswith('```\n')and code.endswith('```'):code=code[4:-3].strip()
            assert candidate['raw']==raw and candidate['code']==code and candidate['code_sha256']==sha(code.encode())
            assert data(directory/f'candidate-{i:02d}.raw.txt')==(raw or'').encode()and data(directory/f'candidate-{i:02d}.py')==code.encode()
            reports=[]
            for task in development:
                k=('development',i,task['id'])
                if candidate['parse_error']:
                    assert k in skip and skip[k]['reason']=='candidate_parse'
                    report=dict(status='error',solved=False,proof=None,failure_kind='candidate_parse',error=candidate['parse_error'],grading_performed=False)
                    counts['development_parse_skips']+=1
                    grade_rows.append(dict(seed=seed,arm=arm,phase='development',candidate_index=i,task_id=task['id'],code_sha256=sha(code.encode()),grading_performed=False,status='error',solved=False,failure_kind='candidate_parse',cleanup_ok=None,graph_sha256=graph_digest(task),child_payload_sha256=None))
                else:
                    assert k in ge;report=ge[k]['report'];assert gs[k]['event_id']<ge[k]['event_id']<sm[i]['event_id']
                reports.append(report)
            expected_feedback=[feedback(t,r)for t,r in zip(development,reports)]
            solved=sum(r.get('solved')is True for r in reports);cost=sum(penalty(t,r)for t,r in zip(development,reports))
            assert sm[i]['feedback']==expected_feedback and sm[i]['solved']==solved and sm[i]['penalty']==cost
            fitness[i]=(-solved,cost,i)
            prev=previous.get(chain);assert(prev['index']if prev else None)==parent
            prompt=protocol.author_prompt(development,prev)
            assert canonical_json(development)in prompt and canonical_json(evaluation)not in prompt
            assert all(canonical_json(t)not in prompt and canonical_json([t['vertex_count'],t['color_count'],t['edges']])not in prompt for t in evaluation)
            # Source-defined arguments are exactly4development tasks and the own predecessor;
            # HTTP request bodies themselves were not logged, so this is reconstruction.
            prompt_sha=sha(prompt.encode());request_seed=int.from_bytes(hashlib.sha256(f'{seed}:{chain}:program-{i}:{prompt}'.encode()).digest()[:4],'big')
            candidate_rows.append(dict(seed=seed,arm=arm,index=i,chain=chain,parent_index=parent,code_sha256=sha(code.encode()),raw_sha256=sha((raw or'').encode()),parse_error=candidate['parse_error'],development_solved=solved,development_penalty=cost,reconstructed_prompt_sha256=prompt_sha,reconstructed_request_seed=request_seed))
            previous[chain]=dict(index=i,code=code,feedback=expected_feedback)
        for generation in range(16//width):
            indices=range(generation*width,(generation+1)*width)
            batch_end=max(en[i]['event_id']for i in indices)
            relevant=[e for e in grade_starts if e['phase']=='development'and e['candidate_index']in indices]
            if relevant:assert batch_end<min(e['event_id']for e in relevant)
        chosen=select('program_selected');assert len(chosen)==1;chosen=chosen[0];best=min(fitness,key=fitness.get)
        choice=read(directory/'selection.json');assert all(choice[k]==chosen[k]for k in choice)
        assert choice['candidate_index']==best and choice['evaluation_seen']is False and choice['model_calls_at_selection']==16
        assert choice['code_sha256']==cm[best]['code_sha256']==result['selected_sha256']and data(directory/'selected.py')==cm[best]['code'].encode()
        assert max(e['event_id']for e in starts+ends+scored)<chosen['event_id']
        eval_keys={('evaluation',best,t['id'])for t in evaluation}
        assert {k for k in ge if k[0]=='evaluation'}==eval_keys and not any(k[0]=='evaluation'for k in skip)
        assert all(gs[k]['event_id']>chosen['event_id']for k in eval_keys)
        eval_solved=0
        for k,event in ge.items():
            task=tasks[event['task_id']];code=cm[event['candidate_index']]['code'];start=gs[k]
            assert event['code_sha256']==start['code_sha256']==sha(code.encode())and event['graph_sha256']==start['graph_sha256']==graph_digest(task)
            assert event['input_sha256']==start['input_sha256']==sha(canonical_json([task['vertex_count'],task['color_count'],task['edges']]).encode())
            assert event['host']==start['host']==result['host']and event['timeout_seconds']==start['timeout_seconds']==10
            assert start['event_id']<event['event_id'];proof_check(task,event['report'],code)
            if k[0]=='evaluation':
                saved=read(directory/f"evaluation-{task['id']}.json");assert saved==dict(task_id=task['id'],graph_sha256=graph_digest(task),selected_sha256=result['selected_sha256'],report=event['report'])
                eval_solved+=event['report']['solved']is True
            grade_rows.append(dict(seed=seed,arm=arm,phase=k[0],candidate_index=k[1],task_id=k[2],code_sha256=sha(code.encode()),grading_performed=True,status=event['report']['status'],solved=event['report']['solved'],failure_kind=event['report'].get('failure_kind'),cleanup_ok=event['report']['cleanup_ok'],graph_sha256=graph_digest(task),child_payload_sha256=event['report']['child_payload_sha256']))
        assert result['evaluation_solved']==eval_solved and result['evaluation_completed']==result['evaluation_graphs']==12
        assert result['training_candidates_scored']==16 and result['grading_calls']==len(grade_ends)
        assert same(sum(e['controller_wall_seconds']for e in grade_ends),result['grading_wall_seconds'])
        budget=result['model_budget'];assert budget['calls']==budget['max_calls']==16 and budget['max_completion_tokens']==32768 and budget['completion_tokens_reserved']==0
        assert budget['completion_tokens_charged']==sum(e['completion_tokens_charged']for e in ends)
        assert all(e['usage'].get('completion_tokens',0)<=2048 for e in ends)
        for field in('prompt_tokens','completion_tokens'):assert result[field]==sum(e['usage'].get(field,0)for e in ends)
        complete_usage=all(all(type(e['usage'].get(k))is int for k in('prompt_tokens','completion_tokens'))for e in ends)
        assert result['client_usage_complete']is complete_usage and result['client_totals_are_lower_bounds']is(not complete_usage)
        assert result['calls']==result['completed_calls']==16 and result['unfinished_calls']==0 and result['server_idle_after']is True
        before,after=result['server_metrics_before'],result['server_metrics_after']
        if result['server_cost_known']:
            for key,field in [('prompt','server_prompt_tokens'),('completion','server_completion_tokens')]:assert same(result[field],after[key]-before[key])and result[field]>=result[key+'_tokens']
        else:assert result['server_prompt_tokens']is None and result['server_completion_tokens']is None
        end=select('program_episode_end');assert len(end)==1 and end[0]['complete']is True and end[0]['evaluation_solved']==eval_solved
        for name in('model_budget','training_candidates_scored','evaluation_completed','selected_sha256','selected_candidate_index','development_solved','grading_calls'):assert end[0][name]==result[name]
        assert all(e['event_id']<end[0]['event_id']for e in grade_ends)
        assert result['remote_solver_cpu_seconds']is None
        intervals.setdefault(seed,[]).append((min(e['timestamp']for e in starts),end[0]['timestamp'],arm))
        early=[i for i in range(16)if sm[i]['solved']==4]
        early_index=min(early,key=lambda i:sm[i]['event_id'])if early else None
        later_calls=sum(e['event_id']>sm[early_index]['event_id']for e in starts)if early else None
        episode_rows.append(dict(seed=seed,arm=arm,selected_index=best,selected_code_sha256=result['selected_sha256'],model_calls=16,first_4of4_development_index=early_index,calls_after_first_4of4=later_calls,selected_development_solved=choice['development_solved'],evaluation_solved=eval_solved,evaluation_graphs=12,actual_grade_calls=len(grade_ends),parse_skipped_development_grades=sum(e['phase']=='development'for e in skips),server_cost_known=result['server_cost_known'],server_prompt_tokens=result['server_prompt_tokens'],server_completion_tokens=result['server_completion_tokens'],client_usage_complete=complete_usage,parent_cpu_scope='Overlapping local orchestration only; remote solver CPU unmeasured',remote_cpu_seconds=None))
    for seed,spans in intervals.items():
        assert len(spans)==2;spans.sort();assert spans[0][1]<spans[1][0]
        assert [x[2]for x in spans]==(['sequential16','independent4']if seed%2 else['independent4','sequential16'])
    assert len(candidate_rows)==128 and len(grade_rows)==608 and len([r for r in grade_rows if r['phase']=='evaluation'])==96
    result=dict(status='PASS',verified=True,created_utc=datetime.now(timezone.utc).isoformat(),source_revision=REV,episodes=episode_rows,
        counters=dict(counts,model_calls=128,candidates=128,selected_programs=8,original_evaluation_grades=96,actual_training_grades=sum(r['phase']=='development'and r['grading_performed']for r in grade_rows),known_server_cost_episodes=sum(r['server_cost_known']for r in episode_rows),infrastructure_faults=0,cleanup_failures=0),
        phase_status_counts={phase:dict(Counter(r['status']for r in grade_rows if r['phase']==phase))for phase in('development','evaluation')},
        original_evaluation_counts={arm:dict(solved=sum(r['evaluation_solved']for r in episode_rows if r['arm']==arm),graphs=48,trained_programs=4)for arm in('sequential16','independent4')},
        scope='Independent completed-artifact protocol/lineage/fitness/source/outer-math/payload audit. No generated source executed locally, no model/SSH/candidate calls; no bootstrap or plots.',
        prompt_evidence='Prompt and request-seed reconstruction from immutable source, four development inputs and own-chain event ancestry; HTTP messages/body/derivedseed were not wire-logged. This is not independent packet-level capture.',
        exclusions='Original12 evaluation inputs/witnesses, CPU baseline source and fresh96 corpus are absent from the pinned author_prompt input arguments; no evaluation model calls or repairs occur after selection. Own generated source is permitted feedback, not an external advisor.',
        limitations=['Twelve reused fixed graphs and four paired training seeds, not96 independent tasks. Same-distribution fresh96 confirmation is separate and not audited here.',
            'Child values/exception names/input-after observations remain unauthenticated. Exact returned graph assignments are checked against original outer constraints; no universal functional/purity guarantee.',
            'Endpoint exclusivity is supported by per-node nonoverlapping scheduling and idle-delimited counters/admission, not an independent network-access audit. Unknown usage/cost is never zero.',
            'All16 proposals were spent per episode even after development success. Training model cost is attributed once per episode; per-graph CPU work is separate.'],
        input_sha256=inputs,audit_seconds=time.monotonic()-began,audit_source_sha256=sha(Path(__file__).read_bytes()))
    for name,obj in [('summary.json',result)]:
        with(OUT/name).open('w')as f:json.dump(obj,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
    record_csv('episodes.csv',episode_rows);record_csv('candidate-lineage.csv',candidate_rows);record_csv('graph-grades.csv',grade_rows)
    (OUT/'NOTES.md').write_text('''# Completed reusable-program protocol audit

The eight frozen episodes pass the source, ancestry, development-fitness, earliest-tie selection and original graph-proof audit. Each spent all16 model calls: one16-step chain or four isolated4-step chains. Five episodes achieved4/4 development success before training ended, but still completed their fixed allocation. Calls after first success are counted by request-start events AFTER its scored-feedback event, excluding already completed members of the same parallel batch.

All128 raw/model-source pairs and eight selected-source hashes match their files. Selection precedes every original evaluation grade, with no later model requests or reselection. Permitted prompts are reconstructed from immutable source, the four development inputs and the own-chain predecessor/code/feedback; HTTP messages/body/request seeds were not independently wire-captured. Original evaluation graphs, witnesses, CPU baseline source and the fresh96 corpus are not inputs to that pinned prompt path. This is source/lineage evidence, not a network-access proof.

There are512 logical development graph checks:452 actual containers plus60 declared parse-error skips. All96 original evaluation graph grades ran, even for poor selected programs. Together with three authored qualification smokes this gives551 actual payload hashes checked, and475 returned graph proofs replayed. Parse skips retain failed outcomes with no container cleanup/payload to invent. Candidate runtime/resource/protocol failures remain negative outcomes; there were no observed grading-infrastructure or cleanup failures.

The four sequential selections solved29/48 original program/graph outcomes; the four independent-chain selections solved47/48. These are12 reused graph instances and four paired trained seeds per arm, not48independent tasks. Original12 results remain separate from any later fresh96 confirmation; no bootstrap or plots are computed here. All eight selected programs must remain in any preregistered follow-up, including the one with0/4 development and0/12 original evaluation success.

Server-counter cost is known for all eight idle-delimited episodes; client usage is complete here. Per-node episodes do not overlap and follow the declared alternating order. Container wall/CPU work and model-token costs remain distinct. Remote solver CPU time is unmeasured/null; local parent CPU observations overlap across threads. Child values, exception names and input postconditions are unauthenticated observations; exact returned assignments satisfy the checked outer graph constraints, not a universal solver/purity guarantee.
''')
    with(OUT/'manifest.json').open('w')as f:json.dump(dict(protocol='program-search-v1-independent-audit',files={p.name:sha(p.read_bytes())for p in OUT.iterdir()if p.is_file()and p.name!='manifest.json'},input_sha256=inputs,original_artifacts_modified=False),f,indent=2)
    print(json.dumps(dict(status='PASS',counters=result['counters'],episodes=episode_rows,audit_seconds=result['audit_seconds']),indent=2))

if __name__=='__main__':audit()
