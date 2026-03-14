#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -x "${PROJECT_ROOT}/aiflow" ]]; then
  "${PROJECT_ROOT}/aiflow" init >/dev/null
  exec "${PROJECT_ROOT}/aiflow" issue "$@"
fi

usage() {
  cat <<'EOF'
Usage:
  bash scripts/demo-issue.sh [issue]

This wrapper has been replaced by CLI command:
  aiflow issue "Trace rule-event pipeline"

Examples:
  bash scripts/demo-issue.sh "Explain authentication module"
EOF
}

usage >&2
exit 1