"""Offline wrapper tests: synthetic modules and evaluators, no candidate execution."""
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import reference_grade_worker as g
import reference_worker as w
import run_references as r
import test_reference_baselines as fixtures


class GradeWorkerTests(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir()
            for name in ('harness','coding_harness','sandbox_code'):
                (source/(name+'.py')).write_text('# SYNTHETIC frozen interface\n')
            pin=dict(revision=w.SOURCE_REVISION,sha256={p.name:w.sha(p) for p in source.iterdir()})
            modules={name:SimpleNamespace(__file__=str(source/(name+'.py'))) for name in ('harness','coding_harness','sandbox_code')}
            events=[];client=SimpleNamespace(model='SYNTHETIC_EXACT_MODEL',budget={'max_calls':1024,'maxcompletion':131072})
            args=SimpleNamespace(method='direct',agents=1,max_tokens=8192,thinking='on')
            task={'function_name':'synthetic'}
            private={'feedback_tests':[{'args':[1],'expected':2}],'holdout_tests':[{'args':[3],'expected':4}]}
            def forbidden(*a,**k):raise AssertionError('Old bound evaluator must never run')
            def original(actual_args,actual_task,actual_private,actual_client,actual_events,evaluator=forbidden,wait_for_pending=True):
                self.assertIs(actual_args,args);self.assertIs(actual_task,task);self.assertIs(actual_private,private)
                self.assertIs(actual_client,client);self.assertIs(actual_events,events)
                self.assertFalse(wait_for_pending)
                self.assertEqual(actual_client.model,'SYNTHETIC_EXACT_MODEL')
                self.assertEqual(actual_client.budget,{'max_calls':1024,'maxcompletion':131072})
                self.assertIs(modules['harness'].Client,client)
                for phase in ('feedback_tests','holdout_tests'):
                    evaluator('SYNTHETIC_SOURCE',task['function_name'],private[phase],'SYNTHETIC_HOST')
                return 0
            modules['coding_harness'].run_experiment=original
            argv=['--run','--provider','deepseek','--source',str(source),'--domain','coding','--model','SYNTHETIC_EXACT_MODEL',
                  '--transport-record',str(root/'case.transport.jsonl'),'--','--method','direct','--agents','1',
                  '--max-tokens','8192','--max-calls','1024','--maxcompletion','131072','--thinking','on']
            def delegated(actual):
                self.assertEqual(actual,argv)
                modules['harness'].Client=client  # Existing transport adapter resolves this dynamically.
                return modules['coding_harness'].run_experiment(args,task,private,client,events,wait_for_pending=False)
            with patch.object(g.worker,'source_pin',return_value=pin) as source_pin,patch.object(g.worker,'verify_gate',return_value={'verified':True}) as gate,patch.object(g.importlib,'import_module',side_effect=lambda name:modules[name]),patch.object(g.worker,'main',side_effect=delegated) as main,patch.object(g.grader,'evaluate_code',return_value={'status':'passed'}) as evaluate:
                yield SimpleNamespace(root=root,source=source,pin=pin,modules=modules,original=original,argv=argv,
                                      source_pin=source_pin,gate=gate,main=main,evaluate=evaluate)

    def test_bound_default_is_replaced_and_receipt_records_independent_authority(self):
        with self.fixture() as f:
            self.assertEqual(g.main(f.argv),0)
            f.source_pin.assert_called_once_with(f.source.resolve())
            f.gate.assert_called_once_with(w.HERE,audit_cohorts=False)
            self.assertEqual(f.evaluate.call_count,2)
            self.assertEqual([x.args[2][0]['args'] for x in f.evaluate.call_args_list],[[1],[3]])
            self.assertIs(f.modules['coding_harness'].run_experiment,f.original)
            receipt=json.loads((f.root/'case.transport.grader-context.json').read_text())
            self.assertFalse(receipt['oracle_sent_to_child'])
            self.assertEqual(receipt['grading_authority'],'outer_parent')
            self.assertEqual(receipt['source_revision'],w.SOURCE_REVISION)
            self.assertEqual(receipt['outer_grader_sha256'],w.sha(g.grader.__file__))
            self.assertEqual(receipt['wrapper_sha256'],w.sha(g.__file__))
            self.assertEqual(receipt['frozen_module_sha256'],f.pin['sha256'])

    def test_explicit_old_evaluator_cannot_override_outer_grader(self):
        calls=[]
        def old_default(*args):raise AssertionError('old evaluator')
        def original(value,evaluator=old_default):return evaluator(value)
        module=SimpleNamespace(run_experiment=original)
        with patch.object(g.grader,'evaluate_code',side_effect=lambda value:calls.append(value)):
            g.inject_evaluator(module)
            module.run_experiment('SYNTHETIC_A')
            module.run_experiment('SYNTHETIC_B',old_default)
        self.assertEqual(calls,['SYNTHETIC_A','SYNTHETIC_B'])

    def test_gate_and_source_fail_closed_before_delegate_or_grade(self):
        for name in ('gate','source_pin'):
            with self.subTest(check=name),self.fixture() as f:
                getattr(f,name).side_effect=RuntimeError('SYNTHETIC pin failure')
                with self.assertRaisesRegex(RuntimeError,'pin failure'):g.main(f.argv)
                f.main.assert_not_called();f.evaluate.assert_not_called()
                self.assertFalse((f.root/'case.transport.grader-context.json').exists())

    def test_wrong_import_identity_is_rejected(self):
        with self.fixture() as f:
            f.modules['coding_harness'].__file__=str(f.root/'other.py')
            with self.assertRaisesRegex(RuntimeError,'Wrong frozen module identity'):g.main(f.argv)
            f.main.assert_not_called();f.evaluate.assert_not_called()

    def test_plan_delegates_unchanged_without_gate_import_or_grade(self):
        argv=['--plan','--domain','coding','--transport-record','SYNTHETIC']
        with patch.object(g.worker,'main',return_value=0) as main,patch.object(g.worker,'verify_gate') as gate,patch.object(g.worker,'source_pin') as pin,patch.object(g.importlib,'import_module') as imp:
            self.assertEqual(g.main(argv),0)
            main.assert_called_once_with(argv);gate.assert_not_called();pin.assert_not_called();imp.assert_not_called()

    def test_arithmetic_uses_original_worker_and_coding_uses_grade_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            metadata=fixtures.ReferenceTests.synthetic_metadata(root)
            with patch.object(r,'HERE',root),patch.object(r,'METADATA',metadata):
                cases,_=r.build_cases('opus',w.OPUS,w.SENTINEL,root/'output',root/'source','SYNTHETIC_CLI')
            self.assertEqual(len(cases),126)
            for case in cases:
                self.assertEqual(Path(case['command'][1]).name,'reference_worker.py' if case['domain']=='arithmetic' else 'reference_grade_worker.py')
                self.assertEqual(case['command'][case['command'].index('--max-tokens')+1],'8192')
                self.assertFalse(case['stop_on_solution'])


if __name__=='__main__':unittest.main()
