# BPO Eagle V2 - 30 Job Run (2026-07-29)

## Operating decision

This run reuses the Eagle factory structure but is isolated from the Australia working-holiday data.

Pipeline:

`Collect -> Normalize -> Deduplicate -> Date/URL verification -> Hiring probability -> Salary -> Career fit -> English feasibility -> Visa -> Red Team -> Final queue -> CV mapping`

## Candidate

- Korean native
- English B1-B2
- IGT Solutions / Agoda project: 3 years 4 months
- Hotel and flight operations
- 50-80 cases per day
- SLA 95%+
- Escalation, QA, SME/floor support and coaching for 15+ new hires

## Final weights

| Dimension | Weight |
|---|---:|
| Estimated hiring probability | 35% |
| Salary | 30% |
| Career fit | 20% |
| English feasibility | 10% |
| Visa / work authorization | 5% |

The estimated hire range is a deterministic prioritization heuristic, not employer-issued or audited probability data.

## 2026-07-29 data-quality result

- 30 current Korean-language opportunities collected
- 25 individual vacancy links
- 24 postings with high-confidence seven-day evidence
- 6 search/feed or date-evidence records remain flagged for manual recheck
- Unknown visa does not reject a vacancy; explicit local-only eligibility remains a hard gate
- Queue result: 4 Apply First, 9 Apply, 13 Verify/Hold, 4 Low Priority

## CV families

1. BPO Operations & SME
2. Customer & Travel Support
3. Shared Services & Order Management
4. Content & Platform Operations
5. Partner & Customer Success

Each vacancy is mapped to a CV family in the run workbook. User contact details remain placeholders in generated CV artifacts until supplied.

## Top queue at run time

1. Transcosmos Malaysia - Customer Service Team Leader - 81.6
2. Trinity Workforce Solution - Native Korean Customer Service - 78.3
3. TARRYRISE - Korean Text Review - 76.9
4. Hanmal Global Career Consulting - Korean Contents Reviewer - 75.9
5. eTeam - Korean CSR with visa and relocation support - 70.7
6. Accenture - Customer Service Analyst - 69.6
7. Mindpec - Korean Customer Service for a global travel platform - 69.0
8. TP - Korean Social Media Support - 68.3
9. Tencent - WXG Korean Customer Service Specialist - 67.7
10. Accenture - Customer Service Associate - 67.6
