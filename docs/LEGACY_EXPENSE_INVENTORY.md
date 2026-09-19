# Legacy expense inventory and parity

Authoritative reference (read only): `C:/Users/rasha/OneDrive/Documents/ChatGPT/ez_telega_bot`.
No provider calls or legacy mutations were made. `C:/HVAC_TECH_CODEX` was not used.

The latest reference already replaced the older per-technician Google Forms with a Django/PostgreSQL expense workflow. Searches of source/docs/templates found no expense form URL mappings or Apps Script expense intake. Historical infrastructure is not evidence for current field semantics.

| Behavior           | Evidence in reference                                                                                                         | Stage 6 decision                                                                                                                            |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Telegram entry     | `telegram_integration/bot.py`: `expenses_command`, `_start_expense`, `expense:new`; `telegram_integration/tests/test_menu.py` | PRESERVE private Expenses action, verify actor using current binding                                                                        |
| Private/group      | `_private_command_technician` requires private chat ID = actor ID                                                             | PRESERVE private only; group initiation deferred                                                                                            |
| Identity           | bot active technician lookup and session technician FK                                                                        | IMPROVE binding generation, revocation and audited shared capability                                                                        |
| Exact fields       | `expenses/forms.py`, `expenses/serializers.py`, `expenses/templates/expenses/technician_expense_form.html`                    | PRESERVE required expense_type and amount, optional note; read-only date/technician                                                         |
| Money              | `expenses/models.py`, `expenses/tests/test_domain.py::test_zero_is_explicitly_valid_and_negative_is_rejected`                 | PRESERVE Decimal(12,2), zero accepted, negative rejected; IMPROVE strict string precision/range, no silent rounding                         |
| Type               | `expenses/services.py::normalize_expense_type`, `expenses/migrations/0004_free_text_expense_type.py`                          | PRESERVE required trimmed case-preserving free text <=100; reject markup/controls; no invented enum/suggestions                             |
| Note               | forms/services optional trimmed multiline text                                                                                | PRESERVE optional plain text; IMPROVE 4000-character bound, control normalization                                                           |
| Date               | `expenses/services.py::technician_local_today`, `submit_expense`; domain local-date test                                      | PRESERVE server submission-time date in explicit technician IANA timezone; browser cannot submit date                                       |
| Timezone           | `technicians/models.py::timezone`; form shows technician timezone                                                             | IMPROVE explicit nullable configuration in Hub; no fallback; block issuance/submission until set, snapshot zone/date on accepted submission |
| Receipt/photo/link | `docs/EXPENSES.md`; schema absence test in `expenses/tests/test_domain.py`                                                    | PRESERVE no application receipt field; photos remain external in work group; uploads/references DEFERRED                                    |
| Duplicate          | domain replay and fresh-new-session tests                                                                                     | PRESERVE distinct real expenses per new session; IMPROVE changed replay returns conflict                                                    |
| Edits              | `correct_expense`, `void_expense`, edit form session                                                                          | DEFER corrections/voiding/UI; immutable revision 1 and latest selector prepared                                                             |
| Confirmation       | `expenses/web_views.py`, success template; `expenses/delivery.py`, acknowledgement hooks                                      | PRESERVE browser success receipt; DEFER Telegram group expense notifications and acknowledgement delivery                                   |
| Google Forms       | latest secure Django form has no Google URL                                                                                   | REMOVE old per-tech Forms and mapping requirements                                                                                          |
| Sheets             | `accounting/calculation.py` reads canonical ACTIVE expenses; `accounting/mirror.py` projects accounting                       | DEFER Sheets output; no intake dependency                                                                                                   |
| Discord            | `docs/LEGACY_MIGRATION_PRINCIPLES.md` explicitly removes Discord                                                              | REMOVE, no rebuild                                                                                                                          |
| Accounting         | `expenses/daily_report.py`, `accounting/calculation.py`: active current rows and Decimal sum, weekly free-text type           | PRESERVE raw facts; DEFER formulas, daily/weekly reports, payout and mirrors                                                                |
| Reimbursement      | no approval/reimbursement/payment fields in expense model/forms                                                               | Do not invent workflow                                                                                                                      |
| Validation         | forms/services/domain tests                                                                                                   | IMPROVE consistent API/DB constraints and bounded requests                                                                                  |
| Managers           | management expense list/detail templates, web_views, correction/void capabilities                                             | PRESERVE read-only list/detail; corrections/void/retry out of scope                                                                         |
| Manual operations  | legacy feature gate, timezone, Telegram group configuration and delivery retry                                                | Hub manager timezone/binding setup retained; no mapping rows or form cloning                                                                |

## Source set inspected

`expenses/{models,services,forms,serializers,web_views,delivery,daily_report}.py`,
`expenses/tests/{test_domain,test_web_api_telegram}.py`,
`expenses/migrations/0004_free_text_expense_type.py`, expense technician and management templates,
`telegram_integration/bot.py`, `telegram_integration/tests/test_menu.py`, `technicians/models.py`,
`accounting/{calculation,mirror}.py`, `docs/{EXPENSES,LEGACY_MIGRATION_PRINCIPLES}.md`.

No binary/reference control is claimed or accepted. Receipt/service-contract is a separate workflow and is excluded.
