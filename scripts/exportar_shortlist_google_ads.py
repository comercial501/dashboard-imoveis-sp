#!/usr/bin/env python3
"""
Migração do Prontidão para Campanha (urgente, 2026-10-01), item 4:
exporta output/shortlist_google_ads.csv — os 77 bairros ordenados pela
nota de prontidão, pra alimentar campanhas do Google Ads.

Lê direto site/data.json (já construído por build_data.py — não reparseia
ITBI/nonStop, só reformata o que o motor já calculou). Rodar depois de
`python3 scripts/build_data.py`."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = ROOT / "site" / "data.json"
OUT_CSV = ROOT / "output" / "shortlist_google_ads.csv"


def tag_busca(bairro_entry, meta):
    si = bairro_entry.get("search_interest")
    if not si:
        return "sem dado"
    if meta and not meta.get("fresco"):
        data_fmt = meta["fetched_at"][:10] if meta.get("fetched_at") else "?"
        return f"sem dado recente (fonte: {meta.get('fonte', '?')}, última tentativa {data_fmt})"
    nivel = {"alto": "Alto", "medio": "Médio", "baixo": "Baixo"}.get(si.get("nivel"), si.get("nivel"))
    fonte = meta.get("fonte", "Google Ads Keyword Planner") if meta else "Google Ads Keyword Planner"
    data_fmt = meta["fetched_at"][:10] if meta and meta.get("fetched_at") else "?"
    return f"{nivel} (fonte: {fonte}, dado de {data_fmt})"


def main():
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    bairros = data["bairros"]
    meta = data.get("search_interest_meta")

    linhas = []
    for nome, b in bairros.items():
        linhas.append({
            "bairro": nome,
            "nota_prontidao": b["prontidao_campanha"],
            "revenda_12m": b["revenda_12m"],
            "tendencia_revenda_pct": b.get("trend_pct_revenda_12m"),
            "giro_12m_pct": b.get("giro_12m_pct"),
            "anuncios_ativos": b["stock_total"],
            "anuncios_perfil_vencedor_faixa_preco": b["estoque_perfil_faixa_preco"],
            "tag_busca": tag_busca(b, meta),
            "amostra_pequena": b["amostra_pequena_ranking"],
            "buscas_google_mes": "",
        })

    linhas.sort(key=lambda l: -l["nota_prontidao"])

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "bairro", "nota_prontidao", "revenda_12m", "tendencia_revenda_pct", "giro_12m_pct",
            "anuncios_ativos", "anuncios_perfil_vencedor_faixa_preco", "tag_busca",
            "amostra_pequena", "buscas_google_mes",
        ])
        w.writeheader()
        w.writerows(linhas)

    print(f"[shortlist] {OUT_CSV} escrito ({len(linhas)} linhas)")


if __name__ == "__main__":
    main()
