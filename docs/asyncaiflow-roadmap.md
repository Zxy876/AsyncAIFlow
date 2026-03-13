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

Dispatch rule in v0.1:

- One Redis queue per action type.
- Worker registers capabilities in MySQL.
- Worker poll loads its capabilities.
- Flow Server scans capability-specific queues in order.
- First claimable action is assigned to the worker.

This model is deliberately simple and works well for early agent orchestration because:

- action types are explicit;
- worker eligibility is transparent;
- routing is easy to debug;
- later priority rules can be added without rewriting the whole model.

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

Dispatch improvements:

- better capability matching
- queue fairness
- retry queue
- heartbeat timeout detection
- worker lease recovery

### Phase 3

DAG orchestration:

- richer dependency conditions
- retry policy
- action timeout
- workflow-level completion hooks

### Phase 4

Context builder:

- repo graph extraction
- diff context builder
- issue context builder
- test context builder

### Phase 5

Agent integration:

- GPT worker
- Copilot worker
- Zread worker
- test worker
- MCP tool-backed execution contracts

## 10. v0.1 success criteria

v0.1 is successful if it can do these five things reliably:

1. Create workflow.
2. Create action.
3. Poll action from worker.
4. Submit execution result.
5. Trigger next action when dependencies are satisfied.

That is the correct minimum for AsyncAIFlow because it proves the core abstraction: the system schedules actions, and workers are interchangeable executors behind that contract.