#!/usr/bin/env python3
"""Offline late-exploratory review-program reporting; original12 and known96 remain separate."""
import argparse, csv, hashlib, json, shutil, sys
from pathlib import Path
HERE=Path(__file__).resolve().parents[2];sys.path.insert(0,str(HERE))
from csp_tasks import verify_assignment
from report_completed_studies import crossed_program_statistics, save_report, LABELS
from plot_lineage import render
OUT=Path(__file__).resolve().parent; RAW=HERE/'runs/program-review-elites4-v1.1'; AUDIT=HERE/'results/program-review-v1.1-audit'
PIN='397ec67bba4d8b41875de4a46a32403e3c207ca6ac4e6431e5e59bbfc48cd1c9'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
INPUTS={}
def read(p):
 p=Path(p).resolve();INPUTS[str(p.relative_to(HERE))]=sha(p);return json.loads(p.read_text())
def need(ok,message):
 if not ok:raise ValueError(message)
def write(p,x):
 with Path(p).open('x')as f:json.dump(x,f,indent=2,allow_nan=False);f.write('\n')
def table(p,rows):
 with p.open('x',newline='')as f:
  w=csv.DictWriter(f,list(rows[0]));w.writeheader();w.writerows(rows)
def proof(task,r):
 need(r.get('cleanup_ok')is True and r.get('provenance')!='infrastructure','Infrastructure/cleanup fault')
 if r.get('proof')is not None:need(verify_assignment(task,r.get('candidate_output'))==r['proof'],'Proof replay mismatch')
 need(r.get('solved')is not True or(r.get('proof',{}).get('solved')is True and r.get('input_unchanged')is True),'Unproven success')
def original():
 receipt=read(AUDIT/'FINAL_AUDIT.json');need(sha(AUDIT/'FINAL_AUDIT.json')==PIN and receipt['verified']is True and receipt['complete']is True,'Final independent audit PASS missing')
 meta,episodes=read(RAW/'metadata.json'),read(RAW/'results.json');need(meta['verified']and meta['complete']and len(episodes)==4,'Incomplete producer')
 full=read(AUDIT/'full-typed-lineage.json');need(sum(len(x['nodes'])for x in full)==404 and sum(len(x['edges'])for x in full)==700,'Detailed lineage differs')
 rows=[];traces={};review_files=[];tasks={t['id']:t for t in read(RAW/'evaluation-inputs.json')}
 for e in sorted(episodes,key=lambda e:e['seed']):
  d=RAW/f"seed-{e['seed']}-review_elites4";need(e['calls']==e['completed_calls']==16 and e['training_candidates_scored']==10 and e['evaluation_completed']==12,'Allocation differs')
  need(sha(d/'selected.py')==e['selected_sha256']==read(d/'selection.json')['code_sha256'],'Selected source differs');INPUTS[str((d/'selected.py').relative_to(HERE))]=sha(d/'selected.py')
  INPUTS[str((d/'events.jsonl').relative_to(HERE))]=sha(d/'events.jsonl');events=[json.loads(l)for l in(d/'events.jsonl').read_text().splitlines()];traces[e['seed']]=events
  reviews=[r for r in events if r['type']=='program_review'];need(len(reviews)==6,'Missing review nodes')
  for r in reviews:
   f=d/('review-'+r['review_id']+'.json');need(read(f)=={k:r[k]for k in ['raw','critique','truncated']},'Raw critique file differs');review_files.append(f)
  for t in tasks.values():
   r=read(d/f"evaluation-{t['id']}.json")['report'];proof(t,r);rows.append(dict(task_id=t['id'],seed=e['seed'],arm=e['arm'],solved=r['solved']))
 cost=dict(arm='review_elites4',selected_programs=4,model_calls=sum(e['calls']for e in episodes),prompt_tokens=sum(e['prompt_tokens']for e in episodes),completion_tokens=sum(e['completion_tokens']for e in episodes),client_cost_is_lower_bound=any(not e['client_usage_complete']for e in episodes),known_server_episodes=sum(e['server_cost_known']for e in episodes),unknown_server_episodes=sum(not e['server_cost_known']for e in episodes),server_prompt_tokens_known=sum(e['server_prompt_tokens']for e in episodes),server_completion_tokens_known=sum(e['server_completion_tokens']for e in episodes),remote_solver_cpu_seconds=None)
 need((cost['model_calls'],cost['prompt_tokens'],cost['completion_tokens'])==(64,290793,66718),'Cost reconciliation differs')
 return rows,cost,meta,episodes,traces,full,review_files

def projection(events,full):
 nodes=[];edges=[];selected=next(r for r in events if r['type']=='program_selected');scored={r['candidate_index']:r for r in events if r['type']=='development_candidate_scored'}
 programs={r['index']:r for r in events if r['type']=='program_candidate'};reviews={r['review_id']:r for r in events if r['type']=='program_review'}
 detailed={(e['source'],e['target'],e['relation'])for e in full['edges']};compact=read(AUDIT/'typed-lineage.json');typed=next(x for x in compact if x['seed']==1)['nodes']
 byprogram={n['index']:n for n in typed if n['type']=='program'};byreview={n['review_id']:n for n in typed if n['type']=='critique'}
 def edge(a,b,kind):edges.append(dict(source=a,target=b,relation=kind))
 for r in events:
  if r['type']=='program_candidate':
   i=r['index'];score=scored[i];nodes.append(dict(id=f'program-{i}',kind='program_candidate',selected=i==selected['candidate_index'],code_sha256=r['code_sha256'],development_score=dict(solved=score['solved'],penalty=score['penalty'],feedback=score['feedback'])))
   if r.get('parent_index')is not None:
    c=byprogram[i];need((f"program:{r['parent_index']}",'call:'+c['request_id'],'repair_target_source')in detailed,'Missing own-parent detail');edge(f"program-{r['parent_index']}",f'program-{i}','own_previous_program')
    need(('critique:'+r['review_id'],'call:'+c['request_id'],'unverified_peer_critique')in detailed,'Missing critique guidance');edge(r['review_id'],f'program-{i}','review_guidance')
  elif r['type']=='program_review':
   nodes.append(dict(id=r['review_id'],kind='review',critique_verified=False,critique=r['critique'],raw=r['raw'],truncated=r['truncated']))
   for field,relation,detail in [('reviewer_candidate_index','review_source','reviewer_source_context'),('target_candidate_index','review_target','target_source_context')]:
    need((f"program:{r[field]}",'call:'+byreview[r['review_id']]['request_id'],detail)in detailed,'Missing review context edge');edge(f"program-{r[field]}",r['review_id'],relation)
 need(len(nodes)==16 and len(edges)==24,'Projection omitted a program/review/edge')
 return dict(seed=1,nodes=nodes,edges=edges,selected_program=selected,selections=[dict(pruned_ids=[f'program-{i}'for i in r['not_retained_indices']],retained_indices=r['retained_indices'])for r in events if r['type']=='review_population_selected'],scope='Readable projection: ALL10programs+6reviews, all6 own-parent+6guidance+6context+6target edges. Omits calls/grade/fitness/population nodes; detailed404node700edge audit remains authority. Figure selected posthoc by lowest training-seed label min(seed)=1, not by outcome rank; not random, representative or causal. Initialprogram3 was selected; its original12 result11/12 is descriptive. Non-retention is not proof of incorrectness.')

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--fresh-audit',type=Path);a=p.parse_args(argv)
 if not a.run:print(json.dumps(dict(mode='plan',original='4programs×12graphs',fresh='4×96only after complete+AstraPASS',bootstrap=5000,seed=20261115)));return
 rows,cost,meta,episodes,traces,full,review_files=original();phase='original12';extra=[]
 if a.fresh_audit:
  base=HERE/'runs/program-review-confirmation-v1.1';m=read(base/'metadata.json');audit=read(a.fresh_audit)
  need(m.get('complete')is True and m.get('verified')is True and m.get('completed_jobs')==384 and audit.get('verified')is True and audit.get('complete')is True,'Fresh confirmation not independently complete')
  pins=audit['input_sha256'];extra=[base/n for n in ['metadata.json','summary.json','grades.jsonl','bindings.json','corpus.json']]
  for f in extra:need(any(pins.get(k)==sha(f)for k in [str(f),str(f.resolve()),str(f.relative_to(HERE))]),'Fresh audit does not bind '+f.name);INPUTS[str(f.relative_to(HERE))]=sha(f)
  corpus=read(base/'corpus.json');tasks={t['id']:t for t in corpus['tasks']};grades=[json.loads(l)for l in(base/'grades.jsonl').read_text().splitlines()];rows=[]
  for g in grades:
   need(g['infrastructure']is False and g['code_sha256']==next(e['selected_sha256']for e in episodes if e['seed']==g['seed']),'Fresh source/infra mismatch');proof(tasks[g['task_id']],g['report']);rows.append({k:g[k]for k in ['task_id','seed','arm','solved']})
  need(len(rows)==384 and len({(r['task_id'],r['seed'])for r in rows})==384,'Fresh coverage differs');phase='known96'
  need(sha(a.fresh_audit)=='1e971e571fbecd88e01a1bebae239e818be31704ead901b926d0470df338ce6f','Fresh final audit SHA differs')
 LABELS['review_elites4']='Reviewer contexts (late exploratory)';report=crossed_program_statistics(rows,5000,20261115)
 report.update(training_costs=[cost],additional_model_calls=0 if a.fresh_audit else 64,input_sha256=dict(INPUTS),producer_source_revision=meta['source']['revision'],training_fleet_wall_seconds=meta['wall_seconds'],remote_solver_cpu_seconds=None,actual_episode_container_grades=188,qualification_container_grades=3,parse_skips_without_execution=20,evaluation_stage_wall_seconds=m.get('wall_seconds')if a.fresh_audit else None,grade_status_counts={k:sum(g['report']['status']==k for g in grades)for k in sorted({g['report']['status']for g in grades})}if a.fresh_audit else None,scope='Late exploratory program-context reviewers;4training seeds; original12 and operator-known96 reported separately. Task-only CI conditions on frozen programs; crossed CI resamples graph and training-seed labels, limited by4seeds. No randomized isolated reviewer-effect claim, no pooling and no generic100% guarantee. Critiques are unverified; absence from population is not mathematical failure. Training64calls charged once, not per graph; no remote solver CPU measurement. No wire-level prompt capture.')
 folder=OUT/phase;save_report(folder,report,True);table(folder/'graph-outcomes.csv',rows);table(folder/'seeds.csv',[dict(seed=s,solved=sum(r['solved']for r in rows if r['seed']==s),graphs=sum(r['seed']==s for r in rows))for s in range(1,5)])
 baseline=read(HERE/('results/program-confirmation-v1-analysis/fresh96/analysis.json'if a.fresh_audit else'results/program-search-v1-analysis/programs/analysis.json'));b=next(x for x in baseline['arms']if x['arm']=='independent4');table(folder/'historical-context.csv',[dict(method='independent4 historical',solved=b['solved'],cases=b['cases'],model_calls=64,prompt_tokens=247144,completion_tokens=69935),dict(method='review_elites4 late exploratory',solved=sum(r['solved']for r in rows),cases=len(rows),model_calls=64,prompt_tokens=290793,completion_tokens=66718)])
 evidence=folder/'evidence';evidence.mkdir()
 for f in extra+[AUDIT/'FINAL_AUDIT.json',AUDIT/'full-typed-lineage.json']+([a.fresh_audit]if a.fresh_audit else[]):shutil.copyfile(f,evidence/f.name)
 if not a.fresh_audit:
  for f in review_files:shutil.copyfile(f,evidence/(f.parent.name+'-'+f.name))
  for e in episodes:shutil.copyfile(RAW/f"seed-{e['seed']}-review_elites4/selected.py",evidence/f"selected-seed-{e['seed']}.py")
  tree=projection(traces[1],next(x for x in full if x['seed']==1));write(folder/'seed1-lineage.json',tree);render(tree,folder/'seed1-lineage','Seed1: ten programs and six unverified reviews; original12 result11/12')
 (folder/'REPORT.md').write_text((folder/'REPORT.md').read_text()+'\nHistorical independent4 context is separate, not a randomized isolated comparison. Original12:47/48; known96:376/384;64training calls,247144input/69935output. Review training:290793input/66718output; four-node fleet214.8215565s includes3qualification containers and drain.188episode containers+3qualification;20parse skips were not executed. No remote CPU time measured.\n')
 report['input_sha256']=dict(INPUTS);(folder/'analysis.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
 need(all(sha(HERE/f)==h for f,h in INPUTS.items()),'Inputs changed during reporting')
 write(folder/'manifest.json',dict(input_sha256=INPUTS,analysis_source_sha256=sha(__file__),statistics_source_sha256=sha(HERE/'report_completed_studies.py'),plot_source_sha256=sha(HERE/'plot_lineage.py'),files={str(f.relative_to(folder)):sha(f)for f in folder.rglob('*')if f.is_file()},raw_inputs_modified=False))
 print(json.dumps(report['arms'],indent=2))
if __name__=='__main__':main()
