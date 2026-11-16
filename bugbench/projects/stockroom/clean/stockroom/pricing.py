"""Quotes: tier prices, promotions, order coupons and VAT.

Pricing a basket happens in four steps, applied to each line in basket order:

1. The unit price is the list price, or the price of the highest tier whose
   ``min_quantity`` is less than or equal to the line quantity.
2. The best applicable promotion is chosen: the one with the largest
   discount.  On a tie the promotion registered first wins.  Promotions never
   stack, and a promotion with a zero discount does not count as applied.
3. An optional order-level coupon is capped at the basket net amount and then
   spread over the lines in proportion to their net amounts using
   :meth:`Money.allocate`.
4. VAT is computed per line on the line net amount (after the coupon share)
   and rounded half-up to the minor unit.
"""
from dataclasses import dataclass

from .errors import InvalidAmount, InvalidQuantity, PromotionError
from .money import Money, to_decimal, total


def _positive_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidQuantity(f"{what} must be a positive int, got {value!r}")
    return value


@dataclass(frozen=True)
class PercentOff:
    """``percent`` off the gross amount of lines for any of ``skus``."""

    code: str
    skus: frozenset
    percent: object

    def discount(self, sku, quantity, unit_price):
        if sku not in self.skus:
            return None
        return unit_price.times(quantity).percent(self.percent)


@dataclass(frozen=True)
class BundleFree:
    """Buy ``buy`` units of ``sku`` and get ``free`` more units free, per group."""

    code: str
    sku: str
    buy: int
    free: int

    def discount(self, sku, quantity, unit_price):
        if sku != self.sku:
            return None
        groups = quantity // (self.buy + self.free)
        return unit_price.times(groups * self.free)


@dataclass(frozen=True)
class QuoteLine:
    sku: str
    quantity: int
    unit_price: Money
    gross: Money
    promotion: object
    discount: Money
    coupon_share: Money
    net: Money
    tax_rate: object
    tax: Money

    @property
    def total(self):
        return self.net + self.tax


@dataclass(frozen=True)
class Quote:
    currency: str
    lines: tuple
    coupon: Money

    def _sum(self, field):
        return total((getattr(line, field) for line in self.lines), self.currency)

    @property
    def gross(self):
        return self._sum("gross")

    @property
    def discount(self):
        return self._sum("discount")

    @property
    def net(self):
        return self._sum("net")

    @property
    def tax(self):
        return self._sum("tax")

    @property
    def total(self):
        return self.net + self.tax

    def line(self, sku):
        for line in self.lines:
            if line.sku == sku:
                return line
        raise KeyError(sku)


class PricingEngine:
    """Prices baskets against a catalogue and a list of promotions."""

    def __init__(self, catalog):
        self.catalog = catalog
        self._promotions = []

    def add_promotion(self, promotion):
        if any(existing.code == promotion.code for existing in self._promotions):
            raise PromotionError(f"promotion {promotion.code!r} already registered")
        if isinstance(promotion, PercentOff):
            rate = to_decimal(promotion.percent)
            if not 0 < rate <= 100:
                raise PromotionError("percent must be in (0, 100]")
            for sku in promotion.skus:
                self.catalog.get(sku)
        elif isinstance(promotion, BundleFree):
            self.catalog.get(promotion.sku)
            _positive_int(promotion.buy, "buy")
            _positive_int(promotion.free, "free")
        else:
            raise PromotionError(f"unsupported promotion type {type(promotion).__name__}")
        self._promotions.append(promotion)
        return promotion

    def remove_promotion(self, code):
        before = len(self._promotions)
        self._promotions = [promo for promo in self._promotions if promo.code != code]
        if len(self._promotions) == before:
            raise PromotionError(f"no promotion {code!r}")

    def promotions(self):
        return tuple(self._promotions)

    def unit_price(self, sku, quantity):
        """Unit price for a line of ``quantity`` units, honouring quantity tiers."""
        product = self.catalog.get(sku)
        _positive_int(quantity, "quantity")
        price = product.list_price
        for tier in product.tiers:
            if quantity >= tier.min_quantity:
                price = tier.unit_price
        return price

    def best_promotion(self, sku, quantity, unit_price):
        """Return ``(promotion or None, discount)`` for one line."""
        best, best_discount = None, Money.zero(self.catalog.currency)
        for promotion in self._promotions:
            discount = promotion.discount(sku, quantity, unit_price)
            if discount is None or not discount:
                continue
            if best is None or discount > best_discount:
                best, best_discount = promotion, discount
        return best, best_discount

    def quote(self, items, coupon=None):
        """Price ``items`` (pairs of SKU and quantity, or a dict) and return a Quote."""
        pairs = list(items.items()) if isinstance(items, dict) else list(items)
        if not pairs:
            raise InvalidQuantity("cannot quote an empty basket")
        currency = self.catalog.currency
        seen = set()
        drafts = []
        for sku, quantity in pairs:
            if sku in seen:
                raise InvalidQuantity(f"duplicate line for {sku}")
            seen.add(sku)
            product = self.catalog.get(sku)
            unit = self.unit_price(sku, quantity)
            gross = unit.times(quantity)
            promotion, discount = self.best_promotion(sku, quantity, unit)
            if discount > gross:
                discount = gross
            drafts.append((product, quantity, unit, gross, promotion, discount, gross - discount))
        coupon = Money.zero(currency) if coupon is None else coupon
        if not isinstance(coupon, Money) or coupon.currency != currency or coupon.amount < 0:
            raise InvalidAmount("coupon must be a non-negative amount in the catalogue currency")
        basket_net = total((draft[6] for draft in drafts), currency)
        applied = min(coupon, basket_net)
        if applied:
            shares = applied.allocate([draft[6].amount for draft in drafts])
        else:
            shares = [Money.zero(currency)] * len(drafts)
        lines = []
        for (product, quantity, unit, gross, promotion, discount, net), share in zip(drafts, shares):
            net = net - share
            tax = net.percent(product.tax_rate)
            code = promotion.code if promotion is not None else None
            lines.append(QuoteLine(product.sku, quantity, unit, gross, code, discount,
                                   share, net, product.tax_rate, tax))
        return Quote(currency, tuple(lines), applied)
