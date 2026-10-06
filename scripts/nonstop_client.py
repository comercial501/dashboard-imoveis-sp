#!/usr/bin/env python3
"""
Cliente da API da nonStop (estoque atual de anúncios).

Docs: https://docs.usenonstop.com/versions/unstable/apis/property
Autenticação: header "Authorization: Bearer <token>" (NONSTOP_TOKEN).
Um token = uma conta — sempre devolve só os imóveis da conta dona do token.

Usa /unstable/imoveis/todos com paginação por cursor (seek, recomendada
pela doc para varrer o catálogo inteiro): perPage alto + sortBy=_id (a
paginação por cursor só funciona com a ordenação padrão por _id).

Filtra availableFor=VENDA, use=RESIDENCIAL, state=SP, city=São Paulo
direto na API — evita trazer aluguel/comercial/outras cidades que de
qualquer forma seriam descartados depois pela normalização de bairro
(mesmos filtros do export manual antigo, ver itbi_methodology_spec.md §1.2).

LIMITAÇÃO CONHECIDA (não existia no export manual em xlsx): o endpoint de
listagem devolve `CardProperty`, que NÃO inclui o campo `status` (PADRAO /
NOVO / REFORMA / LANCAMENTO / CONSTRUCAO) — só a ficha completa de um
imóvel (`/imoveis/{id}`) tem isso. Sem esse campo não dá pra saber, só pela
lista, se um anúncio é lançamento/construção (o que o Painel 7 usa pra
decidir "tem unidade à venda hoje"). Por ora todo imóvel vindo da API entra
como situacao_code=0 (PADRAO) — ou seja, o painel de Captação Ativa fica
levemente mais conservador (pode achar que um endereço já tem unidade
ativa quando na verdade é só uma unidade em lançamento). Ver README.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from clean_itbi import AREA_CAP_NONSTOP, TIPO_IMOVEL_NONSTOP
from normalize import address_key, bairro_canon

BASE_URL = "https://www.usenonstop.com/api"
API_VERSION = "unstable"
REQUEST_TIMEOUT = 60
PER_PAGE = 100


def _get(path, token, params):
    url = f"{BASE_URL}/{API_VERSION}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"nonStop API {e.code} em {path}: {body}") from e


def _fetch_page(token, available_for, current_page):
    params = {
        "availableFor": available_for,
        "perPage": PER_PAGE,
        "currentPage": current_page,
        "sortBy": "_id",
        "sortOrder": 1,
        "use": "RESIDENCIAL",
        "state": "SP",
        "city": "São Paulo",
    }
    return _get("/imoveis/todos", token, params)


def fetch_all_properties(token, available_for="VENDA"):
    """Varre o catálogo inteiro via paginação clássica por currentPage.

    A doc recomenda paginação por cursor (`nextCursor`) para scans
    completos, mas na prática essa conta devolve `nextCursor: null` mesmo
    havendo mais páginas (confirmado: `total` bate com o catálogo real,
    mas o cursor nunca avança) — por isso usamos currentPage, que funciona
    de forma confiável, comparando contra `total` (só vem na 1ª página)."""
    out = []
    page = 1
    total = None
    while True:
        data = _fetch_page(token, available_for, page)
        if total is None:
            total = data.get("total", 0)
        properties = data.get("properties", [])
        out.extend(properties)
        if not properties or len(out) >= total:
            break
        page += 1
        if page > 2000:  # cinto de segurança contra loop infinito por bug de API
            raise RuntimeError("mais de 2000 páginas na paginação da nonStop — algo está errado, abortando.")
    return out


def _situacao_code_from_card(card):
    # CardProperty não tem `status` — ver limitação no topo do arquivo.
    return 0


def card_to_record(card):
    """Converte um CardProperty da API pro formato interno esperado pelo
    engine.py (mesmo shape de parse_usenonstop_xlsx.card_to_record)."""
    address = card.get("address") or {}
    bairro = bairro_canon(address.get("area"))
    street = address.get("street")
    number = address.get("number")
    complement = address.get("complement")

    akey = address_key(street, number) if bairro else None
    adisp_building = f"{street}, {number}" if street and number else street
    adisp = f"{adisp_building} - {complement}" if (adisp_building and complement) else adisp_building

    values = card.get("values") or {}
    areas = card.get("areas") or {}
    geo = (address.get("geo") or {}).get("coordinates") or [None, None]
    lon, lat = (geo + [None, None])[:2]

    # Área privativa às vezes vem com erro de digitação grosseiro (achado
    # de 2026-09-29: um anúncio com "130000" — 130 mil m² — gerava R$/m²
    # de R$13 e um falso "99,8% de desconto" no Valor de Oportunidade).
    # Ver clean_itbi.AREA_CAP_NONSTOP.
    area_privativa = areas.get("private")
    if area_privativa is not None and area_privativa > AREA_CAP_NONSTOP:
        area_privativa = None

    # O campo `url` do CardProperty é só um slug descritivo (não resolve
    # sozinho — testado, dá 404). A página real do imóvel é
    # /imoveis/{user.slug}/{base36Id}, mesmo padrão da coluna "Link nonstop"
    # do export manual antigo.
    user_slug = (card.get("user") or {}).get("slug")
    base36 = card.get("base36Id")
    link = f"https://www.usenonstop.com/imoveis/{user_slug}/{base36}" if user_slug and base36 else None

    return {
        "bairro": bairro,
        "addr_key": akey,
        "addr_display": adisp,
        "addr_display_building": adisp_building,
        "complemento": complement,
        "valor": values.get("sale"),
        "area": area_privativa,
        "quartos": card.get("rooms"),
        "vagas": card.get("parkingLots"),
        "lat": lat,
        "lon": lon,
        "situacao_code": _situacao_code_from_card(card),
        "tipo_imovel": TIPO_IMOVEL_NONSTOP.get(card.get("type")),
        "codigo": card.get("base36Id"),
        "link": link,
        # Passo 3b (2026-10-01, achado da auditoria): a API já manda a data
        # de cadastro do anúncio — antes isso nunca era capturado. Usado
        # hoje só pra desempate na deduplicação (mantém o mais recente);
        # nenhum painel ainda filtra ou avisa por idade — isso é decisão
        # de mercado, fica pra depois.
        "created_at": card.get("createdAt"),
    }


DEDUP_TOLERANCIA_PRECO = 0.03  # +-3%


def deduplicar_registros(records, tolerancia_preco=DEDUP_TOLERANCIA_PRECO, log=print):
    """Passo 3b (2026-10-01), achado da auditoria: o mesmo imóvel às
    vezes aparece mais de uma vez no estoque (republicado, ou corretores
    diferentes anunciando a mesma unidade) — nenhum painel filtrava isso
    antes (só o export de conteúdo tinha essa regra). Mesmo endereço
    (addr_key) + mesma área útil + preço dentro de +-3% um do outro = 1
    anúncio só. Mantém o mais recente (created_at); sem created_at nos
    dois lados, mantém o primeiro encontrado (ordem estável). Registro
    sem addr_key (endereço não reconhecido) não entra em nenhum grupo —
    não dá pra confirmar que é duplicata de nada sem endereço.

    Chamado UMA VEZ em build_data.py, antes de passar usn_records pro
    motor (Python) e pro raw.json (JS recomputa os filtros em cima do
    MESMO conjunto já deduplicado — não precisa deduplicar de novo no
    cliente). Retorna (records_deduplicados, n_removidos)."""
    # Passo 3d (2026-10-05): o anúncio mantido é o MAIS RECENTE (preço e
    # dados atuais), mas a idade do imóvel é a data de cadastro MAIS
    # ANTIGA entre as duplicatas — republicar não "rejuvenesce" o imóvel.
    # `created_at_mais_antigo` carrega isso; usa o valor já existente se
    # houver, pra reaplicar a função sobre um conjunto já deduplicado
    # (check_dedup_aplicada) nunca perder a data original.
    def _cadastro(r):
        return r.get("created_at_mais_antigo") or r.get("created_at") or ""

    sem_endereco = [r for r in records if not r.get("addr_key")]
    por_endereco = {}
    for r in records:
        if r.get("addr_key"):
            por_endereco.setdefault(r["addr_key"], []).append(r)

    for r in sem_endereco:
        r["created_at_mais_antigo"] = _cadastro(r) or None
    dedupados = list(sem_endereco)
    n_removidos = 0
    for grupo in por_endereco.values():
        por_area = {}
        for r in grupo:
            por_area.setdefault(r.get("area"), []).append(r)
        for recs in por_area.values():
            usados = [False] * len(recs)
            for i, r in enumerate(recs):
                if usados[i]:
                    continue
                usados[i] = True
                cluster = [r]
                for j in range(i + 1, len(recs)):
                    if usados[j]:
                        continue
                    r2 = recs[j]
                    v1, v2 = r.get("valor"), r2.get("valor")
                    if v1 and v2 and abs(v2 - v1) <= tolerancia_preco * v1:
                        cluster.append(r2)
                        usados[j] = True
                representante = max(cluster, key=lambda x: x.get("created_at") or "")
                representante["created_at_mais_antigo"] = min((_cadastro(x) for x in cluster if _cadastro(x)), default=None)
                dedupados.append(representante)
                n_removidos += len(cluster) - 1
    if n_removidos:
        log(f"[nonstop] deduplicação: {len(records)} -> {len(dedupados)} anúncios únicos (removidos {n_removidos} republicados/duplicados)")
    return dedupados, n_removidos


def fetch_all_records(token, available_for="VENDA"):
    """Retorna (records, meta) já no formato interno, filtrado pra
    carteira de 77 bairros (bairro=None é descartado, igual ao export
    manual). NÃO deduplica aqui — ver deduplicar_registros(), chamada à
    parte em build_data.py (quem usa esta função isoladamente, como
    scripts de export, decide se quer deduplicar)."""
    cards = fetch_all_properties(token, available_for)
    rows_seen = len(cards)
    records = []
    for card in cards:
        rec = card_to_record(card)
        if rec["bairro"] is None:
            continue
        if rec["valor"] is None or rec["valor"] <= 0:
            continue
        records.append(rec)
    meta = {"fonte": "nonstop_api", "available_for": available_for, "rows_seen": rows_seen, "rows_matched": len(records)}
    return records, meta


if __name__ == "__main__":
    import sys

    token = os.environ.get("NONSTOP_TOKEN", "").strip()
    if not token:
        print("Defina NONSTOP_TOKEN no ambiente (ou .env) pra testar.", file=sys.stderr)
        sys.exit(1)
    records, meta = fetch_all_records(token)
    print(meta)
    by_bairro = {}
    for r in records:
        by_bairro[r["bairro"]] = by_bairro.get(r["bairro"], 0) + 1
    for b, n in sorted(by_bairro.items(), key=lambda x: -x[1])[:10]:
        print(f"  {b}: {n}")
