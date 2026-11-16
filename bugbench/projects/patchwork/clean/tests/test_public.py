"""The project's own regression tests (visible to everyone)."""
import unittest

from patchwork import (Hunk, HunkFailed, MergeConflict, PatchParseError, PatchSet, Text, TreeError, apply_hunks,
                       apply_text, diff_texts, diffstat, make_hunks, merge3, opcodes, parse_patch, similarity, summary)

NUMBERS = "".join(f"{n}\n" for n in range(1, 21))


def edit(text, old, new):
    assert text.count(old) == 1
    return text.replace(old, new)


class TextTests(unittest.TestCase):
    def test_round_trip_and_newline(self):
        for value in ("", "a", "a\n", "a\nb", "\n", "a\r\nb\n"):
            self.assertEqual(str(Text.parse(value)), value)
        self.assertEqual((Text.parse("a\nb").newline, Text.parse("").newline), (False, True))
        self.assertNotEqual(Text.parse("a\n"), Text.parse("a"))


class DiffTests(unittest.TestCase):
    def test_opcodes_tie_break(self):
        self.assertEqual(opcodes("xy", "yx"), [("delete", 0, 1, 0, 0), ("equal", 1, 2, 0, 1), ("insert", 2, 2, 1, 2)])
        self.assertEqual(opcodes("abc", "abXc"), [("equal", 0, 2, 0, 2), ("insert", 2, 2, 2, 3), ("equal", 2, 3, 3, 4)])
        self.assertEqual(similarity("abcd", "abce"), 0.75)

    def test_hunks_far_apart_are_separate(self):
        new = edit(edit(NUMBERS, "\n3\n", "\nthree\n"), "\n11\n", "\neleven\n")
        hunks = make_hunks(NUMBERS, new)
        self.assertEqual([(h.old_start, h.old_len, h.new_start, h.new_len) for h in hunks], [(0, 6, 0, 6), (7, 7, 7, 7)])

    def test_hunks_close_together_are_merged(self):
        new = edit(edit(NUMBERS, "\n3\n", "\nthree\n"), "\n6\n", "\nsix\n")
        hunks = make_hunks(NUMBERS, new)
        self.assertEqual(len(hunks), 1)
        self.assertEqual((hunks[0].old_start, hunks[0].old_len), (0, 9))

    def test_unified_text(self):
        text = diff_texts("a\nb\nc\n", "a\nB\nc\n", "f.txt")
        self.assertEqual(text, "--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n")
        self.assertEqual(diff_texts("x\n", "x\n"), "")


class FormatTests(unittest.TestCase):
    def test_changed_last_line_without_newline(self):
        text = diff_texts("a\nb", "a\nc", "f")
        self.assertEqual(text.splitlines()[-4:], ["-b", "\\ No newline at end of file", "+c",
                                                  "\\ No newline at end of file"])
        patch = parse_patch(text)[0]
        self.assertEqual(apply_text("a\nb", patch.hunks), "a\nc")

    def test_parse_errors(self):
        with self.assertRaises(PatchParseError):
            parse_patch("--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n-b\n")
        with self.assertRaises(PatchParseError):
            parse_patch("just text\n")

    def test_creation_and_omitted_counts(self):
        patch = parse_patch("--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+hello\n")[0]
        self.assertTrue(patch.is_new)
        self.assertEqual((patch.hunks[0].old_len, patch.hunks[0].new_len), (0, 1))


class ApplyTests(unittest.TestCase):
    def test_offset(self):
        new = edit(NUMBERS, "\n10\n", "\nten\n")
        hunks = make_hunks(NUMBERS, new)
        result = apply_hunks("0\n" + NUMBERS, hunks)
        self.assertEqual(str(result.text), "0\n" + new)
        self.assertEqual(result.hunks[0].describe(), "hunk 1 applied at line 8 (offset +1)")

    def test_fuzz_one(self):
        new = edit(NUMBERS, "\n10\n", "\nten\n")
        hunks = make_hunks(NUMBERS, new)
        drifted = edit(NUMBERS, "\n7\n", "\nseven\n")
        with self.assertRaises(HunkFailed):
            apply_hunks(drifted, hunks, fuzz=0)
        result = apply_hunks(drifted, hunks)
        self.assertEqual(str(result.text), edit(drifted, "\n10\n", "\nten\n"))
        self.assertEqual(result.hunks[0].describe(), "hunk 1 applied at line 8 (fuzz 1)")

    def test_reverse_and_partial(self):
        new = edit(NUMBERS, "\n2\n", "\ntwo\n")
        hunks = make_hunks(NUMBERS, new)
        self.assertEqual(apply_text(new, hunks, reverse=True), NUMBERS)
        result = apply_hunks("x\n", hunks + [Hunk(0, 0, [("-", "x"), ("+", "y")])], partial=True)
        self.assertEqual((str(result.text), result.rejected), ("y\n", [0]))


class PatchSetTests(unittest.TestCase):
    def test_tree_round_trip(self):
        old = {"a.txt": NUMBERS, "gone.txt": "bye\n"}
        new = {"a.txt": edit(NUMBERS, "\n5\n", "\nfive\n"), "new.txt": "hi\n"}
        patch = PatchSet.parse(str(PatchSet.diff(old, new)))
        result = patch.apply(old)
        self.assertEqual(result.tree, new)
        self.assertEqual(result.log[0], "patching file a.txt")
        self.assertEqual(patch.apply(new, reverse=True).tree, old)
        self.assertEqual(old, {"a.txt": NUMBERS, "gone.txt": "bye\n"})

    def test_all_or_nothing(self):
        patch = PatchSet.diff({"a": "1\n", "b": "2\n"}, {"a": "one\n", "b": "two\n"})
        with self.assertRaises(HunkFailed):
            patch.apply({"a": "1\n", "b": "zzz\n"})
        with self.assertRaises(TreeError):
            patch.apply({"a": "1\n"})

    def test_diffstat(self):
        patch = PatchSet.diff({"a.txt": "1\n2\n", "bb.txt": "x\n"}, {"a.txt": "1\n3\n4\n", "bb.txt": "x\n", "c": "z\n"})
        self.assertEqual(diffstat(patch), [" a.txt | 3 ++-", " c     | 1 +", " 2 files changed, 3 insertions(+), 1 deletion(-)"])
        self.assertEqual(summary(patch), {"files": 2, "hunks": 2, "insertions": 3, "deletions": 1})


class MergeTests(unittest.TestCase):
    def test_clean_merge_and_conflict(self):
        base = "a\nb\nc\nd\ne\n"
        result = merge3(base, "a\nB\nc\nd\ne\n", "a\nb\nc\nD\ne\n")
        self.assertEqual((str(result.text), result.conflicts), ("a\nB\nc\nD\ne\n", 0))
        conflict = merge3(base, "a\nX\nc\nd\ne\n", "a\nY\nc\nd\ne\n")
        self.assertEqual(str(conflict.text), "a\n<<<<<<< ours\nX\n=======\nY\n>>>>>>> theirs\nc\nd\ne\n")
        with self.assertRaises(MergeConflict):
            merge3(base, "a\nX\nc\nd\ne\n", "a\nY\nc\nd\ne\n", strict=True)


if __name__ == "__main__":
    unittest.main()
