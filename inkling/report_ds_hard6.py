#!/usr/bin/env python3
"""DEEPSEEK_HARD6_PLAN: One DeepSeek (one 32K thinking call) on arithmetic-hard-v6 vs the Inkling swarm arms of
swarm-cancel-hard6-v1 (A deep4, B deep4cancel, C waves2cancel) and One Inkling (agent 0 of arm A), with paired two-sided
exact sign tests; hybrid (DeepSeek only where the swarm abstained). Exploratory addendum: pooled hard-v4 + v5 + v6
(288 cases, deep4 arms; the pre-registered pooled test was v4 + v5 only).
Writes results/swarm-cancel-hard6-v1/deepseek.json and prints Markdown tables."""
import json
from pathlib import Path

from report_hard4 import RUNS, deepseek, sign_test, swarm

OUT = Path(__file__).resolve().parent.parent / 'results' / 'swarm-cancel-hard6-v1'
ARMS = [('A deep4', 'swarm-cancel-hard6-v1-deep4'), ('B deep4cancel', 'swarm-cancel-hard6-v1-deep4cancel'),
        ('C waves2cancel', 'swarm-cancel-hard6-v1-waves2cancel')]


def paired(a, b, keys):
    w, l = sum(a[k] and not b[k] for k in keys), sum(b[k] and not a[k] for k in keys)
    return dict(wins=w, losses=l, p=sign_test(w, l))


def compare(ink, ds):
    keys = sorted(ink)
    assert set(keys) == set(ds), (len(keys), len(ds))
    s = {k: bool(ink[k]['solved']) for k in keys}
    d = {k: bool(ds[k]['solved']) for k in keys}
    one = {k: bool(ink[k]['agents'][0]['verifier_solved']) for k in keys}
    return dict(cases=len(keys), swarm=sum(s.values()), wrong=sum(ink[k]['wrong'] for k in keys),
                abstain=sum(not ink[k]['answered'] for k in keys), deepseek=sum(d.values()), one=sum(one.values()),
                swarm_vs_ds=paired(s, d, keys), one_vs_ds=paired(one, d, keys),
                hybrid=sum(s[k] or (not ink[k]['answered'] and d[k]) for k in keys),
                hybrid_ds_calls=sum(not ink[k]['answered'] for k in keys),
                ds_tokens=round(sum(ds[k]['completion_tokens'] or 0 for k in keys) / len(keys)))


def main():
    ds6 = deepseek('deepseek-hard6-v1')
    res = dict(hard6={name: compare(swarm(d), ds6) for name, d in ARMS if (RUNS / d / 'cases.jsonl').exists()})
    pooled_ink = {**{('v4',) + k: v for k, v in swarm('inkling-hard4-v1').items()},
                  **{('v5',) + k: v for k, v in swarm('inkling-hard5-v1').items()},
                  **{('v6',) + k: v for k, v in swarm('swarm-cancel-hard6-v1-deep4').items()}}
    pooled_ds = {**{('v4',) + k: v for k, v in deepseek('deepseek-hard4-v1', 'deepseek-hard4-seed2-v1').items()},
                 **{('v5',) + k: v for k, v in deepseek('deepseek-hard5-v1').items()},
                 **{('v6',) + k: v for k, v in ds6.items()}}
    res['pooled_v4_v5_v6_exploratory'] = compare(pooled_ink, pooled_ds)
    meta = json.loads((RUNS / 'deepseek-hard6-v1/metadata.json').read_text())
    res['deepseek_errors'] = meta.get('errors')
    res['deepseek_wall_seconds'] = round(meta.get('batch_wall_seconds') or 0)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'deepseek.json').write_text(json.dumps(res, indent=1) + '\n')

    def line(name, r):
        sw, on = r['swarm_vs_ds'], r['one_vs_ds']
        return (f"| {name} | {r['cases']} | **{r['swarm']}** | {r['wrong']} | {r['one']} | {r['deepseek']} | "
                f"+{sw['wins']} / -{sw['losses']} (p = {sw['p']:.3g}) | +{on['wins']} / -{on['losses']} (p = {on['p']:.3g}) | "
                f"{r['hybrid']} ({r['hybrid_ds_calls']} DS calls) |")
    rows = [line(f'hard-v6, swarm arm {n}', r) for n, r in res['hard6'].items()]
    rows.append(line('Pooled v4+v5+v6, deep4 (exploratory)', res['pooled_v4_v5_v6_exploratory']))
    md = ('| Set | Cases | Inkling swarm | Wrong | One Inkling | One DeepSeek | Swarm vs DeepSeek (paired) | '
          'One Inkling vs DeepSeek | Hybrid |\n|---|---:|---:|---:|---:|---:|---|---|---|\n' + '\n'.join(rows) + '\n')
    (OUT / 'deepseek_tables.md').write_text(md)
    print(md)
    print(json.dumps(dict(ds_tokens=res['pooled_v4_v5_v6_exploratory']['ds_tokens'], errors=res['deepseek_errors'],
                          wall=res['deepseek_wall_seconds'])))


if __name__ == '__main__':
    main()
