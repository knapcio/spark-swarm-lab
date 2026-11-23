#!/usr/bin/env python3
"""Offline-screened continuations of RECORDED forced72 plan streams (round-3 ideas 3 and 4).

Each replay rebuilds the agent's exact prompt token ids (same chat template via /tokenize, checked against the
recorded prompt_ids_sha256), appends the recorded generated token ids, splices in a short controller text inside the
still-open thinking channel and continues the SAME sequence with raw /v1/completions over token ids, through
forced72.ForcedClient (same streaming, seed formula, disconnect retry). The shim passes the ids to SGLang /generate,
so the recorded prefix is served from the radix cache when warm. After the continuation the answer is finished
exactly like forced72.run_forced after a length cut (force "\\n</think>\\n" if still thinking, or continue a cut
answer), and the plan is parsed like the worker (forced72.parse_plan, kept only if it is a dict with a nonempty
moves list, as run_arbiterfree.plan_of does).

Modes
  recall  (idea 4) a plan stream that used its whole thinking budget (finish length, thinking open, token count ==
          think cap): append RECALL text (target+x, target-x, target*x, target/x for every distinct given number x,
          only values that are positive integers, i.e. the only ones a legal move can produce; plain controller
          arithmetic on the task, no search) and continue up to RECALL_MAX_TOKENS, then force the answer with the
          worker's post-cut answer budget (total - think cap).
  rewind  EXPERIMENTAL (idea 3; not for screening yet: the offline trigger and the proportional cut only
          approximate the live watchdog, see the round-3 review). A plan stream on which the loop detector fires with REWIND_HITS consecutive checks (the
          research/xl-watchdog-v1 detector: zlib ratio < 0.06 on 2,000-character windows checked every 500
          characters while thinking is open): cut the stream back to REWIND_MARGIN_CHARS characters before the
          start of the first low-ratio window of the triggering run, append NUDGE, continue with a new seed (the
          worker's seed formula with stage 'rewind', so it differs from the original) up to the original thinking
          budget (kept + new <= think cap), then the worker's forcing path with total - kept - new tokens.
          The character cut is mapped to a token count by re-tokenizing: kept = round(len(tok(text[:cut])) *
          len(generated ids) / len(tok(text))), so the kept ids are the model's own ids (cache-friendly).

Cohort: by default only the cases the recorded run did NOT answer (cases.jsonl answered false: abstentions);
--case-list FILE (JSON list of [task_id, seed]) freezes an explicit cohort instead. Agents whose plan the judge
accepted are skipped unless --include-accepted. A recorded stream whose usage lacks completion_tokens is accepted
when its finish_reason is 'length' (the count is taken from token_ids; a watchdog stop never saw the usage chunk).

Records (JSONL, one per replay) carry 'candidate' = {numbers, target, plan}. Unless --no-judge, each plan is judged
with run_variants.judge_with_reason (loaded read-only from --judge-source, default the main tree) with the live seed
formula 90000 + 1000*seed + 10*case_index + slot (case_index from the run's metadata and corpus, as run_variants).
Each record has accept_kind: 'case_rescue' (judge accepted, case abstained in the recording), 'agent_accept' (judge
accepted, case was already answered) or null; OUTPUT.cases.jsonl has one row per cohort case with the same outcome.
'verifier_solved' is the exact verifier's score, for analysis only (an accepted plan it rejects is 'wrong').
--plan-only reads the runs and lists what would be replayed; it makes 0 model calls and contacts no host.
"""
import argparse
import collections
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import uuid
import zlib

from direct_solver import replay_plan
from followup72 import sha
from forced72 import CAPS, END_THINK, ForcedClient, parse_plan, task_prompt
from harness import Budget, Events, canonical, fingerprint, parse_puzzle

RECALL_MAX_TOKENS = 1536
RECALL_HEAD = '\n\nBefore answering: the target plus, minus, times and divided by each given number is '
RECALL_TAIL = ('. Did any of these values, or the target itself, appear as a result above? '
               'If yes, write that derivation as the plan.\n')
NUDGE = '\n\nthis line is exhausted; start again from a different decomposition:'
LOOP_WINDOW, LOOP_STEP, LOOP_RATIO = 2000, 500, 0.06  # research/xl-watchdog-v1 (1692ae6)
REWIND_HITS = 12  # trigger raised from the watchdog's 2 to 12 consecutive checks (round-3 corrections)
REWIND_MARGIN_CHARS = 2000  # one full window before the first low-ratio window of the triggering run
MAX_CONCURRENCY = 20
EXPERIMENTAL_MODES = {'rewind'}
JUDGE_SEED_BASE = 90000  # run_variants.run_agent: 90000 + 1000 * seed + 10 * case_index + slot
VARIANT_ALIASES = {'xl_forced_watchdog': 'xl_forced_original'}  # same prompt and caps; the watchdog is client-side
STEM = re.compile(r'^(?P<task>.+)-s(?P<seed>\d+)-(?P<policy>[A-Za-z0-9_]+)-a(?P<slot>\d+)$')


# ---------------------------------------------------------------- controller texts and the loop detector

def recall_values(numbers, target):
    """(expression, value) for target+x, target-x, target*x, target/x over distinct given x; positive integers only."""
    rows, t = [], Fraction(target)
    for x in dict.fromkeys(int(n) for n in numbers):
        for op, value in (('+', t + x), ('-', t - x), ('*', t * x), ('/', t / x)):
            if value > 0 and value.denominator == 1:
                rows.append((f'{target}{op}{x}', int(value)))
    return rows


def recall_text(numbers, target):
    return RECALL_HEAD + ', '.join(f'{e}={v}' for e, v in recall_values(numbers, target)) + RECALL_TAIL


def loop_ratio(window):
    raw = window.encode()
    return len(zlib.compress(raw)) / max(1, len(raw))


def loop_trigger(text, hits=REWIND_HITS):
    """Offline form of the watchdog: a check every LOOP_STEP characters once LOOP_WINDOW exist, thinking open only.
    Returns the firing point and the start of the first low-ratio window of the triggering run, or None."""
    end = text.find(END_THINK)
    text = text if end < 0 else text[:end]
    run = 0
    for n in range(LOOP_WINDOW, len(text) + 1, LOOP_STEP):
        run = run + 1 if loop_ratio(text[n - LOOP_WINDOW:n]) < LOOP_RATIO else 0
        if run >= hits:
            first_end = n - (hits - 1) * LOOP_STEP
            return dict(fire_char=n, loop_start_char=first_end - LOOP_WINDOW, checks=hits)
    return None


def rewind_cut_char(trigger):
    return max(0, trigger['loop_start_char'] - REWIND_MARGIN_CHARS)


def stream_text(end):
    """The rendered text of a recorded request (reasoning before the last marker, then the answer if any)."""
    reasoning = end.get('reasoning') or ''
    return reasoning + END_THINK + (end.get('response') or '') if end.get('closed_thinking') else reasoning


# ---------------------------------------------------------------- recorded runs

def read_jsonl(path):
    rows = []
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:  # a torn last line of a killed worker
                    pass
    return rows


def load_cases(run_dir):
    """(task_id, seed) -> recorded case outcome and per-slot verdicts (the last row wins if a case repeats)."""
    cases = {}
    path = Path(run_dir) / 'cases.jsonl'
    if path.exists():
        for case in read_jsonl(path):
            cases[(case.get('task_id'), case.get('seed'))] = dict(
                answered=case.get('answered'), solved=case.get('solved'), wrong=case.get('wrong'),
                verdicts={a.get('slot'): a.get('verdict') for a in case.get('agents') or []})
    return cases


def case_indices(run_dir):
    """(task_id, seed) -> case_index exactly as run_variants.main orders its jobs; {} if the plan cannot be rebuilt."""
    run_dir = Path(run_dir).resolve()
    try:
        plan = json.loads((run_dir / 'metadata.json').read_text())['protocol']
        data = json.loads((run_dir.parent.parent / plan['dataset']).read_text())
    except (OSError, KeyError, ValueError):
        return {}
    if data.get('protocol') != plan.get('dataset_protocol'):
        return {}
    tasks = [t for t in data['tasks'] if t['split'] == plan['split']]
    if plan.get('task_ids'):
        tasks = [t for t in tasks if t['id'] in plan['task_ids']]
    if plan.get('numbers_count'):
        tasks = [t for t in tasks if len(t['numbers']) == plan['numbers_count']]
    if len(tasks) != plan.get('tasks'):
        return {}
    return {(t['id'], s): si * len(tasks) + ti for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks)}


def load_agent(path, cases, indices=None):
    """One recorded agent: task, prompt inputs and its first plan request (start + end), or None if it never started."""
    path = Path(path)
    records = read_jsonl(path)
    start = next((r for r in records if r.get('type') == 'run_start'), None)
    if start is None or not isinstance(start.get('config'), dict):
        return None
    config = start['config']
    match = STEM.match(path.stem)
    task_id, seed, slot, policy = ((match['task'], int(match['seed']), int(match['slot']), match['policy'])
                                   if match else (None, None, None, None))
    numbers, target = config['puzzle'].split(':')
    req = next((r for r in records if r.get('type') == 'request_start' and r.get('stage') == 'plan'), None)
    end = next((r for r in records if r.get('type') == 'request_end' and req is not None
                and r.get('request_id') == req.get('request_id')), None)
    puzzle_end = next((r for r in reversed(records) if r.get('type') == 'puzzle_end'), {})
    plan = puzzle_end.get('plan')
    case = cases.get((task_id, seed))
    verdict = case['verdicts'].get(slot) if case else None
    return dict(path=str(path), run=path.parent.parent.name, stem=path.stem, task_id=task_id, seed=seed, slot=slot,
                policy=policy, variant=config['variant'], base_variant=VARIANT_ALIASES.get(config['variant'],
                config['variant']), agent_seed=config['seed'], puzzle=config['puzzle'],
                numbers=[int(n) for n in numbers.split(',')], target=int(target),
                extra=next((r.get('text') or '' for r in records if r.get('type') == 'extra_prompt'), ''),
                start=req, end=end, verdict=verdict, accepted=verdict is True,
                case_answered=case['answered'] if case else None, case_solved=case['solved'] if case else None,
                case_index=(indices or {}).get((task_id, seed)),
                original_plan=plan if isinstance(plan, dict) and isinstance(plan.get('moves'), list) and plan['moves']
                else None)


def load_runs(run_dirs):
    agents = []
    for run_dir in run_dirs:
        cases, indices = load_cases(run_dir), case_indices(run_dir)
        for path in sorted((Path(run_dir) / 'agents').glob('*.jsonl')):
            agent = load_agent(path, cases, indices)
            if agent is not None:
                agents.append(agent)
    return agents


def stream_problem(agent):
    """Why the recorded plan stream cannot be spliced at all (None if it can)."""
    if agent['base_variant'] not in CAPS:
        return 'unknown_variant'
    end = agent['end']
    if end is None:
        return 'no_finished_plan_stream'  # cancelled or killed before request_end
    if end.get('error') or not end.get('response_received'):
        return 'stream_error'
    ids = end.get('token_ids') or []
    reported = (end.get('usage') or {}).get('completion_tokens')
    if not ids or (reported != len(ids) and not (reported is None and end.get('finish_reason') == 'length')):
        return 'token_ids_missing_or_inconsistent'
    return None


def in_cohort(agent, cohort=None):
    """None if the agent's case is in the cohort, else the reason. cohort None = the recording's abstentions."""
    if cohort is not None:
        return None if (agent['task_id'], agent['seed']) in cohort else 'case_not_in_case_list'
    if agent['case_answered'] is None:
        return 'case_not_recorded'
    return None if agent['case_answered'] is False else 'case_answered'


def select(agent, mode, include_accepted=False, cohort=None):
    """(skip_reason, splice) for one agent; splice describes the cut for an eligible stream (estimates only)."""
    problem = in_cohort(agent, cohort) or stream_problem(agent)
    if problem:
        return problem, None
    end, (think_cap, total) = agent['end'], CAPS[agent['base_variant']]
    n_gen = len(end['token_ids'])
    if mode == 'recall':
        if end.get('finish_reason') != 'length':
            return 'not_length', None
        if end.get('closed_thinking'):
            return 'thinking_closed', None
        if n_gen != think_cap or agent['start'].get('request_max_tokens') != think_cap:
            return 'not_at_thinking_budget', None
        splice = dict(kept_tokens=n_gen, continuation_max_tokens=RECALL_MAX_TOKENS, answer_max_tokens=total - think_cap)
    else:
        text = stream_text(end)
        trigger = loop_trigger(text)
        if trigger is None:
            return 'no_loop_trigger', None
        cut = rewind_cut_char(trigger)
        estimate = round(cut * n_gen / max(1, len(text)))
        if estimate < 1:
            return 'loop_from_start', None
        splice = dict(trigger, cut_char=cut, text_chars=len(text),
                      kept_tokens_estimate=estimate, continuation_max_tokens_estimate=think_cap - estimate)
    if agent['accepted'] and not include_accepted:
        return 'accepted', None
    return None, splice


def cohort_cases(agents, cohort=None):
    return sorted({(a['run'], a['task_id'], a['seed']) for a in agents if in_cohort(a, cohort) is None})


def plan_listing(agents, mode, include_accepted=False, cohort=None):
    skipped, items = collections.Counter(), []
    for agent in agents:
        reason, splice = select(agent, mode, include_accepted, cohort)
        if reason:
            skipped[reason] += 1
            continue
        items.append(dict(run=agent['run'], stem=agent['stem'], task_id=agent['task_id'], seed=agent['seed'],
                          slot=agent['slot'], variant=agent['variant'], verdict=agent['verdict'],
                          case_answered=agent['case_answered'], finish_reason=agent['end']['finish_reason'],
                          recorded_tokens=len(agent['end']['token_ids']), **splice))
    listing = dict(mode=mode, experimental=mode in EXPERIMENTAL_MODES,
                   cohort='case_list' if cohort is not None else 'abstained', agents=len(agents),
                   cohort_cases=len(cohort_cases(agents, cohort)), eligible=len(items),
                   cases=len({(i['run'], i['task_id'], i['seed']) for i in items}),
                   skipped=dict(sorted(skipped.items())), model_calls=0, items=items)
    if cohort is not None:
        found = {(t, s) for _, t, s in cohort_cases(agents, cohort)}
        listing['case_list_missing'] = sorted([t, s] for t, s in cohort - found)
    return listing


def read_case_list(path):
    rows = json.loads(Path(path).read_text())
    if not isinstance(rows, list) or not all(isinstance(r, list) and len(r) == 2 and isinstance(r[0], str)
                                             and type(r[1]) is int for r in rows):
        raise ValueError('case list must be a JSON list of [task_id, seed]')
    cohort = {(r[0], r[1]) for r in rows}
    if len(cohort) != len(rows):
        raise ValueError('case list has duplicate cases')
    return cohort


# ---------------------------------------------------------------- one replay

class ReplayError(Exception):
    pass


def tokenize_text(client, text):
    with client.post('/tokenize', dict(model=client.model, prompt=text, add_special_tokens=False), 60) as response:
        return json.load(response)['tokens']


def experiment_for(agent, client, events):
    args = SimpleNamespace(target=agent['target'], rounds=5, seed=agent['agent_seed'], allow_fractions=False)
    e = SimpleNamespace(args=args, client=client, events=events)

    def node(state, parent_id, depth, puzzle_id, agent_id=None):
        node_id = uuid.uuid4().hex[:12]
        events.emit('node', node_id=node_id, parent_id=parent_id, state=canonical(state), depth=depth,
                    puzzle_id=puzzle_id, agent_id=agent_id)
        return node_id
    e.node = node
    return e


def timed(calls, client, stage, prompt_ids, max_tokens, **kwargs):
    t0 = time.monotonic()
    out = client.complete(0, stage, prompt_ids, max_tokens, **kwargs)
    calls.append(dict(stage=stage, request_id=out['request_id'], prompt_tokens=len(prompt_ids), max_tokens=max_tokens,
                      completion_tokens=len(out['token_ids']), finish_reason=out['finish_reason'],
                      closed_thinking=out['answer'] is not None, error=out['error'],
                      latency_s=round(time.monotonic() - t0, 3)))
    return out


def finish_like_worker(client, calls, prefix_ids, first, **context):
    """forced72.run_forced after its first call, with prefix_ids in place of the prompt ids."""
    plan, second, forced = parse_plan(first['answer']), None, False
    eligible = (plan is None and first['response_received'] and first['finish_reason'] == 'length'
                and len(first['token_ids']) > 0 and first['error'] is None)
    if eligible:
        forced = first['answer'] is None
        budget = client.budget.snapshot()
        remaining = budget['max_completion_tokens'] - budget['completion_tokens_charged']
        suffix = client.force_ids() if forced else []
        second = timed(calls, client, 'forced_answer' if forced else 'continued_answer',
                       prefix_ids + first['token_ids'] + suffix, remaining, thinking_closed=True,
                       followup_phase='forced_answer' if forced else 'continued_answer',
                       parent_request_id=first['request_id'], **context)
        answer = second['answer']
        if not forced:
            answer = first['answer'] + (second['text'] if END_THINK not in second['text'] else second['answer'])
        plan = parse_plan(answer)
    return plan, second, forced


def replay_one(agent, mode, endpoint, model, events_path):
    think_cap, total = CAPS[agent['base_variant']]
    end, gen = agent['end'], agent['end']['token_ids']
    record = dict(mode=mode, experimental=mode in EXPERIMENTAL_MODES, run=agent['run'], agent_file=agent['path'], stem=agent['stem'], task_id=agent['task_id'],
                  seed=agent['seed'], slot=agent['slot'], policy=agent['policy'], variant=agent['variant'],
                  agent_seed=agent['agent_seed'], numbers=agent['numbers'], target=agent['target'], endpoint=endpoint,
                  events=str(events_path),
                  original=dict(request_id=end['request_id'], finish_reason=end['finish_reason'],
                                tokens=len(gen), closed_thinking=end.get('closed_thinking'), verdict=agent['verdict'],
                                plan=agent['original_plan']),
                  case_answered=agent['case_answered'], case_solved=agent['case_solved'],
                  case_index=agent['case_index'],
                  started_at=datetime.now(timezone.utc).isoformat(), calls=[], plan=None, candidate=None,
                  verifier_solved=None, error=None, verdict=None, accept_kind=None)
    t0 = time.monotonic()
    events = Events(events_path, f'tail_{mode}')
    try:
        if mode == 'recall':
            budget = Budget(2, RECALL_MAX_TOKENS + total - think_cap)
        else:
            budget = Budget(2, total)  # resized below once the kept length is known
        client = ForcedClient(endpoint, model, budget, events, agent['agent_seed'])
        e = experiment_for(agent, client, events)
        initial, target = parse_puzzle(agent['puzzle'])
        puzzle_id = 'p0-' + fingerprint(initial, target)[:10]
        events.emit('replay_start', mode=mode, source=agent['path'], parent_request_id=end['request_id'],
                    puzzle_id=puzzle_id, target=target, state=canonical(initial))
        prompt_ids = client.chat_prompt_ids(task_prompt(e, initial, agent['base_variant'], agent['extra']))
        if sha(json.dumps(prompt_ids)) != agent['start']['prompt_ids_sha256']:
            raise ReplayError('prompt ids differ from the recorded prompt_ids_sha256')
        context = dict(puzzle_id=puzzle_id, variant=agent['variant'], replay_mode=mode,
                       source_request_id=end['request_id'])
        if mode == 'recall':
            kept = len(gen)
            text = recall_text(agent['numbers'], agent['target'])
            cont_max = RECALL_MAX_TOKENS
            stage = 'recall'
            record['splice'] = dict(kept_tokens=kept, dropped_tokens=0, recall_values=recall_values(
                agent['numbers'], agent['target']))
        else:
            full = stream_text(end)
            trigger = loop_trigger(full)
            if trigger is None:
                raise ReplayError('loop detector does not fire on the recorded stream')
            cut = rewind_cut_char(trigger)
            a, b = len(tokenize_text(client, full[:cut])), len(tokenize_text(client, full))
            kept = min(len(gen), round(a * len(gen) / max(1, b)))
            cont_max = think_cap - kept
            if kept < 1 or cont_max < 1:
                raise ReplayError(f'nothing to rewind to (kept {kept}, continuation {cont_max})')
            client.budget = budget = Budget(2, total - kept)
            text, stage = NUDGE, 'rewind'
            record['splice'] = dict(trigger, cut_char=cut, kept_tokens=kept, dropped_tokens=len(gen) - kept,
                                    retokenized_prefix=a, retokenized_stream=b)
        inserted = tokenize_text(client, text)
        record['splice'].update(inserted_text=text, inserted_tokens=len(inserted), continuation_max_tokens=cont_max)
        prefix = prompt_ids + gen[:kept] + inserted
        events.emit('replay_splice', **record['splice'])
        first = timed(record['calls'], client, stage, prefix, cont_max, followup_phase=stage, **context)
        plan, second, forced = finish_like_worker(client, record['calls'], prefix, first, **context)
        if mode == 'rewind':
            record['continuation_loop_trigger'] = loop_trigger(full[:cut] + text + first['text'])
        result = replay_plan(e, initial, e.node(initial, None, 0, puzzle_id, 0), plan, puzzle_id, 0)
        parsed = isinstance(plan, dict) and isinstance(plan.get('moves'), list) and bool(plan['moves'])
        record.update(plan=plan if parsed else None, verifier_solved=bool(result['solved']), budget_forced=forced,
                      answer_continued=bool(second) and not forced,
                      continuation_tokens=len(first['token_ids']),
                      answer_tokens=len(second['token_ids']) if second else 0,
                      continuation_closed_thinking=first['answer'] is not None,
                      infra_failures=client.infra_failures, budget=client.budget.snapshot())
        record['tokens_generated'] = record['continuation_tokens'] + record['answer_tokens']
        if record['plan'] is not None:
            record['candidate'] = dict(numbers=agent['numbers'], target=agent['target'], plan=record['plan'])
        errors = [c['error'] for c in record['calls'] if c['error']]
        record['error'] = errors[0] if errors else None
    except Exception as exc:  # one replay's fault never stops the others; it is recorded
        record['error'] = f'{type(exc).__name__}: {str(exc)[:300]}'
    finally:
        record['wall_s'] = round(time.monotonic() - t0, 3)
        events.emit('replay_end', error=record['error'], plan=record['plan'], wall_s=record['wall_s'])
        events.close()
    return record


# ---------------------------------------------------------------- driver

def judge_seed(agent):
    return JUDGE_SEED_BASE + 1000 * agent['seed'] + 10 * agent['case_index'] + agent['slot']


def judge_record(record, agent, endpoint, events_path, judge):
    """Judge a replay plan like run_variants.run_agent (same judge, same seed formula) and classify an accept."""
    if record['candidate'] is None:
        return record
    if agent['case_index'] is None:
        record['judge_error'] = 'case_index unknown (metadata/corpus not found): no paired judge seed'
        return record
    record['judge_seed'] = judge_seed(agent)
    try:
        out = judge(record['candidate'], endpoint, events_path, record['judge_seed'])
    except Exception as exc:  # recorded, never fatal for the other replays
        record['judge_error'] = f'{type(exc).__name__}: {str(exc)[:300]}'
        return record
    record.update(verdict=out.get('verdict'), judge_reason=out.get('reason', ''), judge_tokens=out.get('tokens'),
                  judge_infra=out.get('infra'), judge_events=str(events_path))
    if record['verdict'] is True:
        record['accept_kind'] = 'case_rescue' if agent['case_answered'] is False else 'agent_accept'
    return record


def case_rows(agents, records, cohort=None):
    """One row per cohort case: did any replay plan get accepted, and is that a new case rescue?"""
    by_case = collections.defaultdict(list)
    for record in records:
        by_case[(record['run'], record['task_id'], record['seed'])].append(record)
    info = {(a['run'], a['task_id'], a['seed']): a for a in agents}
    rows = []
    for key in cohort_cases(agents, cohort):
        recs, agent = by_case.get(key, []), info[key]
        accepted = [r for r in recs if r.get('verdict') is True]
        rows.append(dict(run=key[0], task_id=key[1], seed=key[2], recorded_answered=agent['case_answered'],
                         recorded_solved=agent['case_solved'], replays=len(recs),
                         replay_errors=sum(r['error'] is not None for r in recs),
                         replay_plans=sum(r['plan'] is not None for r in recs),
                         judge_accepted=len(accepted), judge_accepted_verifier_solved=sum(
                             bool(r['verifier_solved']) for r in accepted),
                         judge_accepted_wrong=sum(not r['verifier_solved'] for r in accepted),
                         outcome=('case_rescue' if accepted and agent['case_answered'] is False else
                                  'agent_accept' if accepted else 'none'),
                         accepted_stems=sorted(r['stem'] for r in accepted),
                         tokens_generated=sum(r.get('tokens_generated') or 0 for r in recs)))
    return rows


def load_judge(source):
    """run_variants.judge_with_reason from the main tree, read-only. Modules this tree already provides (forced72,
    harness, run_benchmark) stay this tree's; harness and run_benchmark are byte-identical to the main tree."""
    import sys
    if str(source) not in sys.path:
        sys.path.append(str(source))
    sys.dont_write_bytecode = True  # read-only: no __pycache__ writes into that tree
    import run_variants
    return run_variants.judge_with_reason


def run_replays(agents, mode, endpoints, output, per_endpoint, model, include_accepted=False, cohort=None,
                judge=None):
    if not 1 <= per_endpoint <= MAX_CONCURRENCY:
        raise ValueError(f'--max-concurrency must be 1..{MAX_CONCURRENCY}')
    items = [a for a in agents if select(a, mode, include_accepted, cohort)[0] is None]
    output = Path(output)
    events_dir = output.with_name(output.name + '.events')
    cases_path = output.with_name(output.name.removesuffix('.jsonl') + '.cases.jsonl')
    if cases_path.exists():
        raise FileExistsError(cases_path)
    events_dir.mkdir(parents=True, exist_ok=True)
    slots = {e: threading.BoundedSemaphore(per_endpoint) for e in endpoints}
    lock, summary, records = threading.Lock(), collections.Counter(), []

    def job(index, agent):
        endpoint = endpoints[index % len(endpoints)]
        name = f"{agent['run']}__{agent['stem']}-{mode}"
        with slots[endpoint]:
            record = replay_one(agent, mode, endpoint, model, events_dir / f'{name}.jsonl')
            if judge is not None:
                judge_record(record, agent, endpoint, events_dir / f'{name}-judge.jsonl', judge)
        return record

    with output.open('x', encoding='utf-8') as sink, \
            ThreadPoolExecutor(max_workers=per_endpoint * len(endpoints)) as pool:
        for future in as_completed([pool.submit(job, i, a) for i, a in enumerate(items)]):
            record = future.result()
            with lock:
                records.append(record)
                sink.write(json.dumps(record, ensure_ascii=False) + '\n')
                sink.flush()
                summary['replays'] += 1
                summary['errors'] += record['error'] is not None
                summary['plans'] += record['plan'] is not None
                summary['judge_accepted'] += record['verdict'] is True
                summary['judge_accepted_wrong'] += record['verdict'] is True and not record['verifier_solved']
                summary['tokens_generated'] += record.get('tokens_generated') or 0
    rows = case_rows(agents, records, cohort)
    with cases_path.open('x', encoding='utf-8') as sink:
        for row in rows:
            sink.write(json.dumps(row) + '\n')
    outcomes = collections.Counter(r['outcome'] for r in rows)
    return dict(mode=mode, experimental=mode in EXPERIMENTAL_MODES, judged=judge is not None, output=str(output),
                cases_output=str(cases_path), cohort_cases=len(rows), case_rescues=outcomes['case_rescue'],
                agent_accept_cases=outcomes['agent_accept'], **summary)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--runs', nargs='+', required=True, help='recorded run directories (each with agents/*.jsonl)')
    p.add_argument('--mode', choices=('recall', 'rewind'), required=True,
                   help='recall (idea 4) | rewind (idea 3, EXPERIMENTAL: approximate offline trigger and cut)')
    p.add_argument('--case-list', type=Path, help='JSON list of [task_id, seed]: the frozen cohort '
                   '(default: the cases the recorded run did not answer)')
    p.add_argument('--no-judge', action='store_true', help='do not judge replay plans')
    p.add_argument('--judge-source', type=Path, default=Path(__file__).resolve().parents[2],
                   help='tree with run_variants.py for judge_with_reason (default: the main tree)')
    p.add_argument('--endpoint', action='append', default=[], help='shim base URL, e.g. http://127.0.0.1:18081/v1 '
                   '(repeat for several; replays are spread round-robin)')
    p.add_argument('--output', type=Path, help='JSONL of replay records (must not exist); events go to OUTPUT.events/')
    p.add_argument('--max-concurrency', type=int, default=8, help=f'per endpoint, 1..{MAX_CONCURRENCY} (default 8)')
    p.add_argument('--model', default='nemotron-lightning')
    p.add_argument('--include-accepted', action='store_true', help='also replay agents whose plan the judge accepted')
    p.add_argument('--plan-only', action='store_true', help='list what would be replayed; 0 model calls')
    args = p.parse_args(argv)
    if not 1 <= args.max_concurrency <= MAX_CONCURRENCY:
        p.error(f'--max-concurrency must be 1..{MAX_CONCURRENCY}')
    cohort = read_case_list(args.case_list) if args.case_list else None
    agents = load_runs(args.runs)
    if args.plan_only:
        print(json.dumps(plan_listing(agents, args.mode, args.include_accepted, cohort)))
        return 0
    if not args.endpoint or args.output is None:
        p.error('--endpoint and --output are required unless --plan-only')
    judge = None if args.no_judge else load_judge(args.judge_source)
    print(json.dumps(run_replays(agents, args.mode, args.endpoint, args.output, args.max_concurrency, args.model,
                                 args.include_accepted, cohort, judge)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
