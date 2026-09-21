# Torre de Controle — Investimento Imobiliário SP

Dashboard estática (sem Node/build step) que cruza vendas reais de imóveis
(ITBI da Prefeitura de SP) com o estoque atual de anúncios (nonStop) para os
47 bairros da carteira, respondendo: **em qual bairro anunciar** e **qual
imóvel priorizar** para gerar leads qualificados.

Mesmo padrão de arquitetura do
[dashboard-meta-topio](https://github.com/comercial501/dashboard-meta-topio)
("Torre de Controle" do Instagram): fontes de dados → `scripts/build_data.py`
→ `site/data.json` → `site/index.html`, atualizado automaticamente todo dia
via GitHub Actions.

## Como surgiu

Existia uma versão anterior (100% manual, em Perl) que dependia de colar
`.xlsx` baixados à mão da Prefeitura e exportados à mão da nonStop toda
semana — ver `scripts/*.pl` e `scripts/dashboard_template.html`, mantidos no
disco local só como referência histórica (não fazem mais parte do
pipeline nem estão neste repositório — ver `.gitignore`). O motor de cálculo
(fórmulas, limiares, normalização de bairro/endereço) foi **portado 1:1**
para Python a partir desse código — mesma metodologia, fonte de dados
automatizada.

## Arquitetura

```
scripts/
  itbi_source.py          ← raspa prefeitura.sp.gov.br, baixa só o que mudou
  xlsx_reader.py           ← leitor .xlsx sem dependências (zipfile + XML da stdlib)
  parse_itbi.py             ← extrai transações residenciais válidas do ITBI
  nonstop_client.py         ← cliente da API da nonStop (estoque atual)
  parse_usenonstop_xlsx.py  ← fallback: lê export manual .xlsx (sem NONSTOP_TOKEN)
  normalize.py               ← normalização de bairro/endereço + estatísticas
  engine.py                   ← motor de cálculo dos 10 painéis
  build_data.py                ← orquestra tudo → site/data.json + site/raw.json
site/
  index.html / styles.css / app.js
  data.json   ← agregado por bairro, carregado no primeiro acesso (rápido)
  raw.json    ← registros individuais (ITBI + nonStop), carregado só quando
                o usuário usa um filtro — ver "Filtros" abaixo
  engine.js   ← porte de scripts/engine.py pra JavaScript, roda no navegador
.github/workflows/build-data.yml  ← roda build_data.py todo dia às 8h (BRT)
```

## Como rodar localmente

```
cp .env.example .env               # preencha NONSTOP_TOKEN no .env (nunca commitar)
python3 scripts/build_data.py      # sincroniza ITBI + nonStop, gera site/data.json
cd site && python3 -m http.server 8731
```

Abra `http://localhost:8731/index.html`. Precisa ser via servidor local (não
`file://`) porque a página carrega `data.json` com `fetch()`.

Sem `NONSTOP_TOKEN` definido, o script cai automaticamente para o export
manual mais recente em `dados-usenonstop/*.xlsx` (se existir algum arquivo
ali) — útil para testar o motor de cálculo sem token configurado.

## Fontes de dados

### ITBI (Prefeitura de SP) — automático, checagem diária

`itbi_source.py` raspa a [página oficial](https://prefeitura.sp.gov.br/web/fazenda/w/acesso_a_informacao/31501)
todo dia, descobre o link atual de cada ano (o nome do arquivo muda todo mês)
e só baixa de novo quando o `Last-Modified`/tamanho do arquivo mudou desde a
última execução. **A prefeitura só atualiza o consolidado mensalmente**
(dados do mês anterior) — rodar diariamente não traz dado novo todo dia, mas
garante que o primeiro dia útil após a atualização mensal já reflita no
dashboard, sem depender de alguém lembrar de baixar manualmente.

### nonStop (estoque de anúncios) — automático via API, diário

`nonstop_client.py` usa a [API da nonStop](https://docs.usenonstop.com/)
(`/unstable/imoveis/todos`, paginação por cursor) filtrando `availableFor=VENDA`,
`use=RESIDENCIAL`, `state=SP`, `city=São Paulo`. Precisa de `NONSTOP_TOKEN`
(Secret do repositório no GitHub, ou `.env` local — nunca no código).

**Limitação conhecida** (não existia no export manual em `.xlsx`): o endpoint
de listagem devolve `CardProperty`, que não inclui o status de construção do
imóvel (lançamento/pronto/reforma/etc — só a ficha completa de um imóvel tem
isso). Sem esse campo, todo imóvel vindo da API entra como "padrão" no
critério de Captação Ativa — o painel fica levemente mais conservador (pode
contar uma unidade em lançamento como "já anunciada hoje" quando na
verdade não deveria bloquear a prospecção daquele endereço). Ver comentário
no topo de `nonstop_client.py`.

### Interesse de busca no Google (Keyword Planner) — opcional

`keyword_client.py` busca, via `GenerateKeywordHistoricalMetrics` da API do
Google Ads, o volume de busca de 3 variantes de palavra-chave por bairro
("apartamento à venda X", "apartamento X", "imóveis X"), geo-segmentado em
São Paulo. É um sinal **prospectivo** de demanda (gente pesquisando agora),
complementar à liquidez do ITBI, que é puramente **retrospectiva** (só
vendas já fechadas) — por isso aparece como selo informativo ("Busca:
Alto/Médio/Baixo") no Ranking de Oportunidade e na Prontidão para Campanha,
sem entrar na fórmula de nenhum score ainda.

**Janela de 3 meses, não 1**: decisão de compra de imóvel tem ciclo de
semanas a meses, então um pico de busca de 30 dias é mais ruído do que
sinal; os outros sinais da dashboard já operam em escala de semestre/ano, e
o próprio Keyword Planner só atualiza o volume em base mensal (média móvel
de 12 meses) — não existe granularidade diária pra explorar mesmo rodando
o pipeline todo dia.

**Limitação de geolocalização**: o Google não segmenta volume de busca por
bairro, só por cidade — a segmentação por bairro depende inteiramente do
nome dele estar no termo pesquisado, um proxy razoável mas imperfeito.

**Classificação Alto/Médio/Baixo**: tercil contra os 47 bairros inteiros,
recalculado a cada busca — **não** muda com os filtros de bairro/preço da
tela (um tercil sobre 2-3 bairros filtrados não teria sentido estatístico).

**Cadência**: mensal, não diária — `data/keyword_state.json` guarda a
última busca; `build_data.py` só chama a API de novo se o cache tiver mais
de 25 dias.

**Setup** (opcional — sem isso, a dashboard funciona normalmente, só sem o
selo):
1. No [Google Cloud Console](https://console.cloud.google.com/), no seu
   projeto: ative a "Google Ads API", crie um cliente OAuth do tipo **"App
   para computador"**, complete a verificação de marca e solicite acesso
   "Basic" (agora automatizado, decidido em minutos).
2. `pip install -r requirements.txt`
3. `python3 scripts/generate_refresh_token.py --client-id ... --client-secret ...`
   — abre o navegador uma vez, você loga e autoriza, o script imprime o
   refresh token.
4. Preencha `GOOGLE_ADS_CLIENT_ID` / `GOOGLE_ADS_CLIENT_SECRET` /
   `GOOGLE_ADS_REFRESH_TOKEN` / `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (o Customer ID
   da conta, sem hífen) no `.env` local e como Secrets do repositório no
   GitHub.

## Metodologia dos painéis

Pesos, limiares e fórmulas exatas estão comentados em `scripts/engine.py`
(cada função referencia a lógica original). Resumo por painel:

1. **Ranking de Oportunidade** — bairros por score (50% z-score do volume de
   vendas residenciais no último ano fechado + 50% z-score da tendência de
   crescimento), normalizado 0–100 entre os 47 bairros.
2. **Prontidão para Campanha** — score combinando 6 sinais (liquidez/tendência
   15%, estoque compatível 20%, alinhamento de preço 15%, captação ativa 15%,
   qualidade×cobertura dos imóveis prioritários 25%, concentração de achados
   de valor 10%).
3. **Perfil por Bairro** — metragem/preço/dormitórios/vagas que mais vendeu,
   com fallback para estimativa regional (vizinhos até 3km) quando a amostra
   do bairro é baixa (< 5 transações ou < 5 imóveis no perfil).
3b. **Estoque × Demanda** — tabela com todos os 47 bairros: quantos anúncios
   ativos hoje batem o perfil vencedor vs. o volume de vendas do ano, com
   drill-down pra ver os anúncios específicos que compõem esse estoque.
4. **Mapa** — bolhas por centróide real (coordenadas do estoque nonStop),
   raio ∝ √volume, cor = score.
5. **Captação Ativa Estratégica** — endereços com 2+ vendas de revenda
   orgânica (excluindo lançamentos e preços incoerentes) sem nenhuma unidade
   anunciada hoje.
6. **Imóveis Prioritários** — pontuação por imóvel (35% liquidez de revenda
   do bairro + 30% alinhamento de preço + 25% aderência ao perfil + 10%
   bônus de captação ativa).
7. **Valor de Oportunidade** — imóveis 20%+ abaixo da mediana paga no bairro
   (só em bairros com 10+ vendas no ano — mediana confiável).

## Filtros (bairro + faixa de preço)

O painel "Filtros" no topo do site deixa selecionar um ou mais dos 47
bairros e/ou uma faixa de preço (aplicada tanto ao valor pago na Prefeitura
quanto ao pedido na nonStop). Ao mudar qualquer filtro, os painéis são
**recalculados** — médias, medianas, scores e rankings refeitos só com os
dados que passam pelo filtro, não apenas a lista final escondida. Isso roda
inteiramente no navegador (`site/engine.js`), carregando `site/raw.json`
(registros individuais) sob demanda na primeira vez que um filtro é usado.

`engine.js` é um porte funcionalmente idêntico de `scripts/engine.py` —
validado campo a campo contra a saída do Python (bairros, ranking,
prontidão, imóveis prioritários, captação ativa, valor de oportunidade)
antes de entrar no site. Qualquer mudança de fórmula/limiar em `engine.py`
precisa ser replicada em `engine.js`, senão os dois lados divergem
silenciosamente.

**Regra sutil herdada da versão original**: o filtro de **preço** vale
sobre os 47 bairros inteiros (inclusive como "doadores" de estimativa
regional pro fallback de vizinhança — ver Perfil por Bairro), mas o filtro
de **bairro** só entra depois, restringindo quais bairros geram linha e
entram na normalização (z-score) do score — nunca restringe de quem um
bairro pode "herdar" perfil quando a amostra própria é pequena.

## Automação (GitHub Actions)

`.github/workflows/build-data.yml` roda `build_data.py` todo dia às 8h
(horário de São Paulo) e commita `site/data.json` se mudou. Precisa do
Secret `NONSTOP_TOKEN` configurado no repositório (Settings → Secrets and
variables → Actions). O cache dos `.xlsx` de ITBI entre execuções evita
rebaixar ~100MB todo dia à toa.
