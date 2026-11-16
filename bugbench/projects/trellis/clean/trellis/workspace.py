"""``Workspace``: a manifest, a registry index and an optional lock file together.

``install()`` resolves (keeping locked versions where possible) and returns
the plan: the new lock text, the changes against the old lock and the
install order.  ``update(names)`` resolves again with those packages
unlocked (all packages when ``names`` is empty) and returns the same plan.
``check()`` lists problems of the current lock without resolving, and
``outdated()`` lists locked packages that have newer releases.
The workspace keeps the new lock after a successful install or update; a
failed resolution leaves the workspace unchanged.
"""
from dataclasses import dataclass

from . import graph, lockfile
from .errors import TrellisError
from .manifest import parse_manifest
from .registry import parse_index
from .resolver import resolve


@dataclass
class Plan:
    lock: str
    changes: list
    order: list
    resolution: object


class Workspace:
    def __init__(self, index_text, manifest_text, lock_text=None, dev=False):
        self.registry = parse_index(index_text)
        self.manifest = parse_manifest(manifest_text)
        self.dev = dev
        self.pins = {}
        if lock_text:
            root, self.pins = lockfile.load(lock_text)
            if root != self.manifest.name:
                raise TrellisError(f"the lock file belongs to {root}, not {self.manifest.name}")

    def _plan(self, unlock):
        resolution = resolve(self.registry, self.manifest.name, self.manifest.requirements(self.dev), self.pins, unlock)
        plan = Plan(lockfile.dump(resolution), lockfile.diff(self.pins, resolution.versions),
                    graph.install_order(resolution, self.registry), resolution)
        self.pins = dict(resolution.versions)
        return plan

    def install(self):
        return self._plan(())

    def update(self, names=()):
        names = list(names)
        for name in names:
            if name not in self.pins:
                raise TrellisError(f"{name} is not locked")
        return self._plan(names or list(self.pins))

    def check(self):
        """Problems of the current lock (see :func:`trellis.lockfile.verify`) without resolving."""
        return lockfile.verify(self.pins, self.manifest.requirements(self.dev), self.registry, self.manifest.name)

    def outdated(self):
        """``[name, locked, newest allowed by the project, newest]`` for locked packages with a newer release.

        "Allowed" only checks the project's own requirement on the package
        (``-`` when the package is not a direct requirement); yanked
        releases and pre-releases are ignored."""
        rows, requirements = [], self.manifest.requirements(self.dev)
        for name in sorted(self.pins):
            if name not in self.registry:
                continue
            releases = [r.version for r in self.registry.releases(name) if not r.yanked and not r.version.is_prerelease]
            if not releases or releases[-1] <= self.pins[name]:
                continue
            allowed = requirements[name].filter(releases) if name in requirements else []
            rows.append([name, str(self.pins[name]), str(allowed[-1]) if allowed else "-", str(releases[-1])])
        return rows

    def tree(self):
        resolution = self._plan(()).resolution
        return graph.tree(resolution, self.registry)

    def why(self, name):
        resolution = self._plan(()).resolution
        return graph.why(resolution, self.registry, name)
