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

usage: report_relay.py --relay DIR --replace DIR --plan PLAN --out DIR
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


def load(arm, d, plan_sha):
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
    acct = r3.accounting([d], wrapper=True)
    reasons += acct['accounting_problems']
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
                server_tokens=a['server_tokens'], wh=a['wh'], window_seconds=a['window_seconds'])


def build(relay_dir, replace_dir, plan_file):
    plan_file = Path(plan_file)
    plan = json.loads(plan_file.read_text()) if plan_file.exists() else None
    plan_sha = hashlib.sha256(plan_file.read_bytes()).hexdigest() if plan else None
    arms = {arm: load(arm, d, plan_sha) for arm, d in (('relay', relay_dir), ('replace', replace_dir))}
    s = dict(plan=str(plan_file), plan_sha256=plan_sha, arms={k: summary(v) for k, v in arms.items()})
    problems = [] if plan else ['frozen plan file not found']
    R, P = arms['relay'], arms['replace']
    if 'rows' in R and 'rows' in P:
        if set(R['rows']) != set(P['rows']):
            problems.append('the two arms ran different cohorts')
        if R['meta'].get('relay_settings') != P['meta'].get('relay_settings'):
            problems.append('the two arms ran different relay settings')
        differing = [k for k in set(R['rows']) & set(P['rows'])
                     if R['rows'][k].get('selected_source_slots') != P['rows'][k].get('selected_source_slots')
                     or len(R['rows'][k]['workers']) != len(P['rows'][k]['workers'])]
        if differing:
            problems.append(f'{len(differing)} case(s) with different selections or worker counts between the arms')
    complete = not problems and all(a.get('status') == 'complete' for a in arms.values())
    s['pairing_problems'] = problems
    s['status'] = 'complete' if complete else 'incomplete'
    if complete:
        common = sorted(R['rows'])
        b = sum(bool(R['rows'][k]['rescued']) and not P['rows'][k]['rescued'] for k in common)
        c = sum(bool(P['rows'][k]['rescued']) and not R['rows'][k]['rescued'] for k in common)
        s['mcnemar'] = dict(cases=len(common), relay_only=b, replace_only=c, exact_p=r3.sign_test(b, c))
        rs, ps = s['arms']['relay'], s['arms']['replace']
        s['facts'] = dict(relay_rescued=rs['rescued'], replace_rescued=ps['rescued'], relay_wrong=rs['wrong'],
                          replace_wrong=ps['wrong'],
                          server_token_ratio_relay_over_replace=(rs['server_tokens'] / ps['server_tokens']
                                                                if ps['server_tokens'] else None),
                          wh_ratio_relay_over_replace=rs['wh'] / ps['wh'] if rs['wh'] is not None and ps['wh'] else None)
    s['decision_rule'] = (plan or {}).get('decision_rule', 'plan not written')
    s['decision'] = ('evaluate the frozen rule against the facts' if complete
                     else 'incomplete - no decision: ' + '; '.join(
                         problems + [f"{k}: {a['status']} ({'; '.join(a.get('reasons') or [])})"
                                     for k, a in arms.items() if a.get('status') != 'complete']))
    s['disclosure'] = r3.disclosure()
    return s


def markdown(s):
    fmt = r3.fmt
    out = ['# Generic artifact relay vs equal-budget replacement', '', f"Status: {s['status']}", '',
           '| arm | status | cases | workers | rescued | wrong | server tokens | Wh | client tokens | artifact chars |',
           '|---|---|---|---|---|---|---|---|---|---|']
    for k in ARMS:
        a = s['arms'][k]
        out.append(f"| {k} | {a['status']} | " + ' | '.join(fmt(a.get(c)) for c in (
            'cases', 'workers', 'rescued', 'wrong', 'server_tokens', 'wh', 'client_tokens', 'artifact_chars_used')) + ' |')
    for k in ARMS:
        if s['arms'][k].get('reasons'):
            out.append(f"\n{k} incomplete: {'; '.join(s['arms'][k]['reasons'])}")
    if s['pairing_problems']:
        out.append(f"\nPairing problems: {'; '.join(s['pairing_problems'])}")
    if 'mcnemar' in s:
        m = s['mcnemar']
        out += ['', f"Paired (exact McNemar): relay-only rescued {m['relay_only']}, replace-only {m['replace_only']}, "
                    f"p = {m['exact_p']:.4g}", '', f"Facts: {json.dumps(s['facts'])}"]
    out += ['', f"Frozen rule: {s['decision_rule']}", '', f"Decision: {s['decision']}", '', '## Disclosures', '',
            s['disclosure'], '']
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--relay', type=Path, required=True)
    p.add_argument('--replace', type=Path, required=True)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    s = build(a.relay, a.replace, a.plan)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(s, indent=1, default=list) + '\n')
    (a.out / 'REPORT.md').write_text(markdown(s))
    print(json.dumps(dict(status=s['status'], mcnemar=s.get('mcnemar'))))
    return 0 if s['status'] == 'complete' else 3


if __name__ == '__main__':
    raise SystemExit(main())
