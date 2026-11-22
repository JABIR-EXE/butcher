# CutPilot: accounts, plans, subscriptions and getting paid

## Status in v1.8

**Account registration and sign-in are implemented for an early hosted pilot. Billing is not implemented.**

The app now has a public marketing site (`/`), public pricing page (`/pricing`), owner registration (`/signup`), sign-in (`/login`), email verification, password reset and a private workspace (`/app`). Each new organization gets its own SQLite workspace file in SaaS mode.

The shown $29 / $59 / $99+ prices are proposals for validation. A selected plan is stored as a preference and the new account starts in `pilot` status. No card is charged, no recurring subscription is created and the app does not yet enforce plan limits.

## 1. What a butcher does

1. Visits the public CutPilot website.
2. Opens Plans & pricing and reviews the proposed packages.
3. Creates an owner account with a name, email and password.
4. Enters the shop name, country, currency and preferred plan.
5. Verifies the email using the link sent by CutPilot (required in hosted setup).
6. Signs in and opens their private shop workspace.
7. Imports the product catalogue and opening stock, then imports POS sales exports using the column-mapping wizard.
8. Reviews sales, stock risks and purchase recommendations.

Each owner account currently creates one shop workspace. Employee invitations, multiple users per shop and multiple locations are not implemented yet.

## 2. What hosted SaaS means

- CutPilot's public website and application run on a hosting provider under a domain you control.
- Butchers visit the website in a browser; they do not install Python, VS Code or SQLite.
- Each owner signs in with their own account.
- The server resolves the owner's organization from the session; business APIs are not meant to trust an organization ID supplied by the browser.
- In v1.8 pilot mode, each shop has a separate SQLite database file on a persistent disk. This is an early single-instance approach, not the long-term database for a larger service.
- Before scale, migrate to managed PostgreSQL with organization-level authorization and database row-level security.

Local preview (`CUTPILOT_MODE=local`) is for development and screen demonstrations only. It stores one workspace on the computer running the app. Account testing (`CUTPILOT_MODE=saas`) can run on your computer using a separate `saas-test-data` directory.

## 3. What is implemented versus what is still missing

| Capability | v1.8 status |
|---|---|
| Public marketing and pricing pages | Implemented |
| Owner registration and sign-in/out | Implemented |
| Password hashing and session expiry | Implemented |
| Email verification and reset flow | Implemented; requires SMTP setup |
| Separate SQLite file per organization | Implemented for early single-instance pilot |
| Two-account isolation tests | Implemented and tested |
| Employee invitations and roles | Not implemented |
| Managed PostgreSQL / scalable multi-tenant service | Not implemented |
| Subscription checkout | Not implemented |
| Verified billing webhooks and recurring subscription state | Not implemented |
| Payout to founder/business account | Not configured |
| Plan limits enforced by backend | Not implemented |

## 4. How subscription money would flow after billing is implemented

1. Butcher chooses a plan in CutPilot.
2. CutPilot asks an approved payment provider to create a hosted checkout session from the server.
3. The butcher pays on the provider's secure checkout page.
4. The provider sends a signed webhook when a subscription is created, renewed, changed, cancelled or payment fails.
5. CutPilot verifies the webhook signature, then updates subscription status and plan entitlements.
6. The provider pays the approved seller/business payout account after fees, refunds, chargebacks and applicable taxes.

Do not mark a user as paid just because the browser returns to a success URL. Only a verified server-side webhook should update a subscription. Never store card numbers or CVV in CutPilot.

## 5. Provider to evaluate first: Paddle

Paddle is a Merchant of Record provider for software and SaaS. Its official supported-country guidance says it works with software businesses globally except countries on its unsupported list. Morocco is not named on the list checked for this guide, but that does **not** guarantee approval. Paddle reviews each vendor and may ask for business, identity, website, product and payout information. Confirm eligibility directly before building around it.

Paddle provides a sandbox for testing products, checkout and webhooks. A production integration would need product/price IDs, a client-side token, server-side API credentials, a webhook endpoint, signature verification and subscription lifecycle handling. Keep API keys and webhook secrets on the server; only the client-side token belongs in browser integration where required.

Paddle's published pay-as-you-go Checkout pricing is currently **5% + $0.50 per transaction**. For example, a $29 checkout would have a listed fee of $1.95 before any other applicable deductions or currency conversion. This is a reference calculation, not an approval or final offer; check the provider's current pricing and contract.

Paddle says payouts are monthly and may be sent by wire transfer or Payoneer when the configured threshold is met (the minimum threshold is $100). Its listed local payout currencies do not include MAD. A Moroccan bank may need to receive another supported currency and convert it; confirm exact eligibility, currency, bank fees and payout methods directly with Paddle and the bank.

Official information:
- Supported countries: https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle
- Paddle pricing: https://www.paddle.com/pricing
- Paddle.js / checkout integration: https://developer.paddle.com/build/checkout/build-overlay-checkout
- Webhooks: https://developer.paddle.com/webhooks/overview
- Sandbox and live setup: https://developer.paddle.com/get-started/quickstart/
- Payout timing and methods: https://www.paddle.com/help/manage/get-paid/when-and-how-do-i-get-paid
- Payout currencies: https://www.paddle.com/help/manage/get-paid/can-i-be-paid-in-my-local-currency

## 6. Other payment-provider notes

- Stripe's published global availability list should be checked before planning a Moroccan-registered business around a standard Stripe account. Do not try to bypass country eligibility using false details.
- PayPal's country feature table lists Morocco for sending, receiving and withdrawing, but confirm business-account terms, recurring subscription support, current fees and the withdrawal route before relying on it.
- Re-check provider availability and terms immediately before launch; they can change.

Official information:
- Stripe global availability: https://stripe.com/global
- PayPal payout-country features: https://developer.paypal.com/payouts/supported-features/

## 7. How the founder gets paid

A payment provider pays the legal seller to the payout method it approved during onboarding. It does not automatically send money to any bank account merely because a checkout succeeds. Confirm:

- Whether the provider accepts the seller's country and business structure.
- The exact legal name and tax/business documents required.
- Supported payout currencies and payout methods for Morocco.
- Minimum payout amount, frequency, conversion costs and bank/SWIFT fees.
- Refund, dispute, chargeback and tax responsibilities.

Do not promise a specific payout route until the provider has approved the account and shown the actual payout options.

## 8. Business and age requirements

A payment provider, hosting service and bank will require accurate identity, age, business, tax and payout details. If the founder is below the provider's minimum age or the local age of majority, a parent/guardian or other legally responsible adult must own or supervise the relevant business, hosting, domain, payment-provider and bank arrangements in accordance with the provider's rules. Never use false age, identity, country or someone else's financial details to get around eligibility checks.

Before accepting recurring payments, have a qualified local professional review the business structure, contracts, local tax treatment and customer obligations. A Merchant of Record may handle some indirect-tax and checkout responsibilities, but it does not remove all company, income-tax, privacy or local legal duties.

## 9. Proposed plan pricing — not validated or live

| Plan | Proposed price | Intended scope to validate |
|---|---:|---|
| Starter | $29/month | One shop, products/stock, imports, sales reporting and basic alerts |
| Professional | $59/month | Starter plus forecasts, purchasing workflows, suppliers and waste tracking |
| Multi-location | $99+/month | Future multi-location and consolidated reporting; not implemented yet |

These prices are hypotheses, not active paid offers. Validate willingness to pay with butcher owners. Do not charge a customer until billing and entitlements are implemented and tested.

## 10. What remains before a commercial launch

- Deploy the hosted pilot on a real domain with HTTPS and working SMTP.
- Use a production-grade web framework/server and complete an independent security review.
- Migrate tenant data to managed PostgreSQL with row-level security before scaling.
- Implement team invitations, roles and account/shop management.
- Add private object storage for imports, upload retention and deletion rules.
- Add encrypted backups and perform restore tests, monitoring, audit logs and incident/support procedures.
- Review and publish accurate terms, privacy notice, cancellations/refunds, data export/deletion and support contact.
- Obtain payment provider approval, implement checkout, signed webhooks, invoices/receipts, cancellations, failed-payment handling and server-side plan limits.
- Test two or more unrelated businesses across all data/API endpoints before allowing real customer data.

Until these are complete, keep the service invite-only and use synthetic or explicitly consented pilot data. The local demo and public pricing page are not a live subscription service.
