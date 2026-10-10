// Calculadora de preço de apartamento (protótipo, 2026-10-10).
// Carregado só quando a aba "Calculadora de preço" abre (app.js: ensureCalculadoraLoaded).
// Lê site/calculadora.json (gerado por scripts/build_data.py -> scripts/calculadora_preco.py).
//
// O CÁLCULO (indexar / estimar / anunciosParecidos) é espelho linha a linha de scripts/calculadora_preco.py —
// scripts/verificar_interface.py compara os dois em centenas de casos. Mexeu aqui, mexa lá (e vice-versa).
(function () {
  "use strict";

  // ------------------------------------------------------------------------
  // 1. Cálculo (espelho do Python)
  // ------------------------------------------------------------------------
  function arred(x) { return Math.floor(x + 0.5); }

  function mediana(v) {
    const a = v.slice().sort((x, y) => x - y);
    const n = a.length;
    if (n === 0) return null;
    return n % 2 ? a[(n - 1) / 2] : (a[n / 2 - 1] + a[n / 2]) / 2;
  }

  function percentil(p, v) {
    const a = v.slice().sort((x, y) => x - y);
    const n = a.length;
    if (n === 0) return null;
    if (n === 1) return a[0];
    const idx = (p / 100) * (n - 1);
    const lo = Math.floor(idx);
    const frac = idx - lo;
    const hi = Math.min(lo + 1, n - 1);
    return a[lo] + (a[hi] - a[lo]) * frac;
  }

  const ANDAR_FAIXAS = [[1, 3], [4, 7], [8, 11], [12, 15], [16, 99]];

  function faixaAndar(andar) {
    for (let i = 0; i < ANDAR_FAIXAS.length; i++) {
      if (andar >= ANDAR_FAIXAS[i][0] && andar <= ANDAR_FAIXAS[i][1]) return i;
    }
    return null;
  }

  function fatorAndar(efeito, andar) {
    if (andar == null) return 1.0;
    const i = faixaAndar(andar);
    if (i === null) return 1.0;
    return efeito[i].fator;
  }

  function indexar(dados) {
    const porPredio = {}, porRua = {}, porBairro = {};
    const predios = dados.predios;
    dados.vendas.forEach((v, i) => {
      const p = predios[v[0]];
      (porPredio[v[0]] = porPredio[v[0]] || []).push(i);
      (porRua[p[3]] = porRua[p[3]] || []).push(i);
      (porBairro[p[2]] = porBairro[p[2]] || []).push(i);
    });
    return { predio: porPredio, rua: porRua, bairro: porBairro };
  }

  function selecionar(dados, ids, area, tol) {
    const vs = dados.vendas;
    return ids.filter((i) => Math.abs(vs[i][3] - area) / area <= tol);
  }

  function escolherNivel(dados, ids, area, tols, minimo) {
    for (let j = 0; j < tols.length; j++) {
      const sel = selecionar(dados, ids, area, tols[j]);
      if (sel.length >= minimo) return { sel, tol: tols[j], ampliada: j === 1 };
    }
    return null;
  }

  function estimarBase(dados, idx, entrada) {
    const area = entrada.area;
    const andar = entrada.andar == null ? null : entrada.andar;
    const p = dados.parametros;
    const vs = dados.vendas;
    const efeito = dados.efeito_andar;
    let escolhido = null;
    if (entrada.predio != null) {
      const r = escolherNivel(dados, idx.predio[entrada.predio] || [], area, p.tol_area_predio, p.min_predio);
      if (r) escolhido = { nivel: "predio", ...r };
    }
    if (escolhido === null && entrada.rua != null) {
      const r = escolherNivel(dados, idx.rua[entrada.rua] || [], area, p.tol_area_rua, p.min_rua);
      if (r) escolhido = { nivel: "rua", ...r };
    }
    if (escolhido === null) {
      const r = escolherNivel(dados, idx.bairro[entrada.bairro] || [], area, p.tol_area_bairro, p.min_bairro);
      if (r) escolhido = { nivel: "bairro", ...r };
    }
    if (escolhido === null) return { ok: false, motivo: "poucas_vendas" };
    const { nivel, sel, tol, ampliada } = escolhido;

    const fUser = fatorAndar(efeito, andar);
    const m2 = sel.map((i) => {
      const v = vs[i];
      const fV = fatorAndar(efeito, v[4]);
      return v[2] * v[6] / v[3] / fV * fUser;
    });
    const n = m2.length;
    const midM2 = mediana(m2);
    let loM2, hiM2;
    if (n >= p.min_quartis) { loM2 = percentil(25, m2); hiM2 = percentil(75, m2); }
    else { loM2 = Math.min(...m2); hiM2 = Math.max(...m2); }
    const p25 = percentil(25, m2);
    const razao = (n >= 2 && p25) ? percentil(75, m2) / p25 : null;
    const estimativa = arred(midM2 * area), minimo = arred(loM2 * area), maximo = arred(hiM2 * area);

    let confianca;
    if (nivel === "predio" && n >= p.alta_min_vendas && razao !== null && razao <= p.razao_max_alta) confianca = "alta";
    else if (nivel === "predio" || (nivel === "rua" && n >= p.media_rua_min && razao !== null && razao <= p.razao_max_media_rua)) confianca = "media";
    else confianca = "baixa";

    const ordem = (i) => {
      const v = vs[i];
      const mesmo = v[0] === entrada.predio ? 0 : 1;
      const dAnd = (andar !== null && v[4] != null) ? Math.abs(v[4] - andar) : 99;
      return [mesmo, Math.abs(v[3] - area) / area, dAnd, -v[1], i];
    };
    const cmp = (a, b) => {
      const x = ordem(a), y = ordem(b);
      for (let k = 0; k < x.length; k++) { if (x[k] !== y[k]) return x[k] < y[k] ? -1 : 1; }
      return 0;
    };
    const similares = sel.slice().sort(cmp).slice(0, p.max_similares);

    return {
      ok: true, nivel, n, tolerancia_area: tol, area_ampliada: ampliada, confianca,
      razao_p75_p25: razao === null ? null : Math.round(razao * 1000) / 1000,
      faixa_nome: n >= p.min_quartis ? "p25_p75" : "min_max",
      estimativa, vendas_minimo: minimo, vendas_maximo: maximo,
      m2: arred(midM2), fator_andar: Math.round(fUser * 10000) / 10000,
      similares,
      ultima_venda: Math.max(...sel.map((i) => vs[i][1])),
    };
  }

  // Estimativa + faixa provável (do erro medido a cada build, dados.precisao) + veredito do preço pedido.
  function estimar(dados, idx, entrada) {
    const res = estimarBase(dados, idx, entrada);
    if (!res.ok) return res;
    const p = dados.parametros;
    const prec = dados.precisao || {};
    let t = prec[`${res.nivel}|${res.confianca}`];
    if (!t || t.n < p.precisao_min_testes) t = prec[`${res.nivel}|*`];
    let m = t ? t.p75 : p.margem_fallback;
    m = Math.min(p.margem_max, Math.max(p.margem_min, m));
    const est = res.estimativa;
    res.margem_pct = Math.round(m * 100 * 10) / 10;
    res.precisao_testes = t ? t.n : 0;
    res.precisao_mediana_pct = t ? Math.round(t.mediano * 100 * 10) / 10 : null;
    res.minimo = arred(est / (1 + m));
    res.maximo = arred(est / (1 - m));
    const pedido = entrada.preco_pedido;
    if (pedido) {
      let veredito;
      if (pedido < res.minimo) veredito = "abaixo";
      else if (pedido <= res.maximo) veredito = "dentro";
      else veredito = "acima";
      res.veredito = veredito;
      res.pedido_vs_estimativa_pct = Math.round((pedido / est - 1) * 100 * 10) / 10;
    }
    return res;
  }

  function anunciosParecidos(dados, entrada, estimativa) {
    const p = dados.parametros;
    const quartos = entrada.quartos == null ? null : entrada.quartos;
    const areaUtil = entrada.area_util;
    const out = [];
    dados.anuncios.forEach((a, i) => {
      const mesmoPredio = entrada.predio != null && a[0] === entrada.predio;
      if (!mesmoPredio) {
        if (a[1] !== entrada.bairro) return;
        if (quartos !== null && a[6] != null && a[6] !== quartos) return;
        if (areaUtil) {
          if (!a[5] || Math.abs(a[5] - areaUtil) / areaUtil > p.tol_anuncio_area) return;
        } else if (estimativa) {
          if (Math.abs(a[4] - estimativa) / estimativa > p.tol_anuncio_valor) return;
        }
      }
      out.push([mesmoPredio ? 0 : 1, estimativa ? Math.abs(a[4] - estimativa) : 0, a[8] || "", i]);
    });
    out.sort((x, y) => {
      for (let k = 0; k < 4; k++) { if (x[k] !== y[k]) return x[k] < y[k] ? -1 : 1; }
      return 0;
    });
    return out.slice(0, p.max_anuncios).map((t) => t[3]);
  }

  window.CALC = { indexar, estimar, anunciosParecidos, fatorAndar, faixaAndar };

  // ------------------------------------------------------------------------
  // 2. Tela
  // ------------------------------------------------------------------------
  const root = document.getElementById("calc-root");
  if (!root) return;

  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const ymLabel = (ym) => `${MESES[(ym % 100) - 1]}/${String(Math.floor(ym / 100)).slice(2)}`;
  const brl = (n) => n == null ? "—" : n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
  const num = (n, d = 0) => n == null ? "—" : n.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });

  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return e;
  }

  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/[^A-Z0-9]+/g, " ").trim();
  const numeroDoEndereco = (addrKey) => String((addrKey.split("|")[1] || "")).replace(/^0+(?=\d)/, "");

  let DADOS = null, IDX = null, BUSCA = null;
  const ESTADO = { local: null, andar: "", area: "", areaUtil: "", quartos: "", banheiros: "", suites: "", vagas: "", condominio: "", iptu: "", pedido: "" };

  function montarBusca() {
    BUSCA = {
      predios: DADOS.predios.map((p, i) => ({ i, texto: norm(p[1] + " " + DADOS.bairros[p[2]]), numero: numeroDoEndereco(p[0]), rua: p[3] })),
      ruas: DADOS.ruas.map((r, i) => ({ i, texto: norm(r[0] + " " + DADOS.bairros[r[1]]), nome: r[0], bairro: r[1] })),
    };
  }

  // sugestões: prédios que casam com o texto digitado; com número que não tem vendas, oferece "usar a rua"
  function sugestoes(texto) {
    const toks = norm(texto).split(" ").filter(Boolean);
    if (!toks.length) return [];
    const ehNumero = (t) => /^\d+$/.test(t);
    const numeros = toks.filter(ehNumero);
    const nomes = toks.filter((t) => !ehNumero(t));
    if (!nomes.length) return [];
    const numero = numeros.length ? numeros[numeros.length - 1].replace(/^0+(?=\d)/, "") : null;
    const casa = (txt) => nomes.every((t) => txt.includes(t));
    let achados = BUSCA.predios.filter((p) => casa(p.texto) && (numero === null || p.numero === numero));
    const out = achados.slice(0, 8).map((p) => ({
      tipo: "predio", predio: p.i, rua: p.rua, bairro: DADOS.predios[p.i][2],
      rotulo: DADOS.predios[p.i][1], bairroNome: DADOS.bairros[DADOS.predios[p.i][2]],
    }));
    if (numero !== null && out.length < 8) {
      const ruas = BUSCA.ruas.filter((r) => casa(r.texto)).slice(0, 4);
      for (const r of ruas) {
        if (out.some((o) => o.tipo === "predio" && o.rua === r.i)) continue;
        out.push({ tipo: "rua", predio: null, rua: r.i, bairro: r.bairro, rotulo: `${r.nome}, ${numero}`, bairroNome: DADOS.bairros[r.bairro], semVendas: true });
      }
    }
    if (numero === null && out.length) {
      out.sort((a, b) => a.rotulo.localeCompare(b.rotulo, "pt-BR", { numeric: true }));
    }
    return out;
  }

  function metragensDoPredio(predio) {
    const cont = {};
    for (const i of (IDX.predio[predio] || [])) {
      const a = Math.round(DADOS.vendas[i][3]);
      cont[a] = (cont[a] || 0) + 1;
    }
    return Object.entries(cont).map(([a, n]) => ({ area: Number(a), n })).sort((x, y) => y.n - x.n || x.area - y.area).slice(0, 6);
  }

  // ---- peças da tela ------------------------------------------------------
  function campoNumero(id, rotulo, ajuda, opts = {}) {
    const inp = h("input", { id, type: "number", inputmode: opts.decimal ? "decimal" : "numeric", min: opts.min ?? 0, max: opts.max, step: opts.step ?? 1, placeholder: opts.placeholder || "", value: ESTADO[opts.chave] || "", class: "calc-input" });
    inp.addEventListener("input", () => { ESTADO[opts.chave] = inp.value; });
    return h("label", { class: "calc-campo", for: id }, h("span", { class: "calc-rotulo" }, rotulo), ajuda ? h("span", { class: "calc-ajuda" }, ajuda) : null, inp);
  }

  function renderFormulario() {
    const form = h("div", { class: "calc-form" });

    // 1. endereço
    const boxLocal = h("div", { class: "calc-local" });
    const lista = h("ul", { class: "calc-sugestoes", role: "listbox", hidden: true });
    const entrada = h("input", { id: "calc-endereco", class: "calc-input calc-input-grande", type: "text", autocomplete: "off", role: "combobox", "aria-expanded": "false", "aria-controls": "calc-sugestoes-lista", placeholder: "Ex.: Rua Sena Madureira, 100" });
    lista.id = "calc-sugestoes-lista";
    let ativo = -1, atuais = [];
    const fechar = () => { lista.hidden = true; entrada.setAttribute("aria-expanded", "false"); ativo = -1; };
    const escolher = (s) => {
      ESTADO.local = s;
      fechar();
      renderLocalEscolhido();
      renderMetragens();
    };
    const marcar = () => [...lista.children].forEach((li, k) => li.classList.toggle("ativo", k === ativo));
    const abrir = () => {
      atuais = sugestoes(entrada.value);
      lista.replaceChildren();
      if (!entrada.value.trim()) { fechar(); return; }
      if (!atuais.length) {
        lista.appendChild(h("li", { class: "calc-sem-sugestao", role: "option" }, "Nenhum endereço da carteira com esse nome. Confira a grafia — ou o endereço é de um bairro fora dos 77 da carteira."));
      }
      atuais.forEach((s, k) => {
        const li = h("li", { role: "option", class: "calc-sugestao" },
          h("b", {}, s.rotulo), h("span", { class: "calc-sug-bairro" }, ` — ${s.bairroNome}`),
          s.semVendas ? h("span", { class: "calc-sug-aviso" }, "sem vendas registradas neste número — compara com a rua") : null);
        li.addEventListener("mousedown", (ev) => { ev.preventDefault(); escolher(s); });
        lista.appendChild(li);
      });
      lista.hidden = false;
      entrada.setAttribute("aria-expanded", "true");
      ativo = -1;
    };
    entrada.addEventListener("input", abrir);
    entrada.addEventListener("focus", abrir);
    entrada.addEventListener("blur", () => setTimeout(fechar, 120));
    entrada.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown") { ev.preventDefault(); ativo = Math.min(ativo + 1, atuais.length - 1); marcar(); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); ativo = Math.max(ativo - 1, 0); marcar(); }
      else if (ev.key === "Enter") { if (ativo >= 0 && atuais[ativo]) { ev.preventDefault(); escolher(atuais[ativo]); } else if (atuais.length === 1) { ev.preventDefault(); escolher(atuais[0]); } }
      else if (ev.key === "Escape") fechar();
    });
    const caixaBusca = h("div", { class: "calc-busca" }, h("label", { class: "calc-rotulo", for: "calc-endereco" }, "Endereço do imóvel"), entrada, lista);
    form.append(h("div", { class: "calc-passo" }, h("div", { class: "calc-passo-titulo" }, "1. Onde fica?"), caixaBusca, boxLocal));

    function renderLocalEscolhido() {
      boxLocal.replaceChildren();
      const s = ESTADO.local;
      if (!s) return;
      boxLocal.append(h("div", { class: "calc-local-card" },
        h("div", {}, h("b", {}, s.rotulo), h("div", { class: "calc-ajuda" }, `${s.bairroNome} · São Paulo${s.semVendas ? " · sem vendas registradas neste número: o cálculo usa as vendas da mesma rua" : ""}`)),
        h("button", { type: "button", class: "calc-link", onclick: () => { ESTADO.local = null; entrada.value = ""; renderLocalEscolhido(); renderMetragens(); entrada.focus(); } }, "Mudar")));
    }
    form.renderLocalEscolhido = renderLocalEscolhido;

    // 2. o imóvel
    const metragens = h("div", { class: "calc-metragens", id: "calc-metragens" });
    function renderMetragens() {
      metragens.replaceChildren();
      const s = ESTADO.local;
      if (!s || s.predio == null) return;
      const ms = metragensDoPredio(s.predio);
      if (!ms.length) return;
      metragens.append(h("span", { class: "calc-ajuda" }, "Metragens que já foram vendidas neste prédio (toque para usar): "));
      ms.forEach((m) => metragens.append(h("button", { type: "button", class: "calc-chip", onclick: () => { ESTADO.area = String(m.area); document.getElementById("calc-area").value = ESTADO.area; } }, `${m.area} m² · ${m.n} ${m.n === 1 ? "venda" : "vendas"}`)));
    }
    form.append(h("div", { class: "calc-passo" },
      h("div", { class: "calc-passo-titulo" }, "2. Qual é o apartamento?"),
      h("div", { class: "calc-tipo" }, h("span", { class: "calc-chip ativo", "aria-current": "true" }, "Apartamento"), h("span", { class: "calc-ajuda" }, "Casas, studios e coberturas: ainda não nesta calculadora.")),
      h("div", { class: "calc-grade" },
        campoNumero("calc-andar", "Andar", "Só o número (térreo = 0 não entra no cálculo de andar)", { chave: "andar", min: 0, max: 60, placeholder: "Ex.: 15" }),
        campoNumero("calc-area", "Área construída (m²)", "A do carnê do IPTU / escritura — a mesma que o ITBI usa", { chave: "area", min: 10, max: 2000, step: "any", decimal: true, placeholder: "Ex.: 140" }),
        campoNumero("calc-area-util", "Área útil (m²) — opcional", "A da planta. Só para mostrar o R$/m² útil e achar anúncios parecidos", { chave: "areaUtil", min: 10, max: 2000, step: "any", decimal: true, placeholder: "Ex.: 110" })),
      metragens));

    // 3. detalhes
    form.append(h("div", { class: "calc-passo" },
      h("div", { class: "calc-passo-titulo" }, "3. Detalhes"),
      h("div", { class: "calc-grade calc-grade-4" },
        campoNumero("calc-quartos", "Quartos", "Contando suítes", { chave: "quartos", max: 15 }),
        campoNumero("calc-banheiros", "Banheiros", "Sem lavabo e serviço", { chave: "banheiros", max: 15 }),
        campoNumero("calc-suites", "Suítes", "", { chave: "suites", max: 15 }),
        campoNumero("calc-vagas", "Vagas", "", { chave: "vagas", max: 15 })),
      h("div", { class: "calc-grade" },
        campoNumero("calc-condominio", "Condomínio (R$ por mês)", "", { chave: "condominio", step: 10, placeholder: "Ex.: 2300" }),
        campoNumero("calc-iptu", "IPTU (R$ por ano)", "O valor total do carnê", { chave: "iptu", step: 10 }),
        campoNumero("calc-pedido", "Preço que o proprietário quer pedir (R$) — opcional", "Para saber se está dentro do mercado", { chave: "pedido", step: 1000, placeholder: "Ex.: 1200000" })),
      h("p", { class: "calc-ajuda calc-aviso-campos" }, "Quartos, banheiros, suítes, vagas, condomínio e IPTU não mudam o preço calculado — o ITBI não traz esses dados. Servem para escolher os anúncios parecidos e para o resumo.")));

    const msg = h("div", { class: "calc-erro", id: "calc-erro", role: "alert", hidden: true });
    const botao = h("button", { type: "button", class: "calc-botao", onclick: calcular }, "Calcular o preço");
    form.append(msg, h("div", { class: "calc-acoes" }, botao, h("button", { type: "button", class: "calc-link", onclick: limpar }, "Limpar tudo")));
    return form;
  }

  function paraNumero(v) { const n = Number(String(v).replace(",", ".")); return v === "" || !isFinite(n) ? null : n; }

  function erro(texto) {
    const e = document.getElementById("calc-erro");
    e.textContent = texto || "";
    e.hidden = !texto;
  }

  function limpar() {
    Object.assign(ESTADO, { local: null, andar: "", area: "", areaUtil: "", quartos: "", banheiros: "", suites: "", vagas: "", condominio: "", iptu: "", pedido: "" });
    montar();
  }

  function entradaDoFormulario() {
    const s = ESTADO.local;
    if (!s) { erro("Escolha o endereço na lista que aparece quando você digita."); return null; }
    const area = paraNumero(ESTADO.area);
    if (!area || area < 10 || area > 2000) { erro("Informe a área construída em m² (entre 10 e 2.000). Dica: toque numa das metragens já vendidas no prédio."); return null; }
    const andar = paraNumero(ESTADO.andar);
    if (andar != null && (andar < 0 || andar > 60 || Math.round(andar) !== andar)) { erro("O andar tem que ser um número inteiro de 0 a 60."); return null; }
    const pedido = paraNumero(ESTADO.pedido);
    if (pedido != null && pedido < 10000) { erro("O preço pedido parece baixo demais — confira se digitou o valor completo (ex.: 1200000)."); return null; }
    erro("");
    return {
      predio: s.predio, rua: s.rua, bairro: s.bairro, area,
      andar: andar != null && andar >= 1 ? andar : null,
      preco_pedido: pedido || null, area_util: paraNumero(ESTADO.areaUtil) || null,
      quartos: paraNumero(ESTADO.quartos),
    };
  }

  // ---- resultado ------------------------------------------------------------
  const NIVEL_TEXTO = {
    predio: (r, ent) => `${r.n} ${r.n === 1 ? "venda parecida" : "vendas parecidas"} no mesmo prédio`,
    rua: (r) => `${r.n} vendas parecidas na mesma rua (outros prédios, mesmo bairro)`,
    bairro: (r, ent) => `${r.n} vendas parecidas no bairro ${DADOS.bairros[ent.bairro]} (não há vendas parecidas suficientes no prédio nem na rua)`,
  };
  const NIVEL_CURTO = { predio: "vendas do próprio prédio", rua: "vendas da rua", bairro: "vendas do bairro" };
  const CONF_TEXTO = {
    alta: ["Confiança alta", "good", "Vendas suficientes no próprio prédio, com preços próximos entre si."],
    media: ["Confiança média", "warning", "Poucas vendas parecidas, ou preços bem diferentes entre si. Use a faixa, não só o número do meio."],
    baixa: ["Confiança baixa", "critical", "Sem vendas parecidas suficientes no prédio: a comparação é com a rua ou o bairro. Serve de referência, não de preço."],
  };

  function renderBarra(r, pedido) {
    const base = Math.min(r.minimo, pedido || r.minimo);
    const topo = Math.max(r.maximo, pedido || r.maximo);
    const folga = (topo - base) * 0.25 || r.estimativa * 0.1;
    const lo = base - folga, hi = topo + folga;
    const pos = (v) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)).toFixed(2)}%`;
    const barra = h("div", { class: "calc-barra" + (pedido ? " com-pedido" : "") },
      h("div", { class: "calc-barra-faixa", style: `left:${pos(r.minimo)};width:calc(${pos(r.maximo)} - ${pos(r.minimo)})` }),
      h("div", { class: "calc-marca calc-marca-est", style: `left:${pos(r.estimativa)}` }, h("span", {}, "Estimativa")));
    if (pedido) barra.append(h("div", { class: `calc-marca calc-marca-pedido ${r.veredito}`, style: `left:${pos(pedido)}` }, h("span", {}, "Pedido")));
    return h("div", {},
      barra,
      h("div", { class: "calc-barra-rotulos" }, h("span", {}, `${brl(r.minimo)}`, h("small", {}, " (limite baixo)")), h("span", {}, `${brl(r.maximo)}`, h("small", {}, " (limite alto)"))));
  }

  const VEREDITO = {
    abaixo: ["Abaixo da faixa provável", "good", "O preço pedido está abaixo do que vendas parecidas costumam alcançar. Dá para pedir mais."],
    dentro: ["Dentro da faixa provável", "good", "O preço pedido está dentro do que vendas parecidas costumam alcançar."],
    acima: ["Acima da faixa provável", "warning", "O preço pedido está acima do que vendas parecidas costumam alcançar — vale conferir o que justifica a diferença (acabamento, vista, reforma)."],
  };

  function tabela(cabecalhos, linhas, classe) {
    return h("div", { class: "table-scroll" }, h("table", { class: `data-table ${classe || ""}` },
      h("thead", {}, h("tr", {}, cabecalhos.map((c) => h("th", {}, c)))),
      h("tbody", {}, linhas.map((l) => h("tr", {}, l.map((c) => h("td", {}, c)))))));
  }

  function renderResultado(ent, r) {
    const out = document.getElementById("calc-resultado");
    out.replaceChildren();
    if (!r.ok) {
      out.append(h("section", { class: "card" }, h("h2", {}, "Sem estimativa"),
        h("p", {}, "Não há vendas parecidas suficientes (nem no prédio, nem na rua, nem no bairro) para essa metragem. Em vez de chutar um número, a calculadora não responde. Tente conferir a área construída informada."),
        h("p", { class: "muted small" }, "Regra: no prédio precisa de 3+ vendas com área até 20% diferente; na rua, 5+ (até 25%); no bairro, 10+ (até 30%).")));
      return;
    }
    const [confNome, confCor, confExpl] = CONF_TEXTO[r.confianca];
    const mesBase = DADOS.mes_base.split("-").map(Number);
    const mesBaseTxt = `${MESES[mesBase[1] - 1]}/${mesBase[0]}`;
    const iptuMes = paraNumero(ESTADO.iptu) != null ? paraNumero(ESTADO.iptu) / 12 : null;
    const cond = paraNumero(ESTADO.condominio);

    const card = h("section", { class: "card calc-resultado-card" });
    card.append(
      h("div", { class: "calc-topo" },
        h("div", {}, h("div", { class: "calc-rotulo" }, "O apartamento vale cerca de"), h("div", { class: "calc-valor" }, brl(r.estimativa)),
          h("div", { class: "calc-ajuda" }, `R$ ${num(r.m2)}/m² da área construída` + (ent.area_util ? ` · R$ ${num(r.estimativa / ent.area_util)}/m² da área útil` : ""))),
        h("div", { class: "calc-selos" }, h("span", { class: `badge ${confCor === "good" ? "gold" : confCor}` }, confNome))),
      renderBarra(r, ent.preco_pedido),
      h("p", { class: "calc-ajuda" }, `Faixa provável: em ${r.precisao_testes.toLocaleString("pt-BR")} testes com vendas reais, em casos como este (${NIVEL_CURTO[r.nivel]}, ${confNome.toLowerCase()}), o preço pago ficou dentro desta faixa em 3 de cada 4 vendas — erro típico de ${num(r.precisao_mediana_pct, 0)}%, margem de ${num(r.margem_pct, 0)}%. `, confExpl));

    if (r.veredito) {
      const [vt, vc, vx] = VEREDITO[r.veredito];
      card.append(h("div", { class: `calc-veredito ${vc}` },
        h("b", {}, `${vt} — pedido de ${brl(ent.preco_pedido)}`),
        h("div", {}, `${vx} (${r.pedido_vs_estimativa_pct > 0 ? "+" : ""}${num(r.pedido_vs_estimativa_pct, 1)}% em relação à estimativa de ${brl(r.estimativa)}.)`),
        r.confianca === "baixa" ? h("div", { class: "calc-ajuda" }, `Como a confiança é baixa, a faixa é larga (${brl(r.minimo)} a ${brl(r.maximo)}): o veredito é só um indicativo.`) : null,
        h("div", { class: "calc-ajuda" }, "A comparação é com o que foi PAGO nas vendas (guias de ITBI), não com preços de anúncio.")));
    }

    const porque = h("div", { class: "calc-porque" },
      h("h3", {}, "Como chegamos nesse número"),
      h("ul", {},
        h("li", {}, `${NIVEL_TEXTO[r.nivel](r, ent)}, com área construída até ${num(r.tolerancia_area * 100)}% diferente de ${num(ent.area, ent.area % 1 ? 1 : 0)} m²${r.area_ampliada ? " (ampliamos a tolerância porque havia poucas vendas na tolerância menor)" : ""}.`),
        h("li", {}, `Cada venda foi atualizada pelo preço de ${mesBaseTxt} (último mês completo), pela variação de R$/m² do mesmo bairro — assim uma venda antiga não puxa o preço pra baixo. A venda mais recente usada é de ${ymLabel(r.ultima_venda)}.`),
        h("li", {}, `O número do meio é a mediana dessas vendas, já atualizadas. As vendas parecidas foram de ${brl(r.vendas_minimo)} a ${brl(r.vendas_maximo)} (${r.faixa_nome === "p25_p75" ? "do 25º ao 75º percentil — metade delas" : "da menor à maior, por serem poucas"}).`),
        h("li", {}, `A faixa provável (${brl(r.minimo)} a ${brl(r.maximo)}) é mais larga que as vendas parecidas de propósito: vem do erro medido ao tirar vendas reais do cálculo e estimar o preço delas com as outras. Preço de apartamento varia por acabamento, vista e estado — coisas que o ITBI não mostra.`),
        ent.andar != null
          ? h("li", {}, r.fator_andar === 1 ? `Andar ${ent.andar}: nos dados, esta faixa de andar não tem diferença de preço medida em relação ao resto do prédio — sem ajuste.` : `Andar ${ent.andar}: nos dados, esta faixa de andar paga ${num(Math.abs(r.fator_andar - 1) * 100, 1)}% ${r.fator_andar > 1 ? "a mais" : "a menos"} que a mediana do mesmo prédio — já considerado.`)
          : h("li", {}, "Andar não informado (ou térreo): sem ajuste de andar."),
        h("li", {}, "O que o ITBI não mostra e fica por sua conta ajustar: acabamento, reforma, vista, face do sol, vagas e estado do prédio.")));
    card.append(porque);

    if (cond != null || iptuMes != null) {
      card.append(h("div", { class: "calc-custos" }, h("b", {}, "Custo mensal para manter: "),
        [cond != null ? `condomínio ${brl(cond)}` : null, iptuMes != null ? `IPTU ${brl(iptuMes)}/mês (${brl(paraNumero(ESTADO.iptu))}/ano)` : null].filter(Boolean).join(" + "),
        cond != null && iptuMes != null ? ` = ${brl(cond + iptuMes)} por mês` : ""));
    }
    out.append(card);

    // vendas parecidas
    const vs = DADOS.vendas;
    const linhasV = r.similares.map((i) => {
      const v = vs[i], p = DADOS.predios[v[0]];
      return [ymLabel(v[1]), v[0] === ent.predio ? "mesmo prédio" : p[1], v[4] != null ? `${v[4]}º` : "—", `${num(v[3], v[3] % 1 ? 1 : 0)} m²`, brl(v[2]), brl(arred(v[2] * v[6])), v[5] != null ? String(v[5]) : "—"];
    });
    out.append(h("section", { class: "card" }, h("h2", {}, "Vendas parecidas (ITBI)"),
      h("div", { class: "card-sub" }, `As ${linhasV.length} mais parecidas entre as ${r.n} usadas no cálculo — valor realmente registrado na guia de ITBI. “Atualizado” = o mesmo valor corrigido para ${mesBaseTxt}. O andar é estimado pelo número do apartamento no ITBI (ex.: apto 152 = 15º); “Vagas” só aparece quando está escrita no complemento.`),
      tabela(["Mês da venda", "Onde", "Andar", "Área construída", "Valor pago", "Atualizado", "Vagas"], linhasV)));

    // anúncios parecidos
    const anuncios = anunciosParecidos(DADOS, ent, r.estimativa);
    const linhasA = anuncios.map((i) => {
      const a = DADOS.anuncios[i];
      const link = a[9] ? h("a", { href: a[9], target: "_blank", rel: "noopener" }, a[8] || "ver") : (a[8] || "—");
      return [a[3] || "—", a[5] != null ? `${num(a[5], a[5] % 1 ? 1 : 0)} m²` : "—", a[6] != null ? String(a[6]) : "—", a[7] != null ? String(a[7]) : "—", brl(a[4]), a[10] != null ? `${a[10]} dias` : "—", link];
    });
    const critA = ent.area_util ? `mesmo bairro, área útil até 25% diferente de ${num(ent.area_util)} m²` : `mesmo bairro, preço até 30% diferente da estimativa`;
    out.append(h("section", { class: "card" }, h("h2", {}, "À venda agora (nonStop)"),
      h("div", { class: "card-sub" }, `Anúncios ativos da rede: primeiro os do mesmo prédio, depois ${critA}${ent.quartos != null ? `, com ${ent.quartos} ${ent.quartos === 1 ? "quarto" : "quartos"}` : ""}. Preço pedido, não preço pago — a área aqui é a útil do anúncio.`),
      linhasA.length ? tabela(["Endereço", "Área", "Quartos", "Vagas", "Preço pedido", "Anunciado há", "Código"], linhasA)
        : h("p", { class: "muted" }, "Nenhum anúncio parecido na rede hoje.")));

    // resumo para copiar
    const resumo = montarResumo(ent, r, anuncios.length);
    const copiar = h("button", { type: "button", class: "calc-botao calc-botao-sec", onclick: async () => {
      try { await navigator.clipboard.writeText(resumo); copiar.textContent = "Resumo copiado ✓"; } catch (e) { copiar.textContent = "Não consegui copiar — selecione o texto abaixo"; }
      setTimeout(() => { copiar.textContent = "Copiar resumo"; }, 2500);
    } }, "Copiar resumo");
    out.append(h("section", { class: "card" }, h("h2", {}, "Resumo para conversar com o proprietário"), h("pre", { class: "calc-resumo" }, resumo), copiar));
    out.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function montarResumo(ent, r, nAnuncios) {
    const s = ESTADO.local;
    const mesBase = DADOS.mes_base.split("-").map(Number);
    const linhas = [
      `Estimativa de preço — ${s.rotulo} (${s.bairroNome})`,
      `Apartamento${ent.andar != null ? `, ${ent.andar}º andar` : ""}, ${num(ent.area, ent.area % 1 ? 1 : 0)} m² de área construída${ent.area_util ? ` (${num(ent.area_util)} m² úteis)` : ""}.`,
      `Valor estimado: cerca de ${brl(r.estimativa)} (faixa de ${brl(r.minimo)} a ${brl(r.maximo)}).`,
      `Base: ${r.n} vendas parecidas ${r.nivel === "predio" ? "no mesmo prédio" : r.nivel === "rua" ? "na mesma rua" : "no bairro"}, valores de guias de ITBI atualizados para ${MESES[mesBase[1] - 1]}/${mesBase[0]}. ${CONF_TEXTO[r.confianca][0]}.`,
    ];
    if (r.veredito) linhas.push(`Preço pretendido de ${brl(ent.preco_pedido)}: ${VEREDITO[r.veredito][0].toLowerCase()} (${r.pedido_vs_estimativa_pct > 0 ? "+" : ""}${num(r.pedido_vs_estimativa_pct, 1)}% sobre a estimativa).`);
    linhas.push(`Faixa provável: ${brl(r.minimo)} a ${brl(r.maximo)} (em testes com vendas reais, o preço pago ficou dentro de faixas assim em 3 de cada 4 casos).`);
    if (nAnuncios) linhas.push(`Há ${nAnuncios} anúncio(s) parecido(s) à venda hoje na rede.`);
    linhas.push("Acabamento, reforma, vista e estado do prédio não entram no cálculo e podem mudar o valor.");
    return linhas.join("\n");
  }

  function calcular() {
    const ent = entradaDoFormulario();
    if (!ent) return;
    renderResultado(ent, estimar(DADOS, IDX, ent));
  }

  function montar() {
    root.replaceChildren();
    const form = renderFormulario();
    root.append(h("section", { class: "card" }, h("h2", {}, "Calculadora de preço de apartamento"),
      h("div", { class: "card-sub" }, `Estimativa de venda com base no que foi realmente pago: guias de ITBI de revenda (compra e venda, 100% do imóvel, valor dentro do padrão — a mesma camada limpa do resto do painel), atualizadas para o preço de ${DADOS.mes_base.split("-").reverse().join("/")} pela variação de R$/m² de cada bairro. ${num(DADOS.resumo.vendas)} vendas em ${num(DADOS.resumo.predios)} prédios dos 77 bairros da carteira. Compara primeiro com o próprio prédio, depois com a rua, depois com o bairro — e diz qual dos três usou e quão confiável é.`),
      form), h("div", { id: "calc-resultado" }));
    form.renderLocalEscolhido();
    if (ESTADO.local) { document.getElementById("calc-endereco").value = ESTADO.local.rotulo; }
  }

  async function iniciar() {
    root.replaceChildren(h("p", { class: "muted" }, "Carregando a calculadora…"));
    try {
      const res = await fetch("calculadora.json", { cache: "no-cache" });
      if (!res.ok) throw new Error(String(res.status));
      DADOS = await res.json();
    } catch (e) {
      root.replaceChildren(h("section", { class: "card" }, h("h2", {}, "Calculadora de preço"),
        h("p", {}, "Os dados da calculadora ainda não estão disponíveis nesta publicação. Eles são gerados junto com a atualização diária — se acabou de entrar no ar, tente de novo depois da próxima atualização (08:00).")));
      return;
    }
    IDX = indexar(DADOS);
    montarBusca();
    if (window.CALC_ESTADO_SALVO) { Object.assign(ESTADO, window.CALC_ESTADO_SALVO); window.CALC_ESTADO_SALVO = null; }
    montar();
  }
  window.CALC.iniciar = iniciar;
  window.CALC.dados = () => DADOS;
  window.CALC.estado = ESTADO;
  iniciar();
})();
