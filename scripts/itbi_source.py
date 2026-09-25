#!/usr/bin/env python3
"""
Descoberta e download automático dos arquivos de ITBI da Prefeitura de SP.

Fonte: https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501
("Dados das Transações Imobiliárias com recolhimento de ITBI").

A Prefeitura publica um único .xlsx por ANO (todas as abas MES-ANO de
janeiro até o último mês fechado). O arquivo do ano corrente é atualizado
mensalmente (dados do mês anterior) — não há atualização diária na fonte,
por isso este módulo é feito para rodar todo dia mas só baixar de novo
quando o arquivo realmente mudou (checa Last-Modified/Content-Length antes
de baixar os ~25-50MB de cada ano).

A URL de cada ano muda com o tempo (o nome do arquivo do ano corrente
embute a data da última atualização, ex: "guias-de-itbi-pagas-27082026").
Por isso a URL nunca é hardcoded — este módulo sempre raspa a página pra
descobrir o link atual de cada ano.
"""
import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

PAGE_URL = "https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501"
USER_AGENT = (
    "Mozilla/5.0 (compatible; TopioImoveisDashboard/1.0; "
    "+https://github.com/comercial501/dashboard-imoveis-sp)"
)
REQUEST_TIMEOUT = 60

# Erros transitórios que valem retry (2026-09-25: o pipeline inteiro falhou
# uma vez por um 403 passageiro da Prefeitura — dia único num histórico de
# execuções diárias, os dias antes/depois funcionaram normal). Alguns
# códigos aqui são provavelmente bloqueio de WAF/rate-limit, não erro de
# verdade; um retry com espera resolve sem precisar de intervenção manual.
RETRYABLE_HTTP_CODES = {403, 408, 429, 500, 502, 503, 504}
RETRY_DELAYS_S = (5, 20, 60)  # 3 tentativas extras (4 no total) com backoff


def _urlopen_retry(req, timeout, log=print):
    """urlopen com retry/backoff pra erros transitórios (ver
    RETRYABLE_HTTP_CODES) — sem isso, uma falha passageira da Prefeitura
    derruba o pipeline inteiro do dia."""
    last_exc = None
    for attempt, delay in enumerate((0,) + RETRY_DELAYS_S):
        if delay:
            log(f"[itbi] tentativa {attempt + 1}/{len(RETRY_DELAYS_S) + 1} em {delay}s (erro anterior: {last_exc})...")
            time.sleep(delay)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code not in RETRYABLE_HTTP_CODES:
                raise
        except urllib.error.URLError as e:
            last_exc = e
    raise last_exc

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "itbi_raw"
STATE_FILE = ROOT / "data" / "itbi_state.json"

# Quantos anos manter localmente. O ranking/tendência (Painel 1) compara
# ano corrente vs. anterior vs. dois anos atrás — 3 anos é o que o motor de
# cálculo espera (ver itbi_methodology_spec.md, §8.2).
YEARS_BACK = 3


def _fetch_text(url, log=print):
    """GET e decodifica como texto usando o charset do Content-Type (ou utf-8)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _urlopen_retry(req, REQUEST_TIMEOUT, log=log) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")


def _fix_raw_url(url):
    """Corrige espaços literais em hrefs (a Prefeitura não escapa sempre) e
    resolve caminhos relativos. Não usa urllib.parse.quote porque isso
    re-escaparia sequências %XX que já vêm corretas em alguns links."""
    url = html.unescape(url)
    url = url.replace(" ", "%20")
    if url.startswith("/"):
        url = "https://prefeitura.sp.gov.br" + url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url


def discover_year_links(log=print):
    """Raspa a página da Prefeitura e retorna {ano: url_xlsx}.

    Cada item da lista de download é um <li> cujo texto começa com o ano
    (ex: "2026 (<a href=...>Excel/xlsx</a>) (<a href=...>ODS</a>)"), então
    o ano é lido diretamente do texto do <li> — não depende de posição.
    """
    body = _fetch_text(PAGE_URL, log=log)

    anchor = "Faça o download"
    idx = body.find(anchor)
    if idx == -1:
        raise RuntimeError(
            f"Não encontrei a âncora \"{anchor}\" na página da Prefeitura — "
            "o layout do site pode ter mudado. Confira manualmente: " + PAGE_URL
        )

    ul_match = re.search(r"<ul>(.*?)</ul>", body[idx:], re.S)
    if not ul_match:
        raise RuntimeError("Não encontrei a lista <ul> de downloads após a âncora esperada.")
    list_html = ul_match.group(1)

    years = {}
    for li_match in re.finditer(r"<li[^>]*>(.*?)</li>", list_html, re.S):
        li_html = li_match.group(1)
        year_match = re.search(r"(\d{4})\s*\(", li_html)
        if not year_match:
            continue
        year = int(year_match.group(1))
        xlsx_match = re.search(
            r'href="([^"]+)"[^>]*>\s*Excel/xlsx', li_html, re.I
        )
        if not xlsx_match:
            continue
        years[year] = _fix_raw_url(xlsx_match.group(1))
    return years


def _head_info(url, log=print):
    """Faz HEAD (via GET com Range mínimo — alguns servidores da Prefeitura
    não respondem bem a HEAD) e devolve (last_modified, content_length)."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with _urlopen_retry(req, REQUEST_TIMEOUT, log=log) as resp:
            return resp.headers.get("Last-Modified"), resp.headers.get("Content-Length")
    except urllib.error.HTTPError as e:
        if e.code == 405:  # método não permitido — cai pra GET normal
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with _urlopen_retry(req, REQUEST_TIMEOUT, log=log) as resp:
                return resp.headers.get("Last-Modified"), resp.headers.get("Content-Length")
        raise


def _load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def _save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def sync(target_years, log=print):
    """Garante que data/itbi_raw/<ano>.xlsx esteja atualizado para cada ano
    em target_years. Só baixa de novo quando Last-Modified/Content-Length
    mudou desde a última sincronização. Retorna o set de anos cujo arquivo
    local mudou nesta chamada (para o build_data.py saber o que reprocessar)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    links = discover_year_links(log=log)
    state = _load_state()
    changed = set()

    for year in target_years:
        url = links.get(year)
        if not url:
            log(f"[itbi] aviso: nenhum link encontrado pro ano {year} na página da Prefeitura — pulando.")
            continue

        last_modified, content_length = _head_info(url, log=log)
        prev = state.get(str(year), {})
        local_path = RAW_DIR / f"{year}.xlsx"

        same = (
            local_path.exists()
            and prev.get("url") == url
            and prev.get("last_modified") == last_modified
            and prev.get("content_length") == content_length
        )
        if same:
            log(f"[itbi] {year}: sem mudança desde a última execução (Last-Modified {last_modified}).")
            continue

        log(f"[itbi] {year}: baixando ({content_length or '?'} bytes, Last-Modified {last_modified})...")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with _urlopen_retry(req, max(REQUEST_TIMEOUT, 300), log=log) as resp:
            data = resp.read()
        local_path.write_bytes(data)

        state[str(year)] = {
            "url": url,
            "last_modified": last_modified,
            "content_length": content_length,
            "bytes_baixados": len(data),
        }
        changed.add(year)
        log(f"[itbi] {year}: atualizado ({len(data):,} bytes).")

    _save_state(state)
    return changed


if __name__ == "__main__":
    import datetime

    current_year = datetime.date.today().year
    target = list(range(current_year - YEARS_BACK + 1, current_year + 1))
    print(f"Anos alvo: {target}")
    changed_years = sync(target)
    print(f"Anos que mudaram: {sorted(changed_years) or 'nenhum'}")
