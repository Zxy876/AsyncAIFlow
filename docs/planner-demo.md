# Planner Demo

This guide shows the first product experience in AsyncAIFlow:

natural language issue -> plan preview

Scope in this demo:

- preview only
- no workflow/action execution
- no scheduler core changes

## 1. Start scheduler

Recommended for demo (no MySQL required):

```bash
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

Local profile still requires Redis:

```bash
docker compose up -d redis
```

Default profile (requires MySQL + Redis first):

```bash
docker compose up -d
```

```bash
mvn spring-boot:run
```

Important:

- Scheduler and planner worker are both long-running processes.
- Start them in separate terminals.

## 2. Start planner worker

In another terminal:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.planner.PlannerWorkerApplication \
  -Dspring-boot.run.profiles=planner-worker
```

## 3. Run demo script

From project root:

```bash
bash scripts/demo-planner.sh
```

Readable plan view:

```bash
bash scripts/demo-planner.sh --text "Explain authentication module"
```

Product-style issue entrypoint:

```bash
bash scripts/demo-issue.sh "Explain authentication module"
```

Save plan JSON for later review:

```bash
bash scripts/demo-issue.sh --save plan.json "Explain authentication module"
```

With custom issue:

```bash
bash scripts/demo-planner.sh "Explain authentication module"
```

With issue and repo context:

```bash
bash scripts/demo-planner.sh "Review auth service error handling" "auth package"
```

With issue, repo context, and file:

```bash
bash scripts/demo-planner.sh "Fix login retry bug" "web login flow" "src/main/java/com/example/auth/LoginService.java"
```

Optional base URL override:

```bash
ASYNCAIFLOW_BASE_URL=http://localhost:8080 bash scripts/demo-planner.sh "Explain authentication module"
```

## 4. Expected response structure

Response shape from POST /planner/plan:

```json
{
  "plan": [
    {
      "type": "search_code",
      "payload": {
        "schemaVersion": "v1",
        "query": "Explain authentication module"
      },
      "depends_on": []
    }
  ]
}
```

Each plan step includes:

- type: action type proposal
- payload: action payload preview
- depends_on: upstream step indexes

## 5. Example outputs

### 5.1 Explain module example

Input:

```bash
bash scripts/demo-planner.sh "Explain authentication module"
```

Typical output:

```json
{
  "plan": [
    {
      "type": "search_code",
      "payload": {
        "schemaVersion": "v1",
        "query": "Explain authentication module"
      },
      "depends_on": []
    },
    {
      "type": "analyze_module",
      "payload": {
        "schemaVersion": "v1",
        "issue": "Explain authentication module"
      },
      "depends_on": [0]
    },
    {
      "type": "generate_explanation",
      "payload": {
        "schemaVersion": "v1",
        "issue": "Explain authentication module"
      },
      "depends_on": [1]
    }
  ]
}
```

### 5.2 Review code example

Input:

```bash
bash scripts/demo-planner.sh "Review authentication error handling"
```

Typical output:

```json
{
  "plan": [
    {
      "type": "search_code",
      "payload": {
        "schemaVersion": "v1",
        "query": "Review authentication error handling"
      },
      "depends_on": []
    },
    {
      "type": "review_code",
      "payload": {
        "schemaVersion": "v1",
        "focus": "issue-driven review",
        "knownIssues": [
          "Review authentication error handling"
        ]
      },
      "depends_on": [0]
    }
  ]
}
```

### 5.3 Fix bug example

Input:

```bash
bash scripts/demo-planner.sh "Fix login retry bug"
```

Typical output:

```json
{
  "plan": [
    {
      "type": "search_code",
      "payload": {
        "schemaVersion": "v1",
        "query": "Fix login retry bug"
      },
      "depends_on": []
    },
    {
      "type": "design_solution",
      "payload": {
        "schemaVersion": "v1",
        "issue": "Fix login retry bug",
        "constraints": [
          "keep plan minimal and execution-oriented"
        ]
      },
      "depends_on": [0]
    },
    {
      "type": "review_code",
      "payload": {
        "schemaVersion": "v1",
        "focus": "issue-driven review",
        "knownIssues": [
          "Fix login retry bug"
        ]
      },
      "depends_on": [1]
    }
  ]
}
```

## 6. Notes

- Planner demo is preview-only and does not create workflows.
- This is the intended milestone boundary before confirm-and-run.
- If planner response changes over time, rely on the response structure in section 4 as the stable contract.
- If you get curl exit code 7, scheduler is not reachable yet. Start scheduler with local profile or wait until startup is complete.
- Use `scripts/demo-issue.sh` when you want a readable developer-facing plan instead of raw JSON.
- Use `scripts/demo-plan-view.sh` and `scripts/demo-run.sh` for the CLI human-in-the-loop flow.
