"""Physical stock kept as FIFO cost lots, plus per-order reservations.

* ``on_hand(sku)``   -- units physically in the warehouse (sum of lot quantities)
* ``reserved(sku)``  -- units promised to confirmed orders and not yet shipped
* ``available(sku)`` -- ``on_hand - reserved``, never reported below zero

Stock leaves the warehouse strictly first-in-first-out: lots are ordered by
receipt date and, for the same date, by the order in which they were
received.  :meth:`Inventory.issue` always consumes the oldest lot first.  The
cost of goods sold (COGS) of an issue is the sum of consumed quantities times
their lot unit costs.  An issue can be undone exactly with
:meth:`Inventory.restore`.
"""
import bisect
from dataclasses import dataclass, replace
import datetime

from .errors import InsufficientStock, InvalidAmount, InvalidQuantity, ReservationError
from .money import Money, total


def _quantity(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidQuantity(f"quantity must be a positive int, got {value!r}")
    return value


@dataclass
class Lot:
    lot_id: str
    sku: str
    quantity: int
    unit_cost: Money
    received_on: datetime.date
    seq: int

    def copy(self):
        return replace(self)

    def sort_key(self):
        return (self.received_on, self.seq)

    @property
    def value(self):
        return self.unit_cost.times(self.quantity)


@dataclass(frozen=True)
class Consumption:
    """``quantity`` units taken from one lot by an issue or a write-off."""

    lot_id: str
    sku: str
    quantity: int
    unit_cost: Money
    received_on: datetime.date
    seq: int

    @property
    def cost(self):
        return self.unit_cost.times(self.quantity)


@dataclass(frozen=True)
class Movement:
    kind: str  # "receive", "issue", "write_off" or "restore"
    sku: str
    quantity: int  # signed: negative when stock leaves
    on: object
    reference: str


@dataclass(frozen=True)
class Snapshot:
    """A frozen copy of the stock, independent of later changes."""

    label: str
    lots: dict  # sku -> list of Lot copies in FIFO order
    reservations: dict  # order_id -> {sku: quantity}

    def on_hand(self, sku):
        return sum(lot.quantity for lot in self.lots.get(sku, ()))

    def skus(self):
        return sorted(sku for sku, lots in self.lots.items() if lots)


def cogs(consumptions, currency):
    """Total cost of a sequence of consumptions."""
    return total((item.cost for item in consumptions), currency)


class Inventory:
    def __init__(self, catalog):
        self.catalog = catalog
        self._lots = {}  # sku -> list of Lot, oldest first
        self._reservations = {}  # order_id -> {sku: quantity}
        self._seq = 0
        self._movements = []

    # -- lots -------------------------------------------------------------
    def _insert_lot(self, lot):
        lots = self._lots.setdefault(lot.sku, [])
        keys = [existing.sort_key() for existing in lots]
        lots.insert(bisect.bisect_right(keys, lot.sort_key()), lot)

    def _find_lot(self, sku, lot_id):
        for lot in self._lots.get(sku, ()):
            if lot.lot_id == lot_id:
                return lot
        return None

    def receive(self, sku, quantity, unit_cost, on):
        """Add a new lot and return its identifier (``SKU#n``)."""
        self.catalog.get(sku)
        _quantity(quantity)
        if not isinstance(unit_cost, Money) or unit_cost.currency != self.catalog.currency:
            raise InvalidAmount(f"unit cost must be Money in {self.catalog.currency}")
        if unit_cost.amount < 0:
            raise InvalidAmount("unit cost cannot be negative")
        if not isinstance(on, datetime.date):
            raise InvalidAmount("receipt date must be a datetime.date")
        self._seq += 1
        lot = Lot(f"{sku}#{self._seq}", sku, quantity, unit_cost, on, self._seq)
        self._insert_lot(lot)
        self._movements.append(Movement("receive", sku, quantity, on, lot.lot_id))
        return lot.lot_id

    def lots(self, sku):
        """Copies of the lots of ``sku`` in FIFO order."""
        return [lot.copy() for lot in self._lots.get(sku, ())]

    def on_hand(self, sku):
        return sum(lot.quantity for lot in self._lots.get(sku, ()))

    def _take(self, sku, quantity, kind, on, reference):
        self.catalog.get(sku)
        _quantity(quantity)
        on_hand = self.on_hand(sku)
        if on_hand < quantity:
            raise InsufficientStock(sku, quantity, on_hand)
        lots = self._lots[sku]
        taken = []
        remaining = quantity
        while remaining:
            lot = lots[0]
            step = min(lot.quantity, remaining)
            lot.quantity -= step
            remaining -= step
            taken.append(Consumption(lot.lot_id, sku, step, lot.unit_cost, lot.received_on, lot.seq))
            if lot.quantity == 0:
                lots.pop(0)
        self._movements.append(Movement(kind, sku, -quantity, on, reference))
        return tuple(taken)

    def issue(self, sku, quantity, on=None, reference=""):
        """Remove ``quantity`` units FIFO and return the consumptions."""
        return self._take(sku, quantity, "issue", on, reference)

    def write_off(self, sku, quantity, on=None, reason=""):
        """Remove damaged or lost units FIFO; reservations are not touched."""
        return self._take(sku, quantity, "write_off", on, reason)

    def restore(self, consumptions, reference=""):
        """Undo an issue: put consumed units back into their original lots.

        Lots that were used up by the issue are re-created at their original
        FIFO position, so a rolled-back issue leaves the stock exactly as it
        was before.
        """
        for item in reversed(tuple(consumptions)):
            lot = self._find_lot(item.sku, item.lot_id)
            if lot is None:
                lot = Lot(item.lot_id, item.sku, 0, item.unit_cost, item.received_on, item.seq)
                self._insert_lot(lot)
            lot.quantity += item.quantity
            self._movements.append(Movement("restore", item.sku, item.quantity, None, reference))

    # -- reservations -----------------------------------------------------
    def reserved(self, sku):
        return sum(items.get(sku, 0) for items in self._reservations.values())

    def available(self, sku):
        return max(0, self.on_hand(sku) - self.reserved(sku))

    def reservation(self, order_id, sku):
        return self._reservations.get(order_id, {}).get(sku, 0)

    def reserve(self, order_id, items):
        """Reserve every ``sku: quantity`` in ``items`` for one order, or nothing."""
        for sku, quantity in items.items():
            self.catalog.get(sku)
            _quantity(quantity)
            if self.available(sku) < quantity:
                raise InsufficientStock(sku, quantity, self.available(sku))
        held = self._reservations.setdefault(order_id, {})
        for sku, quantity in items.items():
            held[sku] = held.get(sku, 0) + quantity

    def release(self, order_id, sku=None, quantity=None):
        """Release a reservation.

        Without ``sku`` everything held by the order is released.  Without
        ``quantity`` the whole reservation for ``sku`` is released.  Releasing
        more than is held raises :class:`ReservationError`.
        """
        held = self._reservations.get(order_id, {})
        if sku is None:
            self._reservations.pop(order_id, None)
            return
        current = held.get(sku, 0)
        amount = current if quantity is None else _quantity(quantity)
        if amount > current:
            raise ReservationError(f"{order_id} holds {current} of {sku}, cannot release {amount}")
        if amount == current:
            held.pop(sku, None)
        else:
            held[sku] = current - amount
        if not held:
            self._reservations.pop(order_id, None)

    # -- history ----------------------------------------------------------
    def movements(self, sku=None):
        return tuple(move for move in self._movements if sku is None or move.sku == sku)

    def snapshot(self, label):
        """Return a :class:`Snapshot` that later stock changes cannot alter."""
        return Snapshot(
            label,
            lots={sku: [lot.copy() for lot in lots] for sku, lots in self._lots.items() if lots},
            reservations={order_id: dict(items) for order_id, items in self._reservations.items()},
        )
