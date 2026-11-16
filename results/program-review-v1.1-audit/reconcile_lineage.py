"""Final receipt/file reconciliation and explicitly typed development-only lineage."""
from pathlib import Path
import json,hashlib,datetime
D=Path(__file__).resolve().parent;R=D.parents[1];O=R/'runs/program-review-elites4-v1.1'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
a=read(D/'AUDIT.json');assert a['verified']and a['complete']
assert sha(D/'audit_review.py')==a['auditor_sha256']
for n,h in a['input_sha256'].items():assert sha(R/n)==h
m=read(O/'metadata.json');assert m['limits']==dict(max_model_calls=16,per_call_max_tokens=2048,max_completion_tokens=32768,request_timeout_seconds=210,graph_timeout_seconds=10,memory_limit_mib=256,cpu_limit_per_container=1,episode_deadline_seconds=None)
all_dags=[]
for seed in range(1,5):
 folder=O/f'seed-{seed}-review_elites4';events=[json.loads(l)for l in(folder/'events.jsonl').read_text().splitlines()];nodes=[];edges=[];candidates={e['index']:e for e in events if e['type']=='program_candidate'};reviews={e['review_id']:e for e in events if e['type']=='program_review'}
 starts={e['request_id']:e for e in events if e['type']=='request_start'};ends={e['request_id']:e for e in events if e['type']=='request_end'};assert set(starts)==set(ends)
 for e in events:
  ty=e['type']
  if ty=='request_start':
   nid='call:'+e['request_id'];nodes.append(dict(id=nid,type='model_review_call'if e['stage'].startswith('review-')else'model_author_call',stage=e['stage'],event_id=e['event_id']))
   if e['stage'].startswith('review-'):
    for role,key in [('reviewer','reviewer_candidate_index'),('target','target_candidate_index')]:
     i=e[key];edges.extend([dict(source='program:'+str(i),target=nid,relation=role+'_source_context'),dict(source='fitness:'+str(i),target=nid,relation=role+'_dev_feedback')])
   elif e['previous_candidate_index']is not None:
    i=e['previous_candidate_index'];edges.extend([dict(source='program:'+str(i),target=nid,relation='repair_target_source'),dict(source='fitness:'+str(i),target=nid,relation='repair_target_dev_feedback'),dict(source='critique:'+e['review_id'],target=nid,relation='unverified_peer_critique')])
  elif ty=='program_candidate':
   i=e['index'];start=next(x for x in starts.values()if x['stage']==f'program-{i}');assert e.get('review_id')==start.get('review_id')
   nodes.append(dict(id='program:'+str(i),type='program_source',index=i,source_sha256=e['code_sha256'],parse_error=e['parse_error'],event_id=e['event_id']));edges.append(dict(source='call:'+start['request_id'],target='program:'+str(i),relation='generated_source'))
  elif ty in ['program_grade_end','program_grade_skipped']:
   i=e['candidate_index'];nid=f"grade:{e['phase']}:{i}:{e['task_id']}";nodes.append(dict(id=nid,type='exact_graph_grade'if ty=='program_grade_end'else'parse_rejection_without_execution',phase=e['phase'],task_id=e['task_id'],candidate_index=i,event_id=e['event_id']));edges.append(dict(source='program:'+str(i),target=nid,relation='evaluated_source'))
   if e['phase']=='development':edges.append(dict(source=nid,target='fitness:'+str(i),relation='development_feedback'))
  elif ty=='development_candidate_scored':nodes.append(dict(id='fitness:'+str(e['candidate_index']),type='development_fitness',solved=e['solved'],penalty=e['penalty'],event_id=e['event_id']))
  elif ty=='program_review':
   rid=e['review_id'];stored=read(folder/('review-'+rid+'.json'));assert stored=={k:e[k]for k in ['raw','critique','truncated']};start=next(x for x in starts.values()if x['stage']=='review-'+rid)
   nodes.append(dict(id='critique:'+rid,type='unverified_critique',content_sha256=hashlib.sha256(e['critique'].encode()).hexdigest(),truncated=e['truncated'],event_id=e['event_id']));edges.append(dict(source='call:'+start['request_id'],target='critique:'+rid,relation='generated_critique'))
  elif ty in ['review_population','review_population_selected']:
   nid=ty+':'+str(e['generation']);ids=e.get('candidate_indices',e.get('retained_indices'));nodes.append(dict(id=nid,type=ty,generation=e['generation'],candidate_indices=ids,event_id=e['event_id']))
   for i in ids:edges.append(dict(source='fitness:'+str(i),target=nid,relation='development_rank'))
  elif ty=='program_selected':
   nodes.append(dict(id='selected',type='immutable_selection',candidate_index=e['candidate_index'],source_sha256=e['code_sha256'],event_id=e['event_id']));edges.append(dict(source='program:'+str(e['candidate_index']),target='selected',relation='earliest_development_best'))
 ids={n['id']for n in nodes};assert len(ids)==len(nodes)and all(e['source']in ids and e['target']in ids for e in edges)
 positions={n['id']:n['event_id']for n in nodes};assert all(positions[e['source']]<positions[e['target']]for e in edges)
 assert len([n for n in nodes if n['type']=='model_author_call'])==10 and len([n for n in nodes if n['type']=='model_review_call'])==6
 all_dags.append(dict(seed=seed,nodes=nodes,edges=edges))
with(D/'full-typed-lineage.json').open('x')as f:json.dump(all_dags,f,indent=2);f.write('\n')
a.update(qualification_container_grades=3,total_container_grades_including_qualification=a['counts']['grades']+3,typed_lineage_sha256=sha(D/'full-typed-lineage.json'),raw_review_files_reconciled=24,final_reconciliation_source_sha256=sha(Path(__file__)),checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),cost_scope='Per-episode grading_calls188 exclude3 authored qualification containers; fleet wall includes qualification. Remote CPU remains unknown. Input/runtime fields bound by frozen source and captured trace; no wire-level request capture.')
with(D/'FINAL_AUDIT.json').open('x')as f:json.dump(a,f,indent=2);f.write('\n')
manifest={str(p.relative_to(D)):sha(p)for p in D.rglob('*')if p.is_file()}
with(D/'ARTIFACT_MANIFEST.json').open('x')as f:json.dump(manifest,f,indent=2);f.write('\n')
print(json.dumps(dict(path=str((D/'FINAL_AUDIT.json').relative_to(R)),sha256=sha(D/'FINAL_AUDIT.json'),verified=True,complete=True,total_containers=191,dag_nodes=sum(len(x['nodes'])for x in all_dags),dag_edges=sum(len(x['edges'])for x in all_dags))))
