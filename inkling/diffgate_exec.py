#!/usr/bin/env python3
"""Differential-consensus gate, the sandbox step (DIFFGATE_PLAN.json): for every frozen population item, execute the
generator reply (runs/diffgate-gen-v1, diffgate_gen.py) to get the inputs, then the accepted program and each frozen
reference on those inputs, all ONLY in the CPU-only sandbox on the given fleet hosts (inkling/sandbox_outputs.py; never
the controller host). No model call. Results go to OUTPUT/records.jsonl, one line per item, each bound to the frozen
plan (sha256), the population (sha256), the generator plan (sha256) and its generation record (sha256 of the record);
a rerun with the same OUTPUT reuses a row only if all its bindings match and refuses rows bound to anything else
(stale). The generator run must embed the frozen generator plan, cover every population item exactly once and be
complete; otherwise nothing runs. The references' hidden results are never part of the sandbox records.

Generator code: the first ```python (or ```) fenced block of the reply, else the whole reply. Items whose generator
reply was recorded as truncated or empty, or whose code fails in the sandbox, have no inputs (gate unavailable). An
infrastructure fault (ssh, docker, host identity, protocol) stops the run: the item is not recorded and the run must be
resumed.

usage: diffgate_exec.py --generations runs/diffgate-gen-v1 --hosts Spark_01 Spark_02 Spark_03 Spark_04
                        --output runs/diffgate-exec-v1 [--population DIFFGATE_POPULATION.json] [--per-host 2]
"""
import argparse
import hashlib
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import sandbox_outputs as so  # noqa: E402

FENCE = re.compile(r'```(?:python|py)?[ \t]*\n(.*?)```', re.S)
GEN_TIMEOUT, PER_INPUT, PROGRAM_TIMEOUT = 10.0, 2.0, 60.0


def generator_code(reply):
    m = FENCE.search(reply or '')
    return m.group(1) if m else (reply or '')


def read_jsonl(path):
    out = []
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def infrastructure(result):
    return bool(result.get('infrastructure'))


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_sha(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def generation_problems(gen_dir, gen_plan_sha, pop):
    """The generator run must embed the frozen generator plan, be complete and drained, and hold exactly one
    unfaulted record per population item. Returns (problems, {item: record})."""
    problems, gen_dir = [], Path(gen_dir)
    meta = json.loads((gen_dir / 'metadata.json').read_text()) if (gen_dir / 'metadata.json').exists() else {}
    summary = json.loads((gen_dir / 'summary.json').read_text()) if (gen_dir / 'summary.json').exists() else {}
    if meta.get('plan_sha256') != gen_plan_sha:
        problems.append('the generator run does not embed the frozen generator plan')
    if summary.get('complete') is not True or summary.get('drain_confirmed') is not True:
        problems.append('the generator run is not complete')
    rows = read_jsonl(gen_dir / 'run' / 'records.jsonl')
    by_item = {}
    for r in rows:
        by_item.setdefault(r.get('item'), []).append(r)
    ids = [i['item_id'] for i in pop['items']]
    missing = [i for i in ids if len(by_item.get(i, [])) != 1]
    if missing or set(by_item) - set(ids):
        problems.append(f'generator records are not exactly one per item (e.g. {missing[:3]})')
    bad = [i for i in ids if len(by_item.get(i, [])) == 1 and (by_item[i][0].get('error')
                                                                or by_item[i][0].get('outcome') is None)]
    if bad:
        problems.append(f'generator records faulted or without an outcome: {bad[:3]}')
    return problems, {i: by_item[i][0] for i in ids if len(by_item.get(i, [])) == 1}


def bindings(plan_sha, pop_sha, gen_plan_sha, generation):
    return dict(plan_sha256=plan_sha, population_sha256=pop_sha, gen_plan_sha256=gen_plan_sha,
                generation_sha256=record_sha(generation))


def run_item(item, generation, host, runner=so.run):
    """One item's sandbox work; returns (record, infrastructure fault or None)."""
    rec = dict(item=item['item_id'], host=host, inputs=None, programs=[], sandbox_seconds=0.0)
    if generation.get('outcome') != 'ok':
        rec['inputs_status'] = f"generator reply {generation.get('outcome')}"
        return rec, None
    gen = runner('generate', generator_code(generation['reply']), 'generate_inputs', host,
                 total_timeout=GEN_TIMEOUT)
    rec['sandbox_seconds'] += gen.get('container_seconds') or 0.0
    if infrastructure(gen):
        return rec, f"generator: {gen.get('error')}"
    if gen.get('status') != 'ok':
        rec['inputs_status'] = f"{gen.get('status')}: {str(gen.get('error'))[:200]}"
        return rec, None
    rec['inputs'], rec['inputs_status'] = gen['inputs'], 'ok'
    programs = [dict(role='accepted', **{k: item['passers'][0][k] for k in ('agent', 'code', 'code_sha256')})]
    programs += [dict(role='reference', run=r['run'], seed=r['seed'], agent=r['agent'], code=r['code'],
                      code_sha256=r['code_sha256']) for r in item['references']]  # never their hidden results
    for prog in programs:
        out = runner('outputs', prog['code'], item['function_name'], host, inputs=rec['inputs'],
                     per_input=PER_INPUT, total_timeout=PROGRAM_TIMEOUT)
        rec['sandbox_seconds'] += out.get('container_seconds') or 0.0
        if infrastructure(out):
            return rec, f"{prog['role']} {prog['code_sha256'][:8]}: {out.get('error')}"
        entry = {k: v for k, v in prog.items() if k != 'code'}
        entry.update(status=out.get('status'), error=out.get('error'),
                     outcomes=[o['sha256'] for o in out.get('outcomes') or []],
                     previews=[o['preview'] for o in out.get('outcomes') or []][:5])
        if entry['status'] == 'ok' and len(entry['outcomes']) != len(rec['inputs']):
            entry['status'] = 'error'
            entry['error'] = 'outcome count differs from the inputs'
        rec['programs'].append(entry)
    return rec, None


def main(argv=None, runner=so.run):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--plan', type=Path, default=ROOT / 'DIFFGATE_PLAN.json')
    p.add_argument('--gen-plan', type=Path, default=ROOT / 'DIFFGATE_GEN_PLAN.json')
    p.add_argument('--population', type=Path, default=ROOT / 'DIFFGATE_POPULATION.json')
    p.add_argument('--generations', type=Path, required=True)
    p.add_argument('--hosts', nargs='+', required=True)
    p.add_argument('--per-host', type=int, default=2)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    for host in a.hosts:
        try:
            so.check_host(host)
        except ValueError as exc:
            p.error(str(exc))
    if not 1 <= a.per_host <= 4:
        p.error('--per-host must be 1..4 (sandbox containers per host at a time)')
    pop = json.loads(a.population.read_text())
    plan_sha, pop_sha, gen_plan_sha = file_sha(a.plan), file_sha(a.population), file_sha(a.gen_plan)
    gen_plan = json.loads(a.gen_plan.read_text())
    if pop.get('status') != 'FROZEN' or gen_plan.get('status') != 'FROZEN':
        p.error('the population and the generator plan must be FROZEN')
    if gen_plan.get('population_sha256') != pop_sha:
        p.error('the generator plan is not bound to this population')
    problems, generations = generation_problems(a.generations, gen_plan_sha, pop)
    if problems:
        p.error('; '.join(problems))
    expect = {i['item_id']: bindings(plan_sha, pop_sha, gen_plan_sha, generations[i['item_id']])
              for i in pop['items']}
    a.output.mkdir(parents=True, exist_ok=True)
    sink_path = a.output / 'records.jsonl'
    existing = read_jsonl(sink_path)
    stale = [r.get('item') for r in existing if r.get('item') not in expect or r.get('bindings') != expect[r['item']]]
    if stale:
        p.error(f'{sink_path} holds rows bound to other artifacts (stale): {stale[:3]}; use a new --output')
    done = {r['item'] for r in existing}
    todo = [i for i in pop['items'] if i['item_id'] not in done]
    lock, faults, stop = threading.Lock(), [], threading.Event()
    slots = {h: threading.BoundedSemaphore(a.per_host) for h in a.hosts}

    def one(job):
        item, host = job
        with slots[host]:
            if stop.is_set():
                return
            try:
                rec, fault = run_item(item, generations[item['item_id']], host, runner)
                rec['bindings'] = expect[item['item_id']]
            except Exception as exc:
                rec, fault = None, f'{type(exc).__name__}: {str(exc)[:300]}'
            with lock:
                if fault:
                    stop.set()
                    faults.append(dict(item=item['item_id'], host=host, fault=fault))
                    return
                with sink_path.open('a') as sink:
                    sink.write(json.dumps(rec) + '\n')
                print(json.dumps(dict(item=rec['item'], inputs=rec['inputs_status'],
                                      programs=len(rec['programs']))), flush=True)
    jobs = [(item, a.hosts[i % len(a.hosts)]) for i, item in enumerate(todo)]
    with ThreadPoolExecutor(max_workers=a.per_host * len(a.hosts)) as pool:
        list(pool.map(one, jobs))
    recorded = {r['item'] for r in read_jsonl(sink_path)}
    out = dict(items=len(pop['items']), recorded=len(recorded),
               complete=recorded == {i['item_id'] for i in pop['items']}, faults=faults)
    (a.output / 'summary.json').write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps(out))
    return 0 if out['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
