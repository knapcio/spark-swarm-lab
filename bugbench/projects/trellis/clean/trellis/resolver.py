"""Dependency resolution by backtracking search.

The resolver decides one package at a time.  The next package is the
required, undecided package with the fewest candidate versions left (ties:
alphabetical).  Candidates are the releases allowed by every requirement on
the package collected so far, newest first; a locked version that is still
allowed is tried first, and a yanked release is a candidate only when it is
the locked version.  Choosing a release adds its dependencies as new
requirements.  When a package has no candidates left, or a new requirement
rules out an already chosen version, the resolver abandons the most recent
choice and tries the next candidate; abandoned choices leave no trace.

``ResolutionImpossible`` describes the first dead end: the package that could
not be satisfied and each requirement on it as ``<who> requires <package>
<constraint>``, in the order the requirements were added.
"""
from dataclasses import dataclass

from .constraint import Constraint
from .errors import ResolutionImpossible, TrellisError
from .registry import check_name
from .version import Version

MAX_STEPS = 10000


@dataclass
class Resolution:
    root: str
    versions: dict          # {name: Version}
    requirements: dict      # {name: [(Constraint, required by)]}

    def __getitem__(self, name):
        return self.versions[name]

    def as_text(self):
        """``{name: "x.y.z"}`` sorted by name."""
        return {name: str(self.versions[name]) for name in sorted(self.versions)}


class _State:
    def __init__(self, chosen, requirements):
        self.chosen = chosen
        self.requirements = requirements

    def copy(self):
        return _State(dict(self.chosen), {name: list(found) for name, found in self.requirements.items()})


class Resolver:
    def __init__(self, registry, locked=None, unlock=()):
        self.registry = registry
        self.locked = {name: Version.parse(v) for name, v in (locked or {}).items()}
        self.unlock = set(unlock)
        self.steps = 0
        self.dead_end = None

    def _locked(self, name):
        return None if name in self.unlock else self.locked.get(name)

    def candidates(self, name, requirements):
        """Allowed releases of ``name``: the locked one first, then newest to oldest."""
        if name not in self.registry:
            return []
        locked = self._locked(name)
        allowed = [release for release in reversed(self.registry.releases(name))
                   if all(constraint.allows(release.version) for constraint, _ in requirements)
                   and (not release.yanked or release.version == locked)]
        return sorted(allowed, key=lambda release: release.version != locked)

    def _remember(self, name, requirements, reason=None):
        if self.dead_end is None:
            lines = [reason or f"no version of {name} satisfies all requirements:"]
            lines += [f"  {source} requires {name} {constraint}" for constraint, source in requirements]
            self.dead_end = lines

    def resolve(self, root, requirements):
        """Resolve ``{name: constraint}`` for the project ``root``; returns a :class:`Resolution`."""
        state = _State({}, {})
        for name, constraint in sorted(requirements.items()):
            check_name(name)
            self.registry.releases(name)
            state.requirements[name] = [(Constraint.parse(constraint), root)]
        found = self._search(state)
        if found is None:
            raise ResolutionImpossible(self.dead_end or ["no solution"])
        return Resolution(root, found.chosen, found.requirements)

    def _search(self, state):
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise ResolutionImpossible([f"gave up after {MAX_STEPS} steps"])
        pending = sorted(name for name in state.requirements if name not in state.chosen)
        if not pending:
            return state
        options = {name: self.candidates(name, state.requirements[name]) for name in pending}
        name = min(pending, key=lambda candidate: (len(options[candidate]), candidate))
        if not options[name]:
            reason = None if name in self.registry else f"package {name} does not exist:"
            self._remember(name, state.requirements[name], reason)
            return None
        for release in options[name]:
            attempt = state.copy()
            attempt.chosen[name] = release.version
            if self._add_dependencies(attempt, release):
                found = self._search(attempt)
                if found is not None:
                    return found
        return None

    def _add_dependencies(self, state, release):
        source = f"{release.name} {release.version}"
        for dep, constraint in sorted(release.dependencies.items()):
            state.requirements.setdefault(dep, []).append((constraint, source))
            chosen = state.chosen.get(dep)
            if chosen is not None and not constraint.allows(chosen):
                self._remember(dep, state.requirements[dep], f"{dep} {chosen} is already chosen but:")
                return False
        return True


def resolve(registry, root, requirements, locked=None, unlock=()):
    """Convenience wrapper around :class:`Resolver`."""
    if not isinstance(root, str) or not root:
        raise TrellisError("the project needs a name")
    return Resolver(registry, locked, unlock).resolve(root, requirements)
