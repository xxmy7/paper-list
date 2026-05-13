"""Local HTTP server that serves the static pages and exposes a /save-favorites
POST endpoint for writing favorites.js directly from the browser.

Workflow:

  python scripts/serve.py             # default http://localhost:8000
  python scripts/serve.py --port 8888

Then open http://localhost:8000/ (NOT file://) and use the browsers as
usual. Clicking the in-page "★ Save" button POSTs the current localStorage
state to /save-favorites which overwrites the committed favorites.js. Then
git add + commit + push as usual.

Binds to localhost only — not reachable from other machines on the LAN.
"""
from __future__ import annotations
import argparse
import http.server
import os
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAV_PATH = ROOT / "favorites.js"


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path != "/save-favorites":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 5_000_000:  # 5MB sanity cap
                self.send_error(413, "Body missing or too large")
                return
            body = self.rfile.read(length).decode("utf-8")
            # Crude shape check so we don't accidentally write garbage.
            if "FAVORITES_SYNCED" not in body:
                self.send_error(400, "Body does not look like a favorites.js file")
                return
            FAV_PATH.write_text(body, encoding="utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"OK")
            print(f"saved {FAV_PATH} ({length} bytes)")
        except Exception as e:
            self.send_error(500, str(e))

    def do_OPTIONS(self):  # noqa: N802
        # Preflight (in case of cross-origin POST). Not strictly needed
        # for same-origin localhost requests, but harmless.
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def end_headers(self):
        # Discourage caching while developing so a rebuild is visible
        # immediately on refresh.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Keep the console quiet — only print on POSTs (above).
        if args and isinstance(args[0], str) and args[0].startswith("POST"):
            super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind host. Default 127.0.0.1 (localhost only). Use 0.0.0.0 to expose to LAN.")
    args = ap.parse_args()

    os.chdir(ROOT)
    with socketserver.TCPServer((args.host, args.port), Handler) as httpd:
        url = f"http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}"
        print(f"serving {ROOT}")
        print(f"  index    {url}/")
        print(f"  ICML     {url}/browsers/icml2026.html")
        print(f"  KDD      {url}/browsers/kdd2026.html")
        print(f"  WWW      {url}/browsers/www2026.html")
        print(f"  ★ All    {url}/browsers/favorites.html")
        print("Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    main()
