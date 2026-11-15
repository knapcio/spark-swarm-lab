"""Offline fixtures only: no Claude process, endpoint or remote grader is invoked."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

import reference_worker as w
import run_references as r


def body():
    return dict(model=w.OPUS, messages=[dict(role='system', content='exact system'), dict(role='user', content='exact user')],
                max_tokens=8192, temperature=.8, seed=123, chat_template_kwargs={'enable_thinking': True})


def reply(**changes):
    result = dict(result='{"moves":[{"i":0,"j":1,"op":"+"}]}', is_error=False, num_turns=1,
                  usage=dict(input_tokens=11, cache_read_input_tokens=7, cache_creation_input_tokens=3, output_tokens=19),
                  modelUsage={w.OPUS:dict(canonicalModel=w.OPUS, provider='firstParty', inputTokens=11, outputTokens=19, thinkingTokens=5)})
    result.update(changes)
    return result


class ReferenceTests(unittest.TestCase):
    def test_exact_messages_isolation_and_unsupported_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            captured = {}
            def runner(argv, **kwargs):
                captured.update(argv=argv, **kwargs)
                return subprocess.CompletedProcess(argv, 0, json.dumps(reply()).encode(), b'')
            record = Path(directory)/'transport.jsonl'
            transport = w.OpusTransport('/SYNTHETIC/claude', record, runner)
            request = urllib.request.Request(w.SENTINEL + '/chat/completions', data=json.dumps(body()).encode())
            with transport(request, timeout=180) as stream:
                result = json.load(stream)
            self.assertEqual(captured['input'], b'exact user')
            self.assertEqual(captured['argv'][captured['argv'].index('--system-prompt')+1], 'exact system')
            self.assertEqual(captured['argv'][captured['argv'].index('--tools')+1], '')
            self.assertFalse(captured['start_new_session'])
            self.assertEqual(captured['env']['CLAUDE_CODE_MAX_OUTPUT_TOKENS'], '8192')
            self.assertNotIn('--bare', captured['argv'])
            self.assertNotIn('--temperature', captured['argv'])
            self.assertNotIn('--seed', captured['argv'])
            self.assertEqual(result['usage'], dict(prompt_tokens=21, completion_tokens=19, total_tokens=40))
            self.assertIsNone(result['choices'][0]['finish_reason'])
            evidence = json.loads(record.read_text())
            self.assertEqual(evidence['request'], body())
            self.assertEqual(evidence['modelUsage'][w.OPUS]['thinkingTokens'], 5)
            self.assertEqual(evidence['finish_reason'], None)

    def test_no_network_fallback_or_cli_on_wrong_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            def forbidden(*a, **k):
                self.fail('No CLI invocation allowed')
            t = w.OpusTransport('/unused', Path(directory)/'record', forbidden)
            with self.assertRaisesRegex(RuntimeError, 'non-sentinel'):
                t(urllib.request.Request('https://example.com', data=b'{}'))

    def test_stderr_is_hash_only_and_failure_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            def fixture(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 1, b'', b'SYNTHETIC_CREDENTIAL_DO_NOT_RECORD')
            p = Path(directory)/'record'
            with self.assertRaisesRegex(RuntimeError, '^Opus transport failure: RuntimeError$'):
                w.OpusTransport('/fake', p, fixture)(urllib.request.Request(w.SENTINEL+'/chat/completions', data=json.dumps(body()).encode()))
            self.assertNotIn('SYNTHETIC_CREDENTIAL_DO_NOT_RECORD', p.read_text())
            self.assertEqual(json.loads(p.read_text())['stderr_bytes'], 34)

    def test_rc_zero_cli_error_does_not_persist_raw_failure_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            def fixture(argv, **kwargs):
                payload = reply(is_error=True, result='SYNTHETIC_SECRET', subtype='SYNTHETIC_SECRET',
                                modelUsage={'SYNTHETIC_SECRET': {}}, total_cost_usd='SYNTHETIC_SECRET',
                                usage={'input_tokens': 12, 'output_tokens': True, 'other': 'SYNTHETIC_SECRET'})
                return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b'')
            p = Path(directory)/'record'
            with self.assertRaisesRegex(RuntimeError, '^Opus transport failure: RuntimeError$'):
                w.OpusTransport('/fake', p, fixture)(urllib.request.Request(w.SENTINEL+'/chat/completions', data=json.dumps(body()).encode()))
            self.assertNotIn('SYNTHETIC_SECRET', p.read_text())
            evidence = json.loads(p.read_text())
            self.assertEqual(evidence['usage'], {'input_tokens': 12})
            self.assertIsNone(evidence['total_cost_usd'])
            self.assertNotIn('result', evidence)
            self.assertNotIn('modelUsage', evidence)
            self.assertNotIn('subtype', evidence)
            self.assertIn('stdout_sha256', evidence)

    def test_http_failure_records_status_without_error_body(self):
        with tempfile.TemporaryDirectory() as directory:
            def fixture(request, **kwargs):
                raise urllib.error.HTTPError(request.full_url, 403, 'SYNTHETIC_SECRET', {}, io.BytesIO(b'SYNTHETIC_SECRET'))
            p = Path(directory)/'record'
            transport = w.OpenAIRecorder('http://localhost:1234/v1', p, fixture)
            request = urllib.request.Request('http://localhost:1234/v1/chat/completions', data=json.dumps(body()).encode())
            with self.assertRaisesRegex(RuntimeError, '^Reference OpenAI transport failure: HTTPError$'):
                transport(request)
            self.assertEqual(json.loads(p.read_text())['http_status'], 403)
            self.assertNotIn('SYNTHETIC_SECRET', p.read_text())

    def test_wrong_model_or_auxiliary_model_rejected(self):
        for models in [{'other':{'provider':'firstParty'}}, {w.OPUS:{'provider':'gateway'}},
                       {w.OPUS:{'provider':'firstParty'}, 'haiku':{'provider':'firstParty'}}]:
            with tempfile.TemporaryDirectory() as directory:
                def fixture(argv, **kwargs):
                    return subprocess.CompletedProcess(argv, 0, json.dumps(reply(modelUsage=models, result='SYNTHETIC_SECRET')).encode(), b'')
                with self.assertRaisesRegex(RuntimeError, 'Opus transport failure'):
                    w.OpusTransport('/fake', Path(directory)/'record', fixture)(urllib.request.Request(w.SENTINEL+'/chat/completions', data=json.dumps(body()).encode()))
                self.assertNotIn('SYNTHETIC_SECRET', (Path(directory)/'record').read_text())

    def test_missing_usage_stays_unknown_and_reasoning_not_double_counted(self):
        self.assertEqual(w.token_usage(reply(usage={})), {})
        self.assertEqual(w.token_usage(reply(usage={'input_tokens':3,'output_tokens':9})), {'completion_tokens':9})
        self.assertEqual(w.token_usage(reply())['completion_tokens'], 19)

    def test_deepseek_records_without_altering_openai_body(self):
        with tempfile.TemporaryDirectory() as directory:
            request = urllib.request.Request('http://localhost:1234/v1/chat/completions', data=json.dumps(body()).encode())
            def fixture(actual, **kwargs):
                self.assertIs(actual, request)
                return io.BytesIO(b'{"model":"SYNTHETIC-DeepSeek","choices":[],"usage":{}}')
            p=Path(directory)/'record'
            t=w.OpenAIRecorder('http://localhost:1234/v1',p,fixture)
            self.assertEqual(json.load(t(request))['model'],'SYNTHETIC-DeepSeek')
            self.assertEqual(json.loads(p.read_text())['request'],body())

    def test_plan_is_126_direct_same_templates_and_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'not-created'
            metadata = self.synthetic_metadata(root)
            with patch.object(r, 'HERE', root), patch.object(r, 'METADATA', metadata):
                cases, _ = r.build_cases('opus', w.OPUS, w.SENTINEL, output, root / 'SYNTHETIC_SOURCE', '/fake/claude')
            self.assertEqual(len(cases),126)
            self.assertFalse(output.exists())
            self.assertEqual(len({(c['domain'],c['task_id'],c['seed']) for c in cases}),126)
            self.assertTrue(all(c['shared_endpoint'] and not c['stop_on_solution'] and not c['server_metrics'] for c in cases))
            code=[c for c in cases if c['domain']=='coding']
            self.assertEqual({c['grader_host'] for c in code},{'Spark_01','Spark_02','Spark_03','Spark_04'})
            self.assertTrue(all(c['command'][c['command'].index('--max-tokens')+1]=='8192' for c in cases))
            self.assertEqual({c['seed'] for c in cases},{1,2,3})

    def test_client_and_math_verifier_work_with_synthetic_cli(self):
        # Use the frozen worktree locally, checkout interfaces in portable CI.
        # A separate interpreter avoids contaminating other tests' harness imports.
        script = r"""
import contextlib, importlib, json, pathlib, sys, tempfile, subprocess
from unittest.mock import patch
import reference_worker as w
source=w.HERE/'.runtime/evaluation-v2-source'
source_scope='frozen_worktree' if source.is_dir() else 'checkout_equivalent_interfaces'
source=source if source.is_dir() else w.HERE
sys.path.insert(0,str(source));h=importlib.import_module('harness')
assert pathlib.Path(h.__file__).resolve().parent==source.resolve()
with tempfile.TemporaryDirectory() as d:
 p=pathlib.Path(d); calls=[]
 def fake(argv,**kwargs):
  calls.append(kwargs['input'])
  result={'result':'{"moves":[{"i":0,"j":1,"op":"+"}]}','is_error':False,'num_turns':1,
          'modelUsage':{w.OPUS:{'canonicalModel':w.OPUS,'provider':'firstParty'}},
          'usage':{'input_tokens':10,'cache_read_input_tokens':0,'cache_creation_input_tokens':0,'output_tokens':8}}
  return subprocess.CompletedProcess(argv,0,json.dumps(result).encode(),b'')
 t=w.OpusTransport('/SYNTHETIC/claude',p/'transport',fake)
 with patch('urllib.request.urlopen',t),contextlib.redirect_stdout(__import__('io').StringIO()):
  rc=h.main(['--method','direct','--puzzle','1,2:3','--model',w.OPUS,'--agents','1','--max-tokens','8192',
             '--max-completion-tokens','32768','--max-calls','1280','--rounds','5','--thinking',
             '--endpoint',w.SENTINEL,'--events',str(p/'events')])
 rows=[json.loads(x) for x in (p/'events').read_text().splitlines()]
 assert rc==0 and len(calls)==1
 assert any(x['type']=='reward' and x['solved'] is True for x in rows)
 end=[x for x in rows if x['type']=='request_end'][0]
 assert end['usage']['completion_tokens']==8 and end['finish_reason'] is None
 assert end['response']=='{"moves":[{"i":0,"j":1,"op":"+"}]}'
"""
        result = subprocess.run([__import__('sys').executable, '-c', script], cwd=w.HERE, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_parser_and_single_holdout_with_synthetic_cli(self):
        script = r"""
import contextlib, importlib, json, pathlib, sys, tempfile, subprocess, argparse
from unittest.mock import patch
import reference_worker as w
source=w.HERE/'.runtime/evaluation-v2-source'
source_scope='frozen_worktree' if source.is_dir() else 'checkout_equivalent_interfaces'
source=source if source.is_dir() else w.HERE
sys.path.insert(0,str(source))
h=importlib.import_module('harness');c=importlib.import_module('coding_harness')
assert pathlib.Path(h.__file__).resolve().parent==source.resolve()
assert pathlib.Path(c.__file__).resolve().parent==source.resolve()
with tempfile.TemporaryDirectory() as d:
 p=pathlib.Path(d);calls=[];grades=[]
 code='def add(a, b):\n    return a + b'
 def fake(argv,**kwargs):
  calls.append(kwargs['input'].decode())
  result={'result':code,'is_error':False,'num_turns':1,'modelUsage':{w.OPUS:{'canonicalModel':w.OPUS,'provider':'firstParty'}}}
  return subprocess.CompletedProcess(argv,0,json.dumps(result).encode(),b'')
 def evaluate(actual,function,tests,host):
  assert actual==code and function=='add' and host=='SYNTHETIC_HOST'
  grades.append(tests[0]['args']);return {'status':'passed','passed':len(tests),'total':len(tests),'cleanup_ok':True}
 events=h.Events(p/'events','direct');budget=h.Budget(1024,131072)
 client=h.Client([w.SENTINEL],w.OPUS,1,8192,180,budget,events,1,True)
 client.system_prompt='Implement or review the specified pure Python function. Return complete Python source for code proposals and the requested JSON for voting. Do not explain or use tools.'
 client.response_parser=c.parse_python_response
 task={'id':'SYNTHETIC','function_name':'add','spec':'Return sum.','examples':[{'args':[1,2],'expected':3},{'args':[2,4],'expected':6}]}
 private={'feedback_tests':[{'args':[11,13],'expected':24}],'holdout_tests':[{'args':[29,31],'expected':60}]}
 args=argparse.Namespace(agents=1,rounds=1,method='direct',host='SYNTHETIC_HOST',code_format='python')
 with patch('urllib.request.urlopen',w.OpusTransport('/SYNTHETIC/claude',p/'transport',fake)):
  result=c.run_experiment(args,task,private,client,events,evaluator=evaluate)
 events.close()
 assert result['solved'] is True and len(calls)==1 and grades==[[11,13],[29,31]]
 assert '29' not in calls[0] and '31' not in calls[0] and '11' not in calls[0]
 rows=[json.loads(x) for x in (p/'events').read_text().splitlines()]
 assert len([x for x in rows if x['type']=='evaluation_end' and x['phase']=='holdout'])==1
"""
        result = subprocess.run([__import__('sys').executable, '-c', script], cwd=w.HERE, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @staticmethod
    def synthetic_metadata(root, curated=False):
        metadata = {}
        for domain, count in [('arithmetic', 24), ('coding', 18)]:
            relative = r.CURATED_METADATA[domain] if curated else f'SYNTHETIC-{domain}.json'
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            cases = []
            for i in range(count):
                flags = ['--method', 'direct', '--seed', '1', '--endpoint', 'http://SYNTHETIC.invalid/v1',
                         '--events', 'SYNTHETIC_OLD_EVENTS', '--max-tokens', '8192']
                if domain == 'arithmetic':
                    flags += ['--model', 'SYNTHETIC_MODEL', '--puzzle', '1,2:3']
                else:
                    flags += ['--tasks', 'SYNTHETIC_TASKS', '--tests', 'SYNTHETIC_TESTS']
                cases.append(dict(task_id=f'SYNTHETIC-{domain}-{i}', slot=i % 4, grader_host=f'Spark_0{1+i%4}',
                                  arm=r.ARMS[domain], command=['python3', 'SYNTHETIC_HARNESS.py'] + flags))
            path.write_text(json.dumps({'cases': cases}))
            metadata[domain] = relative
        return metadata

    def test_public_plan_falls_back_to_curated_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.synthetic_metadata(root, curated=True)
            with patch.object(r, 'HERE', root):
                cases, hashes = r.build_cases('opus', w.OPUS, w.SENTINEL, root/'output', root/'SOURCE', '/fake/claude')
            self.assertEqual(len(cases), 126)
            self.assertEqual(set(hashes), set(r.CURATED_METADATA.values()))
            self.assertFalse((root/'runs').exists())

    @staticmethod
    def attempt(deadline=False, completed=True, domain='arithmetic'):
        row = dict(domain=domain, calls=1, completed_calls=int(completed), unfinished_calls=int(not completed),
                   deadline=deadline, controller_stop=deadline, status='deadline' if deadline else 'complete',
                   returncode=-15 if deadline else 0, controller_error=None, malformed_lines=0, solved=False,
                   infrastructure_failures=None if deadline else 0, missing_prompt_usage=0, missing_completion_usage=0,
                   length_finishes=0)
        records = [dict(type='request_start', request_id='SYNTHETIC-request')]
        if completed:
            records.append(dict(type='request_end', request_id='SYNTHETIC-request', error=None, response='SYNTHETIC-model-text', finish_reason=None))
        if deadline:
            records.append(dict(type='controller_stop', deadline=True, returncode=row['returncode']))
        return row, records

    def test_controlled_deadline_is_budget_outcome_with_unknown_usage(self):
        row, records = self.attempt(deadline=True, completed=False)
        original = dict(row)
        result = r.assess_attempt(row, records)
        self.assertEqual(result['reference_attempt_status'], 'task_budget_exhausted')
        self.assertIsNone(result['reference_operational_halt_reason'])
        self.assertFalse(result['reference_usage_complete'])
        self.assertIsNone(result['reference_output_cap_reached'])
        self.assertTrue(result['reference_infrastructure_count_unknown'])
        self.assertEqual(row, original)  # Preserve unsolved and unknown; never invent infrastructure zero.
        row['solved'] = True
        records.append(dict(type='reward', solved=True))
        self.assertIsNone(r.assess_attempt(row, records)['reference_operational_halt_reason'])
        self.assertTrue(row['solved'])

    def test_completed_output_cap_parser_failure_is_quality_outcome(self):
        row, records = self.attempt()
        row['length_finishes'] = 1
        records[-1].update(error='JSONDecodeError: SYNTHETIC-truncated', finish_reason='length')
        result = r.assess_attempt(row, records)
        self.assertEqual(result['reference_attempt_status'], 'completed')
        self.assertTrue(result['reference_output_cap_reached'])
        self.assertIsNone(result['reference_operational_halt_reason'])

    def test_deadline_needs_dispatch_controlled_exit_and_no_transport_fault(self):
        for fault in ['no_dispatch', 'wrong_request_id', 'crash', 'not_controlled', 'transport', 'known_infrastructure']:
            with self.subTest(fault=fault):
                row, records = self.attempt(deadline=True)
                if fault == 'no_dispatch': records = []
                elif fault == 'wrong_request_id': records[1]['request_id'] = 'different'
                elif fault == 'crash': row['returncode'] = -11
                elif fault == 'not_controlled': row['controller_stop'] = False
                elif fault == 'transport': records[1].update(error='URLError: SYNTHETIC', response=None)
                else: row['infrastructure_failures'] = 1
                result = r.assess_attempt(row, records)
                self.assertEqual(result['reference_attempt_status'], 'requires_review')
                self.assertIsNotNone(result['reference_operational_halt_reason'])

    def test_deadline_during_grade_retains_budget_outcome_but_halts_for_cleanup(self):
        row, records = self.attempt(deadline=True, domain='coding')
        records.append(dict(type='evaluation_start', evaluation_id='SYNTHETIC-grade'))
        result = r.assess_attempt(row, records)
        self.assertEqual(result['reference_attempt_status'], 'task_budget_exhausted')
        self.assertEqual(result['reference_operational_halt_reason'], 'active_coding_grade_requires_exact_owner_cleanup_review')
        records.append(dict(type='evaluation_end', evaluation_id='SYNTHETIC-grade', infrastructure_error=False))
        self.assertIsNone(r.assess_attempt(row, records)['reference_operational_halt_reason'])
        records[-1]['infrastructure_error'] = True
        self.assertEqual(r.assess_attempt(row, records)['reference_attempt_status'], 'requires_review')

    def test_unexplained_missing_completion_is_not_admitted_as_deadline(self):
        row, records = self.attempt(completed=False)
        result = r.assess_attempt(row, records)
        self.assertEqual(result['reference_attempt_status'], 'requires_review')

    def test_optional_private_preflight_records_presence_and_null_portably(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(w.optional_opus_preflight(root), {'opus_preflight_present': False, 'opus_preflight_sha256': None})
            path = root/'diagnostics/swarm-prototype-20261115/opus-access-preflight-20261115.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"scope":"SYNTHETIC"}')
            self.assertEqual(w.optional_opus_preflight(root), {'opus_preflight_present': True, 'opus_preflight_sha256': w.sha(path)})

    def test_real_execution_gate_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                w.verify_gate(Path(directory))

    def test_gate_rejects_claim_without_matching_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            runs=Path(directory)/'runs';runs.mkdir()
            (runs/'throughput-followup-v2-complete.json').write_text(json.dumps(dict(verified=True,development_cohorts=16,evaluation_cohorts=9,ledger_sha256='wrong')))
            (runs/'throughput-followup-v2-ledger.json').write_text('[]')
            with self.assertRaisesRegex(RuntimeError,'hash mismatch'):
                w.verify_gate(Path(directory))


if __name__=='__main__':
    unittest.main()
