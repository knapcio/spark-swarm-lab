"""Generic artifact relay (astra review 2026-11-24, items 4-5): task-agnostic closers versus equal-budget replacements.

For a case the recorded swarm left unanswered:
  RELAY    select up to K distinct, nonempty failed-agent artifacts by SEEDED UNIFORM sampling (seed from the plan and
           the case; no ranking, no task knowledge) and start one worker per artifact on the original task with the
           extra text PROTOCOL + the artifact verbatim (the agent's recorded thinking and answer text in order, frozen
           truncation: the LAST max_chars characters).
  REPLACE  the control: the same number of fresh independent workers (no artifact) with the same budget and the same
           seeds structure (offset from the plan).
Both arms: unchanged judge (run_variants.judge_with_reason, with retry), the first accepted plan per case within the
arm wins and cancels the arm's other workers, the exact verifier only scores. Nothing here reads the task's content:
artifacts are opaque text, selection is a seeded shuffle of slot numbers.
"""
import hashlib
import json
import random
import time
from pathlib import Path

import closers  # generic helpers only: failed_agents, agent_events, EndpointSlots (no matching code is used)
import run_variants

PROTOCOL = ('Another solver worked on this exact task and did not reach an accepted answer. Its work is below. If it '
            'can be completed into a full answer that satisfies the task, give that answer; otherwise abstain using the '
            'answer format.')
ARMS = ('relay', 'replace')
DEFAULT_K, DEFAULT_MAX_CHARS = 4, 12000
SLOT_BASE = dict(relay=200, replace=300)  # worker slot = base + position; stems, seeds and judge seeds stay distinct
DEFAULT_SEED_OFFSETS = dict(relay=19000, replace=19500)


def settings(plan):
    """Frozen relay parameters from the plan (defaults when absent)."""
    r = plan.get('relay') or {}
    return dict(k=int(r.get('k', DEFAULT_K)), max_chars=int(r.get('max_chars', DEFAULT_MAX_CHARS)),
                selection_seed=str(r.get('selection_seed', 'relay-v1')), variant=r.get('variant'),
                seed_offsets={arm: (plan.get('seed_offsets') or {}).get(arm, DEFAULT_SEED_OFFSETS[arm]) for arm in ARMS})


def artifact(events_path):
    """The agent's recorded work: thinking ('reasoning') then answer ('response') of every request_end, in order."""
    parts = []
    for line in Path(events_path).read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'request_end':
            for key in ('reasoning', 'response'):
                if event.get(key):
                    parts.append(event[key])
    return '\n'.join(parts)


def truncate(text, max_chars):
    """Frozen policy: keep the LAST max_chars characters."""
    return text[-max_chars:] if len(text) > max_chars else text


def candidates(seg, case_row):
    """Failed agents with a recorded, nonempty artifact; duplicates (identical text) kept once (lowest slot)."""
    out, seen = [], set()
    for a in sorted(closers.failed_agents(case_row), key=lambda a: a['slot']):
        path = closers.agent_events(seg, case_row, a['slot'])
        if not path.exists():
            continue
        text = artifact(path)
        if not text.strip() or text in seen:
            continue
        seen.add(text)
        out.append(dict(slot=a['slot'], text=text))
    return out


def selection_rng(selection_seed, task_id, seed):
    material = f'{selection_seed}:{task_id}:{seed}'.encode()
    return random.Random(int.from_bytes(hashlib.sha256(material).digest()[:8], 'big'))


def select(cands, k, rng):
    """Seeded uniform sample of up to k candidates (order = sampling order); no ranking."""
    return rng.sample(cands, min(k, len(cands)))


def relay_extra(text, max_chars):
    return PROTOCOL + '\n\n' + truncate(text, max_chars)


def case_plan(seg, case_row, task, seed, s):
    """What a case gets in both arms: the selected artifacts (RELAY) and as many replacement workers (REPLACE)."""
    cands = candidates(seg, case_row)
    chosen = select(cands, s['k'], selection_rng(s['selection_seed'], task['id'], seed))
    return dict(failed_agents=len(closers.failed_agents(case_row)), candidates=len(cands),
                selected=[dict(source_slot=c['slot'], chars=len(c['text']), chars_used=len(truncate(c['text'], s['max_chars'])),
                               text=c['text']) for c in chosen])


def run_arm(arm, plan, source, out, task, seed, case_index, cp, slots, endpoints, s):
    """One arm on one case: len(cp['selected']) workers (RELAY with artifacts, REPLACE without), first accept wins."""
    t0 = time.monotonic()
    race = run_variants.new_race(t0)
    offset = s['seed_offsets'][arm]

    def worker(i, sel):
        slot = SLOT_BASE[arm] + i
        extra = relay_extra(sel['text'], s['max_chars']) if arm == 'relay' else ''
        info = run_variants.run_agent_safe(plan, source, out, task, seed, case_index, arm, slot, extra, slots, offset,
                                           t0, race, endpoints=endpoints)
        return dict(info, position=i, source_slot=sel['source_slot'] if arm == 'relay' else None,
                    artifact_chars_used=sel['chars_used'] if arm == 'relay' else 0)
    workers = run_variants.parallel([lambda i=i, sel=sel: worker(i, sel) for i, sel in enumerate(cp['selected'])])
    selected = next((w for w in workers if w['slot'] == race['winner']), None)
    return dict(arm=arm, task_id=task['id'], seed=seed, case_index=case_index, failed_agents=cp['failed_agents'],
                candidates=cp['candidates'], workers=workers, selected_slot=race['winner'], answer_seconds=race['answer_s'],
                rescued=bool(selected and selected['verifier_solved']), wrong=bool(selected and not selected['verifier_solved']),
                answered=selected is not None, oracle=any(w['verifier_solved'] for w in workers),
                faults=sum(w['infra'] + w['judge_infra'] for w in workers),
                client_tokens=sum(w['tokens'] + w['judge_tokens'] for w in workers),
                artifact_chars_used=sum(w['artifact_chars_used'] for w in workers),
                cancelled_workers=sum(w.get('cancelled', False) for w in workers),
                unstarted_workers=sum(not w.get('started', True) for w in workers),
                case_seconds=round(time.monotonic() - t0, 3))
