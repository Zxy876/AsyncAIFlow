# Human In The Loop

This workflow adds a review checkpoint between planner output and runtime execution.

Flow:

- issue
- AI generates plan
- human reviews or edits plan JSON
- runtime creates workflow and actions

Current scope:

- CLI only
- no web UI
- no scheduler core changes
- no planner logic changes

## 1. Generate a plan

```bash
bash scripts/demo-issue.sh --save plan.json "Find bug in resource mapping"
```

This does two things:

- prints a readable plan preview
- saves raw plan JSON to `plan.json`

## 2. Review the saved plan

```bash
bash scripts/demo-plan-view.sh plan.json
```

Example output:

```text
Plan
 1. search_code
    query: Find bug in resource mapping
 2. analyze_module <- depends on 1
    issue: Find bug in resource mapping
 3. design_solution <- depends on 2
    issue: Find bug in resource mapping
```

## 3. Edit the plan manually

Open `plan.json` and adjust the plan before execution.

Example: insert a `review_code` step before `design_solution`.

```json
{
  "plan": [
    {"type": "search_code", "payload": {"schemaVersion": "v1", "query": "Find bug in resource mapping"}, "depends_on": []},
    {"type": "analyze_module", "payload": {"schemaVersion": "v1", "issue": "Find bug in resource mapping"}, "depends_on": [0]},
    {"type": "review_code", "payload": {"schemaVersion": "v1", "focus": "issue-driven review"}, "depends_on": [1]},
    {"type": "design_solution", "payload": {"schemaVersion": "v1", "issue": "Find bug in resource mapping"}, "depends_on": [2]}
  ]
}
```

## 4. Run the plan

```bash
bash scripts/demo-run.sh plan.json
```

The script will:

- create a workflow
- create actions in plan order
- translate `depends_on` step indexes into real `upstreamActionIds`
- submit the plan to AsyncAIFlow runtime

## 5. Local startup

```bash
docker compose up -d redis
mvn spring-boot:run -Dspring-boot.run.profiles=local
```

## 6. Why this mode matters

This mode keeps execution human-approved:

- AI proposes the development flow
- human fixes planner mistakes before runtime execution
- runtime remains the execution engine, not the planning authority

This is the intended direction for a safe AI development workflow.