#!/bin/bash
# Atualização semanal da dashboard. Rode este comando depois de colar
# arquivos novos em dados-prefeitura/ e/ou dados-usenonstop/.
#
#   ./atualizar.sh
#
# Veja README.md para o passo a passo completo.
set -euo pipefail
cd "$(dirname "$0")"

DATA_DIR="data"
CURRENT_JSON="$DATA_DIR/dashboard_data.json"
BACKUP_JSON="$DATA_DIR/dashboard_data.previous.json"

echo "== Atualizando dashboard =="
echo

if [ -f "$CURRENT_JSON" ]; then
  cp "$CURRENT_JSON" "$BACKUP_JSON"
  HAS_BACKUP=1
else
  HAS_BACKUP=0
  echo "(primeira execução — sem dado anterior pra comparar)"
fi

echo "== 1/3: descobrindo arquivos e recalculando =="
perl scripts/build_data.pl

echo
echo "== 2/3: gerando dashboard.html =="
perl scripts/embed_dashboard.pl

echo
echo "== 3/3: resumo do que mudou =="
if [ "$HAS_BACKUP" = "1" ]; then
  perl scripts/compare_runs.pl "$BACKUP_JSON" "$CURRENT_JSON"
else
  echo "(nada para comparar ainda — rode de novo na próxima atualização para ver o resumo)"
fi

echo "Pronto. Abra dashboard.html no navegador para ver a versão atualizada."
