# SAMPLE - Subcontractor Prequalification Questionnaire

> **SAMPLE DOCUMENT - NOT A REAL FORM.** Glenmara Construction Ltd is a fictional main contractor.
> This form was written to resemble what Irish main contractors commonly ask subcontractors for
> at prequalification. Replace it with each real contractor's own form before using the rules
> built from it (`rules/main_contractors/glenmara_construction_sample.json`).

**Main contractor:** Glenmara Construction Ltd (SAMPLE)
**Form reference:** GC-PQQ-SAMPLE rev. 3
**Return to:** supplychain-portal.glenmara-construction.example.ie
**Renewal:** every 12 months, or sooner if any certificate below expires.

Subcontractors may not start on site until this questionnaire is approved and every
document marked **Required** is current.

---

## A. Company details

| # | Question | Evidence | Required |
| --- | --- | --- | --- |
| A1 | Registered company name and trading name | - | Required |
| A2 | Companies Registration Office (CRO) number | CRO printout | Required |
| A3 | VAT number | - | Required |
| A4 | Registered address and site office address | - | Required |
| A5 | Years trading | - | Required |
| A6 | Directors, and named contact for health and safety | - | Required |
| A7 | Number of direct employees / labour-only subcontractors | - | Required |
| A8 | Trades offered (groundworks, drainage, ducting, etc.) | - | Required |

## B. Insurance

Certificates must name the insurer, policy number, limit of indemnity and expiry date.
Glenmara Construction Ltd to be noted as principal on EL and PL.

| # | Cover | Minimum limit | Required |
| --- | --- | --- | --- |
| B1 | Employer's liability | EUR 13,000,000 any one occurrence | Required |
| B2 | Public liability | EUR 13,000,000 any one occurrence | Required |
| B3 | Professional indemnity (where the package includes any design) | EUR 1,000,000 | Required |
| B4 | Contractor's all risks / plant cover | As appropriate | If applicable |

## C. Tax

| # | Question | Evidence | Required |
| --- | --- | --- | --- |
| C1 | Revenue tax clearance | Tax Clearance Access Number (TCAN) and expiry | Required |
| C2 | RCT status confirmed with Revenue | - | Required |

## D. Health and safety management

| # | Question | Evidence | Required |
| --- | --- | --- | --- |
| D1 | Safety Statement (Safety, Health and Welfare at Work Act 2005, s.20), signed and reviewed in the last 12 months | Copy | Required |
| D2 | Risk assessments and method statements (RAMS) for the works on this project | Copy, for Glenmara approval before start | Required |
| D3 | Every operative holds a current SOLAS Safe Pass | Card list with numbers and expiry dates | Required |
| D4 | Plant operators hold the CSCS card for the plant they operate (e.g. 180° excavator, site dumper); slingers/signallers hold the CSCS Slinger/Signaller card | Card list with numbers and expiry dates | Required |
| D5 | Manual handling training for all operatives | Training records | Required |
| D6 | Site induction completed for each operative before starting | Glenmara induction record | Required (on site) |
| D7 | Will you act as PSCS for any part of the works? | Answer and, if yes, evidence of competence | Answered by the subcontractor |

## E. Accident and incident history (last 3 years)

| # | Question | Required |
| --- | --- | --- |
| E1 | Number of accidents reported to the Health and Safety Authority (HSA) | Required |
| E2 | Number of lost-time injuries | Required |
| E3 | Any HSA improvement notices, prohibition notices or prosecutions, with details of what was done | Required |
| E4 | Declaration signed by a director | Required |

## F. Safety certification

| # | Question | Evidence | Required |
| --- | --- | --- | --- |
| F1 | Current Safe-T-Cert certification **or** registration on the Construction Industry Register Ireland (CIRI) | Certificate or registration number, and expiry | Required |
| F2 | ISO 45001 certification | Certificate | Optional |

## G. Quality and environment

| # | Question | Required |
| --- | --- | --- |
| G1 | Quality management system (e.g. ISO 9001) | Optional |
| G2 | Waste management and environmental procedures | Optional |

## H. References

| # | Question | Required |
| --- | --- | --- |
| H1 | Two references from main contractors you have worked for in the last 3 years: company, contact, phone or email, project, value | Required (2) |

## I. Employment

| # | Question | Required |
| --- | --- | --- |
| I1 | All employees have signed written terms of employment | Required |
| I2 | Pay and pension in line with the Construction Sectoral Employment Order (SEO), with evidence on request | Required on request |

## J. Declaration

Signed by a director confirming the information is true and complete, with date.

---

## How OpsEngine checks this form (SAMPLE mapping)

| Section | Checked automatically as | Notes |
| --- | --- | --- |
| A1-A5 | `company_details` | CRO, VAT, address, years trading. A6-A8 kept for the person filling the form |
| B1 | `employers_liability` (min EUR 13m) | |
| B2 | `public_liability` (min EUR 13m) | Stricter than the EUR 6.5m baseline |
| B3 | `professional_indemnity` (min EUR 1m) | |
| B4 | - | Not checked yet |
| C1 | `tax_clearance` | |
| C2 | - | Not checked yet (roadmap: RCT) |
| D1 | `safety_statement` | Reviewed every 12 months |
| D2 | `rams` per site | Drafts always go to a competent safety reviewer |
| D3 | `safe_pass` | |
| D4 | `cscs_excavator`, `cscs_dumper`, `cscs_slinger_signaller` | Applied by each worker's tasks |
| D5 | `manual_handling` | Only for workers on this contractor's sites |
| D6 | `site_induction` per site | |
| D7 | - | **Never answered by OpsEngine.** PSCS/PSDP roles need a competent person |
| E1-E4 | `accident_incident_history` | Renewed yearly; figures supplied and signed by the customer |
| F1 | `safety_certification` | Scheme must be Safe-T-Cert or CIRI |
| F2, G1-G2 | - | Optional, not checked |
| H1 | `trade_references` | Two referees |
| I1 | `written_terms` | |
| I2 | - | Not checked yet (roadmap: SEO pay/pension evidence) |
| J | - | Signed by the customer |
