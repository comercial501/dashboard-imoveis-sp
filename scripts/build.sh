#!/bin/bash
# Regenerates data/dashboard_data.json from the source spreadsheets and embeds
# it into dashboard.html. Run this after updating the ITBI or Usenonstop files.
# For the weekly update workflow (with a change summary), use ../atualizar.sh
# at the project root instead.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/2: extraindo e agregando dados =="
perl build_data.pl

echo "== 2/2: gerando dashboard.html =="
perl embed_dashboard.pl
