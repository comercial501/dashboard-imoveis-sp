#!/usr/bin/env python3
"""
Testa, SEM LOGIN, os endereços do dashboard na Cloudflare: nenhum arquivo de dados
pode ser entregue. Para cada endereço e cada caminho, o resultado só passa se NÃO
for 200 (redirecionar pro login da Cloudflare, 401, 403, 404 ou 503 valem) e se a
resposta não trouxer pedaço de dado nenhum.

Uso:
  python3 scripts/testar_acesso_anonimo.py https://torre-topio.pages.dev https://abc123.torre-topio.pages.dev ...
Inclua o endereço principal e o endereço único da publicação (o passo "Publicar" mostra
os dois: "Take a peek over at https://<hash>.<projeto>.pages.dev"), mais o endereço
de prévia da branch (https://main.<projeto>.pages.dev) se existir.
Sai com código != 0 se qualquer endereço entregar conteúdo sem login.
"""
import sys
import urllib.error
import urllib.request

CAMINHOS = ["/", "/index.html", "/data.json", "/raw.json", "/versao.json", "/app.js", "/engine.js", "/styles.css",
            "/itbi_clean_log.json", "/historico/anuncios.jsonl", "/output/preco_m2_por_bairro.csv",
            "/output/shortlist_google_ads.csv", "/output/valor_pago_por_bairro.csv", "/_headers",
            "/functions/_middleware.js", "/serve_no_cache.py", "/README.md", "/.env"]
SINAIS_DE_DADO = ['"bairros"', "Torre de Controle", "codigo", '"itbi"', "Bairro,"]


class SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def pedir(url):
    abrir = urllib.request.build_opener(SemRedirecionar).open
    req = urllib.request.Request(url, headers={"User-Agent": "teste-acesso-anonimo"})
    try:
        r = abrir(req, timeout=30)
        return r.status, dict(r.headers), r.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), (e.read(4096).decode("utf-8", "replace") if e.fp else "")


def main(bases):
    falhas = 0
    for base in bases:
        base = base.rstrip("/")
        for c in CAMINHOS:
            status, cab, corpo = pedir(base + c)
            destino = cab.get("Location") or cab.get("location") or ""
            if status == 200:
                resultado, ok = "ENTREGOU CONTEÚDO SEM LOGIN", False
            elif status in (301, 302, 303, 307, 308):
                # só vale se for pro login da Cloudflare
                ok = "cloudflareaccess.com" in destino
                resultado = f"redireciona pro login ({destino[:60]}…)" if ok else f"redireciona pra {destino[:80]} (não é o login!)"
            else:
                ok, resultado = True, f"bloqueado ({status})"
            if ok and any(s in corpo for s in SINAIS_DE_DADO) and status < 300:
                ok, resultado = False, "resposta com cara de dado"
            print(("OK     " if ok else "FALHOU ") + f"{base}{c} → {resultado}")
            falhas += not ok
    print()
    if falhas:
        print(f"{falhas} caminho(s) acessível(is) sem login — NÃO use esse endereço até corrigir.")
        return 1
    print("Nenhum arquivo acessível sem login nos endereços testados.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
