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
já aplicada, votos de endereço/CEP com os 3 anos inteiros — ver revisão
2026-10-01 em cascata_completa). Diferença de escopo: aqui não há janela
de 12 meses — o objetivo é a série histórica ano a ano (2024/2025/2026)
pra calcular variação ano contra ano, não um retrato dos últimos 12
meses. `resolver_revenda_todos_anos()` é verificado contra carteira_77
em scripts/test_carteira_77.py (caminho de código próprio, não reusa
resolver_registros_engine()).

Mediana/P25/P75 usam trim_outliers_iqr (mesmo corte de outlier já usado
em todo o resto do motor) — protege contra erro de digitação isolado
(um zero a mais/a menos) distorcer o P75. `n_vendas` conta TODAS as
revendas do grupo, antes do corte de outlier (mesmo padrão de
engine.py: contagem = bruta, preço = limpo).

Revisão 2026-10-01 (ajustes pedidos pelo usuário):
  1. Só ano real da transação >= 2024 (campo "day", não o arquivo/aba de
     origem) — guia paga com atraso faz alguma transação de 2023 ou
     antes aparecer na planilha de 2024.xlsx.
  2. variacao_pct_ano_anterior só quando NENHUM dos dois anos comparados
     é amostra pequena (comparar medianas de poucas vendas não tem
     significado); senão fica vazio.
  3. Coluna `meses_cobertos`: intervalo de meses com dado real nesse
     grupo (bairro+tipo+ano) especificamente — reflete sozinho que 2026
     (ano em andamento) é parcial, sem precisar hardcodar o mês de
     corte.
  4. main() chama checar_consistencia_com_carteira_77() automaticamente
     ao final e falha (AssertionError, sys.exit(1)) se divergir de
     carteira_77 — não depende mais de lembrar de rodar
     test_carteira_77.py à parte. Não entra no build diário
     (build_data.py nunca chama este script).
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cascata_completa as cc
import tradutor_bairro as tb
from normalize import excel_serial_to_ym, median, percentile, trim_outliers_iqr

ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = ROOT / "output" / "valor_pago_por_bairro.csv"

MIN_AMOSTRA = 10  # mesmo limiar já usado em engine.py (MIN_TRANSACOES_PRECO_M2_12M)
ANO_MINIMO = 2024  # item 1 da revisão: descarta transação real anterior a isso (guia atrasada)
TIPO_POR_USO = {"10": "casa", "20": "apartamento"}
MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def resolver_revenda_todos_anos():
    """Resolve bairro (carteira de 77) pra toda a revenda aprovada, 3
    anos inteiros — mesma tabela de tradução + split de Santo Amaro +
    cascata de 5 métodos + pool de votos de 3 anos inteiros de
    gerar_dados_carteira_77()/resolver_registros_engine() (ver revisão
    2026-10-01 em cascata_completa.py), só que num caminho de código
    independente (não chama nenhuma das duas). Retorna (records, stats)
    — `records` são os dicts originais do parse + `bairro` (destino
    resolvido), só os efetivamente resolvidos pra um dos 77 (fora/
    incerto descartados)."""
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
    # anos inteiros pra série histórica. Votos de endereço/CEP também com
    # os 3 anos inteiros (resolver_universo_itbi simples: vota e resolve
    # o mesmo universo).
    buckets = cc.classificar_revenda_planta_aprovada(itbi_dedup_todos)
    revenda = buckets["revenda"]
    print(f"[export] revenda (3 anos, todos os usos): {len(revenda)}")

    contagem, fora, incerto, _, resolucao = cc.resolver_universo_itbi(cascata, revenda)
    print(f"[export] resolvidos pra carteira: {sum(contagem.values())} | fora={fora} | incerto={incerto}")

    out = []
    for r in revenda:
        destino, _ = resolucao.get(cc._rkey(r), (None, None))
        if not destino:
            continue
        out.append({**r, "bairro": destino})
    return out, {"total_revenda_todos_anos": len(revenda), "fora": fora, "incerto": incerto}


def checar_consistencia_com_carteira_77(revenda_resolvida):
    """Confere que `revenda_resolvida` (resolver_revenda_todos_anos(),
    caminho de código próprio deste script — não chama
    resolver_registros_engine() nem gerar_dados_carteira_77()) bate
    exato com carteira_77 (site/data.json), na janela de 12m, bairro a
    bairro. Levanta AssertionError se divergir — nunca falha silencioso.
    Usada tanto aqui (main(), automática) quanto em
    scripts/test_carteira_77.py (reusa esta função, não duplica a
    lógica)."""
    data_json = ROOT / "site" / "data.json"
    data = json.loads(data_json.read_text(encoding="utf-8"))
    c77 = data["carteira_77"]
    ym_inicio = tuple(int(x) for x in c77["periodo_12m"]["inicio"].split("-"))
    ym_fim = tuple(int(x) for x in c77["periodo_12m"]["fim"].split("-"))

    contagem_12m = {}
    for r in revenda_resolvida:
        if r.get("day") is None:
            continue
        ym = excel_serial_to_ym(r["day"])
        if ym_inicio <= ym <= ym_fim:
            contagem_12m[r["bairro"]] = contagem_12m.get(r["bairro"], 0) + 1

    divergencias = []
    for b, v in c77["bairros"].items():
        esperado = v["revenda_12m"]
        achado = contagem_12m.get(b, 0)
        if achado != esperado:
            divergencias.append(f"{b}: carteira_77.revenda_12m={esperado} != valor_pago_por_bairro={achado}")
    if divergencias:
        raise AssertionError(
            "valor_pago_por_bairro.csv diverge de carteira_77:\n  " + "\n  ".join(divergencias)
        )
    print(f"[export] OK — consistente com carteira_77 em revenda_12m, {len(c77['bairros'])} bairros.")


def main():
    revenda_resolvida, stats = resolver_revenda_todos_anos()

    # {(bairro, tipo, ano): [(valor, mes), ...]}
    grupos = {}
    descartados_ano_antigo = 0
    for r in revenda_resolvida:
        tipo = TIPO_POR_USO.get(r.get("uso_code"))
        if tipo is None or r.get("day") is None:
            continue
        ano, mes = excel_serial_to_ym(r["day"])
        if ano < ANO_MINIMO:
            descartados_ano_antigo += 1
            continue
        grupos.setdefault((r["bairro"], tipo, ano), []).append((r["valor"], mes))
    print(f"[export] descartados por ano real < {ANO_MINIMO} (guia paga com atraso): {descartados_ano_antigo}")

    linhas = []
    for (bairro, tipo, ano), pares in grupos.items():
        valores = [v for v, _ in pares]
        meses = sorted(set(m for _, m in pares))
        n_vendas = len(valores)
        limpos = trim_outliers_iqr(valores)
        meses_cobertos = f"{MESES_PT[meses[0] - 1]}–{MESES_PT[meses[-1] - 1]}" if meses else "—"
        linhas.append({
            "bairro": bairro, "tipo": tipo, "periodo": ano, "meses_cobertos": meses_cobertos,
            "n_vendas": n_vendas,
            "p25": round(percentile(25, limpos), 2),
            "mediana": round(median(limpos), 2),
            "p75": round(percentile(75, limpos), 2),
            "amostra_pequena": n_vendas < MIN_AMOSTRA,
        })

    medianas = {(l["bairro"], l["tipo"], l["periodo"]): l["mediana"] for l in linhas}
    amostra_pequena_por_chave = {(l["bairro"], l["tipo"], l["periodo"]): l["amostra_pequena"] for l in linhas}
    for l in linhas:
        chave_anterior = (l["bairro"], l["tipo"], l["periodo"] - 1)
        ant = medianas.get(chave_anterior)
        # Item 2 da revisão: variação só quando NEM o ano atual NEM o
        # anterior são amostra pequena — comparar medianas calculadas
        # sobre poucas vendas produz uma variação % sem significado.
        ambos_amostra_suficiente = not l["amostra_pequena"] and not amostra_pequena_por_chave.get(chave_anterior, True)
        l["variacao_pct_ano_anterior"] = (
            round(100 * (l["mediana"] - ant) / ant, 1) if (ant and ambos_amostra_suficiente) else None
        )

    linhas.sort(key=lambda l: (l["bairro"], l["tipo"], l["periodo"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "bairro", "tipo", "periodo", "meses_cobertos", "n_vendas", "p25", "mediana", "p75",
            "amostra_pequena", "variacao_pct_ano_anterior",
        ])
        w.writeheader()
        w.writerows(linhas)

    print(f"[export] {OUT_CSV} escrito ({len(linhas)} linhas)")

    checar_consistencia_com_carteira_77(revenda_resolvida)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"[export] FALHOU: {e}", file=sys.stderr)
        sys.exit(1)
