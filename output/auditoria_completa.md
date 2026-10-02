# Auditoria completa da Torre de Controle — 2026-10-01

Relatório em modo leitura: nada foi alterado no código ou nos painéis. Todos os números abaixo foram conferidos de verdade (rodando o sistema, não só lendo o código) contra os dados reais de hoje.

Legenda: 🔴 Grave (número errado chegando no painel) · 🟡 Atenção (risco ou fragilidade, não necessariamente errado) · 🟢 OK (verificado e correto)

---

## 1. Anúncios (nonStop)

### a) Duplicados

A pergunta era: o export de conteúdo já deduplica (mesmo endereço + área + preço ±3%). Os painéis também?

**🔴 Grave.** Não. Conferi o código de cada painel um por um: nenhum deles remove anúncio duplicado. Rodei a mesma regra de deduplicação do export de conteúdo contra o estoque de hoje (2.157 anúncios válidos) e achei **53 duplicados (2,5%)** — provavelmente o mesmo imóvel republicado por outro corretor, ou anunciado duas vezes com pequena diferença de preço.

Isso entra sem filtro em:
- **Estoque total** e **Estoque × Demanda** (cada duplicado conta como um imóvel a mais no estoque do bairro)
- **Imóveis Prioritários** (o mesmo imóvel pode ocupar 2 posições no ranking de 50)
- **Prontidão** (o "estoque no perfil de preço" de cada bairro usa o mesmo número não-deduplicado)

Bairros mais afetados hoje: Perdizes (6 duplicados), Campo Belo (6), Moema (5), Vila Mariana (3), Pinheiros (3), Jardim Paulista (3).

**🟡 Atenção.** Captação Ativa é menos afetada — os endereços vêm do histórico de vendas do ITBI, não do anúncio da nonStop. Mas a lista de "já anunciado hoje" (dentro de cada endereço) pode mostrar o mesmo anúncio duplicado duas vezes, porque também não filtra.

### b) Anúncios antigos

**🔴 Grave — achado novo, importante.** A nonStop manda a data de cadastro do anúncio (`createdAt`), mas **o sistema nunca guarda nem usa essa informação**. Hoje não existe nenhum limite de idade — um anúncio conta no estoque pra sempre, enquanto a nonStop continuar devolvendo ele como "à venda".

Medi a idade real do estoque de hoje:
- **69,3%** dos anúncios têm mais de 90 dias
- **42,6%** têm mais de 180 dias
- **19,7%** têm mais de 1 ano
- o mais antigo tem **1.310 dias (quase 3 anos e 7 meses)**

Não dá pra saber com certeza quantos desses já foram vendidos de verdade (a nonStop deveria parar de devolver um imóvel vendido — isso é responsabilidade da plataforma, não do nosso sistema), mas um anúncio de 3 anos no estoque é, no mínimo, suspeito, e hoje ele pesa igual a um anúncio de ontem em todos os cálculos — estoque, preço mediano, "estoque no perfil", prioridade máxima.

### c) Tipo de área

**🟢 OK.** A nonStop manda três campos de área (`private` = útil, `total` = construída/total, `land` = terreno). O sistema **só usa `private` (área útil)**, de forma consistente — não encontrei nenhum lugar misturando os dois. 99,9% dos anúncios têm essa área preenchida.

Não achei nenhum exemplo "suspeito" de área muito acima do padrão pro número de dormitórios (ex.: apê de 3 quartos com menos de 50m²) na checagem que fiz.

### d) Valores irreais

**🟢 OK, com uma observação.** Já existe um filtro que pega erro de digitação grosseiro: achei um anúncio em Perdizes cadastrado com **130.000 m²** de área (claramente um erro de digitação — devia ser 130m²) e confirmei que o sistema já descarta essa área sozinho (fica em branco, não entra em nenhuma conta). Esse filtro funciona.

Não achei nenhum anúncio de aluguel cadastrado como venda (os valores de venda, mesmo os mais baixos, são compatíveis com venda de verdade — nenhum abaixo de R$100 mil).

**🟡 Atenção.** Achei alguns anúncios com R$/m² muito fora da curva — de R$52 mil a R$86 mil o m² (a mediana do mercado é ~R$13,5 mil/m²), todos na Rua Funchal 65 (Vila Olímpia), Bela Vista, Moema, Ibirapuera e Jardim Paulista. Pode ser imóvel de altíssimo padrão de verdade (não dá pra eu confirmar sem conhecimento de mercado), mas vale uma conferida visual sua nesses endereços específicos.

### e) Bairro do anúncio

**🟢 OK, número bate com o que você falou.** Confirmei: **95,5%** dos 2.258 anúncios ativos têm o bairro reconhecido dentro dos 77 da carteira. Os outros **4,5% (101 anúncios)** têm nome de bairro que não está nos 77 — ou porque é um bairro de verdade fora da carteira, ou porque o nome não bate com nenhum apelido conhecido. Os 20 nomes mais frequentes nesse grupo:

Vila Anglo Brasileira (8), Vila Congonhas (8), Chácara Klabin (8), Água Branca (7), Bela Aliança (7), Vila Dom Pedro I (6), Belenzinho (4), Morro dos Ingleses (4), Vila Mascote (3), Parque Colonial (3), Vila Ida (3), Vila Nair (3), Vila Hamburguesa (2), Vila Buarque (2), Vila Gertrudes (2), São Judas (2), Vila Brasílio Machado (2), "siciliano - LAPA" (1), Campo (1), Alto Do Ipiranga (1).

A maioria parece ser bairro real fora da carteira de 77 (correto ficar de fora). Alguns (como "Alto Do Ipiranga") parecem só uma variação de escrita de um bairro que já está na carteira — provavelmente dá pra recuperar uns poucos com um ajuste na lista de apelidos, mas não decidi isso sozinho (não mexi em nada).

---

## 2. Ficha de cada painel

Pra cada painel: de onde vêm os dados, o que filtra, a fórmula, e o que o número quer dizer — em uma frase.

| # | Painel | De onde vêm os dados | Fórmula/regra principal | O que o número significa |
|---|---|---|---|---|
| 1 | **Visão Geral** | Resumo de todos os outros painéis | — | Primeira tela: top 10 de "onde anunciar agora", alertas de preço e resumo da carteira |
| 2 | **Ranking de Oportunidade** | ITBI (revendas dos últimos 12 meses) | 50% volume de revenda + 50% tendência (ambos "normalizados" comparando os 77 bairros entre si) | Nota 0–100: esse bairro tem liquidez de revenda alta e crescendo? 🟡 bairro com menos de 100 revendas em 12 meses entra com o selo "Amostra pequena" e não aparece no topo |
| 3 | **Prontidão para Campanha** | Combina Ranking + Estoque×Demanda + Preço + Captação + Imóveis Prioritários + Valor de Oportunidade | 6 sinais com pesos fixos (ver seção 3) | Nota 0–100: esse bairro tem munição real pra campanha agora? 🟡 mesma regra de amostra pequena do Ranking |
| 4 | **Estoque × Demanda** | Estoque ativo da nonStop ÷ revendas dos últimos 12 meses | Razão simples (estoque no perfil de preço / revenda) | Quanto estoque compatível com o que realmente se vende existe hoje nesse bairro. 🟡 não tem aviso de amostra pequena — um bairro com poucas vendas pode mostrar uma razão instável sem sinalizar isso |
| 5 | **Perfil por Bairro** | Vendas pagas do ITBI (histórico), por metragem | Metragem/dormitórios/vagas mais comuns nas vendas | O "perfil típico" de quem compra nesse bairro. 🟡 **ainda usa a lógica antiga de metragem** (ficou fora da lista do passo 2 — ver nota abaixo) |
| 6 | **Mapa** | Mesma base do Ranking | Bolha = bairro, tamanho = volume de revenda, cor = nota do Ranking | Visão geográfica da liquidez. 🟡 não mostra aviso de amostra pequena na bolha |
| 7 | **Captação Ativa Estratégica** | Endereços do ITBI com giro repetido (2+ vendas em 3 anos) | Ordenado por "sem unidade anunciada hoje" primeiro, depois mais vendas | Pauta de prospecção: endereços com histórico real de giro, pra ir bater na porta |
| 8 | **Imóveis Prioritários** | Estoque ativo da nonStop, pontuado um a um | 35% liquidez do bairro + 30% alinhamento de preço (suspenso pra apartamento) + 25% aderência à faixa de preço do bairro + 10% bônus de captação | Lista dos imóveis ativos mais "batidos" com o que o bairro historicamente vende |
| 9 | **Por Bairro/Região** | Mesmo de Imóveis Prioritários, filtrado por bairro | — | Mesma lista, recortada por bairro escolhido |
| 10 | **Valor de Oportunidade** | Imóveis Prioritários, cruzado com preço pago | Desconto ≥20% vs. mediana paga no mesmo segmento (só casa — apartamento suspenso) | Imóveis anunciados visivelmente abaixo do que historicamente se pagou |
| 11 | **Preço por m² (Valor Total Pago — Apartamento)** | ITBI (revenda de apartamento, 12m) | Mediana/P25/P75 do valor TOTAL pago (sem R$/m²) | Quanto um apartamento típico está sendo pago no bairro, por faixa de tamanho |
| 12 | **Carteira 77** | Tradução de bairro do IPTU + ITBI | Revenda/planta/giro dos últimos 12 meses | Fotografia fixa de referência — é a régua que todos os outros painéis têm que bater |

**Resumo da pergunta "algum painel ainda depende de lógica antiga?":**
- 🟡 **Perfil por Bairro**: sim, continua 100% na lógica antiga (metragem construída do ITBI batendo com metragem útil do anúncio). **Correção**: isso não foi uma decisão sua de mantê-lo assim — ele simplesmente ficou fora da lista dos 3 painéis do passo 2 (Captação, Estoque×Demanda, Prioridade Máxima). A decisão sobre migrá-lo ou não vem numa próxima rodada.
- 🟢 **Correção importante**: no passo 2b, o componente de "aderência ao tamanho/dormitórios/vagas" do Imóveis Prioritários **não ficou pendente — foi removido de verdade**. Conferi o código que está rodando em produção agora: a "aderência" desse painel hoje é 100% a faixa de preço v2 (o anúncio cair ou não dentro do que se pagou em revenda no bairro, pro mesmo tipo de imóvel) — não existe mais nenhum pedaço de dormitórios/vagas na conta. A fórmula atual, completa:
  - **Casa**: 35% liquidez de revenda do bairro + 30% alinhamento de R$/m² (pedido × mediana paga, mesmo tipo e tamanho) + 25% aderência à faixa de preço (valor do anúncio dentro do P25–P75 pago em revenda no bairro, com nota decrescente quanto mais longe da faixa) + 10% bônus de captação ativa (+100 se o endereço já teve giro comprovado, senão 0).
  - **Apartamento**: o componente de preço (30%) fica indisponível (sem fator de calibração de área ainda) e seu peso é redistribuído proporcionalmente — liquidez de revenda (50%) + aderência à faixa de preço (~35,7%) + bônus de captação (~14,3%).
  - Eu tinha escrito errado no relatório anterior (dizendo que esse pedaço "não foi migrado, pendente de decisão") — o correto é: **foi migrado e simplificado, não existe mais**. Peço desculpa pelo erro.
- 🟢 Todos os outros 10 painéis já usam a base nova (carteira 77, revenda separada de lançamento, faixa de preço em vez de metragem onde isso foi decidido).

---

## 3. Notas e pesos

### a) Critérios e peso de cada nota

**Ranking de Oportunidade** — 50% volume de revenda (12 meses) + 50% tendência de revenda (12m vs. 12m anterior, zerada se a amostra for pequena). **Origem do peso: decisão arbitrária de projeto, não tem uma referência externa documentada** — foi definido assim desde o início e nunca foi revisado.

**Prontidão para Campanha** — 6 sinais:
| Sinal | Peso | O que mede | Origem |
|---|---|---|---|
| f1 — Ranking | 15% | Nota do Ranking | Arbitrário |
| f2 — Estoque no perfil de preço | 20% | Quantos anúncios ativos caem na faixa de preço que o bairro realmente vende | Arbitrário |
| f3 — Gap de preço | 15% | Pedido × pago descolados (só casa) | Arbitrário |
| f4 — Captação ativa | 15% | Quantos endereços com giro comprovado | Arbitrário |
| f5 — Imóveis Prioritários | 25% | Média dos 10 melhores imóveis do bairro | Arbitrário |
| f6 — Valor de Oportunidade | 10% | % do estoque elegível que vira achado de desconto | Arbitrário |

**Imóveis Prioritários** — 35% liquidez de revenda + 30% alinhamento de preço (zerado/redistribuído pra apartamento) + 25% aderência à faixa de preço + 10% bônus de captação ativa. **Arbitrário.**

**Prioridade Máxima** (badge) — é um "sim/não", não uma nota: bairro tem ≤2 imóveis dentro da faixa de preço vencedora **E** 10+ revendas no ano. Os dois números (2 e 10) são **limites arbitrários**, nunca revisados desde que foram definidos.

**Valor de Oportunidade** — desconto ≥20% vira achado; ≥30% ganha o selo "Atenção". **Arbitrário.**

Nenhum desses pesos ou limites veio de um estudo de mercado, benchmark ou pedido documentado com uma razão específica — são todos decisões de projeto tomadas ao longo do caminho, sem revisão até agora. Isso não quer dizer que estão errados, só que **nunca foram testados contra a realidade do mercado** — exatamente o motivo da revisão que você quer fazer.

### b) Teste de sensibilidade (±10 pontos em cada peso)

Rodei o sistema de verdade várias vezes, mudando um peso de cada vez em ±10 pontos (redistribuindo a diferença proporcionalmente entre os outros) e comparando o top 10/20 antes e depois.

**Prontidão (top 10) — bem estável.** A maior mudança troca 1 a 2 bairros de posição; nenhum peso isolado vira o ranking de cabeça pra baixo:

| Peso testado | Quem sai do top 10 | Quem entra |
|---|---|---|
| f1 +10 | Itaim Bibi | Santa Cecília |
| f1 −10 | Paraíso | Vila Madalena |
| f2 +10 | Paraíso | Brooklin |
| f2 −10 | Itaim Bibi | Santa Cecília |
| f3 +10 | Itaim Bibi, Paraíso | Vila Madalena, Indianópolis |
| f3 −10 | *(nenhuma mudança)* | |
| f4 +10 | Paraíso | Santa Cecília |
| f4 −10 | Cerqueira César | Vila Nova Conceição |
| f5 +10 | *(nenhuma mudança)* | |
| f5 −10 | Paraíso | Santa Cecília |
| f6 +10 | *(nenhuma mudança)* | |
| f6 −10 | Itaim Bibi, Paraíso | Brooklin, Vila Madalena |

**Ranking (top 10, testando 60/40 e 40/60 em vez de 50/50) — também estável**: 2 bairros trocam de posição em cada direção (Planalto Paulista/Paraíso saem, Ipiranga/Campo Belo entram com mais peso em volume; Mooca sai, Chácara Inglesa entra com mais peso em tendência).

**Imóveis Prioritários (top 20) — 3 dos 4 pesos são estáveis, mas o de captação é MUITO sensível:**

| Peso testado | Quantos saem do top 20 |
|---|---|
| liquidez (revenda) +10 | 0 |
| liquidez (revenda) −10 | 2 |
| preço +10 e −10 | 0 |
| aderência +10 | 2 |
| aderência −10 | 0 |
| **captação +10** | 0 |
| **captação −10** | **16 de 20** 🟡 |

**🟡 Atenção — achado real.** O bônus de captação ativa hoje é "tudo ou nada" (+100 pontos se o endereço já teve giro comprovado, +0 se não). Isso faz o top 20 de Imóveis Prioritários depender muito mais desse único peso do que os outros três juntos — um imóvel "com captação" quase sempre fica à frente de um "sem captação" parecido, mesmo que os outros 3 critérios sejam melhores. Vale olhar com atenção na revisão.

### c) Casos contraditórios

**🔴 Achado importante, confirma o seu exemplo do Santa Cecília — e mostra que não é um caso isolado.** O selo "Prioridade Máxima" deveria significar "pouquíssimo estoque compatível, bairro escasso de verdade". Mas hoje ele também liga quando o bairro **tem bastante estoque ativo, só que nenhum dentro da faixa de preço** (ou seja: tem oferta, mas ela está fora do padrão de preço que o bairro historicamente vende) — duas situações bem diferentes, com o mesmo selo. Contei **18 bairros** nessa situação hoje, incluindo alguns com bastante estoque de verdade:

| Bairro | Estoque total ativo | Dentro da faixa de preço |
|---|---|---|
| Ipiranga | 50 anúncios | 0 |
| Aclimação | 44 | 0 |
| Bela Vista | 30 | 0 |
| Consolação | 18 | 0 |
| Mooca | 17 | 0 |
| Santa Cecília | 16 | 0 |
| (+ 12 outros bairros) | | |

No top 10 atual do Prontidão, nenhum bairro está nessa situação agora — mas ela aparece em 18 dos 77 bairros, então pode voltar a aparecer no top 10 a qualquer build (foi o caso do Santa Cecília antes do passo 2b).

Também achei 14 bairros com "Prioridade Máxima" ligado mas marcados como "amostra pequena" (menos de 100 revendas no ano) — outro par de selos que juntos soam contraditórios (bairro "prioritário" mas com pouquíssima venda de referência).

---

## 4. Atualização e rotina

### a) Status das buscas do Google

**🟡 Atenção.** Fonte: Google Ads Keyword Planner. Hoje, **47 dos 77 bairros (61%)** têm dado — os outros 30 nunca foram buscados porque o cache foi criado antes da carteira crescer pra 77 bairros. Último dado: **21/09/2026**. Atualiza sozinho a cada 25 dias (o Google só recalcula o volume de busca uma vez por mês, então não faz sentido buscar todo dia) — os 30 que faltam devem entrar sozinhos na próxima atualização automática, dentro de ~2 semanas.

### b) O que acontece se uma fonte falhar

| Fonte | Se falhar | Avisa? |
|---|---|---|
| **ITBI (Prefeitura)** | 🟡 Usa o arquivo salvo da última vez que funcionou e segue o build normalmente — pode ficar com até ~1 dia de atraso | Só no log técnico do GitHub (que você não acompanha no dia a dia) — **nada aparece na tela pro usuário** |
| **nonStop (estoque)** | 🟢 Se a API cair de vez, o build inteiro trava e o site continua mostrando os dados de ontem (não publica nada quebrado) | Só no log técnico — a tela mostra a data da última atualização bem-sucedida, então dá pra perceber que não mudou, mas não tem um aviso explícito de "estoque desatualizado" |
| **nonStop (resposta vazia/poucos dados)** | 🔴 **Não existe nenhuma trava aqui.** Se a nonStop devolver 0 (ou poucos) imóveis por algum motivo (token expirado, integração desligada, etc.) sem dar erro, o build publica um site com estoque zerado em todo canto, **sem nenhum aviso** | Não |
| **Google Ads (busca)** | 🟢 Já tem tratamento: usa o dado salvo anterior e marca como "sem dado recente" na tela quando a tentativa falha ou o dado passa de 30 dias | Sim — selo "Busca: sem dado recente" aparece pro usuário |

O ITBI tem uma segunda trava: se o formato da planilha da Prefeitura mudar (colunas diferentes, cabeçalho diferente), o sistema já detecta e trava o build antes de publicar qualquer coisa errada — **isso já está testado e funciona (🟢)**.

### c) Data da última atualização visível na tela

**🟡 Atenção.** Só existe **uma** data visível, no topo da página: "gerado em [data/hora]" — é a hora em que o build rodou, não necessariamente a hora de cada fonte. Se o ITBI usou um arquivo de 2 dias atrás (porque a Prefeitura caiu), ou se a nonStop demorou mais pra responder, essa única data não mostra isso — ela só diz "o robô rodou agora", não "cada fonte está atualizada até agora". A única exceção é a busca do Google, que tem sua própria data (visível passando o mouse no selo).

---

## 5. Resumo final

### Os 5 achados mais importantes, em ordem de gravidade

1. 🔴 **nonStop sem trava de "resposta vazia"**: se a integração falhar sem dar erro (devolver poucos ou nenhum imóvel), o site publica estoque zerado silenciosamente, sem nenhum aviso. O ITBI tem essa trava (reconciliação exata de linhas); o nonStop não tem nada parecido.
2. 🔴 **Painéis não deduplicam anúncios** (2,5% de duplicados hoje — 53 de 2.157): infla estoque, Estoque×Demanda, Imóveis Prioritários e Prontidão em todo bairro, mesmo que pouco.
3. 🔴 **Anúncios muito antigos contam igual aos novos**: 69% do estoque tem mais de 90 dias, alguns com quase 4 anos, e a data de cadastro (que a nonStop já manda) nunca é usada pra filtrar ou avisar.
4. 🔴 **Selo "Prioridade Máxima" confunde duas situações diferentes**: "bairro realmente escasso" e "bairro com estoque, mas fora da faixa de preço" acendem o mesmo selo — achei 18 bairros nessa segunda situação hoje (o caso do Santa Cecília que você notou não foi coincidência, é estrutural).
5. 🟡 **Nenhuma fonte de dado mostra sua própria data de atualização na tela** (só a busca do Google) — se o ITBI ou a nonStop atrasarem, o usuário não tem como perceber olhando o site.

### Prontos para uso diário × para compartilhar com corretores

**🟢 Prontos pros dois usos hoje:** Ranking de Oportunidade, Carteira 77, Preço por m² (Valor Total Pago — Apartamento), Valor de Oportunidade, Captação Ativa Estratégica.

**🟡 Prontos pra uso diário seu, mas peço cautela antes de compartilhar com corretores sem contexto:** Prontidão para Campanha e Imóveis Prioritários (o selo "Prioridade Máxima" pode confundir um corretor que não sabe da ressalva do item 3c; o peso de captação é muito sensível) e Estoque × Demanda (sem aviso de amostra pequena).

**🟡 Use com uma ressalva clara se for compartilhar:** Perfil por Bairro (ainda na lógica antiga de metragem — bom explicar isso ao corretor que for usar, pra ele não comparar metragem construída com área útil do anúncio sem saber da limitação).

Nenhum painel tem um problema que eu chamaria de "não usar de jeito nenhum" — os achados 🔴 são reais e valem corrigir, mas nenhum deles faz o painel mentir hoje de forma grosseira; são principalmente casos de amostra pequena, estoque desatualizado ou confusão de rótulo, não números fabricados.
