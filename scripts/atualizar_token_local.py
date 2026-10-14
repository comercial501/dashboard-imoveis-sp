#!/usr/bin/env python3
"""
Atualiza o NONSTOP_TOKEN dos arquivos .env deste Mac (só para testes locais com dados reais; a atualização diária usa o segredo do GitHub).

Uso (no Terminal):  python3 scripts/atualizar_token_local.py
Ele pede o token (cole e aperte Enter — o texto NÃO aparece na tela), confere na nonStop se o token funciona e só então grava.
O token nunca é mostrado, nem escrito em outro lugar além dos arquivos .env abaixo.
"""
import getpass
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ENVS = [AQUI.parent / ".env", Path.home() / "dashboard-imoveis-sp" / ".env", Path.home() / "dashboard-imoveis-sp-cidade" / ".env"]


def main():
    token = getpass.getpass("Cole o token NOVO da nonStop (Configurações → Integrações) e aperte Enter: ").strip().strip('"').strip("'")
    if len(token) < 40 or re.search(r"\s", token):
        sys.exit("Isso não parece um token (muito curto ou com espaços). Nada foi gravado.")
    sys.path.insert(0, str(AQUI))
    import nonstop_client
    try:
        dados = nonstop_client._fetch_page(token, "VENDA", 1)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"A nonStop recusou esse token ({str(e)[:160]}). Nada foi gravado.")
    print(f"A nonStop aceitou o token (catálogo com {dados.get('total')} imóveis à venda).")
    feitos = []
    for p in dict.fromkeys(e.resolve() for e in ENVS if e.exists()):
        linhas = p.read_text(encoding="utf-8").splitlines()
        achou = False
        for i, l in enumerate(linhas):
            if re.match(r"\s*(export\s+)?NONSTOP_TOKEN\s*=", l):
                linhas[i] = f"NONSTOP_TOKEN={token}"
                achou = True
        if not achou:
            linhas.append(f"NONSTOP_TOKEN={token}")
        p.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        feitos.append(str(p))
    print("Gravado em:", *feitos, sep="\n  ")


if __name__ == "__main__":
    main()
