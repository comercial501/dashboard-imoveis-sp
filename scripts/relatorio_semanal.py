#!/usr/bin/env python3
"""
Relatório semanal de conferência (Passo 5, 2026-10-06). Toda segunda, depois da
atualização diária das 8h, cria uma Issue no repositório (o GitHub avisa por
e-mail — a Issue é atribuída ao dono) com, em linguagem simples:
  a) data de cada fonte (ITBI, nonStop, Google por bairro) e fonte parada;
  b) atualizações diárias da semana: quantas rodaram e quantas falharam;
  c) bairros com variação > 20% na semana (revenda 12m, estoque da rede, nota
     do Prontidão), com a causa provável;
  d) top 10 do Prontidão: esta semana × semana anterior;
  e) estoque da rede: total, novos, saíram, % com selo "anúncio antigo";
  f) "Semana sem alertas" na primeira linha quando está tudo normal.
E fecha sozinha a Issue da semana anterior.

A "semana anterior" vem do histórico do Git: o último site/data.json
commitado até 7 dias antes (a Action diária commita o data.json). Por isso o
workflow faz checkout com histórico completo.

Uso:
  python3 scripts/relatorio_semanal.py --saida relatorio.md          (só gera o texto)
  python3 scripts/relatorio_semanal.py --criar-issue                 (no GitHub Actions)
Só biblioteca padrão. Variáveis (no Actions): GITHUB_TOKEN, GITHUB_REPOSITORY,
GITHUB_REPOSITORY_OWNER.
"""
import argparse
import datetime
import email.utils
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alertas import GitHub, TZ_BR, fmt_br  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LABEL = "relatorio-semanal"
WORKFLOW_DIARIO = "build-data.yml"

# Limites de "fonte parada" (pedido: 7 dias; ITBI: 45). O Google é mensal por
# natureza (o painel só diz "sem dado recente" depois de 30 dias), então usa o
# mesmo limite do painel — senão alertaria toda semana por desenho.
LIMITE_NONSTOP_DIAS = 7
LIMITE_ITBI_DIAS = 45
LIMITE_GOOGLE_DIAS = 30
# Variação semanal: > 20% E uma mudança mínima em números absolutos (evita
# alertar "3 -> 4 anúncios").
VARIACAO_PCT = 20.0
MIN_ABS = {"revenda_12m": 10, "stock_total": 5, "prontidao_campanha": 5}
MSG_SEM_COMPARACAO = ("ℹ Não há uma semana anterior **comparável** (o arquivo de 7 dias atrás é de uma versão antiga dos dados, "
                      "com outros campos/metodologia, ou não existe). A comparação semanal começa na primeira semana em que as duas pontas são iguais.")
ROTULO = {"revenda_12m": "Revendas em 12 meses", "stock_total": "Estoque da rede (anúncios)", "prontidao_campanha": "Nota do Prontidão"}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def data_json_em(ref):
    return json.loads(git("show", f"{ref}:site/data.json"))


def ref_semana_anterior(agora):
    """Último commit que mexeu em site/data.json até 7 dias antes de `agora`."""
    limite = (agora - datetime.timedelta(days=7)).isoformat()
    ref = git("log", f"--until={limite}", "-1", "--format=%H", "--", "site/data.json").strip()
    return ref or None


def dias_desde(iso_ou_http, agora):
    if not iso_ou_http:
        return None
    try:
        dt = datetime.datetime.fromisoformat(iso_ou_http)
    except ValueError:
        dt = email.utils.parsedate_to_datetime(iso_ou_http)  # "Wed, 30 Sep 2026 13:52:43 GMT"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return (agora - dt).total_seconds() / 86400


def gerado_em(d):
    """Instante de geração do data.json (iso novo, ou o texto antigo 'Tue Oct 06 01:48:01 2026 UTC')."""
    if d.get("generated_at_iso"):
        return datetime.datetime.fromisoformat(d["generated_at_iso"])
    return datetime.datetime.strptime(d["generated_at"], "%a %b %d %H:%M:%S %Y UTC").replace(tzinfo=datetime.timezone.utc)


CAMPOS_COMPARAVEIS = ("revenda_12m", "stock_total", "prontidao_campanha", "amostra_pequena_ranking")


def comparavel(d):
    """O data.json da semana anterior tem a estrutura que o relatório compara?
    (versões antigas — outra metodologia, outros campos — não servem; a
    comparação começa na primeira semana em que as duas pontas são iguais.)"""
    try:
        b = next(iter(d["bairros"].values()))
        return (all(c in b for c in CAMPOS_COMPARAVEIS) and "prontidao_ranking" in d and "imoveis_prioritarios" in d
                and "rows_apos_dedup" in d["meta"]["usn"])
    except Exception:
        return False


def so_data(iso):
    dt = iso if isinstance(iso, datetime.datetime) else datetime.datetime.fromisoformat(iso)
    return dt.astimezone(TZ_BR).strftime("%d/%m/%Y")


def mes_ano(ym):
    a, m = ym.split("-")
    return f"{['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'][int(m)-1]}/{a}"


# ---------------------------------------------------------------------------
# a) fontes
# ---------------------------------------------------------------------------
def secao_fontes(d, agora, alertas):
    f = d["meta"]["fontes"]
    linhas = ["## 1. Datas de cada fonte", "", "| Fonte | Como atualiza | Última atualização | Situação |", "|---|---|---|---|"]
    # ITBI
    itbi = f["itbi"]
    dias = dias_desde(itbi.get("arquivo_atualizado_em"), agora)
    if dias is None:
        dias = 9999  # sem data do arquivo: trata como parado
    mes = mes_ano(itbi["ultimo_mes_dado"])
    parada = (dias is not None and dias > LIMITE_ITBI_DIAS) or itbi.get("sync_ok") is False
    if parada:
        motivo = "falha ao baixar da Prefeitura (usando cópia antiga)" if itbi.get("sync_ok") is False else f"arquivo parado há {dias:.0f} dias (limite {LIMITE_ITBI_DIAS})"
        alertas.append(f"ITBI parado: {motivo}")
    linhas.append(f"| ITBI (Prefeitura) | mensal | arquivo de {so_data(email.utils.parsedate_to_datetime(itbi['arquivo_atualizado_em']).isoformat())} "
                  f"({dias:.0f} dias) · último mês completo: {mes} | " + ("⚠ **parada** — " + motivo if parada else "✅ normal (a Prefeitura publica por mês)") + " |")
    # nonStop
    ns = f["nonstop"]["consultado_em"]
    dns = dias_desde(ns, agora)
    parada_ns = dns is None or dns > LIMITE_NONSTOP_DIAS
    if parada_ns:
        alertas.append(f"nonStop parada há {dns:.0f} dias (limite {LIMITE_NONSTOP_DIAS})")
    linhas.append(f"| nonStop (estoque da rede) | diária | {fmt_br(datetime.datetime.fromisoformat(ns))} ({dns*24:.0f} h atrás) | "
                  + (f"⚠ **parada há {dns:.0f} dias**" if parada_ns else "✅ normal") + " |")
    # Google
    g = f.get("google_busca")
    if g:
        sem = g["n_sem_dado_recente"]
        if sem:
            alertas.append(f"Google: {sem} bairro(s) sem dado recente (busca com mais de {LIMITE_GOOGLE_DIAS} dias)")
        periodo = so_data(g["mais_antiga"]) if so_data(g["mais_antiga"]) == so_data(g["mais_recente"]) else f"{so_data(g['mais_antiga'])} a {so_data(g['mais_recente'])}"
        linhas.append(f"| Google (buscas por bairro) | mensal, por bairro | {periodo} · {g['n_bairros_com_dado']} de {g['n_bairros_total']} bairros com busca | "
                      + (f"⚠ {sem} bairro(s) com busca de mais de {LIMITE_GOOGLE_DIAS} dias" if sem else "✅ normal (todas as buscas com menos de 30 dias)") + " |")
    else:
        linhas.append("| Google (buscas por bairro) | mensal, por bairro | sem dado | ℹ fonte não configurada |")
    linhas.append("")
    # datas por bairro, agrupadas
    bs = {}
    for nome, v in d["bairros"].items():
        si = v.get("search_interest")
        if si:
            bs.setdefault(so_data(si["fetched_at"]), []).append(nome)
    if bs:
        linhas.append("<details><summary>Data da busca do Google por bairro</summary>\n")
        for dia, nomes in sorted(bs.items(), key=lambda x: datetime.datetime.strptime(x[0], "%d/%m/%Y")):
            linhas.append(f"- **{dia}**: {len(nomes)} bairros — " + ", ".join(sorted(nomes)))
        linhas.append("\n</details>\n")
    return linhas


# ---------------------------------------------------------------------------
# b) execuções diárias
# ---------------------------------------------------------------------------
def execucoes_da_semana(agora):
    """(rodaram, falharam, canceladas, lista_falhas, fonte). Usa a API do
    GitHub dentro do Actions; fora dele, estima só pelos commits do data.json."""
    desde = (agora - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        gh = GitHub()
        resp = gh.req("GET", f"/actions/workflows/{WORKFLOW_DIARIO}/runs?created=%3E%3D{desde}&per_page=100&status=completed") or {}
        runs = resp.get("workflow_runs", [])
        ok = [r for r in runs if r["conclusion"] == "success"]
        falhas = [r for r in runs if r["conclusion"] in ("failure", "timed_out")]
        canc = [r for r in runs if r["conclusion"] == "cancelled"]
        return len(runs), len(falhas), len(canc), [(r["created_at"], r["html_url"]) for r in falhas], "API do GitHub"
    commits = git("log", f"--since={desde}", "--format=%H", "--grep=chore: atualizar data.json").split()
    return None, None, None, [], f"estimativa pelo histórico ({len(commits)} dias com dado novo); a contagem de falhas só existe dentro do GitHub Actions"


def secao_execucoes(agora, alertas):
    rodaram, falharam, canc, lista, fonte = execucoes_da_semana(agora)
    linhas = ["## 2. Atualizações diárias da semana", ""]
    if rodaram is None:
        linhas += [f"ℹ Não consegui consultar as execuções ({fonte}).", ""]
        return linhas
    linhas.append(f"**{rodaram} execuções** nos últimos 7 dias: **{rodaram - falharam - canc} com sucesso**, **{falharam} falharam**"
                  + (f", {canc} canceladas" if canc else "") + ".")
    if falharam:
        alertas.append(f"{falharam} atualização(ões) diária(s) falharam na semana")
        linhas += [""] + [f"- ⚠ Falhou em {fmt_br(datetime.datetime.fromisoformat(t.replace('Z', '+00:00')))} — [ver execução]({u})" for t, u in lista]
    linhas.append("")
    return linhas


# ---------------------------------------------------------------------------
# c) variações > 20%
# ---------------------------------------------------------------------------
def variacoes(d_novo, d_velho):
    """{campo: [(bairro, antigo, novo, pct, amostra_pequena)]}"""
    out = {c: [] for c in MIN_ABS}
    for b, v in d_novo["bairros"].items():
        o = d_velho["bairros"].get(b)
        if not o:
            continue
        for c, minimo in MIN_ABS.items():
            a, n = o.get(c), v.get(c)
            if a is None or n is None or a == 0:
                continue
            pct = (n - a) / a * 100
            if abs(pct) > VARIACAO_PCT and abs(n - a) >= minimo:
                out[c].append((b, a, n, pct, bool(v.get("amostra_pequena_ranking"))))
    for c in out:
        out[c].sort(key=lambda x: -abs(x[3]))
    return out


def codigos_por_bairro(d):
    r = {}
    for i in d.get("imoveis_prioritarios", []):
        r.setdefault(i["bairro"], set()).add(i["codigo"])
    return r


def causa_provavel(campo, b, d_novo, d_velho, cod_novo, cod_velho):
    vn, vo = d_novo["bairros"][b], d_velho["bairros"][b]
    if campo == "revenda_12m":
        if d_novo["periodo_12m"]["fim"] != d_velho["periodo_12m"]["fim"]:
            return f"a janela de 12 meses avançou ({mes_ano(d_velho['periodo_12m']['fim'])} → {mes_ano(d_novo['periodo_12m']['fim'])})"
        if (d_novo["meta"].get("fontes") or {}).get("itbi", {}).get("arquivo_atualizado_em") != (d_velho["meta"].get("fontes") or {}).get("itbi", {}).get("arquivo_atualizado_em"):
            return "a Prefeitura publicou uma planilha nova do ITBI"
        return "guias novas ou atrasadas do ITBI entraram no período"
    if campo == "stock_total":
        novos = len(cod_novo.get(b, set()) - cod_velho.get(b, set()))
        sairam = len(cod_velho.get(b, set()) - cod_novo.get(b, set()))
        return f"{novos} anúncio(s) novo(s) na rede e {sairam} que saiu(ram)"
    causas = []
    if vn["revenda_12m"] != vo.get("revenda_12m"):
        causas.append(f"revendas {vo.get('revenda_12m')} → {vn['revenda_12m']}")
    if vn["estoque_perfil_faixa_preco"] != vo.get("estoque_perfil_faixa_preco"):
        causas.append(f"estoque da rede no perfil {vo.get('estoque_perfil_faixa_preco')} → {vn['estoque_perfil_faixa_preco']}")
    if vn.get("selo_escassez_real") != vo.get("selo_escassez_real") or vn.get("estoque_fora_do_perfil") != vo.get("estoque_fora_do_perfil"):
        causas.append("mudou um selo de estoque")
    if vn.get("perfil_vencedor_faixa_preco_v2_meta") != vo.get("perfil_vencedor_faixa_preco_v2_meta"):
        causas.append("mudou o período/amostra da faixa de preço")
    return "; ".join(causas) if causas else "mudança nos demais fatores (preço, captação, achados de valor)"


def secao_variacoes(d_novo, d_velho, alertas):
    linhas = ["## 3. Bairros com variação acima de 20% na semana", ""]
    if not d_velho or not comparavel(d_velho):
        return linhas + [MSG_SEM_COMPARACAO, ""]
    var = variacoes(d_novo, d_velho)
    cn, cv = codigos_por_bairro(d_novo), codigos_por_bairro(d_velho)
    n_grandes = 0
    for campo, itens in var.items():
        grandes = [x for x in itens if not x[4]]
        pequenos = [x for x in itens if x[4]]
        n_grandes += len(grandes)
        linhas.append(f"### {ROTULO[campo]}")
        if not itens:
            linhas += ["Nenhuma variação relevante.", ""]
            continue
        linhas += ["| Bairro | Antes | Agora | Variação | Causa provável |", "|---|---|---|---|---|"]
        for b, a, n, pct, pequeno in grandes + pequenos:
            fmt_ = (lambda x: f"{x:.1f}") if campo == "prontidao_campanha" else (lambda x: f"{x:g}")
            linhas.append(f"| {b}{' (amostra pequena)' if pequeno else ''} | {fmt_(a)} | {fmt_(n)} | {pct:+.0f}% | {causa_provavel(campo, b, d_novo, d_velho, cn, cv)} |")
        linhas.append("")
    linhas.append("_Só entram mudanças com variação acima de 20% **e** pelo menos 10 revendas / 5 anúncios / 5 pontos de nota. "
                  "Bairros de amostra pequena (menos de 100 revendas) aparecem na lista, mas só os bairros grandes contam como alerta._")
    linhas.append("")
    if n_grandes:
        alertas.append(f"{n_grandes} variação(ões) acima de 20% em bairros grandes")
    return linhas


# ---------------------------------------------------------------------------
# d) top 10 Prontidão
# ---------------------------------------------------------------------------
def secao_top10(d_novo, d_velho):
    linhas = ["## 4. Top 10 do Prontidão — esta semana × semana anterior", ""]
    novo = d_novo["prontidao_ranking"][:10]
    if not d_velho or not comparavel(d_velho):
        return linhas + [MSG_SEM_COMPARACAO, ""]
    velho = d_velho["prontidao_ranking"][:10]
    pos_velha = {b: i + 1 for i, b in enumerate(d_velho["prontidao_ranking"])}
    linhas += ["| # | Esta semana | Nota | Semana anterior | Nota | Movimento |", "|---|---|---|---|---|---|"]
    for i in range(10):
        b, o = novo[i], velho[i]
        mov = "🆕 entrou no top 10" if b not in velho else ("=" if pos_velha[b] == i + 1 else (f"↑ subiu de {pos_velha[b]}º" if pos_velha[b] > i + 1 else f"↓ caiu de {pos_velha[b]}º"))
        linhas.append(f"| {i + 1} | {b} | {d_novo['bairros'][b]['prontidao_campanha']:.1f} | {o} | {d_velho['bairros'][o]['prontidao_campanha']:.1f} | {mov} |")
    saiu = [b for b in velho if b not in novo]
    linhas += ["", ("Saiu do top 10: " + ", ".join(saiu) + ".") if saiu else "Os mesmos 10 bairros da semana anterior.", ""]
    return linhas


# ---------------------------------------------------------------------------
# e) estoque da rede
# ---------------------------------------------------------------------------
def secao_estoque(d_novo, d_velho):
    linhas = ["## 5. Estoque da rede nonStop", ""]
    cod_n = {i["codigo"] for i in d_novo["imoveis_prioritarios"]}
    total_n = d_novo["meta"]["usn"]["rows_apos_dedup"]
    antigos_n = sum(1 for i in d_novo["imoveis_prioritarios"] if i.get("anuncio_antigo"))
    pct_n = 100 * antigos_n / max(1, len(d_novo["imoveis_prioritarios"]))
    if not d_velho or not comparavel(d_velho):
        return linhas + [f"**{total_n} anúncios** · {pct_n:.1f}% com selo “anúncio antigo” (mais de 365 dias).", "", MSG_SEM_COMPARACAO, ""]
    cod_v = {i["codigo"] for i in d_velho["imoveis_prioritarios"]}
    total_v = d_velho["meta"]["usn"]["rows_apos_dedup"]
    ant_v = [i.get("anuncio_antigo") for i in d_velho["imoveis_prioritarios"]]
    pct_v = 100 * sum(1 for a in ant_v if a) / len(ant_v) if ant_v else 0
    linhas += [
        f"- **Total de anúncios:** {total_n} (semana anterior: {total_v}, {total_n - total_v:+d})",
        f"- **Novos na semana:** {len(cod_n - cod_v)}",
        f"- **Saíram da rede:** {len(cod_v - cod_n)}",
        f"- **Com selo “anúncio antigo” (mais de 365 dias):** {antigos_n} ({pct_n:.1f}%) — semana anterior: {pct_v:.1f}%",
        "",
        "_“Novos” e “saíram” comparam os códigos dos anúncios nas duas fotografias (pode incluir anúncios que a nonStop republicou com código novo)._",
        "",
    ]
    return linhas


# ---------------------------------------------------------------------------
def montar_relatorio(d_novo, d_velho, agora, ref_velha=None, banner=None):
    alertas = []
    corpo = []
    corpo += secao_fontes(d_novo, agora, alertas)
    corpo += secao_execucoes(agora, alertas)
    corpo += secao_variacoes(d_novo, d_velho, alertas)
    corpo += secao_top10(d_novo, d_velho)
    corpo += secao_estoque(d_novo, d_velho)
    topo = ["✅ **Semana sem alertas**"] if not alertas else [f"⚠ **{len(alertas)} alerta(s) nesta semana:**"] + [f"- {a}" for a in alertas]
    rodape = [
        "---",
        f"_Gerado automaticamente em {fmt_br(agora)} (Brasília). Dados de hoje: {so_data(gerado_em(d_novo))}"
        + (f" · comparado com: {so_data(gerado_em(d_velho))}" if d_velho and comparavel(d_velho) else "") + ". "
        "Esta Issue é fechada sozinha quando sai o relatório da semana seguinte._",
    ]
    titulo = f"Relatório semanal — {agora.astimezone(TZ_BR).strftime('%d/%m/%Y')}"
    if banner:
        topo = [f"> 🧪 **{banner}**", ""] + topo
    return titulo, "\n".join(topo + [""] + corpo + rodape), alertas


def esperar_atualizacao_do_dia(agora_fn, max_min=25):
    """Se a atualização diária de hoje ainda estiver rodando/na fila, espera
    (até max_min minutos) — o relatório sai DEPOIS dela."""
    if not (os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY")):
        return
    gh = GitHub()
    for _ in range(max_min):
        hoje = agora_fn().strftime("%Y-%m-%d")
        pend = []
        for st in ("in_progress", "queued"):
            pend += (gh.req("GET", f"/actions/workflows/{WORKFLOW_DIARIO}/runs?status={st}&created=%3E%3D{hoje}&per_page=5") or {}).get("workflow_runs", [])
        if not pend:
            return
        print(f"[relatorio] atualização diária ainda rodando ({len(pend)}) — esperando 1 min...")
        time.sleep(60)


def publicar(titulo, corpo):
    gh = GitHub()
    gh.garantir_label(LABEL, "0e8a16", "Relatório semanal de conferência (fechado sozinho na semana seguinte)")
    nova = gh.criar_issue(titulo, corpo, [LABEL])
    print(f"[relatorio] Issue criada: {nova['html_url']}")
    for i in gh.issues_abertas(LABEL):
        if i["number"] != nova["number"]:
            gh.comentar(i["number"], f"Fechada automaticamente: saiu o relatório da semana seguinte (#{nova['number']}).")
            gh.fechar(i["number"])
            print(f"[relatorio] Issue #{i['number']} (semana anterior) fechada.")
    return nova["html_url"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--saida", help="grava o relatório (markdown) neste arquivo")
    ap.add_argument("--criar-issue", action="store_true")
    ap.add_argument("--agora", help="ISO-8601 (só pra teste)")
    ap.add_argument("--sem-espera", action="store_true")
    ap.add_argument("--ref-anterior", help="commit do data.json da 'semana anterior' (só pra teste)")
    ap.add_argument("--banner", help="aviso colocado no topo (só pra teste)")
    args = ap.parse_args()

    agora = datetime.datetime.fromisoformat(args.agora) if args.agora else datetime.datetime.now(datetime.timezone.utc)
    if args.criar_issue and not args.sem_espera:
        esperar_atualizacao_do_dia(lambda: datetime.datetime.now(datetime.timezone.utc))
    d_novo = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    ref = args.ref_anterior or ref_semana_anterior(agora)
    d_velho = data_json_em(ref) if ref else None
    titulo, corpo, alertas = montar_relatorio(d_novo, d_velho, agora, ref, banner=args.banner)
    if args.saida:
        Path(args.saida).write_text(f"# {titulo}\n\n{corpo}\n", encoding="utf-8")
        print(f"[relatorio] escrito em {args.saida} ({len(alertas)} alerta(s))")
    if args.criar_issue:
        publicar(titulo, corpo)
    elif not args.saida:
        print(f"# {titulo}\n\n{corpo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
