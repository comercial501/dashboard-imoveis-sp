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
"""
import re

from normalize import address_key, bairro_canon, display_street, normalize_number
from xlsx_reader import Workbook

MONTH_MAP = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}
SHEET_RE = re.compile(r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)-(\d{4})$")

# Códigos de "Uso (IPTU)" residenciais — ver spec §1.1 (metade das linhas
# do ITBI são garagem/terreno/comercial e distorcem muito a mediana se
# misturadas).
USO_RESIDENCIAL_RE = re.compile(r"^(?:10|12|14|20|21|22|25)(?:\.0+)?$")
VALOR_RE = re.compile(r"^-?\d+(\.\d+)?$")

AREA_CAP = 600  # m² — ver spec §6.2: "Área Construída" às vezes guarda a área do prédio inteiro

# Coluna H = "Natureza de Transação". Só "1.Compra e venda" é venda de
# mercado de verdade — o resto (integralização de capital, leilão, herança,
# divórcio, permuta, etc — ~11,6% das linhas residenciais em 2025) usa
# valor contábil/simbólico, sistematicamente mais baixo que preço de
# mercado (mediana R$605mil em "compra e venda" vs. R$150-460mil nas
# outras naturezas, medido em produção). `is_compra_venda` é usado pelo
# motor de cálculo pra filtrar SÓ a mediana de preço e a faixa de
# metragem — volume/liquidez continuam contando qualquer transação
# residencial válida (decisão do usuário: giro do bairro é giro, mesmo
# quando não é um preço confiável).
NATUREZA_COMPRA_VENDA_RE = re.compile(r"^1\.")


def parse_itbi_file(path):
    """Retorna (records, stats) onde cada record é:
    {bairro, sheet_year, day, valor, area, addr_key, addr_display, is_compra_venda}
    e stats = {"rows_seen": int, "rows_matched": int, "duplicates_removed": int, "sheets": [nomes]}."""
    records = []
    rows_seen = 0
    rows_matched = 0
    duplicates_removed = 0
    seen_exact = set()
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
                if not b_raw:
                    continue
                rows_seen += 1

                bairro = bairro_canon(b_raw)
                if not bairro:
                    continue

                uso = (cells.get("X") or "").strip()
                if not USO_RESIDENCIAL_RE.match(uso):
                    continue

                valor_raw = (cells.get("I") or "").strip()
                if not VALOR_RE.match(valor_raw):
                    continue
                valor = float(valor_raw)
                if valor <= 0:
                    continue

                day = None
                data_raw = cells.get("J")
                if data_raw is not None:
                    try:
                        day = int(float(data_raw))
                    except ValueError:
                        pass

                street = cells.get("B")
                number = cells.get("C")

                # Deduplicação de linhas EXATAMENTE idênticas (mesmo bairro +
                # rua + número + valor + data) — medido em produção: ~2,6%
                # das linhas residenciais válidas de 2025 são duplicatas
                # exatas assim, provavelmente registro repetido da própria
                # Prefeitura (não dá pra saber com certeza — em teoria 2
                # unidades idênticas vendidas no mesmo prédio no mesmo dia
                # pelo mesmo preço também bateria essa chave, mas é bem
                # menos provável que duplicidade de registro).
                dedup_key = (bairro, (street or "").strip().upper(), (number or "").strip(), round(valor, 2), day)
                if dedup_key in seen_exact:
                    duplicates_removed += 1
                    continue
                seen_exact.add(dedup_key)

                rows_matched += 1

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

                akey = address_key(street, number)
                adisp = None
                if akey:
                    adisp = f"{display_street(street)}, {normalize_number(number)}"

                records.append({
                    "bairro": bairro,
                    "sheet_year": sheet_year,
                    "day": day,
                    "valor": valor,
                    "area": area,
                    "addr_key": akey,
                    "addr_display": adisp,
                    "is_compra_venda": is_compra_venda,
                })

    return records, {
        "rows_seen": rows_seen, "rows_matched": rows_matched,
        "duplicates_removed": duplicates_removed, "sheets": sheet_names,
    }


def parse_itbi_years(year_to_path):
    """year_to_path: dict {ano: Path}. Agrega todos os anos disponíveis."""
    all_records = []
    total_seen = 0
    total_matched = 0
    total_duplicates = 0
    sheets_found = 0
    for year in sorted(year_to_path):
        path = year_to_path[year]
        if not path.exists():
            continue
        records, stats = parse_itbi_file(path)
        all_records.extend(records)
        total_seen += stats["rows_seen"]
        total_matched += stats["rows_matched"]
        total_duplicates += stats["duplicates_removed"]
        sheets_found += len(stats["sheets"])
    return all_records, {
        "total_rows_seen": total_seen,
        "total_rows_matched": total_matched,
        "duplicates_removed": total_duplicates,
        "sheets_found": sheets_found,
    }


if __name__ == "__main__":
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    year_to_path = {y: root / "data" / "itbi_raw" / f"{y}.xlsx" for y in (2024, 2025, 2026)}
    records, stats = parse_itbi_years(year_to_path)
    print(stats)
    print(f"{len(records)} transações residenciais válidas nos 47 bairros")
    by_bairro = {}
    for r in records:
        by_bairro[r["bairro"]] = by_bairro.get(r["bairro"], 0) + 1
    for b, n in sorted(by_bairro.items(), key=lambda x: -x[1])[:10]:
        print(f"  {b}: {n}")
