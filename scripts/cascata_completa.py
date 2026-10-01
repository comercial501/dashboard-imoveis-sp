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


def carregar_itbi_deduplicado():
    year_to_path = {y: itbi_source.RAW_DIR / f"{y}.xlsx" for y in YEARS}
    records, stats = parse_itbi_years(year_to_path)
    print(f"[itbi] {stats}")
    records, dedup_stats = dedup_by_sql(records, log=lambda *a, **k: None)
    print(f"[itbi] dedup: entrada={dedup_stats['total_entrada']} saida={dedup_stats['total_saida']}")
    # build_clean_layer só pra ganhar o campo `tipo_imovel` (usado por
    # engine._is_valid_sale) — não resolvemos bairro por maioria (clean_itbi.
    # resolve_bairros), então o agrupamento de outlier por bairro+tipo+faixa
    # aqui dentro fica irrelevante (maioria cai no mesmo grupo None) e
    # inofensivo: não usamos `is_clean_sale`/`valor_m2` neste script.
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


def classificar_revenda_planta_aprovada(records_12m):
    """Regra aprovada pelo usuário (2026-09-30). Universo: natureza
    "1.Compra e venda" + unidade de verdade (uso residencial, não prédio
    inteiro — mesmo `tipo_imovel is not None` de clean_itbi/engine).
      REVENDA = proporção transmitida = 100% (is_full_transfer) E valor
        plausível (clean_itbi.VALOR_MIN_REAL..VALOR_MAX_REAL — mesmo corte
        que build_clean_layer já aplicava só dentro do ramo 100%).
      PLANTA = proporção transmitida < 100% E (complemento contém AP/
        APTO/APART/TORRE/BLOCO/CASA/UNIDADE OU financiamento é MCMV/SFH).
      Resto (100% com valor irreal, OU <100% sem nenhum sinal de planta —
        provavelmente fração de herança/divórcio) fica de fora das duas,
        devolvido em buckets separados pro relatório.
    Retorna dict com as 4 listas: revenda, planta, valor_irreal,
    fracao_sem_sinal_planta."""
    revenda, planta, valor_irreal, fracao_sem_sinal = [], [], [], []
    for r in records_12m:
        if not r["is_compra_venda"] or r["tipo_imovel"] is None:
            continue
        if r["is_full_transfer"]:
            if clean_itbi.VALOR_MIN_REAL <= r["valor"] <= clean_itbi.VALOR_MAX_REAL:
                revenda.append(r)
            else:
                valor_irreal.append(r)
        else:
            if _tem_token_unidade(r.get("complemento")) or _financiamento_mcmv_sfh(r.get("tipo_financiamento")):
                planta.append(r)
            else:
                fracao_sem_sinal.append(r)
    return {
        "revenda": revenda, "planta": planta,
        "valor_irreal": valor_irreal, "fracao_sem_sinal_planta": fracao_sem_sinal,
    }


# --- universo de unidades do IPTU (giro) ------------------------------------
def carregar_unidades_iptu():
    """Lê o cadastro reduzido do IPTU, filtra TIPOS_RESIDENCIAIS (apto +
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


def resolver_universo_itbi(cascata, records):
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
    for r in records:
        destino, metodo = cascata.resolver(r["bairro_raw"], r["addr_key"], r["cep"], _sq_itbi(r))
        metodos[metodo] = metodos.get(metodo, 0) + 1
        if metodo == "fora_carteira":
            fora += 1
        elif metodo == "incerto":
            incerto += 1
        elif destino:
            contagem[destino] = contagem.get(destino, 0) + 1
    return contagem, fora, incerto, metodos


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


def rodar(usar_split_santo_amaro, label):
    print(f"\n########## RODADA: {label} ##########")
    tradutor = tb.carregar_tradutor()
    targets = tb.targets_carteira(tradutor)
    print(f"[tradutor] carteira: {len(targets)}")

    split = tb.carregar_split_santo_amaro() if usar_split_santo_amaro else None
    if usar_split_santo_amaro and not split:
        print("[AVISO] usar_split_santo_amaro=True mas santo_amaro_split_resolvido.csv não existe/vazio")

    fabrica_cascata = montar_cascata(tradutor, targets, split)

    itbi_dedup = carregar_itbi_deduplicado()
    periodo_12m, _, _ = engine._mes_base_e_periodo(itbi_dedup)
    print(f"[periodo] 12m: {periodo_12m[0]}..{periodo_12m[-1]}")
    itbi_12m = filtrar_janela_12m(itbi_dedup, periodo_12m)
    print(f"[universo] total 12m (qualquer natureza, dedup): {len(itbi_12m)}")

    # --- coluna "antes": regra antiga (endereço + lançamento), recomputada
    # com código commitado (nunca mais um script descartável) ---
    classificacao_antiga = classificar_enderecos_regra_antiga(itbi_dedup)
    revenda_antiga, planta_antiga = separar_revenda_planta_regra_antiga(itbi_12m, classificacao_antiga)
    antes_combinado = revenda_antiga + planta_antiga
    print(f"[regra antiga/antes] revenda={len(revenda_antiga)} planta={len(planta_antiga)} combinado={len(antes_combinado)}")

    # --- coluna "depois": regra aprovada (proporção transmitida + sinal
    # de unidade/financiamento no complemento) ---
    buckets = classificar_revenda_planta_aprovada(itbi_12m)
    revenda, planta = buckets["revenda"], buckets["planta"]
    n_valor_irreal = len(buckets["valor_irreal"])
    n_fracao_sem_sinal = len(buckets["fracao_sem_sinal_planta"])
    universo_valido = len(revenda) + len(planta) + n_valor_irreal + n_fracao_sem_sinal
    fora_do_universo = len(itbi_12m) - universo_valido
    print(
        f"[regra aprovada/depois] revenda={len(revenda)} planta={len(planta)} "
        f"valor_irreal(100% mas fora de R${clean_itbi.VALOR_MIN_REAL:,.0f}-R${clean_itbi.VALOR_MAX_REAL:,.0f})={n_valor_irreal} "
        f"fracao_sem_sinal_planta(<100% sem AP/TORRE/BLOCO/CASA/UNIDADE/MCMV/SFH)={n_fracao_sem_sinal} "
        f"fora_do_universo(natureza != compra_venda ou prédio inteiro)={fora_do_universo}"
    )

    cascata_antes = fabrica_cascata()
    contagem_antes, fora_antes, incerto_antes, _ = resolver_universo_itbi(cascata_antes, antes_combinado)

    cascata_revenda = fabrica_cascata()
    contagem_revenda, fora_r, incerto_r, _ = resolver_universo_itbi(cascata_revenda, revenda)

    cascata_planta = fabrica_cascata()
    contagem_planta, fora_p, incerto_p, _ = resolver_universo_itbi(cascata_planta, planta)

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

    return {
        "targets": targets,
        "antes": contagem_antes, "revenda": contagem_revenda, "planta": contagem_planta, "unidades": contagem_unidades,
        "fechamento": {
            "antes": (len(antes_combinado), sum(contagem_antes.values()), fora_antes, incerto_antes),
            "revenda": (len(revenda), sum(contagem_revenda.values()), fora_r, incerto_r),
            "planta": (len(planta), sum(contagem_planta.values()), fora_p, incerto_p),
            "unidades": (len(unidades), sum(contagem_unidades.values()), fora_u, incerto_u),
        },
    }


if __name__ == "__main__":
    import sys as _sys
    label = _sys.argv[1] if len(_sys.argv) > 1 else "com_split"
    usar_split = label != "sem_split"
    rodar(usar_split, label)
