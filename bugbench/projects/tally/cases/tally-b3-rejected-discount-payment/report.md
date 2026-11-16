# Acme lost its early payment discount after a rejected payment

Acme has terms of 30 days net with 2 % discount within 10 days. We invoiced
A-1 on 24 April 2026 (10 widgets at 10.00, VAT S, gross 123.00) and A-2 on
28 April (5 widgets, gross 61.50), then closed April. A clerk entered Acme's
payment of 180.81 with the date 29 April by mistake. It was rejected with
`PeriodClosed`, which is right. We entered it again with the real date,
3 May:

```python
import datetime
from tally import Books, PeriodClosed

books = Books()
books.add_customer("ACME", "Acme Ltd", days=30, discount="2", discount_days=10)
books.invoice("A-1", "ACME", datetime.date(2026, 4, 24), [("Widget", "10", "10.00", "S")])
books.invoice("A-2", "ACME", datetime.date(2026, 4, 28), [("Widget", "5", "10.00", "S")])
books.close_period(datetime.date(2026, 4, 30))
try:
    books.receive("P-1", "ACME", "180.81", datetime.date(2026, 4, 29))
except PeriodClosed:
    pass
payment = books.receive("P-2", "ACME", "180.81", datetime.date(2026, 5, 3))
print(payment.allocations, books.statement("ACME"), books.balance("1100"))
```

Expected: both invoices are settled with their discounts (2.46 and 1.23),
nothing is left over, the statement's balance due is 0.00 and the
receivables account (1100) is 0.00.
Actual: the payment is applied as 118.08 and 59.04 without any discount,
3.69 is kept as a prepayment (balance due -3.69), and the receivables
account still shows 7.38, although the statement lists both invoices as
open 0.00.

Without the rejected attempt, the payment on 3 May gets both discounts. A
rejected payment from Beta, who has no discount terms, leaves no trace. The
README says a payment rejected because of a closed period changes nothing.
