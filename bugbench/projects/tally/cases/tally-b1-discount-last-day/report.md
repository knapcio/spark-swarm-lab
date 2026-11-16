# Early payment discount refused on the last day of the discount period

Acme has terms of 30 days net with 2 % discount within 10 days. Invoice A-1
was issued on 4 May 2026 for 10 widgets at 10.00 (VAT S), gross 123.00. Acme
paid 120.54 on 14 May, exactly 10 days after the invoice date.

```python
import datetime
from tally import Books

books = Books()
books.add_customer("ACME", "Acme Ltd", days=30, discount="2", discount_days=10)
books.invoice("A-1", "ACME", datetime.date(2026, 5, 4), [("Widget", "10", "10.00", "S")])
payment = books.receive("P-1", "ACME", "120.54", datetime.date(2026, 5, 14))
print(payment.allocations, books.statement("ACME"))
```

Expected: the payment settles A-1 with a discount of 2.46, and the statement
shows `A-1 2026-05-04 123.00 open 0.00`.
Actual: no discount is given, and the statement shows
`A-1 2026-05-04 123.00 open 2.46` with a balance due of 2.46.

The same payment on 13 May gets the discount. The README says the discount
applies to a payment received on or before the issue date plus
`discount_days`. Our other customer, with 1.5 % within 7 days, has the same
problem on the seventh day.
