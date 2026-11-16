"""Offline schema/transport and balanced-plan regression tests; never call a model."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import csp_search as search
from csp_tasks import verify_assignment
import harness
import run_csp_search as runner


def task(n=24, k=3):
    return dict(id='authored-path', vertex_count=n, color_count=k,
                edges=[[i, i + 1] for i in range(n - 1)])


class GuidedFormatTests(unittest.TestCase):
    def test_schema_encodes_only_cardinality_and_domain_not_edges_or_solution(self):
        for n, k in [(24, 3), (64, 4)]:
            graph = task(n, k)
            schema = search.stage_schema(graph, 'candidate-0')
            self.assertEqual(schema, dict(type='object', properties={'assignment': dict(
                type='array', minItems=n, maxItems=n,
                items=dict(type='integer', enum=list(range(k))))},
                required=['assignment'], additionalProperties=False))
            self.assertEqual(schema, search.stage_schema(dict(graph, edges=[]), 'candidate-99'))
            # A uniformly colored graph is allowed by the format, yet must fail the exact verifier.
            proof = verify_assignment(graph, {'assignment': [0] * n})
            self.assertTrue(proof['valid_schema'])
            self.assertFalse(proof['solved'])
            self.assertEqual(proof['conflicts'], n - 1)

    def test_reviewer_schema_and_unknown_stages(self):
        self.assertEqual(search.stage_schema(task(), 'review-0'), dict(type='object',
            properties={'critique': dict(type='string', minLength=1, maxLength=4000)},
            required=['critique'], additionalProperties=False))
        with self.assertRaises(ValueError):
            search.stage_schema(task(), 'unrecognized-stage')

    def request(self, guided):
        with tempfile.TemporaryDirectory() as directory:
            events = harness.Events(Path(directory) / 'events.jsonl', 'offline')
            client = harness.Client(['http://offline.invalid/v1'], 'frozen-model', 4, 512,
                                    210, harness.Budget(16, 8192), events, 1, False)
            if guided:
                client.schema_for_stage = lambda stage: search.stage_schema(task(), stage)
            requests = []
            def fake_transport(request, timeout):
                self.assertEqual(timeout, 210)
                requests.append(json.loads(request.data))
                return io.BytesIO(json.dumps(dict(choices=[dict(finish_reason='stop',
                    message=dict(content=json.dumps({'assignment': [0] * 24})))],
                    usage=dict(prompt_tokens=12, completion_tokens=25))).encode())
            try:
                with patch('urllib.request.urlopen', side_effect=fake_transport):
                    client.call(0, 'candidate-0', 'identical frozen prompt')
            finally:
                events.close()
            return requests[0]

    def test_opt_in_changes_only_structured_outputs_body_and_preserves_seed(self):
        original, guided = self.request(False), self.request(True)
        self.assertNotIn('structured_outputs', original)
        self.assertEqual(guided.pop('structured_outputs'),
                         {'json': search.stage_schema(task(), 'candidate-0')})
        self.assertEqual(original, guided)

    def test_actual_review_search_routes_all_six_critique_calls_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            events = harness.Events(Path(directory) / 'events.jsonl', 'review_elites4')
            client = harness.Client(['http://offline.invalid/v1'], 'frozen-model', 4, 512,
                                    210, harness.Budget(16, 8192), events, 1, False)
            client.schema_for_stage = lambda stage: search.stage_schema(task(), stage)
            schemas = []
            def fake_transport(request, timeout):
                schema = json.loads(request.data)['structured_outputs']['json']
                schemas.append(schema)
                payload = {'critique': 'Check the adjacent colors.'} if 'critique' in schema['properties'] else {'assignment': [0] * 24}
                return io.BytesIO(json.dumps(dict(choices=[dict(finish_reason='stop',
                    message=dict(content=json.dumps(payload)))],
                    usage=dict(prompt_tokens=12, completion_tokens=25))).encode())
            try:
                with patch('urllib.request.urlopen', side_effect=fake_transport):
                    result = search.run_search(task(), 'review_elites4', client, events, 16)
            finally:
                events.close()
            self.assertFalse(result['solved'])
            self.assertEqual(len(schemas), 16)
            self.assertEqual(sum('critique' in x['properties'] for x in schemas), 6)
            self.assertEqual(sum('assignment' in x['properties'] for x in schemas), 10)

    def test_guided_profile_is_balanced_84_and_original_defaults_unchanged(self):
        original = runner.build_plan('core_off16', 'evaluation', 1, '/tmp/unused', runner.HERE)
        guided = runner.build_plan('core_guided_off16', 'evaluation', 1, '/tmp/unused', runner.HERE)
        self.assertEqual(guided['planned_cases'], 84)
        self.assertEqual(guided['recipe']['arms'], original['recipe']['arms'])
        self.assertEqual(len({c['task_id'] for c in guided['cases']}), 12)
        for old, new in zip(original['cases'], guided['cases']):
            self.assertNotIn('--guided-format', old['command'])
            self.assertEqual(new['command'], old['command'] + ['--guided-format'])
        for key in ['thinking', 'temperature', 'max_tokens', 'max_calls',
                    'max_completion_tokens', 'deadline_seconds', 'request_timeout_seconds']:
            self.assertEqual(original['recipe'][key], guided['recipe'][key])
        for split, seed in [('development', 1), ('evaluation', 2)]:
            with self.assertRaises(ValueError):
                runner.build_plan('core_guided_off16', split, seed, '/tmp/unused', runner.HERE)

    def test_guided_default_is_plan_only_without_gate_metrics_or_execution(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, 'verify_gate') as gate, \
                patch.object(runner, 'drain') as drain, patch.object(runner, 'execute') as execute, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main(['--profile', 'core_guided_off16', '--split',
                'evaluation', '--seed', '1', '--gate-root', directory]), 0)
            self.assertEqual(json.loads(output.getvalue())['mode'], 'plan')
            self.assertFalse((Path(directory) / 'runs').exists())
            gate.assert_not_called(); drain.assert_not_called(); execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
