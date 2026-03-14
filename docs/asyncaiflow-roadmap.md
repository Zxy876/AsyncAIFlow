# AsyncAIFlow Roadmap

## 1. System definition

AsyncAIFlow is an AI-agent-oriented asynchronous workflow engine.

The scheduling target is not the agent itself. The scheduling target is the action.

That distinction matters because it makes the runtime composable:

- Human workflow defines intent.
- Action graph defines execution structure.
- AsyncAIFlow schedules action instances.
- Workers execute actions.
- MCP tools are invoked behind workers.

## 2. System architecture

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
   |      |- worker registry
   |      |- execution log
   |
   +--> Worker Pool
          |- GPT worker
          |- Copilot worker
          |- Zread worker
          |- Test worker
```

### Responsibilities

- Flow API receives workflow, action, and worker requests.
- Flow Server owns action lifecycle, matching, and DAG progression.
- Redis handles short-lived runtime coordination.
- MySQL stores durable metadata and execution history.
- Workers poll tasks by HTTP and execute them with their own toolchains.

## 3. Core concepts

### Action

Action is the smallest executable unit.

Examples:

- search_code
- trace_dependency
- design_solution
- generate_code
- review_code
- run_tests
- fix_bug
- create_pr

### Worker

Worker is the execution endpoint for actions.

In v0.1 a worker follows a simple loop:

```text
while true:
  GET /action/poll?workerId=...
  execute action
  POST /action/result
```

### Capability

Capability is the dispatch contract between action type and worker.

Example:

```json
{
  "workerId": "gpt-worker-1",
  "capabilities": [
    "design_solution",
    "review_code"
  ]
}
```

If a worker declares `design_solution`, it is eligible to receive actions of type `design_solution`.

### Flow

Flow is a DAG of actions.

Example:

```text
design_solution
      |
      v
generate_code
      |
      v
run_tests
      |
      v
review_code
```

v0.1 uses an `action_dependency` table to represent DAG edges explicitly.

### Context Pack

Context pack is the execution context assembled before a worker runs an action.

Possible sources:

- issue data
- related files
- repository graph
- diff
- test output

v0.1 keeps `payload` open-ended so a future context builder can inject richer execution context without changing the dispatch protocol.

## 4. Action workflow model

Current v0.1 model:

1. A workflow is created.
2. Actions are created under the workflow.
3. Actions without upstream dependencies enter `QUEUED` immediately.
4. Actions with upstream dependencies enter `BLOCKED`.
5. A worker polls and claims a queued action if capability matches.
6. The action enters `RUNNING`.
7. The worker submits `SUCCEEDED` or `FAILED`.
8. If succeeded, downstream actions are evaluated.
9. When all upstream actions of a downstream node succeed, that node enters `QUEUED`.

This is the minimal closed loop needed to prove that AsyncAIFlow can coordinate action DAG execution rather than just storing task rows.

## 5. Worker capability model

Dispatch baseline in v0.2:

- actionType resolves to requiredCapability (default same-name)
- optional mapping override via `asyncaiflow.dispatch.capability-mapping`
- one Redis queue per required capability
- worker poll scans queues by worker capability set
- claim re-checks required capability before RUNNING assignment

This minimal formalization keeps dispatch behavior explicit, testable, and backward compatible with same-name action types.

Detailed spec is in [docs/worker-capability-model.md](docs/worker-capability-model.md).

## 6. MySQL schema in v0.1

Tables implemented now:

- workflow
- action
- worker
- action_log
- action_dependency

The first four match the agreed minimal domain. `action_dependency` is added so downstream triggering is concrete rather than implicit.

## 7. Redis model in v0.1

Keys:

- `action:queue:{type}` for capability-aligned queues
- `action:lock:{actionId}` for in-flight claim lock
- `worker:heartbeat:{workerId}` for liveness hints

This is enough to support queueing, claiming, and basic runtime coordination.

## 8. Future MCP and agent integration

AsyncAIFlow should eventually treat workers as orchestration frontends for deeper execution stacks.

Target layering:

```text
Action
  -> Worker
      -> Agent runtime
          -> MCP tool calls
```

Example:

- `search_code` action is dispatched to a search-capable worker.
- That worker may call repository analysis tools through MCP.
- `generate_code` may go to GPT or Copilot workers.
- `run_tests` may go to a test worker bound to CI or local execution tools.

This keeps AsyncAIFlow focused on action scheduling, not tool invocation details.

## 9. Roadmap

### Phase 1

Foundation:

- Spring Boot project skeleton
- MyBatis Plus persistence layer
- MySQL schema
- Redis queue adapter
- workflow, action, worker APIs

### Phase 2

Runtime reliability:

- better capability matching
- queue fairness
- retry queue
- heartbeat timeout detection
- worker lease recovery
- dead-letter handling
- lease renewal observability

### Phase 3

Planner, CLI, and observability:

- planner preview API
- `aiflow issue`, `aiflow plan`, `aiflow run`, `aiflow status`
- `GET /workflows`
- `GET /workflow/{id}`
- `GET /workflow/{id}/actions`
- `GET /action/{id}`

This phase makes the system observable and usable from terminal, even before richer worker capabilities arrive.

### Phase 4

Worker Milestone 1: minimum closed loop:

- `generate_explanation` as existing LLM worker
- `search_code`
- `read_file`

Target flow:

```text
issue
  -> search_code
  -> read_file
  -> generate_explanation
```

This is the first point where AsyncAIFlow becomes a real explain-and-debug loop instead of a planner demo.

### Phase 5

Interactive ASCII CLI:

- `aiflow interactive`
- new issue prompt
- plan preview
- run confirmation
- recent workflow list
- workflow status view
- action detail view

Status: implemented.

The ASCII UI should come after Worker Milestone 1 so the terminal experience wraps a real execution loop rather than an empty shell.

### Phase 6

Worker Milestone 2: code change loop:

- `write_file`
- `run_tests`

Target flow:

```text
issue
  -> search_code
  -> read_file
  -> generate_explanation
  -> write_file
  -> run_tests
```

This is the first milestone where AsyncAIFlow can move from explanation into code modification and verification.

### Phase 7

Extended worker system:

- richer dependency conditions
- retry policy
- action timeout
- workflow-level completion hooks

- repo graph extraction
- diff context builder
- issue context builder
- test context builder

- GPT worker
- Copilot worker
- Zread worker
- test worker
- MCP tool-backed execution contracts

- future workers such as `git_diff`, `review_code`, `generate_patch`, `trace_execution`

## 10. v0.1 success criteria

v0.1 is successful if it can do these five things reliably:

1. Create workflow.
2. Create action.
3. Poll action from worker.
4. Submit execution result.
5. Trigger next action when dependencies are satisfied.

That is the correct minimum for AsyncAIFlow because it proves the core abstraction: the system schedules actions, and workers are interchangeable executors behind that contract.

## 11. Current product status

The system is no longer just a runtime skeleton. It now has six concrete layers:

- Planner: issue -> plan preview
- Runtime: workflow and action DAG execution
- Worker: `generate_explanation`
- Repository worker: `search_code`, `read_file`, and `analyze_module` compatibility via capability mapping
- CLI: `aiflow issue`, `aiflow plan`, `aiflow run`, `aiflow status`
- Interactive CLI: `aiflow interactive`
- Observability: workflow list, workflow status, action detail

Reliability and execution behavior already exceed the original v0.1 baseline:

- lease assignment, timeout reclaim, retry/backoff, dead-letter
- worker heartbeat and stale detection
- lease renewal during long-running execution
- worker-side runtime schema validation with off/warn/strict modes
- integration-style behavior contract tests for schema validation and lease flow

Observability is now available through stable read-only APIs:

- `GET /workflows`
- `GET /workflow/{id}`
- `GET /workflow/{id}/actions`
- `GET /action/{id}`

Worker Milestone 1 is now implemented:

- `search_code`
- `read_file`
- planner-compatible `analyze_module -> read_file` capability mapping
- execution contract tests proving `search_code -> analyze_module -> generate_explanation` can complete as a DAG

Lease renewal observability baseline is now tracked per action:

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

Near-term priorities:

1. Keep runtime scheduling, planner logic, and worker execution model stable while worker capability surface expands.
2. Add `write_file` and `run_tests` as Worker Milestone 2.
3. Decide whether to add `list_files` before or alongside Worker Milestone 2.

Experience threshold:

The first real end-to-end product experience happens when these three conditions are true:

1. CLI is stable.
2. Observability APIs are stable.
3. Worker Milestone 1 is complete.

Those conditions are now satisfied for the explain/debug loop, and the ASCII UI has been added so the system is directly usable by a human operator from terminal.

Planner architecture reference:

- [docs/planner-architecture.md](docs/planner-architecture.md)