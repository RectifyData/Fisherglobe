#!/usr/bin/env bash
# Fetch pinned sources outside Git. Never track Samsung firmware or upstream prebuilts here.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${FISHERGLOBE_WORK:-$ROOT/.work}"
mkdir -p "$WORK"
python3 "$ROOT/scripts/pins.py" checkout --work "$WORK" --name engine --sparse
# Fetch the exact gitlink revisions, not the current tips of their default branches.
python3 "$ROOT/scripts/pins.py" submodules --engine "$WORK/engine"
python3 "$ROOT/scripts/pins.py" checkout --work "$WORK" --name guide
python3 "$ROOT/scripts/pins.py" checkout --work "$WORK" --name samloader
printf 'Pinned engine: '; git -C "$WORK/engine" rev-parse HEAD
printf 'Pinned guide: '; git -C "$WORK/guide" rev-parse HEAD
