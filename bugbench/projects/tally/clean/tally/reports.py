"""Reports.  Amounts are formatted with :func:`tally.money.fmt`; reports never change the books.

* ``trial_balance``: every account with postings, ascending by code, with its
  balance in the debit or the credit column, and a closing total row.
* ``income_statement``: income and expense movements between two dates and
  the result (profit positive, loss negative).  Closing entries are ignored.
* ``balance_sheet``: assets, liabilities and equity on a date, with the
  result not yet closed into retained earnings shown under equity.
* ``vat_report``: per VAT code net and VAT of the invoices less the credit
  notes issued between two dates, as rounded on each document.
* ``aged_receivables``: open invoices per customer by days past due on a
  date: ``current`` (not yet due), ``1-30``, ``31-60``, ``61-90`` and ``90+``.
* ``statement``: a customer's documents with their open amounts, the
  prepayment and the balance due.
"""
from .money import fmt
from .tax import ORDER, TaxLine

BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")


def trial_balance(ledger, until=None):
    rows, debits, credits = [], 0, 0
    for code, balance in ledger.balances(until).items():
        account = ledger.chart.get(code)
        net = balance if account.debit_normal else -balance
        if net >= 0:
            rows.append([code, account.name, fmt(net), ""])
            debits += net
        else:
            rows.append([code, account.name, "", fmt(-net)])
            credits -= net
    rows.append(["total", "", fmt(debits), fmt(credits)])
    return rows


def income_statement(ledger, start, end):
    lines, result = [], 0
    for kind, sign in (("income", 1), ("expense", -1)):
        for code in ledger.chart.codes(kind):
            entries = [entry for entry in ledger.entries(code, start, end) if entry.source != "close"]
            movement = -sum(p.net for entry in entries for p in entry.postings if p.account == code) * sign
            if movement:
                lines.append([code, ledger.chart.get(code).name, fmt(movement)])
                result += movement * sign
    lines.append(["result", "", fmt(result)])
    return lines


def balance_sheet(ledger, on):
    """Asset, liability and equity balances on ``on``; the unclosed result is shown as equity.

    Returns ``[[section or code, name, amount], ...]`` ending with the totals
    of assets and of liabilities plus equity, which are equal for balanced books."""
    balances = ledger.balances(on)
    rows, totals, result = [], {"asset": 0, "other": 0}, 0
    for kind in ("asset", "liability", "equity"):
        rows.append([kind, "", ""])
        for code in ledger.chart.codes(kind):
            if code in balances:
                rows.append([code, ledger.chart.get(code).name, fmt(balances[code])])
                totals["asset" if kind == "asset" else "other"] += balances[code]
    for code, balance in balances.items():
        kind = ledger.chart.get(code).kind
        result += balance if kind == "income" else -balance if kind == "expense" else 0
    if result:
        rows.append(["result", "Unclosed result", fmt(result)])
    rows.append(["total assets", "", fmt(totals["asset"])])
    rows.append(["total liabilities and equity", "", fmt(totals["other"] + result)])
    return rows


def vat_report(invoices, start, end):
    """[[label, net, vat], ...] per VAT code, then a total row; credit notes count negative."""
    sums = {}
    for doc in invoices.documents():
        if not start <= doc.issued <= end:
            continue
        sign = 1 if doc.kind == "invoice" else -1
        for line in doc.tax_lines:
            net, tax = sums.get(line.code, (0, 0))
            sums[line.code] = (net + sign * line.net, tax + sign * line.tax)
    rows = [[TaxLine(code, 0, 0).label(), fmt(sums[code][0]), fmt(sums[code][1])] for code in ORDER if code in sums]
    rows.append(["total", fmt(sum(net for net, _ in sums.values())), fmt(sum(tax for _, tax in sums.values()))])
    return rows


def bucket(days_past_due):
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1-30"
    if days_past_due <= 60:
        return "31-60"
    if days_past_due <= 90:
        return "61-90"
    return "90+"


def aged_receivables(invoices, on):
    """[[customer, current, 1-30, 31-60, 61-90, 90+, total], ...] by customer id, then a total row."""
    table = {}
    for doc in invoices.documents(kind="invoice"):
        if doc.open <= 0 or doc.issued > on:
            continue
        row = table.setdefault(doc.customer_id, dict.fromkeys(BUCKETS, 0))
        row[bucket((on - doc.due).days)] += doc.open
    rows, totals = [], dict.fromkeys(BUCKETS, 0)
    for customer_id in sorted(table):
        row = table[customer_id]
        rows.append([customer_id] + [fmt(row[name]) for name in BUCKETS] + [fmt(sum(row.values()))])
        for name in BUCKETS:
            totals[name] += row[name]
    rows.append(["total"] + [fmt(totals[name]) for name in BUCKETS] + [fmt(sum(totals.values()))])
    return rows


def statement(invoices, payments, customer_id):
    """Lines ``"<number> <issued> <gross> open <open>"`` per document, then prepayment and balance due."""
    invoices.customer(customer_id)
    lines, due = [], 0
    for doc in invoices.documents(customer_id):
        if doc.kind == "invoice":
            lines.append(f"{doc.number} {doc.issued} {fmt(doc.gross)} open {fmt(doc.open)}")
            due += doc.open
        else:
            lines.append(f"{doc.number} {doc.issued} credit {fmt(doc.gross)} for {doc.against}")
    prepaid = payments.prepaid(customer_id)
    lines.append(f"prepaid {fmt(prepaid)}")
    lines.append(f"balance due {fmt(due - prepaid)}")
    return lines
