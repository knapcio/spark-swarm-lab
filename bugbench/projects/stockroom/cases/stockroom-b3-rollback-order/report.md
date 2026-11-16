# Wrong cost of goods sold after a shipment fails

After a shipment fails because of missing stock, later shipments of an
unrelated order are costed from the wrong purchase.

```
product LMP-100 "Desk lamp" 89.00
product BLB-101 "LED bulb" 12.00
receive LMP-100 5 @ 40.00 on 2026-10-01
receive LMP-100 5 @ 46.00 on 2026-10-15
receive BLB-101 4 @ 3.20 on 2026-10-01
order S-610 on 2026-11-03 : LMP-100 x 5, BLB-101 x 4
confirm S-610
writeoff BLB-101 1 on 2026-11-03 reason broken
```

Then `store.ship("S-610", date(2026, 11, 4))` raises `InsufficientStock` for the
bulbs. That is correct: one bulb broke. We cancel S-610 and continue:

```
cancel S-610 on 2026-11-04
order S-611 on 2026-11-05 : LMP-100 x 2
confirm S-611
ship S-611 on 2026-11-06
```

Expected: the shipment of S-611 costs 80.00 PLN (2 lamps from the oldest
purchase at 40.00 PLN; we are FIFO). Actual: 92.00 PLN (2 x 46.00 PLN).

Without the failed attempt, S-611 is costed correctly at 80.00 PLN. The
failed shipment itself left the lamp count unchanged (10 on hand), so we
assumed nothing had changed.
