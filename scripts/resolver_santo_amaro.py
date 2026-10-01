#!/usr/bin/env python3
"""
Item 3, ponto 4 (2026-09-30): aplica a divisão de "Santo Amaro" que o
usuário preencheu em santo_amaro_ceps_preenchido.csv (cópia em
data/iptu_geosampa/raw/, gitignorada — nunca editar esse arquivo aqui).

Regras do usuário:
  1. bairro_mercado da linha = destino final por prefixo de CEP (5
     dígitos). "FORA" = fora da carteira. "Santo Amaro" = só o centro que
     sobrou depois da divisão.
  2. status=VALIDAR_ANUNCIOS (9 prefixos): o bairro_mercado é provisório —
     conferir os anúncios nonStop desse prefixo. 3+ anúncios E 60%+ deles
     num mesmo bairro (dos 77) -> usa esse nome. Senão, mantém o
     provisório.
  3. Prefixo que não aparece no arquivo -> FORA.

Gera scripts/santo_amaro_split_resolvido.csv (committed — é o artefato
final, pequeno e auditável; a fonte com 452 linhas do usuário fica só em
data/, gitignorada) com 2 colunas: cep_prefixo, bairro_mercado_final.
Usado por tradutor_bairro.carregar_split_santo_amaro().
"""
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SRC = Path(__file__).resolve().parent.parent / "data" / "iptu_geosampa" / "raw" / "santo_amaro_ceps_preenchido.csv"
OUT = Path(__file__).resolve().parent / "santo_amaro_split_resolvido.csv"

LIMIAR_PCT = 0.60
MIN_ANUNCIOS = 3


def validar_por_anuncios(prefixos):
    """{prefixo: (bairro_vencedor_ou_None, n_anuncios, detalhe)} — conta
    anúncios nonStop (VENDA, qualquer status) cujo CEP cai em cada
    prefixo, por bairro_canon(address.area) (um dos 77, via normalize
    atualizado nesta auditoria)."""
    from nonstop_client import fetch_all_properties
    from normalize import bairro_canon

    token = os.environ.get("NONSTOP_TOKEN", "").strip()
    if not token:
        raise SystemExit("Defina NONSTOP_TOKEN no ambiente (.env) para validar os anúncios.")

    props = fetch_all_properties(token, "VENDA")
    by_prefix = {p: [] for p in prefixos}
    for card in props:
        addr = card.get("address") or {}
        digits = re.sub(r"\D", "", addr.get("zipcode") or "")
        if len(digits) < 5:
            continue
        pref = digits[:5]
        if pref in by_prefix:
            by_prefix[pref].append(bairro_canon(addr.get("area")))

    out = {}
    for pref, bairros in by_prefix.items():
        n = len(bairros)
        if n < MIN_ANUNCIOS:
            out[pref] = (None, n, "menos de 3 anúncios")
            continue
        c = Counter(bairros)
        bairro, cnt = c.most_common(1)[0]
        pct = cnt / n
        if bairro is not None and pct >= LIMIAR_PCT:
            out[pref] = (bairro, n, f"{cnt}/{n} ({pct:.0%}) = {bairro}")
        else:
            out[pref] = (None, n, f"maioria {bairro!r} só {cnt}/{n} ({pct:.0%}), abaixo de 60%")
    return out


def main():
    with open(SRC, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    prefixos_validar = [r["cep_prefixo"] for r in rows if r["status"] == "VALIDAR_ANUNCIOS"]
    validacao = validar_por_anuncios(prefixos_validar) if prefixos_validar else {}

    final = {}
    print("=== VALIDAR_ANUNCIOS: decisão por prefixo ===")
    for r in rows:
        pref = r["cep_prefixo"]
        provisorio = r["bairro_mercado"].strip()
        if r["status"] == "VALIDAR_ANUNCIOS":
            vencedor, n, detalhe = validacao.get(pref, (None, 0, "sem anúncios"))
            usado = vencedor if vencedor else provisorio
            print(f"  {pref}: provisório={provisorio!r} | {detalhe} -> usa {usado!r}")
            final[pref] = usado
        else:
            final[pref] = provisorio

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cep_prefixo", "bairro_mercado_final"])
        for pref in sorted(final):
            w.writerow([pref, final[pref]])

    c = Counter(final.values())
    print(f"\n=== {len(final)} prefixos resolvidos -> {OUT} ===")
    for bairro, n in c.most_common():
        print(f"  {n:4d}  {bairro}")


if __name__ == "__main__":
    main()
