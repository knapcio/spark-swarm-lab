"""Hidden behavioural probes for the tally project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY 5e6f1d2a-bugbench-tally-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes only use behaviour documented
in ``README.md`` and docstrings.
"""
import datetime

D = datetime.date


def _error(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__
    return None


def _books():
    from tally import Books
    books = Books()
    books.add_customer("ACME", "Acme Ltd", days=30, discount="2", discount_days=10)
    books.add_customer("BETA", "Beta", days=14)
    books.add_customer("GAMMA", "Gamma", days=21, discount="1.5", discount_days=7)
    return books


def _doc(doc):
    return [doc.number, doc.net, doc.tax, doc.gross, doc.open, [[t.code, t.net, t.tax] for t in doc.tax_lines]]


def _postings(entry):
    return [entry.number, str(entry.date), entry.memo, [[p.account, p.debit, p.credit] for p in entry.postings]]


# --- money, chart, ledger -------------------------------------------------------------
def probe_money_parsing():
    from decimal import Decimal
    from tally.money import (check_cents, fmt, parse_amount, parse_date, parse_percent, parse_quantity, percent_of,
                             round_cents)
    out = [parse_amount("0.5"), parse_amount(" 12 "), parse_amount("-3.07", allow_negative=True), parse_amount("100.10"),
           [_error(parse_amount, text) for text in ("-3.07", "1.234", "", "1,5", ".5")], _error(parse_amount, 12),
           [fmt(v) for v in (0, 7, -7, 100, -12345, 99)],
           [round_cents(Decimal(v)) for v in ("12.5", "-12.5", "12.49", "0.5", "-0.4")], _error(round_cents, 1.5),
           _error(round_cents, True), percent_of(12345, Decimal(23)), percent_of(250, Decimal("2")),
           [str(parse_percent(t)) for t in ("0", "12.5", "100")], [_error(parse_percent, t) for t in ("100.01", "-1", "x")],
           [str(parse_quantity(t)) for t in ("2", "0.25", 3, "1.125")],
           [_error(parse_quantity, t) for t in ("0", "1.2345", True, "-1", 2.5)],
           str(parse_date(" 2028-02-29")), [_error(parse_date, t) for t in ("2026-02-30", "2026-2-01", 20260101)],
           check_cents(0), [_error(check_cents, v) for v in (-1, True, "5", 1.0)], _error(check_cents, 0, positive=True),
           str(parse_date(D(2026, 1, 2))), _error(parse_date, datetime.datetime(2026, 1, 2, 3))]
    return out


def probe_chart_of_accounts():
    from tally import Chart
    from tally.ledger import kind_of
    chart = Chart()
    added = chart.add("6200", " Travel ")
    out = [[kind_of(code) for code in ("1500", "2500", "3100", "4200", "5100", "7000", "9999")],
           [added.code, added.name, added.kind, added.debit_normal], chart.codes("expense"), chart.codes("liability"),
           "1000" in chart, "6999" in chart, len(chart.codes()),
           [_error(chart.add, code, "X") for code in ("6200", "0123", "123", "12345", 6300, "A100")],
           _error(chart.add, "6300", "  "), _error(chart.get, "6999"), _error(chart.codes, "revenue"),
           [chart.get(code).signed(500) for code in ("1000", "2200", "3000", "4000", "5900")]]
    chart.add("1500", "Equipment")
    chart.add("1050", "Petty cash")
    out.append([chart.codes("asset"), chart.codes()[:4]])
    return out


def probe_ledger_post_validation():
    from tally import Books, Posting
    from tally.ledger import credit, debit
    books = Books()
    post = books.ledger.post
    day = D(2026, 3, 2)
    out = [_error(post, day, "", [debit("1000", 1), credit("3000", 1)]),
           _error(post, day, "One", [debit("1000", 1)]),
           _error(post, day, "Both", [Posting("1000", 5, 5), credit("3000", 0)]),
           _error(post, day, "Neither", [Posting("1000"), debit("6000", 1), credit("1000", 1)]),
           _error(post, day, "Negative", [debit("1000", -5), credit("3000", -5)]),
           _error(post, day, "Bool", [debit("1000", True), credit("3000", True)]),
           _error(post, day, "Unknown", [debit("1999", 5), credit("3000", 5)]),
           _error(post, day, "Unbalanced", [debit("1000", 5), credit("3000", 4)]),
           _error(post, datetime.datetime(2026, 3, 2, 9), "Time", [debit("1000", 5), credit("3000", 5)]),
           _error(post, day, "Tuple", [("1000", 5, 0), ("3000", 0, 5)]),
           books.ledger.entries()]
    first = post(day, "  Capital ", [debit("1000", 100000), credit("3000", 100000)])
    second = books.journal(D(2026, 3, 5), "Rent", [("6000", 30000, 0), ("1000", 0, 30000)])
    third = books.journal(D(2026, 3, 9), "Split", [("6000", 1000, 0), ("6100", 500, 0), ("1000", 0, 1500)])
    out += [_postings(first), _postings(second), third.total, first.source, second.source,
            [e.number for e in books.ledger.entries("6000")], [e.number for e in books.ledger.entries(start=D(2026, 3, 5))],
            [e.number for e in books.ledger.entries(end=D(2026, 3, 5))], [e.number for e in books.ledger.entries("6100", D(2026, 3, 9), D(2026, 3, 9))],
            _error(books.ledger.entries, "6999"), _error(books.journal, day, "Short", [("6000", 1)]),
            _error(books.journal, day, "Float", [("6000", 1.0, 0), ("1000", 0, 1)])]
    return out


def probe_ledger_balances():
    books = _books()
    books.journal(D(2026, 1, 2), "Capital", [("1000", 1000000, 0), ("3000", 0, 1000000)])
    books.journal(D(2026, 1, 20), "Rent", [("6000", 250000, 0), ("1000", 0, 250000)])
    books.journal(D(2026, 2, 3), "Refund", [("1000", 5000, 0), ("6000", 0, 5000)])
    balances = books.ledger.balances()
    balances["1000"] = 1
    balances["9999"] = 2
    return [books.balance("1000"), books.balance("3000"), books.balance("6000"), books.balance("1000", D(2026, 1, 31)),
            books.balance("6000", D(2026, 1, 19)), books.balance("4000"), books.ledger.balances(),
            books.ledger.balances(D(2026, 1, 20)), books.ledger.balances(D(2026, 1, 1)), _error(books.balance, "1999"),
            _error(books.balance, "1000", "2026-01-31"), books.ledger.net("1000", D(2026, 1, 20), D(2026, 2, 3))]


def probe_closed_periods():
    books = _books()
    books.journal(D(2026, 1, 2), "Capital", [("1000", 50000, 0), ("3000", 0, 50000)])
    books.close_period(D(2026, 1, 31))
    out = [books.ledger.closed_through.isoformat(),
           _error(books.journal, D(2026, 1, 31), "Late", [("6000", 100, 0), ("1000", 0, 100)]),
           _error(books.journal, D(2026, 1, 15), "Late", [("6000", 100, 0), ("1000", 0, 100)]),
           books.journal(D(2026, 2, 1), "On time", [("6000", 100, 0), ("1000", 0, 100)]).number,
           _error(books.close_period, D(2026, 1, 30)), _error(books.close_period, "2026-02-28")]
    books.close_period(D(2026, 1, 31))
    books.close_period(D(2026, 2, 28))
    out += [books.ledger.closed_through.isoformat(), books.ledger.is_open(D(2026, 2, 28)), books.ledger.is_open(D(2026, 3, 1)),
            _error(books.invoice, "INV-9", "BETA", D(2026, 2, 10), [("Audit", "1", "10.00", "S")]),
            _error(books.invoices.get, "INV-9"), books.balance("1100"), len(books.ledger.entries())]
    return out


def probe_close_year():
    books = _books()
    books.journal(D(2025, 6, 1), "Old sale", [("1000", 80000, 0), ("4000", 0, 80000)])
    books.journal(D(2025, 7, 1), "Old rent", [("6000", 30000, 0), ("1000", 0, 30000)])
    first = books.close_year(D(2025, 12, 31))
    books.journal(D(2026, 3, 1), "Sale", [("1000", 10000, 0), ("4100", 0, 10000)])
    books.journal(D(2026, 4, 1), "Rent", [("6000", 40000, 0), ("1000", 0, 40000)])
    statement = books.income_statement(D(2025, 1, 1), D(2025, 12, 31))
    second = books.close_year(D(2026, 12, 31))
    out = [_postings(first), _postings(second), books.balance("3200"), books.balance("4000"), books.balance("6000"),
           statement, books.income_statement(D(2026, 1, 1), D(2026, 12, 31)), books.ledger.closed_through.isoformat(),
           _error(books.close_year, D(2026, 6, 30)), books.close_year(D(2027, 12, 31)), books.ledger.closed_through.isoformat()]
    profit = _books()
    profit.journal(D(2026, 3, 1), "Sale", [("1000", 9000, 0), ("4000", 0, 9000)])
    out.append(_postings(profit.close_year(D(2026, 12, 31))))
    even = _books()
    even.journal(D(2026, 3, 1), "Sale", [("1000", 5000, 0), ("4000", 0, 5000)])
    even.journal(D(2026, 3, 2), "Rent", [("6000", 5000, 0), ("1000", 0, 5000)])
    out.append(_postings(even.close_year(D(2026, 12, 31))))
    return out


# --- documents -------------------------------------------------------------------------
def probe_lines_and_terms():
    from tally import Terms, make_line
    lines = [make_line(" Paper ", "3", "0.15", "S", "50"), make_line("Cable", "2.5", "3.99", "R"),
             make_line("Ink", "0.125", "8.00", "P", "12.5"), make_line("Free", "1", "0.00", "Z"), make_line("Fee", 1, 1999, "E")]
    out = [[[line.description, str(line.quantity), line.unit_price, line.tax_code, str(line.discount), line.net] for line in lines]]
    out.append([_error(make_line, *args) for args in (("", "1", "1.00"), ("X", "0", "1.00"), ("X", "1", "-1.00"),
                                                       ("X", "1", "1.00", "Q"), ("X", "1", "1.00", "S", "101"),
                                                       ("X", "1", "1.234"), ("X", "1", True), ("X", "1", -5))])
    terms = Terms(14, "3", 5)
    out.append([terms.describe(), Terms().describe(), Terms(0).describe(), str(terms.discount)])
    out.append([_error(Terms, *args) for args in ((-1,), (366,), (True,), (10, "2", 11), (10, "2", 0), (10, "0", 3), (10, "x", 3))])
    out.append([Terms(365, "100", 365).describe(), Terms(10, "2", 10).describe()])
    return out


def probe_invoice_posting():
    from tally import Line
    books = _books()
    invoice = books.invoice("INV-1", "BETA", D(2026, 5, 4), [("Audit", "2", "150.00", "S"), ("Training", "1", "99.99", "S", "0", "4100"),
                                                             ("Book", "3", "20.00", "P"), ("Export", "1", "40.00", "Z"),
                                                             ("Insurance", "1", "12.34", "E")])
    other = books.invoice("INV-2", "ACME", D(2026, 5, 6), [Line("Hours", __import__("decimal").Decimal("7.5"), 8000, "R", account="4100"),
                                                           Line("Kit", __import__("decimal").Decimal("2"), 10000, "S")])
    entries = books.ledger.entries()
    out = [_doc(invoice), _doc(other), [_postings(e) for e in entries], str(invoice.due), str(invoice.discount_date),
           str(other.due), str(other.discount_date), invoice.kind, invoice.customer_id]
    out.append([_error(books.invoice, "INV-1", "BETA", D(2026, 5, 4), [("X", "1", "1.00")]),
                _error(books.invoice, "INV-3", "NOBODY", D(2026, 5, 4), [("X", "1", "1.00")]),
                _error(books.invoice, "inv-3", "BETA", D(2026, 5, 4), [("X", "1", "1.00")]),
                _error(books.invoice, "INV-3", "BETA", D(2026, 5, 4), []),
                _error(books.invoice, "INV-3", "BETA", D(2026, 5, 4), [("X", "1", "0.00")]),
                _error(books.invoice, "INV-3", "BETA", D(2026, 5, 4), [("X", "1", "1.00", "S", "100")]),
                _error(books.invoice, "INV-3", "BETA", D(2026, 5, 4), [("X", "1", "1.00", "S", "0", "6000")]),
                _error(books.invoice, "INV-3", "BETA", D(2026, 5, 4), [("X", "1", "1.00", "S", "0", "4999")]),
                _error(books.invoice, "INV-3", "BETA", "2026-05-04", [("X", "1", "1.00")]),
                _error(books.invoice, "INV-3", "BETA", D(2026, 5, 4), ["X"])])
    out.append([len(books.ledger.entries()), [d.number for d in books.invoices.documents()]])
    out.append([_error(books.add_customer, "BETA", "Again"), _error(books.add_customer, "b-1", "x"),
                _error(books.add_customer, "DELTA", " "), _error(books.invoices.add_customer, "DELTA", "D", "net 30"),
                _error(books.invoices.customer, "NOBODY"), books.invoices.customer("GAMMA").terms.describe()])
    return out


def probe_credit_notes():
    books = _books()
    books.invoice("INV-1", "BETA", D(2026, 5, 4), [("Audit", "1", "200.00", "S"), ("Guide", "1", "40.00", "P")])
    note = books.credit_note("CN-1", "INV-1", D(2026, 5, 9), [("Guide returned", "1", "40.00", "P")])
    out = [_doc(note), note.kind, note.against, note.customer_id, books.invoices.get("INV-1").open,
           _postings(books.ledger.entries()[-1]), books.balance("1100"), books.balance("2200"), books.balance("4000")]
    out.append([_error(books.credit_note, "CN-2", "INV-1", D(2026, 5, 3), [("X", "1", "1.00")]),
                _error(books.credit_note, "CN-2", "CN-1", D(2026, 5, 10), [("X", "1", "1.00")]),
                _error(books.credit_note, "CN-2", "INV-9", D(2026, 5, 10), [("X", "1", "1.00")]),
                _error(books.credit_note, "CN-2", "INV-1", D(2026, 5, 10), [("X", "2", "100.01", "S")]),
                _error(books.credit_note, "CN-1", "INV-1", D(2026, 5, 10), [("X", "1", "1.00")])])
    out.append(_error(books.credit_note, "CN-0", "INV-1", D(2026, 5, 10), [("Nothing", "1", "0.00", "S")]))
    exact = books.credit_note("CN-3", "INV-1", D(2026, 5, 10), [("Rest", "1", "200.00", "S")])
    out += [exact.gross, books.invoices.get("INV-1").open, _error(books.credit_note, "CN-4", "INV-1", D(2026, 5, 11), [("X", "1", "0.01")])]
    books.invoice("INV-2", "BETA", D(2026, 5, 20), [("Audit", "1", "10.00", "S")])
    same_day = books.credit_note("CN-6", "INV-2", D(2026, 5, 20), [("Audit", "1", "1.00", "S")])
    out.append([same_day.gross, books.invoices.get("INV-2").open])
    books.close_period(D(2026, 5, 31))
    out += [_error(books.credit_note, "CN-5", "INV-2", D(2026, 5, 31), [("X", "1", "1.00")]),
            books.invoices.get("INV-2").open, _error(books.invoices.get, "CN-5"),
            [d.number for d in books.invoices.documents("BETA", "credit")]]
    return out


# --- payments --------------------------------------------------------------------------
def probe_payment_allocation_order():
    books = _books()
    books.invoice("B-1", "BETA", D(2026, 5, 10), [("Audit", "1", "100.00", "S")])
    books.invoice("B-2", "BETA", D(2026, 5, 2), [("Audit", "1", "50.00", "S")])
    books.invoice("B-3", "BETA", D(2026, 5, 10), [("Audit", "1", "20.00", "S")], terms=__import__("tally").Terms(0))
    books.invoice("B-4", "BETA", D(2026, 6, 1), [("Audit", "1", "30.00", "S")])
    first = books.receive("P-1", "BETA", "100.00", D(2026, 5, 20))
    second = books.receive("P-2", "BETA", 20000, D(2026, 5, 25))
    books.invoice("B-5", "BETA", D(2026, 6, 3), [("Audit", "1", "10.00", "S")])
    same_day = books.receive("P-9", "BETA", "50.00", D(2026, 6, 3))
    out = [list(same_day.allocations), same_day.unapplied]
    out += [list(first.allocations), first.unapplied, list(second.allocations), second.unapplied, second.discount,
           books.payments.prepaid("BETA"), [d.open for d in books.invoices.documents("BETA")],
           _postings(books.ledger.entries()[-1]), [p.payment_id for p in books.payments.payments("BETA")]]
    out.append([_error(books.receive, "P-1", "BETA", "1.00", D(2026, 6, 2)), _error(books.receive, "P-3", "BETA", "0.00", D(2026, 6, 2)),
                _error(books.receive, "P-3", "NOBODY", "1.00", D(2026, 6, 2)), _error(books.receive, "p 3", "BETA", "1.00", D(2026, 6, 2)),
                _error(books.receive, "P-3", "BETA", "-1.00", D(2026, 6, 2)), _error(books.receive, "P-3", "BETA", "1.00", "2026-06-02"),
                _error(books.payments.prepaid, "NOBODY"), len(books.payments.payments())])
    return out


def probe_early_discount_inside_window():
    books = _books()
    books.invoice("A-1", "ACME", D(2026, 5, 4), [("Widget", "10", "10.00", "S")])
    books.invoice("A-2", "ACME", D(2026, 5, 6), [("Widget", "5", "10.00", "S")])
    early = books.receive("P-1", "ACME", "181.00", D(2026, 5, 7))
    out = [list(early.allocations), early.unapplied, early.discount, books.balance("5900"), books.balance("1100")]
    books.invoice("A-3", "ACME", D(2026, 5, 8), [("Widget", "10", "10.00", "S")])
    partial = books.receive("P-2", "ACME", "100.00", D(2026, 5, 9))
    rest = books.receive("P-3", "ACME", "20.54", D(2026, 5, 10))
    out += [list(partial.allocations), list(rest.allocations), books.invoices.get("A-3").open]
    books.invoice("G-1", "GAMMA", D(2026, 5, 4), [("Service", "1", "333.33", "S", "0", "4100")])
    late = books.receive("P-4", "GAMMA", "403.85", D(2026, 5, 12))
    out += [list(late.allocations), books.invoices.get("G-1").open, books.invoices.get("G-1").discount_taken]
    books.invoice("G-2", "GAMMA", D(2026, 6, 1), [("Service", "1", "100.00", "S", "0", "4100")])
    books.credit_note("GC-1", "G-2", D(2026, 6, 2), [("Service credit", "1", "50.00", "S", "0", "4100")])
    credited = books.receive("P-5", "GAMMA", "65.00", D(2026, 6, 3))
    out += [list(credited.allocations), credited.unapplied, books.invoices.get("G-2").open]
    return out


def probe_prepayments():
    books = _books()
    out = [books.apply_prepayment("BETA", D(2026, 5, 1))]
    books.receive("P-1", "ACME", "500.00", D(2026, 5, 1))
    books.invoice("A-1", "ACME", D(2026, 5, 4), [("Widget", "10", "10.00", "S")])
    books.invoice("A-2", "ACME", D(2026, 5, 20), [("Widget", "100", "10.00", "S")])
    out += [books.payments.prepaid("ACME"), books.apply_prepayment("ACME", D(2026, 5, 5)), books.payments.prepaid("ACME"),
            [d.open for d in books.invoices.documents("ACME")], books.apply_prepayment("ACME", D(2026, 5, 21)),
            books.payments.prepaid("ACME"), [d.open for d in books.invoices.documents("ACME")],
            books.invoices.get("A-1").discount_taken, books.apply_prepayment("ACME", D(2026, 5, 22)),
            _postings(books.ledger.entries()[-1]), books.balance("2100"), _error(books.apply_prepayment, "ACME", "2026-05-22")]
    return out


def probe_rejected_payment_without_discount():
    books = _books()
    books.invoice("B-1", "BETA", D(2026, 4, 20), [("Audit", "1", "100.00", "S")])
    books.invoice("A-1", "ACME", D(2026, 4, 2), [("Widget", "1", "50.00", "S")])
    books.close_period(D(2026, 4, 30))
    out = [_error(books.receive, "P-1", "BETA", "200.00", D(2026, 4, 30)), _error(books.receive, "P-2", "ACME", "61.50", D(2026, 4, 29))]
    out += [[d.open for d in books.invoices.documents()], books.payments.prepaid("BETA"), books.payments.payments(),
            books.balance("1100"), books.balance("1000")]
    again = books.receive("P-1", "BETA", "200.00", D(2026, 5, 2))
    out += [list(again.allocations), again.unapplied, books.statement("BETA")]
    books.receive("P-3", "ACME", "100.00", D(2026, 5, 3))
    books.close_period(D(2026, 5, 31))
    out += [_error(books.apply_prepayment, "ACME", D(2026, 5, 31)), books.payments.prepaid("ACME"), books.statement("ACME")]
    return out


# --- reports and script ----------------------------------------------------------------
def _reporting_books():
    books = _books()
    books.journal(D(2026, 1, 2), "Capital", [("1000", 2000000, 0), ("3000", 0, 2000000)])
    books.invoice("INV-1", "BETA", D(2026, 1, 10), [("Audit", "1", "1000.00", "S"), ("Guide", "2", "45.00", "P")])
    books.invoice("INV-2", "ACME", D(2026, 2, 3), [("Hours", "4", "75.00", "R", "0", "4100"), ("Exempt", "1", "80.00", "E")])
    books.invoice("INV-3", "ACME", D(2026, 3, 1), [("Widget", "1", "20.00", "S")])
    books.credit_note("CN-1", "INV-1", D(2026, 2, 1), [("Guide returned", "1", "45.00", "P")])
    books.receive("P-1", "BETA", "500.00", D(2026, 2, 15))
    books.journal(D(2026, 2, 28), "Rent", [("6000", 150000, 0), ("1000", 0, 150000)])
    return books


def probe_trial_balance_and_sheet():
    books = _reporting_books()
    return [books.trial_balance(), books.trial_balance(D(2026, 1, 31)), books.balance_sheet(D(2026, 2, 28)),
            books.balance_sheet(D(2026, 1, 1)), books.income_statement(D(2026, 2, 1), D(2026, 2, 28)),
            books.income_statement(D(2026, 1, 1), D(2026, 12, 31)), _error(books.balance_sheet, "2026-02-28")]


def probe_vat_report():
    books = _reporting_books()
    return [books.vat_report(D(2026, 1, 1), D(2026, 3, 31)), books.vat_report(D(2026, 2, 1), D(2026, 2, 28)),
            books.vat_report(D(2026, 1, 10), D(2026, 1, 10)), books.vat_report(D(2026, 4, 1), D(2026, 4, 30)),
            _error(books.vat_report, D(2026, 1, 1), "2026-02-01")]


def probe_aged_receivables_buckets():
    from tally import Terms
    books = _books()
    for number, day in (("D-0", 31), ("D-1", 30), ("D-30", 1)):
        books.invoice(number, "BETA", D(2026, 1, day), [("Audit", "1", "10.00", "S")], terms=Terms(0))
    books.invoice("D-31", "ACME", D(2025, 12, 31), [("Audit", "1", "20.00", "S")], terms=Terms(0))
    books.invoice("D-60", "ACME", D(2025, 12, 2), [("Audit", "1", "30.00", "S")], terms=Terms(0))
    books.invoice("D-61", "GAMMA", D(2025, 12, 1), [("Audit", "1", "40.00", "S")], terms=Terms(0))
    books.invoice("D-90", "GAMMA", D(2025, 11, 2), [("Audit", "1", "50.00", "S")], terms=Terms(0))
    books.invoice("D-91", "GAMMA", D(2025, 11, 1), [("Audit", "1", "60.00", "S")], terms=Terms(0))
    books.invoice("FUT", "GAMMA", D(2026, 2, 1), [("Audit", "1", "70.00", "S")], terms=Terms(0))
    books.invoice("PAID", "BETA", D(2025, 6, 1), [("Audit", "1", "80.00", "S")], terms=Terms(0))
    books.receive("P-1", "BETA", "98.40", D(2025, 6, 2))
    return [books.aged_receivables(D(2026, 1, 31)), books.aged_receivables(D(2025, 10, 1)), _error(books.aged_receivables, None)]


def probe_statement_lines():
    books = _reporting_books()
    books.receive("P-2", "ACME", "400.00", D(2026, 3, 30))
    return [books.statement("ACME"), books.statement("BETA"), books.statement("GAMMA"), _error(books.statement, "NOBODY")]


def probe_script_replay():
    from tally import replay
    text = ('# books for May\naccount 6200 "Travel costs"\ncustomer ACME "Acme Ltd" net 30 discount 2 within 10\n'
            'customer BETA "Beta" net 14\n'
            'invoice INV-1 to ACME on 2026-05-04 : 3 x "Widget, blue" @ 10.00 S, 1 x "Setup" @ 50.00 R less 10, 2 x "Guide" @ 30.00 P to 4100\n'
            'invoice INV-2 to BETA on 2026-05-05 : 1 x "Consulting" @ 1000.00 S to 4100, 1 x "Travel" @ 20.00\n'
            'credit CN-1 for INV-1 on 2026-05-06 : 1 x "Widget, blue" @ 10.00 S\n'
            "pay P-1 from ACME 150.00 on 2026-05-08\npay P-2 from BETA 2000.00 on 2026-05-20\n"
            'entry on 2026-05-31 "Trip" : 6200 dr 150.00, 1000 cr 150.00\nprepaid BETA on 2026-05-31\nbalance 2100\ntrial\n'
            "statement ACME\naged on 2026-06-30\nvat from 2026-05-01 to 2026-05-31\nclose through 2026-05-31\nclose year 2026-12-31\nbalance 3200\n")
    books, results = replay(text)
    return [results, books.chart.get("6200").name]


def probe_script_errors():
    from tally import ScriptError, replay
    from tally.script import tokenize
    out = [tokenize('a "b, c":d,e ""'), tokenize("  x  "), _error(tokenize, 'a"b'), _error(tokenize, '"open')]
    head = 'customer ACME "Acme" net 30\n'
    for bad in ('customer ACME "Acme" net thirty', "customer ACME \"Acme\" days 30", head + 'invoice INV-1 to ACME on 2026-05-04 : 1 x "W" @ 1.00 S less',
                head + 'invoice INV-1 to ACME on 2026-05-04 : 1 x "W" @ 1.00 S,', head + 'invoice INV-1 to ACME on 2026-05-04 1 x "W" @ 1.00',
                head + 'invoice INV-1 for ACME on 2026-05-04 : 1 x "W" @ 1.00', head + 'invoice INV-1 to ACME on 2026-05-04 : 1 * "W" @ 1.00',
                head + 'invoice INV-1 to ACME on 2026-05-04 : 1 x "W" @ 1.00 S extra 3', head + "pay P-1 from ACME 1.00 at 2026-05-04",
                'entry on 2026-05-04 "x" : 6000 dr 1.00, 1000 cr 2.00', 'entry on 2026-05-04 "x" : 6000 debit 1.00, 1000 cr 1.00',
                "close through", "close month 2026-05-31", "balance", "trial now", "aged 2026-06-30", "vat 2026-05-01 2026-05-31",
                "fly to the moon", head + 'customer BETA "B" net 30 discount 2 inside 10', head + "prepaid ACME at 2026-05-01",
                head + 'credit CN-1 to INV-1 on 2026-05-04 : 1 x "W" @ 1.00', 'customer ACME "Acme" net 30 discount 2 within ten',
                head + "refund R-1 from ACME 5.00 on 2026-05-05", head + "balance ACME on 2026-05-01",
                'frobnicate on 2026-05-31 "x" : 6000 dr 1.00, 1000 cr 1.00'):
        try:
            replay(bad)
            out.append(None)
        except ScriptError as exc:
            out.append([exc.line, type(exc.__cause__).__name__ if exc.__cause__ else None])
    return out


# --- target probes: early payment discount on the last day --------------------------------------
def probe_discount_on_last_day():
    books = _books()
    books.invoice("A-1", "ACME", D(2026, 5, 4), [("Widget", "10", "10.00", "S")])
    on_time = books.receive("P-1", "ACME", "120.54", D(2026, 5, 14))
    books.invoice("G-1", "GAMMA", D(2026, 6, 24), [("Service", "1", "200.00", "S", "0", "4100")])
    gamma = books.receive("P-2", "GAMMA", "242.31", D(2026, 7, 1))
    return [list(on_time.allocations), on_time.unapplied, list(gamma.allocations), gamma.unapplied,
            [d.open for d in books.invoices.documents()], books.balance("5900"), books.balance("1100")]


def probe_discount_last_day_reports():
    books = _books()
    books.invoice("A-1", "ACME", D(2026, 3, 20), [("Widget", "4", "25.00", "S"), ("Guide", "1", "40.00", "P")])
    books.invoice("A-2", "ACME", D(2026, 3, 25), [("Widget", "2", "25.00", "S")])
    books.receive("P-1", "ACME", "200.00", D(2026, 3, 30))
    return [books.statement("ACME"), books.aged_receivables(D(2026, 5, 31)), books.trial_balance()]


def probe_discount_last_day_script():
    from tally import replay
    _, results = replay('customer KAPPA "Kappa" net 21 discount 3 within 14\n'
                        'invoice K-7 to KAPPA on 2026-02-15 : 12 x "Seat licence" @ 49.00 S to 4100\n'
                        "pay K-PAY from KAPPA 701.54 on 2026-03-01\nstatement KAPPA\nbalance 5900\n")
    return results[-3:]


# --- target probes: VAT rounded once per code ---------------------------------------------------
def probe_vat_rounded_per_code():
    books = _books()
    office = books.invoice("INV-31", "BETA", D(2026, 5, 4), [("Toner", "1", "189.00", "S"), ("Pens", "12", "1.15", "S"),
                                                              ("Labels", "2", "12.35", "S")])
    mixed = books.invoice("INV-32", "BETA", D(2026, 5, 5), [("Hours", "3", "33.33", "R", "0", "4100"), ("Hours", "1", "16.66", "R", "0", "4100"),
                                                             ("Guide", "1", "10.10", "P"), ("Guide", "1", "10.10", "P"), ("Pen", "1", "1.90", "S")])
    from tally import make_line
    from tally.tax import tax_summary
    direct = tax_summary([make_line("A", "1", "10.02", "S"), make_line("B", "1", "10.02", "S"), make_line("C", "1", "0.10", "P"),
                          make_line("D", "4", "0.10", "P")])
    return [_doc(office), _doc(mixed), books.balance("2200"), books.balance("1100"), [[t.code, t.net, t.tax] for t in direct]]


def probe_vat_per_code_reports():
    books = _books()
    books.invoice("INV-1", "ACME", D(2026, 5, 4), [("Paper", "5", "4.99", "S"), ("Stapler", "1", "24.90", "S"),
                                                   ("Envelopes", "4", "3.65", "S")])
    note = books.credit_note("CN-1", "INV-1", D(2026, 5, 10), [("Paper", "1", "4.99", "S"), ("Stapler", "1", "24.90", "S"),
                                                               ("Envelopes", "1", "3.65", "S")])
    return [_doc(note), books.vat_report(D(2026, 5, 1), D(2026, 5, 31)), books.trial_balance(), books.statement("ACME")]


def probe_vat_per_code_script():
    from tally import replay
    _, results = replay('customer BETA "Beta" net 14\n'
                        'invoice INV-7 to BETA on 2026-06-01 : 12 x "Pens" @ 1.15 S, 3 x "Binder" @ 7.45 S, 2 x "Labels" @ 12.35 S\n'
                        "pay P-7 from BETA 69.84 on 2026-06-05\nstatement BETA\nvat from 2026-06-01 to 2026-06-30\n")
    return results[1:]


# --- target probes: rejected payment with an early payment discount --------------------------------
def probe_rejected_discount_payment_restores_invoice():
    books = _books()
    books.invoice("A-1", "ACME", D(2026, 4, 24), [("Widget", "10", "10.00", "S")])
    books.close_period(D(2026, 4, 30))
    error = _error(books.receive, "P-1", "ACME", "120.54", D(2026, 4, 30))
    invoice = books.invoices.get("A-1")
    return [error, invoice.open, invoice.paid, invoice.discount_taken, books.statement("ACME"), books.payments.payments()]


def probe_rejected_discount_payment_then_repay():
    books = _books()
    books.invoice("A-1", "ACME", D(2026, 4, 24), [("Widget", "10", "10.00", "S")])
    books.invoice("A-2", "ACME", D(2026, 4, 28), [("Widget", "5", "10.00", "S")])
    books.close_period(D(2026, 4, 30))
    error = _error(books.receive, "P-1", "ACME", "180.81", D(2026, 4, 29))
    again = books.receive("P-2", "ACME", "180.81", D(2026, 5, 3))
    return [error, list(again.allocations), again.unapplied, books.statement("ACME"), books.balance("1100"),
            books.balance("5900"), books.aged_receivables(D(2026, 6, 30))]


def probe_rejected_discount_payment_script():
    from tally import ScriptError, replay
    text = ('customer GAMMA "Gamma" net 21 discount 1.5 within 7\n'
            'invoice G-1 to GAMMA on 2026-06-26 : 1 x "Service" @ 400.00 S to 4100\nclose through 2026-06-30\n')
    books, _ = replay(text)
    try:
        replay("pay P-1 from GAMMA 484.62 on 2026-06-30\n", books)
        line = None
    except ScriptError as exc:
        line = [exc.line, type(exc.__cause__).__name__]
    _, results = replay("pay P-2 from GAMMA 484.62 on 2026-07-01\nstatement GAMMA\ntrial\n", books)
    return [line, results]
