# Amounts ending in 5 are sometimes rounded down

Our invoice lines show amounts with two decimals:

```python
from decimal import Decimal
from inkwell import Environment

line = Environment().from_string("{{ name }}: {{ amount|number(2) }} PLN")
line.render(name="Shipping", amount=Decimal("12.345"))
line.render(name="Handling", amount=Decimal("12.355"))
```

Expected: `Shipping: 12.35 PLN` and `Handling: 12.36 PLN`.
Actual: `Shipping: 12.34 PLN` and `Handling: 12.36 PLN`.

So 12.355 is rounded up correctly, but 12.345 is rounded down. Our accountant
says the printed totals no longer match the ledger. The README says every
rounding filter rounds half up, so a final 5 should always round away from
zero.
