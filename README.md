# EAGLE_SERVER

Evidence-first, visa-first batch validation for the 독수리 project. The server reads an **existing** Notion job database, normalizes the different Stage 1/2/3/Final schemas, checks individual vacancy links, runs deterministic scoring, retrieves policy and row evidence, executes an independent Red Team proof loop, detects duplicates, and produces auditable artifacts.

## Non-negotiable project order

1. Second/third-year specified-work evidence and eligible location/industry.
2. Genuine paid duties and preservable employment evidence.
3. No-car/no-licence execution.
4. Staff accommodation or verified transport.
5. Live individual vacancy and freshness.
6. Only then: CCSTM, HR fit, Reality and priority scoring.

A high HR or CCSTM score can never override a visa, mobility, vacancy, audit or evidence gate.

## Safety defaults

- Existing Stage 1, Stage 2, Stage 3 and Final rows are **report-only**: the V4 runner refuses `APPLY_CHANGES=true` and `ARCHIVE_REJECTED=true`.
- Scheduled GitHub Actions runs never call the paid LLM reasoner and never write to Notion.
- Every processed row is flushed to `output/report.jsonl`; `output/checkpoint.json` survives an interrupted run and is uploaded with `if: always()`.
- `Second Visa=No`, a required car/licence, a closed vacancy or a duplicate is a hard reject.
- `Second Visa=Unknown`, missing audit/evidence grade, an unverified individual URL, stale evidence or an unresolved transport question remains `VERIFY THEN APPLY`.
- A row becomes `APPLY NOW` only when the deterministic score **and** visa-first policy **and** Evidence RAG all pass.
- No existing database is created, replaced, modified or archived by this branch.

## Actual RAG and Red Team behavior

The V4 runner does not rename a weighted score as “RAG”. It runs a separate evidence pipeline:

1. Normalize the job row using aliases for the existing Notion schemas.
2. Build claim-level evidence for vacancy status, specified-work eligibility, no-car execution and audit quality.
3. Retrieve official policy and row evidence with lexical + deterministic semantic retrieval.
4. Force all critical evidence and contradictions into the proof loop even when retrieval ranking is low.
5. Produce `PASS`, `HOLD` or `REJECT` from deterministic proof rules.
6. Optionally call the OpenAI Responses API as a Red Team reasoner. The model may flag risks, but it cannot override the deterministic verdict.

The bundled policy evidence points to the official Home Affairs specified-work rule and the user's no-car project constraint. Exact postcode, industry, paid duties and employer evidence must still be captured in the Notion audit before `Second Visa=Likely` can pass.

## Required GitHub Actions secrets

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

Optional, only for an explicitly dispatched paid-model run:

- `OPENAI_API_KEY`
- repository variable `OPENAI_MODEL` (defaults to `gpt-5-mini`)

The Notion integration must be shared with the existing database. Do not create a replacement database.

## Local dry run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
export NOTION_TOKEN='secret_...'
export NOTION_DATABASE_ID='...'
python -m eagle
```

The compatibility command uses the same V4 runner:

```bash
python main.py
```

## Environment variables

| Variable | Default | Purpose |
|---|---:|---|
| `APPLY_CHANGES` | `false` | Must remain false; existing-row mutation is blocked |
| `ARCHIVE_REJECTED` | `false` | Must remain false; archiving is blocked |
| `URL_CHECK_ENABLED` | `true` | Check whether an individual vacancy URL is live |
| `MAX_ROWS` | unlimited | Limit rows for a smoke run |
| `EAGLE_CONFIG` | `config/scoring.yml` | Override deterministic score profile |
| `EAGLE_EVIDENCE_FILE` | `data/policy_evidence.json` | Official/project evidence corpus |
| `RAG_USE_LLM` | `false` | Call the optional paid Red Team reasoner |
| `REQUIRE_LLM_RAG` | `false` | Fail instead of falling back when the model is unavailable |
| `OPENAI_MODEL` | `gpt-5-mini` | Optional Red Team model |
| `OUTPUT_DIR` | `output` | Report and checkpoint directory |

## Output contract

- `output/report.jsonl` — durable per-row stream written during execution
- `output/checkpoint.json` — completed count, total and last page ID
- `output/report.json` — final structured report
- `output/report.csv` — final review table
- `output/summary.json` — APPLY/VERIFY/HOLD totals and actual RAG providers

## GitHub Actions

Pull requests and pushes run compile checks and regression tests. Manual and scheduled events run the report-only Notion audit. Scheduled events use deterministic hybrid RAG. Manual dispatch can enable the OpenAI reasoner; selecting “require LLM RAG” makes a missing or failed model call fail visibly rather than pretending the model ran.

Concurrency uses `cancel-in-progress: false`, so a newer run does not kill an existing batch. Artifacts upload even after a failed or interrupted pipeline step.

## Validation

```bash
python -m compileall -q eagle main.py
python -m pytest -q
```

Regression tests lock the original project intent: unknown/no second-visa status cannot become APPLY NOW, licence-required roles are rejected, unverified audit evidence remains HOLD, schema aliases resolve the existing Notion columns, and required model mode cannot silently fall back.
