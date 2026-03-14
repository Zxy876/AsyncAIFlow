# AsyncAIFlow v0.2.0

AsyncAIFlow is an asynchronous workflow engine for AI development actions. Instead of scheduling agents directly, it schedules action DAGs and dispatches them to workers with matching capabilities.

This is the first public milestone of the project: a usable baseline that combines runtime reliability, execution observability, planner-driven workflows, and an interactive terminal entrypoint.

## 1. What AsyncAIFlow is

AsyncAIFlow separates planning, orchestration, and execution:

- the planner turns a natural language issue into an action plan
- the runtime owns workflow state, dispatch, retries, and recovery
- workers execute concrete action types such as search, explanation, and review

The result is a composable workflow engine for AI-assisted development tasks rather than a single monolithic agent loop.

## 2. What's new in v0.2.0

- Runtime reliability baseline: worker heartbeat, lease assignment and renewal, timeout reclaim, retry with backoff, stale worker detection, and dead-letter handling.
- Observability APIs: stable read-only endpoints for recent workflows, workflow status, workflow actions, and action execution detail.
- Planner and worker execution stack: planner preview API, worker SDK, GPT worker, repository worker, planner worker, test worker, and typed action schemas.
- Interactive CLI: aiflow init, issue, plan, run, status, and interactive.

## 3. Key workflows now supported

- Natural language issue -> planner preview -> human review -> workflow submission.
- Explain/debug loop: search_code -> analyze_module -> generate_explanation.
- Runtime inspection from both terminal and HTTP APIs.
- Local dogfooding with repository-backed actions and mock GPT fallback when no API key is configured.

## 4. Quick start

```bash
git clone https://github.com/Zxy876/AsyncAIFlow.git
cd AsyncAIFlow

docker compose up -d redis

# start runtime
mvn spring-boot:run -Dspring-boot.run.profiles=local

# start workers in separate terminals
mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication -Dspring-boot.run.profiles=gpt-worker
mvn spring-boot:run -Dapp.main.class=com.asyncaiflow.worker.repository.RepositoryWorkerApplication -Dspring-boot.run.profiles=repository-worker

# run CLI
chmod +x aiflow
./aiflow init
./aiflow interactive
```

## 5. Current limitations

- This is not yet a full closed-loop coding system: write_file and run_tests are not implemented.
- Planner behavior is still heuristic and intentionally minimal.
- The interactive experience is terminal-only; there is no web UI yet.
- Local startup still expects runtime processes and supporting services to be started manually.

## 6. Next milestone

Worker Milestone 2 will add write_file and run_tests.

The goal is to move from explanation-oriented workflows to execution-oriented edit and validation workflows while preserving the current planner/runtime/worker boundaries.