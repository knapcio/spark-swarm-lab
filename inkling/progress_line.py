#!/usr/bin/env python3
"""One progress line for any run directory under runs/ (offline; reads files only).

Recognised run types (first match wins):
  relay screen   relay_replay output (metadata protocol swarm-relay-replay-v1): cases with rows / cohort, rescued,
                 wrong, faults
  closer replay  closer_replay output (rows with 'closers'): cases, rescued, wrong, infra
  arithmetic     run_variants arm (cases.jsonl rows with 'policy'): cases / plan cases, solved, wrong, abstain,
                 cancelled and escalation agents (+ resume segments present)
  coding         cases.json (list of case rows): cases, solved, wrong (answered but not solved), unanswered
  log only       a run that has written no case file yet: the last '{"done": ...}' line of runs/NAME.log
An account_cmd wrapper record (arm_accounting.json with 'command') adds its state: running, or done with the exit
and any accounting/energy error.

usage: progress_line.py RUN_DIR_NAME [--runs DIR]
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def rows_of(path):
    out = []
    for line in Path(path).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a line being written
    return out


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def plan_cases(meta, root):
    plan = (meta or {}).get('protocol')
    if not isinstance(plan, dict):
        return None
    if plan.get('case_list'):
        listed = read(root / plan['case_list']) or read(plan['case_list'])
        return len(listed['cases']) if listed else None
    if isinstance(plan.get('tasks'), int) and isinstance(plan.get('seeds'), list):
        return plan['tasks'] * len(plan['seeds'])
    return None


def wrapper_state(d):
    acct = read(d / 'arm_accounting.json')
    if not acct or 'command' not in acct:
        return ''
    errors = [x for x in (acct.get('accounting_error'), acct.get('energy_error')) if x]
    return f"; account_cmd done (runner exit {acct.get('runner_exit')}" + (f", {'; '.join(e[:80] for e in errors)}" if errors else '') + ')'


def line(name, runs):
    d = runs / name
    meta = read(d / 'metadata.json') or {}
    cases_jsonl, cases_json = d / 'cases.jsonl', d / 'cases.json'
    if meta.get('protocol') == 'swarm-relay-replay-v1':
        rows = rows_of(cases_jsonl) if cases_jsonl.exists() else []
        total = meta.get('cohort_cases') or len((meta.get('cohort') or {}).get('cases') or [])
        return (f"progress {name}: {meta.get('arm', '?')} cases {len(rows)}/{total}, rescued {sum(bool(r.get('rescued')) for r in rows)}, "
                f"wrong {sum(bool(r.get('wrong')) for r in rows)}, faults {sum(bool(r.get('faults')) or 'error' in r for r in rows)}"
                + wrapper_state(d))
    if cases_jsonl.exists():
        rows = rows_of(cases_jsonl)
        if rows and 'closers' in rows[0]:
            return (f"progress {name}: closer cases {len(rows)}, rescued {sum(bool(r.get('solved')) for r in rows)}, "
                    f"wrong {sum(bool(r.get('wrong')) for r in rows)}, infra {sum(bool(r.get('infra')) for r in rows)}"
                    + wrapper_state(d))
        solved, wrong = sum(bool(r.get('solved')) for r in rows), sum(bool(r.get('wrong')) for r in rows)
        total = plan_cases(meta, runs.parent)
        resumes = len([p for p in runs.glob(name + '-resume*') if re.fullmatch(re.escape(name) + r'-resume\d+', p.name)])
        return (f"progress {name}: cases {len(rows)}/{total if total is not None else '?'}, solved {solved}, wrong {wrong}, "
                f"abstain {len(rows) - solved - wrong}, infra {sum(bool(r.get('infra')) or 'error' in r for r in rows)}, "
                f"cancelled agents {sum(r.get('cancelled_agents', 0) or 0 for r in rows)}, "
                f"escalation agents {sum(r.get('escalated_agents', 0) or 0 for r in rows)}"
                + (f', resume segments {resumes}' if resumes else '') + wrapper_state(d))
    if cases_json.exists():
        data = read(cases_json)
        rows = data if isinstance(data, list) else (data or {}).get('cases') or []
        solved = sum(bool(r.get('solved')) for r in rows)
        wrong = sum(bool(r.get('wrong', r.get('answered') and not r.get('solved'))) for r in rows)
        return (f"progress {name}: coding cases {len(rows)}, solved {solved}, wrong {wrong}, "
                f"unanswered {sum(not r.get('answered') for r in rows)}" + wrapper_state(d))
    log = runs / (name + '.log')
    done = [json.loads(x) for x in log.read_text().splitlines() if x.startswith('{"done"')] if log.exists() else []
    if not done:
        state = 'started, no finished item yet' if (d.exists() or log.exists()) else 'not started'
        return f'progress {name}: {state}' + (wrapper_state(d) if d.exists() else '')
    last = done[-1]
    return f"progress {name}: items {last.get('done')}/{last.get('total')}" + wrapper_state(d)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('run')
    p.add_argument('--runs', type=Path, default=ROOT / 'runs')
    a = p.parse_args(argv)
    print(line(a.run, a.runs))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
