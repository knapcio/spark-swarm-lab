"""The chart of accounts and the general ledger.

Account codes are four digits.  The first digit fixes the kind: 1 asset,
2 liability, 3 equity, 4 income, 5-9 expense.  Assets and expenses have a
debit normal balance; liabilities, equity and income a credit normal balance.
Balances are always reported in the account's normal direction, so a bank
account with more debits than credits has a positive balance.

A journal entry has a date, a memo and two or more postings.  Each posting
debits or credits exactly one account by a positive number of cents, and
the debits of an entry must equal its credits.  Entries are numbered from 1
in the order they are posted.

Periods are closed by date: once the books are closed through a date,
nothing may be posted on or before it.  Closing a year moves the balances of
all income and expense accounts into retained earnings with one closing
entry dated on the last day of the year, then closes the books through it.
"""
from dataclasses import dataclass
import datetime
import re

from .errors import DuplicateId, PeriodClosed, TallyError, UnbalancedEntry, UnknownAccount
from .money import check_cents, check_date

KINDS = ("asset", "liability", "equity", "income", "expense")
_KIND_BY_DIGIT = {"1": "asset", "2": "liability", "3": "equity", "4": "income"}
_CODE = re.compile(r"^[1-9]\d{3}$")

BANK = "1000"
RECEIVABLES = "1100"
PREPAYMENTS = "2100"
VAT = "2200"
CAPITAL = "3000"
RETAINED = "3200"
SALES = "4000"
SERVICES = "4100"
DISCOUNTS = "5900"

DEFAULT_ACCOUNTS = (
    (BANK, "Bank"), (RECEIVABLES, "Receivables"), (PREPAYMENTS, "Customer prepayments"),
    (VAT, "VAT payable"), (CAPITAL, "Owner capital"), (RETAINED, "Retained earnings"),
    (SALES, "Sales"), (SERVICES, "Services"), ("5000", "Purchases"), (DISCOUNTS, "Discounts allowed"),
    ("6000", "Rent"), ("6100", "Office supplies"),
)


def kind_of(code):
    """The account kind implied by a code's first digit."""
    if not isinstance(code, str) or not _CODE.match(code):
        raise TallyError(f"bad account code {code!r}")
    return _KIND_BY_DIGIT.get(code[0], "expense")


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    kind: str

    @property
    def debit_normal(self):
        return self.kind in ("asset", "expense")

    def signed(self, net):
        """Balance in the normal direction from a debit-minus-credit amount."""
        return net if self.debit_normal else -net


class Chart:
    """Accounts by code.  ``Chart()`` starts with the default accounts."""

    def __init__(self, accounts=DEFAULT_ACCOUNTS):
        self._accounts = {}
        for code, name in accounts:
            self.add(code, name)

    def add(self, code, name):
        kind = kind_of(code)
        if code in self._accounts:
            raise DuplicateId(f"account {code} already exists")
        if not isinstance(name, str) or not name.strip():
            raise TallyError("an account needs a name")
        account = Account(code, name.strip(), kind)
        self._accounts[code] = account
        return account

    def get(self, code):
        try:
            return self._accounts[code]
        except (KeyError, TypeError):
            raise UnknownAccount(f"no account {code!r}") from None

    def __contains__(self, code):
        return code in self._accounts

    def codes(self, kind=None):
        """Account codes in ascending order, optionally only one kind."""
        if kind is not None and kind not in KINDS:
            raise TallyError(f"unknown account kind {kind!r}")
        return sorted(code for code, account in self._accounts.items() if kind is None or account.kind == kind)



@dataclass(frozen=True)
class Posting:
    account: str
    debit: int = 0
    credit: int = 0

    @property
    def net(self):
        return self.debit - self.credit


@dataclass(frozen=True)
class Entry:
    number: int
    date: datetime.date
    memo: str
    postings: tuple
    source: object = None

    @property
    def total(self):
        return sum(posting.debit for posting in self.postings)


def debit(account, cents):
    return Posting(account, debit=cents)


def credit(account, cents):
    return Posting(account, credit=cents)


class Ledger:
    def __init__(self, chart):
        self.chart = chart
        self._entries = []
        self.closed_through = None

    def is_open(self, date):
        return self.closed_through is None or date > self.closed_through

    def post(self, date, memo, postings, source=None):
        """Validate and record one entry; returns the :class:`Entry`."""
        check_date(date)
        if not self.is_open(date):
            raise PeriodClosed(f"the books are closed through {self.closed_through}")
        if not isinstance(memo, str) or not memo.strip():
            raise UnbalancedEntry("an entry needs a memo")
        postings = tuple(postings)
        if len(postings) < 2:
            raise UnbalancedEntry("an entry needs at least two postings")
        for posting in postings:
            if not isinstance(posting, Posting):
                raise UnbalancedEntry(f"not a posting: {posting!r}")
            self.chart.get(posting.account)
            check_cents(posting.debit)
            check_cents(posting.credit)
            if (posting.debit == 0) == (posting.credit == 0):
                raise UnbalancedEntry("a posting debits or credits, not both or neither")
        debits = sum(posting.debit for posting in postings)
        credits = sum(posting.credit for posting in postings)
        if debits != credits:
            raise UnbalancedEntry(f"debits {debits} != credits {credits}")
        entry = Entry(len(self._entries) + 1, date, memo.strip(), postings, source)
        self._entries.append(entry)
        return entry

    def entries(self, account=None, start=None, end=None):
        """Entries in posting order, optionally touching ``account``, dated in ``[start, end]``."""
        if account is not None:
            self.chart.get(account)
        found = []
        for entry in self._entries:
            if start is not None and entry.date < start:
                continue
            if end is not None and entry.date > end:
                continue
            if account is None or any(p.account == account for p in entry.postings):
                found.append(entry)
        return found

    def net(self, account, start=None, end=None):
        """Debits minus credits on ``account`` for entries dated in ``[start, end]``."""
        return sum(p.net for entry in self.entries(account, start, end) for p in entry.postings if p.account == account)

    def balance(self, account, until=None):
        """Balance of ``account`` in its normal direction, entries dated on or before ``until``."""
        return self.chart.get(account).signed(self.net(account, end=until))

    def balances(self, until=None):
        """{code: balance} for every account with postings, a fresh dict the caller may change."""
        totals = {}
        for entry in self.entries(end=until):
            for posting in entry.postings:
                totals[posting.account] = totals.get(posting.account, 0) + posting.net
        return {code: self.chart.get(code).signed(totals[code]) for code in sorted(totals)}

    def close_period(self, through):
        """Close the books through ``through``; closing never reopens an earlier date."""
        check_date(through)
        if self.closed_through is not None and through < self.closed_through:
            raise PeriodClosed(f"the books are already closed through {self.closed_through}")
        self.closed_through = through

    def close_year(self, year_end):
        """Post the closing entry for the year ending ``year_end`` and close through it.

        Earlier closing entries already emptied the income and expense
        accounts, so their balances on ``year_end`` are this year's result.
        Returns the closing entry, or ``None`` when no income or expense
        account has a balance.  The difference goes to retained earnings."""
        check_date(year_end)
        if not self.is_open(year_end):
            raise PeriodClosed(f"the books are closed through {self.closed_through}")
        postings, result = [], 0
        for kind in ("income", "expense"):
            for code in self.chart.codes(kind):
                net = self.net(code, end=year_end)
                if net > 0:
                    postings.append(credit(code, net))
                elif net < 0:
                    postings.append(debit(code, -net))
                result += net
        if not postings:
            self.close_period(year_end)
            return None
        if result > 0:
            postings.append(debit(RETAINED, result))
        elif result < 0:
            postings.append(credit(RETAINED, -result))
        entry = self.post(year_end, f"Close year {year_end.year}", postings, source="close")
        self.close_period(year_end)
        return entry
