# A job that became ready later is dispatched first

One worker. The backup takes a second; while it runs, `email` becomes ready
at 100 ms and `report` at 600 ms. All three have the default priority:

```python
from relay import Dispatcher, order_of_starts

dispatcher = Dispatcher(workers=1)
dispatcher.submit("report", delay="600ms", takes="10ms")
dispatcher.submit("backup", takes="1s")
dispatcher.submit("email", delay="100ms", takes="10ms")
dispatcher.run()
print(order_of_starts(dispatcher))
```

Expected: `['backup', 'email', 'report']`. When the worker frees up at 1 s,
both are ready, and the README says that among equal priorities the job that
became ready first goes next.
Actual: `['backup', 'report', 'email']`. `report` was submitted first, but it
became ready 500 ms after `email`.

Jobs that are ready at the same moment do run in submission order, and a
higher priority still wins. We see the same wrong order after retries: a job
whose retry was due early starts after a job that became ready later.
