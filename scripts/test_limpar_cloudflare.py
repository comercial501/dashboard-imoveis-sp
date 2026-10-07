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
# --- publicar_cloudflare.sh inteiro, com npx falso: a limpeza NUNCA derruba o deploy ---
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    npx = Path(tmp) / "npx"
    npx.write_text("#!/bin/bash\necho \"npx falso: $@\"\nexit 0\n"); npx.chmod(0o755)
    estado["prod"] = "00000012-aaaa"; apagadas.clear()
    e2 = {**env, "PATH": f"{tmp}:{os.environ['PATH']}", "GITHUB_ACTIONS": "true"}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "publicar_cloudflare.sh")], capture_output=True, text=True, env={**e2, "LIMPAR_APAGAR": "0"}, cwd=ROOT)
    ok(r.returncode == 0 and "pages deploy" in r.stdout and "Apagaria 7" in r.stdout and not apagadas, "LIMPAR_APAGAR=0: deploy + limpeza só listando (nada apagado)")
    ok("::notice title=Limpeza de publicações da Cloudflare::" in r.stdout and "Produção na lista de apagar: não" in r.stdout, "etapa 1: resumo vira anotação do GitHub e confirma que a produção não está na lista")
    r = subprocess.run(["bash", str(ROOT / "scripts" / "publicar_cloudflare.sh")], capture_output=True, text=True, env=e2, cwd=ROOT)
    ok(r.returncode == 0 and set(apagadas) == esperadas and "APAGANDO" in r.stdout, "etapa 2 (padrão do script agora): apaga só as 7 antigas e a produção fica")
    ok("00000012-aaaa" not in apagadas and "Produção na lista de apagar: não" in r.stdout, "etapa 2: a publicação de produção não é apagada")
    apagadas.clear()
    apagadas.clear(); estado["prod"] = None  # API "quebrada" pra limpeza: deploy tem que seguir de pé
    r = subprocess.run(["bash", str(ROOT / "scripts" / "publicar_cloudflare.sh")], capture_output=True, text=True, env=e2, cwd=ROOT)
    ok(r.returncode == 0 and "::warning::A limpeza" in r.stdout and not apagadas, "limpeza que falha NÃO derruba o deploy (só registra o aviso) e não apaga nada")
srv.shutdown()
print(); print("Todos os testes da limpeza passaram." if not falhas else f"{len(falhas)} falha(s)")
sys.exit(1 if falhas else 0)
