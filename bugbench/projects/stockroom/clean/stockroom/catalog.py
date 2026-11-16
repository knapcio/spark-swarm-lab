"""Product catalogue: SKUs, list prices, quantity price tiers and tax classes.

A SKU is three capital letters, a dash and three digits (``WID-001``).  Every
product has a list price in the catalogue currency and a VAT class.  Optional
quantity tiers lower the unit price for larger order lines: a tier applies to
a line whose quantity is *at least* the tier's ``min_quantity``.
"""
from dataclasses import dataclass
from decimal import Decimal
import re

from .errors import DuplicateProduct, InvalidAmount, InvalidQuantity, UnknownProduct
from .money import Money

SKU_PATTERN = re.compile(r"^[A-Z]{3}-\d{3}$")
TAX_RATES = {"standard": Decimal("23"), "reduced": Decimal("8"), "zero": Decimal("0")}


@dataclass(frozen=True)
class PriceTier:
    min_quantity: int
    unit_price: Money


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    list_price: Money
    tax_class: str = "standard"
    tiers: tuple = ()

    @property
    def tax_rate(self):
        """VAT rate in percent, e.g. ``Decimal('23')``."""
        return TAX_RATES[self.tax_class]


def _as_money(value, currency):
    if isinstance(value, Money):
        money = value
    else:
        money = Money(value, currency)
    if money.currency != currency:
        raise InvalidAmount(f"price must be in {currency}, got {money.currency}")
    if money.amount < 0:
        raise InvalidAmount("prices cannot be negative")
    return money


class Catalog:
    """Registry of products, all priced in a single currency."""

    def __init__(self, currency="PLN"):
        Money.zero(currency)  # validates the currency code
        self.currency = currency
        self._products = {}

    def add(self, sku, name, list_price, tax_class="standard", tiers=()):
        """Register a product and return it.

        ``tiers`` is an iterable of ``(min_quantity, unit_price)`` pairs.  Tier
        quantities must be distinct integers of at least 2 and tier prices
        must not exceed the list price.  Tiers are stored sorted by quantity.
        """
        if not isinstance(sku, str) or not SKU_PATTERN.match(sku):
            raise UnknownProduct(f"malformed SKU {sku!r}")
        if sku in self._products:
            raise DuplicateProduct(sku)
        if tax_class not in TAX_RATES:
            raise InvalidAmount(f"unknown tax class {tax_class!r}")
        price = _as_money(list_price, self.currency)
        parsed = []
        seen = set()
        for min_quantity, unit_price in tiers:
            if isinstance(min_quantity, bool) or not isinstance(min_quantity, int) or min_quantity < 2:
                raise InvalidQuantity(f"tier quantity must be an int >= 2, got {min_quantity!r}")
            if min_quantity in seen:
                raise InvalidQuantity(f"duplicate tier quantity {min_quantity}")
            seen.add(min_quantity)
            tier_price = _as_money(unit_price, self.currency)
            if tier_price > price:
                raise InvalidAmount(f"tier price {tier_price} exceeds list price {price}")
            parsed.append(PriceTier(min_quantity, tier_price))
        parsed.sort(key=lambda tier: tier.min_quantity)
        product = Product(sku, str(name), price, tax_class, tuple(parsed))
        self._products[sku] = product
        return product

    def get(self, sku):
        try:
            return self._products[sku]
        except (KeyError, TypeError):
            raise UnknownProduct(f"unknown SKU {sku!r}") from None

    def __contains__(self, sku):
        return sku in self._products

    def __len__(self):
        return len(self._products)

    def __iter__(self):
        return iter(self.products())

    def skus(self):
        """All SKUs in ascending order."""
        return sorted(self._products)

    def products(self):
        """All products in ascending SKU order."""
        return [self._products[sku] for sku in self.skus()]
