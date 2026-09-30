#!/usr/bin/env python3
"""
Cadastro fiscal do IPTU (GeoSampa), usado só pra resolver bairro por quadra
fiscal — item 3 da auditoria de 2026-09-30 (segunda rodada, iniciada em
2026-09-30). Baixado manualmente pelo usuário em
https://geosampa.prefeitura.sp.gov.br (camada Lote -> download -> cadastro
-> IPTU), 3,92 milhões de linhas, 938MB original. O arquivo completo NÃO
entra no git (.gitignore já cobre data/); guardamos só uma versão reduzida
(5 colunas: sql, bairro, cep, logradouro, numero) comprimida em
data/iptu_geosampa/iptu_2026_reduzido.csv.gz (23MB) — ver
_reduzir_arquivo_original() pra regenerar a partir do .zip original, se
precisar.

Achado do usuário (confirmado abaixo): "BAIRRO DO IMOVEL" nesse cadastro
tem muito lixo (nome de torre/bloco/condomínio em vez de bairro de
verdade) e grafias variantes (abreviação tipo "JD"/"STO", sem acento,
etc) — sem normalizar isso, a maioria das quadras fiscais parece ter mais
de 1 "bairro" só por causa da variação de grafia, não porque a quadra
realmente cruza duas vizinhanças.
"""
import csv
import gzip
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REDUZIDO_GZ = ROOT / "data" / "iptu_geosampa" / "iptu_2026_reduzido.csv.gz"
EQUIVALENCIAS_CSV = Path(__file__).resolve().parent / "bairros_equivalencias.csv"

# Primeiro token da string == isto -> não é bairro, é rótulo de
# torre/bloco/unidade/condomínio dentro de um empreendimento (medido em
# produção: TORRE/BLOCO sozinhos somam mais de 170 mil linhas cada).
GARBAGE_TOKENS = {
    "TORRE", "BLOCO", "BL", "ED", "COND", "CONDOMINIO", "SUBCOND", "RES",
    "APTO", "AP", "CASA", "LT", "GARAGEM", "VAGA", "VG", "UNID", "UNIDADE",
    "SALA", "LOJA", "QD", "LOTE",
}

# Abreviação no PRIMEIRO token do nome do bairro -> forma expandida.
# Lista inicial derivada da distribuição real de prefixos curtos no
# cadastro (ver diagnóstico); PQ e PRQ são abreviações concorrentes da
# mesma palavra, por isso as duas apontam pra "PARQUE".
ABREVIACOES = {
    "JD": "JARDIM", "JD.": "JARDIM",
    "VL": "VILA",
    "STA": "SANTA", "STO": "SANTO",
    "PQ": "PARQUE", "PRQ": "PARQUE",
    "CHAC": "CHACARA",
    "CID": "CIDADE",
    "CONJ": "CONJUNTO", "CJ": "CONJUNTO",
    "ENG": "ENGENHEIRO",
    "V": "VILA",  # só como token isolado ("V POMPEIA", "V MADALENA") — não afeta palavras que contêm "v"
}

_MULTI_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_SPACE_RE = re.compile(r"[^A-Z0-9 ]")


def _remove_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalizar_bairro_iptu(raw, equivalencias=None):
    """None se for lixo (torre/bloco/etc) ou vazio. Senão, string
    normalizada (maiúscula, sem acento, abreviação expandida, e — se
    houver uma entrada em bairros_equivalencias.csv — a forma canônica
    revisada manualmente)."""
    if not raw:
        return None
    s = raw.strip().upper()
    s = _remove_acentos(s)
    s = _NON_ALNUM_SPACE_RE.sub(" ", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    if not s:
        return None
    toks = s.split(" ")
    if toks[0] in GARBAGE_TOKENS:
        return None
    # Expande abreviação em QUALQUER token, não só o primeiro — achado
    # revisando os nomes sem match nos 49 bairros: "JARDIM STO AMARO"
    # (STO no 2º token) e "JARDIM V MARIANA"/"V POMPEIA" (V/VL no meio)
    # ficavam sem expandir com a versão só-primeiro-token.
    toks = [ABREVIACOES.get(t, t) for t in toks]
    s = " ".join(toks)
    if equivalencias and s in equivalencias:
        return equivalencias[s]
    return s


def carregar_equivalencias():
    """Lê bairros_equivalencias.csv (variante,canonico) — arquivo editável
    pelo usuário pra corrigir casos que a normalização automática não
    pega. Formato: 2 colunas, cabeçalho "variante,canonico". Vazio/ausente
    é normal (funciona sem)."""
    if not EQUIVALENCIAS_CSV.exists():
        return {}
    out = {}
    with EQUIVALENCIAS_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            variante = (row.get("variante") or "").strip().upper()
            canonico = (row.get("canonico") or "").strip().upper()
            if variante and canonico:
                out[variante] = canonico
    return out


def setor_quadra_de_sql(sql_raw):
    """SQL do GeoSampa vem como texto com hífen antes do dígito
    verificador (ex: "0010030001-4") — MUITO diferente do SQL do ITBI
    (número Excel, sem hífen, zeros à esquerda somem). Aqui só tira
    tudo que não é dígito; os zeros à esquerda já estão preservados
    porque a fonte é texto, não número."""
    if not sql_raw:
        return None
    digits = re.sub(r"\D", "", sql_raw)
    if not digits:
        return None
    digits = digits.zfill(11)
    return digits[:6]


def carregar_quadras(path=REDUZIDO_GZ):
    """Gera (sql6, bairro_normalizado_ou_None) pra cada linha do cadastro
    reduzido. Streaming — nunca carrega o arquivo inteiro na memória."""
    equivalencias = carregar_equivalencias()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sq = setor_quadra_de_sql(row.get("sql"))
            if not sq:
                continue
            b = normalizar_bairro_iptu(row.get("bairro"), equivalencias)
            yield sq, b


def construir_votos_quadra(path=REDUZIDO_GZ):
    """{setor_quadra: {bairro_normalizado: contagem}} — a partir de TODO o
    cadastro do IPTU (não só onde já sabemos o bairro pelos 49 — aqui o
    "voto" é interno ao próprio cadastro do IPTU, que cobre a cidade
    inteira)."""
    votos = {}
    for sq, b in carregar_quadras(path):
        if b is None:
            continue
        votos.setdefault(sq, {}).setdefault(b, 0)
        votos[sq][b] += 1
    return votos


SIMILARIDADE_MIN = 0.82  # limiar do difflib.SequenceMatcher.ratio()


def _similares(a, b):
    """True se a/b são a mesma grafia com erro de digitação/truncamento —
    checa similaridade direta E se a string mais curta é sufixo/quase-
    sufixo da mais longa (achado real: "VILA CARMOZINA" vira "ZINA"/
    "OZINA" em algumas linhas — parece truncamento por limite de campo,
    corta o INÍCIO da string, não o fim, então SequenceMatcher sozinho
    nem sempre pega)."""
    if a == b:
        return True
    curta, longa = (a, b) if len(a) <= len(b) else (b, a)
    if len(curta) >= 4 and longa.endswith(curta):
        return True
    return SequenceMatcher(None, a, b).ratio() >= SIMILARIDADE_MIN


def _clusterizar_variantes(counts):
    """Agrupa grafias parecidas DENTRO de uma mesma quadra (nunca entre
    quadras diferentes — o escopo local evita juntar bairros de verdade
    diferentes que só COINCIDEM em textos parecidos). Começa pela grafia
    mais frequente (mais confiável) e absorve as variantes similares nela;
    retorna um novo dict {grafia_representante: contagem_somada}."""
    itens = sorted(counts.items(), key=lambda kv: -kv[1])
    clusters = []  # [(representante, contagem_total)]
    for nome, n in itens:
        destino = None
        for i, (rep, _) in enumerate(clusters):
            if _similares(nome, rep):
                destino = i
                break
        if destino is None:
            clusters.append([nome, n])
        else:
            clusters[destino][1] += n
    return {rep: n for rep, n in clusters}


def resolver_quadra_com_confianca(votos):
    """{setor_quadra: (bairro_majoritario, confianca_pct, n_lotes)}.
    confianca = % dos lotes da quadra (com bairro reconhecível, ou seja,
    não-lixo, e já agrupando variantes de grafia da mesma quadra) que
    concordam com o bairro majoritário."""
    out = {}
    for sq, counts in votos.items():
        agrupado = _clusterizar_variantes(counts) if len(counts) > 1 else counts
        total = sum(agrupado.values())
        bairro, n = sorted(agrupado.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        out[sq] = (bairro, round(100 * n / total, 1), total)
    return out


def nivel_confianca(pct):
    if pct >= 80:
        return "alta"
    if pct >= 60:
        return "media"
    return "baixa"
