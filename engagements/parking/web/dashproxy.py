#!/usr/bin/env python3
"""Tiny Basic-auth reverse proxy so the internal dashboard opens in a browser.

    python3 dashproxy.py     # http://127.0.0.1:8793
"""
import base64, ssl, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UP = "https://internal.lpr.alfabeta.co.id"
AUTH = "Basic " + base64.b64encode(b"alfabeta:Alfabeta43B!").decode()
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
HOP = {"host", "authorization", "accept-encoding", "connection", "transfer-encoding"}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _go(self, method):
        body = None
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            body = self.rfile.read(n)
        up = "http://52.74.58.117:9110" + self.path[5:] if self.path.startswith("/apip") else UP + self.path
        req = urllib.request.Request(up, data=body, method=method)
        for k, v in self.headers.items():
            if k.lower() not in HOP:
                req.add_header(k, v)
        req.add_header("Authorization", AUTH)
        try:
            with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
                data = r.read()
                self.send_response(r.status)
                for k, v in r.headers.items():
                    if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            msg = str(e).encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self):
        self._go("GET")

    def do_POST(self):
        self._go("POST")


if __name__ == "__main__":
    print("dashboard proxy on :8793", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8793), H).serve_forever()
