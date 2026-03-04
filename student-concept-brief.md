# Malomatia Gov-Service Triage AI

## Student Concept Brief

### 1) Challenge and Market Relevance
Government service requests often arrive through multiple channels, including call centers, email, web forms, and chat. In Malomatia-supported public-service environments, this intake is frequently multilingual, especially Arabic and English, and relies heavily on manual triage by staff. Manual triage creates three systemic problems: slow routing, inconsistent classification, and missed service-level targets.

When an incoming request is placed into the wrong queue, the case can circulate between teams before reaching the right department. That delay reduces first-response speed and increases backlogs. At scale, this harms public trust because citizens experience uncertainty and repeated follow-ups for simple requests. For operations teams, the same issue creates avoidable rework and higher workload pressure.

The market need is clear: a structured, explainable AI triage layer that can process multilingual service requests, identify intent and urgency quickly, and route each case to the correct department with transparent logic.

### 2) Why This Niche Matters in Qatar/GCC Public Services
This is not a generic chatbot idea. It is an operations-focused AI system for public-service triage, designed for Arabic-first environments with bilingual reality. In Qatar and the GCC, digital government adoption is high, but operational consistency across channels is still a challenge. A solution that improves routing quality and response speed has immediate value because it affects both citizen satisfaction and internal efficiency.

This niche is strong for competition and portfolio outcomes for four reasons:
- It solves a real, costly bottleneck in day-to-day public-service delivery.
- It requires intentional AI integration, not superficial automation.
- It can be built as an MVP in one sprint cycle with measurable metrics.
- It has clear expansion potential into multiple government service domains.

### 3) Solution Overview
**Malomatia Gov-Service Triage AI** is an intelligent intake and routing system that supports service operations teams by automating the highest-friction parts of case triage while keeping humans in control of critical decisions.

Core flow:
1. A citizen submits a request in Arabic or English.
2. The system detects language and classifies request intent.
3. The system assigns urgency based on request context and policy rules.
4. The routing engine predicts the best destination department.
5. The platform shows an explanation trace for the recommendation.
6. Staff can approve, override, or escalate using defined thresholds.

This creates faster, more consistent triage with accountable decisioning.

### 4) AI Architecture (Mapped to Core Components)
The architecture is built around six components from the locked ConceptPack:

- **Bilingual intent classification**: A classification model identifies request category from Arabic/English text, including normalized synonyms and common phrasing variations.
- **Urgency detection**: A scoring model estimates urgency using textual signals (time sensitivity, risk indicators, blocked-service language).
- **Department routing prediction**: A routing model maps request + urgency to the most likely responsible department.
- **Policy-grounded decision rules**: Rule constraints enforce service policy boundaries so model outputs do not violate operational protocols.
- **Explainable routing trace**: The system surfaces why a case was routed, including key indicators and policy checks used.
- **Human-in-the-loop escalation**: High-risk or low-confidence cases are escalated to staff for final decision.

At least four explicit AI decisions are operationally justified here:
- Intent decision reduces misclassification.
- Urgency decision prioritizes response allocation.
- Routing decision reduces transfer loops.
- Escalation decision protects quality in uncertain cases.

### 5) MVP Scope (Mapped to Features)
The MVP is intentionally scoped for a 4-week student sprint:

- Arabic/English request classifier
- Urgency scoring pipeline
- Routing engine for department assignment
- Decision explanation UI panel
- Manual override controls for agents
- Escalation threshold configuration

MVP boundary conditions:
- Start with a limited service taxonomy (for example 8-12 request classes).
- Support a fixed set of participating departments.
- Use confidence thresholds to route ambiguous cases to human review.

This keeps implementation feasible while demonstrating meaningful impact.

### 6) KPI Model and Success Measurement
KPIs are tied directly to operations outcomes and competition judging clarity:

- **Triage accuracy**: Percentage of requests correctly classified.
- **Correct routing rate**: Percentage routed to the right department on first attempt.
- **First-response time reduction**: Time improvement versus baseline triage process.
- **Escalation precision**: Proportion of escalated cases that truly needed human intervention.
- **SLA compliance improvement**: Change in on-time handling relative to baseline.

Instrumentation approach:
- Log prediction, decision trace, staff action, and final case destination.
- Compare pre-MVP baseline and post-MVP pilot values.
- Use dashboard snapshots in final demo to show quantified improvement.

### 7) Risk, Governance, and Controls
The solution includes default-on governance controls:

- **Arabic-first model training** to prevent quality drop in local language inputs.
- **Privacy-safe dataset practices** (data minimization, de-identification, secure storage).
- **Audit logging** for every model recommendation and human override.
- **Human override mechanisms** for all critical and uncertain cases.
- **Policy constraint checks** before final routing output is accepted.

These controls make the system deployable in sensitive public-service contexts, not just demo-friendly.

### 8) Demo Walkthrough (Mapped to Script)
The demo should follow this exact narrative:
1. Citizen submits an Arabic request.
2. AI classifies intent.
3. AI detects urgency.
4. System routes case to department.
5. Explanation trace is shown to staff.
6. Staff performs override to show control path.
7. Dashboard displays KPI improvement versus baseline.

This sequence proves technical depth, practical usability, and measurable value in one end-to-end story.

### 9) Portfolio and Expansion Value
This project is portfolio-ready because it demonstrates applied AI, domain-specific design, responsible governance, and measurable operational impact. It can later be expanded to:
- Additional service channels (voice transcript, mobile app submissions).
- More departments and service categories.
- Retrieval-augmented policy references for richer explainability.
- Cross-agency triage interoperability.

As a Sprint submission, it is both realistic and strategically differentiated: Arabic-first, explainable, and built around real public-service constraints.
