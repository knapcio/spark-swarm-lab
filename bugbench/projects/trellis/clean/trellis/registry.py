"""The package registry and its text index format.

Index format, one release per line; ``#`` starts a comment line::

    web 2.3.0: fmt ^2.0; log >=1.0, <2
    fmt 2.0.1
    fmt 1.9.0 yanked

A line is ``<name> <version> [yanked]``, optionally followed by ``:`` and
dependencies separated by ``;``, each ``<name> <constraint>``.  Package names
are lower case letters, digits and ``-``, starting with a letter.  A yanked
release is only used when a lock file already pins it.
"""
from dataclasses import dataclass, field
import re

from .constraint import Constraint
from .errors import DuplicateRelease, FileFormatError, TrellisError, UnknownPackage
from .version import Version

NAME = re.compile(r"^[a-z][a-z0-9-]{0,39}$")


def check_name(name):
    if not isinstance(name, str) or not NAME.match(name):
        raise TrellisError(f"bad package name {name!r}")
    return name


@dataclass(frozen=True)
class Release:
    name: str
    version: Version
    dependencies: dict = field(default_factory=dict, hash=False, compare=False)
    yanked: bool = False


class Registry:
    def __init__(self):
        self._packages = {}

    def add(self, name, version, dependencies=None, yanked=False):
        """Register a release; ``dependencies`` maps names to constraints (text or Constraint)."""
        check_name(name)
        version = Version.parse(version)
        releases = self._packages.setdefault(name, {})
        if version in releases:
            raise DuplicateRelease(f"{name} {version} is already registered")
        deps = {}
        for dep, constraint in (dependencies or {}).items():
            if check_name(dep) == name:
                raise TrellisError(f"{name} cannot depend on itself")
            deps[dep] = Constraint.parse(constraint)
        release = Release(name, version, deps, bool(yanked))
        releases[version] = release
        return release

    def names(self):
        return sorted(self._packages)

    def yank(self, name, version):
        """Mark a release as yanked (it stays usable for locks that pin it)."""
        release = self.release(name, version)
        if release.yanked:
            raise TrellisError(f"{name} {release.version} is already yanked")
        self._packages[name][release.version] = Release(name, release.version, release.dependencies, True)

    def releases(self, name):
        """All releases of ``name``, oldest first."""
        try:
            return [release for _, release in sorted(self._packages[name].items())]
        except KeyError:
            raise UnknownPackage(name) from None

    def release(self, name, version):
        version = Version.parse(version)
        for release in self.releases(name):
            if release.version == version:
                return release
        raise UnknownPackage(f"{name} {version}")

    def __contains__(self, name):
        return name in self._packages

    def newest(self, name, constraint="*"):
        """The newest non-yanked release allowed by ``constraint``, or None."""
        allowed = Constraint.parse(constraint)
        found = [r for r in self.releases(name) if not r.yanked and allowed.allows(r.version)]
        return found[-1] if found else None


def parse_index(text, registry=None):
    """Add every release of an index text to ``registry`` (a new one by default) and return it."""
    registry = registry if registry is not None else Registry()
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, _, tail = line.partition(":")
        words = head.split()
        if len(words) not in (2, 3) or (len(words) == 3 and words[2] != "yanked"):
            raise FileFormatError("index", number, "expected '<name> <version> [yanked]'")
        dependencies = {}
        for item in tail.split(";") if tail.strip() else []:
            name, _, constraint = item.strip().partition(" ")
            if not name or not constraint.strip() or name in dependencies:
                raise FileFormatError("index", number, f"bad dependency {item.strip()!r}")
            dependencies[name] = constraint.strip()
        try:
            registry.add(words[0], words[1], dependencies, yanked=len(words) == 3)
        except TrellisError as exc:
            raise FileFormatError("index", number, str(exc)) from exc
    return registry
