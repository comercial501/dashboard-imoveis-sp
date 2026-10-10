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
      _ids: sel,
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
    const q = t ? t.q : null;
    const ids = res._ids; delete res._ids;
    if (q && q.length === QTS.length) {
      // Escada de preços: quantas vendas parecidas chegaram a cada preço (erro medido nos testes com vendas reais).
      res.escada = ESCADA.map((pp) => [100 - pp, arred(est * interp(QTS, q, pp))]);
      res.teto_verde = arred(est * interp(QTS, q, 100 - p.veredito_verde * 100));
      res.teto_amarelo = arred(est * interp(QTS, q, 100 - p.veredito_amarelo * 100));
      res.piso_mercado = res.escada[0][1];
      const vs = dados.vendas;
      const valores = ids.map((i) => vs[i][2] * vs[i][6]);
      res.maior_venda = arred(Math.max(...valores));
      const pedido = entrada.preco_pedido;
      if (pedido) {
        const x = pedido / est;
        const chegaram = 1 - interp(q, QTS, x) / 100;
        let veredito;
        if (chegaram >= p.veredito_abaixo) veredito = "abaixo";
        else if (chegaram >= p.veredito_verde) veredito = "dentro";
        else if (chegaram >= p.veredito_amarelo) veredito = "alto";
        else veredito = "fora";
        res.veredito = veredito;
        res.pedido_chegaram_pct = arred(chegaram * 100);
        res.pedido_alem_dos_testes = x >= q[q.length - 1];
        res.pedido_vs_estimativa_pct = Math.round((x - 1) * 100 * 10) / 10;
        res.pedido_n_chegaram = valores.filter((v) => v >= pedido).length;
        res.pedido_acima_do_verde = Math.max(0, pedido - res.teto_verde);
      }
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

  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/[^A-Z0-9]+/g, " ").trim();
  const numeroDoEndereco = (addrKey) => String((addrKey.split("|")[1] || "")).replace(/^0+(?=\d)/, "");

  let DADOS = null, IDX = null, BUSCA = null;
  const ESTADO = { local: null, apto: "", andar: "", andarAuto: false, area: "", areaAuto: false, areaNota: "", areaUtil: "", quartos: "", banheiros: "", suites: "", vagas: "", condominio: "", iptu: "", pedido: "" };

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
        out.push({ tipo: "rua", predio: null, rua: r.i, bairro: r.bairro, rotulo: `${bonito(r.nome)}, ${numero}`, bairroNome: DADOS.bairros[r.bairro], semVendas: true });
      }
    }
    if (numero === null && out.length) {
      out.sort((a, b) => a.rotulo.localeCompare(b.rotulo, "pt-BR", { numeric: true }));
    }
    return out;
  }

  // botões com as metragens do cadastro vendidas no prédio; `recalcular` refaz o cálculo ao tocar
  function chipsMetragem(ms, recalcular) {
    const box = h("span", { class: "calc-chips" });
    ms.forEach((m) => box.append(h("button", { type: "button", class: "calc-chip", onclick: () => {
      ESTADO.area = String(m.area); ESTADO.areaAuto = false; ESTADO.areaNota = "";
      const inp = document.getElementById("calc-area"); if (inp) inp.value = ESTADO.area;
      const nota = document.getElementById("calc-area-nota"); if (nota) nota.textContent = "";
      if (recalcular) calcular();
    } }, `${m.area} m² · ${m.n} ${m.n === 1 ? "venda" : "vendas"}`)));
    return box;
  }

  // número do apartamento (ex.: 152) -> andar (15) e, pelo "final" (2), a metragem do cadastro da mesma planta neste prédio
  function resolverPeloApto() {
    const s = ESTADO.local;
    const nota = document.getElementById("calc-area-nota");
    const n = paraNumero(ESTADO.apto);
    ESTADO.areaNota = "";
    if (s && s.predio != null && n != null && n >= 10 && Math.round(n) === n) {
      const conv = DADOS.predios[s.predio][4] || "d";
      const [andar, final] = andarEFinal(n, conv);
      if (andar === null) ESTADO.areaNota = "Não consegui ler o andar deste número de apartamento.";
      else {
        if (ESTADO.andar === "" || ESTADO.andarAuto) { ESTADO.andar = String(andar); ESTADO.andarAuto = true; }
        const cont = {};
        for (const i of (IDX.predio[s.predio] || [])) {
          const v = DADOS.vendas[i];
          if (v[8] === final) { const a = Math.round(v[3]); cont[a] = (cont[a] || 0) + 1; }
        }
        const achadas = Object.entries(cont).map(([a, c]) => ({ area: Number(a), n: c })).sort((x, y) => y.n - x.n || x.area - y.area);
        if (achadas.length && (ESTADO.area === "" || ESTADO.areaAuto)) {
          ESTADO.area = String(achadas[0].area); ESTADO.areaAuto = true;
          ESTADO.areaNota = `Pelo número do apartamento (final ${final}), a metragem do cadastro neste prédio é ${achadas[0].area} m² (${achadas[0].n} ${achadas[0].n === 1 ? "venda" : "vendas"} do mesmo final).`;
        } else if (!achadas.length) {
          ESTADO.areaNota = `Este prédio não tem venda registrada com o final ${final}: escolha a metragem do cadastro abaixo, ou digite a área do carnê do IPTU.`;
        }
      }
    }
    const ia = document.getElementById("calc-andar"), im = document.getElementById("calc-area");
    if (ia) ia.value = ESTADO.andar;
    if (im) im.value = ESTADO.area;
    if (nota) nota.textContent = ESTADO.areaNota;
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
    inp.addEventListener("input", () => {
      ESTADO[opts.chave] = inp.value;
      if (opts.chave === "area") ESTADO.areaAuto = false;      // digitou na mão: não sobrescreve mais pelo número do apartamento
      if (opts.chave === "andar") ESTADO.andarAuto = false;
      if (opts.chave === "apto") resolverPeloApto();
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
    const zerarImovel = () => Object.assign(ESTADO, { apto: "", andar: "", andarAuto: false, area: "", areaAuto: false, areaNota: "", areaUtil: "" });
    const escolher = (s) => {
      const antes = ESTADO.local;
      if (antes && (antes.predio !== s.predio || antes.rua !== s.rua || antes.bairro !== s.bairro)) zerarImovel(); // outro endereço: andar, metragem etc. do anterior não valem
      ESTADO.local = s;
      fechar();
      renderLocalEscolhido();
      renderMetragens();
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

    // 2. o imóvel
    const metragens = h("div", { class: "calc-metragens", id: "calc-metragens" });
    function renderMetragens() {
      metragens.replaceChildren();
      const s = ESTADO.local;
      if (!s || s.predio == null) return;
      const ms = metragensDoPredio(s.predio);
      if (!ms.length) return;
      metragens.append(h("span", { class: "calc-ajuda" }, "Metragens do cadastro que já foram vendidas neste prédio (toque para usar): "), chipsMetragem(ms, false));
    }
    form.append(h("div", { class: "calc-passo" },
      h("div", { class: "calc-passo-titulo" }, "2. Qual é o apartamento?"),
      h("div", { class: "calc-tipo" }, h("span", { class: "calc-chip ativo", "aria-current": "true" }, "Apartamento"), h("span", { class: "calc-ajuda" }, "Casas, studios e coberturas: ainda não nesta calculadora.")),
      h("div", { class: "calc-grade" },
        campoNumero("calc-apto", "Número do apartamento — opcional", "Ex.: 152. Eu descubro o andar e a metragem do cadastro pelo número", { chave: "apto", min: 0, max: 9999, placeholder: "Ex.: 152" }),
        campoNumero("calc-andar", "Andar", "Só o número (preenchido sozinho se você informar o apartamento)", { chave: "andar", min: 0, max: 60, placeholder: "Ex.: 15" }),
        campoNumero("calc-area", "Área construída (m²) — do carnê do IPTU", "Não é a área útil (a do cadastro é bem maior). Sem o carnê, use o número do apartamento", { chave: "area", min: 10, max: 2000, step: "any", decimal: true, placeholder: "Ex.: 140" }),
        campoNumero("calc-area-util", "Área útil (m²) — opcional", "A da planta. Só para mostrar o R$/m² útil e achar anúncios parecidos", { chave: "areaUtil", min: 10, max: 2000, step: "any", decimal: true, placeholder: "Ex.: 110" })),
      h("div", { class: "calc-ajuda calc-nota-area", id: "calc-area-nota" }, ESTADO.areaNota), metragens));

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
    Object.assign(ESTADO, { local: null, apto: "", andar: "", andarAuto: false, area: "", areaAuto: false, areaNota: "", areaUtil: "", quartos: "", banheiros: "", suites: "", vagas: "", condominio: "", iptu: "", pedido: "" });
    montar();
  }

  function entradaDoFormulario() {
    const s = ESTADO.local;
    if (!s) { erro("Escolha o endereço na lista que aparece quando você digita."); return null; }
    const area = paraNumero(ESTADO.area);
    if (!area || area < 10 || area > 2000) {
      const util = paraNumero(ESTADO.areaUtil);
      erro(util
        ? "Você preencheu só a área útil. O cálculo precisa da área construída do cadastro (carnê do IPTU), que costuma ser bem maior — nos apartamentos que conseguimos conferir, entre 1,4 e 1,9 vez a útil, e varia de prédio para prédio. Informe o número do apartamento ou toque numa das metragens do prédio."
        : "Informe a área construída em m² (entre 10 e 2.000) — a do carnê do IPTU — ou o número do apartamento, que eu descubro a metragem do cadastro. Dica: toque numa das metragens já vendidas no prédio.");
      return null;
    }
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
    if (!s || s.predio == null || (r.ok && r.nivel === "predio")) return null;
    const ms = metragensDoPredio(s.predio);
    if (!ms.length) return null;
    return h("section", { class: "card calc-aviso-area" }, h("h3", {}, "Confira a metragem"),
      h("p", {}, `Neste prédio ninguém vendeu um apartamento com área do cadastro perto de ${num(ent.area, ent.area % 1 ? 1 : 0)} m² — as vendas daqui foram de ${ms.map((m) => `${m.area} m²`).join(", ")}. `,
        r.ok ? `Por isso a calculadora usou as vendas d${r.nivel === "rua" ? "a rua" : "o bairro"}, que são menos precisas.` : "Por isso não deu para calcular."),
      h("p", { class: "calc-ajuda" }, "Se você digitou a área útil, toque na metragem do cadastro correspondente (a do cadastro é bem maior que a útil) — ou informe o número do apartamento:"),
      chipsMetragem(ms, true));
  }

  function renderResultado(ent, r) {
    const out = document.getElementById("calc-resultado");
    out.replaceChildren();
    const aviso = avisoMetragem(ent, r);
    if (aviso) out.append(aviso);
    if (!r.ok) {
      out.append(h("section", { class: "card" }, h("h2", {}, "Sem estimativa"),
        h("p", {}, "Não há vendas parecidas suficientes (nem no prédio, nem na rua, nem no bairro) para essa metragem. Em vez de chutar um número, a calculadora não responde. Tente conferir a área construída informada."),
        h("p", { class: "muted small" }, "Regra: no prédio precisa de 3+ vendas com área até 20% diferente; na rua, 5+ (até 25%); no bairro, 10+ (até 30%).")));
      return;
    }
    if (r.teto_verde == null) { // arquivo de dados antigo (sem a tabela de preços): pede a próxima atualização
      out.append(h("section", { class: "card" }, h("h2", {}, "Calculadora em atualização"), h("p", {}, "Os dados desta publicação ainda não têm a tabela de preços por faixa. Tente de novo depois da próxima atualização diária (08:00).")));
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
        h("div", { class: "calc-selos" }, h("span", { class: "badge neutral", title: confExpl }, `${confNome} ${PONTOS[r.confianca]}`))),
      h("div", { class: "calc-anunciar" }, h("b", {}, `Para anunciar: até ${brl(r.teto_verde)}`), ` — acima de ${brl(r.teto_amarelo)} o imóvel fica fora do mercado.`),
      renderBarra(r, ent.preco_pedido),
      h("p", { class: "calc-ajuda" }, `Como medimos: em ${r.precisao_testes.toLocaleString("pt-BR")} testes com vendas reais, em casos como este (${NIVEL_CURTO[r.nivel]}, ${confNome.toLowerCase()}), o erro típico foi de ${num(r.precisao_mediana_pct, 0)}%. As cores dizem quantas vendas parecidas chegaram a cada preço. ${confExpl}`),
      h("div", { class: "calc-escada" }, h("div", { class: "calc-rotulo" }, "Por quanto as vendas parecidas fecharam (valores atualizados)"),
        h("div", { class: "calc-escada-grade" }, r.escada.map(([sh, v]) => h("div", { class: "calc-escada-item" }, h("div", { class: "calc-escada-valor" }, brl(v)), h("div", { class: "calc-ajuda" }, `${sh} em cada 100 chegaram a pelo menos isso`))))));

    if (r.veredito) {
      const [vt, vc, vx] = VEREDITO[r.veredito];
      const sinal = r.pedido_vs_estimativa_pct > 0 ? "acima" : "abaixo";
      card.append(h("div", { class: `calc-veredito ${vc}` },
        h("div", { class: "calc-veredito-titulo" }, h("span", { class: "calc-veredito-selo" }, vt.toUpperCase()), h("b", {}, `Pedido de ${brl(ent.preco_pedido)}`)),
        h("div", { class: "calc-veredito-frase" }, `${em100(r.pedido_chegaram_pct, r.pedido_alem_dos_testes)} vendas parecidas chegaram a esse valor ou mais.`.replace(/^./, (c) => c.toUpperCase())),
        h("div", {}, `${vx} O pedido está ${brl(Math.abs(ent.preco_pedido - r.estimativa))} (${num(Math.abs(r.pedido_vs_estimativa_pct), 1)}%) ${sinal} da estimativa de ${brl(r.estimativa)}.`),
        r.pedido_acima_do_verde > 0 ? h("div", {}, h("b", {}, `Para entrar no preço de mercado, o pedido precisaria baixar ${brl(r.pedido_acima_do_verde)} (até ${brl(r.teto_verde)}).`)) : null,
        h("div", {}, `Nas ${r.n} vendas parecidas usadas (${NIVEL_CURTO[r.nivel]}), a mais cara fechou por ${brl(r.maior_venda)} — ${r.pedido_n_chegaram === 0 ? "nenhuma chegou ao pedido" : `${r.pedido_n_chegaram} ${r.pedido_n_chegaram === 1 ? "chegou" : "chegaram"} ao pedido ou mais`}.`),
        r.confianca === "baixa" ? h("div", { class: "calc-ajuda" }, "Como a confiança é baixa (poucas vendas no prédio), o veredito é um indicativo.") : null,
        h("div", { class: "calc-ajuda" }, "A comparação é com o que foi PAGO nas vendas (guias de ITBI), não com preços de anúncio.")));
    }

    const porque = h("div", { class: "calc-porque" },
      h("h3", {}, "Como chegamos nesse número"),
      h("ul", {},
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
      `Valor estimado: cerca de ${brl(r.estimativa)}.`,
      `Base: ${r.n} vendas parecidas ${r.nivel === "predio" ? "no mesmo prédio" : r.nivel === "rua" ? "na mesma rua" : "no bairro"}, valores de guias de ITBI atualizados para ${MESES[mesBase[1] - 1]}/${mesBase[0]}. ${CONF_TEXTO[r.confianca][0]}.`,
    ];
    linhas.push(`Para anunciar: até ${brl(r.teto_verde)} (preço de mercado). Acima de ${brl(r.teto_amarelo)}, fora do mercado.`);
    if (r.veredito) linhas.push(`Preço pretendido de ${brl(ent.preco_pedido)}: ${VEREDITO[r.veredito][0].toLowerCase()} — ${em100(r.pedido_chegaram_pct, r.pedido_alem_dos_testes)} vendas parecidas chegaram a esse valor (${r.pedido_vs_estimativa_pct > 0 ? "+" : ""}${num(r.pedido_vs_estimativa_pct, 1)}% sobre a estimativa).`);
    linhas.push(`As faixas vêm de testes com vendas reais: verde = pelo menos ${Math.round(DADOS.parametros.veredito_verde * 10)} em cada 10 vendas parecidas chegaram àquele preço.`);
    if (nAnuncios) linhas.push(`Há ${nAnuncios} anúncio(s) parecido(s) à venda hoje na rede.`);
    linhas.push("Acabamento, reforma, vista e estado do prédio não entram no cálculo e podem mudar o valor.");
    return linhas.join("\n");
  }

  function calcular() {
    resolverPeloApto();
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
