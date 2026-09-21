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
  build_data.py                ← orquestra tudo → site/data.json
site/
  index.html / styles.css / app.js / data.json
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

## Automação (GitHub Actions)

`.github/workflows/build-data.yml` roda `build_data.py` todo dia às 8h
(horário de São Paulo) e commita `site/data.json` se mudou. Precisa do
Secret `NONSTOP_TOKEN` configurado no repositório (Settings → Secrets and
variables → Actions). O cache dos `.xlsx` de ITBI entre execuções evita
rebaixar ~100MB todo dia à toa.
