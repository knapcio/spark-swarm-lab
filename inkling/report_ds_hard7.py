#!/usr/bin/env python3
"""DEEPSEEK_HARD7_PLAN: One DeepSeek (one 32K thinking call) on arithmetic-hard-v7 vs the Inkling swarm arms of
swarm-escalate-hard7-v1 (B+ roll8cancel, B deep4cancel, A deep4) and One Inkling (agent 0 of arm A), with paired two-sided
exact sign tests; hybrid (DeepSeek only where the swarm abstained). Exploratory addendum: pooled hard-v4..v7
(384 cases, deep4 arms; the pre-registered pooled test was v4 + v5 only).
Writes results/swarm-escalate-hard7-v1/{deepseek.json, DEEPSEEK.md}."""
import json
from pathlib import Path

from report_hard4 import RUNS, deepseek, sign_test, swarm

OUT = Path(__file__).resolve().parent.parent / 'results' / 'swarm-escalate-hard7-v1'
ARMS = [('B+ roll8cancel', 'swarm-escalate-hard7-v1-roll8cancel'), ('B deep4cancel', 'swarm-escalate-hard7-v1-deep4cancel'),
        ('A deep4', 'swarm-escalate-hard7-v1-deep4')]


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
    ds6 = deepseek('deepseek-hard7-v1')
    res = dict(hard7={name: compare(swarm(d), ds6) for name, d in ARMS if (RUNS / d / 'cases.jsonl').exists()})
    pooled_ink = {**{('v4',) + k: v for k, v in swarm('inkling-hard4-v1').items()},
                  **{('v5',) + k: v for k, v in swarm('inkling-hard5-v1').items()},
                  **{('v6',) + k: v for k, v in swarm('swarm-cancel-hard6-v1-deep4').items()},
                  **{('v7',) + k: v for k, v in swarm('swarm-escalate-hard7-v1-deep4').items()}}
    pooled_ds = {**{('v4',) + k: v for k, v in deepseek('deepseek-hard4-v1', 'deepseek-hard4-seed2-v1').items()},
                 **{('v5',) + k: v for k, v in deepseek('deepseek-hard5-v1').items()},
                 **{('v6',) + k: v for k, v in deepseek('deepseek-hard6-v1').items()},
                 **{('v7',) + k: v for k, v in ds6.items()}}
    res['pooled_v4_v7_exploratory'] = compare(pooled_ink, pooled_ds)
    meta = json.loads((RUNS / 'deepseek-hard7-v1/metadata.json').read_text())
    res['deepseek_errors'] = meta.get('errors')
    res['deepseek_wall_seconds'] = round(meta.get('batch_wall_seconds') or 0)
    import energy
    res['deepseek_energy'] = energy.window(meta['started_utc'], meta['completed_utc'])
    hard7arms = json.loads((OUT / 'report.json').read_text())['arms']
    res['cost'] = {name: dict(solved=hard7arms[pol]['solved'], wall_min=round(hard7arms[pol]['arm_wall_seconds'] / 60),
                              gpu_wh=hard7arms[pol]['energy_wh'], wh_per_solved=hard7arms[pol]['energy_wh_per_solved'],
                              tokens_per_case=hard7arms[pol]['server_tokens_per_case'])
                   for name, pol in (('Inkling swarm B+ roll8cancel', 'roll8cancel'), ('Inkling swarm B deep4cancel', 'deep4cancel'),
                                     ('Inkling swarm A deep4', 'deep4'))}
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
    rows = [line(f'hard-v7, swarm arm {n}', r, n.startswith('A')) for n, r in res['hard7'].items()]
    rows.append(line('Pooled v4..v7, deep4 (exploratory)', res['pooled_v4_v7_exploratory']))
    md = ('| Set | Cases | Inkling swarm | Wrong | One Inkling | One DeepSeek | Swarm vs DeepSeek (paired) | '
          'One Inkling vs DeepSeek | Hybrid |\n|---|---:|---:|---:|---:|---:|---|---|---|\n' + '\n'.join(rows) + '\n')
    md += ('\n| System on hard-v7 (96 cases, whole fleet) | Solved | Completion tokens/case | Wall | GPU energy | Wh per solved case |\n'
           '|---|---:|---:|---:|---:|---:|\n' + ''.join(
               f"| {k} | {v['solved']} | {v['tokens_per_case']:,} | {v['wall_min']} min | {v['gpu_wh']} Wh | {v['wh_per_solved']:.2f} |\n"
               for k, v in res['cost'].items()))
    (OUT / 'deepseek.json').write_text(json.dumps(res, indent=1) + '\n')
    (OUT / 'deepseek_tables.md').write_text(md)
    A, B, P = res['hard7']['A deep4'], res['hard7']['B deep4cancel'], res['hard7']['B+ roll8cancel']
    PO = res['pooled_v4_v7_exploratory']
    c = res['cost']
    (OUT / 'DEEPSEEK.md').write_text(f"""# One DeepSeek on arithmetic-hard-v7 (deepseek-hard7-v1)

Plan [`DEEPSEEK_HARD7_PLAN.json`](../../DEEPSEEK_HARD7_PLAN.json) is a copy of the hard-v5/v6 DeepSeek plan: one 32K thinking
call per case, same worker source, seeds 1-2, seed offset 2900, 8 concurrent requests, native DeepSeek V4.1 TP4 over the
four Sparks. Frozen after hard-v7 existed but before any DeepSeek call on it; the corpus is pinned by sha256. Errors:
{res['deepseek_errors']}. The fleet was switched with the reviewed procedure and switched back to Inkling afterwards.

{md}
- **New default swarm B+ vs One DeepSeek: {P['swarm']} vs {P['deepseek']}, paired +{P['swarm_vs_ds']['wins']} / -{P['swarm_vs_ds']['losses']}
  (p = {P['swarm_vs_ds']['p']:.2g})**, {P['wrong']} wrong answers for the swarm. Old default A: {A['swarm']} (+{A['swarm_vs_ds']['wins']} / -{A['swarm_vs_ds']['losses']}).
- Hybrid (DeepSeek only where the swarm abstains): B+ {P['hybrid']}/96 with {P['hybrid_ds_calls']} DeepSeek calls; A {A['hybrid']} with {A['hybrid_ds_calls']}.
- Cost on the same four Sparks: B+ {c['Inkling swarm B+ roll8cancel']['wh_per_solved']:.2f} Wh per solved case, One DeepSeek
  {c['One DeepSeek (TP4, 4 nodes)']['wh_per_solved']:.2f}, A {c['Inkling swarm A deep4']['wh_per_solved']:.2f}; wall {c['Inkling swarm B+ roll8cancel']['wall_min']} vs {c['One DeepSeek (TP4, 4 nodes)']['wall_min']} vs {c['Inkling swarm A deep4']['wall_min']} min for 96 cases.
  Inkling ran at --mem-fraction-static 0.62 during hard-v7 (the KV raise came afterwards).
- One Inkling (agent 0 of A) vs One DeepSeek: {A['one']} vs {A['deepseek']} (p = {A['one_vs_ds']['p']:.2g}).
- Exploratory pooled addendum, deep4 only, hard-v4..v7 ({PO['cases']} cases): swarm {PO['swarm']} vs DeepSeek {PO['deepseek']},
  +{PO['swarm_vs_ds']['wins']} / -{PO['swarm_vs_ds']['losses']} (p = {PO['swarm_vs_ds']['p']:.2g}).

Numbers: [deepseek.json](deepseek.json); report script `inkling/report_ds_hard7.py`.
""")
    print(md)
    print(json.dumps(dict(ds_tokens=res['pooled_v4_v7_exploratory']['ds_tokens'], errors=res['deepseek_errors'],
                          wall=res['deepseek_wall_seconds'])))


if __name__ == '__main__':
    main()
