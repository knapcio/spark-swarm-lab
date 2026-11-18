#!/usr/bin/env python3
"""Arbiter-free cross-execution selection for the coding swarm (CodeT-style), applied to frozen candidates.

The 32K coding swarm (coding-hard-xl-v1 + v1b + ext-v1, 8 agents per case) selects "the first agent whose code
passes the public feedback cases"; 10 of its 66 answers were wrong (hidden holdout failed) while some other
agent was right in 64/72 cases. CX replaces only the selection step, using nothing hidden:

1. Inputs: one Nemotron call per case (thinking on, budget-forced, 16K serving) sees the PUBLIC task (spec,
   function name, examples) and writes test INPUTS only (no expected outputs).
2. Every feedback-passing candidate is executed on those inputs in the pinned CPU sandbox (no network, 256 MB,
   1 CPU); each run yields an output signature (value, or exception type, per input).
3. Selection: the largest group of candidates with identical signatures; ties -> the group containing the
   earliest agent; the selected candidate is the earliest agent of that group. Cases with fewer than two
   distinct feedback-passing programs keep the original selection.
The hidden holdout result already recorded for each candidate scores the selection afterwards; it is never read
before the selection of every case is frozen (written to selections.json first).
"""
import argparse
import hashlib
import json
import os
import random
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
RUNS = (('coding-hard-xl-v1', 0), ('coding-hard-xl-v1b', 0), ('coding-hard-xl-ext-v1', 4))
SYSTEM = 'You write test inputs for Python functions. Return only the requested JSON.'
N_INPUTS = 24


def load_candidates():
    rows, seen = [], set()
    for run, shift in RUNS:
        for r in json.loads((HERE / 'runs' / run / 'summary.json').read_text()):
            name = (shift, os.path.basename(r['events']))  # v2 fix: ext agents share file names with agents 0-3
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


def input_prompt(task):
    shown = json.dumps(task['examples'])
    return (f"Function name: {task['function_name']}\nSpecification: {task['spec']}\nExamples (args -> expected): {shown}\n\n"
            f"Write {N_INPUTS} diverse, valid test inputs for this function that would expose bugs: edge cases, boundary "
            "values, tricky cases the specification mentions, and a few ordinary cases. Do NOT give expected outputs. "
            f"Return only a JSON array of {N_INPUTS} argument lists, each in the same form as the examples' \"args\" "
            "(a JSON array of positional arguments).")


def _elements(text):
    """Top-level elements of the first JSON array in text, each parsed on its own (v2: one broken element no
    longer discards the whole list; a truncated tail is dropped)."""
    start = text.find('[')
    if start < 0:
        return []
    out, depth, begin, in_str, esc = [], 0, None, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            esc = (ch == '\\') and not esc
            if ch == '"' and not esc:
                in_str = False
            elif ch != '\\':
                esc = False
            continue
        if ch == '"':
            in_str = True
        elif ch in '[{':
            depth += 1
            if depth == 2:
                begin = i
        elif ch in ']}':
            if depth == 2 and begin is not None:
                try:
                    out.append(json.loads(text[begin:i + 1]))
                except ValueError:
                    pass
                begin = None
            depth -= 1
            if depth == 0:
                break
    return out


def parse_inputs(text, arity):
    if not isinstance(text, str):
        return None
    out = [v for v in _elements(text) if isinstance(v, list) and len(v) == arity]
    return out[:40] or None


def gen_inputs(task, endpoint, events_path, seed):
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

    events = Events(events_path, 'cx_inputs')
    try:
        client = Client(endpoint, 'nemotron-lightning', Budget(2, 14000), events, seed)
        ids = client.chat_prompt_ids(input_prompt(task))
        first = client.complete(0, 'inputs', ids, 10240)
        answer = first['answer']
        if first['finish_reason'] == 'length' and first['error'] is None:
            # v2: thinking still open -> force it closed; thinking closed but the answer was cut -> continue it.
            forced = answer is None
            second = client.complete(0, 'inputs_forced' if forced else 'inputs_continued',
                                     ids + first['token_ids'] + (client.force_ids() if forced else []),
                                     14000 - client.budget.snapshot()['completion_tokens_charged'], thinking_closed=True)
            answer = second['answer'] if forced else (answer or '') + (second.get('response') or second['answer'] or '')
        return answer, client.infra_failures
    finally:
        events.close()


def observe(code, function_name, inputs, host, timeout=30):
    """Run one candidate on inputs in the pinned sandbox; return a list of output signatures (None = infra)."""
    if str(SANDBOX) not in sys.path:
        sys.path.insert(0, str(SANDBOX))
    import independent_code_grader as icg
    payload = json.dumps(dict(code=code, function_name=function_name,
                              calls=[dict(args=a, kwargs={}) for a in inputs], timeout=timeout), allow_nan=False)
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
        return ['crash'] * len(inputs)
    if 'setup_error' in data:
        return ['setup:' + data['setup_error']['type']] * len(inputs)
    sig = []
    for obs in data.get('results', []):
        if obs.get('kind') == 'value':
            sig.append('v:' + json.dumps(obs['value'], sort_keys=True))
        elif obs.get('kind') == 'exception':
            sig.append('e:' + obs['exception_type'])
        else:
            sig.append('s:' + obs.get('kind', '?'))
    return sig + ['timeout'] * (len(inputs) - len(sig))


def select(case, signatures, k):
    agents = [a for a in sorted(case) if a < k]
    passing = [a for a in agents if case[a]['feedback_pass']]
    first = passing[0] if passing else None
    if len({case[a]['code'] for a in passing}) < 2 or not signatures:
        return first, 'first_passing'
    groups = {}
    for a in passing:
        groups.setdefault(json.dumps(signatures.get(a)), []).append(a)
    best = max(groups.values(), key=lambda g: (len(g), -min(g)))
    return min(best), 'cx_vote'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run', action='store_true')
    p.add_argument('--per-node', type=int, default=4)
    a = p.parse_args(argv)
    tasks = {t['id']: t for t in json.loads((HERE / 'datasets/coding-hard-v1/tasks.json').read_text())['tasks']}
    cases = load_candidates()
    need = [k for k, c in sorted(cases.items()) if len({c[x]['code'] for x in c if c[x]['feedback_pass']}) >= 2]
    if not a.run:
        print(json.dumps(dict(mode='plan', cases=len(cases), cases_needing_inputs=len(need), model_calls=0)))
        return 0
    a.output.mkdir(parents=True)
    (a.output / 'inputs').mkdir()
    lock, records, faults = threading.Lock(), {}, []

    def work(item):
        index, key = item
        task_id, seed = key
        task = tasks[task_id]
        endpoint, host = ENDPOINTS[index % 4], HOSTS[index % 4]
        stem = f'{task_id}-s{seed}'
        text, infra = gen_inputs(task, endpoint, a.output / 'inputs' / (stem + '.jsonl'), 77000 + index)
        inputs = parse_inputs(text, len(task['examples'][0]['args']))
        sigs = {}
        if inputs:
            for agent, cand in sorted(cases[key].items()):
                if cand['feedback_pass']:
                    sig = observe(cand['code'], task['function_name'], inputs, host)
                    if sig is None:
                        infra += 1
                    sigs[agent] = sig
        with lock:
            records[stem] = dict(task_id=task_id, seed=seed, inputs=inputs, n_inputs=len(inputs or []), infra=infra,
                                 signatures_sha={k: hashlib.sha256(json.dumps(v).encode()).hexdigest()[:12] for k, v in sigs.items()},
                                 signatures=sigs)
            if infra:
                faults.append(stem)
            print(json.dumps(dict(done=len(records), total=len(need), case=stem, n_inputs=len(inputs or []), infra=infra)), flush=True)

    with ThreadPoolExecutor(a.per_node * 4) as pool:
        list(pool.map(work, enumerate(need)))
    (a.output / 'observations.json').write_text(json.dumps(records))
    # Freeze selections BEFORE reading any holdout result.
    selections = {}
    for k in (4, 8):
        for key, case in sorted(cases.items()):
            stem = f'{key[0]}-s{key[1]}'
            sigs = {int(x): v for x, v in (records.get(stem, {}).get('signatures') or {}).items()}
            chosen, rule = select(case, sigs, k)
            selections[f'k{k}:{stem}'] = dict(agent=chosen, rule=rule)
    (a.output / 'selections.json').write_text(json.dumps(selections, indent=1))
    # Score.
    score = {}
    for k in (4, 8):
        base = cx = 0
        for key, case in sorted(cases.items()):
            stem = f'{key[0]}-s{key[1]}'
            agents = [x for x in sorted(case) if x < k]
            first = next((x for x in agents if case[x]['feedback_pass']), None)
            base += bool(first is not None and case[first]['holdout_pass'])
            sel = selections[f'k{k}:{stem}']['agent']
            cx += bool(sel is not None and case[sel]['holdout_pass'])
        score[f'k{k}'] = dict(first_passing=base, cx=cx,
                              oracle=sum(any(case[x]['holdout_pass'] for x in case if x < k) for case in cases.values()))
    meta = dict(completed_utc=datetime.now(timezone.utc).isoformat(), cases=len(cases), cases_with_inputs=len(records),
                infra_cases=faults, score=score, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (a.output / 'summary.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    return 1 if faults else 0


if __name__ == '__main__':
    raise SystemExit(main())
