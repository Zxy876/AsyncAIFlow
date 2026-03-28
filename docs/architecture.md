# AsyncAIFlow Architecture

## 1. System Overview

AsyncAIFlow is an action-oriented orchestration engine for AI development workflows.

It schedules Action instances instead of scheduling agents directly.

High-level architecture:

```mermaid
graph TD
    Dev["👨‍💻 Developer / CLI"]
    API["Flow API (REST)\n/workflow /action /worker /planner"]
    Planner["Planner\nNL → Action Plan"]
    Scheduler["AsyncAIFlow Scheduler Core\nActionService · WorkflowService · WorkerService\nSchedulerMaintenanceService"]
    Redis["Redis\n─────────────\naction:queue:{type}\naction:lock:{actionId}\nworker:heartbeat:{workerId}"]
    MySQL["MySQL\n─────────────\nworkflow\naction\nworker\naction_dependency\naction_log"]
    WorkerPool["Worker Pool"]
    TestWorker["🔧 TestWorker\ntest_action"]
    GPTWorker["🤖 GPT Worker\ndesign_solution · review_code"]
    RepoWorker["📁 Repository Worker\nsearch_code · read_file\nsearch_semantic · build_context_pack\nload_code · analyze_module"]
    PlannerWorker["📋 Planner Worker\nplan_workflow"]
    GitWorker["🗂 Git Worker\ngit operations"]

    Dev -->|"HTTP / aiflow CLI"| API
    API --> Planner
    API --> Scheduler
    Scheduler -->|"enqueue · claim · lock · heartbeat"| Redis
    Scheduler -->|"read / write metadata & logs"| MySQL
    Scheduler -->|"HTTP poll / submit / renew-lease"| WorkerPool
    WorkerPool --- TestWorker
    WorkerPool --- GPTWorker
    WorkerPool --- RepoWorker
    WorkerPool --- PlannerWorker
    WorkerPool --- GitWorker
```

Current system status:

- Scheduler core is production-like for reliability baseline.
- Worker protocol and SDK are stable and reusable.
- Reference worker and first AI worker are both operational.

## 2. Scheduler Core

Scheduler Core owns workflow progression and reliability policy.

Core responsibilities:

- workflow and action lifecycle management
- DAG dependency resolution and downstream activation
- capability-based dispatch with explicit actionType -> requiredCapability resolution
- lease assignment and ownership
- lease renewal for long-running execution
- timeout reclaim
- retry and backoff
- dead-letter termination
- worker liveness maintenance

Core reliability mechanisms:

- lease: prevents concurrent ownership under normal conditions
- heartbeat: tracks worker liveness
- reclaim: recovers timed-out running actions
- retry_wait: delays and requeues retriable failures
- dead_letter: isolates exhausted failures

Design boundary:

- Scheduler decides "when and where to run".
- Worker decides "how to execute".

## 3. Action Model

Action is the smallest schedulable execution unit.

Action state machine:

```mermaid
stateDiagram-v2
    [*] --> BLOCKED : created with unresolved dependencies
    [*] --> QUEUED  : created with no dependencies

    BLOCKED    --> QUEUED      : upstream action succeeds (downstream activation)
    QUEUED     --> RUNNING     : worker polls and acquires lease
    RUNNING    --> SUCCEEDED   : worker submits success result
    RUNNING    --> RETRY_WAIT  : worker submits failure (retries available)\nor lease expires (retries available)
    RUNNING    --> DEAD_LETTER : lease expires (retries exhausted)
    RETRY_WAIT --> QUEUED      : next_run_at reached (enqueue due retries)
    RETRY_WAIT --> DEAD_LETTER : retry budget exhausted

    SUCCEEDED  --> [*]
    DEAD_LETTER --> [*]

    note right of RUNNING
        Lease renewed periodically
        by worker SDK (every 10s)
    end note
```

Typical action states:

- BLOCKED
- QUEUED
- RUNNING
- RETRY_WAIT
- SUCCEEDED
- FAILED
- DEAD_LETTER

Important action fields:

- type: dispatch key and capability contract
- payload: execution input (JSON string)
- workerId: current lease owner
- leaseExpireAt: execution lease deadline
- retryCount and maxRetryCount: retry budget
- backoffSeconds and nextRunAt: retry scheduling
- executionTimeoutSeconds: run timeout policy
- claimTime, firstRenewTime, lastRenewTime: lease timeline checkpoints
- submitTime and reclaimTime: terminal path timeline checkpoints
- leaseRenewSuccessCount and leaseRenewFailureCount: lease renewal counters
- lastLeaseRenewAt: timestamp of latest successful renewal
- executionStartedAt and lastExecutionDurationMs: execution timing observability
- lastReclaimReason: scheduler reclaim reason marker

Lifecycle summary:

1. Action is created.
2. If dependencies are ready, it becomes QUEUED; otherwise BLOCKED.
3. Worker poll assigns RUNNING with lease.
4. Worker submit transitions to SUCCEEDED or failure path.
5. Success may unblock downstream actions.
6. Failure/timeout may enter RETRY_WAIT or terminal state.

## 4. Worker Protocol

Worker protocol is HTTP-based and intentionally minimal.

Endpoints:

- POST /worker/register
- POST /worker/heartbeat
- GET /action/poll?workerId=...
- POST /action/{actionId}/renew-lease
- POST /action/result

Worker loop contract:

```mermaid
sequenceDiagram
    participant W as Worker
    participant S as Flow Server (Scheduler)
    participant R as Redis
    participant DB as MySQL

    W->>S: POST /worker/register (capabilities)
    S->>DB: insert WorkerEntity

    loop Every ~30s
        W->>S: POST /worker/heartbeat
        S->>R: SET worker:heartbeat:{workerId} TTL
    end

    loop Poll cycle
        W->>S: GET /action/poll?workerId=...
        S->>R: LPOP action:queue:{type} + SET action:lock:{actionId}
        S->>DB: UPDATE action SET status=RUNNING, worker_id=..., lease_expire_at=...
        S-->>W: ActionAssignmentResponse (actionId, type, payload)

        par Lease renewal (background thread)
            loop Every 10s while executing
                W->>S: POST /action/{actionId}/renew-lease
                S->>R: EXPIRE action:lock:{actionId} (extend TTL)
            end
        end

        W->>W: execute action (LLM call / code search / git op)

        alt Success
            W->>S: POST /action/result (status=SUCCEEDED, result=...)
            S->>DB: UPDATE action SET status=SUCCEEDED
            S->>R: DEL action:lock:{actionId}
            S->>DB: INSERT action_log
            S->>S: triggerDownstreamActions()
        else Failure
            W->>S: POST /action/result (status=FAILED, errorMessage=...)
            alt retries available
                S->>DB: UPDATE action SET status=RETRY_WAIT, next_run_at=...
            else retries exhausted
                S->>DB: UPDATE action SET status=DEAD_LETTER
            end
            S->>R: DEL action:lock:{actionId}
        end
    end
```

Protocol guarantees:

- scheduler remains the source of truth for orchestration state
- workers remain mostly stateless executors
- new worker types can be added without changing scheduler core

## 5. Worker Types

### TestWorker

Purpose:

- reference implementation for protocol and reliability testing

Capabilities:

- test_action

Behavior:

- random sleep and random success/failure
- payload overrides for deterministic smoke tests

### GPTWorker

Purpose:

- first AI execution worker

Capabilities:

- design_solution
- review_code

Behavior:

- builds prompts from action payload
- calls OpenAI-compatible chat completion API
- returns structured JSON result content
- supports mock fallback when no API key is provided

## 6. AI Worker Model

AI worker model in AsyncAIFlow:

```mermaid
flowchart LR
    Poll["Poll action\n(GET /action/poll)"]
    Context["Build prompt / context\n(payload + retrieval results)"]
    Model["Call model / toolchain\n(LLM · search · git)"]
    Submit["Submit result\n(POST /action/result)"]

    Poll --> Context --> Model --> Submit --> Poll
```

Separation of concerns:

- Scheduler Core: orchestration policy and reliability
- AI Worker: model invocation and task-specific reasoning

Current execution modes for GPTWorker:

- real mode: uses configured API key and endpoint
- mock mode: deterministic fallback for local integration tests

This allows local end-to-end development without blocking on external credentials.

## 7. Context System

Current payload is an open JSON blob, which enables fast iteration.

Near-term direction is typed action schemas per action type, for stronger inter-worker interoperability.

Example target schemas:

- design_solution: issue, context, constraints
- review_code: diff, code, focus, architectureRules
- search_code: query, scope
- trace_dependency: entryPoint, depth

Context assembly sources (planned):

- issue metadata
- repository snippets
- dependency graph
- test output and failure logs
- architecture constraints

Goal:

- make worker outputs composable and machine-consumable across multiple worker types.

Action schema baseline document:

- [docs/action-schema.md](docs/action-schema.md)

## 8. Future Extensions

Priority order (short to medium term):

1. Typed action schema and validation contract expansion.
2. Zread worker for repository context actions.
3. Action-level observability and metrics.

Recommended non-goals for current stage:

- visual workflow editor
- complex DSL
- multi-tenant and RBAC expansion

These should wait until scheduler-worker stability is proven over longer-running workloads.

## Appendix: Internal Component Dependency Graph

Server-side component relationships:

```mermaid
graph TD
    App["AsyncAiFlowApplication\n(Spring Boot entry point)"]

    subgraph Controllers
        AC["ActionController"]
        WFC["WorkflowController"]
        WRC["WorkerController"]
        PC["PlannerController"]
        WLC["WorkflowListController"]
    end

    subgraph Services
        AS["ActionService\n(core orchestration)"]
        WFS["WorkflowService"]
        WRS["WorkerService"]
        PS["PlannerService"]
        SMS["SchedulerMaintenanceService\n(scheduled loops every 2s)"]
        AQS["ActionQueueService\n(Redis operations)"]
        ACR["ActionCapabilityResolver\n(type → capability)"]
    end

    subgraph Mappers
        AM["ActionMapper"]
        WFM["WorkflowMapper"]
        WRM["WorkerMapper"]
        ALM["ActionLogMapper"]
        ADM["ActionDependencyMapper"]
    end

    subgraph Storage
        REDIS["Redis"]
        MYSQL["MySQL"]
    end

    App --> Controllers
    App --> Services

    AC --> AS
    WFC --> WFS
    WRC --> WRS
    PC --> PS
    WLC --> WFS

    AS --> AQS
    AS --> ACR
    AS --> WFS
    AS --> WRS
    AS --> AM
    AS --> ALM
    AS --> ADM

    WFS --> WFM
    WFS --> AM

    WRS --> WRM
    WRS --> AQS

    SMS --> AS
    SMS --> WRS

    AQS --> REDIS
    AM --> MYSQL
    WFM --> MYSQL
    WRM --> MYSQL
    ALM --> MYSQL
    ADM --> MYSQL
```

## Appendix: Architectural Invariants

Operational invariants to keep:

- Scheduler Core remains policy owner.
- Worker protocol stays small and stable.
- Workers are pluggable and replaceable.
- Action type resolves to required capability before assignment.
- Reliability logic stays centralized in scheduler.

Capability model details:

- [docs/worker-capability-model.md](docs/worker-capability-model.md)
