#!/usr/bin/env python3
"""
Pipeline diário da dashboard de Investimento Imobiliário SP.

  1. Sincroniza os .xlsx de ITBI da Prefeitura (itbi_source.py) — só baixa
     de novo o que mudou desde a última execução.
  2. Busca o estoque atual de anúncios na API da nonStop (nonstop_client.py)
     — precisa de NONSTOP_TOKEN. Sem token configurado, cai automaticamente
     para o export manual em dados-usenonstop/*.xlsx (mesmo formato que o
     motor de cálculo já usava antes da automação), pra não travar o
     pipeline enquanto o token não estiver disponível.
  3. Roda o motor de cálculo (engine.py) e escreve site/data.json.

Rodar:
    python3 scripts/build_data.py

Em produção (GitHub Actions), roda todo dia — ver .github/workflows/build-data.yml.
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clean_itbi
import engine
import itbi_source
import validate_build
from normalize import TARGETS, today_excel_serial
from parse_itbi import parse_itbi_years

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data.json"
OUT_RAW = ROOT / "site" / "raw.json"
# Fica em site/ (não em data/, que é ignorado pelo git) de propósito — o
# usuário pediu pra poder auditar esse log, então ele precisa ser
# versionado/committed junto com data.json e raw.json a cada execução.
OUT_CLEAN_LOG = ROOT / "site" / "itbi_clean_log.json"
OUT_PRECO_M2_CSV = ROOT / "output" / "preco_m2_por_bairro.csv"
ENV_FILE = ROOT / ".env"


def _load_dotenv():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _get_usn_records():
    """Estoque atual: API da nonStop se NONSTOP_TOKEN estiver definido,
    senão cai pro export manual (dados-usenonstop/*.xlsx) como fallback."""
    token = os.environ.get("NONSTOP_TOKEN", "").strip()
    if token:
        import nonstop_client

        print("[build] usando API da nonStop (NONSTOP_TOKEN definido)")
        return nonstop_client.fetch_all_records(token)

    print("[build] NONSTOP_TOKEN não definido — usando export manual dados-usenonstop/*.xlsx como fallback")
    from parse_usenonstop_xlsx import parse_usenonstop_xlsx

    candidates = sorted((ROOT / "dados-usenonstop").glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit(
            "Sem NONSTOP_TOKEN e sem nenhum .xlsx em dados-usenonstop/ — não há fonte de estoque disponível."
        )
    records, stats = parse_usenonstop_xlsx(candidates[0])
    print(f"[build] {candidates[0].name}: {stats}")
    return records, {"fonte": "xlsx_manual", "arquivo": candidates[0].name, **stats}


def build_raw_payload(itbi_records, usn_records, years, periodo_12m_externo, carteira_77_bairros):
    """Registros individuais + tabelas de índice, pro motor de cálculo em
    JavaScript (site/engine.js) recomputar tudo no navegador quando o
    usuário usa os filtros de bairro/preço — mesma ideia do antigo
    dashboard_raw.json (ver itbi_methodology_spec.md §18), só que agora
    carregado à parte (site/raw.json) e buscado sob demanda (lazy) na
    primeira vez que um filtro é usado, pra não pesar o carregamento inicial.
    """
    bairro_idx = {b: i for i, b in enumerate(TARGETS)}

    addr_index = {}
    addr_display = []

    def intern_addr(addr_key, display, prefer=False):
        if addr_key is None:
            return None
        if addr_key not in addr_index:
            addr_index[addr_key] = len(addr_display)
            addr_display.append(display)
        elif prefer and display:
            addr_display[addr_index[addr_key]] = display
        return addr_index[addr_key]

    itbi_out = []
    for r in itbi_records:
        aidx = intern_addr(r["addr_key"], r["addr_display"])
        itbi_out.append([
            bairro_idx[r["bairro"]], r["sheet_year"], r["day"], r["valor"], r["area"], aidx,
            r["is_compra_venda"], r["is_full_transfer"], r["tipo_imovel"], r["is_clean_sale"],
            r.get("is_retomada", False),
            # Etapa 2, item 2 (2026-10-01): uso_code (coluna X do ITBI, "10"/
            # "20"/...) — campo NOVO, acrescentado no fim da tupla (não mexe
            # nos índices existentes) pra engine.js replicar
            # engine.py._is_revenda_aprovada (valor total pago em revenda,
            # painel "Preço por m²").
            r.get("uso_code"),
            # Etapa 2, item 1.2b (2026-10-01): is_revenda/is_planta — já
            # calculados por cascata_completa.resolver_registros_engine()
            # (regra aprovada, não recalculada em JS — só o resultado final
            # vem junto, igual ao bairro em si, que já chega resolvido pela
            # cascata via bairro_idx[r["bairro"]] acima).
            r.get("is_revenda", False), r.get("is_planta", False),
        ])

    usn_out = []
    for r in usn_records:
        # Prefere a grafia natural do endereço vinda da nonStop pra tabela
        # compartilhada (usada em referências a nível de PRÉDIO, como
        # Captação Ativa) — mas sem o complemento (número da unidade), que
        # só faz sentido pro anúncio individual, não pro prédio inteiro.
        # addr_display_building = "Rua X, 123" (nunca "Rua X, 123 - apto 45").
        aidx = intern_addr(r["addr_key"], r["addr_display_building"], prefer=True)
        usn_out.append([
            bairro_idx[r["bairro"]], aidx, r["addr_display"], r["valor"], r["area"],
            r["quartos"], r["vagas"], r["lat"], r["lon"], r["situacao_code"], r["codigo"], r["link"],
            r.get("tipo_imovel"),
        ])

    return {
        "years": years,
        "bairros": TARGETS,
        "addr_display": addr_display,
        "itbi": itbi_out,
        "usn": usn_out,
        # Etapa 2, item 1.2b (2026-10-01): unidades IPTU por bairro — dado
        # do IPTU (não do ITBI, não muda com filtro de preço/bairro),
        # calculado só em cascata_completa.gerar_dados_carteira_77() pra
        # não reprocessar o cadastro do GeoSampa aqui. engine.js usa isso
        # pra recalcular giro_12m_pct = revenda_12m (filtrado) / unidades.
        "unidades_iptu": {b: carteira_77_bairros[b]["unidades_iptu"] for b in TARGETS},
        "constants": {
            "reliability_threshold": engine.RELIABILITY_THRESHOLD,
            "neighbor_max_km": 3,
            "neighbor_count": 3,
            "trend_cap": engine.TREND_CAP,
            "launch_min_count": engine.LAUNCH_MIN_COUNT,
            "launch_window_days": engine.LAUNCH_WINDOW_DAYS,
            "addr_min_valor": engine.ADDR_MIN_VALOR,
            "addr_max_ratio": engine.ADDR_MAX_RATIO,
            "addr_max_ratio_area": engine.ADDR_MAX_RATIO_AREA,
            "valor_oportunidade_min_desconto": engine.VALOR_OPORTUNIDADE_MIN_DESCONTO,
            "valor_oportunidade_atencao_desconto": engine.VALOR_OPORTUNIDADE_ATENCAO_DESCONTO,
            "valor_oportunidade_min_vendas_primary": engine.VALOR_OPORTUNIDADE_MIN_VENDAS_PRIMARY,
            "captacao_estrategica_max_stock_match": engine.CAPTACAO_ESTRATEGICA_MAX_STOCK_MATCH,
            "captacao_estrategica_min_enderecos": engine.CAPTACAO_ESTRATEGICA_MIN_ENDERECOS,
            "area_bucket_width": 20,
            "max_per_exact_area": 5,
            "area_cap": 600,
            "pesos_painel8": engine.PESOS_PAINEL8,
            "pesos_prontidao": engine.PESOS_PRONTIDAO,
            "faixas_metragem": [[lo, (hi if hi != float("inf") else None), label] for lo, hi, label in clean_itbi.FAIXAS_METRAGEM],
            "min_transacoes_preco_m2_12m": engine.MIN_TRANSACOES_PRECO_M2_12M,
            "min_vendas_tendencia": engine.MIN_VENDAS_TENDENCIA,
            "min_vendas_top10": engine.MIN_VENDAS_TOP10,
            "min_anuncios_alerta": engine.MIN_ANUNCIOS_ALERTA,
            "janela_preco_m2_dias": engine.JANELA_PRECO_M2_DIAS,
            # Congelado no momento do build — o recompute no navegador (ao
            # aplicar um filtro) usa esse valor, não a data real do
            # visitante, pra bater exatamente com data.json quando nenhum
            # filtro está ativo (mesma janela "últimos 12 meses" nos dois).
            "hoje_serial": today_excel_serial(),
            # Etapa 2, item 1.2b (2026-10-01): fim da janela de 12 meses,
            # já resolvido no servidor (ver engine._compute_volume_12m e
            # cascata_completa.resolver_registros_engine) — engine.js usa
            # isso como âncora pra regenerar periodo_12m/periodo_12m_
            # anterior/meses_incompletos (mesma fórmula, ymAddMonths), em
            # vez de derivar de novo a partir de itbi (que no navegador só
            # tem revenda+planta — derivar ali dava uma janela diferente
            # da de carteira_77/data.json, mesmo bug do lado Python,
            # corrigido com periodo_12m_externo).
            "fim_janela_12m": list(periodo_12m_externo[0][-1]),
        },
    }


SEARCH_INTEREST_MAX_AGE_DIAS = 30  # revisão 2026-10-01 (Prontidão): acima disso, "sem dado recente" em vez do selo alto/médio/baixo


def _get_search_interest():
    """Interesse de busca no Google por bairro (opcional — ver
    keyword_client.py). Sinal PROSPECTIVO de demanda (gente pesquisando
    hoje), complementar à liquidez do ITBI (retrospectiva). Classificação
    Alto/Médio/Baixo é sempre por tercil contra os 77 bairros inteiros —
    de propósito não recalcula por filtro de bairro/preço na tela (com um
    filtro reduzindo pra poucos bairros, tercil perderia sentido), então
    "Alto" sempre quer dizer "alto pra São Paulo inteira", uma referência
    estável.

    Retorna (data, meta). Revisão 2026-10-01 (migração do Prontidão):
    `meta` expõe fonte/data do último fetch bem-sucedido e `fresco`
    (< SEARCH_INTEREST_MAX_AGE_DIAS dias E a tentativa de hoje não
    falhou) — usado pelo front pra trocar o selo alto/médio/baixo por
    "sem dado recente" quando a fonte está desatualizada OU quebrada
    (ver keyword_client.get_search_interest_cached)."""
    import datetime
    import keyword_client

    data, cache_meta = keyword_client.get_search_interest_cached(TARGETS)
    if not data:
        return None, None

    values = sorted(v["avg_monthly_searches"] for v in data.values())
    n = len(values)
    low_cut = values[n // 3]
    high_cut = values[(2 * n) // 3]

    for b, v in data.items():
        s = v["avg_monthly_searches"]
        v["nivel"] = "alto" if s > high_cut else ("baixo" if s <= low_cut else "medio")

    fetched_at = datetime.datetime.fromisoformat(cache_meta["fetched_at"])
    idade_dias = (datetime.datetime.now(datetime.timezone.utc) - fetched_at).days
    meta = {
        "fonte": "Google Ads Keyword Planner",
        "fetched_at": cache_meta["fetched_at"],
        "idade_dias": idade_dias,
        "fresco": idade_dias < SEARCH_INTEREST_MAX_AGE_DIAS and not cache_meta["fetch_falhou"],
    }
    return data, meta


def _attach_search_interest(bairros_out, search_interest):
    for b, entry in bairros_out.items():
        if b in search_interest:
            entry["search_interest"] = search_interest[b]


def _write_preco_m2_csv(preco_m2_painel, path):
    """Export pedido na Etapa 4 (2026-09-29) — mesmo dado do painel "Preço
    por m² — Pago × Pedido", em CSV pra abrir fora da dashboard (Excel/
    Sheets). Uma linha por bairro+faixa (só apartamento, últimos 12 meses
    — ver engine.py._compute_preco_m2_painel)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "bairro", "faixa_metragem", "mediana_pago_r_m2", "mediana_pedido_r_m2", "gap_pct",
        "valor_total_mediana", "valor_total_p25", "valor_total_p75", "n_vendas_revenda_12m",
        "n_transacoes_12m", "n_anuncios", "amostra_pequena",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in preco_m2_painel:
            w.writerow([
                p["bairro"], p["faixa"], p["mediana_pago_m2"], p["mediana_pedido_m2"], p["gap_pct"],
                p["valor_total_mediana"], p["valor_total_p25"], p["valor_total_p75"], p["n_vendas_revenda_12m"],
                p["n_transacoes_12m"], p["n_anuncios"], "sim" if p["amostra_pequena"] else "nao",
            ])


def main():
    _load_dotenv()
    t_start = time.time()

    current_year = datetime.now().year
    years = [current_year - 2, current_year - 1, current_year]

    print(f"[build] anos: {years}")
    if os.environ.get("SKIP_ITBI_SYNC", "").strip() == "1":
        # Escape hatch manual pra congelar a base (usado durante toda a
        # auditoria de correção de metodologia do ITBI, 2026-09-30, pra
        # nenhum relatório antes×depois comparar contra planilhas
        # diferentes no meio do caminho — auditoria mergeada em main em
        # 2026-10-01, tag pos-correcao-itbi) — nunca setado pelo cron;
        # só pra uso manual quando alguém precisar repetir o mesmo tipo
        # de comparação controlada no futuro.
        print("[build] SKIP_ITBI_SYNC=1 — base congelada manualmente, sem checar planilha nova na Prefeitura")
        changed_years = set()
    else:
        # A Prefeitura já bloqueou a Action com 403 mesmo depois do retry/backoff
        # de itbi_source.py (2 vezes em 3 dias, 2026-09-25 e 2026-09-27) — falha
        # de rede aqui não pode mais derrubar o pipeline inteiro (estoque/preço
        # da nonStop continuam querendo atualizar todo dia mesmo sem ITBI novo).
        # Cai pro cache local em data/itbi_raw/ (existe sempre que já rodou com
        # sucesso alguma vez — ver actions/cache no workflow) e tenta de novo
        # amanhã; o pior caso é ITBI com até ~1 dia a mais de atraso, nunca um
        # site fora do ar.
        try:
            changed_years = itbi_source.sync(years)
            print(f"[build] ITBI sincronizado ({time.time() - t_start:.1f}s) — anos atualizados: {sorted(changed_years) or 'nenhum'}")
        except Exception as e:
            print(f"[build] AVISO: falha ao sincronizar ITBI da Prefeitura ({e!r}) — usando o cache local em data/itbi_raw/ (pode estar desatualizado; tenta de novo na próxima execução).")
            changed_years = set()

    year_to_path = {y: itbi_source.RAW_DIR / f"{y}.xlsx" for y in years}
    if not any(p.exists() for p in year_to_path.values()):
        raise SystemExit(
            "Nenhum .xlsx de ITBI em cache (data/itbi_raw/) e a sincronização com a "
            "Prefeitura falhou — não há nada pra processar. Rode de novo manualmente "
            "ou confira se o cache do workflow foi perdido."
        )
    # Item 1 do pedido de 2026-09-30: alarme cedo (antes do resto do
    # pipeline rodar) se alguma aba vier sem cabeçalho reconhecível ou com
    # as colunas lidas por posição deslocadas/renomeadas.
    validate_build.check_header_layout(year_to_path)

    # Item 1 da Etapa 2 (2026-10-01): resolução de bairro ÚNICA — a mesma
    # cascata de 5 métodos (tradução por nome de cadastro + voto de
    # endereço/quadra fiscal/CEP, com a divisão de Santo Amaro) usada por
    # carteira_77, aplicada aqui como a fonte de bairro de TODO o motor.
    # Substitui clean_itbi.resolve_bairros() (maioria por texto cru do
    # próprio ITBI, 49 bairros) — ver scripts/cascata_completa.
    # resolver_registros_engine() e validate_build.
    # check_consistencia_carteira_77 (trava o build se algum painel
    # divergir de carteira_77). Registros que não são revenda nem planta
    # aprovada (fração ideal/herança/divórcio, natureza != compra e
    # venda) não entram mais em nenhum painel — "a base é revenda/planta
    # separadas", não "qualquer transação residencial" como antes.
    import cascata_completa
    itbi_resolvido, targets_novos, resolucao_stats, periodo_12m_externo = cascata_completa.resolver_registros_engine()
    itbi_stats = {
        "total_rows_seen": resolucao_stats["total_rows_seen"],
        "total_rows_matched": resolucao_stats["revenda_todos_anos"] + resolucao_stats["planta_todos_anos"],
    }
    print(f"[build] ITBI resolvido (base nova, 77 bairros): {len(itbi_resolvido)} registros | {resolucao_stats}")

    # build_clean_layer AGORA (bairro já é um dos 77) — natureza, %
    # transmitido, tipo de imóvel, outlier de R$/m² por bairro+tipo+faixa
    # (agrupado corretamente pelos 77, não pelos 49 antigos). Log completo
    # vai pra site/itbi_clean_log.json, auditável fora do build.
    itbi_deduped = itbi_resolvido  # já deduplicado dentro de resolver_registros_engine()
    itbi_records, clean_stats = clean_itbi.build_clean_layer(itbi_deduped)

    clean_log = {
        "gerado_em": datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y UTC"),
        "camada_limpa_preco": clean_stats,
    }
    OUT_CLEAN_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_CLEAN_LOG.write_text(json.dumps(clean_log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build] {OUT_CLEAN_LOG} escrito")

    usn_records, usn_meta = _get_usn_records()
    print(f"[build] estoque: {len(usn_records)} anúncios válidos")

    search_interest, search_interest_meta = _get_search_interest()

    # Item 3 (2026-09-30) / Item 1 da Etapa 2 (2026-10-01): carteira de 77
    # bairros (tradução por nome de cadastro + cascata de 5 métodos, ver
    # scripts/cascata_completa.py) — calculada ANTES de engine.compute()
    # porque agora alimenta o motor (unidades_iptu/giro_12m_pct por
    # bairro, únicos nessa fonte — IPTU, não ITBI) e é a REFERÊNCIA pra
    # validate_build.check_consistencia_carteira_77 travar o build se
    # algum painel divergir. Erro aqui agora é fatal (não um try/except
    # isolado como antes de virar a base principal do motor).
    import cascata_completa
    carteira_77 = cascata_completa.gerar_dados_carteira_77()
    print(f"[build] carteira_77 calculada ({len(carteira_77['bairros'])} bairros)")

    result = engine.compute(itbi_records, usn_records, years, carteira_77["bairros"], periodo_12m_externo)
    print(f"[build] motor de cálculo concluído ({time.time() - t_start:.1f}s total)")

    _write_preco_m2_csv(result["preco_m2_painel"], OUT_PRECO_M2_CSV)
    print(f"[build] {OUT_PRECO_M2_CSV} escrito ({len(result['preco_m2_painel'])} linhas)")

    if search_interest:
        _attach_search_interest(result["bairros"], search_interest)

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y UTC"),
        **result,
    }
    data["carteira_77"] = carteira_77
    # Revisão 2026-10-01 (migração do Prontidão): global (um fetch só pra
    # todos os bairros) — ver _get_search_interest/keyword_client.
    data["search_interest_meta"] = search_interest_meta
    data["meta"]["total_itbi_rows_seen"] = itbi_stats["total_rows_seen"]
    data["meta"]["total_itbi_rows_matched"] = itbi_stats["total_rows_matched"]
    # Item 1 da Etapa 2 (2026-10-01): "bairro recuperado por maioria de
    # endereço" não existe mais (a resolução agora é a cascata de 5
    # métodos, não mais uma recuperação por maioria entre linhas do mesmo
    # endereço) — substituído pelos números que a base nova realmente
    # produz: revenda/planta (todos os anos, antes da janela de 12m) e
    # quantos ficaram de fora da carteira (fora_carteira ou incerto).
    data["meta"]["total_itbi_duplicates_removed"] = resolucao_stats["duplicatas_removidas"]
    data["meta"]["total_itbi_revenda_todos_anos"] = resolucao_stats["revenda_todos_anos"]
    data["meta"]["total_itbi_planta_todos_anos"] = resolucao_stats["planta_todos_anos"]
    data["meta"]["total_itbi_fora_carteira_ou_incerto"] = resolucao_stats["fora_carteira_ou_incerto"]
    data["meta"]["usn"] = usn_meta

    # Protocolo de segurança pedido pelo usuário em 2026-09-30 (dashboard vai
    # integrar no CRM e ser compartilhada com outros corretores — "não pode
    # quebrar em nenhum momento"): 3 checagens antes de sobrescrever o
    # data.json publicado. Levanta SystemExit e PARA aqui se qualquer uma
    # falhar — nem o CSV nem o raw.json chegam a ser escritos, o data.json
    # anterior fica intacto no disco/git.
    validate_build.validate_before_publish(year_to_path, itbi_stats, data, OUT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[build] {OUT} escrito ({OUT.stat().st_size:,} bytes)")

    raw = build_raw_payload(itbi_records, usn_records, years, periodo_12m_externo, carteira_77["bairros"])
    raw["search_interest"] = search_interest or {}
    raw["search_interest_meta"] = search_interest_meta
    OUT_RAW.write_text(json.dumps(raw, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[build] {OUT_RAW} escrito ({OUT_RAW.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
