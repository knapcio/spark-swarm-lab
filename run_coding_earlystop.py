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
sandbox (self_tests) or the judge accepts it (judge) instead of on the feedback cases. The winner is the first proposal
ACCEPTED in time: the worker records its decision as an 'acceptance' trace event before any hidden grading, and the
controller claims the case the moment it observes that event (execute_accepting); the agent's agent deadline applies only
until its decision, the hidden feedback and holdout grading that follows is for scoring only (bounded by
SCORING_GRACE_SECONDS) and can neither change the winner nor be cut by the deadline. A case is solved if the winner passes
ALL hidden cases (feedback and holdout). Without the field everything is as before. Plan-only by default.
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
EARLY_STOP = {None: 'first_feedback_pass_in_time', 'self_tests': 'first_accepted_in_time', 'judge': 'first_accepted_in_time'}
SCORING_GRACE_SECONDS = 600  # hidden grading after a decision: two sandbox grades, normally well under a minute


class TraceTail:
    """Complete JSON lines appended to a worker trace since the last read (a partial last line waits)."""
    def __init__(self, path):
        self.path, self.offset = Path(path), 0

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


def execute_accepting(case, deadline_seconds, cancel, claim, grace_seconds=SCORING_GRACE_SECONDS, poll=.1):
    """execute_cancellable for the no-provided-tests modes. The worker's 'acceptance' event is the decision: when it is
    accepted, claim() (under the controller lock) makes this agent the case winner if the case is still open, which also
    sets the case's cancel event for the OTHER agents; the winner itself is never terminated by it. The agent deadline
    applies only until the decision; after it the hidden scoring may take up to grace_seconds (then terminated and
    flagged scoring_timeout). Returns the run_benchmark row plus accepted, won, decision_seconds, scoring_timeout."""
    start = time.monotonic()
    deadline = cancelled = scoring_timeout = won = False
    error = returncode = decision = decided = None
    tail = TraceTail(case['events'])

    def observe():
        nonlocal decision, decided, won
        if decision is None:
            event = tail.find('acceptance')
            if event is not None:
                decision, decided = bool(event.get('accepted')), time.monotonic()
                won = bool(decision and claim())

    with Path(case['stdout']).open('x') as stdout, Path(case['stderr']).open('x') as stderr:
        try:
            process = subprocess.Popen(case['command'], cwd=HERE, stdout=stdout, stderr=stderr, start_new_session=True)
            while True:
                observe()  # before poll(): a decision written just before exit is still seen in time order
                if process.poll() is not None:
                    returncode = process.returncode
                    break
                if cancel.is_set() and not won:
                    cancelled, returncode = True, terminate(process)
                    break
                now = time.monotonic()
                if decision is None and now - start >= deadline_seconds:
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
    trace = Path(case['events'])
    records, _ = read_trace(trace)
    row = dict(metrics(records, deadline), returncode=returncode, controller_error=error, deadline=deadline,
               cancelled=cancelled, wall_seconds=round(time.monotonic() - start, 6), controller_stop=cancelled or deadline,
               server_cost_known=False, server_cost_reason='shared_endpoint', server_prompt_tokens=None,
               server_completion_tokens=None, server_idle_after=None, time_to_verified_solution_seconds=None,
               accepted=bool(decision) and not cancelled, won=won, scoring_timeout=scoring_timeout,
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
    if acceptance:
        for job in jobs:
            job['command'] = job['command'] + ['--acceptance', acceptance]
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
    rows, errors, lock, stop = [], [], threading.Lock(), threading.Event()
    cancel = {(j['task_id'], j['seed']): threading.Event() for j in jobs}
    first_start, first_done, failed = {}, {}, {}
    stagger, rolling = plan.get('stagger'), plan.get('rolling')
    first_k = stagger['first'] if stagger else rolling['width'] if rolling else len(plan['agent_variants'])
    queues = {e: iter([j for j in jobs if j['endpoint'] == e and j['agent'] < first_k]) for e in ENDPOINTS}
    later = {e: [j for j in jobs if j['endpoint'] == e and j['agent'] >= first_k] for e in ENDPOINTS}
    start = time.monotonic()

    def take(endpoint):
        """Next job for this endpoint (caller holds the lock): a due later agent of an open case first, else the next
        first-wave agent of an open case. Returns (job, waiting) where waiting means later agents are not due yet."""
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

    claimed = {}

    def claim(key):
        """First accepted decision of an open case wins it (time order of observation); later ones do not."""
        with lock:
            if cancel[key].is_set():
                return False
            claimed[key] = time.monotonic()
            cancel[key].set()
            return True

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
                if acceptance:
                    row = execute_accepting(job, deadline, cancel[key], lambda key=key: claim(key))
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
                if acceptance:  # the winner was claimed at its decision time (execute_accepting)
                    if row.pop('won'):
                        row.update(winner=True, stop_seconds=round(claimed[key] - first_start[key], 1))
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
                final_source_sha256=hashes(source),
                summary=dict(cases=len(cases), solved=sum(c['solved'] for c in cases), answered=sum(c['answered'] for c in cases),
                             cancelled=sum(c['cancelled'] for c in cases), never_started=sum(c['never_started'] for c in cases)))
    meta['source_changed_during_run'] = before != meta['final_source_sha256']
    write(output / 'metadata.json', meta)
    print(json.dumps(meta['summary']))
    return int(bool(errors) or meta['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
