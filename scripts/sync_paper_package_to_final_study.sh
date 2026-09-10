#!/usr/bin/env bash
# Sync paper-study-v2 frozen package into docs/final-study/ (plan2 goal path).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/docs/paper-study-v2"
DST="$ROOT/docs/final-study"
mkdir -p "$DST/paper-v2"
# Copy numbered package + audits + aggregates (not huge raw Gazebo trees)
rsync -a --delete \
  --include='*/' \
  --include='*.md' \
  --include='*.json' \
  --include='final/***' \
  --exclude='*' \
  "$SRC/" "$DST/paper-v2/"
# Pointer at final-study root
cat > "$DST/PAPER_V2_README.md" <<EOF
# Paper-level package (plan2)

Authoritative live package: \`docs/paper-study-v2/\`
Synced snapshot: \`docs/final-study/paper-v2/\`

Do not declare All done until \`paper-v2/FINAL_DOD_AUDIT.md\` (and JSON) show every §20 box PASS.
Historical §3 package files in this directory remain baseline artifacts.
EOF
echo "synced to $DST/paper-v2"
