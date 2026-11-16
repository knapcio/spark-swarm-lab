# A rejected batch keeps using up the rate limit

Our `api` key allows 5 jobs per second, burst 2, and at most 400 ms of
waiting. After one job, we try a batch of four that is (correctly) rejected,
then submit two single jobs:

```python
from relay import replay

_, outputs = replay("""
rate api 5/s burst 2 maxwait 400ms
submit warm key api
batch a key api ; b key api ; c key api ; d key api
tokens api
submit e key api
submit f key api
""")
print(outputs)
```

Expected: the batch fails with `error RateLimited`, then `api 1`,
`submitted e ready 0ms` and `submitted f ready 200ms`. The README says a
rejected batch submits nothing and uses no intake tokens, so the bucket
should still hold the 1 token left after `warm`.
Actual: after `error RateLimited` we get `api 0` and then
`error RateLimited` for both `e` and `f`. The rejected batch consumed the
capacity of 3 jobs that were never submitted.

A rejected batch that names each key only once (for example one `api` job
and two `sms` jobs where an `sms` job is rejected) leaves the `api` bucket as
it was, and a single rejected `submit` changes nothing either.
