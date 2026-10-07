#!/usr/bin/env python3
"""
Verificação de interface do dashboard (uso LOCAL — não roda no GitHub Actions):
abre o site num Chrome limpo (Playwright), passa pelos painéis coletando
erros de console, compara o resultado do servidor (data.json) com o recalculado
no navegador (engine.js + raw.json), confere o cabeçalho e o aviso de dado
parado, e gera os PDFs (completo + um por painel) contando as páginas.

Requer: pip install playwright pypdf  (e Google Chrome instalado)
Uso:
  cd site && python3 serve_no_cache.py 8899 &      # servidor local
  python3 scripts/verificar_interface.py [--base http://localhost:8899] [--saida /tmp/pdfs]
Sai com código != 0 se houver erro de console ou divergência de lógica.
"""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAINEIS = ["visao-geral", "ranking", "prontidao", "estoque-demanda", "perfil", "mapa", "captacao",
           "prioritarios", "valor-oportunidade", "preco-m2", "carteira-77"]

JS_PARIDADE = """()=>{
  const eq=(a,b)=>{ if(a===b) return true; if(a==null&&b==null) return true; if(typeof a==="number"&&typeof b==="number") return Math.abs(a-b)<=0.011; return JSON.stringify(a)===JSON.stringify(b); };
  const tol=(a,b)=>{ // arrays/objetos com diferença só de arredondamento (<= 0,011)
    if(eq(a,b)) return true;
    if(Array.isArray(a)&&Array.isArray(b)&&a.length===b.length) return a.every((x,i)=>tol(x,b[i]));
    if(a&&b&&typeof a==="object"&&typeof b==="object"){ const ks=new Set([...Object.keys(a),...Object.keys(b)]); return [...ks].every(k=>tol(a[k],b[k])); }
    return false; };
  const S=SERVER_DATA, J=window.__data; const out={};
  const bf=["perfil_vencedor_faixa_preco_v2","perfil_vencedor_faixa_preco_v2_meta","perfil_faixa_confiavel","estoque_perfil_faixa_preco","estoque_perfil_faixa_preco_nota","estoque_fora_do_perfil","selo_escassez_real","prontidao_campanha","score","stock_demand_ratio","price_gap_pct","revenda_12m","search_interest"];
  let d=0,n=0,ex=[];
  for(const b in S.bairros){ for(const f of bf){ n++; if(!tol(S.bairros[b][f],J.bairros[b][f])){d++; ex.length<5&&ex.push(b+"."+f);} } }
  out.bairros={comparacoes:n,divergencias:d,exemplos:ex};
  const ip=new Map(J.imoveis_prioritarios.map(i=>[i.codigo,i])); let di=0;
  for(const i of S.imoveis_prioritarios){const j=ip.get(i.codigo); if(!j||!eq(i.final_score,j.final_score)||i.captacao_bonus!==j.captacao_bonus) di++;}
  out.painel8={imoveis:S.imoveis_prioritarios.length,divergencias:di};
  let dp=0,np=0; const pj=new Map(J.preco_m2_painel.map(p=>[p.bairro+"|"+p.faixa,p]));
  for(const p of S.preco_m2_painel){const q=pj.get(p.bairro+"|"+p.faixa); for(const k in p){np++; if(!q||!eq(p[k],q[k])) dp++;}}
  out.preco_m2={campos:np,divergencias:dp};
  const vj=new Map(J.valor_oportunidade.imoveis.map(i=>[i.codigo,i])); let dv=0;
  for(const a of S.valor_oportunidade.imoveis){const b=vj.get(a.codigo); if(!b||!eq(a.desconto_pct,b.desconto_pct)||a.n_vendas_predio!==b.n_vendas_predio||a.atencao!==b.atencao) dv++;}
  if(S.valor_oportunidade.imoveis.length!==J.valor_oportunidade.imoveis.length) dv+=Math.abs(S.valor_oportunidade.imoveis.length-J.valor_oportunidade.imoveis.length);
  out.valor_oportunidade={achados:S.valor_oportunidade.imoveis.length,achados_apto:S.valor_oportunidade.imoveis.filter(a=>a.tipo_imovel==="apartamento").length,divergencias:dv,meta_apto:JSON.stringify(S.valor_oportunidade.meta_apto)===JSON.stringify(J.valor_oportunidade.meta_apto)};
  let dci=0, nci=0; const IS=S.valor_oportunidade.correcao_tempo.indices, IJ=J.valor_oportunidade.correcao_tempo.indices;
  for(const b in IS){ for(const t in IS[b]){ const x=IS[b][t], y=(IJ[b]||{})[t]; if(!y||x.janela_meses!==y.janela_meses){dci++;continue;} for(const m in x.fator){nci++; if(Math.abs(x.fator[m]-y.fator[m])>0.0006) dci++; } } }
  out.correcao_tempo={fatores:nci,divergencias:dci,resumo_igual:JSON.stringify(S.valor_oportunidade.correcao_tempo.resumo)===JSON.stringify(J.valor_oportunidade.correcao_tempo.resumo)};
  const k=(t)=>t.map(e=>[e.bairro,e.endereco,e.n_vendas,Math.round(e.preco_mediana),e.tipo_imovel].join("|")).join(";"); /* addr_key no JS é índice interno, não o texto do Python */
  out.top30={n:S.captacao_top30.length,igual:k(S.captacao_top30)===k(J.captacao_top30)};
  const ck=(c)=>[c.bairro,c.endereco,c.n_vendas,Math.round(c.preco_mediana/10)*10].join("|"); /* preço arredondado: Python x JS diferem em 0,01 */ const cs=(l)=>{const m=new Map(); l.forEach(c=>{const x=ck(c); (m.get(x)||m.set(x,[]).get(x)).push(c.tipo_imovel);}); m.forEach(v=>v.sort()); return m;};
  const mp=cs(S.captacao_ativa), mj=cs(J.captacao_ativa); let dt=0; mp.forEach((v,x)=>{ if(JSON.stringify(v)!==JSON.stringify(mj.get(x))) dt+=v.length; });
  if(S.captacao_ativa.length!==J.captacao_ativa.length) dt+=Math.abs(S.captacao_ativa.length-J.captacao_ativa.length);
  out.captacao_tipo={enderecos:S.captacao_ativa.length,divergencias:dt};
  let dpg=0, npg=0; for(const b in S.bairros){ npg++; if(JSON.stringify(S.bairros[b].pagamento)!==JSON.stringify(J.bairros[b].pagamento)) dpg++; }
  out.pagamento={bairros:npg,divergencias:dpg,credito_igual:JSON.stringify(S.contexto_credito)===JSON.stringify(J.contexto_credito)};
  out.prontidao_top10_igual=S.prontidao_ranking.slice(0,10).join()===J.prontidao_ranking.slice(0,10).join();
  return out;}"""

JS_AVISO = """()=>{
  const box=document.getElementById("aviso-dado-parado"); const original=SERVER_DATA.generated_at_iso; const r={};
  const t=(h)=>{SERVER_DATA.generated_at_iso=new Date(Date.now()-h*3600000).toISOString(); atualizarAvisoDadoParado(); return box.hidden?"oculto":box.textContent;};
  r.h29=t(29); r.h30=t(30); r.h31=t(31); r.h120=t(120);
  SERVER_DATA.generated_at_iso=original; atualizarAvisoDadoParado(); r.real=box.hidden?"oculto":box.textContent; return r;}"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8899")
    ap.add_argument("--saida", default="/tmp/verificacao_pdfs")
    args = ap.parse_args()
    out_dir = Path(args.saida)
    out_dir.mkdir(parents=True, exist_ok=True)
    erros = []
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        pg = br.new_page()
        pg.on("pageerror", lambda e: erros.append(str(e)[:200]))
        pg.on("console", lambda m: erros.append(m.text[:200]) if m.type == "error" else None)
        pedidos = []
        pg.on("request", lambda r: pedidos.append(r.url.rsplit("/", 1)[-1]))
        pg.goto(args.base, wait_until="networkidle")
        pg.wait_for_timeout(1500)
        for pid_ in PAINEIS:  # percorre os painéis SEM usar filtro: o raw.json não pode ser pedido
            pg.evaluate(f"()=>window.showPanel('{pid_}')")
            pg.wait_for_timeout(120)
        raw_antes_do_filtro = "raw.json" in pedidos
        # "Ver lista completa" (Estoque × Demanda) é o outro caminho que carrega o raw.json
        pg.evaluate("()=>window.showPanel('estoque-demanda')")
        pg.evaluate("()=>document.querySelector('#estoque-demanda-table tbody tr td:last-child a').click()")
        pg.wait_for_selector(".estoque-detalhe-row", timeout=120000)
        lista_ok = pg.evaluate("()=>document.querySelectorAll('.estoque-detalhe-row .mini-listing-row').length>0 || !!document.querySelector('.estoque-detalhe-row .placeholder-block')")
        pg.evaluate("()=>window.showPanel('visao-geral')")
        cab = pg.evaluate("()=>({atualizado:document.getElementById('updated-at').textContent,fontes:document.getElementById('fontes-status').innerText.replace(/\\n/g,' | ')})")
        pg.evaluate("async()=>{await window.ensureEngineLoaded(); window.recomputeAndRenderAll();}")
        pg.wait_for_timeout(800)
        for pid in PAINEIS:
            pg.evaluate(f"()=>window.showPanel('{pid}')")
            pg.wait_for_timeout(250)
        par = pg.evaluate(JS_PARIDADE)
        pg.evaluate("()=>window.showPanel('visao-geral')")
        telas = {"credito_cartoes": pg.evaluate("()=>document.querySelectorAll('#credito-quadro .credito-item').length")}
        pg.evaluate("()=>{window.showPanel('perfil'); const s=document.getElementById('perfil-select'); s.value='Vila Mariana'; s.dispatchEvent(new Event('change'));}")
        pg.wait_for_timeout(300)
        telas["perfil_como_se_paga"] = pg.evaluate("()=>{const e=[...document.querySelectorAll('#perfil-content h2')].find(h=>h.textContent==='Como se paga neste bairro'); return e? e.parentElement.innerText.slice(0,260).replace(/\\n/g,' | ') : null}")
        pg.evaluate("()=>window.showPanel('carteira-77')")
        telas["carteira_colunas"] = pg.evaluate("()=>[...document.querySelectorAll('#carteira-77-table thead th')].map(t=>t.textContent.replace(/[↕↓↑]/g,'').trim())")
        aviso = pg.evaluate(JS_AVISO)
        pg.evaluate("()=>{document.body.classList.add('printing-all'); window.expandAllCaptacao&&window.expandAllCaptacao();}")
        pg.wait_for_timeout(300)
        pg.emulate_media(media="print")
        pg.pdf(path=str(out_dir / "completo.pdf"), print_background=True, prefer_css_page_size=True)
        pg.emulate_media(media="screen")
        pg.evaluate("()=>document.body.classList.remove('printing-all')")
        for pid in PAINEIS:
            pg.evaluate(f"()=>window.showPanel('{pid}')")
            pg.wait_for_timeout(150)
            label = pg.evaluate(f"()=>{{const e=document.querySelector('.panel[data-panel=\"{pid}\"] h2');return e?e.textContent.trim():'{pid}'}}")
            pg.evaluate(f"()=>window.printPage('{pid}', {label!r})")
            pg.wait_for_timeout(200)
            pg.emulate_media(media="print")
            pg.pdf(path=str(out_dir / f"{pid}.pdf"), print_background=True, prefer_css_page_size=True)
            pg.emulate_media(media="screen")
        br.close()
    try:
        import pypdf
        paginas = {k: len(pypdf.PdfReader(str(out_dir / f"{k}.pdf")).pages) for k in ["completo"] + PAINEIS}
    except ImportError:
        paginas = "(instale pypdf pra contar páginas)"
    print(json.dumps({"cabecalho": cab, "paridade": par, "aviso_dado_parado": aviso, "paginas_pdf": paginas}, ensure_ascii=False, indent=1))
    print("TELAS NOVAS:", json.dumps(telas, ensure_ascii=False))
    print("ERROS DE CONSOLE:", len(erros), erros[:5])
    print("raw.json pedido antes de usar filtro:", raw_antes_do_filtro, "| Ver lista completa abriu:", lista_ok)
    div = (par["bairros"]["divergencias"] + par["painel8"]["divergencias"] + par["preco_m2"]["divergencias"]
           + par["valor_oportunidade"]["divergencias"] + par["captacao_tipo"]["divergencias"] + par["correcao_tempo"]["divergencias"])
    ok = (not erros and par["pagamento"]["divergencias"] == 0 and par["pagamento"]["credito_igual"] and telas["credito_cartoes"] == 4
          and telas["perfil_como_se_paga"] and not raw_antes_do_filtro and lista_ok and div == 0 and par["prontidao_top10_igual"] and par["top30"]["igual"]
          and par["valor_oportunidade"]["meta_apto"] and par["correcao_tempo"]["resumo_igual"])
    print("RESULTADO:", "OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
