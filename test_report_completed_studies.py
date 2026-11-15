"""Synthetic report/provenance/lineage tests only; no real study outcomes or APIs."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import report_completed_studies as r
from csp_tasks import load_tasks

TASK=dict(id='g1',split='evaluation',vertex_count=3,color_count=3,edges=[[0,1],[1,2],[0,2]])

def node(name,values,parents=(),task=TASK,**extra):
 payload={'assignment':values};return dict(type='candidate',id=name,puzzle_id=task['id'],parents=list(parents),payload=payload,verification=r.verify_assignment(task,payload),**extra)

def cost(known=True):
 row=dict(server_idle_after=True,server_cost_known=known,prompt_tokens=10,completion_tokens=20,server_prompt_tokens=10 if known else None,server_completion_tokens=20 if known else None)
 if known:row.update(server_metrics_before=dict(running=0,waiting=0,prompt=100,completion=200),server_metrics_after=dict(running=0,waiting=0,prompt=110,completion=220))
 return row

class ReportTests(unittest.TestCase):
 def test_plan_never_reads_outcomes_or_bootstraps_and_run_gate_precedes_reads(self):
  with patch.object(r,'read',side_effect=AssertionError('No outcome reads')),patch.object(r.ag,'report_for',side_effect=AssertionError('No statistics')),patch.object(r,'verify_gate')as gate,contextlib.redirect_stdout(io.StringIO())as out:
   self.assertEqual(r.main(['--plot']),0);self.assertEqual(json.loads(out.getvalue())['mode'],'plan');gate.assert_not_called()
  with patch.object(r,'verify_gate',side_effect=RuntimeError('Final45 incomplete')),patch.object(r,'solo_report')as load:
   with self.assertRaisesRegex(RuntimeError,'Final45'):r.main(['--run','--output','never'])
   load.assert_not_called()
 def test_source_drain_and_known_unknown_costs_fail_closed(self):
  self.assertTrue(r.check_cost(cost()));self.assertFalse(r.check_cost(cost(False)))
  for change in [dict(server_idle_after=False),dict(server_completion_tokens=19),dict(server_cost_known=False)]:
   row=cost();row.update(change)
   with self.subTest(change=change),self.assertRaises(ValueError):r.check_cost(row)
  identity=dict(revision='fixture',tracked_clean=True,source_files_tracked=True,sha256={'file':'fixed'})
  meta=dict(verified=True,completed_utc='2026-11-15T00:00:00Z',source_before=identity,source_after=copy.deepcopy(identity),incomplete=False,source_changed_during_run=False,initial_idle_checks=[dict(idle=True)]*4)
  self.assertEqual(r.source_complete(meta),identity)
  for fault in ('source','drain','verified','completion'):
   broken=copy.deepcopy(meta)
   if fault=='source':broken['source_after']['sha256']['file']='changed'
   elif fault=='drain':broken['initial_idle_checks'][0]['idle']=None
   elif fault=='verified':broken['verified']=False
   else:broken['incomplete']=True
   with self.assertRaises(ValueError):r.source_complete(broken)
 def test_request_accounting_rejects_duplicate_missing_and_bool_usage(self):
  events=[dict(type='request_start',request_id='a'),dict(type='request_end',request_id='a',usage=dict(prompt_tokens=10,completion_tokens=20))]
  row=dict(calls=1,completed_calls=1,unfinished_calls=0,prompt_tokens=10,completion_tokens=20)
  self.assertTrue(r.check_usage(events,row))
  for broken in [events+[events[0]],events[1:],copy.deepcopy(events)]:
   if len(broken)==2:broken[1]['usage']['prompt_tokens']=True
   with self.assertRaises(ValueError):r.check_usage(broken,row)
 def test_dag_preserves_all_parents_review_roles_ballot_and_selection(self):
  events=[node('a',[0,1,2]),node('b',[1,2,0]),dict(type='review',id='review',reviewer_candidate_id='b',target_ids=['a'],verified_fact=False,valid_schema=True,payload={'critique':'authored fixture'})]
  child=node('consensus',[0,1,2],['a','b'],review_ids=['review'],operation='consensus',origin='derived',model_calls=0,ballot={'source_ids':['a','b']});child['type']='derived_candidate';events+=[child,dict(type='selection',generation=1,survivor_ids=['consensus'],pruned_ids=['a','b'])]
  tree=r.lineage(events,{'g1':TASK});edges={(e['source'],e['target'],e['relation'])for e in tree['edges']}
  self.assertIn(('a','consensus','parent'),edges);self.assertIn(('b','consensus','parent'),edges);self.assertIn(('review','consensus','review_guidance'),edges);self.assertIn(('b','review','reviewer'),edges);self.assertIn(('a','review','review_target'),edges)
  derived=next(n for n in tree['nodes']if n['id']=='consensus');self.assertEqual(derived['model_calls'],0);self.assertEqual(derived['ballot']['source_ids'],['a','b']);self.assertNotIn('wrong',next(n for n in tree['nodes']if n['id']=='a'));self.assertIn('flowchart TD',r.mermaid(tree))
 def test_forward_refs_false_proofs_and_verified_review_claim_rejected(self):
  cases=[[node('b',[0,1,2],['missing'])],[dict(type='reward',node_id='missing',solved=True)],[node('a',[0,0,0])]]
  cases[-1][0]['verification']['solved']=True
  cases.append([node('a',[0,1,2]),dict(type='review',id='review',reviewer_candidate_id='a',target_ids=[],verified_fact=True)])
  for events in cases:
   with self.assertRaises(ValueError):r.lineage(events,{'g1':TASK})
 def test_program_selection_freezes_before_evaluation_and_no_postselection_calls(self):
  code='def solve(n,k,edges): return {"assignment":[0,1,2]}'
  digest=hashlib.sha256(code.encode()).hexdigest();payload={'assignment':[0,1,2]};proof=r.verify_assignment(TASK,payload)
  events=[dict(type='program_candidate',index=0,chain=0,parent_index=None,code=code,code_sha256=digest),dict(type='program_selected',candidate_index=0,code_sha256=digest,evaluation_seen=False),dict(type='program_grade_end',task_id='g1',phase='evaluation',candidate_index=0,code_sha256=digest,graph_sha256=r.graph_digest(TASK),report=dict(grading_authority='outer_parent',oracle_sent_to_child=False,cleanup_ok=True,provenance='candidate',proof=proof,candidate_output=payload,solved=True,status='passed',input_unchanged=True))]
  tree=r.lineage(events,{'g1':TASK});self.assertTrue(tree['nodes'][0]['selected']);self.assertTrue(tree['program_grades'][0]['solved'])
  for broken in [events[:1]+events[2:],events+[dict(type='request_start')]]:
   with self.assertRaises(ValueError):r.lineage(broken,{'g1':TASK})
 def test_crossed_bootstrap_exposes_shared_program_seed_dependence(self):
  rows=[dict(task_id=t,seed=s,arm=a,solved=a=='always'or s==1)for t in ('g1','g2','g3')for s in (1,2)for a in ('variable','always')]
  result=r.crossed_program_statistics(rows,200);variable=next(a for a in result['arms']if a['arm']=='variable')
  self.assertEqual(variable['accuracy'],.5);self.assertEqual(variable['task_cluster95_conditional_frozen_programs'],[.5,.5]);self.assertEqual(variable['crossed_task_training_seed95'],[0,1]);self.assertEqual(result,r.crossed_program_statistics(rows,200));self.assertEqual(result['paired_deltas'][0]['accuracy_delta'],.5)
  with self.assertRaisesRegex(ValueError,'Duplicate'):r.crossed_program_statistics(rows+rows[:1],100)
  with self.assertRaisesRegex(ValueError,'Unbalanced'):r.crossed_program_statistics(rows[1:],100)
 def test_csp_profiles_stay_separate_and_missing_seed_plan_is_explicit(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);(root/'datasets/csp-v1').mkdir(parents=True);tasks=[TASK,dict(TASK,id='g2',vertex_count=4)];dataset=root/'datasets/csp-v1/tasks.json';dataset.write_text(json.dumps({'protocol':'planted-coloring-csp-v1','generator':{},'tasks':tasks}));(root/'csp_tasks.py').write_text('# fixture source marker')
   identity=dict(revision='fixture',tracked_clean=True,source_files_tracked=True,sha256={'csp_tasks.py':r.sha(root/'csp_tasks.py'),'datasets/csp-v1/tasks.json':r.sha(dataset)});paths=[]
   for profile in ('off16','off64'):
    path=root/profile;path.mkdir();paths.append(path);rows=[];cases=[]
    for task in load_tasks(dataset,'evaluation'):
     self.assertNotIn('split',task);self.assertNotEqual(task,next(t for t in tasks if t['id']==task['id']))
     for arm in ('resample','sequential'):
      trace=path/(task['id']+'-'+arm+'.jsonl');candidate=node('a',[i%3 for i in range(task['vertex_count'])],task=task)
      events=[dict(type='run_start',task=task),dict(type='request_start',request_id='call'),dict(type='request_end',request_id='call',usage=dict(prompt_tokens=10,completion_tokens=20)),candidate]
      trace.write_text(''.join(json.dumps(e)+'\n'for e in events));rows.append(dict(cost(False),task_id=task['id'],arm=arm,seed=1,events=str(trace),solved=True,calls=1,completed_calls=1,unfinished_calls=0,wall_seconds=1,time_to_verified_solution_seconds=.5,case_valid=True,returncode=0,infrastructure_failures=0));cases.append(dict(task_id=task['id'],arm=arm,seed=1,task=task))
    meta=dict(verified=True,completed_utc='2026-11-15T00:00:00Z',source_before=identity,source_after=identity,incomplete=False,source_changed_during_run=False,initial_idle_checks=[dict(idle=True)]*4,split='evaluation',profile=profile,dataset_sha256=r.sha(dataset),selection_sha256='selection',planned_cases=4,completed_cases=4,cases=cases,recipe=dict(max_calls=16 if profile=='off16'else 64,arms=['resample','sequential'],splits_and_seeds={'evaluation':[1]}),runtime={},batch_wall_seconds=2)
    (path/'metadata.json').write_text(json.dumps(meta));(path/'summary.json').write_text(json.dumps(rows))
   with patch.object(r,'HERE',root):
    reports,trees=r.csp_reports(paths,100);self.assertEqual(set(reports),{'off16','off64'});self.assertEqual(len(trees),8);self.assertTrue(all(a['cases']==2 for report in reports.values()for a in report['arms']))
    meta=json.loads((paths[0]/'metadata.json').read_text());original=copy.deepcopy(meta)
    meta['cases'][0]['task']=copy.deepcopy(TASK);(paths[0]/'metadata.json').write_text(json.dumps(meta))
    with self.assertRaisesRegex(ValueError,'Worker case differs'):r.csp_reports(paths[:1],100)
    meta=copy.deepcopy(original);meta['cases'][0]['task']['edges']=[[0,1]];(paths[0]/'metadata.json').write_text(json.dumps(meta))
    with self.assertRaisesRegex(ValueError,'Worker case differs'):r.csp_reports(paths[:1],100)
    meta=original;meta['recipe']['splits_and_seeds']['evaluation']=[1,2];(paths[0]/'metadata.json').write_text(json.dumps(meta))
    with self.assertRaisesRegex(ValueError,'seed plan incomplete'):r.csp_reports(paths[:1],100)
    limited,_=r.csp_reports(paths[:1],100,True);self.assertTrue(limited['off16']['limited_seed_plan']);self.assertEqual(limited['off16']['completed_seeds'],[1])
 def test_complete_program_adapter_preserves_training_cost_separate_from_graphs(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);(root/'datasets/csp-v1').mkdir(parents=True);dataset=root/'datasets/csp-v1/tasks.json';tasks=[dict(TASK,id=('dev'if i<4 else'eval')+str(i),split='development'if i<4 else'evaluation',vertex_count=3+i)for i in range(16)];dataset.write_text(json.dumps({'protocol':'planted-coloring-csp-v1','generator':{},'tasks':tasks}));(root/'csp_tasks.py').write_text('# fixture source marker')
   identity=dict(revision='fixture',tracked_clean=True,source_files_tracked=True,sha256={'csp_tasks.py':r.sha(root/'csp_tasks.py'),'datasets/csp-v1/tasks.json':r.sha(dataset)});path=root/'program';path.mkdir();development=load_tasks(dataset,'development');evaluation=load_tasks(dataset,'evaluation');self.assertTrue(all('split'not in task for task in development+evaluation))
   for name,data in [('development-inputs',development),('evaluation-inputs',evaluation)]:(path/(name+'.json')).write_text(json.dumps(data))
   episodes=[];arms=['sequential16','independent4'];pairs=[dict(seed=seed,arms=arms)for seed in range(1,5)]
   def grade_event(task,phase,index,digest):
    payload={'assignment':[i%3 for i in range(task['vertex_count'])]};proof=r.verify_assignment(task,payload)
    return dict(type='program_grade_end',task_id=task['id'],phase=phase,candidate_index=index,code_sha256=digest,graph_sha256=r.graph_digest(task),report=dict(grading_authority='outer_parent',oracle_sent_to_child=False,cleanup_ok=True,provenance='candidate',proof=proof,candidate_output=payload,solved=True,status='passed',input_unchanged=True))
   for pair in pairs:
    for arm in arms:
     episode=path/f"seed-{pair['seed']}-{arm}";episode.mkdir();events=[];code='def solve(n,k,edges): return {"assignment":[i%k for i in range(n)]}';digest=hashlib.sha256(code.encode()).hexdigest()
     for index in range(16):
      width=1 if arm=='sequential16'else 4;events+=[dict(type='request_start',request_id=str(index)),dict(type='request_end',request_id=str(index),usage=dict(prompt_tokens=1,completion_tokens=2)),dict(type='program_candidate',index=index,chain=index%width,parent_index=index-width if index>=width else None,code=code,code_sha256=digest)]
      events += [grade_event(task,'development',index,digest)for task in development];events.append(dict(type='development_candidate_scored',candidate_index=index,solved=4,penalty=0,feedback=[]))
     selected=dict(type='program_selected',candidate_index=0,code_sha256=digest,evaluation_seen=False,model_calls_at_selection=16);events.append(selected)
     for task in evaluation:
      event=grade_event(task,'evaluation',0,digest);events.append(event);(episode/f"evaluation-{task['id']}.json").write_text(json.dumps(dict(selected_sha256=digest,report=event['report'])))
     (episode/'events.jsonl').write_text(''.join(json.dumps(e)+'\n'for e in events));(episode/'selected.py').write_text(code);(episode/'selection.json').write_text(json.dumps(selected))
     row=dict(cost(False),seed=pair['seed'],arm=arm,complete=True,status='complete',calls=16,completed_calls=16,unfinished_calls=0,prompt_tokens=16,completion_tokens=32,client_usage_complete=True,selected_sha256=digest,evaluation_completed=12,training_candidates_scored=16,grading_calls=76);episodes.append(row);(episode/'result.json').write_text(json.dumps(row))
   meta=dict(verified=True,complete=True,completed_utc='2026-11-15T00:00:00Z',source=identity,source_after=identity,initial_idle_checks=[dict(idle=True)]*4,planned_selected_programs=8,recorded_episodes=8,completed_programs=8,development_tasks=4,evaluation_tasks=12,pairs=pairs,dataset_sha256=r.sha(dataset));(path/'metadata.json').write_text(json.dumps(meta));(path/'results.json').write_text(json.dumps(episodes))
   with patch.object(r,'HERE',root):
    result,trees=r.program_report(path,100)
    (path/'development-inputs.json').write_text(json.dumps(tasks[:4]))
    with self.assertRaisesRegex(ValueError,'Program graph inputs differ'):r.program_report(path,100)
    (path/'development-inputs.json').write_text(json.dumps(development+[development[0]]))
    with self.assertRaisesRegex(ValueError,'Program graph inputs differ'):r.program_report(path,100)
   self.assertEqual(len(trees),8);self.assertEqual([x['cases']for x in result['arms']],[48,48]);self.assertEqual([x['model_calls']for x in result['training_costs']],[64,64]);self.assertEqual([x['completion_tokens']for x in result['training_costs']],[128,128]);self.assertTrue(all(x['server_completion_tokens_known']is None for x in result['training_costs']))
 def fixture_solo(self,root,role,seed):
  path=root/f'{role}-{seed}';path.mkdir();arm='direct'if role=='primary'else'refine';revision=role+'-source'
  rows=[dict(task_id=task,arm=arm,seed=seed,split='evaluation',solved=task=='t1'or role=='solo',calls=1,prompt_tokens=10,completion_tokens=20,wall_seconds=1,time_to_verified_solution_seconds=.5,completed_calls=1,unfinished_calls=0,server_idle_after=True,server_cost_known=False,server_prompt_tokens=None,server_completion_tokens=None,infrastructure_failures=0,returncode=0)for task in ('t1','t2')]
  meta=dict(domain='arithmetic',split='evaluation',seed=seed,git_revision=revision,dataset_sha256='same-dataset',source_hashes={'harness.py':'fixed'},final_source_hashes={'harness.py':'fixed'},source_changed_during_run=False,completed_utc='2026-11-15T00:00:00Z',completed_cases=2,incomplete=False,missing_cases=[],slot_failures=[],batch_wall_seconds=2,cases=[{k:x[k]for k in ('task_id','arm','seed')}for x in rows])
  for name,data in [('metadata',meta),('summary',rows)]:(path/(name+'.json')).write_text(json.dumps(data))
  entry=dict(name=path.name,domain='arithmetic',seed=seed,verified=True,valid_for_aggregation=True,fresh_v2=True,returncode=0,incomplete=False,source_changed=False,completed_utc=meta['completed_utc'],completed_cases=2,source_revision=revision)
  return path,entry
 def test_solo_reuses_task_clusters_and_keeps_control_roles_unknown_costs(self):
  with tempfile.TemporaryDirectory()as folder:
   root=Path(folder);primary=[];solo=[];ledgers={}
   for role in ('primary','solo'):
    entries=[]
    for seed in (1,2,3):
     path,entry=self.fixture_solo(root,role,seed);(primary if role=='primary'else solo).append(path);entries.append(entry)
    ledger=root/(role+'.json');ledger.write_text(json.dumps(entries));ledgers[role]=ledger
   report=r.solo_report(primary,solo,ledgers['primary'],ledgers['solo'],200,2,3)
   self.assertEqual(len(report['arms']),2);self.assertEqual(report['tasks'],2);self.assertEqual(report['seeds'],[1,2,3]);self.assertEqual(report['source_variants'],['primary-source','solo-source']);self.assertEqual(report['paired_deltas'][0]['accuracy_delta'],-.5)
   for row in report['arms']:self.assertIsNone(row['server_completion_tokens_known']);self.assertEqual(row['server_cost_known_cases'],0);self.assertEqual(row['cases'],6)
   entries=json.loads(ledgers['solo'].read_text());entries[0]['verified']=False;ledgers['solo'].write_text(json.dumps(entries))
   with self.assertRaisesRegex(ValueError,'Unverified'):r.solo_report(primary,solo,ledgers['primary'],ledgers['solo'],100,2,3)

if __name__=='__main__':unittest.main()
