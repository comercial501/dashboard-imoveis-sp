#!/usr/bin/env python3
"""
Motor de cálculo — porte de build_data.pl para Python.

Toda fórmula/limiar aqui é especificado (com referência de linha do Perl
original) em itbi_methodology_spec.md. Este módulo é agnóstico da fonte dos
dados: recebe listas de records já normalizados (ver parse_itbi.py e
nonstop_client.py / parse_usenonstop_xlsx.py) e devolve a estrutura
agregada consumida pelo site (site/data.json).

Generalização em relação ao original: o Perl tinha os anos 2024/2025/2026
hardcoded. Aqui os "papéis" dos 3 anos mais recentes são dinâmicos:
  - year_curr  = ano em andamento (o mais recente, dados parciais)
  - year_full  = último ano fechado (year_curr - 1) — só usado pra tendência
                 ano-cheio-vs-ano-cheio junto com year_prev
  - year_prev  = dois anos atrás (year_curr - 2) — usado só pra tendência
                 ano-cheio-vs-ano-cheio (equivalente ao "growth_24_25")
Isso evita ter que editar o código todo ano-novo.

Volume/mediana de preço/liquidez "de referência" (Ranking, Prontidão,
Estoque×Demanda, Valor de Oportunidade) NÃO usam só year_full — decisão do
usuário em 2026-09-25: usam os 3 anos juntos (pool pra mediana de preço,
média anual pra volume/liquidez), pra amostra maior e mais estável em
bairros com poucas vendas por ano. year_full/year_prev continuam existindo
só pra calcular a tendência de crescimento, que por definição precisa
comparar anos distintos.
"""
import statistics as _stats

from normalize import (
    AREA_BUCKET_WIDTH,
    NEIGHBOR_COUNT,
    NEIGHBOR_MAX_KM,
    coord_is_valid_sp,
    dedup_cap_exact_area,
    excel_serial_to_ym,
    mean,
    median,
    mode_bucket_from_pairs,
    mode_of,
    nearest_neighbors,
    normalize_0_100,
    percentile,
    today_excel_serial,
    trim_outliers_iqr,
    ym_add_months,
    zscore_map,
)
from normalize import TARGETS
from clean_itbi import FAIXAS_METRAGEM, faixa_metragem

# ---------------------------------------------------------------------------
# Constantes (idênticas ao Perl — ver itbi_methodology_spec.md §19)
# ---------------------------------------------------------------------------
RELIABILITY_THRESHOLD = 5
TREND_CAP = 1.0
LAUNCH_MIN_COUNT = 5
LAUNCH_WINDOW_DAYS = 182
ADDR_MIN_VALOR = 30_000
ADDR_MAX_RATIO = 20
# Razão máx/mín de área (m²) num mesmo endereço acima da qual a faixa
# exibida (area_min/area_max) vira None (não confiável) — NÃO exclui o
# endereço da Captação Ativa, só esconde a metragem exibida (achado da
# auditoria de 2026-09-24: medido em produção, 90% dos endereços com 2+
# vendas de "compra e venda" têm razão ≤1,55x, 99% ≤2,6x; 4x já cobre até
# prédios com unidades bem diferentes — tipo garden + cobertura — sem
# deixar passar erro de digitação óbvio, tipo "29m² e 480m²" no mesmo
# endereço).
ADDR_MAX_RATIO_AREA = 4
VALOR_OPORTUNIDADE_MIN_DESCONTO = 0.20
VALOR_OPORTUNIDADE_ATENCAO_DESCONTO = 0.30
VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY = 10
CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH = 2
CAPTACAO_ESTRATEGICA_MIN_ENDERECOS = 5

# Etapa 3 da auditoria de 2026-09-29: toda comparação pedido×pago passa a
# ser em R$/m², dentro da mesma faixa de metragem e do mesmo tipo de
# imóvel, com mediana (não média). Um segmento (bairro+tipo+faixa) com
# menos de 10 transações pagas nos ÚLTIMOS 12 MESES é "amostra pequena" —
# não gera alerta nem achado de Valor de Oportunidade (mediana pago usa o
# pool de 3 anos de qualquer forma, ver pooled_median; os 12 meses são só
# o portão de confiança "isso ainda reflete o bairro HOJE").
MIN_TRANSACOES_PRECO_M2_12M = 10
JANELA_PRECO_M2_DIAS = 365
# Achado da Etapa 5 (validação, 2026-09-29): metade dos 10 maiores gaps de
# Alertas vinham de 1-4 anúncios só do lado pedido — a regra de amostra
# acima protege só o lado pago. Um segmento só vira alerta/"representativo"
# do bairro (Gap Preço do Ranking, flag_alerta) quando TAMBÉM tem 3+
# anúncios — não mexe em amostra_pequena (que continua só sobre o lado
# pago, usada também pelo Valor de Oportunidade, que nem olha pro lado
# pedido) nem nas tabelas de exibição (Perfil por Bairro, painel de R$/m²),
# que mostram o dado como está, com o badge, sem decidir por quem lê.
MIN_ANUNCIOS_ALERTA = 3

# Etapa 2, item 3 (2026-10-01) — proteção provisória de amostra no
# Ranking (a revisão de pesos do score fica pra depois): achado do
# usuário no export de 01/10 — Jardim da Glória aparecia em 3º em "Onde
# anunciar agora" com 34 vendas e tendência +78,9%, puramente por amostra
# pequena (uma variação de poucas vendas vira um % de tendência enorme).
MIN_VENDAS_TENDENCIA = 50  # por janela (atual E anterior) — abaixo disso, tendência = neutra (não entra no score)
MIN_VENDAS_TOP10 = 100  # bairro com menos que isso em revenda_12m não entra no top 10 de "Onde anunciar agora"

# Passo 3c (2026-10-05), decisões de mercado da auditoria:
# - Anúncio com mais de 365 dias (idade medida contra o horário da consulta
#   à nonStop, ver build_data._get_usn_records) continua em TODAS as contas
#   — só ganha o selo "Anúncio antigo — validar disponibilidade".
ANUNCIO_ANTIGO_DIAS = 365
# - Bônus de captação do Painel 8 deixa de ser tudo-ou-nada: cresce com o
#   nº de vendas no endereço (ITBI, 3 anos, só venda válida). Todo endereço
#   em captacao_ativa tem >= 2 vendas; 5 ou mais = bônus cheio.
CAPTACAO_BONUS_POR_VENDAS = {2: 40, 3: 60, 4: 80}
CAPTACAO_BONUS_MAX = 100

# Passo 4 (2026-10-05): bônus de captação HÍBRIDO.
#  1. Endereço com >= 10 unidades residenciais no IPTU 2026 (e imóvel que não
#     é casa): giro relativo = vendas em 3 anos / unidades; < 7% = 40,
#     7-10% = 60, 10-15% = 80, >= 15% = 100.
#  2. Endereço com < 10 unidades, casa, ou SEM casamento com o IPTU (~1%):
#     escala por nº de vendas (CAPTACAO_BONUS_POR_VENDAS).
#  3. Em qualquer régua, bônus acima de 60 exige >= 3 vendas em 3 anos.
CAPTACAO_MIN_UNIDADES_GIRO = 10
CAPTACAO_GIRO_FAIXAS = ((0.07, 40), (0.10, 60), (0.15, 80))  # abaixo do limite -> bônus; resto -> MAX
CAPTACAO_MIN_VENDAS_BONUS_ALTO = 3
CAPTACAO_BONUS_SEM_MINIMO_MAX = 60
REGUA_GIRO = "giro do prédio"
REGUA_VENDAS = "nº de vendas"


def _bonus_captacao_hibrido(n_vendas, unidades, tipo_imovel):
    """Retorna (bônus, régua, giro). régua = REGUA_GIRO ou REGUA_VENDAS (None
    se o endereço não está na Captação Ativa); giro só vem na régua de giro."""
    if not n_vendas or n_vendas < 2:
        return 0, None, None
    if unidades and unidades >= CAPTACAO_MIN_UNIDADES_GIRO and tipo_imovel != "casa":
        giro = n_vendas / unidades
        bonus = CAPTACAO_BONUS_MAX
        for limite, valor in CAPTACAO_GIRO_FAIXAS:
            if giro < limite:
                bonus = valor
                break
        regua = REGUA_GIRO
    else:
        giro = None
        bonus = _bonus_captacao(n_vendas)
        regua = REGUA_VENDAS
    if n_vendas < CAPTACAO_MIN_VENDAS_BONUS_ALTO:
        bonus = min(bonus, CAPTACAO_BONUS_SEM_MINIMO_MAX)
    return bonus, regua, giro


def _bonus_captacao(n_vendas):
    """None/0/1 vendas = 0 (endereço fora da Captação Ativa); 2/3/4 =
    40/60/80; 5+ = 100."""
    if not n_vendas or n_vendas < 2:
        return 0
    return CAPTACAO_BONUS_POR_VENDAS.get(n_vendas, CAPTACAO_BONUS_MAX)

PESOS_PAINEL8 = {"revenda": 0.35, "preco": 0.30, "aderencia": 0.25, "captacao": 0.10}
PESOS_PRONTIDAO = {"f1": 0.15, "f2": 0.20, "f3": 0.15, "f4": 0.15, "f5": 0.25, "f6": 0.10}

# Passo 2b (2026-10-01): componente de preço do Painel 8 suspenso pra
# apartamento (faixa_metragem() comparava área construída do ITBI x área
# útil do anúncio — mesma distorção do backlog de calibração). Peso de
# "preco" redistribuído PROPORCIONALMENTE entre os 3 componentes
# restantes, só pra apartamento — casa usa PESOS_PAINEL8 normalmente.
_PESOS_PAINEL8_APTO_SOMA = PESOS_PAINEL8["revenda"] + PESOS_PAINEL8["aderencia"] + PESOS_PAINEL8["captacao"]
PESOS_PAINEL8_APARTAMENTO = {
    "revenda": PESOS_PAINEL8["revenda"] / _PESOS_PAINEL8_APTO_SOMA,
    "aderencia": PESOS_PAINEL8["aderencia"] / _PESOS_PAINEL8_APTO_SOMA,
    "captacao": PESOS_PAINEL8["captacao"] / _PESOS_PAINEL8_APTO_SOMA,
}




def _round(v, digits=1):
    return None if v is None else round(v, digits)


# ---------------------------------------------------------------------------
# 1. Agregação por bairro/ano + pares (área, valor) pra faixa de metragem
# ---------------------------------------------------------------------------
def _is_valid_sale(r):
    """Só conta pra preço/metragem de ENDEREÇO específico (Captação Ativa)
    quando é (a) "1.Compra e venda" de mercado, (b) transferência de 100%
    do imóvel (coluna L — ~21% das "compra e venda" são transferência de
    FRAÇÃO ideal entre coproprietários, cujo `valor` corresponde só à
    fração) e (c) uma unidade de verdade, não o prédio inteiro (uso 21/22 —
    ver clean_itbi.TIPO_IMOVEL_POR_USO). NÃO aplica o corte de outlier por
    bairro+tipo+faixa da camada limpa (`is_clean_sale`) — o histórico de UM
    endereço já tem sua própria checagem de coerência (`_price_incoherent`),
    e aplicar ali um corte calibrado pelo bairro inteiro esconderia vendas
    genuínas de um prédio específico. Volume/liquidez continua contando
    qualquer transação residencial válida, cheia ou fracionária — giro é
    giro."""
    return r["is_compra_venda"] and r["is_full_transfer"] and r["tipo_imovel"] is not None


# Etapa 2 do item 3 da auditoria de ITBI (2026-10-01): mesma definição de
# "revenda" já aprovada em cascata_completa.classificar_revenda_planta_
# aprovada — proporção transmitida 100% E uso IPTU residencial (10 ou 20,
# não o conjunto mais amplo {10,12,14,20,21,22,25} de clean_itbi.
# TIPO_IMOVEL_POR_USO). Usada só pelo painel "Preço por m²" (valor total
# pago em apartamento) — ver _compute_preco_m2_painel.
_USO_REVENDA_APROVADA = {"10", "20"}


def _is_revenda_aprovada(r):
    return r["is_compra_venda"] and r["is_full_transfer"] and r.get("uso_code") in _USO_REVENDA_APROVADA


# Captação limpa (2026-10-05): a Captação Ativa passa a contar vendas e
# calcular preço só sobre REVENDA LIMPA — mesma base do carteira_77
# (is_revenda: natureza "1.Compra e venda", proporção 100%, uso
# residencial) MAIS a camada de limpeza de preço do resto do dashboard
# (is_clean_sale: valor entre R$ 10 mil e R$ 100 mi, área conhecida e
# R$/m² dentro de P5–P95 do segmento bairro+tipo+faixa). Antes só exigia
# compra e venda + 100% + tipo de imóvel (_is_valid_sale), então guias de
# valor absurdo (ex.: R$ 36 mil num apartamento de 99 m²) entravam na
# contagem e na faixa. Planta e valores fora do padrão ficam em contagens
# separadas (n_planta / n_valor_fora_padrao), nunca no preço.
CAPTACAO_MIN_VENDAS_FAIXA = 4  # P25-P75 só com 4+ revendas limpas; abaixo disso só a mediana


def _is_revenda_limpa(r):
    return bool(r.get("is_revenda")) and bool(r.get("is_clean_sale"))


def _aggregate_itbi(itbi_records, years):
    """Volume (`count`) conta QUALQUER transação residencial válida — giro
    do bairro é giro, mesmo quando o valor não é confiável pra preço.
    `avg_valor`/`median_valor` e `pairs_all_years` (faixa de metragem/preço,
    Perfil Vencedor) usam a camada de dados limpa (`is_clean_sale` — ver
    clean_itbi.py: natureza, % transmitido, tipo de imóvel, deduplicado por
    SQL e sem outlier de R$/m² pro seu segmento bairro+tipo+faixa) —
    decisão explícita do usuário de não deixar isso contaminar
    preço/metragem, mas manter contando pra volume/liquidez."""
    yearly_count = {b: {y: 0 for y in years} for b in TARGETS}
    yearly_valores_venda = {b: {y: [] for y in years} for b in TARGETS}
    pairs_all_years = {b: [] for b in TARGETS}
    month_counts = {b: {} for b in TARGETS}  # bairro -> (ano,mes) -> count

    for r in itbi_records:
        b = r["bairro"]
        if b not in yearly_count:
            continue
        y = r["sheet_year"]
        valid = r["is_clean_sale"]
        if y in yearly_count[b]:
            yearly_count[b][y] += 1
            if valid:
                yearly_valores_venda[b][y].append(r["valor"])
        if r["area"] is not None and valid:
            pairs_all_years[b].append({"area": r["area"], "valor": r["valor"]})
        if r["day"] is not None:
            try:
                ym = excel_serial_to_ym(r["day"])
                month_counts[b][ym] = month_counts[b].get(ym, 0) + 1
            except Exception:
                pass

    yearly = {}
    for b in TARGETS:
        yearly[b] = {}
        for y in years:
            # trim_outliers_iqr protege a mediana contra erro de digitação
            # isolado (ex: um valor com um zero a mais/a menos) — ver
            # achado da auditoria de 2026-09-24 no README.
            vals = trim_outliers_iqr(yearly_valores_venda[b][y])
            yearly[b][y] = {
                "count": yearly_count[b][y],
                "avg_valor": _round(mean(vals), 2),
                "median_valor": _round(median(vals), 2),
            }

    # Mediana "de referência" do bairro (usada no Ranking, Prontidão,
    # Estoque×Demanda e Valor de Oportunidade) — pool dos 3 anos juntos, não
    # só o último fechado (decisão do usuário, 2026-09-25): amostra maior e
    # mais estável, principalmente em bairros com poucas vendas por ano.
    # Mesmo critério que Captação Ativa e Perfil Vencedor já usavam. Cercas
    # de Tukey aplicadas UMA VEZ sobre o pool combinado (não por ano depois
    # somado), senão o corte de outlier fica inconsistente.
    pooled_median = {}
    for b in TARGETS:
        pool = [v for y in years for v in yearly_valores_venda[b][y]]
        vals = trim_outliers_iqr(pool)
        pooled_median[b] = {
            "avg_valor": _round(mean(vals), 2),
            "median_valor": _round(median(vals), 2),
            "n": len(vals),
        }

    return yearly, pairs_all_years, month_counts, pooled_median


def _h1_count(month_counts_bairro, year):
    return sum(month_counts_bairro.get((year, m), 0) for m in range(1, 7))


def _compute_trend(yearly, month_counts, year_prev, year_full, year_curr):
    trend = {}
    for b in TARGETS:
        c_prev = yearly[b][year_prev]["count"]
        c_full = yearly[b][year_full]["count"]
        growth_prev = (c_full - c_prev) / c_prev if c_prev > 0 else None

        h1_full = _h1_count(month_counts[b], year_full)
        h1_curr = _h1_count(month_counts[b], year_curr)
        growth_h1 = (h1_curr - h1_full) / h1_full if h1_full > 0 else None

        growths = [g for g in (growth_prev, growth_h1) if g is not None]
        trend_pct = mean(growths) if growths else None
        trend_capped = None if trend_pct is None else max(-TREND_CAP, min(TREND_CAP, trend_pct))

        trend[b] = {
            "growth_prev_pct": _round(growth_prev * 100, 1) if growth_prev is not None else None,
            "growth_h1_pct": _round(growth_h1 * 100, 1) if growth_h1 is not None else None,
            "trend_pct": _round(trend_pct * 100, 1) if trend_pct is not None else None,
            "trend_pct_for_score": trend_capped,
        }
    return trend


# ---------------------------------------------------------------------------
# 1b. Volume por janela rolante de 12 meses completos (item 4 da auditoria
# de 2026-09-30) — campos NOVOS, aditivos. NÃO mexe em volume_primary_year/
# trend_pct/_compute_trend acima, que ficam como estavam (marcados
# obsoletos na documentação, não no código: mudar o significado de um
# campo existente conta como quebra mesmo mantendo o nome — regra do
# usuário). Diferenças pro cálculo antigo:
#   - agrupa pela DATA REAL da transação (coluna J via excel_serial_to_ym),
#     não pelo arquivo/aba de origem (sheet_year) — ver diagnóstico:
#     2,37% das linhas têm ano real diferente do arquivo em que aparecem
#   - exclui transações anteriores a 2024-01-01
#   - janela = 12 meses completos terminando no último mês "fechado", não
#     média de 3 anos-calendário (evita tratar 2026 parcial como ano cheio)
#   - tendência = mesmo intervalo de 12 meses, um ano antes (não mais
#     ano-cheio-vs-ano-cheio + 1º semestre)
# ---------------------------------------------------------------------------
VOLUME_12M_MIN_YM = (2024, 1)
# Um mês com menos de 50% da mediana dos 3 meses anteriores é tratado como
# lote incompleto (guias que vazaram pra frente pro arquivo do mês
# seguinte, não um mês fechado de verdade) — ex: em 2026-09-30, a aba
# JUL-2026 (a mais recente que existe) tem 173 linhas com data real de
# AGO-2026, longe o suficiente de um mês cheio (~10 mil) pra não virar o
# fim da janela.
VOLUME_12M_STUB_RATIO = 0.5
# Ajuste de 2026-09-30 (a ambiguidade era da especificação original, não do
# código): os meses "incompletos" NÃO entram na janela de 12 meses nem na
# tendência — ficam de fora inteiramente, só num indicador separado
# informativo (volume_recente_parcial). A janela = os 12 meses completos
# ANTERIORES aos 2 meses mais recentes com dado (defasagem de guia paga com
# atraso — ~2% das vendas de um ano só aparecem na planilha do ano
# seguinte, ver diagnóstico — então mesmo o mês "mais recente com dado"
# ainda pode estar subcontado).
VOLUME_12M_MESES_INCOMPLETOS = 2


def _mes_base_e_periodo(itbi_records):
    """Retorna (periodo_12m, periodo_12m_anterior, meses_incompletos).
    periodo_12m/periodo_12m_anterior são listas de 12 (ano,mês) cada,
    ascendentes. meses_incompletos são os VOLUME_12M_MESES_INCOMPLETOS
    meses mais recentes com dado real — ficam de fora de periodo_12m e de
    periodo_12m_anterior por inteiro (só aparecem no indicador separado
    volume_recente_parcial)."""
    ym_counts = {}
    for r in itbi_records:
        if r["day"] is None:
            continue
        ym = excel_serial_to_ym(r["day"])
        if ym < VOLUME_12M_MIN_YM:
            continue
        ym_counts[ym] = ym_counts.get(ym, 0) + 1

    meses_ordenados = sorted(ym_counts)
    while len(meses_ordenados) > 3:
        ultimo = meses_ordenados[-1]
        anteriores = meses_ordenados[-4:-1]
        mediana_anterior = median([ym_counts[m] for m in anteriores])
        if mediana_anterior > 0 and ym_counts[ultimo] < VOLUME_12M_STUB_RATIO * mediana_anterior:
            meses_ordenados.pop()
            continue
        break

    mes_mais_recente_com_dado = meses_ordenados[-1]
    # janela termina 2 meses antes do mês mais recente com dado — os 2 mais
    # recentes (mes_mais_recente_com_dado e o anterior) são os "incompletos"
    fim_janela = ym_add_months(mes_mais_recente_com_dado, -VOLUME_12M_MESES_INCOMPLETOS)
    periodo_12m = [ym_add_months(fim_janela, -i) for i in range(11, -1, -1)]
    periodo_12m_anterior = [ym_add_months(m, -12) for m in periodo_12m]
    meses_incompletos = [ym_add_months(fim_janela, i) for i in range(1, VOLUME_12M_MESES_INCOMPLETOS + 1)]
    return periodo_12m, periodo_12m_anterior, meses_incompletos


def _compute_volume_12m(itbi_records, periodo_externo=None):
    """volume_12m (por bairro) + trend_pct_12m (por bairro) + periodo_12m
    (metadado único do dataset) + volume_recente_parcial (por bairro,
    indicador separado e informativo, NÃO usado em volume_12m/trend_pct_12m
    — contagem dos meses_incompletos, só pra não perder a visibilidade
    desses 2 meses mais recentes). Mesma definição de "venda válida" que
    volume_primary_year: qualquer transação residencial conta (giro é
    giro) — só muda COMO o período é definido.

    `periodo_externo` (Etapa 2, item 1.1, 2026-10-01 — achado do teste de
    consistência): opcional (periodo_12m, periodo_12m_anterior,
    meses_incompletos) já calculado em OUTRO lugar, pra usar em vez de
    derivar de `itbi_records` aqui. Necessário porque _mes_base_e_periodo
    decide os limites do mês mais recente "completo" com base na
    DISTRIBUIÇÃO de transações por mês do próprio conjunto de entrada
    (detecção de mês "stub") — itbi_records aqui é só revenda+planta
    (universo menor que o de cascata_completa.gerar_dados_carteira_77,
    que roda a mesma função sobre TODOS os registros antes de
    classificar) — sem passar o mesmo período, os dois lados podiam
    escolher um mês de corte diferente e todo revenda_12m/planta_12m
    divergia de carteira_77 (bug real, pego pelo teste de consistência no
    primeiro build depois da migração)."""
    if periodo_externo is not None:
        periodo_12m, periodo_12m_anterior, meses_incompletos = periodo_externo
    else:
        periodo_12m, periodo_12m_anterior, meses_incompletos = _mes_base_e_periodo(itbi_records)
    periodo_set = set(periodo_12m)
    periodo_anterior_set = set(periodo_12m_anterior)
    incompletos_set = set(meses_incompletos)

    count_atual = {b: 0 for b in TARGETS}
    count_anterior = {b: 0 for b in TARGETS}
    count_recente_parcial = {b: 0 for b in TARGETS}
    # Item 2 da auditoria de 2026-09-30: volume_mercado_12m (só "1.Compra e
    # venda") e volume_retomadas_12m (alienação fiduciária + leilão) —
    # indicadores NOVOS e separados, não mexem em count_atual/volume_12m
    # (que continua "giro é giro", qualquer natureza, como sempre foi).
    count_mercado_atual = {b: 0 for b in TARGETS}
    count_mercado_anterior = {b: 0 for b in TARGETS}
    count_retomadas_atual = {b: 0 for b in TARGETS}
    # Item 1 da Etapa 2 (2026-10-01): revenda_12m/planta_12m — mesma
    # janela, mesma função (_mes_base_e_periodo é a MESMA que
    # cascata_completa.rodar() usa, via "from engine import
    # _mes_base_e_periodo" — garante bater com carteira_77 por
    # construção, não só por coincidência) — contagem direta pela tag
    # is_revenda/is_planta (itbi_records já é só revenda+planta, ver
    # cascata_completa.resolver_registros_engine).
    count_revenda_atual = {b: 0 for b in TARGETS}
    count_revenda_anterior = {b: 0 for b in TARGETS}
    count_planta_atual = {b: 0 for b in TARGETS}
    for r in itbi_records:
        b = r["bairro"]
        if b not in count_atual or r["day"] is None:
            continue
        ym = excel_serial_to_ym(r["day"])
        if ym < VOLUME_12M_MIN_YM:
            continue
        if ym in periodo_set:
            count_atual[b] += 1
            if r["is_compra_venda"]:
                count_mercado_atual[b] += 1
            elif r.get("is_retomada"):
                count_retomadas_atual[b] += 1
            if r.get("is_revenda"):
                count_revenda_atual[b] += 1
            elif r.get("is_planta"):
                count_planta_atual[b] += 1
        elif ym in periodo_anterior_set:
            count_anterior[b] += 1
            if r["is_compra_venda"]:
                count_mercado_anterior[b] += 1
            if r.get("is_revenda"):
                count_revenda_anterior[b] += 1
        elif ym in incompletos_set:
            count_recente_parcial[b] += 1

    trend_pct_12m = {}
    trend_pct_mercado_12m = {}
    for b in TARGETS:
        c_ant = count_anterior[b]
        trend_pct_12m[b] = _round((count_atual[b] - c_ant) / c_ant * 100, 1) if c_ant > 0 else None
        cm_ant = count_mercado_anterior[b]
        trend_pct_mercado_12m[b] = _round((count_mercado_atual[b] - cm_ant) / cm_ant * 100, 1) if cm_ant > 0 else None

    def _fmt(ym):
        return f"{ym[0]:04d}-{ym[1]:02d}"

    periodo_meta = {
        "inicio": _fmt(periodo_12m[0]),
        "fim": _fmt(periodo_12m[-1]),
        "meses_incompletos": [_fmt(m) for m in meses_incompletos],
    }
    return (
        count_atual, trend_pct_12m, periodo_meta, count_recente_parcial,
        count_mercado_atual, trend_pct_mercado_12m, count_retomadas_atual,
        count_revenda_atual, count_revenda_anterior, count_planta_atual,
        count_mercado_anterior,
    )


# ---------------------------------------------------------------------------
# 2. Estoque Usenonstop: agregação por bairro + centróides
# ---------------------------------------------------------------------------
def _aggregate_usn(usn_records):
    by_bairro = {b: [] for b in TARGETS}
    for r in usn_records:
        if r["bairro"] in by_bairro:
            by_bairro[r["bairro"]].append(r)

    centroids = {}
    for b in TARGETS:
        pts = [(r["lat"], r["lon"]) for r in by_bairro[b] if coord_is_valid_sp(r["lat"], r["lon"])]
        if pts:
            centroids[b] = (mean([p[0] for p in pts]), mean([p[1] for p in pts]))
        else:
            centroids[b] = None

    stock_total = {b: len(by_bairro[b]) for b in TARGETS}
    # trim_outliers_iqr protege contra anúncio com erro de digitação (ex:
    # um zero a mais no valor) contaminando a mediana pedida do bairro.
    asking_median = {
        b: _round(median(trim_outliers_iqr([r["valor"] for r in by_bairro[b] if r["valor"] is not None])), 2)
        for b in TARGETS
    }
    return by_bairro, centroids, stock_total, asking_median


# ---------------------------------------------------------------------------
# 3b. Perfil vencedor — faixa de preço v2 (revisão 2026-10-01, migração
# do Prontidão): P25-P75 do valor TOTAL pago em revenda nos últimos 12
# meses, por bairro + tipo de imóvel — SEM passar por metragem. Campo
# NOVO, aditivo (perfil_vencedor_faixa_preco_v2) — price_band (v1, modal
# de área, ver _compute_profile abaixo) continua intacto pros painéis
# que ainda não migraram (Estoque×Demanda, flag_prioridade_maxima,
# Captação Estratégica).
#
# Motivo da troca: a faixa v1 vem do BUCKET DE ÁREA mais comum nas
# vendas pagas (área CONSTRUÍDA do ITBI) — pra bairros onde esse bucket
# modal é um apartamento pequeno/antigo (ex: Campo Belo 80-100m²
# construída, ~45m² úteis equivalente), a faixa de preço resultante fica
# muito abaixo do que qualquer anúncio ativo pede hoje (que é área ÚTIL,
# não construída — mesmo problema de régua já identificado no item do
# backlog "calibração de área"). Separar por tipo de imóvel e tirar a
# metragem do meio evita herdar essa distorção.
# ---------------------------------------------------------------------------
PERFIL_PRECO_V2_TIPOS = ("apartamento", "casa")


def _compute_perfil_vencedor_faixa_preco_v2(itbi_records, periodo_12m, usn_by_bairro):
    periodo_set = set(periodo_12m)
    valores_por_bairro_tipo = {b: {t: [] for t in PERFIL_PRECO_V2_TIPOS} for b in TARGETS}
    for r in itbi_records:
        if not r.get("is_revenda"):
            continue
        b = r["bairro"]
        tipo = r.get("tipo_imovel")
        if b not in valores_por_bairro_tipo or tipo not in PERFIL_PRECO_V2_TIPOS:
            continue
        if r["day"] is None:
            continue
        if excel_serial_to_ym(r["day"]) not in periodo_set:
            continue
        valores_por_bairro_tipo[b][tipo].append(r["valor"])

    out = {}
    for b in TARGETS:
        bandas = {}
        for tipo in PERFIL_PRECO_V2_TIPOS:
            valores = valores_por_bairro_tipo[b][tipo]
            if not valores:
                bandas[tipo] = None
                continue
            valores_ok = trim_outliers_iqr(valores)
            bandas[tipo] = [_round(percentile(25, valores_ok), 2), _round(percentile(75, valores_ok), 2)]

        own_stock = usn_by_bairro[b]
        in_band = []
        for r in own_stock:
            banda = bandas.get(r.get("tipo_imovel"))
            if banda and r["valor"] is not None and banda[0] <= r["valor"] <= banda[1]:
                in_band.append(r)
        out[b] = {
            "bandas": bandas,
            "profile_sample_size_faixa_preco_v2": len(in_band),
        }
    return out


# ---------------------------------------------------------------------------
# 3. Perfil vencedor (Painel 3) + fallback regional (Mudança 1)
# ---------------------------------------------------------------------------
def _compute_profile(pairs_all_years, usn_by_bairro, centroids):
    profile = {}
    for b in TARGETS:
        own_pairs = pairs_all_years[b]
        entry = {
            "area_band": None, "price_band": None, "price_band_median": None,
            "area_band_reliability": "insufficient", "area_band_neighbors": [],
            "profile_quartos": None, "profile_vagas": None, "profile_sample_size": 0,
            "profile_reliability": "insufficient", "profile_neighbors": [],
            "profile_pool_sample_size": 0, "profile_sample_size_faixa_preco": 0,
        }

        # Gate 1 — faixa de área/preço
        if len(own_pairs) >= RELIABILITY_THRESHOLD:
            lo, hi, valores = mode_bucket_from_pairs(own_pairs)
            if lo is not None:
                # trim_outliers_iqr protege a faixa/mediana de preço contra
                # erro de digitação isolado dentro do bucket de metragem
                # vencedora — mesmo critério já usado na mediana de bairro e
                # na mediana pedida (achado da auditoria de 2026-09-25: sem
                # isso, 30 dos 45 bairros com faixa individual tinham pelo
                # menos 1 outlier contaminando essa faixa).
                valores_ok = trim_outliers_iqr(valores)
                entry["area_band"] = [lo, hi]
                entry["price_band"] = [_round(percentile(25, valores_ok), 2), _round(percentile(75, valores_ok), 2)]
                entry["price_band_median"] = _round(median(valores_ok), 2)
                entry["area_band_reliability"] = "individual"
        else:
            neighbors = nearest_neighbors(b, centroids, TARGETS, NEIGHBOR_MAX_KM, NEIGHBOR_COUNT)
            if neighbors:
                pool = list(own_pairs)
                neighbor_info = []
                for other, dist in neighbors:
                    n_pairs = pairs_all_years[other]
                    pool.extend(n_pairs)
                    neighbor_info.append({"bairro": other, "distancia_km": round(dist, 2), "n_pares": len(n_pairs)})
                lo, hi, valores = mode_bucket_from_pairs(pool)
                if lo is not None and valores:
                    valores_ok = trim_outliers_iqr(valores)
                    entry["area_band"] = [lo, hi]
                    entry["price_band"] = [_round(percentile(25, valores_ok), 2), _round(percentile(75, valores_ok), 2)]
                    entry["price_band_median"] = _round(median(valores_ok), 2)
                    entry["area_band_reliability"] = "regional"
                    entry["area_band_neighbors"] = neighbor_info

        # Re-score do estoque PRÓPRIO contra a faixa (própria ou regional) —
        # nunca soma estoque de vizinhos aqui (ver spec §6.7).
        own_stock = usn_by_bairro[b]
        if entry["area_band"]:
            lo, hi = entry["area_band"]
            in_band = [r for r in own_stock if r["area"] is not None and lo <= r["area"] < hi]
        else:
            in_band = []
        entry["profile_sample_size"] = len(in_band)
        entry["profile_quartos"] = mode_of([r["quartos"] for r in in_band])
        entry["profile_vagas"] = mode_of([r["vagas"] for r in in_band])

        # Etapa 2, revisão 2026-10-01 (migração do Prontidão para Campanha):
        # contagem SEPARADA de estoque no perfil vencedor por FAIXA DE
        # PREÇO (price_band, em valor total — mesma unidade do anúncio,
        # sem conversão nenhuma) em vez de por metragem. Motivo do
        # usuário: área construída do ITBI != área útil do anúncio (sem
        # fator de calibração ainda — ver backlog), enquanto preço pedido
        # (nonStop) e preço pago (ITBI) são a MESMA unidade (R$), direto
        # comparáveis. Campo NOVO, aditivo — profile_sample_size (área,
        # acima) continua intacto, usado por Estoque×Demanda/flag_
        # prioridade_maxima/Captação Estratégica (fora do escopo desta
        # migração, que é só o painel Prontidão).
        if entry["price_band"]:
            plo, phi = entry["price_band"]
            in_price_band = [r for r in own_stock if r["valor"] is not None and plo <= r["valor"] <= phi]
        else:
            in_price_band = []
        entry["profile_sample_size_faixa_preco"] = len(in_price_band)

        # Gate 2 — dormitórios/vagas (moda), independente do Gate 1
        if entry["profile_sample_size"] >= RELIABILITY_THRESHOLD:
            entry["profile_reliability"] = "individual"
        elif entry["area_band"]:
            neighbors = nearest_neighbors(b, centroids, TARGETS, NEIGHBOR_MAX_KM, NEIGHBOR_COUNT)
            lo, hi = entry["area_band"]
            pool = list(in_band)
            neighbor_info = []
            for other, dist in neighbors:
                other_in_band = [r for r in usn_by_bairro[other] if r["area"] is not None and lo <= r["area"] < hi]
                pool.extend(other_in_band)
                neighbor_info.append({"bairro": other, "distancia_km": round(dist, 2), "n_imoveis": len(other_in_band)})
            if len(pool) >= 2:
                entry["profile_quartos"] = mode_of([r["quartos"] for r in pool])
                entry["profile_vagas"] = mode_of([r["vagas"] for r in pool])
                entry["profile_reliability"] = "regional"
                entry["profile_pool_sample_size"] = len(pool)
                entry["profile_neighbors"] = neighbor_info

        profile[b] = entry
    return profile


# ---------------------------------------------------------------------------
# 4. Liquidez / Captação Ativa (Mudança 2) — agrupamento por endereço
# ---------------------------------------------------------------------------
def _price_incoherent(valores):
    if len(valores) < 2:
        return False
    vmin, vmax = min(valores), max(valores)
    if vmin < ADDR_MIN_VALOR:
        return True
    if vmin > 0 and (vmax / vmin) > ADDR_MAX_RATIO:
        return True
    return False


def _coherent_area_range(areas):
    """area_min/area_max de um endereço com 2+ unidades — None/None se a
    razão máx/mín for grande demais pra confiar (provável erro de
    digitação numa das linhas, não prédio misto de verdade). NÃO exclui o
    endereço da Captação Ativa, só esconde a metragem exibida — ver
    ADDR_MAX_RATIO_AREA."""
    if not areas:
        return None, None
    amin, amax = min(areas), max(areas)
    if len(areas) >= 2 and amin > 0 and (amax / amin) > ADDR_MAX_RATIO_AREA:
        return None, None
    return amin, amax


def _majority_bairro(recs):
    """addr_key agora é só rua+número (ver normalize.address_key) — um
    mesmo prédio pode ter linhas do ITBI com bairro diferente entre si
    (dado preenchido por transação, não é fixo do prédio). Usa o bairro
    mais frequente entre as vendas reais do endereço; empate resolvido
    alfabeticamente (mesmo critério de desempate determinístico já usado
    em mode_of/imoveis_prioritarios)."""
    counts = {}
    for r in recs:
        counts[r["bairro"]] = counts.get(r["bairro"], 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))[0][0]


def _is_launch(days):
    days = sorted(d for d in days if d is not None)
    if len(days) < LAUNCH_MIN_COUNT:
        return False
    for i in range(len(days)):
        cnt = 1
        for j in range(i + 1, len(days)):
            if days[j] - days[i] > LAUNCH_WINDOW_DAYS:
                break
            cnt += 1
        if cnt >= LAUNCH_MIN_COUNT:
            return True
    return False


def _compute_liquidez(itbi_records, usn_by_addr_key, years):
    by_addr = {}
    for r in itbi_records:
        if not r["addr_key"]:
            continue
        by_addr.setdefault(r["addr_key"], []).append(r)

    liquidez = {b: {y: {"total": 0, "revenda": 0} for y in years} for b in TARGETS}
    captacao_ativa = []
    captacao_unico = []
    n_addr_discarded = 0
    n_addr_launch = 0
    n_addr_total_multi = 0
    n_addr_sem_venda_real = 0

    for addr_key, all_recs in by_addr.items():
        # Volume/liquidez conta TODA transação da base nova (revenda OU
        # planta — itbi_records já só tem essas duas, ver
        # cascata_completa.resolver_registros_engine), no bairro em que
        # ela foi resolvida pela cascata. "revenda" aqui usa a tag
        # is_revenda (regra aprovada da Etapa 2, item 1) — NÃO mais
        # detecção de lançamento por endereço (_is_launch), que o usuário
        # rejeitou por classificar condomínio grande/antigo como
        # lançamento e lançamento pequeno/lento como revenda. Isso não
        # muda com o filtro de natureza abaixo, que só afeta a identidade
        # do PRÉDIO (Captação Ativa).
        for r in all_recs:
            if r["sheet_year"] in liquidez[r["bairro"]]:
                liquidez[r["bairro"]][r["sheet_year"]]["total"] += 1
                if r.get("is_revenda"):
                    liquidez[r["bairro"]][r["sheet_year"]]["revenda"] += 1

        # Só REVENDA LIMPA (compra e venda de mercado, 100% do imóvel, uso
        # residencial e valor dentro do padrão — ver _is_revenda_limpa) conta como "venda" pro histórico de PREÇO de um
        # endereço: herança/doação/integralização de capital tem valor
        # contábil, e transferência de fração ideal (coproprietário vendendo
        # só a sua parte) tem valor proporcional à fração, não ao imóvel
        # inteiro — nenhum dos dois é preço de mercado do apartamento e não
        # deveriam contar como "n vendas" nem entrar na faixa de preço
        # exibida pro usuário.
        recs = [r for r in all_recs if _is_revenda_limpa(r)]
        if not recs:
            n_addr_sem_venda_real += 1
            continue
        # Contagens separadas (nunca entram em n_vendas nem na faixa de
        # preço): venda na planta e revenda cujo valor ficou fora do padrão
        # (is_clean_sale falso — subdeclarado, R$/m² fora de P5–P95, etc.).
        n_planta = sum(1 for r in all_recs if r.get("is_planta"))
        n_valor_fora_padrao = sum(1 for r in all_recs if r.get("is_revenda") and not r.get("is_clean_sale"))

        # addr_key é só rua+número (ver normalize.address_key) — o mesmo
        # prédio pode ter linhas do ITBI com bairro diferente entre si
        # (dado preenchido por transação, não fixo do prédio). Usa o bairro
        # majoritário entre as vendas reais como bairro do prédio.
        bairro = _majority_bairro(recs)
        endereco = next((r["addr_display"] for r in recs if r["addr_display"]), addr_key)
        usn_aqui = usn_by_addr_key.get(addr_key, [])
        # Prefere a grafia natural do endereço vinda da nonStop (nível de
        # prédio, sem complemento de unidade) sobre o title-case derivado do
        # ITBI, igual ao critério documentado (ver §3 do spec de metodologia)
        # e já aplicado no lado JS via a tabela de interning do raw.json.
        # Mesmo critério do raw.json/engine.js (tabela de interning: o ÚLTIMO
        # anúncio com grafia vence) — antes o Python pegava o primeiro e as
        # duas pontas divergiam no texto quando dois anúncios do mesmo prédio
        # grafavam o endereço diferente (ex.: "Queiroz" x "Queiróz").
        preferido = next((u["addr_display_building"] for u in reversed(usn_aqui) if u.get("addr_display_building")), None)
        if preferido:
            endereco = preferido
        tem_hoje, unidades_hoje = _tem_unidade_a_venda_hoje(usn_aqui)

        if len(recs) == 1:
            r = recs[0]
            captacao_unico.append({
                "bairro": bairro, "addr_key": addr_key, "endereco": endereco,
                "n_vendas": 1, "preco_mediana": r["valor"], "preco_p25": None, "preco_p75": None,
                "poucas_vendas": True, "n_planta": n_planta, "n_valor_fora_padrao": n_valor_fora_padrao,
                "area_min": r["area"], "area_max": r["area"],
                "tem_unidade_a_venda_hoje": tem_hoje, "unidades_a_venda_hoje": unidades_hoje,
            })
            continue

        n_addr_total_multi += 1
        valores = [r["valor"] for r in recs]
        if _price_incoherent(valores):
            n_addr_discarded += 1
            continue
        if _is_launch([r["day"] for r in recs]):
            n_addr_launch += 1
            continue

        areas = [r["area"] for r in recs if r["area"] is not None]
        area_min, area_max = _coherent_area_range(areas)
        captacao_ativa.append({
            "bairro": bairro, "addr_key": addr_key, "endereco": endereco,
            "n_vendas": len(recs), "preco_mediana": _round(median(valores), 2),
            # Captação limpa: faixa P25-P75 só com 4+ revendas limpas; com
            # menos, só a mediana + "poucas vendas" (em vez de mínimo-máximo).
            "preco_p25": _round(percentile(25, valores), 2) if len(valores) >= CAPTACAO_MIN_VENDAS_FAIXA else None,
            "preco_p75": _round(percentile(75, valores), 2) if len(valores) >= CAPTACAO_MIN_VENDAS_FAIXA else None,
            "poucas_vendas": len(valores) < CAPTACAO_MIN_VENDAS_FAIXA,
            "n_planta": n_planta, "n_valor_fora_padrao": n_valor_fora_padrao,
            "area_min": area_min, "area_max": area_max,
            "tem_unidade_a_venda_hoje": tem_hoje, "unidades_a_venda_hoje": unidades_hoje,
        })

    captacao_ativa.sort(key=lambda c: (c["bairro"].lower(), -c["n_vendas"], c["addr_key"]))

    meta = {
        "enderecos_com_repeticao": n_addr_total_multi,
        "enderecos_descartados_preco": n_addr_discarded,
        "enderecos_lancamento": n_addr_launch,
        "enderecos_sem_venda_real": n_addr_sem_venda_real,
        "enderecos_captacao_ativa": len(captacao_ativa),
    }
    return liquidez, captacao_ativa, captacao_unico, meta


def _tem_unidade_a_venda_hoje(usn_recs_no_addr):
    ativos = [r for r in usn_recs_no_addr if r["situacao_code"] not in (3, 4)]  # exclui LANCAMENTO/CONSTRUCAO
    unidades = [
        {
            "codigo": r["codigo"], "valor": r["valor"], "link": r["link"],
            "idade_dias": r.get("idade_dias"),
            "anuncio_antigo": r.get("idade_dias") is not None and r["idade_dias"] > ANUNCIO_ANTIGO_DIAS,
        }
        for r in ativos
    ]
    return len(ativos) > 0, unidades


# ---------------------------------------------------------------------------
# 4b. Etapa 3 (2026-09-29) — Preço por m² pago × pedido, por bairro + tipo
# de imóvel + faixa de metragem. Toda comparação de preço do motor usa
# isso: Alertas, Valor de Oportunidade, Gap Preço do Ranking, Perfil por
# Bairro, alinhamento de preço de Prontidão/Imóveis Prioritários.
# ---------------------------------------------------------------------------
def _compute_preco_m2(itbi_records, usn_records, hoje_serial):
    """Retorna dict[bairro] = [ {tipo_imovel, faixa, mediana_pago_m2,
    mediana_pedido_m2, gap_pct, n_transacoes, n_transacoes_12m,
    n_anuncios, amostra_pequena}, ... ] — uma entrada por combinação
    (tipo_imovel, faixa) que teve pelo menos uma venda paga OU um anúncio
    pedido nesse bairro.

    Etapa 2, item 1.2d (2026-10-01): pra apartamento, R$/m² pago×pedido é
    substituído por VALOR TOTAL pago (mediana/P25/P75), só revenda
    (`r["is_revenda"]` — itbi_records já só tem revenda+planta, ver
    cascata_completa.resolver_registros_engine) — mesmo tratamento já
    aplicado em `_compute_preco_m2_painel` (item 2). Gap pedido×pago
    suspenso (None) pra apartamento — usado por `_segmento_representativo`
    pro Gap Preço do Ranking/Alertas, que portanto também fica suspenso
    pra bairros cujo segmento representativo seria um apartamento (a
    maioria — ver docstring de `_segmento_representativo`). Casa não muda
    (continua só R$/m², is_clean_sale, qualquer natureza de venda válida —
    nunca inclui planta de verdade: uso 10 é sempre revenda por
    construção, ver cascata_completa.USO_RESIDENCIAL_PLANTA)."""
    pago = {}  # (bairro, tipo, faixa) -> [(valor_m2, day), ...] -- mantido pra casa e pro n_transacoes informativo
    valor_total = {}  # (bairro, faixa) -> [valor, ...] revenda de apartamento
    for r in itbi_records:
        if not r["is_clean_sale"] or r["bairro"] not in TARGETS:
            continue
        f = faixa_metragem(r["area"])
        if f is None:
            continue
        pago.setdefault((r["bairro"], r["tipo_imovel"], f), []).append((r["valor_m2"], r["day"]))
        if r["tipo_imovel"] == "apartamento" and r.get("is_revenda"):
            valor_total.setdefault((r["bairro"], f), []).append(r["valor"])

    pedido = {}  # (bairro, tipo, faixa) -> [valor_m2, ...]
    for r in usn_records:
        if r["bairro"] not in TARGETS or r.get("tipo_imovel") is None:
            continue
        if not r["valor"] or not r["area"]:
            continue
        f = faixa_metragem(r["area"])
        if f is None:
            continue
        pedido.setdefault((r["bairro"], r["tipo_imovel"], f), []).append(r["valor"] / r["area"])

    out = {b: [] for b in TARGETS}
    for key in sorted(set(pago) | set(pedido)):
        bairro, tipo, f = key
        pago_pairs = pago.get(key, [])
        pago_vals = [v for v, _d in pago_pairs]
        n_12m = sum(1 for _v, d in pago_pairs if d is not None and 0 <= (hoje_serial - d) <= JANELA_PRECO_M2_DIAS)
        is_apto = tipo == "apartamento"

        mediana_pago = None if is_apto else (_round(median(pago_vals), 2) if pago_vals else None)
        # P25-P75 de R$/m² pago do segmento — substitui a antiga "Faixa de
        # preço pago (P25-P75)" do Perfil Vencedor (que misturava qualquer
        # tamanho dentro do bucket de metragem vencedora); agora é por
        # tipo+faixa, igual ao resto da Etapa 3. Suspenso (None) pra
        # apartamento junto com mediana_pago_m2.
        p25_pago = None if is_apto else (_round(percentile(25, pago_vals), 2) if pago_vals else None)
        p75_pago = None if is_apto else (_round(percentile(75, pago_vals), 2) if pago_vals else None)

        mediana_pedido = None
        gap_pct = None
        if not is_apto:
            pedido_vals = trim_outliers_iqr(pedido.get(key, []))
            mediana_pedido = _round(median(pedido_vals), 2) if pedido_vals else None
            if mediana_pago and mediana_pedido:
                gap_pct = _round((mediana_pedido - mediana_pago) / mediana_pago * 100, 1)

        valor_total_vals = valor_total.get((bairro, f), []) if is_apto else []
        valor_total_limpos = trim_outliers_iqr(valor_total_vals)
        valor_total_mediana = _round(median(valor_total_limpos), 2) if valor_total_limpos else None
        valor_total_p25 = _round(percentile(25, valor_total_limpos), 2) if valor_total_limpos else None
        valor_total_p75 = _round(percentile(75, valor_total_limpos), 2) if valor_total_limpos else None
        n_revenda = len(valor_total_vals)

        out[bairro].append({
            "tipo_imovel": tipo, "faixa": f,
            "mediana_pago_m2": mediana_pago, "mediana_pedido_m2": mediana_pedido, "gap_pct": gap_pct,
            "p25_pago_m2": p25_pago, "p75_pago_m2": p75_pago,
            "valor_total_mediana": valor_total_mediana if is_apto else None,
            "valor_total_p25": valor_total_p25 if is_apto else None,
            "valor_total_p75": valor_total_p75 if is_apto else None,
            "n_transacoes": len(pago_vals), "n_transacoes_12m": n_12m, "n_anuncios": len(pedido.get(key, [])),
            "amostra_pequena": (n_revenda if is_apto else n_12m) < MIN_TRANSACOES_PRECO_M2_12M,
        })
    return out


def _compute_preco_m2_painel(itbi_records, usn_records, hoje_serial):
    """Painel dedicado "Preço por m² — Pago × Pedido" (Etapa 4, 2026-09-29):
    diferente de `_compute_preco_m2` (que faz pool de 3 anos pras 5
    comparações da Etapa 3), aqui TUDO — inclusive a mediana paga — é
    escopado aos ÚLTIMOS 12 MESES, e só apartamento (o pedido explícito do
    usuário: "só apartamentos residenciais"). Um retrato do mercado AGORA,
    não uma média histórica de 3 anos. Retorna lista achatada (uma linha
    por bairro+faixa), ordenada por bairro.

    Etapa 2, item 2 (2026-10-01): R$/m² pago×pedido pra apartamento vinha
    de `is_clean_sale` (natureza+100%+tipo+outlier), sem distinguir
    revenda de planta — podia misturar lançamento fechado dentro da
    janela de 12 meses com revenda de verdade. Pedido do usuário: pra
    apartamento, trocar R$/m² pago por VALOR TOTAL pago (mediana/P25/P75)
    só de REVENDA (`_is_revenda_aprovada` — mesma regra do item 3) e
    suspender o gap pedido×pago (calibração fica pra depois). `casa` não
    passa pelo filtro `tipo_imovel != "apartamento"` desta função (nunca
    passou — já era só apartamento antes) e continua de fora, sem mudança,
    em qualquer outro lugar do motor que mostre R$/m² de casa.
    `mediana_pago_m2`/`mediana_pedido_m2`/`gap_pct` ficam sempre None
    agora (suspensos); os campos novos `valor_total_*`/`n_vendas_revenda`
    são aditivos."""
    pago = {}  # (bairro, faixa) -> [valor_m2, ...] só dos últimos 12 meses (mantido só por compatibilidade de schema)
    valor_total = {}  # (bairro, faixa) -> [valor, ...] revenda, últimos 12 meses
    for r in itbi_records:
        if r["bairro"] not in TARGETS or r["tipo_imovel"] != "apartamento":
            continue
        if r["day"] is None or not (0 <= (hoje_serial - r["day"]) <= JANELA_PRECO_M2_DIAS):
            continue
        f = faixa_metragem(r["area"])
        if f is None:
            continue
        if r["is_clean_sale"]:
            pago.setdefault((r["bairro"], f), []).append(r["valor_m2"])
        if _is_revenda_aprovada(r):
            valor_total.setdefault((r["bairro"], f), []).append(r["valor"])

    pedido = {}  # (bairro, faixa) -> [valor_m2, ...] (estoque atual, sem janela de tempo — não tem "data da venda")
    for r in usn_records:
        if r["bairro"] not in TARGETS or r.get("tipo_imovel") != "apartamento":
            continue
        if not r["valor"] or not r["area"]:
            continue
        f = faixa_metragem(r["area"])
        if f is None:
            continue
        pedido.setdefault((r["bairro"], f), []).append(r["valor"] / r["area"])

    out = []
    for bairro in TARGETS:
        for _lo, _hi, f in FAIXAS_METRAGEM:
            key = (bairro, f)
            pago_vals = pago.get(key, [])
            valor_total_vals = valor_total.get(key, [])
            if not pago_vals and not valor_total_vals and key not in pedido:
                continue

            valor_total_limpos = trim_outliers_iqr(valor_total_vals)
            valor_total_mediana = _round(median(valor_total_limpos), 2) if valor_total_limpos else None
            valor_total_p25 = _round(percentile(25, valor_total_limpos), 2) if valor_total_limpos else None
            valor_total_p75 = _round(percentile(75, valor_total_limpos), 2) if valor_total_limpos else None

            out.append({
                "bairro": bairro, "faixa": f,
                # Suspensos pra apartamento (item 2 da Etapa 2) — ver
                # docstring. Campo mantido no schema (nunca removido),
                # sempre None daqui em diante.
                "mediana_pago_m2": None, "mediana_pedido_m2": None, "gap_pct": None,
                "valor_total_mediana": valor_total_mediana,
                "valor_total_p25": valor_total_p25, "valor_total_p75": valor_total_p75,
                "n_vendas_revenda_12m": len(valor_total_vals),
                "n_transacoes_12m": len(pago_vals), "n_anuncios": len(pedido.get(key, [])),
                "amostra_pequena": len(valor_total_vals) < MIN_TRANSACOES_PRECO_M2_12M,
            })
    return out


def _segmento_representativo(segmentos):
    """Segmento (tipo+faixa) mais confiável de um bairro pra reduzir a
    matriz de segmentos a UM número por bairro (Gap Preço do Ranking,
    flag_alerta) — o de maior amostra recente entre os que têm os dois
    lados (pago e pedido), não são amostra pequena, E têm 3+ anúncios
    (MIN_ANUNCIOS_ALERTA — achado da Etapa 5: sem isso, um gap podia se
    sustentar sozinho em 1 anúncio). None se nenhum qualificar (bairro vira
    "—", não gera alerta)."""
    candidatos = [
        s for s in segmentos
        if s["gap_pct"] is not None and not s["amostra_pequena"] and s["n_anuncios"] >= MIN_ANUNCIOS_ALERTA
    ]
    if not candidatos:
        return None
    return sorted(candidatos, key=lambda s: -s["n_transacoes_12m"])[0]


def _lookup_mediana_pago_m2(segmentos_bairro, tipo_imovel, area):
    """Mediana de R$/m² pago do segmento (tipo+faixa) de UM imóvel
    específico — usado no alinhamento de preço (Prontidão/Imóveis
    Prioritários) e no Valor de Oportunidade, só pra CASA (apartamento usa
    _lookup_valor_total_mediana, ver Etapa 2 item 1.2d — R$/m² pago fica
    None pra apartamento em _compute_preco_m2). None quando o imóvel não
    tem tipo/área classificável ou o segmento é amostra pequena demais pra
    confiar (mesma regra dos Alertas)."""
    if tipo_imovel is None or not area:
        return None
    f = faixa_metragem(area)
    if f is None:
        return None
    for s in segmentos_bairro:
        if s["tipo_imovel"] == tipo_imovel and s["faixa"] == f:
            if s["amostra_pequena"] or not s["mediana_pago_m2"]:
                return None
            return s["mediana_pago_m2"]
    return None


def _lookup_valor_total_mediana(segmentos_bairro, tipo_imovel, area):
    """Mediana de VALOR TOTAL pago em revenda do segmento (faixa de
    metragem) — só apartamento.

    SUSPENSA (passo 2b, 2026-10-01): nenhum chamador usa mais esta
    função hoje — ela ainda bucketiza por faixa_metragem(area), que
    compara área CONSTRUÍDA do segmento ITBI x área ÚTIL do anúncio
    (mesma distorção do backlog de calibração de área). Mantida (não
    removida) porque o backlog prevê reviver exatamente esta lógica
    assim que existir um fator de calibração construída/útil — ver
    scripts/validate_build.check_faixa_metragem_apartamento_suspensa,
    que trava o build se ela voltar a ser chamada pra apartamento."""
    if tipo_imovel != "apartamento" or not area:
        return None
    f = faixa_metragem(area)
    if f is None:
        return None
    for s in segmentos_bairro:
        if s["tipo_imovel"] == tipo_imovel and s["faixa"] == f:
            if s["amostra_pequena"] or not s.get("valor_total_mediana"):
                return None
            return s["valor_total_mediana"]
    return None


# ---------------------------------------------------------------------------
# 5. Painel 1 — Ranking de Oportunidade (score de bairro)
# ---------------------------------------------------------------------------
def _minmax_rescale_0_100(combined):
    vals = list(combined.values())
    cmin, cmax = percentile(0, vals), percentile(100, vals)
    crange = (cmax - cmin) if (cmax is not None and cmin is not None and cmax != cmin) else 1
    return {k: (v - cmin) / crange * 100 for k, v in combined.items()}


def _score_from_volume_and_trend(volume_map, trend_z):
    vol_z = zscore_map(volume_map)
    combined = {b: (vol_z[b] + trend_z[b]) / 2 for b in vol_z}
    return _minmax_rescale_0_100(combined)


def _tercile(sorted_vals, frac):
    idx = int(len(sorted_vals) * frac)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


# ---------------------------------------------------------------------------
# 6. Painel 8 — pontuação por imóvel
# ---------------------------------------------------------------------------
def _price_alignment_score(valor, mediana):
    if mediana is None or mediana <= 0 or valor is None:
        return {"score": 50, "zone": "sem_referencia", "ratio": None}
    ratio = valor / mediana
    if ratio > 1.0:
        return {"score": max(0, 100 - (ratio - 1) * 100), "zone": "acima", "ratio": ratio}
    elif ratio >= 0.7:
        return {"score": 100, "zone": "normal", "ratio": ratio}
    else:
        s = 100 - (0.7 - ratio) * 200
        return {"score": max(30, s), "zone": "cautela", "ratio": ratio}




def _resumo_imovel(price, aderencia_final, tipo_imovel, score_revenda_bairro, n_vendas_endereco):
    frases = []
    # Passo 2b (2026-10-01): componente de preço suspenso pra apartamento
    # (ver PESOS_PAINEL8_APARTAMENTO) — mensagem fixa em vez do zone/ratio
    # de R$/m², que não existe mais pra esse tipo.
    if tipo_imovel == "apartamento":
        frases.append("Comparação indisponível para apartamentos: aguardando calibração de área")
    else:
        ratio = price["ratio"]
        if price["zone"] == "cautela" and ratio is not None:
            frases.append(f"R$/m² {round((1 - ratio) * 100)}% abaixo do histórico de imóveis do mesmo tipo/tamanho — vale checar antes de anunciar")
        elif price["zone"] == "acima" and price["score"] < 60 and ratio is not None:
            frases.append(f"R$/m² {round((ratio - 1) * 100)}% acima do que se pagou em imóveis do mesmo tipo/tamanho")
        elif price["zone"] == "normal" and ratio is not None and ratio < 0.97:
            frases.append(f"R$/m² {round((1 - ratio) * 100)}% abaixo da mediana paga em imóveis do mesmo tipo/tamanho")

    # Passo 2b: aderência agora é faixa de preço v2 (valor pago em
    # revenda, por tipo) — não tem mais conceito de "estimativa regional"
    # (esse era um reliability de área, v1).
    if aderencia_final >= 80:
        frases.append("Bate com a faixa de preço vencedora do bairro (revenda, 12m)")
    if score_revenda_bairro >= 70:
        frases.append("Bairro com liquidez de revenda alta")
    if n_vendas_endereco:
        frases.append(f"Prédio com histórico de giro comprovado ({n_vendas_endereco} vendas em 3 anos)")

    return " · ".join(frases[:2])


def _compute_imoveis_prioritarios(usn_records, bairros_out, captacao_n_vendas, unidades_por_endereco):
    out = []
    for u in usn_records:
        if u["valor"] is None or u["valor"] <= 0:
            continue
        b = bairros_out.get(u["bairro"])
        if not b:
            continue

        is_apto = u.get("tipo_imovel") == "apartamento"
        # Passo 2b (2026-10-01): componente de preço SUSPENSO pra
        # apartamento — a antiga comparação usava _lookup_valor_total_
        # mediana, que bucketiza por faixa_metragem() (área CONSTRUÍDA do
        # segmento ITBI x área ÚTIL do anúncio — mesma distorção do
        # backlog de calibração). Sem lookup nenhum até ter um fator de
        # calibração; peso redistribuído (PESOS_PAINEL8_APARTAMENTO,
        # abaixo). Casa não muda (R$/m², faixa_metragem mantida).
        if is_apto:
            price = {"score": None, "zone": "indisponivel_apartamento", "ratio": None}
        else:
            valor_comparacao = (u["valor"] / u["area"]) if u["area"] else None
            mediana_comparacao = _lookup_mediana_pago_m2(b["preco_m2_segmentos"], u.get("tipo_imovel"), u["area"])
            price = _price_alignment_score(valor_comparacao, mediana_comparacao)

        # Passo 2b: aderência migrada de area_band (v1, metragem) pra
        # faixa de preço v2 (valor pago em revenda, 12m, por tipo) — não
        # depende mais de profile_quartos/profile_vagas/*_reliability
        # (v1); v2 não tem conceito de dormitórios/vagas típicos nem de
        # confiança regional, então a pontuação é direta (sem multiplicador).
        faixa_v2 = (b.get("perfil_vencedor_faixa_preco_v2") or {}).get(u.get("tipo_imovel"))
        aderencia = 50
        if faixa_v2 and u["valor"] is not None:
            lo, hi = faixa_v2
            if lo <= u["valor"] <= hi:
                aderencia = 100
            else:
                band_width = hi - lo
                dist = (lo - u["valor"]) if u["valor"] < lo else (u["valor"] - hi)
                aderencia = max(0, 100 - (dist / band_width) * 100) if band_width > 0 else 50

        # Passo 3c (2026-10-05): bônus gradual pelo nº de vendas do
        # endereço (ver _bonus_captacao) — antes era 100 ou 0.
        n_vendas_endereco = captacao_n_vendas.get(u["addr_key"], 0) if u["addr_key"] is not None else 0
        tem_captacao = n_vendas_endereco > 0
        unidades_endereco = unidades_por_endereco.get(u["addr_key"]) if u["addr_key"] is not None else None
        bonus, regua, giro = _bonus_captacao_hibrido(n_vendas_endereco, unidades_endereco, u.get("tipo_imovel"))

        if is_apto:
            final_score = (
                PESOS_PAINEL8_APARTAMENTO["revenda"] * b["score_revenda"]
                + PESOS_PAINEL8_APARTAMENTO["aderencia"] * aderencia
                + PESOS_PAINEL8_APARTAMENTO["captacao"] * bonus
            )
        else:
            final_score = (
                PESOS_PAINEL8["revenda"] * b["score_revenda"]
                + PESOS_PAINEL8["preco"] * price["score"]
                + PESOS_PAINEL8["aderencia"] * aderencia
                + PESOS_PAINEL8["captacao"] * bonus
            )

        resumo = _resumo_imovel(price, aderencia, u.get("tipo_imovel"), b["score_revenda"], n_vendas_endereco)

        out.append({
            "bairro": u["bairro"], "endereco": u["addr_display"], "codigo": u["codigo"], "link": u["link"],
            "valor": u["valor"], "area": u["area"], "quartos": u["quartos"], "vagas": u["vagas"],
            "tipo_imovel": u.get("tipo_imovel"),
            "addr_key": u["addr_key"],
            "score_bairro_revenda": _round(b["score_revenda"]), "price_alignment": _round(price["score"]),
            # Passo 2b (2026-10-01): price_alignment é None pra apartamento
            # (componente suspenso, ver price["zone"] == "indisponivel_
            # apartamento"). area_band_reliability/profile_reliability (v1)
            # removidos daqui — não alimentam mais nada neste painel.
            "profile_adherence": _round(aderencia), "tem_captacao_ativa": tem_captacao,
            "captacao_n_vendas": n_vendas_endereco, "captacao_bonus": bonus,
            # Passo 4: qual régua gerou o bônus ("giro do prédio" ou "nº de
            # vendas"), as unidades do IPTU e o giro (só na régua de giro).
            "captacao_regua": regua, "captacao_unidades": unidades_endereco if tem_captacao else None,
            "captacao_giro_pct": _round(giro * 100, 2) if giro is not None else None,
            # Passo 3c: idade do anúncio (dias, vs horário da consulta) e
            # selo "Anúncio antigo" — nunca exclui o imóvel de nenhuma conta.
            "idade_dias": u.get("idade_dias"),
            "anuncio_antigo": u.get("idade_dias") is not None and u["idade_dias"] > ANUNCIO_ANTIGO_DIAS,
            "final_score": _round(final_score, 2), "resumo": resumo,
        })

    # Desempate por endereço (minúsculas) + código — nunca addr_key: no lado
    # JS ele é um índice inteiro interno (não a chave composta em string),
    # então usá-lo aqui faria o desempate divergir entre os dois motores.
    out.sort(key=lambda x: (-x["final_score"], (x["endereco"] or "").lower(), x["codigo"] or ""))
    return out


# ---------------------------------------------------------------------------
# 7. Painel 10 — Valor de Oportunidade
# ---------------------------------------------------------------------------
def _compute_valor_oportunidade(imoveis_prioritarios, bairros_out):
    # Etapa 3 (2026-09-29): desconto compara R$/m² do anúncio contra a
    # mediana R$/m² do MESMO tipo de imóvel + faixa de metragem no bairro
    # — não mais o valor total contra a mediana de TODOS os tamanhos do
    # bairro (achado real: apartamentos de 23-32m² no Alto da Boa Vista
    # apareciam como "77% abaixo" comparados com a mediana de 100-120m²,
    # quando na verdade R$/m² deles era CARO pro próprio tamanho). O
    # "amostra pequena" do segmento (_lookup_mediana_pago_m2 já devolve
    # None nesse caso) substitui o antigo gate por volume do bairro
    # inteiro — a regra de amostra agora é por segmento, não por bairro.
    achados = []
    elegivel_by_bairro = {}
    for im in imoveis_prioritarios:
        b = bairros_out[im["bairro"]]
        is_apto = im.get("tipo_imovel") == "apartamento"
        # Passo 2b (2026-10-01): comparação suspensa pra apartamento —
        # _lookup_valor_total_mediana bucketizava por faixa_metragem()
        # (área construída do ITBI x área útil do anúncio). Sem fator de
        # calibração ainda (ver backlog), apartamento nunca mais vira
        # achado aqui — mediana_ref/valor_ref ficam None, o gate abaixo
        # (`if mediana_ref is None...`) já pula o resto do loop pra ele.
        # Casa não muda (R$/m², faixa_metragem mantida).
        if is_apto:
            mediana_ref = None
            valor_ref = None
        else:
            mediana_ref = _lookup_mediana_pago_m2(b["preco_m2_segmentos"], im.get("tipo_imovel"), im.get("area"))
            valor_ref = (im["valor"] / im["area"]) if im.get("area") else None
        if mediana_ref is None or valor_ref is None:
            continue
        elegivel_by_bairro[im["bairro"]] = elegivel_by_bairro.get(im["bairro"], 0) + 1
        ratio = valor_ref / mediana_ref
        desconto = 1 - ratio
        if desconto < VALOR_OPORTUNIDADE_MIN_DESCONTO:
            continue
        achados.append({
            "bairro": im["bairro"], "endereco": im["endereco"], "codigo": im["codigo"], "link": im["link"],
            "valor": im["valor"], "area": im["area"], "tipo_imovel": im.get("tipo_imovel"),
            "faixa": faixa_metragem(im["area"]),
            "valor_m2": None if is_apto else _round(valor_ref, 2),
            "mediana_pago_m2": None if is_apto else mediana_ref,
            "valor_total_mediana": mediana_ref if is_apto else None,
            "desconto_pct": _round(desconto * 100, 1),
            "atencao": desconto >= VALOR_OPORTUNIDADE_ATENCAO_DESCONTO,
            "idade_dias": im.get("idade_dias"),
            "anuncio_antigo": im.get("anuncio_antigo", False),
        })
    achados.sort(key=lambda a: (-a["desconto_pct"], (a["endereco"] or "").lower(), a["codigo"] or ""))

    stock_eleg = elegivel_by_bairro
    achados_by_bairro = {}
    for a in achados:
        achados_by_bairro[a["bairro"]] = achados_by_bairro.get(a["bairro"], 0) + 1

    por_bairro = []
    for b, n in achados_by_bairro.items():
        total = stock_eleg.get(b, 0)
        por_bairro.append({
            "bairro": b, "n_achados": n, "estoque_total": total,
            "pct_do_estoque": _round(100 * n / total, 1) if total else None,
        })
    por_bairro.sort(key=lambda x: (-x["n_achados"], x["bairro"].lower()))

    # estoque_elegivel_por_bairro cobre TODOS os bairros com estoque
    # elegível (não só os com achado) — usado pelo f6 da Prontidão pra não
    # recalcular elegibilidade com um critério diferente (achado real: até
    # 2026-09-29 o f6 usava o gate antigo por volume do bairro inteiro,
    # inconsistente com o gate por segmento usado aqui).
    return {"imoveis": achados, "por_bairro": por_bairro, "estoque_elegivel_por_bairro": elegivel_by_bairro}


# ---------------------------------------------------------------------------
# 8. Painel 7 — Captação Ativa Estratégica
# ---------------------------------------------------------------------------
def _compute_captacao_estrategica(captacao_ativa, captacao_unico, bairros_out):
    # Mudança 13: NÃO exclui mais endereços que já têm unidade anunciada
    # hoje — um prédio com giro comprovado continua valendo a visita pra
    # tentar captar OUTRAS unidades, mesmo com uma já ativa. A informação
    # "já tem anúncio ativo" vira um dado exibido (não um filtro de
    # exclusão), pra quem for a campo decidir com contexto, não pra
    # dashboard decidir por ele.
    by_bairro_ativa = {}
    for c in captacao_ativa:
        by_bairro_ativa.setdefault(c["bairro"], []).append(c)
    by_bairro_unico = {}
    for c in captacao_unico:
        by_bairro_unico.setdefault(c["bairro"], []).append(c)

    groups = []
    for b in TARGETS:
        enderecos = list(by_bairro_ativa.get(b, []))
        used_unico = False
        if len(enderecos) < CAPTACAO_ESTRATEGICA_MIN_ENDERECOS:
            extra = by_bairro_unico.get(b, [])
            if extra:
                enderecos = enderecos + [{**e, "unico": True} for e in extra]
                used_unico = True
        if not enderecos:
            continue
        for e in enderecos:
            e.setdefault("unico", False)
        # Sem unidade ativa primeiro (só esse prospecção resolve o acesso);
        # dentro de cada grupo, mais vendas primeiro, depois alfabético.
        # Desempate por texto em minúsculas — evita divergir do lado JS,
        # que usa comparação case-insensitive (localeCompare); comparação
        # padrão de string é sensível a maiúscula/minúscula nos dois lados.
        enderecos.sort(key=lambda e: (e["tem_unidade_a_venda_hoje"], -e["n_vendas"], e["endereco"].lower()))

        bo = bairros_out[b]
        groups.append({
            "bairro": b,
            "selo_escassez_real": bo["selo_escassez_real"],
            # Passo 2 (2026-10-01): perfil migrado pra faixa de preço v2
            # (valor pago em revenda, por tipo) — v1 (area_band/
            # price_band/profile_quartos/profile_vagas/
            # profile_reliability) não é mais lido aqui. v2 não tem
            # conceito de dormitórios/vagas típicos (é só faixa de
            # preço) — essa informação sai do cabeçalho do grupo (ver
            # relatório, item 1a).
            "perfil": {
                "faixa_preco": bo["perfil_vencedor_faixa_preco_v2"],
                "estoque_perfil_faixa_preco": bo["estoque_perfil_faixa_preco"],
                "estoque_fora_do_perfil": bo["estoque_fora_do_perfil"],
            },
            "enderecos": [
                {"endereco": e["endereco"], "n_vendas": e["n_vendas"], "preco_mediana": e["preco_mediana"],
                 "preco_p25": e["preco_p25"], "preco_p75": e["preco_p75"], "poucas_vendas": e["poucas_vendas"],
                 "n_planta": e["n_planta"], "n_valor_fora_padrao": e["n_valor_fora_padrao"],
                 "area_min": e["area_min"], "area_max": e["area_max"],
                 "unico": e["unico"], "tem_unidade_a_venda_hoje": e["tem_unidade_a_venda_hoje"],
                 "unidades_a_venda_hoje": e["unidades_a_venda_hoje"]}
                for e in enderecos
            ],
            "_used_unico_fallback": used_unico,
        })

    groups.sort(key=lambda g: (
        0 if g["selo_escassez_real"] else (1 if g["perfil"]["estoque_fora_do_perfil"] else 2),
        -bairros_out[g["bairro"]]["volume_primary_year"],
        g["bairro"].lower(),
    ))
    for g in groups:
        g.pop("_used_unico_fallback", None)
    return groups


# ---------------------------------------------------------------------------
# Orquestração principal
# ---------------------------------------------------------------------------
def compute(itbi_records, usn_records, years, carteira_77_bairros, periodo_12m_externo, unidades_por_endereco=None):
    """years: lista de 3 anos ascendente, ex: [2024, 2025, 2026].
    carteira_77_bairros: dict bairro -> {unidades_iptu, giro_12m_pct, ...}
    de cascata_completa.gerar_dados_carteira_77()['bairros'] — fonte
    única de unidades IPTU/giro (dado do IPTU, não do ITBI; calculado só
    lá pra não reprocessar o cadastro do GeoSampa de novo aqui).
    periodo_12m_externo: (periodo_12m, periodo_12m_anterior,
    meses_incompletos) já calculado por cascata_completa.
    resolver_registros_engine() sobre TODOS os registros antes de
    classificar revenda/planta — ver _compute_volume_12m, item 1.1 da
    Etapa 2 (precisa ser o MESMO período de carteira_77, senão
    revenda_12m/planta_12m divergem — pego pelo teste de consistência).
    unidades_por_endereco: dict addr_key -> nº de unidades residenciais do
    IPTU 2026 (cascata_completa.unidades_por_endereco) — alimenta a régua de
    giro do bônus de captação (Passo 4); vazio = tudo pela régua de vendas."""
    year_prev, year_full, year_curr = years

    yearly, pairs_all_years, month_counts, pooled_median = _aggregate_itbi(itbi_records, years)
    trend = _compute_trend(yearly, month_counts, year_prev, year_full, year_curr)
    (
        volume_12m_map, trend_pct_12m_map, periodo_12m_meta, volume_recente_parcial_map,
        volume_mercado_12m_map, trend_pct_mercado_12m_map, volume_retomadas_12m_map,
        revenda_12m_map, revenda_12m_anterior_map, planta_12m_map,
        volume_mercado_12m_anterior_map,
    ) = _compute_volume_12m(itbi_records, periodo_externo=periodo_12m_externo)

    # Etapa 2, item 1 (2026-10-01, decisão de mercado pós-revisão): o
    # score do Ranking/"Onde anunciar agora" usa SÓ revenda_12m como
    # volume e tendência — não mais volume_mercado_12m (revenda+planta).
    # Motivo: pra Buyer Agent, a liquidez que importa é a REVENDA; o top
    # 10 anterior (volume_mercado_12m) ficava dominado por bairros com um
    # único lançamento grande (Lapa 3.089 de planta, Chácara Santo
    # Antônio 3.104, Alto da Boa Vista 1.078 majoritariamente de 1
    # empreendimento no CEP 04750) — não é liquidez de revenda de
    # verdade. planta_12m continua calculado e exposto (campo
    # "Lançamentos (12m)" nos painéis), só não entra mais no score.
    #
    # Etapa 2, item 3 (2026-10-01): tendência só entra no score se o
    # bairro tiver >= MIN_VENDAS_TENDENCIA vendas de REVENDA em CADA uma
    # das duas janelas (atual e anterior) comparadas; abaixo disso,
    # tendência = neutra (0) — evita um bairro pequeno subir no Ranking
    # só por uma variação de poucas vendas virar um % enorme (achado do
    # usuário: Jardim da Glória, 34 vendas, "tendência" de +78,9%).
    # trend_z resultante é compartilhado pelo score principal e por
    # score_revenda (mesmo insumo agora, arquitetura mais simples).
    trend_frac_revenda_12m_capped = {}
    trend_pct_revenda_12m_map = {}
    amostra_pequena_ranking_map = {}
    for b in TARGETS:
        atual = revenda_12m_map[b]
        anterior = revenda_12m_anterior_map[b]
        if atual >= MIN_VENDAS_TENDENCIA and anterior >= MIN_VENDAS_TENDENCIA and anterior > 0:
            frac = (atual - anterior) / anterior
            trend_frac_revenda_12m_capped[b] = max(-TREND_CAP, min(TREND_CAP, frac))
            trend_pct_revenda_12m_map[b] = _round(frac * 100, 1)
        else:
            trend_frac_revenda_12m_capped[b] = 0.0
            trend_pct_revenda_12m_map[b] = None
        # Regra de amostra mínima (item 3): < 100 REVENDAS em 12m (não
        # mercado) não entra no top 10 de "Onde anunciar agora" e mostra
        # o selo "Amostra pequena" no Ranking.
        amostra_pequena_ranking_map[b] = atual < MIN_VENDAS_TOP10

    usn_by_bairro, centroids, stock_total, asking_median = _aggregate_usn(usn_records)
    profile = _compute_profile(pairs_all_years, usn_by_bairro, centroids)
    perfil_preco_v2 = _compute_perfil_vencedor_faixa_preco_v2(itbi_records, periodo_12m_externo[0], usn_by_bairro)
    hoje_serial = today_excel_serial()
    preco_m2 = _compute_preco_m2(itbi_records, usn_records, hoje_serial)
    preco_m2_painel = _compute_preco_m2_painel(itbi_records, usn_records, hoje_serial)

    usn_by_addr_key = {}
    for r in usn_records:
        if r["addr_key"]:
            usn_by_addr_key.setdefault(r["addr_key"], []).append(r)

    # Passo 3c: % do estoque do bairro com mais de 365 dias de cadastro
    # (denominador = só anúncios com data de cadastro conhecida; None se
    # nenhum tiver — ex.: export manual .xlsx não traz a data).
    estoque_antigo_n, estoque_antigo_pct = {}, {}
    for b in TARGETS:
        com_data = [r for r in usn_by_bairro[b] if r.get("idade_dias") is not None]
        antigos = sum(1 for r in com_data if r["idade_dias"] > ANUNCIO_ANTIGO_DIAS)
        estoque_antigo_n[b] = antigos
        estoque_antigo_pct[b] = _round(100 * antigos / len(com_data), 1) if com_data else None

    liquidez, captacao_ativa, captacao_unico, liquidez_meta = _compute_liquidez(itbi_records, usn_by_addr_key, years)
    addr_in_captacao_ativa = {c["addr_key"]: c["n_vendas"] for c in captacao_ativa}

    # --- montagem preliminar por bairro (sem os campos que dependem de score cross-bairro) ---
    bairros_out = {}
    for b in TARGETS:
        # Volume/liquidez "de referência" (Ranking, Prontidão, Estoque×
        # Demanda) = média anual dos 3 anos, não só o último fechado
        # (decisão do usuário, 2026-09-25) — soma bruta dos 3 anos
        # distorceria a unidade "vendas por ano" usada nos limiares/razões
        # abaixo, já que 2026 (ano em andamento) tem menos meses que os
        # outros dois; a média preserva a leitura "por ano" com amostra
        # maior e mais estável.
        volume_primary = round(mean([yearly[b][y]["count"] for y in years]))
        # stock_match (v1, metragem) MANTIDO só pro campo obsoleto
        # stock_matching_profile (ver nota abaixo) — não entra mais na
        # razão Estoque×Demanda nem em flag_prioridade_maxima.
        stock_match = profile[b]["profile_sample_size"]
        # Passo 2 (2026-10-01): numerador do Estoque×Demanda migrado pra
        # v2 (faixa de preço, por tipo) — mesmo motivo do Prontidão: o
        # bucket de metragem (v1) herda a distorção área construída x
        # área útil. demand continua revenda_12m (Etapa 2, item 1).
        stock_match_v2 = perfil_preco_v2[b]["profile_sample_size_faixa_preco_v2"]
        demand = revenda_12m_map[b]
        ratio = (stock_match_v2 / demand) if demand > 0 else (999 if stock_match_v2 > 0 else 0)

        paid_median = pooled_median[b]["median_valor"]
        asking = asking_median[b]
        # Gap Preço do Ranking / flag_alerta (Etapa 3, 2026-09-29): não é
        # mais "pedido do bairro inteiro" x "pago do bairro inteiro" — é o
        # gap do segmento (tipo+faixa) mais representativo desse bairro
        # (mais transações recentes, entre os que não são amostra pequena).
        # Ver preco_m2_segmentos pra granularidade completa por segmento.
        segmento_rep = _segmento_representativo(preco_m2[b])
        price_gap_pct = segmento_rep["gap_pct"] if segmento_rep else None

        bairros_out[b] = {
            "yearly": {str(y): yearly[b][y] for y in years},
            **trend[b],
            "volume_primary_year": volume_primary,
            # Item 4 da auditoria de 2026-09-30: campos novos, aditivos —
            # volume_primary_year/trend_pct acima ficam obsoletos (mas com
            # o MESMO cálculo de sempre, ver README) até remoção aprovada
            # numa versão futura. volume_12m/trend_pct_12m usam data real
            # da transação + janela rolante de 12 meses completos — ver
            # periodo_12m no retorno de compute() pro período exato.
            "volume_12m": volume_12m_map[b],
            "trend_pct_12m": trend_pct_12m_map[b],
            # Indicador separado, informativo — NÃO entra em volume_12m/
            # trend_pct_12m: contagem dos 2 meses mais recentes com dado
            # (periodo_12m.meses_incompletos), ainda sujeitos a defasagem
            # de guia paga com atraso.
            "volume_recente_parcial": volume_recente_parcial_map[b],
            # Item 2 da auditoria de 2026-09-30: volume_mercado_12m ("1.Compra
            # e venda" só) vira o número PRINCIPAL de liquidez exibido nos
            # painéis (decisão do usuário); volume_12m (giro, qualquer
            # natureza) passa a aparecer como informação secundária.
            # volume_retomadas_12m (alienação fiduciária + leilão) é um
            # indicador à parte, não somado em nenhum dos dois acima.
            "volume_mercado_12m": volume_mercado_12m_map[b],
            "trend_pct_mercado_12m": trend_pct_mercado_12m_map[b],
            "volume_retomadas_12m": volume_retomadas_12m_map[b],
            "preco_m2_segmentos": preco_m2[b],
            # OBSOLETO (passo 2, 2026-10-01): area_band/price_band/
            # profile_quartos/profile_vagas/profile_sample_size/
            # area_band_reliability/area_band_neighbors/profile_
            # reliability/profile_neighbors/profile_pool_sample_size/
            # stock_matching_profile são o sistema de perfil vencedor POR
            # METRAGEM (v1) — herdam a distorção área construída (ITBI) x
            # área útil (anúncio). Nenhum painel deveria mais LER esses
            # campos pra decidir nada (ver scripts/validate_build.
            # check_perfil_v1_obsoleto) — mantidos só porque "Perfil por
            # Bairro" (painel 3) ainda os EXIBE como estão (não migrado
            # nesta rodada, é o painel que descreve o v1 por definição) e
            # _compute_imoveis_prioritarios (Painel 8, "aderência") ainda
            # os USA (fora do escopo do passo 2 — reportado, não
            # corrigido, ver relatório). Remoção só em versão futura, com
            # aprovação do usuário.
            "area_band": profile[b]["area_band"], "price_band": profile[b]["price_band"],
            "price_band_median": profile[b]["price_band_median"],
            "profile_quartos": profile[b]["profile_quartos"], "profile_vagas": profile[b]["profile_vagas"],
            "profile_sample_size": profile[b]["profile_sample_size"],
            "area_band_reliability": profile[b]["area_band_reliability"],
            "area_band_neighbors": profile[b]["area_band_neighbors"],
            "profile_reliability": profile[b]["profile_reliability"],
            "profile_neighbors": profile[b]["profile_neighbors"],
            "profile_pool_sample_size": profile[b]["profile_pool_sample_size"],
            "stock_total": stock_total[b], "stock_matching_profile": stock_match,
            # Revisão 2026-10-01 (v2): estoque no perfil vencedor por
            # FAIXA DE PREÇO vem do valor pago em revenda (12m, por tipo
            # de imóvel), não mais do bucket de metragem — ver
            # _compute_perfil_vencedor_faixa_preco_v2. Passo 2: agora
            # também alimenta a razão Estoque×Demanda (stock_demand_ratio,
            # acima) e flag_prioridade_maxima (abaixo), além do f2 do
            # Prontidão e do shortlist_google_ads.csv — os 3 painéis que
            # ainda liam stock_matching_profile/area_band (v1) migraram
            # nesta rodada.
            "estoque_perfil_faixa_preco": perfil_preco_v2[b]["profile_sample_size_faixa_preco_v2"],
            "perfil_vencedor_faixa_preco_v2": perfil_preco_v2[b]["bandas"],
            # Passo 3c: estoque_fora_do_perfil/selo_escassez_real são
            # preenchidos mais abaixo (precisam do tercil de estoque
            # total/demanda, calculado só depois de todos os bairros).
            "estoque_antigo_365d": estoque_antigo_n[b],
            "estoque_antigo_365d_pct": estoque_antigo_pct[b],
            "asking_median_valor": asking, "paid_median_valor_primary_year": paid_median,
            "centroid": list(centroids[b]) if centroids[b] else None,
            "stock_demand_ratio": round(ratio, 3), "price_gap_pct": price_gap_pct,
            "flag_alerta": price_gap_pct is not None and abs(price_gap_pct) >= 20,
            "liquidez_total_primary_year": round(mean([liquidez[b][y]["total"] for y in years])),
            "liquidez_revenda_primary_year": round(mean([liquidez[b][y]["revenda"] for y in years])),
            "liquidez_por_ano": {str(y): liquidez[b][y] for y in years},
            # Etapa 2, item 1 (2026-10-01): base nova — carteira de 77,
            # revenda/planta separadas (regra aprovada, não mais detecção
            # de lançamento por endereço), unidades/giro do IPTU (fonte
            # única: carteira_77_bairros, ver docstring de compute()).
            # Bate EXATO com data["carteira_77"] — checado em
            # validate_build.check_consistencia_carteira_77.
            "revenda_12m": revenda_12m_map[b],
            "planta_12m": planta_12m_map[b],
            "unidades_iptu": carteira_77_bairros[b]["unidades_iptu"],
            "giro_12m_pct": carteira_77_bairros[b]["giro_12m_pct"],
            "trend_pct_revenda_12m": trend_pct_revenda_12m_map[b],
            "amostra_pequena_ranking": amostra_pequena_ranking_map[b],
        }

    # --- Painel 1: score (volume + tendência) — Etapa 2, item 1 (revisão
    # 2026-10-01, decisão de mercado): volume e tendência do score agora
    # são SÓ revenda_12m/trend_frac_revenda_12m_capped — não mais
    # volume_mercado_12m (revenda+planta). planta_12m continua exposto
    # como indicador separado ("Lançamentos 12m"), sem peso no score.
    # Mesmos pesos de sempre (50% volume + 50% tendência, ver
    # _score_from_volume_and_trend).
    #
    # Nota: com essa mudança, `score` e `score_revenda` (abaixo) usam
    # exatamente o mesmo insumo (revenda_12m + trend_frac_revenda_12m_
    # capped) e ficam matematicamente idênticos — consequência direta e
    # esperada da decisão (antes, score usava volume_mercado_12m e
    # score_revenda já usava revenda_12m, por isso divergiam). Mantidos
    # como dois campos (painéis diferentes os leem por nome: Ranking lê
    # `score`, Imóveis Prioritários/Mapa leem `score_revenda`), não
    # fundidos — simplificar pra um campo só é decisão de produto, fora
    # do escopo desta migração.
    volume_map = {b: bairros_out[b]["revenda_12m"] for b in TARGETS}
    trend_z_input = trend_frac_revenda_12m_capped
    trend_z = zscore_map(trend_z_input)
    score_map = _score_from_volume_and_trend(volume_map, trend_z)

    ratios_sorted = sorted(bairros_out[b]["stock_demand_ratio"] for b in TARGETS)
    low_tercile = _tercile(ratios_sorted, 1 / 3)

    # --- score_revenda (mesma fórmula, mesmo insumo que `score` agora — ver nota acima) ---
    revenda_map = {b: bairros_out[b]["revenda_12m"] for b in TARGETS}
    revenda_z = zscore_map(revenda_map)
    combined_revenda = {b: (revenda_z[b] + trend_z[b]) / 2 for b in TARGETS}
    score_revenda_map = _minmax_rescale_0_100(combined_revenda)

    # --- Índice de Saturação de Oferta (estoque TOTAL, tercil superior) ---
    total_ratio_map = {}
    for b in TARGETS:
        demand = bairros_out[b]["revenda_12m"]
        st = bairros_out[b]["stock_total"]
        total_ratio_map[b] = (st / demand) if demand > 0 else (999 if st > 0 else 0)
    total_ratios_sorted = sorted(total_ratio_map.values())
    high_tercile = _tercile(total_ratios_sorted, 2 / 3)
    # Passo 3c: limiar do selo "Escassez real" — terço mais baixo da razão
    # estoque total / revendas 12m entre os 77 bairros (sempre sobre o
    # universo inteiro, nunca recalculado por filtro de tela — ver
    # raw.json constants.limiar_escassez_real).
    limiar_escassez_real = _tercile(total_ratios_sorted, 1 / 3)

    for b in TARGETS:
        bairros_out[b]["score"] = _round(score_map[b])
        bairros_out[b]["flag_oportunidade"] = (
            bairros_out[b]["stock_demand_ratio"] <= low_tercile and bairros_out[b]["revenda_12m"] > 0
        )
        bairros_out[b]["score_revenda"] = _round(score_revenda_map[b])
        bairros_out[b]["stock_total_demand_ratio"] = round(total_ratio_map[b], 3)
        bairros_out[b]["flag_saturacao_alta"] = total_ratio_map[b] >= high_tercile
        # Passo 3c (2026-10-05): "Prioridade Máxima" dividida em dois
        # selos que NUNCA acendem juntos. Os dois só existem pra bairro
        # com >= 100 revendas em 12m (mesma régua do Ranking, nada de
        # amostra pequena) E com no máximo 2 anúncios dentro da faixa de
        # preço v2:
        #   - Escassez real: o bairro INTEIRO tem pouco anúncio frente à
        #     demanda (estoque total / revendas 12m no terço mais baixo
        #     dos 77 bairros — limiar_escassez_real).
        #   - Estoque fora do perfil: tem estoque ativo suficiente no
        #     bairro, mas quase nada na faixa de preço que de fato vende.
        elegivel_selo = (
            not bairros_out[b]["amostra_pequena_ranking"]
            and bairros_out[b]["estoque_perfil_faixa_preco"] <= CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH
        )
        escassez = elegivel_selo and total_ratio_map[b] <= limiar_escassez_real
        bairros_out[b]["selo_escassez_real"] = escassez
        bairros_out[b]["estoque_fora_do_perfil"] = elegivel_selo and not escassez and bairros_out[b]["stock_total"] > 0

    ranking = sorted(TARGETS, key=lambda b: -bairros_out[b]["score"])

    # --- Painel 8: imóveis prioritários ---
    imoveis_prioritarios = _compute_imoveis_prioritarios(usn_records, bairros_out, addr_in_captacao_ativa, unidades_por_endereco or {})

    # --- Painel 2: Prontidão para Campanha ---
    # Etapa 2, revisão 2026-10-01: f2 agora usa estoque_perfil_faixa_preco
    # (faixa de preço, valor total) em vez de stock_matching_profile
    # (metragem) — ver nota em _compute_profile/bairros_out acima.
    f2_map = normalize_0_100({b: bairros_out[b]["estoque_perfil_faixa_preco"] for b in TARGETS})
    f4_counts = {b: 0 for b in TARGETS}
    for c in captacao_ativa:
        f4_counts[c["bairro"]] += 1
    f4_map = normalize_0_100(f4_counts)

    imoveis_by_bairro = {}
    for im in imoveis_prioritarios:
        imoveis_by_bairro.setdefault(im["bairro"], []).append(im)

    for b in TARGETS:
        f1 = bairros_out[b]["score"]
        f2 = f2_map[b]
        gap = bairros_out[b]["price_gap_pct"]
        f3 = max(0, 100 - abs(gap) * 2) if gap is not None else 50
        f4 = f4_map[b]

        top10 = imoveis_by_bairro.get(b, [])[:10]
        n_im = len(imoveis_by_bairro.get(b, []))
        mean_top10 = mean([t["final_score"] for t in top10]) if top10 else 0
        coverage = min(1, n_im / 10)
        f5 = mean_top10 * coverage

        bairros_out[b]["_f1_f5"] = (f1, f2, f3, f4, f5)

    valor_oportunidade = _compute_valor_oportunidade(imoveis_prioritarios, bairros_out)
    achados_by_bairro_count = {}
    for a in valor_oportunidade["imoveis"]:
        achados_by_bairro_count[a["bairro"]] = achados_by_bairro_count.get(a["bairro"], 0) + 1

    estoque_elegivel = valor_oportunidade["estoque_elegivel_por_bairro"]
    for b in TARGETS:
        f1, f2, f3, f4, f5 = bairros_out[b].pop("_f1_f5")
        # f6 usa a MESMA elegibilidade por segmento do Valor de
        # Oportunidade (Etapa 3, 2026-09-29) — antes recalculava com o
        # gate antigo por volume do bairro inteiro, inconsistente com o
        # critério real usado pra gerar os achados.
        estoque_eleg = estoque_elegivel.get(b, 0)
        if estoque_eleg == 0:
            f6 = 50
        else:
            achados_bairro = achados_by_bairro_count.get(b, 0)
            f6 = 100 * achados_bairro / estoque_eleg

        prontidao = (
            PESOS_PRONTIDAO["f1"] * f1 + PESOS_PRONTIDAO["f2"] * f2 + PESOS_PRONTIDAO["f3"] * f3
            + PESOS_PRONTIDAO["f4"] * f4 + PESOS_PRONTIDAO["f5"] * f5 + PESOS_PRONTIDAO["f6"] * f6
        )
        bairros_out[b]["prontidao_campanha"] = _round(prontidao)

    # Etapa 2, revisão 2026-10-01: mesma regra de amostra mínima do
    # Ranking (item 3 da Etapa 2) — bairro com amostra_pequena_ranking
    # (< 100 revendas em 12m) nunca ocupa posição de topo, mesmo que o
    # score numérico de prontidão seja alto (score calculado sobre pouca
    # amostra não é confiável). Ordena primeiro por "não é amostra
    # pequena" (False < True), depois por prontidão decrescente.
    prontidao_ranking = sorted(
        TARGETS,
        key=lambda b: (bairros_out[b]["amostra_pequena_ranking"], -bairros_out[b]["prontidao_campanha"]),
    )

    captacao_estrategica = _compute_captacao_estrategica(captacao_ativa, captacao_unico, bairros_out)

    return {
        "meta": {
            "years": years,
            "primary_year": year_full,
            "inprogress_year": year_curr,
            "limiar_escassez_real": limiar_escassez_real,
            **liquidez_meta,
        },
        "periodo_12m": periodo_12m_meta,
        "ranking": ranking,
        "prontidao_ranking": prontidao_ranking,
        "bairros": bairros_out,
        "captacao_ativa": captacao_ativa,
        "imoveis_prioritarios": imoveis_prioritarios,
        "valor_oportunidade": valor_oportunidade,
        "captacao_estrategica": captacao_estrategica,
        "preco_m2_painel": preco_m2_painel,
    }
