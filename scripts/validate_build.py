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
    print(f"[validate_build] OK 1/7 — linhas lidas batem: {lido} == {total_rows} totais - {header_rows} cabeçalho, em {sheets_checked} abas.")


def check_variacao_bairros(new_bairros, old_data_path):
    if not old_data_path.exists():
        print("[validate_build] OK 2/7 — sem versão publicada anterior pra comparar (primeira execução).")
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
    print(f"[validate_build] OK 2/7 — nenhum bairro variou mais que {VARIACAO_MAX*100:.0f}% em volume_primary_year.")


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

    print(f"[validate_build] OK 3/7 — formato de data.json íntegro: {len(bairros)} bairros, todas as chaves esperadas presentes.")


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
    print(f"[validate_build] OK 4/7 — {len(TARGETS)} bairros batem exato com carteira_77 em {len(campos)} campos.")


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
    print(f"[validate_build] OK 5/7 — Prontidão: {len(TARGETS)} bairros com nota, top 10 sem amostra pequena.")


def check_perfil_v1_obsoleto(data):
    """Passo 2 (2026-10-01) + passo 2b: "nenhum painel pode ler a faixa
    antiga (v1)" — trava o build se Captação Ativa Estratégica,
    Estoque×Demanda, flag_prioridade_maxima OU a aderência do Painel 8
    (Imóveis Prioritários — estendido no passo 2b) voltarem a depender
    do sistema de perfil por METRAGEM (area_band/price_band/profile_
    quartos/profile_vagas/profile_reliability/stock_matching_profile).

    NÃO é uma proibição geral desses campos no código — eles continuam
    existindo em data.json (obsoletos, não removidos) e ainda alimentam
    um consumidor fora do escopo desta migração, que o usuário pediu pra
    só REPORTAR: o painel "Perfil por Bairro" (que exibe o v1 por
    definição). Checagens:

      1. data.json: `captacao_estrategica[*].perfil` não pode ter chaves
         v1 — só faixa_preco/estoque_perfil_faixa_preco/estoque_fora_do_
         perfil (v2).
      2. data.json: flag_prioridade_maxima de cada bairro precisa bater
         com a recomputação usando estoque_perfil_faixa_preco (v2).
      3. site/app.js: a string literal "stock_matching_profile" não pode
         mais aparecer fora de comentário.
      4. (passo 2b) data.json: `imoveis_prioritarios[*]` não pode ter as
         chaves v1 "area_band_reliability"/"profile_reliability" (a
         aderência agora é só faixa de preço v2, sem conceito de
         confiança regional nem de dormitórios/vagas típicos)."""
    import engine

    divergencias = []

    for g in data.get("captacao_estrategica", []):
        chaves_v1_presentes = {"area_band", "price_band", "profile_quartos", "profile_vagas", "profile_reliability"} & g.get("perfil", {}).keys()
        if chaves_v1_presentes:
            divergencias.append(f"captacao_estrategica[{g.get('bairro')}].perfil ainda tem chave(s) v1: {sorted(chaves_v1_presentes)}")

    bairros = data["bairros"]
    for b in TARGETS:
        v = bairros.get(b, {})
        esperado = (
            v.get("estoque_perfil_faixa_preco", 0) <= engine.CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH
            and v.get("revenda_12m", 0) >= engine.VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY
        )
        if v.get("flag_prioridade_maxima") != esperado:
            divergencias.append(f"{b}.flag_prioridade_maxima={v.get('flag_prioridade_maxima')!r}, esperado {esperado!r} (recomputado via estoque_perfil_faixa_preco v2) — parece estar usando stock_matching_profile (v1) de novo.")

    app_js = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    linhas_proibidas = [
        (i + 1, linha) for i, linha in enumerate(app_js.splitlines())
        if "stock_matching_profile" in linha and not linha.strip().startswith("//")
    ]
    if linhas_proibidas:
        divergencias.append(
            "site/app.js ainda lê 'stock_matching_profile' (v1) fora de comentário: "
            + "; ".join(f"linha {n}: {l.strip()}" for n, l in linhas_proibidas[:10])
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
    print("[validate_build] OK 6/7 — Captação Estratégica/Estoque×Demanda/flag_prioridade_maxima/Painel 8 só usam a faixa de preço v2.")


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
         `valor_oportunidade.imoveis` (deveriam ser só casa agora)."""
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
    ]
    if aptos_valor_oportunidade:
        divergencias.append(
            f"{len(aptos_valor_oportunidade)} achado(s) de apartamento em valor_oportunidade.imoveis "
            "(deveriam ser só casa — comparação por faixa de metragem suspensa pra apartamento)."
        )

    if divergencias:
        linhas = "\n".join(f"  - {d}" for d in divergencias)
        raise ValidationError(f"faixa_metragem() voltou a comparar apartamento ITBI x anúncio:\n{linhas}")
    print("[validate_build] OK 7/7 — faixa_metragem() não compara apartamento ITBI x anúncio em nenhum painel.")


def validate_before_publish(year_to_path, itbi_stats, data, out_path):
    """Chamado por build_data.py logo antes de escrever site/data.json.
    Levanta SystemExit (para o processo com código != 0) se qualquer
    checagem falhar — build_data.py não deve capturar essa exceção."""
    print("[validate_build] rodando as 7 checagens antes de publicar...")
    check_linhas_lidas(year_to_path, itbi_stats)
    check_variacao_bairros(data["bairros"], out_path)
    check_formato_paineis(data)
    check_consistencia_carteira_77(data)
    check_prontidao_consistencia(data)
    check_perfil_v1_obsoleto(data)
    check_faixa_metragem_apartamento_suspensa(data)
    print("[validate_build] todas as checagens passaram — liberado pra publicar.")
