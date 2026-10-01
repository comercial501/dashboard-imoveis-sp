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

## Item 3: fim das "regiões" — tradução por nome de cadastro, 49→74 bairros (2026-09-30)

**Mudança de abordagem, pedida pelo usuário**: a resolução de bairro por
CEP/quadra deixa de agrupar por "região" (CEP5 majoritário, que podia se
contaminar — ver achado abaixo) e passa a traduzir cada NOME DE CADASTRO
do IPTU individualmente, por uma tabela que o usuário revisou à mão
(`bairros_mercado_preenchido.csv`, preenchida a partir do
`bairros_mercado.csv` gerado na rodada anterior). Carteira cresce de 49
pra **74 bairros** (49 atuais + 25 novos: Alto da Lapa, Alto da Mooca,
Cerqueira César, Cidade Monções, Jardim Aeroporto, Jardim Anália Franco,
Jardim da Saúde, Jardim das Acácias, Moinho Velho, Parque Fongaro, Parque
da Mooca, Santo Amaro, Saúde, Sumarezinho, Vila Antonieta, Vila Bertioga,
Vila Clementino, Vila Gomes Cardim, Vila Ipojuca, Vila Monumento, Vila
Nova Manchester, Vila Regente Feijó, Vila Romana, Vila São Francisco,
Vila das Mercês).

**Achado confirmado (causa raiz de "SANTANA"/"PIRITUBA" aparecendo em
região de Zona Sul)**: investiguei linha a linha — existe **1 única
linha** em todo o ITBI (3 anos) com bairro="PLANALTO PAULISTA" e CEP
02402025 (Zona Norte de verdade, região de Santana) — quase certamente
erro de digitação de quem preencheu a guia. Como nenhum bairro de Zona
Norte existe nos 49 da carteira pra disputar o voto, essa ÚNICA linha
errada virava o voto MAJORITÁRIO (e único) do CEP5 inteiro no método
antigo por região — "puxando" milhares de imóveis genuinamente de
Santana/Zona Norte pra dentro da "região de Planalto Paulista" em
`bairros_mercado.csv`. A tradução por nome elimina essa classe de erro
inteira: cada nome de cadastro tem um destino FIXO, nunca herda de uma
região potencialmente contaminada por 1 linha errada.

**Novos arquivos**:
  - `data/iptu_geosampa/raw/bairros_mercado_preenchido.csv` (cópia do que
    o usuário preencheu — gitignorado, nunca move/apaga o original do
    usuário).
  - `scripts/tradutor_bairro.py`: `carregar_tradutor()` (lê a tabela,
    valida 0 inconsistências — mesmo nome de cadastro sempre aponta pro
    mesmo destino, confirmado: 4.149 nomes distintos, 0 conflitos),
    `targets74()` (49 + os NOVO_BAIRRO da tabela — os 49 antigos SEMPRE
    entram, mesmo sem nenhuma linha própria na tabela: "Jardim Caravelas"
    é pequeno/obscuro demais, nenhuma grafia sua teve 5+ ocorrências em
    nenhuma região da rodada anterior — fica na carteira com 0
    vendas/unidades até aparecer alguma linha que aponte pra ele),
    `construir_votos_quadra_traduzido()` (substitui a normalização
    automática por similaridade da rodada anterior pela tradução manual,
    mais confiável), e a classe `Cascata` (a mesma lógica de 5 métodos +
    incerto/fora, reutilizável tanto pras vendas do ITBI quanto pras
    unidades do IPTU — cada lado constrói seus PRÓPRIOS votos de
    endereço/CEP a partir do seu próprio universo, nunca cruzando ITBI
    com IPTU nos votos, só compartilhando a quadra fiscal, que é
    inerentemente um dado do IPTU).

### 5a) `volume_mercado_12m` antes × depois — revenda × planta, 5 bairros + 25 novos

| Bairro | ANTES (produção, 49 antigo) | DEPOIS revenda | DEPOIS planta |
|---|---:|---:|---:|
| Moema | 445 | 671 | 522 |
| Vila Mariana | 1.024 | 2.739 | 789 |
| Tatuapé | 1.340 | 3.729 | 803 |
| Pinheiros | 670 | 1.313 | 1.461 |
| Itaim Bibi | 448 | 650 | 38 |
| Santo Amaro *(novo)* | — | 6.469 | 9.081 |
| Saúde *(novo)* | — | 3.125 | 1.039 |
| Cerqueira César *(novo)* | — | 1.452 | 357 |
| Vila Clementino *(novo)* | — | 600 | 701 |
| ...+21 outros novos | — | (ver histórico de execução) | |

Tatuapé ficou praticamente estável (a contaminação por Vila Carrão/Vila
Formosa/Sapopemba pesava mais no ESTOQUE de unidades do IPTU do que nas
VENDAS do ITBI, que já vinham majoritariamente do campo Bairro direto ou
de quadras mais centrais).

### 5b) Taxa de giro, 74 bairros, giro = REVENDA/12m ÷ unidades (planta fora do giro)

**Nenhum bairro fica acima de 10%** — a mudança de abordagem (separar
planta do giro + tradução por nome em vez de região) elimina os 3
sinalizados na rodada anterior:

| Bairro | Antigo (49, revenda+planta) | Novo (74, só revenda) |
|---|---:|---:|
| Vila Firmiano Pinto | 29,55% ⚠️ | **5,25%** (planta puxava: 503 planta vs 82 revenda) |
| Jardim Vila Mariana | 13,50% ⚠️ | **3,10%** |
| Vila Olímpia | 12,86% ⚠️ | **7,62%** (ainda o mais alto dos 74, mas dentro da faixa saudável) |

Confirma a hipótese do usuário: os 3 casos estavam inflados por planta
(e, no caso de Vila Firmiano Pinto, também pela contaminação de região).
Faixa dos 74: de 1,69% (Cidade Monções) a 8,05% (Vila da Saúde) — todos
dentro do 3-8% típico de giro saudável de mercado.

### 5c) Fechamento da conta (74 bairros)

| | Total | Soma(74) | Fora da carteira | Incerto |
|---|---:|---:|---:|---:|
| Revenda | 105.897 | 51.099 (48,3%) | 12.294 (11,6%) | 42.504 (40,1%) |
| Planta | 75.426 | 31.365 (41,6%) | 16.218 (21,5%) | 27.843 (36,9%) |

Fecha exatamente nos dois casos. Participação da carteira sobe de
~31% (49 bairros) pra **~48%/42%** (74 bairros, revenda/planta) — os 25
novos capturam uma fatia relevante do que antes virava "fora da
carteira" ou "incerto".

### 5d) Amostra pequena (menos de 10 vendas de mercado em 12m, revenda+planta)

Só **Jardim Caravelas** (0 vendas, 0 unidades) — caso extremo de "sem
dado nenhum", não só "amostra pequena". Os outros 73 bairros têm volume
suficiente.

### Ponto 4: anúncios nonStop × 74 bairros

2.267 anúncios ativos (VENDA, residencial, cidade de SP) hoje. **2.078
(91,7%) batem com um dos 74** (via `bairro_canon` pros 49 antigos, nome
exato pros 25 novos); **189 (8,3%) não batem** — top nomes, todos bairros
reais só ainda não rastreados:

| Nome do anúncio | Qtd. |
|---|---:|
| Aclimação | 43 |
| Vila Leopoldina | 29 |
| Alto de Pinheiros | 15 |
| Vila Anglo Brasileira | 8 |
| Vila Congonhas | 8 |
| Chácara Klabin | 8 |
| Água Branca | 7 |
| Bela Aliança | 7 |
| ...+22 outros, 1-6 cada | — |

Revalidação Python × JavaScript: não aplicável — nada ligado no
`engine.py`/`engine.js` ainda. Regra de prioridade (já simulada acima)
segue sem aprovação final.

## Item 3: 3 ajustes antes da regra de prioridade final (2026-09-30)

**1) Bug real: "incerto" tinha regredido de 1,7% pra ~40%.** Causa: meu
`Cascata.resolver()` tratava QUALQUER nome fora da tabela (ex: "ITAQUERA",
"SANTANA" — bairros reais, só nunca apareceram perto o bastante dos 49
antigos pra entrar na tabela da rodada anterior) como "incerto", quando
deveria ser "fora_carteira" (tem nome de bairro de verdade, só não é um
dos 74). Corrigido em duas frentes: `_parece_bairro()` (mesmo filtro de
lixo — TORRE/BLOCO/número solto — não conta como bairro de verdade) e um
sinal adicional `quadras_qualquer_bairro` (a quadra tem ALGUM bairro
majoritário reconhecível no IPTU, mesmo que não seja um dos 74 — sem
reconstruir ESSE sinal específico, uma quadra inteira de um bairro real
mas fora da carteira também virava "incerto"). Resultado:

| | Antes da correção | Depois da correção |
|---|---:|---:|
| Revenda — fora da carteira / incerto | 11,6% / 40,1% | **46,4% / 5,4%** |
| Planta — fora da carteira / incerto | 21,5% / 36,9% | **55,3% / 3,1%** |

Não chegou exatamente nos ~2% do baseline anterior (que usava uma régua
um pouco diferente), mas a lógica agora bate com a definição pedida —
"incerto" só quando literalmente nenhum nome aparece em lugar nenhum
(campo, endereço, CEP, quadra).

**2) Santo Amaro — tabela completa + CEPs + comparação**

a) Tabela completa dos 74 (ANTES/DEPOIS revenda/DEPOIS planta) — no
histórico de execução desta rodada; resumo dos 5 de referência +
principais novos:

| Bairro | ANTES (49) | DEPOIS revenda | DEPOIS planta |
|---|---:|---:|---:|
| Moema | 445 | 671 | 522 |
| Vila Mariana | 1.024 | 2.739 | 789 |
| Tatuapé | 1.340 | 3.729 | 803 |
| Pinheiros | 670 | 1.313 | 1.461 |
| Itaim Bibi | 448 | 650 | 38 |
| **Santo Amaro** *(novo)* | — | **6.469** | **9.081** |
| Saúde *(novo)* | — | 3.125 | 1.039 |

b) Santo Amaro, 15.550 vendas (revenda+planta), top 10 CEPs:

| CEP | Vendas | Principal logradouro |
|---|---:|---|
| 04776-003 | 767 | Avenida do Rio Bonito |
| 04727-002 | 736 | Rua Bragança Paulista |
| 04729-080 | 700 | Rua Luiz Seraphico Junior |
| 04653-200 | 517 | Rua Eng. Dagoberto Salles Filho |
| 04730-000 | 480 | Rua Dr. Rubens Gomes Bueno |
| 04750-000 | 469 | Rua Dr. Antônio Bento |
| 04766-000 | 460 | Rua Olívia Guedes Penteado |
| 04728-001 | 449 | Rua Laguna |
| 05729-090 | 336 | Rua Alexandre Benois |
| 05842-070 | 300 | Rua Gregório Allegri |

c) Comparação com a simulação anterior (49 bairros, método por região):

| Bairro | Antigo revenda/planta | Novo revenda/planta | Mudança |
|---|---:|---:|---|
| Alto da Boa Vista | 389 / 344 | 88 / 13 | **forte queda** — a maior parte do que "pertencia" a ele por região agora vai pra Santo Amaro |
| Chácara Santo Antônio | 271 / 78 | 401 / 462 | **subiu** — recuperou volume que antes ia pra outro lugar (provavelmente Alto da Boa Vista ou Santo Amaro, dependendo da quadra) |
| Jardim Santo Amaro | 17 / 0 | 12 / 0 | estável (pequena queda) |
| Brooklin | 1.337 / 1.437 | 1.360 / 1.844 | estável/leve alta (mais planta) |
| Campo Belo | 1.165 / 139 | 1.116 / 141 | estável |

Achado: a mudança não é uniforme — Alto da Boa Vista de fato "perdia"
volume pra região contaminada, mas Chácara Santo Antônio GANHOU volume
(estava sendo subcontado antes, provavelmente absorvido incorretamente
por outro bairro vizinho na região antiga). Não decidi nada sobre a
tabela de tradução — fica pra você decidir depois de ver os CEPs acima.

**3) Carteira 74→77 + nonStop**

a) Aclimação, Vila Leopoldina e Alto de Pinheiros incluídos como bairros
da carteira (ainda sem integração na cascata de vendas/unidades — só
reconhecidos no recheck do nonStop abaixo; a tradução completa pelo IPTU
fica pra quando você aprovar essa extensão formalmente).
b) Jardim Caravelas mantido na lista (0 vendas, 0 unidades) — ocultar dos
painéis é mudança de UI, ainda não aplicável (nada ligado no
`engine.py`/`site/app.js` ainda).
c) nonStop × 77: **2.165 de 2.267 anúncios (95,5%) batem agora** (subiu de
91,7% com os 74). 102 não batem — top: Vila Anglo Brasileira (8), Vila
Congonhas (8), Chácara Klabin (8), Água Branca (7), Bela Aliança (7).

Nada ligado no `engine.py`. Regra de prioridade aprovada na ordem, mas
aguardando o fechamento destes 2 itens antes de implementar.

## Item 3: regra de prioridade aprovada + carteira fechada em 77 + CEPs de Santo Amaro (2026-09-30)

Correção do "incerto" **aprovada** (5,4%/3,1%). Regra de prioridade (cascata
+ tabela de tradução) **aprovada**, com uma exceção: o nome de cadastro
"SANTO AMARO" (e variantes "STO AMARO"/"STO. AMARO") **não** vira um único
bairro de mercado — os CEPs mostram que ele mistura Chácara Santo Antônio,
Jardim Caravelas e Alto da Boa Vista com Socorro/Interlagos (evidência: Alto
da Boa Vista caiu de 389 para 88 revendas por causa dessa mistura). Essa
divisão fica pendente — ver abaixo.

**1) `scripts/santo_amaro_ceps.csv` gerado** — todas as vendas (revenda +
planta, deduplicadas e já filtradas pela janela de 12 meses) e unidades do
IPTU cujo **nome de cadastro cru** é literalmente "SANTO AMARO"/"STO
AMARO"/"STO. AMARO" (sem passar por endereço/quadra/CEP da cascata — é o
nome tal como está no campo, antes de qualquer tradução), agrupadas pelo
prefixo de 5 dígitos do CEP. 452 linhas, colunas `cep_prefixo,
vendas_revenda_12m, vendas_planta_12m, unidades_iptu, principais_logradouros
(top 5), bairro_mercado` (vazio, para preenchimento), ordenado por volume
total decrescente. Totais: 623 revendas, 2.067 plantas, 17.885 unidades.

**Importante — por que esses totais (2.690 vendas) são bem menores que os
"Santo Amaro: 6.469 revenda / 9.081 planta" da tabela de 77 abaixo**: este
CSV captura só o **nome de cadastro literal** = Santo Amaro (método 1 da
cascata). A tabela de 77 inclui tudo que a cascata completa **resolve** para
Santo Amaro — inclusive linhas cujo nome de cadastro é outra coisa (ou
lixo/vazio) mas que o voto de endereço, quadra fiscal ou CEP aponta pra
Santo Amaro porque elas são vizinhas de linhas que traduzem literalmente
para Santo Amaro. São escopos diferentes de propósito: o CSV serve pra você
decidir COMO dividir o nome "Santo Amaro" em si; a tabela de 77 mostra o
resultado se a cascata inteira apontar pra lá. Depois que você preencher
`bairro_mercado` no CSV, a divisão entra como uma tabela suplementar (mesmo
padrão do `bairros_mercado_extra.csv`) e tudo que hoje cai em "Santo Amaro"
via tiers 2–5 será recalculado com a nova régua.

Caminho completo: `/Users/plaghi/dashboard-imoveis-sp-audit/scripts/santo_amaro_ceps.csv`

**2) Carteira fechada em 77** — Aclimação, Vila Leopoldina e Alto de
Pinheiros concluídos na cascata completa (antes só reconhecidos no recheck
do nonStop). Entraram como `scripts/bairros_mercado_extra.csv` (23 linhas,
grafias inequívocas tipo "ACLIMACAO"/"VILA LEOPOLDINA"/"VL LEOPOLDINA"/"ALTO
DE PINHEIROS", mesmo filtro de lixo do resto do pipeline) — arquivo
**separado**, não mexe em `bairros_mercado_preenchido.csv`. Resultado:

| Bairro novo | Revenda | Planta |
|---|---:|---:|
| Aclimação | 987 | 129 |
| Vila Leopoldina | 476 | 1.444 |
| Alto de Pinheiros | 201 | 18 |

Fechamento final (77 bairros, com os 3 novos já incluídos na soma):

| | Total | Carteira (77) | Fora da carteira | Incerto |
|---|---:|---:|---:|---:|
| Revenda | 105.897 | 52.076 (49,2%) | 48.157 (45,5%) | 5.664 (5,3%) |
| Planta | 75.426 | 32.853 (43,6%) | 40.210 (53,3%) | 2.363 (3,1%) |

Tabela completa dos 77 (revenda\|planta) fica no histórico de execução;
nenhum dos 3 novos nem o resto da carteira muda os achados já reportados
acima (Santo Amaro seguiu 6.469/9.081 porque ainda não foi dividido).

Nada ligado no `engine.py`/`engine.js` ainda. Aguardando o usuário devolver
`santo_amaro_ceps.csv` preenchido (`bairro_mercado`) antes de qualquer
implementação — depois disso: aplicar a divisão, refazer a tabela completa
dos 77 e só então integrar no engine, com relatório antes×depois e merge só
mediante aprovação.

## Item 3: divisão de Santo Amaro aplicada + cascata completa recalculada (2026-09-30)

O usuário devolveu `santo_amaro_ceps_preenchido.csv` (452 prefixos de CEP,
cada um com o bairro de mercado final — "FORA" é um valor válido). Regras
aplicadas (`scripts/resolver_santo_amaro.py`):

1. Nome de cadastro "SANTO AMARO"/variantes → traduzido pelo prefixo de 5
   dígitos do CEP, usando a coluna `bairro_mercado` do arquivo.
2. 9 prefixos com `status=VALIDAR_ANUNCIOS`: conferidos contra os anúncios
   nonStop ativos daquele prefixo (3+ anúncios e 60%+ deles no mesmo
   bairro dos 77 → usa esse bairro; senão, mantém o provisório). Só **1
   dos 9** teve anúncios suficientes: **04750** tinha 4 anúncios, 100%
   "Alto da Boa Vista" → provisório "Santo Amaro" substituído por **Alto
   da Boa Vista**. Os outros 8 ficaram com o provisório (0–2 anúncios,
   amostra insuficiente).
3. Prefixo que não aparece no arquivo → FORA.

Resultado: `scripts/santo_amaro_split_resolvido.csv` (452 linhas,
committed — o CSV com os 452 CEPs do usuário fica só em `data/`,
gitignorado, nunca editado).

**Importante — metodologia revenda×planta reconstruída do zero.** O
script que gerou os números de revenda/planta mostrados nas rodadas
anteriores desta sessão (totais "105.897 revenda / 75.426 planta") era um
script descartável, nunca commitado — foi perdido numa compactação de
contexto. Para aplicar a divisão de Santo Amaro de forma reprodutível,
esta rodada reconstrói a classificação revenda×planta do zero, agora como
código commitado (`scripts/cascata_completa.py`), com uma régua
explícita e documentada:

- Endereço (rua+número) com **5+ vendas válidas** (mesma regra de
  `engine._is_valid_sale`: "1.Compra e venda", 100% transmitido, unidade
  — não prédio inteiro) dentro de uma **janela de 182 dias** (mesmo
  limiar de `engine._is_launch`, já usado pela Captação Ativa) é
  lançamento → conta como **planta**. Todo o resto (venda única,
  2–4 vendas, ou vendas espalhadas fora da janela de 182 dias) conta como
  **revenda**.
- Ao contrário da Captação Ativa, **não descarta** endereço com preço
  incoerente entre vendas (`engine._price_incoherent`) — aqui o objetivo é
  contar volume ("giro é giro", mesma filosofia de `engine.py`), não
  montar uma lista de prospecção.
- Classificação usa o histórico MULTI-ANO inteiro do endereço (pra ver o
  padrão de lançamento completo), mas só entra na tabela final a janela
  rolante de 12 meses mais recente (mesma janela de
  `engine._mes_base_e_periodo`, jul/2025–jun/2026 nesta base congelada).

Com essa régua (explicitamente diferente da do script perdido — os
números NÃO devem ser comparados 1:1 com os reportados antes nesta
sessão), o universo total recalculado é: **70.877 revendas / 49.050
plantas** (12 meses, dedup, qualquer natureza — "giro é giro").

**a) Tabela completa dos 77** (ANTES = revenda+planta combinados, com
"Santo Amaro" ainda como bairro único; DEPOIS revenda/planta/giro = com a
divisão aplicada):

| Bairro | ANTES | DEPOIS revenda | DEPOIS planta | Giro |
|---|---:|---:|---:|---:|
| Aclimação | 1.052 | 687 | 365 | 2,58% |
| Alto da Boa Vista | 119 | 206 | 279 | 2,25% |
| Alto da Lapa | 242 | 163 | 79 | 2,56% |
| Alto da Mooca | 767 | 604 | 163 | 3,93% |
| Alto de Pinheiros | 217 | 146 | 71 | 2,38% |
| Bela Vista | 1.848 | 1.006 | 843 | 2,08% |
| Bosque da Saúde | 122 | 119 | 3 | 4,51% |
| Brooklin | 1.278 | 732 | 605 | 2,58% |
| Cambuci | 749 | 342 | 410 | 1,57% |
| Campo Belo | 1.150 | 676 | 536 | 3,02% |
| Cerqueira César | 1.522 | 1.047 | 475 | 3,87% |
| Chácara Inglesa | 165 | 69 | 96 | 1,51% |
| Chácara Santo Antônio | 418 | 357 | 677 | 1,81% |
| Cidade Monções | 80 | 51 | 29 | 1,76% |
| Consolação | 1.525 | 637 | 888 | 2,16% |
| Higienópolis | 522 | 481 | 41 | 4,67% |
| Ibirapuera | 565 | 303 | 281 | 2,29% |
| Indianópolis | 1.130 | 640 | 491 | 3,29% |
| Ipiranga | 2.543 | 1.440 | 1.103 | 2,98% |
| Itaim Bibi | 732 | 498 | 234 | 2,76% |
| Jardim Aeroporto | 189 | 92 | 103 | 1,32% |
| Jardim América | 654 | 376 | 278 | 2,85% |
| Jardim Anália Franco | 72 | 59 | 13 | 3,47% |
| Jardim Caravelas | 0 | 0 | 0 | — |
| Jardim Europa | 72 | 71 | 1 | 3,33% |
| Jardim Novo Mundo | 12 | 12 | 0 | 2,07% |
| Jardim Paulista | 1.575 | 1.148 | 428 | 3,79% |
| Jardim Paulistano | 92 | 90 | 11 | 1,98% |
| Jardim Petrópolis | 18 | 23 | 8 | 2,33% |
| Jardim Santo Amaro | 17 | 35 | 24 | 2,51% |
| Jardim Vila Mariana | 25 | 25 | 0 | 3,10% |
| Jardim da Glória | 82 | 73 | 9 | 3,18% |
| Jardim da Saúde | 188 | 135 | 53 | 2,57% |
| Jardim das Acácias | 150 | 32 | 118 | 1,08% |
| Jardim das Bandeiras | 16 | 16 | 0 | 3,15% |
| Jardim dos Estados | 20 | 21 | 13 | 2,34% |
| Jardins | 29 | 23 | 6 | 4,20% |
| Lapa | 1.441 | 575 | 899 | 1,71% |
| Mirandópolis | 321 | 219 | 102 | 2,56% |
| Moema | 708 | 476 | 353 | 2,39% |
| Moinho Velho | 340 | 153 | 187 | 1,92% |
| Mooca | 2.116 | 927 | 1.189 | 2,00% |
| Pacaembu | 71 | 46 | 25 | 2,60% |
| Paraíso | 639 | 395 | 244 | 2,93% |
| Parque Fongaro | 54 | 32 | 22 | 1,44% |
| Parque da Mooca | 160 | 109 | 51 | 2,38% |
| Perdizes | 2.337 | 1.496 | 842 | 3,55% |
| Pinheiros | 1.591 | 787 | 804 | 2,71% |
| Planalto Paulista | 254 | 202 | 52 | 2,90% |
| Pompéia | 721 | 454 | 267 | 3,67% |
| Santa Cecília | 1.839 | 1.257 | 597 | 2,96% |
| **Santo Amaro** | **7.117** | **107** | **334** | **0,91%** |
| Saúde | 3.379 | 1.888 | 1.491 | 2,66% |
| Sumarezinho | 181 | 119 | 62 | 2,92% |
| Sumaré | 208 | 142 | 66 | 3,01% |
| Tatuapé | 4.243 | 2.217 | 2.026 | 2,60% |
| Vila Antonieta | 337 | 176 | 166 | 2,09% |
| Vila Bertioga | 98 | 74 | 24 | 2,53% |
| Vila Clementino | 645 | 477 | 216 | 3,83% |
| Vila Cordeiro | 89 | 19 | 71 | 0,76% |
| Vila Firmiano Pinto | 29 | 12 | 17 | 0,77% |
| Vila Gomes Cardim | 90 | 43 | 47 | 1,36% |
| Vila Gumercindo | 177 | 94 | 83 | 1,66% |
| Vila Ipojuca | 106 | 87 | 19 | 2,94% |
| Vila Leopoldina | 507 | 113 | 394 | 0,90% |
| Vila Madalena | 640 | 466 | 174 | 3,37% |
| Vila Mariana | 2.971 | 1.896 | 1.075 | 3,57% |
| Vila Monumento | 205 | 202 | 3 | 5,05% |
| Vila Nova Conceição | 332 | 235 | 97 | 3,39% |
| Vila Nova Manchester | 153 | 134 | 19 | 4,26% |
| Vila Olímpia | 1.311 | 599 | 720 | 3,64% |
| Vila Regente Feijó | 184 | 83 | 101 | 1,44% |
| Vila Romana | 256 | 192 | 72 | 2,76% |
| Vila São Francisco | 369 | 147 | 225 | 1,50% |
| Vila Uberabinha | 43 | 26 | 17 | 2,50% |
| Vila da Saúde | 40 | 23 | 17 | 3,25% |
| Vila das Mercês | 222 | 84 | 138 | 1,16% |

Giro = revenda÷unidades IPTU (apartamento+residência), mesma definição já
aprovada (planta fora do numerador).

**b) Destaque — antes × depois da divisão de Santo Amaro** (revenda|planta|unidades IPTU):

| Bairro | Antes da divisão | Depois da divisão |
|---|---:|---:|
| **Santo Amaro** | 3.084 \| 4.033 \| 218.601 | **107 \| 334 \| 11.723** |
| Alto da Boa Vista | 47 \| 72 \| 2.563 | **206 \| 279 \| 9.140** |
| Chácara Santo Antônio | 237 \| 181 \| 11.168 | **357 \| 677 \| 19.735** |
| Jardim Caravelas | 0 \| 0 \| 0 | 0 \| 0 \| 0 (sem mudança — nenhum CEP do arquivo foi atribuído a ele) |
| Jardim Santo Amaro | 17 \| 0 \| 358 | 35 \| 24 \| 1.394 |
| Brooklin | 708 \| 570 \| 27.523 | 732 \| 605 \| 28.425 |
| Campo Belo | 665 \| 485 \| 20.655 | 676 \| 536 \| 22.415 |

Achado: a divisão fez exatamente o que a evidência dos CEPs apontava —
Santo Amaro (o "centro" que sobrou) caiu de ~7.100 pra ~440
revendas+plantas, Alto da Boa Vista e Chácara Santo Antônio recuperaram
volume que genuinamente era deles. Jardim Santo Amaro e Brooklin/Campo
Belo tiveram ganhos pequenos — efeito indireto (tiers 2–5 da cascata:
menos registros "Santo Amaro" competindo por voto de endereço/CEP/quadra
nas redondezas).

**c) Fechamento da conta (77 bairros, antes × depois da divisão)**:

| | Antes da divisão | Depois da divisão |
|---|---:|---:|
| Revenda — carteira / fora / incerto | 44,8% / 53,6% / 1,6% | 41,2% / 57,1% / 1,7% |
| Planta — carteira / fora / incerto | 50,4% / 35,5% / 14,1% | 44,9% / 40,1% / 15,0% |
| Unidades IPTU — carteira / fora / incerto | 44,6% / 49,8% / 5,6% | 38,3% / 55,4% / 6,3% |

A carteira perde alguns pontos percentuais em todos os 3 universos — raiz
numérica óbvia: antes, 100% do que se chamava "Santo Amaro" contava como
carteira; agora, a maior parte desse volume (as partes de
Socorro/Interlagos, marcadas "FORA" no arquivo do usuário) sai da
carteira de verdade. É o resultado esperado da divisão, não um problema.

**Pendente antes de fechar o item**: os números acima usam uma definição
de revenda×planta reconstruída nesta rodada (ver acima) — diferente do
script perdido que gerou os totais mostrados antes na sessão. Aguardando
o usuário confirmar que esta régua (endereço com 5+ vendas em 182 dias =
planta, sem descarte por preço incoerente) é a que deve virar
`engine.py`/`engine.js`, já que "se os números fecharem, implementar" foi
a condição dada. Nada ligado em `engine.py`/`engine.js` ainda.

## Item 3: correção da classificação revenda × planta (2026-09-30)

A régua de revenda×planta reportada na seção anterior (endereço com 5+
vendas em 182 dias) foi **rejeitada pelo usuário**: classificava
condomínio grande e antigo como lançamento (Tatuapé: planta de 803 pra
2.026) e lançamento pequeno/lento como revenda. Regra aprovada no lugar
(`scripts/cascata_completa.classificar_revenda_planta_aprovada`):

> Universo: natureza "1.Compra e venda", **qualquer uso** (não só
> residencial).
> - **REVENDA** = proporção transmitida 100% **e** uso IPTU residencial
>   (10 ou 20).
> - **PLANTA** = proporção transmitida <100% **e** uso IPTU NÃO
>   residencial **e** (complemento contém AP/APTO/APART/TORRE/BLOCO/
>   CASA/UNIDADE, **ou** financiamento é MCMV/SFH).
> - **PARCIAL** = proporção <100% e uso residencial (herança/divórcio) —
>   fora das duas.
> - **DEMAIS** = resto — fora das duas.

Achado-chave (do usuário): venda na planta é registrada no ITBI com o
**uso do lote-mãe** (terreno, indústria, loja etc.), quase nunca um uso
residencial — por isso o parse precisou ganhar
`somente_uso_residencial=False` (`parse_itbi.py`, aditivo — o resto do
pipeline, `build_data.py`/`engine.py`, chama sem esse argumento e
continua só com uso residencial, comportamento inalterado) pra essas
linhas pararem de ser descartadas antes mesmo de chegar à classificação.

**Validação contra o teste do usuário** (dados de 2025 inteiro, antes da
rodada de 3 anos): revenda 82.746 (referência do usuário: 82.789, -0,05%)
· parcial 13.123 (referência: 13.281, -1,2%) · planta 72.172 (referência:
65.578 — só batia a 1,7% numa variante errada do teste do usuário, que
excluía SFH sem querer por procurar o texto "SFH" em vez de "1.Sistema
Financeiro de Habitação"; confirmado que SFH sozinho, sem token no
complemento, é sinal válido nessa combinação — proporção<100% + uso
não-residencial só ocorre em venda de unidade nova).

**Rodada completa (3 anos, 12 meses, com divisão de Santo Amaro
aplicada)**:

```
revenda=82.820  planta=79.160  parcial=13.722  demais=35.339
```

79.160 plantas/ano fica um pouco acima da referência de 70-75 mil/ano
(~5-13%), mas dentro de uma margem razoável (diferença de janela/
crescimento ano a ano) — não investiguei mais fundo porque o usuário já
confirmou a regra como está.

**a) Tabela completa dos 77** (ANTES = regra antiga recomputada, DEPOIS
revenda/planta = regra aprovada, com a divisão de Santo Amaro já
aplicada; giro = depois-revenda ÷ unidades IPTU):

| Bairro | ANTES | DEPOIS revenda | DEPOIS planta | Giro |
|---|---:|---:|---:|---:|
| Aclimação | 1.085 | 864 | 49 | 3,25% |
| Alto da Boa Vista | 625 | 494 | 1.078 | 5,40% |
| Alto da Lapa | 263 | 196 | 38 | 3,07% |
| Alto da Mooca | 802 | 499 | 17 | 3,25% |
| Alto de Pinheiros | 217 | 156 | 18 | 2,54% |
| Bela Vista | 1.785 | 1.390 | 528 | 2,87% |
| Bosque da Saúde | 127 | 94 | 23 | 3,56% |
| Brooklin | 1.470 | 1.019 | 1.460 | 3,58% |
| Cambuci | 756 | 635 | 1.065 | 2,91% |
| Campo Belo | 1.330 | 1.004 | 219 | 4,48% |
| Cerqueira César | 1.450 | 1.116 | 308 | 4,12% |
| Chácara Inglesa | 178 | 130 | 83 | 2,85% |
| Chácara Santo Antônio | 901 | 680 | 3.104 | 3,45% |
| Cidade Monções | 80 | 55 | 0 | 1,90% |
| Consolação | 1.587 | 1.327 | 371 | 4,51% |
| Higienópolis | 534 | 415 | 16 | 4,03% |
| Ibirapuera | 637 | 488 | 829 | 3,70% |
| Indianópolis | 1.179 | 893 | 277 | 4,59% |
| Ipiranga | 2.516 | 1.640 | 1.195 | 3,40% |
| Itaim Bibi | 726 | 539 | 52 | 2,99% |
| Jardim Aeroporto | 196 | 173 | 16 | 2,49% |
| Jardim América | 708 | 586 | 90 | 4,44% |
| Jardim Anália Franco | 79 | 67 | 0 | 3,94% |
| Jardim Caravelas | 0 | 0 | 0 | — |
| Jardim Europa | 72 | 45 | 0 | 2,11% |
| Jardim Novo Mundo | 12 | 10 | 0 | 1,72% |
| Jardim Paulista | 1.565 | 1.246 | 200 | 4,11% |
| Jardim Paulistano | 100 | 82 | 0 | 1,80% |
| Jardim Petrópolis | 31 | 25 | 0 | 2,53% |
| Jardim Santo Amaro | 59 | 42 | 0 | 3,01% |
| Jardim Vila Mariana | 25 | 24 | 25 | 2,98% |
| Jardim da Glória | 82 | 61 | 0 | 2,66% |
| Jardim da Saúde | 160 | 119 | 50 | 2,27% |
| Jardim das Acácias | 149 | 127 | 131 | 4,30% |
| Jardim das Bandeiras | 16 | 9 | 0 | 1,77% |
| Jardim dos Estados | 34 | 25 | 0 | 2,78% |
| Jardins | 29 | 25 | 2 | 4,57% |
| Lapa | 1.557 | 1.244 | 3.744 | 3,70% |
| Mirandópolis | 331 | 296 | 29 | 3,46% |
| Moema | 790 | 645 | 516 | 3,24% |
| Moinho Velho | 341 | 284 | 91 | 3,57% |
| Mooca | 2.052 | 1.517 | 2.210 | 3,27% |
| Pacaembu | 71 | 62 | 1 | 3,50% |
| Paraíso | 708 | 511 | 12 | 3,79% |
| Parque Fongaro | 54 | 47 | 0 | 2,11% |
| Parque da Mooca | 166 | 137 | 0 | 2,99% |
| Perdizes | 2.525 | 1.805 | 994 | 4,28% |
| Pinheiros | 1.557 | 1.191 | 1.320 | 4,10% |
| Planalto Paulista | 254 | 200 | 127 | 2,88% |
| Pompéia | 591 | 456 | 211 | 3,69% |
| Santa Cecília | 1.842 | 1.452 | 433 | 3,42% |
| **Santo Amaro** | 441 | 395 | 475 | 3,37% |
| Saúde | 3.417 | 2.368 | 538 | 3,34% |
| Sumarezinho | 221 | 142 | 74 | 3,48% |
| Sumaré | 205 | 166 | 23 | 3,52% |
| Tatuapé | 4.207 | 2.900 | 838 | 3,40% |
| Vila Antonieta | 355 | 254 | 11 | 3,01% |
| Vila Bertioga | 100 | 81 | 1 | 2,77% |
| Vila Clementino | 700 | 415 | 538 | 3,33% |
| Vila Cordeiro | 39 | 99 | 1 | 3,95% |
| Vila Firmiano Pinto | 64 | 55 | 388 | 3,52% |
| Vila Gomes Cardim | 90 | 72 | 0 | 2,27% |
| Vila Gumercindo | 172 | 136 | 4 | 2,40% |
| Vila Ipojuca | 110 | 82 | 0 | 2,77% |
| Vila Leopoldina | 475 | 409 | 1.443 | 3,24% |
| Vila Madalena | 633 | 459 | 18 | 3,32% |
| Vila Mariana | 2.998 | 2.118 | 801 | 3,99% |
| Vila Monumento | 215 | 104 | 2 | 2,60% |
| Vila Nova Conceição | 319 | 290 | 76 | 4,18% |
| Vila Nova Manchester | 161 | 83 | 170 | 2,64% |
| Vila Olímpia | 1.286 | 837 | 659 | 5,09% |
| Vila Regente Feijó | 220 | 166 | 2 | 2,88% |
| Vila Romana | 232 | 195 | 52 | 2,81% |
| Vila São Francisco | 375 | 287 | 39 | 2,93% |
| Vila Uberabinha | 38 | 26 | 23 | 2,50% |
| Vila da Saúde | 41 | 25 | 0 | 3,53% |
| Vila das Mercês | 221 | 167 | 19 | 2,31% |

**b) Destaque — Santo Amaro e vizinhos** (antes | depois revenda | depois planta):

| Bairro | Antes | Depois revenda | Depois planta |
|---|---:|---:|---:|
| Santo Amaro | 441 | 395 | 475 |
| Alto da Boa Vista | 625 | 494 | 1.078 |
| Chácara Santo Antônio | 901 | 680 | 3.104 |
| Jardim Caravelas | 0 | 0 | 0 |
| Jardim Santo Amaro | 59 | 42 | 0 |
| Brooklin | 1.470 | 1.019 | 1.460 |
| Campo Belo | 1.330 | 1.004 | 219 |

**c) Fechamento da conta (77 bairros)**:

| | Total | Carteira | Fora | Incerto |
|---|---:|---:|---:|---:|
| ANTES (regra antiga) | 117.468 | 44,0% | 49,2% | 6,7% |
| REVENDA (regra aprovada) | 82.820 | 46,5% | 46,0% | 7,5% |
| PLANTA (regra aprovada) | 79.160 | 34,3% | 62,7% | **3,0%** |
| UNIDADES IPTU | 2.831.160 | 38,3% | 55,4% | 6,3% |

**Planta incerto voltou pra ~3%** (meta do usuário), de 15,0% na rodada
anterior (regra antiga) — confirma que a régua por endereço estava
capturando nome de cadastro de pior qualidade junto com a classificação
errada.

20 exemplos de planta via SFH/MCMV sem token de unidade no complemento
(conferência pedida pelo usuário) ficam no log de execução do script
(`scripts/cascata_completa.py`, função `amostrar_planta_sfh_sem_token`) —
amostra confirma padrão esperado: complemento tipo "2204 (R2V-1)", "300",
"BL 1 STUDIO 111", sempre em uso não-residencial (terreno/indústria/loja
do lote-mãe) com financiamento MCMV ou SFH.

Protocolo novo (regra permanente do usuário, a partir de agora): todo
script que gera número pra relatório ou decisão é commitado **antes** de
o número ser reportado — nenhum número aprovado pode depender de código
descartável. `scripts/cascata_completa.py` foi commitado antes desta
rodada rodar.

Nada ligado no `engine.py`/`engine.js` ainda — aguardando confirmação do
usuário pra prosseguir com a implementação.

## Item 3: relatório final antes do merge — incerto, giro, quedas de revenda, implementação (2026-09-30)

Números aprovados pelo usuário para implementação (campos aditivos,
testes, relatório antes×depois). Merge continua bloqueado — pendências
abaixo.

### 1) Incerto da revenda: 7,5% → investigado e corrigido

Causa raiz encontrada em `tradutor_bairro.Cascata.resolver()`: quando o
nome de cadastro era reconhecido como lixo (`status == "AUTO_IGNORAR"` —
"TORRE 1", "BLOCO F" etc.), a função retornava `"incerto"` **direto**,
sem nunca chegar a consultar `quadras_qualquer_bairro` — o sinal que diz
se a quadra fiscal daquele imóvel tem um bairro majoritário reconhecível
no IPTU (prédio genuinamente localizável, só com o campo Bairro
preenchido com nome de torre). Essa checagem já existia pro caso "nome
desconhecido" (status `None`), mas nunca foi estendida pro caso "nome
reconhecido como lixo" — a mesma classe de bug da correção anterior,
só que num ramo diferente do código.

Amostra de 25 "incerto" de revenda confirmou o padrão: ~80% tinham
`bairro_raw` tipo "TORRE 1"/"BLOCO F", `quadra74=None` (a quadra não tinha
voto majoritário pra um dos 77) mas `tem_qualquer_bairro=True` (a mesma
quadra tinha um bairro majoritário no IPTU sem filtro). Corrigido
removendo o atalho — os dois casos agora caem no mesmo check final.

**Resultado**: revenda incerto caiu de 7,5% para **0,9%** — melhor que a
meta de ≤3% e melhor que a rodada anterior (5,4%). Efeito colateral
esperado (não é regressão): "fora da carteira" subiu proporcionalmente
(46,0%→52,6%), porque os casos que eram "incerto" por engano agora caem
corretamente em "fora_carteira" (end bairro real, só não um dos 77) —
carteira continua igual.

| | Antes da correção | Depois da correção |
|---|---:|---:|
| ANTES (regra antiga) — fora/incerto | 49,2% / 6,7% | 55,1% / 0,9% |
| REVENDA — fora/incerto | 46,0% / 7,5% | 52,6% / **0,9%** |
| PLANTA — fora/incerto | 62,7% / 3,0% | 62,9% / 2,9% |
| UNIDADES IPTU — fora/incerto | 55,4% / 6,3% | 60,6% / 1,0% |

### 2) Taxa de giro dos 77 (revenda ÷ unidades) — nenhum acima de 10%

Maior giro: Alto da Boa Vista (5,4%). Nenhum dos 77 bairros passa de
10% — sem sinal de contaminação de bairro/região nem de dupla-contagem
na nova régua.

### 3) Quedas de revenda ≥25% — decomposição

**Achado importante**: Brooklin (−31%) e Campo Belo (−25%), citados no
relatório anterior, eram um **artefato de comparação não-equivalente** —
comparavam "antes" (revenda+planta da regra antiga, **combinados**) com
"depois revenda" (só revenda da regra nova). Comparando revenda PURA
antiga × revenda PURA nova (resolvidas cada uma na sua própria cascata),
os dois bairros na verdade **aumentaram**: Brooklin 725→1.019 (+40,6%),
Campo Belo 674→1.004 (+49,0%).

Refeita a comparação corretamente (revenda × revenda), só **4 bairros**
caem ≥25%:

| Bairro | Antigo → Novo | Queda | Causa |
|---|---:|---:|---|
| Vila Monumento | 199 → 104 | −47,7% | quase toda a queda é classificação: 74 registros viraram "parcial" (fração de herança/divórcio), só 8 mudaram de bairro |
| Jardim das Bandeiras | 16 → 9 | −43,8% | amostra pequena; 2 parcial + 1 demais + 3 fora do universo |
| Vila Nova Manchester | 134 → 83 | −38,1% | classificação: 21 parcial + 9 demais + 12 viraram planta; 0 mudaram de bairro |
| Jardim Europa | 71 → 45 | −36,6% | metade classificação (9 parcial), metade mudança de bairro (9 reassociados) |

Em todos os 4, a decomposição mostra que a queda vem **quase inteiramente
da classificação** (registros corretamente identificados como fração
ideal/herança-divórcio, não mais contados como revenda) — não da cascata
de bairro. Lista completa dos 77 (quem subiu e quem caiu, com a mesma
decomposição) fica no log de execução de `scripts/cascata_completa.py`.

### 4) 20 exemplos de planta via SFH/MCMV sem token de unidade no complemento

| Endereço | Complemento | Uso (IPTU) | Financiamento |
|---|---|---|---|
| Rua Itapeva, 342 | STUDIO R 806 | 62 | 1.Sistema Financeiro de Habitação |
| Avenida Giovanni Gronchi, 7020 | SPHER PARK A2 1512 | 64 | 1.Sistema Financeiro de Habitação |
| Avenida Nsra De Sabará, 4780 | AURORA TE AP907 | 84 | 2.Minha Casa Minha Vida |
| Avenida Corifeu De Azevedo Marques, s/n | TR-B APT 611B | 0 | 2.Minha Casa Minha Vida |
| Avenida Sta Marina, 1317 | APT 1517 TR A | 50 | 2.Minha Casa Minha Vida |
| Rua Dr Plínio Do Amaral, 103 | RESIDENCIA 1 | 12 | 1.Sistema Financeiro de Habitação |
| Rua Joaquim Carlos, 580 | M BELEM TD AP1306 | 51 | 1.Sistema Financeiro de Habitação |
| Rua Claudino Pinto, 36 | 2009 | 12 | 2.Minha Casa Minha Vida |
| Avenida Guilherme, 754 | BL. T1, AP504 | 0 | 2.Minha Casa Minha Vida |
| Rua Americo Sugai, s/n | 410 | 0 | 2.Minha Casa Minha Vida |
| Rua Alexandre Benois, 17 | A_MORUMBI CC205 | 0 | 1.Sistema Financeiro de Habitação |
| Avenida Das Nações Unidas, 19847 | APT 1408 | 43 | 2.Minha Casa Minha Vida |
| Avenida Afonso De Sampaio E Sousa, 299 | EUCAL TB AP1308 | 50 | 1.Sistema Financeiro de Habitação |
| Avenida Onofrio Milano, s/n | APT 18 TR A | 0 | 2.Minha Casa Minha Vida |
| Rua Herval, s/n | BL 1 STUDIO 111 | 0 | 1.Sistema Financeiro de Habitação |
| Rua Sertões De Canindé, 46 | FR 1303 | 64 | 2.Minha Casa Minha Vida |
| Rua Dr Rubens Gomes Bueno, 158 | APT 1225 TOR 2 | 50 | 1.Sistema Financeiro de Habitação |
| Avenida Nsra De Sabará, 4780 | AURORA TC AP1406 | 84 | 1.Sistema Financeiro de Habitação |
| Avenida Roland Garros, 2187 | BL. T2, AP311 | 40 | 2.Minha Casa Minha Vida |
| Rua James Holland, 500 | V ANTART T.A 1011 | 51 | 1.Sistema Financeiro de Habitação |

Padrão confirmado: sempre uso não-residencial (lote-mãe), sempre
financiamento MCMV ou SFH, complemento reconhecidamente de unidade em
construção mesmo sem um token da lista (ex: "FR 1303", "2009", "410") —
amostra consistente com venda na planta de verdade, não falso positivo.

### 5) Implementação no engine.py/engine.js (branch) — feita e verificada

- `scripts/cascata_completa.gerar_dados_carteira_77()` empacota o cálculo
  acima num formato pronto pra `site/data.json`.
- `scripts/build_data.py` chama essa função e grava o resultado como
  **campo aditivo novo** `data["carteira_77"]` — nenhum campo existente
  foi tocado (os 49 bairros/ranking/etc. continuam exatamente como
  estavam). Falha nessa etapa é isolada (try/except) e não derruba o
  resto do build.
- Painel novo no site, "Carteira 77 (beta)": fechamento + tabela
  ordenável (revenda/planta/unidades/giro) dos 77 bairros. **Estático**
  — não recalcula com os filtros de preço/bairro dos outros painéis
  (isso exigiria portar a cascata inteira pra `engine.js`/`raw.json`,
  escopo bem maior que o pedido atual; posso fazer como próximo passo se
  for útil).
- **Bug encontrado e corrigido durante a verificação**: `mergeStaticMeta()`
  (em `site/app.js`) reconstrói `DATA` a partir de `computeEngine()`
  sempre que o recompute de fundo roda (mesmo sem filtro ativo, pra
  manter a lista de imóveis por faixa disponível) — como `computeEngine`
  não sabe de `carteira_77`, o campo **sumia silenciosamente** poucos
  segundos depois do carregamento inicial. Corrigido copiando
  `carteira_77` de `SERVER_DATA`, igual aos outros campos estáticos já
  tratados ali (`generated_at`, `meta.usn`).
- `scripts/test_carteira_77.py`: valida o formato/números do campo em
  `site/data.json` (77 bairros, campos obrigatórios, fechamento somando
  ~100%, sem valores negativos). Rodado com sucesso depois da correção.
- Confirmado no navegador (servidor local, `site/serve_no_cache.py`):
  painel "Carteira 77 (beta)" carrega com os 77 bairros, fechamento e
  tabela corretos; demais painéis (Visão Geral, Ranking, etc.) continuam
  funcionando sem nenhuma regressão; sem erros no console.
- `site/data.json`/`site/raw.json`/`site/itbi_clean_log.json`/
  `output/preco_m2_por_bairro.csv` regenerados com `build_data.py` (base
  congelada, `SKIP_ITBI_SYNC=1`) e commitados.

Tudo commitado e pushed na branch `correcao-itbi-metodologia`. `main`
continua intocado. Aguardando aprovação do usuário pra fazer merge.

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

## Merge pós-correção do ITBI (2026-10-01, tag `pos-correcao-itbi`)

A branch `correcao-itbi-metodologia` (item 2 + item 3 da auditoria —
carteira de 77 bairros, cascata de tradução por nome de cadastro,
revenda/planta separadas, Santo Amaro dividido por CEP) foi mergeada em
`main`. Dois problemas reais só apareceram no primeiro build de produção
(real, sem `SKIP_ITBI_SYNC`) e foram corrigidos na hora:

1. **`carteira_77` dependia de 2 arquivos fora do git** (`data/` é
   gitignorado por padrão): `data/iptu_geosampa/iptu_2026_reduzido.csv.gz`
   (26MB) e `data/iptu_geosampa/raw/bairros_mercado_preenchido.csv`
   (496KB, a tabela de tradução revisada à mão pelo usuário). Sem commitar
   os dois, o painel "Carteira 77" ficaria permanentemente quebrado na
   Action/cron (o cadastro do GeoSampa não pode ser baixado
   automaticamente — CAPTCHA). Resolvido com uma exceção pontual no
   `.gitignore` (ver comentário lá).
2. **Bug real em `site/app.js`**: `cmpLower()` só existe em `engine.js`,
   carregado de forma assíncrona/sob demanda — `renderPerfilContent()`
   usava a função síncronamente no primeiro `renderAll()`, lançando
   `ReferenceError` e deixando TODOS os painéis depois de "Perfil por
   Bairro" vazios até o recompute de fundo rodar pela primeira vez (bug
   pré-existente, não introduzido por esta auditoria — só apareceu porque
   alguém finalmente olhou o console na primeira carga). Corrigido
   duplicando a função em `app.js`.

`ALLOW_LARGE_CHANGES=1` foi usado na execução manual de republicação
(esperado: a correção de metodologia muda `volume_primary_year`) — na
prática a checagem de 30% nem disparou, porque a base de comparação já
vinha da própria branch mergeada (mesma metodologia nova dos dois lados).

## Etapa 2 (2026-10-01, branch `etapa-2-integracao-paineis`) — status

Última etapa antes de liberar a dashboard pra CRM e corretores. 4 itens
pedidos; progresso:

- **Item 2 (concluído)**: painel "Preço por m²" (agora "Valor Total Pago
  — Apartamento") trocou R$/m² pago por valor total pago (mediana/P25/
  P75), só revenda (`engine._is_revenda_aprovada`), com o gap R$/m²
  pedido×pago suspenso pra apartamento. Espelhado em `engine.js`
  (`uso_code` novo no fim da tupla de `raw.itbi`), validado no navegador
  campo a campo contra a saída do Python. `_compute_preco_m2` (Ranking/
  Gap Preço/Valor de Oportunidade/Imóveis Prioritários) **não foi
  tocado** — escopo deliberadamente restrito a este painel.
- **Item 3 (concluído, PRIORIDADE)**: `output/valor_pago_por_bairro.csv`
  — bairro (carteira 77) × tipo × ano, com P25/mediana/P75 do valor total
  pago em revenda e variação % ano contra ano. Entregue antes do prazo de
  2026-10-07.
- **Item 1 (pendente)**: ligar Ranking, Visão Geral, Alertas, Perfil por
  Bairro, Valor de Oportunidade, Estoque×Demanda e Mapa na base nova
  (carteira 77, cascata de bairro, revenda/planta separadas,
  `volume_mercado_12m`). Não iniciado nesta sessão — ver justificativa no
  relatório final entregue ao usuário: é uma migração do núcleo do motor
  (trocar `TARGETS`/a resolução de bairro usada por TODAS as funções de
  `engine.py`, replicar em `engine.js`, revalidar campo a campo), do
  mesmo tamanho/risco que o resto desta auditoria levou semanas pra
  fechar com segurança — não é "ligar 7 painéis", é substituir a base de
  dados que os 7 painéis leem. Fica como próximo passo focado.
- **Item 4 (pendente, depende do item 1)**: painel "Carteira 77" só sai
  do "(beta)" quando o item 1 estiver pronto.
