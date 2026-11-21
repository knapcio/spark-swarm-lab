#!/usr/bin/env python3
"""Fresh replication on arithmetic-hard-v5 (INKLING_HARD5_PLAN + DEEPSEEK_HARD5_PLAN) and the pre-registered pooled test
over hard-v4 + hard-v5 (192 paired cases): Inkling swarm (deep4 32K + own judge) vs One DeepSeek (32K)."""
import json
from pathlib import Path

from report_hard4 import RUNS, deepseek, sign_test, swarm


def stats(ink, ds):
    keys = sorted(ink)
    assert set(keys) == set(ds), (len(keys), len(ds))
    s = {k: bool(ink[k]['solved']) for k in keys}
    one = {k: bool(ink[k]['agents'][0]['verifier_solved']) for k in keys}
    d = {k: bool(ds[k]['solved']) for k in keys}

    def paired(a, b):
        w, l = sum(a[k] and not b[k] for k in keys), sum(b[k] and not a[k] for k in keys)
        return w, l, sign_test(w, l)

    judge = [a for k in keys for a in ink[k]['agents'] if a['verdict'] is not None]
    return dict(cases=len(keys), swarm=sum(s.values()), wrong=sum(ink[k]['wrong'] for k in keys),
                abstain=sum(not ink[k]['answered'] for k in keys), oracle=sum(ink[k]['oracle'] for k in keys),
                one=sum(one.values()), deepseek=sum(d.values()),
                tokens=round(sum(ink[k]['tokens'] for k in keys) / len(keys)),
                ds_tokens=round(sum(ds[k]['completion_tokens'] or 0 for k in keys) / len(keys)),
                swarm_vs_ds=paired(s, d), one_vs_ds=paired(one, d),
                hybrid=sum(s[k] or (not ink[k]['answered'] and d[k]) for k in keys),
                hybrid_calls=sum(not ink[k]['answered'] for k in keys),
                false_accepts=sum(a['verdict'] is True and not a['verifier_solved'] for a in judge), verdicts=len(judge),
                infra=sum(ink[k]['infra'] for k in keys))


def main():
    v5 = stats(swarm('inkling-hard5-v1'), deepseek('deepseek-hard5-v1'))
    v4 = stats(swarm('inkling-hard4-v1'), deepseek('deepseek-hard4-v1', 'deepseek-hard4-seed2-v1'))
    ink_all = {**{('v4',) + k: v for k, v in swarm('inkling-hard4-v1').items()},
               **{('v5',) + k: v for k, v in swarm('inkling-hard5-v1').items()}}
    ds_all = {**{('v4',) + k: v for k, v in deepseek('deepseek-hard4-v1', 'deepseek-hard4-seed2-v1').items()},
              **{('v5',) + k: v for k, v in deepseek('deepseek-hard5-v1').items()}}
    pooled = stats(ink_all, ds_all)
    meta_i = json.loads((RUNS / 'inkling-hard5-v1/metadata.json').read_text())
    meta_d = json.loads((RUNS / 'deepseek-hard5-v1/metadata.json').read_text())
    res = dict(hard5=v5, hard4=v4, pooled=pooled, errors=dict(inkling=meta_i['errors'], deepseek=meta_d.get('errors')))
    out = RUNS / 'inkling-hard5-v1'
    (out / 'report.json').write_text(json.dumps(res, indent=1))

    def line(name, r):
        sw, on = r['swarm_vs_ds'], r['one_vs_ds']
        return (f"| {name} | {r['cases']} | **{r['swarm']}** | {r['wrong']} | {r['one']} | {r['deepseek']} | "
                f"+{sw[0]} / -{sw[1]} (p = {sw[2]:.3g}) | +{on[0]} / -{on[1]} (p = {on[2]:.3g}) | {r['hybrid']} ({r['hybrid_calls']} DS calls) |")

    md = f"""# Fresh replication on arithmetic-hard-v5 and pooled test

Plans `INKLING_HARD5_PLAN.json` and `DEEPSEEK_HARD5_PLAN.json` were frozen in 4670c56 BEFORE the corpus existed;
arithmetic-hard-v5 (generator seed 2026112101, same rules as hard-v4) was generated afterwards (13ecd62). Inkling swarm
= 4 agents with a 32K budget each plus the swarm's own thinking judge, exactly as in inkling-hard4-v1; One Inkling =
agent 0; One DeepSeek = one 32K thinking call. Errors: Inkling {meta_i['errors']}, DeepSeek {meta_d.get('errors')}.

| Set | Cases | Inkling swarm | Wrong | One Inkling | One DeepSeek | Swarm vs DeepSeek (paired) | One Inkling vs DeepSeek | Hybrid |
|---|---:|---:|---:|---:|---:|---|---|---|
{line('hard-v4 (earlier)', v4)}
{line('**hard-v5 (fresh)**', v5)}
{line('**Pooled (pre-registered)**', pooled)}

Completion tokens per case on hard-v5: Inkling swarm {v5['tokens']:,}, DeepSeek {v5['ds_tokens']:,}.
Inkling judge on hard-v5: {v5['verdicts']} verdicts, {v5['false_accepts']} false accepts. Hybrid = swarm answer, DeepSeek only when the swarm says "no answer".
"""
    (out / 'REPORT.md').write_text(md)
    print(md)


if __name__ == '__main__':
    main()
