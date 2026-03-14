# Schema Validation

## 1. Goal

Runtime schema validation turns Action Schema from documentation contract into execution-time contract.

Current scope:

- GPT Worker
- action types: design_solution, review_code and generate_explanation
- scheduler core is unchanged

## 2. Validation Lifecycle

For each claimed action, GPT Worker executes validation in this order:

1. Parse payload JSON string.
2. Resolve payload schema by action type.
3. Validate payload against JSON Schema.
4. Execute action logic.
5. Build result JSON string.
6. Resolve result schema by action type.
7. Validate result against JSON Schema.
8. Submit result to scheduler.

## 3. Validation Modes

Supported modes:

- off
- warn
- strict

Configuration key:

- asyncaiflow.gpt-worker.validation.mode

Default mode:

- warn

### 3.1 off

- Skip payload/result schema checks.
- Keep only JSON parsing requirements.

### 3.2 warn

- Run payload/result schema checks.
- On validation failure, log structured warning with details.
- Continue execution and allow submit when JSON is parseable.
- Payload parse failure still returns FAILED.

### 3.3 strict

- Run payload/result schema checks.
- On validation failure, return FAILED immediately.
- Prevent submit for invalid result schema.

## 4. Payload Validation Behavior

Payload phase rules:

- If payload JSON cannot be parsed: fail action immediately.
- If payload JSON is parseable but schema-invalid:
  - warn mode: log warning and continue.
  - strict mode: fail action.

Validation logs include:

- phase (payload)
- mode
- actionId
- actionType
- schemaPath
- validation errors

## 5. Result Validation Behavior

Result phase rules:

- Result JSON must be parseable.
- If result JSON parse fails: fail action.
- If result JSON parse succeeds but schema-invalid:
  - warn mode: log warning and still submit.
  - strict mode: fail action.

Validation logs include:

- phase (result)
- mode
- actionId
- actionType
- schemaPath
- validation errors

## 6. Schema Resolver

GPT Worker uses action-type mapping to resolve schema resources:

- design_solution
  - payload: schemas/v1/design_solution.payload.schema.json
  - result: schemas/v1/design_solution.result.schema.json
- review_code
  - payload: schemas/v1/review_code.payload.schema.json
  - result: schemas/v1/review_code.result.schema.json
- generate_explanation
  - payload: schemas/v1/generate_explanation.payload.schema.json
  - result: schemas/v1/generate_explanation.result.schema.json

Configuration key:

- asyncaiflow.gpt-worker.validation.schema-base-path

Default value:

- schemas/v1

## 7. Future Extension

Planned extension path:

1. Reuse the same validator utility in Zread Worker.
2. Add optional scheduler-side pre-validation (non-blocking first).
3. Introduce audit metrics for schema mismatch rates.
4. Enable strict mode incrementally per action type.

## 8. Automated Test Coverage

Integration-style tests for GPT Worker runtime schema validation are in:

- [src/test/java/com/asyncaiflow/worker/gpt/GptWorkerSchemaValidationIntegrationTest.java](src/test/java/com/asyncaiflow/worker/gpt/GptWorkerSchemaValidationIntegrationTest.java)

Covered behavior:

- payload valid JSON + valid schema: execution continues
- payload valid JSON + invalid schema in warn mode: warning and continue
- payload valid JSON + invalid schema in strict mode: fail
- payload invalid JSON: fail immediately
- validation mode off: schema validation skipped
- result valid schema: submit normally
- result invalid schema in warn mode: warning and continue
- result invalid schema in strict mode: fail before submit

Current Phase 1 guarantees:

- scheduler core remains unchanged
- validation enforcement is worker-side only
- default mode is warn for safe rollout on real traffic
- strict mode is available for controlled hard enforcement
