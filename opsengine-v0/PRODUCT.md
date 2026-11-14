# OpsEngine - Product specification (from the founder)

This is the full scope of what OpsEngine should do. Build towards it; keep the boundaries in
CLAUDE.md. Status against this spec is tracked in the "Build status" table at the end.

OpsEngine is an AI-powered Compliance Operations Engine for construction businesses.

It doesn't just identify compliance problems, send reminders or generate reports. It actively
works to resolve issues by taking administrative action, coordinating people and external
providers, collecting evidence and maintaining compliance records.

## 1. Compliance Monitoring
- Continuously monitors a company's compliance status.
- Tracks relevant legal and regulatory requirements.
- Identifies missing, expired or incomplete documentation.
- Monitors employee, subcontractor and site compliance.
- Tracks upcoming renewals, inspections and deadlines.
- Flags potential compliance risks.
- Identifies gaps and areas requiring corrective action.

## 2. Document Management
- Collects and organises compliance documents.
- Reviews safety statements and risk assessments.
- Checks RAMS (Risk Assessments and Method Statements) for missing information.
- Identifies inconsistencies and documentation gaps.
- Prepares and updates documents for human review.
- Requests missing documents from employees and subcontractors.
- Tracks document versions and expiry dates.
- Maintains organised digital compliance records.

## 3. Automated Problem Resolution
- Creates an action whenever a compliance issue is identified.
- Determines what needs to happen to resolve each issue.
- Automatically completes administrative tasks where permitted.
- Requests missing information.
- Contacts relevant people and follows up.
- Coordinates corrective actions.
- Arranges required services and appointments.
- Tracks every issue until it has been resolved and verified.
- Escalates problems that require human judgement or approval.

## 4. Training and Certification Coordination
- Tracks employee training requirements.
- Identifies expired or missing certifications.
- Finds suitable training providers.
- Requests quotes and compares providers.
- Arranges training sessions with approval.
- Tracks attendance and completion evidence.
- Updates employee training records.
- Monitors upcoming training renewals.

## 5. Contractor and Subcontractor Management
- Collects subcontractor compliance documentation.
- Checks insurance certificates and expiry dates.
- Tracks required qualifications and training records.
- Identifies missing or expired documentation.
- Requests outstanding information.
- Maintains subcontractor compliance profiles.
- Monitors subcontractor documentation across projects.
- Flags subcontractors who do not meet defined requirements.

## 6. Inspection and Maintenance Coordination
- Tracks required inspections and servicing.
- Identifies overdue inspections and maintenance.
- Finds suitable qualified inspectors and service providers.
- Requests and compares quotes.
- Books approved providers.
- Coordinates appointments.
- Follows up on incomplete work.
- Collects inspection reports and certificates.
- Tracks corrective actions resulting from inspections.

## 7. Provider Network Management
- Maintains a network of vetted external providers.
- Stores provider qualifications, insurance and service areas.
- Matches businesses with appropriate providers.
- Checks provider credentials and their validity.
- Requests availability and pricing.
- Coordinates bookings and service delivery.
- Tracks provider performance and completed work.
- Maintains provider records and documentation.

Potential provider categories: health and safety consultants; safety trainers; fire safety
inspectors; electrical inspection companies; equipment inspection providers; occupational
health providers; insurance brokers; specialist compliance consultants.

## 8. Corrective Action Management
- Records safety and compliance issues.
- Assigns responsibility for corrective actions.
- Establishes deadlines.
- Sends follow-up requests.
- Tracks progress.
- Collects evidence of completed corrective work.
- Escalates unresolved issues.
- Maintains a record of how each issue was addressed.
- Verifies that required evidence has been received before closing an action.

## 9. Communication and Administration
- Sends emails and notifications.
- Requests documents and missing information.
- Follows up with employees, subcontractors and providers.
- Prepares reports and summaries.
- Schedules appointments.
- Maintains communication histories.
- Requests customer approval before consequential actions.
- Records approvals and decisions.
- Automates repetitive administrative workflows.

## 10. Reporting and Audit Trails
- Maintains a central compliance record.
- Records every issue identified.
- Tracks actions taken by AI and humans.
- Stores supporting evidence and certificates.
- Records approvals and decisions.
- Produces compliance reports.
- Provides an overview of outstanding and resolved issues.
- Maintains a history of changes and completed actions.
- Makes supporting records accessible for audits and reviews.

## 11. Continuous Improvement
- Identifies recurring compliance problems.
- Highlights patterns across projects and sites.
- Identifies frequently missing documents.
- Tracks provider performance.
- Measures how quickly issues are resolved.
- Identifies opportunities to prevent recurring problems.
- Uses historical operational data to improve workflows.

## The core workflow
1. **IDENTIFY** - find compliance gaps, missing documents, expired certifications and potential problems.
2. **DETERMINE** - work out what needs to happen to resolve each issue.
3. **EXECUTE** - take action, coordinate people, request information and arrange required services.
4. **VERIFY** - collect and check evidence that the required work was completed.
5. **MAINTAIN** - update records, close verified actions and continuously monitor compliance.

(In code: `scan` = identify, playbooks = determine, `advance` = execute, `verify` = verify,
records + audit + daily run = maintain.)

## Operating model
- **AI:** monitoring, document processing, issue identification, administrative tasks,
  communication, coordination and follow-ups.
- **External providers:** physical inspections, specialist services, training and repairs.
- **Human oversight:** exceptions, professional judgement, sensitive decisions and approvals.
- **Customer:** keeps control over consequential decisions, spending and authorisations.

The business should become more automated as it grows. Key measure: **human minutes per
customer falling** while revenue per customer holds or rises.

## The central promise
Find the problem. Work out the solution. Take action. Coordinate the people needed. Verify the
evidence. Keep it compliant.

Qualified professionals remain responsible for physical inspections, specialist judgements and
legally required certifications. OpsEngine coordinates these activities and maintains the
supporting evidence without falsely claiming to certify compliance itself.

---

## Build status

See **`AUDIT.md`** (14 Nov 2026) for the honest, capability-by-capability status. In short: the
rules and workflow engine is real and tested on SAMPLE data, but everything that touches the
outside world (sending messages, reading real documents with AI, real providers, quotes,
bookings, approvals with identity) is simulated or blocked, and there is no security layer yet.
An earlier version of this section marked every capability "Built"; that overstated it.
