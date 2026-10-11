#!/usr/bin/env python3
"""Testes da regra da calculadora de preço (sem rede, sem arquivo de dados): leitura de andar/vagas no complemento do
ITBI, escolha do nível (prédio -> rua -> bairro), faixa, confiança, veredito e os casos que NÃO podem responder.
Uso: python3 scripts/test_calculadora.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calculadora_preco as cp

falhas = []


def confere(nome, obtido, esperado):
    if obtido != esperado:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")


# --- número do apartamento e andar ---------------------------------------------------------------------------
confere("AP 152", cp.numero_do_apto("AP 152"), 152)
confere("APTO 61", cp.numero_do_apto("APTO 61"), 61)
confere("AP2201 E 2VGS", cp.numero_do_apto("AP2201 E 2VGS"), 2201)
confere("BL 3 AP 105 E VG", cp.numero_do_apto("BL 3 AP 105 E VG"), 105)
confere("AP 07", cp.numero_do_apto("AP 07"), 7)
confere("CASA B", cp.numero_do_apto("CASA B"), None)
confere("vazio", cp.numero_do_apto(""), None)
confere("None", cp.numero_do_apto(None), None)
confere("exemplo do Paulo: 152 = 15º", cp.andares_do_predio([152, 151, 153])[152], 15)
confere("62 = 6º", cp.andares_do_predio([62, 11, 12])[62], 6)
confere("1704 = 17º", cp.andares_do_predio([1704, 101, 801])[1704], 17)
confere("prédio com 4 dígitos: 801 = 8º (centenas)", cp.andares_do_predio([1704, 101, 801])[801], 8)
confere("prédio só com 101/102/201/202: centenas", cp.andares_do_predio([101, 102, 201, 202])[201], 2)
confere("1 dígito sem andar", 7 in cp.andares_do_predio([7, 8, 152]), False)
confere("andar absurdo descartado", 9999 in cp.andares_do_predio([9999, 152]), False)  # 99º
confere("convenção dezenas", cp.convencao_do_predio([152, 151, 153]), "d")
confere("convenção centenas (4 dígitos no prédio)", cp.convencao_do_predio([1704, 801]), "c")
confere("convenção centenas (101/102/201)", cp.convencao_do_predio([101, 102, 201, 202]), "c")
confere("andar e final: 152 (dezenas)", cp.andar_e_final(152, "d"), (15, 2))
confere("andar e final: 62 (dezenas)", cp.andar_e_final(62, "d"), (6, 2))
confere("andar e final: 1704", cp.andar_e_final(1704, "c"), (17, 4))
confere("andar e final: 801 (centenas)", cp.andar_e_final(801, "c"), (8, 1))
confere("andar e final: 7 não dá", cp.andar_e_final(7, "d"), (None, None))
confere("andar e final: andar 99 não dá", cp.andar_e_final(9999, "c"), (None, None))
confere("mesmo final = mesma posição: 152 e 252", cp.andar_e_final(152, "d")[1] == cp.andar_e_final(252, "d")[1], True)
# --- vagas ---------------------------------------------------------------------------------------------------
confere("E 2 VG", cp.vagas_do_complemento("AP 62 E 2 VG"), 2)
confere("2VGS", cp.vagas_do_complemento("AP2201 E 2VGS"), 2)
confere("E VG = 1", cp.vagas_do_complemento("AP 44 E VG"), 1)
confere("sem vaga escrita", cp.vagas_do_complemento("AP 152"), None)


# --- cálculo ---------------------------------------------------------------------------------------------------
Q_SINT = [0.55, 0.62, 0.72, 0.82, 0.86, 0.90, 0.93, 0.95, 0.98, 1.00, 1.03, 1.07, 1.10, 1.14, 1.20, 1.30, 1.45, 1.70, 2.00]  # p1..p99


def dados_sinteticos():
    # bairro 0; rua 0 com prédios 0 e 1; rua 1 com o prédio 2. venda = [predio, ym, valor, area, andar, vagas, fator]
    vendas = []
    for k in range(6):   # prédio 0: 6 vendas de ~100 m² a ~R$ 10.000/m² (valor/m² varia um pouco)
        vendas.append([0, 202501 + k, 1_000_000 + k * 20_000, 100.0, 3 + k, None, 1.0])
    for k in range(2):   # prédio 1: só 2 vendas parecidas (insuficiente sozinho)
        vendas.append([1, 202506 + k, 900_000, 100.0, 5, None, 1.0])
    for k in range(4):   # prédio 1: mais 4 de outra metragem
        vendas.append([1, 202506 + k, 500_000, 50.0, 2, None, 1.0])
    for k in range(10):  # rua 1 / prédio 2: 10 vendas de 100 m²
        vendas.append([2, 202501 + k, 800_000 + k * 10_000, 100.0, None, None, 1.0])
    return {
        "mes_base": "2026-06", "bairros": ["B"], "ruas": [["Rua A", 0], ["Rua B", 0]],
        "predios": [["RUA A|1", "Rua A, 1", 0, 0], ["RUA A|2", "Rua A, 2", 0, 0], ["RUA B|3", "Rua B, 3", 0, 1]],
        "precisao": {"predio|alta": {"n": 500, "mediano": 0.07, "p75": 0.15, "q": Q_SINT}, "predio|media": {"n": 500, "mediano": 0.12, "p75": 0.25, "q": Q_SINT},
                     "predio|*": {"n": 1000, "mediano": 0.1, "p75": 0.2, "q": Q_SINT},
                     "predio_poucas|media": {"n": 500, "mediano": 0.13, "p75": 0.24, "q": Q_SINT}, "predio_poucas|baixa": {"n": 500, "mediano": 0.15, "p75": 0.29, "q": Q_SINT},
                     "predio_poucas|*": {"n": 1000, "mediano": 0.14, "p75": 0.26, "q": Q_SINT}, "rua|*": {"n": 400, "mediano": 0.19, "p75": 0.32, "q": Q_SINT},
                     "rua|baixa": {"n": 30, "mediano": 0.9, "p75": 0.9}, "bairro|*": {"n": 900, "mediano": 0.2, "p75": 0.35, "q": Q_SINT}, "bairro|baixa": {"n": 900, "mediano": 0.2, "p75": 0.35, "q": Q_SINT}},
        "vendas": vendas, "anuncios": [], "efeito_andar": [{"de": a, "ate": b, "n": 0, "fator": 1.0} for a, b in cp.CALC_ANDAR_FAIXAS],
        "parametros": {
            "tol_area_predio": [0.10, 0.20], "min_predio": 3, "tol_area_rua": [0.15, 0.25], "min_rua": 5,
            "tol_area_bairro": [0.15, 0.30], "min_bairro": 10, "min_quartis": 5, "alta_min_vendas": 5, "razao_max_alta": 1.25,
            "media_rua_min": 8, "razao_max_media_rua": 1.35, "veredito_abaixo": 0.75, "veredito_verde": 0.30, "veredito_amarelo": 0.15, "precisao_min_testes": 100, "margem_fallback": 0.35, "margem_min": 0.03, "margem_max": 0.60, "max_similares": 8, "max_anuncios": 8,
            "tol_anuncio_area": 0.25, "tol_anuncio_valor": 0.30,
        },
    }


d = dados_sinteticos()
idx = cp.indexar(d)
r = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("prédio com 6 vendas: ok", r["ok"], True)
confere("nível prédio", r["nivel"], "predio")
confere("n = 6", r["n"], 6)
confere("faixa por quartis (5+)", r["faixa_nome"], "p25_p75")
confere("confiança alta", r["confianca"], "alta")
confere("mediana de R$/m² = 10.500", r["m2"], 10500)
confere("estimativa = m² x área", r["estimativa"], 1_050_000)
confere("faixa contém a estimativa", r["minimo"] <= r["estimativa"] <= r["maximo"], True)
confere("faixa provável = margem medida (alta: 15%)", (r["margem_pct"], r["minimo"], r["maximo"]), (15.0, 913043, 1235294))
confere("vendas parecidas: mínimo e máximo próprios", (r["vendas_minimo"] <= r["estimativa"] <= r["vendas_maximo"]), True)
confere("metragem 5% maior: área é só escala", cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 105.0, "andar": None})["estimativa"], 1_102_500)

# prédio 1: só 2 vendas parecidas de 100 m² -> não bastam pra "prédio" (mín. 3), mas ainda valem mais que a rua: "predio_poucas"
r = cp.estimar(d, idx, {"predio": 1, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("2 vendas no prédio: usa o prédio (poucas), confiança média", (r["ok"], r["nivel"], r["n"], r["confianca"]), (True, "predio_poucas", 2, "media"))
confere("poucas vendas: margem própria da tabela (24%)", r["margem_pct"], 24.0)
confere("poucas vendas: segunda opinião pela rua (8 vendas)", (r["segunda_opiniao"]["nivel"], r["segunda_opiniao"]["n"]), ("rua", 8))
confere("poucas vendas: mediana de 2 vendas de R$ 900.000 em 100 m² = R$ 900.000", r["estimativa"], 900_000)
# a rua (prédios 0 e 1) diria ~R$ 1.000.000; o prédio diz R$ 900.000 (-10%): dentro da margem de 24%, não diverge
confere("segunda opinião dentro da margem: não diverge", r["segunda_diverge"], False)
# prédio com 1 única venda parecida: confiança baixa
d6 = dados_sinteticos()
d6["vendas"] = [v for v in d6["vendas"] if not (v[0] == 1 and v[3] == 100.0)] + [[1, 202506, 900_000, 100.0, None, None, 1.0]]
r6 = cp.estimar(d6, cp.indexar(d6), {"predio": 1, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("1 venda no prédio: usa o prédio, confiança baixa", (r6["nivel"], r6["n"], r6["confianca"]), ("predio_poucas", 1, "baixa"))
confere("1 venda: margem própria (29%)", r6["margem_pct"], 29.0)
# segunda opinião divergente: a venda do prédio é muito diferente da rua -> avisa
d7 = dados_sinteticos()
d7["vendas"] = [v for v in d7["vendas"] if not (v[0] == 1 and v[3] == 100.0)] + [[1, 202506, 300_000, 100.0, None, None, 1.0]]
r7 = cp.estimar(d7, cp.indexar(d7), {"predio": 1, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("1 venda muito abaixo da rua: segunda opinião diverge", r7["segunda_diverge"], True)
# sem nenhuma venda parecida no prédio (só plantas bem diferentes): cai pra rua, como antes
r8 = cp.estimar(d, idx, {"predio": 1, "rua": 0, "bairro": 0, "area": 75.0, "andar": None})
confere("prédio sem nenhuma venda parecida: vai pra rua ou bairro", (r8["ok"], r8["nivel"] in ("rua", "bairro")), (True, True)) if r8["ok"] else None
# a segunda opinião só existe quando o prédio tem poucas vendas
r9 = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("prédio com vendas suficientes: sem segunda opinião", "segunda_opiniao" in r9, False)
# a calibração mede o nível novo separado do "prédio"
tabc = cp.calibrar_precisao(dados_sinteticos())
confere("calibrar_precisao nunca mistura 'predio' com 'predio_poucas'", all(k.split("|")[0] in ("predio", "predio_poucas", "rua", "bairro") for k in tabc), True)
r = cp.estimar(d, idx, {"predio": 1, "rua": 0, "bairro": 0, "area": 50.0, "andar": None})
confere("4 vendas parecidas: prédio, faixa mín-máx, confiança média", (r["nivel"], r["faixa_nome"], r["confianca"]), ("predio", "min_max", "media"))
# endereço sem vendas (só a rua): predio=None
r = cp.estimar(d, idx, {"predio": None, "rua": 1, "bairro": 0, "area": 100.0, "andar": None})
confere("só a rua, 10 vendas: nível rua", (r["nivel"], r["n"]), ("rua", 10))
# bairro: rua nula e bairro com 24 vendas de 100 m² (6+2+10, mais ...) -> mín. 10
r = cp.estimar(d, idx, {"predio": None, "rua": None, "bairro": 0, "area": 100.0, "andar": None})
confere("bairro: nível bairro", r["nivel"], "bairro")
confere("bairro: confiança baixa", r["confianca"], "baixa")
# NEGATIVOS: metragem sem nenhuma venda parecida não pode dar número
for area in (12.0, 400.0, 75.0):
    r = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": area, "andar": None})
    confere(f"metragem {area} sem vendas parecidas = sem resposta", (r["ok"], r.get("motivo")), (False, "poucas_vendas"))
# tolerância ampliada: 112 m² não tem vendas em ±10% de 100? 112 está a 12% -> 2ª tentativa (±20%) pega as 6 do prédio 0
r = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 112.0, "andar": None})
confere("tolerância ampliada sinalizada", (r["nivel"], r["area_ampliada"], r["tolerancia_area"]), ("predio", True, 0.20))

# veredito = quantas vendas parecidas chegaram àquele preço (quantis Q_SINT: preço pago ÷ estimativa)
est = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None, "preco_pedido": 1_050_000})
confere("escada: 90/75/50/25/10 em cada 100", [x[0] for x in est["escada"]], [90, 75, 50, 25, 10])
confere("escada: preço da mediana = estimativa", est["escada"][2][1], 1_050_000)
confere("teto verde = quantil 70 (1,07 x estimativa)", est["teto_verde"], 1_123_500)
confere("teto amarelo = quantil 85 (1,20 x estimativa)", est["teto_amarelo"], 1_260_000)
confere("piso do mercado = quantil 10 (0,82 x estimativa)", est["piso_mercado"], 861_000)
confere("ordem estimativa <= verde <= amarelo", est["estimativa"] <= est["teto_verde"] <= est["teto_amarelo"], True)
E = 1_050_000
casos = ((0.60, "abaixo"), (1.00, "dentro"), (1.069, "dentro"), (1.08, "alto"), (1.19, "alto"), (1.21, "fora"), (1.60, "fora"), (3.00, "fora"))
for f, esperado in casos:
    r = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None, "preco_pedido": E * f})
    confere(f"veredito pedido = {f} x estimativa", r["veredito"], esperado)
# limites EXATOS: "até R$ X" inclui o próprio X (o botão "Preço de mercado" da tela usa exatamente o teto verde)
tv, ta = est["teto_verde"], est["teto_amarelo"]
for pedido, esperado in ((tv, "dentro"), (tv + 1, "alto"), (ta, "alto"), (ta + 1, "fora"), (est["estimativa"], "dentro")):
    rr = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None, "preco_pedido": pedido})
    confere(f"pedido exatamente em R$ {pedido}", rr["veredito"], esperado)
r = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None, "preco_pedido": 2_000_000})
confere("pedido absurdo (R$ 2 mi) é VERMELHO (fora do mercado)", r["veredito"], "fora")
confere("pedido absurdo: 1 em cada 100 ou menos chegou", (r["pedido_alem_dos_testes"], r["pedido_chegaram_pct"]), (False, 1))
r3 = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None, "preco_pedido": 3_500_000})
confere("pedido além do maior preço dos testes", (r3["veredito"], r3["pedido_alem_dos_testes"]), ("fora", True))
confere("pedido absurdo: nenhuma das vendas parecidas chegou", r["pedido_n_chegaram"], 0)
confere("pedido absurdo: quanto baixar pra entrar no verde", r["pedido_acima_do_verde"], 2_000_000 - r["teto_verde"])
r = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None, "preco_pedido": E * 1.00})
confere("pedido na mediana: metade das vendas chegou (50%)", r["pedido_chegaram_pct"], 50)
r = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("sem pedido: sem veredito, mas com a escada", ("veredito" not in r, "escada" in r), (True, True))
d_sem_q = dados_sinteticos()
for v in d_sem_q["precisao"].values():
    v.pop("q", None)
r = cp.estimar(d_sem_q, cp.indexar(d_sem_q), {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None, "preco_pedido": 5_000_000})
confere("tabela sem quantis: não inventa veredito", ("veredito" not in r, "teto_verde" not in r), (True, True))

# vendas parecidas: cada uma "equivale" à metragem informada (valor atualizado ÷ área × área informada); atípicas são marcadas
r = cp.estimar(d, idx, {"predio": 0, "rua": 0, "bairro": 0, "area": 105.0, "andar": None, "preco_pedido": 1_500_000})
confere("equivalente na metragem 105 (venda de 100 m² a R$ 1.000.000)", sorted(r["similares_eq"])[0], 1_050_000)
confere("uma entrada de equivalente por venda mostrada", len(r["similares_eq"]) == len(r["similares"]) == len(r["similares_flag"]), True)
confere("sem atípicas quando os preços são parecidos", set(r["similares_flag"]), {0})
confere("maior venda é o equivalente, não o total", r["maior_venda"], 1_155_000)  # 1.100.000 x 1,05
d4 = dados_sinteticos()
d4["vendas"].append([0, 202506, 450_000, 100.0, None, None, 1.0])   # venda bem abaixo das demais do mesmo prédio e metragem
d4["vendas"].append([0, 202507, 2_300_000, 100.0, None, None, 1.0]) # e uma bem acima
r4 = cp.estimar(d4, cp.indexar(d4), {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
flags = {d4["vendas"][i][2]: f for i, f in zip(r4["similares"], r4["similares_flag"])}
confere("venda de R$ 450 mil entre plantas iguais: abaixo do padrão", flags[450_000], -1)
confere("venda de R$ 2,3 mi: acima do padrão", flags[2_300_000], 1)
confere("venda normal não é marcada", flags[1_000_000], 0)
# metragens diferentes: o equivalente leva cada venda para a metragem informada (R$/m² x m²)
d5 = dados_sinteticos()
r5 = cp.estimar(d5, cp.indexar(d5), {"predio": 1, "rua": 0, "bairro": 0, "area": 50.0, "andar": None})
confere("vendas de 50 m² (R$ 500.000) equivalem a R$ 500.000 em 50 m²", set(r5["similares_eq"]), {500_000})

# margem: combinação com poucos testes (rua|baixa n=30) usa o nível inteiro (rua|*, 32%), nunca um número de amostra pequena
d3 = dados_sinteticos()
d3["precisao"]["rua|media"] = {"n": 30, "mediano": 0.9, "p75": 0.9}  # só 30 testes: não vale
r = cp.estimar(d3, cp.indexar(d3), {"predio": None, "rua": 1, "bairro": 0, "area": 100.0, "andar": None})
confere("poucos testes na combinação: usa o nível inteiro", (r["confianca"], r["margem_pct"], r["precisao_testes"]), ("media", 32.0, 400))
# sem tabela de precisão: margem de reserva (35%), nunca zero
d3["precisao"] = {}
r = cp.estimar(d3, cp.indexar(d3), {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("sem tabela de precisão: margem de reserva", r["margem_pct"], 35.0)
# margem nunca abaixo do piso (3%) nem acima do teto (60%)
d3["precisao"] = {"predio|*": {"n": 999, "mediano": 0.0, "p75": 0.0}, "predio|alta": {"n": 999, "mediano": 0.0, "p75": 0.0}}
r = cp.estimar(d3, cp.indexar(d3), {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("margem piso", r["margem_pct"], 3.0)
d3["precisao"] = {"predio|*": {"n": 999, "mediano": 0.9, "p75": 0.95}, "predio|alta": {"n": 999, "mediano": 0.9, "p75": 0.95}}
r = cp.estimar(d3, cp.indexar(d3), {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("margem teto", r["margem_pct"], 60.0)
# calibrar_precisao: prédio de preço idêntico por m² => erro ~0; e a tabela tem n e p75
tab = cp.calibrar_precisao(dados_sinteticos())
confere("calibrar_precisao devolve o nível inteiro", "predio|*" in tab and tab["predio|*"]["n"] > 0, True)
confere("erro de teste nunca negativo", all(v["mediano"] >= 0 and v["p75"] >= 0 for v in tab.values()), True)

# efeito do andar: faixa 16+ vale 5% mais -> andar 20 informado sobe a estimativa ~5% (as vendas sem andar não são ajustadas)
d2 = dados_sinteticos()
d2["efeito_andar"][4]["fator"] = 1.05
idx2 = cp.indexar(d2)
r0 = cp.estimar(d2, idx2, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
r1 = cp.estimar(d2, idx2, {"predio": 0, "rua": 0, "bairro": 0, "area": 100.0, "andar": 20})
confere("andar alto sobe 5%", round(r1["estimativa"] / r0["estimativa"], 3), 1.05)
# a ordem das vendas parecidas: mais parecida primeiro; mesmo prédio antes de outro prédio
r = cp.estimar(d, idx, {"predio": 1, "rua": 0, "bairro": 0, "area": 100.0, "andar": None})
confere("mesmo prédio primeiro entre as parecidas", {d["vendas"][i][0] for i in r["similares"][:2]}, {1})

if falhas:
    print("FALHOU:")
    for f in falhas:
        print("  -", f)
    sys.exit(1)
print("OK — regra da calculadora: andar/vagas, 3 níveis, faixa, confiança, veredito e casos sem resposta.")
