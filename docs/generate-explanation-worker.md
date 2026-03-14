# Generate Explanation Worker

## 1. Goal

This milestone connects the first real AI execution capability in AsyncAIFlow:

- action type: `generate_explanation`
- worker: GPT worker
- scope: explanation output only

Planner and runtime are still decoupled:

- planner proposes `search_code -> analyze_module -> generate_explanation`
- this milestone executes the last step with real/mock AI output

## 2. Configuration

Main config file:

- `src/main/resources/application-gpt-worker.yml`

Required capability list now includes:

- `design_solution`
- `review_code`
- `generate_explanation`

Key properties:

- `asyncaiflow.gpt-worker.server-base-url`
- `asyncaiflow.gpt-worker.worker-id`
- `asyncaiflow.gpt-worker.capabilities`
- `asyncaiflow.gpt-worker.validation.mode`
- `asyncaiflow.gpt-worker.validation.schema-base-path`
- `asyncaiflow.gpt-worker.llm.api-key`
- `asyncaiflow.gpt-worker.llm.model`
- `asyncaiflow.gpt-worker.llm.mock-fallback-enabled`

## 3. API Key and Mock Fallback

Execution mode is selected by API key availability:

- real LLM mode: `OPENAI_API_KEY` is set
- mock mode: `OPENAI_API_KEY` is empty and mock fallback is enabled

Mock mode is explicit and traceable:

- completion contains markers like `[MOCK_EXPLANATION]`
- result still follows the runtime schema contract

Enable real model calls:

```bash
export OPENAI_API_KEY=your_key
export OPENAI_MODEL=gpt-4.1-mini
export OPENAI_BASE_URL=https://api.openai.com
export OPENAI_ENDPOINT=/v1/chat/completions
```

## 4. Input Contract

Action payload for `generate_explanation` supports:

- `schemaVersion` (required, `v1`)
- `issue` (required)
- `repo_context` (optional)
- `file` (optional)
- `module` (optional)
- `gathered_context` (optional)

Sample payload:

```json
{
  "schemaVersion": "v1",
  "issue": "Explain how Drift story engine interacts with the Minecraft plugin",
  "repo_context": "DriftSystem backend story routes and Minecraft plugin integration",
  "file": "backend/app/routers/story.py",
  "module": "story-engine",
  "gathered_context": {
    "plugin_classes": ["StoryCreativeManager", "IntentRouter2"],
    "backend_routes": ["backend/app/routers/story.py"]
  }
}
```

Runtime schema file:

- `src/main/resources/schemas/v1/generate_explanation.payload.schema.json`

## 5. Output Contract

Worker result contains at least:

- `schemaVersion`
- `summary`
- `content`
- `worker`
- `model`
- `confidence` (optional)

Sample result:

```json
{
  "schemaVersion": "v1",
  "summary": "Story engine requests are routed through plugin intent handlers before backend story APIs are invoked.",
  "content": "Summary...\nInteraction Flow...\nKey Components...\nOpen Questions...",
  "worker": "gpt-worker",
  "model": "gpt-4.1-mini",
  "confidence": 0.71
}
```

Runtime schema file:

- `src/main/resources/schemas/v1/generate_explanation.result.schema.json`

## 6. Runtime Validation

Validation reuses existing GPT worker schema validation lifecycle:

1. parse payload
2. validate payload schema
3. execute LLM
4. build result JSON
5. validate result schema
6. submit action result

Validation mode options:

- `off`
- `warn`
- `strict`

## 7. DriftSystem Demo Path

Demo issue:

- `Explain how Drift story engine interacts with the Minecraft plugin`

Expected planner chain:

- `search_code`
- `analyze_module`
- `generate_explanation`

Run demo:

Terminal 1:

```bash
docker compose up -d redis
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

Terminal 2:

```bash
mvn spring-boot:run \
  -Dapp.main.class=com.asyncaiflow.worker.gpt.GptWorkerApplication \
  -Dspring-boot.run.profiles=gpt-worker
```

Terminal 3:

```bash
bash scripts/demo-generate-explanation.sh
```

What this script does:

- preview planner chain for DriftSystem issue
- verify chain is `search_code -> analyze_module -> generate_explanation`
- submit executable `generate_explanation` action into runtime

## 8. Focused Test Coverage

Covered by tests:

- mock mode works without API key
- `generate_explanation` result shape matches contract
- action result can be submitted successfully via runtime service

Test classes:

- `src/test/java/com/asyncaiflow/worker/gpt/GptWorkerSchemaValidationIntegrationTest.java`
- `src/test/java/com/asyncaiflow/worker/gpt/GenerateExplanationWorkerExecutionIntegrationTest.java`