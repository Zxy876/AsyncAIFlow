# Planner Architecture

## 1. Goal

Planner layer translates a natural language issue into an AsyncAIFlow action plan.

Scope in this milestone:

- preview plan only
- user confirms before execution
- no scheduler-core changes

## 2. Layering

```text
User Issue
   -> Planner API (/planner/plan)
   -> Plan Preview
   -> User Confirms
   -> Workflow + Actions Creation
   -> Scheduler Runtime Execution
```

Planner and execution are separated by design:

- planner creates plan candidates
- scheduler executes confirmed actions

## 3. Planner Capability and Worker

New capability:

- `plan_workflow`

New worker:

- `planner-worker`

Planner worker currently supports action type:

- `plan_workflow`

Its responsibility is to return a plan payload only.

## 4. Planner API

Endpoint:

- `POST /planner/plan`

Request schema:

```json
{
  "issue": "Explain authentication module",
  "repo_context": "optional",
  "file": "optional"
}
```

Response schema:

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

`depends_on` uses preview-step indexes.

## 5. Minimal Plan Heuristics

Current prototype uses deterministic intent routing:

- explain/understand intent:
  - `search_code`
  - `analyze_module`
  - `generate_explanation`
- review intent:
  - `search_code`
  - `review_code`
- default (bug/fix/general dev):
  - `search_code`
  - `design_solution`
  - `review_code`

This keeps planner behavior transparent during internal dogfooding.

## 6. Start Planner Worker

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.planner.PlannerWorkerApplication \
  -Dspring-boot.run.profiles=planner-worker
```

Config file:

- `src/main/resources/application-planner-worker.yml`

## 7. Architectural Boundary

Planner does not:

- claim actions from runtime queues on behalf of users
- create workflows automatically during preview
- bypass capability dispatch or lease rules

Planner only proposes action graphs.

Scheduler remains policy owner for execution lifecycle.
