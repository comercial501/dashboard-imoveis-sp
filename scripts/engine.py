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
  - year_full  = último ano fechado (year_curr - 1) — métrica primária de
                 volume/mediana/liquidez, equivalente ao "2025" do original
  - year_prev  = dois anos atrás (year_curr - 2) — usado só pra tendência
                 ano-cheio-vs-ano-cheio (equivalente ao "growth_24_25")
Isso evita ter que editar o código todo ano-novo.
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
    zscore_map,
)
from normalize import TARGETS

# ---------------------------------------------------------------------------
# Constantes (idênticas ao Perl — ver itbi_methodology_spec.md §19)
# ---------------------------------------------------------------------------
RELIABILITY_THRESHOLD = 5
TREND_CAP = 1.0
LAUNCH_MIN_COUNT = 5
LAUNCH_WINDOW_DAYS = 182
ADDR_MIN_VALOR = 30_000
ADDR_MAX_RATIO = 20
VALOR_OPORTUNIDADE_MIN_DESCONTO = 0.20
VALOR_OPORTUNIDADE_ATENCAO_DESCONTO = 0.30
VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY = 10
CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH = 2
CAPTACAO_ESTRATEGICA_MIN_ENDERECOS = 5

PESOS_PAINEL8 = {"revenda": 0.35, "preco": 0.30, "aderencia": 0.25, "captacao": 0.10}
PESOS_PRONTIDAO = {"f1": 0.15, "f2": 0.20, "f3": 0.15, "f4": 0.15, "f5": 0.25, "f6": 0.10}


def _confidence(reliability):
    return {"individual": 1.0, "regional": 0.5, "insufficient": 0.0}[reliability]


def _round(v, digits=1):
    return None if v is None else round(v, digits)


# ---------------------------------------------------------------------------
# 1. Agregação por bairro/ano + pares (área, valor) pra faixa de metragem
# ---------------------------------------------------------------------------
def _aggregate_itbi(itbi_records, years):
    yearly_valores = {b: {y: [] for y in years} for b in TARGETS}
    pairs_all_years = {b: [] for b in TARGETS}
    month_counts = {b: {} for b in TARGETS}  # bairro -> (ano,mes) -> count

    for r in itbi_records:
        b = r["bairro"]
        if b not in yearly_valores:
            continue
        y = r["sheet_year"]
        if y in yearly_valores[b]:
            yearly_valores[b][y].append(r["valor"])
        if r["area"] is not None:
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
            vals = yearly_valores[b][y]
            yearly[b][y] = {
                "count": len(vals),
                "avg_valor": _round(mean(vals), 2),
                "median_valor": _round(median(vals), 2),
            }
    return yearly, pairs_all_years, month_counts


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
    asking_median = {
        b: _round(median([r["valor"] for r in by_bairro[b] if r["valor"] is not None]), 2)
        for b in TARGETS
    }
    return by_bairro, centroids, stock_total, asking_median


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
            "profile_pool_sample_size": 0,
        }

        # Gate 1 — faixa de área/preço
        if len(own_pairs) >= RELIABILITY_THRESHOLD:
            lo, hi, valores = mode_bucket_from_pairs(own_pairs)
            if lo is not None:
                entry["area_band"] = [lo, hi]
                entry["price_band"] = [_round(percentile(25, valores), 2), _round(percentile(75, valores), 2)]
                entry["price_band_median"] = _round(median(valores), 2)
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
                    entry["area_band"] = [lo, hi]
                    entry["price_band"] = [_round(percentile(25, valores), 2), _round(percentile(75, valores), 2)]
                    entry["price_band_median"] = _round(median(valores), 2)
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

    for addr_key, recs in by_addr.items():
        bairro = recs[0]["bairro"]
        for r in recs:
            if r["sheet_year"] in liquidez[bairro]:
                liquidez[bairro][r["sheet_year"]]["total"] += 1

        endereco = next((r["addr_display"] for r in recs if r["addr_display"]), addr_key)
        tem_hoje, unidades_hoje = _tem_unidade_a_venda_hoje(usn_by_addr_key.get(addr_key, []))

        if len(recs) == 1:
            r = recs[0]
            if r["sheet_year"] in liquidez[bairro]:
                liquidez[bairro][r["sheet_year"]]["revenda"] += 1
            captacao_unico.append({
                "bairro": bairro, "addr_key": addr_key, "endereco": endereco,
                "n_vendas": 1, "preco_min": r["valor"], "preco_max": r["valor"],
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

        for r in recs:
            if r["sheet_year"] in liquidez[bairro]:
                liquidez[bairro][r["sheet_year"]]["revenda"] += 1
        areas = [r["area"] for r in recs if r["area"] is not None]
        captacao_ativa.append({
            "bairro": bairro, "addr_key": addr_key, "endereco": endereco,
            "n_vendas": len(recs), "preco_min": min(valores), "preco_max": max(valores),
            "preco_medio": _round(mean(valores), 2),
            "area_min": min(areas) if areas else None, "area_max": max(areas) if areas else None,
            "tem_unidade_a_venda_hoje": tem_hoje, "unidades_a_venda_hoje": unidades_hoje,
        })

    captacao_ativa.sort(key=lambda c: (c["bairro"], -c["n_vendas"], c["addr_key"]))

    meta = {
        "enderecos_com_repeticao": n_addr_total_multi,
        "enderecos_descartados_preco": n_addr_discarded,
        "enderecos_lancamento": n_addr_launch,
        "enderecos_captacao_ativa": len(captacao_ativa),
    }
    return liquidez, captacao_ativa, captacao_unico, meta


def _tem_unidade_a_venda_hoje(usn_recs_no_addr):
    ativos = [r for r in usn_recs_no_addr if r["situacao_code"] not in (3, 4)]  # exclui LANCAMENTO/CONSTRUCAO
    unidades = [{"codigo": r["codigo"], "valor": r["valor"], "link": r["link"]} for r in ativos]
    return len(ativos) > 0, unidades


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


def _diff_score(a, b):
    if a is None or b is None:
        return 50
    diff = abs(a - b)
    return 100 if diff == 0 else (50 if diff == 1 else 0)


def _resumo_imovel(price, aderencia_final, area_conf, score_revenda_bairro, tem_captacao):
    frases = []
    ratio = price["ratio"]
    if price["zone"] == "cautela" and ratio is not None:
        frases.append(f"Preço {round((1 - ratio) * 100)}% abaixo do histórico do bairro — vale checar antes de anunciar")
    elif price["zone"] == "acima" and price["score"] < 60 and ratio is not None:
        frases.append(f"Preço {round((ratio - 1) * 100)}% acima do que o bairro historicamente pagou")
    elif price["zone"] == "normal" and ratio is not None and ratio < 0.97:
        frases.append(f"Preço {round((1 - ratio) * 100)}% abaixo da mediana paga no bairro")

    if aderencia_final >= 80:
        sufixo = " (estimativa regional)" if area_conf < 1 else ""
        frases.append(f"Bate com o perfil vencedor do bairro{sufixo}")
    if score_revenda_bairro >= 70:
        frases.append("Bairro com liquidez de revenda alta")
    if tem_captacao:
        frases.append("Prédio com histórico de giro comprovado")

    return " · ".join(frases[:2])


def _compute_imoveis_prioritarios(usn_records, bairros_out, addr_in_captacao_ativa):
    out = []
    for u in usn_records:
        if u["valor"] is None or u["valor"] <= 0:
            continue
        b = bairros_out.get(u["bairro"])
        if not b:
            continue

        price = _price_alignment_score(u["valor"], b["paid_median_valor_primary_year"])

        area_band = b["area_band"]
        area_conf = _confidence(b["area_band_reliability"])
        area_raw = 50
        if area_band and u["area"] is not None:
            lo, hi = area_band
            if lo <= u["area"] < hi:
                area_raw = 100
            else:
                band_width = hi - lo
                dist = (lo - u["area"]) if u["area"] < lo else (u["area"] - hi)
                area_raw = max(0, 100 - (dist / band_width) * 100) if band_width > 0 else 50
        area_score = 50 + (area_raw - 50) * area_conf

        profile_conf = _confidence(b["profile_reliability"])
        quartos_raw = _diff_score(u["quartos"], b["profile_quartos"])
        vagas_raw = _diff_score(u["vagas"], b["profile_vagas"])
        quartos_score = 50 + (quartos_raw - 50) * profile_conf
        vagas_score = 50 + (vagas_raw - 50) * profile_conf

        aderencia = mean([area_score, quartos_score, vagas_score])
        tem_captacao = u["addr_key"] is not None and u["addr_key"] in addr_in_captacao_ativa
        bonus = 100 if tem_captacao else 0

        final_score = (
            PESOS_PAINEL8["revenda"] * b["score_revenda"]
            + PESOS_PAINEL8["preco"] * price["score"]
            + PESOS_PAINEL8["aderencia"] * aderencia
            + PESOS_PAINEL8["captacao"] * bonus
        )

        resumo = _resumo_imovel(price, aderencia, area_conf, b["score_revenda"], tem_captacao)

        out.append({
            "bairro": u["bairro"], "endereco": u["addr_display"], "codigo": u["codigo"], "link": u["link"],
            "valor": u["valor"], "area": u["area"], "quartos": u["quartos"], "vagas": u["vagas"],
            "addr_key": u["addr_key"],
            "score_bairro_revenda": _round(b["score_revenda"]), "price_alignment": _round(price["score"]),
            "profile_adherence": _round(aderencia), "tem_captacao_ativa": tem_captacao,
            "area_band_reliability": b["area_band_reliability"], "profile_reliability": b["profile_reliability"],
            "final_score": _round(final_score, 2), "resumo": resumo,
        })

    out.sort(key=lambda x: (-x["final_score"], x["addr_key"] or "", x["codigo"] or ""))
    return out


# ---------------------------------------------------------------------------
# 7. Painel 10 — Valor de Oportunidade
# ---------------------------------------------------------------------------
def _compute_valor_oportunidade(imoveis_prioritarios, bairros_out):
    achados = []
    for im in imoveis_prioritarios:
        b = bairros_out[im["bairro"]]
        if b["volume_primary_year"] < VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY:
            continue
        mediana = b["paid_median_valor_primary_year"]
        if not mediana or mediana <= 0:
            continue
        ratio = im["valor"] / mediana
        desconto = 1 - ratio
        if desconto < VALOR_OPORTUNIDADE_MIN_DESCONTO:
            continue
        achados.append({
            "bairro": im["bairro"], "endereco": im["endereco"], "codigo": im["codigo"], "link": im["link"],
            "valor": im["valor"], "mediana_paga_bairro": mediana,
            "desconto_pct": _round(desconto * 100, 1),
            "atencao": desconto >= VALOR_OPORTUNIDADE_ATENCAO_DESCONTO,
        })
    achados.sort(key=lambda a: -a["desconto_pct"])

    stock_eleg = {}
    achados_by_bairro = {}
    for im in imoveis_prioritarios:
        b = bairros_out[im["bairro"]]
        if b["volume_primary_year"] >= VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY:
            stock_eleg[im["bairro"]] = stock_eleg.get(im["bairro"], 0) + 1
    for a in achados:
        achados_by_bairro[a["bairro"]] = achados_by_bairro.get(a["bairro"], 0) + 1

    por_bairro = []
    for b, n in achados_by_bairro.items():
        total = stock_eleg.get(b, 0)
        por_bairro.append({
            "bairro": b, "n_achados": n, "estoque_total": total,
            "pct_do_estoque": _round(100 * n / total, 1) if total else None,
        })
    por_bairro.sort(key=lambda x: (-x["n_achados"], x["bairro"]))

    return {"imoveis": achados, "por_bairro": por_bairro}


# ---------------------------------------------------------------------------
# 8. Painel 7 — Captação Ativa Estratégica
# ---------------------------------------------------------------------------
def _compute_captacao_estrategica(captacao_ativa, captacao_unico, bairros_out):
    by_bairro_ativa = {}
    for c in captacao_ativa:
        if not c["tem_unidade_a_venda_hoje"]:
            by_bairro_ativa.setdefault(c["bairro"], []).append(c)
    by_bairro_unico = {}
    for c in captacao_unico:
        if not c["tem_unidade_a_venda_hoje"]:
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
        enderecos.sort(key=lambda e: (-e["n_vendas"], e["endereco"]))

        bo = bairros_out[b]
        groups.append({
            "bairro": b,
            "flag_prioridade_maxima": bo["flag_prioridade_maxima"],
            "perfil": {
                "area_band": bo["area_band"], "price_band": bo["price_band"],
                "profile_quartos": bo["profile_quartos"], "profile_vagas": bo["profile_vagas"],
                "profile_reliability": bo["profile_reliability"],
            },
            "enderecos": [
                {"endereco": e["endereco"], "n_vendas": e["n_vendas"], "preco_min": e["preco_min"],
                 "preco_max": e["preco_max"], "area_min": e["area_min"], "area_max": e["area_max"],
                 "unico": e["unico"]}
                for e in enderecos
            ],
            "_used_unico_fallback": used_unico,
        })

    groups.sort(key=lambda g: (
        0 if g["flag_prioridade_maxima"] else 1,
        -bairros_out[g["bairro"]]["volume_primary_year"],
        g["bairro"],
    ))
    for g in groups:
        g.pop("_used_unico_fallback", None)
    return groups


# ---------------------------------------------------------------------------
# Orquestração principal
# ---------------------------------------------------------------------------
def compute(itbi_records, usn_records, years):
    """years: lista de 3 anos ascendente, ex: [2024, 2025, 2026]."""
    year_prev, year_full, year_curr = years

    yearly, pairs_all_years, month_counts = _aggregate_itbi(itbi_records, years)
    trend = _compute_trend(yearly, month_counts, year_prev, year_full, year_curr)
    usn_by_bairro, centroids, stock_total, asking_median = _aggregate_usn(usn_records)
    profile = _compute_profile(pairs_all_years, usn_by_bairro, centroids)

    usn_by_addr_key = {}
    for r in usn_records:
        if r["addr_key"]:
            usn_by_addr_key.setdefault(r["addr_key"], []).append(r)

    liquidez, captacao_ativa, captacao_unico, liquidez_meta = _compute_liquidez(itbi_records, usn_by_addr_key, years)
    addr_in_captacao_ativa = {c["addr_key"] for c in captacao_ativa}

    # --- montagem preliminar por bairro (sem os campos que dependem de score cross-bairro) ---
    bairros_out = {}
    for b in TARGETS:
        volume_primary = yearly[b][year_full]["count"]
        stock_match = profile[b]["profile_sample_size"]
        demand = volume_primary
        ratio = (stock_match / demand) if demand > 0 else (999 if stock_match > 0 else 0)

        paid_median = yearly[b][year_full]["median_valor"]
        asking = asking_median[b]
        price_gap_pct = _round((asking - paid_median) / paid_median * 100, 1) if (paid_median and asking) else None

        bairros_out[b] = {
            "yearly": {str(y): yearly[b][y] for y in years},
            **trend[b],
            "volume_primary_year": volume_primary,
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
            "asking_median_valor": asking, "paid_median_valor_primary_year": paid_median,
            "centroid": list(centroids[b]) if centroids[b] else None,
            "stock_demand_ratio": round(ratio, 3), "price_gap_pct": price_gap_pct,
            "flag_alerta": price_gap_pct is not None and abs(price_gap_pct) >= 20,
            "liquidez_total_primary_year": liquidez[b][year_full]["total"],
            "liquidez_revenda_primary_year": liquidez[b][year_full]["revenda"],
            "liquidez_por_ano": {str(y): liquidez[b][y] for y in years},
        }

    # --- Painel 1: score (volume + tendência) ---
    volume_map = {b: bairros_out[b]["volume_primary_year"] for b in TARGETS}
    trend_z_input = {b: bairros_out[b]["trend_pct_for_score"] for b in TARGETS}
    trend_z = zscore_map(trend_z_input)
    score_map = _score_from_volume_and_trend(volume_map, trend_z)

    ratios_sorted = sorted(bairros_out[b]["stock_demand_ratio"] for b in TARGETS)
    low_tercile = _tercile(ratios_sorted, 1 / 3)

    # --- Mudança 3a: score_revenda (mesma fórmula, insumo = liquidez_revenda) ---
    revenda_map = {b: bairros_out[b]["liquidez_revenda_primary_year"] for b in TARGETS}
    revenda_z = zscore_map(revenda_map)
    combined_revenda = {b: (revenda_z[b] + trend_z[b]) / 2 for b in TARGETS}
    score_revenda_map = _minmax_rescale_0_100(combined_revenda)

    # --- Índice de Saturação de Oferta (estoque TOTAL, tercil superior) ---
    total_ratio_map = {}
    for b in TARGETS:
        demand = bairros_out[b]["volume_primary_year"]
        st = bairros_out[b]["stock_total"]
        total_ratio_map[b] = (st / demand) if demand > 0 else (999 if st > 0 else 0)
    total_ratios_sorted = sorted(total_ratio_map.values())
    high_tercile = _tercile(total_ratios_sorted, 2 / 3)

    for b in TARGETS:
        bairros_out[b]["score"] = _round(score_map[b])
        bairros_out[b]["flag_oportunidade"] = (
            bairros_out[b]["stock_demand_ratio"] <= low_tercile and bairros_out[b]["volume_primary_year"] > 0
        )
        bairros_out[b]["score_revenda"] = _round(score_revenda_map[b])
        bairros_out[b]["stock_total_demand_ratio"] = round(total_ratio_map[b], 3)
        bairros_out[b]["flag_saturacao_alta"] = total_ratio_map[b] >= high_tercile
        bairros_out[b]["flag_prioridade_maxima"] = (
            bairros_out[b]["stock_matching_profile"] <= CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH
            and bairros_out[b]["volume_primary_year"] >= VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY
        )

    ranking = sorted(TARGETS, key=lambda b: -bairros_out[b]["score"])

    # --- Painel 8: imóveis prioritários ---
    imoveis_prioritarios = _compute_imoveis_prioritarios(usn_records, bairros_out, addr_in_captacao_ativa)

    # --- Painel 2: Prontidão para Campanha ---
    f2_map = normalize_0_100({b: bairros_out[b]["stock_matching_profile"] for b in TARGETS})
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

        vendas_primary = bairros_out[b]["volume_primary_year"]
        if vendas_primary < VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY:
            f6 = 50
        else:
            estoque_eleg = sum(1 for im in imoveis_by_bairro.get(b, []) if bairros_out[im["bairro"]]["volume_primary_year"] >= VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY)
            achados_bairro = 0  # preenchido abaixo após valor_oportunidade
            f6 = None  # placeholder, resolvido após calcular valor_oportunidade

        bairros_out[b]["_f1_f5"] = (f1, f2, f3, f4, f5)

    valor_oportunidade = _compute_valor_oportunidade(imoveis_prioritarios, bairros_out)
    achados_by_bairro_count = {}
    for a in valor_oportunidade["imoveis"]:
        achados_by_bairro_count[a["bairro"]] = achados_by_bairro_count.get(a["bairro"], 0) + 1

    for b in TARGETS:
        f1, f2, f3, f4, f5 = bairros_out[b].pop("_f1_f5")
        vendas_primary = bairros_out[b]["volume_primary_year"]
        if vendas_primary < VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY:
            f6 = 50
        else:
            estoque_eleg = sum(1 for im in imoveis_by_bairro.get(b, []) if bairros_out[im["bairro"]]["volume_primary_year"] >= VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY)
            achados_bairro = achados_by_bairro_count.get(b, 0)
            f6 = 0 if estoque_eleg == 0 else 100 * achados_bairro / estoque_eleg

        prontidao = (
            PESOS_PRONTIDAO["f1"] * f1 + PESOS_PRONTIDAO["f2"] * f2 + PESOS_PRONTIDAO["f3"] * f3
            + PESOS_PRONTIDAO["f4"] * f4 + PESOS_PRONTIDAO["f5"] * f5 + PESOS_PRONTIDAO["f6"] * f6
        )
        bairros_out[b]["prontidao_campanha"] = _round(prontidao)

    prontidao_ranking = sorted(TARGETS, key=lambda b: -bairros_out[b]["prontidao_campanha"])

    captacao_estrategica = _compute_captacao_estrategica(captacao_ativa, captacao_unico, bairros_out)

    return {
        "meta": {
            "years": years,
            "primary_year": year_full,
            "inprogress_year": year_curr,
            **liquidez_meta,
        },
        "ranking": ranking,
        "prontidao_ranking": prontidao_ranking,
        "bairros": bairros_out,
        "captacao_ativa": captacao_ativa,
        "imoveis_prioritarios": imoveis_prioritarios,
        "valor_oportunidade": valor_oportunidade,
        "captacao_estrategica": captacao_estrategica,
    }
