#!/usr/bin/env python3
"""Publish a raw benchmark tree under app results, with reversible path-only edits."""
import argparse
import csv
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
PATH_FIELDS = {"events", "stdout", "stderr", "dataset", "tasks", "tests", "reputation", "output", "benchmark"}
PATH_FLAGS = {"--events", "--reputation", "--tasks", "--tests", "--dataset", "--output"}
PROTECTED = {"response", "reasoning", "code", "prompt", "messages", "source_hashes", "final_source_hashes", "runtime"}


def transform(raw, relative, normalize):
    """Edit whitelisted parsed values; audit the inverse, allowing serialization changes."""
    changes = []
    def audit(original, exported, edits):
        restored = copy.deepcopy(exported)
        for edit in reversed(edits):
            parent = restored
            for key in edit["path"][:-1]: parent = parent[key]
            assert parent[edit["path"][-1]] == edit["export"]
            parent[edit["path"][-1]] = edit["original"]
        assert json.dumps(restored, ensure_ascii=False) == json.dumps(original, ensure_ascii=False), "Semantic inverse failed"
    def document(original, scope, record=None):
        obj, edits = copy.deepcopy(original), []
        def set_value(parent, key, path, replacement):
            value = parent[key]
            if replacement != value:
                edits.append(dict(path=list(path), original=value, export=replacement, scope=scope, record=record))
                parent[key] = replacement
        def walk(value, path=()):
            if isinstance(value, dict):
                for key in value:
                    if key in PROTECTED: continue
                    child = value[key]
                    if key == "command" and isinstance(child, list):
                        for i, token in enumerate(child):
                            if not isinstance(token, str): continue
                            replacement = normalize(token) if i == 1 or i > 1 and child[i-1] in PATH_FLAGS else token
                            if i == 0 and re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", Path(token).name): replacement = "python3"
                            set_value(child, i, path+(key,i), replacement)
                    elif key in PATH_FIELDS and isinstance(child, str): set_value(value, key, path+(key,), normalize(child))
                    else: walk(child, path+(key,))
            elif isinstance(value, list):
                for i, child in enumerate(value): walk(child, path+(i,))
        if scope == "json": walk(obj)
        elif isinstance(obj, dict):
            if scope == "stdout" or obj.get("type") == "run_end":
                if isinstance(obj.get("events"), str): set_value(obj, "events", ("events",), normalize(obj["events"]))
            elif obj.get("type") == "run_start" and isinstance(obj.get("config"), dict):
                for key in ("events", "reputation", "tasks", "tests"):
                    if isinstance(obj["config"].get(key), str): set_value(obj["config"], key, ("config",key), normalize(obj["config"][key]))
        audit(original, obj, edits)
        changes.extend(edits)
        return obj, edits
    if relative.suffix == ".jsonl" or relative.name.endswith(".stdout.log"):
        output = []
        scope = "stdout" if relative.name.endswith(".stdout.log") else "jsonl"
        for index, line in enumerate(raw.splitlines(keepends=True), 1):
            try: original = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError): output.append(line); continue
            obj, edits = document(original, scope, index)
            newline = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b""
            output.append(json.dumps(obj, ensure_ascii=False).encode()+newline if edits else line)
        return b"".join(output), changes
    if relative.name in {"metadata.json", "summary.json", "analysis.json"}:
        obj, edits = document(json.loads(raw), "json")
        return (json.dumps(obj, indent=2, ensure_ascii=False)+"\n").encode() if edits else raw, changes
    if relative.suffix == ".csv":
        original = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
        rows = copy.deepcopy(original)
        if rows and "events" in rows[0]:
            column = rows[0].index("events")
            for i, row in enumerate(rows[1:], 1):
                if len(row) <= column: continue
                replacement = normalize(row[column])
                if replacement != row[column]:
                    changes.append(dict(path=[i,column], original=row[column], export=replacement, scope="csv", record=i))
                    row[column] = replacement
        audit(original, rows, changes)
        if changes:
            output = io.StringIO(newline="")
            csv.writer(output, lineterminator="\r\n" if b"\r\n" in raw else "\n").writerows(rows)
            return output.getvalue().encode(), changes
    return raw, changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="Raw benchmark directory containing metadata.json")
    parser.add_argument("--output", type=Path, help="New directory under this app's results/")
    parser.add_argument("--self-test", action="store_true", help="Run local synthetic fixture only")
    args = parser.parse_args(argv)
    if args.self_test: return self_test()
    if args.source is None or args.output is None: parser.error("source and --output are required")
    source, destination = args.source.resolve(), args.output.resolve()
    if not source.is_dir() or destination.exists() or destination == source or source in destination.parents:
        parser.error("source must exist; output must be new and outside source")
    try: export_root = destination.relative_to(HERE / "results").as_posix()
    except ValueError: parser.error("output must be under app results/")
    metadata = json.loads((source / "metadata.json").read_bytes())
    producers = sorted({str(Path(case["command"][1]).parent) for case in metadata["cases"]})
    if not producers or any(not Path(root).is_absolute() for root in producers): parser.error("absolute producer script paths required in cases.command[1]")
    def normalize(value):
        if not Path(value).is_absolute(): return value
        for root, prefix in [(source, "results/" + export_root)] + [(Path(p), ".") for p in producers] + [(HERE, ".")]:
            try: suffix = Path(value).relative_to(root).as_posix()
            except ValueError: continue
            return prefix if suffix == "." else prefix + "/" + suffix
        return value
    paths = sorted(source.rglob("*"))
    if any(path.is_symlink() for path in paths): parser.error("source symlinks are not supported")
    manifest_name = "export-manifest.json" if (source / "manifest.json").exists() else "manifest.json"
    if (source / manifest_name).exists(): parser.error("source already contains reserved export manifest name")
    destination.mkdir(parents=True, exist_ok=False)
    files = []
    for path in paths:
        relative, target = path.relative_to(source), destination / path.relative_to(source)
        if path.is_dir(): target.mkdir(parents=True, exist_ok=True); continue
        raw = path.read_bytes()
        exported, patches = transform(raw, relative, normalize)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(exported)
        assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(exported).digest()
        files.append(dict(source=str(path), export=str(target.relative_to(HERE)), original_sha256=hashlib.sha256(raw).hexdigest(),
                          export_sha256=hashlib.sha256(exported).hexdigest(), original_bytes=len(raw), export_bytes=len(exported),
                          export_byte_identical=raw == exported, reverse_normalization_semantic_identity=True,
                          formatting_may_change=bool(patches), normalizations=patches))
    manifest = dict(schema_version=2, curated_utc=datetime.now(timezone.utc).isoformat(), source_directory=str(source),
                    exporter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    export_directory=str(destination.relative_to(HERE)), producer_directories=producers,
                    normalization_policy="Only whitelisted path/interpreter values; JSON/CSV formatting may change. Inverse edits restore parsed values/order/types; original/export SHA256 retained. Model response/source VALUES unchanged; scripts/figures copied byte-identically",
                    original_producer_provenance={k:metadata.get(k) for k in ("git_revision","source_hashes","final_source_hashes","source_changed_during_run")},
                    analysis_provenance="Original analysis hash references retained unchanged; file entries map original input hashes to path-normalized exports", files=files)
    (destination / manifest_name).write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+"\n")
    print(json.dumps(dict(output=str(destination), manifest=manifest_name, files=len(files), changed=sum(bool(f["normalizations"]) for f in files))))


def self_test():
    import contextlib
    import tempfile
    global HERE
    previous = HERE
    with tempfile.TemporaryDirectory() as temporary:
        HERE, source, producer = [Path(temporary).resolve()/part for part in ("app", "external/raw,cohort", "frozen/app")]
        source.mkdir(parents=True)
        target, trace = HERE/"results/fixture", str(source/"t-é.jsonl")
        metadata = dict(output=str(source), dataset=str(HERE/"datasets/tasks.json"), tests=str(producer/"tests.json"), response=trace,
                        source_hashes={"harness.py":"a"*64}, cases=[dict(events=trace, command=["/env/bin/python3.12",str(producer/"harness.py"),"--events",trace,"--model",str(producer/"model")])])
        records = [dict(type="run_start",config=dict(events=trace,tasks=str(producer/"tasks.json"))), dict(type="request_end",response=trace,code="é "+trace),dict(type="run_end",events=trace)]
        originals = {"metadata.json":json.dumps(metadata,indent=4).encode()+b"\r\n", "t-é.jsonl":b"".join(json.dumps(r).encode()+b"\r\n" for r in records),
                     "summary.csv":('events,response\r\n"'+trace+'","'+trace+'"\r\n').encode(),
                     "case.stdout.log":("plain "+trace+"\r\n"+json.dumps(dict(events=trace,response=trace))+"\r\n").encode(),
                     "empty.stderr.log":b"", "analysis/plot.svg":("<svg>"+trace+"</svg>").encode(), "analysis/plot.png":b"\x89PNG\x00opaque", "saved.py":("print("+repr(trace)+")").encode(),
                     "analysis/analysis.json":json.dumps(dict(benchmark=str(source),metadata_sha256="b"*64)).encode()}
        for name, raw in originals.items():
            path=source/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
        try:
            with contextlib.redirect_stdout(io.StringIO()): main([str(source),"--output",str(target)])
            manifest=json.loads((target/"manifest.json").read_text())
            assert len(manifest["files"])==len(originals)
            for entry in manifest["files"]:
                assert entry["reverse_normalization_semantic_identity"]
                assert hashlib.sha256(Path(entry["source"]).read_bytes()).hexdigest()==entry["original_sha256"]
                assert hashlib.sha256((HERE/entry["export"]).read_bytes()).hexdigest()==entry["export_sha256"]
            for name in ("empty.stderr.log","analysis/plot.svg","analysis/plot.png","saved.py"): assert (target/name).read_bytes()==originals[name]
            exported=json.loads((target/"metadata.json").read_text()); command=exported["cases"][0]["command"]
            assert command[:2]==["python3","./harness.py"] and command[-1]==str(producer/"model") and exported["response"]==trace
            assert exported["dataset"]=="./datasets/tasks.json" and exported["tests"]=="./tests.json"
            assert json.loads((target/"t-é.jsonl").read_text().splitlines()[1])==records[1]
            assert list(csv.reader(io.StringIO((target/"summary.csv").read_text())))[1][1]==trace
            assert all((source/name).read_bytes()==raw for name,raw in originals.items())
            try:
                with contextlib.redirect_stderr(io.StringIO()): main([str(source),"--output",str(target)])
            except SystemExit as exc: assert exc.code==2
            else: raise AssertionError("Existing destination accepted")
        finally: HERE=previous
    print("PASS: frozen producer/outside raw root, Unicode/CRLF/CSV quoting, response/code preservation, source/figure hashes, semantic inverse, overwrite refusal; no API")


if __name__ == "__main__": main()
