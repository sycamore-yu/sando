#!/usr/bin/env bash
set -euo pipefail

# Install the AMPL Python runtime, the pinned AMPLS C++ API, and the public
# Gurobi 13 solver libraries used by AMPLS.  This script intentionally accepts
# no license material: AMPL activation happens only when the container starts.

AMPLS_ROOT="${AMPLS_ROOT:-/opt/ampls-api}"
AMPL_VENV="${AMPL_VENV:-/opt/ampl-venv}"
AMPLS_COMMIT="9ceda9a9b32d6cc3c4428210c3824fa93b0dc0e1"
SOLVER_LIBS_URL="https://ampl.com/dl/fdabrandao/solver-public-libs.zip"
SOLVER_LIBS_SHA256="a17a86e39678a9fdfdce7eed9c78951663123e5f5cb6ad20be0b82b16dd3718f"

python3 -m venv "${AMPL_VENV}"
"${AMPL_VENV}/bin/python" -m pip install --no-cache-dir --upgrade pip
"${AMPL_VENV}/bin/python" -m pip install --no-cache-dir amplpy==0.18.0
"${AMPL_VENV}/bin/python" -m pip install --no-cache-dir \
  --index-url https://pypi.ampl.com \
  ampl_module_base==20260809 ampl_module_gurobi==20260624

"${AMPL_VENV}/bin/python" - <<'PY'
import importlib
import sys

for name, expected in (
    ("amplpy", "0.18.0"),
    ("ampl_module_base", "20260809"),
    ("ampl_module_gurobi", "20260624"),
):
    module = importlib.import_module(name)
    actual = getattr(module, "__version__", "")
    if actual != expected:
        raise SystemExit(f"{name} version {actual!r}, expected {expected!r}")
print("AMPL Python packages verified", file=sys.stderr)
PY

if [[ -e "${AMPLS_ROOT}" && ! -d "${AMPLS_ROOT}/.git" ]]; then
  if [[ -n "$(find "${AMPLS_ROOT}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "AMPLS_ROOT exists and is not an empty AMPLS checkout: ${AMPLS_ROOT}" >&2
    exit 64
  fi
fi
if [[ ! -d "${AMPLS_ROOT}/.git" ]]; then
  git clone https://github.com/ampl/ampls-api.git "${AMPLS_ROOT}"
fi
git -C "${AMPLS_ROOT}" fetch --tags --depth 1 origin "${AMPLS_COMMIT}"
git -C "${AMPLS_ROOT}" checkout --detach "${AMPLS_COMMIT}"
git -C "${AMPLS_ROOT}" submodule update --init --recursive

archive=/tmp/sando-solver-public-libs.zip
extract=/tmp/sando-solver-public-libs
curl --fail --location --retry 3 --silent --show-error \
  "${SOLVER_LIBS_URL}" --output "${archive}"
echo "${SOLVER_LIBS_SHA256}  ${archive}" | sha256sum --check --strict
rm -rf "${extract}"
mkdir -p "${extract}"
unzip -q "${archive}" -d "${extract}"

# The release currently contains solver-public-libs/solver-public-libs. Keep
# the AMPLS checkout's documented libs/gurobi location independent of that
# archive wrapper while preserving its include/lib/linux64 contents.
solver_root="${extract}/solver-public-libs/solver-public-libs"
if [[ ! -d "${solver_root}" ]]; then
  solver_root="${extract}/solver-public-libs"
fi
[[ -d "${solver_root}/gurobi" ]] || {
  echo "solver-public-libs archive has no gurobi directory" >&2
  exit 1
}
mkdir -p "${AMPLS_ROOT}/libs"
mkdir -p "${AMPLS_ROOT}/libs/gurobi"
cp -a "${solver_root}/gurobi/." "${AMPLS_ROOT}/libs/gurobi/"

[[ -d "${solver_root}/ampls/linux64" ]] || {
  echo "solver-public-libs archive has no ampls/linux64 directory" >&2
  exit 1
}
mkdir -p "${AMPLS_ROOT}/libs/ampls/linux64"
cp -a "${solver_root}/ampls/linux64/." "${AMPLS_ROOT}/libs/ampls/linux64/"
[[ -s "${AMPLS_ROOT}/libs/ampls/linux64/libgurobi-lib.so" ]] || {
  echo "solver-public-libs archive has no AMPLS Gurobi driver" >&2
  exit 1
}

rm -rf "${extract}" "${archive}"
