#!/usr/bin/env python3
"""
Etapa 2, item 3 (PRIORIDADE — prazo 2026-10-07): exporta
output/valor_pago_por_bairro.csv — valor TOTAL pago (não R$/m²) em
REVENDA, por bairro (carteira de 77) + tipo de imóvel + ano, com P25/
mediana/P75 e variação % ano contra ano.

Usa a mesma régua de "revenda" já aprovada (item 3 da auditoria de ITBI,
2026-09-30: proporção transmitida 100% + uso residencial 10/20 — ver
cascata_completa.classificar_revenda_planta_aprovada) e a mesma cascata
de bairro de 77 (tradutor_bairro.Cascata, com a divisão de Santo Amaro
já aplicada). Diferença de escopo: aqui não há janela de 12 meses — o
objetivo é a série histórica ano a ano (2024/2025/2026) pra calcular
variação ano contra ano, não um retrato dos últimos 12 meses.

Mediana/P25/P75 usam trim_outliers_iqr (mesmo corte de outlier já usado
em todo o resto do motor) — protege contra erro de digitação isolado
(um zero a mais/a menos) distorcer o P75. `n_vendas` conta TODAS as
revendas do grupo, antes do corte de outlier (mesmo padrão de
engine.py: contagem = bruta, preço = limpo).
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cascata_completa as cc
import tradutor_bairro as tb
from normalize import excel_serial_to_ym, median, percentile, trim_outliers_iqr

ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = ROOT / "output" / "valor_pago_por_bairro.csv"

MIN_AMOSTRA = 10  # mesmo limiar já usado em engine.py (MIN_TRANSACOES_PRECO_M2_12M)
TIPO_POR_USO = {"10": "casa", "20": "apartamento"}


def main():
    tradutor = tb.carregar_tradutor()
    targets = tb.targets_carteira(tradutor)
    split = tb.carregar_split_santo_amaro()

    print("[export] carregando quadras (qualquer bairro)...")
    quadras_qualquer_bairro = set(cc.ig.construir_votos_quadra().keys())
    print("[export] construindo votos de quadra traduzidos...")
    votos_quadra_resolvidos = tb.construir_votos_quadra_traduzido(tradutor, split_santo_amaro=split)
    cascata = tb.Cascata(
        tradutor, targets, votos_quadra_resolvidos,
        quadras_qualquer_bairro=quadras_qualquer_bairro, split_santo_amaro=split,
    )

    print("[export] parseando ITBI (todos os anos, todos os usos)...")
    itbi_dedup_todos = cc.carregar_itbi_deduplicado()

    # Regra aprovada, SEM restringir à janela de 12 meses — queremos os 3
    # anos inteiros pra série histórica.
    buckets = cc.classificar_revenda_planta_aprovada(itbi_dedup_todos)
    revenda = buckets["revenda"]
    print(f"[export] revenda (3 anos, todos os usos): {len(revenda)}")

    contagem, fora, incerto, _, resolucao = cc.resolver_universo_itbi(cascata, revenda)
    print(f"[export] resolvidos pra carteira: {sum(contagem.values())} | fora={fora} | incerto={incerto}")

    # {(bairro, tipo, ano): [valores]}
    grupos = {}
    for r in revenda:
        destino, _ = resolucao.get(cc._rkey(r), (None, None))
        if not destino:
            continue
        tipo = TIPO_POR_USO.get(r.get("uso_code"))
        if tipo is None or r.get("day") is None:
            continue
        ano = excel_serial_to_ym(r["day"])[0]
        grupos.setdefault((destino, tipo, ano), []).append(r["valor"])

    linhas = []
    for (bairro, tipo, ano), valores in grupos.items():
        n_vendas = len(valores)
        limpos = trim_outliers_iqr(valores)
        linhas.append({
            "bairro": bairro, "tipo": tipo, "periodo": ano, "n_vendas": n_vendas,
            "p25": round(percentile(25, limpos), 2),
            "mediana": round(median(limpos), 2),
            "p75": round(percentile(75, limpos), 2),
            "amostra_pequena": n_vendas < MIN_AMOSTRA,
        })

    medianas = {(l["bairro"], l["tipo"], l["periodo"]): l["mediana"] for l in linhas}
    for l in linhas:
        ant = medianas.get((l["bairro"], l["tipo"], l["periodo"] - 1))
        l["variacao_pct_ano_anterior"] = round(100 * (l["mediana"] - ant) / ant, 1) if ant else None

    linhas.sort(key=lambda l: (l["bairro"], l["tipo"], l["periodo"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "bairro", "tipo", "periodo", "n_vendas", "p25", "mediana", "p75",
            "amostra_pequena", "variacao_pct_ano_anterior",
        ])
        w.writeheader()
        w.writerows(linhas)

    print(f"[export] {OUT_CSV} escrito ({len(linhas)} linhas)")


if __name__ == "__main__":
    main()
