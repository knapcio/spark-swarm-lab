# Throttled jobs start a millisecond before their token exists

Our mail key is limited to 3 jobs per second with a burst of 1. We submit
three jobs at once on an idle dispatcher with three workers:

```python
from relay import Dispatcher, Limiter

limiter = Limiter()
limiter.configure("mail", "3/s", burst=1)
dispatcher = Dispatcher(workers=3, limiter=limiter)
for n in (1, 2, 3):
    dispatcher.submit(f"welcome-{n}", key="mail")
dispatcher.run()
print([[job.id, job.started_at] for job in dispatcher.jobs()])
```

Expected: `welcome-2` starts at 334 ms and `welcome-3` at 667 ms. A token is
earned every 333.33 ms, and the README says waits are rounded up: at the
returned time the token exists, one millisecond earlier it does not.
Actual: `welcome-2` starts at 333 ms and `welcome-3` at 666 ms, before their
tokens are complete.

With `2/s` the jobs start at 0, 500 and 1000 ms as expected. We also had a
key with a maximum wait accept a job that needed 1 ms more than the limit.
