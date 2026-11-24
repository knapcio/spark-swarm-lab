#!/usr/bin/env python3
"""Development screen of swarm variants (all arbiter-free; a Nemotron thinking judge selects).

Policies, each with 4 deep agents (long_forced_original, 16K) per case:
  deep4      4 identical independent agents -> judge -> first accepted
  strategy4  4 independent agents, each with a different task-agnostic strategy hint
  repair4    sequential: agent -> judge with reason -> if rejected, next agent sees its plan + critique
  board2x2   round 1: 2 agents; if none accepted, round 2: 2 agents see all round-1 plans + critiques
  deep4cancel   deep4, but the first judge-accepted plan (in time) is the answer and stops the case at once:
                running agents are terminated, agents and judges not yet started never start
  waves2cancel  agents 0+1 in parallel with the same cancel rule; agents 2+3 only if neither was accepted
  roll8cancel   deep4cancel with adaptive escalation: 4 agents in flight; each agent that ends without an accepted
                plan is replaced at once by a fresh-seed agent on the same node, up to 8 agents in total
  roll8repair   roll8cancel, but each escalation agent (slot >= 4) also sees every plan of this case that the judge has
                rejected so far, with the judge's one-sentence reason (the repair4 critique text)
  roll3to8      roll8cancel with 3 agents in flight instead of 4 (failures replaced by fresh-seed agents up to 8 in total)
  roll3strategy roll8strategy with 3 agents in flight instead of 4 (escalation agents, slot >= 3, get the strategy hints)
  roll12strategy roll8strategy with a cap of 12 agents (failure-driven only, no time trigger)
  roll12cancel  roll8cancel with a cap of 12 agents: roll12strategy WITHOUT any hint (generic: no task-specific text for
                any slot); same seeds, nodes, race and cancel
  roll12idle    roll12cancel plus generic idle-capacity escalation: once a case's slots 0-11 have all ended without an
                accepted plan, extra agents (slots 12-19, no hints) start one at a time on the least-loaded node, only
                while that node has fewer than IDLE_THRESHOLD requests in flight in the shared slots (permits held by
                agents and judges of all cases), at most IDLE_MAX_INFLIGHT extra agents in flight per case; occupancy is
                re-checked whenever any request of any case releases its slot (or every IDLE_POLL_SECONDS); never
                time-triggered. Admission is atomic (least-loaded node + non-blocking permit under one lock, logged
                occupancy exact); the extra agents' judges are idle-gated the same way. A roll12idle arm runs alone
                and is the only policy that uses TrackedSlots. Slots 0-11 pair exactly with roll12cancel (seeds
                1000*seed + offset + slot).
  roll8strategy roll8cancel, but each escalation agent (slot >= 4) gets one of the four task-agnostic strategy hints
                (STRATEGIES[slot - 4]); the first four agents are unchanged
  esc_none, esc_strategy, esc_h02, esc_split
                escalation-only arms for a shared first wave (deep4cancel run once): slots 4-11 only, 4 in flight,
                failure-driven replacement, cancel on accept, on the plan's case_list (cases whose first wave had no
                accepted plan). Hints per escalation slot: none / STRATEGIES[(slot-4)%4] (as roll12strategy) /
                STRATEGIES[(0, 2)[(slot-4)%2]] / SPLIT_HINTS[(slot-4)%4] (partition of the last move).
  esc_extra     idle-capacity add-on (round-3 idea 2) for cases whose first twelve agents failed: slots 12-19 all in
                flight at once (8 per case, two per node), cap 20, hints STRATEGIES[(slot-4)%4] (continuing the default's
                hint cycle), cancel on accept, on the plan's case_list. Per-node requests stay capped by Slots (<= 25).
  roll12burst   roll8cancel with a cap of 12 agents and a time trigger: if no plan is accepted BURST_SECONDS after the
                case started, 8 agents are kept in flight instead of 4 (failures still replaced, first accept cancels)
Every agent record carries timing (seconds from case start); decisions of the original policies are unchanged.
A judge call lost to transport (connection refused / reset / disconnected, stream ended without a result) is retried
once after JUDGE_RETRY_SECONDS with the same seed (agent fields judge_retry, judge_attempts); only a failed retry counts
as infra. Client-side limits (wall limit, timeouts, budget) are never retried.
The exact verifier never influences decisions; it only scores the selected plan.
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from run_agents72 import read, require, sha, validate_source, write
from run_arbiterfree import ENDPOINTS, Slots, plan_of
from run_benchmark import append_controller_stop, execute, metrics, read_trace, terminate
import run_judge

HERE = Path(__file__).resolve().parent
STRATEGIES = [
    'Strategy hint: work backward from the target. Factor it or write it as a sum/difference of numbers you can build.',
    'Strategy hint: look for a product of two available numbers (or of a number and a small built value) close to the target, then adjust.',
    'Strategy hint: consider using every number; subtraction and division can create the small values you need.',
    'Strategy hint: build one large intermediate from the biggest numbers first, then correct it with the small numbers.',
]
SPLIT_HINTS = [
    'Strategy hint: assume the last move subtracts one of the given numbers x. For each x, compute target + x and try to build that value from the other numbers; first list what small groups of the other numbers can make.',
    'Strategy hint: assume the last move adds one of the given numbers x. For each x, compute target - x and try to build that value from the other numbers; first list what small groups of the other numbers can make.',
    'Strategy hint: assume the last move multiplies or divides by one of the given numbers x. For each x, try to build target / x (when it is a whole number) or target * x from the other numbers; first list what small groups of the other numbers can make.',
    'Strategy hint: assume the last move combines two values that are each built from different numbers. Split the numbers into two groups, list what each group can make, and look for a pair that gives the target in one operation.',
]
ESC_HINTS = {'esc_none': lambda slot: '', 'esc_strategy': lambda slot: STRATEGIES[(slot - 4) % 4],
             'esc_h02': lambda slot: STRATEGIES[(0, 2)[(slot - 4) % 2]], 'esc_split': lambda slot: SPLIT_HINTS[(slot - 4) % 4],
             'esc_extra': lambda slot: STRATEGIES[(slot - 4) % 4]}
# escalation-only arms: (first slot, agents in flight, end slot exclusive); default slots 4-11, 4 in flight
ESC_SHAPE = {'esc_extra': (12, 8, 20)}
ESC_DEFAULT_SHAPE = (4, 4, 12)
PAIRED_ADDONS = {'esc_extra'}
ADDON_DEFAULT_POLICY = 'roll12strategy'  # the only baseline an add-on may pair with  # add-on arms on a recorded default arm's clean abstentions (check_pairing)
MAX_REQUESTS_PER_NODE = 25  # fleet rule: never more than 25 concurrent requests on one Spark
# rolling policies: slots that may launch per case (cap - first slot); unstarted_agents counts the ones that never did
IDLE_FIRST, IDLE_CAP, IDLE_THRESHOLD, IDLE_MAX_INFLIGHT, IDLE_POLL_SECONDS = 12, 20, 12, 8, 2.0
ELIGIBLE_SLOTS = dict(roll8cancel=8, roll8repair=8, roll8strategy=8, roll3to8=8, roll3strategy=8, roll12strategy=12,
                      roll12cancel=12, roll12idle=12,  # roll12idle: extra slots 12-19 are opportunistic, not eligible
                      roll12burst=12, **{p: ESC_SHAPE.get(p, ESC_DEFAULT_SHAPE)[2] - ESC_SHAPE.get(p, ESC_DEFAULT_SHAPE)[0]
                                         for p in ESC_HINTS})
JUDGE_TAIL = 'Return only a JSON object {"valid": true} if every move is legal and the target appears, otherwise {"valid": false}.'
REASON_TAIL = ('Return only a JSON object {"valid": true} if every move is legal and the target appears; otherwise '
               '{"valid": false, "reason": "<one sentence: the first illegal move, or why the target never appears>"}.')
JUDGE_RETRY_SECONDS = 2
# Transport LOSS only: the connection or the stream was lost before a result arrived. Client-side limits (wall limit,
# idle/socket timeout, deadline, budget), accounting mismatches, HTTP status errors and server-reported errors that are
# not a disconnect are never retried.
LOSS_TYPES = {'ConnectionRefusedError', 'ConnectionResetError', 'ConnectionAbortedError', 'BrokenPipeError',
              'RemoteDisconnected', 'IncompleteRead', 'JSONDecodeError'}  # JSONDecodeError = truncated stream frame
LOSS_MARKERS = ('connection refused', 'connection reset', 'connection aborted', 'disconnected', 'remote end closed',
                'broken pipe', 'stream ended without finish_reason', 'incompleteread', 'unexpected eof')
LOCAL_LIMIT_MARKERS = ('timed out', 'timeout', 'wall limit', 'deadline', 'budget')


def transport_error(error):
    """True for a request error string (as ForcedClient records it: 'ExcType: message') that is a transport loss:
    connection refused / reset / disconnected, a server stream error reporting a disconnect, or a stream that ended
    without a result (EOF, truncated frame). False for the client's own limits and every other fault."""
    if not error:
        return False
    kind, _, message = str(error).partition(':')
    kind, text = kind.strip(), str(error).lower()
    if any(m in text for m in LOCAL_LIMIT_MARKERS):
        return False
    if kind in LOSS_TYPES:
        return True
    return kind in ('ConnectionError', 'URLError', 'OSError') and any(m in message.lower() for m in LOSS_MARKERS)


class JudgeFault(RuntimeError):
    """A judge attempt raised (not a recorded request error); .record keeps every attempt's charges and errors."""
    def __init__(self, message, record):
        super().__init__(message)
        self.record = record


def judge_with_reason(candidate, endpoint, events_path, seed):
    """Thinking judge with a one-sentence reason (judge_once). An attempt that failed by transport loss is retried once
    after JUDGE_RETRY_SECONDS with the same seed (events in <stem>.retry.jsonl). A clean first call returns exactly as
    before (verdict, reason, infra, tokens). After a retry or any fault the record also holds judge_attempts (tokens,
    infra, error per attempt; tokens is their sum); if the last attempt raised, JudgeFault carries that record."""
    attempts = [judge_once(candidate, endpoint, events_path, seed)]
    if attempts[0]['infra'] and attempts[0]['retryable']:
        time.sleep(JUDGE_RETRY_SECONDS)
        attempts.append(judge_once(candidate, endpoint, Path(events_path).with_suffix('.retry.jsonl'), seed))
    last = attempts[-1]
    out = dict(verdict=last['verdict'], reason=last['reason'], infra=last['infra'], tokens=sum(a['tokens'] for a in attempts))
    if len(attempts) > 1:
        out.update(retry=True, first_error=attempts[0]['error'])
    if any(a.get('trace_error') for a in attempts):
        out['trace_error'] = next(a['trace_error'] for a in attempts if a.get('trace_error'))
    if len(attempts) > 1 or any(a['infra'] for a in attempts):
        out['judge_attempts'] = [dict({k: a[k] for k in ('tokens', 'infra', 'error', 'raised', 'verdict', 'retryable')},
                                      **({'trace_error': a['trace_error']} if a.get('trace_error') else {}))
                                 for a in attempts]
    if last['raised']:
        raise JudgeFault(last['error'], out)
    return out


class GuardedEvents:
    """run_judge.Events whose writes and close never raise: the first OSError is kept as .error (trace_error), so a
    failing trace never drops an attempt's accounting (which is also held in memory)."""
    def __init__(self, path, method):
        self.error = None
        self.inner = run_judge.Events(path, method)  # opening may raise; callers record that as a failed attempt
        self.path = self.inner.path

    def emit(self, kind, **fields):
        try:
            return self.inner.emit(kind, **fields)
        except (OSError, ValueError) as exc:  # ValueError: write to a closed file
            self.error = self.error or f'{type(exc).__name__}: {exc}'[:300]
            return None

    def close(self):
        try:
            self.inner.close()
        except (OSError, ValueError) as exc:
            self.error = self.error or f'{type(exc).__name__}: {exc}'[:300]


def with_trace_error(out, events):
    """A trace that could not be written is an infra fault of its attempt (never retried); accounting is kept."""
    if events.error:
        out.update(trace_error=events.error, infra=out['infra'] + 1, retryable=False)
    return out


def raised_is_retryable(exc):
    """A raised exception is transport loss only if it is a lost connection; a malformed response body (e.g.
    JSONDecodeError from /tokenize) is a server error and never retried."""
    return not isinstance(exc, ValueError) and transport_error(f'{type(exc).__name__}: {exc}')


def judge_once(candidate, endpoint, events_path, seed):
    """One attempt of the thinking judge (same prompt and budgets as before). Never raises: an exception (the trace
    cannot be opened or written, /tokenize refused after the first completion, ...) is recorded with the tokens already
    charged. Returns verdict, reason, infra, tokens, error (first transport-loss error, else first error), raised,
    retryable and, if the trace failed, trace_error."""
    try:
        events = GuardedEvents(events_path, 'judge_reason')
    except Exception as exc:  # nothing was sent; the attempt is an infra fault held in memory
        return dict(verdict=None, reason='', infra=1, tokens=0, error=f'{type(exc).__name__}: {exc}'[:300], raised=True,
                    retryable=False)
    errors, client = [], None
    try:
        client = run_judge.ChatJudge(endpoint, 'nemotron-lightning', run_judge.Budget(2, 8192), events, seed)
        prompt = run_judge.judge_prompt(candidate['numbers'], candidate['target'], candidate['plan'])
        require(prompt.endswith(JUDGE_TAIL), 'judge prompt changed')
        prompt = prompt[:-len(JUDGE_TAIL)] + REASON_TAIL
        ids = client.chat_prompt_ids(prompt, thinking=True)
        first = client.complete(0, 'judge', ids, 6144)
        errors.append(first['error'])
        answer = first['answer']
        if answer is None and first['finish_reason'] == 'length' and first['error'] is None:
            second = client.complete(0, 'judge_forced', ids + first['token_ids'] + client.force_ids(),
                                     8192 - client.budget.snapshot()['completion_tokens_charged'], thinking_closed=True)
            errors.append(second['error'])
            answer = second['answer']
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'[:300]
        out = dict(verdict=None, reason='', infra=(client.infra_failures if client else 0) + 1,
                   tokens=client.budget.snapshot()['completion_tokens_charged'] if client else 0)
        events.emit('judge_end', error=error, **out)
        events.close()
        return with_trace_error(dict(out, error=error, raised=True, retryable=raised_is_retryable(exc)), events)
    verdict, reason = None, ''
    try:
        value = json.loads((answer or '').strip().strip('`').removeprefix('json').strip())
        if isinstance(value, dict) and isinstance(value.get('valid'), bool):
            verdict, reason = value['valid'], str(value.get('reason', ''))[:300]
    except ValueError:
        pass
    out = dict(verdict=verdict, reason=reason, infra=client.infra_failures,
               tokens=client.budget.snapshot()['completion_tokens_charged'])
    events.emit('judge_end', **out)
    events.close()
    errors = [str(e)[:300] for e in errors if e]
    error = next((e for e in errors if transport_error(e)), errors[0] if errors else None)
    return with_trace_error(dict(out, error=error, raised=False, retryable=transport_error(error)), events)


def judge_fields(j):
    """Agent-record fields of a judge record (judge_with_reason result or JudgeFault.record)."""
    f = dict(verdict=j['verdict'], reason=j['reason'], judge_tokens=j['tokens'], judge_infra=j['infra'],
             judge_retry=bool(j.get('retry')))
    if j.get('retry'):
        f['judge_first_error'] = j['first_error']
    if 'judge_attempts' in j:
        f['judge_attempts'] = j['judge_attempts']
    if j.get('trace_error'):
        f['judge_trace_error'] = j['trace_error']
    return f


def fault_record(slot, extra, exc):
    """Agent record for a controller exception: an infra fault that keeps whatever the agent already recorded
    (exc.partial_info from run_agent: worker tokens, judge attempts and charges, retry fields)."""
    info = dict(plan=None, verifier_solved=False, tokens=0, infra=0, slot=slot, extra=bool(extra), deadline=False,
                verdict=None, reason='', judge_tokens=0, judge_infra=0, judge_retry=False, started=True,
                cancelled=False, judge_skipped=False)
    info.update(getattr(exc, 'partial_info', None) or {})
    info.update(slot=slot, infra=info['infra'] + 1, agent_error=f'{type(exc).__name__}: {exc}'[:300])
    return info


def execute_cancellable(case, deadline_seconds, cancel):
    """run_benchmark.execute for a shared endpoint plus a cancel event: when it is set, the worker's process group is
    terminated (killpg) and the row is marked cancelled. run_benchmark.py itself is hash-pinned by earlier frozen
    plans, so it stays unchanged; this loop keeps its process-group, deadline and terminate semantics."""
    start = time.monotonic()
    deadline = cancelled = False
    error = returncode = None
    with Path(case['stdout']).open('x') as stdout, Path(case['stderr']).open('x') as stderr:
        try:
            process = subprocess.Popen(case['command'], cwd=HERE, stdout=stdout, stderr=stderr, start_new_session=True)
            while True:
                if process.poll() is not None:
                    returncode = process.returncode
                    break
                if cancel.is_set():
                    cancelled, returncode = True, terminate(process)
                    break
                if time.monotonic() - start >= deadline_seconds:
                    deadline, returncode = True, terminate(process)
                    break
                time.sleep(.1)
        except OSError as exc:
            error = f'{type(exc).__name__}: {exc}'
    trace = Path(case['events'])
    records, _ = read_trace(trace)
    row = dict(metrics(records, deadline), returncode=returncode, controller_error=error, deadline=deadline,
               cancelled=cancelled, wall_seconds=round(time.monotonic() - start, 6), controller_stop=cancelled or deadline,
               server_cost_known=False, server_cost_reason='shared_endpoint', server_prompt_tokens=None,
               server_completion_tokens=None, server_idle_after=None, time_to_verified_solution_seconds=None)
    if cancelled:
        row.update(status='cancelled', solved=False)
    if row['controller_stop']:
        append_controller_stop(trace, records, row, case)
    return row


def run_agent(plan, source, out, task, seed, case_index, policy, slot, extra, slots, seed_offset, t0=None, race=None,
              node=None, endpoints=None, agent_seed=None):
    """One agent + its judge. race (cancel policies): dict(cancel=Event, accept=callable) shared by the case.
    node: endpoint index override (escalation agents run on the node of the agent they replace).
    endpoints: endpoint list override (default the four tunnels; slots must cover the same endpoints).
    agent_seed: explicit worker seed (replay drivers); default 1000*seed + seed_offset + slot as everywhere."""
    t0 = time.monotonic() if t0 is None else t0
    cancel = race['cancel'] if race else None
    endpoints = endpoints or ENDPOINTS
    endpoint = endpoints[(case_index + slot) % len(endpoints) if node is None else node]
    stem = f"{task['id']}-s{seed}-{policy}-a{slot}"
    events = out / 'agents' / (stem + '.jsonl')
    extra_file = None
    if extra:
        extra_file = out / 'extra' / (stem + '.txt')
        extra_file.write_text(extra)
    command = [sys.executable, str(source / 'forced72_worker.py'), '--run', '--variant', plan['agent_variant'],
               '--puzzle', ','.join(map(str, task['numbers'])) + ':' + str(task['target']), '--endpoint', endpoint,
               '--seed', str(1000 * seed + seed_offset + slot if agent_seed is None else agent_seed), '--events', str(events),
               '--model', 'nemotron-lightning']
    if extra_file:
        command[2:2] = ['--extra-file', str(extra_file)]
    job = dict(task_id=task['id'], split='development', arm=policy, seed=seed, endpoint=endpoint, command=command,
               events=str(events), stdout=str(events).replace('.jsonl', '.stdout.log'),
               stderr=str(events).replace('.jsonl', '.stderr.log'), shared_endpoint=True, stop_on_solution=False)
    timing = dict(queued_s=round(time.monotonic() - t0, 3))
    with slots(endpoint):
        if cancel is not None and cancel.is_set():  # case already answered while this agent waited for a slot
            return dict(plan=None, verifier_solved=False, tokens=0, infra=0, slot=slot, extra=bool(extra), deadline=False,
                        verdict=None, reason='', judge_tokens=0, judge_infra=0, judge_retry=False, started=False,
                        cancelled=False, judge_skipped=False, **timing)
        timing['started_s'] = round(time.monotonic() - t0, 3)
        if race:
            row = execute_cancellable(job, plan['agent_wall_deadline_seconds'], cancel)
        else:
            row = execute(job, deadline_seconds=plan['agent_wall_deadline_seconds'])
    timing['finished_s'] = round(time.monotonic() - t0, 3)
    cancelled = bool(row.get('cancelled'))
    info = plan_of(events)
    if cancelled:
        info['plan'] = None  # a terminated agent has no answer; its partial work is counted server-side
    elif row.get('controller_error') or (row.get('returncode') not in (0, None) and not row['deadline']):
        info['infra'] += 1  # worker process failure: stop admissions, never a silent 'no plan'
    info.update(slot=slot, extra=bool(extra), deadline=bool(row['deadline']), verdict=None, reason='', judge_tokens=0, judge_infra=0,
                judge_retry=False)
    if race:
        info.update(started=True, cancelled=cancelled, judge_skipped=False)
    if info['plan'] is not None:
        cand = dict(numbers=task['numbers'], target=task['target'], plan=info['plan'])
        with slots(endpoint):
            if cancel is not None and cancel.is_set():
                info['judge_skipped'] = True
            else:
                try:
                    j = judge_with_reason(cand, endpoint, out / 'judges' / (stem + '.jsonl'),
                                          90000 + 1000 * seed + 10 * case_index + slot)
                except Exception as exc:  # keep the agent's and the judge's charges for the fault record (fault_record)
                    if isinstance(exc, JudgeFault):
                        info.update(judge_fields(exc.record))
                    exc.partial_info = dict(info, **timing)
                    raise
                info.update(judge_fields(j))
                timing['judged_s'] = round(time.monotonic() - t0, 3)
                if race and info['verdict'] is True:
                    race['accept'](slot)
    info.update(timing)
    return info


def run_agent_safe(plan, source, out, task, seed, case_index, policy, slot, extra, *args, **kwargs):
    """run_agent for every policy path: a controller exception (worker launch, JudgeFault, ...) becomes the agent's
    fault record (fault_record: infra, agent_error, every charge and judge attempt kept), never a lost or None agent."""
    try:
        return run_agent(plan, source, out, task, seed, case_index, policy, slot, extra, *args, **kwargs)
    except Exception as exc:
        return fault_record(slot, extra, exc)


def parallel(fns):
    results = [None] * len(fns)
    threads = [threading.Thread(target=lambda i=i, f=f: results.__setitem__(i, f())) for i, f in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def critique(info):
    if info['plan'] is None:
        return 'A previous attempt produced no complete plan.'
    return f"A previous attempt proposed {json.dumps(info['plan'])}; a careful checker rejected it: {info['reason'] or 'invalid'}."


def rolling(agent, race, case_index, width=4, cap=8, burst_seconds=None, burst_width=8, feedback=None, first=0):
    """Keep `width` agents in flight; an agent that ends without an accept is replaced by the next slot on its node.
    burst_seconds: if the case has no accept by then, raise the in-flight width to burst_width (new slots on nodes
    (case_index + slot) % 4), still within `cap` agents in total. first: number of the first slot (escalation-only arms
    start at 4; `cap` is then the end slot, exclusive)."""
    lock, state, results, threads = threading.Lock(), dict(next=first + width, running=0, width=width), [], []

    def launch(slot, node):  # caller holds the lock
        state['running'] += 1
        extra = feedback(list(results)) if feedback and slot >= width else None
        t = threading.Thread(target=run, args=(slot, node, extra))
        threads.append(t)
        t.start()

    def run(slot, node, extra=None):
        try:
            info = agent(slot, node, extra) if feedback else agent(slot, node)
        except Exception as exc:  # never lose a slot: record it as an infra fault (resume reruns the case)
            info = fault_record(slot, extra, exc)
        with lock:
            results.append(info)
            state['running'] -= 1
            if 'agent_error' in info:
                state['failed'] = True  # no replacements after a controller fault; running agents end normally
            while (race['winner'] is None and not race['cancel'].is_set() and not state.get('failed') and state['next'] < cap
                   and state['running'] < state['width']):
                nxt = state['next']
                state['next'] += 1
                launch(nxt, node if state['running'] == state['width'] - 1 else (case_index + nxt) % 4)

    def burst():
        if race['cancel'].wait(burst_seconds):
            return
        with lock:
            if race['winner'] is not None or state.get('closed') or state.get('failed'):
                return
            state['width'] = burst_width
            race['burst_at'] = True
            while state['next'] < cap and state['running'] < state['width']:
                nxt = state['next']
                state['next'] += 1
                launch(nxt, (case_index + nxt) % 4)
    with lock:
        for s in range(first, first + width):
            launch(s, (case_index + s) % 4)
    if burst_seconds is not None:
        timer = threading.Thread(target=burst, daemon=True)
        timer.start()
    i = 0
    while True:
        with lock:
            if i >= len(threads):
                state['closed'] = True  # a late burst timer must not start agents for a finished case
                break
            t = threads[i]
        t.join()
        i += 1
    return sorted(results, key=lambda a: a['slot'])


class TrackedSlots(Slots):
    """Slots with occupancy, used ONLY by roll12idle arms (every other policy keeps the plain Slots): the same
    per-endpoint semaphores, but every acquisition happens under one condition lock with a non-blocking try-acquire, so
    in_flight[endpoint] (permits held by agents and judges) is exact whenever the lock is held; every release notifies
    the condition."""
    def __init__(self, per_endpoint, endpoints=None):
        super().__init__(per_endpoint)
        self.endpoints = list(endpoints or ENDPOINTS)
        if endpoints:
            self.sem = {e: threading.BoundedSemaphore(per_endpoint) for e in self.endpoints}
        self.cap = per_endpoint
        self.cond = threading.Condition()
        self.in_flight = {e: 0 for e in self.endpoints}

    def try_acquire(self, endpoint, below=None):  # caller holds cond
        """Take a permit now if one is free (and, with `below`, only while occupancy < below); never blocks."""
        if below is not None and self.in_flight[endpoint] >= below:
            return False
        if not self.sem[endpoint].acquire(blocking=False):
            return False
        self.in_flight[endpoint] += 1
        return True

    def release(self, endpoint):
        with self.cond:
            self.in_flight[endpoint] -= 1
            self.sem[endpoint].release()
            self.cond.notify_all()

    def permit(self, endpoint, below=None, poll=None, cancel=None, record=None):
        """Context manager: wait (condition, re-checked on every release, on the case's cancel, or every `poll` s)
        until try_acquire succeeds. If `cancel` is set while waiting, it enters WITHOUT a permit at once (the caller
        sees the cancel and skips its work). record(dict): the occupancy at acquisition, or cancelled=True."""
        slots = self

        class Permit:
            held = False

            def __enter__(self):
                with slots.cond:
                    while True:
                        if cancel is not None and cancel.is_set():
                            if record:
                                record(dict(cancelled=True))
                            return self
                        occupancy = slots.in_flight[endpoint]
                        if slots.try_acquire(endpoint, below):
                            self.held = True
                            if record:
                                record(dict(occupancy=occupancy))
                            return self
                        slots.cond.wait(poll)

            def __exit__(self, *exc):
                if self.held:
                    self.held = False
                    slots.release(endpoint)
                return False
        return Permit()

    def wake(self):
        with self.cond:
            self.cond.notify_all()

    def __call__(self, endpoint):
        return self.permit(endpoint)


class IdleSlots:
    """The slots of one extra roll12idle agent: its worker permit was taken atomically at admission (held from the
    start); every later permit (its judge) is idle-gated the same way: taken only while the node has fewer than
    `threshold` requests in flight, so extra agents never delay other cases' first-wave agents or judges by more than
    the permits they already hold."""
    def __init__(self, slots, endpoint, threshold, poll, cancel=None):
        self.slots, self.endpoint, self.threshold, self.poll, self.cancel = slots, endpoint, threshold, poll, cancel
        self.held = True  # the admission permit, not yet handed to the worker
        self.judge_admission = None  # {'occupancy': n} or {'cancelled': True}

    def drop_unused(self):
        if self.held:
            self.held = False
            self.slots.release(self.endpoint)

    def __call__(self, endpoint):
        owner = self
        if self.held:
            self.held = False

            class Held:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    owner.slots.release(endpoint)
                    return False
            return Held()
        return self.slots.permit(endpoint, below=self.threshold, poll=self.poll, cancel=self.cancel,
                                 record=lambda r: setattr(owner, 'judge_admission', r))


def idle_extension(agent, race, slots, first=None, cap=None, threshold=None, max_inflight=None, poll=None):
    """roll12idle phase 2 (called once slots 0-11 all ended without an accept): admit extra agents first..cap-1. An
    admission is atomic under the slots lock: the least-loaded node whose occupancy is below `threshold` gets its
    permit taken with a non-blocking try-acquire, and the occupancy logged is the exact value at that moment; if no
    node qualifies, the case waits on the condition (every release of any case) or `poll` s and re-checks. At most
    `max_inflight` extra agents of this case at once; no new admission after the first accept. The extra agents'
    judges are idle-gated the same way (IdleSlots). Never time-triggered. agent(slot, node, idle_slots)."""
    first = IDLE_FIRST if first is None else first
    cap = IDLE_CAP if cap is None else cap
    threshold = IDLE_THRESHOLD if threshold is None else threshold
    max_inflight = IDLE_MAX_INFLIGHT if max_inflight is None else max_inflight
    poll = IDLE_POLL_SECONDS if poll is None else poll
    require(isinstance(slots, TrackedSlots), 'roll12idle needs TrackedSlots (occupancy)')
    race['idle_ran'] = True
    race.setdefault('on_cancel', []).append(slots.wake)  # an accept wakes this case's waiters immediately
    if race['cancel'].is_set():
        return []
    results, threads, state = [], [], dict(running=0)

    def run(slot, node, held, occupancy):
        try:
            info = agent(slot, node, held)
        except Exception as exc:  # never lose a slot
            info = fault_record(slot, '', exc)
        held.drop_unused()
        info.update(idle_node=node, idle_occupancy_at_start=occupancy, idle_judge_admission=held.judge_admission)
        with slots.cond:
            results.append(info)
            state['running'] -= 1
            if 'agent_error' in info:
                state['failed'] = True
            slots.cond.notify_all()

    nxt = first
    with slots.cond:
        while nxt < cap and race['winner'] is None and not race['cancel'].is_set() and not state.get('failed'):
            while nxt < cap and state['running'] < max_inflight and not race['cancel'].is_set():
                occ = {i: slots.in_flight[e] for i, e in enumerate(slots.endpoints)}
                node = next((i for i in sorted(occ, key=lambda i: (occ[i], i))
                             if slots.try_acquire(slots.endpoints[i], below=threshold)), None)
                if node is None:
                    break
                held = IdleSlots(slots, slots.endpoints[node], threshold, poll, race['cancel'])
                t = threading.Thread(target=run, args=(nxt, node, held, occ[node]))
                try:
                    t.start()
                except Exception as exc:  # the reserved permit is released and the slot recorded as a fault
                    held.drop_unused()  # cond is re-entrant (RLock)
                    info = fault_record(nxt, '', exc)
                    info.update(idle_node=node, idle_occupancy_at_start=occ[node], started=False)
                    results.append(info)
                    state['failed'] = True
                    nxt += 1
                    break
                state['running'] += 1
                threads.append(t)
                nxt += 1
            if nxt >= cap:
                break
            slots.cond.wait(poll)
    for t in threads:
        t.join()
    return sorted(results, key=lambda a: a['slot'])


def new_race(t0):
    """Shared per-case cancel state: the first accepted agent (in time) wins and cancels the rest."""
    lock, race = threading.Lock(), dict(cancel=threading.Event(), winner=None, answer_s=None)

    def accept(slot):
        with lock:
            if race['winner'] is None:
                race.update(winner=slot, answer_s=round(time.monotonic() - t0, 3))
                race['cancel'].set()
                hooks = list(race.get('on_cancel', []))
            else:
                hooks = []
        for hook in hooks:  # e.g. roll12idle: wake every waiter of this case at once
            hook()
    race['accept'] = accept
    return race


def run_policy(plan, source, out, task, seed, case_index, policy, slots):
    off = plan['seed_offsets'][policy]
    t0 = time.monotonic()
    race = new_race(t0) if policy in ('deep4cancel', 'waves2cancel', 'roll8cancel', 'roll3to8', 'roll3strategy', 'roll8repair', 'roll8strategy', 'roll12strategy', 'roll12cancel', 'roll12idle', 'roll12burst') or policy in ESC_HINTS else None
    agent = lambda slot, extra='': run_agent_safe(plan, source, out, task, seed, case_index, policy, slot, extra, slots, off, t0, race)
    if policy == 'deep4':
        agents = parallel([lambda s=s: agent(s) for s in range(4)])
    elif policy == 'strategy4':
        agents = parallel([lambda s=s: agent(s, STRATEGIES[s]) for s in range(4)])
    elif policy == 'repair4':
        agents, extra = [], ''
        for s in range(4):
            info = agent(s, extra)
            agents.append(info)
            if info['verdict'] is True:
                break
            extra = 'Earlier attempts on this exact task failed:\n' + '\n'.join(critique(a) for a in agents) + \
                    '\nAvoid these mistakes and give a corrected complete plan.'
    elif policy == 'board2x2':
        agents = parallel([lambda s=s: agent(s) for s in range(2)])
        if not any(a['verdict'] is True for a in agents):
            board = 'Shared board from other solvers on this exact task (all rejected by a checker):\n' + \
                    '\n'.join(critique(a) for a in agents) + '\nUse what is useful, avoid their mistakes, and give a complete valid plan.'
            agents += parallel([lambda s=s: agent(s, board) for s in (2, 3)])
    elif policy == 'deep4cancel':
        agents = parallel([lambda s=s: agent(s) for s in range(4)])
    elif policy == 'waves2cancel':
        agents = parallel([lambda s=s: agent(s) for s in range(2)])
        if race['winner'] is None:
            agents += parallel([lambda s=s: agent(s) for s in (2, 3)])
    elif policy == 'roll8cancel':
        agents = rolling(lambda slot, node: run_agent_safe(plan, source, out, task, seed, case_index, policy, slot, '', slots,
                                                      off, t0, race, node), race, case_index)
    elif policy == 'roll8repair':
        def board(done):
            rejected = [a for a in done if a['plan'] is not None and a['verdict'] is False]
            if not rejected:
                return ''
            return ('Earlier attempts on this exact task failed:\n' + '\n'.join(critique(a) for a in rejected) +
                    '\nAvoid these mistakes and give a corrected complete plan.')
        agents = rolling(lambda slot, node, extra='': run_agent_safe(plan, source, out, task, seed, case_index, policy, slot,
                                                                extra or '', slots, off, t0, race, node),
                         race, case_index, feedback=board)
    elif policy == 'roll3to8':
        agents = rolling(lambda slot, node: run_agent_safe(plan, source, out, task, seed, case_index, policy, slot, '', slots,
                                                      off, t0, race, node), race, case_index, width=3)
    elif policy == 'roll3strategy':
        agents = rolling(lambda slot, node: run_agent_safe(plan, source, out, task, seed, case_index, policy, slot,
                                                      STRATEGIES[(slot - 3) % 4] if slot >= 3 else '', slots, off, t0, race, node),
                         race, case_index, width=3)
    elif policy == 'roll12strategy':
        agents = rolling(lambda slot, node: run_agent_safe(plan, source, out, task, seed, case_index, policy, slot,
                                                      STRATEGIES[(slot - 4) % 4] if slot >= 4 else '', slots, off, t0, race, node),
                         race, case_index, cap=12)
    elif policy in ('roll12cancel', 'roll12idle'):
        agents = rolling(lambda slot, node: run_agent_safe(plan, source, out, task, seed, case_index, policy, slot, '', slots,
                                                      off, t0, race, node), race, case_index, cap=12)
        if policy == 'roll12idle' and race['winner'] is None and not any('agent_error' in a for a in agents):
            agents += idle_extension(lambda slot, node, held: run_agent_safe(
                plan, source, out, task, seed, case_index, policy, slot, '', held, off, t0, race, node), race, slots)
    elif policy == 'roll8strategy':
        agents = rolling(lambda slot, node: run_agent_safe(plan, source, out, task, seed, case_index, policy, slot,
                                                      STRATEGIES[(slot - 4) % 4] if slot >= 4 else '', slots, off, t0, race, node),
                         race, case_index)
    elif policy in ESC_HINTS:
        hint = ESC_HINTS[policy]
        first, width, cap = ESC_SHAPE.get(policy, ESC_DEFAULT_SHAPE)
        agents = rolling(lambda slot, node: run_agent_safe(plan, source, out, task, seed, case_index, policy, slot, hint(slot), slots,
                                                      off, t0, race, node), race, case_index, width=width, cap=cap, first=first)
    elif policy == 'roll12burst':
        agents = rolling(lambda slot, node: run_agent_safe(plan, source, out, task, seed, case_index, policy, slot, '', slots,
                                                      off, t0, race, node), race, case_index, cap=12,
                         burst_seconds=plan.get('burst_seconds', 900))
    else:
        raise ValueError(policy)
    if race:  # answer = first accepted in time
        selected = next((a for a in agents if a['slot'] == race['winner']), None)
        selection = dict(selected_slot=race['winner'], answer_seconds=race['answer_s'],
                     cancelled_agents=sum(a['cancelled'] for a in agents),
                     unstarted_agents=sum(not a['started'] for a in agents) + max(0, ELIGIBLE_SLOTS.get(policy, 4) - len(agents)),
                     # escalated = started agents beyond the first wave (all agents of the esc_* add-ons, slots 4-11 or 12-19)
                     escalated_agents=sum(a['slot'] >= (3 if policy in ('roll3to8', 'roll3strategy') else 4) and a['started'] for a in agents),
                     burst=bool(race.get('burst_at')),
                     **({'extra_agents': sum(a['slot'] >= IDLE_FIRST and a['started'] for a in agents),
                         'idle_phase': bool(race.get('idle_ran'))}
                        if policy == 'roll12idle' else {}),
                     skipped_judges=sum(a['judge_skipped'] for a in agents))
    else:  # answer = first accepted in slot order
        selected = next((a for a in agents if a['verdict'] is True), None)
        selection = dict(selected_slot=selected['slot'] if selected else None)
    return dict(policy=policy, agents=agents, answered=selected is not None,
                solved=bool(selected and selected['verifier_solved']), wrong=bool(selected and not selected['verifier_solved']),
                oracle=any(a['verifier_solved'] for a in agents), calls=len(agents),
                tokens=sum(a['tokens'] + a['judge_tokens'] for a in agents),
                infra=sum(a['infra'] + a['judge_infra'] for a in agents), deadlines=sum(a['deadline'] for a in agents),
                case_seconds=round(time.monotonic() - t0, 3), **selection)


def plan_tasks(plan, root=HERE):
    """The plan's tasks in run order (case index = seed position * len(tasks) + task position)."""
    data = read(root / plan['dataset'])
    require(data.get('protocol') == plan['dataset_protocol'], 'Wrong corpus')
    tasks = [t for t in data['tasks'] if t['split'] == plan['split']]
    if plan.get('task_ids'):  # optional subset (smoke plans)
        tasks = [t for t in tasks if t['id'] in plan['task_ids']]
    if plan.get('numbers_count'):  # optional: only tasks with this many numbers
        tasks = [t for t in tasks if len(t['numbers']) == plan['numbers_count']]
    require(len(tasks) == plan['tasks'], 'Wrong task count')
    return tasks


_RESUME = re.compile(r'^(.*)-resume(\d+)$')


def arm_base(run_dir):
    """The arm directory of a run or resume-segment directory."""
    run_dir = Path(run_dir)
    m = _RESUME.match(run_dir.name)
    return run_dir.parent / m.group(1) if m else run_dir


def arm_segments(base):
    """The arm directory and its resume segments, in order."""
    found = [(int(m.group(2)), d) for d in base.parent.glob(base.name + '-resume*')
             if (m := _RESUME.match(d.name)) and m.group(1) == base.name and (d / 'cases.jsonl').exists()]
    return [base] + [d for _, d in sorted(found)]


def arm_latest(run_dir, root=HERE, policy=None, complete=True):
    """Frozen resume rule over an arm's segments: per (task, seed) the latest row counts; a later segment may only
    rerun an infra/error row; the segments must cover the plan's cases exactly. Returns base, segments, plan, tasks,
    index (case index), latest {key: (segment, row)}, clean keys, superseded and unresolved lists."""
    base = arm_base(run_dir)
    segs = arm_segments(base)
    plan = read(base / 'metadata.json')['protocol']
    for seg in segs[1:]:
        meta = read(seg / 'metadata.json')
        require(meta['protocol'] == plan and meta.get('resume'), f'{seg.name} is not a resume segment of {base.name}')
    tasks = plan_tasks(plan, root)
    index = {(t['id'], s): si * len(tasks) + ti for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks)}
    expected = set(index)
    if plan.get('case_list'):
        expected = {(c[0], c[1]) for c in read(root / plan['case_list'])['cases']}
    latest, superseded = {}, []
    for seg in segs:
        seen = set()
        for line in (seg / 'cases.jsonl').read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if policy is not None and row.get('policy') != policy:
                continue
            key = (row['task_id'], row['seed'])
            require(key in index, f'unknown case {key} in {seg.name}')
            require(key not in seen, f'duplicate case {key} in {seg.name}')
            seen.add(key)
            if key in latest:
                prev_seg, prev = latest[key]
                require('error' in prev or prev.get('infra'), f'{seg.name} reruns the clean case {key}')
                superseded.append(dict(task_id=key[0], seed=key[1], segment=prev_seg.name))
            latest[key] = (seg, row)
    if complete:
        require(set(latest) == expected, f'{base.name}: segments do not cover the plan cases exactly')
    else:  # a stopped arm (resume): rows may be missing, never unknown
        require(set(latest) <= expected, f'{base.name}: segments hold cases outside the plan')
    clean = {k for k, (_, row) in latest.items() if 'error' not in row and not row.get('infra')}
    return dict(base=base, segments=segs, plan=plan, tasks=tasks, index=index, latest=latest, clean=clean,
                superseded=superseded, unresolved=[dict(task_id=k[0], seed=k[1]) for k in latest if k not in clean])


def check_pairing(plan, policies, root=HERE):
    """Escalation-only arms (esc_*, esc_extra) require a case_list. The esc_* arms keep their frozen semantics (case
    list built by inkling/strict_hard_cases.py from a shared first wave; paired_with optional). The add-on arms in
    PAIRED_ADDONS (esc_extra, on a default arm's abstentions) require 'paired_with': {plan, policy, run}: the plan's
    agent_variant and each arm's seed offset must equal that plan's agent_variant and seed_offsets[policy], and the
    case_list must be exactly the clean abstentions (answered False, latest clean row per case under the frozen resume
    rule) of that policy in that run (no unresolved infra cases).
    Any present paired_with ({agent_variant, seed_offset} and/or {plan, policy}) must match the plan."""
    esc = [pol for pol in policies if pol in ESC_HINTS]
    addons = [pol for pol in policies if pol in PAIRED_ADDONS]
    paired = plan.get('paired_with')
    if esc:
        require(plan.get('case_list'), f'escalation-only policies {esc} require a case_list')
    if addons:
        require(isinstance(paired, dict) and all(paired.get(k) for k in ('plan', 'policy', 'run')),
                f'add-on policies {addons} require paired_with = {{plan, policy, run}}')
    if not paired:
        return
    expected = {}
    if paired.get('plan'):
        other = read(root / paired['plan'])
        expected = dict(agent_variant=other['agent_variant'], seed_offset=other['seed_offsets'][paired['policy']])
    for key in ('agent_variant', 'seed_offset'):
        if key in paired:
            require(expected.get(key, paired[key]) == paired[key], f'paired_with {key} disagrees with its plan')
            expected[key] = paired[key]
    require(expected, 'paired_with names no agent_variant / seed_offset')
    if 'agent_variant' in expected:
        require(plan['agent_variant'] == expected['agent_variant'], 'agent_variant differs from paired_with')
    if 'seed_offset' in expected:
        for pol in policies:
            require(plan['seed_offsets'][pol] == expected['seed_offset'], f'seed offset of {pol} differs from paired_with')
    if addons:
        check_addon_run(plan, paired, expected, root)


def _resolve(path, root):
    path = Path(path)
    return (path if path.is_absolute() else root / path).resolve()


def check_addon_run(plan, paired, expected, root=HERE):
    """esc_extra pairing: the paired policy is the default ADDON_DEFAULT_POLICY (roll12strategy; other baselines need
    an explicit code change); paired_with.plan_sha256 pins the paired plan file; the run (all its segments) ran exactly
    that plan file (admission path, plan content) with only that policy; the add-on uses the same dataset, task order
    and seed order (identical case indices); the case_list is exactly the run's clean abstentions."""
    require(paired['policy'] == ADDON_DEFAULT_POLICY,
            f"paired policy {paired['policy']} is not the default {ADDON_DEFAULT_POLICY}")
    plan_file = _resolve(paired['plan'], root)
    require(paired.get('plan_sha256') == sha(plan_file), 'paired_with.plan_sha256 does not match the paired plan file')
    other = read(plan_file)
    arm = arm_latest(root / paired['run'], root, policy=paired['policy'])
    for seg in arm['segments']:
        meta = read(seg / 'metadata.json')
        ran = (meta.get('admission') or {}).get('plan')
        require(ran is not None and _resolve(ran, root) == plan_file, f'{seg.name} was not run from the paired plan file')
        require(meta['protocol'] == other, f'{seg.name} ran a different version of the paired plan')
        require(meta.get('policies') == [paired['policy']], f'{seg.name} did not run only the paired policy')
    require(arm['plan'].get('agent_variant') == expected['agent_variant']
            and arm['plan'].get('seed_offsets', {}).get(paired['policy']) == expected['seed_offset'],
            'paired run was not made with the paired plan settings')
    require(plan['dataset'] == other['dataset'] and plan['seeds'] == other['seeds'],
            'add-on dataset or seed order differs from the paired plan (case indices would differ)')
    require([t['id'] for t in plan_tasks(plan, root)] == [t['id'] for t in plan_tasks(other, root)],
            'add-on task order differs from the paired plan (case indices would differ)')
    require(not arm['unresolved'], f"paired run has unresolved infra cases: {arm['unresolved'][:3]}")
    abstained = {k for k in arm['clean'] if not arm['latest'][k][1]['answered']}
    listed = [(c[0], c[1]) for c in read(root / plan['case_list'])['cases']]
    require(len(set(listed)) == len(listed) and set(listed) == abstained,
            f'case_list is not exactly the clean abstentions of the paired run ({len(set(listed))} listed, '
            f'{len(abstained)} abstained)')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    p.add_argument('--resume-from', type=Path, help='previous output: skip its policy cases that finished without infrastructure faults')
    p.add_argument('--policy', action='append', help='run only these policies of the plan (one arm at a time); default all')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == 'swarm-variants-screen-v1', 'Wrong protocol')
    source, out = a.source.resolve(), a.output.resolve()
    validate_source(source, plan['source_revision'])
    tasks = plan_tasks(plan)
    policies = a.policy or plan['policies']
    require(set(policies) <= set(plan['policies']), 'Policy not in plan')
    check_pairing(plan, policies)
    jobs = [(t, s, si * len(tasks) + ti, pol) for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks) for pol in policies]
    if plan.get('case_list'):  # optional: only these (task_id, seed) cases; case indices (node placement) are kept
        listed = [(c[0], c[1]) for c in read(HERE / plan['case_list'])['cases']]
        keep = set(listed)
        require(len(keep) == len(listed), 'case_list has duplicate cases')
        jobs = [j for j in jobs if (j[0]['id'], j[1]) in keep]
        require(len(jobs) == len(keep) * len(policies), 'case_list does not match the corpus')
    concurrent = plan['concurrent_policy_cases']
    if len(policies) == 1:  # optional per-arm case concurrency (e.g. two-agent waves keep the same per-node load)
        concurrent = plan.get('concurrent_policy_cases_by_policy', {}).get(policies[0], concurrent)
    resumed = None
    if a.resume_from:  # continuation after an infrastructure stop: same plan, only unfinished policy cases
        # the union of finished clean cases over the arm and ALL its -resumeN segments (frozen resume rule), so a
        # second resume never reruns a clean case
        finished, segments = set(), None
        for pol in policies:
            arm = arm_latest(a.resume_from, HERE, policy=pol, complete=False)
            finished |= {(k[0], k[1], pol) for k in arm['clean']}
            segments = [d.name for d in arm['segments']]
        jobs = [j for j in jobs if (j[0]['id'], j[1], j[3]) not in finished]
        resumed = dict(resumed_from=str(a.resume_from.resolve()), skipped_finished=len(finished), segments=segments)
    require(plan.get('concurrent_requests_per_endpoint', 0) <= MAX_REQUESTS_PER_NODE, 'Per-node request cap above 25')
    if 'roll12idle' in policies:  # extra agents only below the idle threshold, inside a per-endpoint cap of at most 20
        require(IDLE_THRESHOLD < plan.get('concurrent_requests_per_endpoint', 0) <= 20,
                f'roll12idle needs {IDLE_THRESHOLD} < concurrent_requests_per_endpoint <= 20')
        require(policies == ['roll12idle'] or not a.run, 'roll12idle runs alone (--policy roll12idle)')
    if not a.run:
        print(json.dumps(dict(mode='plan', policy_cases=len(jobs), model_calls=0)))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not out.exists(), 'Frozen plan, admission, new output')
    adm = read(a.admission)
    require(adm.get('verified') is True and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds() <= 900, 'Fresh admission')
    for d in ('agents', 'judges', 'extra'):
        (out / d).mkdir(parents=True, exist_ok=d != 'agents')
    write(out / 'metadata.json', dict(protocol=plan, runner_sha256=sha(Path(__file__)), resume=resumed, policies=policies,
                                      agent_variant=plan['agent_variant'],
                                      seed_offsets={pol: plan['seed_offsets'][pol] for pol in policies},
                                      concurrent_policy_cases=concurrent, started_utc=datetime.now(timezone.utc).isoformat(), admission=adm))
    # TrackedSlots (exact occupancy, one condition lock) only for a roll12idle arm; every other policy keeps plain Slots
    slot_class = TrackedSlots if policies == ['roll12idle'] else Slots
    slots, lock, stop, rows = slot_class(plan['concurrent_requests_per_endpoint']), threading.Lock(), threading.Event(), []

    def work(job):
        task, seed, index, pol = job
        if stop.is_set():
            return
        try:
            rec = run_policy(plan, source, out, task, seed, index, pol, slots)
        except Exception as exc:
            with lock:
                stop.set()
                rows.append(dict(task_id=task['id'], seed=seed, policy=pol, error=f'{type(exc).__name__}: {exc}'))
            return
        rec.update(task_id=task['id'], seed=seed)
        with lock:
            rows.append(rec)
            if rec['infra']:
                stop.set()
            with (out / 'cases.jsonl').open('a') as stream:
                stream.write(json.dumps(rec) + '\n')
            print(json.dumps(dict(done=len(rows), total=len(jobs), policy=pol, task=task['id'], seed=seed, solved=rec['solved'], wrong=rec['wrong'])), flush=True)

    start = time.monotonic()
    with ThreadPoolExecutor(concurrent) as pool:
        list(pool.map(work, jobs))
    meta = read(out / 'metadata.json')
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=time.monotonic() - start, stopped=stop.is_set(),
                errors=[r for r in rows if 'error' in r],
                summary={pol: dict(cases=sum(r.get('policy') == pol and 'error' not in r for r in rows),
                                   solved=sum(r.get('policy') == pol and r.get('solved', False) for r in rows),
                                   wrong=sum(r.get('policy') == pol and r.get('wrong', False) for r in rows))
                         for pol in policies})
    write(out / 'metadata.json', meta)
    print(json.dumps(meta['summary']))
    return int(bool(meta['errors']) or meta['stopped'])


if __name__ == '__main__':
    raise SystemExit(main())
