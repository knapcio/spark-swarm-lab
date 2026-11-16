"""The project's own regression tests (visible to everyone)."""
import datetime
import unittest

from tally import (Books, Chart, CreditTooLarge, InvalidAmount, PeriodClosed, ScriptError, UnbalancedEntry,
                   UnknownAccount, fmt, make_line, parse_amount, replay)

D = datetime.date


def acme_books():
    books = Books()
    books.add_customer("ACME", "Acme Ltd", days=30, discount="2", discount_days=10)
    books.add_customer("BETA", "Beta sp. z o.o.", days=14)
    return books


class MoneyTests(unittest.TestCase):
    def test_parse_and_format(self):
        self.assertEqual(parse_amount("1234.5"), 123450)
        self.assertEqual(fmt(-5), "-0.05")
        with self.assertRaises(InvalidAmount):
            parse_amount("1.234")

    def test_line_net_rounds_half_up(self):
        self.assertEqual(make_line("Paper", "3", "0.15", "S", "50").net, 23)


class LedgerTests(unittest.TestCase):
    def test_unbalanced_entry_is_rejected(self):
        books = Books()
        with self.assertRaises(UnbalancedEntry):
            books.journal(D(2026, 1, 5), "Typo", [("6000", 10000, 0), ("1000", 0, 9000)])
        with self.assertRaises(UnknownAccount):
            books.journal(D(2026, 1, 5), "Typo", [("6999", 10000, 0), ("1000", 0, 10000)])
        self.assertEqual(books.ledger.entries(), [])

    def test_chart_kinds(self):
        chart = Chart()
        self.assertEqual(chart.add("6200", "Travel").kind, "expense")
        self.assertEqual(chart.codes("income"), ["4000", "4100"])

    def test_closed_period_and_year_end(self):
        books = Books()
        books.journal(D(2026, 1, 5), "Capital", [("1000", 500000, 0), ("3000", 0, 500000)])
        books.journal(D(2026, 2, 1), "Rent", [("6000", 120000, 0), ("1000", 0, 120000)])
        books.close_period(D(2026, 1, 31))
        with self.assertRaises(PeriodClosed):
            books.journal(D(2026, 1, 31), "Late", [("6000", 100, 0), ("1000", 0, 100)])
        books.close_year(D(2026, 12, 31))
        self.assertEqual(books.balance("3200"), -120000)
        self.assertEqual(books.balance("6000"), 0)


class InvoiceTests(unittest.TestCase):
    def test_invoice_totals_and_posting(self):
        books = acme_books()
        invoice = books.invoice("INV-1", "ACME", D(2026, 5, 4), [("Widget", "3", "10.00", "S"), ("Guide", "2", "30.00", "P")])
        self.assertEqual((invoice.net, invoice.tax, invoice.gross), (9000, 990, 9990))
        self.assertEqual([(t.code, t.net, t.tax) for t in invoice.tax_lines], [("S", 3000, 690), ("P", 6000, 300)])
        self.assertEqual(books.balance("1100"), 9990)
        self.assertEqual(books.balance("2200"), 990)

    def test_credit_note_limit(self):
        books = acme_books()
        books.invoice("INV-1", "BETA", D(2026, 5, 4), [("Audit", "1", "100.00", "S")])
        books.credit_note("CN-1", "INV-1", D(2026, 5, 6), [("Audit discount", "1", "20.00", "S")])
        self.assertEqual(books.invoices.get("INV-1").open, 9840)
        with self.assertRaises(CreditTooLarge):
            books.credit_note("CN-2", "INV-1", D(2026, 5, 7), [("Too much", "1", "90.00", "S")])


class PaymentTests(unittest.TestCase):
    def test_early_payment_discount(self):
        books = acme_books()
        books.invoice("INV-1", "ACME", D(2026, 5, 4), [("Widget", "10", "10.00", "S")])
        payment = books.receive("P-1", "ACME", "120.54", D(2026, 5, 8))
        self.assertEqual(payment.allocations, (("INV-1", 12054, 246),))
        self.assertEqual(books.balance("1100"), 0)
        self.assertEqual(books.balance("5900"), 246)

    def test_late_payment_is_partial(self):
        books = acme_books()
        books.invoice("INV-1", "ACME", D(2026, 5, 4), [("Widget", "10", "10.00", "S")])
        books.receive("P-1", "ACME", "120.54", D(2026, 5, 20))
        self.assertEqual(books.invoices.get("INV-1").open, 246)

    def test_allocation_order_and_prepayment(self):
        books = acme_books()
        books.invoice("B-1", "BETA", D(2026, 5, 10), [("Audit", "1", "100.00", "S")])
        books.invoice("B-2", "BETA", D(2026, 5, 2), [("Audit", "1", "50.00", "S")])
        payment = books.receive("P-1", "BETA", "200.00", D(2026, 5, 30))
        self.assertEqual(payment.allocations, (("B-2", 6150, 0), ("B-1", 12300, 0)))
        self.assertEqual(books.payments.prepaid("BETA"), 1550)
        books.invoice("B-3", "BETA", D(2026, 6, 1), [("Audit", "1", "10.00", "S")])
        self.assertEqual(books.apply_prepayment("BETA", D(2026, 6, 2)), 1230)

    def test_rejected_payment_changes_nothing(self):
        books = acme_books()
        books.invoice("B-1", "BETA", D(2026, 5, 10), [("Audit", "1", "100.00", "S")])
        books.close_period(D(2026, 5, 31))
        with self.assertRaises(PeriodClosed):
            books.receive("P-1", "BETA", "50.00", D(2026, 5, 31))
        self.assertEqual(books.invoices.get("B-1").open, 12300)
        self.assertEqual(books.payments.payments(), [])


class ReportTests(unittest.TestCase):
    def test_trial_balance_and_aging(self):
        books = acme_books()
        books.invoice("B-1", "BETA", D(2026, 5, 1), [("Audit", "1", "100.00", "S")])
        rows = books.trial_balance()
        self.assertEqual(rows[-1], ["total", "", "123.00", "123.00"])
        self.assertEqual(books.aged_receivables(D(2026, 6, 14))[0], ["BETA", "0.00", "123.00", "0.00", "0.00", "0.00", "123.00"])
        self.assertEqual(books.vat_report(D(2026, 5, 1), D(2026, 5, 31)), [["23%", "100.00", "23.00"], ["total", "100.00", "23.00"]])


class ScriptTests(unittest.TestCase):
    def test_replay(self):
        _, results = replay('customer ACME "Acme Ltd" net 30\n'
                            'invoice INV-1 to ACME on 2026-05-04 : 2 x "Widget" @ 10.00 S less 50\n'
                            "pay P-1 from ACME 5.00 on 2026-05-05\nstatement ACME\n")
        self.assertEqual(results[1]["gross"], "12.30")
        self.assertEqual(results[-1]["lines"], ["INV-1 2026-05-04 12.30 open 7.30", "prepaid 0.00", "balance due 7.30"])

    def test_error_line(self):
        with self.assertRaises(ScriptError) as caught:
            replay('customer ACME "Acme" net 30\n\npay P-1 from NOBODY 5.00 on 2026-05-05\n')
        self.assertEqual(caught.exception.line, 3)


if __name__ == "__main__":
    unittest.main()
