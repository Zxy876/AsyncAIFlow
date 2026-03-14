#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -x "${PROJECT_ROOT}/aiflow" ]]; then
  "${PROJECT_ROOT}/aiflow" init >/dev/null
  exec "${PROJECT_ROOT}/aiflow" run "$@"
fi

usage() {
  cat <<'EOF'
Usage:
  bash scripts/demo-run.sh plan.json

This wrapper has been replaced by CLI command:
  aiflow run plan.json
EOF
}

usage >&2
exit 1