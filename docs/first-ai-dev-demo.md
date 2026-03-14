# First AI Dev Demo

This is the fastest way to show AsyncAIFlow as an AI development workflow preview system.

Goal in 10 minutes:

- start the local runtime
- submit one natural language issue
- see a readable workflow plan preview

Scope:

- planner preview only
- no workflow execution
- no confirm-and-run endpoint

## 1. Start Redis

```bash
docker compose up -d redis
```

## 2. Start scheduler

Use the local profile so the demo does not depend on MySQL:

```bash
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

Wait until the server is fully started on port 8080.

## 3. Run the issue demo

Open another terminal in the project root:

```bash
bash scripts/demo-issue.sh "Explain authentication module"
```

Expected readable output:

```text
Issue: Explain authentication module
Mode: preview-only

Plan
 1. search_code
    query: Explain authentication module
 2. analyze_module <- depends on 1
    issue: Explain authentication module
 3. generate_explanation <- depends on 2
    issue: Explain authentication module
```

## 4. Try two more issue types

Review example:

```bash
bash scripts/demo-issue.sh "Review authentication error handling"
```

Fix example:

```bash
bash scripts/demo-issue.sh "Fix login retry bug" "web login flow"
```

## 5. Optional JSON view

If you want the raw API response instead of the readable plan view:

```bash
bash scripts/demo-issue.sh --json "Explain authentication module"
```

## 6. Optional planner worker process

The preview endpoint works without planner-worker because planning is currently inside the API service.

If you want to show the larger architecture, start planner-worker in a separate terminal:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.planner.PlannerWorkerApplication \
  -Dspring-boot.run.profiles=planner-worker
```

## 7. Troubleshooting

- If the demo says it cannot reach the server, confirm Redis is running and scheduler finished startup.
- If you accidentally use the default profile, start full dependencies first with `docker compose up -d`.
- If readable plan output falls back to JSON, install `jq` or use the JSON mode explicitly.