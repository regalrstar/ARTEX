#!/usr/bin/env python3
"""Proxy cctv-dishub through a pinned IP (Mullvad DNS fails the name)."""
import ssl, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IP, HOST, PORT = "157.20.252.204", "cctv-dishub.tangerangkab.go.id", 8795
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path[4:] if self.path.startswith("/svc") else self.path
        url = f"https://{IP}{path}"
        req = urllib.request.Request(url, headers={"Host": HOST})
        try:
            with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
                data = r.read()
                self.send_response(r.status)
                self.send_header("Content-Type", r.headers.get("Content-Type", "application/octet-stream"))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            msg = str(e).encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


if __name__ == "__main__":
    print("cctv proxy on :8795", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
