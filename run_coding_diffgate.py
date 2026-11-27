#!/usr/bin/env python3
"""Coding swarm with a LIVE differential-consensus gate (DIFFGATE_LIVE_PLAN.json, gate arm): the production public-test
early-stop runner (run_coding_earlystop.py: R2 rolling, code_elastic workers, the same jobs, seeds, endpoints, grading
and fault rules) except that a public-test pass does not end the case.

  passer     an agent whose final proposal passes all public feedback tests (puzzle_end feedback_pass, code)
  order      the worker's trace is tailed and its public-pass event (feedback evaluation_end, passed) is announced
             with its recorded time BEFORE holdout grading; passers vote strictly in that public-pass order, an
             announced passer still in holdout grading holds the later ones; holdout results never reach the gate
  distinct   byte-identical code (sha256) counts once
  rolling    a passer that does not decide the case counts as an ended agent for the replacement rule, so agents keep
             starting up to the plan's cap (agent_variants)
  generator  at the case's first passer, one generator call (research/diffgate-v1 diffgate_gen.py --one, frozen
             generic prompt, {function_name, spec} payload) on that passer's endpoint (its worker thread runs the
             call, so no node exceeds its per-node cap); its reply's code runs in
             the sandbox (generate mode) for the inputs; unusable inputs -> one more call; still unusable -> fallback
  sandbox    each distinct passer runs on the inputs in inkling/sandbox_outputs.py on the case's agent-0 host
             (Spark_01..04 only, verified identity, host-side deadline, cap and cleanup); behaviour = the outcome
             sha256 vector; a passer that cannot run has no behaviour and never votes
  vote       ACCEPT as soon as one behaviour class holds >= 2 distinct passers; the answer is the class member that
             passed first; fallback (no usable inputs): accept at 2 distinct passers; the case's other agents are
             terminated and queued ones never start (as the control does at its first pass)
  abstain    all agents ended without a class of >= 2: unanswered
  faults     a generator transport fault or a sandbox infrastructure fault stops admissions (like a worker fault)

SIGINT / SIGTERM latch only: running executors see the latch at their next poll and terminate and reap their worker;
admissions stop and generator processes are terminated. A worker's own fault is checked before it votes, and a winner
is published only while the stop latch is clear. Concurrency: plan.scheduling.concurrent_agents_per_node counts client
dispatch slots (worker threads per endpoint); a generator call runs inside the triggering slot, so each node sees at
most that many client requests at a time (sandbox runs are CPU containers on the hosts, outside that count).
Gate records: OUTPUT/gate.jsonl (one line per case event) and metadata.gate. Plan-only by default.
"""
import argparse
import hashlib
import json
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import run_coding_earlystop as base
from run_agents72 import read, require, sha, validate_source, write
from run_benchmark import append_controller_stop, metrics, read_trace, server_metrics, terminate
from run_coding_agents import ENDPOINTS, HERE, HOSTS, PROTOCOL, agent_outcome, hashes, make_jobs

sys.path.insert(0, str(HERE / 'inkling'))
import diffgate_exec  # noqa: E402  (generator_code)
import sandbox_outputs  # noqa: E402

GATE = 'differential_v1'
GEN_ATTEMPTS, GEN_TIMEOUT, PER_INPUT, PROGRAM_TIMEOUT = 2, 10.0, 2.0, 60.0


class GateFault(RuntimeError):
    pass


def final_code(events):
    records, _ = read_trace(Path(events))
    end = next((r for r in reversed(records) if r.get('type') == 'puzzle_end'), {})
    code = end.get('code')
    return code if isinstance(code, str) and code.strip() else None


def run_generator(gate_cfg, item, endpoint, events, stop, popen=subprocess.Popen, poll=0.5):
    """One generator call in its own process (diffgate_gen.py --one); terminated on a stop. Returns its record."""
    events = Path(events)
    config = events.with_suffix('.config.json')
    config.write_text(json.dumps(dict(system=gate_cfg['system'], user=gate_cfg['user'],
                                      think_tokens=gate_cfg['think_tokens'], total_tokens=gate_cfg['total_tokens'],
                                      item=item)))
    source = HERE / gate_cfg['source_path']
    out = events.with_suffix('.out')
    with out.open('w') as sink:
        process = popen([sys.executable, str(source / 'diffgate_gen.py'), '--one', str(config), '--endpoint', endpoint,
                         '--events', str(events)], cwd=source, stdout=sink, stderr=subprocess.STDOUT,
                        start_new_session=True)  # its own process group: terminate() signals the group
        while process.poll() is None:
            if stop.is_set() or base.ABORT:
                terminate(process)
                raise GateFault('stopped during a generator call')
            time.sleep(poll)
    try:
        record = json.loads(out.read_text().strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise GateFault(f'generator process gave no record: {exc}')
    if record.get('error'):
        raise GateFault(f"generator fault: {record['error']}")
    return record


class CaseGate:
    """The gate state of one case; every method runs under the case lock."""

    def __init__(self, key, task, endpoint, host, folder, gate_cfg, stop, runner=sandbox_outputs.run,
                 generator=run_generator):
        self.key, self.task, self.endpoint, self.host, self.folder = key, task, endpoint, host, Path(folder)
        self.cfg, self.stop, self.runner, self.generator = gate_cfg, stop, runner, generator
        self.lock, self.order_lock = threading.Lock(), threading.Lock()
        self.passers, self.inputs, self.fallback, self.decision = [], None, False, None
        self.announced, self.ready_code, self.processed = {}, {}, set()
        self.generator_tokens, self.generator_calls, self.sandbox_seconds, self.duplicates = 0, 0, 0.0, 0

    def _inputs(self):
        if self.inputs is not None or self.fallback:
            return
        payload = json.dumps({'function_name': self.task['function_name'], 'spec': self.task['spec']},
                             ensure_ascii=False)
        for attempt in range(GEN_ATTEMPTS):
            item = dict(item_id=f'{self.key[0]}-s{self.key[1]}-g{attempt}', payload=payload)
            rec = self.generator(self.cfg, item, self.endpoint, self.folder / f'{item["item_id"]}.jsonl', self.stop)
            self.generator_calls += 1
            self.generator_tokens += rec.get('tokens_generated') or 0
            if rec.get('outcome') != 'ok':
                continue
            out = self.runner('generate', diffgate_exec.generator_code(rec['reply']), 'generate_inputs', self.host,
                              total_timeout=GEN_TIMEOUT)
            self.sandbox_seconds += out.get('container_seconds') or 0.0
            if out.get('infrastructure'):
                raise GateFault(f"sandbox (generate): {out.get('error')}")
            if out.get('status') == 'ok' and out.get('inputs'):
                self.inputs = out['inputs']
                return
        self.fallback = True

    def add(self, agent, code, passed_at, endpoint=None):
        """A new passer; returns the accepted agent or None. endpoint: where a generator call goes (the passer's own
        node, whose worker thread runs it, so no node exceeds its per-node request cap)."""
        if endpoint is not None:
            self.endpoint = endpoint
        if self.decision is not None:
            return None
        digest = hashlib.sha256(code.encode()).hexdigest()
        if any(p['sha'] == digest for p in self.passers):
            self.duplicates += 1
            return None
        passer = dict(agent=agent, sha=digest, t=passed_at, behaviour=None, status=None)
        self.passers.append(passer)
        self._inputs()
        if self.fallback:
            if len(self.passers) >= 2:
                first = min(self.passers, key=lambda p: p['t'])
                self.decision = dict(agent=first['agent'], rule='fallback', class_size=len(self.passers))
                return first['agent']
            return None
        out = self.runner('outputs', code, self.task['function_name'], self.host, inputs=self.inputs,
                          per_input=PER_INPUT, total_timeout=PROGRAM_TIMEOUT)
        self.sandbox_seconds += out.get('container_seconds') or 0.0
        if out.get('infrastructure'):
            raise GateFault(f"sandbox (outputs): {out.get('error')}")
        passer['status'] = out.get('status')
        outcomes = [o['sha256'] for o in out.get('outcomes') or []]
        if out.get('status') == 'ok' and len(outcomes) == len(self.inputs):
            passer['behaviour'] = hashlib.sha256('|'.join(outcomes).encode()).hexdigest()
        if passer['behaviour'] is None:
            return None
        members = [p for p in self.passers if p['behaviour'] == passer['behaviour']]
        if len(members) >= 2:
            first = min(members, key=lambda p: p['t'])
            self.decision = dict(agent=first['agent'], rule='class', class_size=len(members))
            return first['agent']
        return None

    def announce(self, agent, ts):
        """A public-pass event (recorded before holdout grading); only the order lock, never the gate lock."""
        with self.order_lock:
            self.announced.setdefault(agent, ts)

    def ready(self, agent, code):
        """The agent's worker ended: its final code if it is a passer, else None (it never votes). Caller holds
        self.lock."""
        with self.order_lock:
            self.ready_code[agent] = code

    def process(self, endpoint=None):
        """Vote the announced passers in public-pass order (ts, agent) while the next one is ready; an announced
        passer whose worker is still running (holdout grading) holds the later ones. Returns the decided agent or
        None. Caller holds self.lock."""
        while self.decision is None:
            with self.order_lock:
                order = sorted((ts, a) for a, ts in self.announced.items() if a not in self.processed)
                if not order:
                    return None
                ts, agent = order[0]
                if agent not in self.ready_code:
                    return None
                code = self.ready_code[agent]
            self.processed.add(agent)
            if code is not None:
                decided = self.add(agent, code, ts, endpoint=endpoint)
                if decided is not None:
                    return decided
        return None

    def summary(self):
        behaviours = {p['behaviour'] for p in self.passers if p['behaviour'] is not None}
        return dict(task_id=self.key[0], seed=self.key[1], passers=len(self.passers), duplicates=self.duplicates,
                    announced=len(self.announced), unannounced=sum(1 for a, c in self.ready_code.items()
                                                                  if c is not None and a not in self.announced),
                    behaviours=len(behaviours), fallback=self.fallback, inputs=len(self.inputs or []),
                    generator_calls=self.generator_calls, generator_tokens=self.generator_tokens,
                    sandbox_seconds=round(self.sandbox_seconds, 3), decision=self.decision,
                    all_passers_agree=len(self.passers) >= 2 and len(behaviours) == 1
                    and all(p['behaviour'] is not None for p in self.passers))


def pass_time(event):
    """The public-pass event: evaluation_end of the feedback phase with a passed report; its recorded time (epoch)."""
    if event.get('type') != 'evaluation_end' or event.get('phase') != 'feedback':
        return None
    report = event.get('report')
    if not isinstance(report, dict) or report.get('status') != 'passed':
        return None
    try:
        return datetime.fromisoformat(event['timestamp']).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


def execute_gated(case, deadline_seconds, cancel, announce, poll=.1):
    """run_variants.execute_cancellable plus: the worker's trace is tailed and its public-pass event is announced to the
    gate as soon as it is recorded (before holdout grading); a latched ABORT (SIGINT / SIGTERM) terminates and reaps
    the worker at once (row aborted)."""
    start = time.monotonic()
    deadline = cancelled = aborted = announced = False
    error = returncode = None
    trace, offset = Path(case['events']), 0

    def tail():
        nonlocal offset, announced
        if announced or not trace.exists():
            return
        with trace.open('rb') as stream:
            stream.seek(offset)
            data = stream.read()
        end = data.rfind(b'\n') + 1
        offset += end
        for line in data[:end].splitlines():
            try:
                ts = pass_time(json.loads(line))
            except ValueError:
                continue
            if ts is not None:
                announced = True
                announce(ts)
                return
    with Path(case['stdout']).open('x') as stdout, Path(case['stderr']).open('x') as stderr:
        try:
            process = subprocess.Popen(case['command'], cwd=HERE, stdout=stdout, stderr=stderr, start_new_session=True)
            while True:
                tail()
                if process.poll() is not None:
                    returncode = process.returncode
                    break
                if base.ABORT:
                    aborted, returncode = True, terminate(process)
                    break
                if cancel.is_set():
                    cancelled, returncode = True, terminate(process)
                    break
                if time.monotonic() - start >= deadline_seconds:
                    deadline, returncode = True, terminate(process)
                    break
                time.sleep(poll)
            tail()  # a pass recorded just before the exit
        except OSError as exc:
            error = f'{type(exc).__name__}: {exc}'
    records, _ = read_trace(trace)
    row = dict(metrics(records, deadline), returncode=returncode, controller_error=error, deadline=deadline,
               cancelled=cancelled or aborted, aborted=aborted, wall_seconds=round(time.monotonic() - start, 6),
               controller_stop=cancelled or deadline or aborted, server_cost_known=False,
               server_cost_reason='shared_endpoint', server_prompt_tokens=None, server_completion_tokens=None,
               server_idle_after=None, time_to_verified_solution_seconds=None)
    if cancelled or aborted:
        row.update(status='cancelled' if cancelled else 'aborted', solved=False)
    if row['controller_stop']:
        append_controller_stop(trace, records, row, case)
    return row


def check_gate(plan):
    gate = plan.get('differential_gate') or {}
    require(gate.get('rule') == GATE and plan.get('acceptance') is None
            and plan.get('early_stop') == 'first_feedback_pass_in_time' and plan.get('rolling'),
            'the gate runner needs differential_gate.rule differential_v1 on the public-test rolling path')
    require(all(k in gate for k in ('system', 'user', 'think_tokens', 'total_tokens', 'source_path',
                                    'source_revision')), 'incomplete differential_gate')
    return gate


def main(argv=None, generator=run_generator, runner=sandbox_outputs.run):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == PROTOCOL, 'Wrong protocol')
    gate_cfg = check_gate(plan)
    source, output = a.source.expanduser().resolve(), a.output.resolve()
    validate_source(source, plan['source_revision'])
    validate_source(HERE / gate_cfg['source_path'], gate_cfg['source_revision'])
    before = hashes(source)
    tasks_path, tests_path = HERE / plan['matrix']['tasks'], HERE / plan['matrix']['tests']
    require(sha(tasks_path) == plan['matrix']['tasks_sha256'] and sha(tests_path) == plan['matrix']['tests_sha256'],
            'Corpus hash differs')
    tasks = [t for t in read(tasks_path)['tasks'] if t['split'] == plan['matrix']['split']]
    require(len(tasks) == plan['matrix']['tasks_count'], 'Wrong task count')
    by_task = {t['id']: t for t in tasks}
    jobs = make_jobs(tasks, output, source, plan, tasks_path, tests_path)
    per_node, deadline = plan['scheduling']['concurrent_agents_per_node'], plan['limits']['agent_wall_deadline_seconds']
    meta = dict(protocol=plan, plan_sha256=sha(a.plan), jobs=len(jobs), source_sha256=before, output=str(output),
                runner_sha256=sha(Path(__file__)))
    if not a.run:
        print(json.dumps(dict(mode='plan', jobs=len(jobs), model_calls=0, agents=len(plan['agent_variants']),
                              gate=GATE)))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not output.exists(),
            'Frozen plan, admission and new output required')
    admission = read(a.admission)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(admission['verified_utc'])).total_seconds()
    require(admission.get('verified') is True and 0 <= age <= 900, 'Fresh admission required')
    require(admission.get('plan_sha256') == sha(a.plan) and admission.get('allow_busy') is False
            and admission.get('source_revision') == plan['source_revision'], 'Admission not bound to this plan')
    output.mkdir(parents=True)
    (output / 'gate').mkdir()
    meta.update(started_utc=datetime.now(timezone.utc).isoformat(), admission=admission,
                server_before={e: server_metrics(e, timeout=3) for e in ENDPOINTS})
    write(output / 'metadata.json', meta)
    rows, errors, lock, stop = [], [], threading.Lock(), threading.Event()
    cancel = {(j['task_id'], j['seed']): threading.Event() for j in jobs}
    gates = {}
    for j in jobs:
        key = (j['task_id'], j['seed'])
        if j['agent'] == 0:
            gates[key] = CaseGate(key, by_task[j['task_id']], j['endpoint'], HOSTS[j['slot']], output / 'gate',
                                  gate_cfg, stop, runner=runner, generator=generator)
    first_start, ended, winners = {}, {}, {}
    rolling = plan['rolling']
    first_k = rolling['width']
    queues = {e: iter([j for j in jobs if j['endpoint'] == e and j['agent'] < first_k]) for e in ENDPOINTS}
    later = {e: [j for j in jobs if j['endpoint'] == e and j['agent'] >= first_k] for e in ENDPOINTS}
    start = time.monotonic()
    gate_log = output / 'gate.jsonl'

    def take(endpoint):
        pending = later[endpoint]
        pending[:] = [j for j in pending if not cancel[(j['task_id'], j['seed'])].is_set()]
        for j in pending:
            k = (j['task_id'], j['seed'])
            if ended.get(k, 0) >= j['agent'] - first_k + 1:  # failures AND undecided passers end an agent
                pending.remove(j)
                return j, False
        job = next(queues[endpoint], None)
        while job is not None and cancel[(job['task_id'], job['seed'])].is_set():
            job = next(queues[endpoint], None)
        return job, bool(pending)

    def latch(reason, **fields):
        """Stop admissions (caller holds the lock). On a signal every running worker is also terminated and reaped
        by its executor (its case's cancel event); on a fault running workers finish, as in the control."""
        stop.set()
        errors.append(dict(reason=reason, **fields))
        if reason == 'signal':
            for event in cancel.values():
                event.set()

    def worker(endpoint):
        while True:
            with lock:
                if base.ABORT and not any(e.get('reason') == 'signal' for e in errors):
                    latch('signal', signals=list(base.ABORT))
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
                    latch('source_check_exception', detail=str(exc)[:300])
                    return
                if changed:
                    latch('source_changed', events=job['events'])
                    return
                key = (job['task_id'], job['seed'])
                first_start.setdefault(key, time.monotonic())
            gate = gates[key]
            try:
                row = execute_gated(job, deadline, cancel[key],
                                    announce=lambda ts, agent=job['agent'], g=gate: g.announce(agent, ts))
                row.update({k: job[k] for k in ('task_id', 'split', 'arm', 'seed', 'endpoint', 'events')},
                           agent=job['agent'], case_index=job['case_index'],
                           malformed_lines=read_trace(Path(job['events']))[1], **agent_outcome(job['events']))
                if row['cancelled'] or row['aborted']:
                    row.update(feedback_pass=False, holdout_pass=False)
            except Exception as exc:
                with lock:
                    latch('controller_exception', events=job['events'], detail=str(exc)[:300])
                return
            with lock:  # the worker's own fault is checked BEFORE any vote
                reason = base.fault(row) or ('aborted_by_signal' if row['aborted'] else None)
                if reason:
                    latch(reason, events=job['events'])
            code = final_code(job['events']) if row['feedback_pass'] and not row['cancelled'] and not reason else None
            decided = None
            try:
                with gate.lock:  # passers vote in public-pass order (announced before holdout grading)
                    gate.ready(job['agent'], code)
                    if not stop.is_set() and not cancel[key].is_set():
                        decided = gate.process(endpoint=job['endpoint'])
            except GateFault as exc:
                with lock:
                    latch('gate_fault', events=job['events'], detail=str(exc)[:300])
            except Exception as exc:
                with lock:
                    latch('gate_exception', events=job['events'], detail=f'{type(exc).__name__}: {str(exc)[:300]}')
            with lock:  # publication is serialized against the stop latch: no winner after a fault or a signal
                row['winner'] = False
                rows.append(row)
                if decided is not None and not stop.is_set() and not cancel[key].is_set():
                    winners[key] = (decided, round(time.monotonic() - first_start[key], 1))
                    cancel[key].set()
                if key in winners:  # the winner's row may be appended before or after the deciding passer's
                    for r in rows:
                        if (r['task_id'], r['seed']) == key and r['agent'] == winners[key][0] and not r['winner']:
                            r.update(winner=True, stop_seconds=winners[key][1])
                if decided is None and not row['cancelled'] and key not in winners:
                    ended[key] = ended.get(key, 0) + 1  # failed, or passed without deciding the case
                if code is not None or decided is not None:
                    with gate_log.open('a') as sink:
                        sink.write(json.dumps(dict(event='passer', agent=job['agent'], decided=decided,
                                                   **gate.summary())) + '\n')
                write(output / 'summary.json', rows)
                print(json.dumps(dict(done=len(rows), total=len(jobs), task_id=row['task_id'], agent=row['agent'],
                                      feedback=row['feedback_pass'], cancelled=row['cancelled'],
                                      decided=decided)), flush=True)

    handlers = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, base.on_signal)  # latch only
    signal.signal(signal.SIGTERM, base.on_signal)
    try:
        with ThreadPoolExecutor(max_workers=per_node * 4) as pool:
            for future in [pool.submit(worker, e) for e in ENDPOINTS for _ in range(per_node)]:
                future.result()
    finally:
        signal.signal(signal.SIGINT, handlers[0])
        signal.signal(signal.SIGTERM, handlers[1])
    cases = base.cases_summary(rows, jobs, None)
    write(output / 'cases.json', cases)
    gate_cases = [g.summary() for g in gates.values()]
    write(output / 'gate_cases.json', gate_cases)
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), batch_wall_seconds=time.monotonic() - start,
                started_jobs=len(rows), errors=errors,
                server_after={e: server_metrics(e, timeout=3) for e in ENDPOINTS},
                final_source_sha256=hashes(source),
                gate=dict(generator_calls=sum(g['generator_calls'] for g in gate_cases),
                          generator_tokens=sum(g['generator_tokens'] for g in gate_cases),
                          sandbox_seconds=round(sum(g['sandbox_seconds'] for g in gate_cases), 1),
                          fallback_cases=sum(g['fallback'] for g in gate_cases)),
                summary=dict(cases=len(cases), solved=sum(c['solved'] for c in cases),
                             answered=sum(c['answered'] for c in cases),
                             cancelled=sum(c['cancelled'] for c in cases),
                             never_started=sum(c['never_started'] for c in cases)))
    meta['source_changed_during_run'] = before != meta['final_source_sha256']
    write(output / 'metadata.json', meta)
    print(json.dumps(meta['summary']))
    return int(bool(errors) or meta['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
