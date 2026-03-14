#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ISSUE="${1:-Explain how Drift story engine interacts with the Minecraft plugin}"
REPO_CONTEXT="${2:-DriftSystem backend story routes and Minecraft plugin integration}"
FILE_PATH="${3:-backend/app/routers/story.py}"
MODULE_NAME="${4:-story-engine}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/demo-generate-explanation.sh [issue] [repo_context] [file] [module]

Examples:
  bash scripts/demo-generate-explanation.sh
  bash scripts/demo-generate-explanation.sh "Explain how Drift story engine interacts with the Minecraft plugin"
EOF
}

if [[ "${ISSUE}" == "-h" || "${ISSUE}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  printf '[demo-generate-explanation] python3 is required\n' >&2
  exit 1
fi

planner_plan_file="$(mktemp)"
runtime_plan_file="$(mktemp)"

cleanup() {
  rm -f "$planner_plan_file" "$runtime_plan_file"
}
trap cleanup EXIT

printf '[demo-generate-explanation] step 1/3: planner preview for DriftSystem issue\n' >&2
"${SCRIPT_DIR}/demo-planner.sh" --text --save "$planner_plan_file" "$ISSUE" "$REPO_CONTEXT" "$FILE_PATH"

printf '[demo-generate-explanation] step 2/3: validate expected planner chain and prepare runtime plan\n' >&2
python3 - "$planner_plan_file" "$runtime_plan_file" "$MODULE_NAME" <<'PY'
import json
import sys

planner_plan_path = sys.argv[1]
runtime_plan_path = sys.argv[2]
module_name = sys.argv[3]

with open(planner_plan_path, 'r', encoding='utf-8') as handle:
    planner_plan_root = json.load(handle)

plan = planner_plan_root.get('plan')
if not isinstance(plan, list):
    raise SystemExit('[demo-generate-explanation] invalid planner response: missing plan array')

expected_chain = ['search_code', 'analyze_module', 'generate_explanation']
actual_chain = [step.get('type', '') for step in plan]

if len(actual_chain) < 3 or actual_chain[:3] != expected_chain:
    raise SystemExit(
        '[demo-generate-explanation] unexpected planner chain. expected first steps '
        f'{expected_chain}, got {actual_chain}'
    )

explanation_step = dict(plan[2])
payload = dict(explanation_step.get('payload') or {})
payload.setdefault('module', module_name)
payload.setdefault('gathered_context', {
    'source': 'planner-preview',
    'upstream_steps': expected_chain[:2],
    'note': 'Use search/analyze outputs from full runtime in future iterations.'
})

runtime_plan = {
    'plan': [
        {
            'type': 'generate_explanation',
            'payload': payload,
            'depends_on': []
        }
    ]
}

with open(runtime_plan_path, 'w', encoding='utf-8') as handle:
    json.dump(runtime_plan, handle, ensure_ascii=False, indent=2)

print('[demo-generate-explanation] planner chain verified: search_code -> analyze_module -> generate_explanation')
print('[demo-generate-explanation] runtime plan prepared with 1 executable step: generate_explanation')
PY

cat <<'EOF' >&2
[demo-generate-explanation] step 3/3: submit generate_explanation action to runtime
[demo-generate-explanation] reminder: keep gpt-worker running in another terminal.
EOF

"${SCRIPT_DIR}/demo-run.sh" "$runtime_plan_file"

cat <<'EOF'
[demo-generate-explanation] done.
[demo-generate-explanation] check gpt-worker logs for the generated explanation output.
EOF