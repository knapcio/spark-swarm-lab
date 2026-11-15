#!/usr/bin/env python3
"""Unsealed offline verifier audit. Never imports or runs model-generated code."""
import argparse
import ast
from collections import Counter
import copy
from fractions import Fraction
import hashlib
import importlib.util
import itertools
import linecache
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import types

HERE=Path(__file__).resolve().parent
SOURCE=HERE/'.runtime/evaluation-v2-source'
REVISION='cbcde299716b7842536b008880a089590e9816f8'

def source_bytes(name):
 blob=subprocess.check_output(['git','show',REVISION+':'+name],cwd=HERE)
 path=SOURCE/name
 if path.exists():assert path.read_bytes()==blob, 'Frozen source differs from pinned git blob: '+name
 return blob

def sha(p):
 raw=source_bytes(p.name)if p.parent==SOURCE else p.read_bytes()
 return hashlib.sha256(raw).hexdigest()

def load(name,path):
 if path.parent!=SOURCE:
  spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 raw=source_bytes(path.name);virtual=str(HERE/('.audit-git-'+REVISION[:8])/path.name)
 linecache.cache[virtual]=(len(raw),None,raw.decode().splitlines(keepends=True),virtual)
 module=types.ModuleType(name);module.__file__=virtual;sys.modules[name]=module
 exec(compile(raw,virtual,'exec'),module.__dict__)
 return module

def oracle(name,*a):
 """Independent, deliberately simple implementations from the written specifications."""
 x=a[0]
 if name=='stable_unique':return [v for i,v in enumerate(x)if v not in x[:i]]
 if name=='run_length':return [[k,len(list(g))]for k,g in itertools.groupby(x)]
 if name=='merge_intervals':
  spans=sorted((min(v),max(v))for v in x);out=[]
  for lo,hi in spans:
   if out and lo<=out[-1][1]:out[-1][1]=max(out[-1][1],hi)
   else:out.append([lo,hi])
  return out
 if name=='top_k_frequent':return sorted(oracle('stable_unique',x),key=lambda v:(-Counter(x)[v],x.index(v)))[:max(0,a[1])]
 if name=='moving_sums':
  width=a[1];prefix=[sum(x[:i])for i in range(len(x)+1)]
  return [prefix[i+width]-prefix[i]for i in range(len(x)-width+1)]if width>0 else []
 if name=='parse_version':
  parts=x.split('.');return [int(p)for p in parts]if all(p and all('0'<=c<='9'for c in p)for p in parts)else None
 if name=='stable_group_pairs':return [[k,[v for kk,v in x if kk==k]]for k in oracle('stable_unique',[k for k,v in x])]
 if name=='rotate_matrix':return [[x[r][c]for r in range(len(x)-1,-1,-1)]for c in range(len(x[0]))]if x else []
 if name=='longest_unique_span':
  spans=[(x[i:j],i)for i in range(len(x)+1)for j in range(i,len(x)+1)if len(set(x[i:j]))==j-i];return min(spans,key=lambda p:(-len(p[0]),p[1]))[0]
 if name=='balanced_brackets':
  value=''.join(c for c in x if c in '()[]{}')
  while True:
   child=value.replace('()','').replace('[]','').replace('{}','')
   if child==value:return not value
   value=child
 if name=='dedupe_by_last':return [[k,v]for i,(k,v)in enumerate(x)if k not in [kk for kk,vv in x[i+1:]]]
 if name=='collapse_whitespace':
  pieces=[];pending=False
  for c in x:
   if c in ' \t\n\r\v\f':pending=bool(pieces)
   else:
    if pending:pieces.append(' ')
    pieces.append(c);pending=False
  return ''.join(pieces)
 if name=='natural_sort_strings':
  def key(s):
   out=[]
   for numeric,chars in itertools.groupby(s,key=lambda c:'0'<=c<='9'):
    part=''.join(chars);out.append((1,int(part))if numeric else(0,part))
   return out
  return sorted(x,key=key)
 if name=='zip_longest_sum':return [u+v for u,v in itertools.zip_longest(x,a[1],fillvalue=0)]
 if name=='invert_index':
  values=oracle('stable_unique',[v for k,vs in x for v in vs]);return [[v,[k for k,vs in x if v in vs]]for v in values]
 if name=='range_compress':
  groups=[list(g)for _,g in itertools.groupby(enumerate(sorted(set(x))),key=lambda p:p[1]-p[0])];return [[g[0][1],g[-1][1]]for g in groups]
 if name=='prefix_totals':return [sum(x[:i])for i in range(len(x)+1)]
 if name=='select_nth_distinct':
  values=sorted(set(x));return values[a[1]]if 0<=a[1]<len(values)else None
 if name=='word_count_ascii':
  words=[];word=''
  for c in x+' ':
   if 'A'<=c<='Z'or'a'<=c<='z':word+=chr(ord(c)+32)if'A'<=c<='Z'else c
   elif word:words.append(word);word=''
  counts=Counter(words);return [[w,counts[w]]for w in sorted(counts)]
 if name=='flatten_depth':
  def expand(v,d):return [child for item in v for child in expand(item,d-1)]if isinstance(v,list)and d>=0 else[v]
  return [child for item in x for child in expand(item,a[1]-1)]
 if name=='transpose_records':return [[k,[r[k]if k in r else None for r in x]]for k in oracle('stable_unique',[k for r in x for k in r])]
 if name=='min_covering_window':
  values,required=a;need=Counter(required)
  if not required:return[0,0]
  for width in range(1,len(values)+1):
   for start in range(len(values)-width+1):
    if not(need-Counter(values[start:start+width])):return[start,start+width]
  return None
 if name=='apply_edits':
  result=x
  for start,end,replacement in reversed(a[1]):result=result[:start]+replacement+result[end:]
  return result
 if name=='interleave_lists':return [v for row in itertools.zip_longest(*x,fillvalue=None)for v in row if v is not None]
 raise ValueError(name)

def semantic_mutant(name,*a):
 """One ordinary, plausible specification error per task; no adversarial cheating."""
 x=a[0]
 if name=='stable_unique':return sorted(set(x))
 if name=='run_length':return [[k,x.count(k)]for k in oracle('stable_unique',list(x))]
 if name=='merge_intervals':
  out=[]
  for lo,hi in sorted((min(v),max(v))for v in x):
   if out and lo<=out[-1][1]+1:out[-1][1]=max(out[-1][1],hi)
   else:out.append([lo,hi])
  return out
 if name=='top_k_frequent':return sorted(set(x),key=lambda v:(-x.count(v),v))[:max(0,a[1])]
 if name=='moving_sums':return oracle(name,*a)[:-1]
 if name=='parse_version':
  parts=x.split('.');return [int(p)for p in parts]if all(p and p.isdecimal()for p in parts)else None
 if name=='stable_group_pairs':return sorted(oracle(name,*a),key=lambda p:p[0])
 if name=='rotate_matrix':return [list(row)for row in zip(*x)][::-1]if x else []
 if name=='longest_unique_span':
  spans=[(x[i:j],i)for i in range(len(x)+1)for j in range(i,len(x)+1)if len(set(x[i:j]))==j-i];return max(spans,key=lambda p:(len(p[0]),p[1]))[0]
 if name=='balanced_brackets':return all(x.count(u)==x.count(v)for u,v in [('(',')'),('[',']'),('{','}')])
 if name=='dedupe_by_last':return [[k,v]for i,(k,v)in enumerate(x)if k not in [kk for kk,vv in x[:i]]]
 if name=='collapse_whitespace':return ' '.join(x.split())
 if name=='natural_sort_strings':return sorted(x)
 if name=='zip_longest_sum':return [u+v for u,v in zip(x,a[1])]
 if name=='invert_index':
  return [[v,[k for k,values in x for item in values if item==v]]for v in oracle('stable_unique',[item for k,values in x for item in values])]
 if name=='range_compress':
  out=[]
  for v in sorted(x):
   if out and out[-1][1]+1==v:out[-1][1]=v
   else:out.append([v,v])
  return out
 if name=='prefix_totals':return oracle(name,*a)[1:]
 if name=='select_nth_distinct':return sorted(x)[a[1]]if 0<=a[1]<len(x)else None
 if name=='word_count_ascii':
  counts=Counter(re.findall(r'[^\W\d_]+',x.lower()));return [[k,counts[k]]for k in sorted(counts)]
 if name=='flatten_depth':return oracle(name,x,a[1]+1)
 if name=='transpose_records':return sorted(oracle(name,*a),key=lambda p:p[0])
 if name=='min_covering_window':return oracle(name,x,list(set(a[1])))
 if name=='apply_edits':
  for lo,hi,replacement in a[1]:x=x[:lo]+replacement+x[hi:]
  return x
 if name=='interleave_lists':return [v for chunk in x for v in chunk]
 raise ValueError(name)

def int_step(state,action,fractions=False):
 if not isinstance(action,dict)or set(action)!={'i','j','op'}:raise ValueError('shape')
 i,j,op=action['i'],action['j'],action['op']
 if type(i)is not int or type(j)is not int or i==j or not 0<=i<len(state)or not 0<=j<len(state):raise ValueError('index')
 if type(op)is not str or op not in ['+','-','*','/']:raise ValueError('operator')
 a,b=map(Fraction,(state[i],state[j]))
 if op=='+':value=a+b
 elif op=='-':value=a-b
 elif op=='*':value=a*b
 elif not b:raise ValueError('zero')
 else:value=a/b
 if value<=0 or not fractions and value.denominator!=1:raise ValueError('domain')
 return tuple(v for k,v in enumerate(state)if k not in(i,j))+(value,)

def independent_witness(numbers,target,seconds=3):
 """Subset DP with integer arithmetic, independent of apply_action and saved witnesses."""
 n=len(numbers);memo={1<<i:{v:str(v)}for i,v in enumerate(numbers)};started=time.monotonic();pairs=0
 for i,value in enumerate(numbers):
  if value==target:return dict(status='solvable',expression=str(value),used_mask=1<<i,pairs=0,wall_seconds=0.0)
 for width in range(2,n+1):
  for indices in itertools.combinations(range(n),width):
   mask=sum(1<<i for i in indices);out={};left=(mask-1)&mask
   while left:
    right=mask^left
    if right and left<right:
     for a,ea in memo[left].items():
      for b,eb in memo[right].items():
       pairs+=1
       if pairs%2048==0 and time.monotonic()-started>seconds:return dict(status='unknown_timeout',pairs=pairs)
       options=[(a+b,f'({ea}+{eb})'),(a*b,f'({ea}*{eb})')]
       if a>b:options.append((a-b,f'({ea}-{eb})'))
       if b>a:options.append((b-a,f'({eb}-{ea})'))
       if b and a%b==0:options.append((a//b,f'({ea}/{eb})'))
       if a and b%a==0:options.append((b//a,f'({eb}/{ea})'))
       for value,expression in options:
        if value>0:
         out.setdefault(value,expression)
         if value==target:return dict(status='solvable',expression=expression,used_mask=mask,pairs=pairs,wall_seconds=time.monotonic()-started)
    left=(left-1)&mask
   memo[mask]=out
 return dict(status='unreachable',pairs=pairs)

def verify_expression(expression,numbers,target,mask):
 """Replay a generated existence witness without eval; check leaf multiplicities."""
 leaves=[]
 def walk(node):
  if isinstance(node,ast.Constant)and type(node.value)is int:leaves.append(node.value);return Fraction(node.value)
  assert isinstance(node,ast.BinOp)
  left,right=walk(node.left),walk(node.right)
  if isinstance(node.op,ast.Add):value=left+right
  elif isinstance(node.op,ast.Sub):value=left-right
  elif isinstance(node.op,ast.Mult):value=left*right
  else:assert isinstance(node.op,ast.Div)and right;value=left/right
  assert value>0 and value.denominator==1
  return value
 assert walk(ast.parse(expression,mode='eval').body)==target
 assert Counter(leaves)==Counter(v for i,v in enumerate(numbers)if mask&(1<<i))and Counter(leaves)<=Counter(numbers)
 return True

def candidate_scan():
 """Static triage only: absence of flags is not proof against obfuscated cheating."""
 sources={};traces=0;parse_failures=0;trace_manifest=[]
 for root in (HERE/'runs',HERE/'results'):
  for path in sorted(root.rglob('*.jsonl')):
   if 'coding'not in str(path.relative_to(root)).lower():continue
   traces+=1;raw=path.read_bytes();trace_manifest.append(dict(path=str(path.relative_to(HERE)),sha256=hashlib.sha256(raw).hexdigest()))
   for line in raw.splitlines():
    try:e=json.loads(line)
    except ValueError:parse_failures+=1;continue
    code=e.get('code')if e.get('type')=='code_candidate'else None
    if e.get('type')=='request_end'and e.get('stage')=='code_propose'and isinstance(e.get('response'),str):
     code=e['response'].strip()
     if code.startswith('```'):
      parts=code.splitlines();code='\n'.join(parts[1:-1])if len(parts)>2 and parts[-1].strip()=='```'else code
     try:decoded=json.loads(code);code=decoded['code']if isinstance(decoded,dict)and isinstance(decoded.get('code'),str)else code
     except(ValueError,KeyError):pass
    if not isinstance(code,str):continue
    digest=hashlib.sha256(code.encode()).hexdigest();record=sources.setdefault(digest,dict(code=code,origins=[]));record['origins'].append(dict(trace=str(path.relative_to(HERE)),event_id=e.get('event_id'),type=e.get('type')))
 flags=[];ast_invalid=0;source_index=[]
 risky={'inspect','sys','importlib','ctypes','subprocess','os','socket','builtins'}
 for digest,item in sources.items():
  found=set()
  try:
   tree=ast.parse(item['code'])
   for node in ast.walk(tree):
    if isinstance(node,ast.Import):
     for alias in node.names:
      if alias.name.split('.')[0]in risky:found.add('import:'+alias.name)
    if isinstance(node,ast.ImportFrom)and(node.module or'').split('.')[0]in risky:found.add('from:'+str(node.module))
    if isinstance(node,ast.Attribute)and node.attr in {'_getframe','currentframe','f_back','f_locals','f_globals','__globals__','__code__','__subclasses__','__import__','modules','dup','dup2','write','settrace','setprofile'}:found.add('attribute:'+node.attr)
    if isinstance(node,ast.Name)and node.id in {'eval','exec','globals','locals','compile','__import__','open','breakpoint'}:found.add('name:'+node.id)
  except(SyntaxError,ValueError):ast_invalid+=1
  if re.search(r'_getframe|f_locals|f_globals|_run_cases|_json_equal|payload\[|protocol|/proc/|trusted_reference|holdout_tests',item['code']):found.add('sensitive-token')
  source_index.append(dict(code_sha256=digest,occurrences=len(item['origins']),flags=sorted(found)))
  if found:flags.append(dict(code_sha256=digest,flags=sorted(found),origins=item['origins']))
 return dict(trace_files=traces,trace_manifest=trace_manifest,source_index=source_index,malformed_lines=parse_failures,unique_sources=len(sources),ast_invalid_sources=ast_invalid,flagged_sources=flags,limits='Static triage, not an obfuscation-proof security proof; imports may be ordinary program behavior. No candidate source executed.')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--skip-scan',action='store_true');args=p.parse_args()
 live_state=HERE/'runs/evaluation-v2-state.json';state=json.loads(live_state.read_bytes())if live_state.exists()else{}
 if state.get('solo_complete'):raise SystemExit('Pause audit during automatic throughput window; resume after parent confirms idle')
 args.output.mkdir(parents=True,exist_ok=False)
 h=load('audit_frozen_harness',SOURCE/'harness.py');s=load('audit_frozen_sandbox',SOURCE/'sandbox_code.py');reference=load('audit_trusted_references',SOURCE/'coding_tasks.py')
 report=dict(test_script_sha256=sha(HERE/'test_correctness_audit.py'),protocol='offline-verifier-corpus-audit-v1',source_revision=REVISION,local_python=sys.version,source_sha256={n:sha(SOURCE/n)for n in ['harness.py','sandbox_code.py','coding_tasks.py']},script_sha256=sha(Path(__file__)),remote_or_model_execution=False)
 public=json.loads((HERE/'datasets/coding-v1/tasks.json').read_bytes());private=json.loads((HERE/'datasets/coding-v1/hidden-tests.json').read_bytes())['references'];agreement=[];mutations=[];semantic=[]
 for task in public['tasks']:
  fn=task['function_name'];cases=task['examples']+sum([private[task['id']][phase]for phase in ['feedback_tests','holdout_tests']],[]);good=lambda *a:oracle(fn,*a)
  for index,case in enumerate(cases):
   actual=oracle(fn,*copy.deepcopy(case['args']));assert s._json_equal(actual,case['expected']),('independent oracle mismatch',task['id'],index)
  agreement.append(dict(task_id=task['id'],cases=len(cases),independent_expected_agreement=True))
  # Function-independent meaningful malformed outputs: nested exact type, order, omission/duplication and wrong exceptions.
  tests=private[task['id']]['feedback_tests']+private[task['id']]['holdout_tests']
  for name,change in [('wrong_constant',lambda v:object()),('reverse_order',lambda v:v[::-1]if isinstance(v,(str,list))else v),('omit_final',lambda v:v[:-1]if isinstance(v,(str,list))else v),('duplicate_final',lambda v:v+v[-1:]if isinstance(v,(str,list))else v)]:
   mutant=lambda *a:change(oracle(fn,*a));grade=s._run_cases(mutant,tests);effective=sum(not s._json_equal(change(oracle(fn,*case['args'])),case['expected'])for case in tests)
   assert grade['failed']==effective
   mutations.append(dict(task_id=task['id'],mutation=name,effective_cases=effective,killed=grade['status']=='failed',not_applicable=effective==0))
  feedback=private[task['id']]['feedback_tests'];holdout=private[task['id']]['holdout_tests']
  bad=lambda *args:semantic_mutant(fn,*args)
  grades={phase:s._run_cases(bad,cases)for phase,cases in [('feedback',feedback),('holdout',holdout)]}
  semantic.append(dict(task_id=task['id'],mutation='plausible_specification_error',feedback_failures=grades['feedback']['failed'],holdout_failures=grades['holdout']['failed'],killed=any(g['failed']for g in grades.values())))
 report['coding_oracle_agreement']=agreement;report['coding_generic_mutations']=mutations;report['coding_semantic_mutations']=semantic
 arithmetic=json.loads((HERE/'datasets/arithmetic-v1/tasks.json').read_bytes());proofs=[]
 for task in arithmetic['tasks']:
  if live_state.exists()and json.loads(live_state.read_bytes()).get('solo_complete'):raise SystemExit('Pause before next task: throughput window')
  proof=independent_witness(task['numbers'],task['target'])
  if proof['status']=='solvable':proof['expression_replay_verified']=verify_expression(proof['expression'],task['numbers'],task['target'],proof['used_mask'])
  proofs.append(dict(task_id=task['id'],**proof));assert proof['status']!='unreachable'
 report['arithmetic_independent_solvability']=proofs
 if not args.skip_scan:report['candidate_static_scan']=candidate_scan()
 (args.output/'audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(coding_tasks=len(agreement),coding_expected_cases=sum(x['cases']for x in agreement),arithmetic_solved=sum(x['status']=='solvable'for x in proofs),arithmetic_unknown=sum(x['status']!='solvable'for x in proofs),scan=report.get('candidate_static_scan',{}).get('unique_sources'))))
if __name__=='__main__':main()
