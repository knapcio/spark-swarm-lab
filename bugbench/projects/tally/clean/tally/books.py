"""``Books``: one object wiring the chart, the ledger, invoices and payments together."""
from . import reports
from .errors import TallyError
from .invoices import InvoiceBook, Terms, make_line
from .ledger import Chart, Ledger, Posting
from .money import check_cents, check_date, parse_amount, parse_percent
from .payments import PaymentBook


class Books:
    def __init__(self, chart=None):
        self.chart = chart or Chart()
        self.ledger = Ledger(self.chart)
        self.invoices = InvoiceBook(self.ledger)
        self.payments = PaymentBook(self.ledger, self.invoices)

    # -- master data ----------------------------------------------------------------
    def add_account(self, code, name):
        return self.chart.add(code, name)

    def add_customer(self, customer_id, name, days=30, discount="0", discount_days=0):
        return self.invoices.add_customer(customer_id, name, Terms(days, parse_percent(discount), discount_days))

    # -- documents ------------------------------------------------------------------
    def invoice(self, number, customer_id, issued, lines, terms=None):
        """Issue an invoice.  ``lines`` are ``Line`` objects or tuples for :func:`make_line`."""
        built = [line if not isinstance(line, tuple) else make_line(*line) for line in lines]
        return self.invoices.issue(number, customer_id, issued, built, terms)

    def credit_note(self, number, invoice_number, issued, lines):
        built = [line if not isinstance(line, tuple) else make_line(*line) for line in lines]
        return self.invoices.credit_note(number, invoice_number, issued, built)

    def receive(self, payment_id, customer_id, amount, on):
        """Record a customer payment; ``amount`` is cents or text like ``"120.50"``."""
        cents = parse_amount(amount) if isinstance(amount, str) else amount
        return self.payments.receive(payment_id, customer_id, cents, on)

    def apply_prepayment(self, customer_id, on):
        return self.payments.apply_prepayment(customer_id, on)

    # -- general ledger -------------------------------------------------------------
    def journal(self, date, memo, lines):
        """Post a manual entry from ``(account, debit, credit)`` tuples in cents."""
        postings = []
        for line in lines:
            if not isinstance(line, tuple) or len(line) != 3:
                raise TallyError(f"expected (account, debit, credit), got {line!r}")
            account, dr, cr = line
            postings.append(Posting(account, check_cents(dr), check_cents(cr)))
        return self.ledger.post(date, memo, postings, source="manual")

    def close_period(self, through):
        self.ledger.close_period(through)

    def close_year(self, year_end):
        return self.ledger.close_year(year_end)

    def balance(self, account, until=None):
        if until is not None:
            check_date(until)
        return self.ledger.balance(account, until)

    # -- reports --------------------------------------------------------------------
    def trial_balance(self, until=None):
        return reports.trial_balance(self.ledger, until)

    def balance_sheet(self, on):
        return reports.balance_sheet(self.ledger, check_date(on))

    def income_statement(self, start, end):
        return reports.income_statement(self.ledger, check_date(start), check_date(end))

    def vat_report(self, start, end):
        return reports.vat_report(self.invoices, check_date(start), check_date(end))

    def aged_receivables(self, on):
        return reports.aged_receivables(self.invoices, check_date(on))

    def statement(self, customer_id):
        return reports.statement(self.invoices, self.payments, customer_id)
