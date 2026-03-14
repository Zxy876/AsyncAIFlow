# GPT Worker

## 1. Purpose

GPT Worker is the first AI worker implementation in AsyncAIFlow.

It consumes scheduler actions and executes action types:

- design_solution
- review_code
- generate_explanation

It reuses Worker SDK lifecycle:

- register
- heartbeat
- poll
- submitResult

## 2. Action Contract

Supported action types:

- design_solution
- review_code
- generate_explanation

Input payload is JSON string in Action.payload.

### design_solution payload example

```json
{
  "issue": "Design a resilient async workflow for AI workers",
  "context": "Current stack: Spring Boot + Redis + MySQL",
  "constraints": "Keep scheduler core unchanged"
}
```

### review_code payload example

```json
{
  "focus": "state transitions and idempotency",
  "context": "Review v0.2 scheduler patch",
  "diff": "...git diff snippet...",
  "code": "...target code snippet..."
}
```

Worker result payload is JSON string containing:

- schemaVersion
- worker
- model
- content

And action-specific required fields:

- design_solution: summary
- review_code: findings
- generate_explanation: summary and content

## 3. LLM Modes

GPT Worker supports two modes:

- real LLM mode: OPENAI_API_KEY is set
- mock fallback mode: OPENAI_API_KEY is empty and mock-fallback-enabled is true

Mock fallback makes local integration smoke tests possible without external API keys.

## 4. Configuration

Main configuration file:

- [src/main/resources/application-gpt-worker.yml](src/main/resources/application-gpt-worker.yml)

Key properties:

- asyncaiflow.gpt-worker.server-base-url
- asyncaiflow.gpt-worker.worker-id
- asyncaiflow.gpt-worker.capabilities
- asyncaiflow.gpt-worker.validation.mode
- asyncaiflow.gpt-worker.validation.schema-base-path
- asyncaiflow.gpt-worker.llm.base-url
- asyncaiflow.gpt-worker.llm.endpoint
- asyncaiflow.gpt-worker.llm.api-key
- asyncaiflow.gpt-worker.llm.model
- asyncaiflow.gpt-worker.llm.mock-fallback-enabled

## 5. Runtime schema validation

GPT Worker validates both payload and result JSON schemas for:

- design_solution
- review_code
- generate_explanation

Validation modes:

- off
- warn
- strict

Default mode is warn.

In warn mode:

- payload/result schema mismatch logs warning with validation errors
- payload parse failure returns FAILED
- parseable but schema-invalid result still submits

Detailed validation lifecycle is in:

- [docs/schema-validation.md](docs/schema-validation.md)

## 6. Run GPT Worker

Start scheduler first.

Then run GPT Worker:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication \
  -Dspring-boot.run.profiles=gpt-worker
```

Example with bounded run:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication \
  -Dspring-boot.run.profiles=gpt-worker \
  -Dspring-boot.run.arguments=--asyncaiflow.gpt-worker.max-actions=2
```

When passing multiple arguments:

```bash
-Dspring-boot.run.arguments="--asyncaiflow.gpt-worker.max-actions=2 --asyncaiflow.gpt-worker.worker-id=gpt-worker-2"
```

## 7. Enable Real OpenAI Calls

Set environment variables before startup:

```bash
export OPENAI_API_KEY=your_api_key
export OPENAI_MODEL=gpt-4.1-mini
export OPENAI_BASE_URL=https://api.openai.com
```

Optional custom endpoint:

```bash
export OPENAI_ENDPOINT=/v1/chat/completions
```

## 8. Design Boundary

GPT Worker executes action business logic only.

Scheduler still owns:

- queueing and capability dispatch
- lease and timeout reclaim
- retry and dead-letter policy
- workflow DAG transition

Action schema baseline for design_solution, review_code and generate_explanation:

- [docs/action-schema.md](docs/action-schema.md)

Generate explanation execution demo:

- [docs/generate-explanation-worker.md](docs/generate-explanation-worker.md)
