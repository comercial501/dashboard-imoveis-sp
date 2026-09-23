#!/usr/bin/env python3
"""
Adaptador LEGADO: lê o export manual .xlsx da Usenonstop (dados-usenonstop/).

Existe só para testar/validar o motor de cálculo (engine.py) contra dados
reais enquanto a integração via API (nonstop_client.py) não está
configurada com token. Em produção, o estoque vem da API — ver
nonstop_client.py, que produz records no MESMO formato desta função
(bairro, addr_key, addr_display, valor, area, quartos, vagas, lat, lon,
situacao_code, codigo, link), pra o engine.py ser agnóstico da fonte.

Porta de build_data.pl (discover_usenonstop_source + parsing) — ver
itbi_methodology_spec.md §1.2.
"""
import re

from normalize import address_key, bairro_canon, display_street, normalize_number
from xlsx_reader import Workbook

SITUACAO_CODE = {"PADRAO": 0, "NOVO": 1, "REFORMA": 2, "LANCAMENTO": 3, "CONSTRUCAO": 4}
COORDS_RE = re.compile(r"lat:\s*(-?\d+\.?\d*),\s*lng:\s*(-?\d+\.?\d*)")


def parse_usenonstop_xlsx(path):
    """Retorna (records, stats). Um record por anúncio válido:
    {bairro, addr_key, addr_display, valor, area, quartos, vagas, lat, lon,
     situacao_code, codigo, link}"""
    records = []
    rows_seen = 0
    rows_matched = 0

    with Workbook(path) as wb:
        sheet = wb.sheets[0]
        for row_num, cells in wb.rows(sheet["target"]):
            if row_num == 1:
                continue
            b_raw = cells.get("F")
            if not b_raw:
                continue
            rows_seen += 1

            disp = cells.get("J") or ""
            if not re.search(r"VENDA", disp, re.I):
                continue
            uso = (cells.get("O") or "").strip()
            if uso.upper() != "RESIDENCIAL":
                continue
            bairro = bairro_canon(b_raw)
            if not bairro:
                continue

            rows_matched += 1

            valor = None
            valor_raw = cells.get("K")
            if valor_raw:
                try:
                    v = float(valor_raw)
                    if v > 0:
                        valor = v
                except ValueError:
                    pass

            area = None
            area_raw = cells.get("Q")
            if area_raw:
                try:
                    a = float(area_raw)
                    if a > 0:
                        area = a
                except ValueError:
                    pass

            def _int_or_none(v):
                if v is None:
                    return None
                try:
                    return int(float(v))
                except ValueError:
                    return None

            quartos = _int_or_none(cells.get("X"))
            vagas = _int_or_none(cells.get("T"))

            lat = lon = None
            coords_raw = cells.get("I")
            if coords_raw:
                m = COORDS_RE.search(coords_raw)
                if m:
                    # Labels trocadas na fonte — ver spec §1.2: "lat:" é na
                    # verdade longitude, "lng:" é latitude.
                    lon, lat = float(m.group(1)), float(m.group(2))

            situacao_raw = (cells.get("V") or "").strip().upper()
            situacao_code = SITUACAO_CODE.get(situacao_raw, 0)

            street = cells.get("C")
            number = cells.get("D")
            akey = address_key(bairro, street, number)
            complemento = cells.get("E")
            base_disp = f"{street}, {number}" if street and number else display_street(street)
            adisp = f"{base_disp} - {complemento}" if complemento else base_disp

            records.append({
                "bairro": bairro,
                "addr_key": akey,
                "addr_display": adisp,
                "addr_display_building": base_disp,
                "valor": valor,
                "area": area,
                "quartos": quartos,
                "vagas": vagas,
                "lat": lat,
                "lon": lon,
                "situacao_code": situacao_code,
                "codigo": cells.get("B"),
                "link": cells.get("BA"),
            })

    return records, {"rows_seen": rows_seen, "rows_matched": rows_matched}


if __name__ == "__main__":
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    records, stats = parse_usenonstop_xlsx(root / "dados-usenonstop" / "imoveis.xlsx")
    print(stats)
    print(f"{len(records)} anúncios válidos")
    by_bairro = {}
    for r in records:
        by_bairro[r["bairro"]] = by_bairro.get(r["bairro"], 0) + 1
    for b, n in sorted(by_bairro.items(), key=lambda x: -x[1])[:10]:
        print(f"  {b}: {n}")
