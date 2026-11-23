"""Lead relay (round-3 idea 1, IDEAS-swarm-round3-fable.md): closers for near-miss sightings.

For a case that the swarm left unanswered:
  (a) one short Inkling call writes the wanted list: for each given number x the lines T+x, T-x, T*x, T/x with values
      (the MODEL writes them; the controller only parses its lines),
  (b) the recorded thinking text of each failed agent is scanned for statements `a op b = v` whose v is on the wanted
      list (tier 1) or equals the target (tier 2): regex extraction and string/integer equality only, nothing is
      evaluated,
  (c) the top max_closers failed agents with such a line (ranked by tier-1, tier-2 line counts) get one closer each: the unchanged worker with a small budget
      (forced_original, 7,168 / 8,192) on the original task, the lines appended as extra text,
  (d) each closer plan goes to the unchanged judge (run_variants.judge_with_reason); the first accepted plan (in time)
      answers the case and cancels the other closers. The exact verifier only scores afterwards.
"""
import json
import re
import threading
import time
from pathlib import Path

import run_judge
import run_variants

CLOSER_VARIANT = 'forced_original'
CLOSER_POLICY = 'closer'
CLOSER_SLOT_BASE = 100  # closer slot = 100 + slot of the failed agent it reads (distinct stems, seeds and judge seeds)
CLOSER_SEED_OFFSET = 18000  # agent seed 1000*seed + offset + closer slot (same formula as every arm)
WANTED_SEED_BASE = 70000
WANTED_MAX_TOKENS = 1024
MAX_CLOSERS_PER_CASE = 4  # closers started per case (top-ranked failed agents with leads); the rest are recorded as skipped
MAX_LEAD_LINES = 24  # lines handed to one closer (tier 1 first, then tier 2, each in order of first appearance)
CLOSER_TAIL = ('Check whether one of them can be completed to the target with the unused numbers; if so give the full '
               'plan, otherwise answer with no moves.')
WANTED_SYSTEM = 'Do the requested arithmetic exactly. Write only the requested lines.'

# ---------------------------------------------------------------- statement extraction (string operations only)
_OPS = '+-*/'
_SYMBOLS = str.maketrans({'×': '*', '·': '*', '∗': '*', '⋅': '*', '÷': '/', '−': '-', '–': '-', '—': '-'})
_LATEX = (('\\times', '*'), ('\\cdot', '*'), ('\\div', '/'))
_LETTER_X = re.compile(r'(?<=\d)[ \t]*[xX][ \t]*(?=\d)')  # 55 x 15 -> 55*15 (only between two digits)
# value: an integer (optionally with thousands commas) that is the whole right-hand side: not a decimal, not a
# fraction (412.5, 825/2, 412 1/2), not the start of a longer expression, not part of a comparison operator
_RHS = re.compile(r'(?<![<>!=])=(?!=)[ \t]*(\d{1,3}(?:,\d{3})+|\d+)(?!\d|[.,]\d|[ \t]*[-+*/][ \t]*[\d(]|[ \t]+\d+[ \t]*/[ \t]*\d)')
_LHS = re.compile(r'[0-9()+\-*/ \t]*$')
_TOKEN = re.compile(r'\d+|[()+\-*/]')


def normalize(text):
    """Map the operator spellings seen in thinking text ('×', '·', '÷', '−', '\\times', '55 x 15') to ASCII."""
    for old, new in _LATEX:
        text = text.replace(old, new)
    return _LETTER_X.sub('*', text.translate(_SYMBOLS))


def _kind(tok):
    return 'num' if tok.isdigit() else tok if tok in '()' else 'op'


_BAD_PAIRS = {('num', 'num'), ('num', '('), ('op', 'op'), ('op', ')'), ('(', 'op'), ('(', ')'), (')', 'num'), (')', '(')}


def _expression(left):
    """Longest well-formed arithmetic suffix of the text left of '=' (tokens only, never evaluated), or None."""
    m = _LHS.search(left)
    tokens = _TOKEN.findall(m.group()) if m else []
    if '**' in (m.group() if m else ''):
        return None  # power, not one of the four operations
    start = 0
    for i in range(1, len(tokens)):  # cut at the last adjacency that cannot occur inside one expression
        if (_kind(tokens[i - 1]), _kind(tokens[i])) in _BAD_PAIRS:
            start = i
    tokens = tokens[start:]
    while tokens and _kind(tokens[0]) not in ('num', '('):  # leading operator or stray ')'
        tokens = tokens[1:]
    while tokens and tokens[0] == '(' and tokens.count('(') > tokens.count(')'):  # opening paren of an outer group
        tokens = tokens[1:]
    if not tokens or _kind(tokens[-1]) not in ('num', ')') or 'op' not in map(_kind, tokens):
        return None
    depth = 0
    for tok in tokens:
        depth += (tok == '(') - (tok == ')')
        if depth < 0:
            return None
    if depth:
        return None
    return ' '.join(tokens).replace('( ', '(').replace(' )', ')')


def statements(text):
    """Every statement `expr = v` (expr with at least one of + - * /, v a positive integer) in order of appearance.
    Returns (line, v) with line canonicalised as 'a op b = v'; nothing is evaluated or checked."""
    text = normalize(text)
    out = []
    for m in _RHS.finditer(text):
        expr = _expression(text[:m.start()].rsplit('\n', 1)[-1].rsplit('=', 1)[-1])
        if expr is None:
            continue
        value = int(m.group(1).replace(',', ''))
        if value > 0:
            out.append((f'{expr} = {value}', value))
    return out


def leads(text, wanted, target, limit=MAX_LEAD_LINES):
    """Tier 1: statements whose value is on the wanted list; tier 2: statements whose value is the target.
    Distinct lines in order of first appearance; at most `limit` lines in total, tier 1 first."""
    wanted = set(wanted)
    tier1, tier2, seen = [], [], set()
    for line, value in statements(text):
        if line in seen:
            continue
        if value in wanted and value != target:
            tier1.append(line)
        elif value == target:
            tier2.append(line)
        else:
            continue
        seen.add(line)
    chosen = (tier1 + tier2)[:limit]
    return dict(tier1=tier1, tier2=tier2, lines=chosen, truncated=len(tier1) + len(tier2) - len(chosen))


def closer_extra(lines):
    return 'Another solver computed these lines:\n' + '\n'.join(lines) + '\n' + CLOSER_TAIL


# ---------------------------------------------------------------- wanted list (written by the model)
def wanted_prompt(numbers, target):
    nums = ', '.join(map(str, numbers))
    return (f'Target {target}. Given numbers: {nums}.\nFor each given number x, write these four lines with the exact '
            f'value: "{target}+x = value", "{target}-x = value", "{target}*x = value" and "{target}/x = value". Write '
            f'the division line only if the result is a whole number; otherwise write "{target}/x = none". Use the '
            'number itself in place of x. Write only these lines, one per line, nothing else.\n'
            'Example of the format for target 100 and x = 3:\n100+3 = 103\n100-3 = 97\n100*3 = 300\n100/3 = none')


_WANTED_LINE = re.compile(r'^[\s\-*•]*(\d+)\s*([-+*/])\s*(\d+)\s*=\s*(\d{1,3}(?:,\d{3})+|\d+)\s*\.?\s*$')


def parse_wanted(text, numbers, target):
    """Lines 'T op x = v' (x a given number; 'x op T' accepted for + and *) -> (lines, values). The model's values are
    taken as written (string parsing only); 'none' lines and anything else are ignored."""
    given, lines, values = {str(n) for n in numbers}, [], []
    for raw in normalize(text or '').splitlines():
        m = _WANTED_LINE.match(raw)
        if not m:
            continue
        a, op, b, v = m.group(1), m.group(2), m.group(3), int(m.group(4).replace(',', ''))
        if (a == str(target) and b in given) or (op in '+*' and b == str(target) and a in given):
            line = f'{a}{op}{b} = {v}'
            if line not in lines and v > 0:
                lines.append(line)
                if v not in values:
                    values.append(v)
    return lines, values


def reference_wanted_values(numbers, target):
    """Plan-only REPORT helper: the exact wanted values, used only to estimate tier-1 lead counts without a model call.
    Never used by a run (there the model writes the list)."""
    out = set()
    for x in numbers:
        out.update({target + x, target * x})
        if target - x > 0:
            out.add(target - x)
        if target % x == 0:
            out.add(target // x)
    return out


def ask_wanted(endpoint, events_path, seed, numbers, target):
    """One short call, thinking off (same pattern as run_judge fast mode). A transport failure is retried once after
    run_variants.JUDGE_RETRY_SECONDS with the same seed; a second failure is returned as infra."""
    def once(path):
        events = run_judge.Events(path, 'closer_wanted')
        try:
            forced72 = run_judge._forced72()
            client = forced72.ForcedClient(endpoint, 'nemotron-lightning', run_judge.Budget(1, WANTED_MAX_TOKENS),
                                           events, seed)
            messages = [{'role': 'system', 'content': WANTED_SYSTEM},
                        {'role': 'user', 'content': wanted_prompt(numbers, target)}]
            with client.post('/tokenize', dict(model=client.model, messages=messages, add_generation_prompt=True,
                                               chat_template_kwargs={'enable_thinking': False}), 60) as response:
                ids = json.load(response)['tokens']
            first = client.complete(0, 'wanted', ids, WANTED_MAX_TOKENS, thinking_closed=True)
            lines, values = parse_wanted(first['text'], numbers, target)
            out = dict(lines=lines, values=values, infra=client.infra_failures, error=first['error'],
                       tokens=client.budget.snapshot()['completion_tokens_charged'])
            events.emit('wanted_end', **out)
            return out
        finally:
            events.close()

    def guarded(path):
        try:
            return once(path)
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'[:300]
            if not run_variants.transport_error(error):
                raise
            return dict(lines=[], values=[], infra=1, error=error, tokens=0)

    first = guarded(events_path)
    if not (first['infra'] and run_variants.transport_error(first['error'])):
        return dict(first, retry=False)
    time.sleep(run_variants.JUDGE_RETRY_SECONDS)
    second = guarded(Path(events_path).with_suffix('.retry.jsonl'))
    return dict(second, tokens=first['tokens'] + second['tokens'], retry=True, first_error=first['error'])


# ---------------------------------------------------------------- recorded runs
def agent_thinking(events_path):
    """The thinking text an agent recorded: 'reasoning' of every request_end event, in order."""
    parts = []
    for line in Path(events_path).read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'request_end' and event.get('reasoning'):
            parts.append(event['reasoning'])
    return '\n'.join(parts)


def failed_agents(case):
    """Agents of an unanswered case that ran and were not accepted (no verdict True)."""
    return [a for a in case['agents'] if a.get('started', True) and not a.get('cancelled') and a.get('verdict') is not True]


def agent_events(run_dir, case, slot):
    return Path(run_dir) / 'agents' / f"{case['task_id']}-s{case['seed']}-{case['policy']}-a{slot}.jsonl"


def case_leads(run_dir, case, wanted, target, limit=MAX_LEAD_LINES):
    """Per failed agent: its lead lines (tier 1 / tier 2). Agents without a recorded trace are listed with missing=True."""
    out = []
    for a in failed_agents(case):
        path = agent_events(run_dir, case, a['slot'])
        if not path.exists():
            out.append(dict(slot=a['slot'], missing=True, tier1=[], tier2=[], lines=[], truncated=0))
            continue
        out.append(dict(slot=a['slot'], missing=False, **leads(agent_thinking(path), wanted, target, limit)))
    return out


# ---------------------------------------------------------------- one case
def select_closers(rows, max_closers=MAX_CLOSERS_PER_CASE):
    """Failed agents with at least one lead, ranked by (tier-1 lines desc, tier-2 lines desc, slot asc): the top
    max_closers get a closer, the rest are skipped. Counting and sorting only. Returns (chosen rows, skipped slots)."""
    ranked = sorted((r for r in rows if r['lines']), key=lambda r: (-len(r['tier1']), -len(r['tier2']), r['slot']))
    return ranked[:max_closers], [r['slot'] for r in ranked[max_closers:]]


def run_case(plan, source, out, task, seed, case_index, agent_leads_fn, slots, endpoints, seed_offset=CLOSER_SEED_OFFSET,
             wanted_fn=ask_wanted, max_closers=MAX_CLOSERS_PER_CASE):
    """(a) wanted list -> (b) leads per failed agent (agent_leads_fn(wanted_values) -> case_leads rows) -> (c) one
    closer for each of the top max_closers agents with a lead (select_closers) -> (d) judge; first accepted in time
    wins and cancels the rest."""
    t0 = time.monotonic()
    endpoint = endpoints[case_index % len(endpoints)]
    with slots(endpoint):
        wanted = wanted_fn(endpoint, out / 'wanted' / f"{task['id']}-s{seed}.jsonl",
                           WANTED_SEED_BASE + 1000 * seed + 10 * case_index, task['numbers'], task['target'])
    rows = agent_leads_fn(wanted['values'])
    with_leads, skipped = select_closers(rows, max_closers)
    race = run_variants.new_race(t0)
    closers = run_variants.parallel([
        lambda r=r: dict(run_variants.run_agent(plan, source, out, task, seed, case_index, CLOSER_POLICY,
                                                CLOSER_SLOT_BASE + r['slot'], closer_extra(r['lines']), slots,
                                                seed_offset, t0, race, endpoints=endpoints),
                         source_slot=r['slot'], tier1=len(r['tier1']), tier2=len(r['tier2']), lines=r['lines'])
        for r in with_leads])
    selected = next((c for c in closers if c['slot'] == race['winner']), None)
    return dict(task_id=task['id'], seed=seed, case_index=case_index, numbers=task['numbers'], target=task['target'],
                wanted=wanted, failed_agents=len(rows), missing_traces=sum(r['missing'] for r in rows),
                agents_tier1=sum(bool(r['tier1']) for r in rows), agents_tier2=sum(bool(r['tier2']) for r in rows),
                lead_rows=[{k: r[k] for k in ('slot', 'tier1', 'tier2', 'truncated', 'missing')} for r in rows],
                closers=closers, calls=len(closers) + 1, max_closers=max_closers, skipped_closers=len(skipped),
                skipped_slots=skipped, rescue=selected is not None,
                selected_slot=race['winner'], answer_seconds=race['answer_s'],
                solved=bool(selected and selected['verifier_solved']), wrong=bool(selected and not selected['verifier_solved']),
                oracle=any(c['verifier_solved'] for c in closers),
                tokens=wanted['tokens'] + sum(c['tokens'] + c['judge_tokens'] for c in closers),
                infra=wanted['infra'] + sum(c['infra'] + c['judge_infra'] for c in closers),
                cancelled_closers=sum(c.get('cancelled', False) for c in closers),
                unstarted_closers=sum(not c.get('started', True) for c in closers),
                case_seconds=round(time.monotonic() - t0, 3))


class EndpointSlots:
    """run_arbiterfree.Slots for an explicit endpoint list (agents, judges and wanted calls share it)."""
    def __init__(self, endpoints, per_endpoint):
        self.sem = {e: threading.BoundedSemaphore(per_endpoint) for e in endpoints}

    def __call__(self, endpoint):
        return self.sem[endpoint]
