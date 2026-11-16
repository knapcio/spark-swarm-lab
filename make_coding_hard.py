#!/usr/bin/env python3
"""Harder original coding corpus coding-hard-v1: 8 development + 24 evaluation tasks.

Offline only: no model/API/SSH/Docker execution. Same public/private JSON schema
and protocol string as coding-v1 so coding_harness.py can consume it unchanged.
Every reference below is self-contained (imports inside the function) so its
trusted_reference_source executes on its own. A second, independently written
reference set lives in coding_hard_second_refs.py; build() requires both sets
to agree on every public example, feedback case and holdout case.
"""
import argparse
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import random

PROTOCOL = "original-python-functions-v1"
CORPUS = "coding-hard-v1"
DEFAULT_SEED = 20261116
HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "datasets" / CORPUS
MIN_CASES_PER_PHASE = 10
TARGET_CASES = 32


# ----------------------------------------------------------------------------
# Trusted reference implementations (reference A)
# ----------------------------------------------------------------------------

def repeating_expansion(num, den, base):
    if den == 0 or not 2 <= base <= 36:
        return None
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    negative = num != 0 and (num < 0) != (den < 0)
    num, den = abs(num), abs(den)
    whole, rem = divmod(num, den)
    head = []
    while whole:
        whole, d = divmod(whole, base)
        head.append(digits[d])
    sign = "-" if negative else ""
    head = "".join(reversed(head)) or "0"
    if rem == 0:
        return sign + head
    seen, frac = {}, []
    while rem and rem not in seen:
        seen[rem] = len(frac)
        rem *= base
        frac.append(digits[rem // den])
        rem %= den
    if not rem:
        return sign + head + "." + "".join(frac)
    cut = seen[rem]
    return sign + head + "." + "".join(frac[:cut]) + "(" + "".join(frac[cut:]) + ")"


def wrap_hyphen(text, width):
    if width < 1:
        return None
    words = [w for w in text.split(" ") if w]
    lines, cur = [], ""
    while words:
        word = words.pop(0)
        sep = 1 if cur else 0
        if len(cur) + sep + len(word) <= width:
            cur = cur + " " + word if cur else word
            continue
        room = width - len(cur) - sep
        cut = -1
        for i in range(len(word) - 1):
            if word[i] == "-" and i + 1 <= room:
                cut = i
        if cut >= 0:
            lines.append(cur + " " * sep + word[:cut + 1])
            cur = ""
            words.insert(0, word[cut + 1:])
        elif cur:
            lines.append(cur)
            cur = ""
            words.insert(0, word)
        else:
            lines.append(word[:width])
            words.insert(0, word[width:])
    if cur:
        lines.append(cur)
    return lines


def semver_sort(versions):
    import re
    ident = r"[0-9A-Za-z-]+"
    number = r"0|[1-9][0-9]*"
    pattern = re.compile(rf"({number})\.({number})\.({number})"
                         rf"(?:-({ident}(?:\.{ident})*))?(?:\+({ident}(?:\.{ident})*))?")
    keyed = []
    for index, version in enumerate(versions):
        match = pattern.fullmatch(version)
        if not match:
            continue
        pre = match.group(4)
        if pre is None:
            pre_key = (1,)
        else:
            parts = pre.split(".")
            if any(re.fullmatch("[0-9]+", p) and len(p) > 1 and p[0] == "0" for p in parts):
                continue
            pre_key = (0, tuple((0, int(p), "") if re.fullmatch("[0-9]+", p) else (1, 0, p) for p in parts))
        keyed.append(((int(match.group(1)), int(match.group(2)), int(match.group(3)), pre_key), index, version))
    keyed.sort()
    return [version for _, _, version in keyed]


def stack_vm(program, max_steps):
    import re
    stack, output, calls = [], [], []
    pc, steps, size = 0, 0, len(program)
    with_operand = {"PUSH", "JMP", "JZ", "JNZ", "CALL"}
    plain = {"POP", "DUP", "SWAP", "OVER", "ADD", "SUB", "MUL", "DIV", "MOD", "PRINT", "RET", "HALT"}
    needs = {"POP": 1, "DUP": 1, "SWAP": 2, "OVER": 2, "ADD": 2, "SUB": 2, "MUL": 2,
             "DIV": 2, "MOD": 2, "PRINT": 1, "JZ": 1, "JNZ": 1}

    def done(status):
        return {"status": status, "output": output, "stack": stack, "steps": steps}

    while True:
        if pc == size:
            return done("ok")
        if steps >= max_steps:
            return done("step_limit")
        steps += 1
        parts = program[pc].split(" ")
        op, arg = parts[0], None
        if op in with_operand:
            if len(parts) != 2 or not re.fullmatch(r"-?[0-9]+", parts[1]):
                return done("bad_instruction")
            arg = int(parts[1])
        elif op not in plain or len(parts) != 1:
            return done("bad_instruction")
        if len(stack) < needs.get(op, 0):
            return done("underflow")
        nxt = pc + 1
        if op == "PUSH":
            stack.append(arg)
        elif op == "POP":
            stack.pop()
        elif op == "DUP":
            stack.append(stack[-1])
        elif op == "SWAP":
            stack[-1], stack[-2] = stack[-2], stack[-1]
        elif op == "OVER":
            stack.append(stack[-2])
        elif op in ("ADD", "SUB", "MUL", "DIV", "MOD"):
            a, b = stack[-2], stack[-1]
            if op in ("DIV", "MOD") and b == 0:
                return done("div_zero")
            if op == "ADD":
                value = a + b
            elif op == "SUB":
                value = a - b
            elif op == "MUL":
                value = a * b
            else:
                quotient = abs(a) // abs(b)
                if (a < 0) != (b < 0):
                    quotient = -quotient
                value = quotient if op == "DIV" else a - b * quotient
            del stack[-2:]
            stack.append(value)
        elif op == "PRINT":
            output.append(stack.pop())
        elif op in ("JMP", "CALL"):
            if not 0 <= arg <= size:
                return done("bad_jump")
            if op == "CALL":
                calls.append(pc + 1)
            nxt = arg
        elif op in ("JZ", "JNZ"):
            taken = (stack[-1] == 0) == (op == "JZ")
            if taken and not 0 <= arg <= size:
                return done("bad_jump")
            stack.pop()
            if taken:
                nxt = arg
        elif op == "RET":
            if not calls:
                return done("ret_empty")
            nxt = calls.pop()
        elif op == "HALT":
            return done("ok")
        pc = nxt


def cidr_merge(blocks):
    import re
    octet = r"(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])"
    pattern = re.compile(rf"{octet}\.{octet}\.{octet}\.{octet}/(3[0-2]|[12][0-9]|[0-9])")
    ranges = []
    for block in blocks:
        match = pattern.fullmatch(block)
        if not match:
            continue
        address = 0
        for part in match.groups()[:4]:
            address = address * 256 + int(part)
        size = 1 << (32 - int(match.group(5)))
        start = address - address % size
        ranges.append((start, start + size))
    ranges.sort()
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out = []
    for start, end in merged:
        while start < end:
            size = start & -start if start else 1 << 32
            while size > end - start:
                size >>= 1
            text = ".".join(str((start >> shift) & 255) for shift in (24, 16, 8, 0))
            out.append(text + "/" + str(33 - size.bit_length()))
            start += size
    return out


def nth_distinct_permutation(s, n):
    from collections import Counter
    from math import factorial
    counts = Counter(s)

    def total():
        value = factorial(sum(counts.values()))
        for c in counts.values():
            value //= factorial(c)
        return value

    if n < 0 or n >= total():
        return None
    out = []
    for _ in range(len(s)):
        for ch in sorted(k for k, v in counts.items() if v):
            counts[ch] -= 1
            block = total()
            if n < block:
                out.append(ch)
                break
            n -= block
            counts[ch] += 1
    return "".join(out)


def glob_match(pattern, text):
    tokens, i, size = [], 0, len(pattern)

    def read_char(j):
        if pattern[j] == "\\":
            if j + 1 >= size:
                return None, j
            return pattern[j + 1], j + 2
        return pattern[j], j + 1

    while i < size:
        c = pattern[i]
        if c == "\\":
            if i + 1 >= size:
                return None
            tokens.append(("lit", pattern[i + 1]))
            i += 2
        elif c == "?":
            tokens.append(("any",))
            i += 1
        elif c == "*":
            tokens.append(("star",))
            i += 1
        elif c == "[":
            j, negate, items, first = i + 1, False, [], True
            if j < size and pattern[j] == "!":
                negate, j = True, j + 1
            while True:
                if j >= size:
                    return None
                if pattern[j] == "]" and not first:
                    j += 1
                    break
                low, j = read_char(j)
                if low is None:
                    return None
                first = False
                if j + 1 < size and pattern[j] == "-" and pattern[j + 1] != "]":
                    high, j = read_char(j + 1)
                    if high is None or low > high:
                        return None
                    items.append((low, high))
                else:
                    items.append((low, low))
            tokens.append(("class", negate, items))
            i = j
        else:
            tokens.append(("lit", c))
            i += 1

    def one(token, ch):
        if token[0] == "any":
            return True
        if token[0] == "lit":
            return token[1] == ch
        inside = any(lo <= ch <= hi for lo, hi in token[2])
        return inside != token[1]

    reach = {0}
    for token in tokens:
        if not reach:
            return False
        if token[0] == "star":
            reach = set(range(min(reach), len(text) + 1))
        else:
            reach = {p + 1 for p in reach if p < len(text) and one(token, text[p])}
    return len(text) in reach


def add_business_days(date, n, holidays):
    import datetime
    import re

    def parse(value):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return None
        try:
            return datetime.date(int(value[:4]), int(value[5:7]), int(value[8:]))
        except ValueError:
            return None

    day = parse(date)
    if day is None:
        return None
    closed = {d for d in map(parse, holidays) if d is not None}
    business = lambda d: d.weekday() < 5 and d not in closed
    one = datetime.timedelta(days=1 if n >= 0 else -1)
    remaining = abs(n)
    try:
        if n == 0:
            while not business(day):
                day += one
        while remaining:
            day += one
            if business(day):
                remaining -= 1
    except OverflowError:
        return None
    return day.isoformat()


def rational_eval(expr):
    from fractions import Fraction
    tokens, i = [], 0
    while i < len(expr):
        c = expr[i]
        if c in " \t":
            i += 1
        elif c in "0123456789":
            j = i
            while j < len(expr) and expr[j] in "0123456789":
                j += 1
            tokens.append(("n", int(expr[i:j])))
            i = j
        elif c in "+-*/^()":
            tokens.append((c, None))
            i += 1
        else:
            return "error"

    class Bad(Exception):
        pass

    pos = 0

    def peek():
        return tokens[pos][0] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def expression():
        value = term()
        while peek() in ("+", "-"):
            op = take()[0]
            right = term()
            value = value + right if op == "+" else value - right
        return value

    def term():
        value = unary()
        while peek() in ("*", "/"):
            op = take()[0]
            right = unary()
            if op == "*":
                value = value * right
            else:
                if right == 0:
                    raise Bad()
                value = value / right
        return value

    def unary():
        if peek() == "-":
            take()
            return -unary()
        return power()

    def power():
        base = atom()
        if peek() == "^":
            take()
            exponent = unary()
            if exponent.denominator != 1 or abs(exponent) > 64 or (base == 0 and exponent < 0):
                raise Bad()
            return base ** int(exponent)
        return base

    def atom():
        kind = peek()
        if kind == "n":
            return Fraction(take()[1])
        if kind == "(":
            take()
            value = expression()
            if peek() != ")":
                raise Bad()
            take()
            return value
        raise Bad()

    try:
        value = expression()
        if pos != len(tokens):
            raise Bad()
    except Bad:
        return "error"
    if value.denominator == 1:
        return str(value.numerator)
    return str(value.numerator) + "/" + str(value.denominator)


def shell_words(line, env):
    import re
    name_re = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    size = len(line)

    class Bad(Exception):
        pass

    def expand(i):
        if i + 1 < size and line[i + 1] == "{":
            j = line.find("}", i + 2)
            if j < 0 or not name_re.fullmatch(line[i + 2:j]):
                raise Bad()
            return env.get(line[i + 2:j], ""), j + 1
        match = name_re.match(line, i + 1)
        if match:
            return env.get(match.group(), ""), match.end()
        return "$", i + 1

    words, cur, quoted, active, i = [], [], False, False, 0
    try:
        while i < size:
            c = line[i]
            if c in " \t":
                if active and ("".join(cur) or quoted):
                    words.append("".join(cur))
                cur, quoted, active = [], False, False
                i += 1
            elif c == "\\":
                if i + 1 >= size:
                    return None
                cur.append(line[i + 1])
                active, i = True, i + 2
            elif c == "'":
                j = line.find("'", i + 1)
                if j < 0:
                    return None
                cur.append(line[i + 1:j])
                active, quoted, i = True, True, j + 1
            elif c == '"':
                active, quoted, i = True, True, i + 1
                while True:
                    if i >= size:
                        return None
                    c = line[i]
                    if c == '"':
                        i += 1
                        break
                    if c == "\\" and i + 1 < size and line[i + 1] in '"\\$':
                        cur.append(line[i + 1])
                        i += 2
                    elif c == "$":
                        value, i = expand(i)
                        cur.append(value)
                    else:
                        cur.append(c)
                        i += 1
            elif c == "$":
                value, i = expand(i)
                cur.append(value)
                active = True
            else:
                cur.append(c)
                active, i = True, i + 1
    except Bad:
        return None
    if active and ("".join(cur) or quoted):
        words.append("".join(cur))
    return words


def cron_next(expr, start):
    import calendar
    import datetime
    import re
    fields = expr.split(" ")
    if len(fields) != 5:
        return None
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    sets = []
    for text, (lo, hi) in zip(fields, bounds):
        values = set()
        for item in text.split(","):
            match = re.fullmatch(r"(\*|([0-9]+)(?:-([0-9]+))?)(?:/([0-9]+))?", item)
            if not match:
                return None
            step = int(match.group(4)) if match.group(4) is not None else 1
            if match.group(1) == "*":
                a, b = lo, hi
            elif match.group(3) is not None:
                a, b = int(match.group(2)), int(match.group(3))
            else:
                a = int(match.group(2))
                b = hi if match.group(4) is not None else a
            if step < 1 or not lo <= a <= hi or not lo <= b <= hi or a > b:
                return None
            values.update(range(a, b + 1, step))
        sets.append(values)
    minutes, hours, doms, months, dows = sets
    either = fields[2] != "*" and fields[4] != "*"
    match = re.fullmatch(r"([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2})", start)
    if not match:
        return None
    try:
        now = datetime.datetime(*map(int, match.groups()))
    except ValueError:
        return None
    limit_year = now.year + 5
    try:
        now += datetime.timedelta(minutes=1)
    except OverflowError:
        return None
    day = now.date()
    first = True
    while day.year < limit_year:
        dom_ok, dow_ok = day.day in doms, (day.weekday() + 1) % 7 in dows
        if day.month in months and ((dom_ok or dow_ok) if either else (dom_ok and dow_ok)):
            floor = (now.hour, now.minute) if first else (0, 0)
            for h in sorted(hours):
                for m in sorted(minutes):
                    if (h, m) >= floor:
                        return f"{day.year:04d}-{day.month:02d}-{day.day:02d} {h:02d}:{m:02d}"
        first = False
        if day == datetime.date(9999, 12, 31):
            return None
        day += datetime.timedelta(days=1)
    return None


def date_diff_ymd(a, b):
    import calendar
    import datetime
    import re

    def parse(value):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return None
        try:
            return datetime.date(int(value[:4]), int(value[5:7]), int(value[8:]))
        except ValueError:
            return None

    da, db = parse(a), parse(b)
    if da is None or db is None:
        return None
    sign = 1
    if da > db:
        da, db, sign = db, da, -1

    def shifted(months):
        y, m = divmod(da.year * 12 + da.month - 1 + months, 12)
        return datetime.date(y, m + 1, min(da.day, calendar.monthrange(y, m + 1)[1]))

    total = (db.year - da.year) * 12 + db.month - da.month
    while total > 0 and shifted(total) > db:
        total -= 1
    days = (db - shifted(total)).days
    return [sign * (total // 12), sign * (total % 12), sign * days]


def monthly_occurrences(start, rule, count):
    import calendar
    import datetime
    import re

    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", start):
        return None
    try:
        first = datetime.date(int(start[:4]), int(start[5:7]), int(start[8:]))
    except ValueError:
        return None
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    day_rule = re.fullmatch(r"day:(-?)([1-9][0-9]?)", rule)
    nth_rule = re.fullmatch(r"nth:(-?)([1-5]):(mon|tue|wed|thu|fri|sat|sun)", rule)
    if day_rule:
        number = int(day_rule.group(2))
        if number > 31:
            return None
        number = -number if day_rule.group(1) else number
    elif not nth_rule:
        return None
    if count <= 0:
        return []
    out, year, month = [], first.year, first.month
    while len(out) < count and year <= 9999:
        last = calendar.monthrange(year, month)[1]
        chosen = None
        if day_rule:
            if 0 < number <= last:
                chosen = number
            elif number < 0 and -number <= last:
                chosen = last + 1 + number
        else:
            k = int(nth_rule.group(2)) * (-1 if nth_rule.group(1) else 1)
            weekday = names.index(nth_rule.group(3))
            begin = 1 + (weekday - datetime.date(year, month, 1).weekday()) % 7
            days = list(range(begin, last + 1, 7))
            if -len(days) <= (k - 1 if k > 0 else k) < len(days):
                chosen = days[k - 1] if k > 0 else days[k]
        if chosen is not None and datetime.date(year, month, chosen) >= first:
            out.append(datetime.date(year, month, chosen).isoformat())
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def schedule_jobs(jobs, workers):
    if workers < 1:
        return None
    free_at = [0] * workers
    waiting = list(range(len(jobs)))
    t, out = 0, []
    while waiting:
        idle = [w for w in range(workers) if free_at[w] <= t]
        ready = [i for i in waiting if jobs[i][1] <= t]
        while idle and ready:
            pick = min(ready, key=lambda i: (-jobs[i][3], jobs[i][1], jobs[i][0]))
            worker = idle.pop(0)
            job = jobs[pick]
            out.append([job[0], worker, t, t + job[2]])
            free_at[worker] = t + job[2]
            ready.remove(pick)
            waiting.remove(pick)
        if waiting:
            t = min([f for f in free_at if f > t] + [jobs[i][1] for i in waiting if jobs[i][1] > t])
    out.sort(key=lambda row: (row[2], row[1]))
    return out


def lex_shortest_path(edges, src, dst):
    import heapq
    if any(w < 1 for _, _, w in edges):
        return None
    if src == dst:
        return [0, [src]]
    forward, backward = {}, {}
    for u, v, w in edges:
        forward.setdefault(u, {})
        forward[u][v] = min(w, forward[u].get(v, w))
        backward.setdefault(v, {})
        backward[v][u] = min(w, backward[v].get(u, w))
    dist, heap = {dst: 0}, [(0, dst)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, w in backward.get(u, {}).items():
            if v not in dist or d + w < dist[v]:
                dist[v] = d + w
                heapq.heappush(heap, (d + w, v))
    if src not in dist:
        return None
    path, u = [src], src
    while u != dst:
        u = min(v for v, w in forward[u].items() if v in dist and w + dist[v] == dist[u])
        path.append(u)
    return [dist[src], path]


def stable_topo(names, deps):
    import heapq
    order = list(dict.fromkeys(names))
    pos = {name: i for i, name in enumerate(order)}
    edges = {(a, b) for a, b in deps if a in pos and b in pos}
    succ = {name: set() for name in order}
    indeg = {name: 0 for name in order}
    for a, b in edges:
        succ[a].add(b)
        indeg[b] += 1
    heap = [pos[n] for n in order if indeg[n] == 0]
    heapq.heapify(heap)
    out = []
    while heap:
        name = order[heapq.heappop(heap)]
        out.append(name)
        for nxt in succ[name]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, pos[nxt])

    def on_cycle(name):
        seen, stack = set(), list(succ[name])
        while stack:
            cur = stack.pop()
            if cur == name:
                return True
            if cur not in seen:
                seen.add(cur)
                stack.extend(succ[cur])
        return False

    done = set(out)
    cyclic = [n for n in order if n not in done and on_cycle(n)]
    blocked = [n for n in order if n not in done and n not in cyclic]
    return {"order": out, "cyclic": cyclic, "blocked": blocked}


def order_book(ops):
    bids, asks, used, trades = [], [], set(), []
    for seq, op in enumerate(ops):
        kind = op[0] if op else None
        if kind == "cancel" and len(op) == 2:
            bids[:] = [o for o in bids if o[2] != op[1]]
            asks[:] = [o for o in asks if o[2] != op[1]]
            continue
        if kind == "limit" and len(op) == 5:
            _, oid, side, price, qty = op
            if price < 1:
                continue
        elif kind == "market" and len(op) == 4:
            _, oid, side, qty = op
            price = None
        else:
            continue
        if side not in ("buy", "sell") or qty < 1 or oid in used:
            continue
        used.add(oid)
        book = asks if side == "buy" else bids
        while qty and book:
            best = min(book, key=lambda o: (o[0] if side == "buy" else -o[0], o[1]))
            if price is not None and (best[0] > price if side == "buy" else best[0] < price):
                break
            fill = min(qty, best[3])
            trades.append([oid, best[2], best[0], fill] if side == "buy" else [best[2], oid, best[0], fill])
            qty -= fill
            best[3] -= fill
            if best[3] == 0:
                book.remove(best)
        if qty and price is not None:
            (bids if side == "buy" else asks).append([price, seq, oid, qty])
    return {"trades": trades,
            "bids": [[o[2], o[0], o[3]] for o in sorted(bids, key=lambda o: (-o[0], o[1]))],
            "asks": [[o[2], o[0], o[3]] for o in sorted(asks, key=lambda o: (o[0], o[1]))]}


def ledger(accounts, ops):
    balance = {name: bal for name, bal, _ in accounts}
    limit = {name: od for name, _, od in accounts}
    frozen, today, rejected = set(), {}, []
    shapes = {"dep": 3, "wd": 3, "xfer": 4, "freeze": 2, "thaw": 2, "day": 1}
    for index, op in enumerate(ops):
        kind = op[0] if op else None
        if kind not in shapes or len(op) != shapes[kind]:
            rejected.append([index, "bad_op"])
            continue
        if kind == "day":
            today = {}
            continue
        names = op[1:3] if kind == "xfer" else op[1:2]
        if any(name not in balance for name in names):
            rejected.append([index, "no_account"])
            continue
        if kind == "freeze":
            frozen.add(op[1])
            continue
        if kind == "thaw":
            frozen.discard(op[1])
            continue
        if kind == "xfer" and op[1] == op[2]:
            rejected.append([index, "same_account"])
            continue
        amount = op[-1]
        if amount < 1:
            rejected.append([index, "bad_amount"])
            continue
        if kind == "dep":
            balance[op[1]] += amount
            continue
        source = op[1]
        if source in frozen:
            rejected.append([index, "frozen"])
            continue
        fee = 1 if kind == "xfer" else (2 if today.get(source, 0) >= 3 else 0)
        if balance[source] - amount - fee < -limit[source]:
            rejected.append([index, "insufficient"])
            continue
        balance[source] -= amount + fee
        if kind == "xfer":
            balance[op[2]] += amount
        else:
            today[source] = today.get(source, 0) + 1
    return {"balances": [[name, balance[name]] for name in sorted(balance)], "rejected": rejected}


def spreadsheet_eval(cells):
    import re

    class Bad(Exception):
        pass

    def parse(text):
        tokens, i = [], 0
        while i < len(text):
            c = text[i]
            if c == " ":
                i += 1
            elif c.isascii() and c.isdigit():
                j = i
                while j < len(text) and text[j].isascii() and text[j].isdigit():
                    j += 1
                tokens.append(("int", int(text[i:j])))
                i = j
            elif "A" <= c <= "Z":
                j = i
                while j < len(text) and "A" <= text[j] <= "Z":
                    j += 1
                k = j
                while k < len(text) and text[k].isascii() and text[k].isdigit():
                    k += 1
                word, digits = text[i:j], text[j:k]
                if word == "SUM" and not digits and text[k:k + 1] == "(":
                    tokens.append(("sum", None))
                    k += 1
                elif len(word) == 1 and re.fullmatch(r"[1-9][0-9]?", digits):
                    tokens.append(("ref", (word, int(digits))))
                else:
                    raise Bad()
                i = k
            elif c in "+-*():":
                tokens.append((c, None))
                i += 1
            else:
                raise Bad()
        pos = 0
        refs = []

        def peek():
            return tokens[pos][0] if pos < len(tokens) else None

        def take(kind):
            nonlocal pos
            if peek() != kind:
                raise Bad()
            pos += 1
            return tokens[pos - 1][1]

        def expression():
            node = term()
            while peek() in ("+", "-"):
                op = peek()
                take(op)
                node = (op, node, term())
            return node

        def term():
            node = unary()
            while peek() == "*":
                take("*")
                node = ("*", node, unary())
            return node

        def unary():
            if peek() == "-":
                take("-")
                return ("neg", unary())
            return primary()

        def primary():
            kind = peek()
            if kind == "int":
                return ("int", take("int"))
            if kind == "ref":
                ref = take("ref")
                name = ref[0] + str(ref[1])
                refs.append(name)
                return ("ref", name)
            if kind == "sum":
                take("sum")
                a = take("ref")
                take(":")
                b = take("ref")
                take(")")
                cols = range(min(ord(a[0]), ord(b[0])), max(ord(a[0]), ord(b[0])) + 1)
                rows = range(min(a[1], b[1]), max(a[1], b[1]) + 1)
                names = [chr(c) + str(r) for r in rows for c in cols]
                refs.extend(names)
                return ("sum", names)
            take("(")
            node = expression()
            take(")")
            return node

        node = expression()
        if pos != len(tokens):
            raise Bad()
        return node, refs

    values, formulas = {}, {}
    for key, raw in cells.items():
        if raw.startswith("="):
            try:
                formulas[key] = parse(raw[1:])
            except Bad:
                values[key] = "#SYNTAX"
        elif re.fullmatch(r"-?[0-9]+", raw):
            values[key] = int(raw)
        else:
            values[key] = "#VALUE"

    def reaches(origin):
        seen, stack = set(), [r for r in formulas[origin][1] if r in formulas]
        while stack:
            cur = stack.pop()
            if cur == origin:
                return True
            if cur not in seen:
                seen.add(cur)
                stack.extend(r for r in formulas[cur][1] if r in formulas)
        return False

    for key in formulas:
        if reaches(key):
            values[key] = "#CYCLE"

    def value(key):
        if key not in cells:
            return 0
        if key not in values:
            node, refs = formulas[key]
            error = None
            for ref in refs:
                v = value(ref)
                if isinstance(v, str):
                    error = v
                    break
            values[key] = error if error is not None else compute(node)
        return values[key]

    def compute(node):
        kind = node[0]
        if kind == "int":
            return node[1]
        if kind == "ref":
            return value(node[1])
        if kind == "sum":
            return sum(value(name) for name in node[1])
        if kind == "neg":
            return -compute(node[1])
        left, right = compute(node[1]), compute(node[2])
        return left + right if kind == "+" else left - right if kind == "-" else left * right

    return {key: value(key) for key in cells}


def poly_expand(expr):
    tokens, i = [], 0
    while i < len(expr):
        c = expr[i]
        if c == " ":
            i += 1
        elif c in "0123456789":
            j = i
            while j < len(expr) and expr[j] in "0123456789":
                j += 1
            tokens.append(("int", int(expr[i:j])))
            i = j
        elif c in "x+-*^()":
            tokens.append((c, None))
            i += 1
        else:
            return None

    class Bad(Exception):
        pass

    pos = 0

    def peek():
        return tokens[pos][0] if pos < len(tokens) else None

    def take(kind):
        nonlocal pos
        if peek() != kind:
            raise Bad()
        pos += 1
        return tokens[pos - 1][1]

    def add(p, q, sign=1):
        out = dict(p)
        for d, c in q.items():
            out[d] = out.get(d, 0) + sign * c
        return {d: c for d, c in out.items() if c}

    def mul(p, q):
        out = {}
        for d1, c1 in p.items():
            for d2, c2 in q.items():
                out[d1 + d2] = out.get(d1 + d2, 0) + c1 * c2
        return {d: c for d, c in out.items() if c}

    def expression():
        value = term()
        while peek() in ("+", "-"):
            op = peek()
            take(op)
            value = add(value, term(), 1 if op == "+" else -1)
        return value

    def term():
        value = factor()
        while peek() == "*":
            take("*")
            value = mul(value, factor())
        return value

    def factor():
        if peek() == "-":
            take("-")
            return {d: -c for d, c in factor().items()}
        if peek() == "int":
            base = {0: take("int")}
            base = {d: c for d, c in base.items() if c}
        elif peek() == "x":
            take("x")
            base = {1: 1}
        else:
            take("(")
            base = expression()
            take(")")
        if peek() == "^":
            take("^")
            exponent = take("int")
            if exponent > 20:
                raise Bad()
            result = {0: 1}
            for _ in range(exponent):
                result = mul(result, base)
            base = result
        return base

    try:
        poly = expression()
        if pos != len(tokens):
            raise Bad()
    except Bad:
        return None
    if not poly:
        return "0"
    out = ""
    for degree in sorted(poly, reverse=True):
        coef = poly[degree]
        mag = abs(coef)
        body = str(mag) if degree == 0 or mag != 1 else ""
        if degree >= 1:
            body += "x" + ("^" + str(degree) if degree > 1 else "")
        if coef < 0:
            out += "-" + body
        else:
            out += ("+" if out else "") + body
    return out


def bool_minterms(expr):
    tokens, i = [], 0
    while i < len(expr):
        c = expr[i]
        if c == " ":
            i += 1
        elif "a" <= c <= "z":
            j = i
            while j < len(expr) and "a" <= expr[j] <= "z":
                j += 1
            tokens.append(("var", expr[i:j]))
            i = j
        elif c in "0123456789":
            j = i
            while j < len(expr) and expr[j] in "0123456789":
                j += 1
            if expr[i:j] not in ("0", "1"):
                return None
            tokens.append(("const", expr[i:j] == "1"))
            i = j
        elif expr.startswith("->", i):
            tokens.append(("->", None))
            i += 2
        elif c in "!&^|()":
            tokens.append((c, None))
            i += 1
        else:
            return None

    class Bad(Exception):
        pass

    pos = 0

    def peek():
        return tokens[pos][0] if pos < len(tokens) else None

    def take(kind):
        nonlocal pos
        if peek() != kind:
            raise Bad()
        pos += 1
        return tokens[pos - 1][1]

    def implication():
        left = disjunction()
        if peek() == "->":
            take("->")
            right = implication()
            return ("->", left, right)
        return left

    def binary(op, inner):
        def parse():
            node = inner()
            while peek() == op:
                take(op)
                node = (op, node, inner())
            return node
        return parse

    def negation():
        if peek() == "!":
            take("!")
            return ("!", negation())
        if peek() == "var":
            return ("var", take("var"))
        if peek() == "const":
            return ("const", take("const"))
        take("(")
        node = implication()
        take(")")
        return node

    conjunction = binary("&", negation)
    exclusive = binary("^", conjunction)
    disjunction = binary("|", exclusive)
    try:
        tree = implication()
        if pos != len(tokens):
            raise Bad()
    except Bad:
        return None
    names = sorted({value for kind, value in tokens if kind == "var"})

    def evaluate(node, env):
        kind = node[0]
        if kind == "var":
            return env[node[1]]
        if kind == "const":
            return node[1]
        if kind == "!":
            return not evaluate(node[1], env)
        a, b = evaluate(node[1], env), evaluate(node[2], env)
        return {"&": a and b, "|": a or b, "^": a != b, "->": (not a) or b}[kind]

    minterms = []
    for index in range(2 ** len(names)):
        env = {name: bool(index >> (len(names) - 1 - k) & 1) for k, name in enumerate(names)}
        if evaluate(tree, env):
            minterms.append(index)
    return [names, minterms]


def csv_parse(text):
    if text == "":
        return []
    records, record, i, size = [], [], 0, len(text)

    def at_end_of_field(j):
        return j >= size or text[j] in ",\n" or text.startswith("\r\n", j)

    while True:
        if i < size and text[i] == '"':
            i += 1
            buf = []
            while True:
                if i >= size:
                    return None
                if text[i] == '"':
                    if i + 1 < size and text[i + 1] == '"':
                        buf.append('"')
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    buf.append(text[i])
                    i += 1
            if not at_end_of_field(i):
                return None
            field = "".join(buf)
        else:
            j = i
            while not at_end_of_field(j):
                if text[j] == '"':
                    return None
                j += 1
            field, i = text[i:j], j
        record.append(field)
        if i >= size:
            records.append(record)
            return records
        if text[i] == ",":
            i += 1
            continue
        i += 2 if text.startswith("\r\n", i) else 1
        records.append(record)
        record = []
        if i >= size:
            return records


def league_table(matches):
    stats = {}
    valid = [m for m in matches if m[0] != m[1] and m[2] >= 0 and m[3] >= 0]
    for home, away, hg, ag in valid:
        for team, gf, ga in ((home, hg, ag), (away, ag, hg)):
            s = stats.setdefault(team, [0, 0, 0, 0, 0, 0, 0])
            s[0] += 1
            s[4] += gf
            s[5] += ga
            if gf > ga:
                s[1] += 1
                s[6] += 3
            elif gf == ga:
                s[2] += 1
                s[6] += 1
            else:
                s[3] += 1

    def key(team):
        group = {t for t in stats if stats[t][6] == stats[team][6]}
        h2h_points = h2h_diff = 0
        for home, away, hg, ag in valid:
            if home in group and away in group and team in (home, away):
                gf, ga = (hg, ag) if team == home else (ag, hg)
                h2h_points += 3 if gf > ga else 1 if gf == ga else 0
                h2h_diff += gf - ga
        s = stats[team]
        return (-s[6], -h2h_points, -h2h_diff, -(s[4] - s[5]), -s[4], team)

    return [[team] + stats[team] for team in sorted(stats, key=key)]


def canonical_huffman(freqs):
    import heapq
    weights = {}
    for symbol, weight in freqs:
        if weight > 0:
            weights[symbol] = weights.get(symbol, 0) + weight
    if not weights:
        return []
    lengths = {symbol: 0 for symbol in weights}
    if len(weights) == 1:
        lengths = {symbol: 1 for symbol in weights}
    else:
        heap = [(w, s, [s]) for s, w in weights.items()]
        heapq.heapify(heap)
        while len(heap) > 1:
            w1, k1, l1 = heapq.heappop(heap)
            w2, k2, l2 = heapq.heappop(heap)
            for s in l1 + l2:
                lengths[s] += 1
            heapq.heappush(heap, (w1 + w2, min(k1, k2), l1 + l2))
    ordered = sorted(weights, key=lambda s: (lengths[s], s))
    out, code, previous = [], 0, lengths[ordered[0]]
    for index, symbol in enumerate(ordered):
        if index:
            code = (code + 1) << (lengths[symbol] - previous)
        previous = lengths[symbol]
        out.append([symbol, format(code, "0" + str(previous) + "b")])
    return out


def token_bucket(capacity, refill_ms, requests):
    if capacity < 1 or refill_ms < 1:
        return None
    tokens, mark, last, accepted = capacity, 0, None, []
    for index, (t, cost) in enumerate(requests):
        if cost < 1 or t < 0 or (last is not None and t < last):
            continue
        last = t
        if tokens < capacity:
            gained = (t - mark) // refill_ms
            if tokens + gained >= capacity:
                tokens = capacity
            else:
                tokens += gained
                mark += gained * refill_ms
        if tokens == capacity:
            mark = t
        if cost <= tokens:
            tokens -= cost
            accepted.append(index)
    return accepted


def json_select(doc, path):
    import re
    name_re = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    index_re = re.compile(r"\[(-?(?:0|[1-9][0-9]*))\]")
    if not path.startswith("$"):
        return None
    steps, i = [], 1
    while i < len(path):
        if path.startswith("..", i):
            match = name_re.match(path, i + 2)
            if not match:
                return None
            steps.append(("deep", match.group()))
            i = match.end()
        elif path[i] == ".":
            match = name_re.match(path, i + 1)
            if not match:
                return None
            steps.append(("key", match.group()))
            i = match.end()
        elif path.startswith("[*]", i):
            steps.append(("all", None))
            i += 3
        elif path.startswith("['", i):
            j, buf = i + 2, []
            while True:
                if j >= len(path):
                    return None
                c = path[j]
                if c == "\\":
                    if j + 1 < len(path) and path[j + 1] in "'\\":
                        buf.append(path[j + 1])
                        j += 2
                    else:
                        return None
                elif c == "'":
                    j += 1
                    break
                else:
                    buf.append(c)
                    j += 1
            if not path.startswith("]", j):
                return None
            steps.append(("key", "".join(buf)))
            i = j + 1
        else:
            match = index_re.match(path, i)
            if not match:
                return None
            steps.append(("index", int(match.group(1))))
            i = match.end()

    def deep(node, name, out):
        if type(node) is dict:
            if name in node:
                out.append(node[name])
            for child in node.values():
                deep(child, name, out)
        elif type(node) is list:
            for child in node:
                deep(child, name, out)

    current = [doc]
    for kind, arg in steps:
        nxt = []
        for node in current:
            if kind == "key" and type(node) is dict and arg in node:
                nxt.append(node[arg])
            elif kind == "index" and type(node) is list and -len(node) <= arg < len(node):
                nxt.append(node[arg])
            elif kind == "all" and type(node) is list:
                nxt.extend(node)
            elif kind == "all" and type(node) is dict:
                nxt.extend(node.values())
            elif kind == "deep":
                deep(node, arg, nxt)
        current = nxt
    return current


def common_free_slots(calendars, day_start, day_end, min_len):
    import re

    def minutes(text):
        if text == "24:00":
            return 1440
        if not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", text):
            return None
        return int(text[:2]) * 60 + int(text[3:])

    if min_len < 1:
        return None
    start, end = minutes(day_start), minutes(day_end)
    if start is None or end is None:
        return None
    busy = []
    for offset, intervals in calendars:
        for a, b in intervals:
            ma, mb = minutes(a), minutes(b)
            if ma is None or mb is None:
                return None
            if mb > ma:
                busy.append((max(start, ma - offset), min(end, mb - offset)))
    if end <= start:
        return []
    free, cursor = [], start
    for a, b in sorted(x for x in busy if x[0] < x[1]):
        if a > cursor:
            free.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < end:
        free.append((cursor, end))
    fmt = lambda m: f"{m // 60:02d}:{m % 60:02d}"
    return [[fmt(a), fmt(b)] for a, b in free if b - a >= min_len]


def min_coins_lex(coins, amount):
    if amount < 0:
        return None
    denominations = sorted({c for c in coins if c > 0}, reverse=True)
    best = [None] * (amount + 1)
    best[0] = []
    for value in range(1, amount + 1):
        chosen = None
        for coin in denominations:
            if coin <= value and best[value - coin] is not None:
                candidate = sorted(best[value - coin] + [coin], reverse=True)
                if chosen is None or len(candidate) < len(chosen) or (len(candidate) == len(chosen) and candidate > chosen):
                    chosen = candidate
        best[value] = chosen
    return best[amount]


def render_table(headers, rows, aligns):
    k = len(headers)
    if len(aligns) != k or any(c not in "lrc" for c in aligns) or any(len(row) > k for row in rows):
        return None
    if k == 0:
        return []
    cell = lambda v: str(v).replace("|", "\\|")
    grid = [[cell(h) for h in headers]] + [[cell(v) for v in row] + [""] * (k - len(row)) for row in rows]
    widths = [max([3] + [len(row[c]) for row in grid]) for c in range(k)]

    def pad(text, width, align):
        extra = width - len(text)
        if align == "l":
            return text + " " * extra
        if align == "r":
            return " " * extra + text
        return " " * (extra // 2) + text + " " * (extra - extra // 2)

    line = lambda row: "|" + "|".join(" " + pad(row[c], widths[c], aligns[c]) + " " for c in range(k)) + "|"
    marks = {"l": lambda w: ":" + "-" * (w + 1), "r": lambda w: "-" * (w + 1) + ":", "c": lambda w: ":" + "-" * w + ":"}
    separator = "|" + "|".join(marks[aligns[c]](widths[c]) for c in range(k)) + "|"
    return [line(grid[0]), separator] + [line(row) for row in grid[1:]]


def decode_repeat(text):
    limit, size, pos = 10000, len(text), 0
    digits = "0123456789"

    class Bad(Exception):
        pass

    def sequence(depth):
        nonlocal pos
        nodes = []
        while pos < size:
            c = text[pos]
            if c == "\\":
                if pos + 1 >= size:
                    raise Bad()
                nodes.append(text[pos + 1])
                pos += 2
            elif c in digits:
                j = pos
                while j < size and text[j] in digits:
                    j += 1
                if j < size and text[j] == "[":
                    count = int(text[pos:j])
                    pos = j + 1
                    inner = sequence(depth + 1)
                    if pos >= size or text[pos] != "]":
                        raise Bad()
                    pos += 1
                    nodes.append((count, inner))
                else:
                    nodes.append(text[pos:j])
                    pos = j
            elif c == "[":
                raise Bad()
            elif c == "]":
                if depth == 0:
                    raise Bad()
                return nodes
            else:
                nodes.append(c)
                pos += 1
        if depth:
            raise Bad()
        return nodes

    def length(nodes):
        total = 0
        for node in nodes:
            total += len(node) if isinstance(node, str) else node[0] * length(node[1])
            total = min(total, limit + 1)
        return total

    def build(nodes):
        return "".join(node if isinstance(node, str) else build(node[1]) * node[0] if node[0] else "" for node in nodes)

    try:
        tree = sequence(0)
    except Bad:
        return None
    if length(tree) > limit:
        return None
    return build(tree)


def grid_portals(grid):
    from collections import deque
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    where, starts, ends = {}, [], []
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if ch == "S":
                starts.append((r, c))
            elif ch == "E":
                ends.append((r, c))
            elif "a" <= ch <= "z":
                where.setdefault(ch, []).append((r, c))
            elif ch not in ".#":
                return None
    if len(starts) != 1 or len(ends) != 1 or any(len(v) != 2 for v in where.values()):
        return None
    twin = {}
    for a, b in where.values():
        twin[a], twin[b] = b, a
    dist = {starts[0]: 0}
    queue = deque([starts[0]])
    while queue:
        cell = queue.popleft()
        if cell == ends[0]:
            return dist[cell]
        r, c = cell
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] != "#":
                land = twin.get((nr, nc), (nr, nc))
                if land not in dist:
                    dist[land] = dist[cell] + 1
                    queue.append(land)
    return -1


def lru_ttl(capacity, ops):
    from collections import OrderedDict
    store, out = OrderedDict(), []
    for op in ops:
        if op[0] == "get":
            _, t, key = op
            if key in store and t < store[key][1]:
                store.move_to_end(key)
                out.append(store[key][0])
            else:
                out.append(None)
            continue
        _, t, key, value, ttl = op
        if ttl <= 0:
            store.pop(key, None)
            continue
        for old in [k for k, (_, expiry) in store.items() if expiry <= t]:
            del store[old]
        if key in store:
            store[key] = (value, t + ttl)
            store.move_to_end(key)
        elif capacity > 0:
            if len(store) >= capacity:
                store.popitem(last=False)
            store[key] = (value, t + ttl)
    return out


# ----------------------------------------------------------------------------
# Seeded input generators (trusted generator code; never shown to models)
# ----------------------------------------------------------------------------

def _words(r):
    vocab = ["a", "to", "well-known", "state-of-the-art", "x-", "-y", "co--op", "hyphen-", "antidisestablish",
             "re-entry", "e-mail", "tab\tchar", "end.", "mid-air-refuel", "z", "verylongwordwithout"]
    return " ".join(r.choice(vocab) + " " * r.randrange(3) for _ in range(r.randrange(1, 7))).strip(" ") * r.choice([1, 1, 1])


def _semver(r):
    core = ".".join(r.choice(["0", "1", "2", "10", "01", "9"]) for _ in range(3))
    if r.random() < 0.1:
        core = r.choice(["1.2", "1.2.3.4", "v1.2.3", "1.2.x", "", " 1.0.0"])
    pre = r.choice(["", "", "-alpha", "-alpha.1", "-alpha.beta", "-beta.2", "-beta.11", "-rc.1", "-0", "-00",
                    "-0a", "-x-y", "-1", "-", "-a..b", "-alpha.01"])
    build = r.choice(["", "", "", "+build.5", "+001", "+", "+a.b-c", "+x..y"])
    return core + pre + build


def _vm_program(r):
    n = r.randint(1, 6)
    templates = [
        ["PUSH %d" % n, "DUP", "PRINT", "PUSH 1", "SUB", "DUP", "JNZ 1", "POP"],
        ["PUSH 1", "PUSH %d" % n, "DUP", "JZ 11", "DUP", "PUSH -1", "ADD", "SWAP", "CALL 12", "SWAP", "JMP 2", "POP", "MUL", "RET"],
        ["PUSH %d" % r.randint(-20, 20), "PUSH %d" % r.choice([-7, -3, 0, 3, 7]), "OVER", "OVER", "DIV", "PRINT", "MOD", "PRINT"],
        ["CALL 3", "PRINT", "HALT", "PUSH %d" % n, "RET", "PRINT"],
        ["PUSH 0", "JZ %d" % r.choice([3, 4, 5, -1, 9]), "PUSH 7", "PRINT"],
        ["RET"], ["PUSH 2", "PUSH 3", "SWAP", "SUB", "PRINT", "POP"],
        ["PUSH %d" % n, "JMP 0"],
        ["push 1"], ["PUSH 1 2"], ["PUSH +1"], ["PUSH  1"], ["NOP"], ["PUSH 5", "DUP", "MUL", "PRINT", "HALT", "PRINT"],
    ]
    program = list(r.choice(templates))
    if r.random() < 0.3:
        ops = ["POP", "DUP", "SWAP", "OVER", "ADD", "SUB", "MUL", "DIV", "MOD", "PRINT", "PUSH %d" % r.randint(-9, 9),
               "JZ %d" % r.randint(0, 9), "JNZ %d" % r.randint(0, 9), "RET", "CALL %d" % r.randint(0, 9)]
        program.insert(r.randrange(len(program) + 1), r.choice(ops))
    return program


def _cidr(r):
    if r.random() < 0.12:
        return r.choice(["10.0.0.1", "256.1.1.1/8", "10.0.0.0/33", "1.2.3/8", "01.2.3.4/8", "1.2.3.4/08", "a.b.c.d/1",
                         "1.2.3.4/ 8", "1.2.3.4//8"])
    base = r.choice([(10, 0), (10, 1), (192, 168), (172, 16)])
    return "%d.%d.%d.%d/%d" % (base[0], base[1] ^ r.randrange(2), r.randrange(0, 256, r.choice([1, 64, 128])),
                               r.choice([0, 0, 1, 128, 255]), r.choice([0, 8, 15, 16, 17, 23, 24, 25, 31, 32, 30]))


def _glob_pair(r):
    pieces = {"a": ["a"], "b": ["b"], "?": ["a", "]", "-"], "*": ["", "ab", "]*"], "[ab]": ["a", "b"], "[!a]": ["b", "]"],
              "[a-c]": ["b", "c"], "[]a]": ["]", "a"], "[!]]": ["a", "["], "\\*": ["*"], "\\[": ["["], "-": ["-"],
              "[a-]": ["-", "a"], "[-b]": ["-", "b"], "]": ["]"]}
    chosen = [r.choice(sorted(pieces)) for _ in range(r.randrange(0, 5))]
    pattern = "".join(chosen)
    text = "".join(r.choice(pieces[p]) for p in chosen)
    if r.random() < 0.4:
        position = r.randrange(len(text) + 1)
        text = text[:position] + r.choice("ab-]*[c") + text[position + r.randrange(2):]
    if r.random() < 0.1:
        pattern += r.choice(["[", "\\", "[c-a]", "[!", "[]"])
    return [pattern, text]


def _perm_case(r):
    from collections import Counter
    from math import factorial
    s = "".join(r.choice("aabbcdz") for _ in range(r.randint(1, 16)))
    total = factorial(len(s))
    for count in Counter(s).values():
        total //= factorial(count)
    roll = r.random()
    n = r.randrange(total) if roll < 0.75 else total - 1 if roll < 0.85 else total if roll < 0.95 else -1
    return [s, n]


def _date(r, lo=2019, hi=2030, invalid=0.05):
    import calendar
    y = r.randint(lo, hi)
    m = r.randint(1, 12)
    d = r.choice([1, 15, 28, 29, 30, 31, r.randint(1, 31)])
    if r.random() >= invalid:
        d = min(d, calendar.monthrange(y, m)[1])
    return "%04d-%02d-%02d" % (y, m, d)


def _arith(r, depth=0):
    if depth > 2 or r.random() < 0.35:
        return str(r.randint(0, 12))
    kind = r.randrange(6)
    a, b = _arith(r, depth + 1), _arith(r, depth + 1)
    if kind == 0:
        return "(" + a + ")"
    if kind == 1:
        return "-" + a
    if kind == 2:
        return a + r.choice(["^", " ^ "]) + r.choice(["2", "-1", "3", "0", "-2", "(1/2)", "65"])
    return a + r.choice(["+", "-", "*", "/", " / ", " * "]) + b


def _shell_line(r):
    parts = ["a", "b c", "'q w'", '"d $X e"', "$X", "${Y}", "$Z", "''", '""', "\\ ", "\\$X", "$", "$1", "${X}y",
             '"\\$X"', '"a\\b"', '"\\\\"', "'$X'", "\t", "  ", "f\"g\"h", "$X_1", '"${Y}z"', "x'y'z"]
    line = "".join(r.choice(parts) for _ in range(r.randrange(1, 6)))
    if r.random() < 0.12:
        line += r.choice(["${", "${9}", "'", '"', "\\"])
    return line


def _cron_field(r, lo, hi):
    options = ["*", str(r.randint(lo, hi)), "%d-%d" % tuple(sorted((r.randint(lo, hi), r.randint(lo, hi)))),
               "*/%d" % r.randint(1, 15), "%d/%d" % (r.randint(lo, hi), r.randint(2, 10)),
               "%d,%d" % (r.randint(lo, hi), r.randint(lo, hi))]
    return r.choice(options)


def _cron(r):
    fields = [_cron_field(r, 0, 59), _cron_field(r, 0, 23), r.choice(["*", "*", _cron_field(r, 1, 31)]),
              r.choice(["*", "*", _cron_field(r, 1, 12)]), r.choice(["*", "*", _cron_field(r, 0, 6)])]
    return " ".join(fields)


def _graph(r):
    nodes = list("abcdef")[: r.randint(2, 6)]
    edges = []
    for _ in range(r.randint(0, 10)):
        u, v = r.choice(nodes), r.choice(nodes)
        if u != v:
            edges.append([u, v, r.randint(1, 3)])
    return [edges, r.choice(nodes), r.choice(nodes)]


def _orders(r):
    ops, ids = [], ["o%d" % i for i in range(8)]
    for _ in range(r.randint(1, 9)):
        roll = r.random()
        if roll < 0.6:
            ops.append(["limit", r.choice(ids), r.choice(["buy", "sell"]), r.randint(9, 12), r.randint(1, 5)])
        elif roll < 0.75:
            ops.append(["market", r.choice(ids), r.choice(["buy", "sell"]), r.randint(1, 8)])
        elif roll < 0.9:
            ops.append(["cancel", r.choice(ids)])
        else:
            ops.append(r.choice([["limit", "z", "buy", 0, 1], ["limit", "y", "hold", 10, 1], ["market", "w", "sell", 0], ["noop"]]))
    return ops


def _ledger(r):
    names = ["ann", "bob", "cy"][: r.randint(1, 3)]
    accounts = [[n, r.randint(0, 20), r.choice([0, 0, 5, 10])] for n in names]
    ops = []
    for _ in range(r.randint(1, 10)):
        who = r.choice(names + ["zed"])
        roll = r.randrange(9)
        if roll < 3:
            ops.append(["wd", who, r.choice([1, 3, 5, 8, 0, -2])])
        elif roll == 3:
            ops.append(["dep", who, r.choice([1, 5, 10, 0])])
        elif roll == 4:
            ops.append(["xfer", who, r.choice(names), r.choice([1, 4, 9])])
        elif roll == 5:
            ops.append([r.choice(["freeze", "thaw"]), who])
        elif roll == 6:
            ops.append(["day"])
        else:
            ops.append(r.choice([["wd", who, 2], ["wd", who], ["refund", who, 3], ["day", 1]]))
    return [accounts, ops]


def _sheet(r):
    names = ["A1", "A2", "B1", "B2", "C1"]
    cells = {}
    for name in r.sample(names, r.randint(1, 5)):
        roll = r.randrange(10)
        if roll < 3:
            cells[name] = str(r.randint(-5, 9))
        elif roll < 9:
            refs = [r.choice(names + ["C2"]) for _ in range(2)]
            cells[name] = r.choice(["=%s+%s" % tuple(refs), "=%s*2-%s" % tuple(refs), "=SUM(%s:%s)" % tuple(refs),
                                    "=-(%s)" % refs[0], "=3*(%s - 1)" % refs[1], "=%s" % refs[0]])
        else:
            cells[name] = r.choice(["x", "", "=1+", "=SUM(A1)", "=a1", "=A0", " 5", "=2*-B1", "=A01"])
    return [cells]


def _poly(r, depth=0):
    if depth > 2 or r.random() < 0.3:
        return r.choice(["x", "1", "2", "0", "3", "x^2", "x^0"])
    kind = r.randrange(5)
    a, b = _poly(r, depth + 1), _poly(r, depth + 1)
    if kind == 0:
        return "(" + a + ")^" + r.choice(["2", "3", "0", "1"])
    if kind == 1:
        return "-" + a
    return a + r.choice(["+", "-", "*", " * ", " - "]) + b


def _bool(r, depth=0):
    if depth > 2 or r.random() < 0.3:
        return r.choice(["a", "b", "c", "q", "1", "0"])
    a, b = _bool(r, depth + 1), _bool(r, depth + 1)
    kind = r.randrange(7)
    if kind == 0:
        return "!" + a
    if kind == 1:
        return "(" + a + ")"
    return a + r.choice([" & ", "|", " ^ ", " -> ", "&", "->"]) + b


def _csv(r):
    if r.random() < 0.65:
        rows = [[r.choice(["a", "", "b c", 'q"t', "x,y", "l\nm", "r\r"]) for _ in range(r.randint(1, 3))] for _ in range(r.randint(1, 3))]
        out = []
        for row in rows:
            out.append(",".join('"' + f.replace('"', '""') + '"' if (r.random() < 0.3 or any(ch in f for ch in '",\n')) else f for f in row))
        return r.choice(["\n", "\r\n"]).join(out) + r.choice(["", "\n", "\r\n"])
    return "".join(r.choice(["a", "b", ",", '"', '""', "\n", "\r\n", "\r", " ", '"x"']) for _ in range(r.randrange(1, 8)))


def _matches(r):
    teams = ["Ash", "Birch", "Cedar", "Dogwood"][: r.randint(2, 4)]
    out = []
    for _ in range(r.randint(1, 8)):
        h, a = r.choice(teams), r.choice(teams)
        out.append([h, a, r.choice([0, 0, 1, 1, 2, 3]), r.choice([0, 0, 1, 1, 2, -1 if r.random() < 0.05 else 1])])
    return out


def _freqs(r):
    symbols = list("abcdefg")
    return [[r.choice(symbols), r.choice([1, 1, 2, 3, 5, 8, 0, -1])] for _ in range(r.randint(0, 8))]


def _bucket(r):
    reqs, t = [], 0
    for _ in range(r.randint(1, 10)):
        t += r.choice([0, 0, 1, 3, 5, 10, 25, -4])
        reqs.append([t, r.choice([1, 1, 2, 3, 0, 5])])
    return [r.randint(1, 5), r.choice([1, 4, 5, 10]), reqs]


def _doc(r, depth=0):
    if depth > 2:
        return r.choice([1, "s", None, True, [], {}])
    if r.random() < 0.5:
        return {k: _doc(r, depth + 1) for k in r.sample(["a", "b", "id", "x y", "it's"], r.randint(0, 3))}
    return [_doc(r, depth + 1) for _ in range(r.randint(0, 3))]


def _jpath(r):
    pieces = [".a", ".a", ".b", ".id", "[0]", "[1]", "[-1]", "[*]", "[*]", "..a", "..a", "..id", "['x y']", "['it\\'s']", "[2]"]
    path = "$" + "".join(r.choice(pieces) for _ in range(r.randint(0, 3)))
    if r.random() < 0.1:
        path = r.choice(["a", "$.", "$..", "$[01]", "$['a]", "$[a]", "$.1a", "$['\\x']", "$ .a"])
    return path


def _slots(r):
    def t():
        return "%02d:%02d" % (r.randint(7, 18), r.choice([0, 15, 30, 45])) if r.random() < 0.85 else r.choice(["24:00", "00:00", "7:00"])
    calendars = [[r.choice([0, 0, 60, -60, 90]), [[t(), t()] for _ in range(r.randint(0, 3))]] for _ in range(r.randint(0, 3))]
    return [calendars, r.choice(["08:00", "09:00", "00:00"]), r.choice(["17:00", "18:30", "24:00"]), r.choice([1, 15, 30, 60])]


def _table(r):
    k = r.randint(1, 3)
    headers = [r.choice(["id", "name", "qty", "", "a|b", "longheader"]) for _ in range(k)]
    rows = [[r.choice(["x", "", "pipe|", "wide cell", 7, -12, 100000]) for _ in range(r.randint(0, k))] for _ in range(r.randint(0, 3))]
    return [headers, rows, "".join(r.choice("lrc") for _ in range(k))]


def _repeat(r, depth=0):
    out = ""
    for _ in range(r.randint(1, 3)):
        roll = r.randrange(8)
        if roll < 3:
            out += r.choice(["a", "b", "xy", "7", "12", "\\[", "\\3", "\\\\"])
        elif depth < 2 and roll < 7:
            out += r.choice(["2", "3", "0", "02", "10"]) + "[" + _repeat(r, depth + 1) + "]"
        else:
            out += r.choice(["[a]", "]", "2[", "\\"]) if r.random() < 0.3 else "c"
    return out


def _grid(r):
    rows, cols = r.randint(2, 5), r.randint(2, 6)
    cells = [[r.choice("....#") for _ in range(cols)] for _ in range(rows)]
    free = [(i, j) for i in range(rows) for j in range(cols)]
    r.shuffle(free)
    marks = ["S", "E"] + ["a", "a"] * r.randint(0, 1) + ["b", "b"] * r.randint(0, 1)
    if r.random() < 0.08:
        marks.append(r.choice(["c", "S", "?"]))
    for mark, (i, j) in zip(marks, free):
        cells[i][j] = mark
    return ["".join(row) for row in cells]


def _lru(r):
    ops, t = [], 0
    for _ in range(r.randint(1, 10)):
        t += r.choice([0, 1, 2, 5])
        key = r.choice(["k1", "k2", "k3"])
        if r.random() < 0.5:
            ops.append(["set", t, key, r.randint(0, 9), r.choice([1, 2, 3, 10, 0])])
        else:
            ops.append(["get", t, key])
    return [r.randint(0, 3), ops]


# ----------------------------------------------------------------------------
# Public specifications. Each entry: function, split, label, spec, two public
# examples (authored expected values, asserted against both references),
# hand-picked edge fixtures, seeded generator.
# ----------------------------------------------------------------------------

TASKS = [
 (repeating_expansion, "development", "exact-rational-expansion",
  "Inputs: integers num, den, base. Return the exact positional expansion of num/den in the given base as a string, or None if den == 0 or base is outside 2..36. "
  "Digits are 0-9 then lowercase a-z (a=10 ... z=35). Format: a '-' only when the value is negative (never '-0'), then the integer part in the base (at least one digit, no leading zeros), then, only if the fractional part is nonzero, a '.' followed by the non-repeating fractional digits and, if the expansion does not terminate, the repeating block in parentheses. "
  "The repeating block must be the shortest possible and must start as early as possible: 1/6 in base 10 is '0.1(6)', never '0.1(66)' or '0.16(6)'; 1/3 is '0.(3)'. Terminating expansions have no parentheses and no trailing zeros.",
  [([1, 6, 10], "0.1(6)"), ([-7, 2, 2], "-11.1")],
  [[0, 5, 10], [0, -3, 2], [5, 0, 10], [1, 3, 1], [1, 3, 37], [22, -7, 10], [-1, -7, 10], [255, 16, 16], [1, 36, 36], [100, 3, 36], [-50, 1, 2], [1, 97, 10]],
  lambda r: [r.randint(-400, 400), r.choice([0] + list(range(-40, 0)) + list(range(1, 80)) * 3), r.choice([2, 3, 7, 10, 10, 12, 16, 36, 1, 37])]),

 (wrap_hyphen, "development", "greedy-wrap-hyphen-rules",
  "Inputs: string text and integer width. Return None if width < 1. Words are maximal runs of characters other than the ASCII space ' ' (tabs and all other characters belong to words). Return the list of lines (no line has leading/trailing spaces; [] when there are no words). "
  "Keep a current line (initially empty) and process words in order: "
  "(1) If the word fits on the current line (its length, plus one separating space when the line is non-empty, keeps the line length <= width), append it. "
  "(2) Otherwise, consider the proper prefixes of the word that end with '-' and fit in the remaining room (same space rule). If any exists, append the longest one, end the line, and process the rest of the word as the next word. "
  "(3) Otherwise, if the current line is non-empty, end it and process the same word again on a new empty line. "
  "(4) Otherwise (empty line, no fitting hyphen prefix), output the first width characters of the word as a complete line and process the rest as the next word. "
  "After the last word, a non-empty current line is output.",
  [(["well-known state-of-the-art", 12], ["well-known", "state-of-", "the-art"]), (["abcdefgh", 3], ["abc", "def", "gh"])],
  [["", 5], ["   ", 1], ["a b", 0], ["a  b   c", 1], ["x- y", 2], ["co--op", 3], ["-abc", 2], ["a-b-c-d", 4], ["tab\tchar x", 4], ["hyphen- next", 7], ["aa bb-cc", 5], ["--- --", 2]],
  lambda r: [_words(r), r.choice([0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16])]),

 (semver_sort, "development", "precedence-validation-stability",
  "Input: list of strings. Keep only valid Semantic Versions and return them sorted ascending by precedence; versions of equal precedence keep their input order; duplicates are kept. "
  "Valid form: MAJOR.MINOR.PATCH, each a non-negative ASCII decimal integer with no leading zeros ('0' allowed); then optionally '-' and a pre-release; then optionally '+' and build metadata. "
  "Pre-release and build are each one or more dot-separated non-empty identifiers made only of ASCII letters, digits and '-'. A pre-release identifier made only of digits is numeric and must not have leading zeros; build identifiers may. "
  "Precedence: compare MAJOR, MINOR, PATCH numerically. If equal, a version with a pre-release is lower than one without. Two pre-releases compare identifier by identifier from the left: numeric identifiers compare numerically; alphanumeric identifiers compare by ASCII order; a numeric identifier is lower than an alphanumeric one; if all compared identifiers are equal, the shorter list is lower. Build metadata is ignored for precedence.",
  [([["1.0.0", "1.0.0-rc.1", "1.0.0-alpha", "0.9.12"]], ["0.9.12", "1.0.0-alpha", "1.0.0-rc.1", "1.0.0"]), ([["1.0.0+b", "01.0.0", "1.0.0+a"]], ["1.0.0+b", "1.0.0+a"])],
  [[[]], [["1.0.0-alpha.1", "1.0.0-alpha", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1"]],
   [["1.0.0-01", "1.0.0-0a", "1.0.0-0"]], [["1.0.0-", "1.0.0+", "1.0.0-a..b", "1.0"]], [["2.0.0", "10.0.0", "9.0.0"]],
   [["1.0.0-x-y", "1.0.0-x", "1.0.0--"]], [["1.0.0+001", "1.0.0-1+001"]], [["1.0.0-B", "1.0.0-a", "1.0.0-A1"]]],
  lambda r: [[_semver(r) for _ in range(r.randint(1, 7))]]),

 (stack_vm, "development", "interpreter-error-precedence",
  "Inputs: program (list of instruction strings) and integer max_steps >= 0. Run a stack machine with pc=0, empty stack, empty call stack, empty output. Return {\"status\":S,\"output\":[...],\"stack\":[bottom..top],\"steps\":N}. "
  "Loop: if pc == len(program), status 'ok'. Else if steps == max_steps, status 'step_limit'. Else steps += 1 and execute program[pc]; unless stated, pc += 1. "
  "Syntax: OPCODE or 'OPCODE OPERAND' separated by exactly one space; operand is an optional '-' then ASCII digits. PUSH, JMP, JZ, JNZ, CALL require an operand; all others forbid one. Unknown/malformed: status 'bad_instruction'. "
  "Ops (a = second from top, b = top): PUSH n; POP; DUP; SWAP; OVER (push a); ADD/SUB/MUL push a+b, a-b, a*b; DIV pushes a/b truncated toward zero; MOD pushes a-b*(a DIV b); PRINT pops into output; JMP t; JZ t / JNZ t pop the top and jump if it is zero / nonzero; CALL t pushes pc+1 onto the call stack and jumps; RET pops the call stack into pc; HALT: status 'ok'. "
  "Binary ops pop both operands. A jump target is valid if 0 <= t <= len(program); it is checked only when the jump is taken. "
  "Errors end the run with the stack unchanged by the failing instruction, checked in order: too few operands 'underflow'; zero divisor 'div_zero'; invalid taken target 'bad_jump'; RET with empty call stack 'ret_empty'.",
  [([["PUSH 7", "PUSH -2", "DIV", "PRINT"], 10], {"status": "ok", "output": [-3], "stack": [], "steps": 4}),
   ([["PUSH 1", "JMP 0"], 5], {"status": "step_limit", "output": [], "stack": [1, 1, 1], "steps": 5})],
  [[[], 0], [["PUSH 1"], 0], [["ADD"], 3], [["PUSH 1", "PUSH 0", "MOD"], 9], [["PUSH -7", "PUSH 2", "MOD", "PRINT"], 9],
   [["PUSH 0", "JNZ 99", "PUSH 2"], 9], [["PUSH 1", "JNZ 99"], 9], [["CALL 2", "HALT", "RET"], 9], [["JMP 1"], 3],
   [["PUSH 3", "PRINT", "HALT", "PRINT"], 9], [["PUSH 9", "PUSH 4", "OVER", "OVER", "SUB", "PRINT"], 9], [["PUSH -0", "PRINT"], 3]],
  lambda r: [_vm_program(r), r.choice([3, 10, 25, 60, 200])]),

 (cidr_merge, "development", "ipv4-cover-normalization",
  "Input: list of strings. A valid block is 'a.b.c.d/p': four decimal octets 0..255 and a prefix length 0..32, all ASCII digits without leading zeros ('0' allowed), no spaces. Invalid strings are ignored. "
  "Each valid block denotes the 2^(32-p) addresses of its network; host bits set in the address are cleared first (so '10.0.0.7/24' means 10.0.0.0/24). "
  "Return the minimal list of canonical CIDR blocks whose union is exactly the union of all valid blocks, sorted by network address ascending, each formatted 'a.b.c.d/p' with host bits zero. Return [] when there are no valid blocks. "
  "Adjacent or overlapping ranges must be combined whenever the result is still exactly the same set of addresses (for example 10.0.0.0/25 and 10.0.0.128/25 become 10.0.0.0/24, but 10.0.0.128/25 and 10.0.1.0/25 stay two blocks).",
  [([["10.0.0.0/25", "10.0.0.128/25", "10.0.2.9/24"]], ["10.0.0.0/24", "10.0.2.0/24"]), ([["10.0.0.128/25", "10.0.1.0/24", "1.2.3.4"]], ["10.0.0.128/25", "10.0.1.0/24"])],
  [[[]], [["0.0.0.0/0", "10.0.0.0/8"]], [["255.255.255.255/32"]], [["10.0.0.1/32", "10.0.0.2/32"]], [["10.0.0.0/32", "10.0.0.1/32", "10.0.0.2/31"]],
   [["01.0.0.0/8", "1.0.0.0/08", "1.0.0.0/8 "]], [["192.168.1.0/24", "192.168.0.0/23"]], [["10.0.0.1/31", "10.0.0.3/32", "10.0.0.4/30"]]],
  lambda r: [[_cidr(r) for _ in range(r.randint(1, 7))]]),

 (nth_distinct_permutation, "development", "combinatorial-unranking",
  "Inputs: string s (possibly with repeated characters) and integer n. Consider all distinct strings that are rearrangements of exactly the characters of s, sorted ascending by Unicode code point order (Python string comparison). Return the one at zero-based index n, or None if n < 0 or n is at least the number of distinct rearrangements. The empty string has exactly one rearrangement, ''. "
  "Inputs may have up to 20 characters, so enumerating all permutations is too slow; the function must finish quickly for any valid input.",
  [(["aab", 2], "baa"), (["cab", 6], None)],
  [["", 0], ["", 1], ["a", -1], ["zzzz", 0], ["zzzz", 1], ["abcdefghijklmnopqrst", 2432902008176639999], ["abcdefghijklmnopqrst", 2432902008176640000],
   ["aaaaaaaaaabbbbbbbbbb", 184755], ["aaaaaaaaaabbbbbbbbbb", 92378], ["Ba", 0], ["éea", 3], ["mississippi", 34649]],
  lambda r: _perm_case(r)),

 (glob_match, "development", "pattern-parser-classes",
  "Inputs: strings pattern and text. Return True if the whole text matches the pattern, False if not, or None if the pattern is invalid. Matching is case-sensitive over Unicode code points. "
  "Pattern elements: '?' matches any one character; '*' matches any sequence (including empty); a backslash makes the next character a literal (a trailing lone backslash is invalid); '[' starts a class; any other character matches itself. "
  "Class: after '[', an optional '!' negates the class. Then items are read until an unescaped ']' that is not the first item; a ']' as the first item is a literal. Each item is one character (a backslash escapes the next character) optionally followed by '-' and another such character, forming an inclusive code-point range, except that a '-' immediately followed by ']' is not a range operator (it becomes a literal item). A range whose start is greater than its end is invalid. A class with no closing ']' is invalid. A class matches one character that is in (or, if negated, not in) any item.",
  [(["a[!b-d]?*\\*", "aex*"], True), (["[]a]*", "b"], False)],
  [["", ""], ["", "a"], ["*", ""], ["\\", "a"], ["[", "["], ["[]", "]"], ["[!]]", "a"], ["[!]]", "]"], ["[a-]", "-"], ["[-a]", "b"],
   ["[c-a]", "b"], ["[\\]]", "]"], ["a*b*c", "abxbc"], ["[!", "x"], ["**?", ""], ["[a\\-z]", "b"]],
  lambda r: _glob_pair(r)),

 (add_business_days, "development", "calendar-business-days",
  "Inputs: date string, integer n, list of holiday strings. Dates use 'YYYY-MM-DD' with exactly 4+2+2 ASCII digits and must be real Gregorian dates in years 0001..9999. "
  "Business days are Monday-Friday that are not holidays. Invalid holiday strings are ignored. If date is invalid return None. "
  "If n > 0, move forward one calendar day at a time, counting business days, and return the date of the n-th business day strictly after date. If n < 0, do the same backwards for |n| business days strictly before date. If n == 0, return date itself if it is a business day, otherwise the first business day after it. "
  "The start date need not be a business day. Return the result as 'YYYY-MM-DD', or None if the walk would leave years 0001..9999.",
  [(["2026-11-13", 1, ["2026-11-16"]], "2026-11-17"), (["2026-11-15", 0, []], "2026-11-16")],
  [["2026-02-29", 1, []], ["2028-02-28", 1, []], ["2026-11-16", -1, ["2026-11-13", "bogus", "2026-13-01"]], ["9999-12-31", 1, []], ["0001-01-01", -1, []],
   ["2026-1-01", 0, []], ["2024-12-31", 5, ["2025-01-01", "2025-01-02"]], ["2026-11-14", -1, []], ["2026-11-14", 0, ["2026-11-16", "2026-11-17"]], ["2026-11-16", 0, ["2026-11-16"]]],
  lambda r: [_date(r), r.randint(-25, 25), [_date(r, 2024, 2026) for _ in range(r.randint(0, 6))] + r.sample(["2026-02-30", "x", "2025-12-25"], r.randint(0, 1))]),

 (rational_eval, "evaluation", "parser-exact-rationals",
  "Input: string expr. Evaluate it exactly over rational numbers and return the result as a string: 'p' for an integer, else 'p/q' in lowest terms with q > 1 and the sign on p. Return 'error' for any invalid input or failed operation. "
  "Tokens: ASCII integer literals (digit runs, leading zeros allowed), + - * / ^ ( ); spaces and tabs separate tokens and are otherwise ignored (so '2 3' is two integers, an error); any other character is an error. "
  "Grammar (lowest to highest precedence): expr := term (('+'|'-') term)*; term := unary (('*'|'/') unary)*; unary := '-' unary | power; power := atom ['^' unary]; atom := integer | '(' expr ')'. "
  "So + - * / are left-associative, unary minus binds looser than '^' (-2^2 = -4), '^' is right-associative (2^3^2 = 2^9) and its exponent may be negated (2^-1 = 1/2). There is no unary plus and no implicit multiplication; leftover tokens are an error. "
  "Errors: division by zero; an exponent that is not an integer or whose absolute value exceeds 64; zero raised to a negative power. 0^0 is 1. Any error anywhere makes the whole result 'error'.",
  [(["1/3 + 1/6"], "1/2"), (["-2^2"], "-4")],
  [[""], ["  "], ["2^3^2"], ["2^-2"], ["(1/2)^-3"], ["0^0"], ["0^-1"], ["4^(1/2)"], ["2^65"], ["2^-64"], ["1/(3-3)"], ["--3"], ["+3"], ["2(3)"], ["2 3"],
   ["007/014"], ["-(1/2)^2"], ["1-2-3"], ["8/4/2"], ["(1"], ["1)"], ["1.5"], ["2^2^-1"], ["3*-2"]],
  lambda r: [_arith(r)]),

 (shell_words, "evaluation", "tokenizer-quoting-expansion",
  "Inputs: string line and dict env (string to string). Split line into words like a small POSIX-style shell and return the list of words, or None on error. "
  "Separators are unquoted, unescaped runs of space or tab. Outside quotes, a backslash makes the next character literal (the backslash is removed); a backslash at the end of line is an error. "
  "Single quotes: everything up to the next single quote is literal. Double quotes: characters are literal except that backslash followed by one of \" \\ $ produces that character, any other backslash is kept literally, and $-expansion happens. Unterminated quotes are errors. Adjacent quoted and unquoted parts join into one word. "
  "Expansion (outside single quotes): '$NAME' uses the longest NAME matching [A-Za-z_][A-Za-z0-9_]*; '${NAME}' uses the text up to the first '}', which must be a valid NAME, otherwise (or if there is no '}') it is an error. The value is env[NAME], or '' if missing, inserted literally (no further splitting, quoting or expansion). A '$' not followed by '{' or a name-start character is literal. "
  "A word is kept if its text is non-empty or it contained at least one quoted section; so an unquoted expansion that yields '' alone does not create a word, but '' or \"\" does.",
  [(["a \"b $X\" c\\ d", {"X": "1 2"}], ["a", "b 1 2", "c d"]), (["$Z '' x${Y}y", {"Y": "-"}], ["", "x-y"])],
  [["", {}], [" \t ", {}], ["a\\", {}], ["'abc", {}], ["\"abc", {}], ["${X", {"X": "1"}], ["${1}", {}], ["$1 $ x$", {}], ["\"a\\b\\\"c\"", {}],
   ["'$X'\"$X\"$X", {"X": "v"}], ["$X_1$X", {"X": "a", "X_1": "b"}], ["\"\\\\\"", {}], ["a\"\"b", {}], ["$E$E", {"E": ""}], ["\\'x", {}], ["${}", {}]],
  lambda r: [_shell_line(r), r.choice([{}, {"X": "1 2"}, {"X": "", "Y": "$X"}, {"Y": "'q'"}, {"X_1": "u"}])]),

 (cron_next, "evaluation", "calendar-cron-semantics",
  "Inputs: strings expr and start. Return the earliest minute strictly after start that matches the cron expression, formatted 'YYYY-MM-DD HH:MM', or None. "
  "expr has exactly five fields separated by single spaces: minute 0-59, hour 0-23, day-of-month 1-31, month 1-12, day-of-week 0-6 (0 = Sunday). A field is a comma-separated list of items; each item is '*', 'N' or 'N-M' (N <= M), optionally followed by '/S' with S >= 1. Numbers are ASCII digits (leading zeros allowed); N and M must lie within the field range, S need not. '*' means the full range; '/S' keeps every S-th value of the range starting at its first value; 'N/S' means N through the field maximum with step S. "
  "Day rule: a field is restricted unless its text is exactly '*'. If both day-of-month and day-of-week are restricted, a day matches when either matches; otherwise both must match. Months must always match. "
  "start is 'YYYY-MM-DD HH:MM' (zero-padded, real date, valid time). Return None for an invalid expr or start, or if no matching minute exists before 00:00 on January 1 of (start year + 5) or before year 10000.",
  [(["30 9 * * 1-5", "2026-11-13 09:30"], "2026-11-16 09:30"), (["0 0 29 2 *", "2026-03-01 00:00"], "2028-02-29 00:00")],
  [["0 0 30 2 *", "2026-01-01 00:00"], ["* * * * *", "2026-12-31 23:59"], ["0 0 13 * 5", "2026-11-13 00:00"], ["0 0 13 * */1", "2026-11-13 00:00"],
   ["5-10/3 * * * *", "2026-01-01 00:07"], ["0 12 * * 0", "2026-11-16 12:00"], ["0 0 1 1 *", "9999-06-01 00:00"], ["60 * * * *", "2026-01-01 00:00"],
   ["*/0 * * * *", "2026-01-01 00:00"], ["5-1 * * * *", "2026-01-01 00:00"], ["* * * *", "2026-01-01 00:00"], ["0  0 * * *", "2026-01-01 00:00"],
   ["0 0 31 4,6 *", "2026-01-01 00:00"], ["00 07 * * *", "2026-02-28 07:00"], ["0 0 * * *", "2026-02-29 00:00"], ["59 23 31 12 *", "2026-12-31 23:58"],
   ["0 0 29 2 1", "2027-01-01 00:00"], ["10/20 0 1 * *", "2026-05-01 00:10"], ["*/60 */30 * * */9", "2026-01-01 00:00"]],
  lambda r: [_cron(r), "%s %02d:%02d" % (_date(r, 2025, 2028), r.randint(0, 23), r.choice([0, 15, 59, r.randint(0, 59)]))]),

 (date_diff_ymd, "evaluation", "calendar-month-end-clamping",
  "Inputs: date strings a and b, each 'YYYY-MM-DD' (exactly 4+2+2 ASCII digits, a real Gregorian date in years 0001..9999); if either is invalid return None. Return [years, months, days] from a to b. "
  "Define shift(d, k) as d moved forward by k calendar months, keeping its day-of-month but clamping it to the last day of the target month (Jan 31 shifted by 1 month is Feb 28 or Feb 29). "
  "If a <= b: let T be the largest integer k >= 0 with shift(a, k) <= b; then years = T // 12, months = T % 12, and days = number of days from shift(a, T) to b. Note that T is computed from a, not built up year by year or month by month. "
  "If a > b: return the component-wise negation of the result for (b, a).",
  [(["2026-01-31", "2026-03-01"], [0, 1, 1]), (["2024-02-29", "2025-02-28"], [1, 0, 0])],
  [["2026-01-30", "2026-03-01"], ["2026-03-01", "2026-01-30"], ["2026-05-05", "2026-05-05"], ["2026-02-30", "2026-03-01"], ["2026-3-01", "2026-03-01"],
   ["2023-01-31", "2024-02-29"], ["2024-03-31", "2024-04-30"], ["0001-01-01", "9999-12-31"], ["2026-12-31", "2027-02-28"], ["2026-12-31", "2027-03-30"], ["2027-03-30", "2026-12-31"], ["2020-02-29", "2021-02-28"]],
  lambda r: [_date(r, 2020, 2030), _date(r, 2020, 2030)]),

 (monthly_occurrences, "evaluation", "calendar-recurrence-rules",
  "Inputs: start date string, rule string, integer count. Return the first count dates on or after start (ascending, 'YYYY-MM-DD') that satisfy rule, examining months in order beginning with start's month. Dates use exactly 4+2+2 ASCII digits and must be real Gregorian dates. "
  "Rules: 'day:N' with N in 1..31 is day N of each month; 'day:-N' with N in 1..31 is the N-th day counting back from the month's end ('day:-1' is the last day). 'nth:K:WD' with K in 1..5 is the K-th WD of the month; 'nth:-K:WD' is the K-th WD counting back from the end ('nth:-1:fri' is the last Friday). WD is one of mon tue wed thu fri sat sun (lowercase). Numbers have no leading zeros and no '+'. "
  "Months where the rule's day does not exist are skipped (never clamped). Return None if start or rule is invalid (checked before count). If count <= 0 return []. Dates after 9999-12-31 do not exist; stop there and return what was found.",
  [(["2026-01-31", "day:31", 3], ["2026-01-31", "2026-03-31", "2026-05-31"]), (["2026-11-16", "nth:-1:fri", 2], ["2026-11-27", "2026-12-25"])],
  [["2026-02-01", "day:-29", 2], ["2026-01-01", "nth:5:mon", 3], ["2026-01-01", "day:0", 1], ["2026-01-01", "day:01", 1], ["2026-01-01", "day:32", 1],
   ["2026-01-01", "nth:6:mon", 1], ["2026-01-01", "nth:1:Mon", 1], ["2026-01-01", "day:5", 0], ["2026-02-30", "day:5", 1], ["2026-01-01", "day:-0", 1],
   ["9999-11-01", "day:31", 5], ["2024-01-01", "day:-31", 4], ["2026-11-27", "nth:-1:fri", 1], ["2026-11-28", "nth:-1:fri", 1]],
  lambda r: [_date(r, 2024, 2027), r.choice(["day:%d" % r.randint(1, 31), "day:-%d" % r.randint(1, 31), "nth:%d:%s" % (r.randint(1, 5), r.choice(["mon", "fri", "sun"])),
                                              "nth:-%d:%s" % (r.randint(1, 5), r.choice(["tue", "sat"])), "day:-%d" % r.randint(28, 31), r.choice(["nth:0:mon", "day:+3"]) if r.random() < 0.2 else "day:29"]), r.randint(-1, 6)]),

 (schedule_jobs, "evaluation", "event-simulation-tiebreaks",
  "Inputs: jobs, a list of [id, release, duration, priority] (id: unique string; release >= 0, duration >= 1, priority: integers), and integer workers. Return None if workers < 1. "
  "Simulate non-preemptive scheduling on identical workers numbered 0..workers-1, starting at time 0 with all workers idle. A worker running a job from time s with duration d is busy during [s, s+d) and idle again at time s+d. "
  "At every time t at which some worker is idle and some released (release <= t), not-yet-started job is waiting, start jobs one at a time: choose the waiting job with the highest priority, breaking ties by earlier release, then by smaller id (Python string order); assign it to the lowest-numbered idle worker; repeat while both an idle worker and a waiting job remain. Time then advances to the next moment when a worker becomes idle or a job is released. "
  "Return [[id, worker, start, end], ...] for every job, sorted by start, then by worker. Empty jobs returns [].",
  [([[["a", 0, 3, 1], ["b", 0, 2, 5], ["c", 1, 1, 9]], 1], [["b", 0, 0, 2], ["c", 0, 2, 3], ["a", 0, 3, 6]]),
   ([[["x", 2, 1, 0], ["y", 2, 1, 0]], 3], [["x", 0, 2, 3], ["y", 1, 2, 3]])],
  [[[], 2], [[["a", 0, 1, 0]], 0], [[["b", 5, 1, 0], ["a", 5, 1, 0]], 1], [[["a", 0, 4, 0], ["b", 4, 1, 9], ["c", 0, 4, 0]], 2],
   [[["late", 10, 2, 1], ["early", 0, 1, 1]], 2], [[["p", 3, 1, 2], ["q", 1, 1, 2], ["r", 0, 5, 2]], 1], [[["B", 0, 1, 0], ["a", 0, 1, 0]], 1], [[["a", 0, 2, -1], ["b", 0, 2, -5], ["c", 0, 2, 0]], 2]],
  lambda r: [[["j%d" % i, r.randint(0, 6), r.randint(1, 4), r.randint(0, 2)] for i in r.sample(range(10), r.randint(1, 7))], r.choice([1, 1, 2, 2, 3, 0])]),

 (lex_shortest_path, "evaluation", "graph-shortest-lexicographic",
  "Inputs: edges, a list of [u, v, w] (directed edge from string u to string v with integer weight w; parallel edges allowed), and strings src and dst. "
  "If any w < 1 return None. If src == dst return [0, [src]] (even if src appears in no edge). Otherwise, if dst is unreachable from src return None. "
  "Otherwise return [cost, path] where cost is the minimum total weight of a path from src to dst and path is the node list (starting with src, ending with dst) that is lexicographically smallest, comparing node names element by element with Python string order, among all paths of that minimum cost.",
  [([[["s", "b", 1], ["s", "a", 2], ["a", "t", 1], ["b", "t", 2]], "s", "t"], [3, ["s", "a", "t"]]), ([[["a", "b", 1]], "b", "a"], None)],
  [[[], "x", "x"], [[], "x", "y"], [[["a", "b", 0]], "a", "b"], [[["a", "b", 0]], "a", "a"], [[["a", "b", 5], ["a", "b", 2]], "a", "b"],
   [[["a", "c", 1], ["c", "d", 1], ["a", "b", 1], ["b", "d", 1], ["a", "d", 2]], "a", "d"], [[["a", "B", 1], ["a", "b", 1], ["b", "z", 1], ["B", "z", 1]], "a", "z"],
   [[["s", "x", 1], ["x", "s", 1], ["x", "t", 5], ["s", "t", 6]], "s", "t"], [[["ab", "t", 1], ["s", "ab", 1], ["s", "b", 1], ["b", "t", 1]], "s", "t"]],
  lambda r: _graph(r)),

 (stable_topo, "evaluation", "topological-order-cycles",
  "Inputs: names (list of strings; only the first occurrence of a repeated name counts) and deps (list of [a, b] pairs meaning a must come before b). Pairs naming a node absent from names are ignored; duplicate pairs are harmless; [a, a] is a self-dependency. "
  "Build the order by repeatedly outputting, among the nodes not yet output whose predecessors have all been output, the one that appears earliest in names. Stop when no node can be output. "
  "Every remaining node is classified: it is 'cyclic' if it lies on a directed cycle (including a self-dependency), otherwise 'blocked' (it waits on a cyclic node directly or indirectly). "
  "Return {\"order\": [...], \"cyclic\": [...], \"blocked\": [...]}, where cyclic and blocked list the nodes in names order.",
  [([["c", "a", "b"], [["a", "c"], ["b", "c"]]], {"order": ["a", "b", "c"], "cyclic": [], "blocked": []}),
   ([["a", "b", "c", "d"], [["a", "b"], ["b", "a"], ["b", "c"], ["x", "d"]]], {"order": ["d"], "cyclic": ["a", "b"], "blocked": ["c"]})],
  [[[], []], [["a", "a"], [["a", "a"]]], [["a", "b"], [["a", "b"], ["a", "b"]]], [["d", "c", "b", "a"], [["a", "b"], ["c", "d"]]],
   [["a", "b", "c", "d", "e"], [["b", "c"], ["c", "d"], ["d", "b"], ["a", "e"], ["e", "a"], ["d", "x"]]], [["x", "y", "z"], [["z", "y"], ["y", "y"]]],
   [["p", "q", "r", "s"], [["s", "p"], ["q", "p"], ["r", "q"]]]],
  lambda r: (lambda ns: [ns + r.sample(ns, r.randint(0, 1)), [[r.choice(ns + ["zz"]), r.choice(ns)] for _ in range(r.randint(0, 7))]])(r.sample(list("abcdefg"), r.randint(1, 6)))),

 (order_book, "evaluation", "matching-engine-priorities",
  "Input: ops, a list processed in order; the time of an op is its index. Ops: ['limit', id, side, price, qty], ['market', id, side, qty], ['cancel', id]; side is 'buy' or 'sell'; price, qty integers. "
  "An op is ignored entirely if its kind is unknown or its length is wrong, side is not 'buy'/'sell', qty < 1, a limit price < 1, or (limit/market) its id was used by an earlier non-ignored limit or market op. "
  "Matching: an incoming buy repeatedly trades with the resting sell having the lowest price, ties by earliest time; an incoming sell with the resting buy having the highest price, ties by earliest time. A limit order only trades while the resting price is acceptable (sell price <= buy limit, or buy price >= sell limit); a market order accepts any price. Each trade is at the resting order's price for min(remaining quantities) units and is recorded as [buy_id, sell_id, price, qty]. "
  "Leftover quantity of a limit order rests in the book with its arrival time (partial fills keep the original time); leftover market quantity is discarded. 'cancel' removes the resting order with that id, if any (otherwise nothing happens). "
  "Return {\"trades\": [...], \"bids\": [[id, price, qty], ...] sorted by price descending then time, \"asks\": [[id, price, qty], ...] sorted by price ascending then time}.",
  [([[["limit", "s1", "sell", 10, 5], ["limit", "s2", "sell", 9, 2], ["limit", "b1", "buy", 10, 4]]], {"trades": [["b1", "s2", 9, 2], ["b1", "s1", 10, 2]], "bids": [], "asks": [["s1", 10, 3]]}),
   ([[["limit", "b1", "buy", 5, 1], ["market", "m", "sell", 3], ["cancel", "b1"]]], {"trades": [["b1", "m", 5, 1]], "bids": [], "asks": []})],
  [[[]], [[["limit", "a", "buy", 5, 1], ["limit", "a", "buy", 6, 1]]], [[["limit", "a", "buy", 5, 2], ["cancel", "a"], ["limit", "a", "sell", 5, 1]]],
   [[["limit", "a", "buy", 5, 1], ["limit", "b", "buy", 5, 1], ["limit", "c", "buy", 6, 1], ["market", "m", "sell", 2]]], [[["market", "m", "buy", 0], ["market", "m", "buy", 1], ["limit", "m", "sell", 1, 1]]],
   [[["limit", "a", "sell", 7, 1], ["limit", "b", "buy", 6, 1], ["cancel", "zz"], ["limit", "c", "buy", 0, 1], ["limit", "d", "hold", 7, 1], ["foo"]]], [[["limit", "a", "sell", 5, 3], ["limit", "b", "buy", 9, 1], ["limit", "c", "buy", 9, 9]]]],
  lambda r: [_orders(r)]),

 (ledger, "evaluation", "rule-precedence-simulation",
  "Inputs: accounts, a list of [name, balance, overdraft] (unique names, integers, overdraft >= 0), and ops processed in order. Ops: ['dep', a, amt], ['wd', a, amt], ['xfer', from, to, amt], ['freeze', a], ['thaw', a], ['day']. All accounts start unfrozen. "
  "Each op is either applied or rejected with a reason; the first failing check, in this order, decides: unknown kind or wrong length 'bad_op'; any named account unknown 'no_account'; xfer with from == to 'same_account'; amt < 1 'bad_amount'; wd or xfer from a frozen account 'frozen'; insufficient funds 'insufficient'. "
  "'freeze'/'thaw' set/clear the frozen flag (repeating is not an error). 'day' resets every account's withdrawal count to zero. 'dep' adds amt (frozen accounts may receive deposits and transfers). "
  "'wd' costs amt plus a fee: 0 if the account has fewer than 3 successful withdrawals since the last 'day' (or start), else 2. 'xfer' costs amt plus a fee of 1 to the sender and adds amt to the receiver; it does not count as a withdrawal. A cost is allowed only if balance - cost >= -overdraft; otherwise 'insufficient' and nothing changes. "
  "Return {\"balances\": [[name, balance], ...] sorted by name, \"rejected\": [[op_index, reason], ...] in op order}.",
  [([[["ann", 10, 0], ["bob", 0, 5]], [["xfer", "ann", "bob", 9], ["wd", "bob", 14], ["wd", "bob", 1], ["dep", "zed", 1]]], {"balances": [["ann", 0], ["bob", -5]], "rejected": [[2, "insufficient"], [3, "no_account"]]}),
   ([[["a", 20, 0]], [["wd", "a", 1], ["wd", "a", 1], ["wd", "a", 1], ["wd", "a", 1], ["day"], ["wd", "a", 1]]], {"balances": [["a", 13]], "rejected": []})],
  [[[], []], [[["a", 5, 0]], [["xfer", "a", "a", 0]]], [[["a", 5, 0]], [["xfer", "a", "zz", -1]]], [[["a", 5, 0]], [["freeze", "a"], ["wd", "a", 0], ["wd", "a", 1], ["dep", "a", 1], ["thaw", "a"], ["thaw", "a"], ["wd", "a", 6]]],
   [[["a", 4, 0], ["b", 0, 0]], [["xfer", "a", "b", 4], ["xfer", "a", "b", 3]]], [[["a", 9, 0]], [["wd", "a", 1], ["wd", "a", 2], ["wd", "a", 99], ["wd", "a", 1], ["wd", "a", 3]]], [[["a", 1, 0]], [["day", "x"], ["wd"], ["wd", "a", 1, 2], ["noop", "a", 1]]]],
  lambda r: _ledger(r)),

 (spreadsheet_eval, "evaluation", "formula-graph-errors",
  "Input: dict cells mapping names like 'B7' (one uppercase letter A-Z, row 1..99) to raw strings. Return a dict with the same keys mapping each cell to an int or an error string. "
  "A raw string not starting with '=' is an integer literal (optional '-', ASCII digits) giving that int; anything else (including '') is '#VALUE'. A raw string starting with '=' is a formula; if it does not parse it is '#SYNTAX'. "
  "Formula grammar (spaces separate tokens and are otherwise ignored; a space inside a number, a reference or the 'SUM(' token splits it, so 'SUM (' is invalid): expr := term (('+'|'-') term)*; term := unary ('*' unary)*; unary := '-' unary | primary; primary := integer | REF | 'SUM(' REF ':' REF ')' | '(' expr ')'. REF is one uppercase letter followed by a row 1..99 without leading zeros. SUM adds every cell of the rectangle spanned by the two corners (in any corner order). Referenced cells absent from the input are 0. "
  "A formula cell that can reach itself through references (including via SUM ranges) is '#CYCLE'. Every other formula cell: list its references in textual order, expanding each SUM range row by row (top row first, left to right); if any referenced cell's value is an error, the result is the first such error; otherwise compute the integer value.",
  [([{"A1": "=B1+SUM(A2:B2)", "B1": "2", "A2": "3"}], {"A1": 5, "B1": 2, "A2": 3}), ([{"A1": "=B1", "B1": "=A1", "C1": "=x+C2*0+A1", "C2": "=1+"}], {"A1": "#CYCLE", "B1": "#CYCLE", "C1": "#SYNTAX", "C2": "#SYNTAX"})],
  [[{}], [{"A1": "=A1"}], [{"A1": "=SUM(A1:A1)"}], [{"A1": "=C2+B1", "B1": "x", "C2": "=1+"}], [{"A1": "=SUM(B2:A1)", "A2": "1", "B1": "10", "B2": "100"}],
   [{"A1": "=-(2-5)*-3", "B1": ""}], [{"A1": "= 1 + 2", "B1": "=A01"}], [{"A1": "=B1", "B1": "=C1", "C1": "=B1"}], [{"Z99": "=Z98+1", "Z98": "-4"}],
   [{"A1": "=SUM(A2:A3)", "A2": "=A1", "A3": "1"}], [{"A1": "=2--3", "B1": "=1 2"}], [{"A1": "=SUM (A2:A2)", "B1": "=SUM( A2 : A2 )", "A2": "4"}], [{"A1": "=B1*B1", "B1": "=SUM(C1:C2)", "C1": "#"}]],
  lambda r: _sheet(r)),

 (poly_expand, "evaluation", "polynomial-parse-format",
  "Input: string expr, a polynomial in the single variable x. Return its fully expanded canonical form as a string, or None if expr is invalid. "
  "Tokens: ASCII integer literals (leading zeros allowed), 'x', + - * ^ ( ); spaces separate tokens and are otherwise ignored (so '1 2' is two integers, which is invalid); anything else is invalid. Grammar: expr := term (('+'|'-') term)*; term := factor ('*' factor)*; factor := '-' factor | base ['^' integer]; base := integer | 'x' | '(' expr ')'. "
  "Multiplication must be written with '*'. The exponent is a non-negative integer literal at most 20 (larger is invalid); it applies to the base only, so -x^2 means -(x^2); exponents do not chain. Anything raised to 0 is 1. "
  "Output: nonzero terms in descending degree, no spaces. A term with coefficient c and degree d is written as: for d = 0, |c|; for d >= 1, |c| omitted when |c| = 1, then 'x', then '^d' when d > 1. The first term is preceded by '-' if negative; later terms are joined with '+' or '-' according to their sign. The zero polynomial is '0'.",
  [(["(x-1)^3"], "x^3-3x^2+3x-1"), (["-x^2 + 2*x*x - 1*0"], "x^2")],
  [[""], ["x"], ["-x"], ["--x"], ["0*x"], ["x^0"], ["0^0"], ["(x+1)^21"], ["x^2^2"], ["2x"], ["(x+1)^20-(x+1)^20"], ["x-x+7"], ["(2*x-3)*(2*x+3)"], ["-(x^2)*-1"], ["x^ 2"], ["(x"], ["1-x^3"], ["007*x^01"]],
  lambda r: [_poly(r)]),

 (bool_minterms, "evaluation", "logic-parser-truth-table",
  "Input: string expr, a Boolean formula. Return [variables, minterms] or None if expr is invalid. "
  "Tokens: variables are maximal runs of lowercase ASCII letters a-z; constants are exactly '0' and '1' (any other digit run is invalid); operators '!', '&', '^', '|', '->'; parentheses; spaces separate tokens and are otherwise ignored ('- >' is not an operator); anything else is invalid. "
  "Precedence from highest to lowest: '!' (prefix, may repeat), '&', '^' (exclusive or), '|', '->' (implication). '&', '^', '|' are left-associative; '->' is right-associative (a->b->c is a->(b->c)). "
  "variables is the sorted list of distinct variable names. For each assignment, form the index whose binary digits are the variable values in that sorted order, the first variable being the most significant bit (true = 1). minterms is the ascending list of indices for which expr is true. With no variables the only index is 0, so the result is [[], [0]] or [[], []].",
  [(["a -> b"], [["a", "b"], [0, 1, 3]]), (["!b & c | 0"], [["b", "c"], [1]])],
  [["1"], ["0"], [""], ["a"], ["a->b->c"], ["(a->b)->c"], ["a ^ b ^ c"], ["!!x"], ["10"], ["a & | b"], ["A"], ["ab & a"], ["a | b & c"], ["a -> (b"], ["a - > b"], ["!(p^q)&1"]],
  lambda r: [_bool(r)]),

 (csv_parse, "evaluation", "stateful-tokenizer",
  "Input: string text. Parse it as CSV and return a list of records (each a list of field strings), or None if invalid. "
  "Records end at a terminator: '\\n' or '\\r\\n'. A '\\r' not followed by '\\n' is ordinary data. Fields are separated by ','. "
  "A field that begins with '\"' is quoted: it continues until a '\"' that is not part of a doubled '\"\"'; inside, '\"\"' stands for one '\"' and commas, '\\r' and '\\n' are data. Right after the closing quote there must be a ',', a terminator or the end of text; anything else is invalid. A quoted field without a closing quote is invalid. "
  "An unquoted field runs until the next ',' or terminator or end of text; it must not contain '\"' (invalid otherwise). "
  "The empty text returns []. A terminator at the very end of text does not start another record. Every other position starts a record, so an empty line is the record [\"\"] and a trailing ',' produces a final empty field.",
  [(["a,\"b,\"\"c\"\"\"\r\n,x\n"], [["a", "b,\"c\""], ["", "x"]]), (["a\"b"], None)],
  [[""], ["\n"], ["\r\n\r\n"], ["\r"], [","], ["a,"], ["\"\""], ["\"a\"b"], ["\"a"], ["a\n\nb"], ["\"x\"\r"], ["\"multi\nline\",2"], ["a\r\nb\r"], ["\"\"\"\"\n"]],
  lambda r: [_csv(r)]),

 (league_table, "evaluation", "multi-key-ranking-h2h",
  "Input: matches, a list of [home, away, home_goals, away_goals] (team names are strings; goals integers). A match is invalid and ignored if home == away or either goal count is negative. Only teams in valid matches appear. "
  "Win = 3 points, draw = 1, loss = 0. Rank teams by: (1) points, descending; (2) head-to-head points, descending; (3) head-to-head goal difference, descending; (4) overall goal difference, descending; (5) overall goals scored, descending; (6) name ascending (Python string order). "
  "Head-to-head values for a team are computed only from valid matches in which both teams belong to the group of all teams having exactly the same points as that team (computed once for the whole group, not re-applied to subgroups). "
  "Return rows [name, played, won, drawn, lost, goals_for, goals_against, points] in ranked order.",
  [([[["A", "B", 1, 0], ["B", "C", 1, 0], ["C", "A", 1, 0]]], [["A", 2, 1, 0, 1, 1, 1, 3], ["B", 2, 1, 0, 1, 1, 1, 3], ["C", 2, 1, 0, 1, 1, 1, 3]]),
   ([[["X", "Y", 3, 3], ["Y", "X", -1, 0], ["Z", "Z", 9, 0]]], [["X", 1, 0, 1, 0, 3, 3, 1], ["Y", 1, 0, 1, 0, 3, 3, 1]])],
  [[[]], [[["A", "A", 1, 1]]], [[["A", "B", 0, 0]]], [[["A", "B", 2, 0], ["C", "D", 5, 0], ["A", "C", 0, 1], ["B", "D", 1, 0]]],
   [[["P", "Q", 1, 0], ["Q", "R", 4, 0], ["R", "P", 1, 0], ["S", "P", 0, 9]]], [[["b", "B", 1, 1], ["a", "c", 0, 0]]], [[["A", "B", 1, 0], ["B", "A", 2, 0], ["A", "C", 3, 0], ["B", "C", 1, 0]]]],
  lambda r: [_matches(r)]),

 (canonical_huffman, "evaluation", "deterministic-huffman",
  "Input: freqs, a list of [symbol, weight] (symbol: non-empty string, weight: integer). Entries with weight <= 0 are dropped first; then weights of repeated symbols are summed. Return [] if no symbol remains. "
  "Code lengths: with exactly one symbol its length is 1. Otherwise start with one node per symbol, whose key is the symbol itself. Repeatedly remove the two nodes that are smallest by (weight, key) - first the smallest, then the next smallest - and replace them by one node whose weight is their sum and whose key is the smaller of their two keys (Python string order). Stop when one node remains. A symbol's code length is the number of merges its node took part in (its depth in the tree). "
  "Canonical codes: order symbols by (length, symbol). The first symbol gets the code of all zeros with its length. Each next symbol gets (previous code + 1) shifted left by (its length - previous length). "
  "Return [[symbol, code_bits_string], ...] in that canonical order, codes written in binary with exactly length digits.",
  [([[["a", 5], ["b", 2], ["c", 1], ["d", 1]]], [["a", "0"], ["b", "10"], ["c", "110"], ["d", "111"]]), ([[["z", 3], ["z", 4], ["q", 0]]], [["z", "0"]])],
  [[[]], [[["a", -1]]], [[["a", 1], ["b", 1]]], [[["a", 1], ["b", 1], ["c", 1], ["d", 1], ["e", 1]]], [[["e", 1], ["d", 1], ["c", 1], ["b", 1], ["a", 1]]],
   [[["x", 1], ["y", 1], ["z", 2]]], [[["aa", 2], ["b", 1], ["a", 1], ["B", 1]]], [[["a", 1], ["b", 2], ["c", 4], ["d", 8], ["e", 16], ["f", 32]]], [[["a", 5], ["a", -3], ["b", 2], ["c", 2]]]],
  lambda r: [_freqs(r)]),

 (token_bucket, "evaluation", "rate-limit-exact-accrual",
  "Inputs: integers capacity and refill_ms, and requests, a list of [t, cost] (integers, t in milliseconds). Return None if capacity < 1 or refill_ms < 1. Otherwise return the ascending list of indices of accepted requests. "
  "State: an integer token count (initially capacity) and an integer accrual mark (initially 0). A request is invalid, and skipped without changing anything, if cost < 1, t < 0, or t is earlier than the time of the previous valid request. "
  "For each valid request at time t, in order: (1) if tokens < capacity, let g = floor((t - mark) / refill_ms); if tokens + g >= capacity, set tokens = capacity; otherwise add g to tokens and advance mark by g * refill_ms. (2) Then, if tokens == capacity (whether it was already full or just became full), set mark = t; partial progress is discarded while full. (3) If cost <= tokens, accept the request and subtract cost; otherwise reject it and change nothing more.",
  [([2, 10, [[0, 1], [1, 1], [2, 1], [15, 1], [19, 1]]], [0, 1, 3]), ([1, 5, [[3, 2], [4, 1], [2, 1], [9, 1]]], [1, 3])],
  [[0, 5, []], [1, 0, []], [1, 1, []], [3, 10, [[5, 3], [14, 1], [15, 1], [15, 1], [16, 1]]], [2, 4, [[0, 2], [3, 1], [4, 1], [7, 1], [8, 1]]],
   [1, 10, [[-1, 1], [0, 0], [100, 1]]], [5, 3, [[10, 5], [12, 1], [13, 1], [13, 1], [100, 9]]], [2, 7, [[0, 1], [6, 1], [7, 1], [13, 1], [14, 1], [20, 2]]]],
  lambda r: _bucket(r)),

 (json_select, "evaluation", "path-language-traversal",
  "Inputs: doc (any JSON value) and string path. Return the list of selected values in order, or None if path is invalid. "
  "path starts with '$' (the whole doc) followed by zero or more steps, with no spaces: '.name' where name matches [A-Za-z_][A-Za-z0-9_]*; \"['text']\" selecting key text, where inside the quotes \\' means ' and \\\\ means \\, any other backslash is invalid and the closing quote must be followed by ']'; '[N]' with N an optional '-' and ASCII digits without leading zeros (negative counts from the end); '[*]' selecting all array elements in order or all object values in the object's own key (insertion) order, not sorted; '..name' (recursive descent). "
  "Each step maps every current value, in order, to zero or more values; the results are concatenated. Key steps select from objects that contain the key; index steps select in-range elements of arrays; anything else yields nothing (never an error). "
  "'..name' visits the current value and all its descendants in pre-order (a container before its children; array elements in order; object values in insertion order); each visited object containing key name contributes that key's value at the moment the object is visited (before its children).",
  [([{"a": [{"b": 1}, {"b": 2, "c": {"b": 3}}]}, "$.a[*]..b"], [1, 2, 3]), ([[10, 20], "$[-1]"], [20])],
  [[{}, "$"], [5, "$.a"], [{"a": 1}, "a"], [{"a": 1}, "$."], [[1, 2], "$[2]"], [[1, 2], "$[-3]"], [[1], "$[01]"], [[1], "$[-0]"], [{"x y": 7}, "$['x y']"],
   [{"it's": 1}, "$['it\\'s']"], [{"a": 1}, "$['a]"], [{"a": {"a": {"a": 1}}}, "$..a"], [{"b": [1, {"b": 2}]}, "$..b[*]"], [{"a": 1}, "$['\\x']"], [{"a": 1}, "$.a.b"], [{"k": [1, [2]]}, "$..k..k"], [{"z": 1, "a": {"z": 2}, "m": 3}, "$[*]"], [{"q": {"id": 1}, "b": [{"id": 2}], "id": 0}, "$..id"]],
  lambda r: [_doc(r), _jpath(r)]),

 (common_free_slots, "evaluation", "interval-timezone-arithmetic",
  "Inputs: calendars, a list of [offset, busy] where offset is an integer number of minutes (local time = UTC + offset) and busy is a list of [start, end] local time strings; day_start and day_end (UTC time strings); integer min_len. "
  "A time string is 'HH:MM' with HH 00..23 and MM 00..59 (two digits each), or exactly '24:00'. Return None if min_len < 1 or any time string anywhere is malformed. "
  "Each busy interval is the half-open interval [start, end) in local minutes; an interval with end <= start (in local time) is ignored. Convert it to UTC minutes by subtracting the offset; converted intervals may lie partly or wholly outside 0..1440 and are simply clipped to the window. "
  "Return the free slots within the window [day_start, day_end): the maximal intervals not covered by any busy interval of any person, keeping only those at least min_len minutes long, ascending, as [start, end] strings 'HH:MM' (1440 is '24:00'). If day_end <= day_start, return [] (after validating everything).",
  [([[[0, [["09:00", "10:00"], ["09:30", "11:00"]]], [60, [["13:00", "14:00"]]]], "08:00", "18:00", 30], [["08:00", "09:00"], ["11:00", "12:00"], ["13:00", "18:00"]]),
   ([[], "09:00", "09:00", 1], [])],
  [[[], "00:00", "24:00", 1], [[], "00:00", "24:00", 0], [[[0, [["9:00", "10:00"]]]], "08:00", "18:00", 1], [[[0, [["10:00", "09:00"]]]], "08:00", "18:00", 1],
   [[[0, [["24:00", "24:00"]]]], "00:00", "24:00", 1], [[[-120, [["23:00", "24:00"]]]], "00:00", "24:00", 30], [[[90, [["00:00", "02:00"]]]], "00:00", "02:00", 15],
   [[[0, [["10:00", "11:00"]]], [0, [["11:00", "12:00"]]]], "10:00", "13:00", 60], [[[0, [["09:00", "10:00"]]]], "12:00", "11:00", 1], [[[0, [["24:01", "10:00"]]]], "12:00", "11:00", 1]],
  lambda r: _slots(r)),

 (min_coins_lex, "evaluation", "dp-with-tiebreak",
  "Inputs: list of integers coins (denominations, each usable any number of times) and integer amount. Non-positive coins are ignored; duplicate denominations are the same coin. "
  "Return None if amount < 0 or amount cannot be formed; return [] if amount == 0. Otherwise return a multiset of coins summing to amount with the minimum number of coins, as a list sorted in descending order; if several minimum multisets exist, return the one whose descending list is lexicographically largest (compare first elements, then second, and so on).",
  [([[1, 3, 4], 6], [3, 3]), ([[5, 2, 2, -1, 0], 11], [5, 2, 2, 2])],
  [[[], 0], [[], 5], [[3], -3], [[2], 3], [[7, 3], 14], [[1, 5, 6, 9], 11], [[4, 3, 1], 7], [[10, 7, 1], 14], [[2, 3], 1], [[25, 10, 1], 30], [[6, 4, 9], 12]],
  lambda r: [r.sample(range(1, 16), r.randint(1, 4)) + r.choice([[], [], [2], [3], [0], [-3], [4, 4]]), r.randint(0, 60)]),

 (render_table, "evaluation", "text-layout-alignment",
  "Inputs: headers (list of strings), rows (list of lists of strings or integers), aligns (string with one character 'l', 'r' or 'c' per column). Return the list of output lines, or None if len(aligns) != len(headers), aligns has another character, or a row is longer than headers. If there are no headers, return []. "
  "Header and cell text is str(value) with every '|' replaced by '\\|'. Shorter rows are padded with empty cells. Each column's width is the maximum length (in characters) of its header and cell texts, but at least 3. "
  "A content line is '|' followed, for each column, by ' ' + aligned text + ' ' + '|'. Aligned text is padded with spaces to the width: 'l' pads on the right, 'r' on the left, 'c' puts floor(extra/2) spaces on the left and the rest on the right. "
  "The separator line is '|' followed, for each column of width w, by a segment of length w+2 and '|': ':' then w+1 dashes for 'l'; w+1 dashes then ':' for 'r'; ':' then w dashes then ':' for 'c'. "
  "Output: header line, separator line, then one line per row.",
  [([["id", "name"], [[7, "ann"]], "rl"], ["|  id | name |", "|----:|:-----|", "|   7 | ann  |"]), ([["a"], [], "x"], None)],
  [[[], [], ""], [[], [[1]], ""], [["h"], [["a", "b"]], "l"], [["h", "i"], [[]], "cc"], [["a|b"], [["|"]], "c"], [["long header"], [["x"]], "c"], [["", ""], [[-5, ""]], "rc"], [["n"], [[123456]], "l"]],
  lambda r: _table(r)),

 (decode_repeat, "evaluation", "nested-grammar-size-limit",
  "Input: string text. Decode it and return the result string, or None if invalid or if the decoded result would be longer than 10000 characters. "
  "Grammar, read left to right: a backslash makes the next character a literal (a trailing lone backslash is invalid); a maximal run of ASCII digits immediately followed by '[' is a repeat count (leading zeros allowed, 0 allowed): the matching bracketed content is decoded and repeated count times; a digit run not immediately followed by '[' is literal text; any other character except '[' and ']' is literal. "
  "A '[' not immediately preceded by an (unescaped) count, a ']' without an open bracket, and an unclosed '[' are invalid; the whole text must be valid even inside a part repeated 0 times. "
  "The size limit applies to the final result only, and counts may be huge (for example '0[99999999999[a]]' decodes to ''), so the function must decide the length without building oversized strings.",
  [(["2[a3[b]]c"], "abbbabbbc"), (["x12\\[y"], "x12[y")],
  [[""], ["]"], ["["], ["a\\"], ["\\3[a]"], ["3[a"], ["0[\\]"], ["0[99999999999[a]]"], ["10000[a]"], ["10001[a]"], ["5000[ab]"], ["5001[ab]"], ["99999999999[]"], ["2[]3"], ["a1b2"], ["007[x]"], ["2[2[2[\\\\]]]"]],
  lambda r: [_repeat(r)]),

 (grid_portals, "evaluation", "bfs-with-teleporters",
  "Input: grid, a list of equal-length strings. Cells: 'S' start, 'E' exit, '.' floor, '#' wall, lowercase letters a-z portals. Return None if any other character appears, if there is not exactly one 'S' and exactly one 'E', or if any portal letter does not appear exactly twice. "
  "A move goes to one of the 4 orthogonal neighbours inside the grid that is not a wall and costs 1. Entering a portal cell immediately transports you, within the same move, to the other cell with the same letter; you are then standing on that twin cell (moving away from it is a normal move; stepping back onto it later transports you again). "
  "Return the minimum number of moves from S to E, or -1 if E cannot be reached.",
  [([["S.a", "##.", "a.E"]], 4), ([["S#E"]], -1)],
  [[[]], [["SE"]], [["S.E", "..."]], [["Sa", "Ea"]], [["S", "#", "E"]], [["S.", "aE", "a."]], [["Sx", "#E"]], [["SaE", "a#."]], [["Sa.b", "####", "Eb.a"]], [["S?E"]], [["SS", "EE"]]],
  lambda r: [_grid(r)]),

 (lru_ttl, "evaluation", "cache-simulation-expiry",
  "Inputs: integer capacity >= 0 and ops, a list processed in order with non-decreasing times: ['set', t, key, value, ttl] and ['get', t, key] (key: string, value: int or string, t and ttl: integers). Return the list of results of the get ops, in order. "
  "An entry stored by set at time t with ttl expires at time t + ttl: it is live at time now only if now < t + ttl. "
  "get: if key holds a live entry, return its value and mark the entry most recently used; otherwise return None (no other effect on recency). "
  "set with ttl <= 0: delete key if present; nothing else. set with ttl >= 1: first remove every entry that is not live at time t; then if key is present, replace its value and expiry and mark it most recently used; otherwise, if capacity == 0 do nothing, else if the cache holds capacity entries evict the least recently used one, then insert the new entry as most recently used. Inserting or updating counts as a use.",
  [([2, [["set", 0, "a", 1, 10], ["set", 1, "b", 2, 10], ["get", 2, "a"], ["set", 3, "c", 3, 10], ["get", 4, "b"], ["get", 4, "a"]]], [1, None, 1]),
   ([1, [["set", 0, "k", "v", 5], ["get", 4, "k"], ["get", 5, "k"]]], ["v", None])],
  [[0, [["set", 0, "a", 1, 5], ["get", 0, "a"]]], [3, []], [2, [["set", 0, "a", 1, 1], ["set", 0, "b", 2, 9], ["set", 1, "c", 3, 9], ["get", 1, "b"], ["get", 1, "c"], ["get", 1, "a"]]],
   [2, [["set", 0, "a", 1, 9], ["set", 0, "a", 2, 0], ["get", 0, "a"]]], [2, [["set", 0, "a", 1, 9], ["set", 0, "b", 2, 9], ["set", 1, "a", 5, 9], ["set", 2, "c", 3, 9], ["get", 3, "a"], ["get", 3, "b"]]],
   [1, [["set", 0, "a", 1, 3], ["get", 3, "a"], ["get", 2, "a"]]], [2, [["set", 0, "a", 1, 9], ["set", 0, "b", 2, 9], ["get", 1, "a"], ["get", 1, "zz"], ["set", 2, "c", 3, 9], ["get", 3, "b"], ["get", 3, "a"]]]],
  lambda r: _lru(r)),
]


# ----------------------------------------------------------------------------
# Build, validation and output
# ----------------------------------------------------------------------------

def canonical(value):
    """Same identity the harness uses for disjointness (sort_keys JSON)."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def assert_json(value):
    assert type(value) in (type(None), bool, int, str, list, dict), "Non-JSON exact output type: " + type(value).__name__
    if type(value) is list:
        for item in value:
            assert_json(item)
    if type(value) is dict:
        assert all(type(key) is str for key in value)
        for item in value.values():
            assert_json(item)


def second_references():
    import coding_hard_second_refs
    return coding_hard_second_refs


def run_reference(fn, args):
    """Call a trusted reference on a deep copy and verify it neither mutates nor returns non-JSON."""
    encoded = json.dumps(args, ensure_ascii=False)
    original = json.loads(encoded)
    result = fn(*original)
    assert json.dumps(original, ensure_ascii=False) == encoded, fn.__name__ + " mutated its input"
    assert_json(result)
    return result


def build(seed=DEFAULT_SEED, second=None):
    second = second or second_references()
    public, private, disagreements = [], {}, []
    names = [fn.__name__ for fn, *_ in TASKS]
    assert len(names) == len(set(names)) == 32
    for fn, split, label, spec, examples, fixtures, fuzz in TASKS:
        rng = random.Random(f"{seed}:{fn.__name__}:cases")
        other = getattr(second, fn.__name__)
        task_id = f"{split[:3]}-{fn.__name__}"

        def expect(args):
            a, b = run_reference(fn, args), run_reference(other, args)
            if canonical(a) != canonical(b):
                disagreements.append(dict(task=task_id, args=args, reference_a=a, reference_b=b))
            return a

        shown = []
        for args, expected in examples:
            actual = expect(args)
            assert canonical(actual) == canonical(expected), (fn.__name__, args, actual, expected)
            shown.append(dict(args=args, expected=expected))
        seen = {canonical(e["args"]) for e in shown}
        cases = []

        def add(args):
            key = canonical(args)
            if key in seen:
                return
            seen.add(key)
            cases.append(dict(args=json.loads(json.dumps(args)), expected=expect(args), check_input_unchanged=True, ordered_dict=False))

        for args in fixtures:
            add(args)
        attempts = 0
        while len(cases) < max(TARGET_CASES, len(fixtures) + 12) and attempts < 2000:
            attempts += 1
            add(fuzz(rng))
        random.Random(f"{seed}:{fn.__name__}:test-partition").shuffle(cases)
        half = len(cases) // 2
        feedback, holdout = cases[:half], cases[half:]
        assert len(feedback) >= MIN_CASES_PER_PHASE and len(holdout) >= MIN_CASES_PER_PHASE, fn.__name__
        assert len(feedback) <= 128 and len(holdout) <= 128
        source = inspect.getsource(fn)
        public.append(dict(id=task_id, split=split, function_name=fn.__name__, spec=spec,
                           examples=shown, difficulty_description=label))
        private[task_id] = dict(feedback_tests=feedback, holdout_tests=holdout, trusted_reference_source=source,
                                trusted_reference_sha256=hashlib.sha256(source.encode()).hexdigest())
    assert Counter(t["split"] for t in public) == {"development": 8, "evaluation": 24}
    return public, private, disagreements


def documents(seed=DEFAULT_SEED, second=None):
    public, private, disagreements = build(seed, second)
    if disagreements:
        raise AssertionError("reference disagreement: " + json.dumps(disagreements[:5], ensure_ascii=False)[:4000])
    second_module = second or second_references()
    common = dict(protocol=PROTOCOL, corpus=CORPUS, generator_seed=seed,
                  generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  authorship="Original author-written synthetic tasks; no external benchmark content.",
                  rules="Python 3 pure functions; positional args; no input mutation or external I/O. Outputs use exact JSON types: bool differs from int, integers are not floats, arrays must be Python lists, object keys strings. Ordered array results must match exactly; dictionary key order is checked only when a case explicitly requires it.",
                  limitations="Difficulty labels are descriptive, not empirically calibrated on any model. Expected values come from two independently written trusted references that agree on every case; that is not a formal proof of the specifications.")
    tasks_doc = dict(common, tasks=public)
    hidden_doc = dict(common, references=private,
                      validation=dict(second_reference_module="coding_hard_second_refs.py",
                                      second_reference_sha256=hashlib.sha256(Path(second_module.__file__).read_bytes()).hexdigest(),
                                      dual_reference_agreement=True,
                                      cases_checked=sum(len(v["feedback_tests"]) + len(v["holdout_tests"]) for v in private.values()) + 2 * len(public)),
                      note="Only failed feedback_tests may be disclosed after testing. Never disclose holdout_tests or reference source. Freeze selection, grade holdout once, then no repairs. Each reference source is self-contained (imports inside the function).")
    return {"tasks.json": tasks_doc, "hidden-tests.json": hidden_doc}


def serialize(document):
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, help="Directory for tasks.json + hidden-tests.json; default dry-run; existing files refused")
    args = parser.parse_args(argv)
    docs = documents(args.seed)
    assert {k: serialize(v) for k, v in docs.items()} == {k: serialize(v) for k, v in documents(args.seed).items()}, "Determinism check failed"
    if args.output:
        if any((args.output / name).exists() for name in docs):
            parser.error("output files already exist")
        args.output.mkdir(parents=True, exist_ok=True)
        for name, document in docs.items():
            (args.output / name).write_text(serialize(document))
    private = docs["hidden-tests.json"]["references"]
    print(json.dumps(dict(mode="written" if args.output else "dry_run", corpus=CORPUS, tasks=len(docs["tasks.json"]["tasks"]),
                          development=8, evaluation=24,
                          feedback_cases=sum(len(v["feedback_tests"]) for v in private.values()),
                          holdout_cases=sum(len(v["holdout_tests"]) for v in private.values()),
                          dual_reference_agreement=True, output=str(args.output) if args.output else None)))


if __name__ == "__main__":
    main()
