"""Customer payments, early payment discounts and prepayments.

A payment is applied to the customer's open invoices issued on or before
the payment date, earliest due date first, then in issue order.

Early payment discount: when a payment received on or before an invoice's
discount date covers the invoice's open amount less the discount, the
invoice is settled in full and the discount (its percentage of the
invoice's gross total, rounded half-up) is booked to discounts allowed.
An invoice earns the discount at most once.  Otherwise a payment settles as
much of the invoice as it can, without discount.

Whatever is left after all open invoices is kept as a customer prepayment;
:meth:`PaymentBook.apply_prepayment` later uses it for open invoices.

A payment either is recorded completely or raises without changing any
invoice, prepayment or ledger balance.
"""
from dataclasses import dataclass
import datetime
import re

from .errors import DuplicateId, TallyError
from .ledger import BANK, DISCOUNTS, PREPAYMENTS, RECEIVABLES, credit, debit
from .money import check_cents, check_date, percent_of

_PAYMENT = re.compile(r"^[A-Z][A-Z0-9/-]{0,19}$")


@dataclass(frozen=True)
class Payment:
    payment_id: str
    customer_id: str
    date: datetime.date
    amount: int
    allocations: tuple
    unapplied: int

    @property
    def discount(self):
        return sum(discount for _, _, discount in self.allocations)


class PaymentBook:
    def __init__(self, ledger, invoices):
        self.ledger = ledger
        self.invoices = invoices
        self._payments = {}
        self._prepaid = {}

    def prepaid(self, customer_id):
        """The customer's unused prepayment in cents."""
        self.invoices.customer(customer_id)
        return self._prepaid.get(customer_id, 0)

    def payments(self, customer_id=None):
        return [p for p in self._payments.values() if customer_id is None or p.customer_id == customer_id]

    def _plan(self, customer_id, amount, on, allow_discount=True):
        plan, remaining = [], amount
        for invoice in self.invoices.open_invoices(customer_id, on):
            if remaining == 0:
                break
            discount = 0
            if allow_discount and invoice.discount_date is not None and invoice.discount_taken == 0:
                if on <= invoice.discount_date:
                    offer = min(percent_of(invoice.gross, invoice.terms.discount), invoice.open)
                    if remaining >= invoice.open - offer:
                        discount = offer
            take = min(remaining, invoice.open - discount)
            plan.append((invoice, take, discount))
            remaining -= take
        return plan, remaining

    def _apply(self, plan, on, memo, first, source):
        """Settle the planned invoices and post the entry; undo the settlements if posting fails."""
        discounts = sum(discount for _, _, discount in plan)
        settled = sum(take + discount for _, take, discount in plan)
        postings = list(first)
        if discounts:
            postings.append(debit(DISCOUNTS, discounts))
        if settled:
            postings.append(credit(RECEIVABLES, settled))
        done = []
        try:
            for invoice, take, discount in plan:
                invoice.settle(take, discount)
                done.append((invoice, take, discount))
            return self.ledger.post(on, memo, postings, source=source)
        except TallyError:
            for invoice, take, discount in reversed(done):
                invoice.settle(-take, -discount)
            raise

    def receive(self, payment_id, customer_id, amount, on):
        """Record a payment of ``amount`` cents from a customer on date ``on``."""
        if not isinstance(payment_id, str) or not _PAYMENT.match(payment_id):
            raise TallyError(f"bad payment id {payment_id!r}")
        if payment_id in self._payments:
            raise DuplicateId(f"payment {payment_id} already exists")
        self.invoices.customer(customer_id)
        check_cents(amount, positive=True)
        check_date(on)
        plan, unapplied = self._plan(customer_id, amount, on)
        first = [debit(BANK, amount)]
        extra = [credit(PREPAYMENTS, unapplied)] if unapplied else []
        self._apply(plan, on, f"Payment {payment_id} from {customer_id}", first + extra, payment_id)
        payment = Payment(payment_id, customer_id, on, amount,
                          tuple((invoice.number, take, discount) for invoice, take, discount in plan), unapplied)
        self._payments[payment_id] = payment
        self._prepaid[customer_id] = self._prepaid.get(customer_id, 0) + unapplied
        return payment

    def apply_prepayment(self, customer_id, on):
        """Use the customer's prepayment for invoices open on ``on`` (no discount); returns cents used."""
        check_date(on)
        available = self.prepaid(customer_id)
        plan, left = self._plan(customer_id, available, on, allow_discount=False)
        used = available - left
        if used == 0:
            return 0
        self._apply(plan, on, f"Prepayment applied for {customer_id}", [debit(PREPAYMENTS, used)], "prepayment")
        self._prepaid[customer_id] = left
        return used
