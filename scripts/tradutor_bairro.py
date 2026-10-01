#!/usr/bin/env python3
"""
Tradução de nome de cadastro (IPTU) -> bairro de mercado, pela tabela
`bairros_mercado_preenchido.csv` que o usuário revisou e preencheu à mão
(2026-09-30, "fim das regiões") — substitui a abordagem anterior de
"região por CEP majoritário", que tinha um problema real: uma ÚNICA
linha do ITBI com bairro="PLANALTO PAULISTA" mas CEP de Zona Norte
(02402025 — erro de digitação, provavelmente; é a única linha da cidade
inteira nessa combinação) virava o voto MAJORITÁRIO (e único) daquele
CEP5 inteiro, porque nenhum bairro de Zona Norte existe nos 49 da
carteira pra disputar o voto — isso "puxava" milhares de imóveis do IPTU
genuinamente de Santana/Zona Norte pra dentro da "região de Planalto
Paulista" em bairros_mercado.csv. A abordagem por nome elimina essa
classe de erro inteira: cada nome de cadastro tem UM destino fixo,
nunca "herda" de uma região potencialmente contaminada.

A carteira cresce de 49 pra 74 bairros (49 atuais + 25 NOVO_BAIRRO).
"""
import csv
import gzip
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRADUTOR_CSV = ROOT / "data" / "iptu_geosampa" / "raw" / "bairros_mercado_preenchido.csv"

STATUS_CARTEIRA = {"AUTO_CARTEIRA", "NOVO_BAIRRO"}
STATUS_FORA = {"SUGERIDO_FORA", "PADRAO_FORA"}
STATUS_IGNORAR = {"AUTO_IGNORAR"}

# Achado de 2026-09-30 (correção de regressão): um nome que simplesmente
# não apareceu na tabela (ex: "ITAQUERA", "SANTANA" — bairros reais, só
# longe demais de qualquer um dos 49/74 pra terem entrado numa região da
# rodada anterior) é "fora_carteira", NÃO "incerto" — incerto é só quando
# não há NENHUM nome reconhecível (vazio, ou lixo tipo "TORRE 1"/"BLOCO
# B"/número solto). Mesmo padrão de lixo usado em iptu_geosampa.py.
_GARBAGE_RE = re.compile(
    r"^\s*(\d+|(TORRE|BLOCO|BL|AP|APTO|APART|VAGA|VG|GARAGEM|SALA|LOJA|LT|UNID|UNIDADE|CASA|COND|CONDOMINIO|ED|RES)\b.*)?\s*$",
    re.IGNORECASE,
)


def _parece_bairro(bairro_raw):
    s = (bairro_raw or "").strip()
    return bool(s) and not _GARBAGE_RE.match(s)

NUM_PLACEHOLDER = "99999"


def _chave(bairro_raw):
    return (bairro_raw or "").strip().upper()


def carregar_tradutor(path=TRADUTOR_CSV):
    """{nome_cadastro_iptu (upper+strip): (bairro_mercado, status)}.
    Conferido: 0 inconsistências (mesmo nome_cadastro_iptu sempre aponta
    pro mesmo destino, em qualquer região onde apareceu na tabela
    original)."""
    tradutor = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            chave = _chave(row["nome_cadastro_iptu"])
            if chave in tradutor and tradutor[chave] != (row["bairro_mercado"], row["status"]):
                raise ValueError(f"inconsistência em '{chave}': {tradutor[chave]} != {(row['bairro_mercado'], row['status'])}")
            tradutor[chave] = (row["bairro_mercado"], row["status"])
    return tradutor


def targets74(tradutor):
    """Lista ordenada dos 74 bairros (49 da carteira atual + os NOVO_BAIRRO
    da tabela) — os 25 novos são derivados da própria tabela (nunca
    hardcoded, pra nunca dessincronizar se o usuário editar
    bairros_mercado_preenchido.csv), mas os 49 antigos SEMPRE entram,
    mesmo que algum não tenha nenhuma linha AUTO_CARTEIRA na tabela
    (achado: "Jardim Caravelas" é pequeno/obscuro demais — nenhuma grafia
    sua teve 5+ ocorrências em nenhuma região pra entrar na tabela original
    — continua na carteira, só que com 0 vendas/unidades até aparecer
    alguma linha que aponte pra ele)."""
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from normalize import TARGETS

    novos = {destino for destino, status in tradutor.values() if status == "NOVO_BAIRRO"}
    return sorted(set(TARGETS) | novos)


def traduzir(bairro_raw, tradutor):
    """(destino, status) — destino é um dos 74 só quando status é
    AUTO_CARTEIRA/NOVO_BAIRRO. status None = nome não está na tabela
    (nem carteira, nem fora, nem lixo conhecido) — quem chama decide o
    fallback (voto por endereço, quadra, CEP)."""
    return tradutor.get(_chave(bairro_raw), (None, None))


def construir_votos_quadra_traduzido(tradutor, path=None):
    """{setor_quadra: (bairro_majoritario_74, confianca_pct, n_lotes)} —
    substitui iptu_geosampa.construir_votos_quadra()/resolver_quadra_com_
    confianca() pra esta nova abordagem: cada linha do IPTU traduz direto
    pela tabela (sem normalizar_bairro_iptu/clusterizar_variantes — a
    tabela já é a consolidação manual, mais confiável que o agrupamento
    automático por similaridade). Só linhas que traduzem pra
    AUTO_CARTEIRA/NOVO_BAIRRO votam; confiança = % dos votos válidos da
    quadra que concordam com o majoritário (mesma definição de antes)."""
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import iptu_geosampa as ig
    from iptu_geosampa import nivel_confianca

    votos = {}
    with gzip.open(path or ig.REDUZIDO_GZ, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            destino, status = traduzir(row.get("bairro"), tradutor)
            if status not in STATUS_CARTEIRA:
                continue
            sq = ig.setor_quadra_de_sql(row.get("sql"))
            if not sq:
                continue
            votos.setdefault(sq, Counter())[destino] += 1

    out = {}
    for sq, counts in votos.items():
        total = sum(counts.values())
        destino, n = counts.most_common(1)[0]
        out[sq] = (destino, round(100 * n / total, 1), total)
    return out


class Cascata:
    """Cascata de 5 métodos + incerto/fora, construída UMA VEZ a partir
    de uma fonte de registros (campo bairro + endereço + CEP + SQL) e
    reutilizável pra resolver qualquer outro registro do MESMO universo
    (ITBI ou IPTU, nunca misturados — cada lado vota com seus próprios
    dados, por pedido do usuário: "usar a mesma cascata para as vendas e
    para as unidades" significa mesma LÓGICA, não os mesmos votos)."""

    def __init__(self, tradutor, targets, votos_quadra_resolvidos, quadras_qualquer_bairro=None):
        """votos_quadra_resolvidos: saída de construir_votos_quadra_traduzido()
        — {setor_quadra: (destino_74_ja_traduzido, confianca_pct, n)}.
        quadras_qualquer_bairro: set opcional de setor+quadra que têm ALGUM
        bairro majoritário reconhecível no IPTU, mesmo que não seja um dos
        74 (de iptu_geosampa.construir_votos_quadra(), que não filtra pelos
        74) — usado só pra decidir fora_carteira vs incerto quando nada
        resolve pros 74: sem isso, uma quadra inteira de bairro real mas
        fora da carteira (ex: Itaquera) virava "incerto" em vez de
        "fora_carteira" (achado/regressão de 2026-09-30, corrigido aqui)."""
        self.tradutor = tradutor
        self.targets = set(targets)
        self.addr_votes = {}
        self.cep_votes = {}
        self.quadras_qualquer_bairro = quadras_qualquer_bairro or set()
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from iptu_geosampa import nivel_confianca

        self.quadra74 = {
            sq: (destino, nivel_confianca(pct))
            for sq, (destino, pct, _n) in votos_quadra_resolvidos.items()
        }

    def alimentar_votos(self, registros, get_bairro_raw, get_addr_key, get_cep, get_num_norm):
        """Constrói os votos de endereço/CEP a partir de um universo de
        registros — só conta quem já traduz (tier 1) pra um dos 74."""
        addr_counts = {}
        cep_counts = {}
        for r in registros:
            destino, status = traduzir(get_bairro_raw(r), self.tradutor)
            if status not in STATUS_CARTEIRA:
                continue
            akey = get_addr_key(r)
            if akey:
                addr_counts.setdefault(akey, Counter())[destino] += 1
            cep = get_cep(r)
            if cep:
                cep_counts.setdefault(cep, Counter())[destino] += 1

        def majority(d):
            return {k: c.most_common(1)[0][0] for k, c in d.items()}

        self.addr_votes = majority(addr_counts)
        self.cep_votes = majority(cep_counts)

    def resolver(self, bairro_raw, addr_key, cep, sq, num_norm=None):
        """Retorna (destino_ou_None, metodo). metodo em: campo_original,
        voto_endereco, quadra_alta, cep, quadra_media, fora_carteira,
        incerto. destino só não é None quando metodo resolve pra um dos
        74; "fora_carteira" e "incerto" sempre têm destino None (a
        diferença entre os dois é só informativa — fora_carteira tem
        nome de bairro real, só não é um dos 74)."""
        destino, status = traduzir(bairro_raw, self.tradutor)
        if status in STATUS_CARTEIRA:
            return destino, "campo_original"
        if status in STATUS_FORA:
            return None, "fora_carteira"
        # status None (nome desconhecido, fora da tabela) ou AUTO_IGNORAR
        # (lixo tipo torre/bloco) cai pra próxima camada.
        if num_norm != NUM_PLACEHOLDER:
            v = self.addr_votes.get(addr_key)
            if v in self.targets:
                return v, "voto_endereco"
        info = self.quadra74.get(sq)
        if info and info[1] == "alta":
            return info[0], "quadra_alta"
        v = self.cep_votes.get(cep)
        if v in self.targets:
            return v, "cep"
        if info and info[1] == "media":
            return info[0], "quadra_media"
        # Nenhum método resolveu pra um dos 74 — decide fora_carteira (tem
        # nome de bairro real, só não é um dos 74) vs incerto (não tem
        # nome nenhum, ou é lixo tipo torre/bloco/número solto).
        if status == "AUTO_IGNORAR":
            return None, "incerto"
        if _parece_bairro(bairro_raw) or sq in self.quadras_qualquer_bairro:
            return None, "fora_carteira"
        return None, "incerto"
