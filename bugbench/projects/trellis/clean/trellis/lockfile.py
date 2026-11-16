"""Lock files and lock differences.

A lock file pins one version per package, sorted by name::

    # trellis lock 1
    root shop
    fmt 2.0.1
    web 2.3.0

``diff`` compares two locks and returns one line per package that changed,
sorted by name: ``add <name> <version>``, ``remove <name> <version>``,
``upgrade <name> <old> -> <new>`` or ``downgrade <name> <old> -> <new>``.
"""
from .errors import FileFormatError, TrellisError
from .registry import NAME
from .version import Version

HEADER = "# trellis lock 1"


def dump(resolution):
    lines = [HEADER, f"root {resolution.root}"]
    lines += [f"{name} {resolution.versions[name]}" for name in sorted(resolution.versions)]
    return "\n".join(lines) + "\n"


def load(text):
    """``(root, {name: Version})`` from a lock file."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != HEADER:
        raise FileFormatError("lock", 1, f"the first line must be {HEADER!r}")
    root, pins = None, {}
    for number, raw in enumerate(lines[1:], 2):
        words = raw.split()
        if not words:
            continue
        if len(words) != 2:
            raise FileFormatError("lock", number, "expected '<name> <version>'")
        if words[0] == "root" and root is None:
            root = words[1]
            continue
        if not NAME.match(words[0]) or words[0] in pins:
            raise FileFormatError("lock", number, f"bad or repeated package {words[0]!r}")
        try:
            pins[words[0]] = Version.parse(words[1])
        except TrellisError as exc:
            raise FileFormatError("lock", number, str(exc)) from exc
    if root is None:
        raise FileFormatError("lock", len(lines), "the lock file names no root project")
    return root, pins


def verify(pins, requirements, registry, root="project"):
    """Problems of ``pins`` against the project ``requirements`` and the registry, sorted.

    Lines: ``missing <name>`` (required but not pinned), ``unknown <name>
    <version>`` (not in the registry), ``<who> requires <name> <constraint>,
    pinned <version>`` and ``unused <name>`` (pinned, but nothing needs it).
    An empty list means the lock can be installed as it is."""
    problems, needed, todo = [], set(), [(root, dict(requirements))]
    while todo:
        who, deps = todo.pop()
        for name, constraint in sorted(deps.items()):
            if name not in pins:
                problems.append(f"missing {name}")
                continue
            if not constraint.allows(pins[name]):
                problems.append(f"{who} requires {name} {constraint}, pinned {pins[name]}")
            if name in needed:
                continue
            needed.add(name)
            try:
                release = registry.release(name, pins[name])
            except TrellisError:
                problems.append(f"unknown {name} {pins[name]}")
                continue
            todo.append((f"{name} {pins[name]}", release.dependencies))
    problems += [f"unused {name}" for name in pins if name not in needed]
    return sorted(set(problems))


def diff(old, new):
    """Changes from pins ``old`` to pins ``new`` (both ``{name: Version}``)."""
    changes = []
    for name in sorted(set(old) | set(new)):
        before, after = old.get(name), new.get(name)
        if before is None:
            changes.append(f"add {name} {after}")
        elif after is None:
            changes.append(f"remove {name} {before}")
        elif after > before:
            changes.append(f"upgrade {name} {before} -> {after}")
        elif after < before:
            changes.append(f"downgrade {name} {before} -> {after}")
    return changes
