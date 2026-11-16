# tally

Small double-entry bookkeeping for a service business: a chart of accounts,
a general ledger with closed periods and year-end closing, invoices and
credit notes with VAT, customer payments with early payment discounts and
prepayments, reports and a line-oriented script language. Standard library
only, Python 3.10+.

```python
import datetime
from tally import Books

books = Books()
books.add_customer("ACME", "Acme Ltd", days=30, discount="2", discount_days=10)
books.invoice("INV-1", "ACME", datetime.date(2026, 5, 4), [("Widget", "3", "10.00", "S")])
books.receive("P-1", "ACME", "36.16", datetime.date(2026, 5, 12))
print(books.statement("ACME"), books.trial_balance())
```

## Modules

| Module | Responsibility |
|---|---|
| `money.py` | Cents, half-up rounding, parsing amounts, percentages, quantities and dates |
| `ledger.py` | Chart of accounts and normal balances; journal entries, balances, closed periods, year-end closing |
| `tax.py` | VAT codes and the per-code VAT summary |
| `invoices.py` | Customers, terms, invoice lines, invoices and credit notes |
| `payments.py` | Payment allocation, early payment discounts, prepayments |
| `reports.py` | Trial balance, balance sheet, income statement, VAT report, aged receivables, statements |
| `books.py` | `Books` facade |
| `script.py` | Text command language and replay |
| `errors.py` | Exception hierarchy |

## Business rules

- Amounts are integer cents. Every rounding is half-up to whole cents.
- Every journal entry balances: debits equal credits. Balances are reported
  in each account's normal direction (debit for assets and expenses, credit
  for liabilities, equity and income).
- Nothing may be posted on or before the date the books are closed through.
  Closing a year moves the income and expense balances into retained
  earnings (3200) and closes the books through the year end.
- A line's net is quantity x unit price less the line discount, rounded
  half-up. VAT is computed per VAT code on the sum of the line nets with
  that code and rounded once per code, not per line.
- An invoice is due `days` after its issue date. If its terms offer an early
  payment discount, a payment received on or before the issue date plus
  `discount_days` that covers the open amount less the discount settles the
  invoice in full; the discount is its percentage of the invoice's gross
  total. An invoice earns the discount at most once.
- Payments go to the customer's open invoices issued on or before the
  payment date, earliest due date first, then in issue order. Any remainder
  becomes a prepayment.
- A credit note may not exceed the open amount of its invoice.
- Every operation either completes or raises without changing anything,
  including a payment that is rejected because its date is in a closed
  period.
- Reports never change the books. Aging buckets count days past the due
  date: `current` (not yet due), `1-30`, `31-60`, `61-90`, `90+`.

Run the tests with `python -m unittest discover -s tests`.
