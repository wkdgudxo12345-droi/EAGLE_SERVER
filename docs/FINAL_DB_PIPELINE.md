# Eagle Final DB Continuous Pipeline

## Operating objective

Every cycle collects up to 50 raw vacancies and writes only the highest-value verified records to the Final DB. The Final DB is the source of truth; Stage 1 is no longer a required manual transfer step.

## Cycle

1. Collect official grain-harvest and targeted food-operations vacancies.
2. Reject crawler hard gates, missing URLs, closed URLs and unverifiable URLs.
3. Require food-industry context for food QA, QC, despatch and administration roles.
4. Score candidates with the AUG22 CCSTM, HR and Reality model.
5. Retain at most 15 Fit A/B finalists.
6. Deduplicate by normalized individual URL and Canonical Key.
7. Create new Final DB records or update existing records.
8. Protect APPLIED and INTERVIEW records from automated status replacement.
9. Recheck existing Final DB URLs and mark confirmed closures as CLOSED.
10. Mark unverifiable records STALE only after 14 days without rediscovery.
11. Store cycle reports as GitHub Actions artifacts for 30 days.

## Lifecycle

- NEW: first appearance in the Final DB.
- ACTIVE: rediscovered in a later cycle.
- STALE: not rediscovered for 14 days and the URL cannot be verified.
- CLOSED: the individual vacancy URL is confirmed closed.

The pipeline records First Seen, Last Seen, Seen Count and Pipeline Run ID for auditability.

## Schedule

The workflow runs daily at 09:00 UTC, which is 17:00 in Asia/Kuala_Lumpur. It can also be launched manually from GitHub Actions.

## Required repository secret

- NOTION_TOKEN: valid Notion internal-integration installation token with read, insert and update access to the Final DB.
- FINAL_NOTION_DATA_SOURCE_ID: optional because the workflow contains the current Final DB data-source ID as a fallback.

If the token is invalid, crawling and artifact generation continue, but Final DB synchronization is skipped without failing the whole workflow.

## Manual run

Open GitHub Actions, select `Eagle Final DB Daily Loop`, choose `Run workflow`, keep the raw limit at 50 and the Final DB limit at 15, then run on `main`.

## Safety rules

- No automatic deletion or trashing.
- APPLIED and INTERVIEW statuses are protected.
- Search-result pages do not qualify as individual vacancies.
- Unverifiable URLs do not enter the Final DB.
- Car or licence hard gates remain disqualifying.
- Specified-work eligibility is never guaranteed solely from a job title.
