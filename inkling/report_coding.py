#!/usr/bin/env python3
"""Inkling-2-Mini coding swarm (8 x code_xl 32K) on coding-hard-v1 vs Nemotron (same setup) and DeepSeek.

Inkling agents: runs/inkling-coding-hard-v1 (kept: finished without an operational fault) + runs/inkling-coding-hard-v1b
(resume after amendment 1). Nemotron agents: coding-hard-xl-v1 + v1b (agents 0-3) + ext-v1 (agents 4-7), as in
cx_select.load_candidates. Selection: first agent in fixed order whose code passes all public feedback cases;
solved if it passes all hidden holdout cases.
"""
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from run_agents72 import operational_fault  # noqa: E402

RUNS = HERE / 'runs'


def load(runs):
    cases, seen, faults = {}, set(), 0
    for run, shift in runs:
        for r in json.loads((RUNS / run / 'summary.json').read_text()):
            name = (shift, os.path.basename(r['events']))
            if operational_fault(r):
                faults += 1
                continue
            if name in seen:
                continue
            seen.add(name)
            tokens = r.get('charged_completion_tokens') or r.get('completion_tokens') or 0
            cases.setdefault((r['task_id'], r['seed']), {})[r['agent'] + shift] = dict(
                feedback=bool(r['feedback_pass']), holdout=bool(r['holdout_pass']), tokens=tokens)
    return cases, faults


def sign_test(w, l):
    n, k = w + l, min(w, l)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def curve(cases, k):
    solved = answered = wrong = 0
    for c in cases.values():
        first = next((a for a in sorted(c) if a < k and c[a]['feedback']), None)
        answered += first is not None
        solved += bool(first is not None and c[first]['holdout'])
        wrong += bool(first is not None and not c[first]['holdout'])
    return solved, answered, wrong


def main():
    ink, ink_faults = load((('inkling-coding-hard-v1', 0), ('inkling-coding-hard-v1b', 0)))
    nem, _ = load((('coding-hard-xl-v1', 0), ('coding-hard-xl-v1b', 0), ('coding-hard-xl-ext-v1', 4)))
    ds = {(r['task_id'], r['seed']): r for r in json.loads((RUNS / 'deepseek-coding-v1/summary.json').read_text())}
    keys = sorted(ds)
    complete = all(len(ink.get(k, {})) == 8 for k in keys)
    rows = {}
    for name, cs in (('inkling', ink), ('nemotron', nem)):
        rows[name] = dict(curve=[curve(cs, k)[0] for k in range(1, 9)], answered8=curve(cs, 8)[1], wrong8=curve(cs, 8)[2],
                          oracle8=sum(any(c[a]['holdout'] for a in c if a < 8) for c in cs.values()),
                          oracle4=sum(any(c[a]['holdout'] for a in c if a < 4) for c in cs.values()),
                          one=sum(bool(c.get(0, {}).get('holdout')) for c in cs.values()),
                          tokens8=round(sum(c[a]['tokens'] for c in cs.values() for a in c if a < 8) / len(cs)))
    ds_solved = {k: bool(ds[k]['holdout_pass']) for k in keys}

    def sel(cs, k):
        out = {}
        for key in keys:
            c = cs.get(key, {})
            first = next((a for a in sorted(c) if a < k and c[a]['feedback']), None)
            out[key] = bool(first is not None and c[first]['holdout'])
        return out

    def paired(a, b):
        w = sum(a[k] and not b[k] for k in keys)
        l = sum(b[k] and not a[k] for k in keys)
        return w, l, sign_test(w, l)

    i8, n8 = sel(ink, 8), sel(nem, 8)
    i1 = {k: bool(ink.get(k, {}).get(0, {}).get('holdout')) for k in keys}
    hybrid = sum(i8[k] or (sel_none and ds_solved[k]) for k in keys
                 for sel_none in [not any(ink.get(k, {}).get(a, {}).get('feedback') for a in range(8))])
    hybrid_calls = sum(not any(ink.get(k, {}).get(a, {}).get('feedback') for a in range(8)) for k in keys)
    ds_tokens = round(sum(ds[k]['completion_tokens'] or 0 for k in keys) / len(keys))
    res = dict(complete=complete, inkling_faulted_records_dropped=ink_faults, rows=rows,
               deepseek=dict(solved=sum(ds_solved.values()), tokens=ds_tokens),
               paired_ink8_vs_ds=paired(i8, ds_solved), paired_ink8_vs_nem8=paired(i8, n8),
               paired_one_ink_vs_ds=paired(i1, ds_solved), hybrid=dict(solved=hybrid, deepseek_calls=hybrid_calls))
    out = RUNS / 'inkling-coding-hard-v1b'
    (out / 'report.json').write_text(json.dumps(res, indent=1))
    ri, rn = rows['inkling'], rows['nemotron']
    p1, p2, p3 = res['paired_ink8_vs_ds'], res['paired_ink8_vs_nem8'], res['paired_one_ink_vs_ds']
    md = f"""# Inkling-2-Mini coding swarm on coding-hard-v1 (72 cases)

Plan `INKLING_CODING_PLAN.json` (frozen in 76c9e42; amendment 1 = per-request wall limit 1800 -> 14400 s, source c2eb89e,
unfinished and faulted agents rerun in v1b). 24 evaluation tasks x 3 seeds, 8 independent code_xl agents (32K budget),
selection = first agent in fixed order whose code passes the public feedback cases; solved = that code passes the hidden
holdout cases. Nemotron rows: the same setup (coding-hard-xl-v1/v1b/ext). DeepSeek: one 32K call per case.
All 576 Inkling agents present: {complete}; faulted records dropped and rerun: {ink_faults}.

| 72 cases | k=1 | k=2 | k=3 | k=4 | k=5 | k=6 | k=7 | k=8 | Any of 8 right | Wrong answers (k=8) | Tokens / case (8 agents) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Inkling** | {' | '.join(map(str, ri['curve']))} | {ri['oracle8']} | {ri['wrong8']} | {ri['tokens8']:,} |
| Nemotron | {' | '.join(map(str, rn['curve']))} | {rn['oracle8']} | {rn['wrong8']} | {rn['tokens8']:,} |
| One DeepSeek V4.1 | {res['deepseek']['solved']} | | | | | | | | | | {ds_tokens:,} |

- Inkling 8-agent swarm vs One DeepSeek: +{p1[0]} / -{p1[1]}, p = {p1[2]:.3g}
- Inkling 8 vs Nemotron 8: +{p2[0]} / -{p2[1]}, p = {p2[2]:.3g}
- One Inkling vs One DeepSeek: +{p3[0]} / -{p3[1]}, p = {p3[2]:.3g}
- Hybrid (DeepSeek only where no Inkling agent passed feedback): {hybrid}/72 with {hybrid_calls} DeepSeek calls.
"""
    (out / 'REPORT.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
