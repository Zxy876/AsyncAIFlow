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
  if [[ -z "${OPENAI_BASE_URL:-}" ]]; then
    OPENAI_BASE_URL="$(read_config_value llm_base_url)"
    export OPENAI_BASE_URL
  fi

  if [[ -z "${OPENAI_ENDPOINT:-}" ]]; then
    OPENAI_ENDPOINT="$(read_config_value llm_endpoint)"
    export OPENAI_ENDPOINT
  fi

  if [[ -z "${OPENAI_MODEL:-}" ]]; then
    OPENAI_MODEL="$(read_config_value llm_model)"
    export OPENAI_MODEL
  fi

  if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    OPENAI_API_KEY="$(read_config_value llm_api_key)"
    if [[ -z "${OPENAI_API_KEY}" ]]; then
      OPENAI_API_KEY="$(read_config_value openai_api_key)"
    fi
    export OPENAI_API_KEY
  fi

  if [[ -n "${OPENAI_BASE_URL:-}" ]]; then
    printf '[dev-start] llm base url: %s\n' "${OPENAI_BASE_URL}"
  fi
  if [[ -n "${OPENAI_ENDPOINT:-}" ]]; then
    printf '[dev-start] llm endpoint: %s\n' "${OPENAI_ENDPOINT}"
  fi
  if [[ -n "${OPENAI_MODEL:-}" ]]; then
    printf '[dev-start] llm model: %s\n' "${OPENAI_MODEL}"
  fi
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    printf '[dev-start] llm api key detected\n'
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

printf '[dev-start] all services started in background\n'
printf '[dev-start] logs directory: %s\n' "${LOG_DIR}"
printf '[dev-start] mysql host port: %s (container:3306)\n' "${MYSQL_HOST_PORT}"
printf '[dev-start] datasource url: %s\n' "${RUNTIME_DB_URL}"
printf '[dev-start] repository worker id: %s\n' "${REPOSITORY_WORKER_ID}"
printf '[dev-start] git worker id: %s\n' "${GIT_WORKER_ID}"
printf '[dev-start] gpt worker id: %s\n' "${GPT_WORKER_ID}"
printf '[dev-start] press Ctrl+C to stop runtime, workers, and docker services\n'

while true; do
  sleep 2

done
