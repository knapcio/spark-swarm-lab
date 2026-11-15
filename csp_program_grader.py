"""Outer graph verification for generic solve(n,k,edges); no model execution.

One fresh qualified CPU container per graph. Child observations are unauthenticated;
only the original outer graph and its exact assignment proof define acceptance.
"""
import time
from types import FunctionType

import independent_code_grader as qualified
from csp_tasks import graph_digest, verify_assignment, worker_task


def comparator(task):
    """Bind an original public graph outside the candidate process, never a witness."""
    task = worker_task(task)
    original_args = [task['vertex_count'], task['color_count'], task['edges']]
    def compare(_placeholder_tests, raw):
        data = qualified._strict_json(raw)
        if (type(data) is not dict or type(data.get('version')) is not int or data['version'] != 1
                or set(data) - {'version', 'results', 'setup_error', 'interrupted'}):
            raise ValueError('Invalid observation envelope')
        rows = data.get('results')
        if type(rows) is not list or len(rows) > 1 or data.get('interrupted') not in (None, 'timeout'):
            raise ValueError('Invalid graph observation count/interruption')
        report = dict(status='failed', passed=0, failed=1, total=1, tests_run=len(rows), solved=False,
                      proof=None, graph_verifier_calls=0, graph_edge_checks=0)
        if 'setup_error' in data:
            error = data['setup_error']
            if rows or type(error) is not dict or set(error) != {'type','message'} or not all(type(x) is str for x in error.values()):
                raise ValueError('Invalid setup error')
            report.update(status='error', failure_kind='candidate_runtime', error=error['type']+': '+error['message'][:1000])
        elif not rows and not data.get('interrupted'):
            raise ValueError('Missing graph observation')
        if rows:
            observation = rows[0]
            if type(observation) is not dict:
                raise ValueError('Invalid graph observation')
            kind = observation.get('kind')
            fields = {'value': {'kind','value','args_after','kwargs_after'},
                      'exception': {'kind','exception_type','message','args_after','kwargs_after'},
                      'serialization_error': {'kind','message'}}.get(kind)
            if kind == 'serialization_error' and set(observation) == {'kind','message','args_after','kwargs_after'}:
                fields = set(observation)
            if fields is None or set(observation) != fields:
                raise ValueError('Invalid graph observation fields')
            if kind != 'value' and type(observation.get('message')) is not str:
                raise ValueError('Invalid observation message')
            if kind == 'exception' and (type(observation['exception_type']) is not str or not observation['exception_type'].isidentifier()):
                raise ValueError('Invalid exception observation')
            unchanged = (kind != 'serialization_error' and qualified.json_equal(observation['args_after'], original_args, True)
                         and qualified.json_equal(observation['kwargs_after'], {}, True))
            report['input_unchanged'] = unchanged
            if kind == 'value':
                proof = verify_assignment(task, observation['value'])
                accepted = proof['solved'] and unchanged
                report.update(proof=proof, graph_verifier_calls=1,
                              graph_edge_checks=len(task['edges']) if proof['valid_schema'] else 0,
                              status='passed' if accepted else 'failed', passed=int(accepted), failed=int(not accepted), solved=accepted,
                              failure_kind=None if accepted else 'candidate_input_mutation' if not unchanged else 'candidate_graph_failure')
            else:
                report.update(status='error', failure_kind='candidate_runtime' if kind == 'exception' else 'candidate_serialization',
                              error=observation['message'][:1000])
        if data.get('interrupted'):
            report.update(status='timeout', solved=False, passed=0, failed=1, failure_kind='candidate_timeout')
        return report
    return compare


def evaluator_with(compare):
    """Private function globals avoid cross-call/thread monkeypatching."""
    original = qualified.evaluate_code
    clone = FunctionType(original.__code__, dict(original.__globals__, compare_observations=compare),
                         original.__name__, original.__defaults__, original.__closure__)
    clone.__kwdefaults__ = original.__kwdefaults__
    return clone


def evaluate_program(code, task, host, timeout=10):
    """Fresh container: solve receives only n,k,edges; outer parent verifies output."""
    task = worker_task(task)
    tests = [dict(args=[task['vertex_count'], task['color_count'], task['edges']], expected=None)]
    evaluate = evaluator_with(comparator(task))
    wall, cpu = time.monotonic(), time.process_time()
    report = evaluate(code, 'solve', tests, host, timeout=timeout)
    # Infrastructure/resource/protocol failure cannot inherit a successful proof.
    report['solved'] = bool(report.get('status') == 'passed' and report.get('passed') == 1
                            and report.get('cleanup_ok') is True and report.get('proof', {}).get('solved'))
    report.update(graph_sha256=graph_digest(task), wall_seconds=time.monotonic()-wall,
                  parent_cpu_seconds=time.process_time()-cpu, graph_verifier_calls=report.get('graph_verifier_calls', 0),
                  work_scope='One fresh CPU container and at most one exact full-assignment graph check; wall includes SSH/container/cleanup. No LLM-call or CPU-instruction equivalence.',
                  observation_scope='Child return value and input-after observations are unauthenticated; acceptance checks the returned assignment against the original outer graph.')
    return report
