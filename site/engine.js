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
  for (const [bIdx, addrIdx, addrDisplay, valor, area, quartos, vagas, lat, lon, situacaoCode, codigo, link, tipoImovel, idadeDias] of raw.usn) {
    if (!inPriceRange(valor)) continue;
    usn.push({
      bairro: raw.bairros[bIdx], addrKey: addrIdx, addrDisplay, valor, area, quartos, vagas,
      lat, lon, situacaoCode, codigo, link, tipoImovel, idadeDias,
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
  // Captação limpa (2026-10-05): Captação Ativa conta vendas e calcula preço
  // só sobre REVENDA LIMPA (is_revenda + is_clean_sale) — ver nota
  // equivalente em scripts/engine.py._is_revenda_limpa.
  const isRevendaLimpa = (r) => !!r.isRevenda && !!r.isCleanSale;

  // Proteção de amostra das faixas de preço (2026-10-06) — espelha
  // scripts/engine.py (janelas_meses / escolher_janela / _meta_janela):
  // 12 meses se houver >= C.perfil_min_vendas_faixa vendas limpas no
  // bairro+tipo; senão 24; senão 36; abaixo disso "poucas vendas" (a faixa
  // aparece, mas não entra nas notas). Janelas terminam em C.fim_janela_12m
  // e são cortadas em C.inicio_dados (histórico completo).
  const JANELAS = C.perfil_janelas_meses;
  const ymGe = (a, b) => a[0] * 12 + a[1] >= b[0] * 12 + b[1];
  const janelasMeses = {};
  {
    const meses = [C.fim_janela_12m];
    for (let i = 1; i < Math.max(...JANELAS); i++) meses.push(ymAddMonths(meses[meses.length - 1], -1));
    for (const w of JANELAS) janelasMeses[w] = meses.slice(0, w).filter((m) => ymGe(m, C.inicio_dados)).reverse();
  }
  const janelasSet = {};
  for (const w of JANELAS) janelasSet[w] = new Set(janelasMeses[w].map(ymKey));
  const escolherJanela = (contagens) => {
    for (const w of JANELAS) if (contagens[w] >= C.perfil_min_vendas_faixa) return [w, false];
    return [Math.max(...JANELAS), true];
  };
  const ymFmt = ([y, m]) => `${String(y).padStart(4, "0")}-${String(m).padStart(2, "0")}`;
  const metaJanela = (w, n, poucas) => {
    const ms = janelasMeses[w];
    return { janela_meses: w, meses_com_dado: ms.length, periodo_inicio: ymFmt(ms[0]), periodo_fim: ymFmt(ms[ms.length - 1]), n_vendas_limpas: n, poucas_vendas: poucas };
  };
  const CAPTACAO_MIN_VENDAS_FAIXA = C.captacao_min_vendas_faixa;

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
      const vals = yearlyValoresVenda[b][y]; // camada limpa única: sem corte extra
      yearly[b][y] = { count: yearlyCount[b][y], avg_valor: round(mean(vals), 2), median_valor: round(median(vals), 2) };
    });
  });

  // Mediana "de referência" (Ranking, Prontidão, Estoque×Demanda, Valor de
  // Oportunidade) = pool dos 3 anos juntos, não só o último fechado (ver
  // scripts/engine.py._aggregate_itbi — decisão do usuário, 2026-09-25).
  const pooledMedian = {};
  TARGETS.forEach((b) => {
    const pool = [yearPrev, yearFull, yearCurr].flatMap((y) => yearlyValoresVenda[b][y]);
    const vals = pool; // camada limpa única: sem corte extra
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
      const valorTotalLimpos = valorTotalVals; // camada limpa única: sem corte extra
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
  // (isRevendaLimpa) — gap_pct/mediana_pago_m2/mediana_pedido_m2 ficam
  // sempre null agora (suspensos, calibração fica pra depois); campos
  // novos valor_total_*/n_vendas_revenda_12m são aditivos.
  const precoM2Painel = [];
  {
    const pago = {}, pedido = {}, valorTotal = {};
    for (const r of itbiRecords) {
      if (!(r.bairro in yearlyCount) || r.tipoImovel !== "apartamento") continue;
      const f = faixaMetragem(r.area, C.faixas_metragem);
      if (f == null) continue;
      const key = `${r.bairro}\u0001${f}`;
      if (r.day != null && (C.hoje_serial - r.day) >= 0 && (C.hoje_serial - r.day) <= C.janela_preco_m2_dias && r.isCleanSale) {
        (pago[key] ||= []).push(round(r.valor / r.area, 2));
      }
      if (r.day != null && isRevendaLimpa(r)) {
        const k = ymKey(excelSerialToYm(r.day));
        for (const w of JANELAS) {
          if (janelasSet[w].has(k)) {
            valorTotal[key] ||= Object.fromEntries(JANELAS.map((w2) => [w2, []]));
            valorTotal[key][w].push(r.valor);
          }
        }
      }
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
        const porJanela = valorTotal[key];
        if (!pagoVals.length && !porJanela && !(key in pedido)) continue;
        let janelaUsada, poucas, valorTotalVals;
        if (porJanela) {
          [janelaUsada, poucas] = escolherJanela(Object.fromEntries(JANELAS.map((w) => [w, porJanela[w].length])));
          valorTotalVals = porJanela[janelaUsada];
        } else {
          janelaUsada = Math.max(...JANELAS); poucas = true; valorTotalVals = [];
        }
        const metaJ = metaJanela(janelaUsada, valorTotalVals.length, poucas);

        const valorTotalLimpos = valorTotalVals; // camada limpa única: sem corte extra
        const valorTotalMediana = valorTotalLimpos.length ? round(median(valorTotalLimpos), 2) : null;
        const valorTotalP25 = valorTotalLimpos.length ? round(percentile(25, valorTotalLimpos), 2) : null;
        const valorTotalP75 = valorTotalLimpos.length ? round(percentile(75, valorTotalLimpos), 2) : null;

        precoM2Painel.push({
          bairro, faixa,
          mediana_pago_m2: null, mediana_pedido_m2: null, gap_pct: null,
          valor_total_mediana: valorTotalMediana, valor_total_p25: valorTotalP25, valor_total_p75: valorTotalP75,
          n_vendas_revenda_12m: valorTotalVals.length,
          janela_meses: metaJ.janela_meses, meses_com_dado: metaJ.meses_com_dado,
          periodo_inicio: metaJ.periodo_inicio, periodo_fim: metaJ.periodo_fim, poucas_vendas: poucas,
          n_transacoes_12m: pagoVals.length, n_anuncios: (pedido[key] || []).length,
          amostra_pequena: poucas,
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

  // SUSPENSA (passo 2b, 2026-10-01) — nenhum chamador usa mais esta
  // função hoje (ver nota equivalente em engine.py._lookup_valor_total_
  // mediana); mantida pro backlog de calibração de área.
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
        const valoresOk = valores; // campo OBSOLETO v1; camada limpa única, sem corte extra
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
          const valoresOk = valores; // campo OBSOLETO v1; camada limpa única, sem corte extra
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
  // (bairro, tipo) -> {janela: [valores]} (cumulativo 12 ⊂ 24 ⊂ 36), numa passada só.
  const valsV2 = {};
  TARGETS.forEach((b) => PERFIL_PRECO_V2_TIPOS.forEach((t) => (valsV2[`${b}\u0001${t}`] = Object.fromEntries(JANELAS.map((w) => [w, []])))));
  for (const r of itbiRecords) {
    // Camada limpa única (2026-10-05): só revenda limpa (is_revenda + is_clean_sale).
    if (!isRevendaLimpa(r) || r.day == null) continue;
    const alvo = valsV2[`${r.bairro}\u0001${r.tipoImovel}`];
    if (!alvo) continue;
    const k = ymKey(excelSerialToYm(r.day));
    for (const w of JANELAS) if (janelasSet[w].has(k)) alvo[w].push(r.valor);
  }
  TARGETS.forEach((b) => {
    const bandas = {}, faixaMeta = {}, confiavel = {};
    for (const tipo of PERFIL_PRECO_V2_TIPOS) {
      const porJanela = valsV2[`${b}\u0001${tipo}`];
      const [w, poucas] = escolherJanela(Object.fromEntries(JANELAS.map((w2) => [w2, porJanela[w2].length])));
      const valores = porJanela[w];
      faixaMeta[tipo] = metaJanela(w, valores.length, poucas);
      confiavel[tipo] = valores.length > 0 && !poucas;
      bandas[tipo] = valores.length ? [round(percentile(25, valores), 2), round(percentile(75, valores), 2)] : null;
    }
    const ownStock = usnByBairro[b];
    const inBandV2 = [], inBandNota = [];
    for (const r of ownStock) {
      const banda = bandas[r.tipoImovel];
      if (banda && r.valor != null && r.valor >= banda[0] && r.valor <= banda[1]) {
        inBandV2.push(r);
        if (confiavel[r.tipoImovel]) inBandNota.push(r);
      }
    }
    const temConfiavel = PERFIL_PRECO_V2_TIPOS.some((t) => confiavel[t]);
    perfilPrecoV2[b] = {
      bandas,
      faixa_meta: faixaMeta,
      faixa_confiavel: temConfiavel,
      profile_sample_size_faixa_preco_v2: inBandV2.length,
      estoque_perfil_faixa_preco_nota: temConfiavel ? inBandNota.length : null,
      // Passo 2 (2026-10-01): lista real dos anúncios dentro da faixa —
      // alimenta o drill-down "Ver lista completa" do Estoque×Demanda
      // (ver _matchingListingsByBairro), que antes usava a lista v1
      // (_matching_listings, por metragem).
      _matching_listings_v2: inBandV2,
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
    return [ativos.length > 0, ativos.map((r) => ({
      codigo: r.codigo, valor: r.valor, link: r.link,
      idade_dias: r.idadeDias ?? null,
      anuncio_antigo: r.idadeDias != null && r.idadeDias > C.anuncio_antigo_dias,
    }))];
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
    for (const r of allRecs) {
      if (liquidez[r.bairro][r.sheetYear]) {
        liquidez[r.bairro][r.sheetYear].total++;
        if (r.isRevenda) liquidez[r.bairro][r.sheetYear].revenda++;
      }
    }

    // Só venda válida conta como venda de mercado pro histórico de PREÇO
    // de um endereço — revenda limpa, ver isRevendaLimpa.
    const recs = allRecs.filter(isRevendaLimpa);
    if (!recs.length) { nAddrSemVendaReal++; continue; }
    const nPlanta = allRecs.filter((r) => r.isPlanta).length;
    const nValorForaPadrao = allRecs.filter((r) => r.isRevenda && !r.isCleanSale).length;

    const bairro = majorityBairro(recs);
    const endereco = recs.find((r) => r.addrDisplay)?.addrDisplay || String(addrKey);
    const [temHoje, unidadesHoje] = temUnidadeHoje(usnByAddrKey[addrKey]);

    if (recs.length === 1) {
      const r = recs[0];
      captacaoUnico.push({
        bairro, addr_key: addrKey, endereco, n_vendas: 1, preco_mediana: r.valor, preco_p25: null, preco_p75: null,
        poucas_vendas: true, n_planta: nPlanta, n_valor_fora_padrao: nValorForaPadrao,
        area_min: r.area, area_max: r.area, tem_unidade_a_venda_hoje: temHoje, unidades_a_venda_hoje: unidadesHoje,
      });
      continue;
    }

    nAddrTotalMulti++;
    const valores = recs.map((r) => r.valor);
    if (priceIncoherent(valores)) { nAddrDiscarded++; continue; }
    if (isLaunch(recs.map((r) => r.day))) { nAddrLaunch++; continue; }

    const areas = recs.map((r) => r.area).filter((a) => a != null);
    const [areaMin, areaMax] = coherentAreaRange(areas);
    captacaoAtiva.push({
      bairro, addr_key: addrKey, endereco, n_vendas: recs.length,
      preco_mediana: round(median(valores), 2),
      // Faixa P25-P75 só com 4+ revendas limpas; com menos, só a mediana.
      preco_p25: valores.length >= CAPTACAO_MIN_VENDAS_FAIXA ? round(percentile(25, valores), 2) : null,
      preco_p75: valores.length >= CAPTACAO_MIN_VENDAS_FAIXA ? round(percentile(75, valores), 2) : null,
      poucas_vendas: valores.length < CAPTACAO_MIN_VENDAS_FAIXA,
      n_planta: nPlanta, n_valor_fora_padrao: nValorForaPadrao,
      area_min: areaMin, area_max: areaMax,
      tem_unidade_a_venda_hoje: temHoje, unidades_a_venda_hoje: unidadesHoje,
    });
  }
  captacaoAtiva.sort((a, b) => cmpLower(a.bairro, b.bairro) || b.n_vendas - a.n_vendas || String(a.addr_key).localeCompare(String(b.addr_key)));
  // addr_key vira string ao passar por Object.keys(byAddr) — normaliza pra
  // String() dos dois lados na hora de comparar, senão Set.has(numero) falha
  // silenciosamente contra chaves guardadas como string.
  const captacaoNVendas = new Map(captacaoAtiva.map((c) => [String(c.addr_key), c.n_vendas]));

  // Passo 3c: % do estoque do bairro com mais de 365 dias de cadastro —
  // ver nota equivalente em scripts/engine.py.compute.
  const estoqueAntigoN = {}, estoqueAntigoPct = {};
  TARGETS.forEach((b) => {
    const comData = usnByBairro[b].filter((r) => r.idadeDias != null);
    const antigos = comData.filter((r) => r.idadeDias > C.anuncio_antigo_dias).length;
    estoqueAntigoN[b] = antigos;
    estoqueAntigoPct[b] = comData.length ? round((100 * antigos) / comData.length, 1) : null;
  });

  // --- montagem preliminar por bairro (todos os 47 — o filtro de bairro só entra na normalização/ranking) ---
  const bairrosOut = {};
  TARGETS.forEach((b) => {
    // Volume "de referência" = média anual dos 3 anos, não só o último
    // fechado (ver scripts/engine.py.compute — decisão do usuário, 2026-09-25).
    const volumePrimary = round(mean([yearly[b][yearPrev].count, yearly[b][yearFull].count, yearly[b][yearCurr].count]), 0);
    // stockMatch (v1, metragem) MANTIDO só pro campo obsoleto stock_matching_profile.
    const stockMatch = profile[b].profile_sample_size;
    // Passo 2 (2026-10-01): numerador do Estoque×Demanda migrado pra v2
    // (faixa de preço) + corrige demand pra revenda_12m (o lado Python já
    // usava revenda_12m desde a Etapa 2, item 1 — aqui ainda estava preso
    // em volumePrimary, uma divergência Python x JS que só não aparecia
    // porque nada comparava os dois lados nesse campo específico até agora).
    const stockMatchV2 = perfilPrecoV2[b].profile_sample_size_faixa_preco_v2;
    const demand = countRevendaAtual[b];
    const ratio = demand > 0 ? stockMatchV2 / demand : (stockMatchV2 > 0 ? 999 : 0);
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
      perfil_vencedor_faixa_preco_v2_meta: perfilPrecoV2[b].faixa_meta,
      perfil_faixa_confiavel: perfilPrecoV2[b].faixa_confiavel,
      estoque_perfil_faixa_preco_nota: perfilPrecoV2[b].estoque_perfil_faixa_preco_nota,
      // Passo 3c: selos preenchidos no loop de flags (precisam do estoque
      // total/demanda de todos os bairros) — ver engine.py.compute.
      estoque_fora_do_perfil: false, selo_escassez_real: false,
      estoque_antigo_365d: estoqueAntigoN[b], estoque_antigo_365d_pct: estoqueAntigoPct[b],
      asking_median_valor: asking, paid_median_valor_primary_year: paidMedian,
      centroid: centroids[b],
      stock_demand_ratio: Math.round(ratio * 1000) / 1000, price_gap_pct: priceGapPct,
      flag_alerta: priceGapPct != null && Math.abs(priceGapPct) >= 20,
      liquidez_total_primary_year: round(mean([liquidez[b][yearPrev].total, liquidez[b][yearFull].total, liquidez[b][yearCurr].total]), 0),
      liquidez_revenda_primary_year: round(mean([liquidez[b][yearPrev].revenda, liquidez[b][yearFull].revenda, liquidez[b][yearCurr].revenda]), 0),
      liquidez_por_ano: { [yearPrev]: liquidez[b][yearPrev], [yearFull]: liquidez[b][yearFull], [yearCurr]: liquidez[b][yearCurr] },
      // Passo 2 (2026-10-01): drill-down do Estoque×Demanda migrado pra
      // lista v2 (faixa de preço) — era profile[b]._matching_listings (v1, metragem).
      _matching_listings: perfilPrecoV2[b]._matching_listings_v2,
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
    // Passo 3c (2026-10-05): "Prioridade Máxima" dividida em dois selos
    // que nunca acendem juntos — ver nota equivalente em engine.py.compute.
    // limiar_escassez_real vem fixo do build (universo dos 77), nunca
    // recalculado pelo escopo do filtro.
    const elegivelSelo = !bo.amostra_pequena_ranking && bo.perfil_faixa_confiavel && bo.estoque_perfil_faixa_preco <= C.captacao_estrategica_max_stock_match;
    const escassez = elegivelSelo && totalRatioMapScope[b] <= C.limiar_escassez_real;
    bo.selo_escassez_real = escassez;
    bo.estoque_fora_do_perfil = elegivelSelo && !escassez && bo.stock_total > 0;
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
  // Pesos do Painel 8 só dos componentes DISPONÍVEIS, redistribuídos
  // proporcionalmente — espelha scripts/engine.py.pesos_painel8: preço some
  // em apartamento (Passo 2b) e a aderência some quando a faixa de preço do
  // tipo não tem 30 vendas limpas (2026-10-06).
  const pesosPainel8 = (temPreco, temAderencia) => {
    const ativos = {};
    for (const [k, v] of Object.entries(C.pesos_painel8)) {
      if ((k !== "preco" || temPreco) && (k !== "aderencia" || temAderencia)) ativos[k] = v;
    }
    const soma = Object.values(ativos).reduce((x, y) => x + y, 0);
    return Object.fromEntries(Object.entries(ativos).map(([k, v]) => [k, v / soma]));
  };

  const bonusPorVendas = (nVendas) => {
    if (!nVendas || nVendas < 2) return 0;
    const v = C.captacao_bonus_por_vendas[String(nVendas)];
    return v != null ? v : C.captacao_bonus_max;
  };
  // Passo 4 (2026-10-05): bônus de captação HÍBRIDO — ver nota equivalente
  // em scripts/engine.py._bonus_captacao_hibrido. Retorna { bonus, regua, giro }.
  const bonusCaptacaoHibrido = (nVendas, unidades, tipoImovel) => {
    if (!nVendas || nVendas < 2) return { bonus: 0, regua: null, giro: null };
    let bonus, regua, giro = null;
    if (unidades && unidades >= C.captacao_min_unidades_giro && tipoImovel !== "casa") {
      giro = nVendas / unidades;
      bonus = C.captacao_bonus_max;
      for (const [limite, valor] of C.captacao_giro_faixas) {
        if (giro < limite) { bonus = valor; break; }
      }
      regua = "giro do prédio";
    } else {
      bonus = bonusPorVendas(nVendas);
      regua = "nº de vendas";
    }
    if (nVendas < C.captacao_min_vendas_bonus_alto) bonus = Math.min(bonus, C.captacao_bonus_sem_minimo_max);
    return { bonus, regua, giro };
  };

  const resumoImovel = (price, aderenciaFinal, tipoImovel, scoreRevendaBairro, nVendasEndereco) => {
    const frases = [];
    // Passo 2b: componente de preço suspenso pra apartamento — mensagem
    // fixa em vez do zone/ratio de R$/m², que não existe mais pra esse tipo.
    if (tipoImovel === "apartamento") {
      frases.push("Comparação indisponível para apartamentos: aguardando calibração de área");
    } else {
      const ratio = price.ratio;
      if (price.zone === "cautela" && ratio != null) frases.push(`R$/m² ${Math.round((1 - ratio) * 100)}% abaixo do histórico de imóveis do mesmo tipo/tamanho — vale checar antes de anunciar`);
      else if (price.zone === "acima" && price.score < 60 && ratio != null) frases.push(`R$/m² ${Math.round((ratio - 1) * 100)}% acima do que se pagou em imóveis do mesmo tipo/tamanho`);
      else if (price.zone === "normal" && ratio != null && ratio < 0.97) frases.push(`R$/m² ${Math.round((1 - ratio) * 100)}% abaixo da mediana paga em imóveis do mesmo tipo/tamanho`);
    }
    // Passo 2b: aderência agora é faixa de preço v2 — sem conceito de
    // "estimativa regional" (era reliability de área, v1).
    if (aderenciaFinal != null && aderenciaFinal >= 80) frases.push("Bate com a faixa de preço vencedora do bairro (revenda, 12m)");
    if (scoreRevendaBairro >= 70) frases.push("Bairro com liquidez de revenda alta");
    if (nVendasEndereco) frases.push(`Prédio com histórico de giro comprovado (${nVendasEndereco} vendas em 3 anos)`);
    return frases.slice(0, 2).join(" · ");
  };

  const imoveisPrioritarios = [];
  for (const u of usnRecords) {
    if (u.valor == null || u.valor <= 0) continue;
    if (!scopeSet.has(u.bairro)) continue;
    const b = bairrosOut[u.bairro];
    if (!b) continue;

    const isApto = u.tipoImovel === "apartamento";
    // Passo 2b (2026-10-01): componente de preço SUSPENSO pra apartamento
    // — ver nota equivalente em scripts/engine.py._compute_imoveis_prioritarios.
    let price;
    if (isApto) {
      price = { score: null, zone: "indisponivel_apartamento", ratio: null };
    } else {
      const valorComparacao = u.area ? u.valor / u.area : null;
      const medianaComparacao = lookupMedianaPagoM2(b.preco_m2_segmentos, u.tipoImovel, u.area);
      price = priceAlignmentScore(valorComparacao, medianaComparacao);
    }

    // Passo 2b: aderência migrada de area_band (v1) pra faixa de preço v2.
    const faixaV2 = (b.perfil_vencedor_faixa_preco_v2 || {})[u.tipoImovel];
    const metaFaixa = (b.perfil_vencedor_faixa_preco_v2_meta || {})[u.tipoImovel] || {};
    // Proteção de amostra (2026-10-06): faixa sem 30 vendas limpas = aderência AUSENTE.
    const faixaConfiavel = !!faixaV2 && !(metaFaixa.poucas_vendas ?? true);
    let aderencia = null;
    if (faixaConfiavel && u.valor != null) {
      aderencia = 50;
      const [lo, hi] = faixaV2;
      if (u.valor >= lo && u.valor <= hi) aderencia = 100;
      else {
        const bandWidth = hi - lo;
        const dist = u.valor < lo ? lo - u.valor : u.valor - hi;
        aderencia = bandWidth > 0 ? Math.max(0, 100 - (dist / bandWidth) * 100) : 50;
      }
    }

    // Passo 3c (2026-10-05): bônus gradual pelo nº de vendas do endereço
    // — ver engine.py._bonus_captacao.
    const nVendasEndereco = u.addrKey != null ? (captacaoNVendas.get(String(u.addrKey)) || 0) : 0;
    const temCaptacao = nVendasEndereco > 0;
    const unidadesEndereco = u.addrKey != null && raw.unidades_endereco ? (raw.unidades_endereco[String(u.addrKey)] ?? null) : null;
    const { bonus, regua, giro } = bonusCaptacaoHibrido(nVendasEndereco, unidadesEndereco, u.tipoImovel);
    const pesos = pesosPainel8(!isApto, aderencia != null);
    const componentes = { revenda: b.score_revenda, preco: price.score, aderencia, captacao: bonus };
    const finalScore = Object.keys(pesos).reduce((acc, k) => acc + pesos[k] * componentes[k], 0);

    imoveisPrioritarios.push({
      bairro: u.bairro, endereco: u.addrDisplay, codigo: u.codigo, link: u.link,
      valor: u.valor, area: u.area, quartos: u.quartos, vagas: u.vagas, tipo_imovel: u.tipoImovel, addr_key: u.addrKey,
      score_bairro_revenda: round(b.score_revenda), price_alignment: round(price.score),
      profile_adherence: round(aderencia), tem_captacao_ativa: temCaptacao,
      captacao_n_vendas: nVendasEndereco, captacao_bonus: bonus,
      captacao_regua: regua, captacao_unidades: temCaptacao ? unidadesEndereco : null,
      captacao_giro_pct: giro != null ? round(giro * 100, 2) : null,
      idade_dias: u.idadeDias ?? null,
      anuncio_antigo: u.idadeDias != null && u.idadeDias > C.anuncio_antigo_dias,
      final_score: round(finalScore, 2), resumo: resumoImovel(price, aderencia, u.tipoImovel, b.score_revenda, nVendasEndereco),
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
  // Proteção de amostra (2026-10-06): f2 só usa faixas confiáveis; bairro sem
  // nenhuma = dado ausente (f2 undefined) e o peso é redistribuído (ver engine.py).
  const stockMatchScope = {};
  scope.forEach((b) => { if (bairrosOut[b].estoque_perfil_faixa_preco_nota != null) stockMatchScope[b] = bairrosOut[b].estoque_perfil_faixa_preco_nota; });
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
    // Passo 2b (2026-10-01): comparação suspensa pra apartamento — ver
    // nota equivalente em scripts/engine.py._compute_valor_oportunidade.
    let medianaRef, valorRef;
    if (isApto) {
      medianaRef = null;
      valorRef = null;
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
      idade_dias: im.idade_dias, anuncio_antigo: im.anuncio_antigo,
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

    const fatores = { f1, f2, f3, f4, f5, f6 };
    const disponiveis = Object.entries(fatores).filter(([, v]) => v != null);
    const somaPesos = disponiveis.reduce((acc, [k]) => acc + C.pesos_prontidao[k], 0);
    const prontidao = disponiveis.reduce((acc, [k, v]) => acc + C.pesos_prontidao[k] * v, 0) / somaPesos;
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
      bairro: b, selo_escassez_real: bo.selo_escassez_real,
      // Passo 2 (2026-10-01): perfil migrado pra faixa de preço v2 — ver
      // nota equivalente em scripts/engine.py._compute_captacao_estrategica.
      perfil: {
        faixa_preco: bo.perfil_vencedor_faixa_preco_v2,
        faixa_meta: bo.perfil_vencedor_faixa_preco_v2_meta,
        estoque_perfil_faixa_preco: bo.estoque_perfil_faixa_preco,
        estoque_fora_do_perfil: bo.estoque_fora_do_perfil,
      },
      enderecos: enderecos.map((e) => ({
        endereco: e.endereco, n_vendas: e.n_vendas, preco_mediana: e.preco_mediana,
        preco_p25: e.preco_p25, preco_p75: e.preco_p75, poucas_vendas: e.poucas_vendas,
        n_planta: e.n_planta, n_valor_fora_padrao: e.n_valor_fora_padrao,
        area_min: e.area_min, area_max: e.area_max, unico: e.unico,
        tem_unidade_a_venda_hoje: e.tem_unidade_a_venda_hoje, unidades_a_venda_hoje: e.unidades_a_venda_hoje,
      })),
    });
  });
  const ordemSelo = (g) => (g.selo_escassez_real ? 0 : (g.perfil.estoque_fora_do_perfil ? 1 : 2));
  captacaoEstrategica.sort((a, b) => ordemSelo(a) - ordemSelo(b)
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
    meta: { years: raw.years, primary_year: yearFull, inprogress_year: yearCurr, enderecos_captacao_ativa: captacaoAtivaFinal.length, limiar_escassez_real: C.limiar_escassez_real },
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
