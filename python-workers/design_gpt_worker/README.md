# Design GPT Worker (Python)

Python worker for AsyncAIFlow action type `nl_to_design_dsl`.

This worker uses the Gemini API via the `google-generativeai` SDK and requests JSON output with `response_mime_type="application/json"`.

## Responsibilities

- Translate natural language clothing intent into Design Schema v0.1 JSON DSL.
- Enforce strict boundary: no 3D geometry/render fields.
- Validate DSL with schema + semantic checks.
- Auto-repair with validation feedback up to max retry count.
- Return field mappings and uncertainty markers.

## Environment Variables

- `ASYNCAIFLOW_SERVER_BASE_URL` (default: `http://localhost:8080`)
- `ASYNCAIFLOW_WORKER_ID` (default: `design-gpt-worker-py`)
- `ASYNCAIFLOW_CAPABILITIES` (default: `nl_to_design_dsl`)
- `GEMINI_API_KEY` (required)
- `GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `GEMINI_TEMPERATURE` (default: `0.2`)
- `GEMINI_TIMEOUT_SECONDS` (default: `120`)
- `DSL_TRANSLATE_MAX_RETRIES` (default: `3`)
- `DESIGN_SCHEMA_PATH` (optional, defaults to AsyncAIFlow schema v0.1)

## Run

```bash
cd python-workers/design_gpt_worker
python3 -m pip install -r requirements.txt
python3 worker.py
```

## Tests

```bash
cd python-workers/design_gpt_worker
python3 -m unittest discover -s tests -p 'test_*.py' -v
```
