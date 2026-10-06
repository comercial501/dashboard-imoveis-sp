#!/usr/bin/env python3
"""
Monta a pasta que vai pra Cloudflare Pages (cloudflare-dist/) — só o que o
dashboard precisa para abrir: a página, o código e os dois arquivos de dados
que ele carrega (data.json e raw.json), mais o _headers. Nada de CSV, histórico
de anúncios, log de limpeza nem o servidor local. Confere que os arquivos
existem e que cada um cabe no limite do Pages (25 MiB).

Uso: python3 scripts/preparar_pasta_cloudflare.py [pasta_de_saida]
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLICOS = ["index.html", "app.js", "engine.js", "styles.css", "data.json", "raw.json"]
LIMITE_PAGES = 25 * 1024 * 1024
AVISO_PAGES = 20 * 1024 * 1024  # avisa antes de chegar no limite


def montar(saida):
    saida = Path(saida)
    if saida.exists():
        shutil.rmtree(saida)
    saida.mkdir(parents=True)
    for nome in PUBLICOS:
        origem = ROOT / "site" / nome
        if not origem.exists():
            raise SystemExit(f"falta site/{nome} — rode o build antes.")
        tam = origem.stat().st_size
        if tam > LIMITE_PAGES:
            raise SystemExit(f"site/{nome} tem {tam / 1048576:.1f} MiB, acima do limite de 25 MiB por arquivo do Cloudflare Pages.")
        if tam > AVISO_PAGES:
            print(f"AVISO: site/{nome} já tem {tam / 1048576:.1f} MiB (limite do Pages: 25 MiB).")
        shutil.copy2(origem, saida / nome)
    shutil.copy2(ROOT / "cloudflare" / "_headers", saida / "_headers")
    total = sum(p.stat().st_size for p in saida.iterdir())
    print(f"{saida}: {len(list(saida.iterdir()))} arquivos, {total / 1048576:.1f} MiB — {sorted(p.name for p in saida.iterdir())}")


if __name__ == "__main__":
    montar(sys.argv[1] if len(sys.argv) > 1 else ROOT / "cloudflare-dist")
