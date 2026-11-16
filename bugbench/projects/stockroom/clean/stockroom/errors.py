"""Exception hierarchy used by every stockroom module.

All errors derive from :class:`StockroomError`, so callers that only want to
report a failed command can catch one class.  Domain operations either finish
completely or raise before changing state, unless their docstring says
otherwise.
"""


class StockroomError(Exception):
    """Base class for all errors raised by this package."""


class InvalidAmount(StockroomError):
    """A money amount, currency or ratio list is not acceptable."""


class CurrencyMismatch(StockroomError):
    """Two amounts in different currencies were combined or compared."""


class UnknownProduct(StockroomError):
    """The SKU is not present in the catalogue."""


class DuplicateProduct(StockroomError):
    """The SKU is already present in the catalogue."""


class InvalidQuantity(StockroomError):
    """A quantity is not a positive integer, or exceeds what is allowed."""


class InsufficientStock(StockroomError):
    """Not enough physical or available stock for the requested operation."""

    def __init__(self, sku, requested, available):
        super().__init__(f"{sku}: requested {requested}, only {available} in stock")
        self.sku = sku
        self.requested = requested
        self.available = available


class ReservationError(StockroomError):
    """A reservation cannot be created or released as requested."""


class PromotionError(StockroomError):
    """A promotion definition is invalid or its code is already registered."""


class UnknownOrder(StockroomError):
    """No order with this identifier exists."""


class OrderStateError(StockroomError):
    """The operation is not allowed in the order's current status."""


class JournalError(StockroomError):
    """A journal line could not be parsed or executed.

    ``line`` is the 1-based line number in the journal text.  When the line
    parsed correctly but the domain operation failed, the original exception
    is available as ``__cause__``.
    """

    def __init__(self, line, message):
        super().__init__(f"line {line}: {message}")
        self.line = line
