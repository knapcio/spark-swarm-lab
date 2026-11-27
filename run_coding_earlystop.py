#!/usr/bin/env python3
"""Coding swarm with early stop: run_coding_agents.py, plus a per-case stop as soon as one agent's proposal passes ALL
public feedback cases. The remaining agents of that case are terminated at once (process group; the shim closes the
upstream stream and SGLang aborts) and queued agents of that case never start. Answer = the first feedback-passing
proposal in TIME order; the case is solved if it passes the hidden holdout (graded by the worker, never read by the
controller). Same jobs, seeds, endpoints, grading and fault rules as run_coding_agents.py; a terminated agent is a
controller decision, not an operational fault. Optional plan field stagger = {"first": k, "after_seconds": T}: agents
k.. of a case start only if the case has no passing proposal T seconds after its first agent started. Optional plan field
rolling = {"width": W} (failure-driven replacement, exclusive with stagger): W agents start; agent k >= W of a case
starts only after k - W + 1 agents of that case have ended without a passing proposal. Optional plan field
acceptance = "self_tests" | "judge" (no provided tests; early_stop must then be "first_accepted_in_time"): the workers get
--acceptance, see the statement without the public examples, and a proposal passes when the agent's own tests pass in the
sandbox (self_tests) or the judge accepts it (judge) instead of on the feedback cases. The worker records its decision
as an 'acceptance' trace event (decided_monotonic: this host's monotonic clock, the controller's clock too) BEFORE any
hidden grading. The winner is the accepted proposal with the EARLIEST recorded decision: whenever an executor observes an
accepted decision, the case Arbiter collects every decision already recorded by the case's agents and picks the earliest
(not the poll order). A decision recorded after its agent's deadline is not an acceptance (the agent counts as a
deadline; when the deadline timer fires, the trace is read once more and a decision recorded at or before the deadline
still counts). Optional plan field judge = {"thinking_tokens", "answer_tokens", "max_calls"} (acceptance "judge"
only; defaults 6144 / 2048 / 2, the original judge budget) is passed to every worker as --judge-* options. The hidden feedback and holdout grading after a decision is scoring only (bounded by SCORING_GRACE_SECONDS) and
can neither change the winner nor move the decision. A case is solved if the winner passes ALL hidden cases (feedback and
holdout). Without the field everything is exactly as before (the public-tests path: the first feedback pass observed when a
worker exits, after its in-worker hidden grading, as in every earlier coding study). Optional plan field
suspend_siblings = "hold_dispatch" (acceptance "judge" only; idea #5 live validation): while an agent of a case has a
PENDING verdict (from its first observed 'judge_start' until its decision), the case's other agents hold their next
model dispatch (the worker's --hold-file / --agent-index; the runner mirrors each case's pending agents to
OUTPUT/holds/<task>-s<seed>.json) and no new agent of the case starts. A pending verdict is never an acceptance and the
winner rule is unchanged (the earliest recorded in-time accepted decision). An accepted decision keeps its siblings held
until the arbiter terminates them; a rejection, a late or untimed decision, or a worker that ends without a decision
releases them. An agent's deadline is extended by the time other agents of its case were pending during its life (an
upper bound on its hold). Nothing is cancelled and resumed: true in-flight pausing is not possible on this server.
Plan-only by default.
"""
import argparse
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from run_agents72 import operational_fault, read, require, sha, validate_source, write
from run_benchmark import append_controller_stop, metrics, read_trace, server_metrics, terminate
from run_coding_agents import ENDPOINTS, HERE, PROTOCOL, agent_outcome, hashes, make_jobs
from run_variants import execute_cancellable

ACCEPTANCE = ('self_tests', 'judge')
SUSPEND = ('hold_dispatch',)
EARLY_STOP = {None: 'first_feedback_pass_in_time', 'self_tests': 'first_accepted_in_time', 'judge': 'first_accepted_in_time'}
JUDGE_DEFAULTS = dict(thinking_tokens=6144, answer_tokens=2048, max_calls=2)  # the original judge budget (8192 in total)


def judge_budget(plan):
    """Plan field judge = {thinking_tokens, answer_tokens, max_calls} (acceptance 'judge' only; omitted keys take the
    original defaults 6144 / 2048 / 2). Returned with every key resolved."""
    judge = plan.get('judge')
    require(judge is None or plan.get('acceptance') == 'judge', 'judge budget needs acceptance judge')
    out = dict(JUDGE_DEFAULTS, **(judge or {}))
    require(isinstance(judge, (dict, type(None))) and set(out) == set(JUDGE_DEFAULTS)
            and all(type(v) is int for v in out.values()) and out['thinking_tokens'] > 0 and out['answer_tokens'] > 0
            and out['max_calls'] in (1, 2), 'Invalid judge budget')
    return out


def judge_flags(budget):
    return ['--judge-thinking-tokens', str(budget['thinking_tokens']), '--judge-answer-tokens',
            str(budget['answer_tokens']), '--judge-max-calls', str(budget['max_calls'])]


SCORING_GRACE_SECONDS = 600  # hidden grading after a decision: two sandbox grades, normally well under a minute


class TraceTail:
    """Complete JSON lines appended to a worker trace since the last read (a partial last line waits)."""
    def __init__(self, path):
        self.path, self.offset = Path(path), 0

    def first_of(self, kinds):
        """{kind: the first record of that kind} among the complete lines appended since the last read."""
        found = {}
        if not self.path.exists():
            return found
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            data = stream.read()
        end = data.rfind(b'\n') + 1
        self.offset += end
        for line in data[:end].splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get('type') in kinds and record['type'] not in found:
                found[record['type']] = record
        return found

    def find(self, kind):
        if not self.path.exists():
            return None
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            data = stream.read()
        end = data.rfind(b'\n') + 1
        self.offset += end
        for line in data[:end].splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get('type') == kind:
                return record
        return None


def first_acceptance(path):
    records, _ = read_trace(Path(path))
    return next((r for r in records if r.get('type') == 'acceptance'), None)


def decided_at(event):
    value = event.get('decided_monotonic') if event else None
    return value if type(value) in (int, float) else None


def in_time_acceptance(event, start, deadline_seconds):
    """An acceptance counts only if accepted, timestamped and recorded within the agent's deadline."""
    t = decided_at(event)
    return bool(event and event.get('accepted') is True and t is not None and t - start <= deadline_seconds)


class HoldBoard:
    """Pending judge verdicts per case (suspend_siblings = hold_dispatch). pend/release keep, per case, the set of
    agents whose verdict is pending and every agent's pending intervals; each change is mirrored atomically (temp file
    + rename) to directory/<task>-s<seed>.json = {"pending": [agents]} for the workers' dispatch holds."""

    def __init__(self, directory, clock=time.monotonic):
        self.dir, self.clock, self.lock = Path(directory), clock, threading.RLock()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pending, self.intervals = {}, {}

    def path(self, key):
        return self.dir / f'{key[0]}-s{key[1]}.json'

    def _mirror(self, key):
        path = self.path(key)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(pending=sorted(self.pending.get(key, ())))))
        tmp.replace(path)

    def pend(self, key, agent):
        with self.lock:
            if agent not in self.pending.setdefault(key, set()):
                self.pending[key].add(agent)
                self.intervals.setdefault(key, {}).setdefault(agent, []).append([self.clock(), None])
                self._mirror(key)

    def release(self, key, agent):
        with self.lock:
            if agent in self.pending.get(key, ()):
                self.pending[key].discard(agent)
                self.intervals[key][agent][-1][1] = self.clock()
                self._mirror(key)

    def held(self, key):
        with self.lock:
            return bool(self.pending.get(key))

    def held_seconds(self, key, me, t0, t1):
        """Seconds of [t0, t1] during which an agent of the case other than `me` was pending (union)."""
        with self.lock:
            now = self.clock()
            spans = sorted((max(a, t0), min(b if b is not None else now, t1))
                           for agent, ivs in self.intervals.get(key, {}).items() if agent != me for a, b in ivs)
        total, cur0, cur1 = 0.0, None, None
        for a, b in spans:
            if b <= a:
                continue
            if cur1 is None or a > cur1:
                total += (cur1 - cur0) if cur1 is not None else 0.0
                cur0, cur1 = a, b
            else:
                cur1 = max(cur1, b)
        return total + ((cur1 - cur0) if cur1 is not None else 0.0)

    def summary(self):
        with self.lock:
            now = self.clock()
            seconds = sum((b if b is not None else now) - a for case in self.intervals.values()
                          for ivs in case.values() for a, b in ivs)
            return dict(cases=len(self.intervals), pending_windows=sum(len(ivs) for case in self.intervals.values()
                                                                        for ivs in case.values()),
                        pending_seconds=round(seconds, 1))


class Arbiter:
    """Per-case winner: the accepted, in-time decision with the earliest recorded decided_monotonic among every decision
    already recorded by the case's agents when an accepted decision is observed. Once chosen, the winner is final and the
    case's cancel event is set (the other agents are terminated, queued ones never start)."""
    def __init__(self, cancels):
        self.cancels, self.lock = cancels, threading.RLock()
        self.agents, self.winners = {}, {}

    def register(self, key, agent, events, start, deadline_seconds, extra=None):
        """extra(t): seconds added to the agent's deadline for a decision recorded at t (holds only; default none)."""
        with self.lock:
            self.agents.setdefault(key, {})[agent] = (events, start, deadline_seconds)
            if extra is not None:
                self.extras = getattr(self, 'extras', {})
                self.extras[(key, agent)] = extra

    def winner(self, key):
        with self.lock:
            return self.winners.get(key, (None, None))[0]

    def decided(self, key):
        with self.lock:
            return self.winners.get(key, (None, None))[1]

    def decide(self, key):
        with self.lock:
            if key not in self.winners:
                candidates = []
                for agent, (events, start, limit) in self.agents.get(key, {}).items():
                    event = first_acceptance(events)
                    extra = getattr(self, 'extras', {}).get((key, agent))
                    if extra is not None and decided_at(event) is not None:
                        limit = limit + extra(decided_at(event))
                    if in_time_acceptance(event, start, limit):
                        candidates.append((decided_at(event), agent))
                if candidates:
                    t, agent = min(candidates)
                    self.winners[key] = (agent, t)
                    self.cancels[key].set()
            return self.winners.get(key, (None, None))[0]


def execute_accepting(case, deadline_seconds, arbiter, grace_seconds=SCORING_GRACE_SECONDS, poll=.1, holds=None):
    """execute_cancellable for the no-provided-tests modes (case = a job: task_id, seed, agent, command, events, stdout,
    stderr). The worker's first 'acceptance' event is the decision. An accepted in-time decision asks the arbiter to pick
    the case winner; an agent that is not the winner is terminated once a winner exists (cancelled); the winner never is.
    A decision recorded after deadline_seconds is not an acceptance (deadline). After an in-time decision the hidden
    scoring may take up to grace_seconds (then terminated and flagged scoring_timeout). Returns the run_benchmark row plus
    accepted, won, decision_seconds (recorded decision - start), late_decision, scoring_timeout. holds (a HoldBoard,
    suspend_siblings only): the agent is pending from its first 'judge_start' until a decision that is not an in-time
    acceptance (released) or until the case ends (accepted); its deadline is extended by the time other agents of the
    case were pending."""
    key, me = (case['task_id'], case['seed']), case['agent']
    start = time.monotonic()
    if holds is None:
        arbiter.register(key, me, case['events'], start, deadline_seconds)
    else:
        arbiter.register(key, me, case['events'], start, deadline_seconds,
                         extra=lambda t: holds.held_seconds(key, me, start, t))

    def limit(t):
        return deadline_seconds + (holds.held_seconds(key, me, start, t) if holds is not None else 0)
    deadline = cancelled = scoring_timeout = late = False
    error = returncode = decision = decided = None
    tail = TraceTail(case['events'])

    def observe():
        nonlocal decision, decided, late
        if decision is None:
            if holds is None:
                event = tail.find('acceptance')
            else:
                found = tail.first_of(('judge_start', 'acceptance'))
                if 'judge_start' in found:
                    holds.pend(key, me)  # pending: never an acceptance
                event = found.get('acceptance')
            if event is not None:
                decided = decided_at(event)
                late = decided is None or decided - start > limit(decided)
                decision = in_time_acceptance(event, start, limit(decided) if decided is not None else deadline_seconds)
                if decision:
                    arbiter.decide(key)
                elif holds is not None:
                    holds.release(key, me)  # a rejection (or a late / untimed decision) releases the siblings

    with Path(case['stdout']).open('x') as stdout, Path(case['stderr']).open('x') as stderr:
        try:
            process = subprocess.Popen(case['command'], cwd=HERE, stdout=stdout, stderr=stderr, start_new_session=True)
            while True:
                observe()  # before poll(): a decision written just before exit is still seen
                if process.poll() is not None:
                    returncode = process.returncode
                    break
                winner = arbiter.winner(key)
                if winner is not None and winner != me:
                    cancelled, returncode = True, terminate(process)
                    break
                now = time.monotonic()
                if decision is None and not late and now - start >= limit(now):
                    observe()  # once more: a decision recorded in time may have landed after this iteration's read
                    if decision:
                        continue
                if late or (decision is None and now - start >= limit(now)):
                    deadline, returncode = True, terminate(process)
                    break
                if decision is not None and now - decided >= grace_seconds:
                    deadline = scoring_timeout = True
                    returncode = terminate(process)
                    break
                time.sleep(poll)
        except OSError as exc:
            error = f'{type(exc).__name__}: {exc}'
    if not (cancelled or deadline):
        observe()
        deadline = late
    if holds is not None and not decision:
        holds.release(key, me)  # ended without an in-time acceptance: its siblings go on
    won = not cancelled and not late and arbiter.winner(key) == me
    trace = Path(case['events'])
    records, _ = read_trace(trace)
    row = dict(metrics(records, deadline), returncode=returncode, controller_error=error, deadline=deadline,
               cancelled=cancelled, wall_seconds=round(time.monotonic() - start, 6), controller_stop=cancelled or deadline,
               server_cost_known=False, server_cost_reason='shared_endpoint', server_prompt_tokens=None,
               server_completion_tokens=None, server_idle_after=None, time_to_verified_solution_seconds=None,
               accepted=bool(decision) and not cancelled, won=won, late_decision=late, scoring_timeout=scoring_timeout,
               decision_seconds=round(decided - start, 3) if decided is not None else None)
    if cancelled:
        row.update(status='cancelled', solved=False)
    if row['controller_stop']:
        append_controller_stop(trace, records, row, case)
    return row


def passed(row, acceptance):
    return row['accepted'] if acceptance else row['feedback_pass']


def fault(row):
    if row.get('cancelled'):
        return 'controller_or_transport_failure' if row['controller_error'] or row['malformed_lines'] else None
    return operational_fault(row)


def cases_summary(rows, jobs, acceptance=None):
    cases = {}
    for job in jobs:
        cases.setdefault((job['task_id'], job['seed']), dict(agents=0))['agents'] += 1
    for (task, seed), case in cases.items():
        mine = [r for r in rows if (r['task_id'], r['seed']) == (task, seed)]
        winner = next((r for r in mine if r.get('winner')), None)
        solved = bool(winner and winner['holdout_pass'] and (not acceptance or winner['feedback_pass']))
        case.update(task_id=task, seed=seed, answered=winner is not None,
                    solved=solved, winner_agent=winner['agent'] if winner else None,
                    started=len(mine), cancelled=sum(bool(r.get('cancelled')) for r in mine),
                    never_started=case['agents'] - len(mine),
                    completion_tokens=sum(r['completion_tokens'] or 0 for r in mine),
                    stop_seconds=winner['stop_seconds'] if winner else None)
    return list(cases.values())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    plan = read(a.plan)
    acceptance = plan.get('acceptance')
    require(acceptance is None or acceptance in ACCEPTANCE, 'Unknown acceptance')
    require(plan['protocol'] == PROTOCOL and plan.get('early_stop') == EARLY_STOP[acceptance], 'Wrong protocol')
    source, output = a.source.expanduser().resolve(), a.output.resolve()
    validate_source(source, plan['source_revision'])
    before = hashes(source)
    tasks_path, tests_path = HERE / plan['matrix']['tasks'], HERE / plan['matrix']['tests']
    require(sha(tasks_path) == plan['matrix']['tasks_sha256'] and sha(tests_path) == plan['matrix']['tests_sha256'],
            'Corpus hash differs')
    tasks = [t for t in read(tasks_path)['tasks'] if t['split'] == plan['matrix']['split']]
    if plan['matrix'].get('task_ids'):  # optional subset (smoke plans)
        tasks = [t for t in tasks if t['id'] in plan['matrix']['task_ids']]
    require(len(tasks) == plan['matrix']['tasks_count'], 'Wrong task count')
    jobs = make_jobs(tasks, output, source, plan, tasks_path, tests_path)
    judge = judge_budget(plan)
    suspend = plan.get('suspend_siblings')
    require(suspend is None or (suspend in SUSPEND and acceptance == 'judge'),
            'suspend_siblings needs judge acceptance')
    if acceptance:
        for job in jobs:
            job['command'] = job['command'] + ['--acceptance', acceptance] + (judge_flags(judge) if acceptance == 'judge'
                                                                               else [])
    if suspend:
        for job in jobs:
            hold_file = output / 'holds' / f"{job['task_id']}-s{job['seed']}.json"
            job['command'] = job['command'] + ['--hold-file', str(hold_file), '--agent-index', str(job['agent'])]
    per_node, deadline = plan['scheduling']['concurrent_agents_per_node'], plan['limits']['agent_wall_deadline_seconds']
    meta = dict(protocol=plan, plan_sha256=sha(a.plan), jobs=len(jobs), source_sha256=before, output=str(output),
                runner_sha256=sha(Path(__file__)))
    if not a.run:
        print(json.dumps(dict(mode='plan', jobs=len(jobs), model_calls=0, agents=len(plan['agent_variants']))))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not output.exists(), 'Frozen plan, admission and new output required')
    admission = read(a.admission)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(admission['verified_utc'])).total_seconds()
    require(admission.get('verified') is True and 0 <= age <= 900, 'Fresh admission required')
    output.mkdir(parents=True)
    meta.update(started_utc=datetime.now(timezone.utc).isoformat(), admission=admission,
                server_before={e: server_metrics(e, timeout=3) for e in ENDPOINTS})
    write(output / 'metadata.json', meta)
    holds = HoldBoard(output / 'holds') if suspend else None
    rows, errors, lock, stop = [], [], threading.Lock(), threading.Event()
    cancel = {(j['task_id'], j['seed']): threading.Event() for j in jobs}
    first_start, first_done, failed = {}, {}, {}
    stagger, rolling = plan.get('stagger'), plan.get('rolling')
    first_k = stagger['first'] if stagger else rolling['width'] if rolling else len(plan['agent_variants'])
    queues = {e: iter([j for j in jobs if j['endpoint'] == e and j['agent'] < first_k]) for e in ENDPOINTS}
    later = {e: [j for j in jobs if j['endpoint'] == e and j['agent'] >= first_k] for e in ENDPOINTS}
    start = time.monotonic()

    held_first = {e: [] for e in ENDPOINTS}  # suspend_siblings: first-wave jobs skipped while their case was held

    def take(endpoint):
        """Next job for this endpoint (caller holds the lock): a due later agent of an open case first, else the next
        first-wave agent of an open case. Returns (job, waiting) where waiting means later agents are not due yet.
        With suspend_siblings no agent of a case with a pending verdict starts (it waits; other cases go first)."""
        if holds is not None:
            return take_unheld(endpoint)
        pending = later[endpoint]
        pending[:] = [j for j in pending if not cancel[(j['task_id'], j['seed'])].is_set()]  # answered: never start
        now = time.monotonic()
        for j in pending:
            k = (j['task_id'], j['seed'])
            if rolling:
                due = failed.get(k, 0) >= j['agent'] - first_k + 1
            else:
                due = k in first_start and (now - first_start[k] >= stagger['after_seconds'] or first_done.get(k, 0) >= first_k)
            if due:
                pending.remove(j)
                return j, False
        job = next(queues[endpoint], None)
        while job is not None and cancel[(job['task_id'], job['seed'])].is_set():
            job = next(queues[endpoint], None)  # case already answered: this agent never starts
        return job, bool(pending)

    def take_unheld(endpoint):
        """take() with suspend_siblings: the same order, skipping (not dropping) jobs of held cases."""
        def open_(j):
            return not cancel[(j['task_id'], j['seed'])].is_set()
        pending = later[endpoint]
        pending[:] = [j for j in pending if open_(j)]
        held_first[endpoint][:] = [j for j in held_first[endpoint] if open_(j)]
        now = time.monotonic()
        for j in pending:
            k = (j['task_id'], j['seed'])
            if holds.held(k):
                continue
            if rolling:
                due = failed.get(k, 0) >= j['agent'] - first_k + 1
            else:
                due = k in first_start and (now - first_start[k] >= stagger['after_seconds']
                                            or first_done.get(k, 0) >= first_k)
            if due:
                pending.remove(j)
                return j, False
        for j in list(held_first[endpoint]):
            if not holds.held((j['task_id'], j['seed'])):
                held_first[endpoint].remove(j)
                return j, False
        job = next(queues[endpoint], None)
        while job is not None and (not open_(job) or holds.held((job['task_id'], job['seed']))):
            if open_(job):
                held_first[endpoint].append(job)  # its case has a pending verdict: start it later
            job = next(queues[endpoint], None)
        return job, bool(pending) or bool(held_first[endpoint])

    arbiter = Arbiter(cancel)

    def worker(endpoint):
        while True:
            with lock:
                if stop.is_set():
                    return
                job, waiting = take(endpoint)
            if job is None:
                if not waiting:
                    return
                time.sleep(2)
                continue
            with lock:
                try:
                    changed = hashes(source) != before
                except Exception as exc:
                    stop.set()
                    errors.append(dict(reason='source_check_exception', detail=str(exc)[:300]))
                    return
                if changed:
                    stop.set()
                    errors.append(dict(reason='source_changed', events=job['events']))
                    return
                key = (job['task_id'], job['seed'])
                first_start.setdefault(key, time.monotonic())
            try:
                if acceptance and holds is not None:
                    row = execute_accepting(job, deadline, arbiter, holds=holds)
                elif acceptance:
                    row = execute_accepting(job, deadline, arbiter)
                else:
                    row = execute_cancellable(job, deadline, cancel[key])
                row.update({k: job[k] for k in ('task_id', 'split', 'arm', 'seed', 'endpoint', 'events')},
                           agent=job['agent'], case_index=job['case_index'], malformed_lines=read_trace(Path(job['events']))[1],
                           **agent_outcome(job['events']))
                if row['cancelled']:
                    row.update(feedback_pass=False, holdout_pass=False)  # a terminated agent has no answer
            except Exception as exc:
                with lock:
                    stop.set()
                    errors.append(dict(reason='controller_exception', events=job['events'], detail=str(exc)[:300]))
                return
            with lock:
                if job['agent'] < first_k:
                    first_done[key] = first_done.get(key, 0) + 1
                if not passed(row, acceptance) and not row['cancelled']:
                    failed[key] = failed.get(key, 0) + 1
                row['winner'] = False
                if acceptance:  # the arbiter picked the winner by its recorded decision time (execute_accepting)
                    if row.pop('won'):
                        row.update(winner=True, stop_seconds=round(arbiter.decided(key) - first_start[key], 1))
                elif passed(row, acceptance) and not cancel[key].is_set():
                    row.update(winner=True, stop_seconds=round(time.monotonic() - first_start[key], 1))
                    cancel[key].set()
                rows.append(row)
                reason = fault(row)
                if acceptance and row.get('scoring_timeout'):
                    reason = reason or 'scoring_timeout'
                if reason:
                    stop.set()
                    errors.append(dict(reason=reason, events=job['events']))
                write(output / 'summary.json', rows)
                line = dict(done=len(rows), total=len(jobs), task_id=row['task_id'], agent=row['agent'],
                            feedback=row['feedback_pass'], cancelled=row['cancelled'], winner=row['winner'],
                            status=row['status'])
                if acceptance:
                    line['accepted'] = row['accepted']
                print(json.dumps(line), flush=True)

    with ThreadPoolExecutor(max_workers=per_node * 4) as pool:
        for future in [pool.submit(worker, e) for e in ENDPOINTS for _ in range(per_node)]:
            future.result()
    cases = cases_summary(rows, jobs, acceptance)
    write(output / 'cases.json', cases)
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), batch_wall_seconds=time.monotonic() - start,
                started_jobs=len(rows), errors=errors, server_after={e: server_metrics(e, timeout=3) for e in ENDPOINTS},
                final_source_sha256=hashes(source), **(dict(holds=holds.summary()) if holds is not None else {}),
                summary=dict(cases=len(cases), solved=sum(c['solved'] for c in cases), answered=sum(c['answered'] for c in cases),
                             cancelled=sum(c['cancelled'] for c in cases), never_started=sum(c['never_started'] for c in cases)))
    meta['source_changed_during_run'] = before != meta['final_source_sha256']
    write(output / 'metadata.json', meta)
    print(json.dumps(meta['summary']))
    return int(bool(errors) or meta['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
