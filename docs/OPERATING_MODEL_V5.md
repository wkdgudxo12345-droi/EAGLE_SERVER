# Eagle V5 · Outcome-Driven Cashflow and Specified-Work Model

## Mission and original intent

The system exists to find paid Australian work that the candidate can realistically obtain without a driver licence or vehicle, start from 22 August 2026, and use to build second/third-year Working Holiday eligibility where the industry, location and actual duties are evidenced. Career quality is evaluated only after those gates pass.

The optimisation target is not the highest advertised hourly rate. It is expected usable cashflow after hiring probability, start delay, accommodation, transport, legal eligibility and physical sustainability are considered.

## Decision architecture

Every vacancy is represented by five independent dimensions:

1. **Eligibility** — valid work rights, specified-work industry/location/duties, paid employment and evidence retention.
2. **Execution** — start date, no-car transport, accommodation, credentials and individual live URL.
3. **Candidate fit** — direct experience, transferable Agoda/KFC operations, English and shift reliability.
4. **Cashflow value** — realistic weekly hours, award/pay evidence, accommodation and transport deductions, time to first pay and physical sustainability.
5. **Evidence confidence** — official source, claim-level support, contradictions and freshness.

Eligibility and execution are hard gates. A high weighted score or LLM recommendation can never override them.

## Application portfolio

Use the following allocation until enough outcome data exists for calibrated learning:

- **45% light-duty specified-work operations:** grain sampling/classification, grain-site weighbridge/data entry, processing-site QA/QC, food safety documentation, production administration and despatch where eligibility is evidenced.
- **35% fast-cash entry work:** remote hospitality with accommodation or verified transport, and immediate animal-product processing as the physical fallback.
- **15% career-bridge operations:** reservations, night audit, guest operations, site/workforce administration and coordination at eligible or strategically useful employers.
- **5% stretch:** manager, supervisor, case-work or credential-sensitive roles. Stretch volume remains capped until Australian management evidence or the matching credential exists.

## Gmail feedback controls

Recruitment email content is converted into sanitized outcome codes. Message bodies, names, addresses, document numbers and raw subjects are not stored.

- `R01` — current work-rights screening rejection.
- `R02` — right-to-work verification incomplete.
- `R03` — age/date-of-birth or screening-answer failure.
- `R05` — generic ATS or human-review rejection.
- `R06` — high candidate competition.
- `R07` — interview-stage rejection.
- `R09` — vacancy closed.
- `R10` — unclassified.

Operational responses:

- R01/R02: hold ATS applications requiring current Australian eligibility until work rights are granted or pending status is explicitly accepted.
- R03: run a screening-answer preflight before every submission.
- R06: reduce famous-resort mass applications and increase direct employer, seasonal and less visible operational campaigns.
- R07: preserve the CV family and improve interview evidence, availability and local-readiness answers.
- Managerial/credential-sensitive band: hold unless evidence meets the level gate.

## Five operating loops

### 1. Strategy

Define constraints first: visa status, arrival/start date, licence/vehicle, accommodation, target weekly net cashflow, specified-work objective and physical tolerance. Select an application portfolio rather than one job family.

### 2. Strategy change and security

Change rules only from sanitized outcome signals. Never put Gmail OAuth tokens, Notion tokens, passport details, visa documents, resumes, message bodies or email addresses in repository files or workflow artifacts. Secrets remain in encrypted secret stores. Logs contain hashes and category counts only.

### 3. Information collection

Collect employer campaigns first, then individual job URLs from market sites. Current priority sources are grain handlers, meat/food processors, remote/northern hospitality employers and direct regional operations campaigns. Search-result pages are discovery inputs, never final vacancies.

### 4. Vacancy confirmation

Open each individual vacancy and verify live status, posted/closing date, exact location/postcode, industry, actual duties, employment type, work-right language, mandatory credentials, licence/vehicle, accommodation, transport and start date. Unresolved critical evidence becomes HOLD, not a positive assumption.

### 5. Strategy learning

Outcomes are grouped by role cluster and rejection stage. Deterministic rules change immediately for proven hard failures. Statistical weight learning is allowed only after at least 10 outcomes within the same role cluster; until then results are observational. Hiring probability remains `UNCALIBRATED` rather than fabricated.

## AI model allocation

- **Deterministic policy engine:** final authority for visa, mobility, credentials, vacancy status, duplication and promotion.
- **Small extraction model or rules:** parse job duties, dates, locations and requirements into a schema.
- **LLM evidence reviewer:** identify contradictions and missing evidence; it cannot decide legal eligibility or override a hard gate.
- **Outcome calibrator:** interpretable cluster-level counts and Bayesian/empirical calibration after the minimum sample threshold.
- **Human/Direct Bridge review:** final approval for Notion promotion and application.

## Cashflow guardrails

Before labelling a role financially attractive, verify pay basis, expected paid hours, penalty rates, accommodation deduction, transport cost, first-pay timing and contract duration. Visa holders have the same workplace protections as other employees, and pay must meet the applicable award/agreement or minimum wage. Never treat cash-in-hand, accommodation exchange or recruitment-payment arrangements as acceptable shortcuts.

## Promotion contract

A vacancy enters Final DB only when:

- the URL is individual and live;
- paid duties and evidence are clear;
- specified-work state is Likely with evidence, or Unknown with explicit HOLD;
- no-car execution is proven;
- accommodation or transport is resolved;
- start timing fits;
- role level and credentials fit;
- Evidence Grade is A/B;
- a reviewed CV family exists;
- the row is not a duplicate.

No replacement Notion database is created. Direct Bridge remains the fallback while repository Notion authentication is unavailable.
