#!/usr/bin/env python3
"""
Item 3 (2026-09-30) — versão final: resolve bairro de mercado (dos 77) pra
TODO o universo de vendas ITBI (revenda e planta, janela de 12 meses) e
unidades residenciais do IPTU (taxa de giro), usando:
  - tradutor_bairro.Cascata (tabela de tradução por nome de cadastro +
    voto de endereço + quadra fiscal + CEP, 5 métodos)
  - a divisão de "Santo Amaro" por CEP (scripts/santo_amaro_split_resolvido.csv,
    gerado por resolver_santo_amaro.py a partir do CSV que o usuário
    preencheu)

CLASSIFICAÇÃO REVENDA × PLANTA (regra aprovada em 2026-09-30, ver
classificar_revenda_planta_aprovada) — substitui a régua por
endereço/lançamento (classificar_enderecos_regra_antiga, mantida só pra
gerar a coluna "antes" da comparação, reproduzível porque agora é código
commitado): aquela régua classificava errado — condomínio grande e antigo
virava "lançamento" só por ter 5+ vendas em 182 dias (Tatuapé: planta de
803 pra 2.026), e lançamento pequeno/lento virava "revenda".

Cada universo (revenda, planta, unidades IPTU) constrói seus PRÓPRIOS
votos de endereço/CEP (nunca cruza entre si) — só a quadra fiscal (`votos_
quadra_resolvidos`, inerentemente um dado do IPTU) e a tabela de tradução
são compartilhadas entre os 3, conforme protocolo já aprovado.
"""
import functools
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clean_itbi
import engine
import itbi_source
import iptu_geosampa as ig
import tradutor_bairro as tb
from clean_itbi import build_clean_layer, dedup_by_sql
from normalize import excel_serial_to_ym, normalize_number, normalize_street
from parse_itbi import parse_itbi_years

YEARS = [2024, 2025, 2026]


def _cep8(raw):
    digits = re.sub(r"\D", "", raw or "")
    return digits.zfill(8) if digits else None


def _parsear_e_dedupe_itbi():
    """Parse com `somente_uso_residencial=False` (item 3, ponto 1, achado
    do usuário: venda na planta é registrada no ITBI com o uso do
    LOTE-MÃE — terreno, indústria, loja etc., quase nunca um uso
    residencial) + dedup por SQL — SEM build_clean_layer (que precisa do
    bairro já resolvido pra agrupar o corte de outlier corretamente; ver
    resolver_registros_engine, que resolve bairro ANTES de chamar
    build_clean_layer)."""
    year_to_path = {y: itbi_source.RAW_DIR / f"{y}.xlsx" for y in YEARS}
    records, parse_stats = parse_itbi_years(year_to_path, somente_uso_residencial=False)
    print(f"[itbi] {parse_stats}")
    records, dedup_stats = dedup_by_sql(records, log=lambda *a, **k: None)
    print(f"[itbi] dedup: entrada={dedup_stats['total_entrada']} saida={dedup_stats['total_saida']}")
    return records, parse_stats, dedup_stats


def carregar_itbi_deduplicado():
    """Mesmo parse+dedup de `_parsear_e_dedupe_itbi()`, mais
    `build_clean_layer` só pra ganhar o campo `tipo_imovel` (usado pela
    regra antiga, via engine._is_valid_sale, e por uso_code na regra
    aprovada). Usado pelas rodadas de comparação/relatório deste módulo
    (`rodar`, `gerar_dados_carteira_77`, export de valor pago), que nunca
    usam `is_clean_sale`/`valor_m2` — então o fato de build_clean_layer
    agrupar o corte de outlier por um bairro ainda não resolvido (maioria
    cai no mesmo grupo None) é irrelevante aqui. `resolver_registros_
    engine()` (consumido por engine.py, que USA is_clean_sale pros
    painéis de preço) NÃO usa esta função — chama
    `_parsear_e_dedupe_itbi()` direto e só roda build_clean_layer depois
    de resolver o bairro, pra esse corte funcionar de verdade."""
    records, _parse_stats, _dedup_stats = _parsear_e_dedupe_itbi()
    records, _ = build_clean_layer(records, log=lambda *a, **k: None)
    return records


def classificar_enderecos_regra_antiga(records):
    """REGRA ANTIGA (rejeitada pelo usuário em 2026-09-30 — mantida só
    pra gerar a coluna "antes" da comparação, com código commitado em vez
    do script descartável que gerou o número original): addr_key ->
    "revenda" | "planta". Endereço com 5+ vendas válidas (engine.
    _is_valid_sale) dentro de uma janela de 182 dias (engine._is_launch) é
    lançamento/planta; resto é revenda. Problema encontrado pelo usuário:
    classifica condomínio grande e antigo como lançamento só por ter 5+
    vendas espalhadas em 182 dias, e lançamento pequeno/lento como
    revenda — ver classificar_revenda_planta_aprovada() pra regra certa."""
    by_addr = {}
    for r in records:
        if r["addr_key"]:
            by_addr.setdefault(r["addr_key"], []).append(r)

    out = {}
    for addr_key, recs_all in by_addr.items():
        recs = [r for r in recs_all if engine._is_valid_sale(r)]
        if len(recs) >= 5 and engine._is_launch([r["day"] for r in recs]):
            out[addr_key] = "planta"
        else:
            out[addr_key] = "revenda"
    return out


def filtrar_janela_12m(records, periodo_12m):
    periodo_set = set(periodo_12m)
    out = []
    for r in records:
        if r["day"] is None:
            continue
        ym = excel_serial_to_ym(r["day"])
        if ym in periodo_set:
            out.append(r)
    return out


def separar_revenda_planta_regra_antiga(records_12m, classificacao):
    revenda, planta = [], []
    for r in records_12m:
        c = classificacao.get(r["addr_key"], "revenda")
        if c == "planta":
            planta.append(r)
        else:
            revenda.append(r)
    return revenda, planta


# --- regra aprovada em 2026-09-30 (ver docstring do módulo) -----------------
PLANTA_COMPLEMENTO_TOKENS = {"AP", "APTO", "APART", "TORRE", "BLOCO", "CASA", "UNIDADE"}
_TOKEN_RE = re.compile(r"[^A-Z0-9]+")
# "Tipo de Financiamento" (coluna O): "1.Sistema Financeiro de Habitação"
# (SFH) e "2.Minha Casa Minha Vida" (MCMV) são os 2 tipos relevantes aqui
# (os outros, "3.Consórcio" e "99.SFI, Carteira Hipotecária, etc", não
# entram na regra do usuário).
FINANCIAMENTO_MCMV_SFH_RE = re.compile(r"^[12]\.")


def _tem_token_unidade(complemento):
    if not complemento:
        return False
    toks = _TOKEN_RE.split(complemento.strip().upper())
    return any(t in PLANTA_COMPLEMENTO_TOKENS for t in toks)


def _financiamento_mcmv_sfh(tipo_financiamento):
    return bool(tipo_financiamento) and bool(FINANCIAMENTO_MCMV_SFH_RE.match(tipo_financiamento))


# "Uso residencial" PRA ESTA CLASSIFICAÇÃO = só 10 (residência) e 20
# (apartamento em condomínio) — mais estreito que clean_itbi.
# TIPO_IMOVEL_POR_USO (que também inclui 12/14/21/22/25) de propósito:
# regra explícita do usuário (2026-09-30, revisão 2), porque venda na
# planta é registrada com o uso do LOTE-MÃE (quase sempre != 10/20) e
# revenda de unidade pronta é registrada com o uso da PRÓPRIA unidade
# (10/20).
USO_RESIDENCIAL_PLANTA = {"10", "20"}


def classificar_revenda_planta_aprovada(records_12m_todos_usos):
    """Regra aprovada pelo usuário (2026-09-30, revisão 2 — a revisão 1
    exigia só "proporção<100%" pra planta e foi rejeitada: 74-85% das
    vendas com financiamento MCMV/SFH ou com token de unidade no
    complemento têm proporção=100%, e a venda na planta é registrada com
    o uso do LOTE-MÃE, não residencial — a revisão 1 descartava a imensa
    maioria das plantas de verdade ANTES mesmo de chegar aqui, porque o
    parse só capturava uso residencial). `records_12m_todos_usos` deve
    vir de um parse com `somente_uso_residencial=False`.

    Universo: natureza "1.Compra e venda", qualquer uso.
      REVENDA = proporção transmitida = 100% E uso IPTU residencial
        (10/20 — ver USO_RESIDENCIAL_PLANTA).
      PLANTA = proporção transmitida < 100% E uso IPTU NÃO residencial
        (!= 10/20) E (complemento contém AP/APTO/APART/TORRE/BLOCO/CASA/
        UNIDADE OU financiamento é MCMV/SFH).
      PARCIAL = proporção < 100% E uso residencial (10/20) — fração ideal
        de herança/divórcio, fora das duas.
      DEMAIS = toda outra combinação (100% E uso não-residencial; <100%
        E uso não-residencial SEM nenhum sinal de planta) — também fora
        das duas.
    Retorna dict com as 4 listas: revenda, planta, parcial, demais."""
    revenda, planta, parcial, demais = [], [], [], []
    for r in records_12m_todos_usos:
        if not r["is_compra_venda"]:
            continue
        uso_residencial = r.get("uso_code") in USO_RESIDENCIAL_PLANTA
        if r["is_full_transfer"]:
            if uso_residencial:
                revenda.append(r)
            else:
                demais.append(r)
        else:
            if uso_residencial:
                parcial.append(r)
            elif _tem_token_unidade(r.get("complemento")) or _financiamento_mcmv_sfh(r.get("tipo_financiamento")):
                planta.append(r)
            else:
                demais.append(r)
    return {"revenda": revenda, "planta": planta, "parcial": parcial, "demais": demais}


def amostrar_planta_sfh_sem_token(planta_recs, n=20, seed=42):
    """20 exemplos aleatórios de planta capturada SÓ pelo financiamento
    SFH/MCMV (sem token de unidade no complemento) — pedido do usuário
    (2026-09-30) pra conferir que esses ~13 mil casos/ano são mesmo
    unidade nova (ex: complemento tipo "2204 (R2V-1)", "300", sem AP/
    TORRE/BLOCO) e não um falso positivo do financiamento."""
    import random

    candidatos = [r for r in planta_recs if not _tem_token_unidade(r.get("complemento"))]
    rng = random.Random(seed)
    amostra = rng.sample(candidatos, min(n, len(candidatos)))
    return [
        {
            "endereco": r.get("addr_display") or f"{r.get('bairro_raw')} (sem endereço)",
            "complemento": r.get("complemento"),
            "uso_code": r.get("uso_code"),
            "proporcao_100pct": r["is_full_transfer"],
            "tipo_financiamento": r.get("tipo_financiamento"),
            "bairro_raw": r.get("bairro_raw"),
        }
        for r in amostra
    ]


# --- universo de unidades do IPTU (giro) ------------------------------------
@functools.lru_cache(maxsize=1)
def carregar_unidades_iptu():
    """(Memoizada: lida uma vez só por execução — tanto a carteira_77 quanto
    unidades_por_endereco() usam a mesma lista, nenhum chamador a altera.)
    Lê o cadastro reduzido do IPTU, filtra TIPOS_RESIDENCIAIS (apto +
    residência), devolve registros no shape esperado pela Cascata
    (bairro_raw, addr_key, cep, sq, num_norm)."""
    import csv
    import gzip

    out = []
    with gzip.open(ig.REDUZIDO_GZ, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("tipo_uso") not in ig.TIPOS_RESIDENCIAIS:
                continue
            logradouro = normalize_street(row.get("logradouro"))
            numero = normalize_number(row.get("numero"))
            num_norm = numero if numero else ig.NUM_PLACEHOLDER
            akey = f"{logradouro}|{numero}" if logradouro and numero else None
            out.append({
                "bairro_raw": row.get("bairro"),
                "addr_key": akey,
                "cep": row.get("cep"),
                "sq": ig.setor_quadra_de_sql(row.get("sql")),
                "num_norm": num_norm,
            })
    return out


def unidades_por_endereco():
    """Passo 4 (2026-10-05): nº de unidades residenciais (apto + residência)
    do cadastro do IPTU 2026 por endereço (mesma chave rua|número do ITBI e
    da nonStop, normalize.address_key) — base do bônus de captação por giro
    relativo do prédio (vendas em 3 anos / unidades). Endereço ausente aqui
    = sem casamento com o IPTU."""
    contagem = {}
    for u in carregar_unidades_iptu():
        if u["addr_key"]:
            contagem[u["addr_key"]] = contagem.get(u["addr_key"], 0) + 1
    return contagem


# --- orquestração -----------------------------------------------------------
def montar_cascata(tradutor, targets, split_santo_amaro):
    print("[cascata] carregando quadras (qualquer bairro, p/ fora_carteira x incerto)...")
    quadras_qualquer_bairro = set(ig.construir_votos_quadra().keys())
    print(f"  quadras com ALGUM bairro (qualquer): {len(quadras_qualquer_bairro)}")

    print("[cascata] construindo votos de quadra traduzidos (com split de Santo Amaro)...")
    votos_quadra_resolvidos = tb.construir_votos_quadra_traduzido(tradutor, split_santo_amaro=split_santo_amaro)

    return lambda: tb.Cascata(
        tradutor, targets, votos_quadra_resolvidos,
        quadras_qualquer_bairro=quadras_qualquer_bairro,
        split_santo_amaro=split_santo_amaro,
    )


def _sq_itbi(r):
    # r["sql"] já é o SQL normalizado de 11 dígitos (parse_itbi.normalize_sql
    # roda no parse) — setor+quadra são sempre os 6 primeiros dígitos.
    sql = r.get("sql")
    return sql[:6] if sql else None


def _rkey(r):
    """Chave estável pra casar o MESMO record entre universos diferentes
    (ex: "revenda regra antiga" x "revenda regra aprovada") — mesma
    combinação usada por clean_itbi.dedup_by_sql, então é única dentro de
    cada lista (pós-dedup)."""
    return (r.get("sql"), r.get("day"), round(r["valor"], 2), r.get("complemento") or "")


def resolver_universo_itbi(cascata, records):
    """Retorna (contagem_por_bairro, fora, incerto, metodos, resolucao)
    — `resolucao` é {rkey: (destino, metodo)} pra permitir comparar o
    destino de um MESMO record entre duas rodadas (ver
    decompor_quedas_revenda)."""
    cascata.alimentar_votos(
        records,
        get_bairro_raw=lambda r: r["bairro_raw"],
        get_addr_key=lambda r: r["addr_key"],
        get_cep=lambda r: r["cep"],
        get_num_norm=lambda r: None,
    )
    contagem = {}
    metodos = {}
    fora = 0
    incerto = 0
    resolucao = {}
    for r in records:
        destino, metodo = cascata.resolver(r["bairro_raw"], r["addr_key"], r["cep"], _sq_itbi(r))
        metodos[metodo] = metodos.get(metodo, 0) + 1
        resolucao[_rkey(r)] = (destino, metodo)
        if metodo == "fora_carteira":
            fora += 1
        elif metodo == "incerto":
            incerto += 1
        elif destino:
            contagem[destino] = contagem.get(destino, 0) + 1
    return contagem, fora, incerto, metodos, resolucao


def resolver_universo_itbi_votos_separados(cascata, records_para_votos, records_para_resolver):
    """Como resolver_universo_itbi, mas os votos de endereço/CEP são
    construídos só a partir de `records_para_votos` (não precisa ser a
    mesma lista que vai ser resolvida).

    Revisão 2026-10-01 (item 2 da revisão da Etapa 2): `records_para_
    votos` agora é SEMPRE o universo de 3 anos inteiros (revenda/planta
    de todos os anos), nos DOIS caminhos que usam essa função —
    gerar_dados_carteira_77()/rodar() (vota com 3 anos, resolve só a
    janela de 12m) e resolver_registros_engine() (vota com 3 anos,
    resolve os 3 anos — na prática equivale a resolver_universo_itbi
    simples, já que agora vota e resolve são o mesmo universo lá).
    Motivo: com o pool de votos restrito a 12m (versão anterior), uma
    venda antiga (fora da janela de 12m) num endereço/CEP sem NENHUMA
    venda recente perdia o voto do bairro certo e podia cair em
    vizinho/fora_carteira — isso encolhe artificialmente a contagem do
    "ano anterior" da tendência, inflando a tendência calculada
    (principalmente em bairros pequenos — achado do usuário: Jardim das
    Acácias, 127 vendas, tendência de +69,3%, parte dela gerada por
    exatamente esse artefato). Pool de 3 anos em ambos os lados também
    mantém o teste de consistência passando (mesmos votos, resultado
    idêntico pra quem só olha a fatia de 12m).

    Retorna (contagem_por_bairro, fora, incerto, metodos, resolucao) —
    mesmo formato de resolver_universo_itbi, calculado só sobre
    `records_para_resolver`."""
    cascata.alimentar_votos(
        records_para_votos,
        get_bairro_raw=lambda r: r["bairro_raw"],
        get_addr_key=lambda r: r["addr_key"],
        get_cep=lambda r: r["cep"],
        get_num_norm=lambda r: None,
    )
    contagem = {}
    metodos = {}
    fora = 0
    incerto = 0
    resolucao = {}
    for r in records_para_resolver:
        destino, metodo = cascata.resolver(r["bairro_raw"], r["addr_key"], r["cep"], _sq_itbi(r))
        metodos[metodo] = metodos.get(metodo, 0) + 1
        resolucao[_rkey(r)] = (destino, metodo)
        if metodo == "fora_carteira":
            fora += 1
        elif metodo == "incerto":
            incerto += 1
        elif destino:
            contagem[destino] = contagem.get(destino, 0) + 1
    return contagem, fora, incerto, metodos, resolucao


def resolver_universo_iptu(cascata, registros):
    cascata.alimentar_votos(
        registros,
        get_bairro_raw=lambda r: r["bairro_raw"],
        get_addr_key=lambda r: r["addr_key"],
        get_cep=lambda r: r["cep"],
        get_num_norm=lambda r: r["num_norm"],
    )
    contagem = {}
    fora = incerto = 0
    for r in registros:
        destino, metodo = cascata.resolver(r["bairro_raw"], r["addr_key"], r["cep"], r["sq"], num_norm=r["num_norm"])
        if metodo == "fora_carteira":
            fora += 1
        elif metodo == "incerto":
            incerto += 1
        elif destino:
            contagem[destino] = contagem.get(destino, 0) + 1
    return contagem, fora, incerto


def decompor_quedas_revenda(revenda_antiga, revenda_nova, resolucao_antiga, resolucao_nova, buckets_novos, limiar=0.25):
    """Pra cada bairro com queda de revenda (antiga -> nova) acima de
    `limiar`, decompõe quanto vem de (a) o record ter SAÍDO do balde
    revenda (foi pra planta/parcial/demais na regra nova) vs (b) o record
    ter CONTINUADO revenda mas mudado de bairro resolvido (efeito da
    cascata, não da regra de classificação). `buckets_novos` é o dict de
    classificar_revenda_planta_aprovada() (pra saber pra qual balde foi
    quem saiu de revenda)."""
    keys_revenda_nova = {_rkey(r) for r in revenda_nova}
    keys_planta_nova = {_rkey(r) for r in buckets_novos["planta"]}
    keys_parcial_nova = {_rkey(r) for r in buckets_novos["parcial"]}
    keys_demais_nova = {_rkey(r) for r in buckets_novos["demais"]}

    por_bairro_antigo = {}
    for r in revenda_antiga:
        destino, metodo = resolucao_antiga.get(_rkey(r), (None, None))
        if destino:
            por_bairro_antigo.setdefault(destino, []).append(r)

    out = []
    for bairro, recs_antigos in por_bairro_antigo.items():
        old_total = len(recs_antigos)
        rkeys_antigos = {_rkey(r) for r in recs_antigos}
        unchanged = reassigned = 0
        foi_planta = foi_parcial = foi_demais = fora_do_universo = 0
        for rk in rkeys_antigos:
            if rk in keys_revenda_nova:
                destino_novo, _ = resolucao_nova.get(rk, (None, None))
                if destino_novo == bairro:
                    unchanged += 1
                else:
                    reassigned += 1
            elif rk in keys_planta_nova:
                foi_planta += 1
            elif rk in keys_parcial_nova:
                foi_parcial += 1
            elif rk in keys_demais_nova:
                foi_demais += 1
            else:
                fora_do_universo += 1
        new_total = sum(1 for rk in rkeys_antigos if resolucao_nova.get(rk, (None, None))[0] == bairro) + sum(
            1 for r in revenda_nova if resolucao_nova.get(_rkey(r), (None, None))[0] == bairro and _rkey(r) not in rkeys_antigos
        )
        queda_pct = (old_total - new_total) / old_total if old_total else 0
        if queda_pct >= limiar:
            out.append({
                "bairro": bairro, "old_total": old_total, "new_total": new_total, "queda_pct": queda_pct,
                "unchanged": unchanged, "reassigned_outro_bairro": reassigned,
                "saiu_planta": foi_planta, "saiu_parcial": foi_parcial, "saiu_demais": foi_demais,
                "saiu_fora_do_universo": fora_do_universo,
            })
    out.sort(key=lambda d: -d["queda_pct"])
    return out


def rodar(usar_split_santo_amaro, label):
    print(f"\n########## RODADA: {label} ##########")
    tradutor = tb.carregar_tradutor()
    targets = tb.targets_carteira(tradutor)
    print(f"[tradutor] carteira: {len(targets)}")

    split = tb.carregar_split_santo_amaro() if usar_split_santo_amaro else None
    if usar_split_santo_amaro and not split:
        print("[AVISO] usar_split_santo_amaro=True mas santo_amaro_split_resolvido.csv não existe/vazio")

    fabrica_cascata = montar_cascata(tradutor, targets, split)

    itbi_dedup_todos = carregar_itbi_deduplicado()
    periodo_12m, _, _ = engine._mes_base_e_periodo(itbi_dedup_todos)
    print(f"[periodo] 12m: {periodo_12m[0]}..{periodo_12m[-1]}")
    itbi_12m_todos = filtrar_janela_12m(itbi_dedup_todos, periodo_12m)
    print(f"[universo] total 12m (qualquer natureza/uso, dedup): {len(itbi_12m_todos)}")

    # --- coluna "antes": regra antiga (endereço + lançamento), recomputada
    # com código commitado (nunca mais um script descartável) — mesmo
    # escopo de sempre (só uso residencial via tipo_imovel), senão as
    # linhas de uso não-residencial (que só entraram agora pra alimentar a
    # regra nova) inflariam o "antes" incorretamente.
    itbi_dedup_residencial = [r for r in itbi_dedup_todos if r["tipo_imovel"] is not None]
    itbi_12m_residencial = [r for r in itbi_12m_todos if r["tipo_imovel"] is not None]
    classificacao_antiga = classificar_enderecos_regra_antiga(itbi_dedup_residencial)
    revenda_antiga, planta_antiga = separar_revenda_planta_regra_antiga(itbi_12m_residencial, classificacao_antiga)
    antes_combinado = revenda_antiga + planta_antiga
    print(f"[regra antiga/antes] revenda={len(revenda_antiga)} planta={len(planta_antiga)} combinado={len(antes_combinado)}")

    # --- coluna "depois": regra aprovada (revisão 2 — uso do lote-mãe) ---
    # Revisão 2026-10-01 (item 2 da revisão da Etapa 2): classifica sobre
    # TODOS OS ANOS (itbi_dedup_todos, não mais só itbi_12m_todos) — os
    # votos de endereço/CEP (abaixo) precisam vir do universo de 3 anos
    # inteiro, não só da janela de 12m; ver resolver_registros_engine()
    # para o motivo (achado do usuário: venda antiga num endereço sem
    # venda recente perdia o voto do bairro certo e caía em vizinho/fora,
    # encolhendo artificialmente o "ano anterior" da tendência — Jardim
    # das Acácias, +69,3%). revenda_12m/planta_12m (as métricas da
    # carteira_77) continuam sendo só a fatia de 12m, filtrada depois de
    # classificar — resolvida com votos de 3 anos.
    buckets_todos_anos = classificar_revenda_planta_aprovada(itbi_dedup_todos)
    revenda_todos_anos, planta_todos_anos = buckets_todos_anos["revenda"], buckets_todos_anos["planta"]
    revenda_12m_alvo = filtrar_janela_12m(revenda_todos_anos, periodo_12m)
    planta_12m_alvo = filtrar_janela_12m(planta_todos_anos, periodo_12m)
    # buckets (nome mantido pros prints de fechamento abaixo, que são só
    # sobre o universo de 12m) — reclassifica só pra manter os contadores
    # de parcial/demais/fora_do_universo no mesmo escopo de sempre.
    buckets = classificar_revenda_planta_aprovada(itbi_12m_todos)
    revenda, planta = revenda_12m_alvo, planta_12m_alvo
    n_parcial = len(buckets["parcial"])
    n_demais = len(buckets["demais"])
    soma_buckets = len(revenda) + len(planta) + n_parcial + n_demais
    fora_do_universo = len(itbi_12m_todos) - soma_buckets
    print(
        f"[regra aprovada/depois] revenda={len(revenda)} planta={len(planta)} "
        f"parcial(<100% uso residencial — herança/divórcio)={n_parcial} "
        f"demais(100% uso não-residencial, ou <100% uso não-residencial sem sinal)={n_demais} "
        f"fora_do_universo(natureza != compra_venda)={fora_do_universo}"
    )

    print("\n=== 20 exemplos de planta via SFH/MCMV sem token de unidade no complemento ===")
    for ex in amostrar_planta_sfh_sem_token(planta):
        print(
            f"  {ex['endereco']} | complemento={ex['complemento']!r} | uso={ex['uso_code']} "
            f"| financiamento={ex['tipo_financiamento']!r} | bairro_raw={ex['bairro_raw']!r}"
        )

    cascata_antes = fabrica_cascata()
    contagem_antes, fora_antes, incerto_antes, _, _ = resolver_universo_itbi(cascata_antes, antes_combinado)

    # revenda da regra ANTIGA resolvida SOZINHA (não combinada com
    # planta_antiga) — só pra decompor a queda de revenda por bairro
    # (ver abaixo); a coluna "antes" da tabela principal continua usando
    # o combinado acima.
    cascata_revenda_antiga = fabrica_cascata()
    _, _, _, _, resolucao_revenda_antiga = resolver_universo_itbi(cascata_revenda_antiga, revenda_antiga)

    # Revisão 2026-10-01: votos construídos com revenda/planta de TODOS
    # OS ANOS (revenda_todos_anos/planta_todos_anos), resolvendo só a
    # fatia de 12m (revenda/planta acima, já filtradas) — ver docstring
    # de resolver_universo_itbi_votos_separados.
    cascata_revenda = fabrica_cascata()
    contagem_revenda, fora_r, incerto_r, _, resolucao_revenda = resolver_universo_itbi_votos_separados(
        cascata_revenda, revenda_todos_anos, revenda
    )

    cascata_planta = fabrica_cascata()
    contagem_planta, fora_p, incerto_p, _, _ = resolver_universo_itbi_votos_separados(
        cascata_planta, planta_todos_anos, planta
    )

    print("[iptu] carregando unidades residenciais (apto + residência)...")
    unidades = carregar_unidades_iptu()
    print(f"[iptu] unidades residenciais: {len(unidades)}")
    cascata_unidades = fabrica_cascata()
    contagem_unidades, fora_u, incerto_u = resolver_universo_iptu(cascata_unidades, unidades)

    def _fechamento(nome, total, soma, fora, incerto):
        print(
            f"{nome:<9}: total={total} carteira={soma} ({100*soma/total:.1f}%) "
            f"fora={fora} ({100*fora/total:.1f}%) incerto={incerto} ({100*incerto/total:.1f}%)"
        )

    print(f"\n=== FECHAMENTO ({label}) ===")
    _fechamento("ANTES", len(antes_combinado), sum(contagem_antes.values()), fora_antes, incerto_antes)
    _fechamento("REVENDA", len(revenda), sum(contagem_revenda.values()), fora_r, incerto_r)
    _fechamento("PLANTA", len(planta), sum(contagem_planta.values()), fora_p, incerto_p)
    _fechamento("UNIDADES", len(unidades), sum(contagem_unidades.values()), fora_u, incerto_u)

    print(f"\n=== TODOS OS {len(targets)} (antes|depois_revenda|depois_planta|unidades|giro%) ===")
    linhas = []
    for b in targets:
        antes = contagem_antes.get(b, 0)
        rv = contagem_revenda.get(b, 0)
        pl = contagem_planta.get(b, 0)
        un = contagem_unidades.get(b, 0)
        giro = (100 * rv / un) if un else None
        linhas.append((b, antes, rv, pl, un, giro))
    for b, antes, rv, pl, un, giro in linhas:
        giro_s = f"{giro:.2f}%" if giro is not None else "—"
        print(f"{b}|{antes}|{rv}|{pl}|{un}|{giro_s}")

    print("\n=== GIRO ACIMA DE 10% (revenda/unidades) ===")
    acima10 = [(b, giro) for b, _, _, _, un, giro in linhas if un and giro is not None and giro > 10.0]
    if not acima10:
        print("  nenhum bairro acima de 10%")
    else:
        for b, giro in sorted(acima10, key=lambda x: -x[1]):
            print(f"  {b}: {giro:.2f}%")

    print("\n=== QUEDAS DE REVENDA (regra antiga PURA x aprovada), decomposição — >=25% marcado com * ===")
    # limiar=0 pra devolver TODOS os bairros (não só >=25%) — permite
    # conferir pontualmente qualquer bairro citado no relatório (ex:
    # Brooklin/Campo Belo, que no RELATÓRIO ANTERIOR pareciam cair >25%
    # mas isso comparava "antes" (revenda+planta antigos COMBINADOS) com
    # "depois revenda" só — uma comparação não-equivalente; aqui "antigo"
    # é revenda PURA (sem planta_antiga junto), resolvida sozinha.
    quedas = decompor_quedas_revenda(revenda_antiga, revenda, resolucao_revenda_antiga, resolucao_revenda, buckets, limiar=-1.0)
    for d in sorted(quedas, key=lambda d: -d["queda_pct"]):
        marca = "*" if d["queda_pct"] >= 0.25 else " "
        print(
            f"  {marca} {d['bairro']}: {d['old_total']} -> {d['new_total']} (queda {d['queda_pct']*100:.1f}%) | "
            f"continuou revenda mesmo bairro={d['unchanged']} | revenda mas mudou de bairro={d['reassigned_outro_bairro']} | "
            f"saiu pra planta={d['saiu_planta']} parcial={d['saiu_parcial']} demais={d['saiu_demais']} "
            f"fora_universo={d['saiu_fora_do_universo']}"
        )

    return {
        "targets": targets,
        "periodo_12m": {"inicio": f"{periodo_12m[0][0]:04d}-{periodo_12m[0][1]:02d}", "fim": f"{periodo_12m[-1][0]:04d}-{periodo_12m[-1][1]:02d}"},
        "antes": contagem_antes, "revenda": contagem_revenda, "planta": contagem_planta, "unidades": contagem_unidades,
        "fechamento": {
            "antes": (len(antes_combinado), sum(contagem_antes.values()), fora_antes, incerto_antes),
            "revenda": (len(revenda), sum(contagem_revenda.values()), fora_r, incerto_r),
            "planta": (len(planta), sum(contagem_planta.values()), fora_p, incerto_p),
            "unidades": (len(unidades), sum(contagem_unidades.values()), fora_u, incerto_u),
        },
        "quedas_revenda": quedas,
    }


def gerar_dados_carteira_77():
    """Empacota a saída de rodar() no formato que build_data.py grava em
    site/data.json (chave nova `carteira_77`, aditiva — não mexe em
    nenhuma chave existente). Painel estático (não recalcula com os
    filtros de preço/bairro do resto do site — ver README, seção Item 3:
    implementação no engine.py/engine.js)."""
    resultado = rodar(usar_split_santo_amaro=True, label="producao")
    targets = resultado["targets"]

    def _fech(nome):
        total, soma, fora, incerto = resultado["fechamento"][nome]
        return {
            "total": total, "carteira": soma,
            "carteira_pct": round(100 * soma / total, 1) if total else None,
            "fora_pct": round(100 * fora / total, 1) if total else None,
            "incerto_pct": round(100 * incerto / total, 1) if total else None,
        }

    bairros = {}
    for b in targets:
        rv = resultado["revenda"].get(b, 0)
        pl = resultado["planta"].get(b, 0)
        un = resultado["unidades"].get(b, 0)
        bairros[b] = {
            "revenda_12m": rv, "planta_12m": pl, "unidades_iptu": un,
            "giro_12m_pct": round(100 * rv / un, 2) if un else None,
        }

    return {
        "metodologia_versao": "2026-09-30-item3-v3",
        "periodo_12m": resultado["periodo_12m"],
        "bairros": bairros,
        "fechamento": {
            "revenda": _fech("revenda"),
            "planta": _fech("planta"),
            "unidades": _fech("unidades"),
        },
    }


def resolver_registros_engine():
    """Item 1 da Etapa 2 (2026-10-01): resolve bairro (carteira de 77) +
    marca is_revenda/is_planta em TODOS OS ANOS (não só a janela de 12
    meses — engine.py precisa do histórico multi-ano pra tendência/preço
    pooled) de registros ITBI, usando a MESMA tabela de tradução + split
    de Santo Amaro + cascata de 5 métodos de gerar_dados_carteira_77() —
    mesmas funções, mesmos parâmetros, determinístico, então o resultado
    AQUI bate exatamente com o de gerar_dados_carteira_77() quando ambos
    são restritos à mesma janela de 12 meses (ver validate_build.
    check_consistencia_carteira_77, que garante isso continuar verdade).

    Registros que não são revenda nem planta aprovada (fração ideal de
    herança/divórcio, natureza != compra e venda, etc.) ficam de fora —
    não entram mais em nenhum painel do motor (decisão explícita do
    usuário: a base nova é "revenda/planta separadas", não "qualquer
    transação residencial" como o sistema antigo).

    Retorna (records, targets, stats) — `records` é a lista de dicts no
    mesmo formato de parse_itbi.py (todos os campos originais
    preservados, via spread), mais `bairro` (um dos 77, nunca None — já
    filtrado), `is_revenda`, `is_planta`. `stats` tem `total_rows_seen`
    (pra validate_build.check_linhas_lidas — idêntico independente de
    somente_uso_residencial, contado antes desse filtro) e contagens de
    revenda/planta/fora_ou_incerto."""
    tradutor = tb.carregar_tradutor()
    targets = tb.targets_carteira(tradutor)
    split = tb.carregar_split_santo_amaro()
    fabrica_cascata = montar_cascata(tradutor, targets, split)

    itbi_dedup_todos, parse_stats, dedup_stats = _parsear_e_dedupe_itbi()

    # Mesmo período de gerar_dados_carteira_77()/rodar() (que chama
    # _mes_base_e_periodo sobre itbi_dedup_todos ANTES de classificar) —
    # ver nota em engine._compute_volume_12m sobre por que isso precisa
    # ser idêntico nos dois lados.
    periodo_externo = engine._mes_base_e_periodo(itbi_dedup_todos)

    buckets = classificar_revenda_planta_aprovada(itbi_dedup_todos)
    print(f"[engine] revenda(todos os anos)={len(buckets['revenda'])} planta(todos os anos)={len(buckets['planta'])}")

    # Revisão 2026-10-01 (item 2 da revisão da Etapa 2): os votos de
    # endereço/CEP agora vêm de TODOS OS ANOS (mesmo universo de 3 anos
    # que vai ser resolvido aqui, e o MESMO universo de votos que
    # gerar_dados_carteira_77()/rodar() agora usa — ver docstring de
    # resolver_universo_itbi_votos_separados). Antes, os votos vinham só
    # da janela de 12m: uma venda antiga num endereço/CEP sem venda
    # recente perdia o voto do bairro certo e podia cair em vizinho/fora,
    # encolhendo artificialmente o "ano anterior" da tendência do
    # Ranking. Como aqui vota e resolve são o mesmo universo, isso
    # equivale a resolver_universo_itbi simples — mantido como
    # resolver_universo_itbi_votos_separados(x, x, y) só pra reusar a
    # mesma função (e o mesmo contrato de retorno) nos dois caminhos.
    cascata_revenda = fabrica_cascata()
    _, _, _, _, resolucao_revenda = resolver_universo_itbi_votos_separados(
        cascata_revenda, buckets["revenda"], buckets["revenda"]
    )

    cascata_planta = fabrica_cascata()
    _, _, _, _, resolucao_planta = resolver_universo_itbi_votos_separados(
        cascata_planta, buckets["planta"], buckets["planta"]
    )

    out = []
    fora_ou_incerto = 0
    for r in buckets["revenda"]:
        destino, _metodo = resolucao_revenda.get(_rkey(r), (None, None))
        if destino is None:
            fora_ou_incerto += 1
            continue
        out.append({**r, "bairro": destino, "is_revenda": True, "is_planta": False})
    for r in buckets["planta"]:
        destino, _metodo = resolucao_planta.get(_rkey(r), (None, None))
        if destino is None:
            fora_ou_incerto += 1
            continue
        out.append({**r, "bairro": destino, "is_revenda": False, "is_planta": True})
    print(f"[engine] registros na carteira (77): {len(out)} | fora_carteira/incerto: {fora_ou_incerto}")
    stats = {
        "total_rows_seen": parse_stats["total_rows_seen"],
        "total_rows_matched_todos_usos": parse_stats["total_rows_matched"],
        "duplicatas_removidas": dedup_stats["duplicatas_removidas"],
        "revenda_todos_anos": len(buckets["revenda"]),
        "planta_todos_anos": len(buckets["planta"]),
        "fora_carteira_ou_incerto": fora_ou_incerto,
    }
    return out, targets, stats, periodo_externo


if __name__ == "__main__":
    import sys as _sys
    label = _sys.argv[1] if len(_sys.argv) > 1 else "com_split"
    usar_split = label != "sem_split"
    rodar(usar_split, label)
