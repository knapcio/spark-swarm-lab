#!/usr/bin/env python3
"""Inkling-2-Mini Swarm v2 (deep4 32K + own judge) on arithmetic-hard-v4 vs Nemotron Swarm v2 and DeepSeek.

Same 48 tasks x seeds 1-2, same harness, policy, budgets and judge; only the served model differs. Existing
Nemotron and DeepSeek runs are read, not rerun. Paired comparisons use a two-sided exact sign test over
discordant cases. One <model> = agent 0 of the swarm, scored by the exact verifier.
"""
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
RUNS = HERE / 'runs'


def swarm(*names):
    out = {}
    for name in names:
        for line in open(RUNS / name / 'cases.jsonl'):
            c = json.loads(line)
            out[(c['task_id'], c['seed'])] = c
    return out


def deepseek(*names):
    out = {}
    for name in names:
        for r in json.loads((RUNS / name / 'summary.json').read_text()):
            out[(r['task_id'], r['seed'])] = r
    return out


def sign_test(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    ink = swarm('inkling-hard4-v1')
    nem = swarm('confirm-xl-hard4-v2', 'confirm-xl-hard4-seed2-v1')
    ds = deepseek('deepseek-hard4-v1', 'deepseek-hard4-seed2-v1')
    keys = sorted(ink)
    assert len(keys) == 96 and set(keys) == set(nem) == set(ds), (len(keys), len(nem), len(ds))
    meta = json.loads((RUNS / 'inkling-hard4-v1/metadata.json').read_text())

    def row(c):
        return dict(solved=sum(c[k]['solved'] for k in keys), wrong=sum(c[k]['wrong'] for k in keys),
                    abstain=sum(not c[k]['answered'] for k in keys), oracle=sum(c[k]['oracle'] for k in keys),
                    one=sum(c[k]['agents'][0]['verifier_solved'] for k in keys),
                    tokens=round(sum(c[k]['tokens'] for k in keys) / len(keys)),
                    infra=sum(c[k]['infra'] for k in keys), deadlines=sum(c[k]['deadlines'] for k in keys))

    r_ink, r_nem = row(ink), row(nem)
    ds_solved = {k: bool(ds[k]['solved']) for k in keys}
    ds_tokens = round(sum(ds[k]['completion_tokens'] or 0 for k in keys) / len(keys))

    def paired(a, b):
        w = sum(a[k] and not b[k] for k in keys)
        l = sum(b[k] and not a[k] for k in keys)
        return w, l, sign_test(w, l)

    ink_s = {k: bool(ink[k]['solved']) for k in keys}
    nem_s = {k: bool(nem[k]['solved']) for k in keys}
    ink_one = {k: bool(ink[k]['agents'][0]['verifier_solved']) for k in keys}
    hybrid = sum(ink_s[k] or (not ink[k]['answered'] and ds_solved[k]) for k in keys)
    hybrid_calls = sum(not ink[k]['answered'] for k in keys)
    per_seed = {s: sum(ink_s[k] for k in keys if k[1] == s) for s in (1, 2)}
    judge = [a for k in keys for a in ink[k]['agents'] if a['verdict'] is not None]
    false_accepts = sum(a['verdict'] is True and not a['verifier_solved'] for a in judge)
    false_rejects = sum(a['verdict'] is False and a['verifier_solved'] for a in judge)
    result = dict(inkling=r_ink, nemotron=r_nem, deepseek=dict(solved=sum(ds_solved.values()), tokens=ds_tokens),
                  inkling_per_seed=per_seed,
                  paired_inkling_vs_deepseek=paired(ink_s, ds_solved), paired_inkling_vs_nemotron=paired(ink_s, nem_s),
                  paired_one_inkling_vs_deepseek=paired(ink_one, ds_solved),
                  hybrid=dict(solved=hybrid, deepseek_calls=hybrid_calls),
                  judge=dict(verdicts=len(judge), false_accepts=false_accepts, false_rejects=false_rejects),
                  wall_seconds=round(meta['wall_seconds']), errors=meta['errors'])
    (RUNS / 'inkling-hard4-v1' / 'report.json').write_text(json.dumps(result, indent=1))
    pi, pn, po = result['paired_inkling_vs_deepseek'], result['paired_inkling_vs_nemotron'], result['paired_one_inkling_vs_deepseek']
    md = f"""# Inkling-2-Mini Swarm v2 on arithmetic-hard-v4 (96 cases)

Plan `INKLING_HARD4_PLAN.json` (frozen in 76c9e42 before any Inkling call on these tasks). Same 48 tasks x seeds 1-2,
harness source d94c893, deep4 policy (4 agents, 32K budget each, budget forcing), arbiter-free selection by the
swarm's own thinking judge, exact verifier only for scoring. Only the served model changes: Inkling-2-Mini
(SGLang DSpark recipe, `inkling/TUNING.md`) instead of Nemotron 3.5 Lightning. Nemotron and DeepSeek rows are the
existing runs on the same cases. Errors: {meta['errors']}; infra {r_ink['infra']}, deadlines {r_ink['deadlines']}.
Wall time {round(meta['wall_seconds'] / 60)} min on four Sparks (shared with the coding run).

| 96 cases (48 tasks x 2 seeds) | Solved | Wrong answers | No answer | Any of 4 agents right | Completion tokens / case |
|---|---:|---:|---:|---:|---:|
| **Inkling Swarm (4 x 32K + own judge)** | **{r_ink['solved']}** | {r_ink['wrong']} | {r_ink['abstain']} | {r_ink['oracle']} | {r_ink['tokens']:,} |
| One Inkling (agent 0) | {r_ink['one']} | | | | |
| Nemotron Swarm v2 (same setup) | {r_nem['solved']} | {r_nem['wrong']} | {r_nem['abstain']} | {r_nem['oracle']} | {r_nem['tokens']:,} |
| One Nemotron (agent 0) | {r_nem['one']} | | | | |
| One DeepSeek V4.1 (32K) | {result['deepseek']['solved']} | | | | {ds_tokens:,} |
| Hybrid: Inkling Swarm, DeepSeek only on "no answer" | {hybrid} | | | | {hybrid_calls} DeepSeek calls |

Paired over 96 cases (two-sided exact sign test on discordant cases):
- Inkling Swarm vs One DeepSeek: +{pi[0]} / -{pi[1]}, p = {pi[2]:.3g}
- Inkling Swarm vs Nemotron Swarm v2: +{pn[0]} / -{pn[1]}, p = {pn[2]:.3g}
- One Inkling vs One DeepSeek: +{po[0]} / -{po[1]}, p = {po[2]:.3g}

Per seed, Inkling Swarm: seed 1 {per_seed[1]}/48, seed 2 {per_seed[2]}/48.
Inkling judge: {len(judge)} verdicts, {false_accepts} false accepts, {false_rejects} false rejects (exact verifier as reference).
"""
    (RUNS / 'inkling-hard4-v1' / 'REPORT.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
