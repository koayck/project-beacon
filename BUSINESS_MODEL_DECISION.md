# Business Model Decision

## Final Decision
Project Beacon will use a B2G-only enterprise model with:

1. Fixed annual platform licensing.
2. Separate AI usage billing.
3. Paid support and professional services.
4. Module and fleet expansion upsells.

This model is optimized for public sector procurement, long contract cycles, security requirements, and mission-critical reliability.

## Revenue Model

### 1) Platform License (Fixed)
- Annual license per agency site, command center, or regional control unit.
- Fleet tiers by maximum active drones (for example: 5, 20, 50, 200).
- Includes core command platform, updates, and standard maintenance.

### 2) AI Usage (Variable, Separate from Platform)
- Default model: agency pays AI usage.
- BYO key option (recommended default): agency provides API key; platform billed separately.
- Managed AI option: pass-through AI charges plus management margin.
- Future offline option: no token billing; agency pays local compute infrastructure.

### 3) Support and Services
- Support tiers: standard and mission-critical (24/7, incident response, priority patching, emergency escalation).
- Professional services: deployment, integration, hardening, operator training, and annual recertification.

### 4) Module Upsells
- Thermal SAR module.
- Sweep and route optimization.
- Supply and logistics workflows.
- Compliance and reporting package.

## B2G Go-To-Market Plan

### Target Buyers
- Target agencies in emergency response, civil defense, and public safety.
- Secondary targets: defense-adjacent public units and national resilience programs.

### Sales Motion
1. Win 1-2 B2G pilots for trust and references.
2. Convert paid pilots into 2-3 year framework contracts.
3. Expand contracts by adding more sites, fleet capacity, SLA tier, and modules.
4. Use mission outcomes and compliance evidence to drive renewals.

## Packaging (Simple)

### Agency Starter
- BYO key.
- Core platform.
- Standard support.

### Agency Operational
- Higher fleet tier.
- Advanced mission modules.
- Priority support.
- Mandatory operator training bundle.

### Sovereign Mission-Critical
- Multi-site licensing.
- Compliance package.
- Mission-critical SLA.
- Optional on-prem or offline deployment.
- Dedicated support channel and incident commander access.

## Behavior Consistency Policy for BYO Keys
Because BYO keys can introduce model/runtime variance, enforce a certified profile:

1. Pin approved model version(s) and generation parameters.
2. Version prompts and tool schemas.
3. Run conformance tests before production enablement.
4. Apply hard safety guardrails in code (not only in model behavior).

Certification tiers:
- Certified profile: behavior guarantee and full support.
- Best-effort profile: broader model freedom with reduced guarantees.

## Contract Policy Defaults
1. Platform fee is fixed and separate from AI usage.
2. AI charges are agency responsibility unless managed-AI is purchased.
3. Managed-AI plans include budget caps, alerts, and throttling.
4. SLA terms differ by deployment mode (BYO key, managed cloud AI, offline).
5. Procurement language includes audit logging, data residency, and continuity operations terms.

## Near-Term Execution
1. Launch with BYO key as default offer.
2. Add managed-AI as upsell for agencies that want lower operational overhead.
3. Keep offline deployment as premium sovereign option.
4. Prioritize paid pilots with explicit mission KPIs and procurement conversion criteria.
