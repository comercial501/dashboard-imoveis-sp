"""Calculadora de preço de apartamento (protótipo, 2026-10-10).

Duas partes, as duas neste arquivo:

1. preparar_dados(): monta, a cada build, o arquivo site/calculadora.json — as
   revendas limpas de APARTAMENTO (a mesma camada limpa do resto do painel), cada
   uma já atualizada para o preço de hoje pelo índice da Rodada A2, com o andar
   lido do complemento do ITBI ("AP 152" = 15º andar) e a tabela de quanto o
   andar pesa no preço, medida nos próprios dados.

2. estimar() / anuncios_parecidos(): o cálculo da tela. É espelhado, linha a
   linha, em site/calculadora.js; scripts/verificar_interface.py compara os dois
   em centenas de casos (paridade Python x navegador).

Regras do cálculo (todas visíveis na tela, nada escondido):
- O ITBI e o IPTU usam a MESMA área (área construída do cadastro). Por isso o
  cálculo compara a área construída do cadastro — não a área útil da planta,
  que no ITBI não existe (e vem 10% a 80% menor, conforme o prédio).
- Três níveis, do mais confiável ao menos: mesmo prédio -> mesma rua (mesmo
  bairro) -> bairro. O primeiro nível com vendas parecidas suficientes vence.
- Quartos, banheiros, suítes, vagas, condomínio e IPTU NÃO mudam o preço: o ITBI
  não traz esses dados. Servem para escolher os anúncios parecidos e para o resumo.
"""
import math
import re
from collections import Counter

from normalize import excel_serial_to_ym, haversine_km, TARGETS

# --- parâmetros do cálculo (os mesmos valores vão para o calculadora.json e a tela mostra) ---
AREA_MIN, AREA_MAX = 10, 2000          # mesma faixa que a tela aceita no campo de área
MESMO_PREDIO_KM = 3.0                  # o mesmo endereço em bairros a até 3 km um do outro = o mesmo prédio
INICIO_VENDAS_YM = 202401              # só vendas de jan/2024 em diante (início do índice de correção de tempo)
CALC_TOL_AREA_PREDIO = (0.10, 0.20)   # tolerância de área: 1ª tentativa, 2ª tentativa (ampliada)
CALC_MIN_PREDIO = 3                   # vendas parecidas mínimas pra usar o nível "prédio"
CALC_TOL_AREA_RUA = (0.15, 0.25)
CALC_MIN_RUA = 5
CALC_TOL_AREA_BAIRRO = (0.15, 0.30)
CALC_MIN_BAIRRO = 10
CALC_MIN_PARA_QUARTIS = 5             # com 5+ vendas a faixa é P25–P75; com menos, mínimo–máximo
CALC_ALTA_MIN_VENDAS = 5              # confiança alta: prédio com 5+ vendas parecidas e preços parecidos
CALC_RAZAO_MAX_ALTA = 1.25            # P75 ÷ P25 de até 1,25 (mesma regra do Valor de Oportunidade)
CALC_MEDIA_RUA_MIN = 8                # confiança média na rua: 8+ vendas parecidas
CALC_RAZAO_MAX_MEDIA_RUA = 1.35
CALC_PRECISAO_TESTES = 3000           # vendas retiradas e re-estimadas, por nível, pra medir o erro de verdade
CALC_PRECISAO_MIN_TESTES = 100        # combinação nível+confiança com menos testes que isso usa o nível inteiro
CALC_MARGEM_FALLBACK = 0.35           # sem teste suficiente nem no nível inteiro (não deve acontecer)
CALC_MARGEM_MIN, CALC_MARGEM_MAX = 0.03, 0.60
CALC_MAX_SIMILARES = 8
CALC_MAX_ANUNCIOS = 8
CALC_TOL_ANUNCIO_AREA = 0.25          # anúncio parecido: área útil informada ±25%
CALC_TOL_ANUNCIO_VALOR = 0.30         # sem área útil informada: valor dentro de ±30% da estimativa
CALC_ANDAR_FAIXAS = [(1, 3), (4, 7), (8, 11), (12, 15), (16, 99)]
CALC_ANDAR_MIN_VENDAS_FAIXA = 200     # faixa com menos que isso nos dados = sem ajuste (fator 1)
CALC_ANDAR_CAP = (0.90, 1.10)
CALC_ANDAR_GRUPO_MIN = 4              # grupo (prédio + mesma área) com 4+ vendas...
CALC_ANDAR_GRUPO_AMPLITUDE = 5        # ...espalhadas por pelo menos 5 andares

_RE_APTO = re.compile(r"(?:\bAP|\bAPTO|\bAPT|\bAPARTAMENTO)\.?\s*0*(\d{1,4})\b", re.I)
_RE_VAGAS_N = re.compile(r"(\d)\s*V\s?G", re.I)
_RE_VAGA_UMA = re.compile(r"\bE\s*V\s?G|\bVAGA\b", re.I)


def _arred(x):
    """Arredonda pra inteiro igual em Python e JS (metade sobe, também nos negativos: Math.round)."""
    return math.floor(x + 0.5)


def _dec(x, casas):
    """Arredonda pra `casas` decimais igual ao JS (Math.round(x * 10**casas) / 10**casas)."""
    f = 10 ** casas
    return _arred(x * f) / f


def _mediana(v):
    v = sorted(v)
    n = len(v)
    if n == 0:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _percentil(p, v):
    v = sorted(v)
    n = len(v)
    if n == 0:
        return None
    if n == 1:
        return v[0]
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    frac = idx - lo
    hi = min(lo + 1, n - 1)
    return v[lo] + (v[hi] - v[lo]) * frac


def numero_do_apto(complemento):
    """Número da unidade escrito no complemento do ITBI ("AP 152" -> 152) ou None."""
    m = _RE_APTO.search(complemento or "")
    return int(m.group(1)) if m else None


def vagas_do_complemento(complemento):
    """Vagas escritas no complemento ("E 2 VG" -> 2; "E VG" -> 1) ou None quando não diz."""
    c = complemento or ""
    m = _RE_VAGAS_N.search(c)
    if m:
        return int(m.group(1))
    return 1 if _RE_VAGA_UMA.search(c) else None


def convencao_do_predio(numeros):
    """Como o prédio numera os apartamentos: "c" = centenas (801 = 8º andar, final 01; 1704 = 17º, final 04) ou
    "d" = dezenas (152 = 15º andar, final 2; 62 = 6º, final 2), como no exemplo do Paulo. É "c" se o prédio tem
    unidade de 4 dígitos, ou se todas as de 3 dígitos terminam em 01–20 (101, 102, 201...). Senão, "d"."""
    tem4 = any(n >= 1000 for n in numeros)
    tres = [n for n in numeros if 100 <= n <= 999]
    return "c" if (tem4 or (bool(tres) and all(n % 100 <= 20 for n in tres))) else "d"


def andar_e_final(n, conv):
    """(andar, final) do apartamento de número n numa convenção ("c" ou "d"); (None, None) se não der (1 dígito ou
    andar fora de 1–60). O "final" identifica a posição no andar — mesmo final no mesmo prédio = mesma planta."""
    if n < 10:
        return None, None
    if n >= 1000 or (100 <= n <= 999 and conv == "c"):
        andar, final = n // 100, n % 100
    else:
        andar, final = n // 10, n % 10
    return (andar, final) if 1 <= andar <= 60 else (None, None)


def andares_do_predio(numeros):
    """{numero: andar} para as unidades de UM prédio (ver convencao_do_predio / andar_e_final)."""
    conv = convencao_do_predio(numeros)
    out = {}
    for n in set(numeros):
        a, _f = andar_e_final(n, conv)
        if a is not None:
            out[n] = a
    return out


def faixa_andar(andar):
    for i, (de, ate) in enumerate(CALC_ANDAR_FAIXAS):
        if de <= andar <= ate:
            return i
    return None


def _fator_andar(efeito, andar):
    """Quanto o preço (R$/m²) dessa faixa de andar costuma ser, em relação à mediana do mesmo prédio. Sem
    andar ou faixa sem vendas suficientes = 1,0 (sem ajuste)."""
    if andar is None:
        return 1.0
    i = faixa_andar(andar)
    if i is None:
        return 1.0
    return efeito[i]["fator"]


def _compute_efeito_andar(vendas_por_predio):
    """Mede nos dados quanto o andar pesa no preço: dentro do mesmo prédio, só unidades com a MESMA área
    (mesma planta), preço de hoje, comparado com a mediana do grupo. Mediana por faixa de andar."""
    rel = {i: [] for i in range(len(CALC_ANDAR_FAIXAS))}
    for vs in vendas_por_predio.values():
        grupos = {}
        for v in vs:
            if v["andar"] is not None:
                grupos.setdefault(round(v["area"]), []).append(v)
        for g in grupos.values():
            if len(g) < CALC_ANDAR_GRUPO_MIN:
                continue
            andares = [v["andar"] for v in g]
            if max(andares) - min(andares) < CALC_ANDAR_GRUPO_AMPLITUDE:
                continue
            med = _mediana([v["valor_hoje"] for v in g])
            for v in g:
                i = faixa_andar(v["andar"])
                if i is not None:
                    rel[i].append(v["valor_hoje"] / med)
    out = []
    for i, (de, ate) in enumerate(CALC_ANDAR_FAIXAS):
        n = len(rel[i])
        fator = 1.0
        if n >= CALC_ANDAR_MIN_VENDAS_FAIXA:
            fator = min(CALC_ANDAR_CAP[1], max(CALC_ANDAR_CAP[0], _mediana(rel[i])))
        out.append({"de": de, "ate": ate, "n": n, "fator": round(fator, 4)})
    return out


def preparar_dados(itbi_records, usn_records, indice, fator_fn, gerado_em_iso, centroides=None):
    """Monta o conteúdo do calculadora.json. `fator_fn(indice, bairro, tipo, day)` = correção de tempo da
    Rodada A2 (engine._fator_tempo); `indice` = engine._compute_indice_tempo."""
    mes_base = "%04d-%02d" % indice["mes_base"]
    bairros = list(TARGETS)
    b_idx = {b: i for i, b in enumerate(bairros)}

    brutas = []
    for r in itbi_records:
        if r["tipo_imovel"] != "apartamento" or not (r.get("is_revenda") and r.get("is_clean_sale")):
            continue
        if r["bairro"] not in b_idx or r["day"] is None or not r.get("area") or not r.get("addr_key") or not (AREA_MIN <= r["area"] <= AREA_MAX):
            continue  # área de 4 m² ou 5.000 m² no cadastro é erro de digitação, não apartamento
        ano, mes = excel_serial_to_ym(r["day"])
        if ano * 100 + mes < INICIO_VENDAS_YM:  # vendas registradas atrasadas (2020–2023): o índice de tempo só começa em 2024
            continue
        brutas.append(r)

    # O mesmo prédio às vezes cai em dois ou três bairros vizinhos na resolução de bairro (ex.: Rua João Cachoeira, 892
    # em Itaim Bibi, Jardim Paulista e Vila Nova Conceição), o que partia as vendas dele. Junta no bairro com mais vendas
    # quando os bairros ficam a até MESMO_PREDIO_KM um do outro (distância entre os centros dos anúncios). Endereços
    # homônimos em bairros distantes continuam separados.
    centroides = centroides or {}
    n_por = {}
    for r in brutas:
        n_por.setdefault(r["addr_key"], Counter())[r["bairro"]] += 1
    bairro_do_predio = {}
    for ak, cont in n_por.items():
        dom = sorted(cont.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        for b in cont:
            ca, cb = centroides.get(dom), centroides.get(b)
            junta = b == dom or (ca and cb and haversine_km(ca[0], ca[1], cb[0], cb[1]) <= MESMO_PREDIO_KM)
            bairro_do_predio[(ak, b)] = dom if junta else b
    # número de unidade por prédio -> andar (a convenção de numeração é do prédio)
    chave = lambda r: (r["addr_key"], bairro_do_predio[(r["addr_key"], r["bairro"])])
    numeros = {}
    for r in brutas:
        n = numero_do_apto(r.get("complemento"))
        if n is not None:
            numeros.setdefault(chave(r), []).append(n)
    conv_map = {k: convencao_do_predio(v) for k, v in numeros.items()}

    predios_idx, predios, ruas_idx, ruas = {}, [], {}, []
    displays = {}
    for r in brutas:
        displays.setdefault(chave(r), Counter())[r["addr_display"]] += 1
    vendas = []
    vendas_por_predio = {}
    for r in sorted(brutas, key=lambda r: (chave(r)[1], r["addr_key"], r["bairro"], r["day"], r["valor"])):
        k = chave(r)
        if k not in predios_idx:
            display = displays[k].most_common(1)[0][0]
            rua_nome = display.rsplit(",", 1)[0].strip()
            rk = (r["addr_key"].split("|")[0], k[1])
            if rk not in ruas_idx:
                ruas_idx[rk] = len(ruas)
                ruas.append([rua_nome, b_idx[k[1]]])
            predios_idx[k] = len(predios)
            predios.append([r["addr_key"], display, b_idx[k[1]], ruas_idx[rk], conv_map.get(k, "d")])
        n = numero_do_apto(r.get("complemento"))
        andar, final = andar_e_final(n, conv_map.get(k, "d")) if n is not None else (None, None)
        fator = fator_fn(indice, r["bairro"], "apartamento", r["day"])
        ano, mes = excel_serial_to_ym(r["day"])
        v = {"andar": andar, "area": r["area"], "valor_hoje": r["valor"] * fator}
        vendas_por_predio.setdefault(k, []).append(v)
        vendas.append([predios_idx[k], ano * 100 + mes, _arred(r["valor"]), r["area"], andar,
                       vagas_do_complemento(r.get("complemento")), round(fator, 4), n if andar is not None else None, final])

    efeito = _compute_efeito_andar(vendas_por_predio)

    anuncios = []
    for u in usn_records:
        if u.get("tipo_imovel") != "apartamento" or u["bairro"] not in b_idx or not u.get("valor"):
            continue
        bp = bairro_do_predio.get((u.get("addr_key"), u["bairro"]), u["bairro"])
        k = (u["addr_key"], bp) if u.get("addr_key") else None
        pi = predios_idx.get(k, -1) if k else -1
        rua_i = -1
        if u.get("addr_key"):
            rua_i = ruas_idx.get((u["addr_key"].split("|")[0], bp), -1)
        anuncios.append([pi, b_idx[u["bairro"]], rua_i, u["addr_display"], u["valor"], u.get("area"), u.get("quartos"),
                         u.get("vagas"), u.get("codigo"), u.get("link"), u.get("idade_dias")])
    anuncios.sort(key=lambda a: (a[1], a[3] or "", a[8] or ""))

    dados = {
        "versao": 1,
        "gerado_em_iso": gerado_em_iso,
        "mes_base": mes_base,
        "bairros": bairros,
        "ruas": ruas,
        "predios": predios,
        "vendas": vendas,
        "anuncios": anuncios,
        "efeito_andar": efeito,
        "parametros": {
            "tol_area_predio": list(CALC_TOL_AREA_PREDIO), "min_predio": CALC_MIN_PREDIO,
            "tol_area_rua": list(CALC_TOL_AREA_RUA), "min_rua": CALC_MIN_RUA,
            "tol_area_bairro": list(CALC_TOL_AREA_BAIRRO), "min_bairro": CALC_MIN_BAIRRO,
            "min_quartis": CALC_MIN_PARA_QUARTIS, "alta_min_vendas": CALC_ALTA_MIN_VENDAS, "razao_max_alta": CALC_RAZAO_MAX_ALTA,
            "media_rua_min": CALC_MEDIA_RUA_MIN, "razao_max_media_rua": CALC_RAZAO_MAX_MEDIA_RUA,
            "precisao_min_testes": CALC_PRECISAO_MIN_TESTES, "margem_fallback": CALC_MARGEM_FALLBACK,
            "margem_min": CALC_MARGEM_MIN, "margem_max": CALC_MARGEM_MAX, "max_similares": CALC_MAX_SIMILARES, "max_anuncios": CALC_MAX_ANUNCIOS,
            "tol_anuncio_area": CALC_TOL_ANUNCIO_AREA, "tol_anuncio_valor": CALC_TOL_ANUNCIO_VALOR,
        },
        "resumo": {
            "vendas": len(vendas), "predios": len(predios), "ruas": len(ruas), "anuncios": len(anuncios),
            "vendas_com_andar": sum(1 for v in vendas if v[4] is not None),
        },
    }
    dados["precisao"] = calibrar_precisao(dados)
    return dados


# ---------------------------------------------------------------------------
# Cálculo da tela (espelhado em site/calculadora.js)
# ---------------------------------------------------------------------------
def indexar(dados):
    """Agrupa as vendas por prédio, rua e bairro (uma vez só, depois de carregar o arquivo)."""
    por_predio, por_rua, por_bairro = {}, {}, {}
    predios, ruas = dados["predios"], dados["ruas"]
    for i, v in enumerate(dados["vendas"]):
        p = predios[v[0]]
        por_predio.setdefault(v[0], []).append(i)
        por_rua.setdefault(p[3], []).append(i)
        por_bairro.setdefault(p[2], []).append(i)
    return {"predio": por_predio, "rua": por_rua, "bairro": por_bairro}


def _selecionar(dados, ids, area, tol):
    vs = dados["vendas"]
    return [i for i in ids if abs(vs[i][3] - area) / area <= tol]


def _escolher_nivel(dados, ids, area, tols, minimo):
    """Primeira tolerância (a apertada, depois a ampliada) com vendas parecidas suficientes."""
    for j, tol in enumerate(tols):
        sel = _selecionar(dados, ids, area, tol)
        if len(sel) >= minimo:
            return sel, tol, j == 1
    return None, None, False


def _estimar_base(dados, idx, entrada):
    """Cálculo das vendas parecidas (sem a margem de erro). entrada: {"predio": int|None, "rua": int|None, "bairro": int, "area": m² do cadastro, "andar": int|None,
    "preco_pedido": R$|None, "area_util": m²|None}. Devolve o dicionário do resultado ou
    {"ok": False, "motivo": ...}."""
    area = entrada["area"]
    andar = entrada.get("andar")
    p = dados["parametros"]
    vs = dados["vendas"]
    efeito = dados["efeito_andar"]
    escolhido = None
    if entrada.get("predio") is not None:
        sel, tol, ampliada = _escolher_nivel(dados, idx["predio"].get(entrada["predio"], []), area, p["tol_area_predio"], p["min_predio"])
        if sel:
            escolhido = ("predio", sel, tol, ampliada)
    if escolhido is None and entrada.get("rua") is not None:
        sel, tol, ampliada = _escolher_nivel(dados, idx["rua"].get(entrada["rua"], []), area, p["tol_area_rua"], p["min_rua"])
        if sel:
            escolhido = ("rua", sel, tol, ampliada)
    if escolhido is None:
        sel, tol, ampliada = _escolher_nivel(dados, idx["bairro"].get(entrada["bairro"], []), area, p["tol_area_bairro"], p["min_bairro"])
        if sel:
            escolhido = ("bairro", sel, tol, ampliada)
    if escolhido is None:
        return {"ok": False, "motivo": "poucas_vendas"}
    nivel, sel, tol, ampliada = escolhido

    f_user = _fator_andar(efeito, andar)
    m2 = []
    for i in sel:
        v = vs[i]
        f_v = _fator_andar(efeito, v[4])
        m2.append(v[2] * v[6] / v[3] / f_v * f_user)
    n = len(m2)
    mid_m2 = _mediana(m2)
    if n >= p["min_quartis"]:
        lo_m2, hi_m2 = _percentil(25, m2), _percentil(75, m2)
    else:
        lo_m2, hi_m2 = min(m2), max(m2)
    razao = (_percentil(75, m2) / _percentil(25, m2)) if n >= 2 and _percentil(25, m2) else None
    estimativa, minimo, maximo = _arred(mid_m2 * area), _arred(lo_m2 * area), _arred(hi_m2 * area)

    if nivel == "predio" and n >= p["alta_min_vendas"] and razao is not None and razao <= p["razao_max_alta"]:
        confianca = "alta"
    elif nivel == "predio" or (nivel == "rua" and n >= p["media_rua_min"] and razao is not None and razao <= p["razao_max_media_rua"]):
        confianca = "media"
    else:
        confianca = "baixa"

    # as mais parecidas primeiro: mesmo prédio, diferença de área, diferença de andar, mais recente
    def ordem(i):
        v = vs[i]
        mesmo = 0 if v[0] == entrada.get("predio") else 1
        d_and = abs(v[4] - andar) if (andar is not None and v[4] is not None) else 99
        return (mesmo, abs(v[3] - area) / area, d_and, -v[1], i)
    similares = sorted(sel, key=ordem)[:p["max_similares"]]

    return {
        "ok": True, "nivel": nivel, "n": n, "tolerancia_area": tol, "area_ampliada": ampliada, "confianca": confianca,
        "razao_p75_p25": None if razao is None else _dec(razao, 3),
        "faixa_nome": "p25_p75" if n >= p["min_quartis"] else "min_max",
        "estimativa": estimativa, "vendas_minimo": minimo, "vendas_maximo": maximo,
        "m2": _arred(mid_m2), "fator_andar": _dec(f_user, 4),
        "similares": similares,
        "ultima_venda": max(vs[i][1] for i in sel),
    }


def estimar(dados, idx, entrada):
    """Estimativa + faixa provável + veredito. A faixa vem do ERRO MEDIDO (dados["precisao"], calculado a cada build
    tirando vendas reais do cálculo): em 3 de cada 4 testes do mesmo nível e confiança o preço pago ficou dentro dela.
    Ver calibrar_precisao()."""
    res = _estimar_base(dados, idx, entrada)
    if not res["ok"]:
        return res
    p = dados["parametros"]
    prec = dados.get("precisao") or {}
    t = prec.get(f"{res['nivel']}|{res['confianca']}")
    if not t or t["n"] < p["precisao_min_testes"]:
        t = prec.get(f"{res['nivel']}|*")
    m = t["p75"] if t else p["margem_fallback"]
    m = min(p["margem_max"], max(p["margem_min"], m))
    est = res["estimativa"]
    res["margem_pct"] = _dec(m * 100, 1)
    res["precisao_testes"] = t["n"] if t else 0
    res["precisao_mediana_pct"] = _dec(t["mediano"] * 100, 1) if t else None
    res["minimo"], res["maximo"] = _arred(est / (1 + m)), _arred(est / (1 - m))
    pedido = entrada.get("preco_pedido")
    if pedido:
        if pedido < res["minimo"]:
            veredito = "abaixo"
        elif pedido <= res["maximo"]:
            veredito = "dentro"
        else:
            veredito = "acima"
        res["veredito"] = veredito
        res["pedido_vs_estimativa_pct"] = _dec((pedido / est - 1) * 100, 1)
    return res


def calibrar_precisao(dados):
    """Mede o erro do cálculo de verdade: tira vendas reais (amostra fixa e espaçada) do cálculo, estima cada uma só
    com as outras e compara com o que foi pago (os dois já no preço do último mês completo). Três situações, uma por
    nível: prédio (a venda sai), rua (o prédio inteiro sai) e bairro (prédio e rua saem). Devolve
    {"nivel|confianca": {"n", "mediano", "p75"}} (erro absoluto em fração do preço pago) e "nivel|*" (todas as
    confianças do nível)."""
    idx = indexar(dados)
    vs, predios = dados["vendas"], dados["predios"]
    passo = max(1, len(vs) // CALC_PRECISAO_TESTES)
    amostra = range(0, len(vs), passo)
    erros = {}
    for modo in ("predio", "rua", "bairro"):
        for i in amostra:
            v = vs[i]
            pi = v[0]
            p = predios[pi]
            fora = {i} if modo == "predio" else set(idx["predio"][pi])
            sub = {"predio": {pi: [j for j in idx["predio"][pi] if j not in fora]},
                   "rua": {p[3]: [j for j in idx["rua"][p[3]] if j not in fora]},
                   "bairro": {p[2]: [j for j in idx["bairro"][p[2]] if j not in fora]}}
            if modo == "bairro":
                sub["rua"] = {p[3]: []}
            ent = {"predio": pi if modo == "predio" else None, "rua": p[3] if modo != "bairro" else None,
                   "bairro": p[2], "area": v[3], "andar": v[4]}
            r = _estimar_base(dados, sub, ent)
            if not r["ok"] or r["nivel"] != modo:
                continue
            real = v[2] * v[6]
            e = abs(r["estimativa"] - real) / real
            erros.setdefault(f"{modo}|{r['confianca']}", []).append(e)
            erros.setdefault(f"{modo}|*", []).append(e)
    return {k: {"n": len(e), "mediano": round(_mediana(e), 4), "p75": round(_percentil(75, e), 4)} for k, e in sorted(erros.items())}


def anuncios_parecidos(dados, entrada, estimativa):
    """Anúncios ativos (nonStop) parecidos: do mesmo prédio primeiro; depois do mesmo bairro com os mesmos
    quartos e, se a área útil foi informada, área útil ±25% (senão, valor dentro de ±30% da estimativa)."""
    p = dados["parametros"]
    quartos = entrada.get("quartos")
    area_util = entrada.get("area_util")
    out = []
    for i, a in enumerate(dados["anuncios"]):
        mesmo_predio = entrada.get("predio") is not None and a[0] == entrada["predio"]
        if not mesmo_predio:
            if a[1] != entrada["bairro"]:
                continue
            if quartos is not None and a[6] is not None and a[6] != quartos:
                continue
            if area_util:
                if not a[5] or abs(a[5] - area_util) / area_util > p["tol_anuncio_area"]:
                    continue
            elif estimativa:
                if abs(a[4] - estimativa) / estimativa > p["tol_anuncio_valor"]:
                    continue
        out.append((0 if mesmo_predio else 1, abs(a[4] - estimativa) if estimativa else 0, a[8] or "", i))
    out.sort()
    return [t[3] for t in out[:p["max_anuncios"]]]
