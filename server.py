#!/usr/bin/env python3
"""Read-only, loopback-only viewer for the local swarm JSONL event log."""

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


APP_DIR = Path(__file__).resolve().parent


def read_events(path):
    """Allow a writer's unfinished last record, but reject corrupt older records."""
    lines = path.read_bytes().splitlines()
    events = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if index == len(lines) - 1:
                break
            raise ValueError(f"Malformed event on line {index + 1}") from None
        if not isinstance(event, dict):
            raise ValueError(f"Event {index + 1} is not a JSON object")
        events.append(event)
    return events


def make_handler(runs_dir):
    runs_root = Path(runs_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        def send_payload(self, status, payload, content_type="application/json; charset=utf-8"):
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def send_json(self, status, payload):
            self.send_payload(status, json.dumps(payload, ensure_ascii=False))

        def do_GET(self):
            url = urlsplit(self.path)
            try:
                if url.path in ("/", "/viewer.html"):
                    self.send_payload(200, (APP_DIR / "viewer.html").read_bytes(), "text/html; charset=utf-8")
                elif url.path == "/api/runs":
                    runs = []
                    if runs_root.is_dir():
                        for path in runs_root.rglob("*.jsonl"):
                            resolved = path.resolve()
                            if not resolved.is_relative_to(runs_root) or not resolved.is_file():
                                continue
                            stat = resolved.stat()
                            runs.append({"run_id": path.relative_to(runs_root).as_posix(), "size_bytes": stat.st_size, "modified": stat.st_mtime})
                    self.send_json(200, sorted(runs, key=lambda run: run["modified"], reverse=True))
                elif url.path == "/api/events":
                    query = parse_qs(url.query)
                    values = query.get("run", [])
                    if len(values) != 1 or not values[0]:
                        self.send_json(400, {"error": "Provide a run identifier"})
                        return
                    relative = Path(values[0])
                    path = (runs_root / relative).resolve()
                    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(runs_root) or path.suffix != ".jsonl":
                        self.send_json(403, {"error": "Forbidden path"})
                        return
                    if not path.is_file():
                        self.send_json(404, {"error": "Run not found"})
                        return
                    self.send_json(200, read_events(path))
                elif url.path == "/favicon.ico":
                    self.send_payload(204, b"")
                else:
                    self.send_json(404, {"error": "Page not found"})
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
            except OSError:
                self.send_json(500, {"error": "Cannot read the local file"})

        def do_POST(self):
            self.send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "The viewer is read-only"})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18777)
    parser.add_argument("--runs-dir", type=Path, default=APP_DIR / "runs")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.runs_dir))
    print(f"Swarm viewer: http://127.0.0.1:{server.server_port}  (read-only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
