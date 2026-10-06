#!/usr/bin/env python3
"""
Histórico de anúncios da rede nonStop (Rodada A, item 7 — 2026-10-06).

Registro PERSISTENTE da vida de cada anúncio, atualizado a cada execução do
build (Action diária). Um arquivo só, compacto, uma linha por anúncio
(JSON Lines, ordenado por código — o diff do git fica pequeno): historico/anuncios.jsonl.
Nada disso aparece na tela por enquanto; a base serve depois para "tempo no
mercado" e "margem de negociação".

Cada linha (campos):
  codigo           código do anúncio na nonStop (chave única)
  bairro, endereco, complemento (unidade), tipo (apartamento/casa), area (útil, m²), addr_key
  preco_inicial    preço na primeira vez que o anúncio foi visto
  preco_atual      preço na última vez visto
  mudancas_preco   [[data, novo_preco], ...] — só as mudanças, em ordem
  cadastro         data de cadastro do anúncio (YYYY-MM-DD, dado da nonStop)
  visto_primeira   primeira data em que o build viu o anúncio na rede
  visto_ultima     última data em que o build viu o anúncio na rede
  saida            data (do build) em que o anúncio NÃO apareceu mais; null = ativo
  voltas           (só aparece se > 0) quantas vezes sumiu e voltou

Datas em horário de Brasília (YYYY-MM-DD). A "saída" é o primeiro dia em que o
anúncio não veio mais — a saída real foi entre `visto_ultima` e `saida`.
O registro começa na data da primeira execução; anúncios que já existiam têm
`cadastro` (da nonStop) mas `visto_primeira` = esse primeiro dia.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent.parent / "historico" / "anuncios.jsonl"
BRASILIA = timezone(timedelta(hours=-3))  # sem horário de verão desde 2019


def data_brasilia(instante=None):
    """YYYY-MM-DD no horário de Brasília."""
    instante = instante or datetime.now(timezone.utc)
    return instante.astimezone(BRASILIA).strftime("%Y-%m-%d")


def _data_cadastro(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(BRASILIA).strftime("%Y-%m-%d")
    except ValueError:
        return None


def carregar(caminho=ARQUIVO):
    """dict[codigo] -> linha. Arquivo ausente = histórico vazio."""
    caminho = Path(caminho)
    estado = {}
    if not caminho.exists():
        return estado
    for n, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        if not linha.strip():
            continue
        try:
            r = json.loads(linha)
        except ValueError as e:
            raise SystemExit(f"{caminho}: linha {n} não é JSON válido ({e}) — arquivo de histórico corrompido, não vou sobrescrever.")
        if r["codigo"] in estado:
            raise SystemExit(f"{caminho}: código {r['codigo']} repetido (linha {n}) — arquivo de histórico corrompido.")
        estado[r["codigo"]] = r
    return estado


def serializar(estado):
    return "".join(
        json.dumps(estado[c], ensure_ascii=False, separators=(",", ":")) + "\n"
        for c in sorted(estado)
    )


def salvar(estado, caminho=ARQUIVO):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(serializar(estado), encoding="utf-8")


def atualizar(estado, registros, hoje):
    """Aplica a execução de `hoje` (YYYY-MM-DD) sobre o histórico `estado`
    (dict[codigo] -> linha, NÃO é alterado) usando os anúncios que a rede tem
    agora (`registros`, formato interno do nonstop_client, ANTES da
    deduplicação — cada código tem a sua própria vida).
    Retorna (novo_estado, resumo). Idempotente: rodar duas vezes no mesmo dia
    com os mesmos anúncios não muda nada."""
    novo = {c: {**r, "mudancas_preco": [list(m) for m in r.get("mudancas_preco", [])]} for c, r in estado.items()}
    vistos = set()
    resumo = {"novos": 0, "mudancas_de_preco": 0, "sairam": 0, "voltaram": 0, "ativos": 0}
    for rec in registros:
        codigo = rec.get("codigo")
        preco = rec.get("valor")
        if not codigo or not preco:
            continue
        vistos.add(codigo)
        campos = {
            "bairro": rec.get("bairro"),
            "endereco": rec.get("addr_display_building"),
            "complemento": rec.get("complemento"),
            "tipo": rec.get("tipo_imovel"),
            "area": rec.get("area"),
            "addr_key": rec.get("addr_key"),
        }
        r = novo.get(codigo)
        if r is None:
            novo[codigo] = {
                "codigo": codigo, **campos,
                "preco_inicial": preco, "preco_atual": preco, "mudancas_preco": [],
                "cadastro": _data_cadastro(rec.get("created_at")),
                "visto_primeira": hoje, "visto_ultima": hoje, "saida": None,
            }
            resumo["novos"] += 1
            continue
        r.update(campos)
        if not r.get("cadastro"):
            r["cadastro"] = _data_cadastro(rec.get("created_at"))
        if r["saida"] is not None:
            # Voltou à rede. Se a "saída" foi registrada hoje mesmo (rodada
            # anterior do mesmo dia que não viu o anúncio), não conta como volta.
            if r["saida"] != hoje:
                r["voltas"] = r.get("voltas", 0) + 1
                resumo["voltaram"] += 1
            r["saida"] = None
        if preco != r["preco_atual"]:
            if not r["mudancas_preco"] or r["mudancas_preco"][-1][0] != hoje:
                r["mudancas_preco"].append([hoje, preco])
            else:
                r["mudancas_preco"][-1][1] = preco
            r["preco_atual"] = preco
            resumo["mudancas_de_preco"] += 1
        if hoje > r["visto_ultima"]:
            r["visto_ultima"] = hoje
    for codigo, r in novo.items():
        if codigo not in vistos and r["saida"] is None:
            r["saida"] = hoje
            resumo["sairam"] += 1
    resumo["ativos"] = sum(1 for r in novo.values() if r["saida"] is None)
    resumo["total_no_arquivo"] = len(novo)
    return novo, resumo
