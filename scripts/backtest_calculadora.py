#!/usr/bin/env python3
"""Teste de precisão da calculadora (uso LOCAL): tira uma venda real do cálculo, estima o preço dela só com as
outras e compara com o que foi pago (os dois já no preço do último mês completo). Três situações:
  prédio  — a venda sai, o resto do prédio fica;
  rua     — o PRÉDIO inteiro sai (simula endereço sem vendas), a rua fica;
  bairro  — o prédio e a rua saem, só o bairro fica.
Mostra erro mediano, erro típico (P75) e quantas vezes o preço pago caiu dentro da FAIXA PROVÁVEL (a meta é ~75%; a
faixa é calibrada em outra amostra, espaçada, no próprio build — aqui a amostra é sorteada, então é uma conferência de
verdade). Usa o calculadora.json atual.
Uso: python3 scripts/backtest_calculadora.py [--n 3000] [--seed 11]"""
import argparse
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calculadora_preco as cp

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    d = json.loads((ROOT / "site" / "calculadora.json").read_text(encoding="utf-8"))
    idx = cp.indexar(d)
    V, P = d["vendas"], d["predios"]
    rnd = random.Random(a.seed)
    amostra = rnd.sample(range(len(V)), min(a.n, len(V)))
    res = {}
    for modo in ("predio", "rua", "bairro"):
        linhas = []
        for i in amostra:
            v = V[i]
            pi = v[0]
            predio_ids = set(idx["predio"][pi])
            ex = {i} if modo == "predio" else predio_ids
            rua = P[pi][3]
            bairro = P[pi][2]
            sub = {
                "predio": {pi: [j for j in idx["predio"][pi] if j not in ex]},
                "rua": {rua: [j for j in idx["rua"][rua] if j not in ex]},
                "bairro": {bairro: [j for j in idx["bairro"][bairro] if j not in ex]},
            }
            if modo == "bairro":
                sub["rua"] = {rua: []}
            ent = {"predio": pi if modo == "predio" else None, "rua": rua if modo != "bairro" else None, "bairro": bairro,
                   "area": v[3], "andar": v[4], "preco_pedido": None}
            r = cp.estimar(d, sub, ent)
            if not r["ok"] or not r["nivel"].startswith(modo):
                continue
            real = v[2] * v[6]
            if r["nivel"] == "predio_poucas":
                res.setdefault("predio_poucas", []).append((abs(r["estimativa"] - real) / real, r["minimo"] <= real <= r["maximo"], r["confianca"], (r["estimativa"] - real) / real, r["n"]))
                continue
            linhas.append((abs(r["estimativa"] - real) / real, r["minimo"] <= real <= r["maximo"], r["confianca"], (r["estimativa"] - real) / real, r["n"]))
        res[modo] = linhas

    def resumo(ls):
        if not ls:
            return None
        e = sorted(x[0] for x in ls)
        return {"vendas_testadas": len(ls), "erro_mediano_pct": round(100 * statistics.median(e), 1), "erro_p75_pct": round(100 * e[3 * len(e) // 4], 1),
                "dentro_da_faixa_provavel_pct": round(100 * sum(1 for x in ls if x[1]) / len(ls), 1), "vies_mediano_pct": round(100 * statistics.median(x[3] for x in ls), 1)}
    out = {}
    for modo, ls in res.items():
        out[modo] = {"todas": resumo(ls)}
        for conf in ("alta", "media", "baixa"):
            r = resumo([x for x in ls if x[2] == conf])
            if r:
                out[modo][conf] = r
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
