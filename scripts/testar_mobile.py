#!/usr/bin/env python3
"""
Teste da versão CELULAR do dashboard (uso LOCAL — não roda no GitHub Actions).

Celular (390 px): menu de baixo com 4 botões e a folha de seções; topo enxuto (grupo + nome da seção, fontes recolhidas); "Como usar" em toda
seção; tabelas viram cartões; só 10 itens por lista com "Ver mais"; filtros recolhidos num botão; voltar ao topo; nada rola para o lado; sem erro de console.
Computador (1300 px): nada disso aparece e tudo continua como era (menu lateral, 77 linhas, tabelas, filtros abertos).

Uso:
  cd site && python3 serve_no_cache.py 8899 &
  python3 scripts/testar_mobile.py [--base http://localhost:8899]
Sai com código != 0 se algo falhar.
"""
import argparse, sys
from playwright.sync_api import sync_playwright

PAINEIS = [
    ("visao-geral", "Visão Geral", "Panorama do mercado"), ("perfil", "Perfil por Bairro", "Panorama do mercado"), ("preco-m2", "Valor pago por bairro", "Panorama do mercado"),
    ("mapa", "Mapa", "Panorama do mercado"), ("carteira-77", "Carteira 77", "Panorama do mercado"),
    ("estoque-demanda", "Estoque × Demanda", "Onde captar"), ("captacao", "Captação Ativa", "Onde captar"), ("ranking", "Ranking de Oportunidade", "Onde captar"),
    ("prontidao", "Prontidão para Campanha", "Campanhas Topio"), ("prioritarios", "Imóveis Prioritários", "Campanhas Topio"), ("valor-oportunidade", "Valor de Oportunidade", "Campanhas Topio"),
    ("calculadora", "Calculadora de preço", "Calculadora Topio"),
]
LISTAS = [("ranking", "ranking-table", "tbody > tr"), ("estoque-demanda", "estoque-demanda-table", "tbody > tr"), ("carteira-77", "carteira-77-table", "tbody > tr"),
          ("preco-m2", "preco-m2-table", "tbody > tr"), ("valor-oportunidade", "valor-oportunidade-table", "tbody > tr"), ("prontidao", "prontidao-table", ".rank-row"),
          ("prioritarios", "prioritarios-table", ".imovel-row"), ("captacao", "captacao-top30", ".top30-item")]
JS_VISIVEIS = """([id, sel]) => { const c = document.getElementById(id); return [...c.querySelectorAll(sel)].filter(e => e.getClientRects().length && getComputedStyle(e).display !== 'none').length; }"""


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--base", default="http://localhost:8899"); a = ap.parse_args()
    falhas = []

    def ok(c, m):
        print(("OK     " if c else "FALHOU ") + m)
        if not c: falhas.append(m)

    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        # ------------------------------------------------ celular
        ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True, has_touch=True)
        pg = ctx.new_page(); erros = []
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None); pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(a.base + "/index.html?mob=1"); pg.wait_for_timeout(2500)
        barra = pg.evaluate("()=>{const b=document.getElementById('menu-baixo').getBoundingClientRect();return {nomes:[...document.querySelectorAll('#menu-baixo button')].map(x=>x.innerText.trim()),fundo:Math.round(b.bottom),janela:innerHeight,topo:Math.round(b.top)}}")
        ok(barra["nomes"] == ["Panorama", "Onde captar", "Campanhas", "Calculadora"], f"celular: menu de baixo com os 4 botões {barra['nomes']}")
        ok(barra["fundo"] == barra["janela"], "celular: o menu de baixo fica colado no fim da tela")
        ok(not pg.is_visible("nav.tabs"), "celular: acabou a fila de abas que rolava para o lado")
        # folhas
        for nome, esperado in [("Panorama do mercado", [x[1] for x in PAINEIS if x[2] == "Panorama do mercado"]), ("Onde captar", [x[1] for x in PAINEIS if x[2] == "Onde captar"]), ("Campanhas Topio", [x[1] for x in PAINEIS if x[2] == "Campanhas Topio"])]:
            pg.click(f'#menu-baixo button[data-grupo="{nome}"]'); pg.wait_for_timeout(250)
            itens = pg.evaluate("()=>[...document.querySelectorAll('#menu-folha .folha-item')].map(x=>x.innerText.trim())")
            ok(itens == esperado and pg.is_visible("#menu-folha"), f"celular: a folha de «{nome}» lista as seções certas ({len(itens)})")
            pg.click("#menu-veu", position={"x": 20, "y": 40}); pg.wait_for_timeout(200)
            ok(not pg.is_visible("#menu-folha"), f"celular: tocar fora fecha a folha de «{nome}»")
        pg.click('#menu-baixo button[data-grupo="Calculadora Topio"]'); pg.wait_for_timeout(1500)
        ok(pg.evaluate("()=>document.querySelector('.panel.active').dataset.panel") == "calculadora" and not pg.is_visible("#menu-folha"), "celular: «Calculadora» (uma seção só) abre direto, sem folha")
        # cada seção pelo menu
        for pid, rotulo, grupo in PAINEIS:
            if pid == "calculadora": pg.click('#menu-baixo button[data-grupo="Calculadora Topio"]')
            else:
                pg.click(f'#menu-baixo button[data-grupo="{grupo}"]'); pg.click(f'#menu-folha .folha-item:has-text("{rotulo}")')
            pg.wait_for_timeout(1300)
            r = pg.evaluate("""(pid)=>{const pn=document.querySelector('.panel[data-panel="'+pid+'"]');const cu=pn.querySelector('.como-usar');
              return {ativo:pn.classList.contains('active'), titulo:document.querySelector('#cabecalho-secao .cab-titulo').textContent, eyebrow:document.querySelector('#cabecalho-secao .cab-eyebrow').textContent,
                grupoOn:document.querySelector('#menu-baixo button.on')?.dataset.grupo, passos:cu?[...cu.querySelectorAll('li')].length:0, comoVisivel:!!cu&&cu.getClientRects().length>0,
                largura:document.documentElement.scrollWidth, janela:innerWidth, headerAltura:Math.round(document.querySelector('header.app-header').getBoundingClientRect().height),
                fontesVisiveis:document.getElementById('fontes-status').getClientRects().length>0, h1:document.querySelector('header.app-header h1').getClientRects().length>0}}""", pid)
            ok(r["ativo"] and r["titulo"] == rotulo and r["eyebrow"] == grupo and r["grupoOn"] == grupo, f"celular/{pid}: abre pelo menu; título «{r['titulo']}», tema «{r['eyebrow']}» e botão do tema aceso")
            ok(r["comoVisivel"] and 2 <= r["passos"] <= 3, f"celular/{pid}: «Como usar» à vista com {r['passos']} passos")
            ok(r["largura"] <= r["janela"], f"celular/{pid}: nada rola para o lado ({r['largura']} ≤ {r['janela']})")
            ok(r["headerAltura"] < 190 and not r["fontesVisiveis"] and not r["h1"], f"celular/{pid}: topo enxuto (altura {r['headerAltura']} px, fontes recolhidas)")
        # "ver fontes"
        pg.click("#ver-fontes"); pg.wait_for_timeout(200)
        ok(pg.is_visible("#fontes-status"), "celular: «ver fontes» abre as datas e fontes")
        pg.click("#ver-fontes")
        # listas de 10 + Ver mais
        for pid, cid, sel in LISTAS:
            pg.evaluate("(i)=>showPanel(i)", pid); pg.wait_for_timeout(1300)
            total = pg.evaluate("([id,sel])=>document.getElementById(id).querySelectorAll(sel).length", [cid, sel])
            v1 = pg.evaluate(JS_VISIVEIS, [cid, sel])
            if total <= 10:
                ok(v1 == total, f"celular/{pid}: lista com {total} itens aparece inteira"); continue
            ok(v1 == 10 and pg.is_visible(f"#{cid} .ver-mais-celular"), f"celular/{pid}: mostra só 10 de {total} e tem o botão «Ver mais»")
            pg.click(f"#{cid} .ver-mais-celular"); pg.wait_for_timeout(200)
            v2 = pg.evaluate(JS_VISIVEIS, [cid, sel])
            ok(v2 == total, f"celular/{pid}: «Ver mais» mostra os {total} itens (aparecem {v2})")
            pg.click(f"#{cid} .ver-mais-celular"); pg.wait_for_timeout(200)
            ok(pg.evaluate(JS_VISIVEIS, [cid, sel]) == 10, f"celular/{pid}: «Ver só os 10 primeiros» volta para 10")
        # cartões
        pg.evaluate("()=>showPanel('ranking')"); pg.wait_for_timeout(800)
        c = pg.evaluate("""()=>({thead:getComputedStyle(document.querySelector('#ranking-table thead')).display, tr:getComputedStyle(document.querySelector('#ranking-table tbody tr')).display,
          rotulos:[...document.querySelectorAll('#ranking-table tbody tr:first-child td')].map(t=>t.dataset.label).filter(Boolean).length, titulo:document.querySelector('#ranking-table tbody tr:first-child td.td-titulo')?.textContent})""")
        ok(c["thead"] == "none" and c["tr"] == "block" and c["rotulos"] >= 5 and c["titulo"], f"celular/ranking: a tabela virou cartões (título «{c['titulo']}», {c['rotulos']} rótulos)")
        # sem ordenar? a ordem do ranking continua por nota (1º = maior)
        # filtros recolhidos
        pg.evaluate("()=>showPanel('visao-geral')"); pg.wait_for_timeout(800)
        ok(pg.is_visible("#filtros-card .filtro-chip") and not pg.is_visible("#filtros-card .filtros-grid"), "celular/visão geral: filtros recolhidos num botão")
        pg.click("#filtros-card .filtro-chip"); pg.wait_for_timeout(200)
        ok(pg.is_visible("#filtros-card .filtros-grid"), "celular/visão geral: o botão abre os filtros")
        pg.click("#filtro-bairro-list label:has-text('Moema') input"); pg.wait_for_timeout(1500)
        ok("Moema" in pg.inner_text("#filtros-card .filtro-chip-txt"), f"celular/visão geral: o botão mostra o filtro ativo ({pg.inner_text('#filtros-card .filtro-chip-txt')[:60]})")
        pg.click("#filtro-limpar-tudo"); pg.wait_for_timeout(800)
        pg.evaluate("()=>showPanel('captacao')"); pg.wait_for_timeout(1300)
        ok(pg.is_visible("#captacao-filtros-caixa .filtro-chip") and not pg.is_visible("#captacao-filtros"), "celular/captação: filtros recolhidos num botão")
        pg.click("#captacao-filtros-caixa .filtro-chip"); pg.wait_for_timeout(200)
        ok(pg.is_visible("#captacao-filtros"), "celular/captação: o botão abre os filtros")
        # voltar ao topo
        pg.evaluate("()=>window.scrollTo(0,1500)"); pg.wait_for_timeout(400)
        ok(pg.is_visible("#voltar-topo"), "celular: o botão «voltar ao topo» aparece depois de rolar")
        pg.click("#voltar-topo"); pg.wait_for_timeout(900)
        ok(pg.evaluate("()=>window.scrollY") < 5, "celular: «voltar ao topo» volta mesmo ao topo")
        ok(not erros, f"celular: nenhum erro de console ({erros[:2]})")
        ctx.close()
        # ------------------------------------------------ computador
        ctx = br.new_context(viewport={"width": 1300, "height": 900})
        pg = ctx.new_page(); erros = []; pg.on("pageerror", lambda e: erros.append(str(e)))
        pg.goto(a.base + "/index.html?mob=2"); pg.wait_for_timeout(2500)
        ok(not pg.is_visible("#menu-baixo") and not pg.is_visible("#voltar-topo") and not pg.is_visible("#cabecalho-secao") and not pg.is_visible("#ver-fontes"), "computador: menu de baixo, topo de celular e «voltar ao topo» não aparecem")
        ok(pg.is_visible("nav.tabs") and len(pg.query_selector_all(".nav-grupo")) == 4, "computador: menu lateral com as 4 caixinhas, como antes")
        ok(pg.is_visible("header.app-header h1") and pg.is_visible("#fontes-status"), "computador: cabeçalho completo, como antes")
        ok(not pg.is_visible(".panel.active .como-usar"), "computador: o «Como usar» do celular não aparece")
        ok(pg.is_visible("#filtros-card .filtros-grid") and not pg.is_visible("#filtros-card .filtro-chip"), "computador: filtros abertos, sem o botão de recolher")
        pg.evaluate("()=>showPanel('ranking')"); pg.wait_for_timeout(800)
        d = pg.evaluate("""()=>({thead:getComputedStyle(document.querySelector('#ranking-table thead')).display, visiveis:[...document.querySelectorAll('#ranking-table tbody tr')].filter(e=>e.getClientRects().length).length, botao:!!document.querySelector('#ranking-table .ver-mais-celular')&&document.querySelector('#ranking-table .ver-mais-celular').getClientRects().length>0})""")
        ok(d["thead"] != "none" and d["visiveis"] == 77 and not d["botao"], f"computador/ranking: tabela normal com as {d['visiveis']} linhas e sem «Ver mais»")
        ok(not erros, "computador: nenhum erro de console")
        ctx.close(); br.close()
    print("\nRESULTADO:", "OK" if not falhas else f"{len(falhas)} FALHA(S)")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
