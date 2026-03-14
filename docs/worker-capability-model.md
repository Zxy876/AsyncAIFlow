# Worker Capability Model

## 1. Goal

Worker Capability Model defines who can execute what action type.

Current scope is intentionally minimal:

- explicit worker capability declaration
- explicit actionType -> requiredCapability mapping rule
- scheduler assignment constraint based on required capability
- contract tests for matching and contention behavior

## 2. Worker Declaration Format

Worker registration remains:

```json
{
  "workerId": "gpt-worker-1",
  "capabilities": [
    "design_solution",
    "review_code"
  ]
}
```

Rules:

- capabilities must be non-empty
- capabilities are normalized by trim + distinct
- scheduler treats capabilities as dispatch eligibility set

## 3. ActionType -> RequiredCapability Mapping

Default mapping policy is same-name:

- `design_solution` -> `design_solution`
- `review_code` -> `review_code`

Configurable mapping is supported via:

- `asyncaiflow.dispatch.capability-mapping`

Example:

```yaml
asyncaiflow:
  dispatch:
    capability-mapping:
      design_solution: solution_planner
      review_code: code_reviewer
```

Resolution behavior:

- if mapping exists and is non-blank, use mapped capability
- otherwise fallback to action type itself

## 4. Scheduler Assignment Constraint

Dispatch invariant:

- worker can claim action only if `worker.capabilities` contains resolved required capability of `action.type`

Current scheduler flow:

1. action is enqueued to queue key of required capability
2. poll scans worker capability queues
3. claim validates resolved required capability again before assignment

This double check prevents queue-key drift from violating capability boundary.

## 5. Contention Semantics

Multiple workers may share the same capability.

Current behavior:

- workers with same capability compete for same capability queue
- each action is lock-guarded and assigned to one worker at a time

No preference or fallback ordering is applied yet.

## 6. Future Extensions (Documented Only)

Not implemented in current phase:

- preferred worker ordering per action type
- fallback worker chains
- capability version negotiation
- advanced routing policies

## 7. Contract Test Coverage

Capability contract tests are in:

- `SchedulerReliabilityIntegrationTest`
  - capability match -> claim works
  - capability mismatch -> claim denied
  - same capability workers -> contention with distinct claims
- `ActionCapabilityResolverTest`
  - default same-name mapping
  - configured mapping override
