# CutPilot hosted pilot — account setup and launch checklist (v1.8)

## What is implemented in this release

- Public website at `/` and public pricing page at `/pricing`.
- Sign-up at `/signup`, sign-in at `/login`, sign-out from the app, email verification, password-reset request and password update.
- One owner account creates one butcher-business workspace.
- Each organization gets its own SQLite database file under `CUTPILOT_DATA_DIR/tenants/`. The account database stores users, organizations, memberships, sessions and one-time email tokens.
- API routes under `/api/` (except health/config/auth-me) require a valid HttpOnly session in hosted mode.
- The request thread selects the authenticated organization's database; the browser cannot choose another tenant database path.
- Passwords are hashed using Python's scrypt. Session tokens are random, stored as SHA-256 hashes and expire after the configured number of days.
- Login and registration have basic per-IP rate limits. State-changing requests reject a mismatched Origin header when one is supplied. Session cookies use HttpOnly, SameSite=Lax and Secure when configured.
- Pricing cards link to signup with the chosen plan preselected.

## Important limitations — do not skip

This is an **invite-only hosted pilot foundation**, not a completed production SaaS platform.

- Checkout/recurring billing is not integrated. Account creation does not charge money. The displayed $29 / $59 / $99+ are proposed prices, not active purchasable subscriptions.
- Email verification and password reset require an SMTP service and correct environment variables. Public sign-up is blocked when verification is required but SMTP or the public base URL is missing.
- There is one owner account per workspace in this release. Employee invitations, roles beyond owner, account deletion and self-service organization switching are not implemented yet.
- Each business is physically separated into its own SQLite file. This is a small beta approach for one hosted application instance with persistent storage. It is **not horizontally scalable** and not a substitute for managed PostgreSQL at commercial scale.
- The current server is Python's standard-library `ThreadingHTTPServer`. Before accepting real customer data or charging customers, move to a maintained production web framework/server, add automated security review, backups/restore drills, monitoring, customer support, terms, privacy notice and legal review.
- No hosting provider account, domain, SMTP account or billing-provider account is created by this project. You must configure those separately.

## Test account creation on your own computer

This runs the **SaaS account mode locally** with email verification disabled only for local development. It creates a separate `saas-test-data` folder; it does not overwrite the normal local demo database.

PowerShell, from the inner `cutpilot` folder:

```powershell
$env:CUTPILOT_MODE = "saas"
$env:CUTPILOT_HOST = "127.0.0.1"
$env:CUTPILOT_PORT = "8765"
$env:CUTPILOT_DATA_DIR = "$PWD\saas-test-data"
$env:CUTPILOT_REQUIRE_EMAIL_VERIFICATION = "0"
$env:CUTPILOT_COOKIE_SECURE = "0"
py app.py
```

Then open:

- Public home: `http://127.0.0.1:8765/`
- Public plans: `http://127.0.0.1:8765/pricing`
- Create a butcher account: `http://127.0.0.1:8765/signup`
- Sign in: `http://127.0.0.1:8765/login`
- Workspace: `http://127.0.0.1:8765/app`

Create two test users with two different emails and two different shop names. Add a product to the first shop, sign out, sign into the second shop and confirm the first shop's product is not visible. This is an isolation smoke test, not an independent penetration test.

When finished, stop the server with Ctrl+C. Delete `saas-test-data` only if you want to permanently remove both test accounts and their test data.

To return to the ordinary one-workspace local demo, open a new terminal (or clear the environment variables) and run `py app.py` with `CUTPILOT_MODE` unset or set to `local`.

## Before putting this on the public internet

### 1. Create a source-code repository

- Put the project in a private Git repository.
- Do not upload `data/`, SQLite files, `.env`, email passwords, payment keys or real butcher exports.
- Commit `.env.example`, not your real environment values.

### 2. Hosting and persistent storage

The included `render.yaml` is a starting Render Blueprint for a single paid Python web service with a persistent disk mounted at `/var/data/cutpilot`.

- Connect the Git repository to Render and create the service from the Blueprint.
- Keep `CUTPILOT_MODE=saas`.
- Keep `CUTPILOT_DATA_DIR=/var/data/cutpilot` so both `auth.sqlite3` and the `tenants/` directory survive deploys/restarts.
- Do not use a free Render web service for this SQLite setup: its filesystem is ephemeral and cannot attach a persistent disk.
- Use one instance only while data is stored as tenant SQLite files. Render persistent disks are attached to one service instance and cannot be shared by multiple instances.
- Configure `CUTPILOT_BASE_URL` to the real HTTPS domain, e.g. `https://app.example.com`.
- Configure a custom domain and verify HTTPS before enabling sign-up.

### Approximate early pilot hosting cost

Render currently lists its smallest paid web-service compute tier at **$7/month** and persistent SSD storage at **$0.25 per GB/month**. The included blueprint asks for a 1 GB disk, making a simple baseline about **$7.25/month** before taxes, bandwidth, domain registration, email delivery or add-ons. Re-check the provider's pricing before purchasing. Do not use a free web service for this SQLite setup: free instances have ephemeral filesystems and cannot attach persistent disks.

Official references: https://render.com/pricing and https://render.com/docs/disks

### 3. Email delivery

Set these values privately in the hosting dashboard, never in source code:

```env
CUTPILOT_REQUIRE_EMAIL_VERIFICATION=1
CUTPILOT_BASE_URL=https://app.example.com
CUTPILOT_SMTP_HOST=your-transactional-email-smtp-host
CUTPILOT_SMTP_PORT=587
CUTPILOT_SMTP_USER=your-smtp-user
CUTPILOT_SMTP_PASSWORD=your-smtp-password
CUTPILOT_EMAIL_FROM=CutPilot <noreply@example.com>
CUTPILOT_COOKIE_SECURE=1
CUTPILOT_SESSION_DAYS=7
```

Use a transactional email provider that permits your sender domain. Verify SPF/DKIM/DMARC for the domain and test signup, verification, password reset and delivery to common inboxes. Do not make public registration available until email delivery works.

### 4. Backups and operations

- Back up the complete `/var/data/cutpilot/` directory including `auth.sqlite3` and every file under `tenants/`.
- Schedule encrypted backups and test restoring them before real shops use the service.
- Set a retention policy for old imports and audit information.
- Add uptime/error monitoring and a support contact.
- Have a developer review rate limits, session management, file-upload limits, tenant isolation, cookie/CSRF configuration and server hardening.
- Keep the application on one instance for this storage model. Do not enable horizontal scaling.

## Future production database migration

Before growing beyond a small pilot, migrate business records to managed PostgreSQL. Model `organizations`, `organization_members`, `locations` and every business-owned row with `organization_id`; enforce row-level security and server-side membership checks on all tables. Run automated cross-tenant read/write tests and backup/restore tests. The current per-tenant SQLite layout is a bridge for an early pilot, not the final multi-tenant database architecture.

## Pricing and payment status

The public site and in-app page show proposed Starter ($29/month), Professional ($59/month) and Multi-location ($99+/month) pricing. Selecting a tier preselects it during signup, and the organization's plan preference is stored. It does not collect payment or activate a paid subscription.

A payment provider still needs merchant approval, products/prices, sandbox tests, a server-side webhook signature verifier, subscription lifecycle handling (paid, past due, cancelled, refunded), tax handling, receipts and a payout account. Do not manually grant paid status based on a browser redirect. Provision paid access only from a verified provider webhook.

If using Paddle, create a sandbox first, define product/price IDs, use only the client-side token in browser code, keep API keys and webhook secrets on the server, and provision access from verified webhooks. Review vendor eligibility, tax/legal requirements and payout options with the legally responsible adult/business owner before applying.

## Legal and owner responsibilities

A responsible adult/business owner must own or supervise the hosting, domain, email and payment-provider accounts and any required business registration, contracts, tax and payout arrangements. Never falsify age, identity, business or country details to pass a provider's checks. Before inviting paying shops, publish accurate terms, privacy notice, support/refund process and data deletion/export policy.
