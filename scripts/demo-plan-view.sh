#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -x "${PROJECT_ROOT}/aiflow" ]]; then
  exec "${PROJECT_ROOT}/aiflow" plan "$@"
fi

usage() {
  cat <<'EOF'
Usage:
  bash scripts/demo-plan-view.sh plan.json

This wrapper has been replaced by CLI command:
  aiflow plan plan.json
EOF
}

usage >&2
exit 1