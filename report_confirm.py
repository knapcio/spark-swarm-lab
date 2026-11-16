#!/usr/bin/env python3
"""Report a fresh confirmation run (CONFIRM_*_PLAN): baseline agents 0-3 vs swarm agents 4-11.

Primary: swarm any-of-8 vs baseline any-of-4, paired by case, task-cluster bootstrap.
Also any-of-k curves (fixed order and all-subsets expectation), single-agent rates, tokens.
"""
import argparse
import collections
import json
import random
from itertools import combinations
from pathlib import Path


def load(run):
    rows = json.loads((run / 'summary.json').read_text())
    meta = json.loads((run / 'metadata.json').read_text())
    cases = collections.defaultdict(dict)
    for r in rows:
        cases[(r['task_id'], r['seed'])][r['agent']] = r
    return rows, meta, cases


def solved(case, agents):
    return any(bool(case[a]['solved']) for a in agents)


def bootstrap(cases, metric, draws=5000, seed=0):
    by_task = collections.defaultdict(list)
    for (task, _), case in cases.items():
        by_task[task].append(metric(case))
    tasks = sorted(by_task)
    rng = random.Random(seed)
    stats = []
    for _ in range(draws):
        values = [v for t in (rng.choice(tasks) for _ in tasks) for v in by_task[t]]
        stats.append(sum(values) / len(values))
    stats.sort()
    return stats[int(.025 * draws)], stats[int(.975 * draws) - 1]


def expected(cases, agents, k):
    subsets = list(combinations(agents, k))
    return sum(solved(c, s) for c in cases.values() for s in subsets) / len(subsets)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--title', required=True)
    a = p.parse_args(argv)
    rows, meta, cases = load(a.run)
    variants = meta['protocol']['agent_variants']
    base = [i for i, v in enumerate(variants) if v == variants[0]]
    swarm = [i for i, v in enumerate(variants) if v != variants[0]]
    full = {k: c for k, c in cases.items() if all(a_ in c for a_ in range(len(variants)))}
    n = len(full)
    res = dict(cases=n, errors=meta.get('errors'), incomplete=meta.get('incomplete'), wall_seconds=meta.get('batch_wall_seconds'),
               baseline_variant=variants[base[0]], swarm_variant=variants[swarm[0]])
    res['baseline_any'] = sum(solved(c, base) for c in full.values())
    res['swarm_any'] = sum(solved(c, swarm) for c in full.values())
    res['swarm_any4_matched'] = sum(solved(c, swarm[:4]) for c in full.values())
    res['paired_delta_ci95'] = bootstrap(full, lambda c: solved(c, swarm) - solved(c, base))
    res['baseline_ci95'] = bootstrap(full, lambda c: solved(c, base))
    res['swarm_ci95'] = bootstrap(full, lambda c: solved(c, swarm))
    res['single'] = {v: dict(runs=sum(r['arm'] == v for r in rows), solved=sum(r['arm'] == v and bool(r['solved']) for r in rows),
                             mean_completion_tokens=sum(r['completion_tokens'] or 0 for r in rows if r['arm'] == v) / max(1, sum(r['arm'] == v for r in rows)))
                     for v in dict.fromkeys(variants)}
    res['curves'] = {name: [dict(k=k, fixed=sum(solved(c, order[:k]) for c in full.values()), expected=round(expected(full, order, k), 2))
                            for k in range(1, len(order) + 1)] for name, order in (('baseline', base), ('swarm', swarm))}
    unsolved = sorted({k for k, c in full.items() if not solved(c, swarm)})
    res['swarm_unsolved'] = [list(k) for k in unsolved]
    res['deadlines'] = sum(bool(r['deadline']) for r in rows)
    res['infrastructure'] = sum(bool(r['infrastructure_failures']) for r in rows)
    lines = [f'# {a.title}', '',
             'Fresh tasks generated after the protocol was frozen; every success is a plan accepted by the exact verifier. '
             'No CPU search, teacher, gold answers or communication between agents.', '',
             f'**Primary (paired, {n} cases):** swarm of 8 {res["swarm_variant"]} agents **{res["swarm_any"]}/{n}** '
             f'(95% task-cluster interval {res["swarm_ci95"][0]:.1%}–{res["swarm_ci95"][1]:.1%}) vs baseline 4 {res["baseline_variant"]} agents '
             f'**{res["baseline_any"]}/{n}** ({res["baseline_ci95"][0]:.1%}–{res["baseline_ci95"][1]:.1%}); '
             f'paired difference interval {res["paired_delta_ci95"][0]:+.1%} to {res["paired_delta_ci95"][1]:+.1%}.', '',
             f'Budget-matched (4 agents each, same 32,768-token ceiling): swarm {res["swarm_any4_matched"]}/{n} vs baseline {res["baseline_any"]}/{n}.', '',
             '| Agent type | Single-agent success | Mean completion tokens |', '|---|---:|---:|']
    for v, s in res['single'].items():
        lines.append(f'| {v} | {s["solved"]}/{s["runs"]} ({s["solved"] / max(1, s["runs"]):.1%}) | {s["mean_completion_tokens"]:.0f} |')
    lines += ['', '| k | Baseline any-of-k (fixed / expected) | Swarm any-of-k (fixed / expected) |', '|---:|---:|---:|']
    for k in range(1, len(swarm) + 1):
        b = res['curves']['baseline'][k - 1] if k <= len(base) else None
        s = res['curves']['swarm'][k - 1]
        left = '{} / {}'.format(b['fixed'], b['expected']) if b else '—'
        lines.append('| {} | {} | {} / {} |'.format(k, left, s['fixed'], s['expected']))
    lines += ['', f'Swarm-unsolved cases: {", ".join(f"{t} s{s}" for t, s in unsolved) or "none"}. '
              f'Deadlines {res["deadlines"]}, infrastructure failures {res["infrastructure"]}, run errors {res["errors"]}. '
              f'Batch wall {res["wall_seconds"]:.0f} s (both arms interleaved; not per-arm throughput).']
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'results.json').write_text(json.dumps(res, indent=2) + '\n')
    (a.output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
