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


def build_raw_payload(itbi_records, usn_records, years):
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
            "min_anuncios_alerta": engine.MIN_ANUNCIOS_ALERTA,
            "janela_preco_m2_dias": engine.JANELA_PRECO_M2_DIAS,
            # Congelado no momento do build — o recompute no navegador (ao
            # aplicar um filtro) usa esse valor, não a data real do
            # visitante, pra bater exatamente com data.json quando nenhum
            # filtro está ativo (mesma janela "últimos 12 meses" nos dois).
            "hoje_serial": today_excel_serial(),
        },
    }


def _get_search_interest():
    """Interesse de busca no Google por bairro (opcional — ver
    keyword_client.py). Sinal PROSPECTIVO de demanda (gente pesquisando
    hoje), complementar à liquidez do ITBI (retrospectiva). Classificação
    Alto/Médio/Baixo é sempre por tercil contra os 47 bairros inteiros —
    de propósito não recalcula por filtro de bairro/preço na tela (com um
    filtro reduzindo pra poucos bairros, tercil perderia sentido), então
    "Alto" sempre quer dizer "alto pra São Paulo inteira", uma referência
    estável."""
    import keyword_client

    data = keyword_client.get_search_interest_cached(TARGETS)
    if not data:
        return None

    values = sorted(v["avg_monthly_searches"] for v in data.values())
    n = len(values)
    low_cut = values[n // 3]
    high_cut = values[(2 * n) // 3]

    for b, v in data.items():
        s = v["avg_monthly_searches"]
        v["nivel"] = "alto" if s > high_cut else ("baixo" if s <= low_cut else "medio")
    return data


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
        "n_transacoes_12m", "n_anuncios", "amostra_pequena",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in preco_m2_painel:
            w.writerow([
                p["bairro"], p["faixa"], p["mediana_pago_m2"], p["mediana_pedido_m2"], p["gap_pct"],
                p["n_transacoes_12m"], p["n_anuncios"], "sim" if p["amostra_pequena"] else "nao",
            ])


def main():
    _load_dotenv()
    t_start = time.time()

    current_year = datetime.now().year
    years = [current_year - 2, current_year - 1, current_year]

    print(f"[build] anos: {years}")
    if os.environ.get("SKIP_ITBI_SYNC", "").strip() == "1":
        # Base congelada pra auditoria (pedido do usuário em 2026-09-30):
        # nenhum relatório antes×depois desta correção pode comparar contra
        # planilhas diferentes no meio do caminho. Usa só o que já está em
        # data/itbi_raw/ (a aba AGO-2026 chegou durante o item 4 e vira a
        # base congelada a partir daqui) — nunca setado pelo cron; só ligado
        # manualmente nesta branch até o merge, quando a sincronização
        # automática diária volta a valer.
        print("[build] SKIP_ITBI_SYNC=1 — base congelada da auditoria, sem checar planilha nova na Prefeitura")
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

    itbi_raw_records, itbi_stats = parse_itbi_years(year_to_path)
    print(f"[build] ITBI parseado: {itbi_stats}")

    # Camada de dados limpa (Etapa 2 da auditoria de 2026-09-29, ver
    # clean_itbi.py e README): bairro resolvido por maioria + deduplicação
    # por SQL (volume/liquidez usam esse conjunto) e, por cima dele, os
    # filtros de PREÇO (natureza, % transmitido, tipo de imóvel, outlier de
    # R$/m² por bairro+tipo+faixa de metragem — usado por todo painel de
    # preço). Log completo de quanto saiu em cada etapa vai pra
    # data/itbi_clean_log.json, auditável fora do build.
    itbi_resolved, resolve_stats = clean_itbi.resolve_bairros(itbi_raw_records)
    itbi_deduped, dedup_stats = clean_itbi.dedup_by_sql(itbi_resolved)
    itbi_records, clean_stats = clean_itbi.build_clean_layer(itbi_deduped)

    clean_log = {
        "gerado_em": datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y UTC"),
        "resolucao_bairro": resolve_stats,
        "deduplicacao_sql": dedup_stats,
        "camada_limpa_preco": clean_stats,
    }
    OUT_CLEAN_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_CLEAN_LOG.write_text(json.dumps(clean_log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build] {OUT_CLEAN_LOG} escrito")

    usn_records, usn_meta = _get_usn_records()
    print(f"[build] estoque: {len(usn_records)} anúncios válidos")

    search_interest = _get_search_interest()

    result = engine.compute(itbi_records, usn_records, years)
    print(f"[build] motor de cálculo concluído ({time.time() - t_start:.1f}s total)")

    _write_preco_m2_csv(result["preco_m2_painel"], OUT_PRECO_M2_CSV)
    print(f"[build] {OUT_PRECO_M2_CSV} escrito ({len(result['preco_m2_painel'])} linhas)")

    if search_interest:
        _attach_search_interest(result["bairros"], search_interest)

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y UTC"),
        **result,
    }
    data["meta"]["total_itbi_rows_seen"] = itbi_stats["total_rows_seen"]
    data["meta"]["total_itbi_rows_matched"] = itbi_stats["total_rows_matched"]
    data["meta"]["total_itbi_duplicates_removed"] = dedup_stats["duplicatas_removidas"]
    data["meta"]["total_itbi_bairro_recuperados"] = resolve_stats["recuperados_por_maioria_do_endereco"]
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

    raw = build_raw_payload(itbi_records, usn_records, years)
    raw["search_interest"] = search_interest or {}
    OUT_RAW.write_text(json.dumps(raw, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[build] {OUT_RAW} escrito ({OUT_RAW.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
