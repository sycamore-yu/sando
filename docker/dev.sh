#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE="${SANDO_DEV_IMAGE:-sando-integer-centered:20260907}"
NAME="${SANDO_DEV_CONTAINER:-sando-dev}"
AMPL_UUID_FILE="${AMPL_UUID_FILE:-${HOME}/.config/ampl/uuid}"
HOST_WORKSPACE="${SANDO_DEV_WORKSPACE:-${ROOT_DIR}/docker/dev-workspace}"
BUILD_JOBS="${BUILD_JOBS:-2}"
ROS_DOMAIN_ID="${SANDO_DEV_ROS_DOMAIN_ID:-91}"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
ENV_FILE="/root/sando_ws/src/sando/docker/dev_env.sh"
LOCK_FILE="/root/sando_ws/build-dev/.dev-build.lock"

usage() {
  cat <<'EOF'
usage: docker/dev.sh up|build|test|shell|status|down|exec|freeze|smoke
EOF
}

need_uuid() {
  if [[ ! -r "${AMPL_UUID_FILE}" ]]; then
    echo "AMPL UUID file is not readable: ${AMPL_UUID_FILE}" >&2
    exit 64
  fi
}

check_source() {
  if [[ ! -f "${ROOT_DIR}/package.xml" || ! -f "${ROOT_DIR}/CMakeLists.txt" ]]; then
    echo "host source is incomplete: ${ROOT_DIR}" >&2
    exit 65
  fi
  local missing=0
  local dep
  for dep in DecompROS2 dynus_interfaces gazebo_ros_pkgs uav_simulator; do
    if [[ ! -e "${ROOT_DIR}/deps/${dep}" ]]; then
      echo "missing submodule checkout: deps/${dep}" >&2
      missing=1
    fi
  done
  if [[ "${missing}" -ne 0 ]]; then
    exit 66
  fi
}

container_running() {
  docker inspect -f '{{.State.Running}}' "${NAME}" 2>/dev/null | grep -qx true
}

exec_in() {
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && $(printf '%q ' "$@")"
}

prepare_workspace() {
  mkdir -p "${HOST_WORKSPACE}/build" "${HOST_WORKSPACE}/install" "${HOST_WORKSPACE}/log" \
    "${HOST_WORKSPACE}/python" "${HOST_WORKSPACE}/results" "${HOST_WORKSPACE}/freeze"
}

up() {
  need_uuid
  check_source
  prepare_workspace
  if docker inspect "${NAME}" >/dev/null 2>&1; then
    if container_running; then
      echo "development container ${NAME} is already running"
    else
      docker start "${NAME}" >/dev/null
    fi
  else
    docker run -d \
      --name "${NAME}" \
      --env HEADLESS=1 \
      --env ROS_DOMAIN_ID="${ROS_DOMAIN_ID}" \
      --env SANDO_AMPL_MODE=persistent \
      --env SANDO_DEV=1 \
      --env HOST_UID="${HOST_UID}" \
      --env HOST_GID="${HOST_GID}" \
      --mount "type=bind,src=${AMPL_UUID_FILE},dst=/run/secrets/ampl_uuid,readonly" \
      --mount "type=bind,src=${ROOT_DIR},dst=/root/sando_ws/src/sando" \
      --mount "type=bind,src=${HOST_WORKSPACE}/build,dst=/root/sando_ws/build-dev" \
      --mount "type=bind,src=${HOST_WORKSPACE}/install,dst=/root/sando_ws/install-dev" \
      --mount "type=bind,src=${HOST_WORKSPACE}/log,dst=/root/sando_ws/log-dev" \
      --mount "type=bind,src=${HOST_WORKSPACE}/python,dst=/root/sando_ws/dev-python" \
      --mount "type=bind,src=${HOST_WORKSPACE}/results,dst=/root/sando_ws/dev-results" \
      --workdir /root/sando_ws \
      "${IMAGE}" \
      sleep infinity >/dev/null
  fi
  docker exec "${NAME}" bash -lc "test -r '${AMPL_LICFILE:-/opt/ampl-venv/lib/python3.10/site-packages/ampl_module_base/bin/ampl.lic}'"
  probe
  echo "development container ${NAME} is ready"
}

probe() {
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && /opt/ampl-venv/bin/python - <<'PY'
from pathlib import Path
import os
lic = Path(os.environ['AMPL_LICFILE'])
exe = Path(os.environ['SANDO_AMPL_EXECUTABLE'])
assert lic.is_file(), 'AMPL license file missing'
assert exe.is_file(), 'AMPL executable missing'
from amplpy import AMPL
ampl = AMPL()
ampl.option['solver'] = 'gurobi'
ampl.eval('var x >= 0; minimize o: (x - 1)*(x - 1);')
ampl.solve()
x = float(ampl.get_variable('x').value())
if abs(x - 1.0) > 1e-4:
    raise SystemExit(f'AMPL/Gurobi probe failed: x={x}')
print('ampl_gurobi_probe_ok x=', x)
PY"
}

fix_owner() {
  docker exec "${NAME}" bash -lc "chown -R ${HOST_UID}:${HOST_GID} /root/sando_ws/build-dev /root/sando_ws/install-dev /root/sando_ws/log-dev /root/sando_ws/dev-python /root/sando_ws/dev-results || true"
}

ensure_python() {
  # Keep system site-packages so ROS deps (PyYAML, etc.) stay importable when
  # PATH prefers /root/sando_ws/dev-python/bin/python3 for torch.
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && set -euo pipefail
need_venv=0
if [[ ! -x /root/sando_ws/dev-python/bin/python ]]; then
  need_venv=1
elif ! /root/sando_ws/dev-python/bin/python -c 'import yaml' 2>/dev/null; then
  need_venv=1
fi
if [[ \"\${need_venv}\" -eq 1 ]]; then
  # bind-mount root cannot be removed; clear contents only
  find /root/sando_ws/dev-python -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  /usr/bin/python3 -m venv --system-site-packages /root/sando_ws/dev-python
fi
/root/sando_ws/dev-python/bin/python -c 'import torch,numpy' 2>/dev/null || \
  /root/sando_ws/dev-python/bin/pip install numpy torch --index-url https://download.pytorch.org/whl/cpu
"
}

build() {
  if ! container_running; then
    up
  fi
  docker exec "${NAME}" bash -lc "mkdir -p /root/sando_ws/build-dev /root/sando_ws/install-dev /root/sando_ws/log-dev"
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && flock '${LOCK_FILE}' colcon build --packages-select sando --build-base /root/sando_ws/build-dev --install-base /root/sando_ws/install-dev --parallel-workers ${BUILD_JOBS} --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo -DSANDO_USE_AMPL=ON -DAMPLS_ROOT=/opt/ampls-api"
  ensure_python
  fix_owner
}

test_cmd() {
  if ! container_running; then
    up
  fi
  if [[ ! -x "${HOST_WORKSPACE}/install/sando/lib/sando/sando" ]]; then
    build
  fi
  ensure_python
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_set_loss.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_expert_labels.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_label_queue.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_instance_sampler.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_dagger_aggregate.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_capture_campaign.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_baseline_sim.py"
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && ctest --test-dir /root/sando_ws/build-dev/sando --output-on-failure -R '^(segment_time_consistency|planning_instance_roundtrip|instance_reservoir_sampling|ampl_adapter_real_model|ampl_objective_centering|integer_capture_campaign|baseline_arrival_checks|urdf_mesh_resources|integer_set_loss|integer_expert_labels|integer_label_queue|integer_instance_sampler|integer_dagger_aggregate)$'"
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && python3 /root/sando_ws/src/sando/docker/dev_status.py"
}

status() {
  echo "host_root ${ROOT_DIR}"
  git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD
  git -C "${ROOT_DIR}" rev-parse HEAD
  git -C "${ROOT_DIR}" status --porcelain
  echo "image ${IMAGE}"
  docker image inspect "${IMAGE}" --format 'image_id={{.Id}}'
  if docker inspect "${NAME}" >/dev/null 2>&1; then
    docker inspect "${NAME}" --format 'container={{.Name}} running={{.State.Running}} image={{.Config.Image}} id={{.Image}}'
    docker inspect "${NAME}" --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} rw={{.RW}}{{println}}{{end}}'
  else
    echo "container ${NAME} is absent"
  fi
  if container_running; then
    docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && python3 /root/sando_ws/src/sando/docker/dev_status.py"
  fi
  if docker inspect sando-integer-centered >/dev/null 2>&1; then
    docker inspect sando-integer-centered --format 'official={{.Name}} running={{.State.Running}} image={{.Config.Image}}'
    docker exec sando-integer-centered sha256sum /opt/sando-integer-source.json /root/sando_ws/install/sando/lib/sando/sando
  fi
}

down() {
  if docker inspect "${NAME}" >/dev/null 2>&1; then
    docker stop "${NAME}" >/dev/null
    echo "stopped ${NAME}; workspace kept at ${HOST_WORKSPACE}"
  else
    echo "container ${NAME} is absent"
  fi
}

shell() {
  if ! container_running; then
    up
  fi
  docker exec -it "${NAME}" bash -lc "source '${ENV_FILE}' && exec bash"
}

freeze() {
  prepare_workspace
  python3 - "${ROOT_DIR}" "${HOST_WORKSPACE}" "${IMAGE}" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
root, ws_path, image = map(Path, sys.argv[1:4])
ws = ws_path
def run(args):
    return subprocess.check_output(args, cwd=root, text=True).strip()
def sha(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
image_id = subprocess.check_output(["docker", "image", "inspect", str(image), "--format", "{{.Id}}"], text=True).strip()
config = json.loads((root / "scripts/process_improvement_v1.json").read_text())
payload = {
    "git_head": run(["git", "rev-parse", "HEAD"]),
    "git_branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    "git_status": run(["git", "status", "--porcelain"]),
    "submodules": run(["git", "submodule", "status"]),
    "image": str(image),
    "image_id": image_id,
    "dev_sando": sha(ws / "install/sando/lib/sando/sando"),
    "config": config,
    "config_sha256": hashlib.sha256((root / "scripts/process_improvement_v1.json").read_bytes()).hexdigest(),
}
(ws / "freeze/latest.json").write_text(json.dumps(payload, indent=2) + "\n")
print((ws / "freeze/latest.json").read_text())
PY
}

smoke() {
  if ! container_running; then
    up
  fi
  local marker="${ROOT_DIR}/.sando_dev_mount_check"
  echo "host-visible" > "${marker}"
  docker exec "${NAME}" bash -lc "test -f /root/sando_ws/src/sando/.sando_dev_mount_check && echo container-visible >> /root/sando_ws/src/sando/.sando_dev_mount_check"
  grep -q container-visible "${marker}"
  rm -f "${marker}"
  echo "bind_mount_ok host=${ROOT_DIR} container=/root/sando_ws/src/sando"
}

cmd="${1:-}"
shift || true
case "${cmd}" in
  up) up ;;
  build) build ;;
  test) test_cmd ;;
  shell) shell ;;
  status) status ;;
  down) down ;;
  exec)
    if ! container_running; then up; fi
    exec_in "$@"
    ;;
  freeze) freeze ;;
  smoke) smoke ;;
  probe)
    if ! container_running; then up; fi
    probe
    ;;
  *) usage; exit 64 ;;
esac
