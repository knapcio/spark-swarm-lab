#!/usr/bin/env python3
"""Frozen plans for the live-collaboration replay screens S0 and S1 (DESIGN-live-collab-fable.md, 4.1 and 4.2).

Reads recorded runs only (no model call, no host): writes a plan JSON that the replay driver collab_replay.py on the
collaboration worker source (research/collab-v1) executes, and that inkling/report_collab_screen.py evaluates with the
frozen rules embedded here. Commit and push the plan before any call.

S1 cohort (design 4.2, Fable's A6): recorded cases of the default-type arms swarm-generic-hard18-v1-roll12cancel (G),
swarm-relay-hard19-v1-roll12cancel (G), swarm-wide-hard20-v1-roll12cancel and -roll12wide, swarm-aot-hard21-v1-p-roll12wide
(P) in which all four first-wave agents (slots 0-3) finished their plan request with more than CUT (8,192) tokens, none
was cancelled and none was accepted. Per puzzle (corpus, task) the case with the lowest seed (ties: the arm listed
first) is 'primary' (41 cases); every other cohort case is 'extension' (the grey-zone rerun: 81 pooled cases). Every
planned stream is checked here: plan stage request_end present, token ids consistent with usage, still thinking at the
cut (no Inkling content-text token, id INKLING_CONTENT_TEXT from inkling/shim.py, in the first CUT ids), variant
xl_forced_original, no extra prompt text.

S0 sample (design 4.1): S0_CASES primary S1 cases drawn with random.Random(S0_SEED) (their four first-wave streams cut
at 8,192 and again at 16,384: 80 checkpoints) and 20 coding streams of coding-v29-r2-v1 and coding-aot-v1-p whose
code_propose request is longer than 16K tokens and still thinking at the coding cut, grouped by recorded case: cases
with more such streams first (at most 4 streams per case, lowest agent index first), then run order, task, seed, until
20 streams (100 checkpoints in all).

usage: collab_plans.py s1 --source-revision REV --output COLLAB_S1_PLAN.json [--root DIR]
       collab_plans.py s0 --s1-plan COLLAB_S1_PLAN.json --source-revision REV --output COLLAB_S0_PLAN.json [--root DIR]
"""
import argparse
import hashlib
import json
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
CREDIT = ('Blackboard architectures (Erman, Hayes-Roth, Lesser, Reddy, Hearsay-II, 1980; Nii, 1986) and multi-agent '
          'debate (Du, Li, Torralba, Tenenbaum, Mordatch, 2023); design by Fable (DESIGN-live-collab-fable.md, '
          '2026-11-25); replay pattern of tail_replay.py and reserve_replay.py.')
PROTOCOL = dict(marks=[8192, 16384, 24576], note_max_tokens=2048, min_resume_think=4096, max_submissions=4,
                board_limit_chars=1800, field_limit_chars=160, max_items=3, max_peers=8,
                full_rejected_answer_chars=6000, thinking_cap=30720, total=32768,
                note_prompts='collab.NOTE_FIRST / collab.NOTE_LATER (design 1.10 verbatim)',
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
    primary = {}
    for i, case in enumerate(cases):
        key = case['puzzle_key']
        if key not in primary or case['seed'] < cases[primary[key]]['seed']:
            primary[key] = i
    chosen = set(primary.values())
    for i, case in enumerate(cases):
        case['cohort'] = 'primary' if i in chosen else 'extension'
    cases.sort(key=lambda k: (k['cohort'] != 'primary', k['puzzle_key'], k['seed'], k['run']))
    for n, case in enumerate(cases):
        case['case_id'] = f"{ARM_TAG.get(case['run'], 'x')}-{case['task_id']}-s{case['seed']}"
        for a in case['agents']:
            a['agent_seed'] = 1000 * case['seed'] + S1_SEED_OFFSET + a['slot']
            a['judge_seed'] = JUDGE_SEED_BASE + 1000 * case['seed'] + 10 * n + a['slot']
    return cases, skipped


S1_RULE = dict(
    gate_all_of=['wrong(C) == 0 over all attempts (an accepted answer the exact verifier rejects is wrong)',
                 'rescued puzzles(C) >= rescued puzzles(D\') + 4',
                 'accepted agents(C) >= accepted agents(D\')',
                 'novelty(C) >= novelty(D\') - 0.02 (share of a segment\'s word 5-grams absent from every text another '
                 'agent of the case wrote before the segment started; mean over post-cut thinking segments)'],
    applies_to='each protocol arm C in {C\', C\'div} separately against D\'; the idea continues if any protocol arm '
               'passes (two protocol arms: the chance pass rate is up to about twice the single-arm 8 %)',
    grey_zone='C ahead by 2 or 3 rescued puzzles with rules 1, 3 and 4 met: run the extension cohort (40 cases, '
              'collab_replay.py --cohort extension) and pass if C rescues at least 6 more puzzles than D\' on the '
              'pooled 81 cases, a puzzle counting as rescued by an arm if any of its cases is rescued; rules 1, 3, 4 '
              'again on the pooled cases',
    stop='anything else ends the idea; the rejection goes to review (lab rule)',
    incomplete='any job with an infrastructure fault, a missing job, a prompt or prefix mismatch, or an embedded plan '
               'that differs from the plan file: no decision (rerun the incomplete jobs with --jobs and pass both '
               'output directories to the report)')

S0_CHECKS = [
    dict(id='prefix_identical', metric='share of checkpoints whose composed sequence starts with the recorded prompt '
         'and prefix ids and whose continuation starts with the note call prompt + reply ids', limit='== 1.0',
         on_fail='fix'),
    dict(id='cached_share', metric='1 - prefill_compute / prompt tokens on all nodes during the board phase '
         '(continuation calls only; server counters)', limit='>= 0.95', on_fail='fix or fallback B'),
    dict(id='checkpoint_latency', metric='median over checkpoints of note-call time to first token + continuation '
         'time to first token, at --per-node 20', limit='<= 5.0 s', on_fail='fix or fallback B'),
    dict(id='reply_parse', metric='share of note turns returning a parseable note or a parseable answer',
         limit='>= 0.90', on_fail='fix the note prompt once, then fallback B'),
    dict(id='note_within_256', metric='share of parsed notes with at most 256 reply tokens', limit='>= 0.90',
         on_fail='fix the note prompt once, then fallback B'),
    dict(id='arith_results_correct', metric='share of arithmetic note result sentences whose a op b = c equations '
         'are all correct (offline regex; sentences without an equation count as correct and are also reported)',
         limit='>= 0.90', on_fail='stop'),
    dict(id='focus_distinct', metric='share of focus-line pairs of a group (same case and cut) with word-set '
         'Jaccard < 0.6', limit='>= 0.75', on_fail='stop: nothing to divide'),
    dict(id='answer_at_once', metric='share of continuations that close their thinking within the first 512 '
         'tokens', limit='<= 0.20', on_fail='stop, or fallback B'),
    dict(id='own_repeat', metric='mean share of a continuation\'s word 5-grams already in its own recorded prefix, '
         'minus the same share for the recorded continuation (same streams; recorded texts split by character share)',
         limit='<= +0.10', on_fail='stop, or fallback B'),
]


def base_plan(screen, study, revision):
    return dict(protocol='collab-replay-screen-v1', screen=screen, study=study, status='FROZEN',
                source_revision=revision, source_path=SOURCE_PATH, driver='collab_replay.py',
                report='inkling/report_collab_screen.py', design='DESIGN-live-collab-fable.md', credit=CREDIT,
                generator=f'inkling/collab_plans.py {screen}', protocol_constants=PROTOCOL,
                concurrency='<= 20 requests per node by default (--per-node, hard cap 25); one permit per agent for '
                            'its life; an agent has one request in flight at a time (its gate calls included)',
                judge='run_variants.judge_with_reason, unchanged (main tree, read-only); the exact verifier and '
                      'hidden cases only score, after the agent\'s last model call')


def make_s1(root, revision):
    cases, skipped = s1_cohort(root)
    plan = base_plan('s1', 'collab-s1-v1', revision)
    plan.update(cut=CUT, agent_variant=VARIANT, seed_offset=S1_SEED_OFFSET, judge_seed_base=JUDGE_SEED_BASE,
                source_runs=S1_ARMS, arm_order=["D'", "C'", "C'div"],
                arms={"D'": dict(tag='dp', protocol=False, note='plain continuation, the worker logic: thinking to '
                                 '30,720, forced answer within 32,768'),
                      "C'": dict(tag='cp', protocol=True, division_of_work=False, board='live',
                                 note='protocol, default form (no division-of-work rule)'),
                      "C'div": dict(tag='cdiv', protocol=True, division_of_work=True, board='live',
                                    note='protocol + division-of-work rule (owner decision 2: a separate arm)')},
                cohort_rule=__doc__.split('S1 cohort (design 4.2, Fable\'s A6): ')[1].split('\n\n')[0],
                cohort_counts=dict(primary=sum(k['cohort'] == 'primary' for k in cases),
                                   extension=sum(k['cohort'] == 'extension' for k in cases),
                                   recorded_answered_primary=sum(k['recorded_answered'] for k in cases
                                                                 if k['cohort'] == 'primary')),
                cohort_exclusions=skipped, decision_rule=S1_RULE,
                pairing='arms share prefixes, agent seeds (1000 * seed + 27100 + slot), judge seed bases and nodes '
                        '((job index + slot) % 4); same-seed requests do not reproduce on this serving, so the arms '
                        'are independent samples per case',
                cost='worst case 41 x 4 x 22.5K x 3 arms = 11.1M generated tokens; about 1.8 fleet hours',
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


def make_s0(root, revision, s1_plan):
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
    plan = base_plan('s0', 'collab-s0-v1', revision)
    plan.update(s1_plan_cases=[primary[i]['case_id'] for i in picked], s0_seed=S0_SEED,
                note_prompt='the note prompt of a solver\'s first checkpoint ("Checkpoint 1 of 3") at both cuts: '
                            'each replay is the stream\'s first checkpoint',
                continuation_tokens=2048, answer_at_once_tokens=512, phases=['warm', 'note', 'board'],
                selection=__doc__.split('S0 sample (design 4.1): ')[1].split('\n\n')[0],
                checkpoints=sum(len(g['members']) for g in groups), checks=S0_CHECKS,
                decision_rule='PASS if every check meets its limit; otherwise the failed checks\' actions apply (any '
                              '"stop" action stops the idea, else fix and rerun S0). Incomplete (no decision) if any '
                              'checkpoint has an infrastructure fault or the embedded plan differs from the plan file.',
                groups=groups)
    return plan


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('screen', choices=('s0', 's1'))
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--source-revision', required=True)
    p.add_argument('--s1-plan', type=Path)
    p.add_argument('--output', type=Path, required=True)
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
        plan = make_s0(a.root, a.source_revision, json.loads(a.s1_plan.read_text()))
    a.output.write_text(json.dumps(plan, indent=1) + '\n')
    summary = {k: plan[k] for k in ('study', 'screen') if k in plan}
    summary.update(plan.get('cohort_counts') or dict(checkpoints=plan.get('checkpoints'), groups=len(plan['groups'])))
    print(json.dumps(summary))
    return 0


if __name__ == '__main__':
    sys.exit(main())
