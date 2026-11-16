"""Customers, payment terms, invoices and credit notes.

A line's net amount is quantity x unit price, less the line discount,
rounded half-up to whole cents.  VAT is summarised per code (see
:mod:`tally.tax`) and the gross total is net plus VAT.

Issuing an invoice posts one entry: receivables are debited with the gross
total, each income account is credited with the net of its lines and VAT
payable with the VAT.  A credit note reverses part of an invoice the same
way and may not exceed the invoice's open amount.

The open amount of an invoice is its gross total less payments, early
payment discounts and credit notes.  It is due ``terms.days`` after the
issue date; the early payment discount, if any, can be earned up to and
including ``terms.discount_days`` after the issue date.
"""
from dataclasses import dataclass, field
from decimal import Decimal
import datetime
import re

from .errors import CreditTooLarge, DuplicateId, InvalidAmount, TallyError, UnknownDocument
from .ledger import RECEIVABLES, SALES, VAT, credit, debit
from .money import HUNDRED, check_cents, check_date, parse_amount, parse_percent, parse_quantity, round_cents
from .tax import check_code, tax_summary, tax_total

_CUSTOMER = re.compile(r"^[A-Z][A-Z0-9-]{0,15}$")
_NUMBER = re.compile(r"^[A-Z][A-Z0-9/-]{0,19}$")


@dataclass(frozen=True)
class Terms:
    days: int = 30
    discount: Decimal = Decimal(0)
    discount_days: int = 0

    def __post_init__(self):
        for value in (self.days, self.discount_days):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 365:
                raise InvalidAmount(f"bad number of days: {value!r}")
        object.__setattr__(self, "discount", parse_percent(self.discount))
        if self.discount_days > self.days:
            raise InvalidAmount("the discount period cannot be longer than the payment term")
        if (self.discount == 0) != (self.discount_days == 0):
            raise InvalidAmount("an early payment discount needs both a percentage and a period")

    def describe(self):
        text = f"net {self.days}"
        return text + f", {self.discount}% within {self.discount_days} days" if self.discount else text


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    terms: Terms = Terms()


@dataclass(frozen=True)
class Line:
    description: str
    quantity: Decimal
    unit_price: int
    tax_code: str = "S"
    discount: Decimal = Decimal(0)
    account: str = SALES

    @property
    def net(self):
        return round_cents(self.quantity * self.unit_price * (HUNDRED - self.discount) / HUNDRED)


def make_line(description, quantity, unit_price, tax_code="S", discount="0", account=SALES):
    """Build a validated :class:`Line` from text values (``unit_price`` like ``"12.50"``)."""
    if not isinstance(description, str) or not description.strip():
        raise InvalidAmount("a line needs a description")
    price = unit_price if isinstance(unit_price, int) and not isinstance(unit_price, bool) else parse_amount(unit_price)
    return Line(description.strip(), parse_quantity(quantity), check_cents(price), check_code(tax_code),
                parse_percent(discount), account)


@dataclass(eq=False)
class Invoice:
    number: str
    customer_id: str
    issued: datetime.date
    terms: Terms
    lines: tuple
    seq: int
    kind: str = "invoice"
    against: object = None
    paid: int = 0
    discount_taken: int = 0
    credited: int = 0
    tax_lines: list = field(init=False)

    def __post_init__(self):
        self.tax_lines = tax_summary(self.lines)

    @property
    def net(self):
        return sum(line.net for line in self.lines)

    @property
    def tax(self):
        return tax_total(self.tax_lines)

    @property
    def gross(self):
        return self.net + self.tax

    @property
    def due(self):
        return self.issued + datetime.timedelta(days=self.terms.days)

    @property
    def discount_date(self):
        if not self.terms.discount:
            return None
        return self.issued + datetime.timedelta(days=self.terms.discount_days)

    @property
    def open(self):
        if self.kind != "invoice":
            return 0
        return self.gross - self.paid - self.discount_taken - self.credited

    def settle(self, amount, discount=0):
        """Record a payment and an early payment discount (negative values undo them)."""
        if amount + discount > self.open:
            raise InvalidAmount(f"{self.number}: settling more than the open amount")
        self.paid += amount
        self.discount_taken += discount


class InvoiceBook:
    def __init__(self, ledger):
        self.ledger = ledger
        self._customers = {}
        self._documents = {}

    # -- customers ----------------------------------------------------------------
    def add_customer(self, customer_id, name, terms=None):
        if not isinstance(customer_id, str) or not _CUSTOMER.match(customer_id):
            raise TallyError(f"bad customer id {customer_id!r}")
        if customer_id in self._customers:
            raise DuplicateId(f"customer {customer_id} already exists")
        if not isinstance(name, str) or not name.strip():
            raise TallyError("a customer needs a name")
        if terms is not None and not isinstance(terms, Terms):
            raise TallyError("terms must be a Terms value")
        customer = Customer(customer_id, name.strip(), terms or Terms())
        self._customers[customer_id] = customer
        return customer

    def customer(self, customer_id):
        try:
            return self._customers[customer_id]
        except (KeyError, TypeError):
            raise UnknownDocument(f"no customer {customer_id!r}") from None

    # -- documents ----------------------------------------------------------------
    def _new_document(self, number, issued, lines):
        if not isinstance(number, str) or not _NUMBER.match(number):
            raise TallyError(f"bad document number {number!r}")
        if number in self._documents:
            raise DuplicateId(f"document {number} already exists")
        check_date(issued)
        lines = tuple(lines)
        if not lines or not all(isinstance(line, Line) for line in lines):
            raise InvalidAmount("a document needs at least one line")
        for line in lines:
            if self.ledger.chart.get(line.account).kind != "income":
                raise InvalidAmount(f"line account {line.account} is not an income account")
        return lines

    def _postings(self, document):
        nets = {}
        for line in document.lines:
            nets[line.account] = nets.get(line.account, 0) + line.net
        return [(code, nets[code]) for code in sorted(nets) if nets[code]] + ([(VAT, document.tax)] if document.tax else [])

    def issue(self, number, customer_id, issued, lines, terms=None):
        """Issue an invoice and post it; the customer's terms apply unless ``terms`` is given."""
        customer = self.customer(customer_id)
        lines = self._new_document(number, issued, lines)
        invoice = Invoice(number, customer_id, issued, terms or customer.terms, lines, len(self._documents) + 1)
        if invoice.gross <= 0:
            raise InvalidAmount("an invoice must have a positive total")
        postings = [debit(RECEIVABLES, invoice.gross)] + [credit(code, cents) for code, cents in self._postings(invoice)]
        self.ledger.post(issued, f"Invoice {number} to {customer_id}", postings, source=number)
        self._documents[number] = invoice
        return invoice

    def credit_note(self, number, invoice_number, issued, lines):
        """Issue a credit note against an invoice; it reduces the invoice's open amount."""
        invoice = self.get(invoice_number)
        if invoice.kind != "invoice":
            raise UnknownDocument(f"{invoice_number} is not an invoice")
        lines = self._new_document(number, issued, lines)
        if issued < invoice.issued:
            raise InvalidAmount("a credit note cannot predate its invoice")
        note = Invoice(number, invoice.customer_id, issued, invoice.terms, lines, len(self._documents) + 1,
                       kind="credit", against=invoice_number)
        if note.gross <= 0:
            raise InvalidAmount("a credit note must have a positive total")
        if note.gross > invoice.open:
            raise CreditTooLarge(f"credit {note.gross} exceeds the open amount {invoice.open} of {invoice_number}")
        postings = [debit(code, cents) for code, cents in self._postings(note)] + [credit(RECEIVABLES, note.gross)]
        self.ledger.post(issued, f"Credit note {number} for {invoice_number}", postings, source=number)
        self._documents[number] = note
        invoice.credited += note.gross
        return note

    def get(self, number):
        try:
            return self._documents[number]
        except (KeyError, TypeError):
            raise UnknownDocument(f"no document {number!r}") from None

    def documents(self, customer_id=None, kind=None):
        """Documents in issue order, optionally of one customer and one kind."""
        return [doc for doc in self._documents.values()
                if (customer_id is None or doc.customer_id == customer_id) and (kind is None or doc.kind == kind)]

    def open_invoices(self, customer_id, on=None):
        """Invoices with an open amount, issued on or before ``on``: earliest due date first, then issue order."""
        found = [doc for doc in self.documents(customer_id, "invoice")
                 if doc.open > 0 and (on is None or doc.issued <= on)]
        return sorted(found, key=lambda doc: (doc.due, doc.seq))
