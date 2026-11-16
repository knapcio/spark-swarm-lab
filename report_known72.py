#!/usr/bin/env python3
"""Report the known72 follow-up runs: single agent, independent swarm and optional forced agents.

Reads only completed run directories (summary.json + metadata.json). Writes REPORT.md,
results.json and per-task CSV. Exploratory: the 24 tasks were seen while tuning.
"""
import argparse
import collections
import csv
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(run):
    rows = json.loads((run / 'summary.json').read_text())
    meta = json.loads((run / 'metadata.json').read_text())
    return rows, meta


def cases_by_agent(rows):
    cases = collections.defaultdict(dict)
    for r in rows:
        cases[(r['task_id'], r['seed'])][r.get('agent', 0)] = r
    return cases


def any_of(case, agents):
    return any(bool(case[a]['solved']) for a in agents)


def curve(cases, order):
    out = []
    for k in range(1, len(order) + 1):
        chosen = order[:k]
        full = [c for c in cases.values() if all(a in c for a in chosen)]
        out.append(dict(k=k, cases=len(full), solved=sum(any_of(c, chosen) for c in full),
                        completion_tokens=sum((c[a]['completion_tokens'] or 0) for c in full for a in chosen)))
    return out


def expected_any_of_k(cases, agents, k):
    """Average over all k-subsets of the given agents (exact, small K): removes order luck."""
    from itertools import combinations
    subsets = list(combinations(agents, k))
    full = [c for c in cases.values() if all(a in c for a in agents)]
    return sum(any_of(c, s) for c in full for s in subsets) / len(subsets), len(full)


def task_cluster_ci(cases, agents, draws=4000, seed=0):
    """Bootstrap over tasks (keeping all seeds of a task) for any-of-agents success rate."""
    by_task = collections.defaultdict(list)
    for (task, _), c in cases.items():
        if all(a in c for a in agents):
            by_task[task].append(any_of(c, agents))
    tasks = sorted(by_task)
    rng = random.Random(seed)
    stats = []
    for _ in range(draws):
        sample = [rng.choice(tasks) for _ in tasks]
        values = [v for t in sample for v in by_task[t]]
        stats.append(sum(values) / len(values))
    stats.sort()
    return stats[int(.025 * draws)], stats[int(.975 * draws) - 1]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--single', type=Path, default=HERE / 'runs/nemotron72-known-single-v1')
    p.add_argument('--swarm', type=Path, default=HERE / 'runs/nemotron72-known-swarm-v1')
    p.add_argument('--forced', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    a.output.mkdir(parents=True, exist_ok=True)
    result, lines = {}, ['# Known72 follow-up: single agent and independent swarm', '',
                         'Exploratory: these 24 evaluation tasks (x3 seeds) were seen while designing the methods. '
                         'Not fresh generalization. Every success is a plan that passed the exact verifier; '
                         'no CPU search, teacher, gold answers or shared memory.', '']
    single_rows, single_meta = load(a.single)
    single = cases_by_agent(single_rows)
    s_solved = sum(any_of(c, [0]) for c in single.values())
    result['single_scribe_full'] = dict(cases=len(single), solved=s_solved,
                                        server_completion_tokens=sum(r['server_completion_tokens'] or 0 for r in single_rows),
                                        ci95=task_cluster_ci(single, [0]), errors=single_meta['errors'])
    lines += [f'**Single scribe_full agent:** {s_solved}/{len(single)} '
              f'(task-cluster 95% interval {result["single_scribe_full"]["ci95"][0]:.1%}–{result["single_scribe_full"]["ci95"][1]:.1%}). '
              'Historical references on the same 72 attempts: one reasoning call 18/72, four independent reasoning plans 49/72, '
              'native DeepSeek 72/72.', '']
    swarm_rows, swarm_meta = load(a.swarm)
    swarm = cases_by_agent(swarm_rows)
    variants = swarm_meta['protocol']['agent_variants']
    groups = {v: [i for i, n in enumerate(variants) if n == v] for v in dict.fromkeys(variants)}
    all_agents = list(range(len(variants)))
    result['swarm'] = dict(cases=len(swarm), errors=swarm_meta.get('errors'), mixed_curve=curve(swarm, all_agents),
                           per_variant_curve={v: curve(swarm, g) for v, g in groups.items()},
                           per_agent={v: dict(runs=sum(r['arm'] == v for r in swarm_rows),
                                              solved=sum(r['arm'] == v and bool(r['solved']) for r in swarm_rows),
                                              mean_completion_tokens=sum(r['completion_tokens'] or 0 for r in swarm_rows if r['arm'] == v)
                                              / max(1, sum(r['arm'] == v for r in swarm_rows)),
                                              length_finish_runs=sum(r['arm'] == v and r['length_finishes'] > 0 for r in swarm_rows))
                                      for v in groups},
                           expected_any_of_k={k: expected_any_of_k(swarm, all_agents, k)[0] for k in range(1, len(all_agents) + 1)},
                           ci95_all=task_cluster_ci(swarm, all_agents),
                           deadlines=sum(bool(r['deadline']) for r in swarm_rows),
                           infrastructure=sum(bool(r['infrastructure_failures']) for r in swarm_rows),
                           wall_seconds=swarm_meta.get('batch_wall_seconds'))
    sw = result['swarm']
    lines += ['## Independent swarm (8 agents per case)', '',
              f'All 8 agents: **{sw["mixed_curve"][-1]["solved"]}/{sw["mixed_curve"][-1]["cases"]}** '
              f'(task-cluster 95% interval {sw["ci95_all"][0]:.1%}–{sw["ci95_all"][1]:.1%}). '
              f'Deadlines {sw["deadlines"]}, infrastructure failures {sw["infrastructure"]}.', '',
              '| Agents k | Solved (fixed order) | Expected over all k-subsets | Completion tokens |', '|---:|---:|---:|---:|']
    for row in sw['mixed_curve']:
        lines.append(f'| {row["k"]} | {row["solved"]}/{row["cases"]} | {sw["expected_any_of_k"][row["k"]]:.1f} | {row["completion_tokens"]:,} |')
    lines += ['', '| Agent type | Single-agent success | Mean completion tokens | Runs hitting a length cap | 4 agents of this type |',
              '|---|---:|---:|---:|---:|']
    for v, info in sw['per_agent'].items():
        last = sw['per_variant_curve'][v][-1]
        lines.append(f'| {v} | {info["solved"]}/{info["runs"]} ({info["solved"] / info["runs"]:.1%}) | {info["mean_completion_tokens"]:.0f} '
                     f'| {info["length_finish_runs"]} | {last["solved"]}/{last["cases"]} |')
    per_task = []
    for (task, seed), c in sorted(swarm.items()):
        per_task.append(dict(task_id=task, seed=seed, agents_solved=sum(bool(c[x]['solved']) for x in c), agents=len(c),
                             single_solved=bool(single.get((task, seed), {}).get(0, {}).get('solved'))))
    hard = sorted({r['task_id'] for r in per_task if r['agents_solved'] <= 2})
    lines += ['', f'Hardest tasks (at most 2 of 8 agents in some seed): {", ".join(hard) or "none"}.']
    if a.forced:
        forced_rows, forced_meta = load(a.forced)
        forced = cases_by_agent(forced_rows)
        fv = forced_meta['protocol']['agent_variants'][0]
        fa = list(range(len(forced_meta['protocol']['agent_variants'])))
        result['forced'] = dict(variant=fv, curve=curve(forced, fa), errors=forced_meta.get('errors'),
                                runs=len(forced_rows), solved_runs=sum(bool(r['solved']) for r in forced_rows),
                                mean_completion_tokens=sum(r['completion_tokens'] or 0 for r in forced_rows) / max(1, len(forced_rows)),
                                mean_prompt_tokens=sum(r['prompt_tokens'] or 0 for r in forced_rows) / max(1, len(forced_rows)))
        fr = result['forced']
        lines += ['', f'## Budget-forced agents ({fv})', '',
                  f'Single-agent success {fr["solved_runs"]}/{fr["runs"]} ({fr["solved_runs"] / max(1, fr["runs"]):.1%}); '
                  f'mean completion tokens {fr["mean_completion_tokens"]:.0f}, mean prompt tokens {fr["mean_prompt_tokens"]:.0f}. '
                  f'Any of {len(fa)}: {fr["curve"][-1]["solved"]}/{fr["curve"][-1]["cases"]}.']
    with (a.output / 'per-task.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(per_task[0]))
        writer.writeheader()
        writer.writerows(per_task)
    (a.output / 'results.json').write_text(json.dumps(result, indent=2, default=list) + '\n')
    (a.output / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
