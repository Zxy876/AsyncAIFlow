# Action Schema

## 1. Purpose

AsyncAIFlow uses Action as the smallest execution unit.

To make multiple workers interoperable, action payload and action result must follow explicit schemas.

This document defines v1 contracts for:

- design_solution
- review_code
- search_code
- generate_explanation

## 2. Scope and Boundary

Scheduler Core remains orchestration owner and stores payload/result as JSON strings.

Schema validation is owned by worker implementations in v1.

That keeps scheduler stable while enabling strict worker contracts.

## 3. Versioning Rules

Each payload and result must include:

- schemaVersion: "v1"

Compatibility policy:

- non-breaking changes: add optional fields only
- breaking changes: new major schema version (v2, v3, ...)

## 4. Transport Contract

Action payload and result are serialized JSON strings.

Example action payload envelope:

```json
{
  "schemaVersion": "v1",
  "issue": "Design lease renewal for long-running actions",
  "context": "Current worker loop is poll -> execute -> submit",
  "constraints": [
    "Do not expand scheduler product surface"
  ]
}
```

Example action result envelope:

```json
{
  "schemaVersion": "v1",
  "worker": "gpt-worker",
  "model": "gpt-4.1-mini",
  "summary": "Lease renewal should run periodically during execution.",
  "proposedDesign": [
    {
      "title": "Lease renew loop",
      "rationale": "Prevent duplicate execution for long-running tasks"
    }
  ],
  "confidence": 0.78
}
```

`actionType` is action metadata and should not be duplicated in result JSON to avoid drift between action.type and result payload.

## 5. v1 Payload Schemas

### 5.1 design_solution payload

Required fields:

- schemaVersion
- issue

Optional fields:

- context
- constraints
- acceptanceCriteria
- priority

Schema file:

- [docs/schemas/v1/design_solution.payload.schema.json](docs/schemas/v1/design_solution.payload.schema.json)

### 5.2 review_code payload

Required fields:

- schemaVersion

At least one of the following is required:

- diff
- code

Optional fields:

- focus
- context
- architectureRules
- knownIssues

Schema file:

- [docs/schemas/v1/review_code.payload.schema.json](docs/schemas/v1/review_code.payload.schema.json)

### 5.3 search_code payload

Required fields:

- schemaVersion
- query

Optional fields:

- scope.paths
- scope.languages
- scope.includeTests
- scope.maxResults
- hints.symbols
- hints.keywords

Schema file:

- [docs/schemas/v1/search_code.payload.schema.json](docs/schemas/v1/search_code.payload.schema.json)

### 5.4 generate_explanation payload

Required fields:

- schemaVersion
- issue

Optional fields:

- repo_context
- file
- module
- gathered_context

Schema file:

- [docs/schemas/v1/generate_explanation.payload.schema.json](docs/schemas/v1/generate_explanation.payload.schema.json)

## 6. v1 Result Schemas

### 6.1 design_solution result

Required fields:

- schemaVersion
- summary

Optional fields:

- worker
- model
- proposedDesign
- riskItems
- content
- confidence

Schema file:

- [docs/schemas/v1/design_solution.result.schema.json](docs/schemas/v1/design_solution.result.schema.json)

### 6.2 review_code result

Required fields:

- schemaVersion
- findings

Optional fields:

- worker
- model
- suggestedFixes
- residualRisks
- content
- confidence

Schema file:

- [docs/schemas/v1/review_code.result.schema.json](docs/schemas/v1/review_code.result.schema.json)

### 6.3 search_code result

Required fields:

- schemaVersion
- summary
- matches

Optional fields:

- worker
- model
- symbols
- recommendations
- content
- confidence

Schema file:

- [docs/schemas/v1/search_code.result.schema.json](docs/schemas/v1/search_code.result.schema.json)

### 6.4 generate_explanation result

Required fields:

- schemaVersion
- summary
- content
- worker
- model

Optional fields:

- confidence

Schema file:

- [docs/schemas/v1/generate_explanation.result.schema.json](docs/schemas/v1/generate_explanation.result.schema.json)

## 7. Worker Implementation Guidance

Worker should validate payload before execution:

1. Parse payload JSON string.
2. Validate against action-type payload schema.
3. Reject invalid payload with FAILED result and explicit error message.
4. Produce result JSON that matches action-type result schema.

## 8. Rollout Plan

Phase A:

- document schemas (this file)
- implement validation in GPT worker and future workers

Phase B:

- add optional scheduler-side pre-validation guard
- add schema audit logs and metrics

Phase C:

- enforce strict schema compliance for selected action types

## 9. Next Schema Candidates

After v1 baseline:

- trace_dependency payload/result
- summarize_module payload/result
- run_tests payload/result
- generate_explanation enrichment fields
