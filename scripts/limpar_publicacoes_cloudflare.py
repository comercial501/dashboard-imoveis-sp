#!/usr/bin/env python3
"""
Limpeza das publicações antigas do dashboard na Cloudflare Pages.

Cada envio cria uma publicação com endereço próprio (https://<código>.<projeto>.pages.dev)
e a Cloudflare não apaga as antigas sozinha. Este script mantém só as N mais recentes
(padrão 5) e NUNCA apaga a que está no ar em produção.

POR PADRÃO SÓ LISTA (não apaga nada). Para apagar de verdade: --apagar.
Variáveis de ambiente (as mesmas dos segredos do GitHub):
  CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_PAGES_PROJECT
Uso:
  python3 scripts/limpar_publicacoes_cloudflare.py              # só mostra o que apagaria
  python3 scripts/limpar_publicacoes_cloudflare.py --manter 5 --apagar
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("CLOUDFLARE_API_BASE", "https://api.cloudflare.com/client/v4")


def _api(metodo, caminho, token):
    req = urllib.request.Request(BASE + caminho, method=metodo, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"Cloudflare respondeu {e.code} em {metodo} {caminho}: {corpo}")


def listar_publicacoes(conta, projeto, token):
    """Todas as publicações (produção e prévia), paginadas."""
    todas, pagina = [], 1
    while True:
        r = _api("GET", f"/accounts/{conta}/pages/projects/{projeto}/deployments?per_page=25&page={pagina}", token)
        todas.extend(r.get("result") or [])
        info = r.get("result_info") or {}
        if pagina >= (info.get("total_pages") or 1):
            return todas
        pagina += 1


def escolher_para_apagar(publicacoes, manter, id_em_producao):
    """Mais recentes primeiro; mantém as `manter` primeiras e a que está em produção.
    Retorna (a_manter, a_apagar)."""
    ordenadas = sorted(publicacoes, key=lambda d: d["created_on"], reverse=True)
    a_manter = ordenadas[:manter]
    ids = {d["id"] for d in a_manter}
    resto = [d for d in ordenadas[manter:]]
    extras = [d for d in resto if d["id"] == id_em_producao]  # nunca apaga a de produção
    a_manter = a_manter + extras
    a_apagar = [d for d in resto if d["id"] != id_em_producao]
    return a_manter, a_apagar


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manter", type=int, default=5, help="quantas publicações mais recentes manter (padrão 5)")
    ap.add_argument("--apagar", action="store_true", help="apaga de verdade (sem isso, só lista)")
    args = ap.parse_args()
    if args.manter < 2:
        sys.exit("--manter precisa ser pelo menos 2 (sempre sobra a atual e uma de reserva).")
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    conta = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    projeto = os.environ.get("CLOUDFLARE_PAGES_PROJECT", "")
    if not (token and conta and projeto):
        sys.exit("Faltam CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID ou CLOUDFLARE_PAGES_PROJECT.")

    proj = _api("GET", f"/accounts/{conta}/pages/projects/{projeto}", token).get("result") or {}
    id_prod = (proj.get("canonical_deployment") or {}).get("id")
    if not id_prod:
        sys.exit("Não consegui identificar a publicação que está em produção — não vou apagar nada.")
    pubs = listar_publicacoes(conta, projeto, token)
    manter, apagar = escolher_para_apagar(pubs, args.manter, id_prod)
    print(f"{len(pubs)} publicações no projeto '{projeto}'; produção atual: {id_prod[:8]}")
    print(f"Mantendo {len(manter)}:")
    for d in manter:
        print(f"  = {d['id'][:8]}  {d['created_on'][:19]}  {d.get('environment')}  {d.get('url')}" + ("  <- EM PRODUÇÃO" if d["id"] == id_prod else ""))
    print(f"{'Apagando' if args.apagar else 'Apagaria'} {len(apagar)}:")
    for d in apagar:
        print(f"  - {d['id'][:8]}  {d['created_on'][:19]}  {d.get('environment')}  {d.get('url')}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # Anotação do GitHub: aparece no resumo da execução (e na API pública de anotações).
        resumo = (f"Limpeza das publicações da Cloudflare ({'APAGANDO' if args.apagar else 'SÓ LISTANDO'}): {len(pubs)} no projeto, "
                  f"produção atual {id_prod[:8]}. Mantém {len(manter)}: "
                  + "; ".join(f"{d['id'][:8]} ({d['created_on'][:10]})" + (" EM PRODUÇÃO" if d["id"] == id_prod else "") for d in manter)
                  + f". {'Apaga' if args.apagar else 'Apagaria'} {len(apagar)}: "
                  + ("; ".join(f"{d['id'][:8]} ({d['created_on'][:10]})" for d in apagar) or "nenhuma")
                  + f". Produção na lista de apagar: {'SIM (ERRO)' if any(d['id'] == id_prod for d in apagar) else 'não'}.")
        print("::notice title=Limpeza de publicações da Cloudflare::" + resumo.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"))
    if not args.apagar:
        print("\n(Só listei. Para apagar de verdade, rode de novo com --apagar.)")
        return 0
    for d in apagar:
        _api("DELETE", f"/accounts/{conta}/pages/projects/{projeto}/deployments/{d['id']}?force=true", token)
        print(f"  apagada {d['id'][:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
