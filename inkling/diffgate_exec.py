#!/usr/bin/env python3
"""Differential-consensus gate, the sandbox step (DIFFGATE_PLAN.json): for every frozen population item, execute the
generator reply (runs/diffgate-gen-v1, diffgate_gen.py) to get the inputs, then the accepted program and each frozen
reference on those inputs, all ONLY in the CPU-only sandbox on the given fleet hosts (inkling/sandbox_outputs.py; never
the controller host). No model call. Results go to OUTPUT/records.jsonl, one line per item; a rerun with the same
OUTPUT skips items already recorded without an infrastructure fault (resume).

Generator code: the first ```python (or ```) fenced block of the reply, else the whole reply. Items whose generator
reply was not recorded as 'ok' or whose code fails in the sandbox have no inputs (gate unavailable). An infrastructure
fault (ssh, docker, protocol, cleanup) stops the run: the item is not recorded and the run must be resumed.

usage: diffgate_exec.py --generations runs/diffgate-gen-v1 --hosts Spark_01 Spark_02 Spark_03 Spark_04
                        --output runs/diffgate-exec-v1 [--population DIFFGATE_POPULATION.json] [--per-host 2]
"""
import argparse
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


def run_item(item, generation, host, runner=so.run):
    """One item's sandbox work; returns (record, infrastructure fault or None)."""
    rec = dict(item=item['item_id'], host=host, inputs=None, programs=[], sandbox_seconds=0.0)
    if not generation or generation.get('outcome') != 'ok' or generation.get('error'):
        rec['inputs_status'] = 'no generator reply'
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
                      code_sha256=r['code_sha256'], holdout_pass=r['holdout_pass']) for r in item['references']]
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
    if pop.get('status') != 'FROZEN':
        p.error('the population is not FROZEN')
    summary = json.loads((a.generations / 'summary.json').read_text())
    if summary.get('complete') is not True or summary.get('drain_confirmed') is not True:
        p.error('the generator run is not complete')
    generations = {r['item']: r for r in read_jsonl(a.generations / 'run' / 'records.jsonl')}
    a.output.mkdir(parents=True, exist_ok=True)
    sink_path = a.output / 'records.jsonl'
    done = {r['item'] for r in read_jsonl(sink_path)}
    todo = [i for i in pop['items'] if i['item_id'] not in done]
    lock, faults, stop = threading.Lock(), [], threading.Event()
    slots = {h: threading.BoundedSemaphore(a.per_host) for h in a.hosts}

    def one(job):
        item, host = job
        with slots[host]:
            if stop.is_set():
                return
            try:
                rec, fault = run_item(item, generations.get(item['item_id']), host, runner)
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
