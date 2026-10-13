#!/usr/bin/env python3
"""
Teste do botão "Baixar precificação (PDF)" da Calculadora (uso LOCAL — não roda no GitHub Actions).

Para cada cenário (com pedido, sem pedido, pedido fora do mercado, só pela rua/bairro, pela área útil, poucas vendas):
  - o botão só aparece DEPOIS de calcular (e some se não houver estimativa);
  - o relatório gerado cabe em UMA página A4, tem os blocos certos (sem o veredito quando não há pedido) e nenhum "null", "undefined" ou "NaN";
  - o preço sugerido e a faixa que saem no PDF batem com o cálculo em Python (calculadora_preco.py);
  - o relatório acompanha o preço testado no simulador "E se o proprietário pedir…?".
Uso:
  cd site && python3 serve_no_cache.py 8899 &
  python3 scripts/testar_relatorio.py [--base http://localhost:8899] [--saida /caminho/para/pdfs]
Sai com código != 0 se algo falhar.
"""
import argparse, io, json, re, sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calculadora_preco as cp

ROOT = Path(__file__).resolve().parent.parent
BTN = '.panel[data-panel="calculadora"] .page-pdf-btn'
SOBRA = None
LIXO = re.compile(r"\bnull\b|undefined|NaN", re.I)


def mil(v):
    return f"R$ {v / 1e6:.2f} milhões".replace(".", ",").replace(",00", "") if v >= 1e6 else f"R$ {int(v / 1000 + 0.5):,} mil".replace(",", ".")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8899")
    ap.add_argument("--saida", default="/tmp/relatorios")
    a = ap.parse_args()
    saida = Path(a.saida); saida.mkdir(parents=True, exist_ok=True)
    dados = json.load(open(ROOT / "site" / "calculadora.json")); idx = cp.indexar(dados)
    falhas = []

    def ok(cond, msg):
        print(("OK     " if cond else "FALHOU ") + msg)
        if not cond: falhas.append(msg)

    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        pg = br.new_page(viewport={"width": 1300, "height": 900}); erros = []
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: erros.append(str(e)))

        def abrir():
            pg.goto(a.base + "/index.html?rel=1"); pg.wait_for_timeout(1500)
            pg.click('nav.tabs button:has-text("Calculadora de preço")'); pg.wait_for_selector("#calc-endereco", timeout=60000)

        def calcular(end, apto=None, util=None, pedido=None):
            pg.fill("#calc-endereco", end); pg.wait_for_selector(".calc-sugestao", timeout=5000); pg.click(".calc-sugestao >> nth=0")
            if apto: pg.fill("#calc-apto", str(apto))
            if util:
                if pg.is_visible(".calc-chip-util"): pg.click(".calc-chip-util")   # "Não sei — estimar pela área útil"
                pg.fill("#calc-area-util", str(util))
            if pedido: pg.fill("#calc-pedido", str(pedido))
            pg.wait_for_timeout(300); pg.click("#calc-calcular"); pg.wait_for_timeout(900)

        def relatorio(nome):
            pg.evaluate("()=>window.calcMontarRelatorioParaTeste()")
            pg.evaluate("()=>document.body.classList.add('imprimindo-relatorio')")
            pg.emulate_media(media="print"); pg.wait_for_timeout(600)
            global SOBRA
            SOBRA = pg.evaluate("""()=>{const c=document.querySelector('#relatorio-precificacao .rel-pagina');if(!c)return null;
              const bx=(q)=>document.querySelector('#relatorio-precificacao '+q).getBoundingClientRect();
              return {cabe: c.scrollHeight<=c.clientHeight+1, folga: Math.round(bx('.rel-rodape').top-bx('.rel-conf').bottom)}}""")
            pdf = pg.pdf(prefer_css_page_size=True, print_background=True)
            pg.evaluate("()=>document.body.classList.remove('imprimindo-relatorio')"); pg.emulate_media(media="screen")
            (saida / f"{nome}.pdf").write_bytes(pdf)
            rd = PdfReader(io.BytesIO(pdf))
            return len(rd.pages), "\n".join(pg_.extract_text() for pg_ in rd.pages)

        cenarios = [
            ("com_pedido", dict(end="Rua Sena Madureira 1123", apto=43, pedido=800000), True),
            ("sem_pedido", dict(end="Rua Sena Madureira 1123", apto=43), False),
            ("pedido_fora", dict(end="Rua Sena Madureira 1123", apto=43, pedido=2000000), True),
            ("area_util", dict(end="Rua Sena Madureira 1123", util=90), False),
            ("so_rua", dict(end="Rua Sena Madureira 99999", util=70, pedido=900000), True),
        ]
        # prédio com só 2 vendas (aviso de "poucas vendas") + pedido: é o caso com mais texto no relatório
        pi = next(i for i, v in sorted(idx["predio"].items()) if len(v) == 2 and dados["vendas"][v[0]][7])
        vv = dados["vendas"][idx["predio"][pi][0]]
        cenarios.append(("poucas_vendas", dict(end=dados["predios"][pi][1].replace(",", ""), apto=vv[7], pedido=round(vv[2] * 1.5, -3)), True))
        # prédio com muitas vendas (11+): era o caso em que o gráfico ficava confuso
        pm = next(i for i, v in sorted(idx["predio"].items(), key=lambda kv: -len(kv[1])) if dados["vendas"][v[0]][7])
        vm = dados["vendas"][idx["predio"][pm][0]]
        cenarios.append(("muitas_vendas", dict(end=dados["predios"][pm][1].replace(",", ""), apto=vm[7], pedido=round(vm[2] * 1.2, -3)), True))
        for nome, kw, com_pedido in cenarios:
            abrir()
            ok(not pg.is_visible(BTN), f"{nome}: antes de calcular o botão do PDF não aparece")
            try:
                calcular(**kw)
            except Exception as e:  # noqa: BLE001
                ok(False, f"{nome}: não consegui calcular ({e})"); continue
            ok(pg.is_visible(BTN), f"{nome}: depois de calcular o botão aparece")
            ok("precificação" in pg.inner_text(BTN).lower(), f"{nome}: o botão se chama 'Baixar precificação'")
            n, texto = relatorio(nome)
            ok(n == 1, f"{nome}: o relatório cabe em 1 página A4 (tem {n})")
            ok(SOBRA and SOBRA["cabe"] and SOBRA["folga"] >= 4, f"{nome}: nada passa do fim da página nem encosta no rodapé ({SOBRA})")
            ok(not LIXO.search(texto), f"{nome}: sem 'null', 'undefined' ou 'NaN' no texto")
            ok("Paulo Credidio" in texto and "by Topio" in texto, f"{nome}: assinatura Paulo Credidio · by Topio imóveis")
            ok("preço sugerido de venda" in texto.lower() and "vendas reais usadas na conta" in texto.lower(), f"{nome}: blocos do preço sugerido e do gráfico")
            ok(("Pedido" in texto and "chegaram a" in texto) == com_pedido, f"{nome}: veredito do pedido {'aparece' if com_pedido else 'não aparece (sem pedido)'}")
            est = pg.evaluate("()=>{const r=document.querySelector('#relatorio-precificacao .rel-big');return r?r.textContent:null}")
            # bate com o Python (mesmos dados): reconstrói a entrada pelo que está na tela
            ent = pg.evaluate("()=>{const e=window.__calcUltimaEntrada&&window.__calcUltimaEntrada();return e||null}")
            if ent:
                r = cp.estimar(dados, idx, ent)
                ok(est == mil(r["estimativa"]), f"{nome}: preço sugerido do PDF ({est}) = Python ({mil(r['estimativa'])})")
                ok(mil(r["minimo"]) in texto and mil(r["maximo"]) in texto, f"{nome}: faixa provável do PDF = Python")
            if nome == "muitas_vendas":
                pg.fill("#calc-corretor", "650000"); pg.wait_for_timeout(300)   # só para gerar a imagem mais cheia (pedido + corretor)
                nn, tt = relatorio("muitas_vendas_corretor")
                ok(nn == 1 and SOBRA and SOBRA["cabe"] and SOBRA["folga"] >= 4, f"muitas_vendas: com pedido e corretor, 1 página e nada passa do rodapé ({SOBRA})")
                pg.fill("#calc-corretor", "")
            if nome == "com_pedido":
                # balão "Pedida sugerida pelo corretor": só aparece no PDF quando preenchido
                ok("pedida sugerida pelo corretor" not in texto.lower(), "com_pedido: sem valor do corretor, o balão não sai no PDF")
                pg.fill("#calc-corretor", "740000"); pg.wait_for_timeout(300)
                n3, t3 = relatorio("com_pedido_corretor")
                ok(n3 == 1 and "pedida sugerida pelo corretor" in t3.lower() and "R$ 740 mil" in t3 and "preço sugerido pela calculadora" in t3.lower(), "com_pedido: com o valor do corretor (R$ 740 mil) o PDF mostra os dois balões, em 1 página")
                ok(SOBRA and SOBRA["cabe"] and SOBRA["folga"] >= 4, f"com_pedido: com os dois balões nada passa do rodapé ({SOBRA})")
                pg.fill("#calc-corretor", ""); pg.wait_for_timeout(200)
                # o simulador manda: trocar o pedido na tela troca o PDF
                pg.fill("#calc-sim-valor", "2000000"); pg.wait_for_timeout(500)
                n2, t2 = relatorio("com_pedido_simulador")
                ok("fora do mercado" in t2.lower() and "R$ 2 milhões" in t2, "com_pedido: o PDF acompanha o preço testado no simulador (R$ 2 milhões → fora do mercado)")
        # sem estimativa: o botão some
        abrir()
        try:
            calcular("Rua Sena Madureira 1123", apto=None, util=5000)
        except Exception:
            pass
        ok(not pg.is_visible(BTN), "caso sem resposta/erro: o botão do PDF não aparece")
        ok(not erros, f"nenhum erro de console ({erros[:2]})")
        br.close()
    print("\nRESULTADO:", "OK" if not falhas else f"{len(falhas)} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
