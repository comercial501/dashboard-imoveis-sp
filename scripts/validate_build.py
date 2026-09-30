#!/usr/bin/env python3
"""
Portão de segurança antes de publicar site/data.json — pedido do usuário em
2026-09-30 (o dashboard vai integrar no CRM e ser compartilhado com outros
corretores; "não pode quebrar em nenhum momento"). build_data.py chama
validate_before_publish() logo antes de sobrescrever site/data.json; se
qualquer checagem falhar, levanta SystemExit (sai com código != 0) e o
workflow do GitHub Actions para ANTES do passo de commit — a versão
publicada anterior nunca é sobrescrita por um build ruim.

Três checagens, na ordem em que o usuário pediu:
  1. linhas lidas == linhas da planilha (reconciliação exata, sheet a sheet)
  2. nenhum bairro com variação de volume_primary_year > 30% vs a versão
     publicada atual, a menos que ALLOW_LARGE_CHANGES=1 esteja no ambiente
     (mudança de metodologia deliberada — cada item desta auditoria passa
     por aprovação explícita do usuário antes, então quem liga essa var é
     sempre uma decisão humana, nunca o cron)
  3. formato de site/data.json tem todas as chaves/campos que os painéis
     do site/app.js esperam (checagem estrutural — não substitui abrir a
     dashboard num navegador de verdade, que é feito manualmente a cada
     item desta auditoria; é a rede de segurança pro build automático
     diário, que não tem navegador disponível).
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from normalize import TARGETS
from xlsx_reader import Workbook

SHEET_RE = re.compile(r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)-(\d{4})$")
VARIACAO_MAX = 0.30

# Item 1 do pedido de 2026-09-30: alarme se uma aba vier sem cabeçalho
# reconhecível, ou com as colunas que o pipeline efetivamente lê (por
# posição/letra — ver xlsx_reader.py) deslocadas ou renomeadas. Só cobre as
# 10 colunas que parse_itbi.py de fato consome — não trava por causa da
# bagunça de nome em Z/AA/AB (item 1b do diagnóstico: não usadas hoje).
# Texto exato confirmado em produção (ver diagnóstico de 2026-09-29/30).
EXPECTED_HEADERS = {
    "A": "N° do Cadastro (SQL)",
    "B": "Nome do Logradouro",
    "C": "Número",
    "E": "Bairro",
    "H": "Natureza de Transação",
    "I": "Valor de Transação (declarado pelo contribuinte)",
    "J": "Data de Transação",
    "L": "Proporção Transmitida (%)",
    "W": "Área Construída (m2)",
    "X": "Uso (IPTU)",
}
EXPECTED_COLUMN_COUNT = 28  # A..AB — ver diagnóstico: header sempre tem exatamente 28 colunas preenchidas


def _col_letter(n):
    """1 -> 'A', 26 -> 'Z', 27 -> 'AA', 28 -> 'AB'."""
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


EXPECTED_COLUMNS = [_col_letter(i) for i in range(1, EXPECTED_COLUMN_COUNT + 1)]

REQUIRED_TOP_KEYS = {
    "generated_at", "bairros", "ranking", "valor_oportunidade",
    "imoveis_prioritarios", "captacao_estrategica", "preco_m2_painel", "meta",
    "periodo_12m",
}
REQUIRED_BAIRRO_KEYS = {
    "score", "volume_primary_year", "trend_pct", "stock_demand_ratio",
    "price_gap_pct", "flag_alerta", "preco_m2_segmentos",
    "volume_12m", "trend_pct_12m",
}


class ValidationError(SystemExit):
    def __init__(self, msg):
        super().__init__(f"[validate_build] FALHOU — publicação bloqueada: {msg}")


def _independent_row_count(year_to_path):
    """Reconta linhas de cada aba MMM-AAAA direto do .xlsx, sem depender do
    contador interno de parse_itbi.py — pra pegar um bug que estivesse nos
    DOIS lugares (ex: parse_itbi contando errado E confiando na própria
    contagem) e não só numa divergência entre eles."""
    total_rows = 0
    header_rows = 0
    sheets_checked = 0
    for year, path in year_to_path.items():
        if not path.exists():
            continue
        with Workbook(path) as wb:
            for s in wb.sheets:
                if not SHEET_RE.match(s["name"]):
                    continue
                sheets_checked += 1
                for _rn, cells in wb.rows(s["target"]):
                    total_rows += 1
                    if cells.get("E") == "Bairro":
                        header_rows += 1
    return total_rows, header_rows, sheets_checked


def check_header_layout(year_to_path):
    """Escaneia cada aba MMM-AAAA inteira procurando a linha de cabeçalho
    (onde a coluna E diz "Bairro" — pode estar em qualquer linha, não só na
    1ª: ver diagnóstico, JAN-2024/OUT-2024 têm o cabeçalho no meio/fim da
    aba). Levanta erro se: (a) nenhuma linha de cabeçalho for encontrada,
    (b) alguma das 10 colunas que o pipeline lê tiver texto diferente do
    esperado nessa linha, ou (c) menos de 28 colunas estiverem preenchidas
    nela — sinal de coluna sumida/deslocada, o risco real de ler por
    posição fixa."""
    problemas = []
    for year, path in sorted(year_to_path.items()):
        if not path.exists():
            continue
        with Workbook(path) as wb:
            for s in wb.sheets:
                if not SHEET_RE.match(s["name"]):
                    continue
                header_row = None
                for _rn, cells in wb.rows(s["target"]):
                    if cells.get("E") == "Bairro":
                        header_row = cells
                        break
                if header_row is None:
                    problemas.append(f"{s['name']}: nenhuma linha de cabeçalho reconhecível (coluna E == 'Bairro') em toda a aba")
                    continue

                preenchidas = [c for c in EXPECTED_COLUMNS if header_row.get(c)]
                if len(preenchidas) < EXPECTED_COLUMN_COUNT:
                    faltando = [c for c in EXPECTED_COLUMNS if not header_row.get(c)]
                    problemas.append(f"{s['name']}: só {len(preenchidas)}/{EXPECTED_COLUMN_COUNT} colunas A-AB preenchidas no cabeçalho (faltando: {faltando})")

                for col, expected_text in EXPECTED_HEADERS.items():
                    actual = header_row.get(col)
                    if actual != expected_text:
                        problemas.append(f"{s['name']}: coluna {col} esperava '{expected_text}', veio '{actual}'")

    if problemas:
        raise ValidationError("layout de coluna inesperado em " + str(len(problemas)) + " caso(s):\n  - " + "\n  - ".join(problemas))
    print("[validate_build] OK 0/3 — layout de coluna (cabeçalho + 28 colunas A-AB) confere em todas as abas.")


def check_linhas_lidas(year_to_path, itbi_stats):
    total_rows, header_rows, sheets_checked = _independent_row_count(year_to_path)
    esperado = total_rows - header_rows
    lido = itbi_stats["total_rows_seen"]
    if lido != esperado:
        raise ValidationError(
            f"reconciliação de linhas falhou — planilhas têm {total_rows} linhas em "
            f"{sheets_checked} abas, {header_rows} são cabeçalho (esperado {esperado} "
            f"linhas de dado), mas o parser leu {lido}. Diferença: {lido - esperado:+d}."
        )
    print(f"[validate_build] OK 1/3 — linhas lidas batem: {lido} == {total_rows} totais - {header_rows} cabeçalho, em {sheets_checked} abas.")


def check_variacao_bairros(new_bairros, old_data_path):
    if not old_data_path.exists():
        print("[validate_build] OK 2/3 — sem versão publicada anterior pra comparar (primeira execução).")
        return
    try:
        old_data = json.loads(old_data_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[validate_build] AVISO — não consegui ler a versão anterior pra comparar ({e!r}); pulando checagem 2/3.")
        return
    old_bairros = old_data.get("bairros", {})

    grandes_mudancas = []
    for b in TARGETS:
        old_v = (old_bairros.get(b) or {}).get("volume_primary_year")
        new_v = (new_bairros.get(b) or {}).get("volume_primary_year")
        if old_v is None or new_v is None or old_v == 0:
            continue
        variacao = (new_v - old_v) / old_v
        if abs(variacao) > VARIACAO_MAX:
            grandes_mudancas.append((b, old_v, new_v, variacao))

    if grandes_mudancas:
        grandes_mudancas.sort(key=lambda x: -abs(x[3]))
        linhas = "\n".join(
            f"  - {b}: {old_v} -> {new_v} ({variacao*100:+.1f}%)" for b, old_v, new_v, variacao in grandes_mudancas
        )
        if os.environ.get("ALLOW_LARGE_CHANGES", "").strip() == "1":
            print(
                f"[validate_build] AVISO 2/3 — {len(grandes_mudancas)} bairro(s) com variação de "
                f"volume_primary_year acima de {VARIACAO_MAX*100:.0f}%, mas ALLOW_LARGE_CHANGES=1 "
                f"está setado (mudança de metodologia deliberada) — publicando mesmo assim:\n{linhas}"
            )
            return
        raise ValidationError(
            f"{len(grandes_mudancas)} bairro(s) com variação de volume_primary_year acima de "
            f"{VARIACAO_MAX*100:.0f}% vs a versão publicada atual, sem ALLOW_LARGE_CHANGES=1:\n{linhas}\n"
            f"Se a mudança é esperada (correção deliberada de metodologia), rode de novo com "
            f"ALLOW_LARGE_CHANGES=1 no ambiente."
        )
    print(f"[validate_build] OK 2/3 — nenhum bairro variou mais que {VARIACAO_MAX*100:.0f}% em volume_primary_year.")


def check_formato_paineis(data):
    faltando_topo = REQUIRED_TOP_KEYS - data.keys()
    if faltando_topo:
        raise ValidationError(f"chaves obrigatórias faltando no topo de data.json: {sorted(faltando_topo)}")

    bairros = data["bairros"]
    faltando_bairros = set(TARGETS) - bairros.keys()
    if faltando_bairros:
        raise ValidationError(f"bairro(s) da carteira ausentes em data.json: {sorted(faltando_bairros)}")

    for b, entry in bairros.items():
        faltando = REQUIRED_BAIRRO_KEYS - entry.keys()
        if faltando:
            raise ValidationError(f"bairro '{b}' sem os campos {sorted(faltando)} — um painel que lê esse campo quebraria.")

    if not isinstance(data.get("ranking"), list) or len(data["ranking"]) != len(TARGETS):
        raise ValidationError(f"'ranking' deveria ter {len(TARGETS)} bairros, tem {len(data.get('ranking'))}.")

    print(f"[validate_build] OK 3/3 — formato de data.json íntegro: {len(bairros)} bairros, todas as chaves esperadas presentes.")


def validate_before_publish(year_to_path, itbi_stats, data, out_path):
    """Chamado por build_data.py logo antes de escrever site/data.json.
    Levanta SystemExit (para o processo com código != 0) se qualquer
    checagem falhar — build_data.py não deve capturar essa exceção."""
    print("[validate_build] rodando as 3 checagens antes de publicar...")
    check_linhas_lidas(year_to_path, itbi_stats)
    check_variacao_bairros(data["bairros"], out_path)
    check_formato_paineis(data)
    print("[validate_build] todas as checagens passaram — liberado pra publicar.")
