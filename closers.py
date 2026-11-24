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
import unicodedata
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
# Strict grammar: an expression is ASCII digits, + - * / (after mapping x × · ÷ − and \times/\cdot/\div), parentheses and
# at most single spaces between tokens, then '=' and one ASCII integer. Every character of that span is consumed by the
# grammar; anything else that touches it (a sign, decimal point, digit group, power, unicode digit, ...) drops the
# statement. Lines with powers, exponents, %, !, roots, digit groups or non-ASCII digits are never read.
_SYMBOLS = str.maketrans({'×': '*', '·': '*', '∗': '*', '⋅': '*', '÷': '/', '−': '-', '–': '-', '—': '-'})
_LATEX = (('\\times', '*'), ('\\cdot', '*'), ('\\div', '/'))
_LETTER_X = re.compile(r'(?<=[0-9]) ?[xX] ?(?=[0-9])', re.ASCII)  # 55 x 15 -> 55*15 (only between two digits)
# value: one ASCII integer that is the whole right-hand side: not a decimal, fraction, digit group, exponent, power,
# percent or factorial, not glued to a letter or non-ASCII character, not the start of a longer expression
_RHS = re.compile(r'(?<![<>!=])=(?!=) ?([0-9]+)'
                  r'(?![0-9A-Za-z_]|[^\x00-\x7f]|[.,][0-9]|[ \t]*[-+*/][ \t]*[0-9(]|[ \t]*[\^%!]|[ \t]+[0-9]'
                  r'|[ \t]?[(\-+*/]|[ \t]?[xX](?![A-Za-z_])|[ \t]{2,}(?=\S)|\t|[ \t]?[,.][ \t]?[0-9])', re.ASCII)
_UNPARSED_LINE = re.compile(r'\^|\*\*|[0-9][eE][+-]?[0-9]|\\(?:frac|sqrt|pow)|√|%|!(?!=)'
                            r'|[0-9][     -  ][0-9]')
_LHS = re.compile(r'[0-9()+\-*/ \t]*$', re.ASCII)
_TOKEN = re.compile(r'[0-9]+|[()+\-*/]', re.ASCII)
_LIST_MARKER = re.compile(r'[ \t]*[0-9]{1,2}[).] (?=[0-9(])', re.ASCII)  # '1) ' / '3. ' at the start of a line


def normalize(text):
    """Map the operator spellings seen in thinking text ('×', '·', '÷', '−', '\\times', '55 x 15') to ASCII."""
    for old, new in _LATEX:
        text = text.replace(old, new)
    return _LETTER_X.sub('*', text.translate(_SYMBOLS))


def _unparsed_line(line):
    if _UNPARSED_LINE.search(line):
        return True
    return any(not c.isascii() and (c.isspace() or c.isdigit() or c.isnumeric()
                                    or unicodedata.category(c) in ('Nd', 'Nl', 'No', 'Zs', 'Cf'))
               for c in line)


def _kind(tok):
    return 'num' if tok.isdigit() else tok if tok in '()' else 'op'


_BAD_PAIRS = {('num', 'num'), ('num', '('), ('op', 'op'), ('op', ')'), ('(', 'op'), ('(', ')'), (')', 'num'), (')', '(')}
_SAFE_PREV = set(' \t=:;"\'[{`$>')  # characters that may touch the expression's first character
# the nearest non-space character before a space-separated expression: a word, punctuation, an arrow
_SAFE_SPACED = set('=:;"\'[{`$>.,?→⇒')


def _expression(left, line_start=True):
    """The expression that ends just left of '=' (tokens only, never evaluated), or None. The whole span from its
    first character to '=' must be consumed by the grammar; the expression is never shortened."""
    m = _LHS.search(left)
    seg = m.group()
    span = seg.lstrip(' \t')
    start = len(left) - len(span)  # first character of the expression in `left`
    core = span.rstrip(' \t')
    if span[len(core):] not in ('', ' ') or '\t' in core or '  ' in core:
        return None  # at most single spaces
    tokens = _TOKEN.findall(core)
    if not tokens or ''.join(tokens) != core.replace(' ', ''):
        return None
    if any(len(t) > 1 and t[0] == '0' for t in tokens):
        return None  # leading zero: not a plain integer
    for i in range(1, len(tokens)):  # no cuts: two numbers side by side may be one digit-grouped number
        if (_kind(tokens[i - 1]), _kind(tokens[i])) in _BAD_PAIRS:
            return None
    before = left[:start]
    if before:
        gap = before[len(before.rstrip(' \t')):]
        prev = before.rstrip(' \t')
        if (prev or not line_start) and gap not in ('', ' '):
            return None  # 2+ spaces (or a tab) next to the expression; only indentation at a line start is allowed
        if start == m.start():  # glued
            if left[start - 1] not in _SAFE_PREV:
                return None
        else:
            if prev and not (prev[-1].isalpha() or prev[-1] in _SAFE_SPACED) or prev[-1:] in ('x', 'X'):
                return None  # left neighbour is a digit, operator or 'x' (multiplication) one space away
            if prev[-1:] in ('.', ',') and prev[:-1].rstrip(' ')[-1:].isdigit() and len(prev[:-1]) - len(prev[:-1].rstrip(' ')) <= 1:
                return None  # '1, 250*4' / '1 , 250*4' / '2. 5*4': possibly one number
    if _kind(tokens[0]) not in ('num', '('):
        return None  # a leading sign or operator belongs to the statement; never strip it
    while tokens[0] == '(' and tokens.count('(') > tokens.count(')'):  # opening paren of an outer group
        tokens = tokens[1:]
        if not tokens:
            return None
    if _kind(tokens[0]) not in ('num', '(') or _kind(tokens[-1]) not in ('num', ')') or 'op' not in map(_kind, tokens):
        return None
    depth = 0
    for tok in tokens:
        depth += (tok == '(') - (tok == ')')
        if depth < 0:
            return None
    if depth:
        return None
    return ' '.join(tokens).replace('( ', '(').replace(' )', ')')


def line_statements(raw):
    """Statements `expr = v` DETECTED in one source line (expr with at least one of + - * /, v a positive integer), in
    order: dicts with expr (canonical, for matching only), value, tokens and, for one operation, a/op/b. Nothing is
    evaluated or checked; the canonical form is never shown to a model (closers quote the verbatim source line)."""
    line = normalize(raw)
    if _unparsed_line(line):
        return []
    out = []
    for m in _RHS.finditer(line):
        left = line[:m.start()]
        at_start = '=' not in left
        if not at_start:
            left = left.rsplit('=', 1)[-1]
        else:
            marker = _LIST_MARKER.match(left)
            if marker:
                left = left[marker.end():]
        expr = _expression(left, at_start)
        digits = m.group(1)
        if expr is None or digits[0] == '0':
            continue  # unparsed span, zero or a leading zero
        tokens = expr.replace('(', ' ( ').replace(')', ' ) ').split()
        rec = dict(expr=expr, value=int(digits), tokens=tokens)
        if len(tokens) == 3:
            rec.update(a=int(tokens[0]), op=tokens[1], b=int(tokens[2]))
        out.append(rec)
    return out


def statements(text):
    """(canonical 'expr = v', v) for every detected statement of every line of text, in order (tests, reports)."""
    return [(f"{st['expr']} = {st['value']}", st['value']) for raw in text.splitlines() for st in line_statements(raw)]


def leads(text, wanted, target, limit=MAX_LEAD_LINES):
    """Lead LINES of a thinking text: tier 1 if a detected statement's value is on the wanted list, else tier 2 if one
    equals the target. Lines are the verbatim source lines (only leading/trailing whitespace stripped), distinct, in
    order of first appearance; at most `limit` in total, tier 1 first. matches holds the parsed statements per line."""
    wanted = set(wanted)
    tier1, tier2, matches, seen = [], [], {}, set()
    for raw in text.splitlines():
        found = line_statements(raw)
        if not found:
            continue
        verbatim = raw.strip()
        hit1 = [f for f in found if f['value'] in wanted and f['value'] != target]
        hit2 = [f for f in found if f['value'] == target]
        if not (hit1 or hit2) or verbatim in seen:
            continue
        seen.add(verbatim)
        (tier1 if hit1 else tier2).append(verbatim)
        matches[verbatim] = dict(line=verbatim, tier=1 if hit1 else 2, parsed=hit1 or hit2)
    chosen = (tier1 + tier2)[:limit]
    return dict(tier1=tier1, tier2=tier2, lines=chosen, matches=[matches[line] for line in chosen],
                truncated=len(tier1) + len(tier2) - len(chosen))


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
    """One short call, thinking off (same pattern as run_judge fast mode). A transport loss is retried once after
    run_variants.JUDGE_RETRY_SECONDS with the same seed. Never raises: every attempt's charge and error are kept
    (attempts; tokens is their sum); a failed last attempt is returned as infra."""
    def once(path):
        try:
            events = run_variants.GuardedEvents(path, 'closer_wanted')
        except Exception as exc:
            return dict(lines=[], values=[], infra=1, error=f'{type(exc).__name__}: {exc}'[:300], tokens=0, raised=True,
                        retryable=False)
        client = None
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
        except Exception as exc:
            out = dict(lines=[], values=[], infra=(client.infra_failures if client else 0) + 1,
                       error=f'{type(exc).__name__}: {exc}'[:300],
                       tokens=client.budget.snapshot()['completion_tokens_charged'] if client else 0)
            events.emit('wanted_end', **out)
            events.close()
            return run_variants.with_trace_error(dict(out, raised=True, retryable=run_variants.raised_is_retryable(exc)),
                                                 events)
        out = dict(lines=lines, values=values, infra=client.infra_failures, error=first['error'],
                   tokens=client.budget.snapshot()['completion_tokens_charged'])
        events.emit('wanted_end', **out)
        events.close()
        return run_variants.with_trace_error(dict(out, raised=False, retryable=run_variants.transport_error(first['error'])),
                                             events)

    attempts = [once(events_path)]
    if attempts[0]['infra'] and attempts[0]['retryable']:
        time.sleep(run_variants.JUDGE_RETRY_SECONDS)
        attempts.append(once(Path(events_path).with_suffix('.retry.jsonl')))
    last = attempts[-1]
    out = dict(lines=last['lines'], values=last['values'], infra=last['infra'], error=last['error'],
               tokens=sum(a['tokens'] for a in attempts), retry=len(attempts) > 1,
               attempts=[{k: a[k] for k in ('tokens', 'infra', 'error', 'raised', 'retryable', 'trace_error') if k in a}
                         for a in attempts])
    if len(attempts) > 1:
        out['first_error'] = attempts[0]['error']
    if any(a.get('trace_error') for a in attempts):
        out['trace_error'] = next(a['trace_error'] for a in attempts if a.get('trace_error'))
    return out


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
    try:
        with slots(endpoint):
            wanted = wanted_fn(endpoint, out / 'wanted' / f"{task['id']}-s{seed}.jsonl",
                               WANTED_SEED_BASE + 1000 * seed + 10 * case_index, task['numbers'], task['target'])
    except Exception as exc:  # never lose the case: an infra record (resume reruns it)
        wanted = dict(lines=[], values=[], infra=1, error=f'{type(exc).__name__}: {exc}'[:300], tokens=0, retry=False)
    rows = agent_leads_fn(wanted['values'])
    # a failed wanted call makes the case infra: no closers (tier 1 would be empty); the resume reruns the case
    with_leads, skipped = select_closers(rows, 0 if wanted['infra'] else max_closers)
    race = run_variants.new_race(t0)

    def closer(r):
        slot, extra = CLOSER_SLOT_BASE + r['slot'], closer_extra(r['lines'])
        try:
            info = run_variants.run_agent(plan, source, out, task, seed, case_index, CLOSER_POLICY, slot, extra, slots,
                                          seed_offset, t0, race, endpoints=endpoints)
        except Exception as exc:  # an infra record for this closer (and so the case), with every charge kept
            info = run_variants.fault_record(slot, extra, exc)
        return dict(info, source_slot=r['slot'], tier1=len(r['tier1']), tier2=len(r['tier2']), lines=r['lines'],
                    matches=r.get('matches', []))
    closers = run_variants.parallel([lambda r=r: closer(r) for r in with_leads])
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
                # client-side completion tokens (workers + judges + wanted call); cancelled work is undercounted, so
                # server-side cost must come from the arm driver's counters (inkling/arms.py), never from this field
                client_tokens=wanted['tokens'] + sum(c['tokens'] + c['judge_tokens'] for c in closers),
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
