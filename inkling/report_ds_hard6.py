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
    import energy
    res['deepseek_energy'] = energy.window(meta['started_utc'], meta['completed_utc'])
    hard6 = json.loads((OUT / 'report.json').read_text())['arms']
    res['cost'] = {name: dict(solved=hard6[pol]['solved'], wall_min=round(hard6[pol]['arm_wall_seconds'] / 60),
                              gpu_wh=hard6[pol]['energy_wh'], wh_per_solved=hard6[pol]['energy_wh_per_solved'],
                              tokens_per_case=hard6[pol]['server_tokens_per_case'])
                   for name, pol in (('Inkling swarm A deep4', 'deep4'), ('Inkling swarm B deep4cancel', 'deep4cancel'),
                                     ('Inkling swarm C waves2cancel', 'waves2cancel'))}
    ds_solved = sum(bool(r['solved']) for r in ds6.values())
    res['ds_misses_at_budget'] = sum(not r['solved'] and (r['length_finishes'] or 0) > 0 for r in ds6.values())
    res['cost']['One DeepSeek (TP4, 4 nodes)'] = dict(
        solved=ds_solved, wall_min=round(res['deepseek_wall_seconds'] / 60), gpu_wh=res['deepseek_energy']['total_wh'],
        wh_per_solved=round(res['deepseek_energy']['total_wh'] / ds_solved, 2),
        tokens_per_case=round(sum(r['completion_tokens'] or 0 for r in ds6.values()) / len(ds6)))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'deepseek.json').write_text(json.dumps(res, indent=1) + '\n')

    def line(name, r, one=True):
        sw, on = r['swarm_vs_ds'], r['one_vs_ds']
        one_cols = f"{r['one']} | " if one else 'n/a | '
        one_test = f"+{on['wins']} / -{on['losses']} (p = {on['p']:.3g})" if one else 'n/a (agent 0 often cancelled)'
        return (f"| {name} | {r['cases']} | **{r['swarm']}** | {r['wrong']} | {one_cols}{r['deepseek']} | "
                f"+{sw['wins']} / -{sw['losses']} (p = {sw['p']:.3g}) | {one_test} | "
                f"{r['hybrid']} ({r['hybrid_ds_calls']} DS calls) |")
    rows = [line(f'hard-v6, swarm arm {n}', r, n.startswith('A')) for n, r in res['hard6'].items()]
    rows.append(line('Pooled v4+v5+v6, deep4 (exploratory)', res['pooled_v4_v5_v6_exploratory']))
    md = ('| Set | Cases | Inkling swarm | Wrong | One Inkling | One DeepSeek | Swarm vs DeepSeek (paired) | '
          'One Inkling vs DeepSeek | Hybrid |\n|---|---:|---:|---:|---:|---:|---|---|---|\n' + '\n'.join(rows) + '\n')
    md += ('\n| System on hard-v6 (96 cases, whole fleet) | Solved | Completion tokens/case | Wall | GPU energy | Wh per solved case |\n'
           '|---|---:|---:|---:|---:|---:|\n' + ''.join(
               f"| {k} | {v['solved']} | {v['tokens_per_case']:,} | {v['wall_min']} min | {v['gpu_wh']} Wh | {v['wh_per_solved']:.2f} |\n"
               for k, v in res['cost'].items()))
    (OUT / 'deepseek.json').write_text(json.dumps(res, indent=1) + '\n')
    (OUT / 'deepseek_tables.md').write_text(md)
    A, B = res['hard6']['A deep4'], res['hard6']['B deep4cancel']
    P = res['pooled_v4_v5_v6_exploratory']
    c = res['cost']
    (OUT / 'DEEPSEEK.md').write_text(f"""# One DeepSeek on arithmetic-hard-v6 (deepseek-hard6-v1)

Plan [`DEEPSEEK_HARD6_PLAN.json`](../../DEEPSEEK_HARD6_PLAN.json) (f24a1f6) is a copy of the hard-v5 DeepSeek plan:
one 32K thinking call per case, same worker source, seeds 1-2, seed offset 2900, 8 concurrent requests, native DeepSeek
V4.1 TP4 over the four Sparks. It was frozen after hard-v6 existed (the corpus was generated for the swarm study) but
before any DeepSeek call on it; the corpus is pinned by sha256. Errors: {res['deepseek_errors']}. The fleet was switched with the
reviewed procedure (`inkling/ds_switch_inkling.py`) and switched back to Inkling afterwards.

{md}
- **On hard-v6 the Inkling swarm (A) and One DeepSeek are level**: {A['swarm']} vs {A['deepseek']}, paired
  +{A['swarm_vs_ds']['wins']} / -{A['swarm_vs_ds']['losses']}. The swarm made {A['wrong']} wrong answers and abstained otherwise; of DeepSeek's
  {96 - A['deepseek']} misses, {res['ds_misses_at_budget']} hit the 32K budget and the rest finished within the budget without a valid plan.
- One Inkling (agent 0 of A) is clearly below One DeepSeek ({A['one']} vs {A['deepseek']}, p = {A['one_vs_ds']['p']:.2g}), as on hard-v4/v5.
- Cost on the same four Sparks: the default swarm B costs about the same GPU energy per solved case as One DeepSeek
  ({c['Inkling swarm B deep4cancel']['wh_per_solved']:.2f} vs {c['One DeepSeek (TP4, 4 nodes)']['wh_per_solved']:.2f} Wh) and the same wall time for 96 cases; the old
  default A cost {c['Inkling swarm A deep4']['wh_per_solved']:.2f} Wh. DeepSeek uses ~7x fewer tokens, each far more expensive.
- Hybrid (DeepSeek only where the swarm abstains): {A['hybrid']}/96 with {A['hybrid_ds_calls']} DeepSeek calls (A); {B['hybrid']}/96 with {B['hybrid_ds_calls']} calls (B).
- **Exploratory pooled addendum** (the pre-registered pooled test was hard-v4 + v5 only): over v4 + v5 + v6, 288 cases,
  Inkling swarm (deep4) {P['swarm']} vs One DeepSeek {P['deepseek']}, paired +{P['swarm_vs_ds']['wins']} / -{P['swarm_vs_ds']['losses']}
  (p = {P['swarm_vs_ds']['p']:.2g}), 0 wrong; One Inkling {P['one']} (p = {P['one_vs_ds']['p']:.1g} below DeepSeek); hybrid {P['hybrid']} with
  {P['hybrid_ds_calls']} DeepSeek calls. The swarm matches DeepSeek; it does not beat it significantly.

Numbers: [deepseek.json](deepseek.json); report script `inkling/report_ds_hard6.py`.
""")
    print(md)
    print(json.dumps(dict(ds_tokens=res['pooled_v4_v5_v6_exploratory']['ds_tokens'], errors=res['deepseek_errors'],
                          wall=res['deepseek_wall_seconds'])))


if __name__ == '__main__':
    main()
