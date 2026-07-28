# Eagle Korean BPO Pipeline

## Scope

This pipeline reuses the Eagle operating structure only. It does not reuse Australia working-holiday data, second-visa rules, driving requirements, accommodation scoring, or regional hospitality assumptions.

The target decision is: **Which Korean-speaking BPO or customer-operations vacancies are realistic and strategically valuable for a candidate with 3.25 years of Agoda hotel/flight customer-operations experience?**

## Operating Model

```text
Sources
  -> Intake
  -> Canonical Normalization
  -> Duplicate Control
  -> BPO Hard Gate
  -> Company Research
  -> Role Research
  -> Career Transfer Model
  -> Hiring Reality Model
  -> Strategic Value Model
  -> Red Team Evidence Gate
  -> Final Apply Queue
  -> Application / Interview Feedback
```

## Stage Definitions

### 1. Intake

Collect only individually identifiable vacancies. Preserve the original URL, source, job ID, posting date, company, country, city and raw description.

No job is promoted merely because a search-results page contains relevant keywords.

### 2. Canonical Normalization

Map source-specific fields into `schemas/bpo_job.schema.json`.

Primary normalized fields:

- Opportunity
- Company
- Country / City
- Role Family / Seniority
- Korean Requirement
- Work Authorization / Visa Sponsorship
- Work Mode / Employment Type / Shift Pattern
- Experience Requirement
- Salary / Currency
- Source URL / Source Type
- Posted Date / Freshness Days
- Vacancy Status
- Evidence Text / Evidence Grade

### 3. Duplicate Control

Use normalized individual URL as the primary canonical key. Fall back to company + title + country + city only when a canonical URL is unavailable.

### 4. BPO Hard Gate

Reject or hold before scoring when any of the following is true:

- vacancy is closed, expired, filled or cancelled
- unpaid, volunteer-only or commission-only arrangement
- local nationality, citizenship or permanent residence is mandatory
- candidate lacks the required work authorization and sponsorship is unavailable
- URL is only a search-results or category page
- source cannot establish an individually identifiable vacancy

Unknown work authorization is a `RESEARCH` condition, not an automatic pass.

### 5. Company Research

Research the company separately from the job advert.

Minimum evidence targets:

- legal employer or operating entity
- BPO vendor versus in-house operation
- country and delivery-site footprint
- Korean-language project or client evidence
- sponsorship or employment-pass history when available
- salary market position
- employee-review patterns relevant to operations stability
- layoffs, project closures or client concentration risk

Company research does not override a vacancy-level hard gate.

### 6. Role Research

Extract what the employee will actually do, not only the title.

Distinguish:

- frontline customer support
- travel operations and reservations
- escalations
- QA and audit
- SME / floor support
- training
- workforce management / real-time operations
- partner or vendor support
- customer success operations
- trust and safety / content operations

### 7. Career Transfer Model

The transfer model measures how directly the vacancy uses the candidate's verified Agoda experience.

Weighted components:

- Agoda travel-domain match: 30%
- operations-process match: 20%
- escalation / QA / training match: 20%
- Korean-language value: 15%
- seniority match: 10%
- tools and process match: 5%

The model should reward Hotel + Flight operations, refunds, reissues, overbooking resolution, supplier negotiation, SLA/KPI work, QA, SME support and training.

### 8. Hiring Reality Model

The hiring-reality model answers whether the candidate can realistically enter the role now.

Weighted components:

- live vacancy: 20%
- individual URL: 15%
- work authorization / sponsorship: 25%
- experience requirement: 15%
- country, city and work mode: 10%
- salary and contract clarity: 5%
- evidence quality: 10%

### 9. Strategic Value Model

The strategic-value model prevents the pipeline from optimizing only for immediate acceptance probability.

Weighted components:

- career progression: 30%
- compensation: 20%
- employer brand value: 15%
- transferable scope: 20%
- stability: 15%

### 10. Final Priority

```text
Final Priority =
  45% Career Transfer
+ 35% Hiring Reality
+ 20% Strategic Value
```

Default bands:

- `A / APPLY NOW`: final priority >= 78 and hiring reality >= 55
- `B / VERIFY THEN APPLY`: final priority >= 64
- `C / RESEARCH or HOLD`: evidence, live status or authorization remains unresolved
- `Reject / DO NOT APPLY`: a deterministic hard gate is present

### 11. Red Team Gate

Red Team verifies the evidence behind the model, especially:

- Korean requirement is present in the actual vacancy
- source URL resolves to the same role and company
- work authorization interpretation is supported
- sponsorship claims have a source
- salary claims are not copied from unrelated markets
- company research is current
- no probability or hiring-rate claim is fabricated

### 12. Final Apply Queue

Only the following enter the action queue:

- A: apply immediately with the mapped CV variant
- B: resolve the named evidence gap, then apply

C records remain outside the final queue until the missing evidence is resolved.

## Recommended Notion Separation

Use a separate BPO data source. Do not mix BPO records into the Australia final DB.

Recommended views:

1. BPO Intake
2. BPO Research Required
3. BPO Red Team
4. BPO Apply Now
5. BPO Applied / Interview / Offer
6. BPO Rejected / Closed
7. Company Research Library
8. Performance Feedback

## CV Variants

Recommended first variants:

- Korean Customer Support
- Travel / Reservations Operations
- Escalation / Senior Specialist
- QA / SME / Trainer
- Workforce / Real-Time Operations
- Partner / Vendor Support

## Current Implementation Boundary

The branch provides the BPO profile, deterministic scoring model, canonical schema, tests and architecture. It intentionally does not ingest or rescore the existing Australia records.
