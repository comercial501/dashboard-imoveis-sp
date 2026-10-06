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
// Mesma função de engine.js (desempate alfabético case-insensitive, sem
// localeCompare — ver comentário lá) — duplicada aqui porque app.js usa
// isso (renderPerfilContent) na primeira passada de renderAll(), antes
// de engine.js ter sido injetado (ensureEngineLoaded() só carrega
// engine.js sob demanda, de forma assíncrona — bug real encontrado em
// 2026-10-01 verificando o painel Carteira 77: sem isso, main() lançava
// "cmpLower is not defined" e TODOS os painéis depois de "Perfil por
// Bairro" ficavam vazios até o recompute de fundo rodar pela primeira
// vez).
function cmpLower(a, b) {
  const al = a.toLowerCase(), bl = b.toLowerCase();
  return al < bl ? -1 : al > bl ? 1 : 0;
}
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
// Proteção de amostra das faixas de preço (2026-10-06): cada faixa informa o
// período usado (12, 24 ou 36 meses; o histórico completo do ITBI só começa em
// jan/2024, então "36 meses" = o que existe desde lá) e, abaixo de 30 vendas
// limpas mesmo no período maior, o selo "poucas vendas".
function faixaPeriodoLabel(meta) {
  if (!meta) return "";
  const mesmoNominal = meta.meses_com_dado === meta.janela_meses;
  const meses = mesmoNominal ? `${meta.janela_meses} meses` : `${meta.meses_com_dado} meses, todo o histórico disponível`;
  return `${fmtMesAno(meta.periodo_inicio)}–${fmtMesAno(meta.periodo_fim)} · ${meses} · ${fmtInt(meta.n_vendas_limpas)} vendas limpas`;
}

function periodo12mLabel() {
  const p = DATA.periodo_12m;
  return `${fmtMesAno(p.inicio)}–${fmtMesAno(p.fim)}`;
}

function badge(text, kind) {
  return el("span", { class: `badge ${kind}` }, text);
}

// Passo 3c (2026-10-05): anúncio com mais de 365 dias de cadastro na
// nonStop continua em todas as contas — só ganha este selo (ver
// engine.py.ANUNCIO_ANTIGO_DIAS). idade_dias vem pronto do build.
function anuncioAntigoBadge(idadeDias) {
  const anos = idadeDias != null ? (idadeDias / 365).toFixed(1).replace(".", ",") : null;
  return el("span", {
    class: "badge warning",
    title: idadeDias != null ? `Primeiro cadastro na nonStop há ${fmtInt(idadeDias)} dias (${anos} anos) — vale a data mais antiga entre anúncios duplicados do mesmo imóvel` : "Anúncio com mais de 365 dias",
  }, "Anúncio antigo — validar disponibilidade");
}

// Interesse de busca no Google (Keyword Planner) — sinal PROSPECTIVO de
// demanda (gente pesquisando agora), complementar à liquidez do ITBI
// (retrospectiva, só vendas já fechadas). Classificação Alto/Médio/Baixo é
// por tercil contra os 77 bairros inteiros — só informativo, não entra em
// nenhum score ainda (ver scripts/build_data.py e README). Selo vira
// "sem dado recente" quando a fonte está desatualizada (>=30 dias) ou
// quebrada (ver meta.fresco, build_data._get_search_interest).
function searchInterestBadge(b) {
  const si = b.search_interest;
  if (!si) return null;
  const meta = DATA.search_interest_meta;
  const dataFetch = meta ? new Date(meta.fetched_at).toLocaleDateString("pt-BR") : null;
  const fonte = meta ? meta.fonte : "Google Ads Keyword Planner";
  // Revisão 2026-10-01 (migração do Prontidão): fonte desatualizada
  // (>= 30 dias, ver build_data.SEARCH_INTEREST_MAX_AGE_DIAS) OU quebrada
  // (tentativa de hoje falhou, caiu pro cache antigo) — mostra "sem dado
  // recente" em vez de um selo alto/médio/baixo que pode já não valer
  // mais, em vez de confiar num número que pode ter meses.
  if (meta && !meta.fresco) {
    const el_ = badge("Busca: sem dado recente", "neutral");
    el_.title = `Fonte: ${fonte} · último dado de ${dataFetch} (${meta.idade_dias} dias atrás)`;
    return el_;
  }
  const cfg = { alto: ["Busca: Alto", "gold"], medio: ["Busca: Médio", "neutral"], baixo: ["Busca: Baixo", "neutral"] }[si.nivel];
  if (!cfg) return null;
  const el_ = badge(cfg[0], cfg[1]);
  el_.title = `~${fmtInt(si.avg_monthly_searches)} buscas/mês (média de ${si.meses_com_dado} meses) · Fonte: ${fonte}${dataFetch ? ` · dado de ${dataFetch}` : ""}`;
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
  computed.meta.fontes = SERVER_DATA.meta.fontes;
  // Item 3 (2026-09-30): carteira_77 é estático (painel próprio, não
  // recalcula com filtro — ver README) e vem só do data.json original;
  // sem essa linha, computeEngine() (que não conhece esse campo) apagava
  // carteira_77 assim que o recompute de fundo rodava (achado: o campo
  // sumia do DATA poucos segundos depois do carregamento inicial, mesmo
  // sem nenhum filtro ativo).
  computed.carteira_77 = SERVER_DATA.carteira_77;
  // Revisão 2026-10-01 (migração do Prontidão): search_interest_meta é
  // global (um fetch só pra todos os bairros, ver build_data.py.
  // _get_search_interest) — mesmo motivo/padrão de carteira_77 acima.
  computed.search_interest_meta = SERVER_DATA.search_interest_meta;
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

// Passo 3b (2026-10-01), achado da auditoria: antes nenhuma das 3 fontes
// (ITBI/nonStop/Google) tinha data de atualização visível na tela — se
// uma delas falhasse e o build caísse pro cache/dado antigo, não tinha
// como notar isso sem abrir o console. ITBI com sync_ok=false ou Google
// com fresco=false ganham destaque em vermelho/laranja; nonStop não tem
// aviso de "velho" próprio porque uma falha de busca derruba o build
// inteiro antes de chegar a gerar um data.json novo (ver build_data.py).
function renderFontesStatus() {
  const el_ = document.getElementById("fontes-status");
  if (!el_) return;
  const f = DATA.meta.fontes;
  if (!f) { el_.textContent = ""; return; }
  el_.innerHTML = "";

  const itbiStale = f.itbi && f.itbi.sync_ok === false;
  const itbiData = f.itbi && f.itbi.arquivo_atualizado_em
    ? new Date(f.itbi.arquivo_atualizado_em).toLocaleDateString("pt-BR")
    : "—";
  // Passo 3c (2026-10-05): rótulo explica que o último mês COMPLETO é
  // "jun/2026" e que os meses seguintes ainda estão recebendo guias da
  // Prefeitura — antes mostrava "ITBI: 2026-06", que parecia dado atrasado.
  // Meses vêm de DATA.periodo_12m (fim + meses_incompletos), não de texto fixo.
  const mesLongo = (ym) => { const [y, m] = ym.split("-").map(Number); return `${MES_ABREV[m - 1]}/${y}`; };
  const p12 = DATA.periodo_12m || {};
  const ateMes = f.itbi && f.itbi.ultimo_mes_dado ? mesLongo(f.itbi.ultimo_mes_dado) : "—";
  const incompletos = (p12.meses_incompletos || []).map(mesLongo);
  const itbiTexto = `ITBI: vendas até ${ateMes}${incompletos.length ? ` (${incompletos.map((m) => m.split("/")[0]).join("–")} ainda recebendo guias)` : ""} · arquivo ${itbiData}`;
  el_.appendChild(el("span", { class: "fonte-item" + (itbiStale ? " fonte-stale" : ""), title: itbiStale ? "Falha ao sincronizar com a Prefeitura — usando o último arquivo salvo em cache." : `Último mês completo de dado do ITBI: ${ateMes}. ${incompletos.length ? "Meses incompletos (Prefeitura ainda registrando guias): " + incompletos.join(", ") + ". " : ""}Data do arquivo baixado da Prefeitura: ${itbiData}.` },
    `${itbiTexto}${itbiStale ? " ⚠ dado antigo" : ""}`));

  const nsData = f.nonstop && f.nonstop.consultado_em
    ? new Date(f.nonstop.consultado_em).toLocaleString("pt-BR")
    : "—";
  el_.appendChild(el("span", { class: "fonte-item", title: "Horário da última consulta bem-sucedida à nonStop." }, `nonStop: ${nsData}`));

  const g = f.google_busca;
  const googleStale = g && g.fresco === false;
  const gData = g && g.fetched_at ? new Date(g.fetched_at).toLocaleDateString("pt-BR") : null;
  el_.appendChild(el("span", { class: "fonte-item" + (googleStale ? " fonte-stale" : ""), title: g ? "Data da última busca de interesse no Google Ads Keyword Planner." : "Busca no Google não configurada." },
    g ? `Google: ${gData}${googleStale ? " ⚠ dado antigo" : ""}` : "Google: sem dado"));
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
  renderFontesStatus();

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
  { id: "carteira-77", label: "Carteira 77" },
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
    if (!panelEl) return;
    // Ordem final desejada (topo pro final): botão (só tela) -> título
    // (só impressão) -> meta de período/filtros (só impressão) -> resto
    // do conteúdo. prepend() empilha na ordem inversa de chamada, então
    // insere nessa ordem invertida.
    panelEl.prepend(el("div", { class: "panel-print-meta", id: `print-meta-${p.id}` }));
    panelEl.prepend(el("h1", { class: "panel-print-title" }, p.label));
    // Item 7 (2026-10-01): "Baixar esta página" — PDF só do painel atual
    // (ver printPage). Botão visível na tela (escondido na impressão via
    // .page-pdf-btn em @media print); meta-cabeçalho (período/filtros/
    // data de geração) some na tela, só aparece impresso.
    const pageBtn = el("button", { class: "page-pdf-btn", type: "button" }, "Baixar esta página ↓");
    pageBtn.addEventListener("click", () => printPage(p.id, p.label));
    panelEl.prepend(pageBtn);
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
  // "Carregando lista detalhada do estoque da rede…" se baixado logo após abrir a
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
// Item 7 (2026-10-01): "Baixar esta página" — PDF só do painel ativo no
// momento, com um cabeçalho impresso (nome da página, data/hora de
// geração, período dos dados, filtros aplicados). Reusa a mesma
// impressão nativa (window.print()) do botão "Baixar PDF" — nenhuma
// dependência nova. document.title vira o nome sugerido pro arquivo
// (é o único jeito de influenciar o nome padrão no diálogo nativo
// "Salvar como PDF" do navegador) e volta ao normal depois.
// ---------------------------------------------------------------------------
const ORIGINAL_DOCUMENT_TITLE = document.title;

function todayISODate() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function slugify(s) {
  return s
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function filtrosResumoLabel() {
  if (!filtersActive()) return "nenhum";
  const parts = [];
  if (FILTERS.bairros.size) parts.push(`bairros: ${[...FILTERS.bairros].sort().join(", ")}`);
  if (FILTERS.priceMin != null || FILTERS.priceMax != null) {
    const min = FILTERS.priceMin != null ? fmtMoney(FILTERS.priceMin) : "sem mínimo";
    const max = FILTERS.priceMax != null ? fmtMoney(FILTERS.priceMax) : "sem máximo";
    parts.push(`faixa de preço: ${min} – ${max}`);
  }
  return parts.join(" · ");
}

async function printPage(panelId, label) {
  // Mesmo motivo do printFullDashboard: garante engine.js/raw.json
  // carregados (Estoque × Demanda) antes de imprimir qualquer página.
  await ensureEngineLoaded();
  recomputeAndRenderAll();

  const metaEl = document.getElementById(`print-meta-${panelId}`);
  if (metaEl) {
    const geradoEm = new Date().toLocaleString("pt-BR");
    metaEl.textContent = `Gerado em ${geradoEm} · Período dos dados: ${periodo12mLabel()} · Filtros aplicados: ${filtrosResumoLabel()}`;
  }

  const isCaptacao = panelId === "captacao";
  if (isCaptacao) expandAllCaptacao();

  const prevTitle = document.title;
  document.title = `torre-de-controle_${slugify(label)}_${todayISODate()}`;

  const cleanup = () => {
    document.title = prevTitle || ORIGINAL_DOCUMENT_TITLE;
    if (isCaptacao) restoreAllCaptacao();
    if (metaEl) metaEl.textContent = "";
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
  // Etapa 2, item 3 (2026-10-01): bairro com < MIN_VENDAS_TOP10 (100)
  // vendas de REVENDA em 12m (amostra_pequena_ranking, calculado em
  // engine.py/engine.js) não entra no top 10 de "Onde anunciar agora" —
  // ver badge "Amostra pequena" na tabela completa do Ranking.
  const top10 = DATA.ranking.filter((name) => !DATA.bairros[name].amostra_pequena_ranking).slice(0, 10);
  rankRows(document.getElementById("visao-ranking"), top10, DATA, {
    scoreKey: "score",
    metaFmt: (b) => `${fmtInt(b.revenda_12m)} vendas de revenda (12m, ${periodo12mLabel()}) · tendência ${b.trend_pct_revenda_12m != null ? fmtPct(b.trend_pct_revenda_12m) : "—"} · ${fmtInt(b.planta_12m)} lançamentos (12m) · ${fmtInt(b.volume_12m)} no giro total (todas as transferências)`,
    badges: (b) => {
      const out = [];
      if (b.flag_oportunidade) out.push(badge("Oportunidade", "gold"));
      if (b.flag_saturacao_alta) out.push(badge("Saturação Alta", "warning"));
      return out;
    },
  });

  // Etapa 2, item 5 (2026-10-01): texto atualizado pra base nova
  // (revenda/planta separadas, carteira de 77) — antes mostrava
  // total_itbi_rows_matched (qualquer transação residencial, metodologia
  // antiga, "304.262 transações").
  const fech = DATA.carteira_77.fechamento;
  const mesesIncompletosLabel = DATA.periodo_12m.meses_incompletos.map(fmtMesAno).join(" e ");
  document.getElementById("visao-sub").textContent =
    `${fmtInt(fech.revenda.total)} vendas de revenda e ${fmtInt(fech.planta.total)} de planta na carteira de ${DATA.carteira_77.bairros ? Object.keys(DATA.carteira_77.bairros).length : 77} bairros (período ${periodo12mLabel()}) · ${DATA.meta.usn.rows_matched.toLocaleString("pt-BR")} anúncios de venda no estoque atual. ` +
    `${mesesIncompletosLabel} ainda têm dado incompleto (guia paga com atraso chega depois), número tende a subir um pouco em execuções futuras.`;

  // Item 4 (2026-10-01): limpa antes de montar — sem isso, os 4 cards e
  // o placeholder de alertas duplicavam a cada recompute de fundo
  // (background do engine.js/raw.json carregando, ou filtro aplicado
  // antes desse carregamento terminar — cada passagem por renderAll()
  // empilhava mais nós em cima dos anteriores).
  const tiles = document.getElementById("visao-tiles");
  tiles.innerHTML = "";
  tiles.appendChild(statTile("Imóveis pontuados", fmtInt(DATA.imoveis_prioritarios.length)));
  tiles.appendChild(statTile("Endereços em Captação Ativa", fmtInt(DATA.meta.enderecos_captacao_ativa)));
  tiles.appendChild(statTile("Achados de Valor de Oportunidade", fmtInt(DATA.valor_oportunidade.imoveis.length)));
  // Passo 3c (2026-10-05): "Prioridade Máxima" virou dois selos separados.
  const nEscassez = DATA.captacao_estrategica.filter((g) => g.selo_escassez_real).length;
  const nForaPerfil = DATA.captacao_estrategica.filter((g) => g.perfil.estoque_fora_do_perfil).length;
  tiles.appendChild(statTile("Bairros com pouco estoque na rede", fmtInt(nEscassez)));
  tiles.appendChild(statTile("Bairros com estoque da rede fora do perfil", fmtInt(nForaPerfil)));

  const alertBox = document.getElementById("visao-alertas");
  alertBox.innerHTML = "";
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
      { key: "revenda_12m", label: `Vendas de revenda (12m, ${periodo12mLabel()})` },
      { key: "trend_pct_revenda_12m", label: "Tendência de revenda (12m vs ano anterior)", fmt: (v) => (v == null ? "—" : fmtPct(v)) },
      { key: "planta_12m", label: "Lançamentos (12m)" },
      { key: "volume_12m", label: "Todas as transferências (12m)" },
      { key: "stock_demand_ratio", label: "Estoque da rede/Demanda", fmt: (v) => (v >= 999 ? "∞" : v.toFixed(2)) },
      { key: "price_gap_pct", label: "Gap Preço", fmt: (v) => (v == null ? "—" : fmtPct(v)) },
      {
        key: "flags", label: "Sinais", sortable: false, render: (r) => {
          const wrap = el("div", {});
          if (r.flag_oportunidade) wrap.appendChild(badge("Oportunidade", "gold"));
          if (r.flag_saturacao_alta) wrap.appendChild(badge("Saturação", "warning"));
          if (r.flag_alerta) wrap.appendChild(badge("Alerta preço", "critical"));
          // Etapa 2, item 3 (2026-10-01): bairro com < 100 vendas de
          // REVENDA em 12m não entra no top 10 de "Onde anunciar agora"
          // (ver renderVisaoGeral) — aqui, na tabela completa, mostra o
          // selo em vez de simplesmente sumir.
          if (r.amostra_pequena_ranking) wrap.appendChild(badge("Amostra pequena", "neutral"));
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
    const nameLine = el("div", { class: "rank-name" }, [
      name,
      b.selo_escassez_real ? badge("Pouco estoque na rede", "gold") : null,
      b.amostra_pequena_ranking ? badge("Amostra pequena", "neutral") : null,
      // Revisão 2026-10-01 (item 3 do ajuste da faixa de preço v2):
      // distingue "0 porque não há estoque nenhum" de "0 porque há
      // estoque ativo, mas nenhum dentro da faixa de preço vencedora" —
      // só o 2º caso mostra o selo (ver engine.py.estoque_fora_do_perfil).
      b.estoque_fora_do_perfil ? badge("Estoque da rede fora do perfil", "warning") : null,
      searchInterestBadge(b),
    ]);
    body.appendChild(nameLine);
    body.appendChild(el("div", { class: "rank-meta" }, `Ranking de Oportunidade: score ${fmtInt(b.score)} · estoque da rede no perfil vencedor (faixa de preço) ${fmtInt(b.estoque_perfil_faixa_preco)} · toque para ver os 10 melhores imóveis`));
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
  tiles.appendChild(statTile(`Vendas de revenda (12m, ${periodo12mLabel()})`, fmtInt(b.revenda_12m)));
  tiles.appendChild(statTile("Lançamentos (12m)", fmtInt(b.planta_12m)));
  tiles.appendChild(statTile("Todas as transferências (12m)", fmtInt(b.volume_12m)));
  box.appendChild(tiles);

  // Passo 3c (2026-10-05), item 4: perfil migrado pra faixa de preço v2
  // (valor total pago em revenda, 12m, por tipo de imóvel) — sai o perfil
  // por metragem/dormitórios/vagas (v1), que herdava a distorção área
  // construída do ITBI x área útil do anúncio. Nenhuma informação de
  // tamanho é mais exibida aqui.
  const perfilBox = el("section", { class: "card", style: "margin:0 0 14px; padding:16px 18px;" });
  perfilBox.appendChild(el("h2", { style: "font-size:14.5px" }, "Perfil vencedor — faixa de preço paga em revenda"));
  const faixaV2 = b.perfil_vencedor_faixa_preco_v2 || {};
  const metasV2 = b.perfil_vencedor_faixa_preco_v2_meta || {};
  [["apartamento", "Apartamento"], ["casa", "Casa"]].forEach(([tipo, rotulo]) => {
    const f = faixaV2[tipo];
    const m = metasV2[tipo];
    const linha = el("div", { class: "small", style: "margin-top:6px" }, [
      f ? `${rotulo}: ${fmtMoneyCompact(f[0])} – ${fmtMoneyCompact(f[1])} (P25–P75 do valor total pago) ` : `${rotulo}: sem vendas de revenda no período `,
      m && m.poucas_vendas ? badge("Poucas vendas — fora das notas", "neutral") : null,
    ]);
    perfilBox.appendChild(linha);
    // Período realmente usado nessa faixa (12, 24 ou 36 meses).
    if (m) perfilBox.appendChild(el("div", { class: "small muted" }, `Período usado: ${faixaPeriodoLabel(m)}`));
  });
  perfilBox.appendChild(el("div", { class: "small muted", style: "margin-top:8px" },
    `Anúncios da rede nonStop dentro da faixa: ${fmtInt(b.estoque_perfil_faixa_preco)} de ${fmtInt(b.stock_total)}.`));
  box.appendChild(perfilBox);

  const stockBox = el("section", { class: "card", style: "margin:0 0 14px; padding:16px 18px;" });
  const stockHeader = el("div", { style: "display:flex; align-items:center; gap:8px" }, [
    el("h2", { style: "font-size:14.5px; margin:0" }, "Estoque da rede × Demanda"),
  ]);
  // Passo 2 (2026-10-01): "Estoque no perfil vencedor" migrado pra faixa
  // de preço v2 (era metragem, v1 — ver scripts/engine.py.compute).
  if (b.selo_escassez_real) stockHeader.appendChild(badge("Pouco estoque na rede", "gold"));
  if (b.estoque_fora_do_perfil) stockHeader.appendChild(badge("Estoque da rede fora do perfil", "warning"));
  // barRows() limpa o container que recebe — por isso desenha numa caixa
  // própria e só depois junta com o cabeçalho (antes o título e os selos
  // deste bloco sumiam).
  const stockBars = el("div", {});
  barRows(stockBars, [
    { label: "Estoque total da rede", value: b.stock_total, colorVar: "--series-blue" },
    { label: "Estoque da rede no perfil vencedor (faixa de preço)", value: b.estoque_perfil_faixa_preco, colorVar: "--gold" },
  ], { maxOverride: Math.max(b.stock_total, 1) });
  stockBox.appendChild(stockHeader);
  stockBox.appendChild(stockBars);
  stockBox.appendChild(el("div", { class: "small muted", style: "margin-top:8px" },
    `Razão estoque da rede no perfil / vendas de revenda (12m, ${periodo12mLabel()}): ${b.stock_demand_ratio >= 999 ? "∞ (sem demanda registrada)" : b.stock_demand_ratio.toFixed(2)}`));
  // Passo 3c (2026-10-05): % do estoque com mais de 365 dias de cadastro.
  stockBox.appendChild(el("div", { class: "small muted", style: "margin-top:4px" },
    b.estoque_antigo_365d_pct == null
      ? "Idade do estoque da rede: sem data de cadastro na fonte."
      : `Estoque da rede com mais de 365 dias de cadastro: ${fmtPct(b.estoque_antigo_365d_pct)} (${fmtInt(b.estoque_antigo_365d)} de ${fmtInt(b.stock_total)} anúncios).`));
  box.appendChild(stockBox);

  const priceBox = el("section", { class: "card", style: "margin:0; padding:16px 18px;" });
  priceBox.appendChild(el("h2", { style: "font-size:14.5px" }, "Preço por m² — Pago × Pedido"));
  priceBox.appendChild(el("div", { class: "card-sub", style: "margin-bottom:10px" },
    `Mediana de R$/m² pago (${anosRefLabel()}) × pedido (hoje), dentro do mesmo tipo de imóvel e faixa de metragem — nunca valor total, nunca tamanhos diferentes. Atenção: a faixa de metragem do lado PAGO é a área do cadastro do ITBI (inclui áreas comuns e vagas), não a área útil; o lado PEDIDO usa a área útil do anúncio. Por isso, em apartamento, os dois lados não são diretamente comparáveis (o gap só é calculado para casa).`));
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
    box.appendChild(el("div", { class: "placeholder-block" }, "Sem coordenadas suficientes no estoque atual da rede para desenhar o mapa."));
    return;
  }

  const lats = withCentroid.map((x) => x.b.centroid[0]);
  const lons = withCentroid.map((x) => x.b.centroid[1]);
  const latMin = Math.min(...lats), latMax = Math.max(...lats);
  const lonMin = Math.min(...lons), lonMax = Math.max(...lons);
  const W = 900, H = 620, pad = 40;
  const px = (lon) => pad + ((lon - lonMin) / (lonMax - lonMin || 1)) * (W - 2 * pad);
  const py = (lat) => H - pad - ((lat - latMin) / (latMax - latMin || 1)) * (H - 2 * pad); // norte pra cima

  const maxVolume = Math.max(1, ...withCentroid.map((x) => x.b.revenda_12m));
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
    const r = 5 + Math.sqrt(b.revenda_12m / maxVolume) * 18;
    // Passo 3b (2026-10-01), item d pedido pelo usuário: mesmo selo de
    // amostra pequena já usado no Ranking/Prontidão/Estoque×Demanda
    // (< 100 revendas em 12m) — aqui como borda tracejada na bolha, já
    // que não há espaço pra um badge de texto dentro do mapa.
    const bubbleClass = "map-bubble" + (b.amostra_pequena_ranking ? " amostra-pequena" : "");
    const circle = svg("circle", { cx, cy, r, class: bubbleClass, fill: colorFor(b.score) });
    circle.addEventListener("pointermove", (e) => {
      const rect = s.getBoundingClientRect();
      tooltip.innerHTML = "";
      tooltip.appendChild(el("div", { style: "font-weight:650; margin-bottom:3px" }, name));
      tooltip.appendChild(el("div", {}, `Score ${fmtInt(b.score)} · ${fmtInt(b.revenda_12m)} vendas de revenda (12m, ${periodo12mLabel()}) · ${fmtInt(b.planta_12m)} lançamentos (12m) · ${fmtInt(b.volume_12m)} no giro total`));
      if (b.amostra_pequena_ranking) tooltip.appendChild(el("div", { style: "color:var(--status-warning); font-weight:600; margin-top:2px" }, "Amostra pequena (< 100 revendas em 12m)"));
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
  legend.appendChild(el("div", { class: "item" }, [el("span", { class: "key", style: "background:transparent; border:1.5px dashed var(--status-warning)" }), "Borda tracejada = amostra pequena (< 100 revendas em 12m)"]));
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
      el("span", {}, [
        g.bairro,
        g.selo_escassez_real ? badge("Pouco estoque na rede", "gold") : null,
        // Passo 2 (2026-10-01): selo "Estoque da rede fora do perfil" também aqui
        // (ver engine.py._compute_captacao_estrategica).
        g.perfil.estoque_fora_do_perfil ? badge("Estoque da rede fora do perfil", "warning") : null,
        searchInterestBadge(DATA.bairros[g.bairro]), pdfLink,
      ]),
      el("span", { class: "n" }, `${g.enderecos.length} endereço${g.enderecos.length === 1 ? "" : "s"}`),
    ]);
    details.appendChild(summary);

    // Passo 2 (2026-10-01): perfil migrado pra faixa de preço v2 (valor
    // pago em revenda, 12m, por tipo de imóvel) — era metragem/
    // dormitórios/vagas (v1). v2 não tem conceito de dormitórios/vagas
    // típicos (é só faixa de preço).
    const faixa = g.perfil.faixa_preco || {};
    const metas = g.perfil.faixa_meta || {};
    const parte = (tipo, rotulo) => {
      if (!faixa[tipo]) return null;
      const m = metas[tipo];
      const base = `${rotulo} ${fmtMoneyCompact(faixa[tipo][0])}–${fmtMoneyCompact(faixa[tipo][1])}`;
      return m ? `${base} (${faixaPeriodoLabel(m)}${m.poucas_vendas ? " — POUCAS VENDAS, fora das notas" : ""})` : base;
    };
    const partes = [parte("apartamento", "Apartamento"), parte("casa", "Casa")].filter(Boolean);
    if (partes.length) {
      details.appendChild(el("div", { class: "profile-line" },
        `Perfil vencedor (faixa de preço paga em revenda): ${partes.join(" · ")}`));
    }

    const appendAddrRow = (container, e) => {
      const nameLine = [e.endereco, e.unico ? badge("Endereço único", "neutral") : null];
      if (e.tem_unidade_a_venda_hoje) nameLine.push(badge("Já anunciado hoje", "warning"));
      // Passo 3c: algum anúncio ativo desse endereço tem mais de 365 dias.
      const unidadeAntiga = (e.unidades_a_venda_hoje || []).find((u) => u.anuncio_antigo);
      if (unidadeAntiga) nameLine.push(anuncioAntigoBadge(unidadeAntiga.idade_dias));
      // Captação limpa (2026-10-05): n_vendas = só revenda limpa (compra e
      // venda, 100%, uso residencial, valor dentro do padrão — mesma base do
      // Carteira 77). Planta e valores fora do padrão aparecem à parte e
      // nunca entram no preço. A metragem é a ÁREA DO CADASTRO do ITBI
      // (inclui áreas comuns e vagas), não a área útil.
      const partesMeta = [`${e.n_vendas} revenda${e.n_vendas === 1 ? "" : "s"} limpa${e.n_vendas === 1 ? "" : "s"}`];
      if (e.area_min != null) {
        partesMeta.push(`área do cadastro ${fmtM2(e.area_min)}${e.area_max !== e.area_min ? "–" + fmtM2(e.area_max) : ""}`);
      }
      if (e.n_planta) partesMeta.push(`+${fmtInt(e.n_planta)} na planta (fora do preço)`);
      if (e.n_valor_fora_padrao) partesMeta.push(`${fmtInt(e.n_valor_fora_padrao)} revenda${e.n_valor_fora_padrao === 1 ? "" : "s"} com valor fora do padrão ignorada${e.n_valor_fora_padrao === 1 ? "" : "s"}`);
      const metaLine = partesMeta.join(" · ");
      // Preço: mediana; faixa P25–P75 só com 4+ revendas limpas (senão "poucas vendas").
      const precoNodes = [el("div", { style: "white-space:nowrap" }, `mediana ${fmtMoneyCompact(e.preco_mediana)}`)];
      precoNodes.push(e.poucas_vendas
        ? el("div", { class: "small muted" }, "poucas vendas")
        : el("div", { class: "small muted", style: "white-space:nowrap" }, `P25–P75: ${fmtMoneyCompact(e.preco_p25)} – ${fmtMoneyCompact(e.preco_p75)}`));
      const row = el("div", { class: "addr-row" }, [
        el("div", {}, [
          el("div", { class: "addr-name" }, nameLine),
          el("div", { class: "addr-meta" }, metaLine),
        ]),
        el("div", { class: "addr-price", style: "text-align:right" }, precoNodes),
      ]);
      container.appendChild(row);
      if (e.tem_unidade_a_venda_hoje && e.unidades_a_venda_hoje && e.unidades_a_venda_hoje.length) {
        const links = el("div", { class: "addr-row", style: "padding-top:0; padding-bottom:10px" }, [
          el("div", { class: "small muted" }, [
            "Unidade(s) já anunciada(s) nesse endereço: ",
            ...e.unidades_a_venda_hoje.flatMap((u, i) => [
              i > 0 ? ", " : null,
              u.link ? el("a", { href: u.link, target: "_blank", rel: "noopener" }, u.codigo || "ver") : (u.codigo || "—"),
              u.anuncio_antigo ? ` (${fmtInt(u.idade_dias)} dias)` : null,
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
// Passo 4 (2026-10-05): mostra qual régua gerou o bônus de captação do
// imóvel — "giro do prédio" (vendas em 3 anos ÷ unidades do IPTU, prédios
// com 10+ unidades) ou "nº de vendas" (prédios pequenos, casas, ou endereço
// sem casamento com o IPTU).
function captacaoReguaTexto(im) {
  const n = im.captacao_n_vendas;
  const vendas = `${fmtInt(n)} venda${n === 1 ? "" : "s"} em 3 anos`;
  const limite = n < 3 ? " · limite de 60 pontos com menos de 3 vendas" : "";
  if (im.captacao_regua === "giro do prédio") {
    return `Bônus de captação ${fmtInt(im.captacao_bonus)} — régua: giro do prédio (${vendas} ÷ ${fmtInt(im.captacao_unidades)} unidades = ${fmtPct(im.captacao_giro_pct)})${limite}`;
  }
  let motivo;
  if (im.tipo_imovel === "casa") motivo = "casa";
  else if (im.captacao_unidades == null) motivo = "endereço sem casamento com o IPTU";
  else motivo = `prédio com ${fmtInt(im.captacao_unidades)} unidade${im.captacao_unidades === 1 ? "" : "s"}, menos de 10`;
  return `Bônus de captação ${fmtInt(im.captacao_bonus)} — régua: nº de vendas (${vendas}; ${motivo})${limite}`;
}

function imovelRow(im, i) {
  const item = el("div", { class: `imovel-row${i < 3 ? " r" + (i + 1) : ""}` }, [
    el("div", { class: "medal" }, String(i + 1)),
    el("div", { class: "body" }, [
      el("div", { class: "head-row" }, [
        el("div", { class: "meta-line" }, im.bairro),
        el("span", { class: "score-tag" }, `Score ${fmtInt(im.final_score)}`),
      ]),
      el("div", { style: "font-weight:600; margin:4px 0" }, [im.endereco || "(endereço não informado)", im.anuncio_antigo ? " " : null, im.anuncio_antigo ? anuncioAntigoBadge(im.idade_dias) : null]),
      el("div", { class: "metrics" }, [
        el("span", {}, ["Valor ", el("b", {}, fmtMoneyCompact(im.valor))]),
        el("span", {}, ["Área ", el("b", {}, fmtM2(im.area))]),
        el("span", {}, ["Dorm. ", el("b", {}, im.quartos ?? "—")]),
        el("span", {}, ["Vagas ", el("b", {}, im.vagas ?? "—")]),
      ]),
      el("div", { class: "resumo" }, im.resumo || "—"),
      im.captacao_regua ? el("div", { class: "small muted", style: "margin-top:3px" }, captacaoReguaTexto(im)) : null,
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
    `Mostrando os 50 melhores de ${DATA.imoveis_prioritarios.length} imóveis pontuados. Fórmula (casa): 35% liquidez de revenda do bairro + 30% alinhamento de preço (R$/m² do anúncio × mediana paga do mesmo tipo de imóvel e faixa de metragem) + 25% aderência à faixa de preço vencedora do bairro (valor pago em revenda, 12m, por tipo) + 10% bônus de captação ativa (híbrido: prédio com 10+ unidades no IPTU usa o giro — vendas em 3 anos ÷ unidades: menos de 7% = 40, 7–10% = 60, 10–15% = 80, 15% ou mais = 100; prédio com menos de 10 unidades, casa ou endereço sem casamento com o IPTU usa o nº de vendas: 2 = 40, 3 = 60, 4 = 80, 5 ou mais = 100; bônus acima de 60 exige pelo menos 3 vendas). Apartamento: componente de preço suspenso (aguardando calibração de área) — peso redistribuído entre liquidez (50%), aderência (~35,7%) e captação (~14,3%). Se a faixa de preço do tipo no bairro tem menos de 30 vendas limpas (mesmo em 36 meses), a aderência fica ausente e o peso dela também é redistribuído entre os componentes restantes.`));
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
    container.appendChild(el("div", { class: "note" }, "Carregando lista detalhada do estoque da rede…"));
    ensureEngineLoaded().then(() => recomputeAndRenderAll());
    return;
  }

  const rows = DATA.ranking.map((name) => ({ bairro: name, ...DATA.bairros[name] }));
  sortableTable(container, {
    initialSortKey: "stock_demand_ratio",
    initialSortDir: 1,
    columns: [
      { key: "bairro", label: "Bairro" },
      { key: "revenda_12m", label: `Demanda (revenda 12m, ${periodo12mLabel()})` },
      { key: "stock_total", label: "Estoque total da rede" },
      // Passo 2 (2026-10-01): migrado pra faixa de preço v2 (era metragem, v1).
      { key: "estoque_perfil_faixa_preco", label: "Estoque da rede no perfil (faixa de preço)" },
      { key: "stock_demand_ratio", label: "Cobertura", fmt: (v) => (v >= 999 ? "∞" : v.toFixed(3)) },
      // Passo 3c (2026-10-05): % do estoque do bairro com mais de 365 dias
      // de cadastro na nonStop.
      {
        key: "estoque_antigo_365d_pct", label: "Estoque da rede com +365 dias",
        fmt: (v, r) => (v == null ? "—" : `${fmtPct(v)} (${fmtInt(r.estoque_antigo_365d)})`),
      },
      {
        key: "sinal", label: "Sinal", sortable: false, render: (r) => {
          const wrap = el("div", {});
          if (r.flag_oportunidade) wrap.appendChild(badge("Oportunidade", "gold"));
          if (r.flag_alerta) wrap.appendChild(badge("Alerta preço", "critical"));
          if (r.selo_escassez_real) wrap.appendChild(badge("Pouco estoque na rede", "gold"));
          if (r.estoque_fora_do_perfil) wrap.appendChild(badge("Estoque da rede fora do perfil", "warning"));
          // Passo 3b (2026-10-01), item d pedido pelo usuário: mesmo selo já
          // usado no Ranking/Prontidão (< 100 revendas em 12m) — cobertura
          // calculada sobre pouca amostra não é confiável.
          if (r.amostra_pequena_ranking) wrap.appendChild(badge("Amostra pequena", "neutral"));
          if (!wrap.children.length) wrap.appendChild(badge("Neutro", "neutral"));
          return wrap;
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
    el("h2", { style: "font-size:14.5px" }, `Estoque da rede no perfil vencedor — ${bairro}`),
    el("div", { class: "card-sub" }, `${listings.length} anúncio${listings.length === 1 ? "" : "s"} dentro da faixa de preço vencedora do bairro (valor pago em revenda, 12m, por tipo de imóvel).`),
  ]);
  if (!listings.length) {
    box.appendChild(el("div", { class: "placeholder-block" }, "Nenhum anúncio ativo dentro dessa faixa no momento."));
  } else {
    listings.forEach((r) => {
      const row = el("div", { class: "mini-listing-row" }, [
        el("div", {}, [`${r.addrDisplay || "(endereço não informado)"} · ${fmtM2(r.area)} · ${r.quartos ?? "—"} dorm`, (r.idadeDias != null && r.idadeDias > RAW.constants.anuncio_antigo_dias) ? " " : null, (r.idadeDias != null && r.idadeDias > RAW.constants.anuncio_antigo_dias) ? anuncioAntigoBadge(r.idadeDias) : null]),
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
          r.anuncio_antigo ? anuncioAntigoBadge(r.idade_dias) : null,
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
  bairrosBox.innerHTML = "";
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
    initialSortKey: "valor_total_mediana",
    columns: [
      { key: "bairro", label: "Bairro" },
      { key: "faixa", label: "Faixa de metragem" },
      { key: "valor_total_mediana", label: "Valor total pago (mediana, revenda)", fmt: (v) => (v == null ? "—" : fmtMoneyCompact(v)) },
      { key: "valor_total_p25", label: "P25", fmt: (v) => (v == null ? "—" : fmtMoneyCompact(v)) },
      { key: "valor_total_p75", label: "P75", fmt: (v) => (v == null ? "—" : fmtMoneyCompact(v)) },
      { key: "n_vendas_revenda_12m", label: "Vendas limpas no período", fmt: (v) => fmtInt(v) },
      {
        key: "janela_meses", label: "Período usado", sortable: false,
        render: (r) => el("span", { title: faixaPeriodoLabel({ janela_meses: r.janela_meses, meses_com_dado: r.meses_com_dado, periodo_inicio: r.periodo_inicio, periodo_fim: r.periodo_fim, n_vendas_limpas: r.n_vendas_revenda_12m }) },
          `${fmtMesAno(r.periodo_inicio)}–${fmtMesAno(r.periodo_fim)} (${r.meses_com_dado === r.janela_meses ? r.janela_meses : r.meses_com_dado} meses)`),
      },
      { key: "n_anuncios", label: "Anúncios hoje" },
      {
        key: "amostra_pequena", label: "Amostra", sortable: false,
        render: (r) => (r.poucas_vendas ? badge("Poucas vendas", "neutral") : badge("Confiável", "gold")),
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
