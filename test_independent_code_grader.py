"""Local execution is limited to authored fixtures; SSH/Docker are always fake."""
import json
import shlex
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import independent_code_grader as g


def payload(code, calls, function='f', timeout=1):
    return dict(code=code,function_name=function,calls=[dict(args=x,kwargs={}) for x in calls],timeout=timeout)


def authored(code, tests, timeout=1):
    data=payload(code,[c['args'] for c in tests],timeout=timeout)
    for call,case in zip(data['calls'],tests):call['kwargs']=case.get('kwargs',{})
    process=g._bounded_process([sys.executable,'-I','-S','-c',g.CHILD],json.dumps(data),timeout+2)
    if process.returncode:raise AssertionError(process.stderr)
    return g.compare_observations(tests,process.stdout)


class IndependentGraderTests(unittest.TestCase):
    def test_actual_values_are_compared_only_by_outer_parent(self):
        tests=[{'args':[2,3],'expected':5},{'args':[7,8],'expected':20}]
        report=authored('def f(a,b): return a+b',tests)
        self.assertEqual((report['passed'],report['failed']),(1,1))
        self.assertEqual(report['first_failure']['actual'],15)

    def test_frame_oracle_exploit_cannot_read_expected_values(self):
        code="import sys\ndef f(x): return sys._getframe(1).f_locals['case']['expected']"
        tests=[{'args':[n],'expected':n+37} for n in [2,5,11]]
        report=authored(code,tests)
        self.assertEqual(report['passed'],0)
        self.assertEqual(report['tests_run'],3)
        self.assertIn('case',report['first_failure']['error'])

    def test_stdout_grade_forgery_cannot_pass(self):
        code="import os,sys\ndef f(x):\n os.write(sys._getframe(1).f_globals['protocol'],b'{\"status\":\"passed\",\"passed\":3}')\n os._exit(0)"
        data=payload(code,[[1]])
        process=g._bounded_process([sys.executable,'-I','-S','-c',g.CHILD],json.dumps(data),3)
        self.assertEqual(process.returncode,0)
        with self.assertRaisesRegex(ValueError,'envelope'):
            g.compare_observations([{'args':[1],'expected':42}],process.stdout)

    def test_candidate_cannot_rewrite_outer_comparison(self):
        code="import sys\ndef f(x):\n sys._getframe(1).f_globals['json_equal']=lambda *a:True\n return 0"
        report=authored(code,[{'args':[1],'expected':42}])
        self.assertEqual(report['passed'],0)
        self.assertFalse(g.json_equal(0,42))

    def test_stdout_prints_do_not_replace_return_value(self):
        report=authored("import os\ndef f(x):\n print('{\"passed\":true}')\n os.write(1,b'{\"passed\":true}')\n return 0",[{'args':[1],'expected':42}])
        self.assertEqual(report['passed'],0)

    def test_exact_types_and_serialization_contract(self):
        for expression,expected in [('True',1),('1.0',1),('(1,2)',[1,2]),('{1:2}',{'1':2}),('float("nan")',None)]:
            with self.subTest(expression=expression):
                self.assertEqual(authored('def f(): return '+expression,[{'args':[],'expected':expected}])['passed'],0)
        # A serialization TypeError is not an exception raised by the function.
        self.assertEqual(authored('def f(): return (1,2)',[{'args':[],'expected_exception':'TypeError'}])['passed'],0)
        self.assertEqual(authored('def f(): return [1,True,None]',[{'args':[],'expected':[1,True,None]}])['passed'],1)

    def test_exceptions_mutation_and_dictionary_order(self):
        report=authored("def f(xs):\n xs.clear()\n raise ValueError('authored')",[{'args':[[1]],'expected_exception':'ValueError'}])
        self.assertEqual(report['passed'],0)
        self.assertEqual(report['first_failure']['failure_kind'],'input_mutation')
        self.assertEqual(authored("def f(xs):\n xs.clear()\n raise ValueError('authored')",[{'args':[[1]],'expected_exception':'ValueError','check_input_unchanged':False}])['passed'],1)
        code="def f(): return {'b':2,'a':1}"
        case={'args':[],'expected':{'a':1,'b':2}}
        self.assertEqual(authored(code,[case])['passed'],1)
        self.assertEqual(authored(code,[dict(case,ordered_dict=True)])['passed'],0)

    def test_timeout_observation_is_not_a_grade(self):
        report=authored('def f():\n while True: pass',[{'args':[],'expected':42}],timeout=.03)
        self.assertEqual(report['status'],'timeout')
        self.assertEqual(report['passed'],0)

    def test_protocol_rejects_forged_grades_duplicate_keys_and_nonfinite(self):
        for raw in ['{"version":1,"results":[],"passed":true}',
                    '{"version":1,"version":1,"results":[]}',
                    '{"version":true,"results":[]}',
                    '{"version":1,"results":[{"kind":"value","value":1e999,"args_after":[],"kwargs_after":{}}]}']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):g.compare_observations([{'args':[],'expected':1}],raw)

    def test_bounded_local_transport_terminates_excess_output_and_timeout(self):
        with self.assertRaisesRegex(ValueError,'output'):
            g._bounded_process([sys.executable,'-c',f'import os; os.write(1,b"x"*{g.MAX_OUTPUT+1})'],timeout=2)
        with self.assertRaises(subprocess.TimeoutExpired):
            g._bounded_process([sys.executable,'-c','import time;time.sleep(5)'],timeout=.03)

    def fake_remote(self, wire, returncode=0, oom=False, cleanup=0):
        captured={}
        def remote(host,command,data=None,timeout=15):
            if command[:2]==['docker','run']:
                captured.update(command=command,payload=json.loads(data),host=host)
                return SimpleNamespace(returncode=returncode,stdout=wire,stderr='')
            if command[:2]==['docker','inspect']:
                args=captured['command'];task=next(x.split('=',1)[1] for x in args if x.startswith('swarm-lab.code-task='))
                state={'OOMKilled':oom,'ExitCode':returncode,'Error':'','Running':False}
                return SimpleNamespace(returncode=0,stdout=json.dumps(state)+'\n'+g.OWNER+'\n'+task+'\n',stderr='')
            self.assertEqual(command[:2],['sh','-c'])
            return SimpleNamespace(returncode=cleanup,stdout='',stderr='')
        return captured,remote

    def test_container_input_omits_oracles_and_keeps_isolation(self):
        wire=json.dumps({'version':1,'results':[{'kind':'value','value':'WRONG','args_after':[2],'kwargs_after':{}}]})
        captured,remote=self.fake_remote(wire)
        code='def f(x): return x\n# $(touch NEVER); `id`'
        with patch.object(g,'_ssh',side_effect=remote):
            report=g.evaluate_code(code,'f',[{'args':[2],'expected':'SYNTHETIC_PRIVATE_CANARY','ordered_dict':True}],'Spark_04')
        self.assertFalse(report['oracle_sent_to_child'])
        self.assertEqual(report['passed'],0)
        self.assertEqual(set(captured['payload']),{'code','function_name','calls','timeout'})
        self.assertEqual(captured['payload']['calls'],[{'args':[2],'kwargs':{}}])
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY',json.dumps(captured['payload']))
        self.assertNotIn(code,shlex.join(captured['command']))
        command=captured['command']
        for flag,value in [('--pull','never'),('--runtime','runc'),('--network','none'),('--memory','256m'),('--memory-swap','256m'),('--cpus','1'),('--pids-limit','64'),('--user','65534:65534'),('--security-opt','no-new-privileges')]:self.assertEqual(command[command.index(flag)+1],value)
        self.assertIn('--read-only',command)
        self.assertIn(g.IMAGE,command)
        self.assertNotIn('--rm',command)
        self.assertFalse(set(command)&{'--gpus','--device','--privileged','--volume','-v','--mount'})
        self.assertTrue(report['cleanup_ok'])
        self.assertEqual(report['grading_authority'],'outer_parent')

    def test_oom_and_cleanup_are_explicit(self):
        for clean in [0,1]:
            captured,remote=self.fake_remote('',returncode=137,oom=True,cleanup=clean)
            with patch.object(g,'_ssh',side_effect=remote):report=g.evaluate_code('def f(): pass','f',[{'args':[],'expected':None}],'Spark_04')
            self.assertEqual(report['failure_kind'],'candidate_oom' if clean==0 else 'cleanup_infrastructure')
            self.assertEqual(report['provenance'],'candidate' if clean==0 else 'infrastructure')

    def test_invalid_cases_do_not_contact_any_host(self):
        with patch.object(g,'_ssh') as ssh:
            for case in [{'args':[],'expected':(1,2)},{'args':[],'expected':{1:2}},{'args':[],'expected':float('nan')},{'args':[],'expected':1,'ordered_dict':'false'}]:
                with self.assertRaises(ValueError):g.evaluate_code('def f(): pass','f',[case],'Spark_04')
            ssh.assert_not_called()


if __name__=='__main__':unittest.main()
