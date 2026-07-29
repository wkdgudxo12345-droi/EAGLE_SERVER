# Eagle Incremental Operations

This replaces the slow full-database audit loop with four isolated contracts:

1. **Gmail feedback** reads only rejection-like messages and emits sanitized outcome codes. It never stores message bodies or addresses in GitHub artifacts.
2. **Incremental audit** queries only `PENDING`, `RECHECK`, or `Today Only` rows and reuses a cross-run URL cache.
3. **Promotion candidates** are emitted only when vacancy evidence, visa rules, mobility, URL, audit grade, score, and CV readiness all pass.
4. **Final promotion** is create-only and idempotent. It reads existing Final DB identities first and never updates or archives an existing row.

## Required secrets

Source audit:

- `NOTION_TOKEN`
- `NOTION_DATA_SOURCE_ID`

Final promotion:

- `FINAL_NOTION_DATA_SOURCE_ID`

Optional Gmail feedback:

- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`

## Safe operating modes

- Scheduled runs audit only. They never write to Final DB.
- Manual runs can select `promote_final=true`.
- The promotion job uses the `notion-production` GitHub Environment so reviewer protection can be enabled in repository settings.
- `PROMOTION_REQUIRE_CV_READY=true` prevents a verified vacancy from reaching Final before a reviewed CV exists.
- `CANDIDATE_WORK_RIGHTS=application_in_progress` stores a verified vacancy as `WAIT FOR VISA`; `granted` allows `READY NOW`.

## Gmail outcome codes

- `R01`: work-rights auto rejection
- `R03`: age or date-of-birth screening
- `R05`: generic ATS or human rejection
- `R07`: interview-stage rejection
- `R09`: vacancy closed
- `R10`: unclassified

The Gmail job is optional and exits successfully with `status=skipped` when OAuth secrets are absent.
