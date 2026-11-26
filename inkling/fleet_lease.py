"""The shared fleet lease: one exclusive, non-blocking flock on ROOT/.runtime/FLEET_LEASE.lock held by every runner
that drives the Inkling fleet alone (inkling/arms.py, inkling/coding_arms.py, collab_replay.py of the live-collaboration
screens) from its admission until the fleet has drained. A second runner fails at once with the holder's description
instead of sharing the fleet. The lock dies with its process (kernel flock), so a crashed runner never leaves a stale
lease; the file only keeps the last holder's description for the error message.
"""
import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

LEASE = Path('.runtime') / 'FLEET_LEASE.lock'


class LeaseBusy(RuntimeError):
    pass


@contextmanager
def lease(root, holder):
    """Hold the fleet lease of the repository at `root` for the block; LeaseBusy if another runner holds it."""
    path = Path(root) / LEASE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.lseek(fd, 0, os.SEEK_SET)
            held_by = os.read(fd, 4096).decode(errors='replace').strip()
            raise LeaseBusy(f'fleet lease {path} is held: {held_by or "unknown holder"}') from None
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, json.dumps(dict(holder=holder, pid=os.getpid(), since=time.time())).encode())
        try:
            yield path
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
