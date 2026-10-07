#!/usr/bin/env python3
"""Teste da limpeza de publicações da Cloudflare com uma API falsa local (sem rede, sem conta)."""
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
pubs = [{"id": f"{i:08d}-aaaa", "created_on": f"2026-10-{i:02d}T11:00:00Z", "environment": "production", "url": f"https://{i:08d}.p.pages.dev"} for i in range(1, 13)]
apagadas, estado = [], {"prod": "00000012-aaaa"}


class Falsa(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/accounts/c1/pages/projects/p/deployments"):
            pg = int(self.path.split("page=")[-1]); lote = pubs[(pg - 1) * 25:pg * 25]
            return self._json({"result": lote, "result_info": {"total_pages": 1}})
        if self.path == "/accounts/c1/pages/projects/p":
            return self._json({"result": {"canonical_deployment": {"id": estado["prod"]}}})
        self._json({}, 404)

    def do_DELETE(self):
        apagadas.append(self.path.split("/deployments/")[1].split("?")[0]); self._json({"success": True})

    def log_message(self, *a): pass


srv = http.server.HTTPServer(("127.0.0.1", 8811), Falsa); threading.Thread(target=srv.serve_forever, daemon=True).start()
env = {**os.environ, "CLOUDFLARE_API_BASE": "http://127.0.0.1:8811", "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "c1", "CLOUDFLARE_PAGES_PROJECT": "p"}
falhas = []


def ok(c, n):
    print(("OK   " if c else "FALHOU ") + n)
    if not c: falhas.append(n)


def rodar(*args, e=env):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "limpar_publicacoes_cloudflare.py"), *args], capture_output=True, text=True, env=e)


r = rodar()
ok(r.returncode == 0 and not apagadas and "Apagaria 7" in r.stdout and "Mantendo 5" in r.stdout, "padrão só lista: nada é apagado (mantém 5, apagaria 7)")
r = rodar("--apagar")
esperadas = {f"{i:08d}-aaaa" for i in range(1, 8)}
ok(set(apagadas) == esperadas, "--apagar remove só as 7 mais antigas")
ok("00000012-aaaa" not in apagadas and "00000008-aaaa" not in apagadas, "as 5 mais recentes ficam")
apagadas.clear(); estado["prod"] = "00000003-aaaa"  # produção é uma antiga: nunca apaga
r = rodar("--apagar")
ok("00000003-aaaa" not in apagadas and len(apagadas) == 6 and "EM PRODUÇÃO" in r.stdout, "a publicação em produção nunca é apagada, mesmo velha")
apagadas.clear(); estado["prod"] = None
r = rodar("--apagar")
ok(r.returncode != 0 and not apagadas, "sem identificar a produção: não apaga nada")
estado["prod"] = "00000012-aaaa"
r = rodar("--manter", "1", "--apagar")
ok(r.returncode != 0 and not apagadas, "--manter menor que 2 é recusado")
r = rodar(e={k: v for k, v in env.items() if k != "CLOUDFLARE_API_TOKEN"})
ok(r.returncode != 0 and not apagadas, "sem as variáveis de acesso: não faz nada")
srv.shutdown()
print(); print("Todos os testes da limpeza passaram." if not falhas else f"{len(falhas)} falha(s)")
sys.exit(1 if falhas else 0)
