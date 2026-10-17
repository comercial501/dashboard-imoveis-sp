#!/usr/bin/env python3
"""Teste da deduplicação de anúncios da nonStop (nonstop_client.deduplicar_registros): idempotente de verdade (reaplicar não remove mais nada),
sem perder a data de cadastro mais antiga, e sem juntar anúncios de preço/área/endereço diferentes. Uso: python3 scripts/test_dedup_nonstop.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nonstop_client as nc

falhas = []


def ok(c, m):
    print(("OK     " if c else "FALHOU ") + m)
    if not c:
        falhas.append(m)


def mk(cod, valor, criado, area=50, addr="RUA X|1"):
    return {"addr_key": addr, "area": area, "valor": valor, "created_at": criado, "codigo": cod}


mudo = lambda *a, **k: None
# o caso que travou a atualização de 17/10/2026: 100, 103 e 106 mil (o mais recente do 1º grupo é o de 103; o de 106 ficava a 2,9% dele)
d1, n1 = nc.deduplicar_registros([mk("a", 100000, "2026-01-01"), mk("b", 103000, "2026-03-01"), mk("c", 106000, "2026-02-01")], log=mudo)
d2, n2 = nc.deduplicar_registros(d1, log=mudo)
ok(n2 == 0, "reaplicar a deduplicação num conjunto já deduplicado remove 0 (idempotente)")
ok(len(d1) == 1 and n1 == 2, f"100, 103 e 106 mil viram 1 anúncio só ({len(d1)} ficou, {n1} removidos)")
ok(d1[0]["codigo"] == "b", "fica o anúncio mais recente (103 mil, criado em 03/2026)")
ok(d1[0]["created_at_mais_antigo"] == "2026-01-01", "a data de cadastro mais antiga do grupo é preservada (republicar não rejuvenesce)")
# o que NÃO pode juntar
base = [mk("a", 100000, "2026-01-01"), mk("b", 110000, "2026-01-02"), mk("c", 100000, "2026-01-03", area=60), mk("d", 100000, "2026-01-04", addr="RUA Y|2"),
        {"addr_key": None, "area": 50, "valor": 100000, "created_at": "2026-01-05", "codigo": "e"}]
d, n = nc.deduplicar_registros([dict(r) for r in base], log=mudo)
ok(n == 0 and len(d) == 5, "preço 10% diferente, área diferente, endereço diferente e sem endereço NÃO se juntam")
# cadeia longa: 100, 102, 104, 106, 108 mil — termina e o resultado é estável
cad = [mk(str(i), 100000 + 2000 * i, f"2026-02-{i + 1:02d}") for i in range(5)]
d1, n1 = nc.deduplicar_registros(cad, log=mudo)
d2, n2 = nc.deduplicar_registros(d1, log=mudo)
ok(n2 == 0 and len(d1) >= 1, f"cadeia de preços: termina e é estável ({len(cad)} -> {len(d1)})")
print("\nRESULTADO:", "OK" if not falhas else f"{len(falhas)} FALHA(S)")
sys.exit(1 if falhas else 0)
