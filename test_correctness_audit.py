"""Offline adversarial/mutation checks; authored fixtures only, never model code."""
import copy
from fractions import Fraction as F
import itertools
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest.mock import patch
import correctness_audit as a

H=a.load('test_audit_actual_harness',a.SOURCE/'harness.py')
S=a.load('test_audit_actual_grader',a.SOURCE/'sandbox_code.py')
R=a.load('test_audit_trusted_references',a.SOURCE/'coding_tasks.py')

class ArithmeticIndependentTests(unittest.TestCase):
 def test_exhaustive_small_integer_actions_and_commutative_metamorphism(self):
  for n in (2,3,4):
   for state in itertools.product(range(1,5),repeat=n):
    original=tuple(map(F,state))
    for i,j in itertools.permutations(range(n),2):
     for op in '+-*/':
      action=dict(i=i,j=j,op=op)
      try:expected=a.int_step(original,action)
      except ValueError:
       with self.assertRaises(H.InvalidMove):H.apply_action(original,action)
       continue
      got=H.apply_action(original,action);self.assertEqual(got,expected)
      self.assertEqual(original,tuple(map(F,state)));self.assertEqual(len(got),n-1)
      if op in '+*':self.assertEqual(got,H.apply_action(original,dict(i=j,j=i,op=op)))
 def test_malformed_and_domain_bypass_proposals_rejected(self):
  invalid=[None,[],{},'__import__("os")',dict(i=0,j=0,op='+'),dict(i=True,j=1,op='+'),dict(i=0.0,j=1,op='+'),dict(i='0',j=1,op='+'),dict(i=-1,j=1,op='+'),dict(i=0,j=2,op='+'),dict(i=0,j=1,op='**'),dict(i=0,j=1,op=['+']),dict(i=0,j=1,op='+',value=999)]
  for action in invalid:
   with self.subTest(action=action),self.assertRaises((H.InvalidMove,TypeError)):H.apply_action((F(3),F(2)),action)
  for state,op in [((2,2),'-'),((2,3),'-'),((3,2),'/'),((2,0),'/')]:
   with self.assertRaises(H.InvalidMove):H.apply_action(tuple(map(F,state)),dict(i=0,j=1,op=op))
  self.assertFalse(H.solved((F(1),F(2)),3));self.assertTrue(H.solved((F(3),F(2)),3))
 def test_duplicate_consumption_and_order_boundary(self):
  self.assertEqual(H.apply_action((F(2),F(2),F(9)),dict(i=0,j=1,op='+')),(F(9),F(4)))
  self.assertEqual(H.apply_action((F(7),F(3),F(2),F(5)),dict(i=0,j=2,op='-')),(F(3),F(5),F(5)))
 def test_independent_subset_solver_rejects_unreachable_and_respects_duplicates(self):
  self.assertEqual(a.independent_witness([1,1],3)['status'],'unreachable')
  self.assertEqual(a.independent_witness([2,2,3],12)['status'],'solvable')
  self.assertEqual(a.independent_witness([3,2],1)['status'],'solvable')
  proof=a.independent_witness([3,2],3);self.assertEqual(proof['status'],'solvable');self.assertTrue(a.verify_expression(proof['expression'],[3,2],3,proof['used_mask']))
  with self.assertRaises(AssertionError):a.verify_expression('(3+3)',[3,2],6,3)

class GraderNegativeTests(unittest.TestCase):
 def grade(self,fn,args,expected,**kwargs):return S._run_cases(fn,[dict(args=args,expected=expected,**kwargs)])
 def test_wrong_order_duplicates_missing_values_and_exact_types(self):
  for actual,expected in [([2,1],[1,2]),([1,1,2],[1,2]),([1],[1,2]),(True,1),(1,True),(1.0,1),((1,2),[1,2]),({'k':1,'extra':0},{'k':1}),({'k':[False]},{'k':[0]})]:
   with self.subTest(actual=actual):self.assertEqual(self.grade(lambda:actual,[],expected)['status'],'failed')
 def test_wrong_exception_missing_exception_and_postcondition_mutation(self):
  def bad(_):raise TypeError('wrong')
  case=dict(args=[1],expected_exception='ValueError')
  self.assertEqual(S._run_cases(bad,[case])['status'],'failed')
  self.assertEqual(S._run_cases(lambda _:1,[case])['status'],'failed')
  def mutate(v):v.reverse();return sorted(v)
  self.assertEqual(self.grade(mutate,[[2,1]],[1,2])['first_failure']['failure_kind'],'input_mutation')
 def test_expected_values_are_not_modified_by_grading(self):
  tests=[dict(args=[[1,2]],expected=[1,2])];before=copy.deepcopy(tests)
  self.assertEqual(S._run_cases(lambda v:v,tests)['status'],'passed');self.assertEqual(tests,before)
 def test_known_same_interpreter_frame_spoof_false_pass_is_reproduced(self):
  # Expected vulnerability reproduction, not a claim of secure grading.
  code='def solve(values):\n import sys\n return sys._getframe(1).f_locals["case"]["expected"]\n'
  payload=dict(code=code,function_name='solve',tests=[dict(args=[[1,2]],expected=3),dict(args=[[]],expected=0)],timeout=2)
  process=subprocess.run([sys.executable,'-I','-S','-c',S.RUNNER],input=json.dumps(payload),text=True,capture_output=True,timeout=4)
  self.assertEqual(process.returncode,0);self.assertEqual(json.loads(process.stdout)['status'],'passed')
 def test_known_temporal_mutation_is_only_a_final_state_check(self):
  def transient_mutation(values):values.append(999);values.pop();return sum(values)
  self.assertEqual(self.grade(transient_mutation,[[1,2]],3)['status'],'passed')

class CorpusCoverageTests(unittest.TestCase):
 def test_counts_only_bracket_mutant_exposes_private_coverage_gap(self):
  public=json.loads((a.HERE/'datasets/coding-v1/tasks.json').read_bytes());task=next(t for t in public['tasks']if t['id']=='eva-balanced_brackets')
  private=json.loads((a.HERE/'datasets/coding-v1/hidden-tests.json').read_bytes())['references'][task['id']]
  bad=lambda text:a.semantic_mutant('balanced_brackets',text)
  for phase in ('feedback_tests','holdout_tests'):self.assertEqual(S._run_cases(bad,private[phase])['status'],'passed')
  self.assertEqual(S._run_cases(bad,task['examples'])['status'],'failed')
  self.assertTrue(bad('([)]'));self.assertFalse(a.oracle('balanced_brackets','([)]'))
 def test_source_loader_is_portable_without_private_worktree(self):
  with patch.object(a,'SOURCE',a.HERE/'.nonexistent-audit-worktree'):
   module=a.load('audit_portable_sandbox',a.SOURCE/'sandbox_code.py')
   self.assertEqual(module.IMAGE,S.IMAGE);self.assertEqual(module.RUNNER,S.RUNNER)

class CodingMetamorphicTests(unittest.TestCase):
 def test_order_multiplicity_unicode_and_boundary_relations(self):
  r=random.Random(20261115)
  for _ in range(100):
   values=[r.randrange(-3,4)for _ in range(r.randrange(10))]
   for name,args in [('stable_unique',[values]),('range_compress',[values]),('prefix_totals',[values]),('moving_sums',[values,1]),('zip_longest_sum',[values,[]]),('select_nth_distinct',[values,2]),('top_k_frequent',[values,2])]:
    self.assertTrue(S._json_equal(getattr(R,name)(*copy.deepcopy(args)),a.oracle(name,*args)))
   unique=a.oracle('stable_unique',values);self.assertEqual(a.oracle('stable_unique',unique),unique)
   ranges=a.oracle('range_compress',values);self.assertEqual(a.oracle('range_compress',values+values),ranges)
   self.assertEqual([v for lo,hi in ranges for v in range(lo,hi+1)],sorted(set(values)))
   totals=a.oracle('prefix_totals',values);self.assertEqual([b-c for c,b in zip(totals,totals[1:])],values)
   self.assertEqual(a.oracle('moving_sums',values,1),values)
   self.assertEqual(a.oracle('zip_longest_sum',values,[]),values)
  self.assertEqual(a.oracle('collapse_whitespace',' \tA\u00a0 B\n'),'A\u00a0 B')
  self.assertEqual(a.oracle('word_count_ascii','AéB İC'),[['a',1],['b',1],['c',1]])
  self.assertIsNone(a.oracle('parse_version','1.٢'));self.assertEqual(a.oracle('parse_version','001.0'),[1,0])
  self.assertEqual(a.oracle('min_covering_window',[1,2,1],[1,1]),[0,3])
  self.assertEqual(a.oracle('min_covering_window',[1,2,1],[1]),[0,1])
  self.assertEqual(a.oracle('apply_edits','a🙂bc',[[1,2,'X'],[3,3,'!']]),'aXb!c')
 def test_rotation_inverse_and_flatten_depth_composition(self):
  matrix=[[1,2,3],[4,5,6]];rotated=matrix
  for _ in range(4):rotated=a.oracle('rotate_matrix',rotated)
  self.assertEqual(rotated,matrix)
  value=[1,[2,[3]],False,None]
  self.assertEqual(a.oracle('flatten_depth',a.oracle('flatten_depth',value,1),1),a.oracle('flatten_depth',value,2))
  self.assertEqual(a.oracle('flatten_depth',value,0),value)
  self.assertEqual(a.oracle('natural_sort_strings',['a02','a2','a10','a1']),['a1','a02','a2','a10'])

if __name__=='__main__':unittest.main()
