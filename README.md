# AsyncAIFlow v0.1

AsyncAIFlow is an action-oriented asynchronous workflow engine for coordinating multiple AI workers.

It does not schedule agents directly. It schedules action instances and dispatches them to workers that declare matching capabilities.

## Architecture

```text
Human Workflow
      ->
Action Graph
      ->
AsyncAIFlow Core
      ->
Worker Pool
      ->
MCP Tools
```

Runtime layout in v0.1:

```text
Developer -> Flow API -> Flow Server -> Redis Queue -> Worker Pool
                              |
                              -> MySQL metadata and execution log
```

## What v0.1 covers

- Create workflows.
- Create actions.
- Register workers with capabilities.
- Poll actions over HTTP.
- Submit action results.
- Dispatch actions by capability.
- Trigger downstream actions after upstream success.

This version intentionally keeps the scope small. It is a runnable skeleton for the first end-to-end loop, not a full production scheduler.

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
- action: action instances and current assignment state.
- worker: worker registry and capability declaration.
- action_log: execution result history.
- action_dependency: lightweight DAG edges used to trigger next actions.

Redis keys used in v0.1:

- action:queue:{actionType}
- action:lock:{actionId}
- worker:heartbeat:{workerId}

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

3. Create actions.

```bash
curl -X POST http://localhost:8080/action/create \
  -H 'Content-Type: application/json' \
  -d '{"workflowId":123,"type":"design_solution","payload":"{\"issue\":\"build skeleton\"}"}'
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

5. Submit result.

```bash
curl -X POST http://localhost:8080/action/result \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"gpt-worker-1","actionId":456,"status":"SUCCEEDED","result":"design completed"}'
```

If the completed action unlocks a downstream dependency chain, AsyncAIFlow will move the next action from BLOCKED to QUEUED and place it into the Redis action queue.

## Roadmap

Detailed roadmap and architecture notes are in [docs/asyncaiflow-roadmap.md](docs/asyncaiflow-roadmap.md).