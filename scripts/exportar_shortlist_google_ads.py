#!/usr/bin/env python3
"""
Migração do Prontidão para Campanha (urgente, 2026-10-01), item 4:
exporta output/shortlist_google_ads.csv — os 77 bairros ordenados pela
nota de prontidão, pra alimentar campanhas do Google Ads.

Lê direto site/data.json (já construído por build_data.py — não reparseia
ITBI/nonStop, só reformata o que o motor já calculou). Rodar depois de
`python3 scripts/build_data.py`.

Revisão 2026-10-01 (ajustes pedidos pelo usuário):
  - buscas_google_mes (+ 3 colunas por termo) preenchidas a partir de
    data/keyword_state.json. Pros bairros que faltam nesse cache, busca
    AGORA via keyword_client.fetch_search_interest (função já existente,
    nenhuma integração nova) — só pros que faltam, não refaz os que já
    têm cache. Esse fetch extra NÃO é salvo de volta em data/keyword_
    state.json (ver _carregar_busca_completa) — fica só em memória, pra
    não misturar bairros com fetched_at diferentes sob um timestamp
    global único, o que tornaria search_interest_meta.fresco do painel
    enganoso. O painel/dashboard não muda nada nesta revisão.
  - tag_busca continua refletindo exatamente o que data.json/o painel
    publicado mostra (nivel alto/médio/baixo + fresco, calculados lá) —
    não inventa uma classificação paralela pros bairros buscados agora
    só pra esta exportação."""
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = ROOT / "site" / "data.json"
OUT_CSV = ROOT / "output" / "shortlist_google_ads.csv"
ENV_FILE = ROOT / ".env"


def _load_dotenv():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


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


def _carregar_busca_completa(bairros_alvo, log=print):
    """Combina o cache existente (data/keyword_state.json) com um fetch
    AO VIVO, só pros bairros ausentes do cache — reaproveita
    keyword_client.fetch_search_interest tal como já existe. Retorna
    dict {bairro: {avg_monthly_searches, meses_com_dado, por_termo}} —
    "por_termo" só existe pros bairros que vieram do fetch de agora (o
    cache antigo nunca guardou a granularidade por termo)."""
    import keyword_client as kc

    state = kc._load_state()
    combinado = dict(state["data"]) if state else {}
    faltando = [b for b in bairros_alvo if b not in combinado]

    if not faltando:
        log("[shortlist] cache de busca já cobre todos os bairros.")
        return combinado

    if not kc.credentials_available():
        log(f"[shortlist] GOOGLE_ADS_* não configurado — {len(faltando)} bairro(s) sem cache ficam sem dado de busca: {faltando}")
        return combinado

    log(f"[shortlist] buscando interesse de busca pra {len(faltando)} bairro(s) sem cache (fetch ao vivo, não salvo no cache compartilhado)...")
    try:
        novos = kc.fetch_search_interest(faltando, log=log)
    except Exception as e:
        log(f"[shortlist] aviso: falhou buscar os {len(faltando)} bairro(s) que faltavam ({e}) — ficam sem dado de busca.")
        return combinado
    combinado.update(novos)
    return combinado


def main():
    _load_dotenv()
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    bairros = data["bairros"]
    meta = data.get("search_interest_meta")

    busca_completa = _carregar_busca_completa(list(bairros.keys()))

    linhas = []
    for nome, b in bairros.items():
        si = busca_completa.get(nome)
        por_termo = (si or {}).get("por_termo") or {}
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
            "buscas_google_mes": si["avg_monthly_searches"] if si else "",
            "busca_apartamento_a_venda": por_termo.get("apartamento_a_venda", ""),
            "busca_apartamento": por_termo.get("apartamento", ""),
            "busca_imoveis": por_termo.get("imoveis", ""),
        })

    linhas.sort(key=lambda l: -l["nota_prontidao"])

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "bairro", "nota_prontidao", "revenda_12m", "tendencia_revenda_pct", "giro_12m_pct",
            "anuncios_ativos", "anuncios_perfil_vencedor_faixa_preco", "tag_busca",
            "amostra_pequena", "buscas_google_mes",
            "busca_apartamento_a_venda", "busca_apartamento", "busca_imoveis",
        ])
        w.writeheader()
        w.writerows(linhas)

    print(f"[shortlist] {OUT_CSV} escrito ({len(linhas)} linhas)")


if __name__ == "__main__":
    main()
