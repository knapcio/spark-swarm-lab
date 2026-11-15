#!/usr/bin/env python3
"""Plan-first confirmation of frozen selected programs; remote grading is opt-in and gated."""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import threading
import time
import correctness_audit as audit
import independent_code_grader as grader
from reference_worker import verify_gate

HERE=Path(__file__).resolve().parent
PHASES=('original_feedback','original_holdout','public_examples','posthoc_robustness')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def require(ok,message):
 if not ok:raise ValueError(message)

def probes(name):
 """Posthoc authored probes, scored separately; not a newly untouched holdout."""
 cases={
 'stable_group_pairs':[[[['z',1],['a',2],['z',3]]],[[]]],
 'rotate_matrix':[[[[1,2,3],[4,5,6]]],[[[],[]]],[[]]],
 'longest_unique_span':[['abba'],['a🙂aé🙂'],['abcaXYZ']],
 'balanced_brackets':[['([)]'],[')('],['[(])'],['{[()]}'],['🙂[é](a)'],[''],['([{}])']],
 'dedupe_by_last':[[[['a',1],['b',2],['a',3]]],[[]]],
 'collapse_whitespace':[['\u00a0 A\t\nB \u00a0'],['\v\f\r A\t '],['é\u0301']],
 'natural_sort_strings':[[['a2','a02','a10','2a','1a','','é2','٢a']]],
 'zip_longest_sum':[[[1,2,3],[4]],[[],[2,-1]],[[],[]]],
 'invert_index':[[[['z',['a','a','b']],['a',['b','a']]]],[[]]],
 'range_compress':[[[3,1,2,2,-2,-1,8]],[[]]],
 'prefix_totals':[[[]],[[2,-2,0,-3]]],
 'select_nth_distinct':[[[3,3,1,2],1],[[1,1],-1],[[1,1],1]],
 'word_count_ascii':[['AéB İC abc123DEF'],['é🙂'],['Z z']],
 'flatten_depth':[[[1,[2,[3]],False,None],0],[[1,[2,[3]],False,None],1],[[1,[2,[3]],False,None],2]],
 'transpose_records':[[[{'z':1,'a':2},{'a':None,'b':False}]],[[]]],
 'min_covering_window':[[[1,2,1],[1,1]],[[1,2,1],[1]],[[1],[1,1]],[[],[]]],
 'apply_edits':[['abcdef',[[1,3,'X'],[5,6,'Y']]],['a🙂bc',[[1,2,''],[3,3,'!']]],['',[[0,0,'é']]]],
 'interleave_lists':[[[[1,1],[],[2,-1,3]]],[[]]]}
 require(name in cases,'No independently defined probes for '+name)
 return [dict(args=args,expected=audit.oracle(name,*args),check_input_unchanged=True)for args in cases[name]]

def trace_bytes(root,row):
 relative=Path(row['trace']);require(not relative.is_absolute()and '..'not in relative.parts,'Unsafe trace path')
 raw=root/relative
 if raw.exists():
  require(sha(raw)==row['trace_sha256'],'Original trace changed');return raw.read_bytes()
 parts=relative.parts;require(len(parts)==3 and parts[0]=='runs'and parts[1].startswith('evaluation-v2-coding-s'),'Unknown trace alias')
 cohort=root/'results/evaluation-v2'/parts[1].removeprefix('evaluation-v2-');target=cohort/parts[2]
 manifest=json.loads((cohort/'manifest.json').read_bytes());entries=[e for e in manifest['files']if e['export']==str(target.relative_to(root))]
 require(len(entries)==1 and entries[0]['original_sha256']==row['trace_sha256']and entries[0]['export_sha256']==sha(target),'Curated trace provenance changed')
 return target.read_bytes()

def prepare(root,index,tasks,private):
 selection=json.loads((root/'EVALUATION_SELECTION.json').read_bytes())['coding']
 require(sha(tasks)==selection['dataset_sha256']and sha(private)==selection['private_sha256'],'Frozen corpus SHA mismatch')
 manifest=json.loads((root/'results/correctness-audit-20261115/manifest.json').read_bytes())
 refs=[f for f in manifest['files']if f['path']==str(index.relative_to(root))]
 require(len(refs)==1 and refs[0]['sha256']==sha(index),'Selected-source index changed')
 public={t['id']:t for t in json.loads(tasks.read_bytes())['tasks']if t['split']=='evaluation'}
 hidden=json.loads(private.read_bytes())['references'];rows=json.loads(index.read_bytes())['cases'];keys={(r['task_id'],r['arm'],r['seed'])for r in rows}
 expected={(task,arm,seed)for task in public for arm in selection['arms']for seed in(1,2,3)}
 require(len(rows)==324 and len(keys)==324 and keys==expected,'Selected-case grid mismatch')
 jobs={};cases=[];probe_sets={}
 for row in sorted(rows,key=lambda r:(r['task_id'],r['seed'],r['arm'])):
  task=public[row['task_id']];events=[json.loads(line)for line in trace_bytes(root,row).splitlines()];chosen=[e for e in events if e['type']=='candidate_selected']
  require(len(chosen)==1 and chosen[0]['candidate_id']==row['selected_code_sha256'],'Selection freeze mismatch')
  cid=row['selected_code_sha256'];case=dict(row,phases={})
  if cid is None:case['status']='no_candidate';cases.append(case);continue
  sources={e['candidate_id']:e['code']for e in events if e['type']=='code_candidate'};require(cid in sources and hashlib.sha256(sources[cid].encode()).hexdigest()==cid,'Selected source SHA mismatch')
  fn=task['function_name'];probe_sets[task['id']]=probes(fn)
  phases=(hidden[task['id']]['feedback_tests'],hidden[task['id']]['holdout_tests'],task['examples'],probe_sets[task['id']])
  for phase,tests in zip(PHASES,phases):
   refs=[]
   for start in range(0,len(tests),128):
    chunk=tests[start:start+128];key=digest([cid,fn,phase,digest(chunk),sha(root/'independent_code_grader.py'),grader.IMAGE]);refs.append(key)
    jobs.setdefault(key,dict(job_id=key,code_sha256=cid,code=sources[cid],function_name=fn,phase=phase,test_sha256=digest(chunk),tests=chunk,chunk_start=start))
   case['phases'][phase]=dict(job_ids=refs,total=len(tests))
  cases.append(case)
 return cases,list(jobs.values()),probe_sets

def execute(jobs,hosts,timeout,record,evaluator=None):
 """Four fixed host slots; reuse exact-source/phase/test jobs; halt dispatch on infrastructure."""
 evaluator=evaluator or grader.evaluate_code
 stop=threading.Event();lock=threading.Lock();results={};started=time.monotonic()
 def worker(slot):
  host=hosts[slot]
  for job in jobs[slot::4]:
   if stop.is_set():break
   start=time.monotonic()
   try:report=evaluator(job['code'],job['function_name'],job['tests'],host,timeout)
   except Exception as exc:report=dict(status='error',provenance='infrastructure',failure_kind='controller_infrastructure',cleanup_ok=False,error=type(exc).__name__+': '+str(exc)[:1000])
   if not isinstance(report,dict):report=dict(status='error',provenance='infrastructure',failure_kind='invalid_grade_infrastructure',cleanup_ok=False)
   valid=report.get('grading_authority')=='outer_parent'and report.get('oracle_sent_to_child')is False and report.get('total')==len(job['tests'])and all(type(report.get(k))is int and report[k]>=0 for k in ('passed','tests_run'))and report['passed']<=report['tests_run']<=len(job['tests'])
   if report.get('status')=='passed':valid=valid and report['passed']==report['tests_run']==len(job['tests'])and report.get('failed')==0
   if not valid:report.update(provenance='infrastructure',failure_kind='invalid_grade_infrastructure')
   infrastructure=report.get('provenance')=='infrastructure'or str(report.get('failure_kind')).endswith('_infrastructure')or report.get('cleanup_ok')is not True
   if infrastructure:stop.set()
   result={k:job[k]for k in ('job_id','code_sha256','function_name','phase','test_sha256','chunk_start')};result.update(host=host,test_count=len(job['tests']),wall_seconds=time.monotonic()-start,report=report,infrastructure=infrastructure)
   with lock:
    results[job['job_id']]=result
    with record.open('a')as output:output.write(json.dumps(result,ensure_ascii=False)+'\n')
 def drain():
  with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(worker,range(4)))
 drain()
 return results,dict(complete=len(results)==len(jobs)and not stop.is_set(),halted_on_infrastructure=stop.is_set(),completed_jobs=len(results),planned_jobs=len(jobs),batch_wall_seconds=time.monotonic()-started)

def summarize(cases,results):
 rows=[]
 for case in cases:
  item={k:case[k]for k in ('task_id','arm','seed','selected_code_sha256')};item['phases']={}
  for phase in PHASES:
   refs=case['phases'].get(phase)
   if refs is None:item['phases'][phase]=dict(status='no_candidate',passed=None,total=None,tests_run=None);continue
   chunks=[results.get(k)for k in refs['job_ids']];complete=all(c is not None for c in chunks)
   reports=[c['report']for c in chunks if c is not None]
   status='not_completed'if not complete else'infrastructure'if any(c['infrastructure']for c in chunks)else'passed'if all(r.get('status')=='passed'and r.get('passed')==r.get('total')for r in reports)else'timeout'if any(r.get('status')=='timeout'for r in reports)else'error'if any(r.get('status')=='error'for r in reports)else'failed'
   item['phases'][phase]=dict(status=status,passed=sum(r.get('passed',0)for r in reports)if complete else None,total=refs['total'],tests_run=sum(r.get('tests_run',0)for r in reports)if complete else None,job_ids=refs['job_ids'],failure_kinds=sorted({r['failure_kind']for r in reports if r.get('failure_kind')}))
  rows.append(item)
 return rows

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--output',type=Path);p.add_argument('--index',type=Path,default=HERE/'results/correctness-audit-20261115/selected-primary-scan-index.json');p.add_argument('--tasks',type=Path,default=HERE/'datasets/coding-v1/tasks.json');p.add_argument('--private',type=Path,default=HERE/'datasets/coding-v1/hidden-tests.json');p.add_argument('--hosts',nargs=4,default=['Spark_01','Spark_02','Spark_03','Spark_04']);p.add_argument('--timeout',type=float,default=10);args=p.parse_args(argv)
 require(len(set(args.hosts))==4,'Four distinct fixed hosts required');require(0<args.timeout<=60,'Timeout must be0..60seconds')
 gate=verify_gate(HERE)if args.run else None
 cases,jobs,probe_sets=prepare(HERE,args.index.resolve(),args.tasks.resolve(),args.private.resolve())
 paths=[Path(__file__),HERE/'independent_code_grader.py',HERE/'correctness_audit.py',HERE/'reference_worker.py',HERE/'test_confirm_coding.py',HERE/'test_independent_code_grader.py',HERE/'EVALUATION_SELECTION.json',HERE/'CPU_GRADER_AMENDMENT.json',HERE/'results/correctness-audit-20261115/manifest.json',args.index,args.tasks,args.private]
 plan=dict(protocol='posthoc-independent-coding-confirmation-v1',mode='run'if args.run else'plan',source_hashes={str(f.resolve().relative_to(HERE)):sha(f)for f in paths},selected_cases=len(cases),selected_artifacts=sum(c['selected_code_sha256']is not None for c in cases),frozen_selected_producer=audit.REVISION,distinct_source_function_pairs=len({(j['code_sha256'],j['function_name'])for j in jobs}),planned_unique_grading_jobs=len(jobs),phase_reference_counts={phase:sum(len(c['phases'].get(phase,{}).get('job_ids',[]))for c in cases)for phase in PHASES},image=grader.IMAGE,hosts=args.hosts,timeout=args.timeout,gate=gate,posthoc_probe_sha256=digest(probe_sets),cache_policy='Exact selected codeSHA+function+namedphase+testchunkSHA+graderSHA+image; cache outcomes only within this confirmation; no original grade reused.',scope='New outer-parent confirmation of original feedback/holdout plus separate public examples/posthoc robustness. Exact-artifact cache reuse is not an independent seed replicate or method latency measurement. No original score replacement; no model or candidate optimization.',fixed_slots='One serial grading worker per host; halt all new dispatch on infrastructure, finish owned in-flight cleanup.')
 print(json.dumps(plan,indent=2))
 if not args.run:return 0
 require(args.output is not None,'--run requires new --output directory');args.output.mkdir(parents=True,exist_ok=False)
 (args.output/'metadata.json').write_text(json.dumps(plan,indent=2)+'\n');(args.output/'posthoc-probes.json').write_text(json.dumps(probe_sets,indent=2,ensure_ascii=False)+'\n')
 results,status=execute(jobs,args.hosts,args.timeout,args.output/'grades.jsonl');rows=summarize(cases,results)
 (args.output/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
 flat=[]
 for row in rows:
  item={k:v for k,v in row.items()if k!='phases'}
  for phase,values in row['phases'].items():
   for key in ('status','passed','total','tests_run'):item[phase+'_'+key]=values[key]
  flat.append(item)
 with(args.output/'summary.csv').open('w',newline='')as output:
  writer=csv.DictWriter(output,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
 final_hashes={name:sha(HERE/name)if(HERE/name).is_file()else None for name in plan['source_hashes']}
 plan.update(final_source_hashes=final_hashes,source_changed_during_run=final_hashes!=plan['source_hashes'])
 if plan['source_changed_during_run']:status['complete']=False;status['source_change_halt']=True
 plan.update(status);(args.output/'metadata.json').write_text(json.dumps(plan,indent=2)+'\n')
 print(json.dumps(status));return 0 if status['complete']else 1
if __name__=='__main__':raise SystemExit(main())
