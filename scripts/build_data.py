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
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine
import itbi_source
from normalize import TARGETS
from parse_itbi import parse_itbi_years

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data.json"
OUT_RAW = ROOT / "site" / "raw.json"
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
        ])

    usn_out = []
    for r in usn_records:
        # Prefere a grafia natural do endereço vinda da nonStop, igual ao
        # comportamento original (addr_upgrade_display).
        aidx = intern_addr(r["addr_key"], r["addr_display"], prefer=True)
        usn_out.append([
            bairro_idx[r["bairro"]], aidx, r["addr_display"], r["valor"], r["area"],
            r["quartos"], r["vagas"], r["lat"], r["lon"], r["situacao_code"], r["codigo"], r["link"],
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
        },
    }


def main():
    _load_dotenv()
    t_start = time.time()

    current_year = datetime.now().year
    years = [current_year - 2, current_year - 1, current_year]

    print(f"[build] anos: {years}")
    changed_years = itbi_source.sync(years)
    print(f"[build] ITBI sincronizado ({time.time() - t_start:.1f}s) — anos atualizados: {sorted(changed_years) or 'nenhum'}")

    year_to_path = {y: itbi_source.RAW_DIR / f"{y}.xlsx" for y in years}
    itbi_records, itbi_stats = parse_itbi_years(year_to_path)
    print(f"[build] ITBI parseado: {itbi_stats}")

    usn_records, usn_meta = _get_usn_records()
    print(f"[build] estoque: {len(usn_records)} anúncios válidos")

    result = engine.compute(itbi_records, usn_records, years)
    print(f"[build] motor de cálculo concluído ({time.time() - t_start:.1f}s total)")

    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S %Y UTC"),
        **result,
    }
    data["meta"]["total_itbi_rows_seen"] = itbi_stats["total_rows_seen"]
    data["meta"]["total_itbi_rows_matched"] = itbi_stats["total_rows_matched"]
    data["meta"]["usn"] = usn_meta

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[build] {OUT} escrito ({OUT.stat().st_size:,} bytes)")

    raw = build_raw_payload(itbi_records, usn_records, years)
    OUT_RAW.write_text(json.dumps(raw, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[build] {OUT_RAW} escrito ({OUT_RAW.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
