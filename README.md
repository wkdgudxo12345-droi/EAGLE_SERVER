# EAGLE_SERVER

Evidence-first, visa-first batch validation for the 독수리 project. The server reads an **existing** Notion data source, normalizes the different Stage 1/2/3/Final schemas, checks individual vacancy links, runs deterministic scoring, retrieves policy and row evidence, executes an independent Red Team proof loop, detects duplicates, and produces auditable artifacts.

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
- `Second Visa=No`, a required car/licence, a closed vacancy or a duplicate is a hard reject.
- `Second Visa=Unknown`, missing audit/evidence grade, an unverified individual URL, stale evidence or unresolved transport remains `VERIFY THEN APPLY`.
- A row becomes `APPLY NOW` only when the deterministic score **and** visa-first policy **and** Evidence RAG all pass.
- No existing database or data source is created, replaced, modified or archived by this branch.

## Current Notion API contract

Notion API versions from `2025-09-03` onward separate a database container from its data sources. Eagle uses `Notion-Version: 2026-03-11` and queries:

```text
POST /v1/data_sources/{data_source_id}/query
```

Use `NOTION_DATA_SOURCE_ID` whenever possible. If only `NOTION_DATABASE_ID` is supplied, Eagle retrieves the database container and discovers its single data source. It refuses to guess when multiple data sources exist.

Before checking any vacancy URL, the server retrieves the live data-source schema and resolves the aliases used by the existing Eagle databases. Missing title/URL columns are always fatal. With `STRICT_SCHEMA=true`, missing visa, mobility, audit, evidence or freshness columns also fail preflight rather than silently converting hundreds of rows to HOLD.

Official migration references:

- https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03
- https://developers.notion.com/reference/query-a-data-source

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
- `NOTION_DATA_SOURCE_ID` — preferred
- `NOTION_DATABASE_ID` — optional fallback when the database has exactly one data source

Optional, only for an explicitly dispatched paid-model run:

- `OPENAI_API_KEY`
- repository variable `OPENAI_MODEL` (defaults to `gpt-5-mini`)

The Notion integration must be shared with the existing data source and related sources required by its properties. Do not create a replacement database.

## Local dry run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
export NOTION_TOKEN='secret_...'
export NOTION_DATA_SOURCE_ID='...'
python -m eagle
```

The compatibility command uses the same V4 runner:

```bash
python main.py
```

Run the complete policy chain without Notion or external vacancy requests:

```bash
python -m eagle.smoke
```

## Environment variables

| Variable | Default | Purpose |
|---|---:|---|
| `NOTION_VERSION` | `2026-03-11` | Current data-source API version |
| `NOTION_DATA_SOURCE_ID` | empty | Exact existing Eagle data source |
| `NOTION_DATABASE_ID` | empty | Container used only to discover one source |
| `STRICT_SCHEMA` | `true` | Fail before silently scoring an incomplete schema |
| `APPLY_CHANGES` | `false` | Must remain false; existing-row mutation is blocked |
| `ARCHIVE_REJECTED` | `false` | Must remain false; archiving is blocked |
| `URL_CHECK_ENABLED` | `true` | Check whether an individual vacancy URL is live |
| `URL_CHECK_TIMEOUT_SECONDS` | `18` | Per-vacancy HTTP timeout |
| `MAX_ROWS` | unlimited | Limit rows for a smoke run |
| `EAGLE_CONFIG` | `config/scoring.yml` | Override deterministic score profile |
| `EAGLE_EVIDENCE_FILE` | `data/policy_evidence.json` | Official/project evidence corpus |
| `RAG_USE_LLM` | `false` | Call the optional paid Red Team reasoner |
| `REQUIRE_LLM_RAG` | `false` | Fail instead of falling back when the model is unavailable |
| `OPENAI_MODEL` | `gpt-5-mini` | Optional Red Team model |
| `RESUME_ENABLED` | `true` | Resume an incomplete run with the same fingerprint |
| `STATE_DIR` | `state` | Durable JSONL and checkpoint state |
| `OUTPUT_DIR` | `output` | Reports and copied state artifacts |
| `SOFT_DEADLINE_SECONDS` | `3000` | Pause before the Actions hard timeout |
| `EAGLE_RUN_KEY` | `local` | Identifies one resumable run |
| `EAGLE_CODE_SHA` | `GITHUB_SHA` | Prevents stale state after a code change |

## Interruption and resume behavior

Each completed row is appended to `state/report.jsonl`, flushed and `fsync`-ed. `state/checkpoint.json` is replaced atomically after each row. A partial final JSONL line is ignored on restart while earlier rows remain valid.

The resumable fingerprint includes:

- exact Notion data-source ID;
- scoring configuration;
- policy evidence file;
- GitHub run key;
- code SHA;
- URL/LLM settings;
- row limit.

GitHub Actions restores state from a cache scoped to `github.run_id` and saves a new cache for each `github.run_attempt`. Therefore **Re-run failed jobs** on the same Actions run resumes completed rows. A new scheduled/manual run receives a new run ID and performs a fresh audit.

The Python process has a 50-minute soft deadline inside the 60-minute job. It writes reports and exits with a visible paused status before the hard timeout, leaving enough time for cache and artifact upload. SIGTERM and SIGINT also produce an interruption checkpoint.

## Output contract

- `output/preflight.json` — Notion version, resolved data source and schema health
- `output/report.jsonl` — copied durable per-row stream
- `output/checkpoint.json` — completed count, last page ID and status
- `output/report.json` — final or partial structured report
- `output/report.csv` — final or partial review table
- `output/summary.json` — status, APPLY/VERIFY/HOLD totals and actual RAG providers

## GitHub Actions

Pull requests and pushes run:

1. Python compile checks;
2. end-to-end Eagle policy smoke test;
3. all regression tests;
4. JUnit artifact upload.

Manual and scheduled events additionally run the report-only Notion audit. Scheduled events use deterministic hybrid RAG. Manual dispatch can enable the OpenAI reasoner; selecting `require_llm_rag` makes a missing or failed model call fail visibly rather than pretending the model ran.

Concurrency uses `cancel-in-progress: false`, so a newer run does not kill an existing batch. Reports and state upload with `if: always()` after normal failures or controlled pauses.

## Validation

```bash
python -m compileall -q eagle main.py
python -m eagle.smoke
python -m pytest -q
```

Regression tests lock the original project intent and server contract: unknown/no second-visa status cannot become APPLY NOW, licence-required roles are rejected, unverified audit evidence remains HOLD, schema aliases resolve the existing Notion columns, current data-source endpoints are used, required model mode cannot silently fall back, and resumable JSONL/checkpoint state survives a partial final write.
