# Quickstart Local

This guide is for internal dogfooding by a small group.

Goal: start AsyncAIFlow scheduler + workers locally with minimum setup.

## 1. Prerequisites

- Java 21
- Maven 3.9+
- Docker Desktop (for MySQL and Redis)
- curl

## 2. Profile and Process Matrix

Scheduler:

- default profile: MySQL + Redis (recommended for dogfooding)
- local profile: H2(in-memory) + Redis (faster bootstrap)

Workers:

- test worker profile: `test-worker`
- gpt worker profile: `gpt-worker`

Main class switch (required for worker startup via Maven):

- `-Dapp.main.class=com.asyncaiflow.worker.test.TestWorkerApplication`
- `-Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication`

## 3. Ports and Dependencies

Expected ports:

- scheduler HTTP: `8080`
- MySQL: `3306`
- Redis: `6379`

Dependencies by mode:

- default scheduler mode: MySQL + Redis
- local scheduler mode: Redis only (DB uses in-memory H2)

## 4. Start Dependencies

Start MySQL and Redis:

```bash
docker compose up -d
```

Optional quick check:

```bash
docker compose ps
```

## 5. Start Scheduler

Recommended (internal dogfooding baseline, uses MySQL + Redis):

```bash
mvn spring-boot:run
```

Fast local mode (uses H2 + Redis):

```bash
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

Expected log signal:

- Spring Boot starts on port `8080`

## 6. Start Test Worker

Open another terminal:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.test.TestWorkerApplication \
  -Dspring-boot.run.profiles=test-worker
```

Notes:

- default capability is `test_action`
- handler supports action type `test_action` only
- it auto-registers itself on startup

## 7. Start GPT Worker

Open another terminal:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication \
  -Dspring-boot.run.profiles=gpt-worker
```

Notes:

- default capabilities are `design_solution`, `review_code` and `generate_explanation`
- it auto-registers itself on startup
- if `OPENAI_API_KEY` is empty, worker uses mock fallback by default

Optional real model env vars:

```bash
export OPENAI_API_KEY=your_key
export OPENAI_MODEL=gpt-4.1-mini
export OPENAI_BASE_URL=https://api.openai.com
export OPENAI_ENDPOINT=/v1/chat/completions
```

## 8. Quick Connectivity Checks

Scheduler reachable:

```bash
curl -i http://localhost:8080/action/poll?workerId=check-worker
```

- `400` means worker not registered yet (server is reachable)
- `204` means registered worker has no task currently

Manual worker register check:

```bash
curl -sS -X POST http://localhost:8080/worker/register \
  -H 'Content-Type: application/json' \
  -d '{"workerId":"check-worker","capabilities":["design_solution"]}'
```

Next step:

- continue with [docs/first-workflow.md](docs/first-workflow.md)
