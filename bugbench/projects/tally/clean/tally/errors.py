"""Exception hierarchy for tally.

Every error derives from :class:`TallyError`.  Operations on the books
either complete or raise without changing anything.
"""


class TallyError(Exception):
    """Base class for all errors raised by this package."""


class InvalidAmount(TallyError):
    """An amount, quantity, percentage or date is malformed or out of range."""


class UnknownAccount(TallyError):
    """No account with this code exists in the chart."""


class DuplicateId(TallyError):
    """An account, customer, invoice, credit note or payment id is already used."""


class UnknownDocument(TallyError):
    """No customer, invoice or payment with this id exists."""


class UnbalancedEntry(TallyError):
    """A journal entry is malformed or its debits do not equal its credits."""


class PeriodClosed(TallyError):
    """The date falls in a closed period; nothing may be posted there."""


class CreditTooLarge(TallyError):
    """A credit note would exceed the open amount of its invoice."""


class ScriptError(TallyError):
    """A script line could not be parsed or executed.

    ``line`` is the 1-based line number in the script text.  When the line
    parsed but the bookkeeping operation failed, the original exception is
    available as ``__cause__``.
    """

    def __init__(self, line, message):
        super().__init__(f"line {line}: {message}")
        self.line = line
