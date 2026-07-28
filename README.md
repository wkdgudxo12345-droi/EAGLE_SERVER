# EAGLE_SERVER

A deterministic, evidence-first batch pipeline that reads an existing Notion job database, checks vacancy links, scores each row, detects duplicates, and produces auditable JSON/CSV reports.

## Safety defaults

- `APPLY_CHANGES=false`: no Notion rows are changed.
- `ARCHIVE_REJECTED=false`: no rows are archived.
- Scheduled GitHub Actions runs are always dry runs.
- A row can become `A` or `B` only when an individual job URL is live and no hard gate is detected.
- Missing or incompatible Notion properties are skipped instead of crashing the entire batch.

## Pipeline

1. Read the existing Notion database with pagination.
2. Normalize configured fields.
3. Check the canonical vacancy URL.
4. Apply hard gates and deterministic CCSTM/HR/Reality/RAG scoring.
5. Detect duplicate canonical URLs or fallback identity keys.
6. Optionally write only compatible properties back to Notion.
7. Produce `output/report.json` and `output/report.csv`.

## Required GitHub Actions secrets

- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

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

The compatibility command also works:

```bash
python main.py
```

## Environment variables

| Variable | Default | Purpose |
|---|---:|---|
| `APPLY_CHANGES` | `false` | Write compatible score fields to Notion |
| `ARCHIVE_REJECTED` | `false` | Archive only hard-rejected rows; ignored unless writes are enabled |
| `URL_CHECK_ENABLED` | `true` | Check whether individual job URLs are live |
| `MAX_ROWS` | unlimited | Limit rows for a smoke run |
| `EAGLE_CONFIG` | `config/scoring.yml` | Override scoring profile |
| `OUTPUT_DIR` | `output` | Report directory |

## GitHub Actions

Pull requests and pushes run compile checks and unit tests. Manual and scheduled events additionally run the Notion pipeline. Manual runs expose explicit write and archive toggles; scheduled runs remain dry-run-only.

## Validation

```bash
python -m compileall -q eagle main.py
python -m pytest -q
```
