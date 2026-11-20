#!/usr/bin/env python3
"""Executable-disproof selection for the coding swarm (arbiter-free; the swarm's own model writes the contracts).

Idea (astra, 2026-11-20 idea list #1): agreement between candidates is weak evidence when their errors are
correlated. Instead, the model writes an executable contract from the PUBLIC task only - test inputs plus a
`check(args, out)` that returns False only when an output certainly violates the specification (brute force on
small inputs, or exact properties) - and any candidate that the contract disproves is dropped, even if most
candidates agree with it.

Phase `contracts` (model calls, one per case = task x seed, independent of all candidates):
  the model sees function name, specification and public examples, and returns one Python block defining
  INPUTS (20-30 argument lists) and check(args, out). A contract is VALID only if, in the pinned CPU sandbox,
  it loads, yields at least one input of the right arity, and check() returns exactly True on every public
  example. Invalid contracts are never used.
Phase `select --run NAME` (sandbox only, no model calls): every feedback-passing candidate of that coding run is
  executed on the contract inputs; check() is run on each (input, output value). A candidate is DISPROVED if
  check() returns exactly False on any input (exceptions, timeouts or non-bool results never disprove).
  Frozen rule: earliest non-disproved feedback-passing candidate; if the contract is invalid, there are no
  feedback-passing candidates, or every candidate is disproved, fall back to the earliest feedback-passing
  candidate (the original rule). Selections are written before any holdout result is read; the recorded hidden
  holdout result then scores them.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_agents72 import operational_fault  # noqa: E402

SOURCE_LONG = Path(os.environ.get('SWARM_LONG_SOURCE', HERE / '.runtime/nemotron-long-source'))
SANDBOX = HERE / '.runtime/coding-xl-source'
ENDPOINTS = [f'http://127.0.0.1:{p}/v1' for p in range(18081, 18085)]
HOSTS = ['Spark_01', 'Spark_02', 'Spark_03', 'Spark_04']
SYSTEM = 'You write executable test contracts for Python functions. Return only the requested code block.'
RUN_SETS = {
    'nemotron': (('coding-hard-xl-v1', 0), ('coding-hard-xl-v1b', 0), ('coding-hard-xl-ext-v1', 4)),
    'inkling': (('inkling-coding-hard-v1', 0),),
}
FIRST_CAP, TOTAL_CAP = 12288, 16000


def contract_prompt(task):
    shown = json.dumps(task['examples'])
    return (f"Function name: {task['function_name']}\nSpecification: {task['spec']}\nExamples (args -> expected): {shown}\n\n"
            "Several independently written implementations of this function exist, and some may be subtly wrong. "
            "Write an executable test contract that can disprove wrong implementations without seeing any of them:\n"
            "1. INPUTS: a Python list of 20-30 valid argument lists, each in the same form as the examples' \"args\" "
            "(a list of positional arguments), small enough for brute force, covering edge cases and tricky cases the "
            "specification mentions.\n"
            "2. def check(args, out): return False only if `out` is certainly not what the specification requires for "
            "`args`; otherwise return True. Prefer an obviously correct brute-force reference for small inputs, or exact "
            "properties the specification implies (type, ordering, length, invariants, round trips). check must return "
            "True for every example above.\n"
            "Standard library only, no I/O, fast. Return only one ```python code block defining INPUTS and check.")


def extract_code(text):
    if not isinstance(text, str):
        return None
    blocks = re.findall(r'```(?:python|py)?\s*\n(.*?)```', text, re.S)
    code = max(blocks, key=len) if blocks else text
    return code if 'def check' in code and 'INPUTS' in code else None


def ask_contract(task, endpoint, events_path, seed):
    if str(SOURCE_LONG) not in sys.path:
        sys.path.insert(0, str(SOURCE_LONG))
    import forced72
    from harness import Budget, Events

    class Client(forced72.ForcedClient):
        def chat_prompt_ids(self, prompt):
            messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]
            with self.post('/tokenize', dict(model=self.model, messages=messages, add_generation_prompt=True,
                                             chat_template_kwargs={'enable_thinking': True}), 60) as response:
                return json.load(response)['tokens']

    events = Events(events_path, 'disproof_contract')
    try:
        client = Client(endpoint, 'swarm-model', Budget(2, TOTAL_CAP), events, seed)
        ids = client.chat_prompt_ids(contract_prompt(task))
        first = client.complete(0, 'contract', ids, FIRST_CAP)
        answer = first['answer']
        if first['finish_reason'] == 'length' and first['error'] is None:
            forced = answer is None
            second = client.complete(0, 'contract_forced' if forced else 'contract_continued',
                                     ids + first['token_ids'] + (client.force_ids() if forced else []),
                                     TOTAL_CAP - client.budget.snapshot()['completion_tokens_charged'], thinking_closed=True)
            answer = second['answer'] if forced else (answer or '') + (second['answer'] or '')
        return answer, client.infra_failures, client.budget.snapshot()['completion_tokens_charged']
    finally:
        events.close()


def sandbox(code, function_name, calls, host, timeout=30):
    """Run function_name(*args) for each call in the pinned CPU sandbox. Returns observations, or None on infra."""
    if str(SANDBOX) not in sys.path:
        sys.path.insert(0, str(SANDBOX))
    import independent_code_grader as icg
    payload = json.dumps(dict(code=code, function_name=function_name,
                              calls=[dict(args=a, kwargs={}) for a in calls], timeout=timeout), allow_nan=False)
    task = uuid.uuid4().hex
    name = 'swarm-independent-code-' + task
    command = ['docker', 'run', '--pull', 'never', '--runtime', 'runc', '-i', '--name', name,
               '--label', 'swarm-lab.code-owner=' + icg.OWNER, '--label', 'swarm-lab.code-task=' + task,
               '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--pids-limit', '64', '--memory', '256m', '--memory-swap', '256m', '--cpus', '1', '--user', '65534:65534',
               '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=16m', '--workdir', '/tmp', '--env', 'NVIDIA_VISIBLE_DEVICES=void',
               '--stop-timeout', '1', '--entrypoint', 'python3', icg.IMAGE, '-I', '-S', '-c', icg.CHILD]
    try:
        process = icg._ssh(host, command, payload, timeout + 15)
    except Exception:  # noqa: BLE001
        process = None
    _, _, clean = icg._state_and_cleanup(host, name, task)
    if process is None or process.returncode == 255 or not clean:
        return None
    try:
        data = icg._strict_json(process.stdout)
    except Exception:  # noqa: BLE001
        return []
    if 'setup_error' in data:
        return [dict(kind='setup_error', type=data['setup_error']['type'])] * len(calls)
    obs = data.get('results', [])
    return obs + [dict(kind='timeout')] * (len(calls) - len(obs))


INPUTS_FN = '\n\ndef __contract_inputs():\n    return [list(a) for a in INPUTS][:40]\n'


def validate(task, code, host):
    """VALID contract: loads, yields >= 1 input of the right arity, check() is exactly True on every example."""
    arity = len(task['examples'][0]['args'])
    got = sandbox(code + INPUTS_FN, '__contract_inputs', [[]], host)
    if got is None:
        return dict(valid=None, reason='infra')
    if not got or got[0].get('kind') != 'value' or not isinstance(got[0]['value'], list):
        return dict(valid=False, reason='inputs_unavailable')
    inputs = [a for a in got[0]['value'] if isinstance(a, list) and len(a) == arity]
    if not inputs:
        return dict(valid=False, reason='no_inputs_of_arity')
    ex = sandbox(code, 'check', [[e['args'], e['expected']] for e in task['examples']], host)
    if ex is None:
        return dict(valid=None, reason='infra')
    ok = len(ex) == len(task['examples']) and all(o.get('kind') == 'value' and o['value'] is True for o in ex)
    return dict(valid=ok, reason='ok' if ok else 'rejects_public_example', inputs=inputs if ok else None)


def contracts_main(a):
    tasks = json.loads((HERE / 'datasets/coding-hard-v1/tasks.json').read_text())['tasks']
    cases = [(t, s) for s in (1, 2, 3) for t in tasks if t['split'] == 'evaluation']
    if not a.run:
        print(json.dumps(dict(mode='plan', cases=len(cases), model_calls_max=2 * len(cases))))
        return 0
    a.output.mkdir(parents=True)
    (a.output / 'events').mkdir()
    lock, records = threading.Lock(), {}

    def work(item):
        index, (task, seed) = item
        stem = f"{task['id']}-s{seed}"
        endpoint, host = ENDPOINTS[index % 4], HOSTS[index % 4]
        answer, infra, tokens = ask_contract(task, endpoint, a.output / 'events' / (stem + '.jsonl'), 66000 + index)
        code = extract_code(answer)
        check = validate(task, code, host) if code else dict(valid=False, reason='no_code')
        rec = dict(task_id=task['id'], seed=seed, infra=infra, tokens=tokens, code=code, **check)
        with lock:
            records[stem] = rec
            (a.output / 'contracts.json').write_text(json.dumps(records, indent=1))
            print(json.dumps(dict(done=len(records), total=len(cases), case=stem, valid=rec['valid'],
                                  reason=rec['reason'], n_inputs=len(rec.get('inputs') or []), infra=infra)), flush=True)

    with ThreadPoolExecutor(a.per_node * 4) as pool:
        list(pool.map(work, enumerate(cases)))
    meta = dict(completed_utc=datetime.now(timezone.utc).isoformat(), cases=len(records),
                valid=sum(r['valid'] is True for r in records.values()),
                infra_cases=[k for k, r in records.items() if r['infra'] or r['valid'] is None],
                script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (a.output / 'summary.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    return 1 if meta['infra_cases'] else 0


def load_candidates(run_set):
    rows, seen = [], set()
    for run, shift in RUN_SETS[run_set]:
        for r in json.loads((HERE / 'runs' / run / 'summary.json').read_text()):
            name = (shift, os.path.basename(r['events']))
            if operational_fault(r) or name in seen:
                continue
            seen.add(name)
            end = next(json.loads(l) for l in open(r['events']) if '"puzzle_end"' in l)
            rows.append(dict(task_id=r['task_id'], seed=r['seed'], agent=r['agent'] + shift, code=end.get('code'),
                             feedback_pass=bool(r['feedback_pass']), holdout_pass=bool(r['holdout_pass'])))
    cases = {}
    for r in rows:
        cases.setdefault((r['task_id'], r['seed']), {})[r['agent']] = r
    return cases


def select_main(a):
    tasks = {t['id']: t for t in json.loads((HERE / 'datasets/coding-hard-v1/tasks.json').read_text())['tasks']}
    contracts = json.loads((a.contracts / 'contracts.json').read_text())
    cases = load_candidates(a.candidates)
    a.output.mkdir(parents=True)
    lock, verdicts, faults = threading.Lock(), {}, []

    def work(item):
        index, (key, case) = item
        task = tasks[key[0]]
        stem = f'{key[0]}-s{key[1]}'
        con = contracts.get(stem) or {}
        host = HOSTS[index % 4]
        out, infra = {}, 0
        if con.get('valid') is True:
            for agent in sorted(case):
                cand = case[agent]
                if not cand['feedback_pass'] or not cand['code']:
                    continue
                obs = sandbox(cand['code'], task['function_name'], con['inputs'], host)
                if obs is None:
                    infra += 1
                    out[agent] = dict(disproved=None, infra=True)
                    continue
                pairs = [[args, o['value']] for args, o in zip(con['inputs'], obs) if o.get('kind') == 'value']
                if not pairs:
                    out[agent] = dict(disproved=False, checked=0)
                    continue
                res = sandbox(con['code'], 'check', pairs, host)
                if res is None:
                    infra += 1
                    out[agent] = dict(disproved=None, infra=True)
                    continue
                failing = [i for i, r in enumerate(res) if r.get('kind') == 'value' and r['value'] is False]
                out[agent] = dict(disproved=bool(failing), checked=len(pairs), failing=len(failing),
                                  first_failing_args=pairs[failing[0]][0] if failing else None)
        with lock:
            verdicts[stem] = dict(contract_valid=con.get('valid'), agents=out, infra=infra)
            if infra:
                faults.append(stem)
            print(json.dumps(dict(done=len(verdicts), total=len(cases), case=stem, infra=infra,
                                  disproved=sorted(k for k, v in out.items() if v.get('disproved')))), flush=True)

    with ThreadPoolExecutor(a.workers) as pool:
        list(pool.map(work, enumerate(sorted(cases.items()))))
    # Freeze selections BEFORE reading any holdout result.
    selections = {}
    for k in sorted({min(8, len(c)) for c in cases.values()} | {4}):
        for key, case in sorted(cases.items()):
            stem = f'{key[0]}-s{key[1]}'
            passing = [x for x in sorted(case) if x < k and case[x]['feedback_pass']]
            v = verdicts[stem]['agents']
            survivors = [x for x in passing if not (v.get(x, {}).get('disproved') is True)]
            if verdicts[stem]['contract_valid'] is True and passing and survivors:
                chosen, rule = survivors[0], 'disproof' if survivors[0] != passing[0] else 'disproof_kept_first'
            else:
                chosen, rule = (passing[0] if passing else None), 'first_passing'
            selections[f'k{k}:{stem}'] = dict(agent=chosen, rule=rule)
    (a.output / 'verdicts.json').write_text(json.dumps(verdicts, indent=1))
    (a.output / 'selections.json').write_text(json.dumps(selections, indent=1))
    score = {}
    for k in sorted({int(s.split(':')[0][1:]) for s in selections}):
        base = dp = 0
        wrong_disproved = right_disproved = 0
        for key, case in sorted(cases.items()):
            stem = f'{key[0]}-s{key[1]}'
            agents = [x for x in sorted(case) if x < k]
            first = next((x for x in agents if case[x]['feedback_pass']), None)
            base += bool(first is not None and case[first]['holdout_pass'])
            sel = selections[f'k{k}:{stem}']['agent']
            dp += bool(sel is not None and case[sel]['holdout_pass'])
            for x in agents:
                if verdicts[stem]['agents'].get(x, {}).get('disproved') is True:
                    wrong_disproved += not case[x]['holdout_pass']
                    right_disproved += case[x]['holdout_pass']
        score[f'k{k}'] = dict(first_passing=base, disproof=dp, wrong_candidates_disproved=wrong_disproved,
                              correct_candidates_disproved=right_disproved,
                              oracle=sum(any(case[x]['holdout_pass'] for x in case if x < k) for case in cases.values()))
    meta = dict(completed_utc=datetime.now(timezone.utc).isoformat(), candidates=a.candidates, cases=len(cases),
                valid_contracts=sum(v['contract_valid'] is True for v in verdicts.values()), infra_cases=faults,
                score=score, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (a.output / 'summary.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    return 1 if faults else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('contracts')
    c.add_argument('--output', type=Path, required=True)
    c.add_argument('--run', action='store_true')
    c.add_argument('--per-node', type=int, default=1)
    s = sub.add_parser('select')
    s.add_argument('--contracts', type=Path, required=True)
    s.add_argument('--candidates', choices=sorted(RUN_SETS), required=True)
    s.add_argument('--output', type=Path, required=True)
    s.add_argument('--workers', type=int, default=8)
    a = p.parse_args(argv)
    return contracts_main(a) if a.command == 'contracts' else select_main(a)


if __name__ == '__main__':
    raise SystemExit(main())
