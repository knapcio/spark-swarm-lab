"""The shared fleet lease: one exclusive, non-blocking flock held by every runner that drives the Inkling fleet alone
(inkling/arms.py, inkling/coding_arms.py, collab_replay.py of the live-collaboration screens) from its admission until
the fleet has drained. The lock file lives in the repository's COMMON git directory (`git rev-parse --git-common-dir`),
which the main checkout and every worktree share, so runners started from different worktrees contend for the same
lock. A second runner fails at once with the holder's description instead of sharing the fleet. The lock dies with its
process (kernel flock), so a crashed runner never leaves a stale lease; the file only keeps the last holder's
description for the error message.
"""
import fcntl
import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

LEASE_NAME = 'swarm-lab-FLEET_LEASE.lock'


class LeaseBusy(RuntimeError):
    pass


def lease_path(root):
    """The canonical lock path of the repository holding `root` (the same for the main checkout and every worktree)."""
    try:
        common = subprocess.run(['git', '-C', str(root), 'rev-parse', '--git-common-dir'], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f'the fleet lease needs the swarm-lab git repository ({root}): {exc}') from exc
    common = Path(common)
    if not common.is_absolute():
        common = Path(root) / common
    return common.resolve() / LEASE_NAME


@contextmanager
def lease(root, holder):
    """Hold the fleet lease of the repository at `root` for the block; LeaseBusy if another runner holds it."""
    path = lease_path(root)
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
