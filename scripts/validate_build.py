#!/usr/bin/env python3
"""
Portão de segurança antes de publicar site/data.json — pedido do usuário em
2026-09-30 (o dashboard vai integrar no CRM e ser compartilhado com outros
corretores; "não pode quebrar em nenhum momento"). build_data.py chama
validate_before_publish() logo antes de sobrescrever site/data.json; se
qualquer checagem falhar, levanta SystemExit (sai com código != 0) e o
workflow do GitHub Actions para ANTES do passo de commit — a versão
publicada anterior nunca é sobrescrita por um build ruim.

Três checagens, na ordem em que o usuário pediu:
  1. linhas lidas == linhas da planilha (reconciliação exata, sheet a sheet)
  2. nenhum bairro com variação de volume_primary_year > 30% vs a versão
     publicada atual, a menos que ALLOW_LARGE_CHANGES=1 esteja no ambiente
     (mudança de metodologia deliberada — cada item desta auditoria passa
     por aprovação explícita do usuário antes, então quem liga essa var é
     sempre uma decisão humana, nunca o cron)
  3. formato de site/data.json tem todas as chaves/campos que os painéis
     do site/app.js esperam (checagem estrutural — não substitui abrir a
     dashboard num navegador de verdade, que é feito manualmente a cada
     item desta auditoria; é a rede de segurança pro build automático
     diário, que não tem navegador disponível).
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from normalize import TARGETS
from xlsx_reader import Workbook

ROOT = Path(__file__).resolve().parent.parent

SHEET_RE = re.compile(r"^(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)-(\d{4})$")
VARIACAO_MAX = 0.30

# Item 1 do pedido de 2026-09-30: alarme se uma aba vier sem cabeçalho
# reconhecível, ou com as colunas que o pipeline efetivamente lê (por
# posição/letra — ver xlsx_reader.py) deslocadas ou renomeadas. Só cobre as
# 10 colunas que parse_itbi.py de fato consome — não trava por causa da
# bagunça de nome em Z/AA/AB (item 1b do diagnóstico: não usadas hoje).
# Texto exato confirmado em produção (ver diagnóstico de 2026-09-29/30).
EXPECTED_HEADERS = {
    "A": "N° do Cadastro (SQL)",
    "B": "Nome do Logradouro",
    "C": "Número",
    "E": "Bairro",
    "H": "Natureza de Transação",
    "I": "Valor de Transação (declarado pelo contribuinte)",
    "J": "Data de Transação",
    "L": "Proporção Transmitida (%)",
    "N": "Base de Cálculo adotada",
    "W": "Área Construída (m2)",
    "X": "Uso (IPTU)",
}
EXPECTED_COLUMN_COUNT = 28  # A..AB — ver diagnóstico: header sempre tem exatamente 28 colunas preenchidas


def _col_letter(n):
    """1 -> 'A', 26 -> 'Z', 27 -> 'AA', 28 -> 'AB'."""
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


EXPECTED_COLUMNS = [_col_letter(i) for i in range(1, EXPECTED_COLUMN_COUNT + 1)]

REQUIRED_TOP_KEYS = {
    "generated_at", "bairros", "ranking", "valor_oportunidade",
    "imoveis_prioritarios", "captacao_estrategica", "preco_m2_painel", "meta",
    "periodo_12m",
}
REQUIRED_BAIRRO_KEYS = {
    "score", "volume_primary_year", "trend_pct", "stock_demand_ratio",
    "price_gap_pct", "flag_alerta", "preco_m2_segmentos",
    "volume_12m", "trend_pct_12m", "volume_recente_parcial",
    "volume_mercado_12m", "trend_pct_mercado_12m", "volume_retomadas_12m",
}


class ValidationError(SystemExit):
    def __init__(self, msg):
        super().__init__(f"[validate_build] FALHOU — publicação bloqueada: {msg}")


def _independent_row_count(year_to_path):
    """Reconta linhas de cada aba MMM-AAAA direto do .xlsx, sem depender do
    contador interno de parse_itbi.py — pra pegar um bug que estivesse nos
    DOIS lugares (ex: parse_itbi contando errado E confiando na própria
    contagem) e não só numa divergência entre eles."""
    total_rows = 0
    header_rows = 0
    sheets_checked = 0
    for year, path in year_to_path.items():
        if not path.exists():
            continue
        with Workbook(path) as wb:
            for s in wb.sheets:
                if not SHEET_RE.match(s["name"]):
                    continue
                sheets_checked += 1
                for _rn, cells in wb.rows(s["target"]):
                    total_rows += 1
                    if cells.get("E") == "Bairro":
                        header_rows += 1
    return total_rows, header_rows, sheets_checked


def check_header_layout(year_to_path):
    """Escaneia cada aba MMM-AAAA inteira procurando a linha de cabeçalho
    (onde a coluna E diz "Bairro" — pode estar em qualquer linha, não só na
    1ª: ver diagnóstico, JAN-2024/OUT-2024 têm o cabeçalho no meio/fim da
    aba). Levanta erro se: (a) nenhuma linha de cabeçalho for encontrada,
    (b) alguma das 10 colunas que o pipeline lê tiver texto diferente do
    esperado nessa linha, ou (c) menos de 28 colunas estiverem preenchidas
    nela — sinal de coluna sumida/deslocada, o risco real de ler por
    posição fixa."""
    problemas = []
    for year, path in sorted(year_to_path.items()):
        if not path.exists():
            continue
        with Workbook(path) as wb:
            for s in wb.sheets:
                if not SHEET_RE.match(s["name"]):
                    continue
                header_row = None
                for _rn, cells in wb.rows(s["target"]):
                    if cells.get("E") == "Bairro":
                        header_row = cells
                        break
                if header_row is None:
                    problemas.append(f"{s['name']}: nenhuma linha de cabeçalho reconhecível (coluna E == 'Bairro') em toda a aba")
                    continue

                preenchidas = [c for c in EXPECTED_COLUMNS if header_row.get(c)]
                if len(preenchidas) < EXPECTED_COLUMN_COUNT:
                    faltando = [c for c in EXPECTED_COLUMNS if not header_row.get(c)]
                    problemas.append(f"{s['name']}: só {len(preenchidas)}/{EXPECTED_COLUMN_COUNT} colunas A-AB preenchidas no cabeçalho (faltando: {faltando})")

                for col, expected_text in EXPECTED_HEADERS.items():
                    actual = header_row.get(col)
                    if actual != expected_text:
                        problemas.append(f"{s['name']}: coluna {col} esperava '{expected_text}', veio '{actual}'")

    if problemas:
        raise ValidationError("layout de coluna inesperado em " + str(len(problemas)) + " caso(s):\n  - " + "\n  - ".join(problemas))
    print("[validate_build] OK 0/3 — layout de coluna (cabeçalho + 28 colunas A-AB) confere em todas as abas.")


def check_linhas_lidas(year_to_path, itbi_stats):
    total_rows, header_rows, sheets_checked = _independent_row_count(year_to_path)
    esperado = total_rows - header_rows
    lido = itbi_stats["total_rows_seen"]
    if lido != esperado:
        raise ValidationError(
            f"reconciliação de linhas falhou — planilhas têm {total_rows} linhas em "
            f"{sheets_checked} abas, {header_rows} são cabeçalho (esperado {esperado} "
            f"linhas de dado), mas o parser leu {lido}. Diferença: {lido - esperado:+d}."
        )
    print(f"[validate_build] OK 1/16 — linhas lidas batem: {lido} == {total_rows} totais - {header_rows} cabeçalho, em {sheets_checked} abas.")


def check_variacao_bairros(new_bairros, old_data_path):
    if not old_data_path.exists():
        print("[validate_build] OK 2/16 — sem versão publicada anterior pra comparar (primeira execução).")
        return
    try:
        old_data = json.loads(old_data_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[validate_build] AVISO — não consegui ler a versão anterior pra comparar ({e!r}); pulando checagem 2/3.")
        return
    old_bairros = old_data.get("bairros", {})

    grandes_mudancas = []
    for b in TARGETS:
        old_v = (old_bairros.get(b) or {}).get("volume_primary_year")
        new_v = (new_bairros.get(b) or {}).get("volume_primary_year")
        if old_v is None or new_v is None or old_v == 0:
            continue
        variacao = (new_v - old_v) / old_v
        if abs(variacao) > VARIACAO_MAX:
            grandes_mudancas.append((b, old_v, new_v, variacao))

    if grandes_mudancas:
        grandes_mudancas.sort(key=lambda x: -abs(x[3]))
        linhas = "\n".join(
            f"  - {b}: {old_v} -> {new_v} ({variacao*100:+.1f}%)" for b, old_v, new_v, variacao in grandes_mudancas
        )
        if os.environ.get("ALLOW_LARGE_CHANGES", "").strip() == "1":
            print(
                f"[validate_build] AVISO 2/3 — {len(grandes_mudancas)} bairro(s) com variação de "
                f"volume_primary_year acima de {VARIACAO_MAX*100:.0f}%, mas ALLOW_LARGE_CHANGES=1 "
                f"está setado (mudança de metodologia deliberada) — publicando mesmo assim:\n{linhas}"
            )
            return
        raise ValidationError(
            f"{len(grandes_mudancas)} bairro(s) com variação de volume_primary_year acima de "
            f"{VARIACAO_MAX*100:.0f}% vs a versão publicada atual, sem ALLOW_LARGE_CHANGES=1:\n{linhas}\n"
            f"Se a mudança é esperada (correção deliberada de metodologia), rode de novo com "
            f"ALLOW_LARGE_CHANGES=1 no ambiente."
        )
    print(f"[validate_build] OK 2/16 — nenhum bairro variou mais que {VARIACAO_MAX*100:.0f}% em volume_primary_year.")


def check_formato_paineis(data):
    faltando_topo = REQUIRED_TOP_KEYS - data.keys()
    if faltando_topo:
        raise ValidationError(f"chaves obrigatórias faltando no topo de data.json: {sorted(faltando_topo)}")

    bairros = data["bairros"]
    faltando_bairros = set(TARGETS) - bairros.keys()
    if faltando_bairros:
        raise ValidationError(f"bairro(s) da carteira ausentes em data.json: {sorted(faltando_bairros)}")

    for b, entry in bairros.items():
        faltando = REQUIRED_BAIRRO_KEYS - entry.keys()
        if faltando:
            raise ValidationError(f"bairro '{b}' sem os campos {sorted(faltando)} — um painel que lê esse campo quebraria.")

    if not isinstance(data.get("ranking"), list) or len(data["ranking"]) != len(TARGETS):
        raise ValidationError(f"'ranking' deveria ter {len(TARGETS)} bairros, tem {len(data.get('ranking'))}.")

    print(f"[validate_build] OK 3/16 — formato de data.json íntegro: {len(bairros)} bairros, todas as chaves esperadas presentes.")


def check_consistencia_carteira_77(data):
    """Etapa 2, item 1.1 (2026-10-01), pedido do usuário: carteira_77 é a
    REFERÊNCIA validada — todo painel que mostra volume/revenda/planta/
    unidades/giro por bairro tem que bater EXATO com carteira_77 (achado
    que motivou isso: o export de 01/10 mostrava Tatuapé com 1.317 vendas
    no Ranking e 2.831 revendas no Carteira 77 — dois sistemas de bairro
    diferentes, a regra antiga de detecção de lançamento por endereço
    contra a cascata de 5 métodos). Sem tolerância, sem ALLOW_LARGE_
    CHANGES — uma divergência aqui é sempre um bug de verdade (os dois
    lados usam a mesma tabela/cascata/janela, só não compartilham o
    objeto Python — ver cascata_completa.resolver_registros_engine), não
    uma mudança de metodologia deliberada."""
    c77 = data.get("carteira_77")
    if not c77:
        raise ValidationError("data.json sem carteira_77 — impossível checar consistência (item 1.1 da Etapa 2).")
    bairros = data["bairros"]
    c77_bairros = c77["bairros"]
    campos = ("revenda_12m", "planta_12m", "unidades_iptu", "giro_12m_pct")
    divergencias = []
    for b in TARGETS:
        if b not in c77_bairros:
            divergencias.append(f"{b}: ausente em carteira_77")
            continue
        for campo in campos:
            v_motor = bairros[b].get(campo)
            v_c77 = c77_bairros[b].get(campo)
            if v_motor != v_c77:
                divergencias.append(f"{b}.{campo}: motor={v_motor!r} != carteira_77={v_c77!r}")
    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:30])
        a_mais = f"\n  ... e mais {len(divergencias) - 30}" if len(divergencias) > 30 else ""
        raise ValidationError(
            f"consistência carteira_77 FALHOU — {len(divergencias)} divergência(s) entre bairros_out e "
            f"carteira_77 (deveriam ser idênticos):\n{linhas}{a_mais}"
        )
    print(f"[validate_build] OK 4/16 — {len(TARGETS)} bairros batem exato com carteira_77 em {len(campos)} campos.")


def check_prontidao_consistencia(data):
    """Migração do Prontidão para Campanha (revisão 2026-10-01), item 3
    pedido pelo usuário: "incluir o painel no teste de consistência:
    revenda, tendência e giro de cada bairro devem bater exato com
    carteira_77 e com o Ranking". revenda_12m/giro_12m_pct já são
    conferidos contra carteira_77 em check_consistencia_carteira_77
    (campos compartilhados — Prontidão lê o MESMO bairros_out[b], não
    recalcula nada por conta própria, então não tem como divergir só
    pra ele). trend_pct_revenda_12m não existe em carteira_77 (é um
    conceito só do motor/Ranking) — pela mesma razão (campo único,
    compartilhado), Prontidão e Ranking nunca podem divergir nele.

    O que esta checagem confere especificamente (não coberto em outro
    lugar): prontidao_campanha existe pros 77 bairros, prontidao_ranking
    tem os 77 bairros, e — gate de merge pedido pelo usuário — NENHUM
    bairro com amostra_pequena_ranking=True (< 100 revendas em 12m)
    ocupa uma das 10 primeiras posições do ranking de prontidão."""
    bairros = data["bairros"]
    faltando = [b for b in TARGETS if "prontidao_campanha" not in bairros.get(b, {})]
    if faltando:
        raise ValidationError(f"prontidao_campanha ausente em {len(faltando)} bairro(s): {faltando[:10]}")

    ranking = data.get("prontidao_ranking")
    if not isinstance(ranking, list) or len(ranking) != len(TARGETS):
        raise ValidationError(f"'prontidao_ranking' deveria ter {len(TARGETS)} bairros, tem {len(ranking) if ranking else 0}.")

    top10_amostra_pequena = [b for b in ranking[:10] if bairros.get(b, {}).get("amostra_pequena_ranking")]
    if top10_amostra_pequena:
        raise ValidationError(
            f"bairro(s) com amostra pequena (< 100 revendas em 12m) no top 10 do Prontidão: {top10_amostra_pequena} "
            "— não deveriam ocupar posição de topo (gate de merge pedido pelo usuário)."
        )
    print(f"[validate_build] OK 5/16 — Prontidão: {len(TARGETS)} bairros com nota, top 10 sem amostra pequena.")


def check_perfil_v1_obsoleto(data):
    """Passo 2/2b/3c: "nenhum painel pode ler a faixa antiga (v1)". Desde
    o passo 3c (2026-10-05), "Perfil por Bairro" — o último consumidor —
    também migrou pra faixa de preço v2, então a regra agora vale pro
    site INTEIRO: nenhum painel (site/app.js) lê mais area_band/price_band/
    profile_quartos/profile_vagas/profile_reliability/profile_neighbors/
    profile_sample_size/profile_pool_sample_size/area_band_reliability/
    area_band_neighbors/stock_matching_profile. Esses campos continuam
    existindo em data.json (obsoletos, não removidos — remoção só com
    aprovação do usuário), só não são lidos por nada. Checagens:

      1. data.json: `captacao_estrategica[*].perfil` não pode ter chaves v1.
      2. site/app.js: nenhuma linha fora de comentário pode ler os campos
         v1 acima (regex com limite de palavra — `profile_sample_size_
         faixa_preco_v2` NÃO conta, só o nome exato).
      3. data.json: `imoveis_prioritarios[*]` não pode ter as chaves v1
         "area_band_reliability"/"profile_reliability"."""
    divergencias = []

    for g in data.get("captacao_estrategica", []):
        chaves_v1_presentes = {"area_band", "price_band", "profile_quartos", "profile_vagas", "profile_reliability"} & g.get("perfil", {}).keys()
        if chaves_v1_presentes:
            divergencias.append(f"captacao_estrategica[{g.get('bairro')}].perfil ainda tem chave(s) v1: {sorted(chaves_v1_presentes)}")

    campos_v1 = [
        "area_band", "price_band", "price_band_median", "profile_quartos", "profile_vagas",
        "profile_sample_size", "profile_pool_sample_size", "profile_reliability", "profile_neighbors",
        "area_band_reliability", "area_band_neighbors", "stock_matching_profile",
    ]
    regex_v1 = re.compile(r"\b(" + "|".join(campos_v1) + r")\b")
    app_js = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    achados_js = []
    for i, linha in enumerate(app_js.splitlines()):
        if linha.strip().startswith("//"):
            continue
        m = regex_v1.search(linha)
        if m:
            achados_js.append((i + 1, m.group(1), linha.strip()))
    if achados_js:
        divergencias.append(
            "site/app.js ainda lê campo(s) v1 fora de comentário: "
            + "; ".join(f"linha {n} ({campo}): {l[:80]}" for n, campo, l in achados_js[:10])
        )

    chaves_v1_painel8 = {"area_band_reliability", "profile_reliability"}
    for im in data.get("imoveis_prioritarios", []):
        presentes = chaves_v1_painel8 & im.keys()
        if presentes:
            divergencias.append(f"imoveis_prioritarios[{im.get('endereco')}] ainda tem chave(s) v1: {sorted(presentes)}")
            break  # 1 exemplo basta — evita centenas de linhas repetidas no erro

    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:30])
        raise ValidationError(f"perfil vencedor v1 ainda em uso onde deveria ser v2:\n{linhas}")
    print("[validate_build] OK 6/16 — nenhum painel (site/app.js) lê mais os campos do perfil v1 (metragem); todos usam a faixa de preço v2.")


def check_faixa_metragem_apartamento_suspensa(data):
    """Passo 2b (2026-10-01), item 2 pedido pelo usuário: a comparação
    por faixa_metragem() entre área CONSTRUÍDA (segmento ITBI) e área
    ÚTIL (anúncio) fica suspensa pra APARTAMENTO no componente de preço
    do Painel 8 e no Valor de Oportunidade (aguardando fator de
    calibração — ver backlog). Casa não muda. Trava o build se:

      1. algum imóvel apartamento em `imoveis_prioritarios` tiver
         price_alignment != None (teria que ter vindo de uma comparação
         por faixa de metragem revivida).
      2. existir algum achado de apartamento em
         `valor_oportunidade.imoveis` que NÃO seja comparado com a mediana do
         MESMO PRÉDIO (Rodada A, 2026-10-06: apartamento voltou ao painel, mas só
         por prédio — `comparacao == "predio"`, sem R$/m² nem faixa de metragem)."""
    divergencias = []

    aptos_com_price = [
        im for im in data.get("imoveis_prioritarios", [])
        if im.get("tipo_imovel") == "apartamento" and im.get("price_alignment") is not None
    ]
    if aptos_com_price:
        ex = aptos_com_price[0]
        divergencias.append(
            f"{len(aptos_com_price)} apartamento(s) em imoveis_prioritarios com price_alignment != None "
            f"(ex.: {ex.get('endereco')} = {ex.get('price_alignment')}) — faixa_metragem() parece ter voltado a comparar apartamento."
        )

    aptos_valor_oportunidade = [
        im for im in data.get("valor_oportunidade", {}).get("imoveis", [])
        if im.get("tipo_imovel") == "apartamento"
        and (im.get("comparacao") != "predio" or im.get("valor_m2") is not None or im.get("mediana_pago_m2") is not None)
    ]
    if aptos_valor_oportunidade:
        divergencias.append(
            f"{len(aptos_valor_oportunidade)} achado(s) de apartamento em valor_oportunidade.imoveis que não vêm da "
            "mediana do mesmo prédio (comparação por faixa de metragem segue suspensa pra apartamento)."
        )

    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias)
        raise ValidationError(f"faixa_metragem() voltou a comparar apartamento ITBI x anúncio:\n{linhas}")
    print("[validate_build] OK 7/16 — faixa_metragem() não compara apartamento ITBI x anúncio em nenhum painel.")


def check_selos_idade_bonus(data, usn_records):
    """Passo 3c (2026-10-05), decisões de mercado da auditoria. Trava o
    build se:

      1. SELOS: "Pouco estoque na rede" (campo selo_escassez_real) e
         "Estoque da rede fora do perfil" (que
         substituíram "Prioridade Máxima") divergirem da recomputação
         independente a partir de data.json — regra: só acendem com >= 100
         revendas em 12m (amostra_pequena_ranking False) E <= 2 anúncios na
         faixa de preço v2; "Escassez real" quando estoque total / revendas
         12m <= meta.limiar_escassez_real, "Estoque fora do perfil" no
         resto (e com estoque > 0). Nunca os dois juntos.
      2. IDADE: algum anúncio válido (valor > 0) do estoque ficou FORA de
         imoveis_prioritarios (anúncio antigo NUNCA é excluído — só ganha
         selo), ou `anuncio_antigo` divergir de idade_dias > 365.
      3. BÔNUS DE CAPTAÇÃO (híbrido, Passo 4): captacao_bonus precisa bater
         com a recomputação a partir dos campos do próprio imóvel —
         régua de giro (>= 10 unidades no IPTU e não-casa: < 7% = 40,
         7-10% = 60, 10-15% = 80, >= 15% = 100) ou régua de nº de vendas
         (2=40/3=60/4=80/5+=100) — com bônus acima de 60 só com >= 3
         vendas; captacao_regua coerente (giro só com unidades >= 10 e
         não-casa) e 0 se o endereço não está na Captação Ativa.
      4. (Passo 3d) IDADE = cadastro MAIS ANTIGO entre as duplicatas:
         nenhum anúncio do estoque pode ter created_at_mais_antigo MAIS
         NOVO que o próprio created_at, nem idade_dias menor que a do
         anúncio mantido (sinal de que a data original foi perdida)."""
    import engine

    divergencias = []
    limiar = data.get("meta", {}).get("limiar_escassez_real")
    if limiar is None:
        divergencias.append("data['meta']['limiar_escassez_real'] ausente.")
        limiar = 0
    bairros = data["bairros"]
    for b in TARGETS:
        v = bairros[b]
        demanda, estoque = v["revenda_12m"], v["stock_total"]
        razao = (estoque / demanda) if demanda > 0 else (999 if estoque > 0 else 0)
        elegivel = (
            (not v["amostra_pequena_ranking"]) and v["perfil_faixa_confiavel"]
            and v["estoque_perfil_faixa_preco"] <= engine.CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH
        )
        esp_escassez = elegivel and razao <= limiar
        esp_fora = elegivel and (not esp_escassez) and estoque > 0
        if v.get("selo_escassez_real") != esp_escassez:
            divergencias.append(f"{b}.selo_escassez_real={v.get('selo_escassez_real')!r}, esperado {esp_escassez!r}")
        if v.get("estoque_fora_do_perfil") != esp_fora:
            divergencias.append(f"{b}.estoque_fora_do_perfil={v.get('estoque_fora_do_perfil')!r}, esperado {esp_fora!r}")
        if v.get("selo_escassez_real") and v.get("estoque_fora_do_perfil"):
            divergencias.append(f"{b}: os dois selos acesos ao mesmo tempo (deveriam ser exclusivos)")
        if (v.get("selo_escassez_real") or v.get("estoque_fora_do_perfil")) and v["amostra_pequena_ranking"]:
            divergencias.append(f"{b}: selo aceso em bairro com amostra pequena (< 100 revendas)")

    for u in usn_records:
        mais_antigo, proprio = u.get("created_at_mais_antigo"), u.get("created_at")
        if mais_antigo and proprio and mais_antigo > proprio:
            divergencias.append(f"anúncio {u.get('codigo')}: created_at_mais_antigo ({mais_antigo}) é mais novo que created_at ({proprio}) — data original das duplicatas perdida.")
            break

    ip = data.get("imoveis_prioritarios", [])
    codigos_ip = {im["codigo"] for im in ip}
    validos = [u for u in usn_records if u.get("valor") and u["valor"] > 0 and u["bairro"] in bairros]
    sumidos = [u for u in validos if u["codigo"] not in codigos_ip]
    if sumidos:
        divergencias.append(f"{len(sumidos)} anúncio(s) válido(s) do estoque fora de imoveis_prioritarios (ex.: {sumidos[0]['codigo']}) — anúncio antigo nunca pode ser excluído.")
    for im in ip:
        esperado = im.get("idade_dias") is not None and im["idade_dias"] > engine.ANUNCIO_ANTIGO_DIAS
        if im.get("anuncio_antigo") != esperado:
            divergencias.append(f"imoveis_prioritarios[{im.get('codigo')}].anuncio_antigo={im.get('anuncio_antigo')!r}, esperado {esperado!r} (idade_dias={im.get('idade_dias')})")
            break
        n = im.get("captacao_n_vendas", 0)
        un = im.get("captacao_unidades")
        esperado_b, esperada_regua, _g = engine._bonus_captacao_hibrido(n, un, im.get("tipo_imovel"))
        if im.get("captacao_bonus") != esperado_b or im.get("captacao_regua") != esperada_regua:
            divergencias.append(f"imoveis_prioritarios[{im.get('codigo')}]: bônus {im.get('captacao_bonus')!r}/régua {im.get('captacao_regua')!r}, esperado {esperado_b!r}/{esperada_regua!r} ({n} venda(s), {un} unidade(s), tipo {im.get('tipo_imovel')})")
            break
        if im.get("captacao_bonus", 0) > engine.CAPTACAO_BONUS_SEM_MINIMO_MAX and n < engine.CAPTACAO_MIN_VENDAS_BONUS_ALTO:
            divergencias.append(f"imoveis_prioritarios[{im.get('codigo')}]: bônus {im.get('captacao_bonus')} com só {n} venda(s) (acima de 60 exige >= 3)")
            break

    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:30])
        raise ValidationError(f"selos/idade/bônus de captação inconsistentes:\n{linhas}")
    n_esc = sum(1 for b in TARGETS if bairros[b]["selo_escassez_real"])
    n_fora = sum(1 for b in TARGETS if bairros[b]["estoque_fora_do_perfil"])
    n_antigos = sum(1 for im in ip if im.get("anuncio_antigo"))
    print(f"[validate_build] OK 10/16 — selos ({n_esc} pouco estoque na rede, {n_fora} estoque da rede fora do perfil, exclusivos e só com 100+ revendas), {n_antigos} anúncios antigos mantidos nas contas (idade = cadastro mais antigo entre duplicatas), bônus de captação na escala.")


def check_captacao_limpa(data):
    """Captação limpa (2026-10-05): a Captação Ativa só pode exibir preço
    como MEDIANA (faixa P25-P75 apenas com 4+ revendas limpas; com menos,
    "poucas vendas") — nunca mais mínimo-máximo — e só conta endereços com
    2+ revendas limpas. Trava o build se:

      1. algum endereço de `captacao_ativa` ou `captacao_estrategica`
         tiver as chaves antigas preco_min/preco_max/preco_medio;
      2. n_vendas < 2 em captacao_ativa;
      3. a faixa não respeitar a regra: preco_p25/preco_p75 presentes só
         com n_vendas >= 4 (e poucas_vendas coerente), com
         p25 <= mediana <= p75;
      4. a mediana ficar fora do intervalo plausível de uma venda real
         (abaixo de R$ 10 mil ou acima de R$ 100 mi — limites da camada
         limpa)."""
    import engine
    import clean_itbi

    divergencias = []

    def conferir(e, onde, exigir_dois):
        proibidas = {"preco_min", "preco_max", "preco_medio"} & e.keys()
        if proibidas:
            divergencias.append(f"{onde}: chave(s) antiga(s) {sorted(proibidas)} (faixa mínimo-máximo não pode voltar)")
            return
        n = e["n_vendas"]
        if exigir_dois and n < 2:
            divergencias.append(f"{onde}: n_vendas={n} (< 2 revendas limpas não entra em captacao_ativa)")
        com_faixa = e.get("preco_p25") is not None or e.get("preco_p75") is not None
        if com_faixa and n < engine.CAPTACAO_MIN_VENDAS_FAIXA:
            divergencias.append(f"{onde}: faixa P25-P75 com só {n} venda(s) (exige {engine.CAPTACAO_MIN_VENDAS_FAIXA}+)")
        if (not com_faixa) != bool(e.get("poucas_vendas")):
            divergencias.append(f"{onde}: poucas_vendas={e.get('poucas_vendas')!r} incoerente com a faixa")
        if com_faixa and not (e["preco_p25"] <= e["preco_mediana"] <= e["preco_p75"]):
            divergencias.append(f"{onde}: mediana fora de P25-P75 ({e['preco_p25']}, {e['preco_mediana']}, {e['preco_p75']})")
        if not (clean_itbi.VALOR_MIN_REAL <= e["preco_mediana"] <= clean_itbi.VALOR_MAX_REAL):
            divergencias.append(f"{onde}: mediana {e['preco_mediana']} fora do intervalo real")

    for c in data.get("captacao_ativa", []):
        conferir(c, f"captacao_ativa[{c.get('endereco')}]", True)
        if len(divergencias) >= 20:
            break
    for g in data.get("captacao_estrategica", []):
        for e in g["enderecos"]:
            conferir(e, f"captacao_estrategica[{g['bairro']}][{e.get('endereco')}]", False)
            if len(divergencias) >= 20:
                break

    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:20])
        raise ValidationError(f"Captação Ativa fora da regra de revenda limpa/mediana:\n{linhas}")
    n_end = len(data.get("captacao_ativa", []))
    n_faixa = sum(1 for c in data["captacao_ativa"] if not c["poucas_vendas"])
    print(f"[validate_build] OK 11/16 — Captação Ativa: {n_end} endereços com 2+ revendas limpas, preço por mediana ({n_faixa} com faixa P25-P75, o resto 'poucas vendas'), sem mínimo-máximo.")


def check_camada_limpa_unica(data, itbi_records):
    """CAMADA LIMPA ÚNICA (2026-10-05): uma só regra de limpeza de preço do
    ITBI pro dashboard inteiro (clean_itbi.build_clean_layer: limites duros
    R$ 10 mil–R$ 100 mi + sem subdeclaração vs "Base de Cálculo adotada";
    sem corte P5-P95, sem IQR). Trava o build se qualquer cálculo de preço
    não bater com uma recomputação independente SÓ a partir dessa camada:

      1. integridade da camada: nenhum registro is_clean_sale viola a regra
         (natureza/100%/tipo/limites/subdeclaração) e nenhum que a cumpre
         ficou de fora (nenhum corte extra escondido);
      2. faixa do perfil vencedor v2 (P25-P75 por bairro+tipo, revenda 12m);
      3. painel "Preço por m²" (mediana de valor total pago, apartamento);
      4. Captação Ativa (n_vendas e mediana por endereço);
      5. estático: engine.py só chama trim_outliers_iqr em preço PEDIDO/
         anúncio (nonStop), nunca em preço pago do ITBI, e o exportador de
         valor pago usa a mesma regra (motivo_valor_sujo)."""
    import clean_itbi
    import engine
    from normalize import excel_serial_to_ym, median, percentile, today_excel_serial

    divergencias = []

    # 1. integridade da camada
    for r in itbi_records:
        rege = (
            r.get("tipo_imovel") is not None and r["is_compra_venda"] and r["is_full_transfer"]
            and clean_itbi.motivo_valor_sujo(r["valor"], r.get("base_calculo")) is None
        )
        if bool(r["is_clean_sale"]) != bool(rege):
            divergencias.append(f"camada: registro (SQL {r.get('sql')}, valor {r['valor']}) is_clean_sale={r['is_clean_sale']} mas a regra única diz {bool(rege)}")
            break

    # janelas (proteção de amostra, 2026-10-06): 12/24/36 meses
    pi, pf = data["periodo_12m"]["inicio"], data["periodo_12m"]["fim"]
    y, m = map(int, pi.split("-"))
    periodo = []
    while True:
        periodo.append((y, m))
        if f"{y:04d}-{m:02d}" == pf:
            break
        m += 1
        if m > 12:
            y, m = y + 1, 1
    janelas = engine.janelas_meses(periodo, (min(data["meta"]["years"]), 1))
    conj = {w: set(l) for w, l in janelas.items()}

    # a regra de escolha da janela, testada à parte (casos de borda)
    esc = engine.escolher_janela
    casos = [
        ({12: 30, 24: 50, 36: 60}, (12, False)), ({12: 29, 24: 30, 36: 40}, (24, False)),
        ({12: 5, 24: 29, 36: 30}, (36, False)), ({12: 5, 24: 29, 36: 29}, (36, True)),
    ]
    for entrada, saida in casos:
        if esc(entrada) != saida:
            divergencias.append(f"escolher_janela({entrada}) = {esc(entrada)}, esperado {saida}")

    def mesmo(a, b):
        return a is None and b is None or (a is not None and b is not None and abs(a - b) <= 0.011)

    # 2. faixa v2 (janela adaptativa por bairro+tipo)
    por_bt = {}
    for r in itbi_records:
        if not engine._is_revenda_limpa(r) or r["day"] is None or r.get("tipo_imovel") not in engine.PERFIL_PRECO_V2_TIPOS:
            continue
        ym = excel_serial_to_ym(r["day"])
        for w in janelas:
            if ym in conj[w]:
                por_bt.setdefault((r["bairro"], r["tipo_imovel"]), {w2: [] for w2 in janelas})[w].append(r["valor"])
    for b in TARGETS:
        for tipo in engine.PERFIL_PRECO_V2_TIPOS:
            pj = por_bt.get((b, tipo), {w: [] for w in janelas})
            w, poucas = esc({k: len(v) for k, v in pj.items()})
            vals = pj[w]
            esperado = [round(percentile(25, vals), 2), round(percentile(75, vals), 2)] if vals else None
            achado = data["bairros"][b]["perfil_vencedor_faixa_preco_v2"].get(tipo)
            ok = (esperado is None and achado is None) or (esperado and achado and mesmo(esperado[0], achado[0]) and mesmo(esperado[1], achado[1]))
            meta = data["bairros"][b]["perfil_vencedor_faixa_preco_v2_meta"][tipo]
            if not ok or meta["janela_meses"] != w or meta["poucas_vendas"] != poucas or meta["n_vendas_limpas"] != len(vals):
                divergencias.append(f"faixa v2 {b}/{tipo}: data.json={achado} {meta} != recomputado da camada limpa={esperado} (janela {w}, poucas={poucas}, n={len(vals)})")

    # 3. Preço por m² (valor total, apartamento) — janela adaptativa por bairro+faixa
    hoje = today_excel_serial()
    vt = {}
    for r in itbi_records:
        if r["bairro"] not in TARGETS or r.get("tipo_imovel") != "apartamento" or r["day"] is None:
            continue
        f = clean_itbi.faixa_metragem(r["area"])
        if f is None or not engine._is_revenda_limpa(r):
            continue
        ym = excel_serial_to_ym(r["day"])
        for w in janelas:
            if ym in conj[w]:
                vt.setdefault((r["bairro"], f), {w2: [] for w2 in janelas})[w].append(r["valor"])
    for linha in data["preco_m2_painel"]:
        pj = vt.get((linha["bairro"], linha["faixa"]), {w: [] for w in janelas})
        w, poucas = esc({k: len(v) for k, v in pj.items()})
        vals = pj[w]
        esperado = round(median(vals), 2) if vals else None
        if not mesmo(esperado, linha["valor_total_mediana"]) or linha["janela_meses"] != w or linha["poucas_vendas"] != poucas:
            divergencias.append(f"Preço por m² {linha['bairro']}/{linha['faixa']}: mediana {linha['valor_total_mediana']}/janela {linha['janela_meses']}/poucas {linha['poucas_vendas']} != recomputada {esperado}/{w}/{poucas}")
            if len(divergencias) > 12:
                break

    # 4. Captação Ativa
    por_end = {}
    for r in itbi_records:
        if r.get("addr_key") and engine._is_revenda_limpa(r):
            por_end.setdefault(r["addr_key"], []).append(r["valor"])
    for c in data["captacao_ativa"]:
        vals = por_end.get(c["addr_key"], [])
        if len(vals) != c["n_vendas"] or not mesmo(round(median(vals), 2), c["preco_mediana"]):
            divergencias.append(f"Captação {c['endereco']}: n={c['n_vendas']}/mediana={c['preco_mediana']} != recomputado n={len(vals)}/mediana={round(median(vals), 2) if vals else None}")
            if len(divergencias) > 16:
                break

    # 5. estático
    fonte_engine = (ROOT / "scripts" / "engine.py").read_text(encoding="utf-8").splitlines()
    permitidas = ("pedido.get(key", 'for r in by_bairro[b] if r["valor"]')
    for i, linha in enumerate(fonte_engine):
        if "trim_outliers_iqr(" in linha and not linha.strip().startswith(("#", "def ")) and not any(p in linha for p in permitidas):
            divergencias.append(f"scripts/engine.py linha {i + 1}: trim_outliers_iqr em cálculo que não é preço pedido/anúncio: {linha.strip()[:90]}")
    fonte_export = (ROOT / "scripts" / "exportar_valor_pago_por_bairro.py").read_text(encoding="utf-8")
    if "motivo_valor_sujo" not in fonte_export or "trim_outliers_iqr(" in fonte_export:
        divergencias.append("scripts/exportar_valor_pago_por_bairro.py não usa só a camada limpa única (motivo_valor_sujo) ou ainda usa trim_outliers_iqr.")

    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:20])
        raise ValidationError(f"cálculo de preço fora da camada limpa única:\n{linhas}")
    n_clean = sum(1 for r in itbi_records if r["is_clean_sale"])
    print(f"[validate_build] OK 12/16 — camada limpa única: {n_clean} registros limpos; faixa v2, Preço por m² e Captação batem com a recomputação só da camada limpa; nenhum corte extra.")


def check_faixas_amostra(data):
    """Proteção de amostra das faixas de preço (2026-10-06): trava o build se
      1. o período de uma faixa (perfil v2 por bairro+tipo e Preço por m²)
         for incoerente: janela 12/24 só com >= 30 vendas limpas; "poucas
         vendas" só na janela de 36 meses e só com < 30; meses/ período
         coerentes;
      2. uma faixa "poucas vendas" (ou inexistente) tiver sido usada nas
         notas: aderência do Painel 8 precisa ser None (dado ausente) nesse
         caso e preenchida quando a faixa é confiável; bairro sem nenhuma
         faixa confiável precisa ter estoque_perfil_faixa_preco_nota None e
         nenhum selo de estoque."""
    import engine

    minimo = engine.PERFIL_MIN_VENDAS_FAIXA
    divergencias = []

    def conferir_meta(meta, onde):
        w, n, poucas = meta["janela_meses"], meta["n_vendas_limpas"], meta["poucas_vendas"]
        if w not in engine.PERFIL_JANELAS_MESES:
            divergencias.append(f"{onde}: janela {w} fora de {engine.PERFIL_JANELAS_MESES}")
        if w < max(engine.PERFIL_JANELAS_MESES) and (n < minimo or poucas):
            divergencias.append(f"{onde}: janela de {w} meses com só {n} vendas / poucas_vendas={poucas} (12 e 24 meses exigem >= {minimo})")
        if w == max(engine.PERFIL_JANELAS_MESES) and poucas != (n < minimo):
            divergencias.append(f"{onde}: poucas_vendas={poucas} incoerente com n={n} (limite {minimo})")
        if meta["meses_com_dado"] > w or meta["periodo_inicio"] > meta["periodo_fim"]:
            divergencias.append(f"{onde}: período {meta['periodo_inicio']}..{meta['periodo_fim']} / {meta['meses_com_dado']} meses incoerente")

    bairros = data["bairros"]
    for b in TARGETS:
        v = bairros[b]
        metas = v["perfil_vencedor_faixa_preco_v2_meta"]
        for tipo, meta in metas.items():
            conferir_meta(meta, f"faixa v2 {b}/{tipo}")
        confiavel = any(m["n_vendas_limpas"] > 0 and not m["poucas_vendas"] for m in metas.values())
        if v["perfil_faixa_confiavel"] != confiavel:
            divergencias.append(f"{b}: perfil_faixa_confiavel={v['perfil_faixa_confiavel']} mas as faixas dizem {confiavel}")
        if not confiavel:
            if v["estoque_perfil_faixa_preco_nota"] is not None:
                divergencias.append(f"{b}: sem faixa confiável mas estoque_perfil_faixa_preco_nota={v['estoque_perfil_faixa_preco_nota']} (deveria ser None — dado ausente no f2)")
            if v["selo_escassez_real"] or v["estoque_fora_do_perfil"]:
                divergencias.append(f"{b}: selo de estoque aceso sem nenhuma faixa confiável")
        elif v["estoque_perfil_faixa_preco_nota"] is None:
            divergencias.append(f"{b}: faixa confiável mas estoque_perfil_faixa_preco_nota=None")

    for linha in data["preco_m2_painel"]:
        conferir_meta(
            {"janela_meses": linha["janela_meses"], "n_vendas_limpas": linha["n_vendas_revenda_12m"], "poucas_vendas": linha["poucas_vendas"],
             "meses_com_dado": linha["meses_com_dado"], "periodo_inicio": linha["periodo_inicio"], "periodo_fim": linha["periodo_fim"]},
            f"Preço por m² {linha['bairro']}/{linha['faixa']}",
        )
        if linha["amostra_pequena"] != linha["poucas_vendas"]:
            divergencias.append(f"Preço por m² {linha['bairro']}/{linha['faixa']}: amostra_pequena != poucas_vendas")

    n_ader_ausente = 0
    for im in data["imoveis_prioritarios"]:
        meta = bairros[im["bairro"]]["perfil_vencedor_faixa_preco_v2_meta"].get(im.get("tipo_imovel"))
        faixa = bairros[im["bairro"]]["perfil_vencedor_faixa_preco_v2"].get(im.get("tipo_imovel"))
        confiavel = bool(faixa) and meta is not None and not meta["poucas_vendas"]
        if confiavel and im["profile_adherence"] is None:
            divergencias.append(f"imoveis_prioritarios[{im.get('codigo')}]: faixa confiável mas aderência None")
            break
        if not confiavel:
            n_ader_ausente += 1
            if im["profile_adherence"] is not None:
                divergencias.append(f"imoveis_prioritarios[{im.get('codigo')}]: faixa 'poucas vendas' usada na aderência ({im['profile_adherence']}) — deveria ser dado ausente")
                break

    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:20])
        raise ValidationError(f"faixas de preço fora da regra de amostra (12/24/36 meses, mínimo {minimo}):\n{linhas}")
    cont = {}
    for b in TARGETS:
        for t, m in bairros[b]["perfil_vencedor_faixa_preco_v2_meta"].items():
            k = "poucas vendas" if m["poucas_vendas"] else f"{m['janela_meses']} meses"
            cont[k] = cont.get(k, 0) + 1
    print(f"[validate_build] OK 13/16 — faixas de preço com proteção de amostra: {dict(sorted(cont.items()))}; {n_ader_ausente} imóveis com aderência ausente (peso redistribuído).")


def check_buscas_google(data):
    """Passo 5 (2026-10-06): a data da busca do Google é POR BAIRRO. Confere
    só a COERÊNCIA do que existir (Google é fonte opcional — a falta de
    dado nunca trava a atualização diária): todo bairro com busca tem
    fetched_at/idade_dias/fresco; idade_dias bate com a data (±1 dia);
    fresco == (idade < 30 dias e a busca de agora não falhou); e o resumo
    (search_interest_meta / fontes.google_busca) bate com os bairros."""
    import datetime

    bairros = data["bairros"]
    com = {b: v["search_interest"] for b, v in bairros.items() if v.get("search_interest")}
    if not com:
        print("[validate_build] OK 14/16 — sem dado de busca do Google (fonte opcional); nada a conferir.")
        return
    gerado = datetime.datetime.fromisoformat(data["generated_at_iso"])
    divergencias = []
    for b, si in com.items():
        faltam = [k for k in ("fetched_at", "idade_dias", "fresco", "avg_monthly_searches", "nivel") if k not in si]
        if faltam:
            divergencias.append(f"{b}: busca sem os campos {faltam}")
            continue
        idade = (gerado - datetime.datetime.fromisoformat(si["fetched_at"])).days
        if abs(idade - si["idade_dias"]) > 1:
            divergencias.append(f"{b}: idade_dias={si['idade_dias']} mas a data {si['fetched_at'][:10]} dá {idade}")
        if bool(si["fresco"]) != (si["idade_dias"] < 30 and not si.get("fetch_falhou", False)):
            divergencias.append(f"{b}: fresco={si['fresco']} incoerente com idade {si['idade_dias']} dias")
    meta = data.get("search_interest_meta") or {}
    n_frescos = sum(1 for si in com.values() if si.get("fresco"))
    datas = sorted(si["fetched_at"] for si in com.values() if "fetched_at" in si)
    if meta.get("n_bairros_com_dado") != len(com) or meta.get("n_frescos") != n_frescos or meta.get("mais_antiga") != datas[0]:
        divergencias.append(f"resumo search_interest_meta incoerente com os bairros: {meta} vs {len(com)} bairros, {n_frescos} frescos, mais antiga {datas[0]}")
    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:20])
        raise ValidationError(f"datas de busca do Google por bairro incoerentes:\n{linhas}")
    print(f"[validate_build] OK 14/16 — buscas do Google por bairro: {len(com)} bairros com data própria (de {datas[0][:10]} a {datas[-1][:10]}), {n_frescos} frescos.")


def check_rodada_a(data):
    """Rodada A (2026-10-06): (a) Prontidão — pesos sem f3 somam 100% e a nota
    de cada bairro confere com a recomputação pelos 5 fatores; (b) Valor de
    Oportunidade — todo achado de apartamento compara com a mediana do MESMO
    prédio (>= 4 vendas, P75/P25 <= 1,25) e tem >= 20% de desconto; Atenção só
    a partir de 30%; (c) Top 30 da Captação — <= 30, sem unidade anunciada hoje,
    sem endereço único, na ordem pedida (selo 'Pouco estoque na rede' primeiro,
    depois mais revendas)."""
    import engine

    pesos = engine.PESOS_PRONTIDAO
    if "f3" in pesos or abs(sum(pesos.values()) - 1.0) > 1e-9:
        raise ValidationError(f"pesos da Prontidão fora do combinado (sem f3, somando 100%): {pesos}")

    divergencias = []
    for a in data["valor_oportunidade"]["imoveis"]:
        if a["tipo_imovel"] != "apartamento":
            continue
        if a.get("comparacao") != "predio":
            divergencias.append(f"{a['codigo']}: apartamento comparado por '{a.get('comparacao')}' (deveria ser 'predio')")
        n = a.get("n_vendas_predio")
        razao = a.get("razao_p75_p25_predio")
        if n is None or n < engine.VALOR_OPORT_APTO_MIN_VENDAS:
            divergencias.append(f"{a['codigo']}: prédio com {n} vendas (mínimo {engine.VALOR_OPORT_APTO_MIN_VENDAS})")
        if razao is None or razao > engine.VALOR_OPORT_APTO_MAX_P75_P25 + 0.005:
            divergencias.append(f"{a['codigo']}: prédio não homogêneo (P75/P25 = {razao})")
        med = a.get("valor_total_mediana")
        if not med or a["desconto_pct"] < engine.VALOR_OPORTUNIDADE_MIN_DESCONTO * 100 - 0.06:
            divergencias.append(f"{a['codigo']}: desconto {a['desconto_pct']}% abaixo do mínimo")
        elif abs((1 - a["valor"] / med) * 100 - a["desconto_pct"]) > 0.11:
            divergencias.append(f"{a['codigo']}: desconto {a['desconto_pct']}% não bate com valor/mediana do prédio")
        if a["atencao"] != (a["desconto_pct"] >= engine.VALOR_OPORTUNIDADE_ATENCAO_DESCONTO * 100 - 0.06):
            divergencias.append(f"{a['codigo']}: selo Atenção incoerente com o desconto {a['desconto_pct']}%")
    meta_apto = data["valor_oportunidade"].get("meta_apto") or {}
    n_apto = sum(1 for a in data["valor_oportunidade"]["imoveis"] if a["tipo_imovel"] == "apartamento")
    if meta_apto.get("achados_apto") != n_apto:
        divergencias.append(f"meta_apto.achados_apto={meta_apto.get('achados_apto')} mas há {n_apto} achados de apartamento")

    top = data.get("captacao_top30")
    if not isinstance(top, list) or len(top) > engine.CAPTACAO_TOP_N:
        divergencias.append(f"captacao_top30 deveria ser uma lista de até {engine.CAPTACAO_TOP_N}")
        top = []
    for e in top:
        if e["tem_unidade_a_venda_hoje"] or e["unico"]:
            divergencias.append(f"Top 30: {e['endereco']} tem unidade anunciada hoje ou é endereço único")
    ordem = [(not e["selo_escassez_real"], -e["n_vendas"]) for e in top]
    if ordem != sorted(ordem):
        divergencias.append("Top 30 fora da ordem (selo 'Pouco estoque na rede' primeiro, depois mais revendas)")
    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:20])
        raise ValidationError(f"Rodada A — {len(divergencias)} divergência(s):\n{linhas}")
    print(f"[validate_build] OK 15/16 — Rodada A: Prontidão com 5 fatores (pesos {pesos}); {n_apto} achados de apartamento todos pelo prédio homogêneo (>= 4 vendas, P75/P25 <= 1,25); Top 30 da Captação com {len(top)} endereços na ordem certa.")


def check_historico_anuncios(historico, data):
    """Rodada A (item 7): o histórico de anúncios que vai ser gravado confere
    com os anúncios da rede de hoje — todo código de hoje está lá e ativo, nenhum
    código ativo no arquivo some da rede de hoje, sem código repetido, preço
    atual = preço de hoje, datas coerentes. Sem a API da nonStop (export
    manual) não há o que conferir."""
    estado, registros = historico if historico else (None, None)
    if estado is None or registros is None:
        print("[validate_build] OK 16/16 — histórico de anúncios: sem a API da nonStop hoje, arquivo não é alterado; nada a conferir.")
        return
    hoje = data["meta"]["historico_anuncios"]["data"]
    hoje_por_codigo = {r["codigo"]: r for r in registros if r.get("codigo") and r.get("valor")}
    divergencias = []
    for c, rec in hoje_por_codigo.items():
        h = estado.get(c)
        if h is None:
            divergencias.append(f"{c}: anúncio de hoje não está no histórico")
            continue
        if h["saida"] is not None or h["visto_ultima"] != hoje:
            divergencias.append(f"{c}: aparece hoje mas o histórico diz saída={h['saida']}, visto_ultima={h['visto_ultima']}")
        if h["preco_atual"] != rec["valor"]:
            divergencias.append(f"{c}: preço de hoje {rec['valor']} != preco_atual {h['preco_atual']}")
    for c, h in estado.items():
        if c not in hoje_por_codigo and h["saida"] is None:
            divergencias.append(f"{c}: sumiu da rede mas continua 'ativo' no histórico")
        if h["visto_primeira"] > h["visto_ultima"] or (h["saida"] is not None and h["saida"] <= h["visto_ultima"]):
            divergencias.append(f"{c}: datas incoerentes ({h['visto_primeira']} / {h['visto_ultima']} / {h['saida']})")
        seq = [h["preco_inicial"]] + [m[1] for m in h["mudancas_preco"]]
        if seq[-1] != h["preco_atual"]:
            divergencias.append(f"{c}: preco_atual {h['preco_atual']} não é o último da sequência {seq}")
    ativos = sum(1 for h in estado.values() if h["saida"] is None)
    if ativos != len(hoje_por_codigo):
        divergencias.append(f"{ativos} ativos no histórico x {len(hoje_por_codigo)} anúncios na rede hoje")
    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias[:20])
        raise ValidationError(f"histórico de anúncios incoerente ({len(divergencias)}):\n{linhas}")
    r = data["meta"]["historico_anuncios"]
    print(f"[validate_build] OK 16/16 — histórico de anúncios: {r['ativos']} ativos = {len(hoje_por_codigo)} na rede hoje; {r['novos']} novos, {r['sairam']} saíram, {r['mudancas_de_preco']} mudanças de preço; {len(estado)} anúncios no arquivo.")


VARIACAO_MAX_ESTOQUE = 0.30


def check_variacao_estoque_nonstop(usn_meta, out_path):
    """Passo 3b (2026-10-01), item a pedido pelo usuário: mesma lógica de
    check_variacao_bairros, mas pro ESTOQUE total da nonStop (achado da
    auditoria: uma resposta vazia/anômala da API — ex. token revogado,
    endpoint fora do ar devolvendo lista parcial — não travava nada antes;
    o build publicava silenciosamente um site com metade dos anúncios).
    Só de um lado (queda): um AUMENTO de estoque nunca é perigoso, então
    não trava por isso — mirror de VARIACAO_MAX/ALLOW_LARGE_CHANGES."""
    if not out_path.exists():
        print("[validate_build] OK 8/16 — sem versão publicada anterior pra comparar estoque (primeira execução).")
        return
    try:
        old_data = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[validate_build] AVISO — não consegui ler a versão anterior pra comparar estoque ({e!r}); pulando checagem 8/16.")
        return

    old_n = (old_data.get("meta", {}).get("usn") or {}).get("rows_apos_dedup")
    new_n = usn_meta.get("rows_apos_dedup")
    if old_n is None or new_n is None or old_n == 0:
        print("[validate_build] OK 8/16 — sem 'rows_apos_dedup' na versão anterior ou atual pra comparar (campo novo); pulando.")
        return

    variacao = (new_n - old_n) / old_n
    if variacao < -VARIACAO_MAX_ESTOQUE:
        msg = (
            f"estoque válido da nonStop caiu {abs(variacao)*100:.1f}% (de {old_n} para {new_n} "
            f"anúncios após deduplicação) vs a última publicação — mais que {VARIACAO_MAX_ESTOQUE*100:.0f}%, "
            "parece resposta vazia/anômala da API (token revogado, endpoint fora do ar, etc.), não uma "
            "queda real de estoque."
        )
        if os.environ.get("ALLOW_LARGE_CHANGES", "").strip() == "1":
            print(f"[validate_build] AVISO 8/16 — {msg} Mas ALLOW_LARGE_CHANGES=1 está setado — publicando mesmo assim.")
            return
        raise ValidationError(
            f"{msg} Travando a publicação e mantendo os dados anteriores. Se a queda é real e esperada, "
            "rode de novo com ALLOW_LARGE_CHANGES=1 no ambiente."
        )
    print(f"[validate_build] OK 8/16 — estoque nonStop não caiu mais que {VARIACAO_MAX_ESTOQUE*100:.0f}% ({old_n} -> {new_n}).")


def check_dedup_aplicada(usn_records):
    """Passo 3b (2026-10-01), item b pedido pelo usuário: deduplicação de
    anúncios (mesmo endereço + área + preço ±3%, mantém o mais recente)
    tem que já ter sido aplicada aos usn_records ANTES de chegarem no
    motor/raw.json — ver nonstop_client.deduplicar_registros(), chamada
    uma vez em build_data.py._get_usn_records(). Esta checagem roda a
    MESMA função de novo sobre o conjunto já deduplicado: se achar
    qualquer duplicata nova, é sinal de que _get_usn_records() parou de
    deduplicar (regressão) — deduplicar um conjunto já deduplicado deve
    sempre dar zero remoções (idempotente)."""
    import nonstop_client

    _dedupados, n_removidos = nonstop_client.deduplicar_registros(usn_records, log=lambda *a, **k: None)
    if n_removidos:
        raise ValidationError(
            f"{n_removidos} anúncio(s) duplicado(s) (mesmo endereço+área+preço ±3%) encontrados nos "
            "usn_records que chegaram no motor — a deduplicação deveria ter rodado antes "
            "(ver build_data.py._get_usn_records) e não rodou, ou rodou e não é idempotente."
        )
    print(f"[validate_build] OK 9/16 — {len(usn_records)} anúncios no estoque, nenhuma duplicata (endereço+área+preço ±3%) restante.")


def validate_before_publish(year_to_path, itbi_stats, data, out_path, usn_records, itbi_records, historico=None):
    """Chamado por build_data.py logo antes de escrever site/data.json.
    Levanta SystemExit (para o processo com código != 0) se qualquer
    checagem falhar — build_data.py não deve capturar essa exceção."""
    print("[validate_build] rodando as 16 checagens antes de publicar...")
    check_linhas_lidas(year_to_path, itbi_stats)
    check_variacao_bairros(data["bairros"], out_path)
    check_formato_paineis(data)
    check_consistencia_carteira_77(data)
    check_prontidao_consistencia(data)
    check_perfil_v1_obsoleto(data)
    check_faixa_metragem_apartamento_suspensa(data)
    check_variacao_estoque_nonstop(data["meta"]["usn"], out_path)
    check_dedup_aplicada(usn_records)
    check_selos_idade_bonus(data, usn_records)
    check_captacao_limpa(data)
    check_camada_limpa_unica(data, itbi_records)
    check_faixas_amostra(data)
    check_buscas_google(data)
    check_rodada_a(data)
    check_historico_anuncios(historico, data)
    print("[validate_build] todas as checagens passaram — liberado pra publicar.")
