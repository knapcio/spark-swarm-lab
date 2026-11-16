"""Independent second reference implementations for the hard coding corpus.

Written only from the public spec text and examples. Every function is
self-contained (imports and helpers are nested) so its source can be executed
on its own.
"""


def repeating_expansion(num, den, base):
    if den == 0 or base < 2 or base > 36:
        return None
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    negative = num != 0 and ((num < 0) != (den < 0))
    n, d = abs(num), abs(den)
    whole, rem = divmod(n, d)

    def to_base(v):
        if v == 0:
            return "0"
        out = []
        while v:
            v, r = divmod(v, base)
            out.append(digits[r])
        return "".join(reversed(out))

    text = ("-" if negative else "") + to_base(whole)
    if rem == 0:
        return text
    # Pre-period length: strip from the reduced denominator every prime factor
    # it shares with the base; the number of base-multiplications needed for
    # that is the pre-period, and the order of base modulo the remaining part
    # is the period.
    from math import gcd
    g = gcd(rem, d)
    rr, dd = rem // g, d // g
    rest = dd
    while True:
        h = gcd(rest, base)
        if h == 1:
            break
        rest //= h
    # pre-period = smallest k with (dd / rest) | base^k
    pre = 0
    fac = dd // rest
    p = 1
    while p % fac != 0:
        p *= base
        pre += 1
    period = 0
    if rest != 1:
        period = 1
        x = base % rest
        while x != 1 % rest:
            x = (x * base) % rest
            period += 1
    frac = []
    r = rr
    for _ in range(pre + period):
        r *= base
        q, r = divmod(r, dd)
        frac.append(digits[q])
    if period == 0:
        return text + "." + "".join(frac)
    return text + "." + "".join(frac[:pre]) + "(" + "".join(frac[pre:]) + ")"


def wrap_hyphen(text, width):
    if width < 1:
        return None
    pending = [w for w in text.split(" ") if w != ""]
    pending.reverse()  # use as a stack: pop() yields the next word
    lines = []
    cur = ""
    while pending:
        word = pending.pop()
        room = width - (len(cur) + 1 if cur else 0)
        if len(word) <= room:
            cur = cur + " " + word if cur else word
            continue
        best = -1
        for i in range(len(word) - 1):  # proper prefixes end at index i
            if word[i] == "-" and i + 1 <= room:
                best = i
        if best >= 0:
            piece = word[:best + 1]
            cur = cur + " " + piece if cur else piece
            lines.append(cur)
            cur = ""
            pending.append(word[best + 1:])
            continue
        if cur:
            lines.append(cur)
            cur = ""
            pending.append(word)
            continue
        lines.append(word[:width])
        pending.append(word[width:])
    if cur:
        lines.append(cur)
    return lines


def semver_sort(versions):
    import re
    from functools import cmp_to_key
    num = r"(?:0|[1-9][0-9]*)"
    ident = r"[0-9A-Za-z-]+"
    rx = re.compile(
        r"(" + num + r")\.(" + num + r")\.(" + num + r")"
        r"(?:-(" + ident + r"(?:\." + ident + r")*))?"
        r"(?:\+(" + ident + r"(?:\." + ident + r")*))?"
    )
    parsed = []
    for idx, v in enumerate(versions):
        if not isinstance(v, str):
            continue
        m = rx.fullmatch(v)
        if not m:
            continue
        pre = m.group(4)
        pre_ids = None
        if pre is not None:
            pre_ids = pre.split(".")
            bad = False
            for p in pre_ids:
                if p.isdigit() and p.isascii() and len(p) > 1 and p[0] == "0":
                    bad = True
            if bad:
                continue
        parsed.append((idx, v, (int(m.group(1)), int(m.group(2)), int(m.group(3))), pre_ids))

    def is_num(s):
        return s != "" and all("0" <= c <= "9" for c in s)

    def cmp_ident(a, b):
        na, nb = is_num(a), is_num(b)
        if na and nb:
            return (int(a) > int(b)) - (int(a) < int(b))
        if na:
            return -1
        if nb:
            return 1
        return (a > b) - (a < b)

    def cmp(x, y):
        if x[2] != y[2]:
            return -1 if x[2] < y[2] else 1
        px, py = x[3], y[3]
        if px is None and py is None:
            return 0
        if px is None:
            return 1
        if py is None:
            return -1
        for a, b in zip(px, py):
            c = cmp_ident(a, b)
            if c:
                return c
        return (len(px) > len(py)) - (len(px) < len(py))

    return [p[1] for p in sorted(parsed, key=cmp_to_key(cmp))]


def stack_vm(program, max_steps):
    import re
    needs = {"PUSH", "JMP", "JZ", "JNZ", "CALL"}
    plain = {"POP", "DUP", "SWAP", "OVER", "ADD", "SUB", "MUL", "DIV", "MOD",
             "PRINT", "RET", "HALT"}
    rx = re.compile(r"([^ ]+)(?: (-?[0-9]+))?")
    arity = {"POP": 1, "DUP": 1, "SWAP": 2, "OVER": 2, "ADD": 2, "SUB": 2,
             "MUL": 2, "DIV": 2, "MOD": 2, "PRINT": 1, "JZ": 1, "JNZ": 1}
    stack, calls, out = [], [], []
    pc, steps = 0, 0
    L = len(program)

    def tdiv(a, b):
        q = abs(a) // abs(b)
        return q if (a < 0) == (b < 0) else -q

    def done(status):
        return {"status": status, "output": out, "stack": stack, "steps": steps}

    while True:
        if pc == L:
            return done("ok")
        if steps == max_steps:
            return done("step_limit")
        steps += 1
        ins = program[pc]
        m = rx.fullmatch(ins) if isinstance(ins, str) else None
        if not m:
            return done("bad_instruction")
        op, arg = m.group(1), m.group(2)
        if op in needs:
            if arg is None:
                return done("bad_instruction")
            arg = int(arg)
        elif op in plain:
            if arg is not None:
                return done("bad_instruction")
        else:
            return done("bad_instruction")
        if len(stack) < arity.get(op, 0):
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
                r = a + b
            elif op == "SUB":
                r = a - b
            elif op == "MUL":
                r = a * b
            elif op == "DIV":
                r = tdiv(a, b)
            else:
                r = a - b * tdiv(a, b)
            del stack[-2:]
            stack.append(r)
        elif op == "PRINT":
            out.append(stack.pop())
        elif op in ("JMP", "CALL"):
            if not (0 <= arg <= L):
                return done("bad_jump")
            if op == "CALL":
                calls.append(pc + 1)
            nxt = arg
        elif op in ("JZ", "JNZ"):
            take = (stack[-1] == 0) if op == "JZ" else (stack[-1] != 0)
            if take and not (0 <= arg <= L):
                return done("bad_jump")
            stack.pop()
            if take:
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
    num = r"(0|[1-9][0-9]*)"
    rx = re.compile(num + r"\." + num + r"\." + num + r"\." + num + r"/" + num)
    spans = []
    for b in blocks:
        if not isinstance(b, str):
            continue
        m = rx.fullmatch(b)
        if not m:
            continue
        vals = [int(g) for g in m.groups()]
        if any(v > 255 for v in vals[:4]) or vals[4] > 32:
            continue
        addr = (vals[0] << 24) | (vals[1] << 16) | (vals[2] << 8) | vals[3]
        size = 1 << (32 - vals[4])
        lo = addr - addr % size
        spans.append((lo, lo + size))
    spans.sort()
    merged = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1][1] = hi
        else:
            merged.append([lo, hi])
    out = []
    for lo, hi in merged:
        cur = lo
        while cur < hi:
            size = 1 << 32
            while cur % size != 0 or cur + size > hi:
                size >>= 1
            p = 32 - (size.bit_length() - 1)
            out.append("%d.%d.%d.%d/%d" % (cur >> 24, (cur >> 16) & 255,
                                           (cur >> 8) & 255, cur & 255, p))
            cur += size
    return out


def nth_distinct_permutation(s, n):
    from math import factorial
    from collections import Counter
    cnt = Counter(s)

    def total(c):
        t = factorial(sum(c.values()))
        for v in c.values():
            t //= factorial(v)
        return t

    if n < 0 or n >= total(cnt):
        return None
    out = []
    for _ in range(len(s)):
        for ch in sorted(k for k, v in cnt.items() if v > 0):
            cnt[ch] -= 1
            t = total(cnt)
            if n < t:
                out.append(ch)
                break
            n -= t
            cnt[ch] += 1
    return "".join(out)


def glob_match(pattern, text):
    # compile to tokens: ('lit', c) | ('any',) | ('star',) | ('cls', neg, items)
    toks = []
    i, L = 0, len(pattern)
    while i < L:
        c = pattern[i]
        if c == "\\":
            if i + 1 >= L:
                return None
            toks.append(("lit", pattern[i + 1]))
            i += 2
        elif c == "?":
            toks.append(("any",))
            i += 1
        elif c == "*":
            toks.append(("star",))
            i += 1
        elif c == "[":
            i += 1
            neg = False
            if i < L and pattern[i] == "!":
                neg = True
                i += 1
            items = []
            first = True
            closed = False
            while i < L:
                if pattern[i] == "]" and not first:
                    closed = True
                    i += 1
                    break
                # read one (possibly escaped) character
                if pattern[i] == "\\":
                    if i + 1 >= L:
                        return None
                    lo = pattern[i + 1]
                    i += 2
                else:
                    lo = pattern[i]
                    i += 1
                first = False
                hi = lo
                if i < L and pattern[i] == "-" and not (i + 1 < L and pattern[i + 1] == "]"):
                    if i + 1 >= L:
                        return None  # unclosed class
                    j = i + 1
                    if pattern[j] == "\\":
                        if j + 1 >= L:
                            return None
                        hi = pattern[j + 1]
                        i = j + 2
                    else:
                        hi = pattern[j]
                        i = j + 1
                    if ord(lo) > ord(hi):
                        return None
                items.append((lo, hi))
            if not closed:
                return None
            toks.append(("cls", neg, items))
        else:
            toks.append(("lit", c))
            i += 1

    def ok(tok, ch):
        k = tok[0]
        if k == "lit":
            return tok[1] == ch
        if k == "any":
            return True
        inside = any(lo <= ch <= hi for lo, hi in tok[2])
        return inside != tok[1]

    # NFA simulation over token positions
    def closure(states):
        res = set(states)
        stack = list(states)
        while stack:
            s = stack.pop()
            if s < len(toks) and toks[s][0] == "star" and s + 1 not in res:
                res.add(s + 1)
                stack.append(s + 1)
        return res

    states = closure({0})
    for ch in text:
        nxt = set()
        for s in states:
            if s < len(toks):
                if toks[s][0] == "star":
                    nxt.add(s)
                elif ok(toks[s], ch):
                    nxt.add(s + 1)
        states = closure(nxt)
        if not states:
            return False
    return len(toks) in states


def add_business_days(date, n, holidays):
    import re
    import datetime
    from bisect import bisect_left, bisect_right

    def parse(s):
        if not isinstance(s, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", s):
            return None
        try:
            return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:])).toordinal()
        except ValueError:
            return None

    start = parse(date)
    if start is None:
        return None
    hol = set()
    for h in holidays:
        o = parse(h)
        if o is not None:
            hol.add(o)
    MIN, MAX = 1, datetime.date(9999, 12, 31).toordinal()

    def is_bd(o):
        return o % 7 not in (0, 6) and o not in hol  # ordinal%7: 0=Sun, 6=Sat

    def fmt(o):
        return datetime.date.fromordinal(o).isoformat()

    if n == 0:
        o = start
        while o <= MAX:
            if is_bd(o):
                return fmt(o)
            o += 1
        return None
    step = 1 if n > 0 else -1
    need = abs(n)
    weekday_hols = sorted(h for h in hol if h % 7 not in (0, 6))
    o = start
    while True:
        # skip whole weeks while they cannot contain the target
        if step == 1:
            if o + 7 <= MAX:
                cnt = 5 - (bisect_right(weekday_hols, o + 7) - bisect_right(weekday_hols, o))
                if cnt < need:
                    need -= cnt
                    o += 7
                    continue
        else:
            if o - 7 >= MIN:
                cnt = 5 - (bisect_left(weekday_hols, o) - bisect_left(weekday_hols, o - 7))
                if cnt < need:
                    need -= cnt
                    o -= 7
                    continue
        o += step
        if o < MIN or o > MAX:
            return None
        if is_bd(o):
            need -= 1
            if need == 0:
                return fmt(o)


def rational_eval(expr):
    import re
    from fractions import Fraction

    class Err(Exception):
        pass

    toks = []
    for m in re.finditer(r"([0-9]+)|([-+*/^()])|([ \t]+)|(.)", expr, re.S):
        if m.group(4) is not None:
            return "error"
        if m.group(1) is not None:
            toks.append(("n", int(m.group(1))))
        elif m.group(2) is not None:
            toks.append(("o", m.group(2)))
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take(sym):
        t = peek()
        if t is not None and t == ("o", sym):
            pos[0] += 1
            return True
        return False

    def expr_():
        v = term()
        while True:
            if take("+"):
                v = v + term()
            elif take("-"):
                v = v - term()
            else:
                return v

    def term():
        v = unary()
        while True:
            if take("*"):
                v = v * unary()
            elif take("/"):
                d = unary()
                if d == 0:
                    raise Err()
                v = v / d
            else:
                return v

    def unary():
        if take("-"):
            return -unary()
        return power()

    def power():
        b = atom()
        if take("^"):
            e = unary()
            if e.denominator != 1 or abs(e) > 64:
                raise Err()
            e = int(e)
            if b == 0 and e < 0:
                raise Err()
            return b ** e
        return b

    def atom():
        t = peek()
        if t is None:
            raise Err()
        if t[0] == "n":
            pos[0] += 1
            return Fraction(t[1])
        if take("("):
            v = expr_()
            if not take(")"):
                raise Err()
            return v
        raise Err()

    try:
        v = expr_()
        if pos[0] != len(toks):
            return "error"
    except (Err, RecursionError):
        return "error"
    v = Fraction(v)
    if v.denominator == 1:
        return str(v.numerator)
    return "%d/%d" % (v.numerator, v.denominator)


def shell_words(line, env):
    def is_start(c):
        return c == "_" or ("a" <= c <= "z") or ("A" <= c <= "Z")

    def is_name(c):
        return is_start(c) or ("0" <= c <= "9")

    words = []
    buf = []
    quoted = False
    in_word = False
    i, L = 0, len(line)

    def expand(i):
        # line[i] == '$'; returns (text, new_index) or raises ValueError
        if i + 1 < L and line[i + 1] == "{":
            j = line.find("}", i + 2)
            if j < 0:
                raise ValueError
            name = line[i + 2:j]
            if not name or not is_start(name[0]) or not all(is_name(c) for c in name):
                raise ValueError
            return env.get(name, ""), j + 1
        if i + 1 < L and is_start(line[i + 1]):
            j = i + 1
            while j < L and is_name(line[j]):
                j += 1
            return env.get(line[i + 1:j], ""), j
        return "$", i + 1

    try:
        while i < L:
            c = line[i]
            if c in " \t":
                if in_word and ("".join(buf) or quoted):
                    words.append("".join(buf))
                buf, quoted, in_word = [], False, False
                i += 1
                continue
            in_word = True
            if c == "\\":
                if i + 1 >= L:
                    return None
                buf.append(line[i + 1])
                i += 2
            elif c == "'":
                j = line.find("'", i + 1)
                if j < 0:
                    return None
                buf.append(line[i + 1:j])
                quoted = True
                i = j + 1
            elif c == '"':
                quoted = True
                i += 1
                while True:
                    if i >= L:
                        return None
                    d = line[i]
                    if d == '"':
                        i += 1
                        break
                    if d == "\\":
                        if i + 1 < L and line[i + 1] in '"\\$':
                            buf.append(line[i + 1])
                            i += 2
                        else:
                            buf.append("\\")
                            i += 1
                    elif d == "$":
                        txt, i = expand(i)
                        buf.append(txt)
                    else:
                        buf.append(d)
                        i += 1
            elif c == "$":
                txt, i = expand(i)
                buf.append(txt)
            else:
                buf.append(c)
                i += 1
    except ValueError:
        return None
    if in_word and ("".join(buf) or quoted):
        words.append("".join(buf))
    return words


def cron_next(expr, start):
    import re
    import datetime
    if not isinstance(expr, str) or not isinstance(start, str):
        return None
    parts = expr.split(" ")
    if len(parts) != 5:
        return None
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    item_rx = re.compile(r"(\*|([0-9]+)(?:-([0-9]+))?)(?:/([0-9]+))?")
    sets = []
    for text, (lo, hi) in zip(parts, bounds):
        if text == "":
            return None
        vals = set()
        for item in text.split(","):
            m = item_rx.fullmatch(item)
            if not m:
                return None
            step = 1
            if m.group(4) is not None:
                step = int(m.group(4))
                if step < 1:
                    return None
            if m.group(1) == "*":
                a, b = lo, hi
            else:
                a = int(m.group(2))
                if m.group(3) is not None:
                    b = int(m.group(3))
                elif m.group(4) is not None:
                    b = hi
                else:
                    b = a
                if not (lo <= a <= hi and lo <= b <= hi) or a > b:
                    return None
            vals.update(range(a, b + 1, step))
        sets.append(vals)
    mins, hours, doms, months, dows = sets
    dom_r, dow_r = parts[2] != "*", parts[4] != "*"
    m = re.fullmatch(r"([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2})", start)
    if not m:
        return None
    try:
        sd = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    sh, sm = int(m.group(4)), int(m.group(5))
    if sh > 23 or sm > 59:
        return None
    limit_year = min(sd.year + 5, 10000)
    hm = sorted(h * 60 + mi for h in hours for mi in mins)
    if not hm:
        return None

    def day_ok(d):
        if d.month not in months:
            return False
        a = d.day in doms
        b = (d.isoweekday() % 7) in dows
        if dom_r and dow_r:
            return a or b
        return a and b

    d = sd
    first = True
    while d.year < limit_year:
        if day_ok(d):
            floor = sh * 60 + sm if first else -1
            for x in hm:
                if x > floor:
                    return "%04d-%02d-%02d %02d:%02d" % (d.year, d.month, d.day, x // 60, x % 60)
        first = False
        if d == datetime.date.max:
            break
        d = d + datetime.timedelta(days=1)
    return None


def date_diff_ymd(a, b):
    import re
    import calendar
    import datetime

    def parse(s):
        if not isinstance(s, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", s):
            return None
        try:
            return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:]))
        except ValueError:
            return None

    da, db = parse(a), parse(b)
    if da is None or db is None:
        return None
    def core(x, y):
        def shift(k):
            mi = x.month - 1 + k
            yy, mm = x.year + mi // 12, mi % 12 + 1
            if yy > 9999:
                return None
            return datetime.date(yy, mm, min(x.day, calendar.monthrange(yy, mm)[1]))
        # binary search for the largest k with shift(k) <= y
        lo, hi = 0, (y.year - x.year) * 12 + 12
        while lo < hi:
            mid = (lo + hi + 1) // 2
            s = shift(mid)
            if s is not None and s <= y:
                lo = mid
            else:
                hi = mid - 1
        T = lo
        return [T // 12, T % 12, (y - shift(T)).days]

    if da <= db:
        return core(da, db)
    return [-v for v in core(db, da)]


def monthly_occurrences(start, rule, count):
    import re
    import calendar
    import datetime
    if not isinstance(start, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", start):
        return None
    try:
        sd = datetime.date(int(start[:4]), int(start[5:7]), int(start[8:]))
    except ValueError:
        return None
    if not isinstance(rule, str):
        return None
    wds = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    m1 = re.fullmatch(r"day:(-?)([1-9][0-9]*)", rule)
    m2 = re.fullmatch(r"nth:(-?)([1-9][0-9]*):([a-z]+)", rule)
    if m1:
        N = int(m1.group(2))
        if N > 31:
            return None
        kind, neg, val, wd = "day", m1.group(1) == "-", N, None
    elif m2:
        K = int(m2.group(2))
        if K > 5 or m2.group(3) not in wds:
            return None
        kind, neg, val, wd = "nth", m2.group(1) == "-", K, wds.index(m2.group(3))
    else:
        return None
    if count <= 0:
        return []

    def pick(y, mo):
        ndays = calendar.monthrange(y, mo)[1]
        if kind == "day":
            dd = (ndays - val + 1) if neg else val
            if 1 <= dd <= ndays:
                return dd
            return None
        hits = [dd for dd in range(1, ndays + 1) if calendar.weekday(y, mo, dd) == wd]
        if val > len(hits):
            return None
        return hits[-val] if neg else hits[val - 1]

    out = []
    y, mo = sd.year, sd.month
    while y <= 9999 and len(out) < count:
        dd = pick(y, mo)
        if dd is not None:
            dt = datetime.date(y, mo, dd)
            if dt >= sd:
                out.append(dt.isoformat())
        mo += 1
        if mo == 13:
            y, mo = y + 1, 1
    return out


def schedule_jobs(jobs, workers):
    if workers < 1:
        return None
    pending = [list(j) for j in jobs]
    free_at = [0] * workers
    result = []
    t = 0
    while pending:
        idle = [w for w in range(workers) if free_at[w] <= t]
        while idle:
            ready = [j for j in pending if j[1] <= t]
            if not ready:
                break
            best = min(ready, key=lambda j: (-j[3], j[1], j[0]))
            pending.remove(best)
            w = idle.pop(0)
            free_at[w] = t + best[2]
            result.append([best[0], w, t, t + best[2]])
        if not pending:
            break
        cands = [f for f in free_at if f > t] + [j[1] for j in pending if j[1] > t]
        t = min(cands)
    result.sort(key=lambda r: (r[2], r[1]))
    return result


def lex_shortest_path(edges, src, dst):
    import heapq
    for e in edges:
        if e[2] < 1:
            return None
    if src == dst:
        return [0, [src]]
    rev = {}
    fwd = {}
    for u, v, w in edges:
        rev.setdefault(v, []).append((u, w))
        fwd.setdefault(u, []).append((v, w))
    # distances TO dst via reverse Dijkstra
    dist = {dst: 0}
    heap = [(0, dst)]
    while heap:
        d, x = heapq.heappop(heap)
        if d > dist.get(x, float("inf")):
            continue
        for p, w in rev.get(x, []):
            nd = d + w
            if nd < dist.get(p, float("inf")):
                dist[p] = nd
                heapq.heappush(heap, (nd, p))
    if src not in dist:
        return None
    path = [src]
    cur = src
    while cur != dst:
        opts = [v for v, w in fwd.get(cur, []) if v in dist and w + dist[v] == dist[cur]]
        cur = min(opts)
        path.append(cur)
    return [dist[src], path]


def stable_topo(names, deps):
    import heapq
    order_idx = {}
    uniq = []
    for n in names:
        if n not in order_idx:
            order_idx[n] = len(uniq)
            uniq.append(n)
    succ = {n: set() for n in uniq}
    for pair in deps:
        a, b = pair[0], pair[1]
        if a in order_idx and b in order_idx:
            succ[a].add(b)
    indeg = {n: 0 for n in uniq}
    for a in uniq:
        for b in succ[a]:
            indeg[b] += 1
    heap = [order_idx[n] for n in uniq if indeg[n] == 0]
    heapq.heapify(heap)
    order = []
    while heap:
        n = uniq[heapq.heappop(heap)]
        order.append(n)
        for b in succ[n]:
            indeg[b] -= 1
            if indeg[b] == 0:
                heapq.heappush(heap, order_idx[b])
    done = set(order)
    remaining = [n for n in uniq if n not in done]
    cyclic, blocked = [], []
    for n in remaining:
        seen = set()
        stack = list(succ[n])
        found = False
        while stack:
            x = stack.pop()
            if x == n:
                found = True
                break
            if x in seen:
                continue
            seen.add(x)
            stack.extend(succ[x])
        (cyclic if found else blocked).append(n)
    return {"order": order, "cyclic": cyclic, "blocked": blocked}


def order_book(ops):
    used = set()
    resting = []  # dicts: id, side, price, qty, time
    trades = []
    for t, op in enumerate(ops):
        if not isinstance(op, (list, tuple)) or not op:
            continue
        kind = op[0]
        if kind == "cancel":
            if len(op) != 2:
                continue
            resting = [o for o in resting if o["id"] != op[1]]
            continue
        if kind == "limit":
            if len(op) != 5:
                continue
            _, oid, side, price, qty = op
            if price < 1:
                continue
        elif kind == "market":
            if len(op) != 4:
                continue
            _, oid, side, qty = op
            price = None
        else:
            continue
        if side not in ("buy", "sell") or qty < 1 or oid in used:
            continue
        used.add(oid)
        remaining = qty
        while remaining > 0:
            if side == "buy":
                opp = [o for o in resting if o["side"] == "sell"]
                if not opp:
                    break
                best = min(opp, key=lambda o: (o["price"], o["time"]))
                if price is not None and best["price"] > price:
                    break
            else:
                opp = [o for o in resting if o["side"] == "buy"]
                if not opp:
                    break
                best = min(opp, key=lambda o: (-o["price"], o["time"]))
                if price is not None and best["price"] < price:
                    break
            q = min(remaining, best["qty"])
            if side == "buy":
                trades.append([oid, best["id"], best["price"], q])
            else:
                trades.append([best["id"], oid, best["price"], q])
            remaining -= q
            best["qty"] -= q
            if best["qty"] == 0:
                resting.remove(best)
        if remaining > 0 and price is not None:
            resting.append({"id": oid, "side": side, "price": price, "qty": remaining, "time": t})
    bids = sorted((o for o in resting if o["side"] == "buy"), key=lambda o: (-o["price"], o["time"]))
    asks = sorted((o for o in resting if o["side"] == "sell"), key=lambda o: (o["price"], o["time"]))
    return {"trades": trades,
            "bids": [[o["id"], o["price"], o["qty"]] for o in bids],
            "asks": [[o["id"], o["price"], o["qty"]] for o in asks]}


def ledger(accounts, ops):
    bal = {}
    od = {}
    frozen = {}
    wdc = {}
    for name, b, o in accounts:
        bal[name] = b
        od[name] = o
        frozen[name] = False
        wdc[name] = 0
    shapes = {"dep": 3, "wd": 3, "xfer": 4, "freeze": 2, "thaw": 2, "day": 1}
    rejected = []
    for i, op in enumerate(ops):
        kind = op[0] if isinstance(op, (list, tuple)) and op else None
        if not isinstance(kind, str) or kind not in shapes or len(op) != shapes[kind]:
            rejected.append([i, "bad_op"])
            continue
        if kind == "day":
            for k in wdc:
                wdc[k] = 0
            continue
        named = [op[1], op[2]] if kind == "xfer" else [op[1]]
        if any(not isinstance(n, str) or n not in bal for n in named):
            rejected.append([i, "no_account"])
            continue
        if kind == "freeze":
            frozen[op[1]] = True
            continue
        if kind == "thaw":
            frozen[op[1]] = False
            continue
        if kind == "xfer" and op[1] == op[2]:
            rejected.append([i, "same_account"])
            continue
        amt = op[-1]
        if amt < 1:
            rejected.append([i, "bad_amount"])
            continue
        if kind == "dep":
            bal[op[1]] += amt
            continue
        src = op[1]
        if frozen[src]:
            rejected.append([i, "frozen"])
            continue
        if kind == "wd":
            cost = amt + (0 if wdc[src] < 3 else 2)
        else:
            cost = amt + 1
        if bal[src] - cost < -od[src]:
            rejected.append([i, "insufficient"])
            continue
        bal[src] -= cost
        if kind == "wd":
            wdc[src] += 1
        else:
            bal[op[2]] += amt
    return {"balances": [[n, bal[n]] for n in sorted(bal)], "rejected": rejected}


def spreadsheet_eval(cells):
    import re
    lit_rx = re.compile(r"-?[0-9]+")
    tok_rx = re.compile(r"SUM\(|[A-Z](?:[1-9][0-9]?)(?![0-9])|[0-9]+|[-+*():]")

    class Bad(Exception):
        pass

    def tokenize(s):
        # spaces separate tokens: a token never spans a space
        toks = []
        for chunk in s.split(" "):
            i = 0
            while i < len(chunk):
                m = tok_rx.match(chunk, i)
                if not m:
                    raise Bad()
                toks.append(m.group(0))
                i = m.end()
        return toks

    def is_ref(t):
        return len(t) >= 2 and "A" <= t[0] <= "Z" and t[1:].isdigit()

    def parse(toks):
        # AST: ('n', v) | ('r', name) | ('sum', a, b) | ('neg', x) | (op, l, r)
        p = [0]

        def peek():
            return toks[p[0]] if p[0] < len(toks) else None

        def eat(t):
            if peek() == t:
                p[0] += 1
                return True
            return False

        def expr():
            v = term()
            while True:
                if eat("+"):
                    v = ("+", v, term())
                elif eat("-"):
                    v = ("-", v, term())
                else:
                    return v

        def term():
            v = unary()
            while eat("*"):
                v = ("*", v, unary())
            return v

        def unary():
            if eat("-"):
                return ("neg", unary())
            return primary()

        def primary():
            t = peek()
            if t is None:
                raise Bad()
            if t.isdigit():
                p[0] += 1
                return ("n", int(t))
            if is_ref(t):
                p[0] += 1
                return ("r", t)
            if t == "SUM(":
                p[0] += 1
                a = peek()
                if a is None or not is_ref(a):
                    raise Bad()
                p[0] += 1
                if not eat(":"):
                    raise Bad()
                b = peek()
                if b is None or not is_ref(b):
                    raise Bad()
                p[0] += 1
                if not eat(")"):
                    raise Bad()
                return ("sum", a, b)
            if eat("("):
                v = expr()
                if not eat(")"):
                    raise Bad()
                return v
            raise Bad()

        v = expr()
        if p[0] != len(toks):
            raise Bad()
        return v

    def expand_range(a, b):
        c1, c2 = sorted((a[0], b[0]))
        r1, r2 = sorted((int(a[1:]), int(b[1:])))
        return [chr(c) + str(r) for r in range(r1, r2 + 1) for c in range(ord(c1), ord(c2) + 1)]

    def refs_of(node, acc):
        k = node[0]
        if k == "r":
            acc.append(node[1])
        elif k == "sum":
            acc.extend(expand_range(node[1], node[2]))
        elif k == "neg":
            refs_of(node[1], acc)
        elif k in "+-*":
            refs_of(node[1], acc)
            refs_of(node[2], acc)
        return acc

    result = {}
    asts = {}
    refs = {}
    for name, raw in cells.items():
        if not isinstance(raw, str) or not raw.startswith("="):
            if isinstance(raw, str) and lit_rx.fullmatch(raw):
                result[name] = int(raw)
            else:
                result[name] = "#VALUE"
            continue
        try:
            ast = parse(tokenize(raw[1:]))
        except (Bad, RecursionError):
            result[name] = "#SYNTAX"
            continue
        asts[name] = ast
        refs[name] = refs_of(ast, [])

    # cycle detection: a formula cell that can reach itself
    for name in asts:
        seen = set()
        stack = list(refs[name])
        while stack:
            x = stack.pop()
            if x == name:
                result[name] = "#CYCLE"
                break
            if x in seen or x not in refs:
                continue
            seen.add(x)
            stack.extend(refs[x])

    def value(name):
        if name in result:
            return result[name]
        if name not in cells:
            return 0
        for r in refs[name]:
            v = value(r)
            if isinstance(v, str):
                result[name] = v
                return v

        def ev(node):
            k = node[0]
            if k == "n":
                return node[1]
            if k == "r":
                return value(node[1])
            if k == "sum":
                return sum(value(c) for c in expand_range(node[1], node[2]))
            if k == "neg":
                return -ev(node[1])
            l, r = ev(node[1]), ev(node[2])
            return l + r if k == "+" else (l - r if k == "-" else l * r)

        result[name] = ev(asts[name])
        return result[name]

    for name in cells:
        value(name)
    return {k: result[k] for k in cells}


def poly_expand(expr):
    import re
    if not isinstance(expr, str):
        return None
    toks = []
    for m in re.finditer(r"([0-9]+)|([-+*^()x])|( +)|(.)", expr, re.S):
        if m.group(4) is not None:
            return None
        if m.group(1) is not None:
            toks.append(("n", m.group(1)))
        elif m.group(2) is not None:
            toks.append(("o", m.group(2)))

    class Bad(Exception):
        pass

    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def eat(sym):
        if peek() == ("o", sym):
            pos[0] += 1
            return True
        return False

    # polynomials as dict degree -> coefficient
    def add(p, q, sign=1):
        r = dict(p)
        for d, c in q.items():
            r[d] = r.get(d, 0) + sign * c
        return {d: c for d, c in r.items() if c != 0}

    def mul(p, q):
        r = {}
        for d1, c1 in p.items():
            for d2, c2 in q.items():
                r[d1 + d2] = r.get(d1 + d2, 0) + c1 * c2
        return {d: c for d, c in r.items() if c != 0}

    def expr_():
        v = term()
        while True:
            if eat("+"):
                v = add(v, term())
            elif eat("-"):
                v = add(v, term(), -1)
            else:
                return v

    def term():
        v = factor()
        while eat("*"):
            v = mul(v, factor())
        return v

    def factor():
        if eat("-"):
            return {d: -c for d, c in factor().items()}
        b = base()
        if eat("^"):
            t = peek()
            if t is None or t[0] != "n":
                raise Bad()
            pos[0] += 1
            e = int(t[1])
            if e > 20:
                raise Bad()
            r = {0: 1}
            for _ in range(e):
                r = mul(r, b)
            return r
        return b

    def base():
        t = peek()
        if t is None:
            raise Bad()
        if t[0] == "n":
            pos[0] += 1
            v = int(t[1])
            return {0: v} if v else {}
        if eat("x"):
            return {1: 1}
        if eat("("):
            v = expr_()
            if not eat(")"):
                raise Bad()
            return v
        raise Bad()

    try:
        poly = expr_()
        if pos[0] != len(toks):
            return None
    except (Bad, RecursionError):
        return None
    if not poly:
        return "0"
    out = []
    for i, d in enumerate(sorted(poly, reverse=True)):
        c = poly[d]
        sign = "-" if c < 0 else ("+" if i else "")
        a = abs(c)
        if d == 0:
            body = str(a)
        else:
            body = ("" if a == 1 else str(a)) + "x" + ("^%d" % d if d > 1 else "")
        out.append(sign + body)
    return "".join(out)


def bool_minterms(expr):
    import re
    if not isinstance(expr, str):
        return None
    toks = []
    for m in re.finditer(r"([a-z]+)|([0-9]+)|(->|[!&^|()])|( +)|(.)", expr, re.S):
        if m.group(5) is not None:
            return None
        if m.group(1) is not None:
            toks.append(("v", m.group(1)))
        elif m.group(2) is not None:
            if m.group(2) not in ("0", "1"):
                return None
            toks.append(("c", m.group(2) == "1"))
        elif m.group(3) is not None:
            toks.append(("o", m.group(3)))

    class Bad(Exception):
        pass

    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def eat(sym):
        if peek() == ("o", sym):
            pos[0] += 1
            return True
        return False

    # build closures env -> bool
    def imp():
        left = xor_or()
        if eat("->"):
            right = imp()
            return lambda e, l=left, r=right: (not l(e)) or r(e)
        return left

    def xor_or():
        v = xor_()
        while eat("|"):
            r = xor_()
            v = (lambda e, l=v, r=r: l(e) or r(e))
        return v

    def xor_():
        v = and_()
        while eat("^"):
            r = and_()
            v = (lambda e, l=v, r=r: l(e) != r(e))
        return v

    def and_():
        v = not_()
        while eat("&"):
            r = not_()
            v = (lambda e, l=v, r=r: l(e) and r(e))
        return v

    def not_():
        if eat("!"):
            x = not_()
            return lambda e, x=x: not x(e)
        t = peek()
        if t is None:
            raise Bad()
        if t[0] == "v":
            pos[0] += 1
            return lambda e, n=t[1]: e[n]
        if t[0] == "c":
            pos[0] += 1
            return lambda e, c=t[1]: c
        if eat("("):
            v = imp()
            if not eat(")"):
                raise Bad()
            return v
        raise Bad()

    try:
        f = imp()
        if pos[0] != len(toks):
            return None
    except (Bad, RecursionError):
        return None
    names = sorted({t[1] for t in toks if t[0] == "v"})
    k = len(names)
    mins = []
    for idx in range(1 << k):
        env = {names[j]: bool((idx >> (k - 1 - j)) & 1) for j in range(k)}
        if f(env):
            mins.append(idx)
    return [names, mins]


def csv_parse(text):
    if text == "":
        return []
    L = len(text)
    records = []
    i = 0
    while True:
        rec = []
        while True:
            # parse one field starting at i
            if i < L and text[i] == '"':
                j = i + 1
                buf = []
                while True:
                    k = text.find('"', j)
                    if k < 0:
                        return None
                    buf.append(text[j:k])
                    if k + 1 < L and text[k + 1] == '"':
                        buf.append('"')
                        j = k + 2
                        continue
                    i = k + 1
                    break
                rec.append("".join(buf))
                if not (i == L or text[i] == "," or text[i] == "\n" or text.startswith("\r\n", i)):
                    return None
            else:
                j = i
                while j < L and text[j] != "," and text[j] != "\n" and not text.startswith("\r\n", j):
                    j += 1
                field = text[i:j]
                if '"' in field:
                    return None
                rec.append(field)
                i = j
            if i < L and text[i] == ",":
                i += 1
                continue
            break
        records.append(rec)
        if i == L:
            return records
        i += 2 if text[i] == "\r" else 1
        if i == L:
            return records


def league_table(matches):
    valid = [m for m in matches if m[0] != m[1] and m[2] >= 0 and m[3] >= 0]
    st = {}

    def row(n):
        if n not in st:
            st[n] = {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0}
        return st[n]

    for h, a, hg, ag in valid:
        for team, gf, ga in ((h, hg, ag), (a, ag, hg)):
            r = row(team)
            r["p"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if gf > ga:
                r["w"] += 1
                r["pts"] += 3
            elif gf == ga:
                r["d"] += 1
                r["pts"] += 1
            else:
                r["l"] += 1
    groups = {}
    for n, r in st.items():
        groups.setdefault(r["pts"], set()).add(n)
    h2h = {n: [0, 0] for n in st}
    for pts, members in groups.items():
        for h, a, hg, ag in valid:
            if h in members and a in members:
                h2h[h][1] += hg - ag
                h2h[a][1] += ag - hg
                if hg > ag:
                    h2h[h][0] += 3
                elif hg < ag:
                    h2h[a][0] += 3
                else:
                    h2h[h][0] += 1
                    h2h[a][0] += 1
    order = sorted(st, key=lambda n: (-st[n]["pts"], -h2h[n][0], -h2h[n][1],
                                      -(st[n]["gf"] - st[n]["ga"]), -st[n]["gf"], n))
    return [[n, st[n]["p"], st[n]["w"], st[n]["d"], st[n]["l"], st[n]["gf"], st[n]["ga"], st[n]["pts"]]
            for n in order]


def canonical_huffman(freqs):
    weights = {}
    for sym, w in freqs:
        if w <= 0:
            continue
        weights[sym] = weights.get(sym, 0) + w
    if not weights:
        return []
    if len(weights) == 1:
        lengths = {next(iter(weights)): 1}
    else:
        # explicit tree: node = [weight, key, children]
        nodes = [[w, s, None, s] for s, w in weights.items()]  # last = symbol for leaves
        while len(nodes) > 1:
            nodes.sort(key=lambda n: (n[0], n[1]))
            a, b = nodes[0], nodes[1]
            nodes = nodes[2:] + [[a[0] + b[0], min(a[1], b[1]), (a, b), None]]
        lengths = {}
        stack = [(nodes[0], 0)]
        while stack:
            n, depth = stack.pop()
            if n[2] is None:
                lengths[n[3]] = depth
            else:
                stack.append((n[2][0], depth + 1))
                stack.append((n[2][1], depth + 1))
    order = sorted(lengths, key=lambda s: (lengths[s], s))
    out = []
    code, prev = 0, None
    for s in order:
        ln = lengths[s]
        if prev is None:
            code = 0
        else:
            code = (code + 1) << (ln - prev)
        prev = ln
        out.append([s, format(code, "0%db" % ln)])
    return out


def token_bucket(capacity, refill_ms, requests):
    if capacity < 1 or refill_ms < 1:
        return None
    tokens, mark = capacity, 0
    last = None
    accepted = []
    for idx, (t, cost) in enumerate(requests):
        if cost < 1 or t < 0 or (last is not None and t < last):
            continue
        last = t
        if tokens < capacity:
            g = (t - mark) // refill_ms
            if tokens + g >= capacity:
                tokens = capacity
            else:
                tokens += g
                mark += g * refill_ms
        if tokens == capacity:
            mark = t
        if cost <= tokens:
            tokens -= cost
            accepted.append(idx)
    return accepted


def json_select(doc, path):
    import re
    if not isinstance(path, str) or not path.startswith("$"):
        return None
    steps = []
    i, L = 1, len(path)
    name_rx = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    idx_rx = re.compile(r"\[(-?(?:0|[1-9][0-9]*))\]")
    while i < L:
        if path.startswith("..", i):
            m = name_rx.match(path, i + 2)
            if not m:
                return None
            steps.append(("desc", m.group(0)))
            i = m.end()
        elif path[i] == ".":
            m = name_rx.match(path, i + 1)
            if not m:
                return None
            steps.append(("key", m.group(0)))
            i = m.end()
        elif path.startswith("[*]", i):
            steps.append(("all",))
            i += 3
        elif path.startswith("['", i):
            j = i + 2
            buf = []
            while True:
                if j >= L:
                    return None
                c = path[j]
                if c == "\\":
                    if j + 1 < L and path[j + 1] in "'\\":
                        buf.append(path[j + 1])
                        j += 2
                        continue
                    return None
                if c == "'":
                    break
                buf.append(c)
                j += 1
            if j + 1 >= L or path[j + 1] != "]":
                return None
            steps.append(("key", "".join(buf)))
            i = j + 2
        else:
            m = idx_rx.match(path, i)
            if not m:
                return None
            steps.append(("idx", int(m.group(1))))
            i = m.end()

    def children(v):
        if isinstance(v, list):
            return list(v)
        if isinstance(v, dict):
            return list(v.values())  # insertion order
        return []

    cur = [doc]
    for st in steps:
        nxt = []
        for v in cur:
            if st[0] == "key":
                if isinstance(v, dict) and st[1] in v:
                    nxt.append(v[st[1]])
            elif st[0] == "idx":
                if isinstance(v, list):
                    k = st[1]
                    if -len(v) <= k < len(v):
                        nxt.append(v[k])
            elif st[0] == "all":
                nxt.extend(children(v))
            else:
                stack = [v]
                while stack:
                    x = stack.pop()
                    if isinstance(x, dict) and st[1] in x:
                        nxt.append(x[st[1]])
                    stack.extend(reversed(children(x)))
        cur = nxt
    return cur


def common_free_slots(calendars, day_start, day_end, min_len):
    import re
    rx = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00")

    def mins(s):
        if not isinstance(s, str) or not rx.fullmatch(s):
            raise ValueError
        return int(s[:2]) * 60 + int(s[3:])

    try:
        ds, de = mins(day_start), mins(day_end)
        busy = []
        for offset, intervals in calendars:
            for s, e in intervals:
                a, b = mins(s), mins(e)
                if b > a:
                    busy.append((a - offset, b - offset))
    except ValueError:
        return None
    if min_len < 1:
        return None
    if de <= ds:
        return []
    free = [True] * (de - ds)
    for a, b in busy:
        for m in range(max(a, ds), min(b, de)):
            free[m - ds] = False

    def fmt(m):
        return "%02d:%02d" % (m // 60, m % 60)

    out = []
    m = 0
    n = len(free)
    while m < n:
        if free[m]:
            k = m
            while k < n and free[k]:
                k += 1
            if k - m >= min_len:
                out.append([fmt(ds + m), fmt(ds + k)])
            m = k
        else:
            m += 1
    return out


def min_coins_lex(coins, amount):
    from collections import deque
    if amount < 0:
        return None
    if amount == 0:
        return []
    denoms = sorted({c for c in coins if c > 0}, reverse=True)
    # BFS on remaining amount, from amount down to 0: dist = coins used so far
    dist = {amount: 0}
    q = deque([amount])
    while q:
        r = q.popleft()
        if r == 0:
            break
        for c in denoms:
            nr = r - c
            if nr >= 0 and nr not in dist:
                dist[nr] = dist[r] + 1
                q.append(nr)
    if 0 not in dist:
        return None
    # distance from each remainder to 0 (backward BFS from 0 upward)
    to0 = {0: 0}
    q = deque([0])
    while q:
        r = q.popleft()
        for c in denoms:
            nr = r + c
            if nr <= amount and nr not in to0:
                to0[nr] = to0[r] + 1
                q.append(nr)
    out = []
    r = amount
    while r > 0:
        for c in denoms:  # largest first
            if r - c >= 0 and (r - c) in to0 and to0[r - c] == to0[r] - 1:
                out.append(c)
                r -= c
                break
    return out


def render_table(headers, rows, aligns):
    if len(aligns) != len(headers) or any(a not in "lrc" for a in aligns):
        return None
    if any(len(r) > len(headers) for r in rows):
        return None
    if not headers:
        return []

    def cell(v):
        return str(v).replace("|", "\\|")

    head = [cell(h) for h in headers]
    body = [[cell(v) for v in r] + [""] * (len(headers) - len(r)) for r in rows]
    widths = [max([3, len(head[i])] + [len(r[i]) for r in body]) for i in range(len(headers))]

    def line(vals):
        parts = []
        for v, w, a in zip(vals, widths, aligns):
            extra = w - len(v)
            if a == "l":
                t = v + " " * extra
            elif a == "r":
                t = " " * extra + v
            else:
                t = " " * (extra // 2) + v + " " * (extra - extra // 2)
            parts.append(" " + t + " ")
        return "|" + "|".join(parts) + "|"

    seps = []
    for w, a in zip(widths, aligns):
        if a == "l":
            seps.append(":" + "-" * (w + 1))
        elif a == "r":
            seps.append("-" * (w + 1) + ":")
        else:
            seps.append(":" + "-" * w + ":")
    return [line(head), "|" + "|".join(seps) + "|"] + [line(r) for r in body]


def decode_repeat(text):
    LIMIT = 10000
    # frames: [count, pieces(list of str) or None if overflowed, length (capped at LIMIT+1)]
    frames = [[1, [], 0]]

    def add_text(s):
        f = frames[-1]
        f[2] = min(LIMIT + 1, f[2] + len(s))
        if f[1] is not None:
            if f[2] > LIMIT:
                f[1] = None
            else:
                f[1].append(s)

    i, L = 0, len(text)
    while i < L:
        c = text[i]
        if c == "\\":
            if i + 1 >= L:
                return None
            add_text(text[i + 1])
            i += 2
        elif "0" <= c <= "9":
            j = i
            while j < L and "0" <= text[j] <= "9":
                j += 1
            if j < L and text[j] == "[":
                frames.append([int(text[i:j]), [], 0])
                i = j + 1
            else:
                add_text(text[i:j])
                i = j
        elif c == "[":
            return None
        elif c == "]":
            if len(frames) == 1:
                return None
            cnt, pieces, ln = frames.pop()
            if cnt == 0 or ln == 0:
                total, s = 0, ""
            else:
                total = min(LIMIT + 1, cnt * ln)
                s = "".join(pieces) * cnt if (pieces is not None and total <= LIMIT) else None
            f = frames[-1]
            f[2] = min(LIMIT + 1, f[2] + total)
            if f[1] is not None:
                if f[2] > LIMIT or s is None:
                    f[1] = None
                else:
                    f[1].append(s)
            i += 1
        else:
            add_text(c)
            i += 1
    if len(frames) != 1:
        return None
    if frames[0][2] > LIMIT or frames[0][1] is None:
        return None
    return "".join(frames[0][1])


def grid_portals(grid):
    from collections import deque
    allowed = set("SE.#abcdefghijklmnopqrstuvwxyz")
    starts, exits, portals = [], [], {}
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if ch not in allowed:
                return None
            if ch == "S":
                starts.append((r, c))
            elif ch == "E":
                exits.append((r, c))
            elif "a" <= ch <= "z":
                portals.setdefault(ch, []).append((r, c))
    if len(starts) != 1 or len(exits) != 1:
        return None
    if any(len(v) != 2 for v in portals.values()):
        return None
    twin = {}
    for a, b in portals.values():
        twin[a], twin[b] = b, a
    src, dst = starts[0], exits[0]
    dist = {src: 0}
    q = deque([src])
    while q:
        r, c = q.popleft()
        if (r, c) == dst:
            return dist[(r, c)]
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < len(grid) and 0 <= nc < len(grid[nr]) and grid[nr][nc] != "#":
                land = twin.get((nr, nc), (nr, nc))
                if land not in dist:
                    dist[land] = dist[(r, c)] + 1
                    q.append(land)
    return -1


def lru_ttl(capacity, ops):
    order = []      # keys, least recently used first
    store = {}      # key -> (value, expiry)
    out = []
    for op in ops:
        kind = op[0]
        if kind == "get":
            _, t, key = op
            if key in store and t < store[key][1]:
                order.remove(key)
                order.append(key)
                out.append(store[key][0])
            else:
                out.append(None)
        elif kind == "set":
            _, t, key, value, ttl = op
            if ttl <= 0:
                if key in store:
                    del store[key]
                    order.remove(key)
                continue
            for k in [k for k in order if not (t < store[k][1])]:
                del store[k]
                order.remove(k)
            if key in store:
                store[key] = (value, t + ttl)
                order.remove(key)
                order.append(key)
                continue
            if capacity == 0:
                continue
            if len(order) >= capacity:
                victim = order.pop(0)
                del store[victim]
            store[key] = (value, t + ttl)
            order.append(key)
    return out
