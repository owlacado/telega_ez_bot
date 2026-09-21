# Pilot blocker matrix

Stage 10 reviewed all 35 entries in `TECH_DEBT.md`. This matrix does not replace that
register. It maps each item to the one-technician pilot decision and records the Stage 10
disposition. `RESOLVED` means the full debt acceptance condition is locally proven. `PARTIAL`
means useful local risk reduction exists while the original item remains open.

Classifications for open work:

- **A — FIX NOW LOCALLY:** the complete item, or a clearly bounded part, can be proven locally.
- **B — NEEDS DEDICATED TEST PROVIDER ACCEPTANCE:** real Google or Telegram behavior is needed.
- **C — NEEDS PRODUCT DECISION:** policy, risk ownership, or business scope must be approved.
- **D — PRODUCTION-ONLY:** required before production, not the controlled internal pilot.
- **E — LATER SCALE:** explicitly deferred until measured scale warrants it.

| ID     | Title                                 | Severity | Stage 9 status | Pilot blocker | Production blocker | Live provider | Local proof possible | Class | Dependencies                                        | Current disposition                                    |
| ------ | ------------------------------------- | -------: | -------------- | ------------- | ------------------ | ------------- | -------------------- | ----- | --------------------------------------------------- | ------------------------------------------------------ |
| TD-001 | Identity/navigation                   |     HIGH | RESOLVED       | No            | No                 | No            | Yes                  | —     | Resource identity tests                             | Retain RESOLVED                                        |
| TD-002 | Permanent deletion                    |     HIGH | RESOLVED       | No            | No                 | No            | Yes                  | —     | Version guard tests                                 | Retain RESOLVED                                        |
| TD-003 | Database integrity                    |   MEDIUM | RESOLVED       | No            | No                 | No            | Yes                  | —     | PostgreSQL constraints                              | Retain RESOLVED                                        |
| TD-004 | Transactions/response                 |   MEDIUM | RESOLVED       | No            | No                 | No            | Yes                  | —     | Transaction regressions                             | Retain RESOLVED                                        |
| TD-005 | Input validation                      |   MEDIUM | RESOLVED       | No            | No                 | No            | Yes                  | —     | API validation tests                                | Retain RESOLVED                                        |
| TD-006 | Frontend mutations                    |   MEDIUM | RESOLVED       | No            | No                 | No            | Yes                  | —     | UI mutation tests                                   | Retain RESOLVED                                        |
| TD-007 | Failure recovery                      |   MEDIUM | RESOLVED       | No            | No                 | No            | Yes                  | —     | DB/error tests                                      | Retain RESOLVED                                        |
| TD-008 | Accessibility/layout                  |   MEDIUM | RESOLVED       | No            | No                 | No            | Yes                  | —     | Browser/axe tests                                   | Retain RESOLVED                                        |
| TD-009 | Authentication/authorization          |     HIGH | RESOLVED       | No            | No                 | No            | Yes                  | —     | Auth/CSRF/rate tests                                | Retain RESOLVED                                        |
| TD-010 | Deletion audit/accountability         |     HIGH | OPEN           | No            | Yes                | No            | Yes                  | D     | Production deletion/audit policy                    | TEST control implemented; production policy OPEN       |
| TD-011 | Sensitive data protection             |     HIGH | OPEN           | No            | Yes                | No            | Yes                  | D     | Production collection/encryption policy             | TEST collection disabled; production policy OPEN       |
| TD-012 | Deployment/credentials/origins        |   MEDIUM | OPEN           | Yes           | Yes                | No            | Partly               | C     | TLS/proxy/secret store and origin approval          | PARTIAL: fail-closed config/preflight added            |
| TD-013 | Concurrent profile editing            |   MEDIUM | OPEN           | No            | No                 | No            | Yes                  | —     | Database-owned version and dependent-state boundary | RESOLVED by `fca609190001` and direct DB tests          |
| TD-014 | Provider state invariants             |   MEDIUM | OPEN           | Yes           | Yes                | No            | Yes                  | A     | State policy and additive migration                 | RESOLVED by database CHECK constraints                 |
| TD-015 | Scaling/response size                 |   MEDIUM | OPEN           | No            | Eventually         | No            | Partly               | E     | Defined fleet/history targets                       | OPEN; later scale                                      |
| TD-016 | Durability/operations                 |   MEDIUM | OPEN           | No            | Yes                | No            | Partly               | D     | RPO/RTO, off-host encrypted retention               | PARTIAL: backup tool and isolated restore drill        |
| TD-017 | Observability/timeouts                |   MEDIUM | OPEN           | Yes           | Yes                | No            | Partly               | A     | Alert routing and deployment budgets                | PARTIAL: aggregate health, queue counts, version       |
| TD-018 | External profile images               |   MEDIUM | OPEN           | No            | No                 | No            | Yes                  | —     | Initials-only API/UI/DB/CSP enforcement             | RESOLVED; external images disabled                     |
| TD-019 | Runtime contracts                     |      LOW | OPEN           | No            | Yes                | No            | Yes                  | D     | Independently deployed-client boundary              | OPEN; production-only                                  |
| TD-020 | Accessibility coverage                |      LOW | OPEN           | No            | Yes                | No            | No                   | D     | Manual AT/cross-browser acceptance                  | OPEN; production-only                                  |
| TD-021 | Search consistency                    |   MEDIUM | RESOLVED       | No            | No                 | No            | Yes                  | —     | API/UI search regressions                           | Retain RESOLVED                                        |
| TD-022 | Telegram membership/live acceptance   |   MEDIUM | OPEN           | Yes           | Yes                | Yes           | No                   | B     | Dedicated TEST bot/private/group                    | LIVE TEST REQUIRED                                     |
| TD-023 | Telegram abuse/retention              |   MEDIUM | OPEN           | No            | No                 | No            | Yes                  | —     | Admission budgets and offset-safe retention         | RESOLVED; configurable approved limits enforced        |
| TD-024 | Telegram metadata freshness           |      LOW | OPEN           | No            | Eventually         | Yes           | No                   | E     | Operational demand                                  | OPEN; later scale                                      |
| TD-025 | Google credential operations          |   MEDIUM | OPEN           | Yes           | Yes                | Partly        | Partly               | C     | Key custody, rotation and revocation ownership      | PARTIAL: recovery/incident procedures documented       |
| TD-026 | Google budgets/OAuth retention        |   MEDIUM | OPEN           | No            | No                 | No            | Yes                  | —     | Manager/global budgets and metadata retention       | RESOLVED; provider retry policy preserved              |
| TD-027 | Google OAuth/Calendar live acceptance |   MEDIUM | OPEN           | Yes           | Yes                | Yes           | No                   | B     | Dedicated TEST Google project/account               | LIVE TEST REQUIRED                                     |
| TD-028 | Combined schedule acceptance          |   MEDIUM | OPEN           | Yes           | Yes                | Yes           | No                   | B     | TD-022, TD-027 and schedule TEST run                | LIVE TEST REQUIRED                                     |
| TD-029 | Schedule key/worker operations        |   MEDIUM | OPEN           | Yes           | Yes                | Partly        | Partly               | C     | Key custody, monitoring and capacity ownership      | PARTIAL: health, shutdown and runbooks                 |
| TD-030 | Work Report/Expense TEST acceptance   |   MEDIUM | OPEN           | Yes           | Yes                | Yes           | No                   | B     | TEST mobile Telegram and HTTPS                      | LIVE TEST REQUIRED                                     |
| TD-031 | Business/form retention policy        |   MEDIUM | OPEN           | No            | Yes                | No            | Yes                  | D     | Final production legal/business policy              | TEST policy implemented; production policy OPEN        |
| TD-032 | Long XLSX cell display                |      LOW | OPEN           | No            | Eventually         | No            | Partly               | E     | Approved presentation policy                        | OPEN; later scale                                      |
| TD-033 | Real Google Sheets acceptance         |   MEDIUM | OPEN           | Yes           | Yes                | Yes           | No                   | B     | Dedicated TEST spreadsheet/account                  | LIVE TEST REQUIRED                                     |
| TD-034 | Very-large-fleet Sheets limits        |   MEDIUM | OPEN           | No            | Yes                | Yes           | No                   | D     | Real quota/latency/grid measurements                | OPEN; production-only                                  |
| TD-035 | Google row-height approximation       |      LOW | OPEN           | No            | Eventually         | Yes           | No                   | E     | Supported-client visual acceptance                  | OPEN; later scale                                      |

The pre-Stage-10 pilot blocker set was TD-010, TD-011, TD-012, TD-013, TD-014,
TD-017, TD-018, TD-022, TD-023, TD-025, TD-026, TD-027, TD-028, TD-029, TD-030,
TD-031, and TD-033. Stage 10 locally resolves TD-014 and partially remediates seven other
items. The approved policy implementation removes TD-010, TD-011, TD-013, TD-018, TD-023, TD-026,
and TD-031 from the controlled TEST-pilot blocker set. TD-010, TD-011, and TD-031 remain production
policy obligations. The nine remaining pilot blockers are TD-012, TD-017, TD-022, TD-025, TD-027,
TD-028, TD-029, TD-030, and TD-033.

**PILOT READY: NO.** Four deployment/operations gates and five live TEST-provider gates remain.

## Pilot blocker resolution pass

The post-audit resolution pass adds decision-ready and operator-ready evidence without recording an
approval or contacting a provider:

| Group                      | IDs                                            | Local result                                                                                                                                                                                              | What still blocks closure                                                                                                                                                     |
| -------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Product/security decisions | TD-010, TD-011, TD-018, TD-023, TD-026, TD-031 | Exact questions, options, consequences, recommended one-technician defaults, and approval-dependent changes are recorded in `PILOT_POLICY_DECISIONS.md`.                                                  | Named product/security/records owners must approve an option; approved code and policy work must then be implemented and verified.                                            |
| Operational setup          | TD-012, TD-017, TD-025, TD-029                 | Concrete proxy boundary, existing admission budgets, monitoring exit status, alert thresholds, managed-secret recovery order, and no-network synthetic key rehearsal are documented and locally verified. | The selected environment must install and record TLS/proxy, secret store, alert routing/scheduling, deployed synthetic recovery, and provider-dependent revocation/reconnect. |
| Version boundary           | TD-013                                         | A narrow database-owned `record_version` and dependent-state trigger boundary is ready for approval.                                                                                                      | Approval, additive migration, API/client change, and direct-database concurrency evidence remain.                                                                             |
| Live TEST acceptance       | TD-022, TD-027, TD-028, TD-030, TD-033         | `PILOT_LIVE_ACCEPTANCE_PLAN.md` consolidates exact resources, order, stop criteria, and evidence.                                                                                                         | Every row still requires real dedicated TEST Telegram/Google execution and reviewed sanitized evidence.                                                                       |

## Approved policy implementation

| Group | IDs | Result | Remaining gate |
| ----- | --- | ------ | -------------- |
| Resolved locally | TD-013, TD-018, TD-023, TD-026 | Additive database versioning through `fda609200001`, initials-only profiles, crash-safe database-backed admission, and bounded metadata cleanup are independently audited and tested. | None for the stated debt acceptance condition. |
| Moved out of TEST pilot | TD-010, TD-011, TD-031 | Permanent deletion and sensitive collection are disabled; pilot business evidence has no automatic deletion/anonymization and backups use a rolling 30-day policy. | Final production legal/business/security policy remains open. |
| Operational setup | TD-012, TD-017, TD-025, TD-029 | Local docs, preflight, monitors, recovery tooling, thresholds, and application budgets are ready. | Install and evidence the selected TEST deployment's proxy/TLS, secret store, alert routing, scheduled monitoring, and deployed synthetic recovery. |
| Live TEST acceptance | TD-022, TD-027, TD-028, TD-030, TD-033 | No provider was contacted and every live row remains open. | Execute `PILOT_LIVE_ACCEPTANCE_PLAN.md` with dedicated fictional TEST resources. |

The register is now 15 RESOLVED and 20 OPEN. Nine items remain controlled TEST-pilot blockers.
**PILOT READY: NO.**

## Independent implementation audit

`AUDIT_PILOT_POLICY_IMPLEMENTATION.md` records the adversarial audit. It fixed a Telegram
crash/retry loss path, added durable callback/concurrent dedupe, and narrowed `record_version` to the
approved effective-state boundary with immutable technician identity. Nine of nine policy mutations
were detected, the full backend/frontend/migration gates passed, generated contracts were byte-stable,
and the normal database fingerprint was unchanged after the additive migration. No live provider was
contacted. The remaining blocker set and readiness decision are unchanged.
