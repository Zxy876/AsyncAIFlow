# First Workflow

This guide helps internal users finish one complete run in about 10 minutes.

Scenario:

- scheduler is running
- GPT worker is running
- create one `design_solution` action
- observe claim and completion
- inspect capability/schema/timeline signals

No-API-key fallback path is also supported in this guide via test worker + `test_action`.

## 1. Start Runtime

Follow [docs/quickstart-local.md](docs/quickstart-local.md) first.

For this guide, recommended runtime is:

- scheduler with default profile (`mvn spring-boot:run`)
- GPT worker with `gpt-worker` profile
- MySQL + Redis via Docker Compose

No-API-key runtime (fully local simulation):

- scheduler with `local` profile (`mvn spring-boot:run -Dspring-boot.run.profiles=local`)
- test worker with `test-worker` profile
- Redis only

## 2. Create a Workflow

```bash
WORKFLOW_RESP=$(curl -sS -X POST http://localhost:8080/workflow/create \
  -H 'Content-Type: application/json' \
  -d '{"name":"first-dogfood-flow","description":"internal first workflow"}')

echo "$WORKFLOW_RESP"
WORKFLOW_ID=$(echo "$WORKFLOW_RESP" | jq -r '.data.id')
echo "WORKFLOW_ID=$WORKFLOW_ID"
```

If `jq` is unavailable, copy the workflow id manually from response JSON.

## 3. Register Worker (Optional Manual Check)

GPT worker auto-registers on startup. This manual call is only for explicit verification.

```bash
curl -sS -X POST http://localhost:8080/worker/register \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"gpt-worker-1","capabilities":["design_solution","review_code","generate_explanation"]}'
```

No-API-key test worker check:

```bash
curl -sS -X POST http://localhost:8080/worker/register \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"test-worker-1","capabilities":["test_action"]}'
```

## 4. Create a design_solution Action

```bash
ACTION_RESP=$(curl -sS -X POST http://localhost:8080/action/create \
  -H 'Content-Type: application/json' \
  -d "{\"workflowId\":${WORKFLOW_ID},\"type\":\"design_solution\",\"payload\":\"{\\\"schemaVersion\\\":\\\"v1\\\",\\\"issue\\\":\\\"Design first internal dogfood loop\\\",\\\"context\\\":\\\"small group usage\\\",\\\"constraints\\\":[\\\"keep product surface minimal\\\",\\\"improve first-run experience\\\"]}\",\"maxRetryCount\":2,\"backoffSeconds\":3,\"executionTimeoutSeconds\":300}")

echo "$ACTION_RESP"
ACTION_ID=$(echo "$ACTION_RESP" | jq -r '.data.id')
echo "ACTION_ID=$ACTION_ID"
```

Expected immediate state:

- action status is `QUEUED`

### 4.1 No-API-key local demo action (`test_action`)

Use this if you run test worker instead of GPT worker.

```bash
ACTION_RESP=$(curl -sS -X POST http://localhost:8080/action/create \
  -H 'Content-Type: application/json' \
  -d "{\"workflowId\":${WORKFLOW_ID},\"type\":\"test_action\",\"payload\":\"{\\\"forceResult\\\":\\\"SUCCEEDED\\\",\\\"sleepSeconds\\\":1}\",\"upstreamActionIds\":[],\"maxRetryCount\":0,\"backoffSeconds\":1,\"executionTimeoutSeconds\":120}")

echo "$ACTION_RESP"
ACTION_ID=$(echo "$ACTION_RESP" | jq -r '.data.id')
echo "ACTION_ID=$ACTION_ID"
```

## 5. Observe Worker Claim and Completion

### 5.1 Watch worker log

From GPT worker terminal, expect logs similar to:

- claimed action id
- schema validation warnings (if any)
- submit result

For test worker path, schema validation logs are not expected.

### 5.2 Inspect action state in MySQL

```bash
docker compose exec -T mysql mysql -uroot -proot asyncaiflow -e "
SELECT id, type, status, worker_id, retry_count, lease_expire_at, claim_time, submit_time,
       reclaim_time, lease_renew_success_count, lease_renew_failure_count,
       last_lease_renew_at, last_execution_duration_ms, last_reclaim_reason, error_message
FROM action
WHERE id = ${ACTION_ID};"
```

Typical path for this guide:

- `QUEUED -> RUNNING -> SUCCEEDED`

## 6. Inspect Capability Signals

Check worker capability declaration:

```bash
docker compose exec -T mysql mysql -uroot -proot asyncaiflow -e "
SELECT id, capabilities, status, last_heartbeat_at
FROM worker
ORDER BY updated_at DESC;"
```

What to verify:

- worker has `design_solution`
- worker status is `ONLINE`

## 7. Inspect Schema Validation Signals

Schema validation happens inside GPT worker.

Check worker log for `schema_validation` entries.

Interpretation:

- `mode=warn`: warning only, execution may continue
- `mode=strict`: schema mismatch causes `FAILED`

Schema references:

- [docs/action-schema.md](docs/action-schema.md)
- [docs/schema-validation.md](docs/schema-validation.md)

## 8. Inspect Timeline and Reclaim Signals

For the action row, focus on fields:

- `claim_time`
- `first_renew_time`
- `last_renew_time`
- `submit_time`
- `reclaim_time`
- `lease_renew_success_count`
- `lease_renew_failure_count`
- `last_reclaim_reason`

Quick timeline query:

```bash
docker compose exec -T mysql mysql -uroot -proot asyncaiflow -e "
SELECT id, status, claim_time, first_renew_time, last_renew_time, submit_time,
       reclaim_time, lease_renew_success_count, lease_renew_failure_count,
       last_reclaim_reason
FROM action
WHERE id = ${ACTION_ID};"
```

For short actions, renew counters may stay `0`.

## 9. Next Debug Step

If your first run did not finish as expected, continue with:

- [docs/troubleshooting.md](docs/troubleshooting.md)
