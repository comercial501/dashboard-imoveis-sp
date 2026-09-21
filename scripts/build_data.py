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
from parse_itbi import parse_itbi_years

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data.json"
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


if __name__ == "__main__":
    main()
