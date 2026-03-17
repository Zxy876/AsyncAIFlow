# AsyncAIFlow

AsyncAIFlow is an action-oriented asynchronous workflow engine for coordinating multiple AI worker actions.

It does not schedule agents directly. It schedules action instances and dispatches them to workers that declare matching capabilities.

Current baseline: v0.2 runtime + planner + worker + CLI dogfooding build.

Current stage: internal dogfooding for a small group, with focus on first-run usability, reliability, and observability.

Current milestone: natural language planning, runtime observability, repository worker closed loop, and interactive terminal workflow UX.

## Architecture

```text
Developer
   |
   v
Flow API
   |
   v
Flow Server
   |
   +--> Redis
   |      |- action queue
   |      |- action lock
   |      |- worker heartbeat
   |
   +--> MySQL
   |      |- workflow metadata
   |      |- action instances
   |      |- execution log
   |
   +--> Worker Pool
      |- GPT worker
      |- Repository worker
      |- Planner worker
      |- Test worker
```

## Quick Start

Fast local path (H2 + Redis):

```bash
git clone https://github.com/Zxy876/AsyncAIFlow.git
cd AsyncAIFlow

docker compose up -d redis

# start runtime
mvn spring-boot:run -Dspring-boot.run.profiles=local

# start workers in separate terminals
mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication -Dspring-boot.run.profiles=gpt-worker
mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.repository.RepositoryWorkerApplication -Dspring-boot.run.profiles=repository-worker

# run CLI
chmod +x aiflow
./aiflow init
./aiflow interactive
```

Full-stack path (MySQL + Redis) is documented later in this README and in docs/quickstart-local.md.

## What v0.2 covers

- Create workflows.
- Create actions.
- Register workers with capabilities.
- Worker heartbeat endpoint and stale worker detection.
- Poll actions over HTTP.
- Submit action results.
- Dispatch actions by capability.
- Resolve actionType -> requiredCapability with default same-name mapping and optional explicit mapping.
- Trigger downstream actions after upstream success.
- Action lease assignment and expiration reclaim.
- Retry with max retry count and backoff.
- Timeout reclaim loop and retry requeue loop.
- Idempotent duplicate result handling.

This version is still intentionally focused. It upgrades the runnable skeleton into a more reliable scheduler core without expanding into AI integration yet.

## Tech stack

- Spring Boot 3.3
- MyBatis Plus
- Redis
- MySQL
- Maven
- Java 21

## Project structure

```text
src/main/java/com/asyncaiflow
  |- controller        REST APIs
  |- domain            entities and enums
  |- mapper            MyBatis Plus mappers
  |- service           workflow, action, worker services
  |- support           JSON and exception helpers
  |- web               API response and DTOs

src/main/resources
  |- application.yml
  |- schema.sql

docs
  |- asyncaiflow-roadmap.md
```

## Data model

Core tables:

- workflow: workflow metadata and lifecycle state.
- action: action instances, lease metadata, retry policy and runtime state.
- worker: worker registry, capability declaration and liveness timestamp.
- action_log: execution result history.
- action_dependency: lightweight DAG edges used to trigger next actions.

Redis keys used in v0.1:

- action:queue:{actionType}
- action:lock:{actionId}
- worker:heartbeat:{workerId}

Action reliability fields:

- retry_count
- max_retry_count
- backoff_seconds
- execution_timeout_seconds
- lease_expire_at
- next_run_at
- claim_time
- first_renew_time
- last_renew_time
- submit_time
- reclaim_time
- lease_renew_success_count
- lease_renew_failure_count
- last_lease_renew_at
- execution_started_at
- last_execution_duration_ms
- last_reclaim_reason

## Local run

Option A: full stack with MySQL and Redis.

1. Start MySQL and Redis.

```bash
docker compose up -d
```

2. Start the server.

```bash
mvn spring-boot:run
```

The app expects:

- MySQL at localhost:3306
- Redis at localhost:6379
- database name asyncaiflow
- MySQL username root
- MySQL password root

Schema initialization is handled by [src/main/resources/schema.sql](src/main/resources/schema.sql) on startup.

Option B: fast local bootstrap with H2 and Redis.

If you only want to bring up the server quickly, use the local profile. It keeps Redis as the queue backend but replaces MySQL with in-memory H2.

```bash
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

This profile uses [src/main/resources/application-local.yml](src/main/resources/application-local.yml) and [src/main/resources/schema-h2.sql](src/main/resources/schema-h2.sql).

## First AI workflow demo

AsyncAIFlow can now translate a natural language issue into an action plan preview.

This milestone demonstrates:

- natural language issue input
- planner-generated action plan preview
- no execution side effects (preview only)

Recommended startup for demo (terminal 1):

```bash
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

Planner worker (terminal 2, optional for preview endpoint but useful for full architecture demo):

```bash
mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.planner.PlannerWorkerApplication -Dspring-boot.run.profiles=planner-worker
```

Run the demo script:

```bash
bash scripts/demo-planner.sh
```

Recommended product-style entrypoint:

```bash
bash scripts/demo-issue.sh "Explain authentication module"
```

Save a plan for human review:

```bash
bash scripts/demo-issue.sh --save plan.json "Find bug in resource mapping"
```

Readable plan view:

```bash
bash scripts/demo-planner.sh --text "Explain authentication module"
```

Examples:

```bash
bash scripts/demo-planner.sh "Explain authentication module"
bash scripts/demo-planner.sh "Review auth service error handling" "auth package"
bash scripts/demo-planner.sh "Fix login retry bug" "web login flow" "src/main/java/com/example/auth/LoginService.java"
```

Detailed walkthrough and sample outputs are in [docs/planner-demo.md](docs/planner-demo.md).

Fast 10-minute experience guide is in [docs/first-ai-dev-demo.md](docs/first-ai-dev-demo.md).

Human-in-the-loop workflow is in [docs/human-in-the-loop.md](docs/human-in-the-loop.md).

First real AI output (`generate_explanation`) demo:

```bash
bash scripts/demo-generate-explanation.sh
```

Detailed guide is in [docs/generate-explanation-worker.md](docs/generate-explanation-worker.md).

## AsyncAIFlow CLI

AsyncAIFlow now provides a developer CLI entrypoint:

- `aiflow init`
- `aiflow issue`
- `aiflow plan`
- `aiflow run`
- `aiflow status`
- `aiflow interactive`

CLI quick start:

```bash
chmod +x aiflow
./aiflow init
./aiflow issue "Trace rule-event pipeline" --save plan.json
./aiflow run plan.json
./aiflow status
./aiflow interactive
```

Full CLI guide is in [docs/cli.md](docs/cli.md).

Runtime observability API guide is in [docs/runtime-observability.md](docs/runtime-observability.md).

Worker Milestone 1 repository worker:

```bash
mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.repository.RepositoryWorkerApplication -Dspring-boot.run.profiles=repository-worker
```

This worker now registers `search_code`, `read_file`, `search_semantic`, and `build_context_pack`.

Planner-style explanation and diagnosis flows now use semantic retrieval first:

- `search_semantic`
- `build_context_pack`
- `generate_explanation` or `design_solution`

Zread MCP can be enabled via `application-repository-worker.yml` / environment variables:

- `ASYNCAIFLOW_ZREAD_MCP_ENDPOINT`
- `ASYNCAIFLOW_ZREAD_AUTHORIZATION`

The repository worker now defaults to `https://open.bigmodel.cn/api/mcp/zread/mcp` and will reuse `OPENAI_API_KEY` when `ASYNCAIFLOW_ZREAD_AUTHORIZATION` is not set.

When Zread MCP is disabled or unavailable, `search_semantic` gracefully falls back to local semantic-like scoring over workspace files.

## Workflow Summary Demo

`aiflow run` now follows execution in real time and prints a structured summary automatically when the workflow finishes. No separate `aiflow summary` call needed.

```bash
./aiflow run plan.json
```

```text
[+] Workflow submitted: 2033325050694475777

 Workflow 2033325050694475777 · RUNNING
 [00:03] ✓ search_semantic         COMPLETED
 [00:08] ✓ build_context_pack      COMPLETED
 [00:31] ✓ generate_explanation    COMPLETED
 Workflow COMPLETED in 31s

╔══════════════════════════════════════════════════════════════════════════════╗
║  WORKFLOW SUMMARY  ·  #2033325050694475777  ·  COMPLETED  ·  31s           ║
╚══════════════════════════════════════════════════════════════════════════════╝

Issue    Fix authentication module race condition

Plan
  1. search_semantic   2. build_context_pack   3. generate_explanation

Actions (3)
  ✓ search_semantic          [3s]   Found 6 relevant files across auth package
  ✓ build_context_pack       [5s]   Compiled context from 6 sources
  ✓ generate_explanation     [23s]  Race condition identified in SessionManager

Context Quality
  retrievals : 6       sources : 6
  noise      : none

Key Findings
  • Race condition in SessionManager.validateToken() — concurrent token refresh
    can bypass expiry check
  • Affected call site: src/auth/SessionManager.java:142

Warnings
  • Token refresh and validation share a non-atomic check-then-act block

Suggestions
  • Add synchronized block or use AtomicReference for token state
```

To skip the summary after run:

```bash
./aiflow run plan.json --no-summary
```

To submit and return immediately (no progress streaming):

```bash
./aiflow run plan.json --no-follow
```

To view the summary for any workflow at any time:

```bash
./aiflow summary --workflow-id <id>
```

Full summary API design is in [docs/runtime-observability.md](docs/runtime-observability.md).

## Minimal API flow

1. Create a workflow.

```bash
curl -X POST http://localhost:8080/workflow/create \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo-flow","description":"first async ai flow"}'
```

2. Register a worker.

```bash
curl -X POST http://localhost:8080/worker/register \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"gpt-worker-1","capabilities":["design_solution","generate_code"]}'
```

2.5. Worker heartbeat.

```bash
curl -X POST http://localhost:8080/worker/heartbeat \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"gpt-worker-1"}'
```

3. Create actions.

```bash
curl -X POST http://localhost:8080/action/create \
  -H 'Content-Type: application/json' \
  -d '{"workflowId":123,"type":"design_solution","payload":"{\"issue\":\"build skeleton\"}"}'
```

Action creation now supports optional reliability policy fields:

```json
{
  "maxRetryCount": 3,
  "backoffSeconds": 5,
  "executionTimeoutSeconds": 300
}
```

```bash
curl -X POST http://localhost:8080/action/create \
  -H 'Content-Type: application/json' \
  -d '{"workflowId":123,"type":"generate_code","payload":"{}","upstreamActionIds":[456]}'
```

4. Poll work.

```bash
curl 'http://localhost:8080/action/poll?workerId=gpt-worker-1'
```

4.5. Renew lease during long-running execution.

```bash
curl -X POST http://localhost:8080/action/456/renew-lease \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"gpt-worker-1"}'
```

Worker SDK now starts a periodic lease renew loop while action execution is in progress.

5. Submit result.

```bash
curl -X POST http://localhost:8080/action/result \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"gpt-worker-1","actionId":456,"status":"SUCCEEDED","result":"design completed"}'
```

If the completed action unlocks a downstream dependency chain, AsyncAIFlow will move the next action from BLOCKED to QUEUED and place it into the Redis action queue.

When an action fails or times out, AsyncAIFlow will:

- increment retry_count
- place action into RETRY_WAIT with next_run_at according to backoff
- requeue when next_run_at is due
- move to terminal FAILED or DEAD_LETTER once retry budget is exhausted

## Roadmap

Internal usage docs (first-run and operations):

- [docs/quickstart-local.md](docs/quickstart-local.md)
- [docs/first-workflow.md](docs/first-workflow.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)

Detailed roadmap and architecture notes are in [docs/asyncaiflow-roadmap.md](docs/asyncaiflow-roadmap.md).

Architecture baseline is in [docs/architecture.md](docs/architecture.md).

Action schema baseline is in [docs/action-schema.md](docs/action-schema.md).

Runtime schema validation design is in [docs/schema-validation.md](docs/schema-validation.md).

Scheduler reliability design notes are in [docs/scheduler-reliability-roadmap.md](docs/scheduler-reliability-roadmap.md).

Worker capability model formalization is in [docs/worker-capability-model.md](docs/worker-capability-model.md).

Worker SDK and reference worker notes are in [docs/worker-sdk.md](docs/worker-sdk.md).

GPT worker integration notes are in [docs/gpt-worker.md](docs/gpt-worker.md).

Generate explanation worker milestone guide is in [docs/generate-explanation-worker.md](docs/generate-explanation-worker.md).

Planner layer architecture notes are in [docs/planner-architecture.md](docs/planner-architecture.md).