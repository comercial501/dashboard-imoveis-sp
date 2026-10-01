// Motor de cálculo — porte em JavaScript de scripts/engine.py, pra recomputar
// os 10 painéis no navegador quando o usuário usa os filtros de bairro/preço.
// Mesmas fórmulas, mesmos limiares (lidos de raw.constants, nunca hardcoded
// aqui de novo) — ver itbi_methodology_spec.md. Qualquer mudança de fórmula
// precisa ser espelhada nos dois lados (Python e aqui).

// ---------------------------------------------------------------------------
// Estatísticas auxiliares (porte de scripts/normalize.py)
// ---------------------------------------------------------------------------
function mean(values) {
  const vals = values.filter((v) => v != null);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function median(values) {
  const vals = values.filter((v) => v != null).sort((a, b) => a - b);
  const n = vals.length;
  if (n === 0) return null;
  const mid = Math.floor(n / 2);
  return n % 2 === 1 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
}

function percentile(p, values) {
  const vals = values.filter((v) => v != null).sort((a, b) => a - b);
  const n = vals.length;
  if (n === 0) return null;
  if (n === 1) return vals[0];
  const idx = (p / 100) * (n - 1);
  const lo = Math.floor(idx);
  const frac = idx - lo;
  const hi = Math.min(lo + 1, n - 1);
  return vals[lo] + (vals[hi] - vals[lo]) * frac;
}

function trimOutliersIqr(values, k = 1.5) {
  const vals = values.filter((v) => v != null);
  if (vals.length < 4) return vals;
  const q1 = percentile(25, vals), q3 = percentile(75, vals);
  const iqr = q3 - q1;
  if (iqr === 0) return vals;
  const lo = q1 - k * iqr, hi = q3 + k * iqr;
  const filtered = vals.filter((v) => v >= lo && v <= hi);
  return filtered.length ? filtered : vals;
}

function modeOf(values) {
  const vals = values.filter((v) => v != null);
  if (!vals.length) return null;
  const counts = new Map();
  for (const v of vals) counts.set(v, (counts.get(v) || 0) + 1);
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  return entries[0][0];
}

function zscoreMap(obj) {
  const keys = Object.keys(obj);
  const present = keys.map((k) => obj[k]).filter((v) => v != null);
  if (present.length < 2) {
    const out = {};
    keys.forEach((k) => (out[k] = 0));
    return out;
  }
  const m = mean(present);
  const variance = mean(present.map((x) => (x - m) ** 2));
  const sd = Math.sqrt(variance) || 1;
  const out = {};
  keys.forEach((k) => {
    const v = obj[k];
    out[k] = v == null ? -2 : (v - m) / sd;
  });
  return out;
}

function minmaxRescale0to100(combined) {
  const vals = Object.values(combined);
  const cmin = percentile(0, vals);
  const cmax = percentile(100, vals);
  const crange = cmax != null && cmin != null && cmax !== cmin ? cmax - cmin : 1;
  const out = {};
  Object.entries(combined).forEach(([k, v]) => (out[k] = ((v - cmin) / crange) * 100));
  return out;
}

function normalize0to100(raw) {
  const z = zscoreMap(raw);
  return minmaxRescale0to100(z);
}

function coordIsValidSp(lat, lon) {
  if (lat == null || lon == null) return false;
  return lat >= -24.2 && lat <= -23.0 && lon >= -47.0 && lon <= -46.2;
}

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const rad = 3.14159265358979 / 180;
  const dlat = (lat2 - lat1) * rad;
  const dlon = (lon2 - lon1) * rad;
  const a = Math.sin(dlat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dlon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function nearestNeighbors(bairro, centroids, targets, maxKm, count) {
  const c0 = centroids[bairro];
  if (!c0) return [];
  const dists = [];
  for (const other of targets) {
    if (other === bairro) continue;
    const c1 = centroids[other];
    if (!c1) continue;
    const d = haversineKm(c0[0], c0[1], c1[0], c1[1]);
    if (d <= maxKm) dists.push([other, d]);
  }
  dists.sort((a, b) => a[1] - b[1]);
  return dists.slice(0, count);
}

function dedupCapExactArea(pairs, maxPerExact) {
  const seen = new Map();
  const out = [];
  for (const p of pairs) {
    const key = Math.round(p.area * 100) / 100;
    const n = (seen.get(key) || 0) + 1;
    seen.set(key, n);
    if (n <= maxPerExact) out.push(p);
  }
  return out;
}

function modeBucketFromPairs(rawPairs, width, maxPerExact) {
  const pairs = dedupCapExactArea(rawPairs, maxPerExact);
  if (!pairs.length) return [null, null, []];
  const counts = new Map();
  for (const p of pairs) {
    const b = Math.floor(p.area / width);
    counts.set(b, (counts.get(b) || 0) + 1);
  }
  const bestB = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0][0];
  const lo = bestB * width, hi = (bestB + 1) * width;
  const valores = pairs.filter((p) => p.area >= lo && p.area < hi).map((p) => p.valor);
  return [lo, hi, valores];
}

function round(v, digits = 1) {
  if (v == null) return null;
  const f = 10 ** digits;
  return Math.round(v * f) / f;
}

function confidence(rel) {
  return { individual: 1.0, regional: 0.5, insufficient: 0.0 }[rel];
}

function tercile(sortedVals, frac) {
  let idx = Math.floor(sortedVals.length * frac);
  idx = Math.min(idx, sortedVals.length - 1);
  return sortedVals[idx];
}

// Desempate alfabético de texto (bairro/endereço) — de propósito NÃO usa
// localeCompare (comparação tipo dicionário, ignora maiúscula/minúscula
// como critério primário) porque o lado Python compara string padrão
// (sensível a maiúscula/minúscula). Minúsculas dos dois lados = mesmo
// resultado sempre, sem depender de locale/ICU.
function cmpLower(a, b) {
  const al = a.toLowerCase(), bl = b.toLowerCase();
  return al < bl ? -1 : al > bl ? 1 : 0;
}

// Etapa 2, item 2 (2026-10-01) — mesma regra de
// scripts/engine.py._is_revenda_aprovada: proporção transmitida 100% E
// uso IPTU residencial (10 ou 20 — não o conjunto mais amplo de
// tipoImovel, que também inclui 12/14/21/22/25).
const USO_REVENDA_APROVADA = new Set(["10", "20"]);
function isRevendaAprovada(r) {
  return r.isCompraVenda && r.isFullTransfer && USO_REVENDA_APROVADA.has(r.usoCode);
}

// Faixas vêm de raw.constants.faixas_metragem (mesma fonte que
// scripts/clean_itbi.FAIXAS_METRAGEM — nunca hardcoded aqui de novo).
// Cada item é [lo, hi, label]; hi null = faixa aberta (acima de).
function faixaMetragem(area, faixas) {
  if (area == null) return null;
  for (const [lo, hi, label] of faixas) {
    if ((lo < area && (hi == null || area <= hi)) || (lo === 0 && area === 0)) return label;
  }
  return null;
}

function excelSerialToYm(serial) {
  // Época Excel (sistema 1900): 1899-12-30. Date.UTC em ms.
  const epoch = Date.UTC(1899, 11, 30);
  const d = new Date(epoch + Math.trunc(serial) * 86400000);
  return [d.getUTCFullYear(), d.getUTCMonth() + 1];
}

function ymAddMonths([y, m], delta) {
  const total = y * 12 + (m - 1) + delta;
  return [Math.floor(total / 12), (((total % 12) + 12) % 12) + 1];
}

function ymKey([y, m]) {
  return `${y}-${m}`;
}

// ---------------------------------------------------------------------------
// Decodifica os arrays compactos do raw.json em registros de trabalho,
// já aplicando o filtro de preço (se houver) — o filtro de preço vale
// sobre TODOS os 47 bairros, nunca só sobre o escopo selecionado (ver
// itbi_methodology_spec.md §20, nota 11).
// ---------------------------------------------------------------------------
function decodeRecords(raw, priceMin, priceMax) {
  const inPriceRange = (v) => {
    if (v == null) return true; // registros sem valor não são cortados pelo filtro de preço
    if (priceMin != null && v < priceMin) return false;
    if (priceMax != null && v > priceMax) return false;
    return true;
  };

  const itbi = [];
  for (const [bIdx, sheetYear, day, valor, area, addrIdx, isCompraVenda, isFullTransfer, tipoImovel, isCleanSale, isRetomada, usoCode, isRevenda, isPlanta] of raw.itbi) {
    if (!inPriceRange(valor)) continue;
    itbi.push({
      bairro: raw.bairros[bIdx], sheetYear, day, valor, area, isCompraVenda, isFullTransfer, tipoImovel, isCleanSale, isRetomada, usoCode, isRevenda, isPlanta,
      addrKey: addrIdx, addrDisplay: addrIdx != null ? raw.addr_display[addrIdx] : null,
    });
  }

  const usn = [];
  for (const [bIdx, addrIdx, addrDisplay, valor, area, quartos, vagas, lat, lon, situacaoCode, codigo, link, tipoImovel] of raw.usn) {
    if (!inPriceRange(valor)) continue;
    usn.push({
      bairro: raw.bairros[bIdx], addrKey: addrIdx, addrDisplay, valor, area, quartos, vagas,
      lat, lon, situacaoCode, codigo, link, tipoImovel,
    });
  }

  return { itbi, usn };
}

// ---------------------------------------------------------------------------
// Motor principal
// ---------------------------------------------------------------------------
function computeEngine(raw, { priceMin = null, priceMax = null, bairroScope = null } = {}) {
  const C = raw.constants;
  const TARGETS = raw.bairros;
  const [yearPrev, yearFull, yearCurr] = raw.years;
  const scope = bairroScope && bairroScope.length ? bairroScope : TARGETS;
  const scopeSet = new Set(scope);

  const { itbi: itbiRecords, usn: usnRecords } = decodeRecords(raw, priceMin, priceMax);

  // Captação Ativa (histórico de UM endereço) só filtra natureza + %
  // transmitido + tipo de imóvel (não prédio inteiro) — NÃO aplica o
  // outlier por bairro+tipo+faixa da camada limpa, que já é considerado no
  // isCleanSale de cada linha (esse é usado só na agregação por bairro,
  // abaixo) — ver scripts/engine.py._is_valid_sale.
  const isValidSale = (r) => r.isCompraVenda && r.isFullTransfer && r.tipoImovel != null;

  // --- 1. Agregação ITBI por bairro/ano + pares (área,valor) ---
  // count = QUALQUER transação residencial válida (giro do bairro é giro,
  // mesmo com valor não confiável pra preço). avg_valor/median_valor e
  // pairsAllYears (faixa de metragem/preço) usam a camada de dados limpa
  // (isCleanSale — ver scripts/clean_itbi.py) — comentário equivalente em
  // scripts/engine.py._aggregate_itbi.
  const yearlyCount = {}, yearlyValoresVenda = {}, pairsAllYears = {}, monthCounts = {};
  TARGETS.forEach((b) => {
    yearlyCount[b] = { [yearPrev]: 0, [yearFull]: 0, [yearCurr]: 0 };
    yearlyValoresVenda[b] = { [yearPrev]: [], [yearFull]: [], [yearCurr]: [] };
    pairsAllYears[b] = [];
    monthCounts[b] = {};
  });

  for (const r of itbiRecords) {
    if (!(r.bairro in yearlyCount)) continue;
    const valid = r.isCleanSale;
    if (r.sheetYear in yearlyCount[r.bairro]) {
      yearlyCount[r.bairro][r.sheetYear]++;
      if (valid) yearlyValoresVenda[r.bairro][r.sheetYear].push(r.valor);
    }
    if (r.area != null && valid) pairsAllYears[r.bairro].push({ area: r.area, valor: r.valor });
    if (r.day != null) {
      try {
        const [y, m] = excelSerialToYm(r.day);
        const key = `${y}-${m}`;
        monthCounts[r.bairro][key] = (monthCounts[r.bairro][key] || 0) + 1;
      } catch (e) { /* ignora data inválida */ }
    }
  }

  const yearly = {};
  TARGETS.forEach((b) => {
    yearly[b] = {};
    [yearPrev, yearFull, yearCurr].forEach((y) => {
      const vals = trimOutliersIqr(yearlyValoresVenda[b][y]);
      yearly[b][y] = { count: yearlyCount[b][y], avg_valor: round(mean(vals), 2), median_valor: round(median(vals), 2) };
    });
  });

  // Mediana "de referência" (Ranking, Prontidão, Estoque×Demanda, Valor de
  // Oportunidade) = pool dos 3 anos juntos, não só o último fechado (ver
  // scripts/engine.py._aggregate_itbi — decisão do usuário, 2026-09-25).
  const pooledMedian = {};
  TARGETS.forEach((b) => {
    const pool = [yearPrev, yearFull, yearCurr].flatMap((y) => yearlyValoresVenda[b][y]);
    const vals = trimOutliersIqr(pool);
    pooledMedian[b] = { avg_valor: round(mean(vals), 2), median_valor: round(median(vals), 2), n: vals.length };
  });

  // Etapa 3 (2026-09-29): preço por m² pago x pedido, por bairro + tipo de
  // imóvel + faixa de metragem — ver scripts/engine.py._compute_preco_m2.
  // Etapa 2, item 1.2d (2026-10-01): apartamento troca R$/m² por VALOR
  // TOTAL pago (mediana/P25/P75), só revenda (r.isRevenda) — gap
  // pedido×pago suspenso (null) pra apartamento. Casa não muda (uso 10 é
  // sempre revenda por construção — nunca entra aqui como planta).
  const precoM2 = {};
  TARGETS.forEach((b) => (precoM2[b] = []));
  {
    const pago = {}, pedido = {}, valorTotal = {};
    for (const r of itbiRecords) {
      if (!r.isCleanSale || !(r.bairro in yearlyCount)) continue;
      const f = faixaMetragem(r.area, C.faixas_metragem);
      if (f == null) continue;
      const key = `${r.bairro}\u0001${r.tipoImovel}\u0001${f}`;
      (pago[key] ||= []).push([round(r.valor / r.area, 2), r.day]);
      if (r.tipoImovel === "apartamento" && r.isRevenda) {
        const vtKey = `${r.bairro}\u0001${f}`;
        (valorTotal[vtKey] ||= []).push(r.valor);
      }
    }
    for (const r of usnRecords) {
      if (!(r.bairro in yearlyCount) || r.tipoImovel == null) continue;
      if (!r.valor || !r.area) continue;
      const f = faixaMetragem(r.area, C.faixas_metragem);
      if (f == null) continue;
      const key = `${r.bairro}\u0001${r.tipoImovel}\u0001${f}`;
      (pedido[key] ||= []).push(r.valor / r.area);
    }
    const allKeys = new Set([...Object.keys(pago), ...Object.keys(pedido)]);
    for (const key of allKeys) {
      const [bairro, tipo, faixa] = key.split("\u0001");
      const isApto = tipo === "apartamento";
      const pagoPairs = pago[key] || [];
      const pagoVals = pagoPairs.map(([v]) => v);
      const n12m = pagoPairs.filter(([, d]) => d != null && (C.hoje_serial - d) >= 0 && (C.hoje_serial - d) <= C.janela_preco_m2_dias).length;
      const medianaPago = isApto ? null : (pagoVals.length ? round(median(pagoVals), 2) : null);
      const p25Pago = isApto ? null : (pagoVals.length ? round(percentile(25, pagoVals), 2) : null);
      const p75Pago = isApto ? null : (pagoVals.length ? round(percentile(75, pagoVals), 2) : null);

      let medianaPedido = null, gapPct = null;
      if (!isApto) {
        const pedidoVals = trimOutliersIqr(pedido[key] || []);
        medianaPedido = pedidoVals.length ? round(median(pedidoVals), 2) : null;
        if (medianaPago && medianaPedido) gapPct = round(((medianaPedido - medianaPago) / medianaPago) * 100, 1);
      }

      const valorTotalVals = isApto ? (valorTotal[`${bairro}\u0001${faixa}`] || []) : [];
      const valorTotalLimpos = trimOutliersIqr(valorTotalVals);
      const valorTotalMediana = valorTotalLimpos.length ? round(median(valorTotalLimpos), 2) : null;
      const valorTotalP25 = valorTotalLimpos.length ? round(percentile(25, valorTotalLimpos), 2) : null;
      const valorTotalP75 = valorTotalLimpos.length ? round(percentile(75, valorTotalLimpos), 2) : null;
      const nRevenda = valorTotalVals.length;

      precoM2[bairro].push({
        tipo_imovel: tipo, faixa,
        mediana_pago_m2: medianaPago, mediana_pedido_m2: medianaPedido, gap_pct: gapPct,
        p25_pago_m2: p25Pago, p75_pago_m2: p75Pago,
        valor_total_mediana: isApto ? valorTotalMediana : null,
        valor_total_p25: isApto ? valorTotalP25 : null,
        valor_total_p75: isApto ? valorTotalP75 : null,
        n_transacoes: pagoVals.length, n_transacoes_12m: n12m, n_anuncios: (pedido[key] || []).length,
        amostra_pequena: (isApto ? nRevenda : n12m) < C.min_transacoes_preco_m2_12m,
      });
    }
  }

  // Etapa 4 (2026-09-29): painel dedicado "Preço por m² — Pago × Pedido".
  // Diferente de precoM2 acima (pool de 3 anos pras 5 comparações da
  // Etapa 3), aqui TUDO — inclusive a mediana paga — é escopado aos
  // ÚLTIMOS 12 MESES, e só apartamento — ver
  // scripts/engine.py._compute_preco_m2_painel.
  //
  // Etapa 2, item 2 (2026-10-01): pra apartamento, R$/m² pago×pedido foi
  // substituído por valor TOTAL pago (mediana/P25/P75) só de REVENDA
  // (isRevendaAprovada) — gap_pct/mediana_pago_m2/mediana_pedido_m2 ficam
  // sempre null agora (suspensos, calibração fica pra depois); campos
  // novos valor_total_*/n_vendas_revenda_12m são aditivos.
  const precoM2Painel = [];
  {
    const pago = {}, pedido = {}, valorTotal = {};
    for (const r of itbiRecords) {
      if (!(r.bairro in yearlyCount) || r.tipoImovel !== "apartamento") continue;
      if (r.day == null || (C.hoje_serial - r.day) < 0 || (C.hoje_serial - r.day) > C.janela_preco_m2_dias) continue;
      const f = faixaMetragem(r.area, C.faixas_metragem);
      if (f == null) continue;
      const key = `${r.bairro}\u0001${f}`;
      if (r.isCleanSale) (pago[key] ||= []).push(round(r.valor / r.area, 2));
      if (isRevendaAprovada(r)) (valorTotal[key] ||= []).push(r.valor);
    }
    for (const r of usnRecords) {
      if (!(r.bairro in yearlyCount) || r.tipoImovel !== "apartamento") continue;
      if (!r.valor || !r.area) continue;
      const f = faixaMetragem(r.area, C.faixas_metragem);
      if (f == null) continue;
      const key = `${r.bairro}\u0001${f}`;
      (pedido[key] ||= []).push(r.valor / r.area);
    }
    for (const bairro of TARGETS) {
      for (const [, , faixa] of C.faixas_metragem) {
        const key = `${bairro}\u0001${faixa}`;
        const pagoVals = pago[key] || [];
        const valorTotalVals = valorTotal[key] || [];
        if (!pagoVals.length && !valorTotalVals.length && !(key in pedido)) continue;

        const valorTotalLimpos = trimOutliersIqr(valorTotalVals);
        const valorTotalMediana = valorTotalLimpos.length ? round(median(valorTotalLimpos), 2) : null;
        const valorTotalP25 = valorTotalLimpos.length ? round(percentile(25, valorTotalLimpos), 2) : null;
        const valorTotalP75 = valorTotalLimpos.length ? round(percentile(75, valorTotalLimpos), 2) : null;

        precoM2Painel.push({
          bairro, faixa,
          mediana_pago_m2: null, mediana_pedido_m2: null, gap_pct: null,
          valor_total_mediana: valorTotalMediana, valor_total_p25: valorTotalP25, valor_total_p75: valorTotalP75,
          n_vendas_revenda_12m: valorTotalVals.length,
          n_transacoes_12m: pagoVals.length, n_anuncios: (pedido[key] || []).length,
          amostra_pequena: valorTotalVals.length < C.min_transacoes_preco_m2_12m,
        });
      }
    }
  }

  // Etapa 5 (validação, 2026-09-29): também exige 3+ anúncios
  // (C.min_anuncios_alerta) — sem isso, um gap podia se sustentar sozinho
  // em 1 anúncio do lado pedido.
  const segmentoRepresentativo = (segmentos) => {
    const candidatos = segmentos.filter((s) => s.gap_pct != null && !s.amostra_pequena && s.n_anuncios >= C.min_anuncios_alerta);
    if (!candidatos.length) return null;
    return candidatos.sort((a, b) => b.n_transacoes_12m - a.n_transacoes_12m)[0];
  };

  const lookupMedianaPagoM2 = (segmentosBairro, tipoImovel, area) => {
    if (tipoImovel == null || !area) return null;
    const f = faixaMetragem(area, C.faixas_metragem);
    if (f == null) return null;
    const s = segmentosBairro.find((s) => s.tipo_imovel === tipoImovel && s.faixa === f);
    if (!s || s.amostra_pequena || !s.mediana_pago_m2) return null;
    return s.mediana_pago_m2;
  };

  // Etapa 2, item 1.2d (2026-10-01) — espelha engine.py._lookup_valor_total_mediana.
  const lookupValorTotalMediana = (segmentosBairro, tipoImovel, area) => {
    if (tipoImovel !== "apartamento" || !area) return null;
    const f = faixaMetragem(area, C.faixas_metragem);
    if (f == null) return null;
    const s = segmentosBairro.find((s) => s.tipo_imovel === tipoImovel && s.faixa === f);
    if (!s || s.amostra_pequena || !s.valor_total_mediana) return null;
    return s.valor_total_mediana;
  };

  const h1Count = (mc, year) => {
    let s = 0;
    for (let m = 1; m <= 6; m++) s += mc[`${year}-${m}`] || 0;
    return s;
  };

  const trend = {};
  TARGETS.forEach((b) => {
    const cPrev = yearly[b][yearPrev].count, cFull = yearly[b][yearFull].count;
    const growthPrev = cPrev > 0 ? (cFull - cPrev) / cPrev : null;
    const h1Full = h1Count(monthCounts[b], yearFull), h1Curr = h1Count(monthCounts[b], yearCurr);
    const growthH1 = h1Full > 0 ? (h1Curr - h1Full) / h1Full : null;
    const growths = [growthPrev, growthH1].filter((g) => g != null);
    const trendPct = growths.length ? mean(growths) : null;
    const trendCapped = trendPct == null ? null : Math.max(-C.trend_cap, Math.min(C.trend_cap, trendPct));
    trend[b] = {
      growth_prev_pct: growthPrev != null ? round(growthPrev * 100) : null,
      growth_h1_pct: growthH1 != null ? round(growthH1 * 100) : null,
      trend_pct: trendPct != null ? round(trendPct * 100) : null,
      trend_pct_for_score: trendCapped,
    };
  });

  // Item 4 da auditoria de 2026-09-30 — espelha engine.py._compute_volume_12m
  // (ver comentário lá pro porquê). Campos NOVOS, aditivos; volume_primary_year/
  // trend_pct acima ficam obsoletos mas com o MESMO cálculo de sempre.
  const VOLUME_12M_MIN_YM = [2024, 1];
  const VOLUME_12M_MESES_INCOMPLETOS = 2;
  const ymLt = (a, b) => a[0] * 12 + a[1] < b[0] * 12 + b[1];

  // Etapa 2, item 1.2b (2026-10-01): fim da janela vem de C.fim_janela_12m
  // (calculado no servidor sobre TODOS os registros antes de classificar
  // revenda/planta — ver build_data.build_raw_payload) — NÃO re-derivado
  // aqui a partir de itbiRecords, que no navegador só tem revenda+planta
  // (universo menor que o usado pra calcular o período no servidor; re-
  // derivar aqui escolhia um mês de corte diferente, mesmo bug do lado
  // Python corrigido com periodo_12m_externo em engine.compute()).
  const fimJanela = C.fim_janela_12m;
  const periodo12m = Array.from({ length: 12 }, (_, i) => ymAddMonths(fimJanela, -(11 - i)));
  const periodo12mAnterior = periodo12m.map((m) => ymAddMonths(m, -12));
  const mesesIncompletos = Array.from({ length: VOLUME_12M_MESES_INCOMPLETOS }, (_, i) => ymAddMonths(fimJanela, i + 1));
  const periodoSet = new Set(periodo12m.map(ymKey));
  const periodoAnteriorSet = new Set(periodo12mAnterior.map(ymKey));
  const incompletosSet = new Set(mesesIncompletos.map(ymKey));

  const countAtual = {}, countAnterior = {}, countRecenteParcial = {};
  // Item 2 da auditoria de 2026-09-30: volume_mercado_12m (só "1.Compra e
  // venda") e volume_retomadas_12m (alienação fiduciária + leilão) —
  // espelha engine.py._compute_volume_12m. countAtual/countAnterior (giro,
  // qualquer natureza) não mudam.
  const countMercadoAtual = {}, countMercadoAnterior = {}, countRetomadasAtual = {};
  // Etapa 2, item 1.2b (2026-10-01) — espelha os campos novos de
  // engine.py._compute_volume_12m: revenda_12m/planta_12m (tag
  // isRevenda/isPlanta, já resolvida no servidor).
  const countRevendaAtual = {}, countRevendaAnterior = {}, countPlantaAtual = {};
  TARGETS.forEach((b) => {
    countAtual[b] = 0; countAnterior[b] = 0; countRecenteParcial[b] = 0;
    countMercadoAtual[b] = 0; countMercadoAnterior[b] = 0; countRetomadasAtual[b] = 0;
    countRevendaAtual[b] = 0; countRevendaAnterior[b] = 0; countPlantaAtual[b] = 0;
  });
  for (const r of itbiRecords) {
    if (!(r.bairro in countAtual) || r.day == null) continue;
    const ym = excelSerialToYm(r.day);
    if (ymLt(ym, VOLUME_12M_MIN_YM)) continue;
    const k = ymKey(ym);
    if (periodoSet.has(k)) {
      countAtual[r.bairro] += 1;
      if (r.isCompraVenda) countMercadoAtual[r.bairro] += 1;
      else if (r.isRetomada) countRetomadasAtual[r.bairro] += 1;
      if (r.isRevenda) countRevendaAtual[r.bairro] += 1;
      else if (r.isPlanta) countPlantaAtual[r.bairro] += 1;
    } else if (periodoAnteriorSet.has(k)) {
      countAnterior[r.bairro] += 1;
      if (r.isCompraVenda) countMercadoAnterior[r.bairro] += 1;
      if (r.isRevenda) countRevendaAnterior[r.bairro] += 1;
    } else if (incompletosSet.has(k)) {
      countRecenteParcial[r.bairro] += 1;
    }
  }
  const trendPct12m = {}, trendPctMercado12m = {};
  TARGETS.forEach((b) => {
    const cAnt = countAnterior[b];
    trendPct12m[b] = cAnt > 0 ? round((countAtual[b] - cAnt) / cAnt * 100) : null;
    const cmAnt = countMercadoAnterior[b];
    trendPctMercado12m[b] = cmAnt > 0 ? round((countMercadoAtual[b] - cmAnt) / cmAnt * 100) : null;
  });

  // Etapa 2, item 1 (revisão 2026-10-01, decisão de mercado): score usa
  // SÓ revenda_12m (não mais volume_mercado_12m) como volume e
  // tendência — ver nota equivalente em engine.py compute(). Tendência
  // neutra (0) quando amostra pequena numa das duas janelas
  // (C.min_vendas_tendencia).
  const MIN_VENDAS_TENDENCIA = C.min_vendas_tendencia;
  const MIN_VENDAS_TOP10 = C.min_vendas_top10;
  const trendFracRevenda12mCapped = {}, trendPctRevenda12m = {}, amostraPequenaRanking = {};
  TARGETS.forEach((b) => {
    const atual = countRevendaAtual[b], anterior = countRevendaAnterior[b];
    if (atual >= MIN_VENDAS_TENDENCIA && anterior >= MIN_VENDAS_TENDENCIA && anterior > 0) {
      const frac = (atual - anterior) / anterior;
      trendFracRevenda12mCapped[b] = Math.max(-C.trend_cap, Math.min(C.trend_cap, frac));
      trendPctRevenda12m[b] = round(frac * 100);
    } else {
      trendFracRevenda12mCapped[b] = 0;
      trendPctRevenda12m[b] = null;
    }
    // Regra de amostra mínima (item 3): < 100 REVENDAS em 12m (não mercado).
    amostraPequenaRanking[b] = atual < MIN_VENDAS_TOP10;
  });
  const fmtYm = ([y, m]) => `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}`;
  const periodo12mMeta = {
    inicio: fmtYm(periodo12m[0]),
    fim: fmtYm(periodo12m[periodo12m.length - 1]),
    meses_incompletos: mesesIncompletos.map(fmtYm),
  };

  // --- 2. Estoque nonStop: agregação + centróides ---
  const usnByBairro = {};
  TARGETS.forEach((b) => (usnByBairro[b] = []));
  for (const r of usnRecords) if (r.bairro in usnByBairro) usnByBairro[r.bairro].push(r);

  const centroids = {};
  TARGETS.forEach((b) => {
    const pts = usnByBairro[b].filter((r) => coordIsValidSp(r.lat, r.lon)).map((r) => [r.lat, r.lon]);
    centroids[b] = pts.length ? [mean(pts.map((p) => p[0])), mean(pts.map((p) => p[1]))] : null;
  });

  const stockTotal = {}, askingMedian = {};
  TARGETS.forEach((b) => {
    stockTotal[b] = usnByBairro[b].length;
    askingMedian[b] = round(median(trimOutliersIqr(usnByBairro[b].map((r) => r.valor))), 2);
  });

  // --- 3. Perfil vencedor + fallback regional (Mudança 1) ---
  const profile = {};
  TARGETS.forEach((b) => {
    const ownPairs = pairsAllYears[b];
    const entry = {
      area_band: null, price_band: null, price_band_median: null,
      area_band_reliability: "insufficient", area_band_neighbors: [],
      profile_quartos: null, profile_vagas: null, profile_sample_size: 0,
      profile_reliability: "insufficient", profile_neighbors: [], profile_pool_sample_size: 0,
      profile_sample_size_faixa_preco: 0,
    };

    if (ownPairs.length >= C.reliability_threshold) {
      const [lo, hi, valores] = modeBucketFromPairs(ownPairs, C.area_bucket_width, C.max_per_exact_area);
      if (lo != null) {
        // trimOutliersIqr protege a faixa/mediana contra erro de digitação
        // isolado dentro do bucket de metragem vencedora — ver
        // scripts/engine.py._compute_profile (auditoria de 2026-09-25).
        const valoresOk = trimOutliersIqr(valores);
        entry.area_band = [lo, hi];
        entry.price_band = [round(percentile(25, valoresOk), 2), round(percentile(75, valoresOk), 2)];
        entry.price_band_median = round(median(valoresOk), 2);
        entry.area_band_reliability = "individual";
      }
    } else {
      const neighbors = nearestNeighbors(b, centroids, TARGETS, C.neighbor_max_km, C.neighbor_count);
      if (neighbors.length) {
        let pool = [...ownPairs];
        const neighborInfo = [];
        for (const [other, dist] of neighbors) {
          const nPairs = pairsAllYears[other];
          pool = pool.concat(nPairs);
          neighborInfo.push({ bairro: other, distancia_km: round(dist, 2), n_pares: nPairs.length });
        }
        const [lo, hi, valores] = modeBucketFromPairs(pool, C.area_bucket_width, C.max_per_exact_area);
        if (lo != null && valores.length) {
          const valoresOk = trimOutliersIqr(valores);
          entry.area_band = [lo, hi];
          entry.price_band = [round(percentile(25, valoresOk), 2), round(percentile(75, valoresOk), 2)];
          entry.price_band_median = round(median(valoresOk), 2);
          entry.area_band_reliability = "regional";
          entry.area_band_neighbors = neighborInfo;
        }
      }
    }

    const ownStock = usnByBairro[b];
    let inBand = [];
    if (entry.area_band) {
      const [lo, hi] = entry.area_band;
      inBand = ownStock.filter((r) => r.area != null && r.area >= lo && r.area < hi);
    }
    entry.profile_sample_size = inBand.length;
    entry.profile_quartos = modeOf(inBand.map((r) => r.quartos));
    entry.profile_vagas = modeOf(inBand.map((r) => r.vagas));
    entry._matching_listings = inBand; // uso interno (Estoque x Demanda), não vai pro output final

    // Etapa 2, revisão 2026-10-01 (migração do Prontidão): estoque no
    // perfil vencedor por FAIXA DE PREÇO (valor total), não metragem —
    // ver nota equivalente em scripts/engine.py._compute_profile. Usado
    // só pelo f2 do Prontidão, abaixo; profile_sample_size (área) segue
    // intacto pros outros consumidores.
    let inPriceBand = [];
    if (entry.price_band) {
      const [plo, phi] = entry.price_band;
      inPriceBand = ownStock.filter((r) => r.valor != null && r.valor >= plo && r.valor <= phi);
    }
    entry.profile_sample_size_faixa_preco = inPriceBand.length;

    if (entry.profile_sample_size >= C.reliability_threshold) {
      entry.profile_reliability = "individual";
    } else if (entry.area_band) {
      const neighbors = nearestNeighbors(b, centroids, TARGETS, C.neighbor_max_km, C.neighbor_count);
      const [lo, hi] = entry.area_band;
      let pool = [...inBand];
      const neighborInfo = [];
      for (const [other, dist] of neighbors) {
        const otherInBand = usnByBairro[other].filter((r) => r.area != null && r.area >= lo && r.area < hi);
        pool = pool.concat(otherInBand);
        neighborInfo.push({ bairro: other, distancia_km: round(dist, 2), n_imoveis: otherInBand.length });
      }
      if (pool.length >= 2) {
        entry.profile_quartos = modeOf(pool.map((r) => r.quartos));
        entry.profile_vagas = modeOf(pool.map((r) => r.vagas));
        entry.profile_reliability = "regional";
        entry.profile_pool_sample_size = pool.length;
        entry.profile_neighbors = neighborInfo;
      }
    }
    profile[b] = entry;
  });

  // --- 3b. Perfil vencedor — faixa de preço v2 (revisão 2026-10-01) ---
  // P25-P75 do valor TOTAL pago em revenda nos últimos 12 meses, por
  // bairro + tipo de imóvel, SEM metragem — ver nota equivalente em
  // scripts/engine.py._compute_perfil_vencedor_faixa_preco_v2.
  const PERFIL_PRECO_V2_TIPOS = ["apartamento", "casa"];
  const perfilPrecoV2 = {};
  TARGETS.forEach((b) => {
    const valoresPorTipo = { apartamento: [], casa: [] };
    perfilPrecoV2[b] = { bandas: {}, profile_sample_size_faixa_preco_v2: 0, estoque_fora_do_perfil: false };
    for (const r of itbiRecords) {
      if (r.bairro !== b || !r.isRevenda || r.day == null) continue;
      if (!PERFIL_PRECO_V2_TIPOS.includes(r.tipoImovel)) continue;
      if (!periodoSet.has(ymKey(excelSerialToYm(r.day)))) continue;
      valoresPorTipo[r.tipoImovel].push(r.valor);
    }
    const bandas = {};
    for (const tipo of PERFIL_PRECO_V2_TIPOS) {
      const valores = valoresPorTipo[tipo];
      if (!valores.length) {
        bandas[tipo] = null;
        continue;
      }
      const valoresOk = trimOutliersIqr(valores);
      bandas[tipo] = [round(percentile(25, valoresOk), 2), round(percentile(75, valoresOk), 2)];
    }
    const ownStock = usnByBairro[b];
    const inBandV2 = ownStock.filter((r) => {
      const banda = bandas[r.tipoImovel];
      return banda && r.valor != null && r.valor >= banda[0] && r.valor <= banda[1];
    });
    perfilPrecoV2[b] = {
      bandas,
      profile_sample_size_faixa_preco_v2: inBandV2.length,
      estoque_fora_do_perfil: ownStock.length > 0 && inBandV2.length === 0,
    };
  });

  // --- 4. Liquidez / Captação Ativa (agrupamento por endereço) ---
  const priceIncoherent = (valores) => {
    if (valores.length < 2) return false;
    const vmin = Math.min(...valores), vmax = Math.max(...valores);
    if (vmin < C.addr_min_valor) return true;
    if (vmin > 0 && vmax / vmin > C.addr_max_ratio) return true;
    return false;
  };
  // area_min/area_max de um endereço com 2+ unidades — [null,null] se a
  // razão máx/mín for grande demais pra confiar (provável erro de
  // digitação, não prédio misto de verdade). NÃO exclui o endereço da
  // Captação Ativa, só esconde a metragem exibida.
  const coherentAreaRange = (areas) => {
    if (!areas.length) return [null, null];
    const amin = Math.min(...areas), amax = Math.max(...areas);
    if (areas.length >= 2 && amin > 0 && amax / amin > C.addr_max_ratio_area) return [null, null];
    return [amin, amax];
  };
  const isLaunch = (daysIn) => {
    const days = daysIn.filter((d) => d != null).sort((a, b) => a - b);
    if (days.length < C.launch_min_count) return false;
    for (let i = 0; i < days.length; i++) {
      let cnt = 1;
      for (let j = i + 1; j < days.length; j++) {
        if (days[j] - days[i] > C.launch_window_days) break;
        cnt++;
      }
      if (cnt >= C.launch_min_count) return true;
    }
    return false;
  };

  const usnByAddrKey = {};
  for (const r of usnRecords) if (r.addrKey != null) (usnByAddrKey[r.addrKey] ||= []).push(r);

  const temUnidadeHoje = (recs) => {
    const ativos = (recs || []).filter((r) => r.situacaoCode !== 3 && r.situacaoCode !== 4);
    return [ativos.length > 0, ativos.map((r) => ({ codigo: r.codigo, valor: r.valor, link: r.link }))];
  };

  const byAddr = {};
  for (const r of itbiRecords) if (r.addrKey != null) (byAddr[r.addrKey] ||= []).push(r);

  // addrKey é só rua+número (o mesmo prédio pode ter linhas do ITBI com
  // bairro diferente entre si — dado preenchido por transação, não fixo do
  // prédio). Usa o bairro mais frequente entre as vendas reais do
  // endereço; empate resolvido alfabeticamente (mesmo critério de
  // scripts/engine.py::_majority_bairro).
  const majorityBairro = (recs) => {
    const counts = {};
    for (const r of recs) counts[r.bairro] = (counts[r.bairro] || 0) + 1;
    return Object.keys(counts).sort((a, b) => (counts[b] - counts[a]) || cmpLower(a, b))[0];
  };

  const liquidez = {};
  TARGETS.forEach((b) => (liquidez[b] = { [yearPrev]: { total: 0, revenda: 0 }, [yearFull]: { total: 0, revenda: 0 }, [yearCurr]: { total: 0, revenda: 0 } }));
  const captacaoAtiva = [], captacaoUnico = [];
  let nAddrDiscarded = 0, nAddrLaunch = 0, nAddrTotalMulti = 0, nAddrSemVendaReal = 0;

  for (const addrKey of Object.keys(byAddr)) {
    const allRecs = byAddr[addrKey];
    // Volume/liquidez conta TODA transação residencial válida, no bairro em
    // que foi de fato registrada linha a linha — não muda com o filtro de
    // natureza abaixo, que só afeta a identidade do PRÉDIO (Captação Ativa).
    for (const r of allRecs) if (liquidez[r.bairro][r.sheetYear]) liquidez[r.bairro][r.sheetYear].total++;

    // Só venda válida conta como venda de mercado pro histórico de PREÇO
    // de um endereço (mesmo critério da mediana de bairro — ver isValidSale).
    const recs = allRecs.filter(isValidSale);
    if (!recs.length) { nAddrSemVendaReal++; continue; }

    const bairro = majorityBairro(recs);
    const endereco = recs.find((r) => r.addrDisplay)?.addrDisplay || String(addrKey);
    const [temHoje, unidadesHoje] = temUnidadeHoje(usnByAddrKey[addrKey]);

    if (recs.length === 1) {
      const r = recs[0];
      if (liquidez[bairro][r.sheetYear]) liquidez[bairro][r.sheetYear].revenda++;
      captacaoUnico.push({
        bairro, addr_key: addrKey, endereco, n_vendas: 1, preco_min: r.valor, preco_max: r.valor,
        area_min: r.area, area_max: r.area, tem_unidade_a_venda_hoje: temHoje, unidades_a_venda_hoje: unidadesHoje,
      });
      continue;
    }

    nAddrTotalMulti++;
    const valores = recs.map((r) => r.valor);
    if (priceIncoherent(valores)) { nAddrDiscarded++; continue; }
    if (isLaunch(recs.map((r) => r.day))) { nAddrLaunch++; continue; }

    for (const r of recs) if (liquidez[bairro][r.sheetYear]) liquidez[bairro][r.sheetYear].revenda++;
    const areas = recs.map((r) => r.area).filter((a) => a != null);
    const [areaMin, areaMax] = coherentAreaRange(areas);
    captacaoAtiva.push({
      bairro, addr_key: addrKey, endereco, n_vendas: recs.length,
      preco_min: Math.min(...valores), preco_max: Math.max(...valores), preco_medio: round(mean(valores), 2),
      area_min: areaMin, area_max: areaMax,
      tem_unidade_a_venda_hoje: temHoje, unidades_a_venda_hoje: unidadesHoje,
    });
  }
  captacaoAtiva.sort((a, b) => cmpLower(a.bairro, b.bairro) || b.n_vendas - a.n_vendas || String(a.addr_key).localeCompare(String(b.addr_key)));
  // addr_key vira string ao passar por Object.keys(byAddr) — normaliza pra
  // String() dos dois lados na hora de comparar, senão Set.has(numero) falha
  // silenciosamente contra chaves guardadas como string.
  const addrInCaptacaoAtiva = new Set(captacaoAtiva.map((c) => String(c.addr_key)));

  // --- montagem preliminar por bairro (todos os 47 — o filtro de bairro só entra na normalização/ranking) ---
  const bairrosOut = {};
  TARGETS.forEach((b) => {
    // Volume "de referência" = média anual dos 3 anos, não só o último
    // fechado (ver scripts/engine.py.compute — decisão do usuário, 2026-09-25).
    const volumePrimary = round(mean([yearly[b][yearPrev].count, yearly[b][yearFull].count, yearly[b][yearCurr].count]), 0);
    const stockMatch = profile[b].profile_sample_size;
    const demand = volumePrimary;
    const ratio = demand > 0 ? stockMatch / demand : (stockMatch > 0 ? 999 : 0);
    const paidMedian = pooledMedian[b].median_valor;
    const asking = askingMedian[b];
    // Gap Preço / flag_alerta (Etapa 3, 2026-09-29): segmento (tipo+faixa)
    // mais representativo do bairro, não bairro inteiro x bairro inteiro
    // — ver scripts/engine.py.compute.
    const segmentoRep = segmentoRepresentativo(precoM2[b]);
    const priceGapPct = segmentoRep ? segmentoRep.gap_pct : null;

    const unidadesIptu = raw.unidades_iptu ? raw.unidades_iptu[b] : null;
    const revenda12m = countRevendaAtual[b];
    const giro12mPct = unidadesIptu ? round(100 * revenda12m / unidadesIptu, 2) : null;

    bairrosOut[b] = {
      yearly: { [yearPrev]: yearly[b][yearPrev], [yearFull]: yearly[b][yearFull], [yearCurr]: yearly[b][yearCurr] },
      ...trend[b],
      volume_primary_year: volumePrimary,
      volume_12m: countAtual[b],
      trend_pct_12m: trendPct12m[b],
      volume_recente_parcial: countRecenteParcial[b],
      volume_mercado_12m: countMercadoAtual[b],
      trend_pct_mercado_12m: trendPctMercado12m[b],
      volume_retomadas_12m: countRetomadasAtual[b],
      // Etapa 2, item 1.2b/3 (2026-10-01) — base nova (ver engine.py.compute).
      revenda_12m: revenda12m,
      planta_12m: countPlantaAtual[b],
      unidades_iptu: unidadesIptu,
      giro_12m_pct: giro12mPct,
      trend_pct_revenda_12m: trendPctRevenda12m[b],
      amostra_pequena_ranking: amostraPequenaRanking[b],
      preco_m2_segmentos: precoM2[b],
      area_band: profile[b].area_band, price_band: profile[b].price_band, price_band_median: profile[b].price_band_median,
      profile_quartos: profile[b].profile_quartos, profile_vagas: profile[b].profile_vagas,
      profile_sample_size: profile[b].profile_sample_size,
      area_band_reliability: profile[b].area_band_reliability, area_band_neighbors: profile[b].area_band_neighbors,
      profile_reliability: profile[b].profile_reliability, profile_neighbors: profile[b].profile_neighbors,
      profile_pool_sample_size: profile[b].profile_pool_sample_size,
      stock_total: stockTotal[b], stock_matching_profile: stockMatch,
      // Revisão 2026-10-01 (v2): estoque no perfil vencedor por FAIXA DE
      // PREÇO vem do valor pago em revenda (12m, por tipo) — ver nota
      // equivalente em scripts/engine.py.compute.
      estoque_perfil_faixa_preco: perfilPrecoV2[b].profile_sample_size_faixa_preco_v2,
      perfil_vencedor_faixa_preco_v2: perfilPrecoV2[b].bandas,
      estoque_fora_do_perfil: perfilPrecoV2[b].estoque_fora_do_perfil,
      asking_median_valor: asking, paid_median_valor_primary_year: paidMedian,
      centroid: centroids[b],
      stock_demand_ratio: Math.round(ratio * 1000) / 1000, price_gap_pct: priceGapPct,
      flag_alerta: priceGapPct != null && Math.abs(priceGapPct) >= 20,
      liquidez_total_primary_year: round(mean([liquidez[b][yearPrev].total, liquidez[b][yearFull].total, liquidez[b][yearCurr].total]), 0),
      liquidez_revenda_primary_year: round(mean([liquidez[b][yearPrev].revenda, liquidez[b][yearFull].revenda, liquidez[b][yearCurr].revenda]), 0),
      liquidez_por_ano: { [yearPrev]: liquidez[b][yearPrev], [yearFull]: liquidez[b][yearFull], [yearCurr]: liquidez[b][yearCurr] },
      _matching_listings: profile[b]._matching_listings,
    };
  });

  // --- Painel 1: score — normalização SÓ entre os bairros do escopo ---
  // Etapa 2, item 1 (revisão 2026-10-01, decisão de mercado): volume e
  // tendência = SÓ revenda_12m/trendFracRevenda12mCapped — não mais
  // volume_mercado_12m. Nota: isso deixa `score` e `score_revenda`
  // (abaixo) matematicamente idênticos (mesmo insumo) — consequência
  // esperada da decisão, ver nota equivalente em engine.py compute().
  const volumeMapScope = {}; scope.forEach((b) => (volumeMapScope[b] = bairrosOut[b].revenda_12m));
  const trendZInputScope = {}; scope.forEach((b) => (trendZInputScope[b] = trendFracRevenda12mCapped[b]));
  const trendZScope = zscoreMap(trendZInputScope);
  const volZScope = zscoreMap(volumeMapScope);
  const combinedScope = {}; scope.forEach((b) => (combinedScope[b] = (volZScope[b] + trendZScope[b]) / 2));
  const scoreMapScope = minmaxRescale0to100(combinedScope);

  const ratiosSorted = scope.map((b) => bairrosOut[b].stock_demand_ratio).sort((a, b) => a - b);
  const lowTercile = tercile(ratiosSorted, 1 / 3);

  // score_revenda: mesma fórmula, mesmo insumo que `score` agora (ver nota acima).
  const revendaMapScope = {}; scope.forEach((b) => (revendaMapScope[b] = bairrosOut[b].revenda_12m));
  const revendaZScope = zscoreMap(revendaMapScope);
  const combinedRevendaScope = {}; scope.forEach((b) => (combinedRevendaScope[b] = (revendaZScope[b] + trendZScope[b]) / 2));
  const scoreRevendaMapScope = minmaxRescale0to100(combinedRevendaScope);

  const totalRatioMapScope = {};
  scope.forEach((b) => {
    const demand = bairrosOut[b].revenda_12m, st = bairrosOut[b].stock_total;
    totalRatioMapScope[b] = demand > 0 ? st / demand : (st > 0 ? 999 : 0);
  });
  const totalRatiosSorted = Object.values(totalRatioMapScope).sort((a, b) => a - b);
  const highTercile = tercile(totalRatiosSorted, 2 / 3);

  scope.forEach((b) => {
    const bo = bairrosOut[b];
    bo.score = round(scoreMapScope[b]);
    bo.flag_oportunidade = bo.stock_demand_ratio <= lowTercile && bo.revenda_12m > 0;
    bo.score_revenda = round(scoreRevendaMapScope[b]);
    bo.stock_total_demand_ratio = Math.round(totalRatioMapScope[b] * 1000) / 1000;
    bo.flag_saturacao_alta = totalRatioMapScope[b] >= highTercile;
    bo.flag_prioridade_maxima = bo.stock_matching_profile <= C.captacao_estrategica_max_stock_match
      && bo.revenda_12m >= C.valor_oportunidade_min_vendas_primary;
  });

  const ranking = [...scope].sort((a, b) => bairrosOut[b].score - bairrosOut[a].score);

  // --- Painel 8: imóveis prioritários (só imóveis em bairros do escopo) ---
  const priceAlignmentScore = (valor, mediana) => {
    if (mediana == null || mediana <= 0 || valor == null) return { score: 50, zone: "sem_referencia", ratio: null };
    const ratio = valor / mediana;
    if (ratio > 1.0) return { score: Math.max(0, 100 - (ratio - 1) * 100), zone: "acima", ratio };
    if (ratio >= 0.7) return { score: 100, zone: "normal", ratio };
    const s = 100 - (0.7 - ratio) * 200;
    return { score: Math.max(30, s), zone: "cautela", ratio };
  };
  const diffScore = (a, b) => {
    if (a == null || b == null) return 50;
    const diff = Math.abs(a - b);
    return diff === 0 ? 100 : diff === 1 ? 50 : 0;
  };
  const resumoImovel = (price, aderenciaFinal, areaConf, scoreRevendaBairro, temCaptacao) => {
    const frases = [];
    const ratio = price.ratio;
    if (price.zone === "cautela" && ratio != null) frases.push(`R$/m² ${Math.round((1 - ratio) * 100)}% abaixo do histórico de imóveis do mesmo tipo/tamanho — vale checar antes de anunciar`);
    else if (price.zone === "acima" && price.score < 60 && ratio != null) frases.push(`R$/m² ${Math.round((ratio - 1) * 100)}% acima do que se pagou em imóveis do mesmo tipo/tamanho`);
    else if (price.zone === "normal" && ratio != null && ratio < 0.97) frases.push(`R$/m² ${Math.round((1 - ratio) * 100)}% abaixo da mediana paga em imóveis do mesmo tipo/tamanho`);
    if (aderenciaFinal >= 80) frases.push(`Bate com o perfil vencedor do bairro${areaConf < 1 ? " (estimativa regional)" : ""}`);
    if (scoreRevendaBairro >= 70) frases.push("Bairro com liquidez de revenda alta");
    if (temCaptacao) frases.push("Prédio com histórico de giro comprovado");
    return frases.slice(0, 2).join(" · ");
  };

  const imoveisPrioritarios = [];
  for (const u of usnRecords) {
    if (u.valor == null || u.valor <= 0) continue;
    if (!scopeSet.has(u.bairro)) continue;
    const b = bairrosOut[u.bairro];
    if (!b) continue;

    // Etapa 3 (2026-09-29): R$/m² do anúncio x mediana do MESMO tipo de
    // imóvel + faixa de metragem, não valor total x mediana do bairro
    // inteiro — ver scripts/engine.py._compute_imoveis_prioritarios.
    // Etapa 2, item 1.2d (2026-10-01): apartamento compara VALOR TOTAL
    // pedido x mediana de revenda (não mais R$/m²) — casa não muda.
    let valorComparacao, medianaComparacao;
    if (u.tipoImovel === "apartamento") {
      medianaComparacao = lookupValorTotalMediana(b.preco_m2_segmentos, u.tipoImovel, u.area);
      valorComparacao = u.valor;
    } else {
      valorComparacao = u.area ? u.valor / u.area : null;
      medianaComparacao = lookupMedianaPagoM2(b.preco_m2_segmentos, u.tipoImovel, u.area);
    }
    const price = priceAlignmentScore(valorComparacao, medianaComparacao);
    const areaBand = b.area_band, areaConf = confidence(b.area_band_reliability);
    let areaRaw = 50;
    if (areaBand && u.area != null) {
      const [lo, hi] = areaBand;
      if (u.area >= lo && u.area < hi) areaRaw = 100;
      else {
        const bandWidth = hi - lo;
        const dist = u.area < lo ? lo - u.area : u.area - hi;
        areaRaw = bandWidth > 0 ? Math.max(0, 100 - (dist / bandWidth) * 100) : 50;
      }
    }
    const areaScore = 50 + (areaRaw - 50) * areaConf;
    const profileConf = confidence(b.profile_reliability);
    const quartosScore = 50 + (diffScore(u.quartos, b.profile_quartos) - 50) * profileConf;
    const vagasScore = 50 + (diffScore(u.vagas, b.profile_vagas) - 50) * profileConf;
    const aderencia = mean([areaScore, quartosScore, vagasScore]);
    const temCaptacao = u.addrKey != null && addrInCaptacaoAtiva.has(String(u.addrKey));
    const bonus = temCaptacao ? 100 : 0;
    const finalScore = C.pesos_painel8.revenda * b.score_revenda + C.pesos_painel8.preco * price.score
      + C.pesos_painel8.aderencia * aderencia + C.pesos_painel8.captacao * bonus;

    imoveisPrioritarios.push({
      bairro: u.bairro, endereco: u.addrDisplay, codigo: u.codigo, link: u.link,
      valor: u.valor, area: u.area, quartos: u.quartos, vagas: u.vagas, tipo_imovel: u.tipoImovel, addr_key: u.addrKey,
      score_bairro_revenda: round(b.score_revenda), price_alignment: round(price.score),
      profile_adherence: round(aderencia), tem_captacao_ativa: temCaptacao,
      area_band_reliability: b.area_band_reliability, profile_reliability: b.profile_reliability,
      final_score: round(finalScore, 2), resumo: resumoImovel(price, aderencia, areaConf, b.score_revenda, temCaptacao),
    });
  }
  // Desempate por endereço (minúsculas) + código — nunca addr_key: aqui é
  // um índice inteiro interno, diferente da chave composta em string do
  // lado Python, então usá-lo divergiria o desempate entre os dois motores.
  imoveisPrioritarios.sort((a, b) => b.final_score - a.final_score || cmpLower(a.endereco || "", b.endereco || "") || String(a.codigo || "").localeCompare(String(b.codigo || "")));

  // --- Painel 2: Prontidão ---
  // Etapa 2, revisão 2026-10-01: f2 agora usa estoque_perfil_faixa_preco
  // (faixa de preço) em vez de stock_matching_profile (metragem) — ver
  // nota equivalente em scripts/engine.py.compute.
  const stockMatchScope = {}; scope.forEach((b) => (stockMatchScope[b] = bairrosOut[b].estoque_perfil_faixa_preco));
  const f2MapScope = normalize0to100(stockMatchScope);
  const f4Counts = {}; scope.forEach((b) => (f4Counts[b] = 0));
  for (const c of captacaoAtiva) if (f4Counts[c.bairro] != null) f4Counts[c.bairro]++;
  const f4MapScope = normalize0to100(f4Counts);

  const imoveisByBairro = {};
  for (const im of imoveisPrioritarios) (imoveisByBairro[im.bairro] ||= []).push(im);

  // Etapa 3 (2026-09-29): desconto compara R$/m² do anúncio x mediana R$/m²
  // do MESMO tipo de imóvel + faixa de metragem — não mais valor total x
  // mediana de todos os tamanhos do bairro. "amostra pequena" do segmento
  // (lookupMedianaPagoM2 já devolve null nesse caso) substitui o antigo
  // gate por volume do bairro inteiro — ver
  // scripts/engine.py._compute_valor_oportunidade.
  const valorOportunidadeImoveis = [];
  const elegivelByBairro = {};
  for (const im of imoveisPrioritarios) {
    const b = bairrosOut[im.bairro];
    const isApto = im.tipo_imovel === "apartamento";
    // Etapa 2, item 1.2d (2026-10-01): apartamento compara VALOR TOTAL
    // pedido x mediana de revenda — casa não muda.
    let medianaRef, valorRef;
    if (isApto) {
      medianaRef = lookupValorTotalMediana(b.preco_m2_segmentos, im.tipo_imovel, im.area);
      valorRef = im.valor;
    } else {
      medianaRef = lookupMedianaPagoM2(b.preco_m2_segmentos, im.tipo_imovel, im.area);
      valorRef = im.area ? im.valor / im.area : null;
    }
    if (medianaRef == null || valorRef == null) continue;
    elegivelByBairro[im.bairro] = (elegivelByBairro[im.bairro] || 0) + 1;
    const ratio = valorRef / medianaRef, desconto = 1 - ratio;
    if (desconto < C.valor_oportunidade_min_desconto) continue;
    valorOportunidadeImoveis.push({
      bairro: im.bairro, endereco: im.endereco, codigo: im.codigo, link: im.link,
      valor: im.valor, area: im.area, tipo_imovel: im.tipo_imovel, faixa: faixaMetragem(im.area, C.faixas_metragem),
      valor_m2: isApto ? null : round(valorRef, 2), mediana_pago_m2: isApto ? null : medianaRef,
      valor_total_mediana: isApto ? medianaRef : null,
      desconto_pct: round(desconto * 100), atencao: desconto >= C.valor_oportunidade_atencao_desconto,
    });
  }
  valorOportunidadeImoveis.sort((a, b) => b.desconto_pct - a.desconto_pct || cmpLower(a.endereco || "", b.endereco || "") || String(a.codigo || "").localeCompare(String(b.codigo || "")));

  const achadosByBairro = {};
  for (const a of valorOportunidadeImoveis) achadosByBairro[a.bairro] = (achadosByBairro[a.bairro] || 0) + 1;

  scope.forEach((b) => {
    const bo = bairrosOut[b];
    const f1 = bo.score, f2 = f2MapScope[b];
    const gap = bo.price_gap_pct;
    const f3 = gap != null ? Math.max(0, 100 - Math.abs(gap) * 2) : 50;
    const f4 = f4MapScope[b];

    const top10 = (imoveisByBairro[b] || []).slice(0, 10);
    const nIm = (imoveisByBairro[b] || []).length;
    const meanTop10 = top10.length ? mean(top10.map((t) => t.final_score)) : 0;
    const coverage = Math.min(1, nIm / 10);
    const f5 = meanTop10 * coverage;

    // f6 usa a MESMA elegibilidade por segmento do Valor de Oportunidade
    // (antes recalculava com o gate antigo por volume do bairro inteiro).
    const estoqueEleg = elegivelByBairro[b] || 0;
    let f6;
    if (estoqueEleg === 0) f6 = 50;
    else {
      const achadosBairro = achadosByBairro[b] || 0;
      f6 = (100 * achadosBairro) / estoqueEleg;
    }

    const prontidao = C.pesos_prontidao.f1 * f1 + C.pesos_prontidao.f2 * f2 + C.pesos_prontidao.f3 * f3
      + C.pesos_prontidao.f4 * f4 + C.pesos_prontidao.f5 * f5 + C.pesos_prontidao.f6 * f6;
    bo.prontidao_campanha = round(prontidao);
  });

  const prontidaoRanking = [...scope].sort((a, b) => bairrosOut[b].prontidao_campanha - bairrosOut[a].prontidao_campanha);
  const valorOportunidadePorBairro = Object.entries(achadosByBairro).map(([bairro, n]) => {
    const total = elegivelByBairro[bairro] || 0;
    return { bairro, n_achados: n, estoque_total: total, pct_do_estoque: total ? round((100 * n) / total) : null };
  }).sort((a, b) => b.n_achados - a.n_achados || cmpLower(a.bairro, b.bairro));

  // --- Painel 7: Captação Ativa Estratégica ---
  // Mudança 13: não exclui mais endereços com unidade ativa hoje — um
  // prédio com giro comprovado continua valendo a visita pra tentar captar
  // OUTRAS unidades. "tem_unidade_a_venda_hoje" vira dado exibido, não
  // filtro de exclusão.
  const byBairroAtiva = {}, byBairroUnico = {};
  for (const c of captacaoAtiva) if (scopeSet.has(c.bairro)) (byBairroAtiva[c.bairro] ||= []).push(c);
  for (const c of captacaoUnico) if (scopeSet.has(c.bairro)) (byBairroUnico[c.bairro] ||= []).push(c);

  const captacaoEstrategica = [];
  scope.forEach((b) => {
    let enderecos = [...(byBairroAtiva[b] || [])];
    if (enderecos.length < C.captacao_estrategica_min_enderecos) {
      const extra = byBairroUnico[b] || [];
      if (extra.length) enderecos = enderecos.concat(extra.map((e) => ({ ...e, unico: true })));
    }
    if (!enderecos.length) return;
    enderecos.forEach((e) => { if (e.unico === undefined) e.unico = false; });
    // Sem unidade ativa primeiro (só prospecção resolve o acesso); depois
    // mais vendas, depois alfabético em minúsculas (comparação simples de
    // string, não localeCompare — evita divergir do Python, que compara
    // case-sensitive por padrão).
    enderecos.sort((a, c) => {
      if (a.tem_unidade_a_venda_hoje !== c.tem_unidade_a_venda_hoje) return a.tem_unidade_a_venda_hoje ? 1 : -1;
      if (c.n_vendas !== a.n_vendas) return c.n_vendas - a.n_vendas;
      const al = a.endereco.toLowerCase(), cl = c.endereco.toLowerCase();
      return al < cl ? -1 : al > cl ? 1 : 0;
    });

    const bo = bairrosOut[b];
    captacaoEstrategica.push({
      bairro: b, flag_prioridade_maxima: bo.flag_prioridade_maxima,
      perfil: { area_band: bo.area_band, price_band: bo.price_band, profile_quartos: bo.profile_quartos, profile_vagas: bo.profile_vagas, profile_reliability: bo.profile_reliability },
      enderecos: enderecos.map((e) => ({
        endereco: e.endereco, n_vendas: e.n_vendas, preco_min: e.preco_min, preco_max: e.preco_max,
        area_min: e.area_min, area_max: e.area_max, unico: e.unico,
        tem_unidade_a_venda_hoje: e.tem_unidade_a_venda_hoje, unidades_a_venda_hoje: e.unidades_a_venda_hoje,
      })),
    });
  });
  captacaoEstrategica.sort((a, b) => (a.flag_prioridade_maxima ? 0 : 1) - (b.flag_prioridade_maxima ? 0 : 1)
    || bairrosOut[b.bairro].volume_primary_year - bairrosOut[a.bairro].volume_primary_year
    || cmpLower(a.bairro, b.bairro));

  // --- saída final: só os bairros do escopo ---
  const bairrosFinal = {};
  scope.forEach((b) => {
    const { _matching_listings, ...rest } = bairrosOut[b];
    // Interesse de busca não é recalculado por filtro (é um sinal externo,
    // classificado por tercil contra os 47 bairros inteiros — ver
    // build_data.py._get_search_interest) — só repassa se existir.
    if (raw.search_interest && raw.search_interest[b]) rest.search_interest = raw.search_interest[b];
    bairrosFinal[b] = rest;
  });
  const captacaoAtivaFinal = captacaoAtiva.filter((c) => scopeSet.has(c.bairro));

  return {
    meta: { years: raw.years, primary_year: yearFull, inprogress_year: yearCurr, enderecos_captacao_ativa: captacaoAtivaFinal.length },
    periodo_12m: periodo12mMeta,
    ranking,
    prontidao_ranking: prontidaoRanking,
    bairros: bairrosFinal,
    captacao_ativa: captacaoAtivaFinal,
    imoveis_prioritarios: imoveisPrioritarios,
    valor_oportunidade: { imoveis: valorOportunidadeImoveis, por_bairro: valorOportunidadePorBairro },
    captacao_estrategica: captacaoEstrategica,
    preco_m2_painel: precoM2Painel.filter((p) => scopeSet.has(p.bairro)),
    // uso interno pro painel Estoque x Demanda (listagens que batem o perfil vencedor)
    _matchingListingsByBairro: Object.fromEntries(scope.map((b) => [b, bairrosOut[b]._matching_listings])),
  };
}
