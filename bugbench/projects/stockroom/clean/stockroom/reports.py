"""Read-only reports over inventory snapshots and the order book.

Report rows use plain Python types (str, int and Money) so that callers can
render them however they like.  Rows are sorted by SKU unless stated
otherwise.
"""
from dataclasses import dataclass
import datetime

from .errors import StockroomError
from .money import Money, total
from .orders import STATUSES


@dataclass(frozen=True)
class Period:
    """Half-open date range: ``start <= day < end``."""

    start: datetime.date
    end: datetime.date

    def __post_init__(self):
        if not self.start < self.end:
            raise StockroomError("a period must end after it starts")

    def contains(self, day):
        return self.start <= day < self.end

    @classmethod
    def month(cls, year, month):
        start = datetime.date(year, month, 1)
        end = datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)
        return cls(start, end)

    @classmethod
    def days(cls, start, count):
        return cls(start, start + datetime.timedelta(days=count))


def valuation(snapshot, currency):
    """Stock value at lot cost for one snapshot.

    Returns ``{"label", "lines": [{"sku", "quantity", "value"}], "quantity",
    "value"}``.  SKUs without stock are omitted.
    """
    lines = []
    for sku in snapshot.skus():
        lots = snapshot.lots[sku]
        quantity = sum(lot.quantity for lot in lots)
        value = total((lot.value for lot in lots), currency)
        lines.append({"sku": sku, "quantity": quantity, "value": value})
    return {
        "label": snapshot.label,
        "lines": lines,
        "quantity": sum(line["quantity"] for line in lines),
        "value": total((line["value"] for line in lines), currency),
    }


def shipped_by_sku(orderbook, period, currency):
    """Units shipped and their COGS per SKU for shipments dated inside ``period``."""
    units, costs = {}, {}
    for shipment in orderbook.shipments():
        if not period.contains(shipment.on):
            continue
        for sku, quantity in shipment.items.items():
            units[sku] = units.get(sku, 0) + quantity
        for item in shipment.consumptions:
            costs[item.sku] = costs.get(item.sku, Money.zero(currency)) + item.cost
    return [{"sku": sku, "units": units[sku], "cogs": costs.get(sku, Money.zero(currency))}
            for sku in sorted(units)]


def top_skus(orderbook, period, currency, limit=3):
    """The ``limit`` SKUs with most units shipped; ties are broken by SKU ascending."""
    rows = shipped_by_sku(orderbook, period, currency)
    rows.sort(key=lambda row: (-row["units"], row["sku"]))
    return [(row["sku"], row["units"]) for row in rows[:limit]]


def cogs_total(orderbook, period, currency):
    return total((row["cogs"] for row in shipped_by_sku(orderbook, period, currency)), currency)


def order_status_counts(orderbook):
    """Number of orders in every status, including statuses with no orders."""
    counts = {status: 0 for status in STATUSES}
    for order in orderbook.orders():
        counts[order.status] += 1
    return counts


def stock_status(inventory, catalog):
    """Current on-hand, reserved and available units for every catalogue SKU."""
    return [{"sku": sku, "on_hand": inventory.on_hand(sku), "reserved": inventory.reserved(sku),
             "available": inventory.available(sku)} for sku in catalog.skus()]
