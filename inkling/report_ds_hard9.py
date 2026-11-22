#!/usr/bin/env python3
"""DEEPSEEK_HARD9_PLAN: One DeepSeek on arithmetic-hard-v9 vs the Inkling swarm arms of swarm-repair-hard9-v1, and the
pre-registered pooled test B+ (roll8cancel) vs One DeepSeek over hard-v7 + hard-v9 (192 paired cases).
Writes results/swarm-repair-hard9-v1/{deepseek.json, DEEPSEEK.md}."""
import json
from pathlib import Path

import energy
from report_hard4 import RUNS, deepseek, sign_test, swarm

OUT = Path(__file__).resolve().parent.parent / 'results' / 'swarm-repair-hard9-v1'


def compare(ink, ds):
    keys = sorted(ink)
    assert set(keys) == set(ds), (len(keys), len(ds))
    s = {k: bool(ink[k]['solved']) for k in keys}
    d = {k: bool(ds[k]['solved']) for k in keys}
    w, l = sum(s[k] and not d[k] for k in keys), sum(d[k] and not s[k] for k in keys)
    return dict(cases=len(keys), swarm=sum(s.values()), wrong=sum(ink[k]['wrong'] for k in keys), deepseek=sum(d.values()),
                wins=w, losses=l, p=sign_test(w, l), hybrid=sum(s[k] or (not ink[k]['answered'] and d[k]) for k in keys),
                hybrid_ds_calls=sum(not ink[k]['answered'] for k in keys))


def main():
    ds9, ds7 = deepseek('deepseek-hard9-v1'), deepseek('deepseek-hard7-v1')
    bp9, rp9 = swarm('swarm-repair-hard9-v1-roll8cancel'), swarm('swarm-repair-hard9-v1-roll8repair')
    bp7 = swarm('swarm-escalate-hard7-v1-roll8cancel')
    pooled_ink = {**{('v7',) + k: v for k, v in bp7.items()}, **{('v9',) + k: v for k, v in bp9.items()}}
    pooled_ds = {**{('v7',) + k: v for k, v in ds7.items()}, **{('v9',) + k: v for k, v in ds9.items()}}
    meta = json.loads((RUNS / 'deepseek-hard9-v1/metadata.json').read_text())
    e = energy.window(meta['started_utc'], meta['completed_utc'])
    ds_solved = sum(bool(r['solved']) for r in ds9.values())
    res = dict(hard9_bplus=compare(bp9, ds9), hard9_repair=compare(rp9, ds9), pooled_v7_v9_bplus=compare(pooled_ink, pooled_ds),
               deepseek=dict(solved=ds_solved, errors=meta.get('errors'), wall_min=round(meta['batch_wall_seconds'] / 60),
                             gpu_wh=e['total_wh'], wh_per_solved=round(e['total_wh'] / ds_solved, 2),
                             tokens_per_case=round(sum(r['completion_tokens'] or 0 for r in ds9.values()) / len(ds9))))
    swarm_report = json.loads((OUT / 'report.json').read_text())['arms']
    res['bplus_cost'] = {k: swarm_report['roll8cancel'][k] for k in ('energy_wh', 'energy_wh_per_solved', 'arm_wall_seconds', 'server_tokens_per_case')}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'deepseek.json').write_text(json.dumps(res, indent=1) + '\n')
    line = lambda n, r: (f"| {n} | {r['cases']} | **{r['swarm']}** | {r['wrong']} | {r['deepseek']} | +{r['wins']} / -{r['losses']} (p = {r['p']:.2g}) | "
                         f"{r['hybrid']} ({r['hybrid_ds_calls']} DS calls) |")
    md = ('| Set | Cases | Inkling swarm | Wrong | One DeepSeek | Swarm vs DeepSeek (paired) | Hybrid |\n|---|---:|---:|---:|---:|---|---|\n'
          + line('hard-v9, B+ roll8cancel', res['hard9_bplus']) + '\n' + line('hard-v9, roll8repair', res['hard9_repair']) + '\n'
          + line('**Pooled hard-v7 + v9, B+ (pre-registered)**', res['pooled_v7_v9_bplus']) + '\n')
    P, d, c = res['pooled_v7_v9_bplus'], res['deepseek'], res['bplus_cost']
    (OUT / 'DEEPSEEK.md').write_text(f"""# One DeepSeek on arithmetic-hard-v9 and the pooled B+ vs DeepSeek test (deepseek-hard9-v1)

Plan [`DEEPSEEK_HARD9_PLAN.json`](../../DEEPSEEK_HARD9_PLAN.json) (f266225) is the hard-v5/v6/v7 DeepSeek plan on the
fresh hard-v9 tasks, frozen before any DeepSeek call on them and before any hard-v9 swarm result was read; it
pre-registers the pooled hard-v7 + hard-v9 test of the default swarm B+ against One DeepSeek. Errors: {d['errors']}.

{md}
**Pooled (pre-registered): B+ {P['swarm']} vs One DeepSeek {P['deepseek']} over 192 cases, paired +{P['wins']} / -{P['losses']}
(p = {P['p']:.2g}), {P['wrong']} wrong answers for the swarm.**

Cost on hard-v9 (same four Sparks): One DeepSeek {d['gpu_wh']} Wh, {d['wh_per_solved']:.2f} Wh per solved case, {d['wall_min']} min,
{d['tokens_per_case']:,} completion tokens per case; B+ {c['energy_wh']} Wh, {c['energy_wh_per_solved']:.2f} Wh per solved case,
{c['arm_wall_seconds'] / 60:.0f} min, {c['server_tokens_per_case']:,} server tokens per case.

Numbers: [deepseek.json](deepseek.json); report script `inkling/report_ds_hard9.py`.
""")
    print(md)
    print(json.dumps(dict(pooled=P, deepseek=d)))


if __name__ == '__main__':
    main()
