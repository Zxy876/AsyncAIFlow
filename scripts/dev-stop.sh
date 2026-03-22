#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${LOG_DIR}/dev-start.pids"

matches_asyncaiflow_process() {
  local command="$1"

  [[ -z "${command}" ]] && return 1

  # Kill known AsyncAIFlow Java entrypoints regardless of checkout root, because stale
  # processes may come from another local clone and still interfere with localhost:8080.
  if [[ "${command}" == *"com.asyncaiflow.AsyncAiFlowApplication"* ]] || \
    [[ "${command}" == *"com.asyncaiflow.worker.repository.RepositoryWorkerApplication"* ]] || \
    [[ "${command}" == *"com.asyncaiflow.worker.gpt.GptWorkerApplication"* ]] || \
    [[ "${command}" == *"com.asyncaiflow.worker.git.GitWorkerApplication"* ]] || \
    [[ "${command}" == *"com.asyncaiflow.worker.planner.PlannerWorkerApplication"* ]] || \
    [[ "${command}" == *"design_gpt_worker/worker.py"* ]] || \
    [[ "${command}" == *"bfs_topology_worker/worker.py"* ]] || \
    [[ "${command}" == *"dp_nesting_worker/worker.py"* ]] || \
    [[ "${command}" == *"scan_processing_worker/worker.py"* ]] || \
    [[ "${command}" == *"assembly_worker/worker.py"* ]]; then
    return 0
  fi

  # Keep a conservative fallback for spring-boot launcher wrappers in this checkout.
  [[ "${command}" == *"${PROJECT_ROOT}"* ]] && [[ "${command}" == *"spring-boot:run"* ]]
}

stop_stale_asyncaiflow_processes() {
  local found=0
  local current_bash_pid="${BASHPID:-$$}"

  while IFS= read -r process_line; do
    [[ -z "${process_line}" ]] && continue

    local pid="${process_line%% *}"
    local command="${process_line#* }"

    [[ -z "${pid}" ]] && continue
    [[ "${pid}" == "$$" ]] && continue
    [[ "${pid}" == "${current_bash_pid}" ]] && continue

    if matches_asyncaiflow_process "${command}"; then
      found=1
      stop_pid stale-process "${pid}"
    fi
  done < <(ps ax -o pid= -o command=)

  if [[ "${found}" == "1" ]]; then
    printf '[dev-stop] stale AsyncAIFlow processes cleaned\n'
  fi
}

stop_pid() {
  local name="$1"
  local pid="$2"

  if [[ -z "${pid}" ]]; then
    return 0
  fi

  if ! [[ "${pid}" =~ ^[0-9]+$ ]]; then
    printf '[dev-stop] skip invalid pid for %s: %s\n' "$name" "$pid" >&2
    return 0
  fi

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    printf '[dev-stop] %s already stopped (pid=%s)\n' "$name" "$pid"
    return 0
  fi

  printf '[dev-stop] stopping %s (pid=%s)\n' "$name" "$pid"
  kill "$pid" >/dev/null 2>&1 || true

  for _ in {1..15}; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      printf '[dev-stop] %s stopped\n' "$name"
      return 0
    fi
    sleep 1
  done

  printf '[dev-stop] force stopping %s (pid=%s)\n' "$name" "$pid" >&2
  kill -9 "$pid" >/dev/null 2>&1 || true
}

if [[ -f "${PID_FILE}" ]]; then
  while IFS=':' read -r name pid; do
    [[ -z "${name}" ]] && continue
    stop_pid "$name" "$pid"
  done <"${PID_FILE}"
  rm -f "${PID_FILE}"
else
  printf '[dev-stop] no pid file found at %s\n' "${PID_FILE}"
fi

stop_stale_asyncaiflow_processes

if command -v docker >/dev/null 2>&1; then
  printf '[dev-stop] stopping docker services: mysql, redis\n'
  (
    cd "${PROJECT_ROOT}"
    docker compose stop mysql redis >/dev/null 2>&1 || true
  )
else
  printf '[dev-stop] docker command not found, skip container stop\n' >&2
fi

printf '[dev-stop] done\n'
