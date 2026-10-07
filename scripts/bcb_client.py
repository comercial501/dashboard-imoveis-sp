#!/usr/bin/env python3
"""
Contexto de crédito (Rodada C, item 2): séries públicas do Banco Central (API do SGS,
https://api.bcb.gov.br/dados/serie/bcdata.sgs.<código>/dados). Sem chave, sem cadastro.

Séries (códigos e nomes conferidos no portal de dados abertos do Banco Central em 07/10/2026):
  432    Taxa de juros - Meta Selic definida pelo Copom (% ao ano, diária)
  20772  Taxa média de juros das operações de crédito com recursos direcionados - Pessoas físicas -
         Financiamento imobiliário com taxas de mercado (% ao ano, mensal)
  20773  Taxa média de juros das operações de crédito com recursos direcionados - Pessoas físicas -
         Financiamento imobiliário com taxas reguladas (% ao ano, mensal) — o crédito do SFH/CMN
  13522  IPCA acumulado em 12 meses (% , mensal) — o título oficial não aparece no portal de dados
         abertos; confirmado porque o IPCA de 12 meses calculado a partir da série 433 (IPCA, variação
         mensal) bate exatamente com esta série.

Falha de API NUNCA trava nada: mantém o último valor bom (do data.json anterior), marcado como
desatualizado, e o relatório semanal avisa.
"""
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
BRASILIA = timezone(timedelta(hours=-3))
DIAS_HISTORICO = 800  # janela buscada (cobre 12 meses atrás com folga, mesmo em série mensal atrasada)

SERIES = [
    {
        "id": "selic", "codigo": 432, "nome": "Selic (meta)",
        "nome_oficial": "Taxa de juros - Meta Selic definida pelo Copom", "unidade": "% ao ano", "periodicidade": "diária",
        "explicacao": "Taxa básica de juros do país; quando sobe, o financiamento tende a ficar mais caro.",
    },
    {
        "id": "juros_imob_mercado", "codigo": 20772, "nome": "Juros do financiamento imobiliário (taxas de mercado)",
        "nome_oficial": "Taxa média de juros das operações de crédito com recursos direcionados - Pessoas físicas - Financiamento imobiliário com taxas de mercado",
        "unidade": "% ao ano", "periodicidade": "mensal",
        "explicacao": "Juro médio cobrado de pessoas físicas nos novos financiamentos imobiliários a taxas de mercado (bancos, fora das regras do SFH).",
    },
    {
        "id": "juros_imob_regulada", "codigo": 20773, "nome": "Juros do financiamento imobiliário (taxas reguladas — SFH)",
        "nome_oficial": "Taxa média de juros das operações de crédito com recursos direcionados - Pessoas físicas - Financiamento imobiliário com taxas reguladas",
        "unidade": "% ao ano", "periodicidade": "mensal",
        "explicacao": "Juro médio dos novos financiamentos imobiliários com regras e teto do governo (a faixa do SFH); costuma ser menor que o de mercado.",
    },
    {
        "id": "ipca_12m", "codigo": 13522, "nome": "IPCA acumulado em 12 meses",
        "nome_oficial": "IPCA acumulado em 12 meses (SGS 13522; conferida contra a série 433, IPCA variação mensal)",
        "unidade": "% em 12 meses", "periodicidade": "mensal",
        "explicacao": "Inflação oficial dos últimos 12 meses; o aluguel e o preço dos imóveis costumam ser corrigidos olhando para ela.",
    },
]


def hoje_brasilia(agora=None):
    return (agora or datetime.now(timezone.utc)).astimezone(BRASILIA).date()


def _parse_data(txt):
    d, m, a = txt.split("/")
    return date(int(a), int(m), int(d))


def buscar_pontos(codigo, hoje, tentativas=3, timeout=30, abrir=urllib.request.urlopen):
    """[(data, valor)] ordenado, só com data <= hoje (a série da Selic traz datas futuras)."""
    ini = (hoje - timedelta(days=DIAS_HISTORICO)).strftime("%d/%m/%Y")
    fim = hoje.strftime("%d/%m/%Y")
    url = BASE.format(codigo=codigo) + f"?formato=json&dataInicial={ini}&dataFinal={fim}"
    ultimo_erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "torre-de-controle-topio"})
            with abrir(req, timeout=timeout) as r:
                bruto = json.loads(r.read().decode("utf-8"))
            pontos = sorted((_parse_data(x["data"]), float(x["valor"])) for x in bruto if x.get("valor") not in (None, ""))
            pontos = [p for p in pontos if p[0] <= hoje]
            if not pontos:
                raise ValueError("a API respondeu sem nenhum valor válido")
            return pontos
        except (urllib.error.URLError, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            ultimo_erro = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"série {codigo}: {ultimo_erro!r}")


def _mes_atras(d, meses):
    idx = d.year * 12 + d.month - 1 - meses
    ano, mes = divmod(idx, 12)
    dia = min(d.day, 28)
    return date(ano, mes + 1, dia)


def _ate(pontos, alvo):
    """Último ponto com data <= alvo (ou None)."""
    cand = [p for p in pontos if p[0] <= alvo]
    return cand[-1] if cand else None


def montar_serie(cfg, pontos, consultado_em):
    atual = pontos[-1]
    ant = _ate(pontos, _mes_atras(atual[0], 1) if cfg["periodicidade"] == "diária" else _mes_atras(atual[0], 1))
    ano = _ate(pontos, _mes_atras(atual[0], 12))
    if cfg["periodicidade"] == "mensal":
        # mensal: o ponto do mês anterior é o ponto anterior da série (datas são dia 1 de cada mês)
        ant = pontos[-2] if len(pontos) >= 2 else None
    if ano is not None and ano[0] >= atual[0]:
        ano = None
    if ant is not None and ant[0] >= atual[0]:
        ant = None
    serie = {
        "id": cfg["id"], "codigo": cfg["codigo"], "nome": cfg["nome"], "nome_oficial": cfg["nome_oficial"],
        "fonte": f"Banco Central do Brasil — SGS, série {cfg['codigo']}",
        "url": f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cfg['codigo']}/dados/ultimos/1?formato=json",
        "unidade": cfg["unidade"], "periodicidade": cfg["periodicidade"], "explicacao": cfg["explicacao"],
        "valor": atual[1], "data": atual[0].isoformat(),
        "valor_mes_anterior": ant[1] if ant else None, "data_mes_anterior": ant[0].isoformat() if ant else None,
        "var_mes_pp": round(atual[1] - ant[1], 2) if ant else None,
        "valor_12m": ano[1] if ano else None, "data_12m": ano[0].isoformat() if ano else None,
        "var_12m_pp": round(atual[1] - ano[1], 2) if ano else None,
        "consultado_em": consultado_em, "desatualizado": False, "erro": None,
    }
    return serie


def buscar_contexto(anterior=None, agora=None, buscar=buscar_pontos):
    """Retorna o dict `contexto_credito` do data.json. `anterior` = o mesmo dict do data.json
    publicado antes (fonte do "último valor válido"). Nunca levanta por falha de API."""
    agora = agora or datetime.now(timezone.utc)
    hoje = hoje_brasilia(agora)
    consultado = agora.isoformat()
    antigas = {s["id"]: s for s in ((anterior or {}).get("series") or [])}
    series, falhas = [], []
    for cfg in SERIES:
        try:
            series.append(montar_serie(cfg, buscar(cfg["codigo"], hoje), consultado))
        except Exception as e:  # noqa: BLE001 — fonte secundária: nunca derruba o build
            falhas.append(cfg["id"])
            velho = antigas.get(cfg["id"])
            if velho:
                series.append({**velho, "desatualizado": True, "erro": str(e)[:200]})
            else:
                series.append({
                    "id": cfg["id"], "codigo": cfg["codigo"], "nome": cfg["nome"], "nome_oficial": cfg["nome_oficial"],
                    "fonte": f"Banco Central do Brasil — SGS, série {cfg['codigo']}", "unidade": cfg["unidade"],
                    "periodicidade": cfg["periodicidade"], "explicacao": cfg["explicacao"],
                    "valor": None, "data": None, "valor_mes_anterior": None, "data_mes_anterior": None, "var_mes_pp": None,
                    "valor_12m": None, "data_12m": None, "var_12m_pp": None,
                    "consultado_em": None, "desatualizado": True, "erro": str(e)[:200],
                })
    return {"consultado_em": consultado, "series": series, "falhas": falhas}


if __name__ == "__main__":
    ctx = buscar_contexto()
    for s in ctx["series"]:
        print(f"{s['nome']}: {s['valor']} ({s['data']}) | mês anterior {s['valor_mes_anterior']} ({s['var_mes_pp']} pp) | 12m atrás {s['valor_12m']} ({s['var_12m_pp']} pp) | {'FALHOU: ' + s['erro'] if s['erro'] else 'ok'}")
