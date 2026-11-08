#!/usr/bin/env bash
# Orchestrates a real firmware build. Run on Ubuntu 24.04 with the dependencies
# listed in .github/workflows/build.yml. No adb/fastboot/flash commands exist here.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FISHERGLOBE_WORK="${FISHERGLOBE_WORK:-$ROOT/.work}"
WORK="$FISHERGLOBE_WORK"
ENGINE="$WORK/engine"
REPORTS="$ROOT/reports"
mkdir -p "$REPORTS"
CONFIG="${FISHERGLOBE_CONFIG:-$ROOT/config/port.json}"
STAGE="${1:-build}"
[[ "$STAGE" == inspect || "$STAGE" == build ]] || { echo 'Usage: build.sh [inspect|build]' >&2; exit 2; }

bash "$ROOT/scripts/fetch_sources.sh"
# samloader is installed editable into the exact venv layout expected by UN1CA.
# Its file logger is disabled before the first request (it otherwise logs IMEIs).
python3 - "$WORK/samloader/samloader/logging.py" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text().replace('logging_enabled = True', 'logging_enabled = False').replace('FUS = True', 'FUS = False')
p.write_text(s)
PY
mkdir -p "$ENGINE/out/tools"
if [[ ! -x "$ENGINE/out/tools/venv/bin/samloader" ]]; then
  python3 -m venv "$ENGINE/out/tools/venv"
  "$ENGINE/out/tools/venv/bin/pip" install --disable-pip-version-check -r "$WORK/samloader/requirements.txt"
  "$ENGINE/out/tools/venv/bin/pip" install --disable-pip-version-check --no-deps -e "$WORK/samloader"
fi

python3 "$ROOT/scripts/firmware.py" resolve --config "$CONFIG" --output "$REPORTS/firmware-plan.json"
cp "$REPORTS/firmware-plan.json" "$REPORTS/inputs.json"
export SRC_DIR="$ENGINE"
export OUT_DIR="$ENGINE/out"
export PATH="$OUT_DIR/tools/bin:$PATH"
cd "$ENGINE"
python3 - "$CONFIG" <<'PY'
import json, pathlib, sys
c = json.load(open(sys.argv[1]))['target']
p = pathlib.Path('target/a52sxq/config.sh')
p.write_text(p.read_text().replace('352599501234566', c['fus_tac']))
PY
# Initial extraction config is replaced after inspection by prepare_port.py.
source ./buildenv.sh a52sxq
./scripts/build_dependencies.sh |& tee "$REPORTS/dependencies.log"

python3 "$ROOT/scripts/firmware.py" download --config "$CONFIG" --work "$WORK" \
  --plan "$REPORTS/firmware-plan.json" --output "$REPORTS/downloaded.json"
./scripts/extract_fw.sh --force |& tee "$REPORTS/extract.log"
python3 "$ROOT/scripts/prepare_port.py" --engine "$ENGINE" --config "$CONFIG" --reports "$REPORTS"
# Reload the generated A54 source profile and a52sxq target configuration.
source ./buildenv.sh a52sxq
[[ "$TARGET_CODENAME" == a52sxq ]]
[[ "$SOURCE_FIRMWARE" == SM-A546* ]]
[[ "$TARGET_PLATFORM_SDK_VERSION" == 34 ]]
[[ "$TARGET_OS_FILE_SYSTEM_TYPE" == erofs ]]
cp "$OUT_DIR/config.sh" "$REPORTS/build-config.sh"
python3 "$ROOT/scripts/audit_firmware.py" --engine "$ENGINE" --config "$CONFIG" --reports "$REPORTS"
if [[ "$STAGE" == inspect ]]; then
  echo 'Inspection complete. No ROM was built or hardware tested.'
  exit 0
fi
./scripts/make_rom.sh --force --no-target-files |& tee "$REPORTS/build.log"
python3 "$ROOT/scripts/audit_firmware.py" --engine "$ENGINE" --config "$CONFIG" --reports "$REPORTS" --workdir
./scripts/make_rom.sh --build-rom-zip |& tee "$REPORTS/package.log"
python3 "$ROOT/scripts/validate_artifact.py" --engine "$ENGINE" --reports "$REPORTS" --output "$ROOT/out"
printf 'Build and package checks complete. Hardware boot remains UNTESTED.\n'
