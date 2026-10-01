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

Cada universo (revenda, planta, unidades IPTU) constrói seus PRÓPRIOS
votos de endereço/CEP (nunca cruza entre si) — só a quadra fiscal (`votos_
quadra_resolvidos`, inerentemente um dado do IPTU) e a tabela de tradução
são compartilhadas entre os 3, conforme protocolo já aprovado.

Classificação revenda × planta por ENDEREÇO (mesma lógica/limiares de
engine.py: endereço com 5+ vendas válidas dentro de uma janela de 182 dias
= lançamento/planta; resto = revenda; preço incoerente entre vendas do
mesmo endereço = descartado de ambos, igual à Captação Ativa) — usa o
histórico MULTI-ANO inteiro do endereço pra detectar o padrão, mas só
conta, na tabela final, as transações dentro da janela rolante de 12
meses (mesma janela de engine._mes_base_e_periodo).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def classificar_enderecos(records):
    """addr_key -> "revenda" | "planta". Endereço com 5+ vendas válidas
    (mesmo critério de engine._is_valid_sale) dentro de uma janela de 182
    dias (engine._is_launch) é lançamento/planta; todo o resto é revenda —
    SEM o descarte de preço incoerente que a Captação Ativa aplica
    (engine._price_incoherent): aqui conta volume ("giro é giro", mesma
    filosofia já usada em todo o resto do motor), não identidade de prédio
    pra uma lista de prospecção, então preço não decide se uma transação
    existiu. Classificação usa o histórico MULTI-ANO inteiro do endereço
    (não só a janela de 12 meses) pra ter o padrão de lançamento completo
    à vista."""
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


def separar_revenda_planta(records_12m, classificacao):
    revenda, planta = [], []
    for r in records_12m:
        c = classificacao.get(r["addr_key"], "revenda")
        if c == "planta":
            planta.append(r)
        else:
            revenda.append(r)
    return revenda, planta


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
    classificacao = classificar_enderecos(itbi_dedup)
    periodo_12m, _, _ = engine._mes_base_e_periodo(itbi_dedup)
    print(f"[periodo] 12m: {periodo_12m[0]}..{periodo_12m[-1]}")
    itbi_12m = filtrar_janela_12m(itbi_dedup, periodo_12m)
    revenda_recs, planta_recs = separar_revenda_planta(itbi_12m, classificacao)
    print(f"[classificacao] revenda={len(revenda_recs)} planta={len(planta_recs)}")

    cascata_revenda = fabrica_cascata()
    contagem_revenda, fora_r, incerto_r, _ = resolver_universo_itbi(cascata_revenda, revenda_recs)

    cascata_planta = fabrica_cascata()
    contagem_planta, fora_p, incerto_p, _ = resolver_universo_itbi(cascata_planta, planta_recs)

    print("[iptu] carregando unidades residenciais (apto + residência)...")
    unidades = carregar_unidades_iptu()
    print(f"[iptu] unidades residenciais: {len(unidades)}")
    cascata_unidades = fabrica_cascata()
    contagem_unidades, fora_u, incerto_u = resolver_universo_iptu(cascata_unidades, unidades)

    total_r = len(revenda_recs)
    total_p = len(planta_recs)
    total_u = len(unidades)
    soma_r = sum(contagem_revenda.values())
    soma_p = sum(contagem_planta.values())
    soma_u = sum(contagem_unidades.values())

    print(f"\n=== FECHAMENTO ({label}) ===")
    print(f"REVENDA : total={total_r} carteira={soma_r} ({100*soma_r/total_r:.1f}%) fora={fora_r} ({100*fora_r/total_r:.1f}%) incerto={incerto_r} ({100*incerto_r/total_r:.1f}%)")
    print(f"PLANTA  : total={total_p} carteira={soma_p} ({100*soma_p/total_p:.1f}%) fora={fora_p} ({100*fora_p/total_p:.1f}%) incerto={incerto_p} ({100*incerto_p/total_p:.1f}%)")
    print(f"UNIDADES: total={total_u} carteira={soma_u} ({100*soma_u/total_u:.1f}%) fora={fora_u} ({100*fora_u/total_u:.1f}%) incerto={incerto_u} ({100*incerto_u/total_u:.1f}%)")

    print(f"\n=== TODOS OS {len(targets)} (revenda|planta|unidades|giro%) ===")
    linhas = []
    for b in targets:
        rv = contagem_revenda.get(b, 0)
        pl = contagem_planta.get(b, 0)
        un = contagem_unidades.get(b, 0)
        giro = (100 * rv / un) if un else None
        linhas.append((b, rv, pl, un, giro))
    for b, rv, pl, un, giro in linhas:
        giro_s = f"{giro:.2f}%" if giro is not None else "—"
        print(f"{b}|{rv}|{pl}|{un}|{giro_s}")

    return {
        "targets": targets,
        "revenda": contagem_revenda, "planta": contagem_planta, "unidades": contagem_unidades,
        "fechamento": {
            "revenda": (total_r, soma_r, fora_r, incerto_r),
            "planta": (total_p, soma_p, fora_p, incerto_p),
            "unidades": (total_u, soma_u, fora_u, incerto_u),
        },
    }


if __name__ == "__main__":
    import sys as _sys
    label = _sys.argv[1] if len(_sys.argv) > 1 else "com_split"
    usar_split = label != "sem_split"
    rodar(usar_split, label)
