"""A facade that wires the catalogue, inventory, pricing and order book together.

Most callers only need :class:`Store`; the journal replay uses it as well.
Amounts given as strings or ints are interpreted in the store currency.
"""
import datetime

from . import reports
from .catalog import Catalog
from .errors import StockroomError
from .inventory import Inventory
from .money import Money
from .orders import OrderBook
from .pricing import BundleFree, PercentOff, PricingEngine


class Store:
    def __init__(self, currency="PLN"):
        self.currency = currency
        self.catalog = Catalog(currency)
        self.inventory = Inventory(self.catalog)
        self.pricing = PricingEngine(self.catalog)
        self.orders = OrderBook(self.catalog, self.inventory, self.pricing)
        self._snapshots = {}

    def money(self, value):
        return value if isinstance(value, Money) else Money(value, self.currency)

    # -- catalogue and stock ------------------------------------------------
    def add_product(self, sku, name, price, tax_class="standard", tiers=()):
        tiers = [(quantity, self.money(tier_price)) for quantity, tier_price in tiers]
        return self.catalog.add(sku, name, self.money(price), tax_class, tiers)

    def receive(self, sku, quantity, unit_cost, on):
        return self.inventory.receive(sku, quantity, self.money(unit_cost), on)

    def write_off(self, sku, quantity, on, reason=""):
        return self.inventory.write_off(sku, quantity, on=on, reason=reason)

    # -- promotions ---------------------------------------------------------
    def percent_off(self, code, skus, percent):
        return self.pricing.add_promotion(PercentOff(code, frozenset(skus), percent))

    def bundle(self, code, sku, buy, free):
        return self.pricing.add_promotion(BundleFree(code, sku, buy, free))

    # -- orders -------------------------------------------------------------
    def order(self, order_id, items, on, customer="", coupon=None):
        coupon = None if coupon is None else self.money(coupon)
        return self.orders.create(order_id, items, on, customer, coupon)

    def confirm(self, order_id):
        return self.orders.confirm(order_id)

    def ship(self, order_id, on, items=None):
        return self.orders.ship(order_id, on, items)

    def cancel(self, order_id, on=None):
        return self.orders.cancel(order_id, on)

    def place(self, order_id, items, on, customer="", coupon=None):
        """Create and confirm an order in one step; return the frozen quote."""
        self.order(order_id, items, on, customer, coupon)
        try:
            return self.confirm(order_id)
        except StockroomError:
            self.cancel(order_id, on)
            raise

    # -- snapshots and reports ----------------------------------------------
    def take_snapshot(self, label):
        if label in self._snapshots:
            raise StockroomError(f"snapshot {label!r} already exists")
        snapshot = self.inventory.snapshot(label)
        self._snapshots[label] = snapshot
        return snapshot

    def snapshot(self, label):
        try:
            return self._snapshots[label]
        except KeyError:
            raise StockroomError(f"no snapshot {label!r}") from None

    def valuation(self, label=None):
        """Valuation of a named snapshot, or of the current stock when ``label`` is None."""
        snapshot = self.inventory.snapshot("current") if label is None else self.snapshot(label)
        return reports.valuation(snapshot, self.currency)

    def monthly_shipments(self, year, month):
        return reports.shipped_by_sku(self.orders, reports.Period.month(year, month), self.currency)

    def top_skus(self, start, end, limit=3):
        return reports.top_skus(self.orders, reports.Period(start, end), self.currency, limit)

    def stock_status(self):
        return reports.stock_status(self.inventory, self.catalog)

    @staticmethod
    def date(text):
        try:
            return datetime.date.fromisoformat(text)
        except (TypeError, ValueError):
            raise StockroomError(f"not an ISO date: {text!r}") from None
