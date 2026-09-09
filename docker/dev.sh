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
NUMPY_VERSION="${SANDO_NUMPY_VERSION:-1.21.5}"
TORCH_VERSION="${SANDO_TORCH_VERSION:-2.14.0+cpu}"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
ENV_FILE="/root/sando_ws/src/sando/docker/dev_env.sh"
LOCK_FILE="${HOST_WORKSPACE}/.dev-workflow.lock"

usage() {
  cat <<'EOF'
usage: docker/dev.sh up|build|test|shell|status|down|exec|freeze|release|smoke
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

image_id() { docker image inspect "${IMAGE}" --format '{{.Id}}' 2>/dev/null || true; }

validate_container() {
  local expected actual mount
  expected="$(image_id)"
  [[ -n "${expected}" ]] || { echo "requested development image is unavailable: ${IMAGE}" >&2; exit 67; }
  actual="$(docker inspect "${NAME}" --format '{{.Image}}' 2>/dev/null || true)"
  [[ "${actual}" == "${expected}" ]] || {
    echo "development container ${NAME} uses image ${actual:-<unknown>}, requested ${IMAGE} (${expected}); choose another SANDO_DEV_CONTAINER or explicitly remove the stopped container before reuse" >&2
    exit 68
  }
  while IFS='|' read -r mount; do
    [[ -z "${mount}" ]] && continue
    if ! docker inspect "${NAME}" --format '{{range .Mounts}}{{.Source}}|{{.Destination}}|{{.RW}}{{println}}{{end}}' | grep -Fqx "${mount}"; then
      echo "development container ${NAME} has an unexpected or missing mount: ${mount}" >&2
      exit 69
    fi
  done <<EOF
${AMPL_UUID_FILE}|/run/secrets/ampl_uuid|false
${ROOT_DIR}|/root/sando_ws/src/sando|true
${HOST_WORKSPACE}/build|/root/sando_ws/build-dev|true
${HOST_WORKSPACE}/install|/root/sando_ws/install-dev|true
${HOST_WORKSPACE}/log|/root/sando_ws/log-dev|true
${HOST_WORKSPACE}/python|/root/sando_ws/dev-python|true
${HOST_WORKSPACE}/results|/root/sando_ws/dev-results|true
EOF
}

with_lock() {
  mkdir -p "${HOST_WORKSPACE}"
  exec 9>"${LOCK_FILE}"
  flock -x 9
  "$@"
}

source_fingerprint() {
  python3 "${SCRIPT_DIR}/dev_identity.py" "${ROOT_DIR}"
}

write_build_identity() {
  printf '%s %s\n' "${1}" "$(docker inspect "${NAME}" --format '{{.Image}}')" > "${HOST_WORKSPACE}/.dev-build-identity"
}

build_identity_matches() {
  [[ -r "${HOST_WORKSPACE}/.dev-build-identity" ]] || return 1
  [[ "$(cat "${HOST_WORKSPACE}/.dev-build-identity")" == "$(source_fingerprint) $(image_id)" ]]
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
    validate_container
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
  /root/sando_ws/dev-python/bin/pip install "numpy==${NUMPY_VERSION}" "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu
"
}

build_unlocked() {
  if ! container_running; then up; else validate_container; fi
  local before
  before="$(source_fingerprint)"
  rm -f "${HOST_WORKSPACE}/.dev-build-identity"
  docker exec "${NAME}" bash -lc "mkdir -p /root/sando_ws/build-dev /root/sando_ws/install-dev /root/sando_ws/log-dev"
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && CMAKE_BUILD_PARALLEL_LEVEL=${BUILD_JOBS} MAKEFLAGS=-j${BUILD_JOBS} colcon build --paths /root/sando_ws/src/sando --packages-select sando --build-base /root/sando_ws/build-dev --install-base /root/sando_ws/install-dev --parallel-workers 1 --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo -DSANDO_USE_AMPL=ON -DAMPLS_ROOT=/opt/ampls-api"
  ensure_python
  [[ "${before}" == "$(source_fingerprint)" ]] || { echo "source changed during build; rebuild before testing or freezing" >&2; exit 71; }
  write_build_identity "${before}"
  fix_owner
}

build() { with_lock build_unlocked; }

test_unlocked() {
  if ! container_running; then up; else validate_container; fi
  if [[ ! -x "${HOST_WORKSPACE}/install/sando/lib/sando/sando" ]] || ! build_identity_matches; then
    build_unlocked
  fi
  ensure_python
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_set_loss.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_expert_labels.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_label_queue.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_instance_sampler.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_dagger_aggregate.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_capture_campaign.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_baseline_sim.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_integer_timing_policy.py && python3 /root/sando_ws/src/sando/tests/ampl_model/test_reconstructable_request.py"
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && ctest --test-dir /root/sando_ws/build-dev/sando --output-on-failure -R '^(segment_time_consistency|timing_policy_inference|planning_instance_roundtrip|instance_reservoir_sampling|ampl_adapter_real_model|ampl_objective_centering|integer_capture_campaign|baseline_arrival_checks|urdf_mesh_resources|integer_set_loss|integer_expert_labels|integer_label_queue|integer_queue_recovery|integer_post_capture_identity|integer_throughput|integer_instance_sampler|integer_dagger_aggregate|integer_timing_policy|reconstructable_request|frozen_planning_observation|reconstruct_planning_request)$'"
  docker exec "${NAME}" bash -lc "source '${ENV_FILE}' && python3 /root/sando_ws/src/sando/docker/dev_status.py"
}

test_cmd() { with_lock test_unlocked; }

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
  if ! container_running; then up; else validate_container; fi
  docker exec -it "${NAME}" bash -lc "source '${ENV_FILE}' && exec bash"
}

freeze_unlocked() {
  validate_container
  prepare_workspace
  if ! build_identity_matches; then
    echo "development build identity is missing or stale; run dev-build before freezing" >&2
    exit 70
  fi
  python3 - "${ROOT_DIR}" "${HOST_WORKSPACE}" "${IMAGE}" <<'PY'
import hashlib, json, shutil, subprocess, sys
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
    "schema_version": 2,
    "build_identity": (ws / ".dev-build-identity").read_text().strip(),
    "record_kind": "development-freeze-record",
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
binary = ws / "install/sando/lib/sando/sando"
if not binary.is_file():
    raise SystemExit("development executable missing; run dev-build first")
record_id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
artifact_dir = ws / "freeze" / "artifacts" / record_id
artifact_dir.mkdir(parents=True, exist_ok=True)
artifact = artifact_dir / "sando"
if not artifact.exists():
    temporary = artifact.with_suffix(".tmp")
    shutil.copy2(binary, temporary)
    if sha(temporary) != payload["dev_sando"]:
        raise SystemExit("binary changed while freezing")
    temporary.chmod(0o555)
    temporary.replace(artifact)
if sha(artifact) != payload["dev_sando"]:
    raise SystemExit("frozen artifact hash mismatch")
payload["record_id"] = record_id
payload["artifact"] = str(artifact.relative_to(ws))
record = ws / "freeze" / "records" / f"{record_id}.json"
record.parent.mkdir(parents=True, exist_ok=True)
if record.exists() and json.loads(record.read_text()) != payload:
    raise SystemExit("frozen record identity conflict")
if not record.exists():
    record.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
(ws / "freeze/latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(record)
PY
}

freeze() { with_lock freeze_unlocked; }

release_unlocked() {
  validate_container
  python3 "${SCRIPT_DIR}/freeze_release.py" --root "${ROOT_DIR}" --workspace "${HOST_WORKSPACE}" --base "${IMAGE}" --jobs "${BUILD_JOBS}"
}
release() { with_lock release_unlocked; }

smoke() {
  if ! container_running; then up; else validate_container; fi
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
    if ! container_running; then up; else validate_container; fi
    exec_in "$@"
    ;;
  freeze) freeze ;;
  release) release ;;
  smoke) smoke ;;
  probe)
    if ! container_running; then up; else validate_container; fi
    probe
    ;;
  *) usage; exit 64 ;;
esac
