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

  const TOL_AREA_POUCAS = 0.20; // prédio com só 1 ou 2 vendas parecidas
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
      else {
        // só 1 ou 2 vendas parecidas no prédio: ainda é a melhor referência (testes: erro ~13-15% contra ~20% da rua/bairro),
        // mas com confiança menor, margem própria e segunda opinião (ver estimar)
        const sel1 = selecionar(dados, idx.predio[entrada.predio] || [], area, TOL_AREA_POUCAS);
        if (sel1.length) escolhido = { nivel: "predio_poucas", sel: sel1, tol: TOL_AREA_POUCAS, ampliada: true };
      }
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
    const eq = {}; // cada venda "equivalente" à metragem e ao andar informados
    sel.forEach((i, k) => { eq[i] = m2[k] * area; });
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
    else if (nivel === "predio_poucas") confianca = n >= 2 ? "media" : "baixa"; // no máximo média: poucas vendas
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
      _ids: sel,
      _eq: eq,
    };
  }

  const QTS = [1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 75, 80, 85, 90, 95, 98, 99];
  const ESCADA = [10, 25, 50, 75, 90];
  // Interpolação linear (xs crescente), pontas fixas. Espelho de calculadora_preco._interp.
  function interp(xs, ys, x) {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
    for (let i = 0; i < xs.length - 1; i++) {
      if (xs[i] <= x && x <= xs[i + 1]) {
        if (xs[i + 1] === xs[i]) return ys[i];
        return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i]);
      }
    }
    return ys[ys.length - 1];
  }

  // Estimativa + faixa provável (do erro medido a cada build, dados.precisao) + veredito do preço pedido.
  function estimar(dados, idx, entrada) {
    const res = estimarBase(dados, idx, entrada);
    if (!res.ok) return res;
    const p = dados.parametros;
    const usaUtil = entrada.area_origem === "util_estimada"; // área do cadastro estimada pela útil: faixa mais larga (tabela própria)
    const prec = (usaUtil ? dados.precisao_util : dados.precisao) || {};
    res.area_estimada_pela_util = usaUtil;
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
    if (res.nivel === "predio_poucas") {
      // segunda opinião: o que a rua (ou o bairro) diria, sem separar o prédio
      const alt = estimarBase(dados, idx, { ...entrada, predio: null });
      if (alt.ok) {
        res.segunda_opiniao = { nivel: alt.nivel, n: alt.n, estimativa: alt.estimativa, diferenca_pct: Math.round((alt.estimativa / est - 1) * 100 * 10) / 10 };
        res.segunda_diverge = Math.abs(alt.estimativa / est - 1) > m;
      }
    }
    const q = t ? t.q : null;
    const ids = res._ids; delete res._ids;
    const eqs = res._eq; delete res._eq;
    if (q && q.length === QTS.length) {
      // Escada de preços: quantas vendas parecidas chegaram a cada preço (erro medido nos testes com vendas reais).
      res.escada = ESCADA.map((pp) => [100 - pp, arred(est * interp(QTS, q, pp))]);
      res.teto_verde = arred(est * interp(QTS, q, 100 - p.veredito_verde * 100));
      res.teto_amarelo = arred(est * interp(QTS, q, 100 - p.veredito_amarelo * 100));
      res.piso_mercado = res.escada[0][1];
      const valores = ids.map((i) => eqs[i]); // equivalentes à metragem informada (não o preço total de plantas diferentes)
      res.maior_venda = arred(Math.max(...valores));
      // vendas fora do padrão: equivalente abaixo do percentil 10 ou acima do 90 do que vendas parecidas costumam ter
      const lo = est * interp(QTS, q, 10), hi = est * interp(QTS, q, 90);
      res.similares_eq = res.similares.map((i) => arred(eqs[i]));
      res.similares_flag = res.similares.map((i) => (eqs[i] < lo ? -1 : (eqs[i] > hi ? 1 : 0)));
      const pedido = entrada.preco_pedido;
      if (pedido) {
        const x = pedido / est;
        const chegaram = 1 - interp(q, QTS, x) / 100;
        // A cor é decidida pelos VALORES em reais mostrados na tela ("até R$ X" inclui o próprio X), não pela porcentagem
        const precoAbaixo = arred(est * interp(QTS, q, 100 - p.veredito_abaixo * 100));
        let veredito;
        if (pedido <= precoAbaixo) veredito = "abaixo";
        else if (pedido <= res.teto_verde) veredito = "dentro";
        else if (pedido <= res.teto_amarelo) veredito = "alto";
        else veredito = "fora";
        res.veredito = veredito;
        res.pedido_chegaram_pct = arred(chegaram * 100);
        res.pedido_alem_dos_testes = x >= q[q.length - 1];
        res.pedido_vs_estimativa_pct = Math.round((x - 1) * 100 * 10) / 10;
        res.pedido_n_chegaram = valores.filter((v) => v >= pedido).length;
        res.pedido_acima_do_verde = Math.max(0, pedido - res.teto_verde);
      }
    }
    if (res.similares_eq === undefined) { // sem tabela de precisão: só o equivalente, sem marcar atípicas
      res.similares_eq = res.similares.map((i) => arred(eqs[i]));
      res.similares_flag = res.similares.map(() => 0);
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

  // Espelho de calculadora_preco.andar_e_final: (andar, final) do apartamento de número n na numeração do prédio
  // ("c" = centenas: 801 = 8º, final 01; "d" = dezenas: 152 = 15º, final 2). O "final" identifica a planta.
  function andarEFinal(n, conv) {
    if (n < 10) return [null, null];
    let andar, final;
    if (n >= 1000 || (n >= 100 && n <= 999 && conv === "c")) { andar = Math.floor(n / 100); final = n % 100; }
    else { andar = Math.floor(n / 10); final = n % 10; }
    return andar >= 1 && andar <= 60 ? [andar, final] : [null, null];
  }

  window.CALC = { indexar, estimar, anunciosParecidos, fatorAndar, faixaAndar, andarEFinal };

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
      else if (k === "html") e.innerHTML = v;   // só strings montadas aqui com números e datas (sem texto digitado)
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      e.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return e;
  }

  // A Prefeitura grava os nomes de rua abreviados ("RUA CD DE ITU" = Rua Conde de Itu). A busca entende as duas
  // formas e a tela mostra por extenso. ALIAS: palavra por extenso -> abreviações usadas no ITBI.
  const ALIAS = { CONDE: ["CD"], BARAO: ["BR"], PADRE: ["PDE", "PE"], SAO: ["S"], SANTA: ["STA"], SANTO: ["STO"], GENERAL: ["GAL"], CORONEL: ["CEL"],
    PROFESSOR: ["PROF"], PROFESSORA: ["PROFA"], DOUTOR: ["DR"], DOUTORA: ["DRA"], VISCONDE: ["VISC"], MINISTRO: ["MIN"], CONSELHEIRO: ["CONS"],
    ENGENHEIRO: ["ENG"], MARQUES: ["MARQ"], MARECHAL: ["MAL"], CAPITAO: ["CAP"], NOSSA: ["NSRA", "NSA"], COMENDADOR: ["COMEN"], BRIGADEIRO: ["BRIG"],
    SENADOR: ["SEN"], VEREADOR: ["VER"], MAJOR: ["MAJ"], TENENTE: ["TTE"], DEPUTADO: ["DEP"], ALMIRANTE: ["ALM"], AVENIDA: ["AV", "AVD"], RUA: ["R"], ALAMEDA: ["AL"], PRACA: ["PC"], TRAVESSA: ["TV"] };
  const EXTENSO = { CD: "Conde", BR: "Barão", PDE: "Padre", STA: "Santa", STO: "Santo", GAL: "General", CEL: "Coronel", VISC: "Visconde", MIN: "Ministro",
    CONS: "Conselheiro", ENG: "Engenheiro", MARQ: "Marquês", MAL: "Marechal", CAP: "Capitão", NSRA: "Nossa Senhora", COMEN: "Comendador", BRIG: "Brigadeiro",
    SEN: "Senador", VER: "Vereador", MAJ: "Major", TTE: "Tenente", DEP: "Deputado", ALM: "Almirante", DR: "Dr.", DRA: "Dra.", PROF: "Prof.", PROFA: "Profa." };
  const SEM_VALOR = new Set(["DE", "DA", "DO", "DAS", "DOS", "E", "SENHORA"]);
  // "Rua Cd De Itu, 352" -> "Rua Conde De Itu, 352" ("S" só vira São logo depois do tipo: "Rua S Joaquim")
  function bonito(txt) {
    const ws = String(txt || "").split(" ");
    return ws.map((w, i) => {
      const u = w.replace(/[.,]/g, "").toUpperCase();
      if (u === "S" && i === 1) return "São";
      return EXTENSO[u] && i > 0 ? EXTENSO[u] : w;
    }).join(" ");
  }

  // Anexa filhos num elemento IGNORANDO null/false (o append nativo do navegador escreveria a palavra "null" na tela).
  const anexar = (pai, ...filhos) => { for (const f of filhos.flat()) if (f != null && f !== false) pai.append(f); return pai; };

  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/[^A-Z0-9]+/g, " ").trim();
  const numeroDoEndereco = (addrKey) => String((addrKey.split("|")[1] || "")).replace(/^0+(?=\d)/, "");

  let DADOS = null, IDX = null, BUSCA = null, FORM = null, LINHA = null, AJUSTE = null, CHIPS = null; // FORM: controle do formulário (recolher/expandir)
  const ESTADO = { local: null, apto: "", andar: "", andarAuto: false, area: "", areaAuto: false, areaNota: "", areaManual: false, areaOrigem: "", plantaEscolhida: "", mostrarPlantas: false, ajustarAberto: false, areaUtil: "", quartos: "", banheiros: "", suites: "", vagas: "", condominio: "", iptu: "", pedido: "", corretor: "" };

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
    const nomes = toks.filter((t) => !ehNumero(t) && !SEM_VALOR.has(t));
    if (!nomes.length) return [];
    const numero = numeros.length ? numeros[numeros.length - 1].replace(/^0+(?=\d)/, "") : null;
    // cada palavra digitada casa se aparece no texto (inclusive pedaço de palavra) ou se a abreviação da Prefeitura aparece como palavra inteira
    const casa = (txt) => {
      const palavras = new Set(txt.split(" "));
      return nomes.every((t) => txt.includes(t) || (ALIAS[t] || []).some((a) => palavras.has(a)));
    };
    const achados = BUSCA.predios.filter((p) => casa(p.texto) && (numero === null || p.numero === numero));
    const out = achados.slice(0, 8).map((p) => ({
      tipo: "predio", predio: p.i, rua: p.rua, bairro: DADOS.predios[p.i][2],
      rotulo: bonito(DADOS.predios[p.i][1]), bairroNome: DADOS.bairros[DADOS.predios[p.i][2]],
    }));
    if (numero !== null && out.length < 8) {
      const ruas = BUSCA.ruas.filter((r) => casa(r.texto)).slice(0, 4);
      for (const r of ruas) {
        if (out.some((o) => o.tipo === "predio" && o.rua === r.i)) continue;
        // mesmo nome e número de um prédio que já está na lista (ex.: o mesmo endereço aparecendo em outro bairro): é o mesmo endereço, não repete
        if (out.some((o) => o.rotulo === `${bonito(r.nome)}, ${numero}`)) continue;
        out.push({ tipo: "rua", predio: null, rua: r.i, bairro: r.bairro, rotulo: `${bonito(r.nome)}, ${numero}`, bairroNome: DADOS.bairros[r.bairro], semVendas: true });
      }
    }
    if (numero === null && out.length) {
      out.sort((a, b) => a.rotulo.localeCompare(b.rotulo, "pt-BR", { numeric: true }));
    }
    return out;
  }

  // Plantas já vendidas no prédio (metragem do cadastro) — usadas pra descobrir a do apartamento e como botões de escolha
  const arred1 = (x) => Math.round(x * 10) / 10;

  // botões com as plantas do prédio; tocar = "esta é a planta do apartamento" (`recalcular` refaz o cálculo na hora)
  function chipsMetragem(ms, recalcular, sugerida) {
    const box = h("span", { class: "calc-chips" });
    ms.forEach((m) => box.append(h("button", { type: "button", class: "calc-chip" + (sugerida === m.area ? " sugerida" : ""), onclick: () => {
      ESTADO.plantaEscolhida = m.area; ESTADO.areaManual = false; ESTADO.mostrarPlantas = false;
      const aj = document.getElementById("calc-area"); if (aj) aj.value = "";
      atualizarMetragem();
      if (recalcular) calcular();
    } }, `${m.area} m² · ${m.n} ${m.n === 1 ? "venda" : "vendas"}`, sugerida === m.area ? h("span", { class: "calc-chip-tag" }, "mais provável") : null)));
    return box;
  }

  // número do apartamento (ex.: 152) -> andar (15); a metragem do cadastro sai de atualizarMetragem()
  function resolverPeloApto() {
    const s = ESTADO.local;
    const n = paraNumero(ESTADO.apto);
    if (s && s.predio != null && n != null && n >= 10 && Math.round(n) === n) {
      const [andar] = andarEFinal(n, DADOS.predios[s.predio][4] || "d");
      if (andar !== null && (ESTADO.andar === "" || ESTADO.andarAuto)) { ESTADO.andar = String(andar); ESTADO.andarAuto = true; }
    }
    const ia = document.getElementById("calc-andar");
    if (ia) ia.value = ESTADO.andar;
    atualizarMetragem();
  }

  // De onde vem a área do cadastro (a que o ITBI usa) — nesta ordem: a que a pessoa digitou do carnê; o número do apartamento (mesmo
  // final no mesmo prédio = mesma planta); prédio de planta única; a planta tocada; e, sem nada disso, ESTIMADA pela área útil
  // (útil × relação cadastro÷útil medida nos dados). Devolve {area, origem, texto, ...}; area=null quando precisa escolher/informar.
  function resolverMetragem() {
    const s = ESTADO.local, util = paraNumero(ESTADO.areaUtil), rz = DADOS.razao_util;
    const manual = paraNumero(ESTADO.area);
    if (ESTADO.areaManual && manual >= 10 && manual <= 2000) return { area: manual, origem: "informada", texto: `Metragem do cadastro usada: ${num(manual, manual % 1 ? 1 : 0)} m² (a do carnê que você informou).` };
    if (!s) return null;
    const estimar = () => {
      const area = arred1(util * rz.mediana);
      return { area, origem: "util_estimada", texto: `Metragem do cadastro ESTIMADA pela área útil: ${num(util, util % 1 ? 1 : 0)} m² × ${num(rz.mediana, 2)} = ${num(area, 1)} m². A relação real varia de ${num(rz.q["25"], 2)} a ${num(rz.q["75"], 2)} conforme o prédio, então a faixa fica mais larga.` };
    };
    if (s.predio != null) {
      const n = paraNumero(ESTADO.apto);
      let semFinal = null;
      if (n != null && n >= 10 && Math.round(n) === n) {
        const [andar, final] = andarEFinal(n, DADOS.predios[s.predio][4] || "d");
        if (andar !== null) {
          const cont = {};
          for (const i of (IDX.predio[s.predio] || [])) { const v = DADOS.vendas[i]; if (v[8] === final) { const a = Math.round(v[3]); cont[a] = (cont[a] || 0) + 1; } }
          const achadas = Object.entries(cont).map(([a, c]) => ({ area: Number(a), n: c })).sort((x, y) => y.n - x.n || x.area - y.area);
          if (achadas.length) return { area: achadas[0].area, origem: "apto", texto: `Metragem do cadastro usada: ${achadas[0].area} m² — pelo número do apartamento (final ${final}; ${achadas[0].n} ${achadas[0].n === 1 ? "venda" : "vendas"} do mesmo final neste prédio).` };
          semFinal = final;
        }
      }
      const ms = metragensDoPredio(s.predio, 99);
      if (ms.length && Math.max(...ms.map((m) => m.area)) / Math.min(...ms.map((m) => m.area)) <= 1.03) return { area: ms[0].area, origem: "planta_unica", texto: `Metragem do cadastro usada: ${ms[0].area} m² — este prédio tem uma planta só.` };
      if (ESTADO.plantaEscolhida === "util") { if (util && rz) return estimar(); }
      else if (typeof ESTADO.plantaEscolhida === "number") return { area: ESTADO.plantaEscolhida, origem: "planta_escolhida", texto: `Metragem do cadastro usada: ${ESTADO.plantaEscolhida} m² — a planta que você escolheu.` };
      const alvo = util && rz ? util * rz.mediana : null;
      const sugerida = alvo ? ms.slice().sort((a, b) => Math.abs(Math.log(a.area / alvo)) - Math.abs(Math.log(b.area / alvo)))[0].area : null;
      return { area: null, origem: "", precisaEscolher: true, sugerida, plantas: ms,
        texto: semFinal !== null ? `Este prédio não tem venda registrada com o final ${semFinal}, então não dá para descobrir a planta pelo número. Toque na planta do apartamento abaixo${sugerida ? " (a mais provável, pela sua área útil, está marcada)" : ""}.`
          : `Qual é a planta do apartamento? Informe o número do apartamento (ex.: 152) ou toque na planta abaixo${sugerida ? " (a mais provável, pela sua área útil, está marcada)" : ""}.` };
    }
    // sem prédio na base (rua ou bairro): só dá pra estimar pela área útil
    if (util && rz) return estimar();
    return { area: null, origem: "", precisaUtil: true, texto: "Informe a área útil do apartamento (a do anúncio ou da planta)." };
  }

  // Redesenha a linha "Metragem do cadastro usada…" (e os botões das plantas, quando precisa escolher) e guarda o resultado em ESTADO.
  function atualizarMetragem() {
    if (!LINHA || !DADOS) return;
    const m = resolverMetragem();
    ESTADO.areaOrigem = m && m.origem || "";
    if (!ESTADO.areaManual) {
      ESTADO.area = m && m.area != null ? String(m.area) : "";
      const aj = document.getElementById("calc-area"); if (aj && document.activeElement !== aj) aj.value = "";   // o campo do carnê só tem o que a PESSOA digitou; a metragem automática aparece na linha acima
    }
    LINHA.replaceChildren();
    CHIPS.replaceChildren();
    if (!m) return;
    const s = ESTADO.local;
    const ms = s && s.predio != null ? metragensDoPredio(s.predio, 6) : [];
    const mostrar = ESTADO.mostrarPlantas || m.precisaEscolher;
    anexar(LINHA, h("div", { class: "calc-nota-area" + (m.area == null ? " pendente" : "") }, m.texto),
      h("div", { class: "calc-area-links" },
        h("button", { type: "button", class: "calc-link", id: "calc-abrir-carne", onclick: () => {
          ESTADO.ajustarAberto = !ESTADO.ajustarAberto;
          AJUSTE.hidden = !ESTADO.ajustarAberto;
          if (ESTADO.ajustarAberto) {   // abre logo abaixo do link, com o cursor no campo e visível na tela
            const campo = document.getElementById("calc-area");
            campo.focus({ preventScroll: true });
            AJUSTE.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        } }, ESTADO.ajustarAberto ? "Fechar o campo do carnê" : "Tenho o carnê do IPTU: ajustar a área"),
        ms.length > 1 && !m.precisaEscolher ? h("button", { type: "button", class: "calc-link", onclick: () => { ESTADO.mostrarPlantas = !ESTADO.mostrarPlantas; atualizarMetragem(); } }, "Trocar a planta") : null));
    if (mostrar && ms.length) {
      anexar(CHIPS, h("div", { class: "calc-metragens" }, h("span", { class: "calc-ajuda" }, "Plantas já vendidas neste prédio (metragem do cadastro) — toque na do seu apartamento: "),
        chipsMetragem(ms, false, m.sugerida),
        h("button", { type: "button", class: "calc-chip calc-chip-util", onclick: () => { ESTADO.plantaEscolhida = "util"; ESTADO.areaManual = false; ESTADO.mostrarPlantas = false; atualizarMetragem(); } }, "Não sei — estimar pela área útil")));
    }
    AJUSTE.hidden = !ESTADO.ajustarAberto;
  }

  function metragensDoPredio(predio, limite = 6) {
    const cont = {};
    for (const i of (IDX.predio[predio] || [])) {
      const a = Math.round(DADOS.vendas[i][3]);
      cont[a] = (cont[a] || 0) + 1;
    }
    return Object.entries(cont).map(([a, n]) => ({ area: Number(a), n })).sort((x, y) => y.n - x.n || x.area - y.area).slice(0, limite);
  }

  // ---- peças da tela ------------------------------------------------------
  function campoNumero(id, rotulo, ajuda, opts = {}) {
    const inp = h("input", { id, type: "number", inputmode: opts.decimal ? "decimal" : "numeric", min: opts.min ?? 0, max: opts.max, step: opts.step ?? 1, placeholder: opts.placeholder || "", value: ESTADO[opts.chave] || "", class: "calc-input" });
    inp.addEventListener("input", () => {
      ESTADO[opts.chave] = inp.value;
      if (opts.chave === "area") { ESTADO.areaManual = inp.value !== ""; atualizarMetragem(); }   // digitou a do carnê: vale sobre tudo
      if (opts.chave === "andar") ESTADO.andarAuto = false;
      if (opts.chave === "apto") resolverPeloApto();
      if (opts.chave === "areaUtil") atualizarMetragem();
    });
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
    const zerarImovel = () => Object.assign(ESTADO, { apto: "", andar: "", andarAuto: false, area: "", areaAuto: false, areaNota: "", areaManual: false, areaOrigem: "", plantaEscolhida: "", mostrarPlantas: false, ajustarAberto: false, areaUtil: "" });
    const escolher = (s) => {
      const antes = ESTADO.local;
      if (antes && (antes.predio !== s.predio || antes.rua !== s.rua || antes.bairro !== s.bairro)) zerarImovel(); // outro endereço: andar, metragem etc. do anterior não valem
      ESTADO.local = s;
      fechar();
      renderLocalEscolhido();
      resolverPeloApto();
    };
    const marcar = () => [...lista.children].forEach((li, k) => li.classList.toggle("ativo", k === ativo));
    const abrir = () => {
      atuais = sugestoes(entrada.value);
      lista.replaceChildren();
      if (!entrada.value.trim()) { fechar(); return; }
      if (!atuais.length) {
        const botaoB = h("button", { type: "button", class: "calc-link" }, "Calcular só pelo bairro");
        botaoB.addEventListener("mousedown", (ev) => { ev.preventDefault(); fechar(); boxBairro.hidden = false; selBairro.focus(); });
        lista.appendChild(h("li", { class: "calc-sem-sugestao", role: "option" }, "Nenhum endereço com esse nome. Confira a grafia (a Prefeitura abrevia: “Cd” = Conde, “Pde” = Padre…). Se está certo, é porque não há venda de apartamento registrada nessa rua desde 2024. ", botaoB));
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
    // plano B: o endereço não tem venda de apartamento na base -> calcula só pelo bairro (confiança baixa)
    const selBairro = h("select", { id: "calc-so-bairro", class: "calc-input", "aria-label": "Bairro" }, h("option", { value: "" }, "Escolha o bairro…"),
      DADOS.bairros.map((b, i) => [i, b]).sort((x, y) => x[1].localeCompare(y[1], "pt-BR")).map(([i, b]) => h("option", { value: String(i) }, b)));
    selBairro.addEventListener("change", () => {
      if (selBairro.value === "") return;
      const i = Number(selBairro.value);
      escolher({ tipo: "bairro", predio: null, rua: null, bairro: i, rotulo: entrada.value.trim() || "Endereço não encontrado", bairroNome: DADOS.bairros[i], soBairro: true });
    });
    const boxBairro = h("div", { class: "calc-so-bairro", hidden: true }, h("span", { class: "calc-ajuda" }, "O cálculo usa só as vendas de apartamento do bairro (confiança baixa, margem larga):"), selBairro);
    const linkBairro = h("button", { type: "button", class: "calc-link", onclick: () => { boxBairro.hidden = !boxBairro.hidden; } }, "Não achei o endereço — calcular só pelo bairro");
    const planoB = h("div", { class: "calc-plano-b" }, linkBairro);
    form.append(h("div", { class: "calc-passo" }, h("div", { class: "calc-passo-titulo" }, "1. Onde fica?"), caixaBusca, planoB, boxBairro, boxLocal));

    function renderLocalEscolhido() {
      boxLocal.replaceChildren();
      const s = ESTADO.local;
      planoB.hidden = !!s;                     // endereço escolhido: o plano B some
      if (s) boxBairro.hidden = true;
      if (!s) return;
      boxLocal.append(h("div", { class: "calc-local-card" },
        h("div", {}, h("b", {}, s.rotulo), h("div", { class: "calc-ajuda" }, `${s.bairroNome} · São Paulo${s.soBairro ? " · só pelo bairro: o cálculo usa as vendas de apartamento do bairro" : s.semVendas ? " · sem vendas registradas neste número: o cálculo usa as vendas da mesma rua" : ""}`)),
        h("button", { type: "button", class: "calc-link", onclick: () => { ESTADO.local = null; entrada.value = ""; zerarImovel(); montar(); document.getElementById("calc-endereco").focus(); } }, "Mudar")));
    }
    form.renderLocalEscolhido = renderLocalEscolhido;

    // 2. o imóvel: o que o corretor sabe (número do apartamento, andar, ÁREA ÚTIL). A área do cadastro (a do ITBI/IPTU) vem sozinha.
    LINHA = h("div", { class: "calc-area-linha", id: "calc-area-linha" });
    CHIPS = h("div", { class: "calc-chips-area", id: "calc-chips-area" });
    const campoAjuste = campoNumero("calc-area", "Área construída do carnê do IPTU (m²) — opcional", "Se você tem o carnê, digite a área construída dele: ela vale mais que qualquer cálculo automático", { chave: "area", min: 10, max: 2000, step: "any", decimal: true, placeholder: "Ex.: 140" });
    AJUSTE = h("div", { class: "calc-ajuste", id: "calc-area-ajuste", hidden: true }, campoAjuste);
    form.append(h("div", { class: "calc-passo" },
      h("div", { class: "calc-passo-titulo" }, "2. Qual é o apartamento?"),
      h("div", { class: "calc-tipo" }, h("span", { class: "calc-chip ativo", "aria-current": "true" }, "Apartamento"), h("span", { class: "calc-ajuda" }, "Casas, studios e coberturas: ainda não nesta calculadora.")),
      h("div", { class: "calc-grade calc-grade-3" },
        campoNumero("calc-apto", "Número do apartamento — recomendado", "Ex.: 152. Com ele eu descubro o andar e a metragem do cadastro sozinha", { chave: "apto", min: 0, max: 9999, placeholder: "Ex.: 152" }),
        campoNumero("calc-andar", "Andar", "Só o número (preenchido sozinho se você informar o apartamento)", { chave: "andar", min: 0, max: 60, placeholder: "Ex.: 15" }),
        campoNumero("calc-area-util", "Área útil (m²)", "A que o comprador usa: a do anúncio ou da planta", { chave: "areaUtil", min: 10, max: 1500, step: "any", decimal: true, placeholder: "Ex.: 85" })),
      LINHA, AJUSTE, CHIPS));

    // 3. preço pedido (sempre visível) + detalhes opcionais (recolhidos: não mudam o preço, só os anúncios parecidos e o resumo)
    const detalhes = h("details", { class: "calc-mais", id: "calc-mais" },
      h("summary", { class: "calc-mais-resumo" }, h("span", { class: "calc-mais-titulo" }, "Mais detalhes (opcional)"),
        h("span", { class: "calc-ajuda" }, "quartos, banheiros, suítes, vagas, condomínio e IPTU — não mudam o preço")),
      h("div", { class: "calc-mais-corpo" },
        h("div", { class: "calc-grade calc-grade-4" },
          campoNumero("calc-quartos", "Quartos", "Contando suítes", { chave: "quartos", max: 15 }),
          campoNumero("calc-banheiros", "Banheiros", "Sem lavabo e serviço", { chave: "banheiros", max: 15 }),
          campoNumero("calc-suites", "Suítes", "", { chave: "suites", max: 15 }),
          campoNumero("calc-vagas", "Vagas", "", { chave: "vagas", max: 15 })),
        h("div", { class: "calc-grade" },
          campoNumero("calc-condominio", "Condomínio (R$ por mês)", "", { chave: "condominio", step: 10, placeholder: "Ex.: 2300" }),
          campoNumero("calc-iptu", "IPTU (R$ por ano)", "O valor total do carnê", { chave: "iptu", step: 10 })),
        h("p", { class: "calc-ajuda calc-aviso-campos" }, "Quartos, banheiros, suítes, vagas, condomínio e IPTU não mudam o preço calculado — o ITBI não traz esses dados. Servem para escolher os anúncios parecidos e para o resumo.")));
    if (["quartos", "banheiros", "suites", "vagas", "condominio", "iptu"].some((k) => ESTADO[k] !== "")) detalhes.open = true; // já tem algo preenchido: não esconde
    form.append(h("div", { class: "calc-passo" },
      h("div", { class: "calc-passo-titulo" }, "3. Preço pedido"),
      h("div", { class: "calc-grade calc-grade-pedido" },
        campoNumero("calc-pedido", "Preço que o proprietário quer pedir (R$) — opcional", "Para saber se está dentro do mercado. Dá para testar outros valores depois, no resultado", { chave: "pedido", step: 1000, placeholder: "Ex.: 1200000" })),
      detalhes));

    const msg = h("div", { class: "calc-erro", id: "calc-erro", role: "alert", hidden: true });
    const botao = h("button", { type: "button", class: "calc-botao", id: "calc-calcular", onclick: calcular }, "Calcular o preço");
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
    Object.assign(ESTADO, { local: null, apto: "", andar: "", andarAuto: false, area: "", areaAuto: false, areaNota: "", areaManual: false, areaOrigem: "", plantaEscolhida: "", mostrarPlantas: false, ajustarAberto: false, areaUtil: "", quartos: "", banheiros: "", suites: "", vagas: "", condominio: "", iptu: "", pedido: "", corretor: "" });
    montar();
    document.getElementById("calc-card").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function entradaDoFormulario() {
    const s = ESTADO.local;
    if (!s) { erro("Escolha o endereço na lista que aparece quando você digita."); return null; }
    const util = paraNumero(ESTADO.areaUtil);
    if (ESTADO.areaUtil !== "" && (util == null || util < 10 || util > 1500)) { erro("A área útil tem que ficar entre 10 e 1.500 m²."); return null; }
    if (ESTADO.areaManual) { const mm = paraNumero(ESTADO.area); if (mm == null || mm < 10 || mm > 2000) { erro("A área construída do carnê tem que ficar entre 10 e 2.000 m² (ou apague o campo para eu descobrir sozinha)."); return null; } }
    const metr = resolverMetragem();
    if (!metr || metr.area == null) {
      if (metr && metr.precisaEscolher) { ESTADO.mostrarPlantas = true; atualizarMetragem(); erro("Falta descobrir a planta do apartamento: informe o número do apartamento ou toque na planta certa (a mais provável está marcada) — ou em “Não sei — estimar pela área útil”."); }
      else erro("Informe a área útil do apartamento (ou o número do apartamento, para eu descobrir a metragem do cadastro).");
      return null;
    }
    const area = metr.area;
    const andar = paraNumero(ESTADO.andar);
    if (andar != null && (andar < 0 || andar > 60 || Math.round(andar) !== andar)) { erro("O andar tem que ser um número inteiro de 0 a 60."); return null; }
    const pedido = paraNumero(ESTADO.pedido);
    if (pedido != null && pedido < 10000) { erro("O preço pedido parece baixo demais — confira se digitou o valor completo (ex.: 1200000)."); return null; }
    erro("");
    return {
      predio: s.predio, rua: s.rua, bairro: s.bairro, area, area_origem: metr.origem,
      andar: andar != null && andar >= 1 ? andar : null,
      preco_pedido: pedido || null, area_util: util || null,
      quartos: paraNumero(ESTADO.quartos),
    };
  }

  // ---- resultado ------------------------------------------------------------
  const NIVEL_TEXTO = {
    predio: (r, ent) => `${r.n} ${r.n === 1 ? "venda parecida" : "vendas parecidas"} no mesmo prédio`,
    predio_poucas: (r, ent) => `Só ${r.n} ${r.n === 1 ? "venda parecida" : "vendas parecidas"} no mesmo prédio (ainda é a melhor referência, mas é pouco)`,
    rua: (r) => `${r.n} vendas parecidas na mesma rua (outros prédios, mesmo bairro)`,
    bairro: (r, ent) => `${r.n} vendas parecidas no bairro ${DADOS.bairros[ent.bairro]} (não há vendas parecidas suficientes no prédio nem na rua)`,
  };
  const NIVEL_CURTO = { predio: "vendas do próprio prédio", predio_poucas: "poucas vendas do próprio prédio", rua: "vendas da rua", bairro: "vendas do bairro" };
  const CONF_TEXTO = {
    alta: ["Confiança alta", "good", "Vendas suficientes no próprio prédio, com preços próximos entre si."],
    media: ["Confiança média", "warning", "Poucas vendas parecidas, ou preços bem diferentes entre si. Olhe a régua de cores, não só o número do meio."],
    baixa: ["Confiança baixa", "critical", "Sem vendas parecidas suficientes no prédio: a comparação é com a rua ou o bairro. Serve de referência, não de preço."],
  };

  // Quantas vendas parecidas chegaram a um preço (texto simples, "em cada 100")
  const em100 = (pct, alem) => (alem || pct < 1) ? "menos de 1 em cada 100" : `${pct} em cada 100`;
  const PONTOS = { alta: "●●●", media: "●●○", baixa: "●○○" };

  // Régua em 3 cores: verde = preço de mercado, amarelo = acima, vermelho = fora do mercado. Marcas: Estimativa e Pedido.
  function renderBarra(r, pedido) {
    const lo = Math.min(r.piso_mercado, pedido || Infinity) * 0.97;
    const hi = Math.max(r.teto_amarelo * 1.12, (pedido || 0) * 1.04);
    const pos = (v) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)).toFixed(2)}%`;
    const zona = (de, ate, cls) => h("div", { class: `calc-zona ${cls}`, style: `left:${pos(de)};width:calc(${pos(ate)} - ${pos(de)})` });
    const barra = h("div", { class: "calc-barra" + (pedido ? " com-pedido" : "") },
      zona(lo, r.estimativa, "abaixo"), zona(r.estimativa, r.teto_verde, "verde"), zona(r.teto_verde, r.teto_amarelo, "amarelo"), zona(r.teto_amarelo, hi, "vermelho"),
      h("div", { class: "calc-marca calc-marca-est", style: `left:${pos(r.estimativa)}` }, h("span", {}, "Estimativa")));
    if (pedido) barra.append(h("div", { class: `calc-marca calc-marca-pedido ${r.veredito}`, style: `left:${pos(pedido)}` }, h("span", {}, "Pedido")));
    const p = DADOS.parametros;
    const linha = (cor, titulo, texto) => h("div", { class: "calc-legenda-linha" }, h("span", { class: `calc-ponto ${cor}` }), h("div", {}, h("b", {}, titulo), " ", texto));
    return h("div", {},
      barra,
      h("div", { class: "calc-legenda" },
        linha("verde", `Até ${brl(r.teto_verde)} — preço de mercado.`, `${Math.round(p.veredito_verde * 10)} ou mais em cada 10 vendas parecidas chegaram a esse valor.`),
        linha("amarelo", `De ${brl(r.teto_verde)} a ${brl(r.teto_amarelo)} — acima do mercado.`, `De ${Math.round(p.veredito_amarelo * 100)} a ${Math.round(p.veredito_verde * 100)} em cada 100 chegaram. Exige negociação.`),
        linha("vermelho", `Acima de ${brl(r.teto_amarelo)} — fora do mercado.`, `Menos de ${Math.round(p.veredito_amarelo * 100)} em cada 100 vendas parecidas chegaram a esse valor.`)));
  }

  const VEREDITO = {
    abaixo: ["Abaixo do mercado", "good", "O pedido está abaixo do que a maioria das vendas parecidas alcançou. Dá para pedir mais."],
    dentro: ["No preço de mercado", "good", "O pedido está dentro do que o mercado paga por apartamentos parecidos."],
    alto: ["Acima do mercado", "warning", "O pedido está acima do que a maioria das vendas parecidas alcançou: vai exigir negociação."],
    fora: ["Fora do mercado", "critical", "Pouquíssimas vendas parecidas chegaram a esse valor. Anunciar assim é arriscar ficar parado."],
  };

  function tabela(cabecalhos, linhas, classe) {
    return h("div", { class: "table-scroll" }, h("table", { class: `data-table ${classe || ""}` },
      h("thead", {}, h("tr", {}, cabecalhos.map((c) => h("th", {}, c)))),
      h("tbody", {}, linhas.map((l) => h("tr", {}, l.map((c) => h("td", {}, c)))))));
  }

  // Quando o prédio tem vendas mas nenhuma com a metragem digitada, o cálculo cai pra rua/bairro. Isso não pode passar
  // batido (é o sinal de que digitaram a área útil): avisa e oferece as metragens do cadastro pra tocar e recalcular.
  function avisoMetragem(ent, r) {
    const s = ESTADO.local;
    if (!s || s.predio == null || (r.ok && r.nivel.startsWith("predio")) || ["apto", "planta_unica", "planta_escolhida"].includes(ent.area_origem)) return null;
    const ms = metragensDoPredio(s.predio);
    if (!ms.length) return null;
    return h("section", { class: "card calc-aviso-area" }, h("h3", {}, "Confira a metragem"),
      h("p", {}, `Neste prédio ninguém vendeu um apartamento com área do cadastro perto de ${num(ent.area, ent.area % 1 ? 1 : 0)} m² — as vendas daqui foram de ${ms.map((m) => `${m.area} m²`).join(", ")}. `,
        r.ok ? `Por isso a calculadora usou as vendas d${r.nivel === "rua" ? "a rua" : "o bairro"}, que são menos precisas.` : "Por isso não deu para calcular."),
      h("p", { class: "calc-ajuda" }, "Se você digitou a área útil, toque na metragem do cadastro correspondente (a do cadastro é bem maior que a útil) — ou informe o número do apartamento:"),
      chipsMetragem(ms, true));
  }

  // Veredito do preço pedido (selo colorido + frase de quantas vendas chegaram + quanto baixar + evidência do prédio)
  function blocoVeredito(ent, r) {
    const [vt, vc, vx] = VEREDITO[r.veredito];
    const sinal = r.pedido_vs_estimativa_pct > 0 ? "acima" : "abaixo";
    return h("div", { class: `calc-veredito ${vc}`, id: "calc-veredito" },
      h("div", { class: "calc-veredito-titulo" }, h("span", { class: "calc-veredito-selo" }, vt.toUpperCase()), h("b", {}, `Pedido de ${brl(ent.preco_pedido)}`)),
      h("div", { class: "calc-veredito-frase" }, `${em100(r.pedido_chegaram_pct, r.pedido_alem_dos_testes)} vendas parecidas chegaram a esse valor ou mais.`.replace(/^./, (c) => c.toUpperCase())),
      h("div", {}, `${vx} O pedido está ${brl(Math.abs(ent.preco_pedido - r.estimativa))} (${num(Math.abs(r.pedido_vs_estimativa_pct), 1)}%) ${sinal} da estimativa de ${brl(r.estimativa)}.`),
      r.pedido_acima_do_verde > 0 ? h("div", {}, h("b", {}, `Para entrar no preço de mercado, o pedido precisaria baixar ${brl(r.pedido_acima_do_verde)} (até ${brl(r.teto_verde)}).`)) : null,
      h("div", {}, `Nas ${r.n} vendas parecidas usadas (${NIVEL_CURTO[r.nivel]}), levadas para a sua metragem, a mais alta equivale a ${brl(r.maior_venda)} — ${r.pedido_n_chegaram === 0 ? "nenhuma chegou ao pedido" : `${r.pedido_n_chegaram} ${r.pedido_n_chegaram === 1 ? "chegou" : "chegaram"} ao pedido ou mais`}.`),
      (r.confianca === "baixa" || r.nivel === "predio_poucas") ? h("div", { class: "calc-ajuda" }, `Como há poucas vendas ${r.nivel === "predio_poucas" ? "parecidas no prédio" : "para comparar"}, o veredito é um indicativo.`) : null,
      h("div", { class: "calc-ajuda" }, "A comparação é com o que foi PAGO nas vendas (guias de ITBI), não com preços de anúncio."));
  }

  function renderResultado(ent, r) {
    const out = document.getElementById("calc-resultado");
    out.replaceChildren();
    RELATORIO = null;
    mostrarBotaoRelatorio(false);
    const aviso = avisoMetragem(ent, r);
    if (aviso) out.append(aviso);
    if (!r.ok) {
      out.append(h("section", { class: "card" }, h("h2", {}, "Sem estimativa"),
        h("p", {}, "Não há vendas parecidas suficientes (nem no prédio, nem na rua, nem no bairro) para essa metragem. Em vez de chutar um número, a calculadora não responde. Tente conferir a área construída informada."),
        h("p", { class: "muted small" }, "Regra: no prédio precisa de 3+ vendas com área até 20% diferente; na rua, 5+ (até 25%); no bairro, 10+ (até 30%).")));
      out.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (r.teto_verde == null) { // arquivo de dados antigo (sem a tabela de preços): pede a próxima atualização
      out.append(h("section", { class: "card" }, h("h2", {}, "Calculadora em atualização"), h("p", {}, "Os dados desta publicação ainda não têm a tabela de preços por faixa. Tente de novo depois da próxima atualização diária (08:00).")));
      return;
    }
    const [confNome, confCor, confExplBase] = CONF_TEXTO[r.confianca];
    const confExpl = r.nivel === "predio_poucas"
      ? `Só ${r.n} ${r.n === 1 ? "venda parecida" : "vendas parecidas"} no próprio prédio: ainda é a melhor referência que temos (mais precisa que a rua ou o bairro), mas use com cautela.`
      : confExplBase;
    const mesBase = DADOS.mes_base.split("-").map(Number);
    const mesBaseTxt = `${MESES[mesBase[1] - 1]}/${mesBase[0]}`;
    const iptuMes = paraNumero(ESTADO.iptu) != null ? paraNumero(ESTADO.iptu) / 12 : null;
    const cond = paraNumero(ESTADO.condominio);

    // simulador "E se o proprietário pedir…?": muda o pedido e atualiza régua, cor, frase e resumo na hora (a estimativa não muda)
    const r0 = estimar(DADOS, IDX, { ...ent, preco_pedido: null });
    const estMin = Math.floor(r.estimativa * 0.6 / 1000) * 1000, estMax = Math.ceil(r.estimativa * 2.2 / 1000) * 1000;
    const inputSim = h("input", { id: "calc-sim-valor", type: "number", class: "calc-input calc-sim-input", min: 0, step: 1000, inputmode: "numeric",
      placeholder: `Ex.: ${num(Math.round(r.teto_verde / 1000) * 1000)}`, "aria-label": "Preço que o proprietário pede, em reais" });
    const slider = h("input", { id: "calc-sim-slider", type: "range", class: "calc-slider", min: estMin, max: estMax, step: 1000, "aria-label": "Arraste para testar outros preços" });
    const saida = h("div", { class: "calc-sim-saida", id: "calc-sim-saida" });
    const simulador = h("div", { class: "calc-sim", id: "calc-sim" });
    let resumoPre = null, nAnuncios = 0, rAtual = r;
    const pintar = (valor) => {
      const v = valor != null && isFinite(valor) && valor >= 10000 ? valor : null;
      const ent2 = { ...ent, preco_pedido: v };
      const r2 = v ? estimar(DADOS, IDX, ent2) : r0;
      rAtual = r2;
      RELATORIO = { ent: ent2, r: r2 };   // o PDF sai com o que está na tela (inclui o preço testado no simulador)
      ESTADO.pedido = v ? String(v) : "";
      const campo = document.getElementById("calc-pedido");
      if (campo && document.activeElement !== campo) campo.value = ESTADO.pedido;   // o campo do formulário acompanha
      simulador.className = "calc-sim" + (v ? ` ${VEREDITO[r2.veredito][1]}` : "");
      saida.replaceChildren(renderBarra(r2, v), v ? blocoVeredito(ent2, r2)
        : h("div", { class: "calc-sim-vazio" }, "Digite um preço acima (ou toque num dos botões) para comparar com o mercado."));
      if (resumoPre) resumoPre.textContent = montarResumo(ent2, r2, nAnuncios);
    };
    const definir = (valor, origem) => {
      if (origem !== "input") inputSim.value = valor == null ? "" : String(valor);
      if (origem !== "slider" && valor != null) slider.value = String(Math.max(estMin, Math.min(estMax, valor)));
      pintar(valor);
    };
    let quadro = null;
    inputSim.addEventListener("input", () => { cancelAnimationFrame(quadro); quadro = requestAnimationFrame(() => definir(inputSim.value === "" ? null : Number(inputSim.value), "input")); });
    slider.addEventListener("input", () => { inputSim.value = slider.value; definir(Number(slider.value), "slider"); });
    const botoes = [[`Preço de mercado (até ${brl(r.teto_verde)})`, r.teto_verde], [`Estimativa (${brl(r.estimativa)})`, r.estimativa], [`Limite amarelo (${brl(r.teto_amarelo)})`, r.teto_amarelo]];
    anexar(simulador,
      h("div", { class: "calc-sim-titulo" }, "E se o proprietário pedir…?"),
      h("div", { class: "calc-ajuda" }, "Digite um preço (ou arraste) e veja na hora a cor, a frase e a régua. A estimativa não muda."),
      h("div", { class: "calc-sim-linha" }, h("span", { class: "calc-sim-rs" }, "R$"), inputSim),
      slider,
      h("div", { class: "calc-sim-chips" }, botoes.map(([rot, val]) => h("button", { type: "button", class: "calc-chip", onclick: () => definir(val, "botao") }, rot)),
        h("button", { type: "button", class: "calc-link", onclick: () => definir(null, "botao") }, "Limpar")));

    const card = h("section", { class: "card calc-resultado-card" });
    anexar(card,
      h("div", { class: "calc-topo" },
        h("div", {}, h("div", { class: "calc-rotulo" }, "O apartamento vale cerca de"), h("div", { class: "calc-valor" }, brl(r.estimativa)),
          h("div", { class: "calc-ajuda" }, `R$ ${num(r.m2)}/m² da área construída` + (ent.area_util ? ` · R$ ${num(r.estimativa / ent.area_util)}/m² da área útil` : ""))),
        h("div", { class: "calc-corretor" }, h("label", { class: "calc-rotulo", for: "calc-corretor" }, "Pedida sugerida pelo corretor"),
          h("div", { class: "calc-sim-linha" }, h("span", { class: "calc-sim-rs" }, "R$"),
            h("input", { id: "calc-corretor", type: "number", class: "calc-input calc-corretor-input", min: 0, step: 1000, inputmode: "numeric", value: ESTADO.corretor,
              placeholder: "Ex.: " + num(Math.round(r.teto_verde / 1000) * 1000), "aria-label": "Preço de pedida sugerido pelo corretor, em reais",
              oninput: (ev) => { ESTADO.corretor = ev.target.value; } })),
          h("span", { class: "calc-ajuda" }, "Com quanto você acha que vale começar o anúncio. Sai no PDF ao lado do preço da calculadora.")),
        h("div", { class: "calc-selos" }, h("span", { class: "badge neutral", title: confExpl }, `${confNome} ${PONTOS[r.confianca]}`))),
      h("div", { class: "calc-anunciar" }, h("b", {}, `Para anunciar: até ${brl(r.teto_verde)}`), ` — acima de ${brl(r.teto_amarelo)} o imóvel fica fora do mercado.`),
      r.area_estimada_pela_util ? h("div", { class: "calc-poucas" },
        h("b", {}, "A área do cadastro foi estimada pela área útil."),
        h("div", {}, `${num(ent.area_util, ent.area_util % 1 ? 1 : 0)} m² úteis × ${num(DADOS.razao_util.mediana, 2)} = ${num(ent.area, 1)} m² no cadastro. A relação real varia de ${num(DADOS.razao_util.q["25"], 2)} a ${num(DADOS.razao_util.q["75"], 2)} conforme o prédio — por isso a faixa é mais larga.`),
        h("div", { class: "calc-poucas-alerta" }, "Para uma estimativa mais firme, informe o número do apartamento ou a área construída do carnê do IPTU.")) : "",
      simulador, saida,
      r.nivel === "predio_poucas" ? h("div", { class: "calc-poucas" },
        h("b", {}, `Atenção: só ${r.n} ${r.n === 1 ? "venda parecida" : "vendas parecidas"} neste prédio.`),
        r.segunda_opiniao ? h("div", {}, `Segunda opinião — ${r.segunda_opiniao.nivel === "rua" ? "pela rua" : "pelo bairro"} (${r.segunda_opiniao.n} vendas): ${brl(r.segunda_opiniao.estimativa)} (${r.segunda_opiniao.diferenca_pct > 0 ? "+" : ""}${num(r.segunda_opiniao.diferenca_pct, 1)}% em relação à estimativa do prédio).`) : null,
        r.segunda_diverge ? h("div", { class: "calc-poucas-alerta" }, "As duas estimativas divergem mais do que a margem de erro: confira a metragem, o andar e o estado do imóvel antes de apresentar o preço ao proprietário.") : null) : "",
      h("p", { class: "calc-ajuda" }, `Como medimos: em ${r.precisao_testes.toLocaleString("pt-BR")} testes com vendas reais, em casos como este (${NIVEL_CURTO[r.nivel]}, ${confNome.toLowerCase()}), o erro típico foi de ${num(r.precisao_mediana_pct, 0)}%. As cores dizem quantas vendas parecidas chegaram a cada preço. ${confExpl}`),
      h("div", { class: "calc-escada" }, h("div", { class: "calc-rotulo" }, "Por quanto as vendas parecidas fecharam (valores atualizados)"),
        h("div", { class: "calc-escada-grade" }, r.escada.map(([sh, v]) => h("div", { class: "calc-escada-item" }, h("div", { class: "calc-escada-valor" }, brl(v)), h("div", { class: "calc-ajuda" }, `${sh} em cada 100 chegaram a pelo menos isso`))))));

    const porque = h("div", { class: "calc-porque" },
      h("h3", {}, "Como chegamos nesse número"),
      h("ul", {},
        r.area_estimada_pela_util ? h("li", {}, `A área do cadastro (a que o ITBI usa) foi ESTIMADA a partir da sua área útil: ${num(ent.area_util, 1)} m² × ${num(DADOS.razao_util.mediana, 2)} (mediana de ${num(DADOS.razao_util.n)} casos de ${num(DADOS.razao_util.predios)} prédios em que o anúncio e a venda do mesmo apartamento permitem medir a relação). A faixa e as cores já embutem esse erro, medido em testes.`) : "",
        h("li", {}, `${NIVEL_TEXTO[r.nivel](r, ent)}, com área construída até ${num(r.tolerancia_area * 100)}% diferente de ${num(ent.area, ent.area % 1 ? 1 : 0)} m²${r.area_ampliada ? " (ampliamos a tolerância porque havia poucas vendas na tolerância menor)" : ""}.`),
        h("li", {}, `Cada venda foi atualizada pelo preço de ${mesBaseTxt} (último mês completo), pela variação de R$/m² do mesmo bairro — assim uma venda antiga não puxa o preço pra baixo. A venda mais recente usada é de ${ymLabel(r.ultima_venda)}.`),
        h("li", {}, `O número do meio é a mediana dessas vendas, já atualizadas. As vendas parecidas foram de ${brl(r.vendas_minimo)} a ${brl(r.vendas_maximo)} (${r.faixa_nome === "p25_p75" ? "do 25º ao 75º percentil — metade delas" : "da menor à maior, por serem poucas"}).`),
        h("li", {}, `As cores vêm de ${r.precisao_testes.toLocaleString("pt-BR")} testes: tiramos vendas reais do cálculo, estimamos o preço delas só com as outras e vimos quantas fecharam por cada valor. Verde = pelo menos ${Math.round(DADOS.parametros.veredito_verde * 10)} em cada 10 vendas parecidas chegaram àquele preço; amarelo = de ${Math.round(DADOS.parametros.veredito_amarelo * 100)} a ${Math.round(DADOS.parametros.veredito_verde * 100)} em cada 100; vermelho = menos de ${Math.round(DADOS.parametros.veredito_amarelo * 100)} em cada 100. Preço de apartamento varia por acabamento, vista e estado — coisas que o ITBI não mostra.`),
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

    // vendas parecidas: cada uma levada para a metragem (e o andar) informados, pra poder comparar com a estimativa e com o pedido
    const vs = DADOS.vendas;
    const areaTxt = `${num(ent.area, ent.area % 1 ? 1 : 0)} m²`;
    const FLAG = { "-1": "abaixo do padrão", "1": "acima do padrão" };
    const linhasV = r.similares.map((i, k) => {
      const v = vs[i], p = DADOS.predios[v[0]];
      const igual = Math.abs(v[3] - ent.area) / ent.area <= 0.03;
      const flag = r.similares_flag[k];
      return { atipica: flag !== 0, cels: [ymLabel(v[1]), v[0] === ent.predio ? "mesmo prédio" : p[1], v[4] != null ? `${v[4]}º` : "—",
        h("span", {}, `${num(v[3], v[3] % 1 ? 1 : 0)} m²`, igual ? h("span", { class: "calc-tag-igual" }, "igual") : null),
        brl(v[2]), brl(arred(v[2] * v[6])), `R$ ${num(arred(v[2] * v[6] / v[3]))}`,
        h("span", {}, h("b", {}, brl(r.similares_eq[k])), flag !== 0 ? h("span", { class: `calc-tag-atipica ${flag < 0 ? "baixa" : "alta"}` }, FLAG[String(flag)]) : null),
        v[5] != null ? String(v[5]) : "—"] };
    });
    const nAtip = r.similares_flag.filter((f) => f !== 0).length;
    out.append(h("section", { class: "card" }, h("h2", {}, "Vendas parecidas (ITBI)"),
      h("div", { class: "card-sub" }, `${linhasV.length === r.n ? `As ${r.n} vendas usadas no cálculo` : `As ${linhasV.length} mais parecidas entre as ${r.n} usadas no cálculo`} — valor realmente registrado na guia de ITBI, em ordem de semelhança com o seu apartamento. Como as metragens podem ser diferentes, a última coluna leva cada venda para ${areaTxt} (valor atualizado para ${mesBaseTxt}, R$/m² × ${areaTxt}, com ajuste de andar): é ela que se compara com a estimativa e com o pedido. O andar é estimado pelo número do apartamento (ex.: apto 152 = 15º); “Vagas” só aparece quando está escrita no complemento.`),
      h("div", { class: "table-scroll" }, h("table", { class: "data-table calc-tabela-vendas" },
        h("thead", {}, h("tr", {}, ["Mês da venda", "Onde", "Andar", "Área construída", "Valor pago", "Atualizado", "R$/m²", `Equivale a ${areaTxt}`, "Vagas"].map((c) => h("th", {}, c)))),
        h("tbody", {}, linhasV.map((l) => h("tr", { class: l.atipica ? "calc-linha-atipica" : "" }, l.cels.map((c) => h("td", {}, c))))))),
      nAtip ? h("p", { class: "calc-ajuda calc-nota-atipica" }, `${nAtip === 1 ? "A venda marcada" : `As ${nAtip} vendas marcadas`} “fora do padrão” ficou entre os 10% mais baixos ou mais altos preços que vendas parecidas costumam ter. Pode ser acabamento, estado ou condições diferentes das demais, ou valor declarado diferente do real. Entram no cálculo, mas a mediana não é puxada por elas.`) : null));

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

    // resumo para copiar (acompanha o pedido do simulador)
    nAnuncios = anuncios.length;
    resumoPre = h("pre", { class: "calc-resumo" }, montarResumo(ent, r, nAnuncios));
    const copiar = h("button", { type: "button", class: "calc-botao calc-botao-sec", onclick: async () => {
      try { await navigator.clipboard.writeText(resumoPre.textContent); copiar.textContent = "Resumo copiado ✓"; } catch (e) { copiar.textContent = "Não consegui copiar — selecione o texto abaixo"; }
      setTimeout(() => { copiar.textContent = "Copiar resumo"; }, 2500);
    } }, "Copiar resumo");
    out.append(h("section", { class: "card" }, h("h2", {}, "Resumo para conversar com o proprietário"), resumoPre, copiar));
    definir(ent.preco_pedido || null, "inicio");   // pinta régua e veredito com o pedido do formulário (ou vazio)
    mostrarBotaoRelatorio(true);
    if (FORM) FORM.recolher(ent);   // resultado primeiro: o formulário vira uma linha-resumo
    document.getElementById("calc-card").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function montarResumo(ent, r, nAnuncios) {
    const s = ESTADO.local;
    const mesBase = DADOS.mes_base.split("-").map(Number);
    const linhas = [
      `Estimativa de preço — ${s.rotulo} (${s.bairroNome})`,
      `Apartamento${ent.andar != null ? `, ${ent.andar}º andar` : ""}, ${ent.area_util ? `${num(ent.area_util, ent.area_util % 1 ? 1 : 0)} m² úteis` : `${num(ent.area, ent.area % 1 ? 1 : 0)} m² de área construída`}${ent.area_util ? ` (área do cadastro ${ent.area_origem === "util_estimada" ? "estimada em" : "usada:"} ${num(ent.area, ent.area % 1 ? 1 : 0)} m²)` : ""}.`,
      `Valor estimado: cerca de ${brl(r.estimativa)}.`,
      `Base: ${r.n} vendas parecidas ${r.nivel.startsWith("predio") ? "no mesmo prédio" : r.nivel === "rua" ? "na mesma rua" : "no bairro"}, valores de guias de ITBI atualizados para ${MESES[mesBase[1] - 1]}/${mesBase[0]}. ${CONF_TEXTO[r.confianca][0]}.`,
    ];
    if (r.nivel === "predio_poucas") linhas.push(`Atenção: só ${r.n} ${r.n === 1 ? "venda parecida" : "vendas parecidas"} no prédio${r.segunda_opiniao ? `; ${r.segunda_opiniao.nivel === "rua" ? "pela rua" : "pelo bairro"} a estimativa seria ${brl(r.segunda_opiniao.estimativa)}` : ""}.`);
    linhas.push(`Para anunciar: até ${brl(r.teto_verde)} (preço de mercado). Acima de ${brl(r.teto_amarelo)}, fora do mercado.`);
    if (r.veredito) linhas.push(`Preço pretendido de ${brl(ent.preco_pedido)}: ${VEREDITO[r.veredito][0].toLowerCase()} — ${em100(r.pedido_chegaram_pct, r.pedido_alem_dos_testes)} vendas parecidas chegaram a esse valor (${r.pedido_vs_estimativa_pct > 0 ? "+" : ""}${num(r.pedido_vs_estimativa_pct, 1)}% sobre a estimativa).`);
    linhas.push(`As faixas vêm de testes com vendas reais: verde = pelo menos ${Math.round(DADOS.parametros.veredito_verde * 10)} em cada 10 vendas parecidas chegaram àquele preço.`);
    if (nAnuncios) linhas.push(`Há ${nAnuncios} anúncio(s) parecido(s) à venda hoje na rede.`);
    linhas.push("Acabamento, reforma, vista e estado do prédio não entram no cálculo e podem mudar o valor.");
    return linhas.join("\n");
  }

  // ---- relatório em PDF ("Baixar precificação") -------------------------------------------------------------------
  // Uma página A4, em linguagem simples, para mostrar ao proprietário: preço sugerido, régua do mercado (com o pedido,
  // se houver), gráfico das vendas reais usadas e a confiança. Sai da conta que está na tela (inclui o preço testado no
  // simulador). A impressão esconde o resto da página (ver "Relatório de precificação" em styles.css).
  let RELATORIO = null;

  function mostrarBotaoRelatorio(on) {
    const b = document.querySelector('.panel[data-panel="calculadora"] .page-pdf-btn');
    if (b) b.hidden = !on;
  }

  const mil = (v) => v >= 1e6 ? `R$ ${(v / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} milhões` : `R$ ${num(Math.round(v / 1000))} mil`;

  // Gráfico das vendas reais usadas: o preço fica na horizontal, em faixas verde/amarela/vermelha iguais às da régua; cada ponto é uma
  // venda (já levada para a metragem informada e para o preço de hoje). Pontos de preço parecido se empilham em vez de se sobrepor,
  // e não há texto em cima dos pontos (só a escala embaixo) — com 10+ vendas o texto colado nos pontos virava uma confusão.
  function svgVendas(ent, r) {
    const vs = DADOS.vendas, W = 702, mE = 16, mD = 16, pw = W - mE - mD, R = 6.5, passo = 15;
    const pts = r.similares.slice(0, 12).map((i, k) => ({ v: vs[i], eq: r.similares_eq[k], flag: r.similares_flag[k] })).sort((a, b) => a.eq - b.eq);
    const pedido = ent.preco_pedido || null, corretor = paraNumero(ESTADO.corretor);
    const x0 = Math.min(...pts.map((p) => p.eq), r.piso_mercado, corretor || Infinity) * 0.9;
    const x1 = Math.max(...pts.map((p) => p.eq), r.teto_amarelo * 1.1, (pedido || 0) * 1.05, (corretor || 0) * 1.05);
    const X = (v) => mE + ((v - x0) / (x1 - x0)) * pw;
    const cor = (v) => v <= r.teto_verde ? "#1f9d55" : v <= r.teto_amarelo ? "#d99a1c" : "#c0392b";
    // empilha: cada ponto sobe/desce para a primeira "linha" livre perto dele
    const linhas = [];
    const desloc = [0, -1, 1, -2, 2, -3, 3];
    pts.forEach((p) => {
      p.x = X(p.eq);
      p.l = desloc.find((d) => !linhas.some((q) => q.l === d && Math.abs(q.x - p.x) < 2 * R + 2));
      linhas.push(p);
    });
    const alto = Math.max(...pts.map((p) => Math.abs(p.l)));
    const topoLinhas = 52, cy = topoLinhas + 6 + alto * passo + R, areaH = (alto * 2 + 1) * passo + 14, yAxis = topoLinhas + areaH, H = yAxis + 30;
    const f = (n) => n.toFixed(1);
    const faixa = (de, ate, c) => `<rect x="${f(X(Math.max(de, x0)))}" y="${topoLinhas}" width="${f(X(Math.min(ate, x1)) - X(Math.max(de, x0)))}" height="${areaH}" fill="${c}"/>`;
    const halo = 'stroke="#fff" stroke-width="3.5" stroke-linejoin="round" paint-order="stroke"';
    const vert = (v, c, dash, w) => `<line x1="${f(X(v))}" x2="${f(X(v))}" y1="${topoLinhas - 4}" y2="${yAxis}" stroke="${c}" stroke-width="${w}" ${dash ? `stroke-dasharray="${dash}"` : ""}/>`;
    const rot = (v, linha, c, txt) => { const x = X(v), esq = x > W - 130; return `<text x="${f(x + (esq ? -5 : 5))}" y="${topoLinhas - 8 - linha * 14}" text-anchor="${esq ? "end" : "start"}" font-size="10.5" font-weight="700" fill="${c}" ${halo}>${txt}</text>`; };
    // escala (R$ mil) embaixo
    const passos = [10, 20, 25, 50, 100, 200, 250, 500];
    const faixaMil = (x1 - x0) / 1000, pm = passos.find((q) => faixaMil / q <= 8) || 500;
    let escala = `<line x1="${mE}" x2="${mE + pw}" y1="${yAxis}" y2="${yAxis}" stroke="#9aa3a8" stroke-width="1"/>`;
    for (let m = Math.ceil(x0 / 1000 / pm) * pm; m * 1000 <= x1; m += pm) {
      const x = X(m * 1000);
      escala += `<line x1="${f(x)}" x2="${f(x)}" y1="${yAxis}" y2="${yAxis + 4}" stroke="#9aa3a8"/><text x="${f(x)}" y="${yAxis + 17}" text-anchor="middle" font-size="10" fill="#646c71">R$ ${num(m)} mil</text>`;
    }
    const pontos = pts.map((p) => `<circle cx="${f(p.x)}" cy="${f(cy + p.l * passo)}" r="${R}" fill="${p.flag !== 0 ? "#fff" : cor(p.eq)}" stroke="${cor(p.eq)}" stroke-width="2.4"/>`).join("");
    return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${f(H)}" xmlns="http://www.w3.org/2000/svg" font-family="Inter, sans-serif">`
      + faixa(x0, r.teto_verde, "#e3f4ea") + faixa(r.teto_verde, r.teto_amarelo, "#fdf1d3") + faixa(r.teto_amarelo, x1, "#f8dcd8")
      + vert(r.estimativa, "#1d2226", "6 4", 1.6) + (pedido ? vert(pedido, "#8a5a00", "", 2.4) : "") + (corretor ? vert(corretor, "#00739a", "2 3", 2) : "")
      + pontos + escala
      + rot(r.estimativa, 0, "#1d2226", `Estimativa ${mil(r.estimativa)}`)
      + (pedido ? rot(pedido, 1, "#8a5a00", `Pedido ${mil(pedido)}`) : "")
      + (corretor ? rot(corretor, pedido ? 2 : 1, "#00739a", `Pedida sugerida ${mil(corretor)}`) : "")
      + `</svg>`;
  }

  function montarRelatorio(ent, r) {
    const s = ESTADO.local, p = DADOS.parametros;
    const mb = DADOS.mes_base.split("-").map(Number), mesBaseTxt = `${MESES[mb[1] - 1]}/${mb[0]}`;
    const [confNome] = CONF_TEXTO[r.confianca];
    const pedido = ent.preco_pedido || null;
    const metragem = ent.area_util ? `${num(ent.area_util, ent.area_util % 1 ? 1 : 0)} m² úteis` : `${num(ent.area, ent.area % 1 ? 1 : 0)} m² (metragem do cadastro)`;
    const hoje = new Date().toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", year: "numeric" });
    const [vt, vc, vx] = pedido && r.veredito ? VEREDITO[r.veredito] : [];
    const nPontos = Math.min(12, r.similares.length);
    const corretor = paraNumero(ESTADO.corretor);
    const zonaCorretor = !corretor ? null : corretor <= r.teto_verde ? ["Dentro do preço de mercado", "verde"] : corretor <= r.teto_amarelo ? ["Acima do mercado: exige negociação", "amarelo"] : ["Fora do mercado", "vermelho"];
    const usados = r.similares.slice(0, 12).map((i, k) => ({ eq: r.similares_eq[k], flag: r.similares_flag[k] }));
    const nz = (f) => usados.filter((u) => f(u.eq)).length;
    const nVerde = nz((v) => v <= r.teto_verde), nAmarelo = nz((v) => v > r.teto_verde && v <= r.teto_amarelo), nVermelho = nz((v) => v > r.teto_amarelo), nFora = usados.filter((u) => u.flag !== 0).length;
    const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
    const base = r.nivel.startsWith("predio") ? "no mesmo prédio" : r.nivel === "rua" ? "na mesma rua" : `no bairro ${DADOS.bairros[ent.bairro]}`;
    const verde = Math.round(p.veredito_verde * 100), amarelo = Math.round(p.veredito_amarelo * 100);
    const lo = Math.min(r.piso_mercado, pedido || Infinity) * 0.97, hi = Math.max(r.teto_amarelo * 1.12, (pedido || 0) * 1.04);
    const pos = (v) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)).toFixed(2)}%`;
    const regua = h("div", { class: "rel-regua" },
      h("div", { class: "rel-z verde", style: `left:0;width:${pos(r.teto_verde)}` }),
      h("div", { class: "rel-z amarelo", style: `left:${pos(r.teto_verde)};width:calc(${pos(r.teto_amarelo)} - ${pos(r.teto_verde)})` }),
      h("div", { class: "rel-z vermelho", style: `left:${pos(r.teto_amarelo)};right:0` }),
      h("div", { class: "rel-pin", style: `left:${pos(r.teto_verde)}` }, h("span", {}, mil(r.teto_verde))),
      h("div", { class: "rel-pin", style: `left:${pos(r.teto_amarelo)}` }, h("span", {}, mil(r.teto_amarelo))),
      pedido ? h("div", { class: `rel-pin rel-pedido ${r.veredito}`, style: `left:${pos(pedido)}` }, h("span", {}, `PEDIDO ${mil(pedido)}`)) : null);
    const e = h("div", { class: "rel-pagina" },
      h("div", { class: "rel-topo" },
        h("div", { class: "rel-marca" }, h("img", { src: "logo-topio-t.png", alt: "" }), h("div", {}, h("b", {}, "Paulo Credidio"), h("span", {}, "by Topio imóveis"))),
        h("div", { class: "rel-data" }, "Precificação de imóvel", h("br"), `Dados de ${mesBaseTxt} · gerado em ${hoje}`)),
      h("div", { class: "rel-hero" + (corretor ? " dois" : "") },
        h("div", { class: "rel-end" }, h("div", { class: "rel-eyebrow" }, `Apartamento · ${s.bairroNome}`), h("h1", {}, s.rotulo),
          h("p", {}, `${ent.andar != null ? `${ent.andar}º andar · ` : ""}${metragem}`)),
        h("div", { class: "rel-preco" }, h("small", {}, corretor ? "Preço sugerido pela calculadora" : "Preço sugerido de venda"), h("div", { class: "rel-big" }, mil(r.estimativa)),
          h("p", {}, "Faixa provável: ", h("b", {}, `${mil(r.minimo)} a ${mil(r.maximo)}`))),
        corretor ? h("div", { class: "rel-corretor" }, h("small", {}, "Pedida sugerida pelo corretor"), h("div", { class: "rel-big" }, mil(corretor)),
          h("p", {}, h("span", { class: `rel-ponto ${zonaCorretor[1]}` }), h("b", {}, zonaCorretor[0]))) : null),
      h("section", { class: "rel-sec" },
        h("h2", {}, pedido ? "Onde o preço pedido cai no mercado?" : "Até quanto vale anunciar?"),
        h("div", { class: "rel-sub" }, `Comparamos com vendas reais de apartamentos parecidos, já atualizadas para o preço de ${mesBaseTxt}.`),
        regua,
        h("div", { class: "rel-leg" },
          h("div", { class: "verde" }, h("b", {}, `Até ${mil(r.teto_verde)}`), `Preço de mercado. ${Math.round(p.veredito_verde * 10)} ou mais em cada 10 vendas parecidas chegaram a esse valor.`),
          h("div", { class: "amarelo" }, h("b", {}, `${mil(r.teto_verde)} a ${mil(r.teto_amarelo)}`), `Acima do mercado. De ${amarelo} a ${verde} em cada 100 chegaram: exige negociação.`),
          h("div", { class: "vermelho" }, h("b", {}, `Acima de ${mil(r.teto_amarelo)}`), `Fora do mercado. Menos de ${amarelo} em cada 100 chegaram.`)),
        pedido && r.veredito ? h("div", { class: `rel-veredito ${r.veredito}` },
          h("div", { class: "rel-big2" }, vt === "Acima do mercado" ? "Pedido acima do mercado" : vt === "Abaixo do mercado" ? "Pedido abaixo do mercado" : vt === "Fora do mercado" ? "Pedido fora do mercado" : "Pedido no preço de mercado"),
          h("p", {}, `${em100(r.pedido_chegaram_pct, r.pedido_alem_dos_testes)} vendas parecidas chegaram a ${mil(pedido)} ou mais. ${vx}`
            + (r.pedido_acima_do_verde > 0 ? ` Para entrar no preço de mercado, o pedido precisaria ficar em até ${mil(r.teto_verde)}.` : ""))) : null),
      h("section", { class: "rel-sec" },
        h("h2", {}, "Vendas reais usadas na conta"),
        h("div", { class: "rel-sub" }, `${nPontos === r.n ? `As ${r.n} vendas` : `As ${nPontos} mais parecidas entre as ${r.n} vendas`} ${base}, cada uma já levada para ${num(ent.area, ent.area % 1 ? 1 : 0)} m² de cadastro e para o preço de ${mesBaseTxt}. Cada ponto é uma venda: quanto mais à direita, mais cara; a cor mostra a faixa em que ela ficou.`),
        h("div", { class: "rel-grafico", html: svgVendas(ent, r) }),
        h("div", { class: "rel-legpts" },
          h("span", {}, h("i", { class: "verde" }), plural(nVerde, "venda no preço de mercado", "vendas no preço de mercado")),
          h("span", {}, h("i", { class: "amarelo" }), plural(nAmarelo, "venda acima do mercado", "vendas acima do mercado")),
          h("span", {}, h("i", { class: "vermelho" }), plural(nVermelho, "venda fora do mercado", "vendas fora do mercado")),
          nFora ? h("span", {}, h("i", { class: "vazio" }), plural(nFora, "venda fora do padrão", "vendas fora do padrão")) : null)),
      h("section", { class: "rel-conf" },
        h("b", {}, `${confNome}. `),
        `Em ${r.precisao_testes.toLocaleString("pt-BR")} testes com vendas que já aconteceram, em casos como este o erro típico foi de cerca de ${num(r.precisao_mediana_pct, 0)}%.`,
        r.area_estimada_pela_util ? " A metragem do cadastro foi estimada a partir da área útil, então a estimativa é menos firme." : "",
        r.nivel === "predio_poucas" ? ` Só ${r.n} ${r.n === 1 ? "venda parecida" : "vendas parecidas"} no prédio: use com cautela.` : ""),
      h("div", { class: "rel-rodape" }, "Estimativa feita com guias de ITBI de revenda (valor realmente pago), atualizadas pela variação de preço do bairro. Acabamento, reforma, vista e estado do prédio não entram na conta e podem mudar o valor. Não é laudo de avaliação. Paulo Credidio · by Topio imóveis."));
    return e;
  }

  function baixarRelatorio() {
    if (!RELATORIO) return;
    const { ent, r } = RELATORIO;
    let caixa = document.getElementById("relatorio-precificacao");
    if (!caixa) { caixa = h("div", { id: "relatorio-precificacao" }); document.body.appendChild(caixa); }
    caixa.replaceChildren(montarRelatorio(ent, r));
    const tituloAntes = document.title;
    const nome = ESTADO.local.rotulo.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
    document.title = `precificacao_${nome}_${new Date().toISOString().slice(0, 10)}`;
    document.body.classList.add("imprimindo-relatorio");
    const limpar = () => { document.body.classList.remove("imprimindo-relatorio"); document.title = tituloAntes; caixa.replaceChildren(); window.removeEventListener("afterprint", limpar); };
    window.addEventListener("afterprint", limpar);
    // espera o logo carregar (e a fonte) antes de abrir a impressão
    const logo = caixa.querySelector("img");
    const abrir = () => setTimeout(() => window.print(), 150);
    if (logo && !logo.complete) { logo.addEventListener("load", abrir, { once: true }); logo.addEventListener("error", abrir, { once: true }); } else abrir();
  }
  window.calcBaixarRelatorio = baixarRelatorio;
  window.__calcUltimaEntrada = () => (RELATORIO ? RELATORIO.ent : null);   // só para o teste scripts/testar_relatorio.py
  window.calcMontarRelatorioParaTeste = () => (RELATORIO ? (() => { const c = document.getElementById("relatorio-precificacao") || document.body.appendChild(h("div", { id: "relatorio-precificacao" })); c.replaceChildren(montarRelatorio(RELATORIO.ent, RELATORIO.r)); return c; })() : null);

  function calcular() {
    resolverPeloApto();
    const ent = entradaDoFormulario();
    if (!ent) return;
    renderResultado(ent, estimar(DADOS, IDX, ent));
  }

  // Resumo de uma linha + "Mais" com a explicação completa (mesmo jeito das outras seções do painel).
  function calcResumo(explicacao) {
    const botao = h("button", { type: "button", class: "mais-btn", "aria-expanded": "false" }, "Mais");
    botao.addEventListener("click", () => {
      const aberto = explicacao.classList.toggle("recolhido") === false;
      botao.setAttribute("aria-expanded", String(aberto));
      botao.textContent = aberto ? "Menos" : "Mais";
    });
    return h("div", {}, h("div", { class: "card-resumo" }, h("span", { class: "card-resumo-texto" }, "Estima por quanto vende um apartamento, com base no que já foi pago de verdade no mesmo prédio, na rua ou no bairro."), botao), explicacao);
  }

  function montar() {
    root.replaceChildren();
    const form = renderFormulario();
    const corpo = h("div", { id: "calc-corpo-form" },
      calcResumo(h("div", { class: "card-sub recolhido" }, `Estimativa de venda com base no que foi realmente pago: guias de ITBI de revenda (compra e venda, 100% do imóvel, valor dentro do padrão — a mesma camada limpa do resto do painel), atualizadas para o preço de ${DADOS.mes_base.split("-").reverse().join("/")} pela variação de R$/m² de cada bairro. ${num(DADOS.resumo.vendas)} vendas em ${num(DADOS.resumo.predios)} prédios dos 77 bairros da carteira. Compara primeiro com o próprio prédio, depois com a rua, depois com o bairro — e diz qual dos três usou e quão confiável é.`)),
      form);
    const barra = h("div", { class: "calc-barra-resumo", id: "calc-barra-resumo", hidden: true });
    root.append(h("section", { class: "card", id: "calc-card" }, h("h2", {}, "Calculadora de preço de apartamento"), barra, corpo), h("div", { id: "calc-resultado" }));
    // Depois de calcular, o formulário vira uma linha-resumo ("Editar" reabre, tudo preenchido) e o resultado fica logo abaixo, no topo da tela.
    FORM = {
      recolher(ent) {
        const s = ESTADO.local;
        const partes = [s.bairroNome, paraNumero(ESTADO.apto) != null ? `apto ${ESTADO.apto}` : null, ent.andar != null ? `${ent.andar}º andar` : null,
          ent.area_util ? `${num(ent.area_util, ent.area_util % 1 ? 1 : 0)} m² úteis` : null,
          `${ent.area_origem === "util_estimada" ? "cadastro estimado em " : "cadastro "}${num(ent.area, ent.area % 1 ? 1 : 0)} m²`].filter(Boolean);
        barra.replaceChildren(
          h("div", { class: "calc-barra-resumo-texto" }, h("b", {}, s.rotulo), h("span", { class: "calc-ajuda" }, partes.join(" · "))),
          h("div", { class: "calc-barra-resumo-acoes" },
            h("button", { type: "button", class: "calc-botao calc-botao-sec", id: "calc-editar", onclick: () => FORM.expandir() }, "Editar"),
            h("button", { type: "button", class: "calc-link", onclick: limpar }, "Nova consulta")));
        barra.hidden = false;
        corpo.hidden = true;
      },
      expandir() {
        corpo.hidden = false;
        barra.hidden = true;
        corpo.scrollIntoView({ behavior: "smooth", block: "start" });
      },
    };
    form.renderLocalEscolhido();
    if (ESTADO.local) { document.getElementById("calc-endereco").value = ESTADO.local.rotulo; }
    atualizarMetragem();
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
