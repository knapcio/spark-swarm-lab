"""The project's own regression tests (visible to everyone)."""
import unittest

from trellis import (Constraint, CycleError, FileFormatError, InvalidVersion, Registry, ResolutionImpossible, Version,
                     Workspace, install_order, parse_index, parse_manifest, resolve)
from trellis.lockfile import diff, load

INDEX = """
web 2.3.0: fmt ^2.0; log >=1.0, <2
web 2.1.0: fmt ^1.5
fmt 2.0.1
fmt 1.9.0 yanked
fmt 1.6.0
log 1.4.2: fmt ^2.0
"""
MANIFEST = '[project]\nname = "shop"\n[dependencies]\nweb = "^2.1"\n'


class VersionTests(unittest.TestCase):
    def test_ordering(self):
        versions = [Version.parse(v) for v in ("1.0.0", "1.0.0-rc.10", "1.0.0-rc.2", "0.9.12", "0.10.0")]
        self.assertEqual([str(v) for v in sorted(versions)], ["0.9.12", "0.10.0", "1.0.0-rc.2", "1.0.0-rc.10", "1.0.0"])
        with self.assertRaises(InvalidVersion):
            Version.parse("1.02.0")


class ConstraintTests(unittest.TestCase):
    def test_caret_and_tilde(self):
        self.assertEqual(str(Constraint.parse("^1.2.3")), ">=1.2.3, <2.0.0")
        self.assertEqual(str(Constraint.parse("^0.2.3")), ">=0.2.3, <0.3.0")
        self.assertEqual(str(Constraint.parse("~1.2.3 || 2.*")), ">=1.2.3, <1.3.0 || >=2.0.0, <3.0.0")

    def test_allows_and_prereleases(self):
        constraint = Constraint.parse(">=1.0, <2, !=1.3.0")
        self.assertEqual([constraint.allows(v) for v in ("1.0.0", "1.3.0", "1.9.9", "2.0.0", "1.5.0-rc.1")],
                         [True, False, True, False, False])
        self.assertTrue(Constraint.parse(">=2.0.0-rc.1").allows("2.0.0-rc.3"))


class RegistryAndManifestTests(unittest.TestCase):
    def test_index(self):
        registry = parse_index(INDEX)
        self.assertEqual([str(r.version) for r in registry.releases("fmt")], ["1.6.0", "1.9.0", "2.0.1"])
        self.assertEqual(str(registry.newest("fmt", "^1").version), "1.6.0")
        with self.assertRaises(FileFormatError) as caught:
            parse_index("web 2.3.0\nweb 2.3.0\n")
        self.assertEqual(caught.exception.line, 2)

    def test_manifest(self):
        manifest = parse_manifest(MANIFEST + '[dev-dependencies]\ncheck = "~0.4"\n')
        self.assertEqual(sorted(manifest.requirements(dev=True)), ["check", "web"])
        with self.assertRaises(FileFormatError):
            parse_manifest('[project]\nname = "shop"\n[dependencies]\nweb = ^2\n')


class ResolverTests(unittest.TestCase):
    def test_newest_compatible(self):
        resolution = resolve(parse_index(INDEX), "shop", {"web": "^2.1"})
        self.assertEqual(resolution.as_text(), {"fmt": "2.0.1", "log": "1.4.2", "web": "2.3.0"})

    def test_backtracking(self):
        registry = parse_index("a 2.0.0: b ^9\na 1.0.0: b ^1\nb 1.1.0\nb 1.0.0\n")
        self.assertEqual(resolve(registry, "p", {"a": "*"}).as_text(), {"a": "1.0.0", "b": "1.1.0"})

    def test_conflict_explanation(self):
        registry = parse_index("a 1.0.0: c ^1\nb 1.0.0: c ^2\nc 1.0.0\nc 2.0.0\n")
        with self.assertRaises(ResolutionImpossible) as caught:
            resolve(registry, "p", {"a": "*", "b": "*"})
        self.assertEqual(caught.exception.lines, ["no version of c satisfies all requirements:",
                                                  "  a 1.0.0 requires c >=1.0.0, <2.0.0", "  b 1.0.0 requires c >=2.0.0, <3.0.0"])

    def test_lock_is_preferred_and_yanked_needs_lock(self):
        lock = "# trellis lock 1\nroot shop\nweb 2.1.0\nfmt 1.9.0\n"
        plan = Workspace(INDEX, MANIFEST, lock).install()
        self.assertEqual(plan.resolution.as_text(), {"fmt": "1.9.0", "web": "2.1.0"})
        self.assertEqual(plan.changes, [])


class GraphAndLockTests(unittest.TestCase):
    def test_install_order_chain(self):
        plan = Workspace(INDEX, MANIFEST).install()
        self.assertEqual(plan.order, ["fmt", "log", "web"])

    def test_cycle(self):
        registry = parse_index("a 1.0.0: b *\nb 1.0.0: a *\n")
        with self.assertRaises(CycleError):
            install_order(resolve(registry, "p", {"a": "*"}), registry)

    def test_lock_round_trip_and_diff(self):
        plan = Workspace(INDEX, MANIFEST).install()
        root, pins = load(plan.lock)
        self.assertEqual(root, "shop")
        self.assertEqual(diff(pins, {"fmt": Version.parse("1.6.0"), "web": Version.parse("2.3.0"), "x": Version(1, 0, 0)}),
                         ["downgrade fmt 2.0.1 -> 1.6.0", "remove log 1.4.2", "add x 1.0.0"])

    def test_check_and_outdated(self):
        workspace = Workspace(INDEX, MANIFEST, "# trellis lock 1\nroot shop\nweb 2.1.0\nfmt 1.6.0\nzzz 1.0.0\n")
        self.assertEqual(workspace.check(), ["unused zzz"])
        self.assertEqual(workspace.outdated(), [["fmt", "1.6.0", "-", "2.0.1"], ["web", "2.1.0", "2.3.0", "2.3.0"]])
        self.assertIsInstance(Registry(), Registry)


if __name__ == "__main__":
    unittest.main()
