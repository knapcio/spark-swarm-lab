"""The project's own regression tests (visible to everyone)."""
import datetime
import unittest

from stockroom import InsufficientStock, InvalidAmount, JournalError, Money, Period, Store, replay
from stockroom.journal import tokenize

D = datetime.date


def small_store():
    store = Store("PLN")
    store.add_product("WID-001", "Widget", "2.50", tiers=[(10, "2.30"), (50, "2.10")])
    store.add_product("GAD-002", "Gadget", "40.00")
    store.add_product("BOK-003", "Book", "30.00", tax_class="reduced")
    store.receive("WID-001", 100, "1.20", D(2026, 3, 1))
    store.receive("GAD-002", 5, "25.00", D(2026, 3, 1))
    store.receive("BOK-003", 20, "18.00", D(2026, 3, 1))
    return store


class MoneyTests(unittest.TestCase):
    def test_rounding_is_half_up(self):
        self.assertEqual(Money("0.125", "PLN").amount, Money("0.13", "PLN").amount)
        self.assertEqual(Money("2.50", "PLN").percent(23), Money("0.58", "PLN"))

    def test_floats_are_rejected(self):
        with self.assertRaises(InvalidAmount):
            Money(0.1, "PLN")

    def test_allocate_keeps_every_grosz(self):
        parts = Money("100.00", "PLN").allocate([1, 1, 1])
        self.assertEqual([str(part) for part in parts], ["33.34 PLN", "33.33 PLN", "33.33 PLN"])


class PricingTests(unittest.TestCase):
    def test_list_price_for_single_unit(self):
        quote = small_store().pricing.quote([("WID-001", 1)])
        self.assertEqual(quote.line("WID-001").unit_price, Money("2.50", "PLN"))

    def test_large_order_gets_tier_price(self):
        quote = small_store().pricing.quote([("WID-001", 60)])
        self.assertEqual(quote.line("WID-001").unit_price, Money("2.10", "PLN"))

    def test_vat_per_line(self):
        quote = small_store().pricing.quote([("GAD-002", 1), ("BOK-003", 1)])
        self.assertEqual(quote.tax, Money("11.60", "PLN"))
        self.assertEqual(quote.total, Money("81.60", "PLN"))

    def test_best_promotion_wins(self):
        store = small_store()
        store.percent_off("TEN", ["GAD-002"], "10")
        store.percent_off("TWENTY", ["GAD-002"], "20")
        line = store.pricing.quote([("GAD-002", 2)]).line("GAD-002")
        self.assertEqual((line.promotion, line.discount), ("TWENTY", Money("16.00", "PLN")))


class InventoryTests(unittest.TestCase):
    def test_fifo_cogs(self):
        store = small_store()
        store.receive("WID-001", 10, "1.50", D(2026, 3, 2))
        taken = store.inventory.issue("WID-001", 105)
        self.assertEqual(sum(item.quantity for item in taken), 105)
        self.assertEqual(sum((item.cost for item in taken), Money.zero("PLN")), Money("127.50", "PLN"))

    def test_snapshot_ignores_later_receipts(self):
        store = small_store()
        store.take_snapshot("before")
        store.receive("WID-001", 10, "1.50", D(2026, 3, 2))
        self.assertEqual(store.valuation("before")["value"], Money("605.00", "PLN"))
        self.assertEqual(store.valuation()["value"], Money("620.00", "PLN"))


class OrderTests(unittest.TestCase):
    def test_happy_path(self):
        store = small_store()
        store.place("O-1", [("WID-001", 4), ("GAD-002", 1)], D(2026, 3, 3))
        self.assertEqual(store.inventory.available("GAD-002"), 4)
        shipment = store.ship("O-1", D(2026, 3, 4))
        self.assertEqual(shipment.cogs, Money("29.80", "PLN"))
        self.assertEqual(store.orders.get("O-1").status, "shipped")
        self.assertEqual(store.inventory.reserved("GAD-002"), 0)

    def test_failed_shipment_changes_nothing(self):
        store = small_store()
        store.place("O-1", [("WID-001", 4), ("GAD-002", 3)], D(2026, 3, 3))
        store.write_off("GAD-002", 4, D(2026, 3, 3), "flood")
        with self.assertRaises(InsufficientStock):
            store.ship("O-1", D(2026, 3, 4))
        self.assertEqual(store.inventory.on_hand("WID-001"), 100)
        self.assertEqual(store.orders.get("O-1").status, "confirmed")

    def test_cancel_releases_reservation(self):
        store = small_store()
        store.place("O-1", [("BOK-003", 5)], D(2026, 3, 3))
        store.cancel("O-1")
        self.assertEqual(store.inventory.available("BOK-003"), 20)


class ReportTests(unittest.TestCase):
    def test_period_is_half_open(self):
        march = Period.month(2026, 3)
        self.assertTrue(march.contains(D(2026, 3, 31)))
        self.assertFalse(march.contains(D(2026, 4, 1)))

    def test_top_skus(self):
        store = small_store()
        store.place("O-1", [("WID-001", 3), ("BOK-003", 3), ("GAD-002", 1)], D(2026, 3, 3))
        store.ship("O-1", D(2026, 3, 4))
        self.assertEqual(store.top_skus(D(2026, 3, 1), D(2026, 4, 1)), [("BOK-003", 3), ("WID-001", 3), ("GAD-002", 1)])


class JournalTests(unittest.TestCase):
    def test_tokenize(self):
        self.assertEqual(tokenize('product A "B C" 1'), ["product", "A", "B C", "1"])
        self.assertEqual(tokenize("ship O-1 on 2026-01-01 : X x 1, Y x 2")[4:], [":", "X", "x", "1", ",", "Y", "x", "2"])

    def test_replay(self):
        store, results = replay(
            'product WID-001 "Widget" 2.50\n'
            "receive WID-001 10 @ 1.00 on 2026-03-01\n"
            "order O-1 on 2026-03-02 : WID-001 x 2\n"
            "confirm O-1\n"
            "ship O-1 on 2026-03-03\n")
        self.assertEqual(results[-1]["cogs"], "2.00 PLN")
        self.assertEqual(store.inventory.on_hand("WID-001"), 8)

    def test_error_has_line_number(self):
        with self.assertRaises(JournalError) as caught:
            replay('product WID-001 "Widget" 2.50\nreceive WID-001 ten @ 1.00 on 2026-03-01\n')
        self.assertEqual(caught.exception.line, 2)


if __name__ == "__main__":
    unittest.main()
