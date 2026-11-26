#!/usr/bin/env python3
"""Report for the live-collaboration replay screens S0 and S1 (DESIGN-live-collab-fable.md 4.1, 4.2; plans from
inkling/collab_plans.py, runs from collab_replay.py on research/collab-v1). Writes results/<study>/{report.json,
REPORT.md}.

Validation (complete inputs only): every output directory embeds a plan equal to the plan file; every planned job
(s1: case x arm of the cohort; s0: stream-cut) is present and complete (no infrastructure fault); several output
directories (a rerun of incomplete jobs with --jobs) merge per job, a later complete job replacing an earlier one.
Anything else: "incomplete", no decision. All numbers are unrounded counts or exact fractions.

S1 (frozen in the plan, per protocol arm C against D'): 1. wrong(C) == 0 over all attempts; 2. rescued puzzles(C) >=
rescued(D') + 4; 3. accepted agents(C) >= accepted agents(D'); 4. novelty(C) >= novelty(D') - 0.02. PASS if all hold;
GREY (run the extension cohort) if C leads by 2 or 3 with 1, 3, 4 met; else STOP. With the extension cohort present the
pooled rule applies: per puzzle (rescued if any of its cases is), C >= D' + 6, rules 1, 3, 4 on the pooled cases.
Novelty of a thinking segment after the cut: share of its distinct word 5-grams that occur in no text another agent of
the case wrote before the segment started (peers' recorded prefixes, peers' thinking prorated linearly over their
calls' streaming time, peers' notes); segments are split at the protocol marks by character share so both arms are
measured on segments of the same length; arm novelty = mean over segments.

S0: the plan's checks (prefix identity, cached share of the board phase, checkpoint latency, reply parse rate, note
length, arithmetic result correctness, distinct focus lines, immediate answers, own repetition); PASS if all hold,
else the failed checks' actions (STOP if any says stop, else FIX).

usage: report_collab_screen.py --plan PLAN --runs DIR [DIR ...] [--out DIR]
"""
import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from report_round3_hard17 import sign_test  # noqa: E402

NGRAM = 5
NOVELTY_MARGIN = Fraction(2, 100)
WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
EQUATION = re.compile(r'(-?\d+(?:\.\d+)?)\s*([+\-*/x×÷])\s*(-?\d+(?:\.\d+)?)\s*=\s*(-?\d+(?:\.\d+)?)')


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]


def grams(text, n=NGRAM):
    words = WORD.findall((text or '').lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


# ---------------------------------------------------------------- loading and validation

def load(plan, run_dirs):
    """Merged rows and records of the screen's output directories, with validation problems."""
    problems, jobs, records = [], {}, {}
    for d in run_dirs:
        d = Path(d)
        meta_path = d / 'metadata.json'
        if not meta_path.exists():
            problems.append(f'{d}: no metadata.json')
            continue
        meta = json.loads(meta_path.read_text())
        if meta.get('plan') != plan:
            problems.append(f'{d}: embedded plan differs from the plan file')
            continue
        recs = read_jsonl(d / 'records.jsonl')
        if plan['screen'] == 's1':
            for row in read_jsonl(d / 'cases.jsonl'):
                key = (row['case_id'], row['arm'])
                if key not in jobs or row['status'] == 'complete':
                    jobs[key] = row
                    records[key] = [r for r in recs if (r['case_id'], r['arm']) == key]
        else:
            for r in recs:
                key = (r['group_id'], r['slot'])
                if key not in jobs or r['status'] == 'complete':
                    jobs[key] = r
                    records[key] = [r]
    return jobs, records, problems


def expected_jobs(plan, cohorts):
    if plan['screen'] == 's1':
        return {(k['case_id'], arm) for k in plan['cases'] if k['cohort'] in cohorts for arm in plan['arm_order']}
    return {(g['group_id'], m['slot']) for g in plan['groups'] for m in g['members']}


def completeness(plan, jobs, cohorts):
    want = expected_jobs(plan, cohorts)
    missing = sorted(want - set(jobs))
    bad = sorted(k for k in want & set(jobs) if jobs[k]['status'] != 'complete')
    out = []
    if missing:
        out.append(f'{len(missing)} planned jobs missing, e.g. {missing[0]}')
    if bad:
        out.append(f'{len(bad)} jobs not complete, e.g. {bad[0]}')
    return out


# ---------------------------------------------------------------- novelty (s1)

def split_segment(seg, marks):
    """Pieces of a thinking segment at the protocol marks (character share), with prorated times."""
    start, n, text = seg['think_before'], seg['tokens'], seg.get('text') or ''
    t0 = seg.get('t_first') or seg['t0']
    t1 = seg['t1']
    cuts = [m - start for m in marks if start < m < start + n]
    bounds = [0] + cuts + [n]
    pieces = []
    for a, b in zip(bounds, bounds[1:]):
        ca, cb = round(len(text) * a / max(1, n)), round(len(text) * b / max(1, n))
        pieces.append(dict(text=text[ca:cb], t_start=t0 + (t1 - t0) * a / max(1, n),
                           t_end=t0 + (t1 - t0) * b / max(1, n)))
    return pieces


def written_before(agent, t):
    """Text of an agent written before time t: recorded prefix, thinking (prorated within a call), notes."""
    parts = [agent.get('prefix_text') or '']
    for seg in agent.get('segments') or []:
        text = seg.get('text') or ''
        s0, s1 = seg.get('t_first') or seg['t0'], seg['t1']
        if s1 <= t:
            parts.append(text)
        elif s0 < t:
            parts.append(text[:round(len(text) * (t - s0) / max(1e-9, s1 - s0))])
    for note in agent.get('notes') or []:
        if note.get('t') is not None and note['t'] <= t:
            parts.append(note.get('text') or '')
    return '\n'.join(parts)


def novelty(agents, marks):
    """Per-segment novelty values of one case-arm (segments with at least one 5-gram)."""
    values = []
    for a in agents:
        for seg in a.get('segments') or []:
            for piece in split_segment(seg, marks):
                mine = grams(piece['text'])
                if not mine:
                    continue
                others = set()
                for b in agents:
                    if b is not a:
                        others |= grams(written_before(b, piece['t_start']))
                values.append(Fraction(len(mine - others), len(mine)))
    return values


# ---------------------------------------------------------------- s1

def arm_summary(plan, jobs, records, arm, cohorts):
    rows = [r for (cid, a), r in jobs.items() if a == arm and any(
        k['case_id'] == cid and k['cohort'] in cohorts for k in plan['cases'])]
    puzzles = defaultdict(bool)
    for r in rows:
        puzzles[r['puzzle']] |= r['rescued']
    marks = plan.get('protocol_constants', {}).get('marks', [8192, 16384, 24576])
    nov = []
    stats = Counter()
    read_and_won = 0
    for r in rows:
        agents = records[(r['case_id'], arm)]
        nov += novelty(agents, marks)
        for a in agents:
            for n in a.get('notes') or []:
                stats['note_turns'] += 1
                stats[f"reply_{n['kind']}"] += 1
                stats['note_tokens'] += n.get('tokens') or 0
            for rd in a.get('reads') or []:
                stats['board_reads'] += 1
                stats['board_chars'] += rd.get('chars') or 0
            for s in a.get('submissions') or []:
                stats[f"submit_{s['where']}"] += 1
                stats[f"submit_{s['where']}_accepted"] += s.get('accepted') is True
                if s.get('won') and s.get('read_ids'):
                    read_and_won += 1
    return dict(cases=len(rows), rescued_cases=sum(r['rescued'] for r in rows),
                rescued_puzzles=sum(puzzles.values()), puzzles=len(puzzles),
                answered=sum(r['answered'] for r in rows), wrong=sum(r['wrong'] for r in rows),
                accepted_agents=sum(r['accepted_agents'] for r in rows),
                generated_tokens=sum(r['generated_tokens'] for r in rows),
                wall_s=sum(r['wall_s'] for r in rows), checkpoints=sum(r['checkpoints'] for r in rows),
                segments_measured=len(nov), novelty=float(sum(nov) / len(nov)) if nov else None,
                novelty_exact=str(sum(nov) / len(nov)) if nov else None,
                winners_by_where=dict(Counter(r['winner_where'] for r in rows if r['answered'])),
                winners_who_had_read_an_entry=read_and_won, **stats), dict(puzzles), nov


def s1_decision(plan, jobs, records, cohorts):
    base = "D'"
    protocol_arms = [a for a in plan['arm_order'] if plan['arms'][a].get('protocol')]
    out, puzzle_sets = {}, {}
    for arm in plan['arm_order']:
        out[arm], puzzle_sets[arm], _ = arm_summary(plan, jobs, records, arm, cohorts)
    pooled = 'extension' in cohorts
    need = 6 if pooled else 4
    verdicts = {}
    for arm in protocol_arms:
        c, d = out[arm], out[base]
        cn = Fraction(c['novelty_exact']) if c['novelty_exact'] else None
        dn = Fraction(d['novelty_exact']) if d['novelty_exact'] else None
        diff = c['rescued_puzzles'] - d['rescued_puzzles']
        rules = dict(zero_wrong=c['wrong'] == 0, rescued_lead=diff >= need,
                     accepted_agents=c['accepted_agents'] >= d['accepted_agents'],
                     novelty=cn is not None and dn is not None and cn >= dn - NOVELTY_MARGIN)
        common = sorted(set(puzzle_sets[arm]) & set(puzzle_sets[base]))
        wins = sum(puzzle_sets[arm][p] and not puzzle_sets[base][p] for p in common)
        losses = sum(puzzle_sets[base][p] and not puzzle_sets[arm][p] for p in common)
        if all(rules.values()):
            verdict = 'PASS'
        elif not pooled and diff in (2, 3) and rules['zero_wrong'] and rules['accepted_agents'] and rules['novelty']:
            verdict = 'GREY: run the extension cohort'
        else:
            verdict = 'STOP'
        verdicts[arm] = dict(rules=rules, rescued_lead=diff, required_lead=need, verdict=verdict,
                             paired_puzzles=dict(protocol_only=wins, plain_only=losses,
                                                 sign_test_p=sign_test(wins, losses)))
    overall = ('PASS' if any(v['verdict'] == 'PASS' for v in verdicts.values()) else
               'GREY' if any(v['verdict'].startswith('GREY') for v in verdicts.values()) else 'STOP')
    return dict(arms=out, verdicts=verdicts, overall=overall, pooled=pooled)


# ---------------------------------------------------------------- s0

def equation_ok(m):
    a, op, b, c = float(m.group(1)), m.group(2), float(m.group(3)), float(m.group(4))
    value = {'+': a + b, '-': a - b, '*': a * b, 'x': a * b, '×': a * b,
             '/': a / b if b else None, '÷': a / b if b else None}[op]
    return value is not None and abs(value - c) < 1e-9


def s0_checks(plan, jobs, summary):
    recs = list(jobs.values())
    notes = [r['note'] for r in recs if r.get('note')]
    values = {}
    prefix = [bool(r.get('prefix_identical')) and (r.get('accepted') or bool(r.get('continuation_prefix_identical')))
              for r in recs]
    values['prefix_identical'] = Fraction(sum(prefix), len(prefix)) if prefix else None
    board = ((summary or {}).get('phases') or {}).get('board', {}).get('total')
    values['cached_share'] = (1 - Fraction(round(board['prefill_compute_tokens']), round(board['prompt_tokens']))
                              if board and board.get('prompt_tokens') else None)
    lat = [r['note']['ttft_s'] + r['continuation']['ttft_s'] for r in recs
           if r.get('note') and r.get('continuation') and r['note'].get('ttft_s') is not None
           and r['continuation'].get('ttft_s') is not None]
    values['checkpoint_latency'] = statistics.median(lat) if lat else None
    parsed = [n for n in notes if n['kind'] in ('note', 'answer')]
    values['reply_parse'] = Fraction(len(parsed), len(notes)) if notes else None
    real = [n for n in notes if n['kind'] == 'note']
    values['note_within_256'] = Fraction(sum(n['tokens'] <= 256 for n in real), len(real)) if real else None
    sentences = [s for r in recs if r['family'] == 'arith' and r.get('note') and r['note']['kind'] == 'note'
                 for s in r['note']['note']['results']]
    with_eq = [s for s in sentences if EQUATION.search(s)]
    ok = [s for s in sentences if all(equation_ok(m) for m in EQUATION.finditer(s))]
    values['arith_results_correct'] = Fraction(len(ok), len(sentences)) if sentences else None
    pairs = []
    by_group = defaultdict(list)
    for r in recs:
        if r.get('note') and r['note']['kind'] == 'note' and r['note']['note']['focus']:
            by_group[r['group_id']].append(set(WORD.findall(r['note']['note']['focus'].lower())))
    for focuses in by_group.values():
        for i in range(len(focuses)):
            for j in range(i + 1, len(focuses)):
                union = focuses[i] | focuses[j]
                pairs.append(Fraction(len(focuses[i] & focuses[j]), len(union)) < Fraction(6, 10) if union else False)
    values['focus_distinct'] = Fraction(sum(pairs), len(pairs)) if pairs else None
    conts = [r['continuation'] for r in recs if r.get('continuation')]
    at_once = plan.get('answer_at_once_tokens', 512)
    early = [c['closed'] and (c.get('closed_at_token') is None or c['closed_at_token'] < at_once) for c in conts]
    values['answer_at_once'] = Fraction(sum(early), len(early)) if early else None
    reps, recorded = [], []
    for r in recs:
        c = r.get('continuation')
        if not c:
            continue
        own = grams(r.get('prefix_text'))
        mine, base = grams(c.get('thinking_text')), grams(r.get('recorded_continuation_text'))
        if mine and base:
            reps.append(Fraction(len(mine & own), len(mine)))
            recorded.append(Fraction(len(base & own), len(base)))
    values['own_repeat'] = (sum(reps) / len(reps) - sum(recorded) / len(recorded)) if reps else None
    limits = dict(prefix_identical=lambda v: v == 1, cached_share=lambda v: v >= Fraction(95, 100),
                  checkpoint_latency=lambda v: v <= 5.0, reply_parse=lambda v: v >= Fraction(9, 10),
                  note_within_256=lambda v: v >= Fraction(9, 10), arith_results_correct=lambda v: v >= Fraction(9, 10),
                  focus_distinct=lambda v: v >= Fraction(3, 4), answer_at_once=lambda v: v <= Fraction(1, 5),
                  own_repeat=lambda v: v <= Fraction(1, 10))
    checks = []
    for spec in plan['checks']:
        v = values.get(spec['id'])
        met = v is not None and limits[spec['id']](v)
        checks.append(dict(spec, value=float(v) if v is not None else None, exact=str(v) if v is not None else None,
                           met=met))
    extra = dict(note_turns=len(notes), reply_kinds=dict(Counter(n['kind'] for n in notes)),
                 result_sentences=len(sentences), result_sentences_with_equation=len(with_eq),
                 focus_pairs=len(pairs), continuations=len(conts), latency_samples=len(lat),
                 checkpoint_latency_p90=sorted(lat)[int(0.9 * (len(lat) - 1))] if lat else None,
                 note_call_latency_median=statistics.median([n['latency_s'] for n in notes]) if notes else None,
                 recorded_own_repeat=float(sum(recorded) / len(recorded)) if recorded else None,
                 replay_own_repeat=float(sum(reps) / len(reps)) if reps else None,
                 answers_at_checkpoint=sum(1 for r in recs for s in r.get('submissions') or []),
                 answers_accepted=sum(1 for r in recs for s in r.get('submissions') or [] if s.get('accepted') is True),
                 answers_accepted_wrong=sum(1 for r in recs for s in r.get('submissions') or []
                                            if s.get('accepted') is True and not s.get('verifier_solved')))
    failed = [c for c in checks if not c['met']]
    verdict = ('PASS' if not failed else
               'STOP' if any(c['on_fail'].startswith('stop') for c in failed) else 'FIX')
    return dict(checks=checks, verdict=verdict, failed=[c['id'] for c in failed], **extra)


# ---------------------------------------------------------------- build and write

def build(plan, run_dirs):
    jobs, records, problems = load(plan, run_dirs)
    out = dict(study=plan['study'], screen=plan['screen'], runs=[str(d) for d in run_dirs])
    if plan['screen'] == 's1':
        cohorts = {'primary'} | ({'extension'} if any(
            k[0] in {c['case_id'] for c in plan['cases'] if c['cohort'] == 'extension'} for k in jobs) else set())
        problems += completeness(plan, jobs, cohorts)
        out['cohorts'] = sorted(cohorts)
        if problems:
            out.update(status='incomplete', problems=problems, decision=f"incomplete - {' | '.join(problems)}")
            return out
        out.update(status='complete', **s1_decision(plan, jobs, records, cohorts))
        out['decision'] = out['overall']
    else:
        problems += completeness(plan, jobs, {'primary'})
        summaries = [json.loads((Path(d) / 'summary.json').read_text()) for d in run_dirs
                     if (Path(d) / 'summary.json').exists()]
        if problems:
            out.update(status='incomplete', problems=problems, decision=f"incomplete - {' | '.join(problems)}")
            return out
        out.update(status='complete', **s0_checks(plan, jobs, summaries[-1] if summaries else None))
        out['decision'] = out['verdict']
        if len(run_dirs) > 1:
            out['note'] = 'cached share from the last output directory only'
    return out


def markdown(r):
    lines = [f"# {r['study']} ({r['screen']})", '', f"Decision: **{r['decision']}**", '']
    if r['status'] != 'complete':
        return '\n'.join(lines + ['Problems:'] + [f'- {p}' for p in r['problems']]) + '\n'
    if r['screen'] == 's0':
        lines += ['| check | value | limit | met | on fail |', '|---|---:|---|---|---|']
        for c in r['checks']:
            lines.append(f"| {c['id']} | {c['value']} | {c['limit']} | {c['met']} | {c['on_fail']} |")
        return '\n'.join(lines) + '\n'
    keys = ['cases', 'rescued_puzzles', 'puzzles', 'answered', 'wrong', 'accepted_agents', 'generated_tokens',
            'novelty', 'segments_measured', 'checkpoints', 'note_turns', 'reply_note', 'reply_answer', 'note_tokens',
            'board_reads', 'winners_who_had_read_an_entry']
    lines += ['| arm | ' + ' | '.join(keys) + ' |', '|---|' + '---:|' * len(keys)]
    for arm, s in r['arms'].items():
        lines.append(f'| {arm} | ' + ' | '.join(str(s.get(k, 0)) for k in keys) + ' |')
    lines.append('')
    for arm, v in r['verdicts'].items():
        lines.append(f"- {arm}: {v['verdict']} (lead {v['rescued_lead']}, needed {v['required_lead']}; rules "
                     f"{v['rules']}; paired puzzles {v['paired_puzzles']})")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--runs', type=Path, nargs='+', required=True)
    p.add_argument('--out', type=Path)
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    report = build(plan, a.runs)
    out = a.out or ROOT / 'results' / plan['study']
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str) + '\n')
    (out / 'REPORT.md').write_text(markdown(report))
    print(json.dumps(dict(study=plan['study'], decision=report['decision'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
