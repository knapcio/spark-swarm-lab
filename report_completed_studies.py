#!/usr/bin/env python3
"""Offline completed-study reports. Plan by default; bootstrap/plots require final45 gate."""
import argparse
from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import aggregate_evaluation as ag
from csp_tasks import canonical_json, graph_digest, verify_assignment, worker_task
from reference_worker import verify_gate

HERE=Path(__file__).resolve().parent
LABELS={'solo_refine_thinking_8k':'Sequential full-plan refinement','resample':'Independent resampling','sequential':'Sequential repair','parallel_repair4':'Four repair chains','evolution4':'Evolution with crossover','evolution_mutation4':'Mutation-only evolution','review_elites4':'Review-guided elites','democracy4':'Color-aligned consensus','weighted_democracy4':'Weighted color consensus','sequential16':'Sequential program refinement','independent4':'Four independent program chains'}

def require(ok,message):
 if not ok:raise ValueError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def reference(path):
 try:return str(Path(path).resolve().relative_to(HERE))
 except ValueError:return str(Path(path).resolve())
def read(path,inputs):
 path=Path(path);inputs[reference(path)]=sha(path);return json.loads(path.read_bytes())
def records(path,inputs):
 path=Path(path);inputs[reference(path)]=sha(path);return [json.loads(line)for line in path.read_bytes().splitlines()if line.strip()]
def finite(value):return type(value)in(int,float)and math.isfinite(value)

def source_complete(meta,program=False):
 before=meta.get('source')if program else meta.get('source_before');after=meta.get('source_after')
 require(before and before==after and before.get('tracked_clean')is True and before.get('source_files_tracked')is True and before.get('sha256'),'Captured source identities missing/changed')
 require(meta.get('verified')is True and meta.get('completed_utc')and not meta.get('faults'),'Cohort is unverified/incomplete')
 require(meta.get('complete')is True if program else meta.get('incomplete')is False and meta.get('source_changed_during_run')is False and not meta.get('missing_cases'),'Cohort completion/source flags invalid')
 checks=meta.get('initial_idle_checks',[]);require(len(checks)==4 and all(c.get('idle')is True for c in checks),'Four initial drain receipts required')
 return before

def check_cost(row):
 """Never infer zero from unknowns; independently reconcile known exclusive counters."""
 require(row.get('server_idle_after')is True,'Final endpoint drain not confirmed')
 if row.get('server_cost_known')is not True:
  require(row.get('server_prompt_tokens')is None and row.get('server_completion_tokens')is None,'Unknown server cost must remain null');return False
 before,after=row.get('server_metrics_before'),row.get('server_metrics_after')
 require(before and after and not before.get('error')and not after.get('error'),'Known cost lacks snapshots')
 require(before.get('running')==before.get('waiting')==after.get('running')==after.get('waiting')==0,'Known cost lacks idle endpoints')
 for key in ('prompt','completion'):
  require(finite(before.get(key))and finite(after.get(key)),'Known cost lacks numeric counters')
  delta=after[key]-before[key]
  require(finite(delta)and delta>=row.get(key+'_tokens',0)and delta==row.get('server_'+key+'_tokens'),'Server cost counter mismatch')
 return True

def check_usage(events,row):
 starts=[e for e in events if e.get('type')=='request_start'];ends=[e for e in events if e.get('type')=='request_end']
 require(all(all(type(v)is int and v>=0 for k,v in e.get('usage',{}).items()if k in ('prompt_tokens','completion_tokens'))for e in ends),'Invalid client usage types')
 ss={e['request_id']:e for e in starts};ee={e['request_id']:e for e in ends}
 require(len(ss)==len(starts)and len(ee)==len(ends)and ee.keys()<=ss.keys(),'Request identities duplicate/unpaired')
 require(row.get('calls')==len(starts)and row.get('completed_calls')==len(ends)and row.get('unfinished_calls')==len(starts)-len(ends),'Request totals differ')
 for key in ('prompt_tokens','completion_tokens'):require(row.get(key)==sum(e.get('usage',{}).get(key,0)for e in ends),'Client usage differs')
 require(not any(e.get('error')and e.get('response')is None and e.get('finish_reason')!='length'for e in ends),'Observed transport failure')
 return True

def unique_grid(rows,tasks=None,seeds=None):
 require(rows and all(type(r.get('solved'))is bool for r in rows),'Boolean outcomes required')
 tasks=sorted(tasks or {r['task_id']for r in rows});seeds=sorted(seeds or {r['seed']for r in rows});arms=sorted({r['arm']for r in rows})
 lookup={(r['task_id'],r['seed'],r['arm']):r for r in rows}
 require(len(lookup)==len(rows),'Duplicate task/seed/arm')
 require(set(lookup)==set(itertools.product(tasks,seeds,arms)),'Unbalanced task/seed/arm grid')
 return tasks,seeds,arms,lookup

def solo_report(primary,solo,primary_ledger,solo_ledger,repetitions=5000,expected_tasks=24,expected_seeds=3):
 inputs={};entries=read(primary_ledger,inputs)+read(solo_ledger,inputs)
 require(len({e['name']for e in entries})==len(entries),'Duplicate ledger identities')
 require(all(e.get('verified')is True and e.get('valid_for_aggregation')is True and e.get('returncode')==0 and e.get('fresh_v2')is True for e in entries),'Unverified/legacy ledger entry')
 paths=list(map(Path,primary+solo));labels={str(p.resolve()):'supplemental'for p in map(Path,solo)}
 rows,cohorts,dataset=ag.load_cohorts(paths,'arithmetic',labels,expected_tasks,expected_seeds,entries)
 for path in paths:
  for name in ('metadata.json','summary.json'):inputs[reference(path/name)]=sha(path/name)
 for row in rows:check_cost(row)
 report=ag.report_for(rows,cohorts,dataset,'arithmetic',repetitions)
 report.update(input_sha256=inputs,scope='Primary arithmetic plus separately frozen supplemental solo; shared task/seed labels enable descriptive paired contrasts. Separate execution schedules/source variants are retained; no causal or fleet-throughput inference.',protocol_roles={'primary':[reference(p)for p in primary],'supplemental':[reference(p)for p in solo]},source_variants=sorted({c['source_commit']for c in cohorts}))
 return report

def lineage(events,tasks):
 """Replay proof provenance; model reviews remain explicitly unverified suggestions."""
 nodes={};reviews=set();edges=[];selections=[];selected=None;program_codes={};evaluations=[]
 ids=[e['event_id']for e in events if 'event_id'in e]
 require(not ids or len(ids)==len(events)and ids==list(range(1,len(events)+1)),'Trace event sequence differs')
 for e in events:
  kind=e.get('type')
  if kind=='run_start'and 'task'in e:
   task=tasks.get(e['task'].get('id'));require(task is not None and(e['task']==task or e['task']=={k:v for k,v in task.items()if k!='split'}),'Worker task differs from pinned graph')
  elif kind in ('candidate','derived_candidate'):
   name=e.get('id');parents=e.get('parents',[]);review_ids=e.get('review_ids',[])
   require(name and name not in nodes and set(parents)<=nodes.keys()and set(review_ids)<=reviews,'Missing/forward/duplicate lineage source')
   task=tasks[e['puzzle_id']];proof=verify_assignment(task,e.get('payload'));require(proof==e.get('verification'),'Assignment proof mismatch')
   if e.get('sha256'):require(hashlib.sha256(canonical_json(e.get('payload')).encode()).hexdigest()==e['sha256'],'Candidate payload SHA mismatch')
   nodes[name]=dict(id=name,kind=kind,origin=e.get('origin','derived'if kind=='derived_candidate'else'model'),operation=e.get('operation'),verification=proof,duplicate_of=e.get('duplicate_of'),payload=e.get('payload'),ballot=e.get('ballot'),verified_elapsed_seconds=e.get('verified_elapsed_seconds'),model_calls=e.get('model_calls'))
   if e.get('duplicate_of'):require(e['duplicate_of']in nodes and e['duplicate_of']!=name,'Unknown duplicate source')
   edges.extend(dict(source=p,target=name,relation='parent')for p in parents);edges.extend(dict(source=p,target=name,relation='review_guidance')for p in review_ids)
  elif kind=='review':
   name=e.get('id');sources=[e.get('reviewer_candidate_id')]+e.get('target_ids',[])
   require(name and name not in nodes and all(s in nodes for s in sources),'Review source missing')
   require(e.get('verified_fact')is False,'Review must not be represented as a verified fact')
   nodes[name]=dict(id=name,kind='review',verified_fact=False,valid_schema=e.get('valid_schema'),payload=e.get('payload'),ballot=e.get('ballot'),verified_elapsed_seconds=e.get('verified_elapsed_seconds'),model_calls=e.get('model_calls'));reviews.add(name)
   nodes[name].update(reviewer_candidate_id=e['reviewer_candidate_id'],target_ids=e.get('target_ids',[]),completed_elapsed_seconds=e.get('completed_elapsed_seconds'))
   edges.append(dict(source=e['reviewer_candidate_id'],target=name,relation='reviewer'));edges.extend(dict(source=s,target=name,relation='review_target')for s in e.get('target_ids',[]))
  elif kind=='selection':
   survivors=e.get('survivor_ids',[]);pruned=e.get('pruned_ids',[])
   require(set(survivors+pruned)<=nodes.keys()and not set(survivors)&set(pruned),'Invalid selection lineage');selections.append(e)
  elif kind=='reward'and e.get('solved'):
   require(e.get('node_id')in nodes and nodes[e['node_id']].get('verification',{}).get('solved')is True,'Reward without preceding exact proof')
  elif kind=='program_candidate':
   require(selected is None,'Program proposed after selection');name='program-'+str(e['index']);parent=e.get('parent_index')
   require(name not in nodes and(parent is None or'program-'+str(parent)in nodes),'Program parent missing/duplicate')
   require(hashlib.sha256(e['code'].encode()).hexdigest()==e['code_sha256'],'Program source hash mismatch')
   nodes[name]=dict(id=name,kind=kind,chain=e['chain'],code_sha256=e['code_sha256'],parse_error=e.get('parse_error'));program_codes[e['index']]=e['code_sha256']
   if parent is not None:edges.append(dict(source='program-'+str(parent),target=name,relation='own_previous_program'))
  elif kind=='development_candidate_scored':
   name='program-'+str(e['candidate_index']);require(name in nodes,'Development score has no program');nodes[name]['development_score']={k:e.get(k)for k in ('solved','penalty','feedback')}
  elif kind=='program_selected':
   require(selected is None and e.get('evaluation_seen')is False and program_codes.get(e['candidate_index'])==e['code_sha256'],'Program selection freeze mismatch');selected=e;nodes['program-'+str(e['candidate_index'])]['selected']=True
  elif kind=='request_start':require(selected is None,'Model request after final program selection')
  elif kind=='program_grade_end':
   task=tasks[e['task_id']];report=e['report']
   require(report.get('grading_authority')=='outer_parent'and report.get('oracle_sent_to_child')is False and report.get('cleanup_ok')is True and report.get('provenance')!='infrastructure','Program grade authority/cleanup invalid')
   require(e['code_sha256']==program_codes.get(e['candidate_index'])and e['graph_sha256']==graph_digest(task),'Program/graph identity mismatch')
   if e['phase']=='evaluation':require(selected and e['candidate_index']==selected['candidate_index']and e['code_sha256']==selected['code_sha256'],'Evaluation before selection or changed program')
   proof=verify_assignment(task,report.get('candidate_output'))if report.get('proof')is not None else None
   require(proof==report.get('proof'),'Program proof replay mismatch')
   if report.get('solved'):require(proof and proof['solved']and report.get('status')=='passed'and report.get('input_unchanged')is True,'False-positive program proof')
   evaluations.append(dict(task_id=task['id'],phase=e['phase'],solved=report.get('solved')is True,code_sha256=e['code_sha256'],report=report))
 return dict(nodes=list(nodes.values()),edges=edges,selections=selections,selected_program=selected,program_grades=evaluations,scope='Lineage DAG, not proof that a parent/review caused improvement; derived consensuses are not model samples.')

def csp_reports(paths,repetitions=5000,allow_limited_seeds=False):
 groups=defaultdict(list);inputs={};all_lineages={};dataset_path=HERE/'datasets/csp-v1/tasks.json';dataset=read(dataset_path,inputs);public={t['id']:t for t in dataset['tasks']}
 for path in map(Path,paths):
  meta=read(path/'metadata.json',inputs);source=source_complete(meta);require(meta['split']=='evaluation','Development CSP belongs in a separate report')
  require(source['sha256']['csp_tasks.py']==sha(HERE/'csp_tasks.py'),'Exact graph verifier source unavailable')
  require(source['sha256']['datasets/csp-v1/tasks.json']==meta['dataset_sha256']==sha(dataset_path),'CSP public dataset source mismatch')
  rows=read(path/'summary.json',inputs);require(len(rows)==meta['planned_cases']==meta['completed_cases']and all(r.get('case_valid')is True for r in rows),'CSP case matrix incomplete/invalid')
  cases={(c['task_id'],c['arm'],c['seed']):c for c in meta['cases']};require(set(cases)=={(r['task_id'],r['arm'],r['seed'])for r in rows}and len(cases)==len(rows),'CSP planned/observed grid differs')
  for row in rows:
   check_cost(row);case=cases[row['task_id'],row['arm'],row['seed']];require(case['task_id']in public and case['task']==worker_task(public[case['task_id']]),'Worker case differs from pinned public graph');trace=path/Path(row['events']).name;events=records(trace,inputs);check_usage(events,row);tree=lineage(events,{case['task_id']:case['task']});tree['case_outcome']={k:row.get(k)for k in ('solved','status','deadline','time_to_verified_solution_seconds')};all_lineages[reference(trace)]=tree
   require(not row['solved']or any(n.get('verification',{}).get('solved')for n in tree['nodes']),'Summary solved without proof');row=dict(row,cohort=reference(path));groups[meta['profile']].append((row,meta,source))
 reports={}
 for profile,items in groups.items():
  rows=[v[0]for v in items];tasks,seeds,arms,_=unique_grid(rows);first=items[0][1];planned=first['recipe']['splits_and_seeds']['evaluation']
  require(set(seeds)<=set(planned)and(allow_limited_seeds or set(seeds)==set(planned)),'Profile seed plan incomplete; explicitly allow limited complete cohorts')
  require(all(meta['recipe']==first['recipe']and meta['dataset_sha256']==first['dataset_sha256']and meta['selection_sha256']==first['selection_sha256']and source==items[0][2]for _,meta,source in items),'Profile recipe/data/source variants cannot be pooled')
  require(set(arms)==set(first['recipe']['arms'])and set(tasks)=={t['id']for t in public.values()if t['split']=='evaluation'},'Profile arm/task coverage differs')
  cohorts=[dict(directory=reference(p),source_commit=m['source_before']['revision'],source_hashes=m['source_before']['sha256'],runtime=m['runtime'],configuration=m['recipe'],mixed_arm_queue_wall_seconds=m['batch_wall_seconds'])for p in map(Path,paths)if(m:=read(p/'metadata.json',inputs))['profile']==profile]
  result=ag.report_for(rows,cohorts,first['dataset_sha256'],'csp '+profile,repetitions);result.update(profile=profile,planned_seeds=planned,completed_seeds=seeds,limited_seed_plan=set(seeds)!=set(planned),input_sha256=inputs,scope='Separate CSP profile; complete provided cohorts only, task-cluster intervals retain all observed seeds. Budgets/thinking profiles never pooled; no mixed-queue per-arm throughput inference.')
  deadline=first['recipe'].get('deadline_seconds',180)
  if deadline not in ag.TIMES:
   for arm in arms:
    selected=[row for row in rows if row['arm']==arm];proofs=[row.get('time_to_verified_solution_seconds')for row in selected if row['solved']and finite(row.get('time_to_verified_solution_seconds'))]
    result['success_by_time'].append(dict(arm=arm,seconds=deadline,solved_by_time=sum(t<=deadline for t in proofs),cases=len(selected),fraction=sum(t<=deadline for t in proofs)/len(selected),missing_solved_proof_times=sum(row['solved']for row in selected)-len(proofs)))
  reports[profile]=result
 return reports,all_lineages

def crossed_program_statistics(rows,repetitions=5000,seed=20261115):
 tasks,seeds,arms,lookup=unique_grid(rows);rng=random.Random(seed);samples={a:[]for a in arms};differences={(a,b):[]for a,b in itertools.combinations(arms,2)}
 for _ in range(repetitions):
  tt=rng.choices(tasks,k=len(tasks));ss=rng.choices(seeds,k=len(seeds));point={a:statistics.mean(lookup[t,s,a]['solved']for t in tt for s in ss)for a in arms}
  for a in arms:samples[a].append(point[a])
  for a,b in differences:differences[a,b].append(point[a]-point[b])
 def interval(values):return[ag.quantile(values,.025),ag.quantile(values,.975)]
 output=[]
 for arm in arms:
  means=[statistics.mean(lookup[t,s,arm]['solved']for s in seeds)for t in tasks];conditional=ag.cluster_ci(means,repetitions,seed)
  output.append(dict(arm=arm,tasks=len(tasks),training_seeds=len(seeds),cases=len(tasks)*len(seeds),solved=sum(lookup[t,s,arm]['solved']for t in tasks for s in seeds),accuracy=statistics.mean(means),task_cluster95_conditional_frozen_programs=list(conditional),crossed_task_training_seed95=interval(samples[arm])))
 paired=[dict(arm_a=a,arm_b=b,accuracy_delta=statistics.mean(lookup[t,s,a]['solved']-lookup[t,s,b]['solved']for t in tasks for s in seeds),crossed_task_training_seed95=interval(values))for(a,b),values in differences.items()]
 return dict(arms=output,paired_deltas=paired,bootstrap=dict(repetitions=repetitions,seed=seed,axes='Independent resampling of graph tasks and paired training-seed labels; Cartesian outcomes, shared draws across arms'),scope='Four-training-seed-limited exploratory intervals. Task-only CI is conditional on frozen programs; crossed bootstrap includes empirical training-seed variation. Forty-eight graph/seed outcomes are not independent tasks.')

def program_report(path,repetitions=5000):
 path=Path(path);inputs={};meta=read(path/'metadata.json',inputs);source=source_complete(meta,True);require(source['sha256']['csp_tasks.py']==sha(HERE/'csp_tasks.py'),'Exact graph verifier source unavailable')
 development=read(path/'development-inputs.json',inputs);evaluation=read(path/'evaluation-inputs.json',inputs);tasks_list=development+evaluation;tasks={t['id']:t for t in tasks_list};dataset_path=HERE/'datasets/csp-v1/tasks.json';public=read(dataset_path,inputs);require(meta['dataset_sha256']==source['sha256']['datasets/csp-v1/tasks.json']==sha(dataset_path)and tasks=={t['id']:worker_task(t)for t in public['tasks']}and len(tasks_list)==len(tasks)and len(development)==meta['development_tasks']==4 and len(evaluation)==meta['evaluation_tasks']==12,'Program graph inputs differ from pinned public corpus');episodes=read(path/'results.json',inputs)
 require(len(episodes)==meta['recorded_episodes']==meta['completed_programs']==meta['planned_selected_programs']==8 and all(e.get('complete')is True and e.get('status')=='complete'and e.get('calls')==16 for e in episodes),'Program episodes incomplete')
 expected={(arm,pair['seed'])for pair in meta['pairs']for arm in pair['arms']};require(len(expected)==8 and len({p['seed']for p in meta['pairs']})==4 and{(e['arm'],e['seed'])for e in episodes}==expected,'Program arm/training-seed grid differs');evaluation_ids={t['id']for t in evaluation};require(evaluation_ids=={t['id']for t in public['tasks']if t['split']=='evaluation'}and{t['id']for t in development}=={t['id']for t in public['tasks']if t['split']=='development'},'Program development/evaluation partition differs')
 graph_rows=[];trees={}
 for episode in episodes:
  check_cost(episode);directory=path/f"seed-{episode['seed']}-{episode['arm']}";require(read(directory/'result.json',inputs)==episode,'Episode summary differs')
  trace=directory/'events.jsonl';events=records(trace,inputs);check_usage(events,episode);tree=lineage(events,tasks);trees[reference(trace)]=tree;selected=read(directory/'selection.json',inputs)
  require(episode.get('grading_calls')==len(tree['program_grades']),'Program grader call accounting differs')
  require(episode.get('training_candidates_scored')==16 and len([n for n in tree['nodes']if n['kind']=='program_candidate'])==16 and tree['selected_program'].get('model_calls_at_selection')==16,'Program16-candidate training allocation differs')
  inputs[reference(directory/'selected.py')]=sha(directory/'selected.py');require(sha(directory/'selected.py')==episode['selected_sha256']==selected['code_sha256']==tree['selected_program']['code_sha256'],'Frozen selected code differs')
  grades=[g for g in tree['program_grades']if g['phase']=='evaluation'];require(len(grades)==episode['evaluation_completed']==12 and{g['task_id']for g in grades}==evaluation_ids,'Program evaluation graph grid incomplete')
  for grade in grades:
   stored=read(directory/f"evaluation-{grade['task_id']}.json",inputs);require(stored['selected_sha256']==selected['code_sha256']and stored['report']==grade['report'],'Program evaluation artifact differs');graph_rows.append(dict(task_id=grade['task_id'],seed=episode['seed'],arm=episode['arm'],solved=grade['solved']))
 training_costs=[]
 for arm in sorted({e['arm']for e in episodes}):
  selected=[e for e in episodes if e['arm']==arm];known=[e for e in selected if e.get('server_cost_known')is True]
  training_costs.append(dict(arm=arm,selected_programs=len(selected),model_calls=sum(e['calls']for e in selected),prompt_tokens=sum(e['prompt_tokens']for e in selected),completion_tokens=sum(e['completion_tokens']for e in selected),client_cost_is_lower_bound=any(e.get('client_usage_complete')is not True for e in selected),known_server_episodes=len(known),unknown_server_episodes=len(selected)-len(known),server_prompt_tokens_known=sum(e['server_prompt_tokens']for e in known)if known else None,server_completion_tokens_known=sum(e['server_completion_tokens']for e in known)if known else None,remote_solver_cpu_seconds=None))
 result=crossed_program_statistics(graph_rows,repetitions);result['training_costs']=training_costs;result.update(input_sha256=inputs,source=source,episodes=episodes,dataset_sha256=meta['dataset_sha256'],cost_scope='Training calls/tokens/server counters attributed once per selected-program episode; per-graph CPU grading separate. No remote solver CPU measurement; never multiply training usage by12graphs. Episode worker wall excludes final endpoint drain; mixed master wall includes qualification/scheduling/parallel episodes and drain, never per-arm fleet throughput.',source_files=meta['source']['sha256'],mixed_episode_master_wall_seconds=meta.get('wall_seconds'))
 return result,trees

def mermaid(tree):
 mapping={n['id']:'n'+str(i)for i,n in enumerate(tree['nodes'])};lines=['flowchart TD']
 for node in tree['nodes']:
  label=' / '.join(str(node.get(k,''))for k in('id','kind','operation')).replace('"',"'").replace('\n',' ')[:160];lines.append('  '+mapping[node['id']]+'["'+label+'"]')
 for edge in tree['edges']:lines.append('  '+mapping[edge['source']]+' -->|'+edge['relation']+'| '+mapping[edge['target']])
 return '\n'.join(lines)+'\n'

def save_report(path,report,plot=False):
 path.mkdir(parents=True,exist_ok=False);(path/'analysis.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
 for name,key in [('summary','arms'),('paired-deltas','paired_deltas'),('paired-cases','paired_cases'),('success-by-time','success_by_time'),('training-costs','training_costs')]:
  if report.get(key):ag.csv_out(path/(name+'.csv'),report[key])
 table=['| Method | Solved | Accuracy | 95% interval |','|---|---:|---:|---:|']
 for row in report['arms']:
  interval=[row['cluster95_low'],row['cluster95_high']]if 'cluster95_low'in row else row['crossed_task_training_seed95']
  table.append(f"| {LABELS.get(row['arm'].split('/')[-1],row['arm'])} | {row['solved']}/{row['cases']} | {row['accuracy']:.1%} | {interval[0]:.1%}–{interval[1]:.1%} |")
 if report.get('training_costs'):
  table+=['','Training is charged once per frozen program, separate from graph evaluation.','', '| Method | Model calls | Client prompt / completion | Known server completion | Coverage |','|---|---:|---:|---:|---:|']
  for row in report['training_costs']:table.append(f"| {LABELS.get(row['arm'],row['arm'])} | {row['model_calls']} | {row['prompt_tokens']} / {row['completion_tokens']} | {row['server_completion_tokens_known']} | {row['known_server_episodes']}/{row['selected_programs']} |")
 else:
  table+=['','| Method | Calls | Client completion | Known server completion | Coverage | Median / p95 case wall s |','|---|---:|---:|---:|---:|---:|']
  for row in report['arms']:
   lower='*'if row['client_cost_is_lower_bound']else''
   table.append(f"| {LABELS.get(row['arm'].split('/')[-1],row['arm'])} | {row['calls']} | {row['completion_tokens']}{lower} | {row['server_completion_tokens_known']} | {row['server_cost_known_cases']}/{row['cases']} | {row['median_occupied_case_wall_seconds']:.3f} / {row['p95_occupied_case_wall_seconds']:.3f} |")
  table+=['','* Client completion usage with cancelled/missing responses is a lower bound. Known server totals cover only the indicated cases; unknowns are not zeros.']
 (path/'REPORT.md').write_text('\n'.join(table)+'\n\n'+report['scope']+'\n')
 if plot:
  if 'domain'in report:ag.plots(report,path)
  else:
   import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
   fig,ax=plt.subplots(figsize=(9,4))
   for i,row in enumerate(report['arms']):
    lo,hi=row['crossed_task_training_seed95'];ax.errorbar(row['accuracy']*100,i,xerr=[[100*(row['accuracy']-lo)],[100*(hi-row['accuracy'])]],fmt='o',capsize=4)
   ax.set(yticks=list(range(len(report['arms']))),yticklabels=[LABELS.get(r['arm'],r['arm'])for r in report['arms']],xlim=(-2,102),xlabel='Evaluation graph success (%); crossed task/training-seed95%',title='Frozen reusable programs; four training seeds, fixed graph scope');fig.tight_layout()
   for suffix in ('svg','png'):fig.savefig(path/('accuracy-crossed95.'+suffix),dpi=180)
   plt.close(fig)

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--kind',choices=('solo','csp','program'),default='solo');parser.add_argument('inputs',nargs='*',type=Path);parser.add_argument('--run',action='store_true');parser.add_argument('--output',type=Path);parser.add_argument('--plot',action='store_true');parser.add_argument('--repetitions',type=int,default=5000);parser.add_argument('--allow-limited-seeds',action='store_true');args=parser.parse_args(argv)
 require(args.repetitions>=100,'At least100 bootstrap repetitions required for real reporting')
 if not args.run:print(json.dumps(dict(mode='plan',kind=args.kind,inputs=[str(p)for p in args.inputs],repetitions=args.repetitions,plot=args.plot,required_gate='Final verified45 throughput via reference_worker.verify_gate; no source or outcome read in plan mode'),indent=2));return 0
 gate=verify_gate(HERE);require(args.output is not None and not args.output.exists(),'New output directory required');trees={}
 if args.kind=='solo':reports={'solo-comparison':solo_report([HERE/f'results/evaluation-v2/arithmetic-s{s}'for s in(1,2,3)],[HERE/f'results/solo-control-v2/evaluation-s{s}'for s in(1,2,3)],HERE/'runs/evaluation-v2-ledger.json',HERE/'runs/solo-control-v2-ledger.json',args.repetitions)}
 elif args.kind=='csp':require(args.inputs,'Provide complete CSP evaluation cohort directories');reports,trees=csp_reports(args.inputs,args.repetitions,args.allow_limited_seeds)
 else:require(len(args.inputs)==1,'Provide one complete program master directory');report,trees=program_report(args.inputs[0],args.repetitions);reports={'programs':report}
 args.output.mkdir(parents=True,exist_ok=False)
 for name,report in reports.items():save_report(args.output/name,report,args.plot)
 lineage_index={}
 for index,(trace,tree)in enumerate(trees.items()):
  name=f'lineage-{index:04d}';(args.output/(name+'.json')).write_text(json.dumps(tree,indent=2)+'\n');(args.output/(name+'.mmd')).write_text(mermaid(tree));lineage_index[trace]=name
 (args.output/'lineage-index.json').write_text(json.dumps(lineage_index,indent=2)+'\n')
 manifest=dict(mode='completed-offline-report',gate=gate,original_benchmark_files_modified=False,coding_grade_policy='Original frozen coding grades and later independent confirmation are separate report sections/datasets; never pooled or silently replaced',source_sha256={name:sha(HERE/name)for name in ['report_completed_studies.py','test_report_completed_studies.py','aggregate_evaluation.py','export_benchmark.py','csp_tasks.py']},files={str(p.relative_to(args.output)):sha(p)for p in args.output.rglob('*')if p.is_file()})
 (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Wrote complete offline report',args.output);return 0
if __name__=='__main__':raise SystemExit(main())
