#!/usr/bin/env python3
"""Original coding corpus: 6 development + 18 evaluation tasks. No model/API execution."""
import argparse
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import random
import re

PROTOCOL = "original-python-functions-v1"


def stable_unique(values):
    return list(dict.fromkeys(values))


def run_length(text):
    out = []
    for ch in text:
        if out and out[-1][0] == ch: out[-1][1] += 1
        else: out.append([ch, 1])
    return out


def merge_intervals(intervals):
    out = []
    for start, end in sorted([sorted(pair) for pair in intervals]):
        if out and start <= out[-1][1]: out[-1][1] = max(out[-1][1], end)
        else: out.append([start, end])
    return out


def top_k_frequent(values, k):
    return sorted(set(values), key=lambda v: (-values.count(v), values.index(v)))[:max(0, k)]


def moving_sums(values, width):
    return [sum(values[i:i+width]) for i in range(len(values)-width+1)] if width > 0 else []


def parse_version(text):
    return list(map(int, text.split("."))) if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", text) else None


def stable_group_pairs(pairs):
    groups = {}
    for key, value in pairs: groups.setdefault(key, []).append(value)
    return [[key, values] for key, values in groups.items()]


def rotate_matrix(matrix):
    return [list(row) for row in zip(*matrix[::-1])] if matrix else []


def longest_unique_span(text):
    best = ""
    for start in range(len(text)):
        end = start
        while end < len(text) and text[end] not in text[start:end]: end += 1
        if end-start > len(best): best = text[start:end]
    return best


def balanced_brackets(text):
    stack, pairs = [], {")": "(", "]": "[", "}": "{"}
    for ch in text:
        if ch in "([{": stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]: return False
    return not stack


def dedupe_by_last(records):
    out, seen = [], set()
    for key, value in reversed(records):
        if key not in seen: out.append([key, value]); seen.add(key)
    return out[::-1]


def collapse_whitespace(text):
    return re.sub(r"[ \t\n\r\v\f]+", " ", text).strip(" \t\n\r\v\f")


def natural_sort_strings(strings):
    def key(text):
        return [(1, int(part)) if re.fullmatch("[0-9]+", part) else (0, part)
                for part in re.split("([0-9]+)", text) if part]
    return sorted(strings, key=key)


def zip_longest_sum(left, right):
    return [(left[i] if i < len(left) else 0)+(right[i] if i < len(right) else 0) for i in range(max(len(left), len(right)))]


def invert_index(groups):
    out = {}
    for key, values in groups:
        for value in values:
            sources = out.setdefault(value, [])
            if key not in sources: sources.append(key)
    return [[value, sources] for value, sources in out.items()]


def range_compress(values):
    out = []
    for value in sorted(set(values)):
        if out and value == out[-1][1]+1: out[-1][1] = value
        else: out.append([value, value])
    return out


def prefix_totals(values):
    out = [0]
    for value in values: out.append(out[-1]+value)
    return out


def select_nth_distinct(values, n):
    ordered = sorted(set(values))
    return ordered[n] if 0 <= n < len(ordered) else None


def word_count_ascii(text):
    counts = Counter(word.lower() for word in re.findall("[A-Za-z]+", text, flags=re.ASCII))
    return [[word, counts[word]] for word in sorted(counts)]


def flatten_depth(values, depth):
    out = list(values)
    for _ in range(max(0, depth)):
        out = [child for value in out for child in (value if isinstance(value, list) else [value])]
    return out


def transpose_records(records):
    keys = list(dict.fromkeys(key for record in records for key in record))
    return [[key, [record.get(key) for record in records]] for key in keys]


def min_covering_window(values, required):
    if not required: return [0, 0]
    need, best = Counter(required), None
    for start in range(len(values)):
        counts = Counter()
        for end in range(start, len(values)):
            counts[values[end]] += 1
            if all(counts[v] >= n for v, n in need.items()):
                if best is None or end+1-start < best[1]-best[0]: best = [start, end+1]
                break
    return best


def apply_edits(text, edits):
    out, cursor = [], 0
    for start, end, replacement in edits: out.extend([text[cursor:start], replacement]); cursor = end
    return "".join(out)+text[cursor:]


def interleave_lists(chunks):
    return [chunk[i] for i in range(max(map(len, chunks), default=0)) for chunk in chunks if i < len(chunk)]


def ints(r): return [r.randint(-4, 6) for _ in range(r.randrange(9))]
def text(r): return "".join(r.choice("abAAé🙂\u0301 \t\u00a0") for _ in range(r.randrange(12)))
def pairs(r): return [[r.choice(["a", "b", "é"]), r.randint(-3, 3)] for _ in range(r.randrange(8))]
def random_groups(r): return [[key,[r.choice(["x","é","🙂"]) for _ in range(r.randrange(5))]] for key in ["a","b","é"][:r.randrange(4)]]

# Each entry: trusted function, descriptive label, unambiguous public contract,
# two independently authored expected examples, extra hidden fixtures, seeded case generator.
TASKS = [
 (stable_unique,"basic-order","Input is a list of integers. Return each distinct value once, in first-occurrence order; empty returns [].", [([[2,-1,2,3,-1]],[2,-1,3]),([[]],[])], [[[0,0]], [[-2,-1,-2]]], lambda r:[ints(r)]),
 (run_length,"basic-unicode","Run-length encode adjacent equal Unicode code points as [character,count] pairs. No normalization; empty returns [].", [(["aaééa"],[["a",2],["é",2],["a",1]]),([""],[])], [["🙂🙂a"],["e\u0301e\u0301"]], lambda r:[text(r)]),
 (merge_intervals,"sorting-boundaries","Input integer endpoint pairs. Normalize each pair to [min,max], sort, merge intervals that overlap or share an endpoint; adjacency alone does not merge. Return sorted pairs; empty [].", [([[[5,2],[1,3],[8,9]]],[[1,5],[8,9]]),([[]],[])], [[[[1,2],[3,4]]],[[[-2,-5],[-3,0],[0,0]]]], lambda r:[[[r.randint(-8,8),r.randint(-8,8)] for _ in range(r.randrange(7))]]),
 (top_k_frequent,"counting-ties","Input integer list and integer k. Return up to k distinct values by descending count; ties follow first occurrence in input. k<=0 or empty returns [].", [([[3,1,3,2,1],2],[3,1]),([[1,2],0],[])], [[[-1,-1,0],9],[[],3]], lambda r:[ints(r),r.randint(-2,7)]),
 (moving_sums,"window-boundaries","Input integer list and integer width. Return sums of each contiguous full-width window, left to right. width<=0 or width>length returns []; no padding.", [([[1,-2,4,3],2],[-1,2,7]),([[1,2],3],[])], [[[],1],[[4],0],[[4],1]], lambda r:[ints(r),r.randint(-1,10)]),
 (parse_version,"ascii-validation","Input a string. Accept only one or more ASCII decimal digits per dot-separated component, no whitespace/signs/empty components. Return integer components, preserving trailing zeros; invalid returns None. Unicode digits are invalid.", [(["01.2.0"],[1,2,0]),(["1..2"],None)], [[""],["١.2"],["1.2\n"],["0"]], lambda r:[r.choice(["1.02","0.0"," 1","1.","+2","２","3.4.5", "1\t2"])]),
 (stable_group_pairs,"grouping-order","Input [string_key,integer_value] pairs. Group values by exact key, preserving first key appearance and value order. Return [key,values] pairs; empty []. No Unicode normalization.", [([[["b",2],["a",1],["b",3]]],[["b",[2,3]],["a",[1]]]),([[]],[])], [[[["é",-1],["é",-1]]]],lambda r:[pairs(r)]),
 (rotate_matrix,"matrix-shapes","Input a rectangular integer matrix. Return its 90-degree clockwise rotation. [] and matrices with zero columns return []; rows are guaranteed equal length.", [([[[1,2,3],[4,5,6]]],[[4,1],[5,2],[6,3]]),([[]],[])], [[[[],[]]],[[[-1],[2],[3]]]],lambda r:[[[r.randint(-3,3) for _ in range(3)] for _ in range(r.randrange(5))]]),
 (longest_unique_span,"substring-ties","Return the longest contiguous substring with no repeated Unicode code point; choose earliest starting position on a length tie. Empty returns ''. No normalization.", [(["abba"],"ab"),(["🙂a🙂b"],"a🙂b")], [[""],["aaaa"],["e\u0301e"]],lambda r:[text(r)]),
 (balanced_brackets,"stack-state","For a string, return whether (), [] and {} are properly nested and closed. Ignore every other Unicode code point. Empty/no brackets returns True.", [(["a([{}])é"],True),(["([)]"],False)], [[""],[")"],["(()"]],lambda r:["".join(r.choice("()[]{}aé") for _ in range(r.randrange(12)))]),
 (dedupe_by_last,"record-order","Input [string_key,integer_value] records. Keep only the last record for each exact key. Order output records by their last-occurrence positions in the original input. Empty [].", [([[["a",1],["b",2],["a",3]]],[["b",2],["a",3]]),([[]],[])], [[[["é",1],["é",-2]]]],lambda r:[pairs(r)]),
 (collapse_whitespace,"ascii-unicode-boundary","Collapse runs of ASCII space, tab, LF, CR, vertical tab and form feed into one ASCII space and strip only those characters at both ends. Preserve all other code points including NBSP; no normalization.", [([" \ta\n b  "],"a b"),(["\u00a0a\u00a0"],"\u00a0a\u00a0")], [[""],["\r\v\f"],["é\t🙂"]],lambda r:[text(r)]),
 (natural_sort_strings,"token-sort-ties","Split strings into maximal ASCII-digit and non-digit runs. Compare digit runs by integer value, non-digit runs by case-sensitive Unicode lexical order; text tokens sort before numeric tokens when kinds differ. Shorter equal-prefix token lists sort first; equal keys preserve input order. Empty strings allowed; Unicode digits are text.", [([["x10","x2","x02","x1"]],["x1","x2","x02","x10"]),([["2","a","","1"]],["","a","1","2"])], [[["é2","é10","é02","x٢"]]],lambda r:[[r.choice(["a2","a10","A1","é3","2","", "a02"]) for _ in range(r.randrange(8))]]),
 (zip_longest_sum,"unequal-lengths","Input two integer lists. Sum corresponding entries, treating missing entries as zero; return length=max(input lengths). Both empty returns [].", [([[1,-2],[3,4,5]],[4,2,5]),([[],[]],[])], [[[],[-1,2]],[[0],[]]],lambda r:[ints(r),ints(r)]),
 (invert_index,"inverse-dedup-order","Input [unique_string_key,list_of_strings] groups. Return [value,source_keys] pairs: values ordered by first encounter scanning groups then their lists, source keys by group order with no duplicates per value. Exact Unicode equality; empty [].", [([[["a",["x","x","y"]],["b",["y","z"]]]],[["x",["a"]],["y",["a","b"]],["z",["b"]]]),([[]],[])], [[[["é",[]],["b",["🙂","🙂"]]]]],lambda r:[random_groups(r)]),
 (range_compress,"integer-ranges","Input integers in any order, with duplicates. Sort distinct values and compress maximal consecutive integer runs into [start,end] pairs. Empty [].", [([[4,2,3,2,-1,0]],[[-1,0],[2,4]]),([[]],[])], [[[0]],[[1,3,5]], [[-3,-2,-1]]],lambda r:[ints(r)]),
 (prefix_totals,"prefix-boundaries","Input integer list. Return cumulative totals including an initial zero, so output length is input length+1. Empty returns [0].", [([[2,-3,4]],[0,2,-1,3]),([[]],[0])], [[[0,0]], [[-1,-2]]],lambda r:[ints(r)]),
 (select_nth_distinct,"selection-invalid-index","Input integer list and integer n. Return the zero-based nth smallest distinct value; n<0 or n>=distinct count returns None. Empty returns None.", [([[4,1,4,-2],1],1),([[1,2],-1],None)], [[[],0],[[5,5],1],[[0],0]],lambda r:[ints(r),r.randint(-2,9)]),
 (word_count_ascii,"ascii-tokenization","Words are maximal original-input runs of ASCII letters A-Z/a-z; all other code points, including Unicode letters, delimit words. Lowercase ASCII words and return [word,count] pairs sorted lexically. Empty/no words returns [].", [(["Hi, HI! café"],[["caf",1],["hi",2]]),(["123_é"],[])], [[""],["A-a_a"],["ÉABC🙂abc"]],lambda r:[r.choice(["A B a","éabc Éx","123","Hello🙂HELLO","", "İABC"])]),
 (flatten_depth,"nested-json","Input a list of JSON scalars/nested lists and integer depth. Flatten list-valued elements by one layer per step, at most depth steps; depth<=0 returns an equal list. Do not flatten strings or dicts (dict inputs excluded). Preserve order and scalars including None/bools.", [([[1,[2,[3]],None],1],[1,2,[3],None]),([["ab",[True,[]]],0],["ab",[True,[]]])], [[[],3],[[[[]],False],2]],lambda r:[[r.randint(-3,3),[r.randint(0,4),[None,"é"]],True],r.randint(-1,4)]),
 (transpose_records,"missing-record-fields","Input list of dicts with string keys and JSON scalar values. Discover keys by record order and each dict's insertion order. Return [key,column] pairs, each column containing that key's value per record or None if absent. Empty input/only empty dicts returns [].", [([[{"b":2},{"a":1,"b":3}]],[["b",[2,3]],["a",[None,1]]]),([[]],[])], [[[{},{}]],[[{"é":None},{"a":-1}]]],lambda r:[[{k:r.randint(-3,3) for k in ["a","é","b"] if r.randrange(2)} for _ in range(r.randrange(5))]]),
 (min_covering_window,"multiset-window","Input integer lists values and required. Return [start,end) indices of shortest contiguous window containing required with its multiplicities; ties choose earliest start. required=[] returns [0,0]; impossible returns None.", [([[1,2,1,3,2],[1,2]],[0,2]),([[1,2],[1,1]],None)], [[[],[]],[[],[1]],[[2,1,2,1],[1,1]]],lambda r:[ints(r),[r.randint(-2,3) for _ in range(r.randrange(4))]]),
 (apply_edits,"original-index-edits","Input Unicode text and valid non-overlapping [start,end,replacement] edits sorted by start. Indices are code-point offsets into ORIGINAL text, 0<=start<=end<=len(text); same-start edits excluded. Apply simultaneously using half-open intervals; start=end inserts. Preserve untouched text; no normalization.", [(["abcd",[[1,2,"X"],[3,4,""]]],"aXc"),(["é🙂",[[1,1,"!"]]],"é!🙂")], [["",[]],["abc",[[0,1,""],[1,3,"Z"]]]],lambda r:["é🙂abc",[[0,1,r.choice(["","X","🙂"])],[3,5,"!"]]]),
 (interleave_lists,"ragged-round-robin","Input list of integer lists. Take index 0 from each nonempty list in input order, then index 1 from each long enough list, and continue until exhausted. Preserve duplicates/negatives. Empty/all empty returns [].", [([[[1,2],[],[3,4,5]]],[1,3,2,4,5]),([[]],[])], [[[[],[]]],[[[-1],[0,0],[]]]],lambda r:[[ints(r) for _ in range(r.randrange(5))]])
]


def build(seed):
    rng, public, private = random.Random(seed), [], {}
    for index, (fn, label, spec, examples, fixtures, fuzz) in enumerate(TASKS):
        split = "development" if index < 6 else "evaluation"
        task_id = f"{split[:3]}-{fn.__name__}"
        shown = []
        for args, expected in examples:
            assert fn(*json.loads(json.dumps(args))) == expected, fn.__name__
            shown.append(dict(args=args, expected=expected))
        seen = {json.dumps(e["args"]) for e in shown}
        cases = []
        for args in fixtures+[fuzz(rng) for _ in range(16)]:
            encoded = json.dumps(args)
            if encoded in seen: continue
            seen.add(encoded)
            original = json.loads(encoded)
            expected = fn(*original)
            assert json.dumps(original) == encoded, "Reference mutated input"
            json.dumps(expected, allow_nan=False)
            cases.append(dict(args=args, expected=expected))
        assert len(cases) >= 3, fn.__name__
        public.append(dict(id=task_id, split=split, function_name=fn.__name__, spec=spec,
                           examples=shown, difficulty_description=label))
        private[task_id] = dict(tests=cases, trusted_reference_source=inspect.getsource(fn), trusted_reference_sha256=hashlib.sha256(inspect.getsource(fn).encode()).hexdigest())
    assert len(public) == len({t["function_name"] for t in public}) == 24
    assert Counter(t["split"] for t in public) == {"development":6,"evaluation":18}
    return public, private


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--output", type=Path, help="New directory; default dry-run; existing output refused")
    args = parser.parse_args(argv)
    if args.output and args.output.exists(): parser.error("output directory already exists")
    public, private = build(args.seed)
    assert (public, private) == build(args.seed), "Determinism check failed"
    common = dict(protocol=PROTOCOL, generator_seed=args.seed,
                  generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  authorship="Original author-written synthetic tasks; no external benchmark content.",
                  rules="Python 3 pure functions, positional args, JSON-serializable outputs, no external I/O.",
                  limitations="Difficulty descriptions are descriptive, not empirically calibrated. Hidden expected values use trusted references, not an independent correctness proof.")
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        for name, data in [("tasks.json",dict(common,tasks=public)),("hidden-tests.json",dict(common,references=private,note="Never feed tests or reference source to model; references use the imports in coding_tasks.py."))]:
            (args.output/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps(dict(mode="written" if args.output else "dry_run",tasks=24,development=6,evaluation=18,
                         hidden_cases=sum(len(v["tests"]) for v in private.values()),verified=True,output=str(args.output) if args.output else None)))


if __name__ == "__main__": main()
