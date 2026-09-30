# Torre de Controle — Investimento Imobiliário SP

Dashboard estática (sem Node/build step) que cruza vendas reais de imóveis
(ITBI da Prefeitura de SP) com o estoque atual de anúncios (nonStop) para os
49 bairros da carteira, respondendo: **em qual bairro anunciar** e **qual
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

**Classificação Alto/Médio/Baixo**: tercil contra os 49 bairros inteiros,
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

## Camada de dados limpa (auditoria de 2026-09-29, pré-conteúdo público)

Antes de a dashboard passar a alimentar posts públicos (Instagram), uma
revisão encontrou dois problemas de fundo — um deles bem maior que
qualquer achado anterior desta auditoria. `scripts/clean_itbi.py` resolve
os dois; `site/itbi_clean_log.json` é o log completo, auditável, de
quantas linhas saíram em cada filtro a cada execução do pipeline.

**1. Bairro (coluna E do ITBI) some ou vem errado em ~91% das linhas —
inclusive de prédios que já rastreamos.** É texto livre preenchido por
transação no cartório, não um dado fixo do imóvel: pode faltar numa linha
e estar correto em outra do MESMO endereço. Filtrar por bairro linha a
linha (como o pipeline fazia até 2026-09-27) descartava a venda inteira.
Exemplo real: Av. Ibirapuera, 2927 (Moema) é um lançamento com 36 vendas
registradas entre 2024-2026 — só 8 tinham bairro preenchido, poucas demais
espalhadas em 2 anos pra disparar o detector de lançamento (5+ vendas em
182 dias), então o endereço aparecia na Captação Ativa como se fosse um
prédio comum com uma faixa de preço "implausível" (R$139mil-R$730mil).
**Decisão**: `clean_itbi.resolve_bairros()` decide o bairro de um endereço
pela MAIORIA entre as linhas do mesmo endereço que já têm bairro
reconhecido, recuperando as que vieram sem — **21.731 vendas residenciais
recuperadas** em produção. Endereços sem NENHUMA linha com bairro
reconhecido continuam fora (de verdade fora da carteira de 49 bairros).

**2. Deduplicação por rua+número+valor+data (usada até 2026-09-27)
confundia unidades DIFERENTES com preço e data coincidentes** — comum em
lançamento com tabela de preço padronizada (várias unidades idênticas,
mesmo dia, mesmo valor, `SQL` do cadastro diferente). **Decisão**: dedup
agora usa o SQL (coluna A, "N° do Cadastro do Imóvel" — identificador
oficial e inequívoco), com fallback pra chave antiga só quando o SQL está
ausente (raro). Em produção: **565 duplicatas reais** (contra ~2,6%
medido com a chave antiga, que superestimava por contar unidades
diferentes como se fossem a mesma).

**3. Camada de preço limpa, usada por todo cálculo de R$ do motor**
(mediana de bairro, Perfil Vencedor, e a partir da próxima etapa também
Alertas/Valor de Oportunidade/Ranking) — em cima do bairro já resolvido e
deduplicado, filtra em sequência:
   - só uso residencial de UNIDADE (exclui código 21/22 do IPTU — "prédio
     de apartamento não em condomínio", ou seja, o **prédio inteiro**
     vendido de uma vez, sem equivalente em nenhum anúncio da nonStop);
   - só "1.Compra e venda" (exclui herança/doação/integralização de
     capital — valor contábil, não preço de mercado);
   - só 100% do imóvel transmitido (proporção transmitida < 100% é
     transferência de fração entre coproprietários — valor da fração, não
     do imóvel inteiro);
   - só com Área Construída (IPTU) válida;
   - sem outlier de R$/m² pro seu segmento **bairro + tipo de imóvel
     (apartamento/casa) + faixa de metragem** (até 50m², 50–80m², 80–120m²,
     acima de 120m²) — cerca de percentil P5–P95, calculada uma vez por
     segmento com 10+ transações (segmentos menores não têm poder
     estatístico pra um corte de cauda confiável, ficam sem trim).

Volume/liquidez (Ranking de Oportunidade, Estoque×Demanda) continuam
usando o conjunto residencial bruto já resolvido/deduplicado, sem os
filtros de preço acima — giro é giro, mesmo com natureza não comercial ou
transferência parcial (decisão do usuário, mantida desde a 1ª rodada desta
auditoria). Captação Ativa (histórico de UM endereço) usa natureza +
100% transmitido + tipo de unidade, mas **não** o corte de outlier por
segmento — um endereço específico já tem sua própria checagem de
coerência (`ADDR_MAX_RATIO`), e aplicar ali um corte calibrado pelo bairro
inteiro esconderia vendas genuínas de um prédio específico.

Impacto em produção dessa rodada: `total_itbi_rows_matched` foi de
185.930 pra 304.262 (+64%, a maior parte é bairro fora da carteira ou
recuperado — não inflação de dado ruim); Captação Ativa foi de 2.905 pra
4.393 endereços; endereços descartados como lançamento foram de 163 pra
618 (o detector agora vê o histórico completo). Revalidado Python ×
JavaScript: 0 divergências reais em 4.393 endereços de Captação Ativa (1
mistura de acento num texto de exibição, sem efeito em nenhum número) e
em todos os outros painéis.

## Preço por R$/m², segmentado (Etapa 3 da auditoria de 2026-09-29)

Toda comparação de preço pedido × pago do motor passou a ser em **R$/m²**,
dentro do **mesmo tipo de imóvel** (apartamento/casa — código "Uso (IPTU)"
do ITBI e campo `type` da nonStop, mapeados pra 2 categorias em
`clean_itbi.TIPO_IMOVEL_POR_USO`/`TIPO_IMOVEL_NONSTOP`) e da **mesma faixa
de metragem** (até 50m², 50–80m², 80–120m², acima de 120m²), sempre com
**mediana**, nunca média nem valor total. `engine._compute_preco_m2()`
calcula isso uma vez por bairro (todas as combinações tipo+faixa que têm
pelo menos uma venda paga OU um anúncio) e alimenta os 5 pontos abaixo:

- **Alertas** (Visão Geral) — virou lista de SEGMENTOS (bairro + tipo +
  faixa), não mais de bairros inteiros. Ex: Ibirapuera aparecia com gap de
  988% comparando a mediana pedida de TODOS os tamanhos com a paga de
  apartamentos de 120-140m²; hoje o gap de 598% é "Ibirapuera ·
  Apartamento · acima de 120m²" — mesmo tipo, mesma faixa (ver limitação
  conhecida abaixo).
- **Valor de Oportunidade** — desconto compara R$/m² do anúncio com a
  mediana R$/m² do MESMO segmento, não mais o valor total com a mediana de
  todos os tamanhos do bairro. Corrigiu o caso relatado (4 studios de
  23-32m² no Alto da Boa Vista apareciam como "70-77% abaixo" comparados
  com apartamentos de 100-120m²; hoje não geram achado nenhum, porque não
  há venda paga registrada de apartamento até 50m² nesse bairro — sem
  referência confiável, sem achado forçado).
- **Gap Preço do Ranking de Oportunidade** — vira o gap do segmento mais
  representativo do bairro (mais transações pagas nos últimos 12 meses,
  entre os que não são amostra pequena), não mais bairro inteiro × bairro
  inteiro.
- **Perfil por Bairro** — "Faixa de preço pago (P25-P75)" e "Mediana paga
  × pedida" viraram uma tabela com uma linha por segmento (tipo + faixa)
  que tem dado, com P25-P75 pago, mediana pedida, gap e tamanho da
  amostra — substituindo a comparação única do "bucket de metragem
  vencedora" do bairro inteiro.
- **Alinhamento de preço** (Prontidão para Campanha e Imóveis
  Prioritários) — compara R$/m² do anúncio com a mediana do MESMO
  segmento, em vez do valor total do imóvel com a mediana de todos os
  tamanhos do bairro.

**Regra de amostra**: um segmento (bairro + tipo + faixa) com menos de 10
vendas pagas nos ÚLTIMOS 12 MESES (`MIN_TRANSACOES_PRECO_M2_12M`, distinto
do pool de 3 anos usado pra calcular a própria mediana — a janela de 12
meses é só o portão de confiança "isso ainda reflete o bairro HOJE") vira
`amostra_pequena`, e não gera alerta nem achado de Valor de Oportunidade.

**Achado extra testando isso**: um anúncio da nonStop tinha área
"130000" (130 mil m² — erro de digitação, provavelmente 130m² com 3
zeros a mais), gerando R$/m² de R$13 e um falso "99,8% de desconto".
`clean_itbi.AREA_CAP_NONSTOP = 2000` descarta área de anúncio acima
disso (maior área legítima na amostra real: 895m²).

**Limitação conhecida**: a faixa "acima de 120m²" é aberta (sem teto) —
um apartamento de 130m² e uma cobertura de 500m² caem no mesmo segmento.
Em bairros de altíssimo padrão (Ibirapuera, Itaim Bibi) isso ainda pode
gerar gaps grandes mesmo comparando "mesmo tipo, mesma faixa", porque o
estoque anunciado nessa faixa pode ser sistematicamente mais luxuoso que
o que historicamente se vendeu. As faixas de metragem usadas são as que
foram pedidas explicitamente; não criei uma faixa adicional pra
"altíssimo padrão" sem confirmar com o usuário.

Revalidado Python × JavaScript depois de toda a Etapa 3: 0 divergências
em `preco_m2_segmentos` (49 bairros), Valor de Oportunidade (41
achados) e Imóveis Prioritários (1.820 imóveis).

## Painel "Preço por m² — Pago × Pedido" (Etapa 4 da auditoria de 2026-09-29)

Painel dedicado (aba própria, `engine._compute_preco_m2_painel()`) com
escopo dele mesmo, diferente do resto da Etapa 3: **só apartamento**
(nem casa) e **só últimos 12 meses** — inclusive a mediana paga, não só a
checagem de amostra. É um retrato do mercado AGORA, não o pool de 3 anos
usado nas outras 5 comparações. Uma linha por bairro × faixa de metragem
(4 faixas × 49 bairros = até 196 linhas, 157 com dado real na última
execução):

- Mediana de R$/m² pago (ITBI limpo, últimos 12 meses)
- Mediana de R$/m² pedido (estoque atual da nonStop — sem janela de
  tempo, porque anúncio não tem "data da venda")
- Gap % entre os dois
- Número de vendas pagas (12 meses) e de anúncios na amostra
- Selo "Amostra pequena" quando há menos de 10 vendas pagas no segmento
  nos últimos 12 meses (mesma regra da Etapa 3) — mostra a linha mesmo
  assim, só avisa que a referência ainda não é confiável.

Exportado também em `output/preco_m2_por_bairro.csv` a cada execução do
`build_data.py` (committed pelo workflow, igual `site/data.json`) —
também se beneficia do `AREA_CAP_NONSTOP` descrito acima.

Revalidado Python × JavaScript: 0 divergências nas 157 linhas do painel.

## Validação e correção do lado pedido (Etapa 5 da auditoria de 2026-09-29)

Na validação final da Etapa 3/4, um achado novo: a `amostra_pequena`
(10+ vendas pagas nos últimos 12 meses) só protege o lado PAGO da
comparação. O lado PEDIDO (`n_anuncios`) não tinha piso nenhum — um único
anúncio da nonStop conseguia sozinho sustentar um "gap" de centenas de
pontos percentuais contra a mediana paga.

Antes da correção, 19 dos 105 segmentos que passavam no filtro de gap
(±20 p.p.) e não eram `amostra_pequena` tinham **1 ou 2 anúncios** do lado
pedido — por exemplo "Santa Cecília · apartamento · 80–120m²" com gap de
+236,6% sustentado por 1 único anúncio, ou "Mooca · apartamento ·
50–80m²" com +243,4% também sobre 1 anúncio. Esses são ruído de amostra,
não sinal de mercado.

Adicionada constante `MIN_ANUNCIOS_ALERTA = 3` (`scripts/engine.py`,
espelhada em `site/engine.js` via `C.min_anuncios_alerta`): um segmento só
vira alerta, ou "segmento representativo" de um bairro no Ranking (Gap
Preço/`flag_alerta`), se tiver **3 ou mais anúncios ativos** além de
passar na regra de amostra paga já existente. Aplicado em:

- `_segmento_representativo()` — usado pelo Gap Preço do Ranking e por
  `flag_alerta`.
- Alertas (Visão Geral) — filtro em `site/app.js`, mesmo critério.

`_lookup_mediana_pago_m2()` (Valor de Oportunidade e Imóveis
Prioritários) **não** ganhou esse piso — ela só lê a mediana do lado
pago, nunca calcula nada a partir do lado pedido, então o risco de
amostra fina do lado pedido não se aplica ali.

Resultado: de 105 segmentos elegíveis pra alerta antes da correção, 86
sobraram depois (19 removidos, todos com 1-2 anúncios). Revalidado Python
× JavaScript: 0 divergências em `price_gap_pct`/`flag_alerta` (49
bairros) e na lista de Alertas recomputada (86 segmentos nos dois
motores).

## Persistência e descrições dos painéis (Etapa 6 da auditoria de 2026-09-29)

A limpeza e a nova lógica de R$/m² (Etapas 2-5) já rodam automaticamente,
sem passo manual nenhum: o GitHub Actions (`.github/workflows/build-data.yml`)
executa `python3 scripts/build_data.py` **todo dia** às 8h BRT — não só
semanal —, e esse script já embute 100% da limpeza (`clean_itbi.py`) e do
motor novo (`engine.compute()`). Localmente, dois LaunchAgents cuidam do
resto sem depender de terminal aberto: um mantém `serve_no_cache.py`
sempre ligado, o outro faz `git pull` às 8h20 e ao meio-dia pra puxar o
`data.json` que a Action já atualizou (ver "Automação local" acima).
Nenhum dos dois caminhos automáticos depende de `atualizar.sh`.

**Achado à parte, fora do escopo original da Etapa 6**: `atualizar.sh` e
`scripts/build.sh` chamavam um pipeline antigo em Perl
(`build_data.pl`/`embed_dashboard.pl`, gerando `dashboard_data.json`/
`dashboard.html` — nada disso existe mais no fluxo atual). O próprio
README já afirmava (seção "Como surgiu") que esse fluxo Perl "não faz
mais parte do pipeline nem está neste repositório", mas os arquivos
continuavam commitados — quem rodasse `./atualizar.sh` manualmente
receberia um resultado desatualizado, sem nenhuma correção das Etapas
2-5. Removê-los (`atualizar.sh`, `scripts/build.sh` e os 6 `scripts/*.pl`)
ficou pendente de uma ação de exclusão em git que o ambiente sandbox
bloqueou por segurança (irreversível dentro da sessão, mesmo sendo
reversível via histórico do git) — fica pra você rodar localmente:
`git rm atualizar.sh scripts/build.sh scripts/build_data.pl scripts/compare_runs.pl scripts/embed_dashboard.pl scripts/verify.pl scripts/verify_mudanca1.pl scripts/verify_mudanca2.pl scripts/verify_mudanca3.pl scripts/verify_raw.pl`.
Isso não afeta a atualização automática — ela nunca chamou esses
arquivos.

**Descrições dos painéis** (texto visível na própria dashboard) revisadas
pra deixar explícito, onde antes só era implícito, que a comparação é em
R$/m² dentro do mesmo segmento (tipo de imóvel + faixa de metragem):
Ranking de Oportunidade (coluna "Gap Preço"/badge "Alerta preço"),
Prontidão para Campanha e Estoque × Demanda ("alinhamento de preço"/
"Alerta preço"), e Imóveis Prioritários para Campanha ("alinhamento de
preço"). Alertas, Perfil por Bairro, Valor de Oportunidade e o painel
"Preço por m²" já tinham sido atualizados nas Etapas 3-5.

## Segunda auditoria: leitura, datas e protocolo de segurança (2026-09-30)

Nova rodada, motivada por revisão direta das planilhas oficiais de ITBI
(583-586 mil linhas) — desta vez com um protocolo de segurança formal,
porque a dashboard vai integrar com um CRM e ser usada por outros
corretores: nenhuma mudança pode quebrar a versão em produção sem
aprovação explícita, passo a passo.

**Protocolo**: tag `pre-correcao-itbi` (rollback de 1 comando pro estado
anterior a esta rodada) + backup de `data.json`/`raw.json`/
`itbi_clean_log.json` em `backups/*.pre-correcao-itbi` + todo o trabalho
numa branch separada (`correcao-itbi-metodologia`, num `git worktree`
próprio — nunca no checkout que os LaunchAgents locais servem ao vivo).
Merge na `main` só acontece com aprovação explícita, depois de um
relatório final.

**Regra adicional**: mudar o SIGNIFICADO de um campo existente conta como
quebra, mesmo mantendo o nome — por isso todo achado desta rodada que
mexe em cálculo já existente vira campo NOVO, nunca uma reinterpretação
silenciosa de um campo que os painéis já leem.

**`scripts/validate_build.py`** (chamado por `build_data.py`, ver
"Automação" abaixo): 4 checagens antes de sobrescrever `site/data.json` —
layout de coluna (cabeçalho reconhecível em qualquer posição da aba +
28 colunas A-AB, olhando as 10 colunas que o pipeline lê), reconciliação
de linhas lidas vs. total real do `.xlsx`, nenhum bairro variando >30% em
`volume_primary_year` sem `ALLOW_LARGE_CHANGES=1` explícito no ambiente, e
formato de `data.json` íntegro (chaves que os painéis esperam). Qualquer
falha levanta `SystemExit` — o workflow do GitHub Actions para antes do
commit, a versão publicada anterior nunca é sobrescrita por um build ruim.

**Achado de leitura (diagnóstico, sem mudança de código)**: JAN-2024 e
OUT-2024 não estão sem cabeçalho — o cabeçalho está no MEIO/FIM da aba
(linha 12.152 de 13.152, e 21.028 de 21.030, respectivamente), não na
linha 1. O parser já lida bem com isso (procura o cabeçalho pelo
conteúdo, não pela posição). Colunas 27-29 (Z/AA/AB) têm nomes
duplicados/com erro de digitação em algumas abas, mas não são lidas pelo
pipeline hoje — sem efeito real.

**`volume_12m`/`trend_pct_12m`/`periodo_12m` (item 4)** — campos NOVOS,
aditivos. `volume_primary_year`/`trend_pct` continuam com o MESMO cálculo
de sempre (marcados **obsoletos** aqui na documentação — não no código —
até uma remoção futura aprovada pelo usuário) porque:
  - agrupam pela data do ARQUIVO/aba de origem (`sheet_year`), não pela
    data real da transação (coluna J) — 2,37% das linhas têm ano real
    diferente do arquivo em que aparecem (guia paga com atraso; casos
    extremos: guias de 1995 aparecendo no arquivo de 2024);
  - `volume_primary_year` é a média simples dos 3 anos-calendário,
    tratando 2026 (parcial, 7 meses) com o mesmo peso que 2024/2025
    (ano cheio) — acaba SUBESTIMANDO o volume corrente.

`volume_12m`/`trend_pct_12m` (`engine._compute_volume_12m`, espelhado em
`engine.js`) corrigem isso:
  - agrupam pela data REAL da transação, excluindo tudo antes de
    2024-01-01;
  - acham o último mês com dado real que não é um "lote incompleto"
    (heurística: um mês com menos de 50% da mediana dos 3 meses
    anteriores é descartado — protege contra guia que vaza pra dentro da
    aba do mês seguinte, ex: linhas com data real de agosto/2026
    aparecendo na aba JUL-2026 antes de a aba AGO-2026 existir);
  - **os 2 meses mais recentes com dado ficam de FORA da janela inteira**
    (ajuste de 2026-09-30 — a versão original desta seção deixava eles
    DENTRO da janela, só marcados; o usuário corrigiu: defasagem de guia
    paga com atraso significa que mesmo o mês "mais recente com dado"
    ainda está subcontado, e não deve entrar nem no volume nem na
    tendência). A janela de 12 meses termina 2 meses antes do mês mais
    recente com dado;
  - tendência = mesmo intervalo de 12 meses, comparado com os 12 meses
    imediatamente anteriores (não mais ano-cheio + 1º semestre);
  - `periodo_12m` (novo campo no topo do `data.json`) expõe
    `{inicio, fim, meses_incompletos}`;
  - `volume_recente_parcial` (novo campo por bairro) — contagem dos 2
    meses excluídos, só como indicador informativo separado; nunca entra
    em `volume_12m`/`trend_pct_12m`.

**Onde a dashboard passou a mostrar o quê**: Ranking, Visão Geral, Perfil
por Bairro e Mapa de Oportunidade agora exibem `volume_12m`/
`trend_pct_12m` com o período visível. A coluna "Demanda" do painel
Estoque × Demanda continua mostrando `volume_primary_year` DE PROPÓSITO —
ela alimenta `stock_demand_ratio`, que não foi recalculado nesta etapa;
trocar só o número exibido ali criaria uma conta que não bate com a razão
mostrada ao lado. Pelo mesmo motivo, o **Score** do Ranking de
Oportunidade continua usando a base antiga (`volume_primary_year`/
`trend_pct_for_score`) — recalcular o Score com a base de 12 meses é uma
mudança maior, registrada como pendente de decisão do usuário, não feita
silenciosamente aqui. Badge visível "Nota calculada com a metodologia
anterior — revisão pendente" no Ranking e na Visão Geral, enquanto isso
não for decidido.

**Achado notável, investigado a fundo**: Pinheiros mostra tendência
negativa na base nova (-5,4%) contra positiva na base antiga (+12,8% de
`growth_prev_pct`, mediado com -7,1% de `growth_h1_pct` = +2,8% final) —
a inversão de sinal **permanece** mesmo depois do ajuste da janela.
Causa raiz, confirmada mês a mês com a data real de transação: Pinheiros
teve um crescimento real e forte de vendas entre 2024 (~690/ano) e 2025
(~778/ano, +12,8%) — é esse salto que `growth_prev_pct` captura. Só que
esse crescimento **já tinha passado do pico** por volta de dez/2025 (85
vendas naquele mês, o maior do período) e vem desacelerando desde então —
os 12 meses mais recentes fechados (jul/2025-jun/2026, 746 vendas) já são
menores que os 12 meses imediatamente anteriores (jul/2024-jun/2025, 789
vendas). O método antigo mistura um comparativo ano-cheio já superado com
um comparativo de 1º semestre mais recente, e a média dos dois ainda dá
positivo porque o salto de 2024→2025 foi grande; o método novo olha só a
janela mais recente contra a anterior e captura a desaceleração que já
está em curso. As duas leituras são "verdadeiras" na própria janela — a
nova é mais atual.

Revalidado Python × JavaScript: 0 divergências em `volume_12m`,
`trend_pct_12m`, `periodo_12m` e `volume_recente_parcial` nos 49 bairros.

**Base congelada pra esta auditoria**: `SKIP_ITBI_SYNC=1` (env var) pula
`itbi_source.sync()` em `build_data.py` e usa só o `.xlsx` já em
`data/itbi_raw/` — a aba AGO-2026, que chegou durante o item 4, virou a
base oficial usada em TODO relatório antes×depois a partir daqui, até o
merge. Nunca setado pelo cron/GitHub Actions; só ligado manualmente nesta
branch. Reprodutibilidade confirmada: rodar de novo com a flag reproduz
`data.json`/`raw.json`/CSV byte a byte.

## Naturezas, valores e "vendas de mercado" (item 2 da auditoria de 2026-09-30)

**Volume de mercado, separado do giro.** `volume_12m`/`volume_primary_year`
continuam contando QUALQUER natureza residencial (giro é giro, decisão de
2026-09-25) — não mudaram. Dois campos novos, por cima:

- **`volume_mercado_12m`/`trend_pct_mercado_12m`** — só natureza
  "1.Compra e venda", mesma janela rolante de 12 meses do item 4. Virou o
  número PRINCIPAL de liquidez nos painéis (Ranking, Visão Geral, Perfil
  por Bairro, Mapa), rotulado "Vendas de mercado (12m)". `volume_12m`
  (giro) passa a aparecer como informação secundária, rotulado "Todas as
  transferências (12m)".
- **`volume_retomadas_12m`** — soma "17.Resolução da alienação fiduciária
  por inadimplemento" (retomada pelo banco) + "4.Arrematação (em leilão ou
  hasta pública)", mesma janela. Indicador à parte — não soma em
  `volume_mercado_12m` nem em `volume_12m`.

As demais naturezas (integralização de capital, dação, permuta, partilha
etc.) não ganham indicador próprio — ficam fora de `volume_mercado_12m` e
de qualquer cálculo de preço, mas continuam dentro do giro bruto
(`volume_12m`), como sempre.

**Quantas linhas saem de cada natureza** (dentro do universo já filtrado
por tipo de imóvel — apartamento/casa —, base congelada, 3 anos): a soma
`excluidos_natureza_nao_compra_venda` (5.654) agora vem quebrada por tipo
em `excluidos_natureza_nao_compra_venda_por_tipo` no
`site/itbi_clean_log.json`. As 5 maiores: Integralização de capital
(1.769), Dação em pagamento (849), Arrematação/leilão (670), Permuta
(557), Resolução de alienação fiduciária (409) — essas duas últimas são
exatamente o que alimenta `volume_retomadas_12m`.

**Valor irreal** — novo filtro na camada de preço: exclui "1.Compra e
venda" de 100% do imóvel com valor ≤ R$10 mil ou > R$100 milhões
(`clean_itbi.VALOR_MIN_REAL`/`VALOR_MAX_REAL`). 400 linhas excluídas na
base congelada — soma no `excluidos_valor_irreal` do log de limpeza.

**Achado notável, ao comparar giro × mercado nos 5 bairros de referência**:
Itaim Bibi mostra tendência de giro positiva (+2,1%) mas tendência de
mercado NEGATIVA (-4,7%) — o giro bruto está sendo sustentado por
transações de natureza não-mercado (financiamento/dação/etc.) crescendo,
enquanto a venda de mercado de verdade está caindo. Sem separar os dois,
esse bairro pareceria "esquentando" quando na verdade está esfriando.

| Bairro | Giro (`volume_12m`) | tendência giro | Mercado (`volume_mercado_12m`) | tendência mercado | Retomadas (`volume_retomadas_12m`) |
|---|---:|---:|---:|---:|---:|
| Moema | 521 | -7,0% | 445 | -8,4% | 6 |
| Vila Mariana | 1.173 | -6,0% | 1.023 | -9,3% | 22 |
| Tatuapé | 1.503 | -5,1% | 1.308 | -5,2% | 46 |
| Pinheiros | 746 | -5,4% | 669 | -5,9% | 10 |
| Itaim Bibi | 531 | **+2,1%** | 448 | **-4,7%** | 4 |

Revalidado Python × JavaScript: 0 divergências em `volume_mercado_12m`,
`trend_pct_mercado_12m` e `volume_retomadas_12m` nos 49 bairros.

**Achado extra, respondendo ao ponto 1a da revisão do item 2: bug real no
dedup por SQL.** A versão de 2026-09-29 de `dedup_by_sql()` usava a chave
SQL+valor+data, SEM complemento — confundindo unidades DIFERENTES do
mesmo lançamento com tabela de preço padronizada (mesmo SQL do
lote/torre-mãe, mesmo dia de fechamento, valor coincidente, complemento
diferente: ex. "AP 601" e "AP 1813"). Medido na base congelada: **373 das
622 "duplicatas" (60%) tinham complemento diferente** — eram vendas de
verdade sendo descartadas. Corrigido: `dedup_by_sql()` agora inclui
complemento na chave (coluna D, capturada em `parse_itbi.py` como novo
campo `complemento`), como o pedido original já especificava. Duplicatas
de verdade (mesmo SQL+valor+data+complemento) continuam removidas
normalmente. Por bairro (universo dos 49 bairros, 2024-2026):

| Bairro | Duplicatas (chave antiga) | Duplicatas (chave nova) | Vendas recuperadas |
|---|---:|---:|---:|
| Moema | 6 | 5 | 1 |
| Vila Mariana | 35 | 21 | 14 |
| Tatuapé | 67 | 16 | 51 |
| Pinheiros | 24 | 9 | 15 |
| Itaim Bibi | 9 | 8 | 1 |
| **Total (49 bairros)** | **622** | **249** | **373** |

As 3 checagens de segurança continuam passando com a chave nova (nenhum
bairro varia >30% em `volume_primary_year` — 373 linhas espalhadas em 49
bairros × 3 anos é pequeno demais pra disparar o alarme).

**Outliers de preço (P5-P95 por bairro+tipo+faixa)**: confirmado, já
estava sendo aplicado desde a auditoria de 2026-09-29 — não é novo neste
item. Por bairro (candidatos a preço = passaram nos filtros de tipo/
natureza/fração/valor/área; removidos = fora de P5-P95 dentro do seu
segmento bairro+tipo+faixa):

| Bairro | Candidatos a preço | Removidos por outlier |
|---|---:|---:|
| Moema | 1.133 | 115 |
| Vila Mariana | 2.360 | 241 |
| Tatuapé | 3.136 | 314 |
| Pinheiros | 1.456 | 147 |
| Itaim Bibi | 1.042 | 103 |

**Proporção transmitida < 100% (transferência parcial)**: confirmado
programaticamente — **zero** linhas com fração<100% têm `is_clean_sale=True`
ou `valor_m2` preenchido (checagem automatizada, 0 violações nas 33.450
linhas da camada limpa). Por bairro, linhas excluídas por esse motivo:

| Bairro | Excluídas por fração<100% |
|---|---:|
| Moema | 126 |
| Vila Mariana | 524 |
| Tatuapé | 496 |
| Pinheiros | 418 |
| Itaim Bibi | 178 |

**Composição de `volume_retomadas_12m`, confirmada**: só natureza "4."
(leilão/arrematação) + "17." (alienação fiduciária) — permuta ("15.") NÃO
entra, verificado linha a linha. Por bairro, na janela de 12 meses
(jul/2025-jun/2026):

| Bairro | Leilão (nat. 4) | Alienação fiduciária (nat. 17) | Soma = `volume_retomadas_12m` | Permuta (nat. 15, referência — não conta) |
|---|---:|---:|---:|---:|
| Moema | 3 | 3 | 6 | 10 |
| Vila Mariana | 15 | 7 | 22 | 11 |
| Tatuapé | 25 | 21 | 46 | 13 |
| Pinheiros | 5 | 5 | 10 | 9 |
| Itaim Bibi | 3 | 1 | 4 | 11 |

**Abrangência de cada número (ponto 3)** — dois escopos diferentes que não
devem ser confundidos:
  - `excluidos_natureza_nao_compra_venda_por_tipo` e `excluidos_valor_irreal`
    (no `itbi_clean_log.json`): **49 bairros da carteira** (depois de
    `resolve_bairros`), **pool de 2024-2026 inteiro** (não é janela de 12
    meses), e só dentro do universo já classificado como apartamento/casa
    (uso 10/12/14/20/25 — "prédio inteiro", uso 21/22, já saiu antes).
  - `volume_retomadas_12m` (campo do motor, por bairro): **49 bairros da
    carteira**, mas **janela rolante de 12 meses** (jul/2025-jun/2026, a
    mesma do item 4) e **qualquer uso residencial** (inclui "prédio
    inteiro", igual `volume_12m`/`volume_mercado_12m` — giro é giro).

**Compras na planta (uso IPTU do cadastro antigo, complemento indica
unidade residencial)** — regra aprovada (complemento contém AP/APTO/
APART/TORRE/BLOCO/CASA/UNIDADE, OU financiamento SFH/MCMV, E natureza
compra e venda), mas `volume_planta_12m` **ainda não implementado**: a
cobertura de bairro por voto de endereço (10,4% das 183.611 linhas
candidatas) é baixa demais pra virar um número confiável por bairro —
prédio novo não tem venda anterior no mesmo endereço pra "votar" o bairro.
Aguardando o item 3 (bairro por CEP) subir essa cobertura antes de
implementar.

## Item 3 (continuação): bairro por quadra fiscal do IPTU/GeoSampa

Depois de esgotar os métodos internos (endereço, CEP — ver seção acima),
o usuário baixou manualmente o cadastro fiscal do IPTU no GeoSampa (camada
Lote → download → cadastro → IPTU; portal legado, protegido por CAPTCHA,
sem download automatizável) — 3,92 milhões de linhas, 938MB. Só as 5
colunas necessárias (`sql`, `bairro`, `cep`, `logradouro`, `numero`) são
mantidas, comprimidas em `data/iptu_geosampa/iptu_2026_reduzido.csv.gz`
(23MB, gitignorado — `data/` já não entra no git). Lógica em
`scripts/iptu_geosampa.py`.

**SQL do GeoSampa ≠ SQL do ITBI, formatos diferentes**: no GeoSampa vem
como texto com hífen antes do dígito verificador ("0010030001-4", zeros à
esquerda preservados porque é texto, não número do Excel) — `normalize_sql`
do `parse_itbi.py` (que espera número Excel) não serve aqui;
`iptu_geosampa.setor_quadra_de_sql` tira tudo que não é dígito e usa os 6
primeiros (setor+quadra) dos 11.

**Normalização do campo "Bairro" do IPTU** (tem tanto lixo quanto o do
ITBI — TORRE/BLOCO/COND somam mais de 170 mil linhas cada, entre 3,92
milhões): remove acento, expande abreviação (JD, VL, V, STA, STO, PQ,
PRQ, CHAC, CID, CONJ, CJ, ENG — em QUALQUER token, não só o primeiro,
depois de um bug pego no meio do caminho: "JARDIM STO AMARO" só
normalizava certo se STO fosse o primeiro token). Dentro de cada quadra,
grafias parecidas (erro de digitação, truncamento) são agrupadas antes de
calcular maioria/confiança (`difflib.SequenceMatcher`, stdlib, sem
dependência nova) — pega casos como "VILA ESTER"/"VILA ESTHER"/
"VILA HESTER" e até truncamento no INÍCIO da string ("VILA CARMOZINA" →
"OZINA"/"ZINA" nalgumas linhas). Pureza (quadra com 1 bairro só) foi de
12,3% (bate com a medição prévia do usuário) pra 51,5% de quadras em
confiança "alta" (≥80% de concordância) depois de normalizar + agrupar —
23,3% "média" (60-79%) e 25,2% "baixa" (<60%, quase sempre fronteira real
entre bairros vizinhos, não erro de leitura — ex: uma quadra com "Jardim
América"/"Jardim Europa"/"Jardim Paulistano" misturados).

**`bairros_equivalencias.csv`** (arquivo editável pedido pelo usuário):
populado só com variações de grafia INEQUÍVOCAS de um dos 49 bairros
(erro de digitação claro, sem risco de confundir com outro bairro de
verdade) — ex: "INDIANOPLIS"→Indianópolis, "BROOKLYN"/"BROOKLIM"/
"BLOOKLIN"→Brooklin, "CHACARA SANTOANTONIO" (e variantes)→Chácara Santo
Antônio. **Deixados de fora de propósito**, por risco de mesclar bairros
DIFERENTES de verdade: "VILA MARIA"/"VILA MARINGA"/"VILA MARACANA"/
"VILA MARILENA"/"VILA MIRIAN" (parecidos com "Vila Mariana" só no texto —
São Paulo tem vários "Vila [nome próprio]" genuinamente distintos, Vila
Maria em especial é um bairro grande e conhecido, não é Vila Mariana),
"JARDIM PAULISTINHA"/"JARDIM PAULA"/"JARDIM AMELIA" (parecidos com
Jardim Paulista/América), "VILA N SRA CONCEICAO" (pode ser "Nossa
Senhora da Conceição", não necessariamente "Vila Nova Conceição").

**Correção de métrica (2026-09-30, mesma família de confusão do ponto 1
da rodada anterior)**: "cobertura"/"sem bairro" tinham virado, sem querer,
"caiu fora dos 49" — mas uma venda num bairro fora da carteira TEM
bairro, não é lacuna nenhuma. As duas métricas certas, separadas:

| | Revenda | Planta |
|---|---:|---:|
| (a) SEM NENHUM bairro — antes do IPTU | 104.572 (33,1%) | 60.718 (33,1%) |
| (a) SEM NENHUM bairro — depois do IPTU | 2.648 (**0,8%**) | 5.418 (**3,0%**) |
| Meta de 90% = recebe algum bairro (inverso de a) | 66,9% → **99,2%** | 66,9% → **97,0%** |
| (b) Atribuído aos 49 (participação da carteira) — antes | 104.828 (33,2%) | 38.557 (21,0%) |
| (b) Atribuído aos 49 (participação da carteira) — depois | 111.508 (35,3%) | 44.835 (24,4%) |

Com a métrica certa, **a meta de 90% é batida com folga nos dois
universos** (99,2% e 97,0%) — os "38,6%/28,2%" da versão anterior deste
relatório mediam (b), não (a), e por isso pareciam uma lacuna que não
existia. (b) — quanto do volume cai especificamente nos 49 bairros — é
só um dado descritivo (quanto da cidade nossa carteira representa,
~9-11%), não uma falha de método.

## Item 3: simulação da regra de prioridade (proposta pelo usuário)

Ordem proposta: 1º campo Bairro (ITBI, direto) → 2º voto por endereço →
3º quadra IPTU confiança ALTA → 4º CEP (8 dígitos) → 5º quadra IPTU
confiança MÉDIA → 6º "incerto" (confiança baixa ou nenhum método
resolveu — conta no total da cidade, não entra em nenhum dos 49).
Simulado sobre `volume_mercado_12m` (só "1.Compra e venda", janela de
12 meses congelada, jul/2025-jun/2026) nos 5 bairros de referência —
**ainda não ligado no `engine.py`**, só simulação:

| Bairro | `volume_mercado_12m` ANTES (produção hoje) | DEPOIS (cascata de 5 métodos) |
|---|---:|---:|
| Moema | 453 | 629 (+39%) |
| Vila Mariana | 1.043 | 2.605 (**+150%**) |
| Tatuapé | 1.340 | 3.699 (**+176%**) |
| Pinheiros | 677 | 1.310 (+93%) |
| Itaim Bibi | 436 | 718 (+65%) |

**O salto é grande — investiguei se era bug antes de reportar; não é.**
CEP (8 dígitos) é um método bem mais amplo que voto por endereço: só
Tatuapé tem ~400 CEPs distintos cujo voto majoritário é o próprio
Tatuapé, cada um com 30-60 votos quase unânimes (ex.: CEP 03066065, 61
votos, 100% Tatuapé) — volume represado que o voto por endereço (exige
aquele endereço exato já ter uma venda com bairro confiável) nunca
alcançava, mas que o CEP (a área postal inteira) recupera de uma vez.
Bairros grandes e consolidados (Tatuapé, Vila Mariana) ganham
desproporcionalmente mais que bairros menores (Itaim Bibi, Moema) porque
têm mais CEPs "seus" represados.

Entrada por método, por bairro (quantas linhas novas cada método
contribuiu):

| Bairro | campo_original | voto_endereço | quadra_alta | CEP | quadra_média |
|---|---:|---:|---:|---:|---:|
| Moema | 256 | 197 | 23 | 134 | 19 |
| Vila Mariana | 536 | 507 | 672 | 842 | 48 |
| Tatuapé | 799 | 541 | 832 | 1.393 | 134 |
| Pinheiros | 456 | 221 | 333 | 244 | 56 |
| Itaim Bibi | 173 | 263 | 1 | 254 | 27 |

**"Incerto" (nenhum dos 5 métodos resolve)**: 64,6% de todo o universo
compra-e-venda/12 meses da CIDADE (não só planta) — consistente com (b)
acima (~35% cai nos 49, 65% não), confirma que não é bug, é só reflexo de
quanto da cidade fica fora da carteira mesmo.

**Ressalva metodológica**: esta simulação usa o parse bruto, sem passar
pela deduplicação (`dedup_by_sql`) — por isso o "ANTES" aqui (1.340 pra
Tatuapé) é um pouco maior que o `volume_mercado_12m` real publicado
(1.308, relatório do item 2) — a diferença (~2%) é o efeito da dedup, que
tanto "antes" quanto "depois" sofreriam igualmente em produção; não muda
a magnitude do salto relativo.

Revalidação Python × JavaScript: não aplicável ainda — só simulação,
nada ligado no `engine.py`/`engine.js`. Regra de prioridade, `volume_planta_12m`
e `volume_total_12m` seguem pendentes de aprovação do usuário.

## Item 3: 4 conferências antes de aprovar a regra de prioridade (2026-09-30)

**Correção de metodologia encontrada rodando a conferência**: a simulação
anterior deduplicava o conjunto inteiro da cidade (315.658 linhas) numa
ordem diferente da produção (produção resolve bairro por endereço e
DESCARTA endereço sem nenhum bairro reconhecido, só depois deduplica o
que sobrou — 50.332 linhas). Deduplicar antes de descartar deixava o
"antes" da simulação artificialmente baixo (ex.: Moema 292 em vez de
445). Corrigido: agora recupera bairro por voto de endereço SEM
descartar (pra poder aplicar a cascata nos que sobrariam), mas dedupe
**depois** dessa recuperação, igual à ordem real da produção. `parse_itbi.py`
ganhou um campo novo (`cep`, cru, coluna G) pra dar suporte a isso e ao
item 4.

**1) Revenda × planta, separados** — `volume_mercado_12m`, mesma janela
(jul/2025-jun/2026), com dedup real:

| Bairro | ANTES (produção) | DEPOIS revenda | DEPOIS planta | DEPOIS total |
|---|---:|---:|---:|---:|
| Moema | 445 | 655 | 672 | 1.327 |
| Vila Mariana | 1.024 | 2.484 | 715 | 3.199 |
| Tatuapé | 1.340 | 3.710 | 660 | 4.370 |
| Pinheiros | 670 | 1.298 | 1.355 | 2.653 |
| Itaim Bibi | 448 | 728 | 35 | 763 |

Confirma o padrão: em Pinheiros, planta (1.355) supera revenda recuperada
(1.298) — bairro com muito lançamento recente. Em Itaim Bibi é o oposto
(728 revenda vs. 35 planta) — bairro mais consolidado, menos terreno
disponível pra lançar.

**2) Taxa de giro (unidades residenciais do IPTU) — concluído** depois
do reenvio do `IPTU_2026.zip`. Duas mudanças permanentes pedidas pelo
usuário:
  - o `.zip` original agora tem uma CÓPIA em
    `data/iptu_geosampa/raw/IPTU_2026.zip` (gitignorado) — nunca movido
    nem apagado de `~/Downloads`;
  - a versão reduzida ganhou uma 6ª coluna, `tipo_uso` ("TIPO DE USO DO
    IMOVEL"), resto do cadastro continua descartado. `iptu_geosampa.py`
    ganhou `reduzir_arquivo_original()` (regenera a partir do `.zip`
    sempre que precisar) e `contar_unidades_residenciais_por_bairro()`
    (nova, reutilizável).

Unidade residencial = só "Apartamento em condomínio" + "Residência"
(as 2 categorias que o usuário pediu literalmente — de propósito não
inclui "Residência coletiva"/"Residência e outro uso", ambíguas e
pequenas: ~12 mil linhas juntas contra ~650 mil das duas principais).
Bairro de cada unidade resolvido com uma cascata TODA dentro do cadastro
do IPTU (nunca cruza com o ITBI): campo Bairro → voto por endereço (só
dentro do IPTU) → quadra alta → CEP (só dentro do IPTU) → quadra média.
1.062.509 de 2.831.160 unidades residenciais da cidade (37,5%) caem nos
49 bairros — coerente com a participação de ~31-35% medida no ponto 3
(a carteira representa parte substancial do estoque residencial
mesmo sendo minoria territorial da cidade).

**Taxa de giro = `volume_mercado_12m` (revenda + planta, cascata do item
3) ÷ unidades residenciais**, todos os 49, ordenados (3 acima de 10%):

| Bairro | vendas_mercado_12m | unidades_IPTU | taxa de giro |
|---|---:|---:|---:|
| **Vila Firmiano Pinto** | 688 | 2.328 | **29,55%** ⚠️ |
| **Jardim Vila Mariana** | 135 | 1.000 | **13,50%** ⚠️ |
| **Vila Olímpia** | 2.092 | 16.266 | **12,86%** ⚠️ |
| Lapa | 5.252 | 60.962 | 8,62% |
| Pinheiros | 2.653 | 31.759 | 8,35% |
| Brooklin | 2.774 | 34.913 | 7,95% |
| Jardins | 136 | 1.780 | 7,64% |
| Alto da Boa Vista | 733 | 9.732 | 7,53% |
| Perdizes | 3.343 | 46.502 | 7,19% |
| Moema | 1.327 | 19.020 | 6,98% |
| Jardim América | 1.186 | 17.011 | 6,97% |
| Indianópolis | 1.219 | 20.189 | 6,04% |
| Planalto Paulista | 472 | 8.075 | 5,85% |
| Itaim Bibi | 763 | 14.038 | 5,44% |
| Consolação | 2.292 | 42.286 | 5,42% |
| Cambuci | 1.904 | 35.287 | 5,40% |
| Mooca | 3.947 | 73.825 | 5,35% |
| Campo Belo | 1.304 | 25.733 | 5,07% |
| Ipiranga | 3.750 | 74.205 | 5,05% |
| Jardim das Bandeiras | 27 | 540 | 5,00% |
| Bosque da Saúde | 559 | 11.238 | 4,97% |
| Vila Nova Conceição | 366 | 7.371 | 4,97% |
| Pompéia | 594 | 12.050 | 4,93% |
| Paraíso | 814 | 17.713 | 4,60% |
| Santa Cecília | 2.193 | 48.435 | 4,53% |
| Vila Mariana | 3.199 | 73.642 | 4,34% |
| Higienópolis | 468 | 10.872 | 4,30% |
| Bela Vista | 2.410 | 57.658 | 4,18% |
| Jardim Paulista | 1.683 | 41.108 | 4,09% |
| Sumaré | 206 | 5.077 | 4,06% |
| Vila da Saúde | 367 | 9.259 | 3,96% |
| Vila Madalena | 647 | 17.468 | 3,70% |
| Tatuapé | 4.370 | 118.485 | 3,69% |
| Mirandópolis | 538 | 15.128 | 3,56% |
| Ibirapuera | 635 | 19.172 | 3,31% |
| Vila Gumercindo | 308 | 9.458 | 3,26% |
| Pacaembu | 48 | 1.572 | 3,05% |
| Vila Uberabinha | 31 | 1.111 | 2,79% |
| Chácara Inglesa | 378 | 14.124 | 2,68% |
| Jardim da Glória | 87 | 3.395 | 2,56% |
| Vila Cordeiro | 76 | 2.982 | 2,55% |
| Jardim Europa | 54 | 2.196 | 2,46% |
| Chácara Santo Antônio | 349 | 16.423 | 2,13% |
| Jardim Petrópolis | 20 | 1.113 | 1,80% |
| Jardim Paulistano | 93 | 5.378 | 1,73% |
| Jardim Santo Amaro | 17 | 1.065 | 1,60% |
| Jardim Caravelas | 22 | 1.799 | 1,22% |
| Jardim dos Estados | 9 | 1.066 | 0,84% |
| Jardim Novo Mundo | 5 | 700 | 0,71% |

Giro anual saudável de mercado costuma ficar na casa de 3-8%; os 3
sinalizados merecem checagem manual antes de confiar no número — são
bairros pequenos (poucas unidades no denominador), então um efeito
pontual (ex.: um lançamento grande recuperado via CEP/quadra, ou
"unidades residenciais" subcontadas nesse bairro especificamente) pode
estar inflando a taxa desproporcionalmente. Não investiguei caso a caso
ainda — fica pra quando/se você quiser aprofundar.

**3) Fechamento da conta** — com dedup real, "fora da carteira" separado
de "incerto" (antes misturados no "64,6%"):

| | Total | Nos 49 (soma) | Fora da carteira | Incerto |
|---|---:|---:|---:|---:|
| Revenda (mercado) | 105.897 | 37.560 (35,5%) | 67.504 (63,7%) | 833 (0,8%) |
| Planta | 75.426 | 18.983 (25,2%) | 54.173 (71,8%) | 2.270 (3,0%) |
| **Total** | **181.323** | **56.543 (31,2%)** | **121.677 (67,1%)** | **3.103 (1,7%)** |

Fecha exatamente (soma + fora + incerto = total nos 3 casos). "Incerto"
de verdade (nenhum método acha NENHUM bairro) é pequeno — 1,7% da
cidade; os outros 67,1% têm bairro, só não é um dos 49.

**4) `scripts/bairros_mercado.csv`** (gerado, 5.857 linhas, 44 dos 49
bairros com pelo menos 1 nome de cadastro) — região de cada bairro
definida pelos CEPs (5 dígitos) cujo voto majoritário (linhas do ITBI com
bairro direto confiável) é aquele bairro; dentro da região, conta TODOS
os nomes crus do campo Bairro do IPTU (sem nenhum mapeamento aplicado).
Conferido contra o exemplo do usuário — região de Moema: MOEMA (2.525),
INDIANOPOLIS (2.189), PLANALTO PAULISTA (378), VILA UBERABINHA (354) —
mesma ordem de grandeza do que você tinha achado (números diferentes
porque a região exata usada foi outra). Linha de corte: nomes com menos
de 5 imóveis foram descartados (ruído). Coluna `bairro_mercado` vazia,
pronta pra você preencher — nenhum mapeamento foi aplicado.

5 bairros dos 49 ficaram sem nenhum CEP5 mapeado (Vila Cordeiro, Jardim
Caravelas, Jardim Santo Amaro, Vila Uberabinha, Jardim Vila Mariana) —
bairros pequenos/enclaves sem CEP5 próprio majoritário; não entram no
CSV ainda.

Nada ligado no `engine.py`. Regra de prioridade segue sem aprovação.

## Metodologia dos painéis

Pesos, limiares e fórmulas exatas estão comentados em `scripts/engine.py`
(cada função referencia a lógica original). Resumo por painel:

1. **Ranking de Oportunidade** — bairros por score (50% z-score do volume
   médio anual de vendas residenciais, pool 2024–2026 + 50% z-score da
   tendência de crescimento), normalizado 0–100 entre os 49 bairros.
2. **Prontidão para Campanha** — score combinando 6 sinais (liquidez/tendência
   15%, estoque compatível 20%, alinhamento de preço 15%, captação ativa 15%,
   qualidade×cobertura dos imóveis prioritários 25%, concentração de achados
   de valor 10%).
3. **Perfil por Bairro** — metragem/preço/dormitórios/vagas que mais vendeu,
   com fallback para estimativa regional (vizinhos até 3km) quando a amostra
   do bairro é baixa (< 5 transações ou < 5 imóveis no perfil).
3b. **Estoque × Demanda** — tabela com todos os 49 bairros: quantos anúncios
   ativos hoje batem o perfil vencedor vs. o volume médio anual de vendas
   (pool 2024–2026), com drill-down pra ver os anúncios específicos que
   compõem esse estoque.
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
   (só em bairros com 10+ vendas/ano em média, 2024–2026 — mediana confiável).

## Filtros (bairro + faixa de preço)

O painel "Filtros" no topo do site deixa selecionar um ou mais dos 49
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
sobre os 49 bairros inteiros (inclusive como "doadores" de estimativa
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
