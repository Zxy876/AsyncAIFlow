# Worker SDK

## 1. Purpose

AsyncAIFlow scheduler core is responsible for action lifecycle and dispatch.

Worker SDK is the integration layer for executors.

It gives a worker only four responsibilities:

- register
- heartbeat
- poll
- submit result

That keeps worker implementation small and keeps scheduling policy inside the scheduler core.

## 2. Worker lifecycle

Reference lifecycle:

```text
startup
  -> register worker
  -> enter loop
      -> heartbeat when due
      -> poll action
      -> execute action
  -> renew lease periodically while executing
      -> submit result
      -> repeat
```

Reference loop is implemented in:

- [src/main/java/com/asyncaiflow/worker/sdk/WorkerLoop.java](src/main/java/com/asyncaiflow/worker/sdk/WorkerLoop.java)

## 3. SDK surface

Main SDK classes:

- [src/main/java/com/asyncaiflow/worker/sdk/AsyncAiFlowWorkerClient.java](src/main/java/com/asyncaiflow/worker/sdk/AsyncAiFlowWorkerClient.java)
- [src/main/java/com/asyncaiflow/worker/sdk/WorkerConfig.java](src/main/java/com/asyncaiflow/worker/sdk/WorkerConfig.java)
- [src/main/java/com/asyncaiflow/worker/sdk/WorkerActionHandler.java](src/main/java/com/asyncaiflow/worker/sdk/WorkerActionHandler.java)
- [src/main/java/com/asyncaiflow/worker/sdk/WorkerExecutionResult.java](src/main/java/com/asyncaiflow/worker/sdk/WorkerExecutionResult.java)

Worker SDK protocol models are under:

- [src/main/java/com/asyncaiflow/worker/sdk/model](src/main/java/com/asyncaiflow/worker/sdk/model)

## 4. Register protocol

Endpoint:

- `POST /worker/register`

Request body:

```json
{
  "workerId": "test-worker-1",
  "capabilities": ["test_action"]
}
```

Registration declares the worker identity and capability set used by scheduler dispatch.

## 5. Heartbeat protocol

Endpoint:

- `POST /worker/heartbeat`

Request body:

```json
{
  "workerId": "test-worker-1"
}
```

Heartbeat updates worker liveness.

Scheduler uses it to maintain:

- `last_heartbeat_at`
- `ONLINE`
- `STALE`

Worker SDK sends heartbeat periodically during the execution loop.

## 6. Poll protocol

Endpoint:

- `GET /action/poll?workerId=test-worker-1`

Behavior:

- `200` with action payload means action assigned
- `204` means no work available

Poll response payload contains:

- `actionId`
- `workflowId`
- `type`
- `payload`
- `retryCount`
- `leaseExpireAt`

The `leaseExpireAt` field tells the worker the current execution lease deadline.

## 7. Result submission protocol

Endpoint:

- `POST /action/result`

Request body:

```json
{
  "workerId": "test-worker-1",
  "actionId": 123,
  "status": "SUCCEEDED",
  "result": "execution output",
  "errorMessage": null
}
```

Allowed result statuses at worker side:

- `SUCCEEDED`
- `FAILED`

Scheduler decides whether failed execution should retry, wait, or enter terminal state.

## 8. Lease renewal protocol

Endpoint:

- `POST /action/{actionId}/renew-lease`

Request body:

```json
{
  "workerId": "test-worker-1"
}
```

Rules:

- action must still be `RUNNING`
- `workerId` must match action lease owner
- expired lease cannot be renewed

On success scheduler updates:

- `lease_expire_at = now + execution_timeout_seconds`
- lock ttl to the same duration

WorkerLoop starts a periodic renew task during execution and stops it before submit.

## 9. Capability declaration

Capability is the dispatch contract between worker and action type.

Examples:

- `test_action`
- `design_solution`
- `search_code`
- `trace_dependency`

Worker only needs to declare the action types it can handle.

Scheduler owns matching logic.

Current mapping rule:

- default: required capability equals action type
- optional override: `asyncaiflow.dispatch.capability-mapping`

Capability model formalization:

- [docs/worker-capability-model.md](docs/worker-capability-model.md)

## 10. Reference TestWorker

Reference implementation:

- [src/main/java/com/asyncaiflow/worker/test/TestWorkerApplication.java](src/main/java/com/asyncaiflow/worker/test/TestWorkerApplication.java)
- [src/main/java/com/asyncaiflow/worker/test/TestWorkerActionHandler.java](src/main/java/com/asyncaiflow/worker/test/TestWorkerActionHandler.java)
- [src/main/java/com/asyncaiflow/worker/test/TestWorkerProperties.java](src/main/java/com/asyncaiflow/worker/test/TestWorkerProperties.java)
- [src/main/resources/application-test-worker.yml](src/main/resources/application-test-worker.yml)

Capability:

- `test_action`

Behavior:

- polls actions continuously
- sleeps random seconds
- randomly succeeds or fails

Optional payload overrides are supported for deterministic demos:

```json
{
  "sleepSeconds": 2,
  "forceResult": "SUCCEEDED",
  "successRate": 1.0
}
```

Useful for validating:

- lease behavior
- retry behavior
- timeout reclaim
- downstream activation

## 11. Running the reference worker

Start scheduler first.

Then run TestWorker:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.test.TestWorkerApplication \
  -Dspring-boot.run.profiles=test-worker
```

Example with bounded run for smoke tests:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.test.TestWorkerApplication \
  -Dspring-boot.run.profiles=test-worker \
  -Dspring-boot.run.arguments=--asyncaiflow.reference-worker.max-actions=2
```

The `app.main.class` property keeps scheduler packaging stable by default while allowing `spring-boot:run` to switch to the reference worker entrypoint explicitly.

If you need multiple runtime overrides, pass them as a quoted space-separated string:

```bash
-Dspring-boot.run.arguments="--asyncaiflow.reference-worker.worker-id=test-worker-2 --asyncaiflow.reference-worker.max-actions=2"
```

Useful overrides:

- `--asyncaiflow.reference-worker.server-base-url=http://localhost:8080`
- `--asyncaiflow.reference-worker.worker-id=test-worker-2`
- `--asyncaiflow.reference-worker.poll-interval-millis=1000`
- `--asyncaiflow.reference-worker.heartbeat-interval-millis=5000`
- `--asyncaiflow.reference-worker.test.success-rate=0.5`

## 12. Design boundary

Worker SDK does not own:

- retry policy
- lease reclaim
- timeout handling
- workflow progression

Those remain inside scheduler core.

Worker SDK only provides a clean protocol adapter so new workers can plug in without changing scheduler behavior.

## 13. GPT Worker

The first AI worker implementation built on top of this SDK is documented in:

- [docs/gpt-worker.md](docs/gpt-worker.md)