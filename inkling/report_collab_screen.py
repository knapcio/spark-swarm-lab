#!/usr/bin/env python3
"""Report for the live-collaboration replay screens S0 and S1 (DESIGN-live-collab-fable.md 4.1, 4.2; plans from
inkling/collab_plans.py, runs from collab_replay.py on research/collab-v1). Writes results/<study>/{report.json,
REPORT.md}.

Validation (complete inputs only; anything else is "incomplete", no decision):
- every output directory embeds a plan equal to the plan file and records no bypass (collab_replay --no-source-check);
- S1: every planned job (case x arm of the cohorts present) is complete AS A UNIT: a complete case row and exactly
  one complete agent record per planned slot. Several output directories (a rerun of incomplete jobs with --jobs)
  merge per job: a later directory may only complete a job that was missing, not started or incomplete; a job complete
  in two directories is a validation problem;
- S0: exactly one output directory (its phase counters belong to one intact attempt), every checkpoint complete;
- torn JSONL lines are skipped and listed; they leave their job incomplete.
All gate quantities are unrounded (exact fractions where they are ratios).

Also: JSONL is decoded line by line (a torn or non-UTF-8 line is skipped and listed); every run must have used the
plan's per_node; S0 rows must be unique per checkpoint; wrong acceptances recorded in a replaced (incomplete) S1 attempt
still count for its job.

S1 (frozen in the plan, per protocol arm C against the shared control D'): 1. wrong(C) == 0 over all attempts;
2. rescued puzzles(C) >= rescued(D') + primary_margin; 3. accepted agents(C) >= accepted agents(D'); 4. novelty(C) >=
novelty(D') - 0.02. PASS if all hold; GREY (run the extension cohort) if the lead is inside grey_band with 1, 3, 4 met;
else STOP. The primary look always comes from the validated primary jobs; with the extension cohort present the
pooled look applies only to arms that were GREY at the primary look (per puzzle, rescued if any of its cases is;
lead >= pooled_margin; rules 1, 3, 4 on the pooled cases); a primary PASS stays a PASS. Margins and their
calibration (familywise false pass <= 10 % for two arms and both looks) are the plan's decision_rule.margins.
Novelty: pieces of post-cut thinking at the common thinking-token boundaries (8,192 / 16,384 / 24,576 / 30,720),
mapped to text and time with the streamed progress samples (time, tokens, characters every 128 tokens); cancelled
partial streams count with their streamed text; a piece counts if it has >= MIN_GRAMS distinct word 5-grams; its
novelty is the share of them absent from every text another agent of the case had written when the piece started
(recorded prefixes, thinking by time, notes by time); arm novelty = mean over counted pieces (token-weighted also
reported).

S0: the plan's checks; PASS if all hold, else the failed checks' actions (STOP if any says stop, else FIX).
Arithmetic statements are checked with exact_claims.py (whole expressions with precedence, parentheses and powers,
chained equalities, exact rationals), the SAME implementation as the workers' pre-posting verifier: the plan pins its
sha256 (exact_claims_sha256) and the report refuses a plan or a worker revision whose copy differs. Facts-only notes
(collab-s0-v2): arith_results_correct is over the POSTED statements of arithmetic checkpoints that contain at least one
evaluable equation; unparseable ones are reported apart. Old-format notes (collab-s0-v1): over the result sentences.
A dev plan (plan.dev, a 2-node development fleet) gets the checks computed but never a decision.

usage: report_collab_screen.py --plan PLAN --runs DIR [DIR ...] [--out DIR]
"""
import argparse
import bisect
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import exact_claims  # noqa: E402
from report_round3_hard17 import sign_test  # noqa: E402

NGRAM = 5
MIN_GRAMS = 20
NOVELTY_MARGIN = Fraction(2, 100)
BOUNDARIES = (8192, 16384, 24576, 30720)
WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def read_jsonl(path, torn):
    """Rows of a JSONL file, decoded line by line: a line that is not valid UTF-8 or not JSON is skipped and listed
    in `torn` (it never aborts the load)."""
    path = Path(path)
    rows = []
    if not path.exists():
        return rows
    for i, raw in enumerate(path.read_bytes().split(b'\n')):
        if not raw.strip():
            continue
        try:
            rows.append(json.loads(raw.decode('utf-8')))
        except (UnicodeDecodeError, ValueError):
            torn.append(f'{path}:{i + 1}')
    return rows


def grams(text, n=NGRAM):
    words = WORD.findall((text or '').lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


# ---------------------------------------------------------------- loading and validation

def read_dir(plan, d, problems, torn):
    d = Path(d)
    meta_path = d / 'metadata.json'
    if not meta_path.exists():
        problems.append(f'{d}: no metadata.json')
        return None
    meta = json.loads(meta_path.read_text())
    if meta.get('plan') != plan:
        problems.append(f'{d}: embedded plan differs from the plan file')
        return None
    if [b for b in meta.get('bypass') or [] if not (b == 'dev' and plan.get('dev'))]:
        problems.append(f"{d}: run bypassed the freeze checks ({', '.join(meta['bypass'])})")
        return None
    summary = json.loads((d / 'summary.json').read_text()) if (d / 'summary.json').exists() else None
    if not summary or summary.get('drain_confirmed') is not True:
        problems.append(f'{d}: the end-of-run drain was not confirmed (drain_confirmed is not true)')
    return dict(meta=meta, records=read_jsonl(d / 'records.jsonl', torn), rows=read_jsonl(d / 'cases.jsonl', torn),
                summary=summary)


def s1_unit(plan, case, arm, row, records):
    """None if the job (row + its agent records) is complete as a unit, else the reason."""
    if row.get('status') != 'complete':
        return f"status {row.get('status')}"
    slots = sorted(m['slot'] for m in case['agents'])
    mine = [r for r in records if r.get('case_id') == case['case_id'] and r.get('arm') == arm]
    if sorted(r.get('slot') for r in mine) != slots:
        return f'agent records {sorted(r.get("slot") for r in mine)} != slots {slots}'
    if any(r.get('status') != 'complete' for r in mine):
        return 'an agent record is not complete'
    return None


def wrong_acceptances(d, row, records):
    """Identities of the wrong acceptances one attempt recorded: every accepted submission the exact verifier rejects in
    its surviving agent records, and, if the attempt's case row counts more (records lost), the row's surplus."""
    ids = {(str(d), r.get('slot'), i) for r in records for i, sub in enumerate(r.get('submissions') or [])
           if sub.get('accepted') is True and not sub.get('verifier_solved')}
    counted = int((row or {}).get('wrong') or 0)
    ids |= {(str(d), 'row', i) for i in range(len(ids), counted)}
    return ids


def load_s1(plan, run_dirs, cohorts):
    """Jobs complete as units (any directory order; a job complete twice is a problem) and, independently, the wrong
    acceptances of EVERY attempt: all directories' rows and surviving agent records count, whichever attempt is
    selected and whether or not the attempt has a case row."""
    problems, torn, attempts, wrongs = [], [], {}, {}
    cases = {k['case_id']: k for k in plan['cases']}
    for d in run_dirs:
        got = read_dir(plan, d, problems, torn)
        if got is None:
            continue
        by_job = {}
        for r in got['records']:
            by_job.setdefault((r.get('case_id'), r.get('arm')), []).append(r)
        rows = {(row.get('case_id'), row.get('arm')): row for row in got['rows']}
        for key in set(rows) | set(by_job):
            if key[0] not in cases:
                problems.append(f'{d}: unplanned job {key}')
                continue
            wrongs.setdefault(key, set()).update(wrong_acceptances(d, rows.get(key), by_job.get(key, [])))
            if key in rows:
                why = s1_unit(plan, cases[key[0]], key[1], rows[key], got['records'])
                attempts.setdefault(key, []).append((why, rows[key], by_job.get(key, [])))
    jobs, records = {}, {}
    for key, tries in attempts.items():
        complete = [t for t in tries if t[0] is None]
        if len(complete) > 1:
            problems.append(f'job {key} complete in two output directories')
        chosen = complete[0] if complete else tries[-1]
        jobs[key] = chosen
        records[key] = chosen[2]
    want = {(k['case_id'], arm) for k in plan['cases'] if k['cohort'] in cohorts for arm in plan['arm_order']}
    missing = sorted(want - set(jobs))
    bad = sorted((k, jobs[k][0]) for k in want & set(jobs) if jobs[k][0] is not None)
    if missing:
        problems.append(f'{len(missing)} planned jobs missing, e.g. {missing[0]}')
    if bad:
        problems.append(f'{len(bad)} jobs not complete as a unit, e.g. {bad[0]}')
    final = {}
    for k, v in jobs.items():
        if k in want:
            mine = wrong_acceptances('selected', v[1], v[2])
            total = len(wrongs.get(k, set()))
            final[k] = dict(v[1], wrong=total, wrong_in_other_attempts=total - len(mine))
    return final, records, problems, torn


# ---------------------------------------------------------------- novelty (s1)

def char_at(seg, token):
    """Characters of a segment's text written after `token` of its tokens (progress samples, linear within one)."""
    prog = [(0, 0)] + [(tk, ch) for _, tk, ch in seg.get('progress') or []]
    if len(prog) == 1:
        prog.append((seg['tokens'], len(seg.get('text') or '')))
    tks = [p[0] for p in prog]
    i = bisect.bisect_right(tks, token) - 1
    if i >= len(prog) - 1:
        return min(prog[-1][1], len(seg.get('text') or ''))
    (t0, c0), (t1, c1) = prog[i], prog[i + 1]
    return min(len(seg.get('text') or ''), round(c0 + (c1 - c0) * (token - t0) / max(1, t1 - t0)))


def time_at(seg, token):
    prog = [(seg.get('t_first') or seg['t0'], 0)] + [(t, tk) for t, tk, _ in seg.get('progress') or []]
    if len(prog) == 1:
        prog.append((seg['t1'], seg['tokens']))
    tks = [p[1] for p in prog]
    i = bisect.bisect_right(tks, token) - 1
    if i >= len(prog) - 1:
        return prog[-1][0]
    (a, ta), (b, tb) = prog[i], prog[i + 1]
    return a + (b - a) * (token - ta) / max(1, tb - ta)


def pieces(seg):
    """The thinking of a segment split at the common thinking-token boundaries: (bin, text, start time, tokens) per
    piece. Only thinking counts (thinking_tokens; a cancelled or closed segment without a located end of thinking
    keeps its streamed thinking text as one piece)."""
    start = seg['think_before']
    think = seg.get('thinking_tokens')
    text = seg.get('text') or ''
    if think is None:
        return [dict(bin=bin_of(start), text=text, t_start=seg.get('t_first') or seg['t0'], tokens=0)]
    cuts = [b - start for b in BOUNDARIES if start < b < start + think]
    bounds = [0] + cuts + [think]
    return [dict(bin=bin_of(start + a), text=text[char_at(seg, a):char_at(seg, b)], t_start=time_at(seg, a),
                 tokens=b - a) for a, b in zip(bounds, bounds[1:]) if b > a]


def bin_of(token):
    """Index of the common thinking-token bin [BOUNDARIES[i], BOUNDARIES[i + 1]) holding `token`."""
    return max(0, bisect.bisect_right(BOUNDARIES, token) - 1)


def chars_by(seg, t):
    """Characters of a segment's text written by time t."""
    prog = [(seg.get('t_first') or seg['t0'], 0)] + [(tt, ch) for tt, _, ch in seg.get('progress') or []]
    if len(prog) == 1:
        prog.append((seg['t1'], len(seg.get('text') or '')))
    if t <= prog[0][0]:
        return 0
    for (a, ca), (b, cb) in zip(prog, prog[1:]):
        if t <= b:
            return round(ca + (cb - ca) * (t - a) / max(1e-9, b - a))
    return len(seg.get('text') or '')


def written_before(agent, t):
    parts = [agent.get('prefix_text') or '']
    for seg in agent.get('segments') or []:
        parts.append((seg.get('text') or '')[:chars_by(seg, t)])
    for note in agent.get('notes') or []:
        if note.get('t') is not None and note['t'] <= t:
            parts.append(note.get('text') or '')
    return '\n'.join(parts)


def novelty(agents):
    """(value, tokens) per counted bin of one case-arm. All thinking pieces of an agent in one common bin (split by
    rejection-driven request breaks) are combined before scoring: a distinct 5-gram of the bin is novel if, at the
    start of the piece where it first appears, no other agent of the case had written it; a bin counts if it has
    >= MIN_GRAMS distinct 5-grams."""
    out = []
    for a in agents:
        bins = defaultdict(list)
        for seg in a.get('segments') or []:
            for piece in pieces(seg):
                bins[piece['bin']].append(piece)
        for parts in bins.values():
            seen, novel, tokens = set(), 0, 0
            for piece in sorted(parts, key=lambda q: q['t_start']):
                tokens += piece['tokens']
                new = grams(piece['text']) - seen
                if not new:
                    continue
                others = set()
                for b in agents:
                    if b is not a:
                        others |= grams(written_before(b, piece['t_start']))
                novel += len(new - others)
                seen |= new
            if len(seen) >= MIN_GRAMS:
                out.append((Fraction(novel, len(seen)), tokens))
    return out


def arm_summary(plan, jobs, records, arm):
    rows = [r for (cid, a), r in jobs.items() if a == arm]
    puzzles = defaultdict(bool)
    for r in rows:
        puzzles[r['puzzle']] |= r['rescued']
    nov, stats, read_and_won = [], Counter(), 0
    for r in rows:
        agents = records[(r['case_id'], arm)]
        nov += novelty(agents)
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
    mean = sum(v for v, _ in nov) / len(nov) if nov else None
    weighted = (sum(v * w for v, w in nov) / sum(w for _, w in nov)) if nov and sum(w for _, w in nov) else None
    return dict(cases=len(rows), rescued_cases=sum(r['rescued'] for r in rows), rescued_puzzles=sum(puzzles.values()),
                puzzles=len(puzzles), answered=sum(r['answered'] for r in rows), wrong=sum(r['wrong'] for r in rows),
                accepted_agents=sum(r['accepted_agents'] for r in rows),
                generated_tokens=sum(r['generated_tokens'] for r in rows),
                retry_tokens=sum(r.get('retry_tokens') or 0 for r in rows),
                cancelled_tokens=sum(r.get('cancelled_tokens') or 0 for r in rows),
                wall_s=sum(r['wall_s'] for r in rows), checkpoints=sum(r['checkpoints'] for r in rows),
                pieces_counted=len(nov), novelty=float(mean) if mean is not None else None,
                novelty_exact=str(mean) if mean is not None else None,
                novelty_token_weighted=float(weighted) if weighted is not None else None,
                winners_by_where=dict(Counter(r['winner_where'] for r in rows if r['answered'])),
                winners_who_had_read_an_entry=read_and_won, **stats), dict(puzzles)


def look(plan, jobs, records, pooled, eligible=None):
    """One look of the S1 gate. pooled: per-puzzle rescue over primary + extension cases, pooled_margin, and only arms
    in `eligible` (GREY at the primary look) can pass."""
    base = "D'"
    margins = plan['decision_rule']['margins']
    protocol_arms = [a for a in plan['arm_order'] if plan['arms'][a].get('protocol')]
    out, puzzle_sets = {}, {}
    for arm in plan['arm_order']:
        out[arm], puzzle_sets[arm] = arm_summary(plan, jobs, records, arm)
    need = margins['pooled_margin'] if pooled else margins['primary_margin']
    grey = margins['grey_band']
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
        if pooled and arm not in eligible:
            verdict = 'NOT ELIGIBLE at the pooled look (was not GREY at the primary look)'
        elif all(rules.values()):
            verdict = 'PASS'
        elif not pooled and grey[0] <= diff <= grey[1] and rules['zero_wrong'] and rules['accepted_agents'] \
                and rules['novelty']:
            verdict = 'GREY: run the extension cohort'
        else:
            verdict = 'STOP'
        verdicts[arm] = dict(rules=rules, rescued_lead=diff, required_lead=need, verdict=verdict,
                             paired_puzzles=dict(protocol_only=wins, plain_only=losses,
                                                 sign_test_p=sign_test(wins, losses)))
    return dict(arms=out, verdicts=verdicts, margins=margins)


def s1_decision(plan, jobs, records, pooled):
    """The primary look on the validated primary jobs; with the extension present, the pooled look for the arms that
    were GREY at the primary look. A primary PASS stays a PASS whatever the pooled look says."""
    primary_ids = {k['case_id'] for k in plan['cases'] if k['cohort'] == 'primary'}
    primary_jobs = {k: v for k, v in jobs.items() if k[0] in primary_ids}
    first = look(plan, primary_jobs, records, False)
    out = dict(primary=first, pooled=pooled)
    final = {arm: v['verdict'] for arm, v in first['verdicts'].items()}
    if pooled:
        grey = {arm for arm, v in first['verdicts'].items() if v['verdict'].startswith('GREY')}
        second = look(plan, jobs, records, True, grey)
        out['pooled_look'] = second
        for arm in grey:
            final[arm] = 'PASS (pooled)' if second['verdicts'][arm]['verdict'] == 'PASS' else 'STOP'
    passing = [arm for arm, v in final.items() if v.startswith('PASS')]
    out.update(final_verdicts=final, passing_arms=passing,
               overall='PASS' if passing else 'GREY' if any(v.startswith('GREY') for v in final.values()) else 'STOP')
    # flat views for the markdown and older readers
    shown = out.get('pooled_look') or first
    out.update(arms=shown['arms'], verdicts=shown['verdicts'], margins=first['margins'])
    return out


# ---------------------------------------------------------------- s0

def statements(rec):
    """(text, tag) of the arithmetic-relevant statements of one checkpoint's note: the POSTED statements of a
    facts-only note (tag VERIFIED / agent-checked / UNVERIFIED), else the result sentences of an old-format note."""
    note = rec.get('note') or {}
    if note.get('kind') != 'note':
        return []
    if 'claims' in note:
        return [(x['text'], x['tag']) for x in note['claims'] if x.get('tag') != 'drop']
    return [(x, None) for x in (note.get('note') or {}).get('results') or []]


def claim_counts(recs):
    """Statements made / dropped / UNVERIFIED / agent-checked / VERIFIED, checker tokens and latency (facts notes)."""
    claims = [x for r in recs for x in ((r.get('note') or {}).get('claims') or [])]
    checks = [v for r in recs for v in r.get('verifications') or []]
    lat = [v['t1'] - v['t0'] for v in checks if v.get('t1') is not None and v.get('t0') is not None]
    tags = Counter(x.get('tag') for x in claims)
    return dict(claims_made=len(claims), claims_dropped=tags.get('drop', 0),
                claims_unverified=tags.get('UNVERIFIED', 0), claims_agent_checked=tags.get('agent-checked', 0),
                claims_verified=tags.get('VERIFIED', 0),
                drops_by_reason=dict(Counter(x.get('mechanical') if x.get('tag') == 'drop' and 'checker' not in x
                                             else 'checker: ' + str((x.get('checker') or {}).get('verdict'))
                                             for x in claims if x.get('tag') == 'drop')),
                verifier_calls=len(checks), verifier_prompt_tokens=sum(v.get('prompt_tokens') or 0 for v in checks),
                verifier_completion_tokens=sum(v.get('completion_tokens') or 0 for v in checks),
                verifier_latency_median_s=statistics.median(lat) if lat else None,
                verifier_latency_p90_s=sorted(lat)[int(0.9 * (len(lat) - 1))] if lat else None)


def board_miss(recs, board):
    """Board-phase prefill per node split into the structurally new tokens (each continuation's appended board turn,
    read.appended_tokens; runs without it: reply + board turn, board_new_tokens) and the rest (recomputed cached
    prefix: eviction)."""
    out = {}
    for node, v in (board.get('per_node') or {}).items():
        if 'error' in v:
            continue
        mine = [r for r in recs if r.get('endpoint') == node and r.get('continuation')]
        turn = [((r.get('read') or {}).get('appended_tokens')) for r in mine]
        # the appended board turn is new text; the note reply was generated (and cached) by the note call
        new = sum(turn) if mine and all(isinstance(x, int) for x in turn) else sum(
            r.get('board_new_tokens') or 0 for r in mine)
        computed = v.get('prefill_compute_tokens') or 0
        prompt = v.get('prompt_tokens') or 0
        out[node] = dict(prompt_tokens=prompt, prefill_compute_tokens=computed, structural_new_tokens=new,
                         eviction_tokens=max(0, computed - new),
                         best_possible_share=float(1 - Fraction(round(new), round(prompt))) if prompt else None)
    return out


def ratio(a, b):
    return Fraction(a, b) if b else None


def s0_checks(plan, recs, summary):
    notes = [r['note'] for r in recs if r.get('note')]
    accepted = [r for r in recs if r.get('accepted')]
    values = {}
    prefix = [bool(r.get('prefix_identical')) and (r.get('accepted') or bool(r.get('continuation_prefix_identical')))
              for r in recs]
    values['prefix_identical'] = ratio(sum(prefix), len(prefix))
    joins = [j for r in recs for j in r.get('joins') or []]
    # the board-turn join of each continued checkpoint closes its note reply; finished replies keep their terminator
    stop_replies = [r['joins'][0] for r in recs if r.get('joins') and r.get('note')
                    and r['note'].get('finish_reason') == 'stop']
    pre = (summary or {}).get('preflight') or {}
    pre_ok = (len(pre) == plan.get('nodes', 4) and all(
        isinstance(fams, dict) and fams and all(r.get('ok') for r in fams.values()) for fams in pre.values()))
    values['turn_boundaries'] = (ratio(sum(j['terminated'] for j in stop_replies), len(stop_replies))
                                 if pre_ok and stop_replies else (Fraction(0) if not pre_ok else None))
    board = ((summary or {}).get('phases') or {}).get('board') or {}
    sent = Counter()
    for r in recs:
        if r.get('continuation'):
            sent[r.get('endpoint')] += int(r['continuation'].get('attempts') or 1)
    shares, reconciled = {}, {}
    for node, v in (board.get('per_node') or {}).items():
        ok = ('error' not in v and all(isinstance(v.get(k), (int, float)) and math.isfinite(v[k]) and v[k] >= 0
                                       for k in ('prompt_tokens', 'prefill_compute_tokens', 'requests'))
              and v['prompt_tokens'] > 0 and v['prefill_compute_tokens'] <= v['prompt_tokens'])
        reconciled[node] = bool(ok) and round(v['requests']) == sent.get(node, 0)
        shares[node] = (1 - Fraction(round(v['prefill_compute_tokens']), round(v['prompt_tokens']))
                        if reconciled[node] else None)
    values['cached_share'] = (min(shares.values()) if len(shares) == plan.get('nodes', 4)
                              and all(x is not None for x in shares.values()) else None)
    continued = [r for r in recs if r.get('continuation')]
    lat = [(r['note']['t_first'] - r['note']['t0']) + (r['continuation']['t_first'] - r['continuation']['t0'])
           for r in continued if r.get('note') and r['note'].get('t_first') is not None
           and r['continuation'].get('t_first') is not None]
    values['checkpoint_latency'] = statistics.median(lat) if lat and len(lat) == len(continued) else None
    parsed = [n for n in notes if n['kind'] in ('note', 'answer')]
    values['reply_parse'] = ratio(len(parsed), len(notes))
    real = [n for n in notes if n['kind'] == 'note']
    values['note_within_256'] = ratio(sum(n['tokens'] <= 256 for n in real), len(real))
    sentences = [t for r in recs if r['family'] == 'arith' for t, _ in statements(r)]
    status = [exact_claims.check_claim(t)[0] for t in sentences]
    checkable = [x for x in status if x in (exact_claims.TRUE, exact_claims.FALSE)]
    values['arith_results_correct'] = ratio(sum(x == exact_claims.TRUE for x in checkable), len(checkable))
    pairs, by_group = [], defaultdict(list)
    for r in recs:
        if r.get('note') and r['note']['kind'] == 'note' and r['note']['note']['focus']:
            by_group[r['group_id']].append(set(WORD.findall(r['note']['note']['focus'].lower())))
    for focuses in by_group.values():
        for i in range(len(focuses)):
            for j in range(i + 1, len(focuses)):
                union = focuses[i] | focuses[j]
                pairs.append(bool(union) and Fraction(len(focuses[i] & focuses[j]), len(union)) < Fraction(6, 10))
    values['focus_distinct'] = ratio(sum(pairs), len(pairs))
    conts = [r['continuation'] for r in recs if r.get('continuation')]
    expected_conts = len(recs) - len(accepted)
    closes = [cn for cn in conts if cn['closed']]
    located = [cn for cn in closes if cn.get('closed_at_token') is not None]
    measured = [cn for cn in conts if not cn['closed']] + located
    at_once = plan.get('answer_at_once_tokens', 512)
    coverage_ok = (len(conts) == expected_conts and len(conts) > 0
                   and (not closes or len(located) >= Fraction(9, 10) * len(closes)))
    values['answer_at_once'] = (ratio(sum(cn['closed'] and cn['closed_at_token'] < at_once for cn in measured),
                                      len(measured)) if coverage_ok else None)
    reps, recorded = [], []
    for r in recs:
        cn = r.get('continuation')
        if not cn:
            continue
        own = grams(r.get('prefix_text'))
        mine, base = grams(cn.get('thinking_text')), grams(r.get('recorded_continuation_text'))
        if mine and base:
            reps.append(Fraction(len(mine & own), len(mine)))
            recorded.append(Fraction(len(base & own), len(base)))
    values['own_repeat'] = (sum(reps) / len(reps) - sum(recorded) / len(recorded)) if reps else None
    limits = dict(prefix_identical=lambda v: v == 1, turn_boundaries=lambda v: v == 1,
                  cached_share=lambda v: v >= Fraction(95, 100), checkpoint_latency=lambda v: v <= 5.0,
                  reply_parse=lambda v: v >= Fraction(9, 10), note_within_256=lambda v: v >= Fraction(9, 10),
                  arith_results_correct=lambda v: v >= Fraction(9, 10), focus_distinct=lambda v: v >= Fraction(3, 4),
                  answer_at_once=lambda v: v <= Fraction(1, 5), own_repeat=lambda v: v <= Fraction(1, 10))
    checks = []
    for spec in plan['checks']:
        v = values.get(spec['id'])
        met = v is not None and limits[spec['id']](v)
        checks.append(dict(spec, value=float(v) if v is not None else None, exact=str(v) if v is not None else None,
                           met=met))
    by_family = {}
    for fam in sorted({r['family'] for r in recs}):
        mine = [r for r in recs if r['family'] == fam]
        fn = [r['note'] for r in mine if r.get('note')]
        by_family[fam] = dict(checkpoints=len(mine), singleton_groups=sum(1 for r in mine if r.get('group_size') == 1),
                              reply_kinds=dict(Counter(n['kind'] for n in fn)),
                              note_tokens_median=statistics.median([n['tokens'] for n in fn]) if fn else None)
    extra = dict(note_turns=len(notes), reply_kinds=dict(Counter(n['kind'] for n in notes)), by_family=by_family,
                 accepted_at_checkpoint_no_continuation=len(accepted), continuations=len(conts),
                 continuations_expected=expected_conts, closes=len(closes), closes_located=len(located),
                 board_requests_sent=dict(sent), board_counters_reconciled=reconciled,
                 result_sentences=len(sentences), result_sentences_checkable=len(checkable),
                 result_sentences_false=sum(x == exact_claims.FALSE for x in status),
                 result_sentences_unsupported=sum(x == exact_claims.UNPARSEABLE for x in status),
                 claims=claim_counts(recs), board_miss_by_node=board_miss(recs, board),
                 note_tokens_max=max((n['tokens'] for n in real), default=None),
                 note_finish_length=sum(n.get('finish_reason') == 'length' for n in notes), focus_pairs=len(pairs),
                 cached_share_by_node={k: (float(v) if v is not None else None) for k, v in shares.items()},
                 board_phase_peak_per_node=board.get('peak_per_node'), joins=len(joins),
                 latency_samples=len(lat), checkpoint_latency_p90=sorted(lat)[int(0.9 * (len(lat) - 1))] if lat else None,
                 recorded_own_repeat=float(sum(recorded) / len(recorded)) if recorded else None,
                 replay_own_repeat=float(sum(reps) / len(reps)) if reps else None,
                 answers_at_checkpoint=sum(1 for r in recs for s in r.get('submissions') or []),
                 answers_accepted=sum(1 for r in recs for s in r.get('submissions') or [] if s.get('accepted') is True),
                 answers_accepted_wrong=sum(1 for r in recs for s in r.get('submissions') or []
                                            if s.get('accepted') is True and not s.get('verifier_solved')),
                 proxies=['checkpoint_latency (sum of two first-token times)',
                          'own_repeat (recorded texts split by character share)'])
    failed = [c for c in checks if not c['met']]
    verdict = ('PASS' if not failed else
               'STOP' if any(c['on_fail'].startswith('stop') for c in failed) else 'FIX')
    return dict(checks=checks, verdict=verdict, failed=[c['id'] for c in failed], **extra)


# ---------------------------------------------------------------- build and write

def build(plan, run_dirs):
    out = dict(study=plan['study'], screen=plan['screen'], runs=[str(d) for d in run_dirs])
    if plan['screen'] == 's1':
        extension_ids = {c['case_id'] for c in plan['cases'] if c['cohort'] == 'extension'}
        present = set()
        for d in run_dirs:
            meta = Path(d) / 'metadata.json'
            if meta.exists() and json.loads(meta.read_text()).get('cohort') == 'extension':
                present.add('extension')
        cohorts = {'primary'} | present
        jobs, records, problems, torn = load_s1(plan, run_dirs, cohorts)
        out.update(cohorts=sorted(cohorts), torn_lines=torn)
        problems += load_problems(plan, run_dirs)
        if problems:
            out.update(status='incomplete', problems=problems, decision=f"incomplete - {' | '.join(problems)}")
            return out
        out.update(status='complete', **s1_decision(plan, jobs, records, 'extension' in cohorts))
        out['decision'] = out['overall']
        return out
    problems, torn = [], []
    if len(run_dirs) != 1:
        problems.append('S0 needs exactly one output directory (one intact attempt)')
    got = read_dir(plan, run_dirs[0], problems, torn) if run_dirs else None
    recs = got['records'] if got else []
    want = {(g['group_id'], m['slot']) for g in plan['groups'] for m in plan_members(g)}
    keys = Counter((r.get('group_id'), r.get('slot')) for r in recs)
    dup = sorted(k for k, n in keys.items() if n > 1)
    if dup:
        problems.append(f'{len(dup)} checkpoints recorded more than once, e.g. {dup[0]}')
    have = {(r.get('group_id'), r.get('slot')): r for r in recs}
    problems += load_problems(plan, run_dirs[:1])
    if got is not None:
        if set(have) != want:
            problems.append(f'{len(want - set(have))} planned checkpoints missing')
        bad = [k for k, r in have.items() if r.get('status') != 'complete']
        if bad:
            problems.append(f'{len(bad)} checkpoints not complete, e.g. {bad[0]}')
        if got['summary'] is None or got['summary'].get('aborted'):
            problems.append('S0 run has no summary or was aborted' + (
                f": {got['summary']['aborted']}" if got['summary'] and got['summary'].get('aborted') else ''))
    out['torn_lines'] = torn
    pin = plan.get('exact_claims_sha256')
    if pin and pin != exact_claims_sha256():
        problems.append('this report\'s exact_claims.py differs from the plan pin')
    if pin and worker_exact_claims_sha256(plan.get('source_revision')) != pin:
        problems.append('the worker revision\'s exact_claims.py differs from the plan pin (not one implementation)')
    if problems:
        out.update(status='incomplete', problems=problems, decision=f"incomplete - {' | '.join(problems)}")
        return out
    out.update(status='complete', **s0_checks(plan, recs, got['summary']))
    out['decision'] = out['verdict']
    if plan.get('dev'):
        out.update(status='dev', decision=f"DEV RUN, not for decisions (checks: {out['verdict']})")
    return out


def worker_exact_claims_sha256(revision, repo=ROOT):
    """sha256 of exact_claims.py at the plan's worker revision (same repository); None if unreadable."""
    import hashlib
    import subprocess
    try:
        blob = subprocess.run(['git', '-C', str(repo), 'show', f'{revision}:exact_claims.py'], capture_output=True,
                              check=True).stdout
    except (subprocess.CalledProcessError, OSError, TypeError):
        return None
    return hashlib.sha256(blob).hexdigest()


def exact_claims_sha256():
    import hashlib
    return hashlib.sha256((HERE / 'exact_claims.py').read_bytes()).hexdigest()


def load_problems(plan, run_dirs):
    """The frozen load: every run used the plan's per_node."""
    out = []
    for d in run_dirs:
        meta = Path(d) / 'metadata.json'
        if meta.exists():
            used = json.loads(meta.read_text()).get('per_node')
            if used != plan.get('per_node'):
                out.append(f'{d}: per_node {used} != frozen {plan.get("per_node")}')
    return out


def plan_members(group):
    return group['members']


def markdown(r):
    lines = [f"# {r['study']} ({r['screen']})", '', f"Decision: **{r['decision']}**", '']
    if r['status'] not in ('complete', 'dev'):
        return '\n'.join(lines + ['Problems:'] + [f'- {p}' for p in r['problems']]) + '\n'
    if r['screen'] == 's0':
        lines += ['| check | value | limit | met | on fail |', '|---|---:|---|---|---|']
        for c in r['checks']:
            lines.append(f"| {c['id']} | {c['value']} | {c['limit']} | {c['met']} | {c['on_fail']} |")
        lines += ['', f"Proxies: {', '.join(r['proxies'])}", f"By family: {json.dumps(r['by_family'])}",
                  f"Statements: {json.dumps(r.get('claims'))}",
                  f"Arithmetic statements: {r.get('result_sentences')} made, {r.get('result_sentences_checkable')} "
                  f"evaluable, {r.get('result_sentences_false')} false, {r.get('result_sentences_unsupported')} "
                  f"not parseable",
                  f"Board-phase prefill by node: {json.dumps(r.get('board_miss_by_node'))}"]
        return '\n'.join(lines) + '\n'
    keys = ['cases', 'rescued_puzzles', 'puzzles', 'answered', 'wrong', 'accepted_agents', 'generated_tokens',
            'retry_tokens', 'cancelled_tokens', 'novelty', 'novelty_token_weighted', 'pieces_counted', 'checkpoints',
            'note_turns', 'reply_note', 'reply_answer', 'note_tokens', 'board_reads', 'winners_who_had_read_an_entry']
    lines += ['| arm | ' + ' | '.join(keys) + ' |', '|---|' + '---:|' * len(keys)]
    for arm, s in r['arms'].items():
        lines.append(f'| {arm} | ' + ' | '.join(str(s.get(k, 0)) for k in keys) + ' |')
    lines.append('')
    for arm, v in r['verdicts'].items():
        lines.append(f"- {arm}: {v['verdict']} (lead {v['rescued_lead']}, needed {v['required_lead']}; rules "
                     f"{v['rules']}; paired puzzles {v['paired_puzzles']})")
    if r.get('final_verdicts'):
        lines += ['', 'Final verdicts (a primary PASS stays a PASS):'] + [
            f'- {arm}: **{v}**' + (f" (primary look: {r['primary']['verdicts'][arm]['verdict']})"
                                   if r.get('pooled') else '') for arm, v in r['final_verdicts'].items()]
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
