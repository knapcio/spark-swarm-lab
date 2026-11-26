#!/usr/bin/env python3
"""Frozen plans for the live-collaboration replay screens S0 and S1 (DESIGN-live-collab-fable.md, 4.1 and 4.2).

Reads recorded runs only (no model call, no host): writes a plan JSON that the replay driver collab_replay.py on the
collaboration worker source (research/collab-v1) executes, and that inkling/report_collab_screen.py evaluates with the
frozen rules embedded here. Commit and push the plan before any call.

S1 cohort (design 4.2, Fable's A6): recorded cases of the default-type arms swarm-generic-hard18-v1-roll12cancel (G),
swarm-relay-hard19-v1-roll12cancel (G), swarm-wide-hard20-v1-roll12cancel and -roll12wide, swarm-aot-hard21-v1-p-roll12wide
(P) in which all four first-wave agents (slots 0-3) finished their plan request with more than CUT (8,192) tokens, none
was cancelled and none was accepted. Per puzzle (corpus, task) the case with the lowest seed (ties: the arm listed
first) is 'primary' (41 cases); per puzzle the case with the lowest OTHER seed (ties: the arm listed first) is
'extension' (one distinct second seed per eligible puzzle: 29 cases; a puzzle whose other cases share the primary seed
in another policy has none); the remaining cohort cases are not planned. Every
planned stream is checked here: plan stage request_end present, token ids consistent with usage, still thinking at the
cut (no Inkling content-text token, id INKLING_CONTENT_TEXT from inkling/shim.py, in the first CUT ids), variant
xl_forced_original, no extra prompt text.

S0 sample (design 4.1): S0_CASES primary S1 cases drawn with random.Random(S0_SEED) (their four first-wave streams cut
at 8,192 and again at 16,384: 80 checkpoints) and 20 coding streams of coding-v29-r2-v1 and coding-aot-v1-p whose
code_propose request is longer than 16K tokens and still thinking at the coding cut, grouped by recorded case: cases
with more such streams first (at most 4 streams per case, lowest agent index first), then run order, task, seed, until
20 streams (100 checkpoints in all).

S0 v2 (collab-s0-v2, the amended rerun after collab-s0-v1 STOP; S0_AMENDMENTS): same sample, same checks and limits,
same 20 requests per node; facts-only notes with a pre-posting verifier, the note call capped at NOTE_MAX_TOKENS, the
appended board turn budgeted to BOARD_SHARE of the retained context, and each stream's warm-up and note back to back
under one permit in waves of WAVE_GROUPS groups. --dev writes a 2-node development plan (study suffix -dev, plan.dev)
that the report never uses for a decision.

usage: collab_plans.py s1 --source-revision REV --output COLLAB_S1_PLAN.json [--root DIR]
       collab_plans.py s0 --s1-plan COLLAB_S1_PLAN.json --source-revision REV --output COLLAB_S0_PLAN.json [--root DIR]
                       [--dev]
"""
import argparse
import functools
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CUT = 8192
S0_CUTS = (8192, 16384)
CODING_CUT = 8192
S0_CASES, S0_SEED, S0_CODING_STREAMS, S0_CODING_PER_CASE = 10, 2026112600, 20, 4
INKLING_CONTENT_TEXT = 200004  # inkling/shim.py CONTENT_TEXT: the model answers only after this token
S1_ARMS = ['swarm-generic-hard18-v1-roll12cancel', 'swarm-relay-hard19-v1-roll12cancel',
           'swarm-wide-hard20-v1-roll12cancel', 'swarm-wide-hard20-v1-roll12wide', 'swarm-aot-hard21-v1-p-roll12wide']
ARM_TAG = {'swarm-generic-hard18-v1-roll12cancel': 'h18g', 'swarm-relay-hard19-v1-roll12cancel': 'h19g',
           'swarm-wide-hard20-v1-roll12cancel': 'h20g', 'swarm-wide-hard20-v1-roll12wide': 'h20w',
           'swarm-aot-hard21-v1-p-roll12wide': 'h21p'}
CODING_RUNS = ['coding-v29-r2-v1', 'coding-aot-v1-p']
CODING_NAME = re.compile(r'(?P<task>.+)-s(?P<seed>\d+)-a(?P<agent>\d+)-code_xl\.jsonl$')
VARIANT, CODING_VARIANT = 'xl_forced_original', 'code_xl'
S1_SEED_OFFSET = 27100  # agent seed 1000 * case seed + offset + slot (the same in every arm)
JUDGE_SEED_BASE = 90000
SOURCE_PATH = '.runtime/collab-source'
JUDGE_ENTRY = ('run_variants', 'run_judge')  # what collab_replay.load_judge imports from the judge tree
JUDGE_EXTRA = ('inkling/admit.py', 'inkling/fleet_lease.py')  # run (admission) and loaded (lease) by the driver
FLEET = dict(endpoints=[f'http://127.0.0.1:{p}/v1' for p in range(18081, 18085)],
             hosts=['Spark_01', 'Spark_02', 'Spark_03', 'Spark_04'])  # canonical pairs (run_coding_agents, admit.py)
PER_NODE = 20
SERVING_FROM = 'SWARM_FAIR_HARD23_PLAN.json'  # the current serving identity (v2.9.2 recipe), checked by admit.py
TEMPLATE = (Path.home() / '.cache/huggingface/hub/models--thinkingmachines--Inkling-2-Mini/snapshots/'
            'ed40e7da625f594fc9c4990f5f66be24873c22d7/chat_template.jinja')
ALPHA = 0.10  # familywise false-pass bound of the S1 gate (two protocol arms, two looks)
NULL_RESCUES = range(5, 11)  # null: every arm rescues each primary puzzle with p = k / 41 (design: 6-9 in D', +-1)
POWER_GAIN = 6  # power reported for a true gain of 6 rescued puzzles in one protocol arm
CREDIT = ('Blackboard architectures (Erman, Hayes-Roth, Lesser, Reddy, Hearsay-II, 1980; Nii, 1986) and multi-agent '
          'debate (Du, Li, Torralba, Tenenbaum, Mordatch, 2023); design by Fable (DESIGN-live-collab-fable.md, '
          '2026-11-25); replay pattern of tail_replay.py and reserve_replay.py.')
NOTE_MAX_TOKENS = 200   # hard cap of the note call: every note is <= 256 tokens by construction
BOARD_SHARE = 0.03      # the appended board turn <= 3 % of the retained context (astra, S0 review)
WAVE_GROUPS = 20        # S0 v2: groups per wave (one stream per node per group: <= 20 streams per node)
VERIFY_MAX_TOKENS = 8
ARITH_COVERAGE = '>= 0.75'  # collab-s0-v1 under exact_claims: 63/80 = 0.79 of the arithmetic checkpoints had an
                            # evaluable statement (3 result slots then, 1 "computed" now); collab-s0-v2-dev: 75/80
PROTOCOL = dict(marks=[8192, 16384, 24576], note_max_tokens=NOTE_MAX_TOKENS, min_resume_think=4096, max_submissions=4,
                board_limit_chars=1800, field_limit_chars=160, max_items=1, max_peers=8, board_share=BOARD_SHARE,
                full_rejected_answer_chars=6000, thinking_cap=30720, total=32768,
                note_format='facts only: {"focus", "computed", "tried", "checked"}, at most one statement per kind, '
                            '<= 60 words; no reviews (opinions about other entries are not observations)',
                note_schema='validated before anything is cleaned or posted: only focus / computed / tried / checked, '
                            'strings, <= 60 words in all, focus <= 12 words, a statement <= 240 characters (never '
                            'clipped); a violation makes the reply unparseable (counted against reply_parse, reason '
                            'recorded); tried must read "approach: ...; observed: ...", checked "input: ...; expected: '
                            '...; got: ..." (else the statement is dropped)',
                verifier=f'before posting: exact_claims.py (decimals exact from their text; a statement whose '
                         f'equation is joined to a name is unparseable as a whole; a false equation drops the '
                         f'statement; a true "computed" one is VERIFIED; an arithmetic-looking one that does not parse '
                         f'is UNVERIFIED); "checked" statements against the family\'s known cases (coding: the task '
                         f'examples and public cases): a contradiction is dropped, a match fixes input and expected '
                         f'only so the observed "got" still goes to the checker; otherwise ONE CHECKER TURN on the '
                         f'solver\'s own note sequence (its pinned prompt + prefix ids, its note turn, then a user turn '
                         f'collab.CHECK_PROMPT; thinking closed, temperature 0, max_tokens {VERIFY_MAX_TOKENS}; the '
                         f'prefix is served from the cache, only the checker turn is new prompt): a first word SUPPORTED '
                         f'-> agent-checked, else dropped (no verdict counted apart); a checker fault is an '
                         f'infrastructure fault; checker tokens (cancelled included) are accounted apart (verifier_* '
                         f'fields) and count toward compute. S0: inline under the solver\'s permit; S1 protocol arms '
                         f'(verify_async): next to the continuation, the solver\'s permit counting two units',
                board_priority='with a budget: compact WHOLE lines for peer rejections (who, pass count; <= 3, newest '
                               'first) are reserved and always shown, then VERIFIED, agent-checked, UNVERIFIED statements '
                               '(each newest first), focus lines, end lines, old-format entries; the longest prefix '
                               'within the budget is shown and an omission line counts the rest',
                board_budget_rule='the budget (board_share x retained context) applies to the peer entries; the fixed '
                                  'board text, the solver\'s own rejection evidence (one failing public case in full, '
                                  'owner decision 3) and the reserved rejection lines with the omission line are always '
                                  'sent; the final token count is checked before dispatch. Consequence for cached_share '
                                  '(gate unchanged): a board turn after an own coding rejection can exceed 3 % of a '
                                  'short context (about 670 tokens of fixed text + evidence against about 274 at 8,192), '
                                  'which lowers that node\'s cached share; it is reported per node, not exempted',
                note_prompts='collab.NOTE_FIRST / collab.NOTE_LATER (facts-only, S0 amendment)',
                board_prompt='collab.BOARD_PROMPT; the division-of-work rule only in arms with division_of_work true '
                             '(owner decision 2026-11-26)',
                evidence='arithmetic: the judge reason (none if the judge thinking was cut); coding: pass count and '
                         'exactly one failing public case (owner decision 2026-11-26)')


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_jsonl(path):
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def segments(run_dir):
    base = Path(run_dir)
    found = sorted((int(m.group(1)), d) for d in base.parent.glob(base.name + '-resume*')
                   if d.is_dir() and (m := re.match(re.escape(base.name) + r'-resume(\d+)$', d.name)))
    return [base] + [d for _, d in found]


def latest_rows(run_dir):
    """(task_id, seed) -> (segment dir, case row): a later segment's row replaces an earlier one; rows with an
    'error' field are not cases."""
    out = {}
    for seg in segments(run_dir):
        path = seg / 'cases.jsonl'
        if not path.exists():
            continue
        for row in read_jsonl(path):
            if 'error' not in row:
                out[(row['task_id'], row['seed'])] = (seg, row)
    return out


def plan_request(path, stage):
    """(run_start config, extra prompt text, request_start, request_end) of a trace's first `stage` request."""
    records = read_jsonl(path)
    run_start = next((r for r in records if r.get('type') == 'run_start'), {})
    extra = next((r.get('text') or '' for r in records if r.get('type') == 'extra_prompt'), '')
    start = next((r for r in records if r.get('type') == 'request_start' and r.get('stage') == stage), None)
    end = next((r for r in records if start and r.get('type') == 'request_end'
                and r.get('request_id') == start.get('request_id')), None)
    return run_start.get('config') or {}, extra, start, end


def stream_fields(path, stage, cut, root):
    """Plan fields of one recorded stream, or (None, reason) if it cannot be cut at `cut`."""
    config, extra, start, end = plan_request(path, stage)
    if end is None:
        return None, 'no finished request'
    ids = end.get('token_ids') or []
    usage = (end.get('usage') or {}).get('completion_tokens')
    if usage is not None and usage != len(ids) and not end.get('attempts'):
        return None, 'token ids inconsistent with usage'
    if len(ids) <= cut:
        return None, f'{len(ids)} tokens <= cut'
    if INKLING_CONTENT_TEXT in ids[:cut]:
        return None, 'thinking closed before the cut'
    if extra:
        return None, 'extra prompt text'
    return dict(trace=str(Path(path).resolve().relative_to(Path(root).resolve())),
                prompt_ids_sha256=start.get('prompt_ids_sha256'), prefix_ids_sha256=sha(json.dumps(ids[:cut])),
                recorded_tokens=len(ids), recorded_finish_reason=end.get('finish_reason'),
                recorded_closed_thinking=bool(end.get('closed_thinking')), worker_seed=config.get('seed'),
                worker_variant=config.get('variant')), None


def s1_cohort(root, arms=S1_ARMS, cut=CUT):
    """All cohort cases (dicts) and the per-arm exclusion counts."""
    cases, skipped = [], {}
    for arm in arms:
        run = Path(root) / 'runs' / arm
        corpus = arm.split('-v1-')[0]
        for (task_id, seed), (seg, row) in sorted(latest_rows(run).items()):
            first = sorted((a for a in row['agents'] if a['slot'] < 4), key=lambda a: a['slot'])
            if len(first) != 4:
                continue
            if any(a.get('verdict') is True or a.get('cancelled') for a in first):
                continue
            agents, reason = [], None
            for a in first:
                path = seg / 'agents' / f"{task_id}-s{seed}-{row['policy']}-a{a['slot']}.jsonl"
                if not path.exists():
                    reason = 'missing trace'
                    break
                fields, why = stream_fields(path, 'plan', cut, root)
                if fields is None:
                    reason = why
                    break
                if fields['worker_variant'] != VARIANT:
                    reason = f"variant {fields['worker_variant']}"
                    break
                config = plan_request(path, 'plan')[0]
                agents.append(dict(fields, slot=a['slot'], puzzle=config['puzzle']))
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            if len({x['puzzle'] for x in agents}) != 1 or len({x['prompt_ids_sha256'] for x in agents}) != 1:
                raise ValueError(f'{arm} {task_id} s{seed}: first-wave agents differ in puzzle or prompt')
            numbers, target = agents[0]['puzzle'].split(':')
            cases.append(dict(corpus=corpus, run=arm, run_segment=seg.name, task_id=task_id, seed=seed,
                              puzzle_key=f'{corpus}:{task_id}', puzzle=agents[0]['puzzle'],
                              numbers=[int(n) for n in numbers.split(',')], target=int(target),
                              recorded_answered=bool(row.get('answered')), recorded_solved=bool(row.get('solved')),
                              agents=[{k: v for k, v in x.items() if k != 'puzzle'} for x in agents]))
    primary, second = {}, {}
    for i, case in enumerate(cases):
        key = case['puzzle_key']
        if key not in primary or case['seed'] < cases[primary[key]]['seed']:
            primary[key] = i
    for i, case in enumerate(cases):
        key = case['puzzle_key']
        if case['seed'] != cases[primary[key]]['seed'] and (key not in second or case['seed'] < cases[second[key]]['seed']):
            second[key] = i
    roles = {i: 'primary' for i in primary.values()}
    roles.update({i: 'extension' for i in second.values()})
    if len(cases) > len(roles):
        skipped['same seed as the puzzle\'s primary or extension case (not planned)'] = len(cases) - len(roles)
    cases = [dict(case, cohort=roles[i]) for i, case in enumerate(cases) if i in roles]
    cases.sort(key=lambda k: (k['cohort'] != 'primary', k['puzzle_key'], k['seed'], k['run']))
    for n, case in enumerate(cases):
        case['case_id'] = f"{ARM_TAG.get(case['run'], 'x')}-{case['task_id']}-s{case['seed']}"
        for a in case['agents']:
            a['agent_seed'] = 1000 * case['seed'] + S1_SEED_OFFSET + a['slot']
            a['judge_seed'] = JUDGE_SEED_BASE + 1000 * case['seed'] + 10 * n + a['slot']
    return cases, skipped


def _binom(n, p):
    return [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]


@functools.lru_cache(maxsize=None)
def arm_distribution(n, e, p):
    """{(primary rescues X, pooled rescues B): probability} of one arm under the null: every puzzle rescued with
    probability p independently; e of the n puzzles have an extension case (a puzzle counts as rescued in the pooled
    look if its primary or its extension case is)."""
    out = {}
    for a0, pa0 in enumerate(_binom(n - e, p)):
        for a1, pa1 in enumerate(_binom(e, p)):
            for y, py in enumerate(_binom(e - a1, p)):
                key = (a0 + a1, a0 + a1 + y)
                out[key] = out.get(key, 0.0) + pa0 * pa1 * py
    return out


def pass_probability(control, arm, m1, m2):
    """P(the arm passes) given the control's (X, B): primary lead >= m1, or a primary lead of m1-2 or m1-1 (GREY)
    and a pooled lead >= m2."""
    x_d, b_d = control
    return sum(q for (x, b), q in arm.items() if x - x_d >= m1 or (m1 - 2 <= x - x_d <= m1 - 1 and b - b_d >= m2))


def familywise(n, e, p, m1, m2, arms=2, p_arm=None):
    """P(at least one of `arms` protocol arms passes) against a shared control; arms independent given the control.
    p_arm: the first protocol arm's rescue probability (power), default p (null)."""
    control = arm_distribution(n, e, p)
    null_arm = control
    first = arm_distribution(n, e, p_arm) if p_arm is not None else null_arm
    total = 0.0
    for d, pd in control.items():
        q_first, q_null = pass_probability(d, first, m1, m2), pass_probability(d, null_arm, m1, m2)
        total += pd * (1 - (1 - q_first) * (1 - q_null) ** (arms - 1))
    return total


def calibrate(n, e, alpha=ALPHA, rescues=NULL_RESCUES, arms=2):
    """The smallest primary margin m1 (then the smallest pooled margin m2 >= m1) whose familywise false-pass
    probability is <= alpha for every null rescue rate k/n in `rescues`. Exact enumeration of binomials."""
    for m1 in range(2, n):
        if max(familywise(n, e, k / n, m1, n + 1, arms) for k in rescues) > alpha:
            continue  # the primary look alone already exceeds alpha
        for m2 in range(m1, n + 2):
            worst = max(familywise(n, e, k / n, m1, m2, arms) for k in rescues)
            if worst <= alpha:
                table = {str(k): round(familywise(n, e, k / n, m1, m2, arms), 6) for k in rescues}
                single = {str(k): round(familywise(n, e, k / n, m1, m2, 1), 6) for k in rescues}
                power = {str(k): round(familywise(n, e, k / n, m1, m2, arms, p_arm=min(1.0, (k + POWER_GAIN) / n)), 6)
                         for k in rescues}
                return dict(primary_margin=m1, grey_band=[m1 - 2, m1 - 1], pooled_margin=m2,
                            familywise_false_pass_max=round(worst, 6), familywise_false_pass_by_null_rescues=table,
                            single_arm_false_pass_by_null_rescues=single,
                            power_one_arm_true_gain_6_by_null_rescues=power)
    raise ValueError('no calibration found')


S1_RULE = dict(
    gate_all_of=['wrong(C) == 0 over all attempts (an accepted answer the exact verifier rejects is wrong)',
                 'rescued puzzles(C) >= rescued puzzles(D\') + primary_margin (calibration below)',
                 'accepted agents(C) >= accepted agents(D\')',
                 'novelty(C) >= novelty(D\') - 0.02 (share of a piece\'s distinct word 5-grams absent from every text '
                 'another agent of the case had written when the piece started; pieces = post-cut thinking split at the '
                 'common thinking-token boundaries 8,192 / 16,384 / 24,576 / 30,720 via streamed progress samples; '
                 'cancelled partial streams count with their streamed text; a piece counts if it has >= 20 distinct '
                 '5-grams; arm novelty = mean over counted pieces)'],
    applies_to='each protocol arm C in {C\', C\'div} separately against the shared control D\'; the idea continues if '
               'any protocol arm passes, and every passing arm goes to the A/B',
    grey_zone='a primary lead inside grey_band with rules 1, 3 and 4 met: run the extension cohort (one distinct second '
              'seed per eligible puzzle; collab_replay.py --cohort extension) and pass if C leads D\' by at least '
              'pooled_margin rescued puzzles on the pooled cases, a puzzle counting as rescued by an arm if any of its '
              'cases is; rules 1, 3, 4 again on the pooled cases; only arms that were GREY at the primary look can '
              'pass at the pooled look',
    stop='anything else ends the idea; the rejection goes to review (lab rule)',
    incomplete='any job with an infrastructure fault, a missing job, a prompt or prefix mismatch, or an embedded plan '
               'that differs from the plan file: no decision (rerun the incomplete jobs with --jobs and pass both '
               'output directories to the report)')

S0_CHECKS = [
    dict(id='prefix_identical', metric='share of checkpoints whose composed sequence starts with the recorded prompt '
         'and prefix ids and (if continued) whose continuation starts with the note call prompt + reply ids',
         limit='== 1.0', on_fail='fix'),
    dict(id='turn_boundaries', metric='the rendered-fixture preflight passed on every endpoint (full note, board and '
         'own-rejection sequences equal to the template rendering) and every join of a finished reply kept exactly '
         'the template terminator', limit='== 1.0', on_fail='fix'),
    dict(id='cached_share', metric='per node: 1 - prefill_compute / prompt tokens during the board phase; valid only '
         'with finite nonnegative deltas on every node whose request delta equals the continuation requests (attempts) '
         'the driver sent to that node in the phase; the check uses the LOWEST node', limit='>= 0.95',
         on_fail='fix or fallback B'),
    dict(id='checkpoint_latency', metric='PROXY: median over ALL continued checkpoints (every one must have both '
         'first-token times) of (note call first-token time - send time) + (continuation first-token time - send '
         'time), raw seconds, at the frozen per_node', limit='<= 5.0 s', on_fail='fix or fallback B'),
    dict(id='reply_parse', metric='share of note turns returning a parseable note or a parseable answer',
         limit='>= 0.90', on_fail='fix the note prompt once, then fallback B'),
    dict(id='note_within_256', metric='share of parsed notes with at most 256 reply tokens', limit='>= 0.90',
         on_fail='fix the note prompt once, then fallback B'),
    dict(id='arith_results_correct', metric='share of the POSTED statements of arithmetic checkpoints (facts-only '
         'notes; old-format notes: result sentences) WITH at least one evaluable equation (exact_claims.find_equations: '
         'maximal arithmetic runs, identifiers break a run) whose equations all hold (exact_claims.check_statement: '
         'whole expressions with precedence, parentheses and powers, chained equalities, exact rationals; the '
         'implementation the pre-posting verifier uses); statements with an arithmetic-looking but unparseable '
         'equation and statements without one are reported, not counted; none evaluable = not met', limit='>= 0.90',
         on_fail='stop'),
    dict(id='arith_coverage', metric='ADDED in collab-s0-v2 (sol review): share of ALL arithmetic checkpoints with at '
         'least one POSTED statement containing an evaluable equation (exact_claims TRUE or FALSE); keeps '
         'arith_results_correct from passing on a few posts after many drops; derivation: collab-s0-v1 under '
         'exact_claims 63/80 = 0.79, collab-s0-v2-dev 75/80 = 0.94', limit=ARITH_COVERAGE,
         on_fail='fix the note prompt once, then fallback B'),
    dict(id='focus_distinct', metric='share of focus-line pairs of a group (same case and cut, groups of >= 2 notes) '
         'with word-set Jaccard < 0.6', limit='>= 0.75', on_fail='stop: nothing to divide'),
    dict(id='answer_at_once', metric='share of continuations whose thinking closes within the first 512 tokens (token '
         'position of the end-of-thinking ids) among continuations that stayed open or have a located close; needs '
         'every continuation present and the close located in >= 90 % of the continuations that closed',
         limit='<= 0.20', on_fail='stop, or fallback B'),
    dict(id='own_repeat', metric='PROXY: mean share of a continuation\'s word 5-grams already in its own recorded '
         'prefix, minus the same share for the recorded continuation (recorded texts split by character share: the '
         'shim has no /detokenize)', limit='<= +0.10', on_fail='stop, or fallback B'),
]


def judge_files(root):
    """Every module of `root` that importing the judge entry modules loads (a superset of what the driver loads:
    its own tree shadows harness etc.), plus the admission script and the lease."""
    import subprocess
    code = ('import sys; from pathlib import Path; root = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(root))\n'
            f'import {", ".join(JUDGE_ENTRY)}\n'
            'print("\\n".join(sorted(str(Path(m.__file__).resolve().relative_to(root)) for m in list(sys.modules.values())'
            ' if getattr(m, "__file__", None) and root in Path(m.__file__).resolve().parents)))')
    out = subprocess.run([sys.executable, '-B', '-c', code, str(root)], capture_output=True, text=True, check=True)
    return sorted(set(out.stdout.split()) | set(JUDGE_EXTRA))


def judge_hashes(root):
    return {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() for name in judge_files(root)}


def serving(root):
    out = dict(json.loads((Path(root) / SERVING_FROM).read_text())['serving'], identity_from=SERVING_FROM)
    if TEMPLATE.exists():
        out['chat_template_sha256'] = hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()
        out['chat_template'] = 'thinkingmachines/Inkling-2-Mini snapshot ed40e7da chat_template.jinja'
    return out


def base_plan(screen, study, revision, root=ROOT):
    """root: the repository whose recorded runs are read; judge pins and serving identity come from THIS generator's
    tree (the main tree the plan is committed to and the driver's --judge-source)."""
    return dict(protocol='collab-replay-screen-v3', screen=screen, study=study, status='FROZEN', nodes=4,
                fleet=FLEET, per_node=PER_NODE,
                source_revision=revision, source_path=SOURCE_PATH, driver='collab_replay.py',
                judge_code_sha256=judge_hashes(ROOT), serving=serving(ROOT),
                execution='each screen alone on the fleet: collab_replay.py --run with plan.fleet\'s four --endpoint/'
                          '--host pairs holds the fleet lease (inkling/fleet_lease.py), runs inkling/admit.py (idle '
                          'fleet, receipt bound to this plan\'s sha256), checks every module it loads from '
                          '--judge-source against judge_code_sha256, runs the rendered-fixture preflight on every '
                          'endpoint, keeps <= per_node requests per node and drains the fleet before exiting',
                report='inkling/report_collab_screen.py', design='DESIGN-live-collab-fable.md', credit=CREDIT,
                generator=f'inkling/collab_plans.py {screen}', protocol_constants=PROTOCOL,
                concurrency='<= 20 requests per node by default (--per-node, hard cap 25); one permit per agent for '
                            'its life; an agent has one request in flight at a time (its gate calls included)',
                judge='run_variants.judge_with_reason, unchanged (main tree, read-only); the exact verifier and '
                      'hidden cases only score, after the agent\'s last model call')


def make_s1(root, revision):
    cases, skipped = s1_cohort(root)
    plan = base_plan('s1', 'collab-s1-v1', revision, root)
    n = sum(k['cohort'] == 'primary' for k in cases)
    e = sum(k['cohort'] == 'extension' for k in cases)
    rule = dict(S1_RULE, margins=calibrate(n, e),
                null_model=f'all arms identical; each of the {n} primary puzzles rescued independently with '
                           f'probability k/{n} (k in {NULL_RESCUES.start}..{NULL_RESCUES.stop - 1}, the design expects '
                           f'6-9 for D\'); {e} puzzles have an extension case; the two protocol arms independent given '
                           f'the shared control; rules 1, 3 and 4 ignored (a conservative bound); exact enumeration '
                           f'(collab_plans.familywise)')
    plan.update(cut=CUT, agent_variant=VARIANT, seed_offset=S1_SEED_OFFSET, judge_seed_base=JUDGE_SEED_BASE,
                source_runs=S1_ARMS, arm_order=["D'", "C'", "C'div"],
                arms={"D'": dict(tag='dp', protocol=False, note='plain continuation, the worker logic: thinking to '
                                 '30,720, forced answer within 32,768'),
                      "C'": dict(tag='cp', protocol=True, division_of_work=False, board='live',
                                 note_max_tokens=NOTE_MAX_TOKENS, board_share=BOARD_SHARE, verify_async=True,
                                 note='protocol, default form (no division-of-work rule)'),
                      "C'div": dict(tag='cdiv', protocol=True, division_of_work=True, board='live',
                                    note_max_tokens=NOTE_MAX_TOKENS, board_share=BOARD_SHARE, verify_async=True,
                                    note='protocol + division-of-work rule (owner decision 2: a separate arm)')},
                cohort_rule=__doc__.split('S1 cohort (design 4.2, Fable\'s A6): ')[1].split('\n\n')[0],
                cohort_counts=dict(primary=sum(k['cohort'] == 'primary' for k in cases),
                                   extension=sum(k['cohort'] == 'extension' for k in cases),
                                   recorded_answered_primary=sum(k['recorded_answered'] for k in cases
                                                                 if k['cohort'] == 'primary')),
                cohort_exclusions=skipped, decision_rule=rule,
                pairing='arms share prefixes, agent seeds (1000 * seed + 27100 + slot), judge seed bases and nodes '
                        '((job index + slot) % 4); same-seed requests do not reproduce on this serving, so the arms '
                        'are independent samples per case',
                cost='worst case 41 x 4 x 22.5K x 3 arms = 11.1M generated tokens; about 1.8 fleet hours (extension: '
                     '29 more cases)',
                cases=cases)
    return plan


def coding_streams(root, runs=CODING_RUNS, cut=CODING_CUT, min_tokens=16384):
    groups = {}
    for ri, run in enumerate(runs):
        d = Path(root) / 'runs' / run
        matrix = json.loads((d / 'metadata.json').read_text())['protocol']['matrix']
        for f in sorted(d.glob('*.jsonl')):
            m = CODING_NAME.match(f.name)
            if not m:
                continue
            fields, _ = stream_fields(f, 'code_propose', cut, root)
            if fields is None or fields['recorded_tokens'] <= min_tokens or fields['worker_variant'] != CODING_VARIANT:
                continue
            key = (ri, run, m['task'], int(m['seed']))
            groups.setdefault(key, []).append(dict(fields, agent=int(m['agent']), task_id=m['task'],
                                                   seed=int(m['seed']), tasks=matrix['tasks'], tests=matrix['tests']))
    return groups


S0_AMENDMENTS = [
    'notes: facts only (focus + at most one computed / tried / checked statement), every statement checked before '
    'posting (protocol_constants.verifier); owner 2026-11-26 after collab-s0-v1 STOP',
    f'note call max_tokens {NOTE_MAX_TOKENS} (note_within_256 holds by construction; a note cut by the cap is '
    'unparseable and counts against reply_parse)',
    f'board turn budget: the whole appended turn <= {BOARD_SHARE} x the retained context, lowest-priority entries '
    'dropped first (astra: new board suffixes alone capped cached_share at 94.2-94.5 %)',
    'warm-up: per stream on prompt + prefix WITHOUT its last token (no discarded token inside the reused prefix), its '
    'note at once under the same permit; no global warm phase (collab-s0-v1: 1.03M of 1.20M note prompt tokens '
    'recomputed after a 1.17M-token warm phase)',
    f'waves of {WAVE_GROUPS} whole groups (each group on distinct nodes: <= {WAVE_GROUPS} streams per node), note and '
    'board phases per wave, board-phase barrier per wave; per_node stays 20',
    'arith_results_correct: over the POSTED statements (exact_claims.py, the verifier\'s implementation; whole '
    'expressions and chains), unparseable ones reported apart; collab-s0-v1\'s regex substring check was a checker '
    'artifact (astra review: 12 flagged equations correct, one real error missed)',
    'reported, not gated: statements made / dropped / UNVERIFIED / agent-checked / VERIFIED and drop rate by family, '
    'drops by reason (checker without a verdict apart), prefilter accuracy, schema violations, checker tokens (new and '
    'cached), latency, board-phase prefill split into new text and eviction per node',
    'collab-s0-v3 (after collab-s0-v2 FIX, checkpoint_latency 23.5 s, every other gate met): warm-ups of a wave '
    'complete before its notes: the latency proxy measures cached-prefix notes, not replay prefill queueing (v2: note '
    'first-token median 21.0 s behind the other streams\' warm-up prefill on the node, continuation 2.5 s); thresholds, '
    'on_fail actions, waves, per_node and protocol unchanged',
    'review round (sol + collab-s0-v2-dev): the checker is a turn on the solver\'s own cached note sequence (dev: '
    '603K fresh excerpt prompt tokens evicted the streams\' prefixes, cached_share 0.385), its verdict the first word '
    '(dev: 32 "SUPPORTEDThe..." replies lost); a new gate arith_coverage >= 0.75 (stricter; no limit loosened); the '
    'note schema enforced before cleaning; budgeted boards reserve compact rejection lines',
]


def make_s0(root, revision, s1_plan, dev=False):
    primary = [k for k in s1_plan['cases'] if k['cohort'] == 'primary']
    picked = sorted(random.Random(S0_SEED).sample(range(len(primary)), S0_CASES))
    groups = []
    for cut in S0_CUTS:
        for i in picked:
            case = primary[i]
            members = []
            for a in case['agents']:
                if a['recorded_tokens'] <= cut:
                    raise ValueError(f"{case['case_id']} slot {a['slot']} is not longer than {cut}")
                path = Path(root) / a['trace']
                fields, why = stream_fields(path, 'plan', cut, root)
                if fields is None:
                    raise ValueError(f"{case['case_id']} slot {a['slot']}: {why}")
                members.append(dict(fields, slot=a['slot'], task_id=case['task_id'], seed=case['seed'],
                                    puzzle=case['puzzle'], numbers=case['numbers'], target=case['target'],
                                    agent_seed=fields['worker_seed'], judge_seed=a['judge_seed']))
            groups.append(dict(group_id=f"{case['case_id']}-c{cut}", family='arith', cut=cut,
                               case_id=case['case_id'], members=members))
    coding = coding_streams(root)
    order = sorted(coding, key=lambda k: (-len(coding[k]), k[0], k[2], k[3]))
    left = S0_CODING_STREAMS
    for key in order:
        if left <= 0:
            break
        streams = sorted(coding[key], key=lambda x: x['agent'])[:min(S0_CODING_PER_CASE, left)]
        left -= len(streams)
        _, run, task, seed = key
        members = [dict(s, slot=i, agent_seed=s['worker_seed']) for i, s in enumerate(streams)]
        groups.append(dict(group_id=f"{'v29' if 'v29' in run else 'aot'}-{task}-s{seed}-c{CODING_CUT}",
                           family='coding', cut=CODING_CUT, run=run, members=members))
    plan = base_plan('s0', 'collab-s0-v3-dev' if dev else 'collab-s0-v3', revision, root)
    plan.update(s1_plan_cases=[primary[i]['case_id'] for i in picked], s0_seed=S0_SEED,
                note_prompt='the note prompt of a solver\'s first checkpoint ("Checkpoint 1 of 3") at both cuts: '
                            'each replay is the stream\'s first checkpoint',
                continuation_tokens=2048, answer_at_once_tokens=512, phases=['warm', 'note', 'board'],
                wave_groups=WAVE_GROUPS, warm_barrier=True,
                amends='collab-s0-v2 (FIX on checkpoint_latency only; results/collab-s0-v2 kept as is), which amended '
                       'collab-s0-v1 (STOP; results/collab-s0-v1 kept as is)', amendments=S0_AMENDMENTS,
                exact_claims_sha256=hashlib.sha256((HERE / 'exact_claims.py').read_bytes()).hexdigest(),
                selection=__doc__.split('S0 sample (design 4.1): ')[1].split('\n\n')[0],
                checkpoints=sum(len(g['members']) for g in groups), checks=S0_CHECKS,
                decision_rule='PASS if every check meets its limit; otherwise the failed checks\' actions apply (any '
                              '"stop" action stops the idea, else fix and rerun S0). Incomplete (no decision) if any '
                              'checkpoint has an infrastructure fault or the embedded plan differs from the plan file.',
                groups=groups)
    if dev:
        plan.update(dev=True, nodes=2, fleet=dict(dev=True, endpoints='given at launch (--dev --endpoint/--host)'),
                    execution='DEV ONLY: collab_replay.py --run --dev on a 2-node development fleet (never the decision '
                              'fleet endpoints); no lease, no admission; the report computes the checks but never '
                              'decides')
    return plan


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('screen', choices=('s0', 's1'))
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--source-revision', required=True)
    p.add_argument('--s1-plan', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--dev', action='store_true', help='s0: a 2-node development plan (never for decisions)')
    a = p.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{40}', a.source_revision):
        p.error('--source-revision must be a full commit hash')
    if a.output.exists():
        p.error('output exists')
    if a.screen == 's1':
        plan = make_s1(a.root, a.source_revision)
    else:
        if not a.s1_plan:
            p.error('s0 needs --s1-plan')
        plan = make_s0(a.root, a.source_revision, json.loads(a.s1_plan.read_text()), dev=a.dev)
    a.output.write_text(json.dumps(plan, indent=1) + '\n')
    summary = {k: plan[k] for k in ('study', 'screen') if k in plan}
    summary.update(plan.get('cohort_counts') or dict(checkpoints=plan.get('checkpoints'), groups=len(plan['groups'])))
    print(json.dumps(summary))
    return 0


if __name__ == '__main__':
    sys.exit(main())
