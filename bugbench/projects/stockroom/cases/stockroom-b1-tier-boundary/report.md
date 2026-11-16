# Quantity discount missing when ordering exactly the tier quantity

Our widget has a quantity price: 2.50 PLN each, 2.30 PLN from 10 units, 2.10 PLN
from 50 units.

```
product WID-001 "Widget" 2.50 tiers 10=2.30 50=2.10
receive WID-001 100 @ 1.20 on 2026-03-01
order O-1 on 2026-03-02 : WID-001 x 10
confirm O-1
```

Expected: unit price 2.30 PLN, so the order total is 28.29 PLN (23.00 net + 5.29 VAT).
Actual: unit price 2.50 PLN and a total of 30.75 PLN.

With 11 units the 2.30 price is applied correctly. Customers ordering exactly
the advertised quantity ("from 10 units") are overcharged. The README says a
tier applies to lines whose quantity is at least the tier's minimum quantity.
