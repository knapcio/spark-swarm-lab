#!/usr/bin/env python3
"""Post-hoc early-stop simulation for the Inkling-2-Mini coding swarm (coding-hard-v1, 72 cases, 8 agents).

Exploratory, read-only replay of recorded traces; no model calls, no sandbox calls, no machine access.

Policy: stop a case (cancel every still-running or not-yet-started agent) as soon as the first candidate, in TIME
order of its feedback result, passes the public feedback cases and is not disproved by the case's contract.
Score = recorded hidden holdout result of the candidate picked.

Data (same as the 69/72 and 70/72 numbers):
  candidates  runs/inkling-coding-hard-v1 + runs/inkling-coding-hard-v1b (first non-faulted record per events file,
              exactly as inkling/report_coding.py and disproof_select.load_candidates)
  verdicts    runs/disproof-select-inkling-v1/verdicts.json (contract_valid, per-agent disproved)
  contracts   runs/disproof-contracts-v1/contracts.json + events/ (tokens and latency of the contract call)

Candidate time = timestamp of the agent's feedback `evaluation_end` event. Two timelines:
  recorded  absolute wall clock as recorded. Agents of one case did NOT start together (per-endpoint work queues,
            12 agents/node, shared with another study), so an agent not yet started at the stop costs 0 tokens.
            Valid only for cases whose 8 agents all come from one run; the 7 cases mixing v1 and v1b agents use
            the aligned timeline instead (flagged in the output).
  aligned   every agent's times taken relative to its own run_start, i.e. all 8 agents launched together at t=0
            (the 'agents run in parallel' idealisation).
Tokens of an agent at stop time T: sum over its requests (completion_tokens_charged); a request still generating at T
is linearly interpolated from request_start to request_end (ESTIMATE: includes queue/prefill time, no per-token
timestamps). Agents whose last request ended before T but whose grading was still running are counted in full.
Variants:
  fb_only        first feedback-passing candidate in time order, contracts ignored.
  disproof       contract valid -> first feedback-passing, non-disproved candidate in time order; contract invalid
                 -> first feedback-passing in time order; contract valid but every passing candidate disproved ->
                 no early stop, run to end, pick by the frozen rule's fallback (earliest feedback-passing by agent
                 order). Contract latency ignored (contract assumed ready at t=0).
  disproof_wait  same pick as disproof, but the stop cannot happen before the contract is ready (contract started at
                 the case start; its wall = first request_start .. last request_end of its own trace, measured in a
                 different run under different load; sandbox validation time not recorded, ignored). This also
                 applies when the contract is invalid (invalidity is only known once it is ready).
No candidate qualifies -> the case runs to the end with the same answer as the corresponding run-to-end rule.
"""
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from run_agents72 import operational_fault  # noqa: E402

RUNS = HERE / 'runs'
OUT = HERE / 'results/inkling-coding-early-stop-sim/sim.json'
CANDIDATE_RUNS = ('inkling-coding-hard-v1', 'inkling-coding-hard-v1b')


def ts(event):
    return datetime.fromisoformat(event['timestamp']).timestamp()


def load_agent(row):
    events = [json.loads(line) for line in open(row['events']) if line.strip()]
    start, end = ts(events[0]), ts(events[-1])
    reqs, open_req = [], {}
    feedback_t = None
    for e in events:
        if e['type'] == 'request_start':
            open_req[e['request_id']] = ts(e)
        elif e['type'] == 'request_end':
            s = open_req.pop(e['request_id'])
            reqs.append((s, ts(e), int(e.get('completion_tokens_charged') or (e.get('usage') or {}).get('completion_tokens') or 0)))
        elif e['type'] == 'evaluation_end' and e.get('phase') == 'feedback':
            feedback_t = ts(e)
    for s in open_req.values():  # never observed in kept records; counted as running until the agent's end
        reqs.append((s, end, 0))
    tokens = sum(r[2] for r in reqs)
    charged = row.get('charged_completion_tokens') or row.get('completion_tokens') or 0
    return dict(start=start, end=end, reqs=reqs, feedback_t=feedback_t, tokens=tokens, summary_tokens=charged,
                feedback=bool(row['feedback_pass']), holdout=bool(row['holdout_pass']))


def load_cases():
    cases, seen = {}, set()
    for run in CANDIDATE_RUNS:
        for r in json.loads((RUNS / run / 'summary.json').read_text()):
            name = os.path.basename(r['events'])
            if operational_fault(r) or name in seen:
                continue
            seen.add(name)
            a = load_agent(r)
            a['run'] = run
            cases.setdefault(f"{r['task_id']}-s{r['seed']}", {})[r['agent']] = a
    return cases


def contract_info(stem, contracts):
    rec = contracts.get(stem) or {}
    path = RUNS / 'disproof-contracts-v1/events' / (stem + '.jsonl')
    wall = None
    if path.exists():
        ev = [json.loads(line) for line in open(path) if line.strip()]
        starts = [ts(e) for e in ev if e['type'] == 'request_start']
        ends = [ts(e) for e in ev if e['type'] == 'request_end']
        if starts and ends:
            wall = max(ends) - min(starts)
    return dict(tokens=int(rec.get('tokens') or 0), wall=wall, valid=rec.get('valid'))


def tokens_at(agent, t, offset):
    total = 0.0
    for s, e, n in agent['reqs']:
        s, e = s - offset, e - offset
        if e <= t:
            total += n
        elif s < t:
            total += n * (t - s) / (e - s) if e > s else n
    return total


def simulate_case(case, verdict, contract, timeline):
    mixed = len({a['run'] for a in case.values()}) > 1
    used = 'aligned' if (timeline == 'recorded' and mixed) else timeline
    off = {k: (a['start'] if used == 'aligned' else 0.0) for k, a in case.items()}
    t0 = min(a['start'] - off[k] for k, a in case.items())
    t_end = max(a['end'] - off[k] for k, a in case.items())
    full_tokens = sum(a['tokens'] for a in case.values())
    order = sorted((a['feedback_t'] - off[k], k) for k, a in case.items() if a['feedback'] and a['feedback_t'] is not None)
    agent_order_first = next((k for k in sorted(case) if case[k]['feedback']), None)
    valid = verdict['contract_valid'] is True
    disproved = {int(k) for k, v in verdict['agents'].items() if v.get('disproved') is True}
    out = {}
    for variant in ('fb_only', 'disproof', 'disproof_wait'):
        if variant == 'fb_only':
            quals = order
        elif valid:
            quals = [x for x in order if x[1] not in disproved]
        else:
            quals = order
        if quals:
            t_pick, pick = quals[0]
            t_stop = t_pick
            if variant == 'disproof_wait' and contract['wall'] is not None:
                t_stop = max(t_pick, t0 + contract['wall'])
            t_stop = min(t_stop, t_end)
            early = True
        else:  # never qualifies: run to the end, same answer as the run-to-end rule
            pick = agent_order_first
            t_stop, early = t_end, False
        tok = sum(tokens_at(a, t_stop, off[k]) for k, a in case.items())
        extra = contract['tokens'] if variant != 'fb_only' else 0
        out[variant] = dict(pick=pick, early=early, solved=bool(pick is not None and case[pick]['holdout']),
                            stop_s=round(t_stop - t0, 1), tokens=round(tok), contract_tokens=extra)
    return dict(timeline=used, mixed_runs=mixed, wall_s=round(t_end - t0, 1), tokens_full=full_tokens,
                feedback_time_order=[k for _, k in order], agent_order_first=agent_order_first,
                contract_valid=verdict['contract_valid'], disproved=sorted(disproved),
                contract_tokens=contract['tokens'], contract_wall_s=None if contract['wall'] is None else round(contract['wall'], 1),
                variants=out)


def baseline(case, verdict):
    first = next((k for k in sorted(case) if case[k]['feedback']), None)
    passing = [k for k in sorted(case) if case[k]['feedback']]
    dis = {int(k) for k, v in verdict['agents'].items() if v.get('disproved') is True}
    surv = [k for k in passing if k not in dis]
    dp = surv[0] if (verdict['contract_valid'] is True and surv) else first
    return dict(original=bool(first is not None and case[first]['holdout']), original_pick=first,
                disproof=bool(dp is not None and case[dp]['holdout']), disproof_pick=dp)


def pct(a, b):
    return round(100.0 * (1 - a / b), 1) if b else None


def main():
    cases = load_cases()
    verdicts = json.loads((RUNS / 'disproof-select-inkling-v1/verdicts.json').read_text())
    contracts = json.loads((RUNS / 'disproof-contracts-v1/contracts.json').read_text())
    assert len(cases) == 72 and all(len(c) == 8 for c in cases.values()), 'expected 72 complete cases'
    token_mismatch = [(s, k) for s, c in cases.items() for k, a in c.items() if a['tokens'] != a['summary_tokens']]
    base = {s: baseline(c, verdicts[s]) for s, c in cases.items()}
    orig_solved = sum(b['original'] for b in base.values())
    disp_solved = sum(b['disproof'] for b in base.values())
    contract_meta = {s: contract_info(s, contracts) for s in cases}
    result = dict(
        description=__doc__.strip().split('\n')[0], post_hoc=True,
        reproduced=dict(original_solved=orig_solved, disproof_solved=disp_solved,
                        tokens_per_case_full=round(sum(a['tokens'] for c in cases.values() for a in c.values()) / 72),
                        agent_tokens_trace_vs_summary_mismatches=len(token_mismatch)),
        contracts=dict(valid=sum(v['contract_valid'] is True for v in verdicts.values()),
                       tokens_total=sum(c['tokens'] for c in contract_meta.values()),
                       tokens_per_case=round(sum(c['tokens'] for c in contract_meta.values()) / 72),
                       wall_median_s=round(statistics.median(c['wall'] for c in contract_meta.values() if c['wall']), 1),
                       wall_missing=[s for s, c in contract_meta.items() if c['wall'] is None]),
        timelines={})
    for timeline in ('recorded', 'aligned'):
        per = {s: simulate_case(cases[s], verdicts[s], contract_meta[s], timeline) for s in sorted(cases)}
        full_tok = sum(p['tokens_full'] for p in per.values())
        walls = [p['wall_s'] for p in per.values()]
        summary = dict(cases_on_aligned_fallback=sorted(s for s, p in per.items() if p['timeline'] != timeline),
                       tokens_full_total=full_tok, tokens_full_per_case=round(full_tok / 72),
                       wall_full_total_s=round(sum(walls)), wall_full_median_s=round(statistics.median(walls), 1),
                       variants={})
        for variant, ref_key in (('fb_only', 'original'), ('disproof', 'disproof'), ('disproof_wait', 'disproof')):
            v = {s: p['variants'][variant] for s, p in per.items()}
            tok = sum(x['tokens'] for x in v.values())
            ctok = sum(x['contract_tokens'] for x in v.values())
            stops = [x['stop_s'] for x in v.values()]
            changed = []
            for s, x in v.items():
                b = base[s]
                for name in ('original', 'disproof'):
                    if x['solved'] != b[name]:
                        changed.append(dict(case=s, vs=name, early_stop_solved=x['solved'], early_pick=x['pick'],
                                            run_to_end_pick=b[name + '_pick'], run_to_end_solved=b[name],
                                            feedback_time_order=per[s]['feedback_time_order'],
                                            disproved=per[s]['disproved'], contract_valid=per[s]['contract_valid'],
                                            holdout_by_agent={k: cases[s][k]['holdout'] for k in sorted(cases[s])}))
            summary['variants'][variant] = dict(
                solved=sum(x['solved'] for x in v.values()), compare_to=ref_key,
                stopped_early=sum(x['early'] for x in v.values()),
                tokens_total_estimate=tok, tokens_per_case_estimate=round(tok / 72), tokens_saved_pct=pct(tok, full_tok),
                contract_tokens_total=ctok,
                tokens_incl_contract_per_case=round((tok + ctok) / 72),
                saved_incl_contract_vs_full_with_contract_pct=pct(tok + ctok, full_tok + ctok) if ctok else None,
                saved_incl_contract_vs_full_without_contract_pct=pct(tok + ctok, full_tok),
                stop_total_s=round(sum(stops)), stop_median_s=round(statistics.median(stops), 1),
                wall_saved_total_pct=pct(sum(stops), sum(walls)),
                wall_saved_median_of_case_pct=round(statistics.median(100 * (1 - x['stop_s'] / per[s]['wall_s'])
                                                                      for s, x in v.items()), 1),
                changed_cases=changed)
        summary['per_case'] = per
        result['timelines'][timeline] = summary
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    brief = dict(reproduced=result['reproduced'], contracts=result['contracts'],
                 timelines={t: dict({k: v for k, v in s.items() if k not in ('per_case', 'variants')},
                                    variants={n: {k: (len(x) if k == 'changed_cases' else x) for k, x in d.items()}
                                              for n, d in s['variants'].items()})
                            for t, s in result['timelines'].items()})
    print(json.dumps(brief, indent=1))
    for t, s in result['timelines'].items():
        for n, d in s['variants'].items():
            for c in d['changed_cases']:
                print(t, n, json.dumps(c))


if __name__ == '__main__':
    main()
