"""A line-oriented script language for keeping books.

One command per line; blank lines and lines starting with ``#`` are
ignored.  Amounts use a dot and at most two decimals; dates are ISO::

    account 6200 "Travel"
    customer ACME "Acme Ltd" net 30 discount 2 within 10
    invoice INV-1 to ACME on 2026-05-04 : 3 x "Widget" @ 10.00 S, 1 x "Setup" @ 50.00 S less 10
    credit CN-1 for INV-1 on 2026-05-06 : 1 x "Widget" @ 10.00 S
    pay P-1 from ACME 1205.40 on 2026-05-14
    prepaid ACME on 2026-06-01
    entry on 2026-05-31 "May rent" : 6000 dr 1500.00, 1000 cr 1500.00
    close through 2026-04-30
    close year 2026-12-31
    balance 1100
    trial
    statement ACME
    aged on 2026-06-30
    vat from 2026-05-01 to 2026-05-31

An invoice line is ``<quantity> x "<description>" @ <unit price> <VAT code>``,
optionally followed by ``less <percent>`` and ``to <income account>``.

``replay`` runs the lines in order and returns ``(books, results)``.  It
stops at the first failing line by raising :class:`ScriptError` with that
line number.
"""
from .books import Books
from .errors import ScriptError, TallyError
from .invoices import make_line
from .money import fmt, parse_amount, parse_date


def tokenize(text, line=0):
    """Split one line into words; double quotes group words, ``:`` and ``,`` stand alone."""
    tokens, current, quoted = [], [], False
    for char in text:
        if quoted:
            if char == '"':
                quoted = False
                tokens.append("".join(current))
                current = []
            else:
                current.append(char)
        elif char == '"':
            if current:
                raise ScriptError(line, "quote inside a word")
            quoted = True
        elif char.isspace() or char in ":,":
            if current:
                tokens.append("".join(current))
                current = []
            if not char.isspace():
                tokens.append(char)
        else:
            current.append(char)
    if quoted:
        raise ScriptError(line, "unterminated quote")
    if current:
        tokens.append("".join(current))
    return tokens


def _expect(words, index, word):
    if index >= len(words) or words[index] != word:
        raise TallyError(f"expected {word!r}")


def _items(words):
    """Split the words after ``:`` into comma separated groups."""
    if ":" not in words:
        raise TallyError("missing ':' before the lines")
    groups, current = [], []
    for word in words[words.index(":") + 1:]:
        if word == ",":
            groups.append(current)
            current = []
        else:
            current.append(word)
    groups.append(current)
    if any(not group for group in groups):
        raise TallyError("empty line item")
    return groups


def _invoice_line(group):
    if len(group) < 5 or group[1] != "x" or group[3] != "@":
        raise TallyError("an item is: <qty> x \"<description>\" @ <price> [<code>] [less <pct>] [to <account>]")
    options = {"code": "S", "less": "0", "to": "4000"}
    rest = group[5:]
    if len(group) > 5 and group[5] not in ("less", "to"):
        options["code"], rest = group[5], group[6:]
    while rest:
        if len(rest) < 2 or rest[0] not in ("less", "to"):
            raise TallyError(f"unexpected {' '.join(rest)!r}")
        options[rest[0]], rest = rest[1], rest[2:]
    return make_line(group[2], group[0], group[4], options["code"], options["less"], options["to"])


def execute(books, words):
    """Run one tokenized command; returns a result dict."""
    command, args = words[0], words[1:]
    if command == "account" and len(args) == 2:
        books.add_account(args[0], args[1])
        return {"command": command}
    if command == "customer" and len(args) in (4, 8):
        _expect(args, 2, "net")
        discount, within = "0", 0
        if len(args) == 8:
            _expect(args, 4, "discount")
            _expect(args, 6, "within")
            discount, within = args[5], int(args[7])
        books.add_customer(args[0], args[1], int(args[3]), discount, within)
        return {"command": command}
    if command in ("invoice", "credit") and len(args) >= 6:
        _expect(args, 1, "to" if command == "invoice" else "for")
        _expect(args, 3, "on")
        lines = [_invoice_line(group) for group in _items(args)]
        method = books.invoice if command == "invoice" else books.credit_note
        doc = method(args[0], args[2], parse_date(args[4]), lines)
        return {"command": command, "number": doc.number, "gross": fmt(doc.gross)}
    if command == "pay" and len(args) == 6:
        _expect(args, 1, "from")
        _expect(args, 4, "on")
        payment = books.receive(args[0], args[2], parse_amount(args[3]), parse_date(args[5]))
        return {"command": command, "allocations": [[n, fmt(t), fmt(d)] for n, t, d in payment.allocations],
                "unapplied": fmt(payment.unapplied)}
    if command == "prepaid" and len(args) == 3:
        _expect(args, 1, "on")
        return {"command": command, "used": fmt(books.apply_prepayment(args[0], parse_date(args[2])))}
    if command == "entry" and len(args) >= 6:
        _expect(args, 0, "on")
        lines = []
        for group in _items(args):
            if len(group) != 3 or group[1] not in ("dr", "cr"):
                raise TallyError("an entry line is: <account> dr|cr <amount>")
            cents = parse_amount(group[2])
            lines.append((group[0], cents, 0) if group[1] == "dr" else (group[0], 0, cents))
        entry = books.journal(parse_date(args[1]), args[2], lines)
        return {"command": command, "number": entry.number}
    if command == "close" and len(args) == 2 and args[0] in ("through", "year"):
        if args[0] == "through":
            books.close_period(parse_date(args[1]))
        else:
            books.close_year(parse_date(args[1]))
        return {"command": command}
    if command == "balance" and len(args) == 1:
        return {"command": command, "balance": fmt(books.balance(args[0]))}
    if command == "trial" and not args:
        return {"command": command, "rows": books.trial_balance()}
    if command == "statement" and len(args) == 1:
        return {"command": command, "lines": books.statement(args[0])}
    if command == "aged" and len(args) == 2 and args[0] == "on":
        return {"command": command, "rows": books.aged_receivables(parse_date(args[1]))}
    if command == "vat" and len(args) == 4 and args[0] == "from" and args[2] == "to":
        return {"command": command, "rows": books.vat_report(parse_date(args[1]), parse_date(args[3]))}
    raise TallyError(f"cannot understand {' '.join(words)!r}")


def replay(text, books=None):
    """Run a script; returns ``(books, results)``."""
    books = books if books is not None else Books()
    results = []
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        words = tokenize(stripped, number)
        try:
            results.append(execute(books, words))
        except ScriptError:
            raise
        except (TallyError, ValueError) as exc:
            raise ScriptError(number, str(exc)) from exc
    return books, results
