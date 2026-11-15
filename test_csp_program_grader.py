"""Authored tiny graphs and fake SSH only; no candidate, corpus or container runs."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import csp_program_grader as c
import independent_code_grader as q

PATH = dict(id='authored-path', vertex_count=3, color_count=2, edges=[[0,1],[1,2]])
TRIANGLE = dict(id='authored-triangle', vertex_count=3, color_count=2, edges=[[0,1],[0,2],[1,2]])


def wire(value, task=PATH, **updates):
    row=dict(kind='value', value=value, args_after=[task['vertex_count'],task['color_count'],copy.deepcopy(task['edges'])], kwargs_after={})
    row.update(updates)
    return json.dumps(dict(version=1,results=[row]))


def remote_fixture(raw, returncode=0, oom=False, cleanup=0):
    captured={}
    def ssh(host,command,payload=None,timeout=15):
        if command[:2]==['docker','run']:
            captured.update(host=host,command=command,payload=json.loads(payload),timeout=timeout)
            return SimpleNamespace(returncode=returncode,stdout=raw,stderr='')
        if command[:2]==['docker','inspect']:
            token=next(x.split('=',1)[1] for x in captured['command'] if x.startswith('swarm-lab.code-task='))
            return SimpleNamespace(returncode=0,stdout=json.dumps(dict(OOMKilled=oom,ExitCode=returncode,Error='',Running=False))+'\n'+q.OWNER+'\n'+token+'\n',stderr='')
        if command[:2]!=['sh','-c']:raise AssertionError('Unexpected transport')
        return SimpleNamespace(returncode=cleanup,stdout='',stderr='')
    return captured,ssh


class ProgramGraderTests(unittest.TestCase):
    def test_exact_assignment_uses_original_graph_not_placeholder_equality(self):
        compare=c.comparator(PATH)
        for value in [None,{'assignment':[False,True,False]}, {'assignment':[0,0,0]}, {'assignment':[0,1,0],'passed':True}]:
            with self.subTest(value=value):
                report=compare([{'expected':None}],wire(value))
                self.assertFalse(report['solved']);self.assertEqual(report['passed'],0)
                self.assertEqual(report['graph_verifier_calls'],1)
                self.assertEqual(report['candidate_output'],value)
                self.assertEqual(c.verify_assignment(PATH,report['candidate_output']),report['proof'])
        report=compare([{'expected':None}],wire({'assignment':[0,1,0]}))
        self.assertEqual(report['status'],'passed');self.assertTrue(report['solved'])
        self.assertEqual(report['graph_edge_checks'],2)
        self.assertEqual(report['candidate_output'],{'assignment':[0,1,0]})
        self.assertEqual(c.verify_assignment(PATH,report['candidate_output']),report['proof'])

    def test_changed_inputs_never_change_outer_graph(self):
        task=copy.deepcopy(PATH)
        report=c.comparator(task)([],wire({'assignment':[0,1,0]},args_after=[3,2,[]]))
        self.assertFalse(report['solved']);self.assertFalse(report['input_unchanged'])
        self.assertTrue(report['proof']['solved'])
        self.assertEqual(task,PATH)

    def test_envelope_fields_counts_and_nonfinite_are_strict(self):
        rows=[{'status':'passed','passed':1}, {'version':True,'results':[]},
              {'version':1,'results':[]}, {'version':1,'results':[],'solved':True},
              {'version':1,'results':[{},{}]},
              {'version':1,'results':[{'kind':'value','value':None,'args_after':[],'kwargs_after':{},'proof':True}]}]
        for row in rows:
            with self.subTest(row=row),self.assertRaises(ValueError):c.comparator(PATH)([],json.dumps(row))
        for raw in ['{"version":1,"version":1,"results":[]}',wire(float('nan'))]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):c.comparator(PATH)([],raw)

    def test_timeout_exception_setup_and_serialization_never_solve(self):
        rows=[dict(version=1,results=[],interrupted='timeout'),
              dict(version=1,results=[],setup_error={'type':'SyntaxError','message':'authored'}),
              dict(version=1,results=[dict(kind='exception',exception_type='RuntimeError',message='authored',args_after=[3,2,PATH['edges']],kwargs_after={})]),
              dict(version=1,results=[dict(kind='serialization_error',message='authored')])]
        late=json.loads(wire({'assignment':[0,1,0]}));late['interrupted']='timeout';rows.append(late)
        for row in rows:
            with self.subTest(row=row):
                report=c.comparator(PATH)([],json.dumps(row))
                self.assertFalse(report['solved']);self.assertEqual(report['passed'],0)
                self.assertIn(report['status'],['error','timeout'])

    def test_clone_preserves_qualified_function_defaults_and_parallel_private_bindings(self):
        original=q.evaluate_code;comparison=q.compare_observations
        first=c.evaluator_with(c.comparator(PATH));second=c.evaluator_with(c.comparator(TRIANGLE))
        self.assertIs(first.__code__,original.__code__)
        self.assertIs(first.__defaults__,original.__defaults__)
        self.assertEqual(first.__defaults__,(10,))
        self.assertEqual(set(first.__globals__),set(original.__globals__))
        for key in original.__globals__:
            if key!='compare_observations':self.assertIs(first.__globals__[key],original.__globals__[key])
        self.assertIs(q.compare_observations,comparison);self.assertIs(q.evaluate_code,original)
        with ThreadPoolExecutor(2) as pool:
            path,triangle=list(pool.map(lambda f:f.__globals__['compare_observations']([],wire({'assignment':[0,1,0]})),[first,second]))
        self.assertTrue(path['solved']);self.assertFalse(triangle['solved'])
        self.assertIs(q.compare_observations,comparison)

    def test_real_api_reuses_child_isolation_cleanup_and_omits_oracle(self):
        captured,ssh=remote_fixture(wire({'assignment':[0,1,0]}))
        with patch.object(q,'_ssh',side_effect=ssh):
            report=c.evaluate_program('SYNTHETIC_SOURCE_ONLY',PATH,'Spark_04')
        self.assertTrue(report['solved']);self.assertTrue(report['cleanup_ok'])
        self.assertFalse(report['oracle_sent_to_child']);self.assertEqual(report['grading_authority'],'outer_parent')
        self.assertEqual(captured['payload'],dict(code='SYNTHETIC_SOURCE_ONLY',function_name='solve',calls=[dict(args=[3,2,PATH['edges']],kwargs={})],timeout=10))
        self.assertEqual(captured['timeout'],25)
        command=captured['command']
        self.assertEqual(command[-1],q.CHILD);self.assertIn(q.IMAGE,command)
        for flag,value in [('--network','none'),('--memory','256m'),('--memory-swap','256m'),('--cpus','1'),('--user','65534:65534'),('--runtime','runc')]:
            self.assertEqual(command[command.index(flag)+1],value)
        self.assertIn('--read-only',command)
        self.assertFalse(set(command)&{'--gpus','--device','--privileged','--volume','-v','--mount'})
        self.assertEqual(report['graph_verifier_calls'],1)
        self.assertGreaterEqual(report['wall_seconds'],0)
        self.assertIsNone(report['remote_cpu_seconds'])
        self.assertIn('not instrumented',report['remote_cpu_seconds_reason'])
        self.assertIn('concurrent',report['parent_cpu_scope'])

    def test_protocol_oom_and_cleanup_failure_remain_non_success(self):
        for raw,rc,oom,cleanup,kind in [('{"status":"passed"}',0,False,0,'candidate_protocol'),('',137,True,0,'candidate_oom'),(wire({'assignment':[0,1,0]}),0,False,1,'cleanup_infrastructure')]:
            with self.subTest(kind=kind):
                _,ssh=remote_fixture(raw,rc,oom,cleanup)
                with patch.object(q,'_ssh',side_effect=ssh):report=c.evaluate_program('SYNTHETIC',PATH,'Spark_04')
                self.assertFalse(report['solved']);self.assertEqual(report['failure_kind'],kind)


if __name__=='__main__':unittest.main()
