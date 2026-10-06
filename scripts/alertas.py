#!/usr/bin/env python3
"""
Alerta imediato (Passo 5, 2026-10-06): quando a atualização diária TRAVA (um
dos checks de segurança do validate_build barrou a publicação, a planilha do
ITBI veio num formato novo, a nonStop não respondeu...), cria na hora uma
Issue "⚠ Atualização travada" no repositório, em linguagem simples — o GitHub
avisa por e-mail (a Issue é atribuída ao dono do repositório).

Usado pelo workflow .github/workflows/build-data.yml:
  python3 scripts/alertas.py travada --log build.log   (passo `if: failure()`)
  python3 scripts/alertas.py resolvida                 (passo `if: success()`:
      fecha a Issue de alerta aberta, com um comentário)
  python3 scripts/alertas.py travada --log x.log --teste   (cria e fecha na
      hora uma Issue "[TESTE]" — pra conferir permissões e e-mail)

Só biblioteca padrão. Variáveis: GITHUB_TOKEN, GITHUB_REPOSITORY,
GITHUB_RUN_ID, GITHUB_SERVER_URL, GITHUB_REPOSITORY_OWNER (todas já
existem dentro do GitHub Actions). `--dry-run` só imprime.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    TZ_BR = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem tzdata: Brasília = UTC-3 fixo (sem horário de verão desde 2019)
    TZ_BR = datetime.timezone(datetime.timedelta(hours=-3))

ROOT = Path(__file__).resolve().parent.parent
TITULO = "⚠ Atualização travada"
LABEL = "alerta"


def agora_br(agora=None):
    return (agora or datetime.datetime.now(datetime.timezone.utc)).astimezone(TZ_BR)


def fmt_br(dt):
    return dt.astimezone(TZ_BR).strftime("%d/%m/%Y às %H:%M")


# ---------------------------------------------------------------------------
# Motivo em linguagem simples a partir do log do build
# ---------------------------------------------------------------------------
REGRAS = [
    ("estoque válido da nonStop caiu", "queda_estoque",
     "A nonStop devolveu **muito menos anúncios** do que na última atualização (queda acima de 30%). "
     "Pode ser um problema na integração (token, filtro de imóveis) e não uma queda real do mercado, "
     "então o site NÃO foi atualizado pra não publicar um estoque pela metade."),
    ("layout de coluna inesperado", "formato_itbi",
     "A planilha do ITBI da Prefeitura veio com um **formato diferente** (colunas mudaram de lugar, de nome ou sumiram). "
     "O site não foi atualizado porque os números poderiam sair errados — o leitor da planilha precisa de ajuste."),
    ("reconciliação de linhas falhou", "linhas_itbi",
     "O número de linhas lidas da planilha do ITBI **não bate** com o total que está na planilha. "
     "Pode ser arquivo incompleto ou mudança de formato."),
    ("variação de volume_primary_year", "variacao_bairros",
     "Um ou mais bairros tiveram **variação de volume de vendas acima de 30%** em relação à versão publicada, "
     "o que normalmente indica mudança de metodologia ou dado quebrado — o site não foi atualizado."),
    ("consistência carteira_77", "carteira_77",
     "Os painéis **divergiram do Carteira 77** (a base de referência de vendas por bairro). Isso nunca deveria acontecer."),
    ("cálculo de preço fora da camada limpa", "camada_limpa",
     "Algum cálculo de preço **não está usando a regra única de limpeza** do ITBI — o site não foi atualizado."),
    ("faixas de preço fora da regra", "faixas_amostra",
     "As faixas de preço **não seguem a regra de amostra** (12/24/36 meses, mínimo de 30 vendas) — o site não foi atualizado."),
    ("Captação Ativa fora da regra", "captacao",
     "A **Captação Ativa** saiu fora da regra de revenda limpa/mediana — o site não foi atualizado."),
    ("selos/idade/bônus", "selos",
     "Os **selos de estoque, a idade dos anúncios ou o bônus de captação** ficaram inconsistentes — o site não foi atualizado."),
    ("duplicado(s)", "duplicatas",
     "Apareceram **anúncios duplicados** no estoque da nonStop depois da limpeza — o site não foi atualizado."),
    ("datas de busca do Google", "google",
     "As **datas de busca do Google por bairro** ficaram incoerentes — o site não foi atualizado."),
    ("Rodada A —", "rodada_a",
     "A conferência da **Prontidão, do Valor de Oportunidade de apartamentos ou do Top 30 da Captação** deu diferença — o site não foi atualizado."),
    ("histórico de anúncios incoerente", "historico_anuncios",
     "O **histórico de anúncios** ficou incoerente com os anúncios da rede de hoje — o site não foi atualizado e o arquivo do histórico não foi alterado."),
    ("perfil vencedor v1", "perfil_v1", "Um painel voltou a usar o cálculo antigo de perfil por metragem — o site não foi atualizado."),
    ("faixa_metragem() voltou", "faixa_metragem", "Voltou a comparação antiga por metragem em apartamento — o site não foi atualizado."),
]


def explicar_motivo(log):
    """Retorna (categoria, texto_simples, detalhe_tecnico)."""
    m = re.search(r"\[validate_build\] FALHOU — publicação bloqueada: (.*?)(?=\n\[|\Z)", log, re.S)
    if m:
        detalhe = m.group(1).strip()
        for chave, categoria, texto in REGRAS:
            if chave in detalhe:
                return categoria, texto, detalhe
        return ("check", "Uma **conferência interna de qualidade** barrou a publicação (detalhe técnico abaixo). "
                "O site não foi atualizado.", detalhe)
    if "Nenhum .xlsx de ITBI em cache" in log:
        return ("itbi_download", "Não consegui **baixar a planilha do ITBI** da Prefeitura e não há cópia guardada pra usar no lugar.",
                "Nenhum .xlsx de ITBI em cache e a sincronização com a Prefeitura falhou.")
    m = re.search(r"nonStop API (\d{3}) em ([^\n:]*)", log)
    if m:
        return ("nonstop_api", f"A **nonStop recusou ou não respondeu** (erro {m.group(1)}). Pode ser token vencido/revogado ou instabilidade deles.",
                m.group(0))
    if "NONSTOP_TOKEN" in log and "Sem NONSTOP_TOKEN" in log:
        return ("nonstop_token", "O **token da nonStop não está configurado** neste ambiente.", "Sem NONSTOP_TOKEN e sem .xlsx de fallback.")
    if "Traceback (most recent call last)" in log:
        ultimas = "\n".join(log.strip().splitlines()[-6:])
        return ("erro_programa", "O programa deu um **erro inesperado** (provavelmente um bug ou um dado fora do que ele conhece).", ultimas)
    ultimas = "\n".join(log.strip().splitlines()[-6:]) if log.strip() else "(sem log)"
    return ("desconhecido", "A atualização **falhou antes de terminar**. O site continua com a última versão boa.", ultimas)


def ultima_atualizacao_boa():
    """Data do data.json publicado (o que continua no ar quando a execução trava)."""
    try:
        d = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
        return datetime.datetime.fromisoformat(d["generated_at_iso"])
    except Exception:
        return None


def montar_issue(log, run_url, teste=False, agora=None):
    categoria, texto, detalhe = explicar_motivo(log)
    boa = ultima_atualizacao_boa()
    quando = fmt_br(agora_br(agora))
    linhas = [
        "## ⚠ A atualização diária do dashboard travou" + (" (TESTE — pode ignorar)" if teste else ""),
        "",
        f"**Quando:** {quando} (Brasília)",
        "",
        f"**O que aconteceu:** {texto}",
        "",
        "**E o que está no ar?** "
        + (f"O site continua com a última atualização boa, de **{fmt_br(boa)}**. Nada errado foi publicado." if boa
           else "O site continua com a última versão boa. Nada errado foi publicado."),
        "",
    ]
    if categoria == "queda_estoque":
        linhas += ["**Se a queda for real e esperada:** rode a atualização de novo com `ALLOW_LARGE_CHANGES=1`.", ""]
    linhas += [
        f"**Ver a execução:** {run_url}" if run_url else "**Ver a execução:** aba Actions do repositório.",
        "",
        "<details><summary>Detalhe técnico</summary>",
        "",
        "```",
        detalhe[:3000],
        "```",
        "</details>",
    ]
    return {"categoria": categoria, "titulo": TITULO + (" [TESTE]" if teste else ""), "corpo": "\n".join(linhas)}


# ---------------------------------------------------------------------------
# GitHub (REST)
# ---------------------------------------------------------------------------
class GitHub:
    def __init__(self):
        self.token = os.environ["GITHUB_TOKEN"]
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.base = os.environ.get("GITHUB_API_URL", "https://api.github.com")

    def req(self, metodo, caminho, corpo=None, ok_status=()):
        data = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        r = urllib.request.Request(
            f"{self.base}/repos/{self.repo}{caminho}", data=data, method=metodo,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "dashboard-imoveis-sp-rotina"},
        )
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                txt = resp.read().decode("utf-8")
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            if e.code in ok_status:
                return None
            raise RuntimeError(f"GitHub API {metodo} {caminho} -> {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}") from e

    def garantir_label(self, nome, cor, descricao):
        self.req("POST", "/labels", {"name": nome, "color": cor, "description": descricao}, ok_status=(422,))

    def issues_abertas(self, label):
        return self.req("GET", f"/issues?state=open&labels={urllib.request.quote(label)}&per_page=100") or []

    def criar_issue(self, titulo, corpo, labels):
        dono = os.environ.get("GITHUB_REPOSITORY_OWNER") or self.repo.split("/")[0]
        try:
            return self.req("POST", "/issues", {"title": titulo, "body": corpo, "labels": labels, "assignees": [dono]})
        except RuntimeError as e:
            if "422" in str(e):  # assignee inválido: cria sem atribuir
                return self.req("POST", "/issues", {"title": titulo, "body": corpo, "labels": labels})
            raise

    def comentar(self, numero, texto):
        self.req("POST", f"/issues/{numero}/comments", {"body": texto})

    def fechar(self, numero):
        self.req("PATCH", f"/issues/{numero}", {"state": "closed", "state_reason": "completed"})


def cmd_travada(args):
    log = Path(args.log).read_text(encoding="utf-8", errors="ignore") if args.log and Path(args.log).exists() else ""
    if args.teste and not log:
        log = "[validate_build] FALHOU — publicação bloqueada: estoque válido da nonStop caiu 50.0% (de 2000 para 1000 anúncios após deduplicação) — TESTE do alerta"
    run_url = None
    if os.environ.get("GITHUB_RUN_ID") and os.environ.get("GITHUB_REPOSITORY"):
        run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    issue = montar_issue(log, run_url, teste=args.teste)
    if args.dry_run:
        print(issue["titulo"]); print(); print(issue["corpo"]); return 0
    gh = GitHub()
    gh.garantir_label(LABEL, "d73a4a", "Alerta imediato da rotina de conferência")
    if not args.teste:
        for i in gh.issues_abertas(LABEL):
            if i["title"] == TITULO:
                gh.comentar(i["number"], f"Travou **de novo** em {fmt_br(agora_br())}.\n\n{issue['corpo']}")
                print(f"[alertas] Issue #{i['number']} já aberta — comentário adicionado.")
                return 0
    criada = gh.criar_issue(issue["titulo"], issue["corpo"], [LABEL])
    print(f"[alertas] Issue criada: {criada['html_url']}")
    if args.teste:
        gh.comentar(criada["number"], "Teste do alerta — fechando automaticamente.")
        gh.fechar(criada["number"])
    return 0


def cmd_resolvida(args):
    if args.dry_run:
        print("(dry-run) fecharia a Issue de alerta aberta, se houver."); return 0
    gh = GitHub()
    for i in gh.issues_abertas(LABEL):
        if i["title"] == TITULO:
            gh.comentar(i["number"], f"✅ A atualização voltou a rodar normalmente em {fmt_br(agora_br())}. Fechando.")
            gh.fechar(i["number"])
            print(f"[alertas] Issue #{i['number']} fechada (atualização normalizada).")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("travada"); t.add_argument("--log"); t.add_argument("--teste", action="store_true"); t.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("resolvida"); r.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        return cmd_travada(args) if args.cmd == "travada" else cmd_resolvida(args)
    except Exception as e:  # o alerta nunca pode derrubar o passo que o chamou com erro mudo
        print(f"[alertas] não consegui falar com o GitHub: {e}", file=sys.stderr)
        return 0 if args.cmd == "resolvida" else 1


if __name__ == "__main__":
    sys.exit(main())
