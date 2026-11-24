"""Judge replay screens (Fable round 4, ideas 3 and 4): the unchanged Inkling judge protocol on RECORDED candidates.

  coding  a generic protocol judge as a second acceptance key: it sees the task statement exactly as the agents saw it
          (coding_harness.context), the candidate program and the protocol line "it passed the available checks; they
          are partial", and answers {"valid": true} or {"valid": false, "reason": ...}. No task-specific tips; the
          system prompt names no domain. Candidates: every recorded winner (the first public-test-passing program of a
          case) of the given coding arms.
  arith   a second, independent call of the unchanged arithmetic judge (run_variants.judge_with_reason, other seed) on
          every recorded accepted plan whose answer was forced at the end of the thinking budget, plus an equal-size
          seeded random sample of accepted self-closed plans as the control.
The exact verifier / hidden-test result is copied into each candidate for scoring only; no decision reads it.
"""
import hashlib
import json
import random
from pathlib import Path

import run_judge
import run_variants

HERE = Path(__file__).resolve().parent
GENERIC_SYSTEM = 'You check proposed answers carefully. Return only the requested JSON object.'
CODING_TAIL = ('Return only a JSON object {"valid": true} if the program meets every requirement of the task statement; '
               'otherwise {"valid": false, "reason": "<one sentence: the first requirement it does not meet>"}.')
SECOND_JUDGE_SALT = 'second-judge-v1'
CODING_JUDGE_SALT = 'coding-judge-v1'
CONTROL_SEED = 'judge-control-v1'


def coding_judge_prompt(task, code):
    """Generic protocol judge prompt for a program: the agents' own task statement + the candidate + the JSON
    protocol. Nothing in it is specific to a task or to programming beyond showing the statement and the program."""
    import coding_harness
    return ('Task statement:\n' + coding_harness.context(task) + '\n\n'
            'A solver proposed the answer below. It passed the available checks; they are partial. Check carefully '
            'whether it meets every requirement of the task statement.\nAnswer:\n```python\n' + code + '\n```\n'
            + CODING_TAIL)


_GENERIC_JUDGE = None


def GenericJudge(*args, **kwargs):  # noqa: N802 - client factory like run_judge.ChatJudge, with a domain-free system
    global _GENERIC_JUDGE
    if _GENERIC_JUDGE is None:
        forced72 = run_judge._forced72()

        class _Judge(forced72.ForcedClient):
            def chat_prompt_ids(self, prompt, thinking=True):
                messages = [{'role': 'system', 'content': GENERIC_SYSTEM}, {'role': 'user', 'content': prompt}]
                with self.post('/tokenize', dict(model=self.model, messages=messages, add_generation_prompt=True,
                                                 chat_template_kwargs={'enable_thinking': thinking}), 60) as response:
                    return json.load(response)['tokens']
        _GENERIC_JUDGE = _Judge
    return _GENERIC_JUDGE(*args, **kwargs)


def stable_seed(*parts):
    return int.from_bytes(hashlib.sha256(':'.join(map(str, parts)).encode()).digest()[:4], 'big') & 0x7FFFFFFF


def trace_end(path):
    """The puzzle_end event of an agent trace ({} if missing)."""
    path = Path(path)
    if not path.exists():
        return {}
    end = {}
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'puzzle_end':
            end = event
    return end


def read(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- coding winners
def coding_winners(run_dir, root=None):
    """Every recorded winner of a coding arm (cases.json answered rows): the winning agent's program, its feedback
    and hidden (holdout) results and whether its answer was forced. Returns (candidates, skipped reasons)."""
    run_dir, root = Path(run_dir), root or HERE
    meta = read(run_dir / 'metadata.json')
    plan = meta['protocol']
    tasks = {t['id']: t for t in read(root / plan['matrix']['tasks'])['tasks']}
    variants = plan['agent_variants']
    out, skipped = [], []
    for row in read(run_dir / 'cases.json'):
        if not row.get('answered'):
            continue
        agent = row['winner_agent']
        trace = run_dir / f"{row['task_id']}-s{row['seed']}-a{agent}-{variants[agent]}.jsonl"
        end = trace_end(trace)
        if not end.get('code') or not end.get('feedback_pass'):
            skipped.append(f"{row['task_id']} s{row['seed']}: winner trace without a feedback-passing program")
            continue
        out.append(dict(part='coding', group='winner', run=run_dir.name, task_id=row['task_id'], seed=row['seed'],
                        agent=agent, code=end['code'], forced=bool(end.get('budget_forced')),
                        truth=bool(end.get('holdout_pass')), recorded_case_solved=bool(row.get('solved')),
                        judge_seed=stable_seed(CODING_JUDGE_SALT, run_dir.name, row['task_id'], row['seed'], agent),
                        statement_task=tasks[row['task_id']]))
    return out, skipped


# ---------------------------------------------------------------- arithmetic accepted plans
def arith_accepted(run_dir, root=None, include_rejected_forced=False):
    """Every judge-accepted plan of a finished arithmetic arm (all its policies, frozen resume rule, latest rows):
    numbers, target, plan, whether the answer was forced (puzzle_end budget_forced) and the verifier result.
    include_rejected_forced: also the forced plans the first judge rejected (verdict False), the set where a second
    judge's false accepts would show (Fable's variance estimate)."""
    run_dir, root = Path(run_dir), root or HERE
    meta = read(run_dir / 'metadata.json')
    out = []
    for policy in meta.get('policies') or meta['protocol']['policies']:
        arm = run_variants.arm_latest(run_dir, root, policy=policy)
        tasks = {t['id']: t for t in arm['tasks']}
        for (task_id, seed), (seg, row) in sorted(arm['latest'].items(), key=lambda kv: arm['index'][kv[0]]):
            for a in row.get('agents') or []:
                if not a.get('plan') or a.get('verdict') not in (True, False):
                    continue
                if a['verdict'] is False and not include_rejected_forced:
                    continue
                end = trace_end(Path(seg) / 'agents' / f"{task_id}-s{seed}-{policy}-a{a['slot']}.jsonl")
                if a['verdict'] is False and not end.get('budget_forced'):
                    continue
                task = tasks[task_id]
                out.append(dict(part='arith', run=run_dir.name, policy=policy, task_id=task_id, seed=seed, slot=a['slot'],
                                case_index=arm['index'][(task_id, seed)], numbers=task['numbers'], target=task['target'],
                                plan=a['plan'], forced=bool(end.get('budget_forced')), truth=bool(a.get('verifier_solved')),
                                first_verdict=a['verdict'],
                                recorded_judge_tokens=a.get('judge_tokens') or 0,
                                judge_seed=stable_seed(SECOND_JUDGE_SALT, run_dir.name, policy, task_id, seed, a['slot'])))
    return out


def arith_selection(candidates, control_seed=CONTROL_SEED):
    """All forced accepted plans ('forced') + an equal-size seeded random sample of self-closed accepted plans
    ('control') + every forced plan the first judge rejected, if present ('forced_rejected')."""
    accepted = [c for c in candidates if c.get('first_verdict', True) is True]
    forced = [dict(c, group='forced') for c in accepted if c['forced']]
    closed = [c for c in accepted if not c['forced']]
    control = random.Random(stable_seed(control_seed)).sample(closed, min(len(forced), len(closed)))
    rejected = [dict(c, group='forced_rejected') for c in candidates if c.get('first_verdict') is False]
    return forced + [dict(c, group='control') for c in control] + rejected


# ---------------------------------------------------------------- run discovery
def coding_runs(runs_dir):
    """Finished coding arms: coding-roll*-v1*, coding-stagger-v1*, coding-earlystop-v1* with cases.json (arms that ran
    every agent to the end record no winner and are listed as skipped); smoke runs excluded."""
    keep, skipped = [], []
    for d in sorted(Path(runs_dir).iterdir()):
        name = d.name
        if not d.is_dir() or 'smoke' in name or not any(name.startswith(p) for p in ('coding-roll', 'coding-stagger-v1',
                                                                                     'coding-earlystop-v1')):
            continue
        if not name.startswith(('coding-roll-v1', 'coding-roll2-v1', 'coding-roll3-v1', 'coding-stagger-v1',
                                'coding-earlystop-v1')):
            continue
        (keep if (d / 'cases.json').exists() else skipped).append(d)
    return keep, [f'{d.name}: no cases.json (no recorded winner)' for d in skipped]


def arith_runs(runs_dir):
    """Finished Inkling arithmetic arms (run_variants protocol, Inkling serving, arm_accounting.json present, not a smoke
    run, not a resume segment); the frozen resume rule merges segments."""
    keep = []
    for d in sorted(Path(runs_dir).iterdir()):
        meta_path = d / 'metadata.json'
        if not d.is_dir() or 'smoke' in d.name or '-resume' in d.name or not meta_path.exists():
            continue
        try:
            plan = read(meta_path).get('protocol')
        except ValueError:
            continue
        if not isinstance(plan, dict) or plan.get('protocol') != 'swarm-variants-screen-v1':
            continue
        serving = plan.get('serving')
        if 'Inkling' not in (serving.get('model', '') if isinstance(serving, dict) else str(serving)):
            continue
        if (d / 'arm_accounting.json').exists():
            keep.append(d)
    return keep
