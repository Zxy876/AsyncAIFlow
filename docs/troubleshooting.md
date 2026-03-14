# Troubleshooting

This page is for internal dogfooding diagnostics.

Focus: quickly explain why an action did not run or did not complete.

## 1. Capability Mismatch

Symptom:

- action stays `QUEUED`
- worker keeps polling but receives no assignment (`204`)

Common internal pitfall:

- test worker default capability is `test_action`, so it will not claim `design_solution`

Checks:

1. Verify action type and status.

```bash
docker compose exec -T mysql mysql -uroot -proot asyncaiflow -e "
SELECT id, type, status, worker_id, error_message
FROM action
ORDER BY id DESC
LIMIT 20;"
```

2. Verify worker capabilities.

```bash
docker compose exec -T mysql mysql -uroot -proot asyncaiflow -e "
SELECT id, capabilities, status, last_heartbeat_at
FROM worker
ORDER BY updated_at DESC;"
```

3. Check capability mapping config.

- `asyncaiflow.dispatch.capability-mapping` in `application.yml`

Fix:

- ensure worker declares required capability
- or adjust mapping to match your internal naming contract
- restart affected process after config change

## 2. Schema Validation Warnings

Symptom:

- GPT worker logs warnings containing `schema_validation`

Checks:

1. Confirm validation mode in `application-gpt-worker.yml`.

- `asyncaiflow.gpt-worker.validation.mode`

2. Check action payload JSON in DB.

```bash
docker compose exec -T mysql mysql -uroot -proot asyncaiflow -e "
SELECT id, type, payload
FROM action
ORDER BY id DESC
LIMIT 5;"
```

3. Compare payload/result with schema docs.

- [docs/action-schema.md](docs/action-schema.md)
- [docs/schema-validation.md](docs/schema-validation.md)

Fix:

- correct payload structure to schema v1
- keep `warn` mode for early dogfooding
- use `strict` only when your payload contract is stable

## 3. Lease Expiration and Reclaim

Symptom:

- action transitions to `RETRY_WAIT` or `DEAD_LETTER`
- `last_reclaim_reason` is `LEASE_EXPIRED`

Checks:

```bash
docker compose exec -T mysql mysql -uroot -proot asyncaiflow -e "
SELECT id, status, retry_count, next_run_at, lease_expire_at,
       reclaim_time, last_reclaim_reason, lease_renew_success_count,
       lease_renew_failure_count, error_message
FROM action
ORDER BY id DESC
LIMIT 20;"
```

Fix:

- keep worker process alive and stable
- ensure worker can call renew endpoint during long execution (SDK does this automatically)
- increase `executionTimeoutSeconds` for long-running actions
- investigate network latency or process pauses if renew failures grow

## 4. Worker Not Polling

Symptom:

- no new heartbeat updates
- worker status becomes `STALE`
- no claim logs from worker process

Checks:

1. Verify worker process is running with correct profile and main class.

Test worker:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.test.TestWorkerApplication \
  -Dspring-boot.run.profiles=test-worker
```

GPT worker:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication \
  -Dspring-boot.run.profiles=gpt-worker
```

2. Verify scheduler reachable.

```bash
curl -sS -X POST http://localhost:8080/worker/heartbeat \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"gpt-worker-1"}'
```

Fix:

- correct `server-base-url` to `http://localhost:8080`
- make sure scheduler is running on port `8080`
- check worker logs for HTTP client errors

## 5. Action Stuck in Queue

Symptom:

- action remains `QUEUED` for a long time

Checks:

1. Check queue length in Redis.

```bash
docker compose exec -T redis redis-cli LLEN action:queue:design_solution
```

2. Check action lock key.

```bash
docker compose exec -T redis redis-cli GET action:lock:ACTION_ID
```

3. Check DB status and worker health.

```bash
docker compose exec -T mysql mysql -uroot -proot asyncaiflow -e "
SELECT id, type, status, worker_id, lease_expire_at, updated_at
FROM action
WHERE id = ACTION_ID;"
```

Fix:

- if worker is down, restart worker and wait for reclaim/retry loop
- if capability mismatch exists, fix worker capability or mapping
- only for manual emergency recovery: delete stale lock key when DB action is not `RUNNING`

Emergency command (use carefully):

```bash
docker compose exec -T redis redis-cli DEL action:lock:ACTION_ID
```

## 6. Minimal Diagnostic Checklist

When someone says "it does not run", collect these first:

1. latest scheduler log snippet
2. latest worker log snippet
3. one action row (`status`, `type`, `worker_id`, timeline fields)
4. one worker row (`capabilities`, `status`, `last_heartbeat_at`)
5. one Redis queue length for target capability

This small checklist is usually enough to explain most internal dogfooding failures.
