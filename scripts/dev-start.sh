#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${LOG_DIR}/dev-start.pids"
CONFIG_FILE="${PROJECT_ROOT}/.aiflow/config.json"
RUNTIME_URL="${ASYNCAIFLOW_RUNTIME_URL:-http://localhost:8080}"
RUNTIME_DB_PASSWORD="${SPRING_DATASOURCE_PASSWORD:-root}"
MYSQL_HOST_PORT=""
RUNTIME_DB_URL=""
RUN_SUFFIX="$(date +%s)-$$"
REPOSITORY_WORKER_ID="${ASYNCAIFLOW_REPOSITORY_WORKER_ID:-repository-worker-dev-${RUN_SUFFIX}}"
GIT_WORKER_ID="${ASYNCAIFLOW_GIT_WORKER_ID:-git-worker-dev-${RUN_SUFFIX}}"
GPT_WORKER_ID="${ASYNCAIFLOW_GPT_WORKER_ID:-gpt-worker-dev-${RUN_SUFFIX}}"
DESIGN_GPT_WORKER_ID="${ASYNCAIFLOW_DESIGN_GPT_WORKER_ID:-design-gpt-worker-py}"
DESIGN_GPT_WORKER_DIR="${PROJECT_ROOT}/python-workers/design_gpt_worker"
BFS_TOPOLOGY_WORKER_ID="${ASYNCAIFLOW_BFS_TOPOLOGY_WORKER_ID:-bfs-topology-worker-py}"
BFS_TOPOLOGY_WORKER_DIR="${PROJECT_ROOT}/python-workers/bfs_topology_worker"
DP_NESTING_WORKER_ID="${ASYNCAIFLOW_DP_NESTING_WORKER_ID:-dp-nesting-worker-py}"
DP_NESTING_WORKER_DIR="${PROJECT_ROOT}/python-workers/dp_nesting_worker"
SCAN_PROCESSING_WORKER_ID="${ASYNCAIFLOW_SCAN_PROCESSING_WORKER_ID:-scan-processing-worker-py}"
SCAN_PROCESSING_WORKER_DIR="${PROJECT_ROOT}/python-workers/scan_processing_worker"
ASSEMBLY_WORKER_ID="${ASYNCAIFLOW_ASSEMBLY_WORKER_ID:-assembly-worker-py}"
ASSEMBLY_WORKER_DIR="${PROJECT_ROOT}/python-workers/assembly_worker"
LAST_STARTED_PID=""
LAST_STARTED_LOG_FILE=""

mkdir -p "${LOG_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  printf '[dev-start] docker command not found; please install Docker Desktop\n' >&2
  exit 1
fi

# Ensure the Docker daemon is running; on macOS auto-launch Docker Desktop if needed.
if ! docker info >/dev/null 2>&1; then
  printf '[dev-start] Docker daemon is not running\n'
  if [[ "$(uname)" == "Darwin" ]] && open -Ra "Docker" 2>/dev/null; then
    printf '[dev-start] launching Docker Desktop, please wait...\n'
    open -a Docker
  fi
  printf '[dev-start] waiting for Docker daemon (up to 60s)...\n'
  deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    if docker info >/dev/null 2>&1; then
      printf '[dev-start] Docker daemon is ready\n'
      break
    fi
    sleep 2
  done
  if ! docker info >/dev/null 2>&1; then
    printf '[dev-start] Docker daemon did not become ready within 60s; please start Docker Desktop manually\n' >&2
    exit 1
  fi
fi

if ! command -v mvn >/dev/null 2>&1; then
  printf '[dev-start] maven (mvn) is required\n' >&2
  exit 1
fi

printf '[dev-start] ensuring clean local startup state\n'
"${SCRIPT_DIR}/dev-stop.sh" >/dev/null 2>&1 || true

: > "${PID_FILE}"

append_pid() {
  local name="$1"
  local pid="$2"
  printf '%s:%s\n' "$name" "$pid" >>"${PID_FILE}"
}

read_config_value() {
  local key="$1"

  if [[ ! -f "${CONFIG_FILE}" ]]; then
    return 0
  fi

  python3 - "$CONFIG_FILE" "$key" <<'PY'
import json
import pathlib
import sys

config_path = pathlib.Path(sys.argv[1])
key = sys.argv[2]

try:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)

value = payload.get(key, "")
if isinstance(value, str):
    print(value)
PY
}

load_llm_environment() {
  if [[ -z "${GEMINI_MODEL:-}" ]]; then
    GEMINI_MODEL="$(read_config_value gemini_model)"
    if [[ -z "${GEMINI_MODEL}" ]]; then
      GEMINI_MODEL="$(read_config_value llm_model)"
    fi
    if [[ -z "${GEMINI_MODEL}" ]]; then
      GEMINI_MODEL="gemini-2.5-flash"
    fi
    export GEMINI_MODEL
  fi

  if [[ -z "${GEMINI_API_KEY:-}" ]]; then
    GEMINI_API_KEY="$(read_config_value gemini_api_key)"
    if [[ -z "${GEMINI_API_KEY}" ]]; then
      GEMINI_API_KEY="$(read_config_value llm_api_key)"
    fi
    export GEMINI_API_KEY
  fi

  if [[ -n "${GEMINI_MODEL:-}" ]]; then
    printf '[dev-start] gemini model: %s\n' "${GEMINI_MODEL}"
  fi
  if [[ -n "${GEMINI_API_KEY:-}" ]]; then
    printf '[dev-start] gemini api key detected\n'
  fi
}

is_port_listening() {
  local port="$1"
  lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
}

select_mysql_host_port() {
  if [[ -n "${ASYNCAIFLOW_MYSQL_PORT:-}" ]]; then
    MYSQL_HOST_PORT="${ASYNCAIFLOW_MYSQL_PORT}"
    if is_port_listening "${MYSQL_HOST_PORT}"; then
      printf '[dev-start] requested ASYNCAIFLOW_MYSQL_PORT=%s is already in use\n' "${MYSQL_HOST_PORT}" >&2
      return 1
    fi
    return 0
  fi

  if ! is_port_listening 3306; then
    MYSQL_HOST_PORT="3306"
    return 0
  fi

  for candidate in {3307..3320}; do
    if ! is_port_listening "${candidate}"; then
      MYSQL_HOST_PORT="${candidate}"
      printf '[dev-start] host port 3306 is occupied, mysql container will use localhost:%s\n' "${MYSQL_HOST_PORT}"
      return 0
    fi
  done

  printf '[dev-start] no free host port found for mysql in [3307..3320]; set ASYNCAIFLOW_MYSQL_PORT manually\n' >&2
  return 1
}

wait_for_compose_service() {
  local service="$1"
  local deadline=$((SECONDS + 120))

  while (( SECONDS < deadline )); do
    local container_id=""
    container_id=$(cd "${PROJECT_ROOT}" && ASYNCAIFLOW_MYSQL_PORT="${MYSQL_HOST_PORT}" docker compose ps -q "${service}" 2>/dev/null || true)

    if [[ -n "${container_id}" ]]; then
      local status=""
      status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}" 2>/dev/null || true)
      if [[ "${status}" == "healthy" ]]; then
        printf '[dev-start] %s is healthy\n' "${service}"
        return 0
      fi
    fi

    sleep 2
  done

  printf '[dev-start] %s did not become healthy within 120s\n' "${service}" >&2
  (cd "${PROJECT_ROOT}" && ASYNCAIFLOW_MYSQL_PORT="${MYSQL_HOST_PORT}" docker compose ps "${service}" >&2) || true
  return 1
}

print_log_excerpt() {
  local name="$1"
  local log_file="$2"

  if [[ ! -f "${log_file}" ]]; then
    return 0
  fi

  printf '[dev-start] last 40 lines of %s log (%s):\n' "$name" "$log_file" >&2
  tail -n 40 "${log_file}" >&2 || true
}

start_process() {
  local name="$1"
  shift

  local log_file="${LOG_DIR}/${name}.log"
  printf '[dev-start] starting %s -> %s\n' "$name" "$log_file"

  (
    cd "${PROJECT_ROOT}"
    "$@"
  ) >"${log_file}" 2>&1 &

  local pid=$!
  append_pid "$name" "$pid"
  LAST_STARTED_PID="$pid"
  LAST_STARTED_LOG_FILE="$log_file"
  printf '[dev-start] %s pid=%s\n' "$name" "$pid"
}

wait_for_runtime() {
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    if curl -s --noproxy '*' --connect-timeout 1 --max-time 2 -o /dev/null "${RUNTIME_URL}/action/poll?workerId=dev-start-probe"; then
      printf '[dev-start] runtime is reachable at %s\n' "${RUNTIME_URL}"
      return 0
    fi
    sleep 2
  done

  printf '[dev-start] runtime did not become reachable within 120s\n' >&2
  return 1
}

wait_for_worker_registration() {
  local name="$1"
  local worker_id="$2"
  local pid="$3"
  local log_file="$4"
  local deadline=$((SECONDS + 120))

  while (( SECONDS < deadline )); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      printf '[dev-start] %s exited before registering workerId=%s\n' "$name" "$worker_id" >&2
      print_log_excerpt "$name" "$log_file"
      return 1
    fi

    local http_code
    http_code=$(curl -sS --noproxy '*' --connect-timeout 2 --max-time 5 \
      -H 'Content-Type: application/json' \
      -d "{\"workerId\":\"${worker_id}\"}" \
      -o /dev/null -w "%{http_code}" \
      "${RUNTIME_URL}/worker/heartbeat" || true)

    if [[ "${http_code}" == "200" ]]; then
      printf '[dev-start] %s registered successfully as %s\n' "$name" "$worker_id"
      return 0
    fi

    sleep 2
  done

  printf '[dev-start] %s did not register within 120s (workerId=%s)\n' "$name" "$worker_id" >&2
  print_log_excerpt "$name" "$log_file"
  return 1
}

cleanup() {
  printf '\n[dev-start] Ctrl+C received, stopping services...\n'
  "${SCRIPT_DIR}/dev-stop.sh"
  exit 0
}

trap cleanup INT TERM

if ! select_mysql_host_port; then
  exit 1
fi

load_llm_environment

RUNTIME_DB_URL="${SPRING_DATASOURCE_URL:-jdbc:mysql://localhost:${MYSQL_HOST_PORT}/asyncaiflow?useSSL=false&serverTimezone=UTC}"

printf '[dev-start] starting docker services: mysql, redis\n'
(
  cd "${PROJECT_ROOT}"
  ASYNCAIFLOW_MYSQL_PORT="${MYSQL_HOST_PORT}" docker compose up -d mysql redis
)

if ! wait_for_compose_service mysql; then
  "${SCRIPT_DIR}/dev-stop.sh"
  exit 1
fi

if ! wait_for_compose_service redis; then
  "${SCRIPT_DIR}/dev-stop.sh"
  exit 1
fi

start_process runtime env "SPRING_DATASOURCE_PASSWORD=${RUNTIME_DB_PASSWORD}" "SPRING_DATASOURCE_URL=${RUNTIME_DB_URL}" mvn spring-boot:run

if ! wait_for_runtime; then
  printf '[dev-start] runtime start failed, see %s\n' "${LOG_DIR}/runtime.log" >&2
  "${SCRIPT_DIR}/dev-stop.sh"
  exit 1
fi

start_process repository-worker mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.repository.RepositoryWorkerApplication -Dspring-boot.run.profiles=repository-worker "-Dspring-boot.run.arguments=--asyncaiflow.repository-worker.worker-id=${REPOSITORY_WORKER_ID}"
repository_worker_pid="${LAST_STARTED_PID}"
repository_worker_log="${LAST_STARTED_LOG_FILE}"

start_process git-worker mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.git.GitWorkerApplication -Dspring-boot.run.profiles=git-worker "-Dspring-boot.run.arguments=--asyncaiflow.git-worker.worker-id=${GIT_WORKER_ID}"
git_worker_pid="${LAST_STARTED_PID}"
git_worker_log="${LAST_STARTED_LOG_FILE}"

start_process gpt-worker mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication -Dspring-boot.run.profiles=gpt-worker "-Dspring-boot.run.arguments=--asyncaiflow.gpt-worker.worker-id=${GPT_WORKER_ID}"
gpt_worker_pid="${LAST_STARTED_PID}"
gpt_worker_log="${LAST_STARTED_LOG_FILE}"

if ! wait_for_worker_registration repository-worker "${REPOSITORY_WORKER_ID}" "${repository_worker_pid}" "${repository_worker_log}"; then
  "${SCRIPT_DIR}/dev-stop.sh"
  exit 1
fi

if ! wait_for_worker_registration git-worker "${GIT_WORKER_ID}" "${git_worker_pid}" "${git_worker_log}"; then
  "${SCRIPT_DIR}/dev-stop.sh"
  exit 1
fi

if ! wait_for_worker_registration gpt-worker "${GPT_WORKER_ID}" "${gpt_worker_pid}" "${gpt_worker_log}"; then
  "${SCRIPT_DIR}/dev-stop.sh"
  exit 1
fi

# ── Design GPT Worker (Python) ──────────────────────────────────────────────
# Handles nl_to_design_dsl actions. Requires GEMINI_API_KEY and a virtualenv
# at python-workers/design_gpt_worker/.venv (run `python3 -m venv .venv &&
# pip install -r requirements.txt` once to create it).
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  printf '[dev-start] GEMINI_API_KEY not set — skipping design-gpt-worker (Python).\n'
  printf '[dev-start] nl_to_design_dsl tasks will stall. Set GEMINI_API_KEY or add it to .aiflow/config.json.\n'
elif [[ ! -f "${DESIGN_GPT_WORKER_DIR}/.venv/bin/python3" ]]; then
  printf '[dev-start] design-gpt-worker venv not found at %s/.venv — skipping.\n' "${DESIGN_GPT_WORKER_DIR}"
  printf '[dev-start] Run: cd %s && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n' "${DESIGN_GPT_WORKER_DIR}"
else
  start_process design-gpt-worker \
    env \
      "ASYNCAIFLOW_WORKER_ID=${DESIGN_GPT_WORKER_ID}" \
      "ASYNCAIFLOW_SERVER_BASE_URL=${RUNTIME_URL}" \
      "GEMINI_API_KEY=${GEMINI_API_KEY}" \
      "GEMINI_MODEL=${GEMINI_MODEL:-gemini-2.5-flash}" \
    "${DESIGN_GPT_WORKER_DIR}/.venv/bin/python3" "${DESIGN_GPT_WORKER_DIR}/worker.py"

  design_gpt_worker_pid="${LAST_STARTED_PID}"
  design_gpt_worker_log="${LAST_STARTED_LOG_FILE}"

  if ! wait_for_worker_registration design-gpt-worker "${DESIGN_GPT_WORKER_ID}" "${design_gpt_worker_pid}" "${design_gpt_worker_log}"; then
    printf '[dev-start] warning: design-gpt-worker did not register. Check %s\n' "${LOG_DIR}/design-gpt-worker.log" >&2
    printf '[dev-start] continuing — nl_to_design_dsl tasks will stall until worker comes online.\n' >&2
  else
    printf '[dev-start] design-gpt-worker registered as %s\n' "${DESIGN_GPT_WORKER_ID}"
  fi
fi
# ────────────────────────────────────────────────────────────────────────────

# ── BFS Topology Worker (Python) ─────────────────────────────────────────────
# Handles topology_validate actions (phase 2 of the design DAG).
# No LLM key required — pure graph analysis using networkx.
# Requires a virtualenv at python-workers/bfs_topology_worker/.venv
# (run `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` once).
if [[ ! -f "${BFS_TOPOLOGY_WORKER_DIR}/.venv/bin/python3" ]]; then
  printf '[dev-start] bfs-topology-worker venv not found at %s/.venv — skipping.\n' "${BFS_TOPOLOGY_WORKER_DIR}"
  printf '[dev-start] Run: cd %s && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n' "${BFS_TOPOLOGY_WORKER_DIR}"
else
  start_process bfs-topology-worker \
    env \
      "ASYNCAIFLOW_WORKER_ID=${BFS_TOPOLOGY_WORKER_ID}" \
      "ASYNCAIFLOW_SERVER_BASE_URL=${RUNTIME_URL}" \
    "${BFS_TOPOLOGY_WORKER_DIR}/.venv/bin/python3" "${BFS_TOPOLOGY_WORKER_DIR}/worker.py"

  bfs_topology_worker_pid="${LAST_STARTED_PID}"
  bfs_topology_worker_log="${LAST_STARTED_LOG_FILE}"

  if ! wait_for_worker_registration bfs-topology-worker "${BFS_TOPOLOGY_WORKER_ID}" "${bfs_topology_worker_pid}" "${bfs_topology_worker_log}"; then
    printf '[dev-start] warning: bfs-topology-worker did not register. Check %s\n' "${LOG_DIR}/bfs-topology-worker.log" >&2
    printf '[dev-start] continuing — topology_validate actions will stall until worker comes online.\n' >&2
  else
    printf '[dev-start] bfs-topology-worker registered as %s\n' "${BFS_TOPOLOGY_WORKER_ID}"
  fi
fi
# ─────────────────────────────────────────────────────────────────────────────

# ── DP Nesting Worker (Python) ───────────────────────────────────────────────
# Handles dp_nesting actions (phase 3 of the design DAG).
# Requires a virtualenv at python-workers/dp_nesting_worker/.venv
# (run `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` once).
if [[ ! -f "${DP_NESTING_WORKER_DIR}/.venv/bin/python3" ]]; then
  printf '[dev-start] dp-nesting-worker venv not found at %s/.venv — skipping.\n' "${DP_NESTING_WORKER_DIR}"
  printf '[dev-start] Run: cd %s && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n' "${DP_NESTING_WORKER_DIR}"
else
  start_process dp-nesting-worker \
    env \
      "ASYNCAIFLOW_WORKER_ID=${DP_NESTING_WORKER_ID}" \
      "ASYNCAIFLOW_SERVER_BASE_URL=${RUNTIME_URL}" \
    "${DP_NESTING_WORKER_DIR}/.venv/bin/python3" "${DP_NESTING_WORKER_DIR}/worker.py"

  dp_nesting_worker_pid="${LAST_STARTED_PID}"
  dp_nesting_worker_log="${LAST_STARTED_LOG_FILE}"

  if ! wait_for_worker_registration dp-nesting-worker "${DP_NESTING_WORKER_ID}" "${dp_nesting_worker_pid}" "${dp_nesting_worker_log}"; then
    printf '[dev-start] warning: dp-nesting-worker did not register. Check %s\n' "${LOG_DIR}/dp-nesting-worker.log" >&2
    printf '[dev-start] continuing — dp_nesting actions will stall until worker comes online.\n' >&2
  else
    printf '[dev-start] dp-nesting-worker registered as %s\n' "${DP_NESTING_WORKER_ID}"
  fi
fi
# ─────────────────────────────────────────────────────────────────────────────

# ── Scan Processing Worker (Python) ─────────────────────────────────────────
# Handles process_raw_scan actions for cleaning photogrammetry / LiDAR meshes.
# Requires a virtualenv at python-workers/scan_processing_worker/.venv
# (run `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` once).
if [[ ! -f "${SCAN_PROCESSING_WORKER_DIR}/.venv/bin/python3" ]]; then
  printf '[dev-start] scan-processing-worker venv not found at %s/.venv — skipping.\n' "${SCAN_PROCESSING_WORKER_DIR}"
  printf '[dev-start] Run: cd %s && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n' "${SCAN_PROCESSING_WORKER_DIR}"
else
  start_process scan-processing-worker \
    env \
      "ASYNCAIFLOW_WORKER_ID=${SCAN_PROCESSING_WORKER_ID}" \
      "ASYNCAIFLOW_SERVER_BASE_URL=${RUNTIME_URL}" \
    "${SCAN_PROCESSING_WORKER_DIR}/.venv/bin/python3" "${SCAN_PROCESSING_WORKER_DIR}/worker.py"

  scan_processing_worker_pid="${LAST_STARTED_PID}"
  scan_processing_worker_log="${LAST_STARTED_LOG_FILE}"

  if ! wait_for_worker_registration scan-processing-worker "${SCAN_PROCESSING_WORKER_ID}" "${scan_processing_worker_pid}" "${scan_processing_worker_log}"; then
    printf '[dev-start] warning: scan-processing-worker did not register. Check %s\n' "${LOG_DIR}/scan-processing-worker.log" >&2
    printf '[dev-start] continuing — process_raw_scan actions will stall until worker comes online.\n' >&2
  else
    printf '[dev-start] scan-processing-worker registered as %s\n' "${SCAN_PROCESSING_WORKER_ID}"
  fi
fi
# ─────────────────────────────────────────────────────────────────────────────

# ── Assembly Worker (Python) ────────────────────────────────────────────────
# Handles 3d_assembly_render actions for base-garment + module scene assembly.
# Requires a virtualenv at python-workers/assembly_worker/.venv
# (run `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` once).
if [[ ! -f "${ASSEMBLY_WORKER_DIR}/.venv/bin/python3" ]]; then
  printf '[dev-start] assembly-worker venv not found at %s/.venv — skipping.\n' "${ASSEMBLY_WORKER_DIR}"
  printf '[dev-start] Run: cd %s && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n' "${ASSEMBLY_WORKER_DIR}"
else
  start_process assembly-worker \
    env \
      "ASYNCAIFLOW_WORKER_ID=${ASSEMBLY_WORKER_ID}" \
      "ASYNCAIFLOW_SERVER_BASE_URL=${RUNTIME_URL}" \
    "${ASSEMBLY_WORKER_DIR}/.venv/bin/python3" "${ASSEMBLY_WORKER_DIR}/worker.py"

  assembly_worker_pid="${LAST_STARTED_PID}"
  assembly_worker_log="${LAST_STARTED_LOG_FILE}"

  if ! wait_for_worker_registration assembly-worker "${ASSEMBLY_WORKER_ID}" "${assembly_worker_pid}" "${assembly_worker_log}"; then
    printf '[dev-start] warning: assembly-worker did not register. Check %s\n' "${LOG_DIR}/assembly-worker.log" >&2
    printf '[dev-start] continuing — 3d_assembly_render actions will stall until worker comes online.\n' >&2
  else
    printf '[dev-start] assembly-worker registered as %s\n' "${ASSEMBLY_WORKER_ID}"
  fi
fi
# ─────────────────────────────────────────────────────────────────────────────

printf '[dev-start] all services started in background\n'
printf '[dev-start] logs directory: %s\n' "${LOG_DIR}"
printf '[dev-start] mysql host port: %s (container:3306)\n' "${MYSQL_HOST_PORT}"
printf '[dev-start] datasource url: %s\n' "${RUNTIME_DB_URL}"
printf '[dev-start] repository worker id: %s\n' "${REPOSITORY_WORKER_ID}"
printf '[dev-start] git worker id: %s\n' "${GIT_WORKER_ID}"
printf '[dev-start] gpt worker id: %s\n' "${GPT_WORKER_ID}"
printf '[dev-start] design-gpt-worker id: %s\n' "${DESIGN_GPT_WORKER_ID}"
printf '[dev-start] bfs-topology-worker id: %s\n' "${BFS_TOPOLOGY_WORKER_ID}"
printf '[dev-start] dp-nesting-worker id: %s\n' "${DP_NESTING_WORKER_ID}"
printf '[dev-start] scan-processing-worker id: %s\n' "${SCAN_PROCESSING_WORKER_ID}"
printf '[dev-start] assembly-worker id: %s\n' "${ASSEMBLY_WORKER_ID}"
printf '[dev-start] press Ctrl+C to stop runtime, workers, and docker services\n'

while true; do
  sleep 2

done
