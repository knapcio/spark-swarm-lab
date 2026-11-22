#!/usr/bin/env python3
"""Cost of the policies measured on 2026-11-21/22 (each arm alone on the four Sparks): solved, server-generated tokens per
case, wall, GPU-rail energy, Wh per solved case and cases per hour. Reads runs/*/arm_accounting.json, cases and the
studies' report.json files; writes results/energy-defaults-20261122/{energy.json, tables.md}."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / 'runs'
OUT = ROOT / 'results' / 'energy-defaults-20261122'


def row(corpus, label, n, solved, tokens, wall_s, wh):
    return dict(corpus=corpus, policy=label, cases=n, solved=solved, tokens_per_case=round(tokens / n), wall_min=round(wall_s / 60),
                gpu_wh=round(wh, 1), wh_per_solved=round(wh / solved, 2), cases_per_hour=round(n / (wall_s / 3600)))


def arith(d, label, corpus):
    a = json.loads((R / d / 'arm_accounting.json').read_text())
    cases = [json.loads(l) for l in (R / d / 'cases.jsonl').read_text().splitlines()]
    return row(corpus, label, len(cases), sum(c['solved'] for c in cases), a['server']['total']['generation_tokens'],
               a['runner_wall_seconds'], a['energy']['total_wh'])


def main():
    rows = []
    for corpus, pre, arms in (('arithmetic-hard-v6', 'swarm-cancel-hard6-v1', ('deep4', 'deep4cancel', 'waves2cancel')),
                              ('arithmetic-hard-v7', 'swarm-escalate-hard7-v1', ('deep4', 'deep4cancel', 'roll8cancel')),
                              ('arithmetic-hard-v8', 'swarm-burst-hard8-v1', ('roll8cancel', 'roll12burst')),
                              ('arithmetic-hard-v9', 'swarm-repair-hard9-v1', ('roll8cancel', 'roll8repair'))):
        for pol in arms:
            if (R / f'{pre}-{pol}' / 'arm_accounting.json').exists():
                rows.append(arith(f'{pre}-{pol}', pol, corpus))
    for corpus, rep, key, d, label in (('coding-hard-v1 s4-6', 'coding-earlystop-v1', 'full', 'coding-earlystop-v1-full', 'all 8 to the end'),
                                       ('coding-hard-v1 s4-6', 'coding-earlystop-v1', 'stop', 'coding-earlystop-v1-stop', 'early stop'),
                                       ('coding-hard-v1 s7-9', 'coding-stagger-v1', 'all8', 'coding-stagger-v1-e8', 'early stop'),
                                       ('coding-hard-v1 s7-9', 'coding-stagger-v1', 'stagger', 'coding-stagger-v1-s44', 'early stop + stagger')):
        a = json.loads((R / d / 'arm_accounting.json').read_text())
        solved = json.loads((ROOT / 'results' / rep / 'report.json').read_text())[key]['solved']
        rows.append(row(corpus, label, 72, solved, a['server']['total']['generation_tokens'], a['runner_wall_seconds'], a['energy']['total_wh']))
    for corpus, rep in (('arithmetic-hard-v6', 'swarm-cancel-hard6-v1'), ('arithmetic-hard-v7', 'swarm-escalate-hard7-v1')):
        j = json.loads((ROOT / 'results' / rep / 'deepseek.json').read_text())['cost']['One DeepSeek (TP4, 4 nodes)']
        rows.append(row(corpus, 'One DeepSeek (TP4, reference)', 96, j['solved'], j['tokens_per_case'] * 96, j['wall_min'] * 60, j['gpu_wh']))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'energy.json').write_text(json.dumps(rows, indent=1) + '\n')
    md = ('| Corpus | Policy | Cases | Solved | Server tokens/case | Wall | GPU Wh | Wh per solved | Cases per hour |\n'
          '|---|---|---:|---:|---:|---:|---:|---:|---:|\n' + ''.join(
              f"| {r['corpus']} | {r['policy']} | {r['cases']} | {r['solved']} | {r['tokens_per_case']:,} | {r['wall_min']} min | {r['gpu_wh']} | "
              f"{r['wh_per_solved']:.2f} | {r['cases_per_hour']} |\n" for r in rows))
    (OUT / 'tables.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
