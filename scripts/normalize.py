#!/usr/bin/env python3
"""
Normalização de bairro/endereço + estatísticas auxiliares.

Porta 1:1 de build_data.pl (Perl) — ver itbi_methodology_spec.md §2, §3, §5
para a especificação completa com número de linha do original. Qualquer
mudança de fórmula/limiar aqui precisa ser espelhada na documentação (e,
quando o front-end voltar a recalcular no navegador, no JS também).
"""
import math
import re
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# §2 — Normalização de bairro
# ---------------------------------------------------------------------------

ACCENTS = {
    "Á": "A", "À": "A", "Ã": "A", "Â": "A", "Ä": "A",
    "É": "E", "È": "E", "Ê": "E", "Ë": "E",
    "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
    "Ó": "O", "Ò": "O", "Õ": "O", "Ô": "O", "Ö": "O",
    "Ú": "U", "Ù": "U", "Û": "U", "Ü": "U",
    "Ç": "C", "Ñ": "N",
}

# Os 49 bairros-alvo da carteira (47 originais de build_data.pl @TARGETS +
# Jardim América/Jardim Paulistano, adicionados em 2026-09-24 a pedido do
# usuário). Único lugar onde essa lista existe — não há config externa.
TARGETS = [
    "Vila Madalena", "Lapa", "Pinheiros", "Itaim Bibi", "Vila Olímpia", "Brooklin",
    "Chácara Santo Antônio", "Alto da Boa Vista", "Jardim dos Estados", "Jardim Petrópolis",
    "Vila Cordeiro", "Jardim Caravelas", "Jardim Santo Amaro", "Campo Belo", "Indianópolis",
    "Jardim Novo Mundo", "Moema", "Vila Uberabinha", "Vila Nova Conceição", "Jardim Europa",
    "Jardins", "Jardim Paulista", "Ibirapuera", "Jardim das Bandeiras", "Sumaré", "Pacaembu",
    "Higienópolis", "Perdizes", "Pompéia", "Santa Cecília", "Consolação", "Bela Vista",
    "Paraíso", "Planalto Paulista", "Mirandópolis", "Chácara Inglesa", "Bosque da Saúde",
    "Vila Mariana", "Jardim Vila Mariana", "Vila Gumercindo", "Vila Firmiano Pinto",
    "Jardim da Glória", "Cambuci", "Vila da Saúde", "Ipiranga", "Mooca", "Tatuapé",
    "Jardim América", "Jardim Paulistano",
]
assert len(TARGETS) == 49, f"esperava 49 bairros-alvo, achei {len(TARGETS)}"

ALIASES = {
    "BROOKLIN PAULISTA": "BROOKLIN",
    "BROOKLIN NOVO": "BROOKLIN",
    "VILA POMPEIA": "POMPEIA",
    "JD AMERICA": "JARDIM AMERICA",
    "JD PAULISTANO": "JARDIM PAULISTANO",
}

_PAREN_RE = re.compile(r"\([^)]*\)")
_QUOTE_RE = re.compile(r'"[^"]*"')
_NON_ALNUM_SPACE_RE = re.compile(r"[^A-Z0-9\s]")
_MULTI_SPACE_RE = re.compile(r"\s+")


def _apply_accents(s):
    for k, v in ACCENTS.items():
        s = s.replace(k, v)
    return s


def normalize_bairro(s):
    """Uppercase -> remove (parênteses) -> remove "aspas" -> remove acento
    -> remove não-alfanumérico -> colapsa espaço -> trim. Ordem importa."""
    if s is None:
        return ""
    s = s.upper()
    s = _PAREN_RE.sub("", s)
    s = _QUOTE_RE.sub("", s)
    s = _apply_accents(s)
    s = _NON_ALNUM_SPACE_RE.sub("", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


_CANON_BY_NORM = {normalize_bairro(t): t for t in TARGETS}


def bairro_canon(raw):
    """Retorna o nome canônico (com acento/caixa original) de TARGETS, ou
    None se o bairro (após normalizar + aplicar alias) não estiver na
    carteira de 49 bairros."""
    n = normalize_bairro(raw)
    if not n:
        return None
    n = ALIASES.get(n, n)
    return _CANON_BY_NORM.get(n)


# ---------------------------------------------------------------------------
# §3 — Normalização de endereço (join ITBI x Usenonstop)
# ---------------------------------------------------------------------------

STREET_ABBR = {
    "R": "RUA", "AV": "AVENIDA", "AL": "ALAMEDA", "PC": "PRACA", "PCA": "PRACA",
    "ES": "ESTRADA", "EST": "ESTRADA", "TV": "TRAVESSA", "VD": "VIADUTO",
    "LG": "LARGO", "PQ": "PARQUE", "PRQ": "PARQUE", "ROD": "RODOVIA", "RV": "RODOVIA",
}


def normalize_street(s):
    if s is None:
        return ""
    s = s.upper()
    s = _apply_accents(s)
    s = _NON_ALNUM_SPACE_RE.sub("", s)
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    tokens = s.split(" ") if s else []
    if tokens and tokens[0] in STREET_ABBR:
        tokens[0] = STREET_ABBR[tokens[0]]
    return " ".join(tokens)


_TRAILING_ZERO_RE = re.compile(r"\.0+$")
_LEADING_ZERO_RE = re.compile(r"^0+(?=\d)")


def normalize_number(s):
    if s is None:
        return ""
    s = str(s)
    s = _TRAILING_ZERO_RE.sub("", s)
    s = s.strip()
    s = _LEADING_ZERO_RE.sub("", s)
    return s


def address_key(street, number):
    """Chave de endereço = SÓ rua+número, sem bairro (auditoria de
    2026-09-23: a coluna "Bairro" do ITBI é preenchida por transação, não é
    um dado fixo do prédio — o mesmo edifício aparece com bairros diferentes
    em vendas diferentes em ~6% dos endereços da carteira, quase sempre
    entre bairros vizinhos, ex: Alameda Franca 107 tinha 2 vendas em
    "Jardins" e 2 em "Jardim Paulista", partindo o histórico do MESMO
    prédio em dois endereços incompletos. Retorna None se rua OU número
    normalizados ficarem vazios."""
    s = normalize_street(street)
    n = normalize_number(number)
    if not s or not n:
        return None
    return f"{s}|{n}"


def display_street(street):
    """Title-case só pra exibição (não reacentua — a normalização já removeu acento)."""
    norm = normalize_street(street)
    return " ".join(tok.capitalize() for tok in norm.split(" ") if tok)


# ---------------------------------------------------------------------------
# §5 — Estatísticas auxiliares
# ---------------------------------------------------------------------------


def mean(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def median(values):
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2


def percentile(p, values):
    """Interpolação linear pela posição idx = p/100 * (n-1). p=0 -> mínimo,
    p=100 -> máximo (não é o percentil "puro" estatístico, é min/max com
    interpolação — mesmo comportamento do Perl original)."""
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return None
    if n == 1:
        return vals[0]
    idx = (p / 100) * (n - 1)
    lo = math.floor(idx)
    frac = idx - lo
    hi = min(lo + 1, n - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * frac


def trim_outliers_iqr(values, k=1.5):
    """Remove outliers pelas cercas de Tukey: fora de [Q1-k*IQR, Q3+k*IQR].
    Método padrão, adaptado automaticamente à escala de cada bairro (não
    exige um limiar absoluto fixo, que não funcionaria igual pra 49 bairros
    com faixas de preço tão diferentes). Com menos de 4 valores, Q1/Q3 não
    são informativos o bastante — devolve a lista original sem filtrar."""
    vals = [v for v in values if v is not None]
    if len(vals) < 4:
        return vals
    q1, q3 = percentile(25, vals), percentile(75, vals)
    iqr = q3 - q1
    if iqr == 0:
        return vals
    lo, hi = q1 - k * iqr, q3 + k * iqr
    filtered = [v for v in vals if lo <= v <= hi]
    return filtered if filtered else vals


def mode_of(values):
    """Moda com desempate determinístico: valor numericamente menor vence
    (replica `sort { $c{$b} <=> $c{$a} || $a <=> $b }` do Perl — não confiar
    em ordem de iteração "por acaso")."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return best[0]


def zscore_map(d):
    """d: dict[key -> valor ou None]. Retorna dict[key -> zscore]. Requer
    >=2 valores não-nulos (senão zscore=0 pra todos). Desvio populacional
    (não amostral). Valor ausente (None) recebe zscore fixo -2 (tratado
    como "baixo", nunca ignorado silenciosamente)."""
    present = [v for v in d.values() if v is not None]
    if len(present) < 2:
        return {k: 0.0 for k in d}
    m = sum(present) / len(present)
    var = sum((x - m) ** 2 for x in present) / len(present)
    sd = math.sqrt(var)
    if sd == 0:
        sd = 1.0
    out = {}
    for k, v in d.items():
        out[k] = -2.0 if v is None else (v - m) / sd
    return out


def normalize_0_100(raw):
    """raw: dict[key -> valor ou None]. z-score -> min-max rescale linear
    pra faixa 0-100, usando o mínimo/máximo dos PRÓPRIOS z-scores."""
    z = zscore_map(raw)
    zvals = list(z.values())
    zmin = percentile(0, zvals)
    zmax = percentile(100, zvals)
    zrange = (zmax - zmin) if (zmax is not None and zmin is not None and zmax != zmin) else 1
    return {k: (zv - zmin) / zrange * 100 for k, zv in z.items()}


_EXCEL_EPOCH = date(1899, 12, 30)


def excel_serial_to_ym(serial):
    """Converte data serial do Excel (sistema 1900, época 1899-12-30 —
    absorve o bug clássico do "ano bissexto fantasma" de 1900) para (ano, mês)."""
    d = _EXCEL_EPOCH + timedelta(days=int(serial))
    return d.year, d.month


def coord_is_valid_sp(lat, lon):
    """Bounding box grosseiro da Grande São Paulo."""
    if lat is None or lon is None:
        return False
    return -24.2 <= lat <= -23.0 and -47.0 <= lon <= -46.2


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    rad = 3.14159265358979 / 180
    dlat = (lat2 - lat1) * rad
    dlon = (lon2 - lon1) * rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


NEIGHBOR_MAX_KM = 3
NEIGHBOR_COUNT = 3


def nearest_neighbors(bairro, centroids, targets, max_km=NEIGHBOR_MAX_KM, count=NEIGHBOR_COUNT):
    """centroids: dict[bairro -> (lat, lon) ou None]. targets: iterável dos
    49 bairros (sempre a lista completa, mesmo com filtro de UI ativo — ver
    itbi_methodology_spec.md §6.8). Retorna lista [(bairro, distancia_km), ...]
    ordenada por distância crescente, no máximo `count` itens."""
    c0 = centroids.get(bairro)
    if not c0:
        return []
    dists = []
    for other in targets:
        if other == bairro:
            continue
        c1 = centroids.get(other)
        if not c1:
            continue
        d = haversine_km(c0[0], c0[1], c1[0], c1[1])
        if d <= max_km:
            dists.append((other, d))
    dists.sort(key=lambda x: x[1])
    return dists[:count]


MAX_PER_EXACT_AREA = 5


def dedup_cap_exact_area(pairs):
    """pairs: lista de dict com chave 'area'. No máximo MAX_PER_EXACT_AREA
    ocorrências por valor exato de área (arredondado a 2 casas), na ordem
    em que aparecem."""
    seen = {}
    out = []
    for p in pairs:
        key = round(p["area"], 2)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= MAX_PER_EXACT_AREA:
            out.append(p)
    return out


AREA_BUCKET_WIDTH = 20


def mode_bucket_from_pairs(raw_pairs, width=AREA_BUCKET_WIDTH):
    """Retorna (lo, hi, valores_no_bucket_vencedor). hi é exclusivo.
    Desempate: bucket de índice numérico menor vence."""
    pairs = dedup_cap_exact_area(raw_pairs)
    if not pairs:
        return None, None, []
    counts = {}
    for p in pairs:
        b = int(p["area"] // width)
        counts[b] = counts.get(b, 0) + 1
    best_b = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    lo, hi = best_b * width, (best_b + 1) * width
    valores = [p["valor"] for p in pairs if lo <= p["area"] < hi]
    return lo, hi, valores
