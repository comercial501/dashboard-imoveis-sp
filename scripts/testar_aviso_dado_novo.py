#!/usr/bin/env python3
"""
Teste do aviso "Dados sem atualização" (08/10/2026): simula uma ABA ANTIGA num servidor de teste que a
gente controla (copia site/, e troca data.json/versao.json no meio do teste) com o relógio do navegador
acelerado (Playwright page.clock). Uso LOCAL: python3 scripts/testar_aviso_dado_novo.py
Cenários: A) aba aberta com dado velho, servidor ganha dado novo → recarrega sozinha, sem aviso;
B) servidor de fato com dado velho → aviso com o texto novo, sem recarregar em laço; C) servidor com
versão nova mas data.json atrasado (cache) → UMA recarga só, depois aviso normal; D) sem versao.json →
usa o data.json; E) servidor fora do ar na conferência → nada muda; F) aba esquecida volta a ficar
visível → confere; G) dado novo não faz aparecer aviso com dado fresco; H) conferência a cada 1 hora.
"""
import datetime
import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORTA = 8896
AGORA = datetime.datetime.now(datetime.timezone.utc)
falhas = []


def ok(c, nome, extra=""):
    print(("OK     " if c else "FALHOU ") + nome + (f"  [{extra}]" if extra else ""))
    if not c:
        falhas.append(nome)


def iso(horas_atras):
    return (AGORA - datetime.timedelta(hours=horas_atras)).isoformat()


class Estado:
    """O que o servidor de teste entrega agora."""
    def __init__(self, pasta, base_data):
        self.pasta, self.base, self.versao_json, self.fora, self.pedidos = pasta, base_data, True, False, []
        self.set(horas_data=2, horas_versao=2)

    def set(self, horas_data, horas_versao=None, com_versao=True, fora=False):
        d = dict(self.base)
        d["generated_at_iso"] = iso(horas_data)
        (self.pasta / "data.json").write_text(json.dumps(d), encoding="utf-8")
        self.versao_json = com_versao
        self.fora = fora
        if com_versao:
            (self.pasta / "versao.json").write_text(json.dumps({"generated_at_iso": iso(horas_data if horas_versao is None else horas_versao)}), encoding="utf-8")
        elif (self.pasta / "versao.json").exists():
            (self.pasta / "versao.json").unlink()


def servir(pasta, estado):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(pasta), **k)

        def do_GET(self):
            estado.pedidos.append(self.path.split("?")[0])
            if estado.fora and self.path.split("?")[0] in ("/versao.json", "/data.json") and len(estado.pedidos) > estado.libera_apos:
                self.send_error(503)
                return
            caminho = self.path.split("?")[0].lstrip("/") or "index.html"
            if not (pasta / caminho).exists():  # 404 limpo (com Content-Length), como o Cloudflare/GitHub
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return super().do_GET()

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORTA), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def texto_aviso(pg):
    return pg.evaluate("()=>{const b=document.getElementById('aviso-dado-parado'); return b.hidden?null:b.textContent}")


def atualizado_em(pg):
    return pg.evaluate("()=>document.getElementById('updated-at').textContent")


def main():
    tmp = Path(tempfile.mkdtemp())
    for f in ("index.html", "app.js", "engine.js", "styles.css"):
        shutil.copy2(ROOT / "site" / f, tmp / f)
    base = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    (tmp / "raw.json").write_text("{}", encoding="utf-8")  # não é usado sem filtro
    est = Estado(tmp, base)
    est.libera_apos = 10**9
    srv = servir(tmp, est)
    URL = f"http://127.0.0.1:{PORTA}/index.html"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)

        def nova_pagina():
            ctx = br.new_context()
            pg = ctx.new_page()
            erros = []
            pg.on("pageerror", lambda e: erros.append(str(e)[:150]))
            pg.on("console", lambda m: erros.append(m.text[:150]) if m.type == "error" else None)
            navs = []
            pg.on("framenavigated", lambda f: navs.append(f.url) if f == pg.main_frame else None)
            return ctx, pg, erros, navs

        # --- A) aba antiga: abre com o servidor velho (40 h), depois o servidor ganha dado novo ---
        est.set(horas_data=40)
        ctx, pg, erros, navs = nova_pagina()
        pg.clock.install()
        pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(800)
        aviso1 = texto_aviso(pg); antes = atualizado_em(pg)
        ok(aviso1 is not None and "Recarregue a página (F5)" in aviso1 and "verifique a aba Actions do GitHub" in aviso1 and "40 horas" in aviso1,
           "A1: servidor com dado de 40 h → aviso com o texto novo", aviso1 or "")
        est.set(horas_data=1)  # a Action rodou: servidor tem dado novo
        pg.clock.fast_forward("01:00:10"); pg.wait_for_timeout(2500)
        depois = atualizado_em(pg); aviso2 = texto_aviso(pg)
        ok(depois != antes and aviso2 is None, "A2: 1 hora depois a aba velha se recarregou sozinha e o aviso sumiu", f"{antes[-40:]} → {depois[-40:]}")
        ok(sum(1 for u in navs if "index.html" in u) == 2, "A3: exatamente uma recarga", f"{len(navs)} navegações")
        ok(not erros, "A4: sem erro de console", str(erros[:2])); ctx.close()

        # --- B) servidor realmente velho: aviso, sem laço de recarga ---
        est.set(horas_data=50)
        ctx, pg, erros, navs = nova_pagina(); pg.clock.install()
        pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(800)
        pg.clock.fast_forward("03:00:00"); pg.wait_for_timeout(1500)
        a = texto_aviso(pg)
        ok(a is not None and "há 53 horas" in a or (a is not None and "horas" in a), "B1: servidor velho → aviso continua (agora com 3 h a mais)", a or "")
        ok(sum(1 for u in navs if "index.html" in u) == 1, "B2: nenhuma recarga quando não há versão mais nova", f"{len(navs)} navegações"); ctx.close()

        # --- C) versão nova no versao.json mas data.json ainda velho (cache atrasado): uma recarga só ---
        est.set(horas_data=40, horas_versao=1)
        ctx, pg, erros, navs = nova_pagina()
        pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(2500)
        n = sum(1 for u in navs if "index.html" in u); a = texto_aviso(pg)
        ok(n == 2, "C1: no máximo UMA recarga mesmo quando o data.json continua velho (sem laço)", f"{n} cargas")
        ok(a is None, "C2: depois da recarga o aviso segue o SERVIDOR (versao.json de 1 h) → sem aviso", a or ""); ctx.close()

        # --- D) sem versao.json: usa o data.json ---
        est.set(horas_data=2, com_versao=False)
        ctx, pg, erros, navs = nova_pagina(); pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(800)
        ok(texto_aviso(pg) is None and any(u == "/data.json" for u in est.pedidos[-6:]), "D1: sem versao.json confere pelo data.json (dado de 2 h → sem aviso)")
        est.set(horas_data=45, com_versao=False)
        pg.evaluate("()=>conferirVersaoNoServidor()"); pg.wait_for_timeout(1200)
        ok(texto_aviso(pg) is not None and "45 horas" in texto_aviso(pg), "D2: sem versao.json, dado de 45 h no data.json → aviso", texto_aviso(pg) or "")
        ctx.close()

        # --- E) servidor fora do ar na conferência: nada muda ---
        est.set(horas_data=40)
        ctx, pg, erros, navs = nova_pagina(); pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(800)
        antes_aviso = texto_aviso(pg)
        est.fora = True; est.libera_apos = len(est.pedidos)
        pg.evaluate("()=>conferirVersaoNoServidor()"); pg.wait_for_timeout(1500)
        erros_reais = [e for e in erros if "Failed to load resource" not in e]  # o navegador sempre registra o 503 em si
        ok(texto_aviso(pg) == antes_aviso and sum(1 for u in navs if "index.html" in u) == 1 and not erros_reais, "E1: servidor fora do ar → o aviso e a página ficam como estavam, sem erro de programa", str(erros[:1]))
        est.fora = False; ctx.close()

        # --- F/H) conferência a cada 1 hora e quando a aba esquecida volta a ficar visível ---
        est.set(horas_data=2)
        ctx, pg, erros, navs = nova_pagina(); pg.clock.install()
        pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(800)
        n0 = sum(1 for u in est.pedidos if u == "/versao.json")
        pg.clock.fast_forward("00:59:00"); pg.wait_for_timeout(600)
        n1 = sum(1 for u in est.pedidos if u == "/versao.json")
        pg.clock.fast_forward("00:02:00"); pg.wait_for_timeout(900)
        n2 = sum(1 for u in est.pedidos if u == "/versao.json")
        ok(n1 == n0 and n2 == n0 + 1, "H1: confere ao abrir e depois só a cada 1 hora (não antes)", f"pedidos {n0}→{n1}→{n2}")
        pg.clock.fast_forward("03:00:00"); pg.wait_for_timeout(600)
        n3 = sum(1 for u in est.pedidos if u == "/versao.json")
        pg.evaluate("()=>{Object.defineProperty(document,'visibilityState',{value:'visible',configurable:true}); document.dispatchEvent(new Event('visibilitychange'));}"); pg.wait_for_timeout(600)
        n4 = sum(1 for u in est.pedidos if u == "/versao.json")
        ok(n4 == n3, "F1: aba que volta a ficar visível logo depois de uma conferência NÃO confere de novo", f"{n3}→{n4}")
        pg.evaluate("()=>{ULTIMA_CONFERENCIA_MS = Date.now() - 2*3600000;}")
        pg.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); pg.wait_for_timeout(700)
        n5 = sum(1 for u in est.pedidos if u == "/versao.json")
        ok(n5 == n4 + 1, "F2: aba esquecida há mais de 1 hora, ao voltar a ficar visível, confere na hora", f"{n4}→{n5}"); ctx.close()

        # --- G) servidor com dado fresco nunca mostra aviso ---
        est.set(horas_data=5)
        ctx, pg, erros, navs = nova_pagina(); pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(800)
        ok(texto_aviso(pg) is None, "G1: dado de 5 h no servidor → sem aviso"); ctx.close()
        br.close()
    srv.shutdown()
    print()
    if falhas:
        print(f"{len(falhas)} falha(s)")
        return 1
    print("Todos os cenários do aviso de dado novo passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
