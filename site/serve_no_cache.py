#!/usr/bin/env python3
"""Servidor estático local pra dashboard, igual ao `python3 -m http.server`,
só que manda Cache-Control: no-store — sem isso, o navegador guarda em cache
o data.json/raw.json antigo e a dashboard parece "não atualizar" mesmo
depois do pipeline diário rodar (só resolvia com hard refresh manual)."""
import http.server
import os
import sys

DEFAULT_PORT = 8731


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    with http.server.ThreadingHTTPServer(("", port), NoCacheHandler) as httpd:
        print(f"Servindo em http://localhost:{port} (sem cache)")
        httpd.serve_forever()
