#!/usr/bin/env bash
set -euo pipefail

AMPL_VENV="${AMPL_VENV:-/opt/ampl-venv}"
AMPL_BASE_BIN="${AMPL_VENV}/lib/python3.10/site-packages/ampl_module_base/bin"
AMPL_GUROBI_BIN="${AMPL_VENV}/lib/python3.10/site-packages/ampl_module_gurobi/bin"
export AMPL_BASE_BIN AMPL_GUROBI_BIN
export AMPL_LICFILE="${AMPL_BASE_BIN}/ampl.lic"
export AMPLKEY_RUNTIME_DIR="${AMPLKEY_RUNTIME_DIR:-/tmp/amplkey}"
mkdir -p "${AMPLKEY_RUNTIME_DIR}"

if [[ ! -r /run/secrets/ampl_uuid ]]; then
  echo "AMPL license secret is required at /run/secrets/ampl_uuid" >&2
  exit 64
fi

# Read the UUID inside Python so it is never placed in a command line, shell
# trace, environment listing, or diagnostic message.
"${AMPL_VENV}/bin/python" - <<'PY'
from amplpy import modules

with open("/run/secrets/ampl_uuid", encoding="utf-8") as secret:
    uuid = secret.read().strip()
if not uuid:
    raise SystemExit("AMPL license secret is empty")
modules.activate(uuid, verbose=False)
PY

if [[ ! -r "${AMPL_LICFILE}" ]]; then
  echo "AMPL activation did not produce the module license file" >&2
  exit 65
fi
export PATH="${AMPL_BASE_BIN}:${AMPL_GUROBI_BIN}:${PATH}"
export SANDO_AMPL_EXECUTABLE="${SANDO_AMPL_EXECUTABLE:-${AMPL_BASE_BIN}/ampl}"
export AMPLS_ROOT="${AMPLS_ROOT:-/opt/ampls-api}"
export LD_LIBRARY_PATH="${AMPLS_ROOT}/libs/ampls/linux64:${AMPLS_ROOT}/libs/gurobi/lib/linux64:${LD_LIBRARY_PATH:-}"

xvfb_pid=""
if [[ "${HEADLESS:-0}" == "1" && -z "${DISPLAY:-}" ]]; then
  Xvfb :99 -screen 0 1280x1024x24 >/tmp/sando-xvfb.log 2>&1 &
  xvfb_pid=$!
  export DISPLAY=:99
  for _ in {1..50}; do
    [[ -S /tmp/.X11-unix/X99 ]] && break
    sleep 0.1
  done
  if [[ ! -S /tmp/.X11-unix/X99 ]]; then
    echo "Xvfb did not become ready" >&2
    exit 66
  fi
fi
cleanup() {
  if [[ -n "${xvfb_pid}" ]]; then
    kill "${xvfb_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "$#" -gt 0 ]]; then
  exec "$@"
fi
exec /sando.sh
