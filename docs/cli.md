# AsyncAIFlow CLI

## 1. Overview

AsyncAIFlow CLI turns runtime + planner APIs into a local developer tool.

Main entrypoint:

- `aiflow`

Commands in this milestone:

- `aiflow init`
- `aiflow issue`
- `aiflow plan`
- `aiflow run`
- `aiflow status`
- `aiflow summary`
- `aiflow interactive`

Scope boundary:

- CLI only calls runtime APIs.
- No planner logic changes.
- No scheduler core changes.
- No worker capability expansion beyond existing runtime behavior.

## 2. Installation

### 2.1 Prerequisites

- Python 3.9+
- AsyncAIFlow runtime reachable (default: `http://localhost:8080`)

### 2.2 Install command locally

From AsyncAIFlow repository root:

```bash
chmod +x aiflow
```

Option A: symlink into PATH (macOS/Linux):

```bash
sudo ln -sf "$(pwd)/aiflow" /usr/local/bin/aiflow
```

Option B: project-local PATH export:

```bash
export PATH="$(pwd):$PATH"
```

Validate installation:

```bash
aiflow --help
```

## 3. Initialization

Initialize in your target project directory:

```bash
aiflow init
```

This creates:

- `.aiflow/config.json`

Generated config shape:

```json
{
  "openai_api_key": "",
  "deepseek_api_key": "",
  "runtime_url": "http://localhost:8080"
}
```

If API keys are empty, worker-side execution can still run in mock fallback mode.

## 4. Commands

### 4.1 aiflow issue

Generate a plan from natural language issue:

```bash
aiflow issue "Trace rule-event pipeline"
```

Default output:

```text
AsyncAIFlow Plan

1 search_code
2 analyze_module
3 generate_explanation
```

Useful options:

- `--save plan.json`
- `--edit`
- `--repo-context "..."`
- `--file backend/app/routers/story.py`
- `--json`

Example:

```bash
aiflow issue \
  "Explain how Drift story engine interacts with the Minecraft plugin" \
  --repo-context "DriftSystem backend story routes and Minecraft plugin integration" \
  --file backend/app/routers/story.py \
  --save plan.json
```

### 4.2 aiflow plan

Render readable plan tree from file:

```bash
aiflow plan plan.json
```

### 4.3 aiflow run

Submit plan file to runtime and create workflow/actions:

```bash
aiflow run plan.json
```

Default behavior:

- stream workflow progress until `COMPLETED` or `FAILED`
- then print workflow summary automatically

Sample output:

```text
Running workflow
workflow_id: 2032...

✓ search_code
✓ analyze_module
→ generate_explanation

Workflow 2032 completed

Workflow Summary
...
Context Quality
- retrievalCount: 5
- noise: dependency directories detected
```

Optional flags:

- `--no-follow` (submit only, do not stream progress)
- `--no-summary` (do not print summary after run)

After submission, CLI writes local run metadata to:

- `.aiflow/last-run.json`

### 4.4 aiflow status

Query workflow status from runtime:

```bash
aiflow status --workflow-id 2032
```

Or use last submitted run:

```bash
aiflow status
```

Notes:

- If no workflow id is provided, CLI uses local `.aiflow/last-run.json` when available, otherwise it asks runtime for the latest workflow via `GET /workflows`.
- CLI reads workflow state from `GET /workflow/{workflowId}` and `GET /workflow/{workflowId}/actions`.
- Status icons map to runtime observability state: `✓` completed, `→` running, `·` pending, `✗` failed.

### 4.5 aiflow interactive

Start an interactive ASCII console:

```bash
aiflow interactive
```

Main menu:

- new issue prompt -> plan preview -> run confirmation
- recent workflow list
- workflow status view
- workflow summary view
- action detail view
- run plan file
- settings editor (`runtime_url`, API keys)

Notes:

- Interactive mode uses the same runtime APIs and local `.aiflow` files as non-interactive commands.
- Running a workflow from interactive mode streams status updates until `COMPLETED` or `FAILED`.

### 4.6 aiflow summary

Show an aggregated summary for one workflow:

```bash
aiflow summary --workflow-id 2032
```

Or use latest workflow resolution (same behavior as `aiflow status`):

```bash
aiflow summary
```

Use `--json` for raw summary payload:

```bash
aiflow summary --workflow-id 2032 --json
```

Rendered summary includes `Context Quality` so you can quickly spot retrieval noise (for example, `.venv`/`site-packages` hits).

## 5. End-to-end Example

Start runtime (example local mode):

```bash
docker compose up -d redis
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

In your project directory:

```bash
aiflow init
aiflow issue "Explain authentication module" --save plan.json
aiflow plan plan.json
aiflow run plan.json
aiflow status
aiflow summary
aiflow interactive
```

## 6. Script Migration

Legacy demo scripts now forward to CLI commands:

- `scripts/demo-issue.sh` -> `aiflow issue`
- `scripts/demo-plan-view.sh` -> `aiflow plan`
- `scripts/demo-run.sh` -> `aiflow run`

They remain for compatibility but CLI is the primary developer interface.