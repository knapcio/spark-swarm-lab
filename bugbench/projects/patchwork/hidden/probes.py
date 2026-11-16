"""Hidden behavioural probes for the patchwork project. NEVER shown to agents.

BUGBENCH-HIDDEN-CANARY 4aa5da40-bugbench-patchwork-probes

Each ``probe_*`` function builds fresh state, exercises public behaviour and
returns a JSON-compatible observation.  This file contains no expected values:
the trusted parent compares observations with ``expected.json``, which was
frozen from the clean reference project.  Probes only use behaviour documented
in ``README.md`` and docstrings.
"""


def _error(callable_, *args, **kwargs):
    try:
        callable_(*args, **kwargs)
    except Exception as exc:  # observation only; the parent decides
        return type(exc).__name__
    return None


def _lines(*items):
    return "".join(item + "\n" for item in items)


def _numbers(count, start=1):
    return "".join(f"{n}\n" for n in range(start, start + count))


def _swap(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def _hunk(h):
    return [h.old_start, h.new_start, [tag + text for tag, text in h.lines], h.old_newline, h.new_newline]


def _shape(hunks):
    return [[h.old_start, h.old_len, h.new_start, h.new_len] for h in hunks]


def _results(result):
    return [r.describe() for r in result.hunks]


# --- text and lcs -------------------------------------------------------------------------
def probe_text_parse_and_equality():
    from patchwork import Text
    values = ["", "a", "a\n", "a\nb", "a\nb\n", "\n", "\n\n", "a\r\nb", " x \n\ty"]
    out = [[list(Text.parse(v).lines), Text.parse(v).newline, str(Text.parse(v)) == v, len(Text.parse(v))] for v in values]
    t = Text.parse("a\nb")
    out += [Text.parse(t) is t, t == Text(["a", "b"], False), t == Text(["a", "b"]), Text([], False).newline,
            hash(t) == hash(Text(("a", "b"), False)), repr(Text.parse("q\n")), t[1], list(t), t.__eq__("a\nb") is NotImplemented,
            str(t.replace(newline=True)), str(t.replace(lines=["z"])), str(Text.parse("").replace(lines=["k"], newline=False))]
    out.append([_error(Text, ["a\nb"]), _error(Text, [1]), _error(Text, ["a"], 1), _error(Text.parse, 5),
                _error(setattr, t, "newline", True), _error(Text.parse, None)])
    return out


def probe_text_keys_and_loose():
    from patchwork import Text, loose
    from patchwork.text import same_line, same_lines
    t = Text.parse("a  b\n\tc\t d \nend")
    return [t.keys(), t.keys(True), Text.parse("x\n").keys(), Text.parse("").keys(),
            [loose(s) for s in ("  a \t b  ", "", "\t", "a\tb", "x y")],
            [same_line("a b", "a  b"), same_line("a b", "a  b", True), same_line("ab", "a b", True)],
            [same_lines(["a"], ["a", "b"]), same_lines([" a"], ["a "], True), same_lines([], []), same_lines(["a"], ["b"])]]


def probe_opcodes_tie_break():
    from patchwork import opcodes
    pairs = [("xy", "yx"), ("abcabba", "cbabac"), ("", "ab"), ("ab", ""), ("abc", "abc"), ("abc", "xyz"),
             ("aab", "ab"), ("ab", "aab"), ("abcd", "acbd"), ("abab", "baba"), ("aXbXc", "abc"), ("abc", "aXbYc"),
             ("abcde", "aXcYe"), ("a", "b"), ("aa", "a")]
    return [[list(op) for op in opcodes(a, b)] for a, b in pairs]


def probe_matches_similarity_distance():
    from patchwork import edit_distance, matches, similarity
    from patchwork.lcs import lcs_lengths
    pairs = [("", ""), ("abc", "abc"), ("abc", ""), ("kitten", "sitting"), ("abcbdab", "bdcaba"), ("aaa", "aa"),
             ("xaby", "xbay"), ("ab", "abab")]
    out = [[[list(p) for p in matches(a, b)], similarity(a, b), edit_distance(a, b)] for a, b in pairs]
    out.append(lcs_lengths("abc", "bac"))
    out.append(lcs_lengths("", "ab"))
    return out


# --- hunks ----------------------------------------------------------------------------------
def probe_make_hunks_basic():
    from patchwork import make_hunks
    base = _numbers(12)
    out = []
    for new, context in [(_swap(base, "\n6\n", "\nsix\n"), 3), (_swap(base, "\n6\n", "\nsix\n"), 1),
                         (_swap(base, "\n6\n", "\nsix\n"), 0), ("0\n" + base, 3), (base + "13\n", 2),
                         ("", 3), (_swap(base, "1\n2\n", ""), 3), (_swap(base, "\n4\n5\n", "\nfour\n"), 2),
                         (_swap(base, "\n11\n", "\n11\nx\ny\n"), 3)]:
        out.append([_hunk(h) for h in make_hunks(base, new, context)])
    out.append([_hunk(h) for h in make_hunks("", "a\nb", 3)])
    out.append([_hunk(h) for h in make_hunks("a\nb\nc\nd", "a\nb\nc\nd\n", 1)])
    out.append([_hunk(h) for h in make_hunks("a\nb\n", "a\nb\n")])
    out.append([_error(make_hunks, "a", "b", -1), _error(make_hunks, "a", "b", True), _error(make_hunks, "a", "b", 1.0),
                _error(make_hunks, 3, "b")])
    return out


def probe_make_hunks_ignore_space():
    from patchwork import make_hunks
    old = "def f():\n    return  1\nx = 2\ny = 3\n"
    new = "def f():\n    return 1\nx = 2\ny = 4\n"
    return [[_hunk(h) for h in make_hunks(old, new, 1)], [_hunk(h) for h in make_hunks(old, new, 1, True)],
            make_hunks("a  b\n", "a b\n", 3, True), [_hunk(h) for h in make_hunks("a\n", " a \nb\n", 3, True)]]


def probe_hunk_properties_and_reverse():
    from patchwork import Hunk
    h = Hunk(4, 6, [(" ", "a"), (" ", "b"), ("-", "c"), ("-", "d"), ("+", "C"), (" ", "e"), ("+", "F"), (" ", "g")], True, False)
    r = h.reversed()
    out = [h.old_len, h.new_len, h.additions, h.deletions, h.old_lines(), h.new_lines(), h.leading_context(),
           h.trailing_context(), _hunk(r), _hunk(r.reversed()) == _hunk(h), r.leading_context(), r.trailing_context()]
    plain = Hunk(0, 0, [("+", "x")])
    out += [plain.leading_context(), plain.trailing_context(), Hunk(0, 0, [(" ", "a"), (" ", "b")]).trailing_context(),
            Hunk(0, 0, [(" ", "a"), (" ", "b")]).leading_context(), h.validate() is h]
    out.append([_error(Hunk(-1, 0, [("+", "x")]).validate), _error(Hunk(0, True, [("+", "x")]).validate),
                _error(Hunk(0, 0, [("*", "x")]).validate), _error(Hunk(0, 0, [("+", "x\ny")]).validate),
                _error(Hunk(0, 0, [(" ", "x")]).validate), _error(Hunk(0, 0, [("+",)]).validate),
                _error(Hunk(0, 0, [("+", 5)]).validate), _error(Hunk(0, 0, []).validate)])
    mixed = Hunk(0, 0, [("-", "a"), ("+", "b"), ("-", "c"), (" ", "d"), ("+", "e"), ("-", "f")])
    out.append(_hunk(mixed.reversed()))
    return out


def probe_hunk_gap_boundary():
    from patchwork import make_hunks
    base = _numbers(30)
    out = []
    for first, second, context in [(5, 12, 3), (5, 13, 3), (5, 11, 3), (4, 9, 2), (4, 10, 2), (10, 13, 1),
                                   (10, 14, 1), (3, 5, 0), (6, 16, 4), (6, 17, 4)]:
        new = _swap(_swap(base, f"\n{first}\n", f"\nX{first}\n"), f"\n{second}\n", f"\nX{second}\n")
        out.append(_shape(make_hunks(base, new, context)))
    return out


def probe_diff_texts_gap_boundary():
    from patchwork import diff_texts
    old = _lines("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo")
    new = _swap(_swap(old, "bravo\n", "BRAVO\n"), "golf\n", "GOLF\n")
    insert = _swap(old, "charlie\n", "charlie\nnew\n")
    insert = _swap(insert, "india\n", "india\nmore\n")
    return [diff_texts(old, new, "words.txt", context=2), diff_texts(old, new, "words.txt", context=1),
            diff_texts(old, insert, "g", context=3), diff_texts(old, insert, "g", context=2)]


def probe_diffstat_gap_boundary():
    from patchwork import PatchSet, diffstat, summary
    from patchwork.stats import file_counts
    old = {"a.txt": _numbers(40), "b.txt": _numbers(40)}
    new = {"a.txt": _swap(_swap(old["a.txt"], "\n10\n", "\nten\n"), "\n17\n", "\nseventeen\n"),
           "b.txt": _swap(_swap(old["b.txt"], "\n10\n", "\nten\n"), "\n18\n", "\neighteen\n")}
    patch = PatchSet.diff(old, new)
    narrow = PatchSet.diff(old, new, context=1)
    return [summary(patch), [file_counts(f) for f in patch.files], summary(narrow), diffstat(patch),
            str(patch).count("@@ -")]


def probe_trimmed_leaves_hunk():
    from patchwork import Hunk, make_hunks
    hunk = make_hunks(_numbers(15), _swap(_numbers(15), "\n8\n", "\neight\n"))[0]
    before = _hunk(hunk)
    one = hunk.trimmed(1)
    two = hunk.trimmed(2)
    three = hunk.trimmed(3)
    out = [_hunk(one), _hunk(two), _hunk(three), _hunk(hunk) == before, _hunk(hunk.trimmed(0)) == before]
    edge = Hunk(0, 0, [(" ", "a"), ("-", "b"), ("+", "B"), (" ", "c"), (" ", "d"), (" ", "e")])
    out += [_hunk(edge.trimmed(2)), _hunk(edge.trimmed(2)), _hunk(edge)]
    return out


# --- unified format ---------------------------------------------------------------------------
def probe_format_headers():
    from patchwork import Hunk, format_hunk
    from patchwork.unified import format_header
    hunks = [Hunk(0, 0, [("+", "a")]), Hunk(0, 0, [("-", "a")]), Hunk(4, 4, [("-", "x"), ("+", "y")]),
             Hunk(9, 10, [(" ", "c"), ("+", "n")]), Hunk(3, 2, [("-", "a"), ("-", "b")]), Hunk(7, 7, [("+", "a"), ("+", "b")]),
             Hunk(0, 0, [(" ", "a"), ("-", "b"), (" ", "c")], False, False),
             Hunk(1, 1, [("-", "b"), ("+", "c")], False, True), Hunk(1, 1, [("-", "b"), ("+", "c")], True, False),
             Hunk(1, 1, [("-", "b"), ("+", "c")], False, False), Hunk(0, 0, [(" ", "a"), ("+", "b")], True, False)]
    return [[format_header(h), format_hunk(h)] for h in hunks]


def probe_parse_paths_and_commentary():
    from patchwork import parse_patch
    text = ("From: someone\nSubject: fix\n\ndiff --git a/src/x.py b/src/x.py\nindex 1..2 100644\n"
            "--- a/src/x.py\t2026-01-01 10:00\n+++ b/src/x.py\t2026-01-02 10:00\n@@ -2,2 +2,2 @@ def f():\n a\n-b\n+c\n"
            "@@ -10 +10,2 @@\n x\n+y\n"
            "--- a/old/name.txt\n+++ b/new/name.txt\n@@ -1 +1 @@\n-q\n+r\n"
            "--- /dev/null\n+++ b/made.txt\n@@ -0,0 +1,2 @@\n+1\n+2\n"
            "--- a/dead.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-1\n-2\n-- \n2.40\n")
    patches = parse_patch(text)
    out = [[p.old_path, p.new_path, p.path, p.is_new, p.is_deleted, p.is_rename, [_hunk(h) for h in p.hunks]] for p in patches]
    out.append([[p.old_path, p.new_path] for p in parse_patch("--- x/y/z.c\n+++ x/y/z.c\n@@ -1 +1 @@\n-a\n+b\n", strip=2)])
    out.append([[p.old_path, p.new_path] for p in parse_patch("--- z.c\n+++ z.c\n@@ -1 +1 @@\n-a\n+b\n", strip=0)])
    blank = parse_patch("--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n a\n\n-b\n+c\n")[0]
    out.append(_hunk(blank.hunks[0]))
    out.append(_hunk(parse_patch("--- a/f\n+++ b/f\n@@ -3,0 +4,2 @@\n+x\n+y\n")[0].hunks[0]))
    return out


def probe_parse_errors():
    from patchwork import PatchParseError, parse_patch
    bad = ["", "nothing here\n", "@@ -1 +1 @@\n-a\n+b\n", "--- a/f\n+++ b/f\n", "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n-b\n",
           "--- a/f\n+++ b/f\n@@ -1 +1 @@\n a\n", "--- a/f\n+++ b/f\n@@ -0 +1 @@\n-a\n+b\n",
           "--- a/f\n+++ b/f\n@@ -1 +1 @@\n*a\n+b\n", "--- a/f\n+++ b/f\n@@ -1 +1 @@\n\\ No newline at end of file\n-a\n+b\n",
           "--- /dev/null\n+++ /dev/null\n@@ -0,0 +1 @@\n+a\n", "--- f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b\n",
           "--- a/f\n+++ b/f\n@@ -5 +5 @@\n-a\n+b\n@@ -3 +3 @@\n-c\n+d\n",
           "--- a/f\n+++ b/f\n@@ -5 +5 @@\n-a\n+b\n@@ -5 +5 @@\n-c\n+d\n",
           "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n\\ No newline at end of file\n",
           "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n", None, "--- a/f\n+++ b/f\n@@ -1 +1 @@ \n-a\n+b\n"]
    out = []
    for text in bad:
        try:
            parse_patch(text)
            out.append(None)
        except PatchParseError as exc:
            out.append(["PatchParseError", exc.line])
        except Exception as exc:  # observation only
            out.append(type(exc).__name__)
    ok = parse_patch("--- a/f\n+++ b/f\n@@ -5 +5 @@\n-a\n+b\n@@ -6 +6 @@\n-c\n+d\n")[0]
    out.append([_hunk(h) for h in ok.hunks])
    return out


def probe_parse_marker_after_changed_lines():
    from patchwork import parse_patch
    texts = ["--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n",
             "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+b\n",
             "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n-b\n+b\n\\ No newline at end of file\n",
             "--- a/f\n+++ b/f\n@@ -1 +1,2 @@\n x\n+y\n\\ No newline at end of file\n"]
    return [[_hunk(h) for h in parse_patch(text)[0].hunks] for text in texts]


def probe_marker_after_context_flags():
    from patchwork import parse_patch
    texts = ["--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n\\ No newline at end of file\n",
             "--- a/env\n+++ b/env\n@@ -2,2 +2,3 @@\n-K=1\n+K=2\n+L=3\n M=9\n\\ No newline at end of file\n",
             "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n-x\n+y\n z\n\\ No newline at end of file\n--- a/g\n+++ b/g\n@@ -1 +1 @@\n-p\n+q\n"]
    return [[[_hunk(h) for h in p.hunks] for p in parse_patch(text)] for text in texts]


def probe_marker_context_patchset_apply():
    from patchwork import PatchSet
    old = {"motd": "Welcome\nto the\nserver", "notes.txt": "one\ntwo\nthree\nfour\nfive"}
    new = {"motd": "Welcome\nto this\nserver", "notes.txt": "one\n2\nthree\nfour\nfive"}
    text = str(PatchSet.diff(old, new, context=3))
    patch = PatchSet.parse(text)
    result = patch.apply(old)
    return [result.tree, result.tree == new, patch.apply(new, reverse=True).tree == old]


def probe_marker_context_apply_hunks():
    from patchwork import apply_hunks, parse_patch
    patch = parse_patch("--- a/cfg\n+++ b/cfg\n@@ -2,3 +2,3 @@\n b\n-c\n+C\n d\n\\ No newline at end of file\n")[0]
    shifted = apply_hunks("0\na\nb\nc\nd", patch.hunks)
    exact = apply_hunks("a\nb\nc\nd", patch.hunks)
    inserted = parse_patch("--- a/l\n+++ b/l\n@@ -1,2 +1,3 @@\n x\n+y\n z\n\\ No newline at end of file\n")[0]
    return [str(shifted.text), _results(shifted), str(exact.text), str(apply_hunks("x\nz", inserted.hunks).text)]


def probe_format_round_trip():
    from patchwork import PatchSet
    cases = [({"f": "a\nb\nc\n"}, {"f": "a\nc\n"}), ({"f": "a\nb"}, {"f": "a\nb\n"}), ({"f": "a\nb\n"}, {"f": "a\nb"}),
             ({"f": ""}, {"f": "x"}), ({"f": "x"}, {}), ({}, {"g": "1\n2\n"}), ({"f": _numbers(30)}, {"f": _numbers(29, 2)})]
    out = []
    for old, new in cases:
        text = str(PatchSet.diff(old, new))
        again = str(PatchSet.parse(text))
        out.append([text, again == text, PatchSet.parse(text).apply(old).tree == new])
    return out


# --- applying ---------------------------------------------------------------------------------
def probe_find_search_order():
    from patchwork import find
    lines = ["a", "b", "a", "b", "a", "c", "a"]
    return [find(lines, ["a"], 3), find(lines, ["a"], 3, floor=4), find(lines, ["a", "b"], 3), find(lines, ["a", "c"], 0),
            find(lines, ["c", "a"], 6), find(lines, ["z"], 2), find(lines, [], 9), find(lines, [], 2, floor=5),
            find(lines, ["a"] * 8, 0), find(lines, ["A "], 0, ignore_space=True), find(lines, ["a"], -4),
            find(lines, ["a", "b"], 2, floor=3), find(lines, ["b"], 0, floor=2), find(lines, ["a"], 100)]


def probe_apply_offsets_multi_hunk():
    from patchwork import apply_hunks, make_hunks
    base = _numbers(40)
    new = _swap(_swap(_swap(base, "\n5\n", "\nfive\n"), "\n20\n", "\n20\n20b\n"), "\n35\n", "\n")
    hunks = make_hunks(base, new)
    target = "x\ny\n" + _swap(base, "\n27\n", "\n")
    shifted = apply_hunks(target, hunks)
    exact = apply_hunks(base, hunks)
    return [_shape(hunks), _results(shifted), str(shifted.text) == "x\ny\n" + _swap(new, "\n27\n", "\n"),
            _results(exact), str(exact.text) == new, exact.clean, shifted.clean, exact.rejected]


def probe_apply_fuzz_one():
    from patchwork import apply_hunks, make_hunks
    base = _numbers(20)
    new = _swap(base, "\n12\n", "\ntwelve\n")
    drifted = _swap(base, "\n15\n", "\nfifteen\n")
    result = apply_hunks("pre\n" + drifted, make_hunks(base, new))
    other = apply_hunks(_swap(base, "\n9\n", "\nnine\n"), make_hunks(base, new), fuzz=1)
    return [_results(result), str(result.text).count("twelve"), _results(other), str(other.text).split("\n")[8:13]]


def probe_fuzz_two_offsets():
    from patchwork import apply_hunks, make_hunks
    base = _numbers(24)
    new = _swap(base, "\n12\n", "\ntwelve\n")
    out = []
    for drift in [("\n10\n", "\nten\n"), ("\n14\n", "\nfourteen\n"), ("\n10\n", "\nten\n10.5\n")]:
        target = _swap(base, *drift)
        result = apply_hunks(target, make_hunks(base, new))
        out.append([_results(result), str(result.text) == _swap(target, "\n12\n", "\ntwelve\n")])
    two = make_hunks(base, _swap(_swap(base, "\n4\n", "\nfour\n"), "\n18\n", "\neighteen\n"))
    target = _swap(_swap(base, "\n2\n", "\ntwo\n"), "\n16\n", "\nsixteen\n")
    result = apply_hunks(target, two)
    out.append([_results(result), str(result.text).split("\n")[:20]])
    return out


def probe_apply_reverse_partial_errors():
    from patchwork import Hunk, HunkFailed, PatchworkError, apply_hunks, apply_text, make_hunks
    base = _numbers(10)
    new = _swap(_swap(base, "\n2\n", "\ntwo\n"), "\n9\n", "\nnine\n")
    hunks = make_hunks(base, new, 1)
    out = [apply_text(new, hunks, reverse=True) == base, _results(apply_hunks(new, hunks, reverse=True))]
    broken = _swap(base, "\n9\n", "\nNINE\n")
    partial = apply_hunks(broken, hunks, fuzz=0, partial=True)
    out += [_results(partial), partial.rejected, str(partial.text).split("\n")[:3], partial.clean]
    try:
        apply_hunks(broken, hunks, fuzz=0, path="n.txt")
        out.append(None)
    except HunkFailed as exc:
        out.append([exc.path, exc.index])
    out.append([_error(apply_hunks, base, hunks, fuzz=-1), _error(apply_hunks, base, hunks, fuzz=4),
                _error(apply_hunks, base, hunks, fuzz=True), _error(apply_hunks, 7, hunks), apply_text(base, [], fuzz=3) == base])
    out.append(apply_text("a\nb\n", [Hunk(5, 5, [("+", "z")])]))
    out.append(apply_text("a\nb\n", [Hunk(0, 0, [("+", "z")]), Hunk(0, 1, [("+", "y")])]))
    out.append(issubclass(HunkFailed, PatchworkError))
    return out


def probe_apply_newline_end():
    from patchwork import apply_hunks, make_hunks
    out = []
    for old, new, target in [("a\nb\n", "a\nb", "a\nb\n"), ("a\nb", "a\nb\n", "a\nb"), ("a\nb", "a\nc", "x\na\nb"),
                             ("a\nb\nc\nd\ne\nf\n", "a\nB\nc\nd\ne\nf\n", "a\nb\nc\nd\ne\nf"),
                             ("1\n2\n3\n4\n5\n6\n7\n8\n", "1\n2\n3\n4\n5\n6\n7\nx", "1\n2\n3\n4\n5\n6\n7\n8\n"),
                             ("k\n", "", "k\n"), ("", "z", "")]:
        result = apply_hunks(target, make_hunks(old, new))
        out.append([str(result.text), _results(result)])
    return out


def probe_is_applied():
    from patchwork import is_applied, make_hunks
    base = _numbers(12)
    new = _swap(base, "\n6\n", "\nsix\n")
    hunks = make_hunks(base, new)
    return [is_applied(new, hunks), is_applied(base, hunks), is_applied("0\n" + new, hunks),
            is_applied(new.replace("six", "six  "), hunks), is_applied(new.replace("six", "six  "), hunks, ignore_space=True)]


# --- patch sets ---------------------------------------------------------------------------------
def probe_patchset_diff_and_format():
    from patchwork import PatchSet, diff_texts
    old = {"b.txt": "1\n2\n3\n", "a.txt": "x\n", "same": "s\n", "gone": "g\n"}
    new = {"b.txt": "1\n3\n", "a.txt": "y\n", "same": "s\n", "c/new.txt": "n\n"}
    patch = PatchSet.diff(old, new, context=1)
    out = [str(patch), patch.paths(), len(patch), [[f.old_path, f.new_path] for f in patch.files],
           str(PatchSet.diff({"w": "a b\n"}, {"w": "a  b\n"}, ignore_space=True)), len(PatchSet.diff(old, old)),
           diff_texts("a\n", "b\n", "o.txt", "n.txt", context=0)]
    out.append([_error(PatchSet.diff, [], {}), _error(PatchSet.diff, {"x": 1}, {}), _error(PatchSet.diff, {"": "a"}, {}),
                _error(PatchSet, ["x"]), _error(PatchSet.parse, "nothing")])
    return out


def probe_patchset_apply_actions():
    from patchwork import FilePatch, Hunk, PatchSet, TreeError
    tree = {"keep.txt": "k\n", "old.txt": "1\n2\n3\n", "del.txt": "d1\nd2\n"}
    patch = PatchSet([FilePatch("old.txt", "new.txt", [Hunk(1, 1, [("-", "2"), ("+", "two")])]),
                      FilePatch("del.txt", None, [Hunk(0, 0, [("-", "d1"), ("-", "d2")])]),
                      FilePatch(None, "made/n.txt", [Hunk(0, 0, [("+", "hello")])])])
    result = patch.apply(tree)
    out = [result.tree, result.log, result.offsets, result.fuzzy, sorted(result.results), patch.paths(), tree["old.txt"]]
    errors = []
    for files, target in [([FilePatch(None, "keep.txt", [Hunk(0, 0, [("+", "x")])])], tree),
                          ([FilePatch("nope", "nope", [Hunk(0, 0, [("-", "x"), ("+", "y")])])], tree),
                          ([FilePatch("old.txt", "keep.txt", [Hunk(0, 0, [("-", "1"), ("+", "x")])])], tree),
                          ([FilePatch("del.txt", None, [Hunk(0, 0, [("-", "d1")])])], tree)]:
        try:
            PatchSet(files).apply(target)
            errors.append(None)
        except TreeError as exc:
            errors.append(["TreeError", exc.path])
        except Exception as exc:  # observation only
            errors.append([type(exc).__name__, getattr(exc, "path", None), getattr(exc, "index", None)])
    out.append(errors)
    out.append([_error(patch.apply, "x"), _error(patch.apply, {"a": 1})])
    return out


def probe_patchset_reverse_and_atomic():
    from patchwork import HunkFailed, PatchSet
    old = {"a": _numbers(10), "b": "x\ny\n", "c": "gone\n"}
    new = {"a": _swap(_numbers(10), "\n4\n", "\nfour\n"), "b": "x\nY\n", "d": "fresh\n"}
    patch = PatchSet.parse(str(PatchSet.diff(old, new)))
    back = patch.reversed()
    out = [[[f.old_path, f.new_path] for f in back.files], back.apply(new).tree == old, patch.apply(new, reverse=True).log]
    broken = dict(old, b="x\nz\n")
    try:
        patch.apply(broken)
        out.append(None)
    except HunkFailed as exc:
        out.append([exc.path, exc.index])
    out.append(broken == dict(old, b="x\nz\n"))
    out.append(patch.apply(dict(old, a="pre\n" + old["a"])).log)
    return out


def probe_patchset_reused_across_trees():
    from patchwork import PatchSet
    base = _lines("[db]", "name = shop", "user = app", "[web]", "bind = 0.0.0.0", "port = 80", "name = shop",
                  "threads = 2", "gzip = on", "cache = 64", "tls = off")
    new = _swap(base, "threads = 2\n", "threads = 6\n")
    text = str(PatchSet.diff({"site.ini": base}, {"site.ini": new}))
    patch = PatchSet.parse(text)
    drifted = _swap(_swap(base, "bind = 0.0.0.0", "bind = 10.1.1.1"), "port = 80", "port = 8080")
    out = []
    for tree in [{"site.ini": base}, {"site.ini": _swap(base, "[web]", "[http]")}, {"site.ini": drifted},
                 {"site.ini": base}, {"site.ini": "# copy\n" + base}]:
        try:
            result = patch.apply(tree)
            out.append([result.log, result.tree["site.ini"].split("\n")])
        except Exception as exc:  # observation only
            out.append(type(exc).__name__)
    out.append(str(patch) == text)
    return out


# --- merge and stats ----------------------------------------------------------------------------
def probe_merge_regions():
    from patchwork import merge3
    base = _lines("a", "b", "c", "d", "e", "f")
    cases = [(base, base), (_swap(base, "b\n", "B\n"), base), (base, _swap(base, "e\n", "E\n")),
             (_swap(base, "b\n", "B\n"), _swap(base, "b\n", "B\n")), (_swap(base, "a\n", ""), _swap(base, "f\n", "f\ng\n")),
             ("x\n" + base, base + "y\n"), (_swap(base, "c\nd\n", ""), _swap(base, "e\n", "E\n"))]
    return [[str(r.text), r.conflicts, r.regions, r.clean] for r in (merge3(base, o, t) for o, t in cases)]


def probe_merge_conflicts_and_newline():
    from patchwork import MergeConflict, conflict_count, merge3, merge_text
    base = "a\nb\nc\n"
    out = [merge_text(base, "a\nX\nc\n", "a\nY\nc\n", labels=("mine", "main")),
           merge_text(base, "a\nX\nc\n", "a\nY\nc\n", show_base=True),
           merge_text(base, "a\nX\nX2\nc\n", "a\nc\n"), merge3(base, "Q\nb\nR\n", "a\nS\nc\n").conflicts,
           conflict_count(merge_text(base, "Q\nb\nR\n", "S\nb\nT\n")), conflict_count("<<<<<<< x\n<<<<<<<\n"),
           [merge_text("a\nb", "a\nb\n", "a\nB"), merge_text("a\nb", "a\nB", "a\nb"), merge_text("a\nb\n", "a\nb\n", "a\nb"),
            merge_text("", "x\n", "")]]
    try:
        merge3(base, "Q\nb\nR\n", "S\nb\nT\n", strict=True)
    except MergeConflict as exc:
        out.append(exc.conflicts)
    out.append([_error(merge3, base, base, base, labels=("a",)), _error(merge3, base, base, base, labels=("a", "")),
                _error(merge3, base, base, base, labels=["a", "b"]), _error(merge3, 1, base, base)])
    return out


def probe_diffstat_scaling_and_summary():
    from patchwork import FilePatch, Hunk, PatchSet, diffstat, summary
    from patchwork.stats import churn, summary_line
    big = FilePatch("big.py", "big.py", [Hunk(0, 0, [("-", str(n)) for n in range(30)] + [("+", str(n)) for n in range(90)])])
    small = FilePatch("s.py", "s.py", [Hunk(0, 0, [("-", "a"), ("+", "b")])])
    one = FilePatch("old/x", "new/x", [Hunk(0, 0, [("+", "z")])])
    gone = FilePatch("g", None, [Hunk(0, 0, [("-", "q")] * 3)])
    patch = PatchSet([big, small, one, gone])
    return [diffstat(patch), diffstat(patch, width=20), diffstat(patch, width=200), diffstat([small]), diffstat([]),
            diffstat([one]), summary(patch), summary([]), churn(patch), summary_line([gone]),
            [_error(diffstat, patch, 0), _error(diffstat, patch, True), _error(diffstat, patch, 2.5)],
            diffstat([FilePatch("w", "w", [Hunk(0, 0, [("+", "a")] * 41)])])]


# --- defaults and ordering edges ----------------------------------------------------------------
def probe_option_defaults():
    from patchwork import Hunk, PatchSet, apply_hunks, diff_texts, find, make_hunks
    from patchwork.text import same_lines
    old, new = "a b\nc\n", "a  b\nc\n"
    out = [find(["a  b", "c"], ["a b"], 0), same_lines(["a  b"], ["a b"]), len(PatchSet.diff({"f": old}, {"f": new})),
           diff_texts(old, new, "f"), _error(apply_hunks, "x\na  b\ny\n", make_hunks("x\na b\ny\n", "x\na b\nY\n"), fuzz=0),
           _error(PatchSet.diff({"f": "a b\nq\n"}, {"f": "a b\nQ\n"}).apply, {"f": "a  b\nq\n"}, fuzz=0),
           Hunk(0, 0, [("+", "x")]).validate().old_start]
    return out


def probe_fuzz_limits():
    from patchwork import apply_hunks, make_hunks
    base = _numbers(10)
    end = make_hunks(base, _swap(base, "\n10\n", "\nten\n"))
    tail = apply_hunks(_swap(base, "\n7\n", "\nseven\n"), end)
    start = make_hunks(base, _swap(base, "1\n", "one\n"))
    head = apply_hunks(_swap(base, "\n4\n", "\nfour\n"), start)
    mid = _swap(base, "\n5\n", "\nfive\n")
    target = _swap(base, "\n3\n", "\nthree\n")
    return [_results(tail), str(tail.text).split("\n")[-3:], _results(head), str(head.text).split("\n")[:2],
            _error(apply_hunks, target, make_hunks(base, mid), fuzz=1)]


def probe_edge_ordering():
    from patchwork import FilePatch, Hunk, PatchParseError, PatchSet, make_hunks, parse_patch
    from patchwork.stats import churn, diffstat
    base = _numbers(30)
    new = _swap(_swap(_swap(base, "\n3\n", "\nX3\n"), "\n12\n", "\nX12\n"), "\n16\n", "\nX16\n")
    nearer = _swap(_swap(_swap(base, "\n5\n", "\nX5\n"), "\n9\n", "\nX9\n"), "\n15\n", "\nX15\n")
    out = [_shape(make_hunks(base, new)), _shape(make_hunks(base, nearer))]
    ps = PatchSet([FilePatch("z.txt", "z.txt", make_hunks(base, _swap(base, "\n12\n", "\nX\n"))),
                   FilePatch("m.txt", "m.txt", make_hunks(base, _swap(base, "\n20\n", "\nY\n")))])
    drift = {"z.txt": _swap(base, "\n9\n", "\nnine\n"), "m.txt": _swap(base, "\n17\n", "\nseventeen\n"), "a.txt": "a\n"}
    result = ps.apply(drift)
    out += [result.fuzzy, list(result.tree), list(result.results)]
    rows = [FilePatch(name, name, [Hunk(0, 0, [("+", "x")] * n)]) for name, n in (("q", 2), ("b", 2), ("k", 5), ("a", 1))]
    out += [list(churn(rows)), diffstat(rows, width=1)]
    texts = ["--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b", "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b\n--- end",
             "note\n+++ not a header\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b\n",
             "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b\n@@ -10,3 +10,3 @@\n x\n-y\n+z\n w\n@@ -11 +11 @@\n-y\n+q\n"]
    for text in texts:
        try:
            out.append([[_hunk(h) for h in p.hunks] for p in parse_patch(text)])
        except PatchParseError as exc:
            out.append(["PatchParseError", exc.line])
        except Exception as exc:  # observation only
            out.append(type(exc).__name__)
    return out
