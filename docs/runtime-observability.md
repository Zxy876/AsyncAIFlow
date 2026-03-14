# Runtime Observability APIs

AsyncAIFlow now exposes stable read-only runtime APIs for workflow and action execution state.

These endpoints are intended for:

- CLI status output
- runtime debugging tools
- workflow execution dashboards

Internal scheduler and worker state remains unchanged. These APIs provide a normalized read model on top of the runtime database state.

## Status Model

Action status is normalized into a stable external contract:

- `PENDING`: action exists but is not currently executing
- `RUNNING`: action is actively assigned and executing
- `COMPLETED`: action finished successfully
- `FAILED`: action exhausted or terminally failed

Workflow status is normalized into:

- `RUNNING`
- `COMPLETED`
- `FAILED`

## Endpoints

### 1. GET /workflows

Returns recent workflows so CLI and tooling can discover the latest execution without already knowing a workflow id.

Example:

```json
{
  "success": true,
  "message": "recent workflows",
  "data": [
    {
      "workflowId": 12345,
      "status": "RUNNING",
      "createdAt": "2026-03-14T12:00:00",
      "issue": "Explain Drift story engine"
    }
  ]
}
```

### 2. GET /workflow/{workflowId}

Returns workflow execution state with embedded action summaries.

Example:

```json
{
  "success": true,
  "message": "workflow execution state",
  "data": {
    "workflowId": 12345,
    "status": "RUNNING",
    "createdAt": "2026-03-14T12:00:00",
    "actions": [
      {
        "actionId": 2001,
        "type": "search_code",
        "status": "COMPLETED",
        "workerId": "worker-search-1",
        "createdAt": "2026-03-14T12:00:02",
        "finishedAt": "2026-03-14T12:00:04"
      },
      {
        "actionId": 2002,
        "type": "generate_explanation",
        "status": "RUNNING",
        "workerId": "worker-gpt-1",
        "createdAt": "2026-03-14T12:00:05",
        "finishedAt": null
      }
    ]
  }
}
```

### 3. GET /workflow/{workflowId}/actions

Returns workflow action execution summaries only.

Example:

```json
{
  "success": true,
  "message": "workflow action execution state",
  "data": [
    {
      "actionId": 2001,
      "type": "search_code",
      "status": "COMPLETED",
      "workerId": "worker-search-1",
      "createdAt": "2026-03-14T12:00:02",
      "finishedAt": "2026-03-14T12:00:04"
    },
    {
      "actionId": 2002,
      "type": "generate_explanation",
      "status": "RUNNING",
      "workerId": "worker-gpt-1",
      "createdAt": "2026-03-14T12:00:05",
      "finishedAt": null
    }
  ]
}
```

### 4. GET /action/{actionId}

Returns action execution detail with worker ownership, timing, latest structured result, and collected logs.

Example:

```json
{
  "success": true,
  "message": "action execution state",
  "data": {
    "actionId": 2001,
    "workflowId": 12345,
    "type": "search_code",
    "status": "COMPLETED",
    "workerId": "worker-search-1",
    "startedAt": "2026-03-14T12:00:02",
    "finishedAt": "2026-03-14T12:00:04",
    "payload": {
      "query": "auth service"
    },
    "result": {
      "summary": "Found AuthService and JwtTokenProvider"
    },
    "error": null,
    "logs": [
      {
        "workerId": "worker-search-1",
        "status": "SUCCEEDED",
        "createdAt": "2026-03-14T12:00:04",
        "result": {
          "summary": "Found AuthService and JwtTokenProvider"
        }
      }
    ]
  }
}
```

## CLI Usage

`aiflow status` uses these runtime observability endpoints.

Examples:

```bash
aiflow status --workflow-id 12345
```

```bash
aiflow status
```

When no explicit workflow id is provided, CLI first checks local `.aiflow/last-run.json` and then falls back to `GET /workflows`.

Example terminal output:

```text
Workflow 12345

Progress 2/3

✓ search_code
✓ analyze_module
→ generate_explanation
```

## Notes

- These APIs are read-only. They do not enqueue, poll, retry, or mutate execution state.
- Action payload and result are returned as parsed JSON when stored content is valid JSON.
- If stored payload or result content is not valid JSON, the raw string is returned instead.
- `issue` in `GET /workflows` is resolved from workflow description when present, otherwise workflow name.