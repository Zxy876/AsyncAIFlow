#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${ASYNCAIFLOW_BASE_URL:-http://localhost:8080}"
WAIT_SECONDS="${ASYNCAIFLOW_WAIT_SECONDS:-60}"
VIEW="json"
SAVE_PATH=""

usage() {
  cat <<'EOF'
Usage:
  bash scripts/demo-planner.sh [--json|--text] [--save path] [issue] [repo_context] [file]

Examples:
  bash scripts/demo-planner.sh "Explain authentication module"
  bash scripts/demo-planner.sh --text "Explain authentication module"
  bash scripts/demo-planner.sh --save plan.json "Explain authentication module"
  bash scripts/demo-planner.sh --text "Fix login retry bug" "web login flow" "src/main/java/com/example/auth/LoginService.java"
EOF
}

while (($# > 0)); do
  case "$1" in
    --json)
      VIEW="json"
      shift
      ;;
    --text)
      VIEW="text"
      shift
      ;;
    --save)
      if (($# < 2)); then
        printf '[demo-planner] missing path after --save\n' >&2
        usage >&2
        exit 1
      fi
      SAVE_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      printf '[demo-planner] unknown option: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

ISSUE="${1:-Explain authentication module}"
REPO_CONTEXT="${2:-}"
FILE_PATH="${3:-}"

wait_for_server() {
  local deadline=$((SECONDS + WAIT_SECONDS))
  while (( SECONDS < deadline )); do
    # A non-2xx HTTP response still means server is reachable, so we do not use --fail.
    if curl -s --connect-timeout 1 --max-time 2 \
      -o /dev/null "${BASE_URL}/action/poll?workerId=planner-demo-probe" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

if ! wait_for_server; then
  cat >&2 <<EOF
[demo-planner] cannot reach AsyncAIFlow server at ${BASE_URL}
[demo-planner] quick start (terminal 1):
  mvn spring-boot:run -Dspring-boot.run.profiles=local
[demo-planner] local profile still requires Redis:
  docker compose up -d redis
[demo-planner] planner worker (terminal 2, optional for preview endpoint):
  mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.planner.PlannerWorkerApplication -Dspring-boot.run.profiles=planner-worker
[demo-planner] if using default profile, start dependencies first:
  docker compose up -d
EOF
  exit 1
fi

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

render_text_plan() {
  local response="$1"

  if ! command -v jq >/dev/null 2>&1; then
    printf '[demo-planner] jq not found; falling back to JSON output\n' >&2
    printf '%s\n' "$response"
    return
  fi

  printf 'Issue: %s\n' "$ISSUE"
  if [[ -n "$REPO_CONTEXT" ]]; then
    printf 'Repo context: %s\n' "$REPO_CONTEXT"
  fi
  if [[ -n "$FILE_PATH" ]]; then
    printf 'File: %s\n' "$FILE_PATH"
  fi
  printf 'Mode: preview-only\n\n'
  printf 'Plan\n'
  printf '%s\n' "$response" | jq -r '
    .plan
    | to_entries[]
    | . as $entry
    | ($entry.key + 1) as $index
    | " " + ($index | tostring) + ". " + $entry.value.type
      + (if ($entry.value.depends_on | length) > 0
         then " <- depends on " + (($entry.value.depends_on | map(. + 1 | tostring)) | join(", "))
         else "" end)
      + "\n    " + (
          if (($entry.value.payload.query // "") != "") then
            "query: " + $entry.value.payload.query
          elif (($entry.value.payload.issue // "") != "") then
            "issue: " + $entry.value.payload.issue
          elif (($entry.value.payload.focus // "") != "") then
            "focus: " + $entry.value.payload.focus
          else
            "schemaVersion: " + ($entry.value.payload.schemaVersion // "n/a")
          end
        )
  '
}

issue_escaped="$(json_escape "$ISSUE")"
payload="{\"issue\":\"${issue_escaped}\""

if [[ -n "$REPO_CONTEXT" ]]; then
  repo_context_escaped="$(json_escape "$REPO_CONTEXT")"
  payload+=",\"repo_context\":\"${repo_context_escaped}\""
fi

if [[ -n "$FILE_PATH" ]]; then
  file_path_escaped="$(json_escape "$FILE_PATH")"
  payload+=",\"file\":\"${file_path_escaped}\""
fi

payload+="}"

response_file="$(mktemp)"
cleanup() {
  rm -f "$response_file"
}
trap cleanup EXIT

http_status="$(curl -sS -o "$response_file" -w "%{http_code}" -X POST "${BASE_URL}/planner/plan" \
  -H "Content-Type: application/json" \
  -d "$payload")"

if [[ "$http_status" -lt 200 || "$http_status" -ge 300 ]]; then
  printf '[demo-planner] request failed with HTTP %s\n' "$http_status" >&2
  cat "$response_file" >&2
  exit 1
fi

response="$(cat "$response_file")"

if [[ -n "$SAVE_PATH" ]]; then
  save_dir="$(dirname "$SAVE_PATH")"
  mkdir -p "$save_dir"
  if command -v jq >/dev/null 2>&1; then
    printf '%s\n' "$response" | jq . > "$SAVE_PATH"
  else
    printf '%s\n' "$response" > "$SAVE_PATH"
  fi
  printf '[demo-planner] saved plan to %s\n' "$SAVE_PATH" >&2
fi

if [[ "$VIEW" == "text" ]]; then
  render_text_plan "$response"
elif command -v jq >/dev/null 2>&1; then
  printf '%s\n' "$response" | jq .
else
  printf '%s\n' "$response"
fi
