# Invoice VAT is one cent too low

Invoice INV-31 to Beta has three lines, all at the standard rate (VAT code
S, 23 %): 1 toner at 189.00, 12 pens at 1.15 and 2 label packs at 12.35. The
net total is 227.50.

```python
import datetime
from tally import Books

books = Books()
books.add_customer("BETA", "Beta", days=14)
invoice = books.invoice("INV-31", "BETA", datetime.date(2026, 5, 4),
                        [("Toner", "1", "189.00", "S"), ("Pens", "12", "1.15", "S"), ("Labels", "2", "12.35", "S")])
print(invoice.tax, invoice.gross)
```

Expected: VAT 52.33 (23 % of 227.50 is 52.325, rounded half-up) and gross
279.83.
Actual: VAT 52.32 and gross 279.82.

The May VAT report also shows 52.32 for the 23 % row. Invoices with one line
per VAT code come out right. The README says VAT is computed per VAT code on
the sum of the line nets and rounded once per code, not per line.
