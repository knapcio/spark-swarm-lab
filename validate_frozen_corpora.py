#!/usr/bin/env python3
"""Offline checks of frozen arithmetic witnesses and trusted coding references."""
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import coding_tasks
import make_tasks
from sandbox_code import _run_cases

HERE = Path(__file__).resolve().parent

def load(name):
    return json.loads((HERE / name).read_text())

def main():
    arithmetic = load('datasets/arithmetic-v1/tasks.json')
    witnesses = load('datasets/arithmetic-v1/reference-witnesses.json')
    assert arithmetic['protocol'] == witnesses['protocol'] == make_tasks.PROTOCOL
    make_tasks.verify(arithmetic['tasks'], witnesses['witnesses'], set(witnesses['excluded_prior_fingerprints']))
    public = load('datasets/coding-v1/tasks.json')
    private = load('datasets/coding-v1/hidden-tests.json')
    assert public['protocol'] == private['protocol'] == coding_tasks.PROTOCOL
    tasks = public['tasks']
    assert Counter(t['split'] for t in tasks) == {'development': 6, 'evaluation': 18}
    assert len({t['function_name'] for t in tasks}) == len(tasks) == 24
    assert {t['id'] for t in tasks} == set(private['references'])
    trusted = {fn.__name__: fn for fn, *_ in coding_tasks.TASKS}
    count = 0
    for task in tasks:
        fn, ref = trusted[task['function_name']], private['references'][task['id']]
        assert hashlib.sha256(inspect.getsource(fn).encode()).hexdigest() == ref['trusted_reference_sha256']
        assert hashlib.sha256(ref['trusted_reference_source'].encode()).hexdigest() == ref['trusted_reference_sha256']
        partitions = [task['examples'], ref['feedback_tests'], ref['holdout_tests']]
        inputs = [{json.dumps([case['args'], case.get('kwargs', {})]) for case in cases} for cases in partitions]
        assert len(partitions[0]) == 2 and all(len(cases) >= 3 for cases in partitions[1:])
        assert all(not inputs[i] & inputs[j] for i in range(3) for j in range(i))
        for cases in partitions:
            assert _run_cases(fn, cases)['status'] == 'passed', task['id']
        count += len(ref['feedback_tests']) + len(ref['holdout_tests'])
    print(f'Validated 32 arithmetic witnesses, 24 trusted coding references, {count} feedback/holdout cases.')

if __name__ == '__main__': main()
