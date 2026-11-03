#!/usr/bin/env python3
"""Local Data Browser server for Career OS.

Stdlib only (http.server + json) - no new dependency. Binds to 127.0.0.1
ONLY: this serves private career data and must never be reachable from
anything but this machine. No auth is implemented because nothing but
localhost can reach it in the first place - don't change the bind host
without adding auth first.

Routes:
  GET  /             static HTML/CSS/JS shell (index.html next to this file)
  GET  /api/data     full export (career_os.services.export.export_all)
  GET  /api/pipeline lightweight pipeline view (career_os.services.pipeline)
  GET  /api/metrics  dashboard metrics with drill-down specs (career_os.services.metrics)
  GET  /api/role/<id> one role's dossier + company (drill-down drawer)
  GET  /static/<dashboard.js|dashboard.css>  fixed allowlist
  POST /api/update   {"text": "..."} -> career_os.services.update.apply_update

Each request opens and closes its own DB connection - no shared connection
across threads, no new concurrency pattern to reason about.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC_ROOT))

from career_os import db  # noqa: E402
from career_os.services import dossier as dossier_svc  # noqa: E402
from career_os.services import export as export_svc  # noqa: E402
from career_os.services import metrics as metrics_svc  # noqa: E402
from career_os.services import actions as actions_svc  # noqa: E402
from career_os.services import pipeline as pipeline_svc  # noqa: E402
from career_os.services import update as update_svc  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
# Only these files are served from /static/: a fixed allowlist, so no path can escape the folder.
STATIC_FILES = {"dashboard.js": "application/javascript; charset=utf-8", "dashboard.css": "text/css; charset=utf-8"}
INDEX_FILE = STATIC_DIR / "index.html"


class DataBrowserHandler(BaseHTTPRequestHandler):
    server_version = "CareerOSDataBrowser/0.1"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - stdlib method name
        if self.path.split("?")[0] in ("/", "/index.html"):
            if not INDEX_FILE.exists():
                self._send_html("<h1>index.html not found</h1>")
                return
            self._send_html(INDEX_FILE.read_text(encoding="utf-8"))
            return

        if self.path == "/api/data":
            conn = db.get_connection()
            try:
                self._send_json(export_svc.export_all(conn))
            finally:
                conn.close()
            return

        if self.path == "/api/actions":
            conn = db.get_connection()
            try:
                self._send_json(actions_svc.compute_actions(conn))
            finally:
                conn.close()
            return

        if self.path == "/api/metrics":
            conn = db.get_connection()
            try:
                self._send_json(metrics_svc.compute_metrics(conn))
            finally:
                conn.close()
            return

        if self.path.startswith("/api/role/"):
            tail = self.path[len("/api/role/"):].split("?")[0]
            if not tail.isdigit():
                self._send_json({"error": "bad_role_id"}, status=400)
                return
            conn = db.get_connection()
            try:
                dossier = dossier_svc.get_role_dossier(conn, int(tail))
                if dossier is None:
                    self._send_json({"error": "not_found"}, status=404)
                    return
                company = conn.execute("SELECT c.name FROM roles r JOIN companies c ON c.id = r.company_id WHERE r.id = ?",
                                       (int(tail),)).fetchone()
                dossier["company"] = company["name"] if company else None
                self._send_json(dossier)
            finally:
                conn.close()
            return

        if self.path.startswith("/static/"):
            name = self.path[len("/static/"):].split("?")[0]
            if name not in STATIC_FILES or not (STATIC_DIR / name).exists():
                self._send_json({"error": "not_found"}, status=404)
                return
            body = (STATIC_DIR / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", STATIC_FILES[name])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/pipeline":
            conn = db.get_connection()
            try:
                self._send_json({"pipeline": pipeline_svc.get_pipeline(conn)})
            finally:
                conn.close()
            return

        self._send_json({"error": "not_found"}, status=404)

    def do_POST(self):  # noqa: N802 - stdlib method name
        if self.path != "/api/update":
            self._send_json({"error": "not_found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid_json"}, status=400)
            return

        text = (body.get("text") or "").strip()
        if not text:
            self._send_json({"error": "empty_text"}, status=400)
            return

        conn = db.get_connection()
        try:
            result = update_svc.apply_update(conn, text)
            self._send_json({"result": result})
        except Exception as exc:  # noqa: BLE001 - never 500 the whole UI on a bad dispatcher path
            self._send_json({"error": str(exc)}, status=500)
        finally:
            conn.close()

    def log_message(self, format, *args):  # noqa: A002 - quiet, stdlib signature
        pass  # keep terminal output clean; errors still surface via response bodies


def serve(port: int = 8765) -> None:
    db.init_db()  # idempotent - make sure the DB exists before serving
    server = ThreadingHTTPServer(("127.0.0.1", port), DataBrowserHandler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Career OS Data Browser running at {url}")
    print("Bound to 127.0.0.1 only - not reachable from other devices. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
        server.shutdown()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    serve(port)
