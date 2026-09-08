#!/usr/bin/env bash
# Idempotent environment for docker exec and Makefile targets.
# Source only. Does not activate the AMPL UUID (entrypoint does that once).

if [[ "${SANDO_DEV_ENV_LOADED:-0}" == "1" ]]; then
  return 0 2>/dev/null || exit 0
fi

SANDO_WS="${SANDO_WS:-/root/sando_ws}"
AMPL_VENV="${AMPL_VENV:-/opt/ampl-venv}"
AMPL_BASE_BIN="${AMPL_VENV}/lib/python3.10/site-packages/ampl_module_base/bin"
AMPL_GUROBI_BIN="${AMPL_VENV}/lib/python3.10/site-packages/ampl_module_gurobi/bin"
AMPLS_ROOT="${AMPLS_ROOT:-/opt/ampls-api}"
DEV_PYTHON="${SANDO_WS}/dev-python"
DEV_BUILD="${SANDO_WS}/build-dev"
DEV_INSTALL="${SANDO_WS}/install-dev"

if [[ -f /opt/ros/humble/setup.bash ]]; then
  # shellcheck disable=SC1091
  source /opt/ros/humble/setup.bash
fi
if [[ -f /root/livox_ws/install/setup.bash ]]; then
  # shellcheck disable=SC1091
  source /root/livox_ws/install/setup.bash
fi
if [[ -f "${SANDO_WS}/install/setup.bash" ]]; then
  # shellcheck disable=SC1091
  source "${SANDO_WS}/install/setup.bash"
fi
if [[ -f "${DEV_INSTALL}/setup.bash" ]]; then
  # shellcheck disable=SC1091
  source "${DEV_INSTALL}/setup.bash"
fi

export AMPL_VENV AMPL_BASE_BIN AMPL_GUROBI_BIN AMPLS_ROOT
export AMPL_LICFILE="${AMPL_LICFILE:-${AMPL_BASE_BIN}/ampl.lic}"
export AMPLKEY_RUNTIME_DIR="${AMPLKEY_RUNTIME_DIR:-/tmp/amplkey}"
export SANDO_AMPL_EXECUTABLE="${SANDO_AMPL_EXECUTABLE:-${AMPL_BASE_BIN}/ampl}"
export SANDO_AMPL_MODE="${SANDO_AMPL_MODE:-persistent}"
export PATH="${DEV_PYTHON}/bin:${AMPL_BASE_BIN}:${AMPL_GUROBI_BIN}:${PATH}"
export LD_LIBRARY_PATH="${AMPLS_ROOT}/libs/ampls/linux64:${AMPLS_ROOT}/libs/gurobi/lib/linux64:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="${SANDO_WS}/src/sando/scripts:${PYTHONPATH:-}"
export CMAKE_PREFIX_PATH="${DEV_INSTALL}:${CMAKE_PREFIX_PATH:-}"
export SANDO_DEV_BUILD="${DEV_BUILD}"
export SANDO_DEV_INSTALL="${DEV_INSTALL}"
export SANDO_DEV_ENV_LOADED=1
