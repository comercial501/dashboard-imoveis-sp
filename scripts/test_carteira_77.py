#!/usr/bin/env python3
"""
Validação do campo `carteira_77` em site/data.json e da consistência com
`bairros` (item 3 de 2026-09-30 + item 1 da Etapa 2 de 2026-10-01 — desde
a migração do motor pra base nova, `bairros` também tem 77 entradas e
bate exato com `carteira_77`) — não é um framework de testes (o projeto
não tem um; ver README "engine.js é... validado campo a campo"), é um
script de conferência, no mesmo espírito do resto da auditoria: roda
depois de `python3 scripts/build_data.py` e falha alto (AssertionError)
se o formato ou os números não baterem com o esperado.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_JSON = ROOT / "site" / "data.json"


def main():
    data = json.loads(DATA_JSON.read_text(encoding="utf-8"))

    assert "bairros" in data and len(data["bairros"]) == 77, (
        f"esperava 77 bairros em `bairros` (item 1 da Etapa 2 migrou o motor pra base nova), achei {len(data.get('bairros', {}))}"
    )

    assert "carteira_77" in data, "data.json sem o campo carteira_77 — build_data.py rodou sem a etapa nova?"
    c77 = data["carteira_77"]

    for chave in ("metodologia_versao", "periodo_12m", "bairros", "fechamento"):
        assert chave in c77, f"carteira_77 sem a chave '{chave}'"

    bairros = c77["bairros"]
    assert len(bairros) == 77, f"esperava 77 bairros em carteira_77.bairros, achei {len(bairros)}"

    for b, v in bairros.items():
        for campo in ("revenda_12m", "planta_12m", "unidades_iptu", "giro_12m_pct"):
            assert campo in v, f"bairro '{b}' sem o campo '{campo}'"
        assert v["revenda_12m"] >= 0 and v["planta_12m"] >= 0 and v["unidades_iptu"] >= 0, f"bairro '{b}' com contagem negativa"
        # Item 1.1 da Etapa 2: mesma checagem de validate_build.
        # check_consistencia_carteira_77, rodável fora do build também.
        motor = data["bairros"].get(b)
        assert motor is not None, f"bairro '{b}' existe em carteira_77 mas não em bairros_out"
        for campo in ("revenda_12m", "planta_12m", "unidades_iptu", "giro_12m_pct"):
            assert motor[campo] == v[campo], f"{b}.{campo}: bairros_out={motor[campo]!r} != carteira_77={v[campo]!r}"
        if v["giro_12m_pct"] is not None:
            assert v["giro_12m_pct"] >= 0, f"bairro '{b}' com giro negativo"
            assert v["unidades_iptu"] > 0, f"bairro '{b}' tem giro mas 0 unidades IPTU — inconsistente"
        else:
            assert v["unidades_iptu"] == 0, f"bairro '{b}' tem unidades IPTU mas giro None — inconsistente"

    soma_revenda = sum(v["revenda_12m"] for v in bairros.values())
    soma_planta = sum(v["planta_12m"] for v in bairros.values())
    soma_unidades = sum(v["unidades_iptu"] for v in bairros.values())
    print(f"[test_carteira_77] soma revenda_12m={soma_revenda} planta_12m={soma_planta} unidades_iptu={soma_unidades}")

    fech = c77["fechamento"]
    for universo in ("revenda", "planta", "unidades"):
        assert universo in fech, f"fechamento sem '{universo}'"
        f = fech[universo]
        soma_pct = f["carteira_pct"] + f["fora_pct"] + f["incerto_pct"]
        assert abs(soma_pct - 100.0) < 0.5, f"fechamento '{universo}': carteira+fora+incerto = {soma_pct:.1f}%, deveria ser ~100%"
        print(f"[test_carteira_77] {universo}: total={f['total']} carteira={f['carteira_pct']}% fora={f['fora_pct']}% incerto={f['incerto_pct']}%")

    # Meta do usuário (2026-09-30): incerto de planta ~3%, revenda não
    # deveria regredir acima disso (tinha um bug de AUTO_IGNORAR corrigido
    # nesta mesma rodada).
    for universo in ("revenda", "planta"):
        incerto_pct = fech[universo]["incerto_pct"]
        if incerto_pct > 5.0:
            print(f"[test_carteira_77] AVISO: incerto de {universo} em {incerto_pct}%, acima da meta de ~3%")

    print("[test_carteira_77] OK — todas as checagens passaram.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"[test_carteira_77] FALHOU: {e}", file=sys.stderr)
        sys.exit(1)
