"""A small line-oriented command language for replaying warehouse activity.

One command per line; blank lines and lines starting with ``#`` are ignored.
Amounts are in the store currency and dates are ISO ``YYYY-MM-DD``::

    product WID-001 "Widget" 2.50 tax standard tiers 10=2.30 50=2.10
    receive WID-001 100 @ 1.20 on 2026-03-01
    writeoff WID-001 3 on 2026-03-05 reason damaged
    promo SPRING percent 10 on WID-001,GAD-002
    promo B3G1 bundle WID-001 buy 3 free 1
    order O-1 on 2026-03-02 customer ACME coupon 5.00 : WID-001 x 12, GAD-002 x 1
    confirm O-1
    ship O-1 on 2026-03-03 : WID-001 x 5
    ship O-1 on 2026-03-04
    cancel O-2 on 2026-03-04
    snapshot end-of-march

``replay`` executes the commands in order and stops at the first failing
line by raising :class:`JournalError` with the line number.
"""
import re

from .errors import JournalError, StockroomError
from .store import Store

_INT = re.compile(r"^\d+$")
_ITEM_SKU = re.compile(r"^[A-Z]{3}-\d{3}$")


def tokenize(text, line=0):
    """Split one line into tokens; double quotes group words, ``:`` and ``,`` stand alone."""
    tokens, current, quoted, index = [], [], False, 0
    while index < len(text):
        char = text[index]
        if quoted:
            if char == "\\" and index + 1 < len(text):
                current.append(text[index + 1])
                index += 1
            elif char == '"':
                quoted = False
                tokens.append("".join(current))
                current = []
            else:
                current.append(char)
        elif char == '"':
            if current:
                raise JournalError(line, "quote inside a word")
            quoted = True
        elif char.isspace() or char in ":,":
            if current:
                tokens.append("".join(current))
                current = []
            if char in ":,":
                tokens.append(char)
        else:
            current.append(char)
        index += 1
    if quoted:
        raise JournalError(line, "unterminated quote")
    if current:
        tokens.append("".join(current))
    return tokens


class _Cursor:
    def __init__(self, tokens, line):
        self.tokens, self.line, self.position = tokens, line, 0

    def more(self):
        return self.position < len(self.tokens)

    def peek(self):
        return self.tokens[self.position] if self.more() else None

    def take(self, what="value"):
        if not self.more():
            raise JournalError(self.line, f"missing {what}")
        token = self.tokens[self.position]
        self.position += 1
        return token

    def expect(self, keyword):
        token = self.take(repr(keyword))
        if token != keyword:
            raise JournalError(self.line, f"expected {keyword!r}, got {token!r}")

    def integer(self, what):
        token = self.take(what)
        if not _INT.match(token):
            raise JournalError(self.line, f"{what} must be a whole number, got {token!r}")
        return int(token)

    def date(self):
        try:
            return Store.date(self.take("date"))
        except StockroomError as exc:
            raise JournalError(self.line, str(exc)) from None

    def done(self):
        if self.more():
            raise JournalError(self.line, f"unexpected {self.peek()!r}")

    def items(self):
        """Parse ``SKU x QTY, SKU x QTY`` up to the end of the line."""
        items = []
        while True:
            sku = self.take("SKU")
            if not _ITEM_SKU.match(sku):
                raise JournalError(self.line, f"malformed SKU {sku!r}")
            self.expect("x")
            items.append((sku, self.integer("quantity")))
            if not self.more():
                return items
            self.expect(",")


def _product(cursor, store):
    sku, name, price = cursor.take("SKU"), cursor.take("name"), cursor.take("price")
    tax_class, tiers = "standard", []
    while cursor.more():
        keyword = cursor.take()
        if keyword == "tax":
            tax_class = cursor.take("tax class")
        elif keyword == "tiers":
            while cursor.more() and "=" in cursor.peek():
                quantity, _, tier_price = cursor.take().partition("=")
                if not _INT.match(quantity):
                    raise JournalError(cursor.line, f"bad tier quantity {quantity!r}")
                tiers.append((int(quantity), tier_price))
        else:
            raise JournalError(cursor.line, f"unknown product option {keyword!r}")
    store.add_product(sku, name, price, tax_class, tiers)
    return {"sku": sku}


def _receive(cursor, store):
    sku, quantity = cursor.take("SKU"), cursor.integer("quantity")
    cursor.expect("@")
    cost = cursor.take("unit cost")
    cursor.expect("on")
    on = cursor.date()
    cursor.done()
    return {"lot": store.receive(sku, quantity, cost, on)}


def _writeoff(cursor, store):
    sku, quantity = cursor.take("SKU"), cursor.integer("quantity")
    cursor.expect("on")
    on, reason = cursor.date(), ""
    if cursor.more():
        cursor.expect("reason")
        reason = cursor.take("reason")
    cursor.done()
    store.write_off(sku, quantity, on, reason)
    return {"sku": sku, "quantity": quantity}


def _promo(cursor, store):
    code, kind = cursor.take("code"), cursor.take("promotion kind")
    if kind == "percent":
        percent = cursor.take("percent")
        cursor.expect("on")
        skus = [cursor.take("SKU")]
        while cursor.more():
            cursor.expect(",")
            skus.append(cursor.take("SKU"))
        store.percent_off(code, skus, percent)
    elif kind == "bundle":
        sku = cursor.take("SKU")
        cursor.expect("buy")
        buy = cursor.integer("buy")
        cursor.expect("free")
        free = cursor.integer("free")
        cursor.done()
        store.bundle(code, sku, buy, free)
    else:
        raise JournalError(cursor.line, f"unknown promotion kind {kind!r}")
    return {"code": code}


def _order(cursor, store):
    order_id = cursor.take("order id")
    cursor.expect("on")
    on, customer, coupon = cursor.date(), "", None
    while cursor.peek() in ("customer", "coupon"):
        if cursor.take() == "customer":
            customer = cursor.take("customer")
        else:
            coupon = cursor.take("coupon amount")
    cursor.expect(":")
    store.order(order_id, cursor.items(), on, customer, coupon)
    return {"order": order_id}


def _confirm(cursor, store):
    order_id = cursor.take("order id")
    cursor.done()
    quote = store.confirm(order_id)
    return {"order": order_id, "total": str(quote.total)}


def _ship(cursor, store):
    order_id = cursor.take("order id")
    cursor.expect("on")
    on, items = cursor.date(), None
    if cursor.more():
        cursor.expect(":")
        items = dict(cursor.items())
    shipment = store.ship(order_id, on, items)
    return {"shipment": shipment.shipment_id, "cogs": str(shipment.cogs)}


def _cancel(cursor, store):
    order_id, on = cursor.take("order id"), None
    if cursor.more():
        cursor.expect("on")
        on = cursor.date()
    cursor.done()
    store.cancel(order_id, on)
    return {"order": order_id}


def _snapshot(cursor, store):
    label = cursor.take("label")
    cursor.done()
    store.take_snapshot(label)
    return {"label": label}


COMMANDS = {"product": _product, "receive": _receive, "writeoff": _writeoff, "promo": _promo,
            "order": _order, "confirm": _confirm, "ship": _ship, "cancel": _cancel,
            "snapshot": _snapshot}


def replay(text, store=None):
    """Execute every command in ``text``; return ``(store, results)``."""
    store = Store() if store is None else store
    results = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cursor = _Cursor(tokenize(stripped, number), number)
        command = cursor.take("command")
        handler = COMMANDS.get(command)
        if handler is None:
            raise JournalError(number, f"unknown command {command!r}")
        try:
            result = handler(cursor, store)
        except JournalError:
            raise
        except StockroomError as exc:
            raise JournalError(number, str(exc)) from exc
        result.update(line=number, command=command)
        results.append(result)
    return store, results
