# Validation rules

> **These are DEMONSTRATION rules for a portfolio project. They are not legal, RBI or other regulatory requirements.**
> Nothing here should be read as a statement of what any regulator or lender requires. Thresholds are arbitrary defaults chosen to make the demo behave sensibly.

## How rules run

* Every enabled rule records at least one result per run (`PASS`, `FAIL`, `WARN` or `SKIPPED`) so a run is fully reviewable. Disabled rules record `SKIPPED` with the reason.
* Results store the rule **version** that produced them; an admin edit bumps the version and writes a `RULE_UPDATED` audit event with a mandatory reason.
* `FAIL`/`WARN` results become **exceptions** (one per `(application, dedupe_key)`; re-running does not duplicate). When the condition clears, the exception is auto-resolved and the audit log records it.
* `WARN` results are capped at `MEDIUM` severity.
* The engine never approves or rejects a loan. An application with zero exceptions is simply "Verified" by the automated pre-check; a human decision is still required.
* LLM output is never an input to any rule outcome. The optional LLM may only fill *missing* extracted fields (values must appear verbatim in the document text) or write a narrative summary of already-computed results.

## Built-in rules

| ID | Name | Default severity | Exception category | What it checks | Default parameters |
|---|---|---|---|---|---|
| R001 | PAN information missing | HIGH | Missing Document | A PAN document must be present and its PAN number readable. | `{}` |
| R002 | Applicant name mismatch | HIGH | Identity Mismatch | Applicant name on each document is compared (normalised, order/initial-insensitive, fuzzy) with the application record. | `{'match_threshold': 0.92, 'review_threshold': 0.8}` |
| R003 | Required bank statement missing | MEDIUM | Missing Document | At least one bank statement must be uploaded. | `{}` |
| R004 | Salary information inconsistent | HIGH | Financial Mismatch | Net salary on the salary slip is compared with salary-like credits in the bank statement. | `{'tolerance_pct': 10.0}` |
| R005 | Duplicate document detected | MEDIUM | Duplicate Document | Exact duplicate uploads (same SHA-256) within the application, or the same file under another application. | `{}` |
| R006 | Statement period incomplete | MEDIUM | Incomplete Statement | Bank statement must cover a minimum number of months, be recent, and have activity in each month. | `{'min_months': 6, 'max_age_days': 150}` |
| R007 | Required ITR missing | MEDIUM | Missing Document | ITR is required for the configured application types. | `{'required_for': ['SELF_EMPLOYED']}` |
| R008 | OCR confidence below threshold | LOW | Low OCR Confidence | OCR-read documents with mean word confidence below the threshold need a human look. | `{'threshold': 0.7}` |
| R009 | Bank account name mismatch | HIGH | Identity Mismatch | Bank statement account holder is compared with the application record (and the application form's account holder). | `{'match_threshold': 0.92, 'review_threshold': 0.8}` |
| R010 | Invalid document format | MEDIUM | Invalid Document | Corrupted, encrypted, empty or unreadable files, or extension/content mismatch. A processing issue, not an accusation. | `{}` |
| R011 | Address inconsistency | MEDIUM | Identity Mismatch | Residential address on Aadhaar vs application form (abbreviation/format tolerant; pincode disagreement is material). | `{'match_threshold': 0.8, 'review_threshold': 0.6}` |
| R012 | Declared income inconsistent with ITR | MEDIUM | Financial Mismatch | Declared annual income (monthly x 12) is compared with the income declared in the ITR. | `{'tolerance_pct': 25.0}` |
| R013 | Bank account used in another application | HIGH | Manual Verification Required | Same bank + masked account identifier appears in another application. Masked digits can collide by chance: manual check only. | `{}` |
| R014 | Anomalous transactions | MEDIUM | Anomalous Transaction | Statistical anomaly detection flagged transactions. An anomaly is not proof of fraud. | `{}` |
| R015 | Other required documents missing | MEDIUM | Missing Document | Other mandatory documents per application type. | `{'SALARIED': ['AADHAAR', 'SALARY_SLIP', 'LOAN_APPLICATION'], 'SELF_EMPLOYED': ['AADHAAR', 'GST_CERTIFICATE', 'BUSINESS_REGISTRATION', 'LOAN_APPLICATION']}` |
| R016 | Manual verification required | MEDIUM | Manual Verification Required | Document type uncertain, or text contains instruction-like content (possible prompt injection). | `{'min_classification_confidence': 0.5}` |
| R017 | Identifier format invalid | MEDIUM | Invalid Document | PAN / GSTIN format (and GSTIN checksum) validation. | `{}` |
| R018 | Declared income vs observed credits | LOW | Financial Mismatch | Median monthly bank credits compared with declared monthly income. | `{'min_ratio': 0.5, 'max_ratio': 2.0}` |
| R019 | PAN number inconsistent across documents | HIGH | Identity Mismatch | PAN number on the PAN card, application form and ITR must match exactly. | `{}` |

## Admin-created rules

Admins can add two generic rule kinds through the API/UI: `required_document` (`{"category": "GST_CERTIFICATE", "application_types": ["SELF_EMPLOYED"]}`) and `field_present` (`{"category": "PAN", "field": "name"}`). Built-in rules can be enabled/disabled and have severity/thresholds changed; their logic cannot be edited from the UI.

## Exception workflow

`OPEN -> IN_REVIEW -> AWAITING_DOCUMENTS | ESCALATED | RESOLVED`, and `RESOLVED -> REOPENED`. A comment is required to resolve, escalate, request documents or reopen. Only an admin can resolve an escalated exception. Every transition, comment and assignment is audited.

## Anomaly detection (R014)

* **Isolation Forest** per account (needs >= 30 transactions; contamination 0.03) on scale-free features (log amount, ratio to the median of its direction, direction, transactions in month, day of month).
* **Robust z-score** (median/MAD on log amounts, MAD floor 0.25, positive direction only) so constant salary credits do not produce absurd scores.
* **Simple rule baseline**: amount >= 5x the median of its direction, or a credit above 3x declared monthly income.
* A transaction is flagged only when Isolation Forest flags it **and** an interpretable corroboration exists (robust z >= 3, or a *credit* >= 5x median), or when robust-z and ratio both fire. Regular payments (same description in >= 3 months with stable amounts) are exempt.
* **Account-level checks**: monthly credit spike, unusual transaction frequency, inconsistent salary credits, missing salary month.
* Output wording is deliberately neutral ("statistically unusual"); anomalies are prompts for review, never evidence of fraud.
