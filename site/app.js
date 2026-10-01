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
// Vendas/mediana "de referência" usam pool/média dos 3 anos, não só o
// último fechado (decisão do usuário, 2026-09-25) — ver engine.js/engine.py.
function anosRefLabel() {
  const ys = DATA.meta.years;
  return `${ys[0]}–${ys[ys.length - 1]}`;
}
// Item 4 da auditoria de 2026-09-30: volume_12m/trend_pct_12m usam uma
// janela rolante de 12 meses completos pela data real da transação — o
// período exato muda a cada atualização (ver engine.py._compute_volume_12m),
// por isso sempre mostrado na tela junto com o número, nunca hardcoded.
const MES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
function fmtMesAno(ym) {
  const [y, m] = ym.split("-").map(Number);
  return `${MES_ABREV[m - 1]}/${String(y).slice(2)}`;
}
function periodo12mLabel() {
  const p = DATA.periodo_12m;
  return `${fmtMesAno(p.inicio)}–${fmtMesAno(p.fim)}`;
}

function badge(text, kind) {
  return el("span", { class: `badge ${kind}` }, text);
}

function reliabilityTag(rel) {
  const label = { individual: "próprio bairro", regional: "estimativa regional", insufficient: "dado insuficiente" }[rel] || rel;
  return el("span", { class: `reliability-tag ${rel}` }, label);
}

// Interesse de busca no Google (Keyword Planner) — sinal PROSPECTIVO de
// demanda (gente pesquisando agora), complementar à liquidez do ITBI
// (retrospectiva, só vendas já fechadas). Classificação Alto/Médio/Baixo é
// por tercil contra os 49 bairros inteiros — só informativo, não entra em
// nenhum score ainda (ver scripts/build_data.py e README).
function searchInterestBadge(b) {
  const si = b.search_interest;
  if (!si) return null;
  const cfg = { alto: ["Busca: Alto", "gold"], medio: ["Busca: Médio", "neutral"], baixo: ["Busca: Baixo", "neutral"] }[si.nivel];
  if (!cfg) return null;
  const el_ = badge(cfg[0], cfg[1]);
  el_.title = `~${fmtInt(si.avg_monthly_searches)} buscas/mês (média de ${si.meses_com_dado} meses)`;
  return el_;
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
let DATA = null; // "view" atualmente exibida (dado do servidor, ou recomputado pelo engine.js com filtro)
let SERVER_DATA = null; // snapshot original de data.json, pra restaurar instantaneamente ao limpar filtros
let RAW = null; // conteúdo de raw.json, carregado sob demanda (lazy)
let RAW_PROMISE = null;
const FILTERS = { bairros: new Set(), priceMin: null, priceMax: null };

function filtersActive() {
  return FILTERS.bairros.size > 0 || FILTERS.priceMin != null || FILTERS.priceMax != null;
}

function ensureEngineLoaded() {
  if (RAW_PROMISE) return RAW_PROMISE;
  RAW_PROMISE = (async () => {
    if (!window.computeEngine) {
      await new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "engine.js";
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    const res = await fetch("raw.json");
    RAW = await res.json();
  })();
  return RAW_PROMISE;
}

function mergeStaticMeta(computed) {
  // O engine.js recalcula só o que muda com o filtro. Estatísticas de
  // ingestão (total de linhas lidas/batidas na fonte) são globais e não
  // mudam com o filtro — herda do data.json original pros painéis que as
  // exibem (ex: resumo da Visão Geral) não quebrarem.
  computed.generated_at = SERVER_DATA.generated_at;
  computed.meta.total_itbi_rows_seen = SERVER_DATA.meta.total_itbi_rows_seen;
  computed.meta.total_itbi_rows_matched = SERVER_DATA.meta.total_itbi_rows_matched;
  computed.meta.usn = SERVER_DATA.meta.usn;
  return computed;
}

function recomputeAndRenderAll() {
  if (!filtersActive()) {
    // Sem filtro: se já carregamos o engine (por causa do painel Estoque x
    // Demanda), recomputa mesmo assim pra manter a lista de imóveis por
    // faixa disponível — resultado é idêntico ao data.json original.
    if (RAW) {
      DATA = mergeStaticMeta(computeEngine(RAW, {}));
    } else {
      DATA = SERVER_DATA;
    }
  } else {
    DATA = mergeStaticMeta(computeEngine(RAW, {
      bairroScope: [...FILTERS.bairros],
      priceMin: FILTERS.priceMin,
      priceMax: FILTERS.priceMax,
    }));
  }
  window.__data = DATA;
  renderAll();
}

function renderAll() {
  renderVisaoGeral();
  renderRanking();
  renderProntidao();
  renderPerfil();
  renderMapa();
  renderCaptacao();
  renderPrioritarios();
  renderPorBairro();
  renderValorOportunidade();
  renderEstoqueDemanda();
  renderPrecoM2();
  renderCarteira77();
}

async function main() {
  const res = await fetch("data.json");
  if (!res.ok) {
    document.querySelector(".app").prepend(el("div", { class: "note" }, "Não consegui carregar data.json. Rode `python3 scripts/build_data.py` e sirva a pasta site/ com um servidor local."));
    return;
  }
  SERVER_DATA = await res.json();
  DATA = SERVER_DATA;
  window.__data = DATA;

  const m = DATA.meta;
  document.getElementById("updated-at").textContent = `Dados de ${m.years.join("/")} · gerado em ${DATA.generated_at}`;
  const fonte = m.usn && m.usn.fonte === "nonstop_api" ? "API nonStop" : "export nonStop";
  document.getElementById("fontes-foot").textContent = `ITBI (Prefeitura) · ${fonte}`;

  setupTabs();
  setupFiltros();
  renderAll(); // já dispara o carregamento em segundo plano do engine.js/raw.json (ver renderEstoqueDemanda)
}

const PANELS = [
  { id: "visao-geral", label: "Visão Geral" },
  { id: "ranking", label: "Ranking de Oportunidade" },
  { id: "prontidao", label: "Prontidão para Campanha" },
  { id: "estoque-demanda", label: "Estoque × Demanda" },
  { id: "perfil", label: "Perfil por Bairro" },
  { id: "mapa", label: "Mapa" },
  { id: "captacao", label: "Captação Ativa" },
  { id: "prioritarios", label: "Imóveis Prioritários" },
  { id: "por-bairro", label: "Por Bairro/Região" },
  { id: "valor-oportunidade", label: "Valor de Oportunidade" },
  { id: "preco-m2", label: "Preço por m²" },
  { id: "carteira-77", label: "Carteira 77 (beta)" },
];

function setupTabs() {
  const nav = document.getElementById("tabs");
  PANELS.forEach((p, i) => {
    const btn = el("button", { "data-panel": p.id, class: i === 0 ? "active" : "" }, p.label);
    btn.addEventListener("click", () => showPanel(p.id));
    nav.appendChild(btn);

    // Título só visível na impressão (ver @media print / .panel-print-title
    // em styles.css) — na tela o nome já está na aba lateral; no PDF
    // completo os painéis viram páginas sequenciais e precisam de um
    // cabeçalho próprio pra identificar qual análise é qual.
    const panelEl = document.querySelector(`.panel[data-panel="${p.id}"]`);
    if (panelEl) panelEl.prepend(el("h1", { class: "panel-print-title" }, p.label));
  });
}

function showPanel(id) {
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === id));
  document.querySelectorAll("nav.tabs button").forEach((b) => b.classList.toggle("active", b.dataset.panel === id));
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
}
document.addEventListener("DOMContentLoaded", () => showPanel("visao-geral"));

// ---------------------------------------------------------------------------
// "Baixar PDF" — impressão nativa do navegador (sem lib de PDF em JS: ver
// @media print em styles.css). O botão global do cabeçalho baixa a
// dashboard INTEIRA (todos os painéis, um por página — todos já estão
// renderizados no DOM o tempo todo por renderAll(), só escondidos); a
// Captação Ativa também tem um link por bairro (ver renderCaptacao) que
// isola só aquele grupo antes de imprimir.
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("pdf-btn");
  if (btn) btn.addEventListener("click", () => printFullDashboard());
});

function expandAllCaptacao(root = document) {
  root.querySelectorAll(".captacao-group").forEach((d) => {
    d.dataset.wasOpen = d.open ? "1" : "0";
    d.open = true;
  });
  root.querySelectorAll(".captacao-rest").forEach((r) => {
    r.dataset.prevDisplay = r.style.display;
    r.style.display = "";
  });
}
function restoreAllCaptacao() {
  document.querySelectorAll(".captacao-group[data-was-open]").forEach((d) => {
    d.open = d.dataset.wasOpen === "1";
    delete d.dataset.wasOpen;
  });
  document.querySelectorAll(".captacao-rest[data-prev-display]").forEach((r) => {
    r.style.display = r.dataset.prevDisplay;
    delete r.dataset.prevDisplay;
  });
}

// Impressão direta (Cmd/Ctrl+P) fora dos botões da dashboard: se a Captação
// Ativa for o painel visível, expande do mesmo jeito (senão um <details>
// fechado não aparece no PDF).
window.addEventListener("beforeprint", () => {
  if (document.body.classList.contains("printing-captacao-group") || document.body.classList.contains("printing-all")) return;
  const activePanel = document.querySelector(".panel.active");
  if (!activePanel || activePanel.dataset.panel !== "captacao") return;
  expandAllCaptacao(activePanel);
});
window.addEventListener("afterprint", () => {
  if (document.body.classList.contains("printing-captacao-group") || document.body.classList.contains("printing-all")) return;
  restoreAllCaptacao();
});

async function printFullDashboard() {
  // Estoque × Demanda só busca engine.js/raw.json (e enche
  // DATA._matchingListingsByBairro) na primeira vez que alguém entra nessa
  // aba ou mexe num filtro — sem isso, o PDF completo podia sair com
  // "Carregando lista detalhada de estoque…" se baixado logo após abrir a
  // página. Garante que já carregou antes de imprimir.
  await ensureEngineLoaded();
  recomputeAndRenderAll();

  document.body.classList.add("printing-all");
  expandAllCaptacao();
  const cleanup = () => {
    document.body.classList.remove("printing-all");
    restoreAllCaptacao();
    window.removeEventListener("afterprint", cleanup);
  };
  window.addEventListener("afterprint", cleanup);
  window.print();
}

function printCaptacaoGroup(detailsEl) {
  const wasOpen = detailsEl.open;
  detailsEl.open = true;
  const rest = detailsEl.querySelector(".captacao-rest");
  const prevRestDisplay = rest ? rest.style.display : null;
  if (rest) rest.style.display = "";
  detailsEl.classList.add("print-only-this");
  document.body.classList.add("printing-captacao-group");
  const cleanup = () => {
    detailsEl.classList.remove("print-only-this");
    document.body.classList.remove("printing-captacao-group");
    detailsEl.open = wasOpen;
    if (rest) rest.style.display = prevRestDisplay;
    window.removeEventListener("afterprint", cleanup);
  };
  window.addEventListener("afterprint", cleanup);
  window.print();
}

// ---------------------------------------------------------------------------
// Filtros (bairro multi-seleção + faixa de preço) — recalcula tudo via
// engine.js quando ativos.
// ---------------------------------------------------------------------------
function setupFiltros() {
  const listBox = document.getElementById("filtro-bairro-list");
  const countLabel = document.getElementById("filtro-bairro-count");
  const statusLabel = document.getElementById("filtro-status");
  const searchInput = document.getElementById("filtro-busca-bairro");
  const minInput = document.getElementById("filtro-preco-min");
  const maxInput = document.getElementById("filtro-preco-max");

  SERVER_DATA.ranking.slice().sort((a, b) => a.localeCompare(b, "pt-BR")).forEach((name) => {
    const item = el("label", { class: "filtro-bairro-item" });
    const checkbox = el("input", { type: "checkbox", value: name });
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) FILTERS.bairros.add(name);
      else FILTERS.bairros.delete(name);
      onFilterChange();
    });
    item.appendChild(checkbox);
    item.appendChild(el("span", {}, name));
    item.dataset.name = name.toLowerCase();
    listBox.appendChild(item);
  });

  function updateStatus() {
    countLabel.textContent = FILTERS.bairros.size ? `${FILTERS.bairros.size} selecionado${FILTERS.bairros.size === 1 ? "" : "s"}` : "todos";
    const parts = [];
    if (FILTERS.bairros.size) parts.push(`${FILTERS.bairros.size} bairro(s)`);
    if (FILTERS.priceMin != null || FILTERS.priceMax != null) parts.push("faixa de preço");
    statusLabel.textContent = parts.length ? `Filtro ativo: ${parts.join(" + ")} — recalculando ao vivo.` : "";
    statusLabel.classList.toggle("active", parts.length > 0);
  }

  let debounceTimer = null;
  function onFilterChange() {
    updateStatus();
    if (!RAW) {
      statusLabel.textContent = "Carregando motor de recálculo…";
      statusLabel.classList.add("active");
    }
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      ensureEngineLoaded().then(() => { recomputeAndRenderAll(); updateStatus(); });
    }, 250);
  }

  searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    listBox.querySelectorAll(".filtro-bairro-item").forEach((item) => {
      item.classList.toggle("hidden", q.length > 0 && !item.dataset.name.includes(q));
    });
  });

  document.getElementById("filtro-selecionar-todos").addEventListener("click", (e) => {
    e.preventDefault();
    listBox.querySelectorAll(".filtro-bairro-item:not(.hidden) input").forEach((cb) => {
      cb.checked = true;
      FILTERS.bairros.add(cb.value);
    });
    onFilterChange();
  });

  document.getElementById("filtro-limpar-bairros").addEventListener("click", (e) => {
    e.preventDefault();
    FILTERS.bairros.clear();
    listBox.querySelectorAll("input").forEach((cb) => (cb.checked = false));
    onFilterChange();
  });

  [minInput, maxInput].forEach((input, idx) => {
    input.addEventListener("input", () => {
      const v = input.value.trim() === "" ? null : Number(input.value);
      if (idx === 0) FILTERS.priceMin = v;
      else FILTERS.priceMax = v;
      onFilterChange();
    });
  });

  document.getElementById("filtro-limpar-tudo").addEventListener("click", (e) => {
    e.preventDefault();
    FILTERS.bairros.clear();
    FILTERS.priceMin = null;
    FILTERS.priceMax = null;
    listBox.querySelectorAll("input").forEach((cb) => (cb.checked = false));
    minInput.value = "";
    maxInput.value = "";
    searchInput.value = "";
    listBox.querySelectorAll(".filtro-bairro-item").forEach((item) => item.classList.remove("hidden"));
    updateStatus();
    DATA = RAW ? mergeStaticMeta(computeEngine(RAW, {})) : SERVER_DATA;
    window.__data = DATA;
    renderAll();
  });
}

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
    metaFmt: (b) => `${fmtInt(b.volume_mercado_12m)} vendas de mercado (12m, ${periodo12mLabel()}) · tendência ${b.trend_pct_mercado_12m != null ? fmtPct(b.trend_pct_mercado_12m) : "—"} · ${fmtInt(b.volume_12m)} no giro total (todas as transferências)`,
    badges: (b) => {
      const out = [];
      if (b.flag_oportunidade) out.push(badge("Oportunidade", "gold"));
      if (b.flag_saturacao_alta) out.push(badge("Saturação Alta", "warning"));
      return out;
    },
  });

  const mesesIncompletosLabel = DATA.periodo_12m.meses_incompletos.map(fmtMesAno).join(" e ");
  document.getElementById("visao-sub").textContent =
    `${DATA.meta.total_itbi_rows_matched.toLocaleString("pt-BR")} transações de ITBI residenciais válidas (${DATA.meta.years.join("–")}) · ${DATA.meta.usn.rows_matched.toLocaleString("pt-BR")} anúncios de venda no estoque atual. ` +
    `Vendas dos últimos 12 meses: janela ${periodo12mLabel()} — ${mesesIncompletosLabel} ainda têm dado incompleto (guia paga com atraso chega depois), número tende a subir um pouco em execuções futuras.`;

  const tiles = document.getElementById("visao-tiles");
  tiles.appendChild(statTile("Imóveis pontuados", fmtInt(DATA.imoveis_prioritarios.length)));
  tiles.appendChild(statTile("Endereços em Captação Ativa", fmtInt(DATA.meta.enderecos_captacao_ativa)));
  tiles.appendChild(statTile("Achados de Valor de Oportunidade", fmtInt(DATA.valor_oportunidade.imoveis.length)));
  const prioritariosBairros = new Set(DATA.captacao_estrategica.filter((g) => g.flag_prioridade_maxima).map((g) => g.bairro));
  tiles.appendChild(statTile("Bairros Prioridade Máxima", fmtInt(prioritariosBairros.size)));

  const alertBox = document.getElementById("visao-alertas");
  // Etapa 3 (2026-09-29): alerta é por SEGMENTO (bairro + tipo de imóvel +
  // faixa de metragem), não por bairro inteiro — comparar "tudo que se
  // pede" contra "tudo que se pagou" misturava apartamento pequeno com
  // casa grande. amostra_pequena (menos de 10 transações pagas nos
  // últimos 12 meses nesse segmento) nunca vira alerta.
  // Etapa 5 (validação, 2026-09-29): também exige 3+ anúncios ativos no
  // segmento — sem isso, um único anúncio do lado pedido podia sustentar
  // um alerta sozinho.
  const segmentosAlerta = [];
  DATA.ranking.forEach((name) => {
    (DATA.bairros[name].preco_m2_segmentos || []).forEach((s) => {
      if (s.gap_pct == null || s.amostra_pequena || Math.abs(s.gap_pct) < 20 || s.n_anuncios < 3) return;
      segmentosAlerta.push({ bairro: name, ...s });
    });
  });
  segmentosAlerta.sort((a, b) => Math.abs(b.gap_pct) - Math.abs(a.gap_pct));
  const alertas = segmentosAlerta.slice(0, 12);
  if (!alertas.length) {
    alertBox.appendChild(el("div", { class: "placeholder-block" }, "Nenhum segmento (bairro + tipo + faixa) com gap de R$/m² acima do limiar e amostra suficiente no momento."));
  } else {
    barRows(
      alertBox,
      alertas.map((a) => ({
        label: `${a.bairro} · ${a.tipo_imovel === "casa" ? "Casa" : "Apartamento"} · ${a.faixa}`,
        value: Math.abs(a.gap_pct),
        colorVar: a.gap_pct > 0 ? "--status-warning" : "--series-blue",
      })),
      { valueFmt: (v) => fmtPct(v), colorVar: "--status-warning" }
    );
    alertBox.appendChild(el("div", { class: "note" }, "Gap de R$/m², dentro do mesmo tipo de imóvel e faixa de metragem (nunca valor total nem tamanhos diferentes). Pedido acima do pago (laranja) = estoque anunciado caro demais pro histórico desse segmento; pedido abaixo do pago (azul) = estoque anunciado barato demais (pode ser subprecificação real, pode ser amostra de anúncios pequena)."));
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
      { key: "volume_mercado_12m", label: `Vendas de mercado (12m, ${periodo12mLabel()})` },
      { key: "trend_pct_mercado_12m", label: "Tendência (12m vs ano anterior)", fmt: (v) => (v == null ? "—" : fmtPct(v)) },
      { key: "volume_12m", label: "Todas as transferências (12m)" },
      { key: "stock_demand_ratio", label: "Estoque/Demanda", fmt: (v) => (v >= 999 ? "∞" : v.toFixed(2)) },
      { key: "price_gap_pct", label: "Gap Preço", fmt: (v) => (v == null ? "—" : fmtPct(v)) },
      {
        key: "flags", label: "Sinais", sortable: false, render: (r) => {
          const wrap = el("div", {});
          if (r.flag_oportunidade) wrap.appendChild(badge("Oportunidade", "gold"));
          if (r.flag_saturacao_alta) wrap.appendChild(badge("Saturação", "warning"));
          if (r.flag_alerta) wrap.appendChild(badge("Alerta preço", "critical"));
          const si = searchInterestBadge(r);
          if (si) wrap.appendChild(si);
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
  const container = document.getElementById("prontidao-table");
  container.innerHTML = "";
  const imoveisByBairro = {};
  DATA.imoveis_prioritarios.forEach((im) => (imoveisByBairro[im.bairro] ||= []).push(im));

  DATA.prontidao_ranking.forEach((name, i) => {
    const b = DATA.bairros[name];
    const wrap = el("div", {});
    const row = el("div", { class: "rank-row" + (i < 3 ? " top3" : ""), style: "cursor:pointer" });
    row.appendChild(el("div", { class: "rank-num" }, String(i + 1)));
    const body = el("div", { class: "rank-body" });
    const nameLine = el("div", { class: "rank-name" }, [name, b.flag_prioridade_maxima ? badge("Prioridade Máxima", "gold") : null, searchInterestBadge(b)]);
    body.appendChild(nameLine);
    body.appendChild(el("div", { class: "rank-meta" }, `Ranking de Oportunidade: score ${fmtInt(b.score)} · estoque no perfil ${fmtInt(b.stock_matching_profile)} · toque para ver os 10 melhores imóveis`));
    row.appendChild(body);
    const track = el("div", { class: "rank-bar-track" });
    track.appendChild(el("div", { class: "rank-bar-fill", style: `width:${Math.min(100, b.prontidao_campanha)}%` }));
    row.appendChild(track);
    row.appendChild(el("div", { class: "rank-score" }, fmtInt(b.prontidao_campanha)));
    wrap.appendChild(row);

    const expandBox = el("div", { class: "prontidao-expand", style: "display:none" });
    let loaded = false;
    row.addEventListener("click", () => {
      const showing = expandBox.style.display !== "none";
      expandBox.style.display = showing ? "none" : "block";
      if (!showing && !loaded) {
        loaded = true;
        const top10 = (imoveisByBairro[name] || []).slice(0, 10);
        if (!top10.length) {
          expandBox.appendChild(el("div", { class: "placeholder-block" }, "Nenhum imóvel pontuado neste bairro com os filtros atuais."));
        } else {
          top10.forEach((im, idx) => expandBox.appendChild(imovelRow(im, idx)));
        }
      }
    });
    wrap.appendChild(expandBox);
    container.appendChild(wrap);
  });
}

// ---------------------------------------------------------------------------
// Perfil por Bairro (Painéis 3, 4, 5)
// ---------------------------------------------------------------------------
function renderPerfil() {
  const select = document.getElementById("perfil-select");
  const prev = select.value;
  select.innerHTML = "";
  DATA.ranking.forEach((name) => select.appendChild(el("option", { value: name }, name)));
  select.value = DATA.ranking.includes(prev) ? prev : DATA.ranking[0];
  select.onchange = () => renderPerfilContent(select.value);
  if (select.value) renderPerfilContent(select.value);
  else document.getElementById("perfil-content").innerHTML = "";
}

function renderPerfilContent(name) {
  const b = DATA.bairros[name];
  const box = document.getElementById("perfil-content");
  box.innerHTML = "";

  const tiles = el("div", { class: "perfil-tiles" });
  tiles.appendChild(statTile("Score de Oportunidade", fmtInt(b.score)));
  tiles.appendChild(statTile("Score de Revenda", fmtInt(b.score_revenda)));
  tiles.appendChild(statTile("Prontidão para Campanha", fmtInt(b.prontidao_campanha)));
  tiles.appendChild(statTile(`Vendas de mercado (12m, ${periodo12mLabel()})`, fmtInt(b.volume_mercado_12m)));
  tiles.appendChild(statTile("Todas as transferências (12m)", fmtInt(b.volume_12m)));
  box.appendChild(tiles);

  const perfilBox = el("section", { class: "card", style: "margin:0 0 14px; padding:16px 18px;" });
  perfilBox.appendChild(el("h2", { style: "font-size:14.5px" }, "Perfil vencedor (o que mais vendeu)"));
  if (b.area_band) {
    const line = el("div", { class: "small" }, [
      `Metragem: ${fmtM2(b.area_band[0])}–${fmtM2(b.area_band[1])} `,
      reliabilityTag(b.area_band_reliability),
    ]);
    perfilBox.appendChild(line);
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
    `Razão estoque no perfil / vendas por ano (méd. ${anosRefLabel()}): ${b.stock_demand_ratio >= 999 ? "∞ (sem demanda registrada)" : b.stock_demand_ratio.toFixed(2)}`));
  box.appendChild(stockBox);

  const priceBox = el("section", { class: "card", style: "margin:0; padding:16px 18px;" });
  priceBox.appendChild(el("h2", { style: "font-size:14.5px" }, "Preço por m² — Pago × Pedido"));
  priceBox.appendChild(el("div", { class: "card-sub", style: "margin-bottom:10px" },
    `Mediana de R$/m² pago (${anosRefLabel()}) × pedido (hoje), dentro do mesmo tipo de imóvel e faixa de metragem — nunca valor total, nunca tamanhos diferentes.`));
  const segmentos = (b.preco_m2_segmentos || [])
    .filter((s) => s.mediana_pago_m2 != null || s.mediana_pedido_m2 != null)
    .sort((s1, s2) => (s2.n_transacoes_12m - s1.n_transacoes_12m) || cmpLower(s1.tipo_imovel, s2.tipo_imovel) || cmpLower(s1.faixa, s2.faixa));
  if (!segmentos.length) {
    priceBox.appendChild(el("div", { class: "placeholder-block" }, "Sem transações pagas nem anúncios suficientes pra segmentar preço por tipo/tamanho nesse bairro."));
  } else {
    segmentos.forEach((s) => {
      const nomeLine = [`${s.tipo_imovel === "casa" ? "Casa" : "Apartamento"} · ${s.faixa}`];
      if (s.amostra_pequena) nomeLine.push(badge("Amostra pequena", "neutral"));
      const faixaPago = s.p25_pago_m2 != null
        ? `${fmtMoneyCompact(s.p25_pago_m2)} – ${fmtMoneyCompact(s.p75_pago_m2)}/m² (P25–P75) · mediana ${fmtMoneyCompact(s.mediana_pago_m2)}/m²`
        : "sem venda paga na amostra";
      const metaLine = [
        `Pago: ${faixaPago}`,
        `Pedido: ${s.mediana_pedido_m2 != null ? fmtMoneyCompact(s.mediana_pedido_m2) + "/m² (mediana)" : "sem anúncio na amostra"}`,
        `${fmtInt(s.n_transacoes)} venda(s) (${fmtInt(s.n_transacoes_12m)} nos últimos 12 meses) · ${fmtInt(s.n_anuncios)} anúncio(s)`,
      ];
      const row = el("div", { class: "addr-row", style: "align-items:flex-start" }, [
        el("div", {}, [
          el("div", { class: "addr-name" }, nomeLine),
          ...metaLine.map((t) => el("div", { class: "addr-meta" }, t)),
        ]),
        el("div", { class: "addr-price" }, s.gap_pct != null ? `${s.gap_pct >= 0 ? "+" : ""}${fmtPct(s.gap_pct)}` : "—"),
      ]);
      priceBox.appendChild(row);
    });
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

  const maxVolume = Math.max(1, ...withCentroid.map((x) => x.b.volume_mercado_12m));
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
    const r = 5 + Math.sqrt(b.volume_mercado_12m / maxVolume) * 18;
    const circle = svg("circle", { cx, cy, r, class: "map-bubble", fill: colorFor(b.score) });
    circle.addEventListener("pointermove", (e) => {
      const rect = s.getBoundingClientRect();
      tooltip.innerHTML = "";
      tooltip.appendChild(el("div", { style: "font-weight:650; margin-bottom:3px" }, name));
      tooltip.appendChild(el("div", {}, `Score ${fmtInt(b.score)} · ${fmtInt(b.volume_mercado_12m)} vendas de mercado (12m, ${periodo12mLabel()}) · ${fmtInt(b.volume_12m)} no giro total`));
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
    const pdfLink = el("a", { href: "#", class: "captacao-pdf-link" }, "Baixar PDF ↓");
    pdfLink.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      printCaptacaoGroup(details);
    });
    const summary = el("summary", {}, [
      el("span", {}, [g.bairro, g.flag_prioridade_maxima ? badge("Prioridade Máxima", "gold") : null, searchInterestBadge(DATA.bairros[g.bairro]), pdfLink]),
      el("span", { class: "n" }, `${g.enderecos.length} endereço${g.enderecos.length === 1 ? "" : "s"}`),
    ]);
    details.appendChild(summary);

    if (g.perfil.area_band) {
      details.appendChild(el("div", { class: "profile-line" },
        `Perfil vencedor: ${fmtM2(g.perfil.area_band[0])}–${fmtM2(g.perfil.area_band[1])} · ${g.perfil.profile_quartos ?? "—"} dorm · ${g.perfil.profile_vagas ?? "—"} vaga(s)`));
    }

    const appendAddrRow = (container, e) => {
      const nameLine = [e.endereco, e.unico ? badge("Endereço único", "neutral") : null];
      if (e.tem_unidade_a_venda_hoje) nameLine.push(badge("Já anunciado hoje", "warning"));
      let metaLine = `${e.n_vendas} venda${e.n_vendas === 1 ? "" : "s"}${e.area_min != null ? ` · ${fmtM2(e.area_min)}${e.area_max !== e.area_min ? "–" + fmtM2(e.area_max) : ""}` : ""}`;
      const row = el("div", { class: "addr-row" }, [
        el("div", {}, [
          el("div", { class: "addr-name" }, nameLine),
          el("div", { class: "addr-meta" }, metaLine),
        ]),
        el("div", { class: "addr-price" }, e.preco_min === e.preco_max ? fmtMoneyCompact(e.preco_min) : `${fmtMoneyCompact(e.preco_min)} – ${fmtMoneyCompact(e.preco_max)}`),
      ]);
      container.appendChild(row);
      if (e.tem_unidade_a_venda_hoje && e.unidades_a_venda_hoje && e.unidades_a_venda_hoje.length) {
        const links = el("div", { class: "addr-row", style: "padding-top:0; padding-bottom:10px" }, [
          el("div", { class: "small muted" }, [
            "Unidade(s) já anunciada(s) nesse endereço: ",
            ...e.unidades_a_venda_hoje.flatMap((u, i) => [
              i > 0 ? ", " : null,
              u.link ? el("a", { href: u.link, target: "_blank", rel: "noopener" }, u.codigo || "ver") : (u.codigo || "—"),
            ]),
          ]),
        ]);
        container.appendChild(links);
      }
    };

    // Bairros com muitos endereços elegíveis (ex: Jardim Paulista, Vila
    // Mariana) deixavam o grupo expandido gigante. Mostra só os 15 mais
    // líquidos (topo da ordenação já existente — sem anúncio ativo hoje
    // primeiro, mais vendas primeiro) e esconde o resto atrás de "ver
    // todos", do mais quente pro mais frio.
    const TOP_N = 15;
    const top = g.enderecos.slice(0, TOP_N);
    const rest = g.enderecos.slice(TOP_N);
    top.forEach((e) => appendAddrRow(details, e));

    if (rest.length) {
      const restBox = el("div", { class: "captacao-rest", style: "display:none" });
      rest.forEach((e) => appendAddrRow(restBox, e));
      const toggle = el("a", { href: "#", class: "captacao-toggle" }, `Ver todos os ${g.enderecos.length} endereços (do mais quente ao mais frio) ↓`);
      toggle.addEventListener("click", (ev) => {
        ev.preventDefault();
        const showing = restBox.style.display !== "none";
        restBox.style.display = showing ? "none" : "";
        toggle.textContent = showing
          ? `Ver todos os ${g.enderecos.length} endereços (do mais quente ao mais frio) ↓`
          : `Mostrar só os ${TOP_N} mais líquidos ↑`;
      });
      details.appendChild(toggle);
      details.appendChild(restBox);
    }
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
    `Mostrando os 50 melhores de ${DATA.imoveis_prioritarios.length} imóveis pontuados. Fórmula: 35% liquidez de revenda do bairro + 30% alinhamento de preço (R$/m² do anúncio × mediana paga do mesmo tipo de imóvel e faixa de metragem) + 25% aderência ao perfil vencedor (metragem/dormitórios/vagas) + 10% bônus de captação ativa.`));
}

// ---------------------------------------------------------------------------
// Por Bairro/Região (Painel 9)
// ---------------------------------------------------------------------------
function renderPorBairro() {
  const select = document.getElementById("porbairro-select");
  const prev = select.value;
  select.innerHTML = "";
  DATA.ranking.forEach((name) => {
    const n = DATA.imoveis_prioritarios.filter((im) => im.bairro === name).length;
    if (n > 0) select.appendChild(el("option", { value: name }, `${name} (${n})`));
  });
  const values = [...select.options].map((o) => o.value);
  select.value = values.includes(prev) ? prev : values[0] || "";
  select.onchange = () => renderPorBairroContent(select.value);
  if (select.options.length) renderPorBairroContent(select.value);
  else document.getElementById("porbairro-content").innerHTML = "";
}

function renderPorBairroContent(name) {
  const box = document.getElementById("porbairro-content");
  box.innerHTML = "";
  const items = DATA.imoveis_prioritarios.filter((im) => im.bairro === name);
  items.forEach((im, i) => box.appendChild(imovelRow(im, i)));
}

// ---------------------------------------------------------------------------
// Estoque × Demanda (tabela completa, todos os bairros do escopo)
// ---------------------------------------------------------------------------
function renderEstoqueDemanda() {
  const container = document.getElementById("estoque-demanda-table");
  container.innerHTML = "";

  if (!DATA._matchingListingsByBairro) {
    container.appendChild(el("div", { class: "note" }, "Carregando lista detalhada de estoque…"));
    ensureEngineLoaded().then(() => recomputeAndRenderAll());
    return;
  }

  const rows = DATA.ranking.map((name) => ({ bairro: name, ...DATA.bairros[name] }));
  sortableTable(container, {
    initialSortKey: "stock_demand_ratio",
    initialSortDir: 1,
    columns: [
      { key: "bairro", label: "Bairro" },
      { key: "volume_primary_year", label: `Demanda (méd./ano ${anosRefLabel()})` },
      { key: "stock_total", label: "Estoque total" },
      { key: "stock_matching_profile", label: "Estoque no perfil" },
      { key: "stock_demand_ratio", label: "Cobertura", fmt: (v) => (v >= 999 ? "∞" : v.toFixed(3)) },
      {
        key: "sinal", label: "Sinal", sortable: false, render: (r) => {
          if (r.flag_oportunidade) return badge("Oportunidade", "gold");
          if (r.flag_alerta) return badge("Alerta preço", "critical");
          return badge("Neutro", "neutral");
        },
      },
      {
        key: "detalhes", label: "Detalhes", sortable: false, render: (r) => {
          const link = el("a", { href: "#" }, "Ver lista completa");
          link.addEventListener("click", (e) => { e.preventDefault(); toggleEstoqueDetalhe(r.bairro, e.currentTarget); });
          return link;
        },
      },
    ],
    rows,
  });
}

// Acordeão: a linha de detalhe é inserida logo abaixo da linha clicada (não
// no fim da tabela inteira) — com 49 bairros na lista, um clique numa linha
// do topo abria a resposta lá embaixo, fora da tela, parecendo que o link
// não fazia nada.
function toggleEstoqueDetalhe(bairro, linkEl) {
  const table = linkEl.closest("table");
  const clickedRow = linkEl.closest("tr");
  const existing = table.querySelector(".estoque-detalhe-row");
  const wasOpenForSameRow = existing && existing.dataset.bairro === bairro;
  if (existing) existing.remove();
  if (wasOpenForSameRow) return;

  const listings = (DATA._matchingListingsByBairro && DATA._matchingListingsByBairro[bairro]) || [];
  const nCols = clickedRow.children.length;
  const box = el("div", { class: "card", style: "margin:0" }, [
    el("h2", { style: "font-size:14.5px" }, `Estoque no perfil vencedor — ${bairro}`),
    el("div", { class: "card-sub" }, `${listings.length} anúncio${listings.length === 1 ? "" : "s"} dentro da faixa de metragem vencedora do bairro.`),
  ]);
  if (!listings.length) {
    box.appendChild(el("div", { class: "placeholder-block" }, "Nenhum anúncio ativo dentro dessa faixa no momento."));
  } else {
    listings.forEach((r) => {
      const row = el("div", { class: "mini-listing-row" }, [
        el("div", {}, `${r.addrDisplay || "(endereço não informado)"} · ${fmtM2(r.area)} · ${r.quartos ?? "—"} dorm`),
        el("div", {}, [fmtMoneyCompact(r.valor), " ", r.link ? el("a", { href: r.link, target: "_blank", rel: "noopener" }, "Ver ↗") : null]),
      ]);
      box.appendChild(row);
    });
  }
  const detalheRow = el("tr", { class: "estoque-detalhe-row", "data-bairro": bairro }, [
    el("td", { colspan: String(nCols) }, [box]),
  ]);
  clickedRow.after(detalheRow);
  detalheRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
      {
        key: "tipo_imovel", label: "Tipo · Faixa", sortable: false,
        render: (r) => el("div", {}, `${r.tipo_imovel === "casa" ? "Casa" : "Apartamento"} · ${r.faixa}`),
      },
      { key: "valor_m2", label: "R$/m² anúncio", fmt: (v) => fmtMoneyCompact(v) },
      { key: "mediana_pago_m2", label: "R$/m² mediana (mesmo tipo/faixa)", fmt: (v) => fmtMoneyCompact(v) },
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

// ---------------------------------------------------------------------------
// Preço por m² — Pago × Pedido (Painel 11, Etapa 4 da auditoria de 2026-09-29)
// ---------------------------------------------------------------------------
function renderPrecoM2() {
  const container = document.getElementById("preco-m2-table");
  container.innerHTML = "";
  const rows = DATA.preco_m2_painel || [];
  if (!rows.length) {
    container.appendChild(el("div", { class: "placeholder-block" }, "Sem apartamentos suficientes nos últimos 12 meses pra calcular esse painel."));
    return;
  }
  sortableTable(container, {
    initialSortKey: "gap_pct",
    columns: [
      { key: "bairro", label: "Bairro" },
      { key: "faixa", label: "Faixa de metragem" },
      { key: "mediana_pago_m2", label: "R$/m² pago (mediana, 12m)", fmt: (v) => (v == null ? "—" : fmtMoneyCompact(v)) },
      { key: "mediana_pedido_m2", label: "R$/m² pedido (mediana, hoje)", fmt: (v) => (v == null ? "—" : fmtMoneyCompact(v)) },
      { key: "gap_pct", label: "Gap", fmt: (v) => (v == null ? "—" : (v >= 0 ? "+" : "") + fmtPct(v)) },
      { key: "n_transacoes_12m", label: "Vendas (12m)", fmt: (v) => fmtInt(v) },
      { key: "n_anuncios", label: "Anúncios" },
      {
        key: "amostra_pequena", label: "Amostra", sortable: false,
        render: (r) => (r.amostra_pequena ? badge("Amostra pequena", "neutral") : badge("Confiável", "gold")),
      },
    ],
    rows,
  });
}

function renderCarteira77() {
  const fechContainer = document.getElementById("carteira-77-fechamento");
  const tableContainer = document.getElementById("carteira-77-table");
  if (!fechContainer || !tableContainer) return; // painel pode não existir em builds antigos de data.json
  fechContainer.innerHTML = "";
  tableContainer.innerHTML = "";

  const c77 = DATA.carteira_77;
  if (!c77) {
    tableContainer.appendChild(el("div", { class: "placeholder-block" }, "data.json ainda não tem o campo carteira_77 — rode scripts/build_data.py de novo."));
    return;
  }

  const f = c77.fechamento;
  const linha = (nome, stats) =>
    el("div", { class: "fechamento-linha" }, [
      el("strong", {}, nome + ": "),
      `total ${fmtInt(stats.total)} · carteira ${fmtPct(stats.carteira_pct)} · fora ${fmtPct(stats.fora_pct)} · incerto ${fmtPct(stats.incerto_pct)}`,
    ]);
  fechContainer.appendChild(
    el("div", { class: "card-sub" }, [
      el("div", {}, `Período (12 meses): ${c77.periodo_12m.inicio} a ${c77.periodo_12m.fim}`),
      linha("Revenda", f.revenda),
      linha("Planta", f.planta),
      linha("Unidades IPTU", f.unidades),
    ])
  );

  const rows = Object.entries(c77.bairros).map(([bairro, v]) => ({ bairro, ...v }));
  sortableTable(tableContainer, {
    initialSortKey: "revenda_12m",
    columns: [
      { key: "bairro", label: "Bairro" },
      { key: "revenda_12m", label: "Revenda (12m)", fmt: (v) => fmtInt(v) },
      { key: "planta_12m", label: "Planta (12m)", fmt: (v) => fmtInt(v) },
      { key: "unidades_iptu", label: "Unidades IPTU", fmt: (v) => fmtInt(v) },
      { key: "giro_12m_pct", label: "Giro", fmt: (v) => (v == null ? "—" : fmtPct(v)) },
    ],
    rows,
  });
}

main().catch((e) => console.error("MAIN FAILED", e.stack || e));
