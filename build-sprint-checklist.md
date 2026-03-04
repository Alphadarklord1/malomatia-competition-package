# Malomatia Gov-Service Triage AI

## Build Sprint Checklist (4 Weeks)

### Week 1: Data, Taxonomy, Baseline Classifier
- Define request taxonomy (8-12 service categories).
- Collect and prepare privacy-safe bilingual sample dataset.
- Apply Arabic-first preprocessing and labeling standards.
- Build baseline Arabic/English intent classifier.
- Validate class balance and initial precision/recall.
- Set up logging schema for predictions and agent actions.

**Week 1 Exit Criteria**
- Working bilingual classifier with baseline metrics.
- Approved taxonomy and dataset quality checklist.
- Logging foundation ready for KPI tracking.

### Week 2: Urgency, Routing, Policy Rules
- Implement urgency scoring model.
- Build department routing prediction component.
- Define policy-grounded rule constraints.
- Add confidence scoring for low-certainty detection.
- Integrate intent + urgency + routing in one inference flow.

**Week 2 Exit Criteria**
- End-to-end triage engine produces route recommendations.
- Policy checks run before output is finalized.
- Low-confidence cases are flaggable for review.

### Week 3: Explanation UI, Override, Escalation
- Build decision explanation UI panel (intent, urgency, route rationale).
- Implement manual override controls for staff.
- Configure escalation thresholds for risk/uncertainty.
- Add full audit logs for recommendations and overrides.
- Run internal agent usability review and adjust UI wording.

**Week 3 Exit Criteria**
- Staff can see why routing was recommended.
- Staff can override and escalate reliably.
- Audit trail captures all critical decisions.

### Week 4: KPI Instrumentation, Demo, Judging Narrative
- Compute KPI baseline vs pilot values:
  - Triage accuracy
  - Correct routing rate
  - First-response time reduction
  - Escalation precision
  - SLA compliance improvement
- Build simple KPI dashboard views for demo.
- Rehearse 7-step demo script from Arabic request to KPI impact.
- Prepare judging narrative: novelty, feasibility, impact, governance.

**Week 4 Exit Criteria**
- Quantified KPI improvements are visible.
- Demo is stable and repeatable.
- Final pitch clearly maps technical decisions to business/public-service value.

## Final Demo Readiness Checklist
- Arabic request example included.
- Intent classification shown live.
- Urgency scoring shown live.
- Routing outcome shown live.
- Explanation trace shown clearly.
- Override path demonstrated.
- KPI improvement evidence displayed.

## Governance and Risk Controls (Must-Have)
- Arabic-first model behavior validated.
- Privacy-safe dataset confirmed.
- Policy constraints enabled in routing flow.
- Human override available for critical cases.
- Audit logging enabled end-to-end.

## Submission Evidence Pack
- Architecture diagram (intent, urgency, routing, policy, HITL).
- KPI table: baseline vs pilot.
- 2-3 failure-case examples and safe handling.
- Short note on rollout path for Qatar/GCC public-service contexts.
