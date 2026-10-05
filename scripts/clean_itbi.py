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
from normalize import percentile  # noqa: F401 (usado por outros módulos que importam daqui)

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



# Item 2 da auditoria de 2026-09-30: valor declarado implausível pra uma
# venda de mercado de verdade (erro de digitação, valor simbólico entre
# parentes, etc) — só aplica a "compra e venda" de 100% do imóvel (não faz
# sentido julgar o valor de uma FRAÇÃO pelo mesmo limiar do imóvel inteiro).
VALOR_MIN_REAL = 10_000
VALOR_MAX_REAL = 100_000_000

# Camada limpa única (2026-10-05): regra de SUBDECLARAÇÃO. A Prefeitura
# calcula o ITBI sobre a "Base de Cálculo adotada" (o maior entre o valor
# declarado e o venal de referência). Quando o valor declarado fica abaixo de
# SUBDECLARACAO_LIMITE da base, o declarado é descartado do PREÇO (a guia
# continua contando em volume/giro). Distribuição medida nas revendas dos
# últimos 12 meses: 80% têm declarado = base; percentis 1/5/10 = 0,28/0,70/
# 0,84. Comparando cada guia com as outras vendas do MESMO prédio, abaixo de
# 50% da base 98-100% estão muito abaixo das vizinhas (anomalia real); entre
# 60-70% só ~55%; entre 70-80% ~35% (perto do ruído natural de 7%).
SUBDECLARACAO_LIMITE = 0.60


def motivo_valor_sujo(valor, base_calculo):
    """REGRA ÚNICA de valor (camada limpa): devolve None se o valor serve
    pra PREÇO, ou o motivo da exclusão — "valor_irreal" (fora de
    VALOR_MIN_REAL..VALOR_MAX_REAL) ou "subdeclarado" (declarado abaixo de
    SUBDECLARACAO_LIMITE x base de cálculo adotada). Usada por
    build_clean_layer e por qualquer script que calcule preço direto de
    registros do parse (ex.: exportar_valor_pago_por_bairro.py)."""
    if not (VALOR_MIN_REAL <= valor <= VALOR_MAX_REAL):
        return "valor_irreal"
    if eh_subdeclarado(valor, base_calculo):
        return "subdeclarado"
    return None


def eh_subdeclarado(valor, base_calculo, limite=None):
    """True se o valor declarado ficou abaixo de `limite` (default
    SUBDECLARACAO_LIMITE) da base de cálculo adotada. Sem base (None/<=0) a
    regra não se aplica."""
    if not base_calculo or base_calculo <= 0:
        return False
    return valor < (SUBDECLARACAO_LIMITE if limite is None else limite) * base_calculo


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
    """CAMADA LIMPA ÚNICA DE PREÇO (2026-10-05) — a mesma regra pro
    dashboard inteiro (Captação Ativa, faixa do perfil vencedor v2, painel
    "Preço por m²", medianas de bairro, exportações). records: já resolvidos
    (bairro sempre presente) e deduplicados. Devolve
    (records_com_flag_e_campos_novos, log_auditavel).

    is_clean_sale = True quando o registro é uma venda de mercado cujo VALOR
    é confiável pra preço:
      1. tipo de imóvel conhecido (não é prédio inteiro, uso 21/22);
      2. natureza "1.Compra e venda";
      3. 100% do imóvel (proporção transmitida);
      4. limites duros: VALOR_MIN_REAL <= valor <= VALOR_MAX_REAL;
      5. sem subdeclaração: valor declarado >= SUBDECLARACAO_LIMITE x "Base
         de Cálculo adotada" pela Prefeitura (quando a base existe).
    NÃO há mais corte estatístico por R$/m² (P5-P95 por segmento — tirava
    ~10% de vendas legítimas de propósito) nem exigência de área: mediana e
    P25-P75 já são robustas e valor total não depende de área. `valor_m2`
    continua calculado quando a área é válida (R$/m² só existe com área).

    Cada record de entrada ganha:
      - tipo_imovel: "apartamento" | "casa" | None
      - valor_m2: valor / area, quando area válida (senão None)
      - is_clean_sale: ver regra acima
    Volume/liquidez (engine.py) continuam usando is_compra_venda/
    is_full_transfer direto nos records originais — is_clean_sale é só
    pra cálculo de PREÇO."""
    entrada = len(records)
    excl_tipo = 0
    excl_natureza = 0
    excl_natureza_por_tipo = {}
    excl_fracao = 0
    excl_valor_irreal = 0
    excl_subdeclarado = 0
    limpos_sem_area = 0

    candidatos = []
    for r in records:
        tipo = TIPO_IMOVEL_POR_USO.get(r["uso_code"])
        rec = {**r, "tipo_imovel": tipo, "valor_m2": None, "is_clean_sale": False}
        if r.get("area"):
            rec["valor_m2"] = round(r["valor"] / r["area"], 2)
        candidatos.append(rec)
        if tipo is None:
            excl_tipo += 1
            continue
        if not r["is_compra_venda"]:
            excl_natureza += 1
            label = r.get("natureza_raw") or "(sem natureza)"
            excl_natureza_por_tipo[label] = excl_natureza_por_tipo.get(label, 0) + 1
            continue
        if not r["is_full_transfer"]:
            excl_fracao += 1
            continue
        # Só faz sentido julgar o valor aqui porque já garantimos "compra e
        # venda" + 100% do imóvel (fração e outras naturezas têm valor
        # sistematicamente menor, não comparável a este limiar).
        motivo = motivo_valor_sujo(r["valor"], r.get("base_calculo"))
        if motivo == "valor_irreal":
            excl_valor_irreal += 1
            continue
        if motivo == "subdeclarado":
            excl_subdeclarado += 1
            continue
        rec["is_clean_sale"] = True
        if not r.get("area"):
            limpos_sem_area += 1

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
        "excluidos_subdeclarado": excl_subdeclarado,
        "subdeclaracao_limite": SUBDECLARACAO_LIMITE,
        "limpos_sem_area_valida": limpos_sem_area,
        "total_saida_clean_sale": saida_limpa,
    }
    log(
        "[clean] build_clean_layer: entrada={total_entrada} -> limpo={total_saida_clean_sale} "
        "(prédio inteiro -{excluidos_predio_inteiro_uso_21_22}, natureza -{excluidos_natureza_nao_compra_venda}, "
        "fração parcial -{excluidos_transferencia_parcial}, valor irreal -{excluidos_valor_irreal}, "
        "subdeclarado -{excluidos_subdeclarado}; limpos sem área válida: {limpos_sem_area_valida})".format(**stats)
    )
    return candidatos, stats
