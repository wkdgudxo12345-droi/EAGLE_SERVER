# Eagle Direct Bridge Operations

## Purpose

Keep Eagle operational when the GitHub repository secret `NOTION_TOKEN` is missing, stale, or invalid.

## Operating model

1. GitHub Actions performs deterministic tests and public-source crawling.
2. Crawl outputs remain GitHub artifacts and do not require Notion credentials.
3. Verified vacancies are written to the existing Notion Stage 1 data source through the connected Notion operator bridge.
4. Only evidence-backed rows are promoted to the existing Final DB.
5. No replacement databases are created.

## Failure isolation

A Notion API authentication failure must not fail the public crawl or delete output files. The workflow preflight marks Notion unavailable, skips repository-based rescoring, writes `output/workflow_status.json`, and uploads crawl artifacts.

## Direct Bridge gates

- Individual employer or job URL required.
- Vacancy must be live when checked.
- Closed, duplicated, licence-required, own-vehicle-required, citizen/PR-only and unpaid roles are rejected.
- Arrival date: 2026-08-15.
- Earliest work start: 2026-08-22.
- Candidate has no driver licence and no vehicle.
- Specified work is never guaranteed from a title alone.
- Grain roles require actual harvest/receival duties.
- Meat and food roles require eligible postcode, eligible industry and evidenced duties.
- Administrative support is marked `RECHECK` unless industry, postcode and operational connection are evidenced.

## Recovery path

Repository-based Notion rescoring can be restored later by replacing `NOTION_TOKEN`. Direct Bridge remains a valid fallback and does not block job collection or Notion operations.