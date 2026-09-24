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
python3 site/serve_no_cache.py
```

Abra `http://localhost:8731/index.html`. Precisa ser via servidor local (não
`file://`) porque a página carrega `data.json` com `fetch()`. Use
`serve_no_cache.py` em vez de `python3 -m http.server` — ele manda
`Cache-Control: no-store`, senão o navegador guarda `data.json`/`raw.json`
em cache e a dashboard parece "não atualizar" mesmo depois do pipeline
diário rodar.

### Automação local (Mac) — servidor sempre ligado + sync diário

Pra acessar a dashboard (inclusive do celular, via [Tailscale](https://tailscale.com))
sem precisar abrir terminal nenhum: dois LaunchAgents do macOS cuidam disso
sozinhos — `~/Library/LaunchAgents/com.topio.dashboard-imoveis.server.plist`
(mantém `serve_no_cache.py` sempre rodando na porta 8731, reinicia sozinho
se cair) e `com.topio.dashboard-imoveis.sync.plist` (`git pull` automático
às 8h20 e ao meio-dia, depois que a Action do GitHub atualiza `data.json`).
**Importante**: o projeto precisa ficar fora de `~/Desktop` (ou de
`~/Documents`/`~/Downloads`) — essas pastas têm uma proteção de privacidade
do macOS que bloqueia processos rodados via `launchd` (diferente de rodar
pelo Terminal).

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

## Limpeza de dados do ITBI (auditoria de 2026-09-24)

Uma auditoria completa da metodologia encontrou dois problemas reais nos
dados brutos do ITBI, corrigidos em `parse_itbi.py`/`engine.py`:

- **Natureza de transação**: ~11,6% das linhas residenciais válidas não são
  venda de mercado — são integralização de capital, leilão, herança,
  divórcio, permuta etc. (coluna "Natureza de Transação" do ITBI), com
  valor sistematicamente mais baixo que compra e venda genuína (medido em
  produção, 2025: mediana R$605mil em "1.Compra e venda" vs. R$150-460mil
  nessas outras naturezas). Isso puxava a mediana de preço pago pra baixo
  artificialmente. **Decisão**: `avg_valor`/`median_valor`/faixa de
  metragem (Perfil Vencedor) agora usam só `is_compra_venda=True`; volume
  de vendas e liquidez continuam contando qualquer transação residencial
  válida (giro do bairro é giro, mesmo quando o valor não é confiável pra
  preço). Lançamentos **não** foram adicionados a esse filtro — continuam
  contando pra mediana/perfil, só saem da Captação Ativa (decisão do
  usuário).
- **Duplicidade exata**: ~2,6% das linhas eram duplicatas exatas (mesmo
  bairro+rua+número+valor+data) — colapsadas para 1 por grupo.

Isso reduz alguns gaps de preço que estavam inflados por ruído (ex:
Ipiranga caiu de 250% pra 230% de gap), mas não elimina completamente
diferenças legítimas entre "o que se pagou historicamente" e "o que se
pede hoje" — um gap grande que sobra depois da limpeza pode ainda refletir
mercado real, vale conferir com conhecimento local.

Uma segunda rodada da mesma auditoria endereçou mais dois pontos:

- **Mediana de preço pedido sem proteção contra outlier**: `asking_median`
  (preço pedido hoje, usado em Prontidão para Campanha e Perfil Vencedor)
  não filtrava anúncios com valor digitado errado (ex: metro quadrado
  lançado como valor total). **Decisão**: aplica cercas de Tukey (IQR) —
  a mesma técnica já usada pra preço pago do ITBI — antes de calcular a
  mediana.
- **Faixa de metragem de Captação Ativa sem checagem de coerência**: um
  endereço com histórico de 2+ vendas podia reportar `area_min`/`area_max`
  vindos de unidades completamente diferentes (ex: um apto de 45m² e uma
  cobertura de 300m² no mesmo prédio), o que sugere erro de leitura do
  ITBI ou plantas tão diferentes que a faixa não ajuda a decisão de
  captação. **Decisão**: quando a razão `area_max/area_min` de um endereço
  ultrapassa 4x, a faixa vira `None`/`None` em vez de mostrar um intervalo
  enganoso — limiar calibrado pela distribuição real de 3.345 endereços
  com múltiplas vendas (p50=1,0x, p75=1,16x, p90=1,55x, p95=1,85x,
  p99=2,6x — 4x já é bem acima do ruído normal de plantas variadas no
  mesmo prédio).

Uma terceira rodada (2026-09-23, motivada por um endereço que o usuário
conferiu pessoalmente contra a planilha) encontrou dois problemas mais
sérios, específicos da Captação Ativa (histórico de vendas por endereço):

- **Endereço partido em dois bairros**: a coluna "Bairro" do ITBI é
  preenchida por TRANSAÇÃO, não é um dado fixo do prédio — o cartório às
  vezes registra o mesmo edifício com bairros diferentes em vendas
  diferentes (medido: **592 dos 9.514 endereços únicos da carteira, 6,2%**,
  quase sempre entre bairros vizinhos: Indianópolis/Moema, Perdizes/
  Pompéia, Higienópolis/Santa Cecília, Jardim Paulista/Jardins etc.). Como
  a chave de endereço antiga incluía o bairro (`bairro|rua|número`), isso
  partia o histórico de UM prédio em duas entradas incompletas na Captação
  Ativa — ex: Alameda Franca, 107 aparecia com só 2 vendas (as de
  "Jardins") quando na verdade tinha 4 (as outras 2 registradas como
  "Jardim Paulista"). **Decisão**: a chave de endereço agora é só
  `rua|número` (`normalize.address_key`); o bairro exibido pro endereço
  fica sendo o mais frequente entre as vendas reais dali (empate resolvido
  alfabeticamente).
- **Captação Ativa não aplicava o filtro de natureza de transação**: a
  correção da 1ª rodada (só "compra e venda" conta pra preço) tinha sido
  aplicada na mediana por bairro, mas não na faixa de preço por endereço
  — uma transferência de herança/doação continuava contando como "venda"
  e podia virar o `preco_min` exibido. Ex: Rua Rio Grande, 574 mostrava
  R$149mil–R$1,8M (12 "vendas"); o R$149mil era uma transferência sem
  natureza de compra e venda — a faixa real, com as 10 vendas de mercado
  genuínas, é R$1,36M–R$1,8M. **Decisão**: mesmo filtro `is_compra_venda`
  da mediana de bairro, agora também na faixa de preço/contagem de vendas
  por endereço; um endereço cuja ÚNICA venda registrada não é compra e
  venda sai da Captação Ativa (não tem preço de mercado de referência).

Os dois motores (Python e JavaScript) foram revalidados campo a campo após
essa mudança — 0 divergências em `captacao_ativa` (3.013 endereços),
`bairros`, `ranking`, `imoveis_prioritarios` e `valor_oportunidade`.

Uma quarta rodada (2026-09-24, motivada pelo usuário conferindo endereços
do Jardim Paulista pessoalmente e achando faixas de preço "impossíveis"
como R$95mil–R$1,4M pro mesmo apartamento) encontrou o problema mais
significativo de toda a auditoria:

- **~20% das linhas "1.Compra e venda" são transferência de FRAÇÃO ideal,
  não do imóvel inteiro.** O ITBI tem uma coluna (L) com o percentual do
  imóvel efetivamente transacionado — confirmado comparando com as colunas
  de valor venal de referência (K = referência do imóvel inteiro, M = K ×
  L/100). Quando um imóvel é herdado por vários herdeiros, partilhado num
  divórcio, ou tem uma fração doada, cada transferência de fração vira uma
  linha própria no ITBI com `L < 100` — e o `valor` dessa linha é o preço
  só da fração, não do apartamento inteiro. **Medido: 4.529 das 22.760
  linhas "compra e venda" residenciais da carteira (19,9%, quase 1 em
  cada 5) são transferências parciais.** Exemplo real — Rua Jose Maria
  Lisboa, 356: uma venda de R$1,5M foi registrada em 2 linhas de ITBI no
  mesmo dia (79,82% por R$1.405.000 + 20,18% por R$95.000); sem esse
  filtro, o R$95mil parecia ser o preço de um apartamento inteiro de
  137m², quando na origem é só a 5ª parte de uma venda de R$1,5M.
  **Decisão**: nova checagem `is_full_transfer` (L ≥ 99,99%, tolerância só
  pra ruído de arredondamento), combinada com `is_compra_venda` em TODO
  lugar que calcula preço/metragem (mediana de bairro, faixa de metragem
  do Perfil Vencedor, faixa de preço da Captação Ativa) — igual às
  correções anteriores, volume/liquidez continua contando qualquer
  transação, fracionária ou não.

Essa é a correção de maior impacto de toda a auditoria (19,9% das linhas
válidas afetadas, contra 11,6% da natureza de transação e 2,6% das
duplicatas). Revalidado Python × JavaScript de novo: 0 divergências em
`captacao_ativa` (2.811 endereços), `bairros` e `imoveis_prioritarios`
(1.820 imóveis).

**Limitação conhecida que continua**: a checagem de coerência de preço por
endereço (`ADDR_MAX_RATIO = 20x`) não pega tudo — ex: Avenida Brig Luis
Antonio, 3249 ainda mostra R$59.561–R$480.000 (8x) pra apartamentos de
74–77m², mesmo já filtrando natureza e fração. Não é um bug de pipeline
identificado (a linha é "compra e venda", 100% do imóvel) — pode ser uma
venda genuinamente distressed (leilão, favor familiar) que a Prefeitura
registrou como compra e venda comum. Vale conferir esses casos residuais
pessoalmente (Google/QuintoAndar) antes de usar como referência de preço.

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
   orgânica (excluindo lançamentos e preços incoerentes). Endereços sem
   nenhuma unidade anunciada hoje vêm primeiro (prospecção resolve um acesso
   que não existe por outro caminho); endereços que já têm alguma unidade
   ativa continuam na lista, marcados, porque o prédio com giro comprovado
   ainda vale a visita pra tentar captar outras unidades — **não são mais
   excluídos** (mudança de metodologia: ver comentário "Mudança 13" em
   `engine.py`).
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
