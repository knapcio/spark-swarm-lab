"""Order lifecycle.

::

    DRAFT --confirm--> CONFIRMED --ship--> PARTIALLY_SHIPPED --ship--> SHIPPED
      |                    |                      |
      +------cancel--------+--------cancel--------+-------> CANCELLED

* ``confirm`` prices the order (the quote is frozen from then on) and
  reserves every line.  It fails without side effects if a line is not
  available.
* ``ship`` issues stock for some or all of the remaining quantities.  A
  shipment is atomic: if any line cannot be issued (for example after a
  write-off reduced physical stock below the reservation) no stock moves, the
  reservations stay as they were and the order is unchanged.
* ``cancel`` releases whatever is still reserved.  Units already shipped are
  not returned to stock.
"""
from dataclasses import dataclass, field
import datetime

from .errors import InsufficientStock, InvalidQuantity, OrderStateError, UnknownOrder
from .inventory import cogs
from .money import Money, total

DRAFT = "draft"
CONFIRMED = "confirmed"
PARTIALLY_SHIPPED = "partially_shipped"
SHIPPED = "shipped"
CANCELLED = "cancelled"
STATUSES = (DRAFT, CONFIRMED, PARTIALLY_SHIPPED, SHIPPED, CANCELLED)


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    order_id: str
    on: datetime.date
    items: dict  # sku -> quantity
    consumptions: tuple
    cogs: Money


@dataclass
class Order:
    order_id: str
    created_on: datetime.date
    items: dict  # sku -> ordered quantity, in basket order
    customer: str = ""
    coupon: object = None
    status: str = DRAFT
    quote: object = None
    shipments: list = field(default_factory=list)
    closed_on: object = None

    def shipped(self, sku):
        return sum(shipment.items.get(sku, 0) for shipment in self.shipments)

    def remaining(self, sku):
        return self.items[sku] - self.shipped(sku)

    def cogs(self, currency):
        return total((shipment.cogs for shipment in self.shipments), currency)


class OrderBook:
    def __init__(self, catalog, inventory, pricing):
        self.catalog = catalog
        self.inventory = inventory
        self.pricing = pricing
        self._orders = {}

    def create(self, order_id, items, on, customer="", coupon=None):
        """Create a DRAFT order from ``(sku, quantity)`` pairs or a dict."""
        if not isinstance(order_id, str) or not order_id:
            raise OrderStateError("order id must be a non-empty string")
        if order_id in self._orders:
            raise OrderStateError(f"order {order_id} already exists")
        if not isinstance(on, datetime.date):
            raise OrderStateError("order date must be a datetime.date")
        pairs = list(items.items()) if isinstance(items, dict) else list(items)
        if not pairs:
            raise InvalidQuantity("an order needs at least one line")
        lines = {}
        for sku, quantity in pairs:
            self.catalog.get(sku)
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
                raise InvalidQuantity(f"quantity must be a positive int, got {quantity!r}")
            if sku in lines:
                raise InvalidQuantity(f"duplicate line for {sku}")
            lines[sku] = quantity
        order = Order(order_id, on, lines, customer, coupon)
        self._orders[order_id] = order
        return order

    def get(self, order_id):
        try:
            return self._orders[order_id]
        except KeyError:
            raise UnknownOrder(order_id) from None

    def orders(self, status=None):
        return [order for order in self._orders.values() if status is None or order.status == status]

    def _require(self, order, *allowed):
        if order.status not in allowed:
            raise OrderStateError(f"order {order.order_id} is {order.status}")

    def confirm(self, order_id):
        """Freeze the price and reserve stock for every line."""
        order = self.get(order_id)
        self._require(order, DRAFT)
        quote = self.pricing.quote(order.items, coupon=order.coupon)
        self.inventory.reserve(order_id, order.items)
        order.quote = quote
        order.status = CONFIRMED
        return quote

    def ship(self, order_id, on, items=None):
        """Ship ``items`` (default: everything remaining) and return the Shipment."""
        order = self.get(order_id)
        self._require(order, CONFIRMED, PARTIALLY_SHIPPED)
        if items is None:
            items = {sku: order.remaining(sku) for sku in order.items if order.remaining(sku)}
        else:
            items = dict(items)
        if not items:
            raise InvalidQuantity("nothing to ship")
        for sku, quantity in items.items():
            if sku not in order.items:
                raise InvalidQuantity(f"{sku} is not part of order {order_id}")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
                raise InvalidQuantity(f"quantity must be a positive int, got {quantity!r}")
            if quantity > order.remaining(sku):
                raise InvalidQuantity(f"{sku}: only {order.remaining(sku)} left to ship")
        issued = []
        try:
            for sku, quantity in items.items():
                issued.extend(self.inventory.issue(sku, quantity, on=on, reference=order_id))
        except InsufficientStock:
            self.inventory.restore(issued, reference=order_id)
            raise
        for sku, quantity in items.items():
            self.inventory.release(order_id, sku, quantity)
        currency = self.catalog.currency
        shipment = Shipment(f"{order_id}/{len(order.shipments) + 1}", order_id, on, items,
                            tuple(issued), cogs(issued, currency))
        order.shipments.append(shipment)
        if all(order.remaining(sku) == 0 for sku in order.items):
            order.status = SHIPPED
            order.closed_on = on
        else:
            order.status = PARTIALLY_SHIPPED
        return shipment

    def cancel(self, order_id, on=None):
        """Cancel an order that is not fully shipped and release its reservations."""
        order = self.get(order_id)
        self._require(order, DRAFT, CONFIRMED, PARTIALLY_SHIPPED)
        if order.status != DRAFT:
            self.inventory.release(order_id)
        order.status = CANCELLED
        order.closed_on = on

    def shipments(self):
        """Every shipment of every order, in order of creation."""
        return [shipment for order in self._orders.values() for shipment in order.shipments]
