#!/usr/bin/env python3
"""Coding references with frozen orchestration and an independent outer grader."""
import argparse
import importlib
import inspect
import json
from pathlib import Path
import sys

import independent_code_grader as grader
import reference_worker as worker


def inject_evaluator(module):
    """Override the bound default explicitly; changing a module name is insufficient."""
    original = module.run_experiment
    signature = inspect.signature(original)
    def run_with_outer(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.arguments['evaluator'] = grader.evaluate_code
        return original(*bound.args, **bound.kwargs)
    module.run_experiment = run_with_outer
    return original


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--source', type=Path, default=worker.HERE / '.runtime/evaluation-v2-source')
    parser.add_argument('--domain', required=True)
    parser.add_argument('--transport-record', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan', action='store_true')
    args, _ = parser.parse_known_args(argv)
    worker.require(args.domain == 'coding', 'Independent grade wrapper accepts only coding references')
    if not args.run or args.plan:
        return worker.main(argv)
    worker.verify_gate(worker.HERE, audit_cohorts=False)
    source = args.source.resolve()
    pin = worker.source_pin(source)
    receipt = args.transport_record.with_suffix('.grader-context.json')
    worker.require(not receipt.exists(), 'Grader context already exists')
    old_path = list(sys.path)
    sys.path.insert(0, str(source))
    original, coding = None, None
    try:
        coding = importlib.import_module('coding_harness')
        for name in ('coding_harness', 'harness', 'sandbox_code'):
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve()
            worker.require(path == source / (name + '.py') and worker.sha(path) == pin['sha256'][name + '.py'], 'Wrong frozen module identity: ' + name)
        context = dict(protocol='independent-reference-grade-v1', source_revision=pin['revision'],
                       wrapper_sha256=worker.sha(__file__), outer_grader_sha256=worker.sha(grader.__file__),
                       frozen_module_sha256={name: pin['sha256'][name] for name in ('coding_harness.py', 'harness.py', 'sandbox_code.py')},
                       image=grader.IMAGE, grading_authority='outer_parent', oracle_sent_to_child=False,
                       scope='Frozen prompts, task partitions, selection and budgets; expected values stay in the trusted outer grader. Child observations remain unauthenticated against arbitrary interpreter tampering.')
        with receipt.open('x') as stream:
            json.dump(context, stream, indent=2)
            stream.write('\n')
        original = inject_evaluator(coding)
        return worker.main(argv)
    finally:
        if original is not None:
            coding.run_experiment = original
        sys.path[:] = old_path


if __name__ == '__main__':
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # Same case-process lifetime as the original coding CLI; no grader is active
    # after main returns. Pending transport threads belong only to this process.
    __import__('os')._exit(code)
