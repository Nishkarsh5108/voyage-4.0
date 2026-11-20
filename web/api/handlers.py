"""HTTP handlers: the JSON API of web/API.md, server-sent events for runs, and static files from web/static/."""
from __future__ import annotations

import json
import re
import time
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

from . import KLOOK, LISTINGS, NUMBERS, OTA_FILES, STATIC, UserError
from .artefacts import MODELS
from .benches import room_view, rooms_map, tours_relate
from .feeds import MAX_TOTAL_BYTES, UPLOADS, parse_upload
from .jsonutil import dumps
from .pipeline import RUNS, pair_detail, review_queue, save_answer
from .presets import PRESETS, CITY_LABEL, OTA_ID

MAX_BODY = int(MAX_TOTAL_BYTES * 1.5)  # JSON escaping / base64 overhead on top of 40 MB of file content
MIME = {".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".map": "application/json; charset=utf-8", ".geojson": "application/geo+json; charset=utf-8", ".svg": "image/svg+xml",
        ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon", ".csv": "text/csv; charset=utf-8",
        ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8", ".wasm": "application/wasm", ".pdf": "application/pdf",
        ".mp4": "video/mp4", ".webm": "video/webm"}
SSE_KEEPALIVE = 15.0


def status_payload() -> dict:
    out = MODELS.status()
    out["data"] = {"listings": LISTINGS.exists(), "ota": all(p.exists() for p in OTA_FILES.values()), "klook": KLOOK.exists()}
    out["runs"] = RUNS.list()
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "CanonLocal/1.0"
    quiet = False

    # ------------------------------------------------------------------ plumbing
    def log_message(self, fmt, *args):
        if not self.quiet:
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None, head: bool = False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def json(self, obj, status: int = 200):
        self._send(status, dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def error(self, status: int, message: str, fix: str | None = None, detail: str | None = None):
        out = {"error": message}
        if detail:
            out["detail"] = detail
        if fix:
            out["fix"] = fix
        self.json(out, status)

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise UserError(f"The request is {n / 1e6:.1f} MB; uploads are limited to {MAX_TOTAL_BYTES // (1024 * 1024)} MB of files.", status=413)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            raise UserError("The request has no JSON body.")
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise UserError(f"The request body is not valid JSON: {e}.")
        if not isinstance(obj, dict):
            raise UserError("The request body must be a JSON object.")
        return obj

    def _guard(self, fn, *args):
        try:
            fn(*args)
        except UserError as e:
            self.json(e.payload(), e.status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            try:
                self.error(500, f"Internal error: {type(e).__name__}: {e}", detail=traceback.format_exc(limit=3)[-1200:])
            except OSError:
                pass

    # ------------------------------------------------------------------ verbs
    def do_GET(self):
        self._guard(self._get, False)

    def do_HEAD(self):
        self._guard(self._get, True)

    def do_POST(self):
        self._guard(self._post)

    # ------------------------------------------------------------------ GET routes
    def _get(self, head: bool):
        u = urlparse(self.path)
        path, q = unquote(u.path), parse_qs(u.query)
        if path == "/numbers.json":
            if not NUMBERS.exists():
                raise UserError("submission/round1/numbers.json is missing.", status=404,
                                fix=r".venv\Scripts\python.exe -I -X utf8 scripts\figures\round1_figures.py")
            return self._send(200, NUMBERS.read_bytes(), MIME[".json"], head=head)
        if not path.startswith("/api/"):
            return self._static(path, head)
        if path == "/api/status":
            return self.json(status_payload())
        if path == "/api/presets":
            return self.json(PRESETS.summary())
        if path == "/api/runs":
            return self.json(RUNS.list())
        m = re.fullmatch(r"/api/runs/(r\d+)(?:/(.*))?", path)
        if not m:
            raise UserError(f"No API route {path}.", status=404)
        run = RUNS.get(m.group(1))
        rest = m.group(2) or ""
        if rest == "":
            return self.json(run.info())
        if rest == "events":
            return self._events(run)
        if rest == "records":
            G = run.need("G")
            return self.json({"n": len(G), "sources": run.sources, "name": G["name"].tolist(), "kind": G["kind"].tolist(),
                              "src_id": G["src_id"].astype(str).tolist()})
        if rest == "canonical":
            return self.json(run.need("canonical"))
        if rest == "review":
            limit = int((q.get("limit") or ["60"])[0])
            return self.json(review_queue(run, limit))
        mm = re.fullmatch(r"array/([a-z]+)", rest)
        if mm:
            return self._array(run, mm.group(1), head)
        mm = re.fullmatch(r"record/(\d+)", rest)
        if mm:
            return self.json(run.record(int(mm.group(1))))
        mm = re.fullmatch(r"pair/(\d+)", rest)
        if mm:
            return self.json(pair_detail(run, int(mm.group(1))))
        raise UserError(f"No API route {path}.", status=404)

    def _array(self, run, name: str, head: bool):
        from .pipeline import ARRAY_DTYPES
        if name not in ARRAY_DTYPES:
            raise UserError(f"There is no array called {name!r}. Arrays: {', '.join(ARRAY_DTYPES)}.", status=404)
        a = run.arrays.get(name)
        if a is None:
            if run.finished and run.failed:
                raise UserError(f"Run {run.id} failed before the array {name!r} was made.", status=409)
            raise UserError(f"The array {name!r} is not ready yet; its stage has not finished.", status=409)
        a = np.ascontiguousarray(a, dtype=a.dtype.newbyteorder("<"))
        self._send(200, a.tobytes(), "application/octet-stream",
                   {"X-Dtype": np.dtype(a.dtype).name, "X-Length": str(len(a)),
                    "Access-Control-Expose-Headers": "X-Dtype, X-Length"}, head=head)

    def _events(self, run):
        try:
            last = int(self.headers.get("Last-Event-ID", "-1"))
        except ValueError:
            last = -1
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        i = last + 1
        try:
            while True:
                with run.cond:
                    if i >= len(run.events) and not run.finished:
                        run.cond.wait(timeout=SSE_KEEPALIVE)
                    batch = run.events[i:]
                    finished = run.finished
                if batch:
                    chunk = "".join(f"id: {eid}\nevent: {typ}\ndata: {data}\n\n" for eid, typ, data in batch)
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                    i += len(batch)
                elif not finished:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                if finished and i >= len(run.events):
                    # the stream is complete: ask EventSource not to reconnect (it would replay everything) and close
                    self.wfile.write(b"retry: 86400000\n\n")
                    self.wfile.flush()
                    return
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _static(self, path: str, head: bool):
        rel = path.lstrip("/")
        if rel == "" or rel.endswith("/"):
            rel += "index.html"
        root = STATIC.resolve()
        target = (root / rel).resolve()
        if root not in target.parents and target != root:
            raise UserError("Not found.", status=404)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            if not root.exists():
                raise UserError("web/static/ does not exist yet; the API is up but there is no page to serve.", status=404)
            raise UserError(f"Not found: {path}", status=404)
        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype, head=head)

    # ------------------------------------------------------------------ POST routes
    def _post(self):
        path = urlparse(self.path).path
        if path == "/api/uploads":
            body = self.body()
            frame, report, ok = parse_upload(body.get("files"))
            if not ok:
                return self.json({"ok": False, "report": report})
            uid = UPLOADS.add(frame, report)
            return self.json({"ok": True, "upload_id": uid, "report": report})
        if path == "/api/runs":
            body = self.body()
            MODELS.require()
            if body.get("preset"):
                preset = str(body["preset"])
                if preset != OTA_ID and preset not in CITY_LABEL:
                    raise UserError(f"There is no preset called {preset!r}.", status=404)
                label = "Goibibo × MakeMyTrip" if preset == OTA_ID else CITY_LABEL[preset]
                run = RUNS.start({"preset": preset}, lambda: PRESETS.ingest(preset), label)
            elif body.get("upload_id"):
                uid = str(body["upload_id"])
                frame, report = UPLOADS.get(uid)

                def make(frame=frame, uid=uid):
                    from .presets import Ingest
                    return Ingest(frame.copy(), "grp", list(dict.fromkeys(frame["source"])), f"upload {uid}", upload_id=uid, kind="upload")

                run = RUNS.start({"upload_id": uid}, make, f"upload {uid}")
            else:
                raise UserError("Send {\"preset\": \"dubai\"} or {\"upload_id\": \"u1\"}.")
            return self.json({"run_id": run.id})
        if path == "/api/review":
            body = self.body()
            run = RUNS.get(str(body.get("run_id")))
            try:
                k = int(body.get("k"))
            except (TypeError, ValueError):
                raise UserError("k must be a candidate index (an integer).")
            return self.json(save_answer(run, k, str(body.get("decision"))))
        if path == "/api/rooms/parse":
            return self.json(room_view(self.body().get("text")))
        if path == "/api/rooms/map":
            body = self.body()
            return self.json(rooms_map(body.get("a"), body.get("b")))
        if path == "/api/tours/relate":
            body = self.body()
            return self.json(tours_relate(body.get("a"), body.get("b"), body.get("city")))
        raise UserError(f"No API route POST {path}.", status=404)


def warm_up() -> None:
    """Load what the first requests need, in the background: preset counts, model files."""
    t = time.time()
    try:
        PRESETS.summary()
        if not MODELS.missing():
            MODELS.art()
            MODELS.booster("final")
        print(f"[canon] warm-up done in {time.time() - t:.1f}s", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[canon] warm-up: {e}", flush=True)

