#!/bin/bash
# Publica o dashboard na Cloudflare Pages (envio direto da pasta, sem build).
# Usado pelo build-data.yml (depois de cada atualização bem-sucedida) e pelo
# publicar-cloudflare.yml (manual). Precisa dos 3 segredos do GitHub:
#   CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_PAGES_PROJECT
# Sem eles, pula sem erro (a Cloudflare é opcional; o acesso pelo Tailscale não depende disso).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ] || [ -z "${CLOUDFLARE_PAGES_PROJECT:-}" ]; then
  echo "::notice::Cloudflare não configurada (faltam segredos no GitHub) — publicação pulada."
  exit 0
fi

python3 scripts/preparar_pasta_cloudflare.py cloudflare-dist

# Cria o projeto na primeira vez (se já existir, só segue).
npx --yes wrangler@4 pages project create "$CLOUDFLARE_PAGES_PROJECT" --production-branch main >/dev/null 2>&1 || true

# A pasta "functions/" (a trava de login) é lida do diretório atual.
npx --yes wrangler@4 pages deploy cloudflare-dist \
  --project-name "$CLOUDFLARE_PAGES_PROJECT" --branch main --commit-dirty=true

# Limpeza das publicações antigas (mantém as 5 mais recentes + a de produção).
# NUNCA derruba o deploy: se falhar, só registra o aviso no log.
# ETAPA 1 (aprovada em 07/10/2026): só LISTA o que apagaria. A etapa 2 troca para 1.
LIMPAR_APAGAR="${LIMPAR_APAGAR:-0}"
modo=""
[ "$LIMPAR_APAGAR" = "1" ] && modo="--apagar"
python3 scripts/limpar_publicacoes_cloudflare.py --manter 5 $modo \
  || echo "::warning::A limpeza das publicações antigas da Cloudflare falhou (o deploy foi concluído normalmente). Veja o log acima."
exit 0
