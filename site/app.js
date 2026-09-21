// Torre de Controle — Investimento Imobiliário SP
// Consome site/data.json (gerado por scripts/build_data.py). Sem build step,
// sem dependências externas — abrir via um servidor estático local
// (ex: `python3 -m http.server` dentro de site/) por causa de fetch() + file://.

const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v; // só com strings estáticas confiáveis
    else e.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

function svg(tag, attrs = {}) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

function fmtInt(n) {
  if (n == null) return "—";
  return Math.round(n).toLocaleString("pt-BR");
}
function fmtMoney(n) {
  if (n == null) return "—";
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
}
function fmtMoneyCompact(n) {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return "R$ " + (n / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + "M";
  if (Math.abs(n) >= 1_000) return "R$ " + (n / 1_000).toLocaleString("pt-BR", { maximumFractionDigits: 0 }) + "mil";
  return fmtMoney(n);
}
function fmtPct(n, digits = 1) {
  if (n == null) return "—";
  return n.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + "%";
}
function fmtM2(n) {
  if (n == null) return "—";
  return fmtInt(n) + "m²";
}
function sum(arr) { return arr.reduce((a, b) => a + b, 0); }

function badge(text, kind) {
  return el("span", { class: `badge ${kind}` }, text);
}

function reliabilityTag(rel) {
  const label = { individual: "próprio bairro", regional: "estimativa regional", insufficient: "dado insuficiente" }[rel] || rel;
  return el("span", { class: `reliability-tag ${rel}` }, label);
}

// ---------------------------------------------------------------------------
// Tabela ordenável genérica
// ---------------------------------------------------------------------------
function sortableTable(container, { columns, rows, initialSortKey, initialSortDir = -1 }) {
  let sortCol = initialSortKey;
  let sortDir = initialSortDir;

  function render() {
    container.innerHTML = "";
    const sorted = [...rows].sort((a, b) => {
      const av = a[sortCol], bv = b[sortCol];
      if (av == null) return 1;
      if (bv == null) return -1;
      return av < bv ? -1 * sortDir : av > bv ? 1 * sortDir : 0;
    });

    const wrap = el("div", { class: "table-scroll" });
    const table = el("table", { class: "data-table" });
    const thead = el("thead");
    const trh = el("tr");
    columns.forEach((c) => {
      const th = el("th", { class: c.sortable === false ? "" : "sortable" + (sortCol === c.key ? " active" : "") }, [
        c.label,
        c.sortable === false ? "" : el("span", { class: "arrow" }, sortCol === c.key ? (sortDir === 1 ? "↑" : "↓") : "↕"),
      ]);
      if (c.sortable !== false) {
        th.addEventListener("click", () => {
          if (sortCol === c.key) sortDir *= -1;
          else { sortCol = c.key; sortDir = -1; }
          render();
        });
      }
      trh.appendChild(th);
    });
    thead.appendChild(trh);
    table.appendChild(thead);

    const tbody = el("tbody");
    sorted.forEach((r) => {
      const tr = el("tr");
      columns.forEach((c) => {
        const val = r[c.key];
        const td = el("td", { class: c.key === "desc" ? "desc" : "" });
        if (c.render) td.appendChild(c.render(r));
        else td.textContent = c.fmt ? c.fmt(val, r) : (val == null ? "—" : String(val));
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    container.appendChild(wrap);
  }
  render();
}

// ---------------------------------------------------------------------------
// Barras horizontais (ranking / comparação)
// ---------------------------------------------------------------------------
function barRows(container, rows, { valueFmt = (v) => fmtInt(v), colorVar = "--gold", maxOverride } = {}) {
  container.innerHTML = "";
  const max = maxOverride || Math.max(1, ...rows.map((r) => r.value));
  rows.forEach((r) => {
    const row = el("div", { class: "bar-row" + (r.local ? " local" : "") });
    row.appendChild(el("div", { class: "bar-label" }, r.label));
    const track = el("div", { class: "bar-track" });
    track.appendChild(el("div", { class: "bar-fill", style: `width:${Math.min(100, (r.value / max) * 100)}%; background:var(${r.colorVar || colorVar})` }));
    row.appendChild(track);
    row.appendChild(el("div", { class: "bar-val" }, valueFmt(r.value)));
    container.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// Ranking de bairros (linhas com barra + score)
// ---------------------------------------------------------------------------
function rankRows(container, names, data, { scoreKey, metaFmt, badges, maxOverride }) {
  container.innerHTML = "";
  const max = maxOverride || 100;
  names.forEach((name, i) => {
    const b = data.bairros[name];
    const row = el("div", { class: "rank-row" + (i < 3 ? " top3" : "") });
    row.appendChild(el("div", { class: "rank-num" }, String(i + 1)));
    const body = el("div", { class: "rank-body" });
    const nameLine = el("div", { class: "rank-name" }, name);
    if (badges) badges(b).forEach((bd) => nameLine.appendChild(bd));
    body.appendChild(nameLine);
    body.appendChild(el("div", { class: "rank-meta" }, metaFmt(b)));
    row.appendChild(body);
    const track = el("div", { class: "rank-bar-track" });
    track.appendChild(el("div", { class: "rank-bar-fill", style: `width:${Math.min(100, (b[scoreKey] / max) * 100)}%` }));
    row.appendChild(track);
    row.appendChild(el("div", { class: "rank-score" }, fmtInt(b[scoreKey])));
    container.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
let DATA = null;

async function main() {
  const res = await fetch("data.json");
  if (!res.ok) {
    document.querySelector(".app").prepend(el("div", { class: "note" }, "Não consegui carregar data.json. Rode `python3 scripts/build_data.py` e sirva a pasta site/ com um servidor local."));
    return;
  }
  DATA = await res.json();
  window.__data = DATA;

  const m = DATA.meta;
  document.getElementById("updated-at").textContent = `Dados de ${m.years.join("/")} · gerado em ${DATA.generated_at}`;
  const fonte = m.usn && m.usn.fonte === "nonstop_api" ? "API nonStop" : "export nonStop";
  document.getElementById("fontes-foot").textContent = `ITBI (Prefeitura) · ${fonte}`;

  setupTabs();
  renderVisaoGeral();
  renderRanking();
  renderProntidao();
  renderPerfil();
  renderMapa();
  renderCaptacao();
  renderPrioritarios();
  renderPorBairro();
  renderValorOportunidade();
}

const PANELS = [
  { id: "visao-geral", label: "Visão Geral" },
  { id: "ranking", label: "Ranking de Oportunidade" },
  { id: "prontidao", label: "Prontidão para Campanha" },
  { id: "perfil", label: "Perfil por Bairro" },
  { id: "mapa", label: "Mapa" },
  { id: "captacao", label: "Captação Ativa" },
  { id: "prioritarios", label: "Imóveis Prioritários" },
  { id: "por-bairro", label: "Por Bairro/Região" },
  { id: "valor-oportunidade", label: "Valor de Oportunidade" },
];

function setupTabs() {
  const nav = document.getElementById("tabs");
  PANELS.forEach((p, i) => {
    const btn = el("button", { "data-panel": p.id, class: i === 0 ? "active" : "" }, p.label);
    btn.addEventListener("click", () => showPanel(p.id));
    nav.appendChild(btn);
  });
}

function showPanel(id) {
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === id));
  document.querySelectorAll("nav.tabs button").forEach((b) => b.classList.toggle("active", b.dataset.panel === id));
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
}
document.addEventListener("DOMContentLoaded", () => showPanel("visao-geral"));

function statTile(label, value, sub) {
  return el("div", { class: "stat-tile" }, [
    el("div", { class: "label" }, label),
    el("div", { class: "value" }, String(value)),
    sub ? el("div", { class: "delta flat" }, sub) : null,
  ]);
}

// ---------------------------------------------------------------------------
// Visão Geral
// ---------------------------------------------------------------------------
function renderVisaoGeral() {
  const top10 = DATA.ranking.slice(0, 10);
  rankRows(document.getElementById("visao-ranking"), top10, DATA, {
    scoreKey: "score",
    metaFmt: (b) => `${fmtInt(b.volume_primary_year)} vendas em ${DATA.meta.primary_year} · tendência ${b.trend_pct != null ? fmtPct(b.trend_pct) : "—"}`,
    badges: (b) => {
      const out = [];
      if (b.flag_oportunidade) out.push(badge("Oportunidade", "gold"));
      if (b.flag_saturacao_alta) out.push(badge("Saturação Alta", "warning"));
      return out;
    },
  });

  document.getElementById("visao-sub").textContent =
    `${DATA.meta.total_itbi_rows_matched.toLocaleString("pt-BR")} transações de ITBI residenciais válidas (${DATA.meta.years.join("–")}) · ${DATA.meta.usn.rows_matched.toLocaleString("pt-BR")} anúncios de venda no estoque atual.`;

  const tiles = document.getElementById("visao-tiles");
  tiles.appendChild(statTile("Imóveis pontuados", fmtInt(DATA.imoveis_prioritarios.length)));
  tiles.appendChild(statTile("Endereços em Captação Ativa", fmtInt(DATA.meta.enderecos_captacao_ativa)));
  tiles.appendChild(statTile("Achados de Valor de Oportunidade", fmtInt(DATA.valor_oportunidade.imoveis.length)));
  const prioritariosBairros = new Set(DATA.captacao_estrategica.filter((g) => g.flag_prioridade_maxima).map((g) => g.bairro));
  tiles.appendChild(statTile("Bairros Prioridade Máxima", fmtInt(prioritariosBairros.size)));

  const alertBox = document.getElementById("visao-alertas");
  const alertas = DATA.ranking
    .map((name) => ({ name, b: DATA.bairros[name] }))
    .filter((x) => x.b.flag_alerta)
    .sort((a, b) => Math.abs(b.b.price_gap_pct) - Math.abs(a.b.price_gap_pct))
    .slice(0, 12);
  if (!alertas.length) {
    alertBox.appendChild(el("div", { class: "placeholder-block" }, "Nenhum bairro com gap de preço acima do limiar no momento."));
  } else {
    barRows(
      alertBox,
      alertas.map((a) => ({
        label: a.name,
        value: Math.abs(a.b.price_gap_pct),
        colorVar: a.b.price_gap_pct > 0 ? "--status-warning" : "--series-blue",
      })),
      { valueFmt: (v) => fmtPct(v), colorVar: "--status-warning" }
    );
    alertBox.appendChild(el("div", { class: "note" }, "Pedido acima do pago (laranja) = estoque anunciado caro demais pro histórico do bairro; pedido abaixo do pago (azul) = estoque anunciado barato demais (pode ser subprecificação real, pode ser dado de amostra pequena — confira o painel Perfil por Bairro)."));
  }
}

// ---------------------------------------------------------------------------
// Ranking de Oportunidade (Painel 1)
// ---------------------------------------------------------------------------
function renderRanking() {
  const rows = DATA.ranking.map((name, i) => {
    const b = DATA.bairros[name];
    return { pos: i + 1, bairro: name, ...b };
  });
  sortableTable(document.getElementById("ranking-table"), {
    initialSortKey: "score",
    columns: [
      { key: "pos", label: "#", sortable: false },
      { key: "bairro", label: "Bairro" },
      { key: "score", label: "Score", fmt: (v) => fmtInt(v) },
      { key: "volume_primary_year", label: `Vendas ${DATA.meta.primary_year}` },
      { key: "trend_pct", label: "Tendência", fmt: (v) => (v == null ? "—" : fmtPct(v)) },
      { key: "stock_demand_ratio", label: "Estoque/Demanda", fmt: (v) => (v >= 999 ? "∞" : v.toFixed(2)) },
      { key: "price_gap_pct", label: "Gap Preço", fmt: (v) => (v == null ? "—" : fmtPct(v)) },
      {
        key: "flags", label: "Sinais", sortable: false, render: (r) => {
          const wrap = el("div", {});
          if (r.flag_oportunidade) wrap.appendChild(badge("Oportunidade", "gold"));
          if (r.flag_saturacao_alta) wrap.appendChild(badge("Saturação", "warning"));
          if (r.flag_alerta) wrap.appendChild(badge("Alerta preço", "critical"));
          return wrap;
        },
      },
    ],
    rows,
  });
}

// ---------------------------------------------------------------------------
// Prontidão para Campanha (Painel 2)
// ---------------------------------------------------------------------------
function renderProntidao() {
  rankRows(document.getElementById("prontidao-table"), DATA.prontidao_ranking, DATA, {
    scoreKey: "prontidao_campanha",
    metaFmt: (b) => `Ranking de Oportunidade: score ${fmtInt(b.score)} · estoque no perfil ${fmtInt(b.stock_matching_profile)}`,
    badges: (b) => (b.flag_prioridade_maxima ? [badge("Prioridade Máxima", "gold")] : []),
  });
}

// ---------------------------------------------------------------------------
// Perfil por Bairro (Painéis 3, 4, 5)
// ---------------------------------------------------------------------------
function renderPerfil() {
  const select = document.getElementById("perfil-select");
  DATA.ranking.forEach((name) => select.appendChild(el("option", { value: name }, name)));
  select.addEventListener("change", () => renderPerfilContent(select.value));
  renderPerfilContent(select.value);
}

function renderPerfilContent(name) {
  const b = DATA.bairros[name];
  const box = document.getElementById("perfil-content");
  box.innerHTML = "";

  const tiles = el("div", { class: "perfil-tiles" });
  tiles.appendChild(statTile("Score de Oportunidade", fmtInt(b.score)));
  tiles.appendChild(statTile("Score de Revenda", fmtInt(b.score_revenda)));
  tiles.appendChild(statTile("Prontidão para Campanha", fmtInt(b.prontidao_campanha)));
  tiles.appendChild(statTile(`Vendas ${DATA.meta.primary_year}`, fmtInt(b.volume_primary_year)));
  box.appendChild(tiles);

  const perfilBox = el("section", { class: "card", style: "margin:0 0 14px; padding:16px 18px;" });
  perfilBox.appendChild(el("h2", { style: "font-size:14.5px" }, "Perfil vencedor (o que mais vendeu)"));
  if (b.area_band) {
    const line = el("div", { class: "small" }, [
      `Metragem: ${fmtM2(b.area_band[0])}–${fmtM2(b.area_band[1])} `,
      reliabilityTag(b.area_band_reliability),
    ]);
    perfilBox.appendChild(line);
    perfilBox.appendChild(el("div", { class: "small muted", style: "margin-top:4px" },
      `Faixa de preço pago (P25–P75): ${fmtMoneyCompact(b.price_band[0])} – ${fmtMoneyCompact(b.price_band[1])} · mediana ${fmtMoneyCompact(b.price_band_median)}`));
    if (b.area_band_neighbors.length) {
      perfilBox.appendChild(el("div", { class: "small muted", style: "margin-top:4px" },
        `Estimado a partir de: ${b.area_band_neighbors.map((n) => `${n.bairro} (${n.distancia_km}km, ${n.n_pares} transações)`).join(", ")}`));
    }
    perfilBox.appendChild(el("div", { class: "small", style: "margin-top:10px" }, [
      `Dormitórios típicos: ${b.profile_quartos ?? "—"} · Vagas típicas: ${b.profile_vagas ?? "—"} `,
      reliabilityTag(b.profile_reliability),
      ` (amostra: ${fmtInt(b.profile_sample_size)})`,
    ]));
  } else {
    perfilBox.appendChild(el("div", { class: "placeholder-block" }, "Amostra insuficiente para calcular um perfil vencedor, mesmo com estimativa regional."));
  }
  box.appendChild(perfilBox);

  const stockBox = el("section", { class: "card", style: "margin:0 0 14px; padding:16px 18px;" });
  stockBox.appendChild(el("h2", { style: "font-size:14.5px" }, "Estoque × Demanda"));
  barRows(stockBox, [
    { label: "Estoque total anunciado", value: b.stock_total, colorVar: "--series-blue" },
    { label: "Estoque no perfil vencedor", value: b.stock_matching_profile, colorVar: "--gold" },
  ], { maxOverride: Math.max(b.stock_total, 1) });
  stockBox.appendChild(el("div", { class: "small muted", style: "margin-top:8px" },
    `Razão estoque no perfil / vendas ${DATA.meta.primary_year}: ${b.stock_demand_ratio >= 999 ? "∞ (sem demanda registrada)" : b.stock_demand_ratio.toFixed(2)}`));
  box.appendChild(stockBox);

  const priceBox = el("section", { class: "card", style: "margin:0; padding:16px 18px;" });
  priceBox.appendChild(el("h2", { style: "font-size:14.5px" }, "Faixa de Preço que Converte"));
  barRows(priceBox, [
    { label: `Mediana paga (${DATA.meta.primary_year})`, value: b.paid_median_valor_primary_year || 0, colorVar: "--series-aqua" },
    { label: "Mediana pedida (hoje)", value: b.asking_median_valor || 0, colorVar: "--series-orange" },
  ], { valueFmt: (v) => fmtMoneyCompact(v), maxOverride: Math.max(b.paid_median_valor_primary_year || 0, b.asking_median_valor || 0, 1) });
  if (b.price_gap_pct != null) {
    priceBox.appendChild(el("div", { class: "small muted", style: "margin-top:8px" },
      `Gap: pedido está ${fmtPct(Math.abs(b.price_gap_pct))} ${b.price_gap_pct >= 0 ? "acima" : "abaixo"} do que o bairro historicamente pagou.`));
  }
  box.appendChild(priceBox);
}

// ---------------------------------------------------------------------------
// Mapa de Oportunidade (Painel 6)
// ---------------------------------------------------------------------------
const MAP_COLOR_RAMP = ["#2a2416", "#4d3f1e", "#7a6127", "#a6852f", "#c9a84c", "#f0d078"];

function renderMapa() {
  const box = document.getElementById("mapa-content");
  box.innerHTML = "";

  const withCentroid = DATA.ranking
    .map((name) => ({ name, b: DATA.bairros[name] }))
    .filter((x) => x.b.centroid);
  if (!withCentroid.length) {
    box.appendChild(el("div", { class: "placeholder-block" }, "Sem coordenadas suficientes no estoque atual para desenhar o mapa."));
    return;
  }

  const lats = withCentroid.map((x) => x.b.centroid[0]);
  const lons = withCentroid.map((x) => x.b.centroid[1]);
  const latMin = Math.min(...lats), latMax = Math.max(...lats);
  const lonMin = Math.min(...lons), lonMax = Math.max(...lons);
  const W = 900, H = 620, pad = 40;
  const px = (lon) => pad + ((lon - lonMin) / (lonMax - lonMin || 1)) * (W - 2 * pad);
  const py = (lat) => H - pad - ((lat - latMin) / (latMax - latMin || 1)) * (H - 2 * pad); // norte pra cima

  const maxVolume = Math.max(1, ...withCentroid.map((x) => x.b.volume_primary_year));
  const scores = withCentroid.map((x) => x.b.score);
  const scoreMin = Math.min(...scores), scoreMax = Math.max(...scores);
  const colorFor = (score) => {
    const t = (score - scoreMin) / (scoreMax - scoreMin || 1);
    const idx = Math.min(5, Math.floor(t * 6));
    return MAP_COLOR_RAMP[idx];
  };

  const wrap = el("div", { class: "map-wrap" });
  const s = svg("svg", { class: "map-svg", viewBox: `0 0 ${W} ${H}` });
  const tooltip = el("div", { class: "map-tooltip" });

  const topLabelSet = new Set(DATA.ranking.slice(0, 12));

  withCentroid.forEach(({ name, b }) => {
    const cx = px(b.centroid[1]), cy = py(b.centroid[0]);
    const r = 5 + Math.sqrt(b.volume_primary_year / maxVolume) * 18;
    const circle = svg("circle", { cx, cy, r, class: "map-bubble", fill: colorFor(b.score) });
    circle.addEventListener("pointermove", (e) => {
      const rect = s.getBoundingClientRect();
      tooltip.innerHTML = "";
      tooltip.appendChild(el("div", { style: "font-weight:650; margin-bottom:3px" }, name));
      tooltip.appendChild(el("div", {}, `Score ${fmtInt(b.score)} · ${fmtInt(b.volume_primary_year)} vendas`));
      tooltip.style.left = (cx / W) * rect.width + "px";
      tooltip.style.top = (cy / H) * rect.height + "px";
      tooltip.style.opacity = 1;
    });
    circle.addEventListener("pointerleave", () => (tooltip.style.opacity = 0));
    s.appendChild(circle);
    if (topLabelSet.has(name)) {
      const t = svg("text", { x: cx, y: cy - r - 4, class: "map-label", "text-anchor": "middle" });
      t.textContent = name;
      s.appendChild(t);
    }
  });

  wrap.appendChild(s);
  wrap.appendChild(tooltip);
  box.appendChild(wrap);

  const legend = el("div", { class: "legend" });
  legend.appendChild(el("div", { class: "item" }, [el("span", { class: "key", style: `background:${MAP_COLOR_RAMP[0]}` }), "Score baixo"]));
  legend.appendChild(el("div", { class: "item" }, [el("span", { class: "key", style: `background:${MAP_COLOR_RAMP[5]}` }), "Score alto"]));
  legend.appendChild(el("div", { class: "item" }, "Raio da bolha ∝ √(vendas no ano)"));
  box.appendChild(legend);
}

// ---------------------------------------------------------------------------
// Captação Ativa Estratégica (Painel 7)
// ---------------------------------------------------------------------------
function renderCaptacao() {
  const box = document.getElementById("captacao-list");
  box.innerHTML = "";
  if (!DATA.captacao_estrategica.length) {
    box.appendChild(el("div", { class: "placeholder-block" }, "Nenhum endereço elegível para captação ativa no momento."));
    return;
  }
  DATA.captacao_estrategica.forEach((g) => {
    const details = el("details", { class: "captacao-group" });
    const summary = el("summary", {}, [
      el("span", {}, [g.bairro, g.flag_prioridade_maxima ? badge("Prioridade Máxima", "gold") : null]),
      el("span", { class: "n" }, `${g.enderecos.length} endereço${g.enderecos.length === 1 ? "" : "s"}`),
    ]);
    details.appendChild(summary);

    if (g.perfil.area_band) {
      details.appendChild(el("div", { class: "profile-line" },
        `Perfil vencedor: ${fmtM2(g.perfil.area_band[0])}–${fmtM2(g.perfil.area_band[1])} · ${g.perfil.profile_quartos ?? "—"} dorm · ${g.perfil.profile_vagas ?? "—"} vaga(s)`));
    }

    g.enderecos.forEach((e) => {
      const row = el("div", { class: "addr-row" }, [
        el("div", {}, [
          el("div", { class: "addr-name" }, [e.endereco, e.unico ? badge("Endereço único", "neutral") : null]),
          el("div", { class: "addr-meta" }, `${e.n_vendas} venda${e.n_vendas === 1 ? "" : "s"}${e.area_min != null ? ` · ${fmtM2(e.area_min)}${e.area_max !== e.area_min ? "–" + fmtM2(e.area_max) : ""}` : ""}`),
        ]),
        el("div", { class: "addr-price" }, e.preco_min === e.preco_max ? fmtMoneyCompact(e.preco_min) : `${fmtMoneyCompact(e.preco_min)} – ${fmtMoneyCompact(e.preco_max)}`),
      ]);
      details.appendChild(row);
    });
    box.appendChild(details);
  });
}

// ---------------------------------------------------------------------------
// Imóveis Prioritários (Painel 8)
// ---------------------------------------------------------------------------
function imovelRow(im, i) {
  const item = el("div", { class: `imovel-row${i < 3 ? " r" + (i + 1) : ""}` }, [
    el("div", { class: "medal" }, String(i + 1)),
    el("div", { class: "body" }, [
      el("div", { class: "head-row" }, [
        el("div", { class: "meta-line" }, im.bairro),
        el("span", { class: "score-tag" }, `Score ${fmtInt(im.final_score)}`),
      ]),
      el("div", { style: "font-weight:600; margin:4px 0" }, im.endereco || "(endereço não informado)"),
      el("div", { class: "metrics" }, [
        el("span", {}, ["Valor ", el("b", {}, fmtMoneyCompact(im.valor))]),
        el("span", {}, ["Área ", el("b", {}, fmtM2(im.area))]),
        el("span", {}, ["Dorm. ", el("b", {}, im.quartos ?? "—")]),
        el("span", {}, ["Vagas ", el("b", {}, im.vagas ?? "—")]),
      ]),
      el("div", { class: "resumo" }, im.resumo || "—"),
    ]),
  ]);
  if (im.link) {
    const headRow = item.querySelector(".head-row");
    headRow.appendChild(el("a", { class: "imovel-link", href: im.link, target: "_blank", rel: "noopener" }, "Ver anúncio ↗"));
  }
  return item;
}

function renderPrioritarios() {
  const box = document.getElementById("prioritarios-table");
  box.innerHTML = "";
  const top = DATA.imoveis_prioritarios.slice(0, 50);
  top.forEach((im, i) => box.appendChild(imovelRow(im, i)));
  box.appendChild(el("div", { class: "note methodology" },
    `Mostrando os 50 melhores de ${DATA.imoveis_prioritarios.length} imóveis pontuados. Fórmula: 35% liquidez de revenda do bairro + 30% alinhamento de preço + 25% aderência ao perfil vencedor (metragem/dormitórios/vagas) + 10% bônus de captação ativa.`));
}

// ---------------------------------------------------------------------------
// Por Bairro/Região (Painel 9)
// ---------------------------------------------------------------------------
function renderPorBairro() {
  const select = document.getElementById("porbairro-select");
  DATA.ranking.forEach((name) => {
    const n = DATA.imoveis_prioritarios.filter((im) => im.bairro === name).length;
    if (n > 0) select.appendChild(el("option", { value: name }, `${name} (${n})`));
  });
  select.addEventListener("change", () => renderPorBairroContent(select.value));
  if (select.options.length) renderPorBairroContent(select.value);
}

function renderPorBairroContent(name) {
  const box = document.getElementById("porbairro-content");
  box.innerHTML = "";
  const items = DATA.imoveis_prioritarios.filter((im) => im.bairro === name);
  items.forEach((im, i) => box.appendChild(imovelRow(im, i)));
}

// ---------------------------------------------------------------------------
// Valor de Oportunidade (Painel 10)
// ---------------------------------------------------------------------------
function renderValorOportunidade() {
  const rows = DATA.valor_oportunidade.imoveis;
  sortableTable(document.getElementById("valor-oportunidade-table"), {
    initialSortKey: "desconto_pct",
    columns: [
      { key: "bairro", label: "Bairro" },
      { key: "endereco", label: "Endereço", key2: "desc" },
      { key: "valor", label: "Valor pedido", fmt: (v) => fmtMoneyCompact(v) },
      { key: "mediana_paga_bairro", label: "Mediana paga", fmt: (v) => fmtMoneyCompact(v) },
      {
        key: "desconto_pct", label: "Desconto", render: (r) => el("div", {}, [
          fmtPct(r.desconto_pct) + " ",
          r.atencao ? badge("Atenção", "critical") : null,
        ]),
      },
      {
        key: "link", label: "", sortable: false, render: (r) =>
          r.link ? el("a", { href: r.link, target: "_blank", rel: "noopener" }, "Ver ↗") : el("span", { class: "muted" }, "—"),
      },
    ],
    rows,
  });

  const bairrosBox = document.getElementById("valor-oportunidade-bairros");
  const porBairro = DATA.valor_oportunidade.por_bairro.slice(0, 15);
  if (!porBairro.length) {
    bairrosBox.appendChild(el("div", { class: "placeholder-block" }, "Nenhum achado no momento."));
  } else {
    barRows(bairrosBox, porBairro.map((p) => ({ label: p.bairro, value: p.n_achados, colorVar: "--gold" })), { valueFmt: (v) => fmtInt(v) });
  }
}

main().catch((e) => console.error("MAIN FAILED", e.stack || e));
