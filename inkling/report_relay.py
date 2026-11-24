#!/usr/bin/env python3
"""Gate/report for a generic artifact-relay screen (relay_replay.py): RELAY vs equal-budget REPLACE on the same frozen
abstentions. Writes OUT/{REPORT.md, report.json}.

Inputs: the two arm output directories written by relay_replay.py under inkling/account_cmd.py (each holds cases.jsonl,
metadata.json and the account_cmd arm_accounting.json) and the frozen plan file.
Complete only if, for BOTH arms: cases.jsonl, metadata.json (the right arm, not stopped, every cohort case present
once, no fault or error row) and a clean account_cmd record (shared validation of report_round3_hard17: runner exit 0,
counters present and consistent, idle after, UTC window) exist; both arms ran the frozen plan (plan sha256), the same
relay settings and exactly the same cohort with the same selected artifacts and worker counts per case; otherwise
'incomplete' with the reasons and no decision facts are evaluated.
Paired comparison: exact McNemar (two-sided binomial on the discordant cases) of rescued, RELAY vs REPLACE.
Costs: server generation tokens and GPU Wh of each arm from its account_cmd record (handoff/context input is charged
there too: prompt processing is server work).

Both arms' cohorts must equal the frozen case list given with --case-list. Input work (prompt and computed prefill
tokens) is reported next to generated tokens; total compute = generated + computed prefill. With several seeds of the
same puzzle the cases are not independent, so the McNemar p is descriptive only (the report says so).

Window screen (relay.window, Fable round 4 idea 2): --tail DIR --dense DIR compares two RELAY arms on the same frozen
cohort whose relay settings differ only in the window (same selections, worker counts and worker seeds), with rescues
per window and the number of workers whose excerpt changed.

usage: report_relay.py --relay DIR --replace DIR --plan PLAN --case-list FILE --out DIR
       report_relay.py --tail DIR --dense DIR --plan PLAN --case-list FILE --out DIR
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import report_round3_hard17 as r3  # noqa: E402

ARMS = ('relay', 'replace')
# comparison modes: (first role, its metadata arm), (second role, its metadata arm)
MODES = dict(replace=(('relay', 'relay'), ('replace', 'replace')),  # RELAY vs equal-budget REPLACE
             window=(('tail', 'relay'), ('dense', 'relay')))         # two RELAY arms: tail vs dense window


INPUT_KEYS = ('generation_tokens', 'prompt_tokens', 'prefill_compute_tokens')


def server_work(d):
    """Generation and input work of the arm from its account_cmd record (None + problem if a counter is invalid)."""
    rec = json.loads((Path(d) / 'arm_accounting.json').read_text()) if (Path(d) / 'arm_accounting.json').exists() else {}
    total = ((rec.get('server') or {}).get('total') or {})
    values, problems = {}, []
    for k in INPUT_KEYS:
        x = total.get(k)
        if not isinstance(x, (int, float)) or x != x or x < 0:
            problems.append(f'server {k} missing or invalid')
        values[k] = x
    if problems:
        return dict.fromkeys(('generation_tokens', 'prompt_tokens', 'prefill_compute_tokens', 'total_compute_tokens',
                              'total_tokens_incl_cached_prompt')), problems
    return dict(values, total_compute_tokens=values['generation_tokens'] + values['prefill_compute_tokens'],
                total_tokens_incl_cached_prompt=values['generation_tokens'] + values['prompt_tokens']), []


def load(arm, d, plan_sha, frozen_cases=None):
    d = Path(d)
    if not (d / 'cases.jsonl').exists():
        return dict(status='not run', dir=str(d))
    reasons = []
    meta = json.loads((d / 'metadata.json').read_text()) if (d / 'metadata.json').exists() else {}
    if not meta:
        reasons.append('no metadata.json')
    if meta and meta.get('arm') != arm:
        reasons.append(f"metadata arm is {meta.get('arm')!r}, expected {arm!r}")
    if meta and (meta.get('stopped') or not meta.get('completed_utc')):
        reasons.append('run stopped or not completed')
    if meta and meta.get('plan_sha256') != plan_sha:
        reasons.append('ran a different plan (plan_sha256 differs from the frozen plan file)')
    rows = r3.round3_gate.read_rows(d / 'cases.jsonl')
    keys = [(r.get('run'), r['task_id'], r['seed']) for r in rows]
    cohort = [tuple(c) for c in (meta.get('cohort') or {}).get('cases', [])]
    if len(set(keys)) != len(keys):
        reasons.append('duplicate case rows')
    if set(keys) != set(cohort):
        reasons.append(f'cases differ from the cohort ({len(set(cohort) - set(keys))} missing, {len(set(keys) - set(cohort))} extra)')
    faulted = [k for k, r in zip(keys, rows) if r.get('faults') or 'error' in r]
    if faulted:
        reasons.append(f'{len(faulted)} faulted case row(s)')
    if frozen_cases is not None and set(keys) != frozen_cases:
        reasons.append(f'cases differ from the frozen case list ({len(frozen_cases - set(keys))} missing, '
                       f'{len(set(keys) - frozen_cases)} extra)')
    acct = r3.accounting([d], wrapper=True)
    reasons += acct['accounting_problems']
    work, work_problems = server_work(d)
    reasons += work_problems
    acct = dict(acct, server_work=work)
    return dict(status='incomplete' if reasons else 'complete', reasons=reasons, dir=str(d), meta=meta,
                rows={k: r for k, r in zip(keys, rows)}, **acct)


def summary(a):
    if 'rows' not in a:
        return {k: a[k] for k in ('status', 'dir', 'reasons') if k in a}
    rows = list(a['rows'].values())
    return dict(status=a['status'], reasons=a['reasons'], cases=len(rows), workers=sum(len(r['workers']) for r in rows),
                rescued=sum(bool(r['rescued']) for r in rows), wrong=sum(bool(r['wrong']) for r in rows),
                answered=sum(bool(r['answered']) for r in rows), faults=sum(bool(r.get('faults')) for r in rows),
                client_tokens=sum(r.get('client_tokens') or 0 for r in rows),
                artifact_chars_used=sum(r.get('artifact_chars_used') or 0 for r in rows),
                server_tokens=a['server_tokens'], wh=a['wh'], window_seconds=a['window_seconds'], **a['server_work'],
                distinct_puzzles=len({k[1] for k in a['rows']}))


def build(first_dir, second_dir, plan_file, case_list, mode='replace'):
    """mode 'replace': RELAY vs REPLACE (equal settings). mode 'window': two RELAY arms on the same cohort whose relay
    settings differ only in relay.window (tail vs dense), with the same selections and worker counts per case."""
    (n1, arm1), (n2, arm2) = MODES[mode]
    plan_file, case_list = Path(plan_file), Path(case_list)
    plan = json.loads(plan_file.read_text()) if plan_file.exists() else None
    plan_sha = hashlib.sha256(plan_file.read_bytes()).hexdigest() if plan is not None else None
    frozen = {tuple(c[:3]) for c in json.loads(case_list.read_text())['cases']} if case_list.exists() else None
    arms = {name: load(arm, d, plan_sha, frozen if frozen is not None else set())
            for name, arm, d in ((n1, arm1, first_dir), (n2, arm2, second_dir))}
    s = dict(mode=mode, arm_names=[n1, n2], plan=str(plan_file), plan_sha256=plan_sha, case_list=str(case_list),
             case_list_sha256=hashlib.sha256(case_list.read_bytes()).hexdigest() if frozen is not None else None,
             arms={k: summary(v) for k, v in arms.items()})
    problems = ([] if plan is not None else ['frozen plan file not found']) + ([] if frozen is not None else ['frozen case list not found'])
    R, P = arms[n1], arms[n2]
    if 'rows' in R and 'rows' in P:
        if set(R['rows']) != set(P['rows']):
            problems.append('the two arms ran different cohorts')
        sr, sp = dict(R['meta'].get('relay_settings') or {}), dict(P['meta'].get('relay_settings') or {})
        if mode == 'window':
            if not (sr.get('changed_only') and sp.get('changed_only')):
                problems.append('a tail-vs-dense screen needs both arms run with relay.changed_only')
            if (sr.get('window'), sp.get('window')) != (n1, n2):
                problems.append(f"relay windows are {sr.get('window')!r} / {sp.get('window')!r}, expected {n1!r} / {n2!r}")
            sr.pop('window', None)
            sp.pop('window', None)
        if sr != sp:
            problems.append('the two arms ran different relay settings' + (' (beyond the window)' if mode == 'window' else ''))
        differing = [k for k in set(R['rows']) & set(P['rows'])
                     if R['rows'][k].get('selected_source_slots') != P['rows'][k].get('selected_source_slots')
                     or R['rows'][k].get('worker_positions') != P['rows'][k].get('worker_positions')
                     or len(R['rows'][k]['workers']) != len(P['rows'][k]['workers'])]
        if differing:
            problems.append(f'{len(differing)} case(s) with different selections or worker counts between the arms')
        if mode == 'window':  # paired workers: same slots and seeds, same endpoint set and per-endpoint cap
            seeds_differ = [k for k in set(R['rows']) & set(P['rows'])
                            if [(w.get('slot'), w.get('agent_seed')) for w in R['rows'][k]['workers']]
                            != [(w.get('slot'), w.get('agent_seed')) for w in P['rows'][k]['workers']]]
            if seeds_differ:
                problems.append(f'{len(seeds_differ)} case(s) whose worker slots or seeds differ between the arms')
            for field in ('endpoints', 'max_per_endpoint'):
                if R['meta'].get(field) != P['meta'].get(field):
                    problems.append(f'the two arms ran with different {field}')
    complete = not problems and all(a.get('status') == 'complete' for a in arms.values())
    s['pairing_problems'] = problems
    s['status'] = 'complete' if complete else 'incomplete'
    if complete:
        common = sorted(R['rows'])
        b = sum(bool(R['rows'][k]['rescued']) and not P['rows'][k]['rescued'] for k in common)
        c = sum(bool(P['rows'][k]['rescued']) and not R['rows'][k]['rescued'] for k in common)
        puzzles = len({k[1] for k in common})
        s['mcnemar'] = {'cases': len(common), 'distinct_puzzles': puzzles, f'{n1}_only': b, f'{n2}_only': c,
                        'exact_p': r3.sign_test(b, c),
                        'note': ('descriptive only: the cases are not independent (several seeds of the same puzzle)'
                                 if puzzles < len(common) else 'cases are distinct puzzles')}
        x, y = s['arms'][n1], s['arms'][n2]
        s['facts'] = {f'{n1}_rescued': x['rescued'], f'{n2}_rescued': y['rescued'], f'{n1}_wrong': x['wrong'],
                      f'{n2}_wrong': y['wrong'],
                      f'server_token_ratio_{n1}_over_{n2}': x['server_tokens'] / y['server_tokens'] if y['server_tokens'] else None,
                      f'compute_token_ratio_{n1}_over_{n2}': (x['total_compute_tokens'] / y['total_compute_tokens']
                                                             if y['total_compute_tokens'] else None),
                      f'wh_ratio_{n1}_over_{n2}': x['wh'] / y['wh'] if x['wh'] is not None and y['wh'] else None}
        if mode == 'window':  # the changed-only subset: workers that started in both arms, accepted workers per arm
            pairs = [(w1, w2) for k in common for w1, w2 in zip(R['rows'][k]['workers'], P['rows'][k]['workers'])]
            started = [(w1, w2) for w1, w2 in pairs if w1.get('started', True) and w2.get('started', True)]
            s['facts'].update(rescues_per_window={n1: x['rescued'], n2: y['rescued']},
                              changed_workers=len(pairs), changed_workers_started_in_both=len(started),
                              accepted_workers={n1: sum(w1.get('verdict') is True for w1, _ in pairs),
                                                n2: sum(w2.get('verdict') is True for _, w2 in pairs)},
                              accepted_workers_started_in_both={n1: sum(w1.get('verdict') is True for w1, _ in started),
                                                                n2: sum(w2.get('verdict') is True for _, w2 in started)})
    s['decision_rule'] = (plan or {}).get('decision_rule', 'plan not written')
    s['decision'] = ('evaluate the frozen rule against the facts' if complete
                     else 'incomplete - no decision: ' + '; '.join(
                         problems + [f"{k}: {a['status']} ({'; '.join(a.get('reasons') or [])})"
                                     for k, a in arms.items() if a.get('status') != 'complete']))
    s['disclosure'] = r3.disclosure()
    return s


def markdown(s):
    fmt = r3.fmt
    n1, n2 = s['arm_names']
    title = ('Generic artifact relay vs equal-budget replacement' if s['mode'] == 'replace'
             else 'Artifact relay: tail window vs dense window')
    out = [f'# {title}', '', f"Status: {s['status']}", '',
           '| arm | status | cases | puzzles | workers | rescued | wrong | generated | prompt | prefill computed | '
           'total compute | Wh | artifact chars |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for k in (n1, n2):
        a = s['arms'][k]
        out.append(f"| {k} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'distinct_puzzles', 'workers', 'rescued', 'wrong', 'generation_tokens', 'prompt_tokens',
            'prefill_compute_tokens', 'total_compute_tokens', 'wh', 'artifact_chars_used')) + ' |')
    out += ['', 'total compute = generated + prefill computed (server counters; cached prompt tokens are not recomputed).']
    for k in (n1, n2):
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if s['pairing_problems']:
        out.append(f"\nPairing problems: {'; '.join(s['pairing_problems'])}")
    if 'mcnemar' in s:
        m = s['mcnemar']
        out += ['', f"Paired (exact McNemar): {n1}-only rescued {m[n1 + '_only']}, {n2}-only {m[n2 + '_only']}, "
                    f"p = {m['exact_p']:.4g} over {m['cases']} cases / {m['distinct_puzzles']} distinct puzzles ({m['note']})",
                '', f"Facts: {json.dumps(s['facts'])}"]
    out += ['', f"Frozen rule: {s['decision_rule']}", '', f"Decision: {s['decision']}", '', '## Disclosures', '',
            s['disclosure'], '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--relay', type=Path, help='mode replace: the RELAY arm')
    p.add_argument('--replace', type=Path, help='mode replace: the REPLACE arm')
    p.add_argument('--tail', type=Path, help='mode window: the RELAY arm run with relay.window tail')
    p.add_argument('--dense', type=Path, help='mode window: the RELAY arm run with relay.window dense')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--case-list', type=Path, required=True, help='the frozen case list both arms were run on')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    if a.tail or a.dense:
        if not (a.tail and a.dense) or a.relay or a.replace:
            raise SystemExit('window screen: give --tail and --dense (and not --relay/--replace)')
        s = build(a.tail, a.dense, a.plan, a.case_list, mode='window')
    else:
        if not (a.relay and a.replace):
            raise SystemExit('give --relay and --replace, or --tail and --dense')
        s = build(a.relay, a.replace, a.plan, a.case_list)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (a.out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(status=s['status'], mcnemar=s.get('mcnemar'))))
    return 0 if s['status'] == 'complete' else 3


if __name__ == '__main__':
    raise SystemExit(main())
