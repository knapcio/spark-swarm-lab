# Month-end stock snapshot changes after we ship

We take a snapshot at month end and print its valuation later for the
accountant. The printed numbers do not match what the snapshot showed when we
took it.

```
product LMP-100 "Desk lamp" 89.00
product BLB-101 "LED bulb" 12.00
receive LMP-100 6 @ 41.00 on 2026-10-01
receive BLB-101 40 @ 3.20 on 2026-10-01
order S-501 on 2026-10-30 : LMP-100 x 2, BLB-101 x 10
confirm S-501
snapshot october-close
ship S-501 on 2026-11-02
```

Right after the `snapshot` line, `store.valuation("october-close")` reports 46
units worth 374.00 PLN. After the `ship` line (made in November), the same
call reports 34 units worth 260.00 PLN.

Expected: the October snapshot keeps showing 46 units / 374.00 PLN forever. A
snapshot should be a frozen copy of the stock at the time it was taken.
Receiving new stock after the snapshot does not change it, which is what makes
this confusing.
