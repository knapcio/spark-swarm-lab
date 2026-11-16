"""patchwork: line diffs, unified patches, fuzzy patch application and three-way merges."""
from .apply import ApplyResult, HunkResult, apply_hunks, apply_text, find, is_applied
from .errors import HunkFailed, MergeConflict, PatchParseError, PatchworkError, TreeError
from .hunks import Hunk, make_hunks
from .lcs import edit_distance, matches, opcodes, similarity
from .merge import MergeResult, conflict_count, merge3, merge_text
from .patchset import PatchSet, TreeResult, diff_texts
from .stats import diffstat, summary
from .text import Text, loose
from .unified import FilePatch, format_file_patch, format_hunk, parse_patch

__all__ = ["ApplyResult", "FilePatch", "Hunk", "HunkFailed", "HunkResult", "MergeConflict", "MergeResult",
           "PatchParseError", "PatchSet", "PatchworkError", "Text", "TreeError", "TreeResult", "apply_hunks",
           "apply_text", "conflict_count", "diff_texts", "diffstat", "edit_distance", "find", "format_file_patch",
           "format_hunk", "is_applied", "loose", "make_hunks", "matches", "merge3", "merge_text", "opcodes",
           "parse_patch", "similarity", "summary"]
