#!/usr/bin/env python3
"""
Interesse de busca no Google (Keyword Planner) por bairro — sinal de
demanda PROSPECTIVA de comprador, complementar à liquidez de vendas do
ITBI (que é só retrospectiva — vendas já fechadas).

Usa GenerateKeywordHistoricalMetrics (não GenerateKeywordIdeas): esse método
devolve métricas para EXATAMENTE as palavras-chave pedidas — sem expandir
pra ideias relacionadas — o que é o que queremos aqui (comparar os 47
bairros pelo mesmo critério, não descobrir novos termos).

Requer GOOGLE_ADS_CLIENT_ID / GOOGLE_ADS_CLIENT_SECRET / GOOGLE_ADS_REFRESH_TOKEN
/ GOOGLE_ADS_LOGIN_CUSTOMER_ID no ambiente (.env local ou Secret do GitHub).
Sem isso definido, build_data.py pula esse sinal inteiro (dashboard funciona
normalmente sem ele — é um selo informativo a mais, não uma dependência).

Cadência: o próprio Google só atualiza o volume de busca mensalmente (é uma
média móvel de 12 meses, recalculada uma vez por mês) — não faz sentido
chamar a API todo dia. build_data.py só rechama se o cache local
(data/keyword_state.json) tiver mais de 25 dias.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "keyword_state.json"
CACHE_MAX_AGE_DAYS = 25

# Templates de busca por bairro — cobre as três formas mais comuns de
# alguém pesquisar intenção de compra num bairro específico.
KEYWORD_TEMPLATES = [
    "apartamento à venda {bairro}",
    "apartamento {bairro}",
    "imóveis {bairro}",
]

GEO_LOCATION_NAME = "São Paulo"
LANGUAGE_CODE = "pt"


def _client_config():
    return {
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
        "use_proto_plus": True,
    }


def credentials_available():
    return all(
        os.environ.get(k, "").strip()
        for k in ("GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN", "GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    )


def _resolve_geo_target(client, customer_id, location_name):
    service = client.get_service("GeoTargetConstantService")
    request = client.get_type("SuggestGeoTargetConstantsRequest")
    request.locale = "pt-BR"
    request.country_code = "BR"
    request.location_names.names.append(location_name)
    response = service.suggest_geo_target_constants(request)
    for suggestion in response.geo_target_constant_suggestions:
        gtc = suggestion.geo_target_constant
        if gtc.country_code == "BR" and gtc.target_type in ("City", "Municipality"):
            return gtc.resource_name
    if response.geo_target_constant_suggestions:
        return response.geo_target_constant_suggestions[0].geo_target_constant.resource_name
    raise RuntimeError(f"Nenhum geo target encontrado para '{location_name}'.")


def _resolve_language(client, customer_id, code):
    ga_service = client.get_service("GoogleAdsService")
    query = f"SELECT language_constant.id, language_constant.code, language_constant.resource_name FROM language_constant WHERE language_constant.code = '{code}'"
    for row in ga_service.search(customer_id=customer_id, query=query):
        return row.language_constant.resource_name
    raise RuntimeError(f"Idioma '{code}' não encontrado.")


MONTH_NAMES = [
    None, "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
]


def _months_back(n, from_year, from_month):
    """Retorna lista de (ano, mes) dos n últimos MESES FECHADOS (não inclui
    o mês corrente, que ainda não tem dado completo)."""
    out = []
    y, m = from_year, from_month
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        out.append((y, m))
    return list(reversed(out))


def fetch_search_interest(bairros, months_back=3, log=print):
    """Retorna dict {bairro: {"avg_monthly_searches": int, "months": [...]}}
    com o total de buscas mensais somado das variantes de keyword daquele
    bairro, nos últimos `months_back` meses fechados."""
    from google.ads.googleads.client import GoogleAdsClient
    import datetime

    client = GoogleAdsClient.load_from_dict(_client_config())
    customer_id = os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]

    geo_resource = _resolve_geo_target(client, customer_id, GEO_LOCATION_NAME)
    lang_resource = _resolve_language(client, customer_id, LANGUAGE_CODE)

    today = datetime.date.today()
    target_months = _months_back(months_back, today.year, today.month)
    start_y, start_m = target_months[0]
    end_y, end_m = target_months[-1]

    keyword_to_bairro = {}
    keywords = []
    for bairro in bairros:
        for template in KEYWORD_TEMPLATES:
            kw = template.format(bairro=bairro).lower()
            keyword_to_bairro[kw] = bairro
            keywords.append(kw)

    log(f"[keywords] consultando {len(keywords)} termos ({months_back} meses: {target_months[0]}..{target_months[-1]})")

    service = client.get_service("KeywordPlanIdeaService")
    request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    request.customer_id = customer_id
    request.keywords.extend(keywords)
    request.language = lang_resource
    request.geo_target_constants.append(geo_resource)
    request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    request.historical_metrics_options.year_month_range.start.year = start_y
    request.historical_metrics_options.year_month_range.start.month = getattr(
        client.enums.MonthOfYearEnum, MONTH_NAMES[start_m]
    )
    request.historical_metrics_options.year_month_range.end.year = end_y
    request.historical_metrics_options.year_month_range.end.month = getattr(
        client.enums.MonthOfYearEnum, MONTH_NAMES[end_m]
    )

    response = service.generate_keyword_historical_metrics(request=request)

    by_bairro_monthly = {b: {} for b in bairros}  # bairro -> (year,month) -> soma
    for result in response.results:
        text = (result.text or "").lower()
        matched_bairros = set()
        for kw in [text] + list(result.close_variants):
            if kw in keyword_to_bairro:
                matched_bairros.add(keyword_to_bairro[kw])
        if not matched_bairros:
            continue
        for msv in result.keyword_metrics.monthly_search_volumes:
            key = (msv.year, msv.month.value if hasattr(msv.month, "value") else int(msv.month))
            searches = msv.monthly_searches if msv.monthly_searches else 0
            for b in matched_bairros:
                by_bairro_monthly[b][key] = by_bairro_monthly[b].get(key, 0) + searches

    out = {}
    for b in bairros:
        vals = list(by_bairro_monthly[b].values())
        out[b] = {
            "avg_monthly_searches": round(sum(vals) / len(vals)) if vals else 0,
            "meses_com_dado": len(vals),
        }
    return out


def _load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return None


def _save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def get_search_interest_cached(bairros, log=print):
    """Usa o cache se tiver menos de CACHE_MAX_AGE_DAYS dias; senão busca de
    novo na API e atualiza o cache. Retorna None se não há credenciais
    configuradas (feature opcional)."""
    import datetime

    if not credentials_available():
        log("[keywords] GOOGLE_ADS_* não configurado — pulando sinal de interesse de busca (opcional).")
        return None

    state = _load_state()
    if state:
        fetched_at = datetime.datetime.fromisoformat(state["fetched_at"])
        age_days = (datetime.datetime.now(datetime.timezone.utc) - fetched_at).days
        if age_days < CACHE_MAX_AGE_DAYS:
            log(f"[keywords] usando cache ({age_days} dias, dados atualizam mensalmente na fonte).")
            return state["data"]

    try:
        data = fetch_search_interest(bairros, log=log)
    except Exception as e:
        log(f"[keywords] aviso: falhou buscar interesse de busca ({e}) — seguindo sem esse sinal.")
        return state["data"] if state else None

    _save_state({"fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "data": data})
    return data


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from normalize import TARGETS

    result = get_search_interest_cached(TARGETS)
    if result:
        for b, v in sorted(result.items(), key=lambda x: -x[1]["avg_monthly_searches"])[:15]:
            print(f"  {b}: {v['avg_monthly_searches']} buscas/mês")
