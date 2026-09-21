#!/usr/bin/env python3
"""
Leitor de .xlsx sem dependências externas (só stdlib: zipfile + xml).

Porta em Python de scripts/XlsxExtract.pm (mesma técnica: um .xlsx é um
.zip contendo XML — não precisamos do "unzip" do sistema como o Perl usava,
o módulo `zipfile` do Python já lê isso nativamente).

Lê célula por letra de coluna (ex: "B", "W"), não por nome de cabeçalho —
de propósito: as planilhas da Prefeitura/Usenonstop não têm cabeçalho
padronizado que o parser possa confiar, e o motor de cálculo original
(build_data.pl) também lê por letra fixa. Ver itbi_methodology_spec.md §1.3.
"""
import re
import zipfile
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
COL_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _col_letters(cell_ref):
    m = COL_RE.match(cell_ref)
    return m.group(1) if m else None


def _xml_unescape(s):
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def read_shared_strings(zf):
    """Retorna lista de strings indexada pela ordem de <si> em sharedStrings.xml."""
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    out = []
    for si in root.findall("m:si", NS):
        # concatena todo texto de todas as tags <t> dentro do <si> (cobre
        # "rich text" com formatação inline — várias <t> por <si>)
        text = "".join(t.text or "" for t in si.iter("{%s}t" % NS["m"]))
        out.append(text)
    return out


def read_workbook_sheets(zf):
    """Retorna lista ordenada de {"name": ..., "target": "xl/worksheets/sheetN.xml"}."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    rid_to_target = {}
    for rel in rels_root.findall(f"{rel_ns}Relationship"):
        rid_to_target[rel.get("Id")] = rel.get("Target")

    r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    sheets = []
    for sheet in wb.findall("m:sheets/m:sheet", NS):
        name = sheet.get("name")
        rid = sheet.get(f"{r_ns}id")
        target = rid_to_target.get(rid)
        if target is None:
            continue
        if not target.startswith("xl/") and not target.startswith("/"):
            target = "xl/" + target
        target = target.lstrip("/")
        sheets.append({"name": name, "target": target})
    return sheets


def iter_sheet_rows(zf, sheet_target, shared_strings):
    """Gera (row_num:int, cells:dict[str,str]) para cada linha da planilha.
    `cells` mapeia letra de coluna -> valor decodificado (string). Células
    vazias/sem valor não entram no dict (mesmo comportamento do Perl:
    ausência != string vazia)."""
    raw = zf.read(sheet_target)
    # iterparse pra não carregar a árvore inteira de uma vez (planilhas de
    # até ~50MB/centenas de milhares de linhas)
    context = ET.iterparse(__import__("io").BytesIO(raw), events=("end",))
    row_tag = "{%s}row" % NS["m"]
    c_tag = "{%s}c" % NS["m"]
    v_tag = "{%s}v" % NS["m"]
    is_tag = "{%s}is" % NS["m"]

    for event, elem in context:
        if elem.tag != row_tag:
            continue
        row_num = int(elem.get("r"))
        cells = {}
        for c in elem.findall(c_tag):
            ref = c.get("r")
            col = _col_letters(ref) if ref else None
            if col is None:
                continue
            ctype = c.get("t")
            val = None
            if ctype == "s":
                v = c.find(v_tag)
                if v is not None and v.text is not None:
                    idx = int(v.text)
                    if 0 <= idx < len(shared_strings):
                        val = shared_strings[idx]
            elif ctype == "str":
                v = c.find(v_tag)
                val = v.text if v is not None else None
            elif ctype == "inlineStr":
                is_el = c.find(is_tag)
                if is_el is not None:
                    val = "".join(t.text or "" for t in is_el.iter("{%s}t" % NS["m"]))
            else:
                v = c.find(v_tag)
                val = v.text if v is not None else None
            if val is not None and len(val) > 0:
                cells[col] = _xml_unescape(val) if isinstance(val, str) else val
        yield row_num, cells
        elem.clear()


class Workbook:
    """Contexto simples: `with Workbook(path) as wb: wb.sheets` / `wb.rows(target)`."""

    def __init__(self, path):
        self.path = path
        self._zf = None
        self._shared = None
        self.sheets = []

    def __enter__(self):
        self._zf = zipfile.ZipFile(self.path)
        self._shared = read_shared_strings(self._zf)
        self.sheets = read_workbook_sheets(self._zf)
        return self

    def __exit__(self, *exc):
        if self._zf:
            self._zf.close()

    def rows(self, sheet_target):
        return iter_sheet_rows(self._zf, sheet_target, self._shared)


if __name__ == "__main__":
    import sys

    path = sys.argv[1]
    with Workbook(path) as wb:
        print(f"{len(wb.sheets)} abas:")
        for s in wb.sheets[:15]:
            print(" -", s["name"], "->", s["target"])
        if wb.sheets:
            first = wb.sheets[0]
            n = 0
            for row_num, cells in wb.rows(first["target"]):
                if n < 5:
                    print(row_num, cells)
                n += 1
            print(f"total linhas na aba '{first['name']}': {n}")
