"""Hidden behavioural probes for the stockroom project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY 7f3c2a91-bugbench-stockroom-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes may only use the documented
public API (``README.md`` and docstrings), so any fix that preserves documented
behaviour can pass.
"""
import datetime

D = datetime.date


def _m(value):
    return str(value)


def _error(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__
    return None


def _store(tiers=((10, "2.30"), (50, "2.10"))):
    from stockroom import Store
    store = Store("PLN")
    store.add_product("WID-001", "Widget", "2.50", tiers=list(tiers))
    store.add_product("GAD-002", "Gadget", "40.00")
    store.add_product("BOK-003", "Book", "30.00", tax_class="reduced")
    store.add_product("FOO-004", "Food", "9.99", tax_class="zero")
    return store


def _lines(quote):
    return [[line.sku, line.quantity, _m(line.unit_price), _m(line.gross), line.promotion, _m(line.discount),
             _m(line.coupon_share), _m(line.net), _m(line.tax)] for line in quote.lines]


# --- money --------------------------------------------------------------------
def probe_money_rounding_and_parse():
    from stockroom import Money
    return [_m(Money("0.005", "PLN")), _m(Money("-0.005", "PLN")), _m(Money("2.675", "EUR")),
            _m(Money("12", "JPY")), _m(Money("1.0005", "KWD")), _m(Money.parse(" 12.5 USD ")),
            Money("3.20", "PLN").minor_units, _m(Money.from_minor(-1234, "PLN")),
            _m(Money("19.99", "PLN").times(3)), _m(Money("2.50", "PLN").percent("23")),
            _error(Money, 0.5, "PLN"), _error(Money, "1", "XYZ"), _error(Money.parse, "12,50 PLN")]


def probe_money_allocate():
    from stockroom import Money
    cases = [("100.00", [1, 1, 1]), ("0.05", [1, 1, 1]), ("-0.05", [1, 1, 1]), ("10.00", [3, 0, 1]),
             ("1.00", ["0.5", "0.25", "0.25"]), ("7", [1, 1, 1, 1])]
    out = [[_m(part) for part in Money(amount, "JPY" if amount == "7" else "PLN").allocate(ratios)]
           for amount, ratios in cases]
    out.append(_error(Money("1.00", "PLN").allocate, [0, 0]))
    return out


def probe_money_compare_and_mismatch():
    from stockroom import Money
    a, b = Money("1.00", "PLN"), Money("1.00", "EUR")
    return [a == b, a == Money("1.0", "PLN"), _error(lambda: a + b), _error(lambda: a < b),
            sorted(_m(x) for x in [Money("3", "PLN"), Money("-1", "PLN"), Money("2.5", "PLN")]),
            bool(Money("0.00", "PLN")), _error(setattr, a, "_amount", 5),
            [a < Money("1.00", "PLN"), a <= Money("1.00", "PLN"), a > Money("0.99", "PLN"), a >= Money("1.01", "PLN")]]


# --- catalogue ------------------------------------------------------------------
def probe_catalog_validation():
    from stockroom import Store
    store = Store("PLN")
    return [_error(store.add_product, "wid-1", "x", "1.00"),
            _error(store.add_product, "WID-001", "x", "1.00", "luxury"),
            _error(store.add_product, "WID-001", "x", "1.00", tiers=[(1, "0.90")]),
            _error(store.add_product, "WID-001", "x", "1.00", tiers=[(5, "1.10")]),
            _error(store.add_product, "WID-001", "x", "1.00", tiers=[(5, "0.90"), (5, "0.80")]),
            _m(store.add_product("WID-001", "x", "1.00", tiers=[(20, "0.80"), (5, "0.90")]).tiers[0].unit_price),
            _error(store.add_product, "WID-001", "y", "2.00"),
            store.catalog.skus(), _error(store.catalog.get, "NOP-000")]


# --- pricing: tiers -----------------------------------------------------------
def probe_tier_below_and_above_boundaries():
    store = _store()
    return [[q, _m(store.pricing.unit_price("WID-001", q))] for q in (1, 2, 9, 11, 49, 51, 500)]


def probe_tier_exact_boundaries():
    store = _store()
    return [[q, _m(store.pricing.unit_price("WID-001", q))] for q in (10, 50)]


def probe_tier_boundary_other_product():
    from stockroom import Store
    store = Store("EUR")
    store.add_product("PEN-010", "Pen", "1.00", tiers=[(3, "0.95"), (12, "0.80"), (144, "0.50")])
    quote = store.pricing.quote([("PEN-010", 12)])
    return [_m(store.pricing.unit_price("PEN-010", 3)), _m(store.pricing.unit_price("PEN-010", 144)),
            _m(quote.total), _lines(quote)]


def probe_tier_boundary_via_journal():
    from stockroom import replay
    _, results = replay('product CUP-020 "Cup" 8.00 tiers 6=7.00 24=6.00\n'
                        "receive CUP-020 100 @ 3.00 on 2026-05-01\n"
                        "order O-9 on 2026-05-02 : CUP-020 x 24\n"
                        "confirm O-9\n")
    return results[-1]["total"]


# --- pricing: promotions, coupons, VAT ----------------------------------------
def probe_promotion_tie_and_bundle():
    store = _store()
    store.percent_off("FIRST", ["GAD-002", "BOK-003"], "25")
    store.bundle("B3G1", "GAD-002", 3, 1)
    store.percent_off("SECOND", ["GAD-002"], "25")
    quote = store.pricing.quote([("GAD-002", 4), ("BOK-003", 2), ("WID-001", 8)])
    out = _lines(quote)
    store.pricing.remove_promotion("FIRST")
    out.append(_lines(store.pricing.quote([("GAD-002", 4)])))
    out.append(_error(store.percent_off, "SECOND", ["GAD-002"], "5"))
    out.append(_error(store.percent_off, "BAD", ["GAD-002"], "0"))
    return out


def probe_coupon_allocation_and_vat():
    store = _store()
    quote = store.pricing.quote([("GAD-002", 1), ("BOK-003", 1), ("FOO-004", 1)], coupon=store.money("10.00"))
    big = store.pricing.quote([("FOO-004", 1)], coupon=store.money("50.00"))
    return [_lines(quote), _m(quote.net), _m(quote.tax), _m(quote.total), _m(big.coupon), _m(big.total),
            _error(store.pricing.quote, []), _error(store.pricing.quote, [("GAD-002", 1), ("GAD-002", 2)])]


# --- inventory ----------------------------------------------------------------
def probe_fifo_and_backdated_receipt():
    store = _store()
    store.receive("WID-001", 5, "1.00", D(2026, 3, 2))
    store.receive("WID-001", 5, "2.00", D(2026, 3, 1))
    store.receive("WID-001", 5, "3.00", D(2026, 3, 2))
    taken = store.inventory.issue("WID-001", 7)
    return [[c.lot_id, c.quantity, _m(c.cost)] for c in taken] + [
        [lot.lot_id, lot.quantity] for lot in store.inventory.lots("WID-001")]


def probe_reservations():
    store = _store()
    store.receive("GAD-002", 5, "20.00", D(2026, 3, 1))
    inv = store.inventory
    inv.reserve("A", {"GAD-002": 3})
    out = [inv.available("GAD-002"), _error(inv.reserve, "B", {"GAD-002": 3}), inv.reserved("GAD-002"),
           _error(inv.release, "A", "GAD-002", 4)]
    inv.release("A", "GAD-002", 1)
    out.append([inv.reservation("A", "GAD-002"), inv.available("GAD-002")])
    store.write_off("GAD-002", 4, D(2026, 3, 2))
    out.append([inv.on_hand("GAD-002"), inv.reserved("GAD-002"), inv.available("GAD-002")])
    inv.release("A")
    out.append(inv.reserved("GAD-002"))
    return out


def probe_snapshot_after_receipt():
    store = _store()
    store.receive("WID-001", 10, "1.00", D(2026, 3, 1))
    store.take_snapshot("s")
    store.receive("WID-001", 10, "2.00", D(2026, 3, 2))
    return [_m(store.valuation("s")["value"]), _m(store.valuation()["value"]),
            _error(store.take_snapshot, "s"), _error(store.snapshot, "nope")]


def probe_snapshot_after_shipment():
    store = _store()
    store.receive("WID-001", 10, "1.00", D(2026, 3, 1))
    store.receive("BOK-003", 4, "12.50", D(2026, 3, 1))
    store.place("O-1", [("WID-001", 6), ("BOK-003", 4)], D(2026, 3, 2))
    store.take_snapshot("before-shipping")
    store.ship("O-1", D(2026, 3, 3))
    report = store.valuation("before-shipping")
    return [[line["sku"], line["quantity"], _m(line["value"])] for line in report["lines"]] + [
        report["quantity"], _m(report["value"]), _m(store.valuation()["value"])]


def probe_snapshot_after_writeoff():
    store = _store()
    store.receive("GAD-002", 3, "21.00", D(2026, 3, 1))
    snap = store.take_snapshot("t0")
    store.write_off("GAD-002", 2, D(2026, 3, 4), "broken")
    return [snap.on_hand("GAD-002"), store.snapshot("t0").on_hand("GAD-002"), store.inventory.on_hand("GAD-002")]


def probe_snapshot_survives_direct_issue():
    store = _store()
    store.receive("FOO-004", 4, "4.00", D(2026, 3, 1))
    store.receive("FOO-004", 4, "5.00", D(2026, 3, 2))
    snap = store.inventory.snapshot("t0")
    store.inventory.issue("FOO-004", 6)
    return [[[lot.lot_id, lot.quantity] for lot in snap.lots["FOO-004"]], snap.on_hand("FOO-004"),
            store.inventory.on_hand("FOO-004")]


def probe_accessors_and_validation_edges():
    store = _store(tiers=((2, "2.50"),))
    out = [_m(store.pricing.unit_price("WID-001", 2))]
    store.receive("WID-001", 3, "0.00", D(2026, 3, 1))
    store.receive("GAD-002", 2, "20.00", D(2026, 3, 1))
    out.append(_error(store.receive, "WID-001", 1, "-0.01", D(2026, 3, 1)))
    copies = store.inventory.lots("WID-001")
    copies[0].quantity = 99
    out.append(store.inventory.on_hand("WID-001"))
    store.percent_off("ALL", ["GAD-002"], "100")
    quote = store.pricing.quote([("WID-001", 1), ("GAD-002", 1)])
    out.append([_m(quote.line("GAD-002").net), _m(quote.total), _error(quote.line, "BOK-003")])
    store.place("O-1", [("WID-001", 2)], D(2026, 3, 2))
    store.order("O-2", [("GAD-002", 1)], D(2026, 3, 2))
    store.ship("O-1", D(2026, 3, 3), {"WID-001": 1})
    out.append([[o.order_id for o in store.orders.orders(status)] for status in ("draft", "partially_shipped", "shipped")])
    out.append([[m.kind, m.sku, m.quantity, m.reference] for m in store.inventory.movements("WID-001")])
    out.append(len(store.inventory.movements()))
    return out


# --- orders -------------------------------------------------------------------
def probe_order_lifecycle():
    store = _store()
    store.receive("WID-001", 30, "1.00", D(2026, 3, 1))
    store.receive("GAD-002", 2, "20.00", D(2026, 3, 1))
    store.order("O-1", [("WID-001", 12), ("GAD-002", 2)], D(2026, 3, 2), coupon="3.00")
    out = [_error(store.ship, "O-1", D(2026, 3, 2))]
    quote = store.confirm("O-1")
    out += [_m(quote.total), _error(store.confirm, "O-1"), store.inventory.available("WID-001")]
    first = store.ship("O-1", D(2026, 3, 3), {"WID-001": 5})
    out += [first.shipment_id, _m(first.cogs), store.orders.get("O-1").status,
            _error(store.ship, "O-1", D(2026, 3, 3), {"WID-001": 8}),
            _error(store.ship, "O-1", D(2026, 3, 3), {"BOK-003": 1})]
    second = store.ship("O-1", D(2026, 3, 4))
    order = store.orders.get("O-1")
    out += [second.items, order.status, str(order.closed_on), _m(order.cogs("PLN")),
            _error(store.cancel, "O-1"), store.inventory.reserved("WID-001")]
    return out


def probe_cancel_after_partial_shipment():
    store = _store()
    store.receive("BOK-003", 10, "15.00", D(2026, 3, 1))
    store.place("O-1", [("BOK-003", 6)], D(2026, 3, 2))
    store.ship("O-1", D(2026, 3, 3), {"BOK-003": 2})
    store.cancel("O-1", D(2026, 3, 5))
    order = store.orders.get("O-1")
    return [order.status, order.remaining("BOK-003"), store.inventory.on_hand("BOK-003"),
            store.inventory.available("BOK-003"), _error(store.ship, "O-1", D(2026, 3, 6))]


def probe_place_rolls_back_on_shortage():
    store = _store()
    store.receive("GAD-002", 1, "20.00", D(2026, 3, 1))
    error = _error(store.place, "O-1", [("GAD-002", 2)], D(2026, 3, 2))
    return [error, store.orders.get("O-1").status, store.inventory.reserved("GAD-002"),
            _error(store.order, "O-1", [("GAD-002", 1)], D(2026, 3, 2)),
            _error(store.order, "O-2", [("GAD-002", 0)], D(2026, 3, 2))]


def probe_failed_shipment_partial_lot():
    store = _store()
    store.receive("WID-001", 10, "1.00", D(2026, 3, 1))
    store.receive("GAD-002", 2, "20.00", D(2026, 3, 1))
    store.place("O-1", [("WID-001", 4), ("GAD-002", 2)], D(2026, 3, 2))
    store.write_off("GAD-002", 1, D(2026, 3, 2))
    error = _error(store.ship, "O-1", D(2026, 3, 3))
    return [error, [[lot.lot_id, lot.quantity] for lot in store.inventory.lots("WID-001")],
            store.inventory.reservation("O-1", "WID-001"), store.orders.get("O-1").status]


def _rollback_store():
    store = _store()
    store.receive("WID-001", 10, "1.00", D(2026, 3, 1))
    store.receive("WID-001", 10, "2.00", D(2026, 3, 2))
    store.receive("GAD-002", 2, "20.00", D(2026, 3, 1))
    store.place("O-1", [("WID-001", 10), ("GAD-002", 2)], D(2026, 3, 3))
    store.write_off("GAD-002", 1, D(2026, 3, 3), "dropped")
    return store


def probe_failed_shipment_then_cogs():
    store = _rollback_store()
    error = _error(store.ship, "O-1", D(2026, 3, 4))
    store.cancel("O-1", D(2026, 3, 4))
    store.place("O-2", [("WID-001", 5)], D(2026, 3, 5))
    shipment = store.ship("O-2", D(2026, 3, 6))
    return [error, _m(shipment.cogs), [c.lot_id for c in shipment.consumptions]]


def probe_failed_shipment_restores_lot_order():
    store = _rollback_store()
    before = [[lot.lot_id, lot.quantity, str(lot.received_on)] for lot in store.inventory.lots("WID-001")]
    _error(store.ship, "O-1", D(2026, 3, 4))
    after = [[lot.lot_id, lot.quantity, str(lot.received_on)] for lot in store.inventory.lots("WID-001")]
    return [before == after, after, store.inventory.reservation("O-1", "WID-001")]


def probe_failed_shipment_three_lots():
    store = _store()
    for day, cost in ((1, "1.00"), (2, "1.10"), (3, "1.20"), (4, "1.30")):
        store.receive("FOO-004", 3, cost, D(2026, 4, day))
    store.receive("BOK-003", 1, "10.00", D(2026, 4, 1))
    store.place("O-1", [("FOO-004", 8), ("BOK-003", 1)], D(2026, 4, 5))
    store.write_off("BOK-003", 1, D(2026, 4, 5))
    _error(store.ship, "O-1", D(2026, 4, 6), {"FOO-004": 7, "BOK-003": 1})
    shipment = store.ship("O-1", D(2026, 4, 6), {"FOO-004": 8})
    return [_m(shipment.cogs), [[c.lot_id, c.quantity] for c in shipment.consumptions]]


def probe_failed_shipment_via_journal():
    from stockroom import JournalError, replay
    setup = ('product MUG-030 "Mug" 12.00\nproduct TEA-031 "Tea" 9.00 tax reduced\n'
             "receive MUG-030 4 @ 5.00 on 2026-06-01\nreceive MUG-030 4 @ 6.50 on 2026-06-02\n"
             "receive TEA-031 1 @ 4.00 on 2026-06-01\n"
             "order A on 2026-06-03 : MUG-030 x 4, TEA-031 x 1\nconfirm A\n"
             "writeoff TEA-031 1 on 2026-06-03 reason expired\n")
    try:
        replay(setup + "ship A on 2026-06-04\n")
        failed_line, cause = None, None
    except JournalError as exc:
        failed_line, cause = exc.line, type(exc.__cause__).__name__
    store, _ = replay(setup)
    try:
        store.ship("A", D(2026, 6, 4))
    except Exception:
        pass
    _, results = replay("cancel A\norder B on 2026-06-05 : MUG-030 x 4\nconfirm B\nship B on 2026-06-06\n", store)
    return [failed_line, cause, results[-1]["cogs"], store.inventory.on_hand("MUG-030")]


# --- reports ------------------------------------------------------------------
def probe_reports():
    from stockroom import Period
    from stockroom.reports import order_status_counts
    store = _store()
    store.receive("WID-001", 50, "1.00", D(2026, 1, 1))
    store.receive("GAD-002", 10, "20.00", D(2026, 1, 1))
    store.receive("BOK-003", 10, "10.00", D(2026, 1, 1))
    store.place("O-1", [("WID-001", 4), ("GAD-002", 4)], D(2026, 1, 30))
    store.ship("O-1", D(2026, 1, 31))
    store.place("O-2", [("BOK-003", 4), ("WID-001", 1)], D(2026, 2, 1))
    store.ship("O-2", D(2026, 2, 1))
    store.place("O-3", [("BOK-003", 1)], D(2026, 2, 2))
    store.order("O-4", [("BOK-003", 1)], D(2026, 2, 2))
    jan = store.monthly_shipments(2026, 1)
    return [[[r["sku"], r["units"], _m(r["cogs"])] for r in jan],
            store.top_skus(D(2026, 1, 1), D(2026, 3, 1), 2), store.top_skus(D(2026, 2, 1), D(2026, 2, 2)),
            order_status_counts(store.orders), store.stock_status()[1],
            [str(p.end) for p in (Period.month(2026, 12), Period.days(D(2026, 2, 27), 2))],
            _error(Period, D(2026, 1, 2), D(2026, 1, 2))]


# --- journal ------------------------------------------------------------------
def probe_journal_parsing():
    from stockroom import replay
    from stockroom.journal import tokenize
    out = [tokenize('product X "say \\"hi\\"" 1'), tokenize("a:b,c")]
    bad = ['product WID-001 "Widget 2.50', "frobnicate\n", 'product WID-001 "W" 1.00\nreceive WID-001 5 @ 1 on 2026-13-01',
           'product WID-001 "W" 1.00 colour red', 'product WID-001 "W" 1.00\n\n# c\norder X on 2026-01-01 : WID-001 x 1 WID-001',
           'product WID-001 "W" 1.00\nreceive WID-001 5 @ 1 on 2026-01-01\norder X on 2026-01-01 : WID-001 x 9\nconfirm X']
    for text in bad:
        try:
            replay(text)
            out.append(None)
        except Exception as exc:
            out.append([type(exc).__name__, getattr(exc, "line", None),
                        type(exc.__cause__).__name__ if exc.__cause__ else None])
    store, results = replay('product WID-001 "Wide widget" 2.50 tax reduced tiers 10=2.30\n'
                            "promo P percent 10 on WID-001\npromo B bundle WID-001 buy 9 free 1\n"
                            "receive WID-001 20 @ 1.00 on 2026-01-01\n"
                            "order X on 2026-01-02 customer ACME coupon 1.00 : WID-001 x 11\n"
                            "confirm X\nsnapshot s1\ncancel X on 2026-01-03\n")
    out.append([[r["line"], r["command"]] for r in results])
    out.append([results[5]["total"], store.catalog.get("WID-001").name, store.orders.get("X").customer])
    return out
