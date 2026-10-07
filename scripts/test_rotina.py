#!/usr/bin/env python3
"""
Testes da rotina de conferência do Passo 5 (alertas.py, relatorio_semanal.py e
o cache de buscas por bairro). Sem rede, sem GitHub: python3 scripts/test_rotina.py
Sai com código != 0 se qualquer teste falhar.
"""
import copy
import datetime
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import alertas
import historico_anuncios as ha
import keyword_client as kc
import relatorio_semanal as rel

ROOT = Path(__file__).resolve().parent.parent
falhas = []


def ok(cond, nome):
    print(("OK   " if cond else "FALHOU ") + nome)
    if not cond:
        falhas.append(nome)


# ---------------------------------------------------------------------------
# 1. alertas: motivo em linguagem simples a partir do log
# ---------------------------------------------------------------------------
casos = {
    "queda_estoque": "[validate_build] FALHOU — publicação bloqueada: estoque válido da nonStop caiu 50.0% (de 1000 para 500 anúncios)",
    "formato_itbi": "[validate_build] FALHOU — publicação bloqueada: layout de coluna inesperado em 3 caso(s):\n  - JAN-2026: coluna N esperava 'Base', veio 'X'",
    "linhas_itbi": "[validate_build] FALHOU — publicação bloqueada: reconciliação de linhas falhou — planilhas têm 10 linhas",
    "variacao_bairros": "[validate_build] FALHOU — publicação bloqueada: 3 bairro(s) com variação de volume_primary_year acima de 30%",
    "camada_limpa": "[validate_build] FALHOU — publicação bloqueada: cálculo de preço fora da camada limpa única:\n  - x",
    "faixas_amostra": "[validate_build] FALHOU — publicação bloqueada: faixas de preço fora da regra de amostra (12/24/36 meses, mínimo 30):\n  - y",
    "google": "[validate_build] FALHOU — publicação bloqueada: datas de busca do Google por bairro incoerentes:\n  - z",
    "rodada_a": "[validate_build] FALHOU — publicação bloqueada: Rodada A — 2 divergência(s):\n  - x",
    "historico_anuncios": "[validate_build] FALHOU — publicação bloqueada: histórico de anúncios incoerente (1):\n  - y",
    "itbi_download": "SystemExit: Nenhum .xlsx de ITBI em cache (data/itbi_raw/) e a sincronização com a Prefeitura falhou",
    "nonstop_api": "RuntimeError: nonStop API 401 em /imoveis/todos: {\"error\":\"unauthorized\"}",
    "erro_programa": "linha\nTraceback (most recent call last):\n  File \"x.py\", line 1, in <module>\nKeyError: 'a'",
    "desconhecido": "qualquer coisa sem padrão conhecido",
}
for esperado, log in casos.items():
    cat, texto, detalhe = alertas.explicar_motivo("saida do build\n" + log + "\n")
    ok(cat == esperado and texto and detalhe, f"alerta: log '{esperado}' -> categoria {cat}")
cat, texto, detalhe = alertas.explicar_motivo("[validate_build] FALHOU — publicação bloqueada: uma coisa nova e desconhecida\n")
ok(cat == "check" and "conferência interna" in texto, "alerta: check desconhecido cai na mensagem genérica de check")

iss = alertas.montar_issue(casos["queda_estoque"], "https://github.com/x/y/actions/runs/1", agora=datetime.datetime(2026, 10, 6, 11, 5, tzinfo=datetime.timezone.utc))
ok(iss["titulo"] == "⚠ Atualização travada", "alerta: título exato '⚠ Atualização travada'")
ok("08:05" in iss["corpo"] and "ALLOW_LARGE_CHANGES=1" in iss["corpo"] and "actions/runs/1" in iss["corpo"], "alerta: corpo com hora de Brasília, dica de ALLOW_LARGE_CHANGES e link da execução")
ok(alertas.montar_issue(casos["queda_estoque"], None, teste=True)["titulo"].endswith("[TESTE]"), "alerta: modo teste marca [TESTE]")

# ---------------------------------------------------------------------------
# 2. cache de buscas do Google por bairro (migração + só busca quem falta/venceu)
# ---------------------------------------------------------------------------
v1 = {"fetched_at": "2026-09-21T22:00:00+00:00", "data": {"A": {"avg_monthly_searches": 10, "meses_com_dado": 3}, "B": {"avg_monthly_searches": 20, "meses_com_dado": 3}}}
v2 = kc.migrar_estado(v1)
ok(v2["versao"] == 2 and v2["bairros"]["A"]["fetched_at"] == "2026-09-21T22:00:00+00:00" and set(v2["bairros"]) == {"A", "B"}, "cache: v1 migra pra v2 com a data antiga em cada bairro")
ok(kc.migrar_estado(v2) is v2, "cache: v2 não é migrado de novo")
ok(kc.migrar_estado(None)["bairros"] == {}, "cache: sem estado vira v2 vazio")

with tempfile.TemporaryDirectory() as td:
    kc.STATE_FILE = Path(td) / "keyword_state.json"
    kc._save_state(v1)
    chamadas = []

    def falso_fetch(bairros, log=print, **kw):
        chamadas.append(list(bairros))
        return {b: {"avg_monthly_searches": 99, "meses_com_dado": 3, "por_termo": {}} for b in bairros}

    kc.fetch_search_interest = falso_fetch
    kc.credentials_available = lambda: True
    agora = datetime.datetime(2026, 10, 6, 12, 0, tzinfo=datetime.timezone.utc)
    data, meta = kc.get_search_interest_cached(["A", "B", "C"], log=lambda *a: None, agora=agora)
    ok(chamadas == [["C"]], "cache: só o bairro que faltava (C) foi buscado — A e B (15 dias) ficam como estão")
    ok(data["A"]["fetched_at"].startswith("2026-09-21") and data["C"]["fetched_at"].startswith("2026-10-06"), "cache: cada bairro mantém a PRÓPRIA data de busca")
    ok(meta["buscados_agora"] == ["C"] and not meta["tentativa_falhou"], "cache: meta informa quem foi buscado agora")
    agora2 = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.timezone.utc)  # A e B com 29 dias; C com 14
    chamadas.clear()
    data, meta = kc.get_search_interest_cached(["A", "B", "C"], log=lambda *a: None, agora=agora2)
    ok(chamadas == [["A", "B"]], "cache: bairros com mais de 25 dias são rebuscados, o recente (C) não")

    def fetch_quebrado(bairros, log=print, **kw):
        raise RuntimeError("API fora do ar")

    kc.fetch_search_interest = fetch_quebrado
    agora3 = datetime.datetime(2026, 11, 20, 12, 0, tzinfo=datetime.timezone.utc)
    data, meta = kc.get_search_interest_cached(["A", "B", "C"], log=lambda *a: None, agora=agora3)
    ok(meta["tentativa_falhou"] and all(v["fetch_falhou"] for v in data.values()), "cache: falha da API mantém o dado antigo e marca fetch_falhou por bairro")
    ok(data["A"]["fetched_at"].startswith("2026-10-20"), "cache: falha NÃO atualiza a data da busca")

# ---------------------------------------------------------------------------
# 3. relatório semanal (dados sintéticos, com a mesma forma do data.json)
# ---------------------------------------------------------------------------
AGORA = datetime.datetime(2026, 10, 12, 12, 0, tzinfo=datetime.timezone.utc)


def bairro(rev, estoque, nota, pequeno=False, perfil=3):
    return {"revenda_12m": rev, "stock_total": estoque, "prontidao_campanha": nota, "amostra_pequena_ranking": pequeno,
            "estoque_perfil_faixa_preco": perfil, "selo_escassez_real": False, "estoque_fora_do_perfil": False,
            "search_interest": {"fetched_at": "2026-10-06T10:00:00+00:00"}, "perfil_vencedor_faixa_preco_v2_meta": {}}


def dados(semana):
    ranking = ["Moema", "Pinheiros", "Perdizes"] + [f"B{i}" for i in range(7)]
    b = {"Moema": bairro(600, 100, 60.0), "Pinheiros": bairro(1000, 80, 55.0), "Perdizes": bairro(1500, 120, 50.0), "Pequeno": bairro(40, 4, 30.0, pequeno=True)}
    for i in range(7):
        b[f"B{i}"] = bairro(500, 50, 40.0 - i)
    imoveis = [{"bairro": "Moema", "codigo": f"M{i}", "anuncio_antigo": i % 5 == 0} for i in range(100)]
    d = {
        "generated_at_iso": "2026-10-12T11:10:00+00:00", "bairros": b, "prontidao_ranking": ranking,
        "periodo_12m": {"fim": "2026-06"}, "imoveis_prioritarios": imoveis,
        "meta": {"usn": {"rows_apos_dedup": 100},
                 "fontes": {"itbi": {"ultimo_mes_dado": "2026-06", "arquivo_atualizado_em": "Wed, 30 Sep 2026 13:52:43 GMT", "sync_ok": True},
                            "nonstop": {"consultado_em": "2026-10-12T11:05:00+00:00"},
                            "google_busca": {"n_sem_dado_recente": 0, "mais_antiga": "2026-09-21T22:00:00+00:00", "mais_recente": "2026-10-06T10:00:00+00:00",
                                             "n_bairros_com_dado": 77, "n_bairros_total": 77}}},
    }
    return d


novo, velho = dados(1), dados(0)
titulo, corpo, alertas_ = rel.montar_relatorio(novo, velho, AGORA)
ok("Semana sem alertas" in corpo.splitlines()[0] and not alertas_, "relatório: tudo normal -> 'Semana sem alertas' na primeira linha")
ok(titulo == "Relatório semanal — 12/10/2026", "relatório: título com a data de Brasília")
for trecho in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5."):
    ok(trecho in corpo, f"relatório: seção {trecho}")

n2 = copy.deepcopy(novo)
n2["bairros"]["Moema"]["revenda_12m"] = 800  # +33%, +200 revendas, bairro grande
n2["bairros"]["Pequeno"]["revenda_12m"] = 80  # +100%, mas amostra pequena -> não é alerta
n2["periodo_12m"]["fim"] = "2026-07"
_, corpo2, al2 = rel.montar_relatorio(n2, velho, AGORA)
ok(any("variação" in a for a in al2) and "Semana sem alertas" not in corpo2, "relatório: variação >20% em bairro grande vira alerta")
ok("a janela de 12 meses avançou" in corpo2, "relatório: causa provável da variação de revendas (janela de 12 meses avançou)")
ok("Pequeno (amostra pequena)" in corpo2, "relatório: amostra pequena aparece na lista")
n3 = copy.deepcopy(novo)
n3["bairros"]["Pequeno"]["revenda_12m"] = 80
_, _, al3 = rel.montar_relatorio(n3, velho, AGORA)
ok(not al3, "relatório: variação só em bairro de amostra pequena NÃO é alerta")

n4 = copy.deepcopy(novo)
n4["bairros"]["Moema"]["stock_total"] = 160
n4["imoveis_prioritarios"] += [{"bairro": "Moema", "codigo": f"N{i}", "anuncio_antigo": False} for i in range(60)]
_, corpo4, _ = rel.montar_relatorio(n4, velho, AGORA)
ok("60 anúncio(s) novo(s)" in corpo4 and "**Novos na semana:** 60" in corpo4, "relatório: estoque novo contado (e causa provável do estoque)")

n5 = copy.deepcopy(novo)
n5["meta"]["fontes"]["nonstop"]["consultado_em"] = "2026-10-01T11:05:00+00:00"  # 11 dias
n5["meta"]["fontes"]["itbi"]["arquivo_atualizado_em"] = "Wed, 01 Jul 2026 13:52:43 GMT"  # > 45 dias
n5["meta"]["fontes"]["google_busca"]["n_sem_dado_recente"] = 3
_, corpo5, al5 = rel.montar_relatorio(n5, velho, AGORA)
ok(sum("parad" in a for a in al5) == 2 and any("Google" in a for a in al5), "relatório: nonStop (>7 dias), ITBI (>45 dias) e Google (sem dado recente) viram alerta")

n6 = copy.deepcopy(novo)
n6["prontidao_ranking"] = ["Pinheiros", "Moema", "Perdizes", "Pequeno"] + [f"B{i}" for i in range(6)]
_, corpo6, _ = rel.montar_relatorio(n6, velho, AGORA)
ok("↑ subiu de 2º" in corpo6 and "↓ caiu de 1º" in corpo6 and "entrou no top 10" in corpo6, "relatório: top 10 mostra subiu/caiu/entrou")

_, corpo7, _ = rel.montar_relatorio(novo, None, AGORA)
ok("comparável" in corpo7 and "## 5." in corpo7, "relatório: sem semana anterior não quebra")

antigo = copy.deepcopy(velho)
for b_ in antigo["bairros"].values():
    b_.pop("revenda_12m")  # versão antiga dos dados (sem esse campo)
_, corpo8, al8 = rel.montar_relatorio(novo, antigo, AGORA)
ok("comparável" in corpo8 and not any("variação" in a for a in al8), "relatório: semana anterior de versão antiga é detectada e NÃO gera falso alerta")

# ---------------------------------------------------------------------------
# 3b. histórico de anúncios (Rodada A, item 7; data e hora desde 07/10/2026)
# ---------------------------------------------------------------------------
import validate_build as vb

T1, T2, T3, T4 = "2026-10-06T13:41:00", "2026-10-06T21:37:10", "2026-10-06T21:50:00", "2026-10-07T11:02:30"


def _rec(codigo, valor, **kw):
    base = {"codigo": codigo, "valor": valor, "bairro": "Moema", "addr_display_building": "Rua X, 10", "complemento": "ap 12",
            "tipo_imovel": "apartamento", "area": 80.0, "addr_key": "rua x|10", "created_at": "2026-03-05T15:00:00.000Z"}
    base.update(kw)
    return base


est, r1 = ha.atualizar({}, [_rec("a1", 1_000_000), _rec("b2", 2_000_000)], T1)
ok(r1["novos"] == 2 and r1["ativos"] == 2 and est["a1"]["cadastro"] == "2026-03-05" and est["a1"]["visto_primeira"] == T1,
   "histórico: primeira execução cria os anúncios com primeiro preço, cadastro e data+hora da primeira vez visto")
est_b, r1b = ha.atualizar(est, [_rec("a1", 1_000_000), _rec("b2", 2_000_000)], T2)
ok(r1b["novos"] == 0 and r1b["sairam"] == 0 and r1b["mudancas_de_preco"] == 0 and est_b["a1"]["visto_primeira"] == T1 and est_b["a1"]["visto_ultima"] == T2,
   "histórico: segunda execução no mesmo dia só avança a última vez visto (com a hora)")
est2, r2 = ha.atualizar(est, [_rec("a1", 950_000), _rec("c3", 500_000)], T2)
ok(est2["a1"]["preco_inicial"] == 1_000_000 and est2["a1"]["preco_atual"] == 950_000 and est2["a1"]["mudancas_preco"] == [[T2, 950_000]]
   and est2["a1"]["visto_ultima"] == T2, "histórico: mudança de preço guarda primeiro preço, preço atual e a mudança com data e hora")
ok(est2["b2"]["saida"] == T2 and est2["b2"]["visto_primeira"] == T1 and est2["b2"]["visto_ultima"] == T1 and r2["sairam"] == 1 and r2["novos"] == 1 and r2["ativos"] == 2,
   "histórico: anúncio visto numa execução e ausente na seguinte (MESMO DIA) sai com saída > última vez visto")
est3, r3 = ha.atualizar(est2, [_rec("a1", 950_000), _rec("b2", 2_100_000), _rec("c3", 500_000)], T4)
ok(est3["b2"]["saida"] is None and est3["b2"].get("voltas") == 1 and est3["b2"]["preco_atual"] == 2_100_000 and r3["voltaram"] == 1,
   "histórico: anúncio que volta à rede zera a saída e conta a volta")
ok(est["a1"]["preco_atual"] == 1_000_000 and est["a1"]["mudancas_preco"] == [], "histórico: a função não altera o estado recebido")
# Regressão do travamento de 06/10/2026 (check 16): várias execuções no mesmo dia, anúncio que sai na segunda.
dd = {"meta": {"historico_anuncios": {"agora": T2, "data": T2[:10], "ativos": 2, "novos": 1, "sairam": 1, "mudancas_de_preco": 1}}}
regs_t2 = [_rec("a1", 950_000), _rec("c3", 500_000)]


def _bloqueia(estado, registros, dados):
    try:
        vb.check_historico_anuncios((estado, registros), dados)
        return False
    except vb.ValidationError:
        return True


import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    passou_mesmo_dia = not _bloqueia(est2, regs_t2, dd)
ok(passou_mesmo_dia, "check 16: duas execuções no mesmo dia com um anúncio que saiu na segunda PASSA (o caso que travou em 06/10)")
import copy as _cp
x = _cp.deepcopy(est2); x["b2"]["saida"] = x["b2"]["visto_ultima"]
ok(_bloqueia(x, regs_t2, dd), "check 16: saída igual à última vez visto bloqueia")
x = _cp.deepcopy(est2); x["b2"]["saida"] = "2026-10-06T10:00:00"
ok(_bloqueia(x, regs_t2, dd), "check 16: saída ANTES da última vez visto (data e hora) bloqueia")
x = _cp.deepcopy(est2); x["b2"]["visto_primeira"] = "2026-10-06T18:00:00"
ok(_bloqueia(x, regs_t2, dd), "check 16: primeira vez visto depois da última bloqueia")
x = _cp.deepcopy(est2); x["b2"]["saida"] = "2026-10-06"
ok(_bloqueia(x, regs_t2, dd), "check 16: data sem hora bloqueia")
x = _cp.deepcopy(est2); x["a1"]["mudancas_preco"] = [["2026-10-05T10:00:00", 950_000]]
ok(_bloqueia(x, regs_t2, dd), "check 16: mudança de preço antes da primeira vez visto bloqueia")
# Arquivo antigo (só data) é convertido ao carregar, sem perder dados
with tempfile.TemporaryDirectory() as tmp:
    arq = Path(tmp) / "h.jsonl"
    ha.salvar(est3, arq)
    ok(ha.carregar(arq) == est3, "histórico: gravar e ler o arquivo devolve o mesmo conteúdo")
    velho = {"codigo": "z9", "bairro": "Moema", "endereco": "R", "complemento": None, "tipo": "casa", "area": 90, "addr_key": "k", "preco_inicial": 5, "preco_atual": 6,
             "mudancas_preco": [["2026-10-06", 6]], "cadastro": "2026-01-01", "visto_primeira": "2026-10-06", "visto_ultima": "2026-10-06", "saida": "2026-10-06"}
    arq.write_text(json.dumps(velho) + "\n", encoding="utf-8")
    z = ha.carregar(arq)["z9"]
    ok(z["visto_primeira"] == "2026-10-06T00:00:00" and z["saida"] == "2026-10-06T23:59:59" and z["mudancas_preco"] == [["2026-10-06T00:00:00", 6]] and z["preco_atual"] == 6,
       "histórico: arquivo antigo (só data) vira data e hora sem perder dados, mantendo primeira <= última < saída")
    arq.write_text('{"codigo":"x"\n', encoding="utf-8")
    try:
        ha.carregar(arq)
        ok(False, "histórico: arquivo corrompido deveria parar o build")
    except SystemExit:
        ok(True, "histórico: arquivo corrompido para o build em vez de ser sobrescrito")
    arq.write_text('{"codigo":"x"}\n{"codigo":"x"}\n', encoding="utf-8")
    try:
        ha.carregar(arq)
        ok(False, "histórico: código repetido deveria parar o build")
    except SystemExit:
        ok(True, "histórico: código repetido para o build")
ok(ha.data_brasilia(datetime.datetime(2026, 10, 7, 2, 30, tzinfo=datetime.timezone.utc)) == "2026-10-06", "histórico: data em horário de Brasília (02:30 UTC ainda é o dia anterior)")
ok(ha.agora_brasilia(datetime.datetime(2026, 10, 7, 2, 30, 5, tzinfo=datetime.timezone.utc)) == "2026-10-06T23:30:05", "histórico: data e hora em horário de Brasília")

# ---------------------------------------------------------------------------
# 3c. Rodada C: forma de pagamento (ITBI) e contexto de crédito (Banco Central)
# ---------------------------------------------------------------------------
import engine as _eng
import bcb_client as _bcb

ok(_eng.categoria_pagamento(None) == "a_vista" and _eng.categoria_pagamento("") == "a_vista" and _eng.categoria_pagamento("1.Sistema Financeiro de Habitação") == "sfh"
   and _eng.categoria_pagamento("2.Minha Casa Minha Vida") == "mcmv" and _eng.categoria_pagamento("3.Consórcio") == "consorcio"
   and _eng.categoria_pagamento("99.SFI, Carteira Hipotecária, etc") == "sfi" and _eng.categoria_pagamento("7.Qualquer coisa nova") == "outros",
   "pagamento: categorias pelo texto do Tipo de Financiamento (vazio = à vista, texto novo = outros)")


def _r(tipo, valor, vf):
    return {"tipo_financiamento": tipo, "valor": valor, "valor_financiado": vf}


amostra = ([_r(None, 1_000_000, 0)] * 6 + [_r("1.Sistema Financeiro de Habitação", 1_000_000, 700_000)] * 12 + [_r("2.Minha Casa Minha Vida", 300_000, 240_000)] * 3
           + [_r("3.Consórcio", 500_000, 400_000)] * 2 + [_r("99.SFI, Carteira Hipotecária, etc", 800_000, 400_000)])
pf = _eng.perfil_pagamento(amostra)
ok(pf["n_vendas"] == 24 and abs(sum(pf["pct"].values()) - 100.0) < 1e-9 and sum(pf["contagem"].values()) == 24, "pagamento: percentuais somam exatamente 100% e a contagem bate")
ok(pf["pct"]["a_vista"] == 25.0 and pf["financiamento_bancario_pct"] == 66.7 and pf["pct"]["consorcio"] == 8.3, "pagamento: à vista 25%, financiamento de banco 66,7% (SFH+MCMV+SFI), consórcio à parte")
ok(pf["pct_financiado_mediana"] == 70.0 and pf["n_financiadas_com_valor"] == 16, "pagamento: mediana do % financiado só entre as financiadas por banco (SFH/MCMV/SFI) com valor")
# 33 casos de arredondamento: sempre 100,0
import random
random.seed(3)
for _ in range(200):
    c = {k: random.randint(0, 40) for k in _eng.PAGAMENTO_CATEGORIAS}
    if sum(c.values()) == 0:
        continue
    assert abs(sum(_eng._percentuais_somando_100(c, sum(c.values())).values()) - 100.0) < 1e-9
ok(True, "pagamento: 200 sorteios de contagens — os percentuais arredondados sempre somam 100,0")
incons = _eng.perfil_pagamento([_r(None, 100_000, 50_000), _r("1.Sistema Financeiro de Habitação", 100_000, 0), _r("1.Sistema Financeiro de Habitação", 100_000, -5_000), _r("1.Sistema Financeiro de Habitação", 100_000, 200_000)])
ok(incons["n_inconsistentes"] == 4 and incons["pct_financiado_mediana"] is None and incons["pct"]["a_vista"] == 25.0,
   "pagamento: sem tipo mas com valor financiado, e com tipo mas valor 0/negativo/acima da venda, contam como inconsistentes e não entram na mediana")
ok(_eng.perfil_pagamento([]) is None, "pagamento: lista vazia não vira perfil")
ok(_eng.perfil_pagamento([_r("1.Sistema Financeiro de Habitação", 1_000_000, 500_000)] * 5)["pct_financiado_mediana"] is None, "pagamento: menos de 10 compras financiadas não gera mediana")

# --- Banco Central: série falsa, fuso, futuro, fallback ---
hoje_ = datetime.date(2026, 10, 7)
D = datetime.date
mensal = [(D(2025, m, 1), 10.0 + m / 10) for m in range(8, 13)] + [(D(2026, m, 1), 11.0 + m / 10) for m in range(1, 9)]
diaria = [(D(2025, 10, 6), 15.0), (D(2025, 10, 7), 15.0), (D(2026, 9, 7), 14.0), (D(2026, 10, 7), 13.75)]


def _falsa(cod, hj):
    if cod == 432:
        return diaria
    if cod in (20772, 20773, 13522):
        return mensal
    raise RuntimeError("fora do ar")


agora_ = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=datetime.timezone.utc)
ctx1 = _bcb.buscar_contexto(agora=agora_, buscar=_falsa)
sel = next(x for x in ctx1["series"] if x["id"] == "selic")
ok(sel["valor"] == 13.75 and sel["valor_mes_anterior"] == 14.0 and sel["var_mes_pp"] == -0.25 and sel["valor_12m"] == 15.0 and sel["var_12m_pp"] == -1.25, "banco central: valor atual, mês anterior e 12 meses atrás da Selic (diária)")
ip = next(x for x in ctx1["series"] if x["id"] == "ipca_12m")
ok(ip["data"] == "2026-08-01" and ip["valor_mes_anterior"] == mensal[-2][1] and ip["valor_12m"] == mensal[-13][1] if len(mensal) >= 13 else ip["valor_12m"] is not None, "banco central: série mensal usa o ponto anterior e o de 12 meses atrás")
ok(not ctx1["falhas"] and all(not x["desatualizado"] and x["fonte"].startswith("Banco Central") and x["explicacao"] for x in ctx1["series"]), "banco central: com a API ok nada fica desatualizado e toda série traz fonte e explicação")


def _quebrada(cod, hj):
    raise RuntimeError("API fora do ar")


ctx2 = _bcb.buscar_contexto(anterior=ctx1, agora=agora_ + datetime.timedelta(days=1), buscar=_quebrada)
ok(len(ctx2["falhas"]) == 4 and all(x["desatualizado"] and x["valor"] is not None and x["data"] == y["data"] and x["erro"] for x, y in zip(ctx2["series"], ctx1["series"])),
   "banco central: API fora do ar mantém o último valor bom (com a data dele) e marca desatualizado — não levanta erro")
ctx3 = _bcb.buscar_contexto(anterior=None, agora=agora_, buscar=_quebrada)
ok(all(x["valor"] is None and x["desatualizado"] for x in ctx3["series"]), "banco central: sem valor guardado e sem API, a série fica vazia mas o build não quebra")
ctx4 = _bcb.buscar_contexto(anterior=ctx1, agora=agora_, buscar=lambda c, h: _falsa(c, h) if c != 13522 else (_ for _ in ()).throw(RuntimeError("só o IPCA falhou")))
ok(ctx4["falhas"] == ["ipca_12m"] and [x["desatualizado"] for x in ctx4["series"]] == [False, False, False, True], "banco central: falha de UMA série não afeta as outras")
# filtro de datas futuras (a série da Selic traz dias que ainda não chegaram)
import json as _json


class _Resp:
    def __init__(self, corpo): self.corpo = corpo
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self.corpo


fut = _json.dumps([{"data": "06/10/2026", "valor": "13.75"}, {"data": "07/10/2026", "valor": "13.75"}, {"data": "02/11/2026", "valor": "99.0"}]).encode()
pts = _bcb.buscar_pontos(432, hoje_, abrir=lambda req, timeout: _Resp(fut))
ok(pts[-1] == (D(2026, 10, 7), 13.75) and all(p[0] <= hoje_ for p in pts), "banco central: datas futuras da API são descartadas")

# relatório semanal com a seção de crédito
_c = copy.deepcopy(json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))) if (ROOT / "site" / "data.json").exists() else None
if _c is not None and "contexto_credito" in _c:
    alertas_ = []
    linhas_ = rel.secao_credito(_c, alertas_)
    ok(any("Selic" in x for x in linhas_) and not alertas_, "relatório: seção de contexto de crédito com os números (sem alerta quando tudo atualizou)")
    _c["contexto_credito"] = ctx2
    alertas_ = []
    linhas_ = rel.secao_credito(_c, alertas_)
    ok(len(alertas_) == 4 and any("dado de" in x for x in linhas_), "relatório: série desatualizada aparece com 'dado de [data]' e vira alerta da semana")

# ---------------------------------------------------------------------------
# 4. relatório com os dados reais do repositório (histórico do Git)
# ---------------------------------------------------------------------------
try:
    real = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    if "n_sem_dado_recente" in (real["meta"]["fontes"].get("google_busca") or {}):
        ref = rel.ref_semana_anterior(datetime.datetime.now(datetime.timezone.utc))
        antigo = rel.data_json_em(ref) if ref else None
        t, c, a = rel.montar_relatorio(real, antigo, datetime.datetime.now(datetime.timezone.utc))
        ok(len(c) > 500 and "## 5." in c, f"relatório com dados reais ({len(a)} alerta(s), semana anterior {'encontrada' if antigo else 'ausente'})")
except Exception as e:  # noqa: BLE001
    ok(False, f"relatório com dados reais levantou {e!r}")

print()
if falhas:
    print(f"{len(falhas)} teste(s) falharam:")
    for f in falhas:
        print("  -", f)
    sys.exit(1)
print("Todos os testes da rotina passaram.")
