# stockroom

A small warehouse ledger: a product catalogue with quantity price tiers, FIFO
cost lots, order reservations, promotions, per-line VAT, reports and a
line-oriented journal language for replaying activity. Standard library only,
Python 3.10+.

```python
import datetime
from stockroom import Store

store = Store("PLN")
store.add_product("WID-001", "Widget", "2.50", tiers=[(10, "2.30"), (50, "2.10")])
store.receive("WID-001", 100, "1.20", datetime.date(2026, 3, 1))
quote = store.place("O-1", [("WID-001", 12)], datetime.date(2026, 3, 2))
shipment = store.ship("O-1", datetime.date(2026, 3, 3))
print(quote.total, shipment.cogs)
```

## Modules

| Module | Responsibility |
|---|---|
| `money.py` | Exact `Money` values, half-up rounding, allocation |
| `catalog.py` | Products, SKUs, tiers, VAT classes |
| `pricing.py` | Tier prices, promotions, coupons, VAT quotes |
| `inventory.py` | FIFO lots, issues, write-offs, restores, reservations, snapshots |
| `orders.py` | Order lifecycle: confirm, ship (atomic), cancel |
| `reports.py` | Valuation, shipments per SKU, top SKUs, stock status |
| `store.py` | Facade wiring everything together |
| `journal.py` | Text command language and replay |
| `errors.py` | Exception hierarchy |

## Business rules

- All rounding is half-up to the currency's minor unit.
- A price tier applies to order lines whose quantity is at least the tier's
  minimum quantity.
- One promotion per line: the largest discount wins; on a tie, the promotion
  registered first wins.
- VAT is computed and rounded per line.
- Stock is issued first-in-first-out by receipt date, then receipt order.
- Shipments are atomic. A failed shipment leaves stock, reservations and the
  order exactly as they were.
- A snapshot is a frozen copy of the stock at the time it was taken.

Run the tests with `python -m unittest discover -s tests`.
