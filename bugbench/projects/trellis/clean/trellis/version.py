"""Semantic versions: ``MAJOR.MINOR.PATCH`` with an optional pre-release tag.

``1.4.0-rc.2`` has the pre-release identifiers ``rc`` and ``2``.  Ordering:

* versions compare by major, then minor, then patch;
* a pre-release is lower than the release with the same numbers
  (``1.4.0-rc.2 < 1.4.0``);
* pre-release identifiers compare left to right: numeric identifiers
  numerically (``rc.2 < rc.10``), alphanumeric ones as text, and a numeric
  identifier is lower than an alphanumeric one; when all shared identifiers
  are equal, the shorter tag is lower (``rc < rc.1``).

Numeric parts and numeric identifiers have no leading zeros.
"""
from dataclasses import dataclass
import functools
import re

from .errors import InvalidVersion

_NUMBER = r"(0|[1-9]\d*)"
_IDENT = r"[0-9A-Za-z-]+"
_VERSION = re.compile(rf"^{_NUMBER}\.{_NUMBER}\.{_NUMBER}(?:-({_IDENT}(?:\.{_IDENT})*))?$")
_PARTIAL = re.compile(rf"^{_NUMBER}(?:\.{_NUMBER}(?:\.{_NUMBER}(?:-({_IDENT}(?:\.{_IDENT})*))?)?)?$")


def _identifiers(tag):
    if not tag:
        return ()
    parts = []
    for part in tag.split("."):
        if part.isdigit():
            if len(part) > 1 and part[0] == "0":
                raise InvalidVersion(f"numeric identifier with a leading zero: {part!r}")
            parts.append(int(part))
        else:
            parts.append(part)
    return tuple(parts)


@functools.total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    pre: tuple = ()

    @classmethod
    def parse(cls, text):
        if isinstance(text, Version):
            return text
        match = _VERSION.match(text.strip()) if isinstance(text, str) else None
        if not match:
            raise InvalidVersion(f"not a version: {text!r}")
        major, minor, patch, tag = match.groups()
        return cls(int(major), int(minor), int(patch), _identifiers(tag))

    @property
    def release(self):
        """The numbers without the pre-release tag, as a tuple."""
        return (self.major, self.minor, self.patch)

    @property
    def is_prerelease(self):
        return bool(self.pre)

    def _key(self):
        tag = tuple((0, part, "") if isinstance(part, int) else (1, 0, part) for part in self.pre)
        return (self.release, 0 if self.pre else 1, tag)

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __str__(self):
        text = f"{self.major}.{self.minor}.{self.patch}"
        return text + "-" + ".".join(str(part) for part in self.pre) if self.pre else text

    def next_major(self):
        return Version(self.major + 1, 0, 0)

    def next_minor(self):
        return Version(self.major, self.minor + 1, 0)

    def next_patch(self):
        return Version(self.major, self.minor, self.patch + 1)


def parse_partial(text):
    """``"1"``, ``"1.2"`` or a full version: ``(numbers, pre-release identifiers)``."""
    match = _PARTIAL.match(text) if isinstance(text, str) else None
    if not match:
        raise InvalidVersion(f"not a version: {text!r}")
    numbers = [int(group) for group in match.groups()[:3] if group is not None]
    return numbers, _identifiers(match.group(4))


def sort_versions(versions, newest_first=False):
    return sorted((Version.parse(v) for v in versions), reverse=newest_first)
