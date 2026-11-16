"""Project manifests.

::

    # shop manifest
    [project]
    name = "shop"

    [dependencies]
    web = "^2.1"
    log = ">=1.0, <1.5 || 2.*"

    [dev-dependencies]
    check = "~0.4"

Values are double-quoted.  A package may appear in only one of the two
dependency sections.  Development dependencies are resolved only when asked
for (``dev=True``).
"""
from dataclasses import dataclass, field
import re

from .constraint import Constraint
from .errors import FileFormatError, TrellisError
from .registry import NAME

_SECTION = re.compile(r"^\[([a-z-]+)\]$")
_PAIR = re.compile(r'^([A-Za-z0-9_-]+)\s*=\s*"([^"]*)"$')
SECTIONS = ("project", "dependencies", "dev-dependencies")


@dataclass
class Manifest:
    name: str
    dependencies: dict = field(default_factory=dict)
    dev_dependencies: dict = field(default_factory=dict)

    def requirements(self, dev=False):
        """{package: Constraint} to resolve, including development dependencies when ``dev``."""
        found = dict(self.dependencies)
        if dev:
            found.update(self.dev_dependencies)
        return found


def parse_manifest(text):
    section, name, deps, dev = None, None, {}, {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _SECTION.match(line)
        if match:
            if match.group(1) not in SECTIONS:
                raise FileFormatError("manifest", number, f"unknown section [{match.group(1)}]")
            section = match.group(1)
            continue
        pair = _PAIR.match(line)
        if not pair or section is None:
            raise FileFormatError("manifest", number, 'expected key = "value" inside a section')
        key, value = pair.groups()
        if section == "project":
            if key != "name" or not NAME.match(value):
                raise FileFormatError("manifest", number, "the project section only takes a valid name")
            name = value
            continue
        if not NAME.match(key):
            raise FileFormatError("manifest", number, f"bad package name {key!r}")
        if key in deps or key in dev:
            raise FileFormatError("manifest", number, f"{key} is listed twice")
        try:
            (deps if section == "dependencies" else dev)[key] = Constraint.parse(value)
        except TrellisError as exc:
            raise FileFormatError("manifest", number, str(exc)) from exc
    if name is None:
        raise FileFormatError("manifest", 0, "the manifest has no project name")
    if name in deps or name in dev:
        raise FileFormatError("manifest", 0, "a project cannot depend on itself")
    return Manifest(name, deps, dev)
