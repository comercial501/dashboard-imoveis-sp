#!/usr/bin/env python3
"""
Região de cada venda FORA da carteira de bairros — só para a Calculadora de preço (14/10/2026, pedido do Paulo:
"a calculadora tem que achar qualquer endereço de São Paulo").

A carteira (TARGETS) é a lista de bairros que o Paulo acompanha nos painéis; o resto da cidade não tem "bairro" na nossa base.
Para a Calculadora, cada venda de fora ganha uma REGIÃO: o nome do bairro que o cadastro do IPTU mais usa no CEP de 5 dígitos
daquela venda (ex.: "Vila Formosa"), separada por sub-região do CEP (3 primeiros dígitos) para não juntar lugares distantes
que têm o mesmo nome. A região vira o "bairro" da venda só dentro da Calculadora (o nível «bairro» da estimativa e o nome que aparece
na tela, sempre com "(fora da carteira)" ao lado). Nenhum painel usa isso.
"""
import csv
import gzip
import re
from collections import Counter, defaultdict

import iptu_geosampa as ig
import tradutor_bairro as tb

SUFIXO = " (fora da carteira)"
_EXPANDE = {"JD": "Jardim", "JDS": "Jardins", "VL": "Vila", "VLA": "Vila", "PQ": "Parque", "PRQ": "Parque", "PQE": "Parque", "CJ": "Conjunto",
            "HAB": "Habitacional", "CHAC": "Chácara", "CH": "Chácara", "STA": "Santa", "STO": "Santo", "RES": "Residencial", "CID": "Cidade",
            "PCA": "Praça", "PC": "Praça", "JARD": "Jardim", "V": "Vila", "SP": "SP"}
_MINUSCULAS = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def cep8(raw):
    """CEP do ITBI chega como número ('1103020.0', '1103020') ou texto ('01103-020'): devolve 8 dígitos ou None."""
    s = str(raw or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.0+)?", s):
        s = s.split(".")[0]
    d = re.sub(r"\D", "", s)
    return d.zfill(8) if d else None


def nome_bonito(nome):
    palavras = re.sub(r"\s+", " ", (nome or "").strip()).upper().split(" ")
    out = []
    for i, p in enumerate(palavras):
        p = p.strip(".")
        if p in _MINUSCULAS and i > 0:
            out.append(p.lower())
        elif p in _EXPANDE:
            out.append(_EXPANDE[p])
        else:
            out.append(p.capitalize())
    return " ".join(out)


def mapa_cep5_nome(path=None):
    """{cep5: nome do bairro mais comum no cadastro do IPTU para esse CEP de 5 dígitos}."""
    cont = defaultdict(Counter)
    with gzip.open(path or ig.REDUZIDO_GZ, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            nome = (row.get("bairro") or "").strip().upper()
            if not tb._parece_bairro(nome) or any(c.isdigit() for c in nome) or len(nome) < 4:
                continue
            c5 = tb._cep5(row.get("cep"))
            if c5:
                cont[c5][nome] += 1
    return {c5: c.most_common(1)[0][0] for c5, c in cont.items()}


def atribuir_regioes(registros, mapa=None):
    """Devolve {**registro, "bairro": "<Região> (fora da carteira)", "regiao_cep5": ...} para cada venda que tem CEP e região conhecida."""
    mapa = mapa if mapa is not None else mapa_cep5_nome()
    brutos = []
    grupos = defaultdict(set)   # nome bonito -> {cep3, ...}
    for r in registros:
        c8 = cep8(r.get("cep"))
        if not c8:
            continue
        nome = mapa.get(c8[:5])
        nome = nome_bonito(nome) if nome else f"Região do CEP {c8[:5]}-"
        brutos.append((r, nome, c8[:3]))
        grupos[nome].add(c8[:3])
    out = []
    for r, nome, c3 in brutos:
        # o mesmo nome em sub-regiões do CEP diferentes (lugares distantes) não pode virar um bairro só: separa pelo CEP
        rotulo = nome if len(grupos[nome]) == 1 else f"{nome} · CEP {c3}"
        out.append({**r, "bairro": rotulo + SUFIXO, "regiao_cep5": (cep8(r.get("cep")) or "")[:5]})
    return out
