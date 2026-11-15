from pathlib import Path
from collections import Counter
from datetime import datetime
import ast,copy,hashlib,json,math,subprocess,sys
base=Path(sys.argv[1]).resolve();app=Path(sys.argv[2]).resolve();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();digest=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def check(ok,why):
 if not ok:raise AssertionError(why)
def infra(report):
 if report.get('cleanup_ok')is False:return True
 if report.get('provenance')=='infrastructure'or str(report.get('failure_kind','')).endswith('_infrastructure'):return True
 if report.get('provenance')=='candidate'or str(report.get('failure_kind','')).startswith('candidate_'):return False
 return 'exit_code'in report or str(report.get('error','')).startswith('Invalid runner protocol')or report.get('status')not in('passed','failed','error','timeout')
def projection(r):return{k:r[k]for k in('status','passed','total','error','first_failure')if k in r}
def parse(content,python=False):
 if not isinstance(content,str):return None
 text=content.strip()
 if text.startswith('```'):
  lines=text.splitlines(keepends=True)
  if len(lines)<3 or lines[-1].strip()!='```'or python and lines[0].strip().lower()not in('```','```python'):return None
  text=''.join(lines[1:-1]).strip()
 if python:return text or None
 try:return json.loads(text)
 except(ValueError,TypeError):return None
def bounded(value):
 text=json.dumps(value,allow_nan=False)
 return value if len(text)<=1200 else{'truncated_or_non_json':True,'preview':text[:1200]}
ledger_raw=(app/'runs/evaluation-v2-ledger.json').read_bytes();entry=next(e for e in json.loads(ledger_raw)if e['name']==base.name)
check(entry['domain']=='coding'and entry['seed']==3 and entry['split']=='evaluation','ledger cohort identity')
check(entry['verified']is True and entry['valid_for_aggregation']is True and entry['fresh_v2']is True and entry['returncode']==0,'verified fresh-v2 receipt gate')
meta=json.loads((base/'metadata.json').read_text());rows=json.loads((base/'summary.json').read_text());producer=Path(meta['cases'][0]['command'][1]).parent;revision='cbcde299716b7842536b008880a089590e9816f8'
boundary_path=Path(entry['grader_boundary']['path']);boundary=json.loads(boundary_path.read_text());check(entry['grader_boundary']['verified']is True and boundary['verified']is True and boundary['cohort']==base.name and boundary['owned_containers_remaining']==[]and boundary['local_coding_children_remaining']==[],'verified owned-grader boundary')
check(meta['git_revision']==entry['source_revision']==revision and entry['source_path']==str(producer),'source revision')
check(meta['completed_cases']==entry['completed_cases']==len(meta['cases'])==len(rows)==108 and not meta['incomplete']and not meta['missing_cases']and not meta['slot_failures']and meta['completed_utc'],'complete108')
check(meta['source_changed_during_run']is False and meta['source_hashes']==meta['final_source_hashes'],'source unchanged')
for name,value in meta['source_hashes'].items():
 check(sha(producer/name)==value,'captured source '+name);check(hashlib.sha256(subprocess.check_output(['git','show',revision+':'+name],cwd=app)).hexdigest()==value,'git blob '+name)
check(meta['runtime']==json.loads((producer/'runtime.json').read_text())and entry['serving_runtime_sha256']==meta['source_hashes']['runtime.json']=='072b628126f36aa559fa864372118c7e0497e44d1b37d29be99ea3c7f8cf6ec5','runtime snapshot')
check(meta['runtime']['cpu_grader_image']=='python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd','new CPU image metadata')
check(meta['runtime']['arm64_manifest_digest']=='sha256:6ff5ff0ddf3658d2c2d677dac5ca2d4726ce0156b4371166d918181b210bd4bc','serving image metadata')
source=(producer/'sandbox_code.py').read_text();tree=ast.parse(source);lines=source.splitlines(keepends=True);functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
def expression(n):
 if isinstance(n,ast.Constant):return n.value
 if isinstance(n,ast.BinOp)and isinstance(n.op,ast.Add):return expression(n.left)+expression(n.right)
 if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr=='getsource':
  f=functions[n.args[0].id];return ''.join(lines[f.lineno-1:f.end_lineno])
 raise AssertionError('unexpected static runner expression')
runner=next(n.value for n in tree.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='RUNNER'for t in n.targets));check(hashlib.sha256(expression(runner).encode()).hexdigest()==meta['sandbox_runner_sha256'],'static grader runner hash')
image=next(n.value.value for n in tree.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='IMAGE'for t in n.targets));check(image==meta['runtime']['cpu_grader_image'],'actual grader IMAGE literal')
selection=json.loads((app/'EVALUATION_SELECTION.json').read_text());check(entry['selection_sha256']==sha(app/'EVALUATION_SELECTION.json'),'selection receipt hash');check(meta['arms']==selection['coding']['arms'][3:]+selection['coding']['arms'][:3]and meta['seed']==3 and meta['split']=='evaluation'and meta['code_format']=='python','predeclared cohort')
for name in('EVALUATION_SELECTION.json','RUNTIME_V2_AMENDMENT.json','CPU_GRADER_AMENDMENT.json'):
 check(datetime.fromisoformat(json.loads((app/name).read_text())['frozen_utc'])<datetime.fromisoformat(meta['started_utc']),'pre-run freeze '+name)
public=json.loads(Path(meta['dataset']).read_text());private=json.loads(Path(meta['tests']).read_text());check(sha(Path(meta['dataset']))==meta['dataset_sha256']==selection['coding']['dataset_sha256'],'public corpus hash');check(sha(Path(meta['tests']))==meta['tests_sha256']==selection['coding']['private_sha256'],'private corpus hash')
tasks={t['id']:t for t in public['tasks']if t['split']=='evaluation'};check(len(tasks)==18,'evaluation18');private_hashes={}
for taskid,task in tasks.items():
 ref=private['references'][taskid];parts={k:{digest([c['args'],c.get('kwargs',{})])for c in ref[k]}for k in('feedback_tests','holdout_tests')};examples={digest([c['args'],c.get('kwargs',{})])for c in task['examples']};check(not parts['feedback_tests']&parts['holdout_tests']and not examples&(parts['feedback_tests']|parts['holdout_tests']),'disjoint public/feedback/holdout inputs')
 private_hashes[taskid]={phase:dict(cases=len(ref[phase+'_tests']),sha256=digest(ref[phase+'_tests']))for phase in('feedback','holdout')}
planned={(c['task_id'],c['arm'],c['seed']):c for c in meta['cases']};check(len(planned)==108 and set(planned)=={(t,a,3)for t in tasks for a in meta['arms']},'balanced plan');check(len({(r['task_id'],r['arm'],r['seed'])for r in rows})==108,'unique summary')
arm_specs={'direct_off':('direct',1,1,'off',1024),'solo_iterative':('iterative',1,3,'off',1024),'direct_thinking':('direct',1,1,'on',8192),'independent8':('independent',8,3,'off',1024),'shared8':('shared',8,3,'off',1024),'democracy8':('democracy',8,3,'off',1024)}
counts=Counter();classes=Counter();error_classes=Counter();all_requests=set();case_results=[];resource_events=[]
for row in rows:
 case=planned[row['task_id'],row['arm'],row['seed']];task=tasks[row['task_id']];reference=private['references'][row['task_id']];events=[json.loads(l)for l in Path(row['events']).read_text().splitlines()];check([e['event_id']for e in events]==list(range(1,len(events)+1)),'event sequence');check(len({e['run_id']for e in events})==1,'run identity')
 start=events[0];cfg=start['config'];check(start['type']=='run_start'and start['domain']=='coding'and start['task_id']==row['task_id'],'trace task');check(start['public_sha256']==meta['dataset_sha256']and start['private_sha256']==meta['tests_sha256'],'trace corpus pins')
 expected=arm_specs[row['arm']];check(tuple(cfg[k]for k in('method','agents','rounds','thinking','max_tokens'))==expected,'arm config');check(cfg['max_calls']==1024 and cfg['maxcompletion']==131072 and cfg['seed']==3 and cfg['code_format']=='python','request limits')
 command=case['command'];required={'--tasks':meta['dataset'],'--tests':meta['tests'],'--task-id':row['task_id'],'--method':cfg['method'],'--agents':str(cfg['agents']),'--rounds':str(cfg['rounds']),'--endpoint':case['endpoint'],'--host':case['grader_host'],'--events':row['events'],'--max-tokens':str(cfg['max_tokens']),'--max-calls':'1024','--maxcompletion':'131072','--seed':'3','--thinking':cfg['thinking'],'--code-format':'python'}
 slot=case['slot'];check(0<=slot<4 and case['endpoint']==f'http://127.0.0.1:{18081+slot}/v1'and case['grader_host']==f'Spark_{slot+1:02d}','fixed endpoint/grader slot pairing')
 check(len(command)==2+2*len(required)and Path(command[1])==producer/'coding_harness.py','bounded command inputs')
 for flag,value in required.items():check(command.count(flag)==1 and command[command.index(flag)+1]==value,'command '+flag)
 check(all(cfg[k]==v for k,v in{'tasks':meta['dataset'],'tests':meta['tests'],'task_id':row['task_id'],'endpoint':case['endpoint'],'host':case['grader_host'],'events':row['events']}.items()),'config task/host')
 context='Implement this pure Python 3 function using only the standard library. Do not mutate any input, do external I/O, or rely on external packages. Return exact JSON-compatible values: arrays must be Python lists; bool and int are distinct; floats are outside this corpus; preserve every ordering required by the specification.\n'+json.dumps({k:task[k]for k in('id','function_name','spec','examples')},ensure_ascii=False)
 prefix=context+'\nReturn complete Python function source only. Do not wrap it in JSON or include explanations.'
 requests={};ended={};nodes={};candidates={};candidate_rows=[];feedback_reports={};eval_starts={};eval_ends={};cache={};frozen=None;selected_id=None;holdouts=[];facts={};memory=[];memory_base=None;vote_round=None;shortlists={};votes_by_round={};passing_feedback=[];last_chosen=None;local=Counter()
 for position,e in enumerate(events):
  typ=e['type']
  if typ=='node':nodes[e['node_id']]=e
  if typ in('request_start','code_prompt','code_vote_prompt','code_candidate','memory_write'):check(frozen is None,'no model start/prompt/repair after selection freeze')
  if typ=='request_start':
   rid=e['request_id'];check(rid not in requests and rid not in all_requests,'unique request ID');requests[rid]=e;all_requests.add(rid)
  if typ=='request_end':
   rid=e['request_id'];check(rid in requests and rid not in ended,'request pairing');ended[rid]=e;check(all(e.get(k)==requests[rid].get(k)for k in('agent_id','stage','round','puzzle_id')),'request context')
   check(e.get('usage',{}).get('completion_tokens',0)<=cfg['max_tokens']and e['completion_tokens_charged']==e.get('usage',{}).get('completion_tokens',cfg['max_tokens']),'request cap/reservation')
   if e.get('error'):error_classes[e['error'].split(':',1)[0]]+=1
  if typ=='code_prompt':
   check(e['prompt'].startswith(prefix),'public-only initial context');tail=e['prompt'][len(prefix):];expected_tails={''}
   if cfg['method']in('iterative','independent'):
    eligible={c['candidate_id']for c in candidate_rows if c['agent_id']==e['agent_id']and c['round']<e['round']and c['candidate_id']in feedback_reports and not infra(feedback_reports[c['candidate_id']])}
    bases=sorted(eligible,key=lambda cid:(-feedback_reports[cid].get('passed',0),cid))[:1]
   elif cfg['method']in('shared','democracy'):bases=[memory_base]if memory_base else[]
   else:bases=[]
   expected_tails={''}if not bases else{'\nPrevious implementation:\n'+candidates[cid]+'\nFeedback (not holdout): '+json.dumps(projection(feedback_reports[cid]),ensure_ascii=False)for cid in bases}
   suffix='\nVerified feedback-test observations from prior rounds (not global impossibility claims): '+json.dumps(memory,ensure_ascii=False)if memory else ''
   check(tail.endswith(suffix)if suffix else True,'feedback memory exact');repair=tail[:-len(suffix)]if suffix else tail;check(repair in expected_tails,'repair derives only from prior feedback/code')
   if cfg['method']in('direct','iterative','independent'):check(not suffix,'private track no shared facts')
  if typ=='code_vote_prompt':
   pre=context+'\nReview these implementations against the specification and examples. Feedback tests are partial, not a correctness proof. Select the candidate most likely to generalize (or the best repair base if none passes feedback). Return JSON {"candidate_id":"id"}.\nCandidates:\n';check(e['prompt'].startswith(pre),'public review context');display=json.loads(e['prompt'][len(pre):]);check(0<len(display)<=4,'shortlist cap')
   eligible=set(feedback_reports);passing={cid for cid in eligible if feedback_reports[cid]['status']=='passed'};eligible=passing or eligible;ranked=sorted(eligible,key=lambda cid:(-feedback_reports[cid].get('passed',0),cid))[:4];check([card['candidate_id']for card in display]==ranked,'feedback-ranked shortlist exact')
   vote_round=e['round'];shortlists[vote_round]=ranked
   for card in display:check(card['candidate_id']in feedback_reports and card['code']==candidates[card['candidate_id']]and card['feedback']==projection(feedback_reports[card['candidate_id']]),'vote input feedback-only')
  if typ=='code_candidate':
   cid=e['candidate_id'];check(hashlib.sha256(e['code'].encode()).hexdigest()==cid,'candidate artifact hash');check(cid not in candidates or candidates[cid]==e['code'],'same hash same source');check(nodes[e['node_id']]['state']==[cid[:12]],'candidate node')
   replies=[r for r in ended.values()if r['stage']=='code_propose'and r['agent_id']==e['agent_id']and r['round']==e['round']];check(len(replies)==1 and not replies[0].get('error')and parse(replies[0].get('response'),True)==e['code'],'model source unchanged except optional fence/trim')
   candidates[cid]=e['code'];candidate_rows.append(e);local['candidate_artifacts']+=1
  if typ=='evaluation_start':
   check((e['phase'],e['candidate_id'])not in cache,'cacheable phase/code result must be reused');check(e['candidate_id']in candidates and e['evaluation_id']not in eval_starts,'grade artifact/start ID');check(e['phase']in('feedback','holdout'),'grade phase');eval_starts[e['evaluation_id']]=e
   if e['phase']=='feedback':check(frozen is None,'no feedback retry after freeze')
   else:check(frozen is not None and e['candidate_id']==selected_id and not holdouts,'one frozen holdout');holdouts.append(e)
  if typ=='evaluation_end':
   eid=e['evaluation_id'];check(eid in eval_starts and eid not in eval_ends,'grade pairing');check(all(e[k]==eval_starts[eid][k]for k in('phase','candidate_id','node_id','puzzle_id')),'grade context');report=e['report'];check(e['infrastructure_error']==infra(report),'independent grader error typing');phase=e['phase'];tests=reference[phase+'_tests'];check(report.get('total')==len(tests),'exact phase case count')
   if report['status']in('passed','failed'):
    check(report['tests_run']==len(tests)and report['passed']+report['failed']==len(tests)and (report['status']=='passed')==(report['passed']==len(tests)),'grade tally');failure=report.get('first_failure')
    if failure:
     test=tests[failure['test_index']];check(failure['input']==bounded({'args':test['args'],'kwargs':test.get('kwargs',{})})and failure['expected']==bounded(test.get('expected',{'exception':test.get('expected_exception')})),'exact private-case failure input/expected')
   if report.get('failure_kind')=='candidate_oom':check(report.get('container_state',{}).get('OOMKilled')is True and report['container_state']['ExitCode']==137 and not e['infrastructure_error'],'OOM model resource classification');resource_events.append(dict(trace=Path(row['events']).name,evaluation_id=eid,candidate_id=e['candidate_id'],kind='candidate_oom',container_state=report['container_state'],infrastructure_error=e['infrastructure_error'],cleanup_ok=report['cleanup_ok'],cacheable=False))
   check(report.get('cleanup_ok')is True,'owned grader cleanup');eval_ends[eid]=e;classes[(phase,report['status'],report.get('failure_kind'))]+=1;local['grade_'+phase]+=1
   if phase=='feedback':
    feedback_reports[e['candidate_id']]=report
    if report['status']=='passed'and not infra(report):passing_feedback.append(e['candidate_id'])
   if not infra(report)and(report['status']in('passed','failed')or report['status']=='error'and str(report.get('error','')).startswith(('SyntaxError:','IndentationError:','TabError:'))):cache[(phase,e['candidate_id'])]=eid
  if typ=='evaluation_reused':
   key=e['phase'],e['candidate_id'];check(key in cache and cache[key]==e['source_evaluation_id'],'cache phase/code/source key');check(e['report']==eval_ends[cache[key]]['report']and not infra(e['report'])and e['report']['status']not in('timeout',),'cache report exact; no transient reuse');check(e['phase']=='feedback'and frozen is None,'no holdout reuse/repair');feedback_reports[e['candidate_id']]=e['report'];local['cache_reuses']+=1
   if e['report']['status']=='passed':passing_feedback.append(e['candidate_id'])
  if typ=='memory_write':
   cid=e['candidate_id'];check(cid in feedback_reports and e['failure']==feedback_reports[cid].get('first_failure')and e['fact_kind']=='feedback_test_failure','shared fact prior feedback');check(e['fact_id']==digest([e['failure'].get('input'),e['failure'].get('expected')]),'fact artifact hash');facts[e['fact_id']]={k:e[k]for k in('fact_kind','candidate_id','source_agent_id','failure')}
  if typ=='memory_snapshot':
   memory=e['facts'];memory_base=e['base_candidate_id'];check(len(memory)<=4 and all(f in facts.values()for f in memory),'memory from verified prior feedback only')
  if typ=='vote':
   replies=[r for r in ended.values()if r['stage']=='code_vote'and r['agent_id']==e['agent_id']and r['round']==e['round']];check(len(replies)==1,'vote request pair');reply=parse(replies[0].get('response'))if not replies[0].get('error')else None;choice=reply.get('candidate_id')if isinstance(reply,dict)else None;check(e['candidate_id']==choice and e['valid']==(choice in shortlists[e['round']])and e['weight']==1,'vote derives from raw reply');votes_by_round.setdefault(e['round'],[]).append(e)
  if typ=='chosen':
   tally={cid:sum(v['valid']and v['candidate_id']==cid for v in votes_by_round[vote_round])for cid in shortlists[vote_round]};check(e['tally']==tally and e['candidate_id']==max(shortlists[vote_round],key=lambda cid:tally[cid]),'semantic review tally/selection');last_chosen=e['candidate_id']
  if typ=='candidate_selected':
   check(frozen is None and e['holdout_seen']is False,'single pre-holdout freeze');frozen=position;selected_id=e['candidate_id'];check(selected_id is None or selected_id in feedback_reports,'selected artifact feedback-graded')
   if cfg['method']=='democracy'and selected_id is not None:check(selected_id==last_chosen,'democracy freezes reviewed candidate')
   if cfg['method']!='democracy':
    eligible={cid for cid,report in feedback_reports.items()if not infra(report)};ranked=sorted(eligible,key=lambda cid:(-feedback_reports[cid].get('passed',0),cid));expected_selection=passing_feedback[0]if passing_feedback else ranked[0]if ranked else None;check(selected_id==expected_selection,'first feedback pass or exact feedback ranking')
  if typ in('selection_complete','run_end')and 'holdout'in e:
   check(frozen is not None and e['candidate_id']==selected_id,'immutable selected candidate');hold=[g for g in eval_ends.values()if g['phase']=='holdout'];check(e['holdout']==(hold[-1]['report']if hold else None),'final holdout report exact');check(e.get('feedback')==(projection(feedback_reports[selected_id])if selected_id else None),'final feedback projection');expected_solved=bool(hold and hold[-1]['report']['status']=='passed'and not infra(hold[-1]['report']));check(e['solved']==expected_solved,'final success from single holdout');check(e['budget']['calls']<=1024 and e['budget']['completion_tokens_charged']+e['budget']['completion_tokens_reserved']<=131072,'worker budget reservation bound')
  if typ=='reward':check(e['basis']in('single_frozen_holdout_grade','no_candidate_selected')and bool(e['solved'])==bool(holdouts and eval_ends[holdouts[0]['evaluation_id']]['report']['status']=='passed'),'reward derives only from holdout')
  if typ=='controller_stop':check(position==len(events)-1 and(not e['solved']or any(r['type']=='reward'and r['solved']for r in events[:position])),'controller proof precedes stop')
 check(frozen is not None and len(holdouts)==int(selected_id is not None)and len(eval_starts)==len(eval_ends),'one holdout per selected code; grades completed')
 expected={'calls':len(requests),'completed_calls':len(ended),'unfinished_calls':len(requests)-len(ended),'prompt_tokens':sum(e.get('usage',{}).get('prompt_tokens',0)for e in ended.values()),'completion_tokens':sum(e.get('usage',{}).get('completion_tokens',0)for e in ended.values()),'charged_completion_tokens':sum(e['completion_tokens_charged']for e in ended.values()),'feedback_eval_count':local['grade_feedback'],'holdout_eval_count':local['grade_holdout'],'grader_eval_count':len(eval_ends),'grader_errors':sum(infra(e['report'])or e['report']['status']in('error','timeout')for e in eval_ends.values()),'grader_infrastructure_errors':sum(infra(e['report'])for e in eval_ends.values())}
 for k,value in expected.items():check(row[k]==value,'summary '+k)
 hold=[e for e in eval_ends.values()if e['phase']=='holdout'];holdreport=hold[-1]['report']if hold else{};feedback=feedback_reports.get(selected_id,{})
 for name,value in [('holdout_status',holdreport.get('status')),('holdout_passed',holdreport.get('passed')),('holdout_total',holdreport.get('total')),('feedback_final_status',feedback.get('status')),('feedback_final_passed',feedback.get('passed')),('feedback_final_total',feedback.get('total'))]:check(row[name]==value,'final summary '+name)
 check(row['solved']==bool(holdreport.get('status')=='passed')and row['calls']<=1024 and row['charged_completion_tokens']<=131072,'summary success/budget')
 before,after=row['server_metrics_before'],row['server_metrics_after'];known=False;delta={}
 if before and after and not before.get('error')and not after.get('error')and row['server_idle_after']and before.get('running')==before.get('waiting')==0:
  if all(k in before and k in after and after[k]>=before[k]for k in('prompt','completion')):delta={k:after[k]-before[k]for k in('prompt','completion')};known=all(delta[k]>=row[k+'_tokens']for k in delta)
 check(known==row['server_cost_known'],'server known state')
 for k in('prompt','completion'):check(row['server_'+k+'_tokens']==(int(delta[k])if known else None),'server counter delta')
 local.update(worker_run_end_present=int(any(e['type']=='run_end'for e in events)),selection_pending_model_calls=int(any(e['type']=='selection_complete'and e.get('pending_model_calls',0)>0 for e in events)),cases=1,request_starts=len(requests),request_ends=len(ended),unfinished_calls=len(requests)-len(ended),selected_candidates=int(selected_id is not None),no_candidate=int(selected_id is None),known_server_cases=int(known));counts.update(local);case_results.append(dict(task_id=row['task_id'],arm=row['arm'],trace=Path(row['events']).name,trace_sha256=sha(Path(row['events'])),selected_candidate_sha256=selected_id,**local))
audit=dict(schema_version=1,domain='coding',split='evaluation',seed=3,status='PASS',protocol_version='runtime-v2',valid_for_aggregation=True,ledger_entry_verified=True,ledger_snapshot_sha256=hashlib.sha256(ledger_raw).hexdigest(),ledger_completed_entry_sha256=hashlib.sha256(json.dumps(entry,ensure_ascii=False).encode()).hexdigest(),metadata_sha256=sha(base/'metadata.json'),summary_sha256=sha(base/'summary.json'),source_commit=revision,source_hashes=meta['source_hashes'],runtime_sha256=meta['source_hashes']['runtime.json'],sandbox_runner_sha256=meta['sandbox_runner_sha256'],grader_boundary_sha256=sha(boundary_path),grader_boundary_verified=True,grader_boundary_wall_seconds=boundary['wall_seconds'],public_sha256=meta['dataset_sha256'],private_sha256=meta['tests_sha256'],private_phase_hashes=private_hashes,counts=dict(counts),grade_classes=[dict(phase=k[0],status=k[1],failure_kind=k[2],events=v)for k,v in classes.items()],request_error_categories=dict(error_classes),candidate_resource_events=resource_events,checks=['Verified fresh-v2 completed108case receipt; source/git/runtime/CPUimage/runner/data/command pins','18task public/feedback/holdout inputs disjoint; phase report totals and first-failure fields match exact private cases','Every candidate SHA and source matches its raw model response with only optional fencing/trim','Every model prompt/review/shared fact reconstructed from public context and prior feedback/code, no holdout information','Selection freezes before exactly one holdout per selected candidate; no postselection model starts/repairs/feedback retry','Grade IDs/cache keys and reused reports match prior cacheable same-phase same-code grade; transient errors/timeouts not reused','Single-holdout reports/rewards/summaries agree; no selected candidate means zero holdout and unsolved','Request IDs/usage/reservation/cost and case budgets independently reconciled; unknown server totals remain null','Candidate OOM, if present, requires retained kernel evidence and is model resource failure rather than infrastructure'],limits='Pinned grading control flow and reported artifacts audited offline; model candidate code was not re-executed, and malicious grade-forgery resistance is not claimed.',audit_script_sha256=sha(Path(__file__)),cases=case_results)
Path(sys.argv[3]).write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps(dict(status='PASS',counts=dict(counts))))
