#!/usr/bin/env python3
"""
Novo export para conteúdo (PRIORIDADE — prazo 2026-10-07):
output/oferta_por_faixa_bairro.csv — oferta ATUAL de apartamento (nonStop,
availableFor=VENDA), por faixa de preço pedido × bairro (carteira de 77).

Fonte: o MESMO estoque atual que o dashboard usa (nonstop_client.
fetch_all_records, com fallback pro export manual dados-usenonstop/*.xlsx
se NONSTOP_TOKEN não estiver configurado — ver
scripts/build_data.py._get_usn_records, mesmo padrão, reproduzido aqui
porque este é um script standalone, não chama build_data.py). bairro já
vem resolvido pra carteira de 77 (normalize.bairro_canon, aplicado dentro
de nonstop_client.card_to_record); tipo_imovel já vem classificado
(clean_itbi.TIPO_IMOVEL_NONSTOP) — este script filtra só "apartamento".

Este export NÃO toca em nada do dashboard (data.json, raw.json, engine.py/
engine.js, nenhum painel) — só lê o estoque ao vivo e escreve um CSV novo.

ÁREA ÚTIL FORA DO RAZOÁVEL: exclui anúncio com área preenchida fora de
[20m², 1.000m²], ANTES de deduplicar. nonStop já tem um teto de 2000m² pra
erro de digitação grosseiro (AREA_CAP_NONSTOP, ver clean_itbi.py) — este é
um corte mais rigoroso, específico deste export. Anúncio sem área
preenchida (None) não é excluído por este filtro (não dá pra saber se é
"razoável" sem o dado), mas naturalmente não contribui pra
mediana/P25/P75 de área (normalize.median/percentile já ignoram None).

DEDUPLICAÇÃO (pedido do usuário, 2026-10-01): o mesmo imóvel às vezes
aparece mais de uma vez no estoque (republicado, ou corretores diferentes
anunciando a mesma unidade) — mesmo endereço (addr_key: rua+número, sem
bairro — normalize.address_key) + mesma área útil + preço dentro de ±3%
um do outro conta como 1 anúncio só. Anúncio sem addr_key (rua/número não
reconhecido pelo parser) não entra em nenhum grupo — fica sozinho (não dá
pra confirmar que é duplicata de nada sem endereço). Clustering guloso
(não é um algoritmo com transitividade garantida — A~B e B~C não implica
A~C testado contra A —, mas suficiente pro objetivo: reduzir
republicações óbvias do MESMO imóvel, não fazer deduplicação perfeita).

FAIXAS DE PREÇO: 4 janelas específicas pedidas pelo usuário — NÃO é uma
partição do mercado inteiro (há lacunas entre elas, e nada abaixo de 400mil
nem acima de 2,7mi); um anúncio fora das 4 simplesmente não entra no
export. Bairro × faixa sem nenhum anúncio não gera linha (mesmo padrão de
scripts/exportar_valor_pago_por_bairro.py — zero não é "linha com 0", é
"sem linha").
"""
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from normalize import median, percentile

ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = ROOT / "output" / "oferta_por_faixa_bairro.csv"
ENV_FILE = ROOT / ".env"

AREA_MIN_RAZOAVEL = 20
AREA_MAX_RAZOAVEL = 1000
DEDUP_PRECO_TOLERANCIA = 0.03  # ±3%
MIN_AMOSTRA = 5

FAIXAS_PRECO = [
    ("R$ 400-500 mil", 400_000, 500_000),
    ("R$ 750-850 mil", 750_000, 850_000),
    ("R$ 1,4-1,6 mi", 1_400_000, 1_600_000),
    ("R$ 2,3-2,7 mi", 2_300_000, 2_700_000),
]


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


def carregar_anuncios_apartamento_venda():
    """Mesma fonte/fallback que build_data.py usa pro estoque atual (ver
    _get_usn_records): API da nonStop se NONSTOP_TOKEN estiver
    configurado (.env ou ambiente), senão o export manual .xlsx mais
    recente em dados-usenonstop/. Retorna só tipo_imovel == "apartamento"
    (disponível pra venda — availableFor=VENDA já filtrado na origem)."""
    _load_dotenv()
    token = os.environ.get("NONSTOP_TOKEN", "").strip()
    if token:
        import nonstop_client
        print("[oferta] usando API da nonStop (NONSTOP_TOKEN definido)")
        records, meta = nonstop_client.fetch_all_records(token, available_for="VENDA")
    else:
        print("[oferta] NONSTOP_TOKEN não definido — usando export manual dados-usenonstop/*.xlsx")
        from parse_usenonstop_xlsx import parse_usenonstop_xlsx
        candidatos = sorted((ROOT / "dados-usenonstop").glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidatos:
            raise SystemExit(
                "Sem NONSTOP_TOKEN e sem nenhum .xlsx em dados-usenonstop/ — não há fonte de estoque disponível."
            )
        records, stats = parse_usenonstop_xlsx(candidatos[0])
        meta = {"fonte": "xlsx_manual", "arquivo": candidatos[0].name, **stats}
    print(f"[oferta] estoque bruto ({meta.get('fonte')}): {len(records)} anúncios (venda, carteira de 77)")

    apartamentos = [r for r in records if r.get("tipo_imovel") == "apartamento"]
    print(f"[oferta] apartamentos: {len(apartamentos)}")
    return apartamentos


def filtrar_area_razoavel(anuncios):
    validos, excluidos = [], 0
    for r in anuncios:
        area = r.get("area")
        if area is not None and (area < AREA_MIN_RAZOAVEL or area > AREA_MAX_RAZOAVEL):
            excluidos += 1
            continue
        validos.append(r)
    return validos, excluidos


def deduplicar_anuncios(anuncios):
    """Mesmo addr_key + mesma área útil + preço dentro de ±3% = 1
    anúncio. Representante do grupo é o anúncio com mais campos
    preenchidos (quartos/vagas) — critério de desempate arbitrário mas
    determinístico, já que o objetivo é só CONTAR anúncios únicos, não
    escolher "o anúncio certo"."""
    sem_endereco = [r for r in anuncios if not r.get("addr_key")]
    por_endereco = {}
    for r in anuncios:
        if r.get("addr_key"):
            por_endereco.setdefault(r["addr_key"], []).append(r)

    dedupados = list(sem_endereco)
    n_removidos = 0
    for grupo in por_endereco.values():
        por_area = {}
        for r in grupo:
            por_area.setdefault(r.get("area"), []).append(r)
        for recs in por_area.values():
            usados = [False] * len(recs)
            for i, r in enumerate(recs):
                if usados[i]:
                    continue
                usados[i] = True
                cluster = [r]
                for j in range(i + 1, len(recs)):
                    if usados[j]:
                        continue
                    r2 = recs[j]
                    v1, v2 = r.get("valor"), r2.get("valor")
                    if v1 and v2 and abs(v2 - v1) <= DEDUP_PRECO_TOLERANCIA * v1:
                        cluster.append(r2)
                        usados[j] = True
                representante = max(cluster, key=lambda x: (x.get("quartos") is not None) + (x.get("vagas") is not None))
                dedupados.append(representante)
                n_removidos += len(cluster) - 1
    print(f"[oferta] deduplicação: {len(anuncios)} -> {len(dedupados)} anúncios únicos (removidos {n_removidos} republicados/duplicados)")
    return dedupados


def faixa_de(valor):
    if valor is None:
        return None
    for nome, lo, hi in FAIXAS_PRECO:
        if lo <= valor <= hi:
            return nome
    return None


def _r(v, nd=1):
    return round(v, nd) if v is not None else None


def main():
    anuncios = carregar_anuncios_apartamento_venda()
    anuncios, excluidos_area = filtrar_area_razoavel(anuncios)
    print(f"[oferta] excluídos por área útil fora de [{AREA_MIN_RAZOAVEL}m², {AREA_MAX_RAZOAVEL}m²]: {excluidos_area}")
    anuncios = deduplicar_anuncios(anuncios)

    grupos = {}
    for r in anuncios:
        faixa = faixa_de(r.get("valor"))
        bairro = r.get("bairro")
        if faixa is None or bairro is None:
            continue
        grupos.setdefault((faixa, bairro), []).append(r)

    data_extracao = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    linhas = []
    for (faixa, bairro), recs in grupos.items():
        areas = [r.get("area") for r in recs]
        quartos = [r.get("quartos") for r in recs]
        vagas = [r.get("vagas") for r in recs]
        n_anuncios = len(recs)
        linhas.append({
            "faixa_preco": faixa, "bairro": bairro, "n_anuncios": n_anuncios,
            "area_p25": _r(percentile(25, areas)),
            "area_mediana": _r(median(areas)),
            "area_p75": _r(percentile(75, areas)),
            "dormitorios_mediana": _r(median(quartos)),
            "vagas_mediana": _r(median(vagas)),
            "amostra_pequena": n_anuncios < MIN_AMOSTRA,
            "data_extracao": data_extracao,
        })

    ordem_faixa = {nome: i for i, (nome, _, _) in enumerate(FAIXAS_PRECO)}
    linhas.sort(key=lambda l: (ordem_faixa[l["faixa_preco"]], l["bairro"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "faixa_preco", "bairro", "n_anuncios", "area_p25", "area_mediana", "area_p75",
            "dormitorios_mediana", "vagas_mediana", "amostra_pequena", "data_extracao",
        ])
        w.writeheader()
        w.writerows(linhas)

    print(f"[oferta] {OUT_CSV} escrito ({len(linhas)} linhas, {len(grupos)} combinações faixa x bairro com >=1 anúncio)")


if __name__ == "__main__":
    main()
