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
  roll8strategy roll8cancel, but each escalation agent (slot >= 4) gets one of the four task-agnostic strategy hints
                (STRATEGIES[slot - 4]); the first four agents are unchanged
  esc_none, esc_strategy, esc_h02, esc_split
                escalation-only arms for a shared first wave (deep4cancel run once): slots 4-11 only, 4 in flight,
                failure-driven replacement, cancel on accept, on the plan's case_list (cases whose first wave had no
                accepted plan). Hints per escalation slot: none / STRATEGIES[(slot-4)%4] (as roll12strategy) /
                STRATEGIES[(0, 2)[(slot-4)%2]] / SPLIT_HINTS[(slot-4)%4] (partition of the last move).
  roll12burst   roll8cancel with a cap of 12 agents and a time trigger: if no plan is accepted BURST_SECONDS after the
                case started, 8 agents are kept in flight instead of 4 (failures still replaced, first accept cancels)
Every agent record carries timing (seconds from case start); decisions of the original policies are unchanged.
The exact verifier never influences decisions; it only scores the selected plan.
"""
import argparse
import json
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
             'esc_h02': lambda slot: STRATEGIES[(0, 2)[(slot - 4) % 2]], 'esc_split': lambda slot: SPLIT_HINTS[(slot - 4) % 4]}
JUDGE_TAIL = 'Return only a JSON object {"valid": true} if every move is legal and the target appears, otherwise {"valid": false}.'
REASON_TAIL = ('Return only a JSON object {"valid": true} if every move is legal and the target appears; otherwise '
               '{"valid": false, "reason": "<one sentence: the first illegal move, or why the target never appears>"}.')


def judge_with_reason(candidate, endpoint, events_path, seed):
    """Same thinking judge as run_judge.judge, but asks for a one-sentence reason when rejecting."""
    events = run_judge.Events(events_path, 'judge_reason')
    try:
        client = run_judge.ChatJudge(endpoint, 'nemotron-lightning', run_judge.Budget(2, 8192), events, seed)
        prompt = run_judge.judge_prompt(candidate['numbers'], candidate['target'], candidate['plan'])
        require(prompt.endswith(JUDGE_TAIL), 'judge prompt changed')
        prompt = prompt[:-len(JUDGE_TAIL)] + REASON_TAIL
        ids = client.chat_prompt_ids(prompt, thinking=True)
        first = client.complete(0, 'judge', ids, 6144)
        answer = first['answer']
        if answer is None and first['finish_reason'] == 'length' and first['error'] is None:
            second = client.complete(0, 'judge_forced', ids + first['token_ids'] + client.force_ids(),
                                     8192 - client.budget.snapshot()['completion_tokens_charged'], thinking_closed=True)
            answer = second['answer']
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
        return out
    finally:
        events.close()


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
              node=None):
    """One agent + its judge. race (cancel policies): dict(cancel=Event, accept=callable) shared by the case.
    node: endpoint index override (escalation agents run on the node of the agent they replace)."""
    t0 = time.monotonic() if t0 is None else t0
    cancel = race['cancel'] if race else None
    endpoint = ENDPOINTS[(case_index + slot) % 4 if node is None else node]
    stem = f"{task['id']}-s{seed}-{policy}-a{slot}"
    events = out / 'agents' / (stem + '.jsonl')
    extra_file = None
    if extra:
        extra_file = out / 'extra' / (stem + '.txt')
        extra_file.write_text(extra)
    command = [sys.executable, str(source / 'forced72_worker.py'), '--run', '--variant', plan['agent_variant'],
               '--puzzle', ','.join(map(str, task['numbers'])) + ':' + str(task['target']), '--endpoint', endpoint,
               '--seed', str(1000 * seed + seed_offset + slot), '--events', str(events), '--model', 'nemotron-lightning']
    if extra_file:
        command[2:2] = ['--extra-file', str(extra_file)]
    job = dict(task_id=task['id'], split='development', arm=policy, seed=seed, endpoint=endpoint, command=command,
               events=str(events), stdout=str(events).replace('.jsonl', '.stdout.log'),
               stderr=str(events).replace('.jsonl', '.stderr.log'), shared_endpoint=True, stop_on_solution=False)
    timing = dict(queued_s=round(time.monotonic() - t0, 3))
    with slots(endpoint):
        if cancel is not None and cancel.is_set():  # case already answered while this agent waited for a slot
            return dict(plan=None, verifier_solved=False, tokens=0, infra=0, slot=slot, extra=bool(extra), deadline=False,
                        verdict=None, reason='', judge_tokens=0, judge_infra=0, started=False, cancelled=False,
                        judge_skipped=False, **timing)
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
    info.update(slot=slot, extra=bool(extra), deadline=bool(row['deadline']), verdict=None, reason='', judge_tokens=0, judge_infra=0)
    if race:
        info.update(started=True, cancelled=cancelled, judge_skipped=False)
    if info['plan'] is not None:
        cand = dict(numbers=task['numbers'], target=task['target'], plan=info['plan'])
        with slots(endpoint):
            if cancel is not None and cancel.is_set():
                info['judge_skipped'] = True
            else:
                j = judge_with_reason(cand, endpoint, out / 'judges' / (stem + '.jsonl'), 90000 + 1000 * seed + 10 * case_index + slot)
                info.update(verdict=j['verdict'], reason=j['reason'], judge_tokens=j['tokens'], judge_infra=j['infra'])
                timing['judged_s'] = round(time.monotonic() - t0, 3)
                if race and info['verdict'] is True:
                    race['accept'](slot)
    info.update(timing)
    return info


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
        info = agent(slot, node, extra) if feedback else agent(slot, node)
        with lock:
            results.append(info)
            state['running'] -= 1
            while (race['winner'] is None and not race['cancel'].is_set() and state['next'] < cap
                   and state['running'] < state['width']):
                nxt = state['next']
                state['next'] += 1
                launch(nxt, node if state['running'] == state['width'] - 1 else (case_index + nxt) % 4)

    def burst():
        if race['cancel'].wait(burst_seconds):
            return
        with lock:
            if race['winner'] is not None or state.get('closed'):
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


def new_race(t0):
    """Shared per-case cancel state: the first accepted agent (in time) wins and cancels the rest."""
    lock, race = threading.Lock(), dict(cancel=threading.Event(), winner=None, answer_s=None)

    def accept(slot):
        with lock:
            if race['winner'] is None:
                race.update(winner=slot, answer_s=round(time.monotonic() - t0, 3))
                race['cancel'].set()
    race['accept'] = accept
    return race


def run_policy(plan, source, out, task, seed, case_index, policy, slots):
    off = plan['seed_offsets'][policy]
    t0 = time.monotonic()
    race = new_race(t0) if policy in ('deep4cancel', 'waves2cancel', 'roll8cancel', 'roll3to8', 'roll3strategy', 'roll8repair', 'roll8strategy', 'roll12strategy', 'roll12burst') or policy in ESC_HINTS else None
    agent = lambda slot, extra='': run_agent(plan, source, out, task, seed, case_index, policy, slot, extra, slots, off, t0, race)
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
        agents = rolling(lambda slot, node: run_agent(plan, source, out, task, seed, case_index, policy, slot, '', slots,
                                                      off, t0, race, node), race, case_index)
    elif policy == 'roll8repair':
        def board(done):
            rejected = [a for a in done if a['plan'] is not None and a['verdict'] is False]
            if not rejected:
                return ''
            return ('Earlier attempts on this exact task failed:\n' + '\n'.join(critique(a) for a in rejected) +
                    '\nAvoid these mistakes and give a corrected complete plan.')
        agents = rolling(lambda slot, node, extra='': run_agent(plan, source, out, task, seed, case_index, policy, slot,
                                                                extra or '', slots, off, t0, race, node),
                         race, case_index, feedback=board)
    elif policy == 'roll3to8':
        agents = rolling(lambda slot, node: run_agent(plan, source, out, task, seed, case_index, policy, slot, '', slots,
                                                      off, t0, race, node), race, case_index, width=3)
    elif policy == 'roll3strategy':
        agents = rolling(lambda slot, node: run_agent(plan, source, out, task, seed, case_index, policy, slot,
                                                      STRATEGIES[(slot - 3) % 4] if slot >= 3 else '', slots, off, t0, race, node),
                         race, case_index, width=3)
    elif policy == 'roll12strategy':
        agents = rolling(lambda slot, node: run_agent(plan, source, out, task, seed, case_index, policy, slot,
                                                      STRATEGIES[(slot - 4) % 4] if slot >= 4 else '', slots, off, t0, race, node),
                         race, case_index, cap=12)
    elif policy == 'roll8strategy':
        agents = rolling(lambda slot, node: run_agent(plan, source, out, task, seed, case_index, policy, slot,
                                                      STRATEGIES[(slot - 4) % 4] if slot >= 4 else '', slots, off, t0, race, node),
                         race, case_index)
    elif policy in ESC_HINTS:
        hint = ESC_HINTS[policy]
        agents = rolling(lambda slot, node: run_agent(plan, source, out, task, seed, case_index, policy, slot, hint(slot), slots,
                                                      off, t0, race, node), race, case_index, cap=12, first=4)
    elif policy == 'roll12burst':
        agents = rolling(lambda slot, node: run_agent(plan, source, out, task, seed, case_index, policy, slot, '', slots,
                                                      off, t0, race, node), race, case_index, cap=12,
                         burst_seconds=plan.get('burst_seconds', 900))
    else:
        raise ValueError(policy)
    if race:  # answer = first accepted in time
        selected = next((a for a in agents if a['slot'] == race['winner']), None)
        selection = dict(selected_slot=race['winner'], answer_seconds=race['answer_s'],
                     cancelled_agents=sum(a['cancelled'] for a in agents),
                     unstarted_agents=sum(not a['started'] for a in agents) + max(0, 4 - len(agents)),
                     escalated_agents=sum(a['slot'] >= (3 if policy in ('roll3to8', 'roll3strategy') else 4) and a['started'] for a in agents),
                     burst=bool(race.get('burst_at')),
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
    data = read(HERE / plan['dataset'])
    require(data.get('protocol') == plan['dataset_protocol'], 'Wrong corpus')
    tasks = [t for t in data['tasks'] if t['split'] == plan['split']]
    if plan.get('task_ids'):  # optional subset (smoke plans)
        tasks = [t for t in tasks if t['id'] in plan['task_ids']]
    if plan.get('numbers_count'):  # optional: only tasks with this many numbers
        tasks = [t for t in tasks if len(t['numbers']) == plan['numbers_count']]
    require(len(tasks) == plan['tasks'], 'Wrong task count')
    policies = a.policy or plan['policies']
    require(set(policies) <= set(plan['policies']), 'Policy not in plan')
    jobs = [(t, s, si * len(tasks) + ti, pol) for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks) for pol in policies]
    if plan.get('case_list'):  # optional: only these (task_id, seed) cases; case indices (node placement) are kept
        keep = {(c[0], c[1]) for c in read(HERE / plan['case_list'])['cases']}
        jobs = [j for j in jobs if (j[0]['id'], j[1]) in keep]
        require(len(jobs) == len(keep) * len(policies), 'case_list does not match the corpus')
    concurrent = plan['concurrent_policy_cases']
    if len(policies) == 1:  # optional per-arm case concurrency (e.g. two-agent waves keep the same per-node load)
        concurrent = plan.get('concurrent_policy_cases_by_policy', {}).get(policies[0], concurrent)
    resumed = None
    if a.resume_from:  # continuation after an infrastructure stop: same plan, only unfinished policy cases
        prev = [json.loads(line) for line in (a.resume_from / 'cases.jsonl').read_text().splitlines()]
        finished = {(r['task_id'], r['seed'], r['policy']) for r in prev if 'error' not in r and not r['infra']}
        jobs = [j for j in jobs if (j[0]['id'], j[1], j[3]) not in finished]
        resumed = dict(resumed_from=str(a.resume_from.resolve()), skipped_finished=len(finished))
    if not a.run:
        print(json.dumps(dict(mode='plan', policy_cases=len(jobs), model_calls=0)))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not out.exists(), 'Frozen plan, admission, new output')
    adm = read(a.admission)
    require(adm.get('verified') is True and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds() <= 900, 'Fresh admission')
    for d in ('agents', 'judges', 'extra'):
        (out / d).mkdir(parents=True, exist_ok=d != 'agents')
    write(out / 'metadata.json', dict(protocol=plan, runner_sha256=sha(Path(__file__)), resume=resumed, policies=policies,
                                      concurrent_policy_cases=concurrent, started_utc=datetime.now(timezone.utc).isoformat(), admission=adm))
    slots, lock, stop, rows = Slots(plan['concurrent_requests_per_endpoint']), threading.Lock(), threading.Event(), []

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
