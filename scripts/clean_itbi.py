#!/usr/bin/env python3
"""
Camada de dados limpa do ITBI — usada por todo cálculo de PREÇO do motor
(mediana de bairro, faixa de metragem, Alertas, Valor de Oportunidade,
Perfil por Bairro, Prontidão/Imóveis Prioritários, e o painel de Preço por
m²). Volume/liquidez (Ranking de Oportunidade, Estoque×Demanda) continuam
usando o conjunto residencial bruto (giro é giro, mesmo com natureza não
comercial ou transferência parcial) — ver engine.py.

Auditoria de 2026-09-29 (ver README) encontrou dois problemas que exigem
olhar o conjunto INTEIRO de linhas de um endereço/imóvel, não uma linha
por vez — por isso ficam aqui, separados de parse_itbi.py:

1. Bairro (coluna E) é texto livre preenchido por transação, não um dado
   fixo do imóvel — pode faltar numa linha e estar correto em outra do
   MESMO endereço. resolve_bairros() decide por maioria entre as linhas
   do mesmo endereço.
2. A deduplicação por rua+número+valor+data (usada até 2026-09-27)
   confundia unidades DIFERENTES com preço/data coincidentes (comum em
   lançamento com tabela de preço padronizada). dedup_by_sql() usa o
   SQL (cadastro do imóvel, coluna A do ITBI) — identificador oficial e
   inequívoco — com fallback pra chave antiga só quando o SQL está
   ausente (raro).

Depois de bairro resolvido + deduplicado, build_clean_layer() aplica os
filtros de PREÇO propriamente ditos (natureza, % transmitido, tipo de
imóvel, outlier por bairro+tipo+faixa de metragem) e devolve um log
auditável de quantas linhas saíram em cada etapa.
"""
from normalize import percentile

# "Uso (IPTU)" -> tipo de imóvel comparável a um anúncio de venda (unidade
# individual). 21/22 ("Prédio de apartamento, não em condomínio") são o
# PRÉDIO INTEIRO vendido de uma vez, não uma unidade — não tem equivalente
# em nenhum anúncio da nonStop, então ficam fora de qualquer comparação de
# preço por unidade (medido em 2026-09-29: 25 vendas nos 49 bairros, <0,2%
# do total — volume irrelevante perto do problema de comparar prédio
# inteiro com apartamento).
TIPO_IMOVEL_POR_USO = {
    "20": "apartamento", "25": "apartamento",
    "10": "casa", "12": "casa", "14": "casa",
}

# Campo "type" da API da nonStop (e coluna "Tipo" do export manual — mesmo
# vocabulário nos dois, confirmado em 2026-09-29) -> mesma classificação de
# 2 categorias usada pro ITBI acima, pra comparação de preço por m² ser
# sempre "mesmo tipo de imóvel". Tipos fora dessa lista (TERRENO_*,
# comercial, rural etc. — já deveriam estar excluídos pelo filtro
# use=RESIDENCIAL, mas por segurança) ficam None: fora de qualquer
# comparação por tipo.
TIPO_IMOVEL_NONSTOP = {
    "APARTAMENTO_TIPO": "apartamento", "APARTAMENTO_GARDEN": "apartamento",
    "COBERTURA": "apartamento", "STUDIO": "apartamento", "LOFT": "apartamento",
    "FLAT": "apartamento", "DUPLEX": "apartamento",
    "CASA_TIPO": "casa", "SOBRADO": "casa", "CASA_EM_CONDOMINIO": "casa", "CASA_DE_VILA": "casa",
}

# Cap de área privativa dos anúncios da nonStop — achado testando a Etapa 3
# (2026-09-29): um anúncio tinha área "130000" (130 mil m², claramente um
# erro de digitação — provavelmente 130m² com 3 zeros a mais), gerando um
# R$/m² de R$13 e um falso "99,8% de desconto" no Valor de Oportunidade.
# Maior área legítima na amostra real: 895m² (mansão/cobertura grande) — um
# teto de 2000m² corta só o erro óbvio, sem descartar casas grandes de
# verdade (mais alto que o AREA_CAP=600 do ITBI de propósito: aqui é
# anúncio de UMA unidade específica, não o problema de "área construída
# pode ser do prédio inteiro" que o ITBI tem).
AREA_CAP_NONSTOP = 2000

# Faixas de metragem (Etapa 3 da auditoria de 2026-09-29) — usadas tanto
# pra remover outlier de R$/m² (aqui) quanto pra segmentar toda comparação
# de preço pedido × pago (engine.py).
FAIXAS_METRAGEM = [
    (0, 50, "até 50m²"),
    (50, 80, "50–80m²"),
    (80, 120, "80–120m²"),
    (120, float("inf"), "acima de 120m²"),
]


def faixa_metragem(area):
    """Retorna o rótulo da faixa de metragem pra uma área em m², ou None
    se a área for inválida (None ou fora de qualquer faixa, o que não
    deveria acontecer já que a faixa final é aberta)."""
    if area is None:
        return None
    for lo, hi, label in FAIXAS_METRAGEM:
        if lo < area <= hi or (lo == 0 and area == 0):
            return label
    return None


MIN_AMOSTRA_OUTLIER = 10  # segmentos menores que isso não têm poder estatístico pra P5/P95 confiável

# Item 2 da auditoria de 2026-09-30: valor declarado implausível pra uma
# venda de mercado de verdade (erro de digitação, valor simbólico entre
# parentes, etc) — só aplica a "compra e venda" de 100% do imóvel (não faz
# sentido julgar o valor de uma FRAÇÃO pelo mesmo limiar do imóvel inteiro).
VALOR_MIN_REAL = 10_000
VALOR_MAX_REAL = 100_000_000


def resolve_bairros(records, log=print):
    """Endereços (rua+número) cujo bairro varia entre linhas — ou falta —
    recebem o bairro mais frequente entre as linhas do MESMO endereço que
    já têm um bairro reconhecido (um dos 49 da carteira). Endereços sem
    NENHUMA linha com bairro reconhecido são descartados (fora da
    carteira). Retorna (records_resolvidos, stats)."""
    by_addr = {}
    sem_addr_key = 0
    for r in records:
        if not r["addr_key"]:
            sem_addr_key += 1
            continue
        by_addr.setdefault(r["addr_key"], []).append(r)

    sem_bairro_direto = sum(1 for r in records if r["addr_key"] and not r["bairro"])
    recuperados = 0
    descartados_sem_bairro = 0
    out = []

    for addr_key, recs in by_addr.items():
        counts = {}
        for r in recs:
            if r["bairro"]:
                counts[r["bairro"]] = counts.get(r["bairro"], 0) + 1
        if not counts:
            descartados_sem_bairro += len(recs)
            continue
        bairro_resolvido = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[0][0]
        for r in recs:
            if not r["bairro"]:
                recuperados += 1
            out.append({**r, "bairro": bairro_resolvido})

    stats = {
        "total_entrada": len(records),
        "sem_addr_key_descartados": sem_addr_key,
        "sem_bairro_direto_na_propria_linha": sem_bairro_direto,
        "recuperados_por_maioria_do_endereco": recuperados,
        "descartados_endereco_sem_nenhum_bairro_reconhecido": descartados_sem_bairro,
        "total_saida": len(out),
    }
    log(f"[clean] resolve_bairros: {stats}")
    return out, stats


def dedup_by_sql(records, log=print):
    """Deduplicação pelo SQL (cadastro do imóvel) + valor + data + complemento
    — chave oficial e inequívoca do imóvel, ao contrário de rua+número (que
    várias unidades de um mesmo prédio compartilham). Cai pra chave antiga
    (bairro+rua+número+valor+data+complemento) só quando o SQL está ausente.

    Achado de 2026-09-30 (respondendo ao item 2, ponto 1a): a versão
    anterior desta função (auditoria de 2026-09-29) NÃO incluía o
    complemento na chave — SQL+valor+data sozinhos confundiam unidades
    DIFERENTES do mesmo lançamento com tabela de preço padronizada (mesmo
    SQL do lote/torre-mãe, mesmo dia de fechamento, valor coincidente,
    complemento diferente — ex: "AP 601" vs "AP 1813"). Medido em produção:
    373 das 622 "duplicatas" removidas pela chave antiga (60%) tinham
    complemento diferente — eram vendas de verdade sendo descartadas."""
    seen = set()
    out = []
    duplicatas = 0
    sem_sql = 0
    for r in records:
        if r["sql"]:
            key = ("sql", r["sql"], round(r["valor"], 2), r["day"], r.get("complemento") or "")
        else:
            sem_sql += 1
            key = ("fallback", r["bairro"], r["addr_key"], round(r["valor"], 2), r["day"], r.get("complemento") or "")
        if key in seen:
            duplicatas += 1
            continue
        seen.add(key)
        out.append(r)

    stats = {
        "total_entrada": len(records),
        "sem_sql_usou_chave_antiga": sem_sql,
        "duplicatas_removidas": duplicatas,
        "total_saida": len(out),
    }
    log(f"[clean] dedup_by_sql: {stats}")
    return out, stats


def build_clean_layer(records, log=print):
    """records: já resolvidos (bairro sempre presente) e deduplicados.
    Aplica os filtros de PREÇO (natureza, % transmitido, tipo de imóvel,
    área válida, outlier de R$/m² por bairro+tipo+faixa) e devolve
    (records_com_flag_e_campos_novos, log_auditavel).

    Cada record de entrada ganha:
      - tipo_imovel: "apartamento" | "casa" | None (None = fora do escopo,
        ex: prédio inteiro — não confundir com "não residencial", que já
        foi filtrado em parse_itbi.py)
      - valor_m2: valor / area, quando area válida
      - is_clean_sale: True só quando passa TODOS os filtros desta camada
    Volume/liquidez (engine.py) continuam usando is_compra_venda/
    is_full_transfer direto nos records originais — is_clean_sale é só
    pra cálculo de PREÇO.
    """
    entrada = len(records)
    excl_tipo = 0
    excl_natureza = 0
    excl_natureza_por_tipo = {}
    excl_fracao = 0
    excl_valor_irreal = 0
    excl_sem_area = 0

    candidatos = []
    for r in records:
        tipo = TIPO_IMOVEL_POR_USO.get(r["uso_code"])
        rec = {**r, "tipo_imovel": tipo, "valor_m2": None, "is_clean_sale": False}
        if tipo is None:
            excl_tipo += 1
            candidatos.append(rec)
            continue
        if not r["is_compra_venda"]:
            excl_natureza += 1
            label = r.get("natureza_raw") or "(sem natureza)"
            excl_natureza_por_tipo[label] = excl_natureza_por_tipo.get(label, 0) + 1
            candidatos.append(rec)
            continue
        if not r["is_full_transfer"]:
            excl_fracao += 1
            candidatos.append(rec)
            continue
        # Item 2 da auditoria de 2026-09-30: valor implausível pra uma venda
        # de mercado (erro de digitação/valor simbólico) — só faz sentido
        # julgar aqui porque já garantimos "compra e venda" + 100% do imóvel
        # (fração e outras naturezas têm valor sistematicamente menor, não
        # comparável a este limiar).
        if not (VALOR_MIN_REAL <= r["valor"] <= VALOR_MAX_REAL):
            excl_valor_irreal += 1
            candidatos.append(rec)
            continue
        if not r["area"]:
            excl_sem_area += 1
            candidatos.append(rec)
            continue
        rec["valor_m2"] = round(r["valor"] / r["area"], 2)
        candidatos.append(rec)

    # Outlier de R$/m² por bairro + tipo + faixa de metragem — cercas
    # simples de percentil (P5/P95), não Tukey/IQR: aqui queremos um corte
    # absoluto de cauda (Etapa 3 pediu P5–P95 explicitamente), diferente do
    # trim_outliers_iqr usado no resto do motor (adaptativo por IQR).
    groups = {}
    for rec in candidatos:
        if rec["valor_m2"] is None:
            continue
        f = faixa_metragem(rec["area"])
        if f is None:
            continue
        rec["_faixa_metragem"] = f
        groups.setdefault((rec["bairro"], rec["tipo_imovel"], f), []).append(rec)

    excl_outlier = 0
    segmentos_log = []
    for (bairro, tipo, f), recs in groups.items():
        vals = [rec["valor_m2"] for rec in recs]
        n = len(vals)
        if n < MIN_AMOSTRA_OUTLIER:
            segmentos_log.append({
                "bairro": bairro, "tipo_imovel": tipo, "faixa": f,
                "n": n, "amostra_pequena": True, "removidos": 0,
            })
            for rec in recs:
                rec["is_clean_sale"] = True
            continue
        p5, p95 = percentile(5, vals), percentile(95, vals)
        removidos_aqui = 0
        for rec in recs:
            if p5 <= rec["valor_m2"] <= p95:
                rec["is_clean_sale"] = True
            else:
                removidos_aqui += 1
        excl_outlier += removidos_aqui
        segmentos_log.append({
            "bairro": bairro, "tipo_imovel": tipo, "faixa": f, "n": n,
            "amostra_pequena": False, "p5_valor_m2": round(p5, 2), "p95_valor_m2": round(p95, 2),
            "removidos": removidos_aqui,
        })

    saida_limpa = sum(1 for rec in candidatos if rec["is_clean_sale"])
    stats = {
        "total_entrada": entrada,
        "excluidos_predio_inteiro_uso_21_22": excl_tipo,
        "excluidos_natureza_nao_compra_venda": excl_natureza,
        "excluidos_natureza_nao_compra_venda_por_tipo": dict(
            sorted(excl_natureza_por_tipo.items(), key=lambda kv: -kv[1])
        ),
        "excluidos_transferencia_parcial": excl_fracao,
        "excluidos_valor_irreal": excl_valor_irreal,
        "excluidos_sem_area_construida_valida": excl_sem_area,
        "excluidos_outlier_valor_m2_fora_p5_p95": excl_outlier,
        "total_saida_clean_sale": saida_limpa,
        "segmentos_bairro_tipo_faixa": sorted(segmentos_log, key=lambda s: -s["removidos"]),
    }
    log(
        "[clean] build_clean_layer: entrada={total_entrada} -> limpo={total_saida_clean_sale} "
        "(prédio inteiro -{excluidos_predio_inteiro_uso_21_22}, natureza -{excluidos_natureza_nao_compra_venda}, "
        "fração parcial -{excluidos_transferencia_parcial}, valor irreal -{excluidos_valor_irreal}, "
        "sem área -{excluidos_sem_area_construida_valida}, "
        "outlier R$/m² -{excluidos_outlier_valor_m2_fora_p5_p95})".format(**stats)
    )
    return candidatos, stats
