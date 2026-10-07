#!/usr/bin/env python3
"""
Diagnóstico (Rodada C, item 1a) da forma de pagamento no ITBI: valores distintos de
"Tipo de Financiamento" (col. O), como aparece a compra SEM financiamento, e a coluna
"Valor Financiado" (col. P) — nas REVENDAS LIMPAS dos últimos 12 meses (mesma janela e mesma
camada limpa do dashboard). Uso MANUAL (leva uns 3 min): python3 scripts/diagnostico_financiamento.py
"""
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cascata_completa
import clean_itbi
import engine
from normalize import excel_serial_to_ym


def carregar():
    registros, _targets, _stats, periodo = cascata_completa.resolver_registros_engine()
    itbi, _ = clean_itbi.build_clean_layer(registros)
    return itbi, set(periodo[0])


def main():
    itbi, janela = carregar()
    rev = [r for r in itbi if engine._is_revenda_limpa(r) and r["day"] is not None and excel_serial_to_ym(r["day"]) in janela]
    pla = [r for r in itbi if r.get("is_planta") and r["day"] is not None and excel_serial_to_ym(r["day"]) in janela]
    print(f"revendas limpas nos últimos 12 meses: {len(rev)} | plantas (12m): {len(pla)}")
    for nome, grupo in (("REVENDA LIMPA", rev), ("PLANTA", pla)):
        print(f"\n=== {nome}: valores distintos de 'Tipo de Financiamento' ===")
        c = collections.Counter(repr(r.get("tipo_financiamento")) for r in grupo)
        for k, n in c.most_common():
            print(f"  {k:60s} {n:7d}  ({100 * n / len(grupo):.1f}%)")
        vf0 = [r for r in grupo if r.get("valor_financiado") is None]
        print(f"  valor_financiado ausente/ilegível: {len(vf0)}")
        sem_tipo = [r for r in grupo if not r.get("tipo_financiamento")]
        sem_tipo_com_valor = [r for r in sem_tipo if (r.get("valor_financiado") or 0) > 0]
        com_tipo = [r for r in grupo if r.get("tipo_financiamento")]
        com_tipo_zero = [r for r in com_tipo if not (r.get("valor_financiado") or 0) > 0]
        acima_venda = [r for r in com_tipo if (r.get("valor_financiado") or 0) > r["valor"]]
        acima_base = [r for r in com_tipo if r.get("base_calculo") and (r.get("valor_financiado") or 0) > r["base_calculo"]]
        print(f"  SEM tipo de financiamento: {len(sem_tipo)} | desses, com 'Valor Financiado' > 0: {len(sem_tipo_com_valor)}")
        print(f"  COM tipo de financiamento: {len(com_tipo)} | desses, com 'Valor Financiado' vazio ou 0: {len(com_tipo_zero)}")
        print(f"  COM tipo e valor financiado > valor da venda declarado: {len(acima_venda)} | > base de cálculo: {len(acima_base)}")
        pcts = sorted(r["valor_financiado"] / r["valor"] for r in com_tipo if (r.get("valor_financiado") or 0) > 0)
        if pcts:
            q = lambda p: pcts[int(p * (len(pcts) - 1))]
            print(f"  % financiado sobre o valor (só com tipo e valor > 0, n={len(pcts)}): P5={q(.05):.2f} P25={q(.25):.2f} mediana={q(.5):.2f} P75={q(.75):.2f} P95={q(.95):.2f} máx={pcts[-1]:.2f}")
        ex = sorted(com_tipo_zero, key=lambda r: r["valor"])[:3] + sorted(acima_venda, key=lambda r: -(r["valor_financiado"] / r["valor"]))[:3]
        for r in ex:
            print(f"    ex.: {r.get('addr_display')} | valor {r['valor']:,.0f} | tipo {r.get('tipo_financiamento')!r} | financiado {r.get('valor_financiado')}")


if __name__ == "__main__":
    main()
