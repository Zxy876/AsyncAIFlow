# Scheduler Reliability Roadmap (v0.2)

## 1. Goal

v0.2 focuses on scheduler reliability, not feature breadth.

The objective is to turn the v0.1 runnable skeleton into a more fault-tolerant async action scheduler by adding:

- worker liveness tracking
- action lease ownership
- action lease renewal
- timeout reclaim
- retry with backoff
- state transition guard and idempotent result handling

## 2. Worker heartbeat model

### Data model

Worker table tracks heartbeat with `last_heartbeat_at` and status:

- `ONLINE`: heartbeat is fresh
- `STALE`: heartbeat exceeds timeout
- `OFFLINE`: reserved for manual or future control path

### APIs

- `POST /worker/register`
- `POST /worker/heartbeat`

### Runtime behavior

- heartbeat updates `last_heartbeat_at` and sets status to `ONLINE`
- poll also refreshes heartbeat
- scheduled worker maintenance marks online workers as `STALE` when heartbeat timeout is exceeded

## 3. Action lease model

### Lease assignment

When worker polls and receives an action:

1. scheduler claims queue item with Redis lock
2. action status transitions `QUEUED -> RUNNING`
3. action gets `lease_expire_at = now + execution_timeout_seconds`
4. lock ttl is refreshed to match execution timeout

### Lease ownership

- `worker_id` on action row indicates the current lease owner
- while action is `RUNNING` and lease valid, result must come from same worker

### Lease renewal

Workers can renew an active lease during long-running execution through:

- `POST /action/{actionId}/renew-lease`

Renewal checks:

- action must be `RUNNING`
- worker id must match lease owner
- lease must not already be expired

On success:

- `lease_expire_at` is moved forward by `execution_timeout_seconds`
- Redis lock ttl is refreshed to the same duration

Worker SDK loop starts periodic renewal while handler execution is in progress.

### Lease renewal observability baseline

Action row now tracks explicit execution timeline and renewal counters:

- `claim_time`
- `first_renew_time`
- `last_renew_time`
- `submit_time`
- `reclaim_time`

- `lease_renew_success_count`
- `lease_renew_failure_count`
- `last_lease_renew_at`
- `execution_started_at`
- `last_execution_duration_ms`
- `last_reclaim_reason`

Current semantics:

- poll claim sets `claim_time`
- successful renew increments success count and updates `last_lease_renew_at`
- first successful renew sets `first_renew_time`
- every successful renew updates `last_renew_time`
- accepted worker submit sets `submit_time`
- scheduler reclaim sets `reclaim_time`
- owner-side renew conflicts increment failure count
- scheduler reclaim on expired lease sets `last_reclaim_reason = LEASE_EXPIRED`
- action completion and reclaim both update `last_execution_duration_ms`

### Lease reclaim

A scheduled action maintenance loop scans:

- `status = RUNNING`
- `lease_expire_at <= now`

Expired leased actions are reclaimed and moved into retry or terminal flow.

## 4. Timeout and retry lifecycle

### Policy fields

Each action has:

- `retry_count`
- `max_retry_count`
- `backoff_seconds`
- `execution_timeout_seconds`
- `next_run_at`

### Failure or timeout handling

On failure result or lease timeout:

1. increment `retry_count`
2. if retry budget remains:
   - transition to `RETRY_WAIT`
   - set `next_run_at` with exponential backoff (capped)
3. if retry budget is exhausted:
   - worker-reported failure ends in `FAILED`
   - timeout reclaim ends in `DEAD_LETTER`

### Retry requeue

A scheduled loop scans `RETRY_WAIT` actions where `next_run_at <= now`, then:

- transitions `RETRY_WAIT -> QUEUED`
- clears lease metadata
- pushes action back to Redis capability queue

## 5. Action status state machine

Defined statuses:

- `BLOCKED`
- `QUEUED`
- `RUNNING`
- `RETRY_WAIT`
- `SUCCEEDED`
- `FAILED`
- `DEAD_LETTER`

Allowed transitions:

- `BLOCKED -> QUEUED`
- `QUEUED -> RUNNING`
- `RUNNING -> SUCCEEDED`
- `RUNNING -> RETRY_WAIT`
- `RUNNING -> FAILED`
- `RUNNING -> DEAD_LETTER`
- `RETRY_WAIT -> QUEUED`
- `RETRY_WAIT -> DEAD_LETTER`

All other transitions are rejected by state guards.

## 6. Idempotency and submission safety

Result submission protections:

- only running action can be mutated by result submit
- worker id must match lease owner for running action
- duplicate submissions after terminal or retry-wait state are treated as safe no-op
- stale late result (lease already expired) is ignored to prevent corruption

This prevents repeated or late callbacks from breaking action state.

## 7. Failure recovery strategy

Recovery strategy combines Redis lock + DB truth:

- Redis queue and lock provide dispatch-time coordination
- DB action row stores authoritative lifecycle and lease metadata
- scheduled maintenance uses DB state to recover from worker crash, missed result, and timeout

Recovery paths:

- worker crash before submit: lease expires, action reclaimed
- transient execution failure: retry with backoff
- repeated timeout/failure beyond budget: terminal `FAILED`/`DEAD_LETTER`
- stale worker: worker marked `STALE`, no hard crash of scheduler

## 8. Test coverage in v0.2

Integration-style tests verify:

- poll assigns lease
- running owner action can renew lease
- lease renewal conflict for wrong worker
- lease renewal conflict for expired lease
- expired lease can be reclaimed
- downstream activation only after upstream success
- retry count increments correctly
- duplicate result submission is safely handled

Worker loop tests verify:

- periodic renew is triggered during long execution
- renew is skipped when assignment has no lease deadline
- renew observability fields remain compatible with SDK action snapshot model

This test set validates scheduler reliability behavior without expanding to AI worker integration yet.
