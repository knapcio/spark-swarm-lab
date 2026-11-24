#!/usr/bin/env python3
"""Report for swarm-hints-hard16-v1 (plans 65ea777): shared first wave on 192 six-number cases of arithmetic-hard-v16,
then four escalation-only arms on the strict-hard cases (N no hints, S current hints = default, H02 hints 0+2, P
last-move partition). Primary: correct rescues per arm, exact McNemar vs S. Writes results/swarm-hints-hard16-v1/."""
import json
from collections import Counter

from report_cancel_hard6 import RUNS, ROOT, load, paired, summarize

OUT = ROOT / 'results' / 'swarm-hints-hard16-v1'
WAVE = 'swarm-hints-hard16-v1-wave-deep4cancel'
ARMS = [('N', 'esc_none'), ('S', 'esc_strategy'), ('H02', 'esc_h02'), ('P', 'esc_split')]
NAMES = dict(N='N: no hints', S='S: current 4 strategy hints (default)', H02='H02: hints 0 + 2 only', P='P: last-move partition hints')


def vs(v):
    return '' if v is None else f"+{v['wins']} / -{v['losses']}, p = {v['p']:.3g}"


def segments(run):
    return [run] + [f'{run}-resume{i}' for i in range(1, 10) if (RUNS / f'{run}-resume{i}' / 'cases.jsonl').exists()]


def main():
    hard = json.loads((OUT / 'strict_hard_cases.json').read_text())
    data = {k: load(segments(f'swarm-hints-hard16-v1-{pol}')) for k, pol in ARMS if (RUNS / f'swarm-hints-hard16-v1-{pol}' / 'cases.jsonl').exists()}
    wave = summarize(*load(segments(WAVE)))
    res = dict(wave=wave, strict_hard=len(hard['cases']), arms={}, vs_S={}, accepted_by_hint={})
    for k, (cases, acct) in data.items():
        s = summarize(cases, acct)
        res['arms'][k] = s
        hints = Counter()
        for r in cases.values():
            for a in r['agents']:
                if a.get('verdict') is True:
                    hints[(a['slot'] - 4) % 4] += 1
        res['accepted_by_hint'][k] = dict(sorted(hints.items()))
    if 'S' in data:
        for k in data:
            if k != 'S':
                res['vs_S'][k] = paired(data[k][0], data['S'][0])
        q = [k for k in data if k != 'S' and res['arms'][k]['wrong'] == 0 and res['vs_S'][k]['wins'] > res['vs_S'][k]['losses']
             and res['vs_S'][k]['p'] < 0.05]
        res['decision'] = dict(qualifying=q, new_default=max(q, key=lambda k: res['arms'][k]['solved']) if q else None,
                               hints_show_no_benefit=('N' in data and res['arms']['N']['solved'] >= res['arms']['S']['solved']))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'report.json').write_text(json.dumps(res, indent=1) + '\n')
    lines = ['| Arm | Rescued (correct) | Wrong | Abstain | Server tokens/case | Arm wall | GPU Wh | vs S (+/-, p) |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for k, _ in ARMS:
        if k in res['arms']:
            s, v = res['arms'][k], res['vs_S'].get(k)
            lines.append(f"| {NAMES[k]} | **{s['solved']}** | {s['wrong']} | {s['abstain']} | {s['server_tokens_per_case']:,} | "
                         f"{s['arm_wall_seconds'] / 60:.0f} min | {s['energy_wh']} | {vs(v)} |")
    md = '\n'.join(lines) + '\n'
    (OUT / 'tables.md').write_text(md)
    d = res.get('decision')
    verdict = '' if d is None else (f"**Default escalation hints change to {d['new_default']}** (confirmation on a fresh full-swarm corpus follows)."
                                     if d['new_default'] else '**The default escalation hints stay** (no arm beats S with p < 0.05 and 0 wrong).')
    if d and d['hints_show_no_benefit']:
        verdict += ' N (no hints) rescued at least as many cases as S: the current hints show no measurable benefit on this corpus.'
    (OUT / 'REPORT.md').write_text(f"""# Escalation hints on a shared first wave (swarm-hints-hard16-v1)

Plans `SWARM_HINTS_HARD16_WAVE_PLAN.json` and `SWARM_HINTS_HARD16_ESC_PLAN.json` (65ea777) were frozen and pushed before
arithmetic-hard-v16 (b079f8b) was generated. Fable round-2 ideas 4 and 5, and the recheck of the current strategy hints.
Phase 1 ran the default first wave (4 unhinted agents, cancel on accept) once on 192 six-number cases (24 evaluation tasks
x 8 seeds): {wave['solved']} solved, {wave['wrong']} wrong, {res['strict_hard']} cases without an accepted plan (the strict-hard cases).
Phase 2 ran four escalation-only arms on exactly those cases, each alone on the fleet: slots 4-11, 4 in flight,
failure-driven replacement, cancel on accept, the same agent and judge seeds in every arm; only the hint text differs.
Selection caveat: the cases are chosen by the swarm's own first-wave failure, so the counts are rescues, not a solved rate.

## Result

{md}
Accepted agents by hint position ((slot - 4) mod 4): {res['accepted_by_hint']}.

{verdict}

**Mechanism.** The P hints each fix one assumption about the final move and turn the six-number task into a smaller
sub-target the agent computes itself: (0) the last move subtracts a given x, so build target + x; (1) it adds x, so build
target - x; (2) it multiplies or divides by x; (3) it combines two values built from disjoint groups. Accepted P agents by
hint: 0: {res['accepted_by_hint'].get('P', {}).get('0', 0)}, 1: {res['accepted_by_hint'].get('P', {}).get('1', 0)}, 2: {res['accepted_by_hint'].get('P', {}).get('2', 0)}, 3: {res['accepted_by_hint'].get('P', {}).get('3', 0)}; the additive and subtractive last moves carry most rescues, consistent with
Fable's finding that the last move uses a single given number in 90 % of solutions (subtraction 65 %). The current hints
are generic strategies ("work backward", "product near the target", ...) and rescued fewer cases than no hint at all (S 14
vs N 19, not significant). P also used 23 % fewer tokens per case and 22 % less wall, because rescued cases stop early.
The hints are derived from a failure analysis of older corpora of the same generator; hard-v16 was generated after the
plans were frozen, so this is a fresh-corpus result, but conditional on first-wave failure (rescues, not a solved rate).
Per the frozen rule, P becomes the default escalation hint set after a full-swarm confirmation on a fresh corpus
(roll12strategy with P hints vs roll12strategy), which is queued next.

Files: `run_variants.py` (`esc_*`, `SPLIT_HINTS`), `inkling/strict_hard_cases.py`, `inkling/report_hints_hard16.py`, numbers in [report.json](report.json).
""")
    print(md)


if __name__ == '__main__':
    main()
