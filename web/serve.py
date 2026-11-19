"""Local Canon site: static pages from web/static/ plus the JSON API described in web/API.md.

Usage : .venv\\Scripts\\python.exe -X utf8 web\\serve.py [--port 8765]
Binds 127.0.0.1 only: uploaded feeds never leave this machine. Stop with Ctrl+C.
"""
import argparse
import socket
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canon_web.handlers import Handler, status_payload, warm_up  # noqa: E402


class Server(ThreadingHTTPServer):
    """Refuses a port another program already listens on. (On Windows, SO_REUSEADDR, which http.server sets by default,
    would let two servers share a port silently and split the requests between them.)"""
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    ap = argparse.ArgumentParser(description="Serve the Canon site and API on 127.0.0.1.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--quiet", action="store_true", help="do not log every request")
    args = ap.parse_args()
    Handler.quiet = args.quiet
    try:
        httpd = Server(("127.0.0.1", args.port), Handler)
    except OSError as e:
        raise SystemExit(f"Port {args.port} is busy ({e}). Try: .venv\\Scripts\\python.exe -X utf8 web\\serve.py --port {args.port + 1}")
    st = status_payload()
    if not st["model"]["ready"]:
        print(f"[canon] the trained matcher is missing ({', '.join(st['model']['missing'])}); runs will fail until you run:\n        {st['model']['rebuild']}")
    if not st["loco"]["ready"]:
        print(f"[canon] leave-one-city-out boosters missing for some cities; labelled pairs will be scored by the final model. Rebuild:\n        {st['loco']['rebuild']}")
    threading.Thread(target=warm_up, daemon=True, name="warm-up").start()
    print(f"Canon is running at http://127.0.0.1:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
