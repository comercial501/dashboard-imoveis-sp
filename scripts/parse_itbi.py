#!/usr/bin/env python3
"""
Extrai transações ITBI residenciais válidas dos .xlsx anuais baixados pelo
itbi_source.py (data/itbi_raw/<ano>.xlsx).

Porta de build_data.pl (discover_itbi_sources + o parsing por linha) — ver
itbi_methodology_spec.md §1.1. Cada arquivo já é o consolidado oficial de um
ano inteiro (todas as abas MES-ANO daquele ano), baixado direto da
Prefeitura — não há mais o cenário de múltiplos arquivos manuais
sobrepondo o mesmo mês (§4.1 do spec), então não precisamos da resolução
de duplicidade por mtime: cada ano tem exatamente 1 arquivo autoritativo.

Este módulo faz só a extração linha-a-linha (uso residencial + valor
válido) — NÃO filtra por bairro, NÃO deduplica. Essas duas etapas dependem
de olhar o conjunto inteiro de linhas de um mesmo endereço/imóvel, então
ficam em clean_itbi.py (auditoria de 2026-09-29, ver README):
  - bairro (coluna E) é texto livre preenchido por transação, não é um
    dado fixo do imóvel — pode vir vazio/não-padronizado numa linha e
    correto em outra do MESMO endereço. Filtrar aqui, linha a linha,
    descartava ~16 mil vendas válidas de prédios que já rastreamos (uma
    delas: Av. Ibirapuera 2927, um lançamento com 36 vendas onde só 8
    sobreviviam — poucas demais pro detector de lançamento disparar).
    clean_itbi.resolve_bairros() decide o bairro por MAIORIA entre as
    linhas do mesmo endereço, recuperando as que vieram sem bairro.
  - duplicidade exata por rua+número+valor+data (chave antiga) confundia
    unidades DIFERENTES de um mesmo prédio com preço/data coincidentes
    (comum em lançamento com tabela de preço padronizada). O SQL (coluna
    A, "N° do Cadastro") é o identificador oficial e inequívoco do imóvel
    — clean_itbi.dedup_by_sql() deduplica por SQL+valor+data.
"""
import re

from normalize import address_key, bairro_canon, display_street, normalize_number
from xlsx_reader import Workbook

MONTH_MAP = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}
SHEET_RE = re.compile(r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)-(\d{4})$")

# Códigos de "Uso (IPTU)" residenciais (coluna X) — confirmado 1:1 contra a
# "Descrição do uso (IPTU)" (coluna Y) do próprio arquivo em 2026-09-29:
#   10 RESIDÊNCIA (casa) · 12 RESIDÊNCIA COLETIVA, exclusive cortiço (casa)
#   14 RESIDÊNCIA E OUTRO USO, predominância residencial (casa)
#   20 APARTAMENTO EM CONDOMÍNIO (exige fração ideal) — a maioria disparada
#   21 PRÉDIO DE APARTAMENTO, não em condomínio, exclusivamente residencial
#   22 idem, uso misto (apartamentos e escritórios/consultórios)
#   25 FLAT RESIDENCIAL EM CONDOMÍNIO (exige fração ideal)
# 21/22 são o PRÉDIO INTEIRO vendido de uma vez (não uma unidade) — ver
# clean_itbi.TIPO_IMOVEL_POR_USO, ficam fora da classificação apto/casa.
USO_RESIDENCIAL_RE = re.compile(r"^(?:10|12|14|20|21|22|25)(?:\.0+)?$")
VALOR_RE = re.compile(r"^-?\d+(\.\d+)?$")

AREA_CAP = 600  # m² — ver spec §6.2: "Área Construída" às vezes guarda a área do prédio inteiro

# Coluna H = "Natureza de Transação". Só "1.Compra e venda" é venda de
# mercado de verdade — o resto (integralização de capital, leilão, herança,
# divórcio, permuta, etc — ~11,6% das linhas residenciais) usa valor
# contábil/simbólico, sistematicamente mais baixo que preço de mercado.
# `is_compra_venda` é usado pelo motor de cálculo pra filtrar SÓ a mediana
# de preço e a faixa de metragem — volume/liquidez continuam contando
# qualquer transação residencial válida (decisão do usuário: giro do
# bairro é giro, mesmo quando não é um preço confiável).
NATUREZA_COMPRA_VENDA_RE = re.compile(r"^1\.")
# Item 2 da auditoria de 2026-09-30: "17.Resolução da alienação fiduciária
# por inadimplemento" (retomada pelo banco/credor) e "4.Arrematação (em
# leilão ou hasta pública)" viram um indicador de volume SEPARADO
# (volume_retomadas_12m em engine.py) — são vendas de verdade (mudam de
# dono), mas o valor registrado é o da dívida/lance, não preço de mercado;
# não contam nem pra volume_mercado_12m nem pra preço.
NATUREZA_RETOMADA_RE = re.compile(r"^(17|4)\.")


def normalize_sql(sql_raw):
    """SQL (N° do Cadastro) é sempre 11 dígitos: setor (3) + quadra (3) +
    lote (4) + dígito verificador (1) — confirmado na aba EXPLICAÇÕES do
    próprio arquivo. A planilha guarda como NÚMERO, então zeros à esquerda
    somem (ex: setor "001" vira "1") e o Excel às vezes serializa o mesmo
    valor em notação científica numa linha/arquivo e decimal simples noutra
    (achado de 2026-09-30: 11.554 SQLs — 3,5% do total — têm mais de uma
    representação em string no dataset; comparar a string crua, como o
    dedup fazia antes, arrisca tratar o MESMO imóvel como SQLs diferentes).
    Sempre usar esta função — nunca a string crua da célula — pra
    deduplicar ou extrair setor/quadra."""
    if not sql_raw:
        return None
    try:
        n = int(float(sql_raw))
    except ValueError:
        return None
    if n <= 0:
        return None
    return str(n).zfill(11)


def parse_itbi_file(path):
    """Retorna (records, stats). Cada record:
    {bairro, bairro_raw, sheet_year, day, valor, area, sql, uso_code,
     addr_key, addr_display, is_compra_venda, is_full_transfer}
    `bairro` é o resultado de bairro_canon() — pode ser None aqui (a
    resolução por maioria acontece depois, em clean_itbi.py).
    stats = {"rows_seen", "rows_matched", "sheets"}."""
    records = []
    rows_seen = 0
    rows_matched = 0
    sheet_names = []

    with Workbook(path) as wb:
        for sheet in wb.sheets:
            m = SHEET_RE.match(sheet["name"])
            if not m:
                continue
            sheet_year = int(m.group(2))
            sheet_names.append(sheet["name"])

            for row_num, cells in wb.rows(sheet["target"]):
                b_raw = cells.get("E")
                # Linha de cabeçalho (2025/2026 repetem em algumas abas) —
                # "Bairro" nunca é um bairro de verdade, só descarta. NÃO
                # descarta bairro vazio/None aqui — é exatamente o que
                # resolve_bairros() precisa ver pra recuperar a linha pela
                # maioria das outras linhas do mesmo endereço (auditoria de
                # 2026-09-29: ~91% das linhas residenciais têm bairro em
                # branco ou fora da carteira; boa parte tem o MESMO
                # endereço de uma linha com bairro certo).
                if b_raw == "Bairro":
                    continue
                rows_seen += 1

                uso = (cells.get("X") or "").strip()
                if not USO_RESIDENCIAL_RE.match(uso):
                    continue

                valor_raw = (cells.get("I") or "").strip()
                if not VALOR_RE.match(valor_raw):
                    continue
                valor = float(valor_raw)
                if valor <= 0:
                    continue

                rows_matched += 1

                day = None
                data_raw = cells.get("J")
                if data_raw is not None:
                    try:
                        day = int(float(data_raw))
                    except ValueError:
                        pass

                street = cells.get("B")
                number = cells.get("C")
                complemento = (cells.get("D") or "").strip()

                area = None
                area_raw = cells.get("W")
                if area_raw is not None:
                    try:
                        a = float(area_raw)
                        if 0 < a <= AREA_CAP:
                            area = a
                    except ValueError:
                        pass

                natureza = (cells.get("H") or "").strip()
                is_compra_venda = bool(NATUREZA_COMPRA_VENDA_RE.match(natureza))
                is_retomada = bool(NATUREZA_RETOMADA_RE.match(natureza))

                # Coluna L = % do imóvel efetivamente transacionado (auditoria
                # de 2026-09-24/29: confirmado contra K/M ("Valor Venal de
                # Referência" e sua proporção) e contra o nome oficial da
                # coluna, "Proporção Transmitida (%)"). ~21% das linhas
                # residenciais "1.Compra e venda" nos 49 bairros têm L < 100
                # — transferência de FRAÇÃO ideal (partilha de herança/
                # divórcio entre coproprietários, doação de parte), não
                # venda do imóvel inteiro. `is_full_transfer` só filtra
                # preço/metragem, nunca volume/liquidez.
                pct_raw = cells.get("L")
                is_full_transfer = True
                if pct_raw is not None:
                    try:
                        is_full_transfer = float(pct_raw) >= 99.99
                    except ValueError:
                        pass

                akey = address_key(street, number)
                adisp = None
                if akey:
                    adisp = f"{display_street(street)}, {normalize_number(number)}"

                uso_code = uso.split(".")[0] if uso else None

                records.append({
                    "bairro": bairro_canon(b_raw),
                    "bairro_raw": b_raw,
                    "sheet_year": sheet_year,
                    "day": day,
                    "valor": valor,
                    "area": area,
                    "sql": normalize_sql(cells.get("A")),
                    "uso_code": uso_code,
                    "addr_key": akey,
                    "addr_display": adisp,
                    "is_compra_venda": is_compra_venda,
                    "is_full_transfer": is_full_transfer,
                    "is_retomada": is_retomada,
                    # Item 2 (achado de 2026-09-30, respondendo ao ponto 1a):
                    # deduplicação por SQL+valor+data SEM complemento confundia
                    # unidades DIFERENTES do mesmo prédio (mesmo SQL do lote,
                    # mesmo dia de fechamento, preço coincidente — comum em
                    # lançamento com tabela padronizada) — ver clean_itbi.dedup_by_sql.
                    "complemento": complemento,
                    # Item 3 (continuação, 2026-09-30): CEP (coluna G), cru —
                    # normalizado só na hora de usar (ver normalize_cep em
                    # clean_itbi.py ou scripts que consomem isso).
                    "cep": (cells.get("G") or "").strip() or None,
                    # Texto completo da natureza (coluna H) — só usado pro
                    # log de limpeza (quebra por tipo de natureza excluída),
                    # nunca sai daqui pro raw.json (bool já basta pro motor).
                    "natureza_raw": natureza,
                })

    return records, {
        "rows_seen": rows_seen, "rows_matched": rows_matched, "sheets": sheet_names,
    }


def parse_itbi_years(year_to_path):
    """year_to_path: dict {ano: Path}. Agrega todos os anos disponíveis."""
    all_records = []
    total_seen = 0
    total_matched = 0
    sheets_found = 0
    for year in sorted(year_to_path):
        path = year_to_path[year]
        if not path.exists():
            continue
        records, stats = parse_itbi_file(path)
        all_records.extend(records)
        total_seen += stats["rows_seen"]
        total_matched += stats["rows_matched"]
        sheets_found += len(stats["sheets"])
    return all_records, {
        "total_rows_seen": total_seen,
        "total_rows_matched": total_matched,
        "sheets_found": sheets_found,
    }


if __name__ == "__main__":
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    year_to_path = {y: root / "data" / "itbi_raw" / f"{y}.xlsx" for y in (2024, 2025, 2026)}
    records, stats = parse_itbi_years(year_to_path)
    print(stats)
    print(f"{len(records)} transações residenciais válidas (qualquer bairro, antes da resolução/limpeza)")
