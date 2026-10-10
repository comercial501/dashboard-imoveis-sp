#!/usr/bin/env python3
"""
Verificação da aba "Calculadora de preço" (uso LOCAL — não roda no GitHub Actions).

1. PARIDADE: gera casos de teste (prédio, rua e bairro, com e sem andar/preço pedido, e casos sem resposta),
   calcula cada um em Python (scripts/calculadora_preco.py) e no navegador (site/calculadora.js) e compara tudo:
   nível, nº de vendas, confiança, estimativa, faixa, vendas parecidas, anúncios parecidos, veredito.
2. TELA: digita um endereço de verdade, escolhe na lista, preenche e calcula; confere o resultado na tela contra o
   Python; testa endereço sem vendas no número, erros de preenchimento, tela de celular sem rolagem pro lado
   e ausência de erro de console.

Uso:
  cd site && python3 serve_no_cache.py 8899 &
  python3 scripts/verificar_calculadora.py [--base http://localhost:8899] [--prints /caminho/para/prints]
Sai com código != 0 se algo divergir.
"""
import argparse
import json
import random
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calculadora_preco as cp

ROOT = Path(__file__).resolve().parent.parent


def gerar_casos(dados, idx, n_cada=80, seed=7):
    rnd = random.Random(seed)
    vendas, predios = dados["vendas"], dados["predios"]
    casos = []
    ids_predios = sorted(idx["predio"])
    ids_ruas = sorted(idx["rua"])
    ids_bairros = sorted(idx["bairro"])

    def andar():
        return rnd.choice([None, None, 0, 1, 2, 3, 5, 9, 12, 15, 18, 25]) or None

    def pedido(est):
        return rnd.choice([None, None, round(est * rnd.choice([0.6, 0.85, 0.95, 1.0, 1.08, 1.3, 1.6]), -3)]) if est else None

    for _ in range(n_cada):  # prédio: metragem de uma venda do próprio prédio, mexida um pouco
        pi = rnd.choice(ids_predios)
        v = vendas[rnd.choice(idx["predio"][pi])]
        area = round(v[3] * rnd.choice([1, 1, 0.97, 1.05, 1.15, 0.85]), 1)
        casos.append({"predio": pi, "rua": predios[pi][3], "bairro": predios[pi][2], "area": area, "andar": andar(), "quartos": rnd.choice([None, 2, 3]), "area_util": rnd.choice([None, round(area * 0.8)])})
    for _ in range(n_cada):  # só a rua (número sem vendas)
        ri = rnd.choice(ids_ruas)
        v = vendas[rnd.choice(idx["rua"][ri])]
        casos.append({"predio": None, "rua": ri, "bairro": predios[v[0]][2], "area": round(v[3] * rnd.choice([1, 0.9, 1.1]), 1), "andar": andar(), "quartos": rnd.choice([None, 1, 3]), "area_util": None})
    for _ in range(n_cada):  # só o bairro
        bi = rnd.choice(ids_bairros)
        v = vendas[rnd.choice(idx["bairro"][bi])]
        casos.append({"predio": None, "rua": None, "bairro": bi, "area": round(v[3] * rnd.choice([1, 0.9, 1.1]), 1), "andar": andar(), "quartos": rnd.choice([None, 2]), "area_util": rnd.choice([None, 90])})
    for _ in range(20):  # metragens absurdas -> sem resposta
        bi = rnd.choice(ids_bairros)
        casos.append({"predio": None, "rua": None, "bairro": bi, "area": rnd.choice([12, 1800, 950]), "andar": None, "quartos": None, "area_util": None})
    for c in casos:
        r = cp.estimar(dados, idx, c)
        c["preco_pedido"] = pedido(r["estimativa"]) if r["ok"] else None
    return casos


JS_CASOS = """(casos)=>{
  const D=window.CALC.dados(); const I=window.CALC.indexar(D);
  return casos.map(c=>{ const r=window.CALC.estimar(D,I,c); const a=r.ok?window.CALC.anunciosParecidos(D,c,r.estimativa):window.CALC.anunciosParecidos(D,c,null); return {r,a}; });
}"""


def comparar(py, js):
    difs = []
    for k in ("ok", "nivel", "n", "confianca", "area_ampliada", "faixa_nome", "estimativa", "minimo", "maximo", "m2", "similares", "ultima_venda", "veredito", "tolerancia_area", "motivo", "vendas_minimo", "vendas_maximo", "margem_pct", "precisao_testes", "precisao_mediana_pct"):
        if py.get(k) != js.get(k):
            difs.append((k, py.get(k), js.get(k)))
    for k in ("razao_p75_p25", "fator_andar", "pedido_vs_estimativa_pct"):  # arredondamento agora é idêntico: sem tolerância
        if py.get(k) != js.get(k):
            difs.append((k, py.get(k), js.get(k)))
    return difs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8899")
    ap.add_argument("--prints", default="/tmp/prints_calculadora")
    args = ap.parse_args()
    prints = Path(args.prints)
    prints.mkdir(parents=True, exist_ok=True)
    dados = json.loads((ROOT / "site" / "calculadora.json").read_text(encoding="utf-8"))
    idx = cp.indexar(dados)
    casos = gerar_casos(dados, idx)
    esperados = []
    for c in casos:
        r = cp.estimar(dados, idx, c)
        esperados.append({"r": r, "a": cp.anuncios_parecidos(dados, c, r["estimativa"] if r["ok"] else None)})
    erros = []
    resultado = {}
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        ctx = br.new_context(viewport={"width": 1366, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: erros.append(str(e)[:200]))
        pg.on("console", lambda m: erros.append(m.text[:200]) if m.type == "error" else None)
        pg.goto(args.base, wait_until="networkidle")
        pg.wait_for_timeout(800)
        pg.evaluate("()=>window.showPanel('calculadora')")
        pg.wait_for_selector("#calc-endereco", timeout=60000)

        # ---- 1. paridade -------------------------------------------------------------------
        obtidos = pg.evaluate(JS_CASOS, casos)
        divergentes, ex = 0, []
        por_nivel = {}
        for c, e, o in zip(casos, esperados, obtidos):
            difs = comparar(e["r"], o["r"])
            if e["a"] != o["a"]:
                difs.append(("anuncios", e["a"], o["a"]))
            if e["r"]["ok"]:
                por_nivel[e["r"]["nivel"]] = por_nivel.get(e["r"]["nivel"], 0) + 1
            else:
                por_nivel["sem_resposta"] = por_nivel.get("sem_resposta", 0) + 1
            if difs:
                divergentes += 1
                if len(ex) < 5:
                    ex.append({"caso": c, "difs": difs[:4]})
        resultado["paridade"] = {"casos": len(casos), "divergencias": divergentes, "por_nivel": por_nivel, "exemplos": ex}

        # ---- 2. tela --------------------------------------------------------------------------
        # prédio com vendas e anúncio no mesmo prédio, pra ver as duas tabelas cheias
        pred_anun = {a[0] for a in dados["anuncios"] if a[0] >= 0}
        cand = [pi for pi in sorted(idx["predio"]) if pi in pred_anun and len(idx["predio"][pi]) >= 6]
        pi = cand[len(cand) // 3]
        nome = dados["predios"][pi][1]
        bairro = dados["bairros"][dados["predios"][pi][2]]
        metragem = max({round(dados["vendas"][i][3]) for i in idx["predio"][pi]}, key=lambda a: sum(1 for i in idx["predio"][pi] if round(dados["vendas"][i][3]) == a))
        tela = {"predio_testado": f"{nome} ({bairro})", "metragem": metragem}
        pg.fill("#calc-endereco", nome.replace(",", ""))
        pg.wait_for_selector(".calc-sugestao", timeout=5000)
        tela["sugestoes"] = pg.evaluate("()=>[...document.querySelectorAll('.calc-sugestao')].map(l=>l.innerText.replace(/\\n/g,' | '))")
        pg.click(".calc-sugestao >> nth=0")
        tela["local_escolhido"] = pg.inner_text(".calc-local-card").replace("\n", " | ")
        tela["chips_metragem"] = pg.evaluate("()=>[...document.querySelectorAll('.calc-metragens .calc-chip')].map(b=>b.textContent)")
        # erro sem área
        pg.click(".calc-botao")
        tela["erro_sem_area"] = pg.inner_text("#calc-erro") if pg.is_visible("#calc-erro") else None
        pg.click(".calc-metragens .calc-chip >> nth=0")
        area_chip = float(pg.input_value("#calc-area"))
        pg.fill("#calc-andar", "15")
        pg.fill("#calc-area-util", str(round(area_chip * 0.8)))
        pg.fill("#calc-quartos", "3")
        pg.fill("#calc-banheiros", "3")
        pg.fill("#calc-suites", "1")
        pg.fill("#calc-vagas", "2")
        pg.fill("#calc-condominio", "2300")
        pg.fill("#calc-iptu", "6000")
        esp = cp.estimar(dados, idx, {"predio": pi, "rua": dados["predios"][pi][3], "bairro": dados["predios"][pi][2], "area": area_chip, "andar": 15, "preco_pedido": None})
        pg.fill("#calc-pedido", str(int(round(esp["estimativa"] * 1.25, -3))))
        pg.click(".calc-botao")
        pg.wait_for_selector(".calc-valor", timeout=5000)
        tela["valor_na_tela"] = pg.inner_text(".calc-valor")
        tela["valor_python"] = esp["estimativa"]
        tela["veredito"] = pg.inner_text(".calc-veredito").replace("\n", " | ")
        tela["selo"] = pg.inner_text(".calc-selos")
        tela["tabelas"] = pg.evaluate("()=>[...document.querySelectorAll('#calc-resultado section.card')].map(s=>({titulo:s.querySelector('h2')?.textContent, linhas:s.querySelectorAll('tbody tr').length}))")
        tela["custos"] = pg.inner_text(".calc-custos")
        tela["resumo"] = pg.inner_text(".calc-resumo")
        pg.screenshot(path=str(prints / "desktop_resultado.png"), full_page=True)
        pg.evaluate("()=>window.scrollTo(0,0)")
        pg.screenshot(path=str(prints / "desktop_topo.png"))
        tela["valor_confere"] = tela["valor_na_tela"].replace("R$", "").replace(" ", "").replace(".", "").strip() == str(esp["estimativa"])

        # número da rua sem vendas
        pg.click(".calc-local-card .calc-link")
        rua_nome = dados["predios"][pi][1].rsplit(",", 1)[0]
        pg.fill("#calc-endereco", f"{rua_nome} 99999")
        pg.wait_for_selector(".calc-sugestao", timeout=5000)
        tela["sugestao_sem_vendas"] = pg.inner_text(".calc-sugestao >> nth=0").replace("\n", " | ")
        pg.click(".calc-sugestao >> nth=0")
        pg.fill("#calc-area", str(area_chip))
        pg.click(".calc-botao")
        pg.wait_for_selector(".calc-valor", timeout=5000)
        tela["rua_valor"] = pg.inner_text(".calc-valor")
        tela["rua_selo"] = pg.inner_text(".calc-selos")
        tela["rua_porque"] = pg.inner_text(".calc-porque li >> nth=0")
        # endereço inexistente
        pg.click(".calc-local-card .calc-link")
        pg.fill("#calc-endereco", "Rua Que Nao Existe Nenhuma 12")
        tela["inexistente"] = pg.inner_text(".calc-sem-sugestao")
        # acento e abreviação
        pg.fill("#calc-endereco", "r sena madureira")
        pg.wait_for_timeout(100)
        tela["busca_sena"] = pg.evaluate("()=>[...document.querySelectorAll('.calc-sugestao')].slice(0,3).map(l=>l.innerText.replace(/\\n/g,' | '))")
        # celular
        ctx2 = br.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
        m = ctx2.new_page()
        m.on("pageerror", lambda e: erros.append("mobile: " + str(e)[:200]))
        m.on("console", lambda x: erros.append("mobile: " + x.text[:200]) if x.type == "error" else None)
        m.goto(args.base, wait_until="networkidle")
        m.evaluate("()=>window.showPanel('calculadora')")
        m.wait_for_selector("#calc-endereco", timeout=60000)
        m.fill("#calc-endereco", nome.replace(",", ""))
        m.wait_for_selector(".calc-sugestao")
        m.click(".calc-sugestao >> nth=0")
        m.click(".calc-metragens .calc-chip >> nth=0")
        m.fill("#calc-andar", "10")
        m.fill("#calc-pedido", str(int(round(esp["estimativa"] * 1.0, -3))))
        m.click(".calc-botao")
        m.wait_for_selector(".calc-valor")
        m.wait_for_timeout(600)
        tela["mobile_largura"] = m.evaluate("()=>({scroll:document.documentElement.scrollWidth, janela:375, innerWidth:innerWidth})")
        tela["mobile_veredito"] = m.inner_text(".calc-veredito").replace("\n", " | ")
        m.screenshot(path=str(prints / "mobile_resultado.png"), full_page=True)
        ctx2.close()
        resultado["tela"] = tela
        br.close()
    print(json.dumps(resultado, ensure_ascii=False, indent=1, default=str))
    print("ERROS DE CONSOLE:", len(erros), erros[:5])
    t = resultado["tela"]
    ok = (not erros and resultado["paridade"]["divergencias"] == 0 and t["valor_confere"] and t["erro_sem_area"]
          and t["mobile_largura"]["scroll"] <= t["mobile_largura"]["janela"] and t["rua_valor"] and "Nenhum endereço" in t["inexistente"]
          and "sem vendas" in t["sugestao_sem_vendas"])
    print("RESULTADO:", "OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
