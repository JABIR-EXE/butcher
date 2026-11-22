# How to present and pilot CutPilot

## Recommended commercial model: hosted SaaS

The target customer experience is one hosted CutPilot website with individual owner accounts and a private workspace for each butcher business. A butcher visits your domain, creates an owner account, verifies their email, signs in and imports their products and sales. They do not install Python, VS Code or SQLite.

**What exists in v1.8:** the project includes a working early account pilot in `CUTPILOT_MODE=saas`: owner registration, login/logout, email verification and password reset, plus a separate SQLite database file per business. Two-account data isolation has been tested. The `render.yaml` file is a starting deployment template, not an already-deployed public service.

**What is not ready:** there is no subscription checkout or recurring billing; no employee invitations or role system; no managed PostgreSQL database; no production-grade web framework/server review; no automatic backup/restore operation; and no formal security audit. The file-per-business SQLite approach is for an invite-only single-instance pilot, not a scalable commercial architecture.

The usual `CUTPILOT_MODE=local` remains useful for recording a demo with synthetic data. It is a single local workspace and is not the customer account mode. Do not expose the local server directly to the internet.

## 30-second butcher-owner pitch

“CutPilot works with the till you already have. You upload your product list and current stock once, then import a sales export from your till. CutPilot shows what sells, tracks stock, estimates revenue and product gross profit, warns about products that may run out, and prepares a suggested buying list. You review and approve every order. You keep your existing till and your usual suppliers.”

## Demonstration sequence

1. Start on the public CutPilot landing page and show Plans & pricing.
2. Explain that prices are proposed and checkout is not active.
3. In the local demo workspace, import the product catalogue and opening stock.
4. Import sample sales and show automatic column detection, manual mapping, preview and row validation.
5. Show sales/revenue and clearly label gross profit as an estimate based on recorded costs.
6. Show low-stock alerts and explain the forecast and lead-time assumptions behind a suggested purchase.
7. Show a draft supplier order and confirm that the owner approves it before sending.
8. For a separate account-flow recording, switch into local SaaS test mode and register two fake shop accounts. Show that the product records in one shop do not appear in the other.
9. Explain that the account flow is an early pilot foundation, not yet a public, production-hardened service.

## Proposed price experiments — not live billing

| Plan | Proposed price | Intended customer |
|---|---:|---|
| Starter | $29 / shop / month | One small shop using stock, imports, sales reporting and basic alerts |
| Professional | $59 / shop / month | Shop wanting forecasts, supplier workflows, waste tracking and the assistant |
| Multi-location | From $99 / month | Future multi-location business; functionality still needs development |

These are hypotheses, not validated market rates or active checkout prices. Ask owners what inventory work takes, what software they already use, the impact of stockouts/waste, and what value would justify a monthly fee. Do not promise specific savings until pilots measure them.

## Before a public commercial launch

- Deploy the hosted pilot only after an adult/business owner has configured hosting, domain and transactional email accounts.
- Keep signup invite-only while using the file-per-business SQLite pilot.
- Migrate to managed PostgreSQL and use tenant-level database security policies before scaling.
- Use a maintained production web framework/server and complete an independent security review.
- Add employee invitations and role permissions if those are part of the package.
- Add encrypted backups and restore tests, monitoring, private import storage, audit logs and data export/deletion.
- Publish legally reviewed terms, privacy notice, support, refund/cancellation and data-retention policies.
- Implement payment checkout, signed webhooks, subscription lifecycle handling and server-side plan entitlements before collecting subscriptions.

Until those gates are met, present CutPilot as a demonstration or supervised pilot. Do not take payment for access that is not yet provisioned and supported.
