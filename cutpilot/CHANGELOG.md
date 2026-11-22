# Changelog

## 1.8.0 — Hosted account pilot foundation

- Added a public marketing website and public pricing page.
- Kept the in-app Plans & pricing page.
- Added owner registration, sign-in, sign-out, email verification, password-reset request and password-reset flow.
- Added scrypt password hashing, expiring hashed sessions, HttpOnly SameSite cookies, basic login/registration rate limits and same-origin checks.
- Added one private SQLite workspace database per butcher business in SaaS mode; API requests resolve their tenant from the signed-in server-side session.
- Added `render.yaml` for a single-instance hosted pilot with persistent storage and SMTP configuration.
- Added local SaaS-mode test instructions, hosted launch guide, public pricing page and account pages.
- Billing is deliberately not enabled. Price cards are proposed plans; signup creates a pilot account without charging.
- Clearly documents that per-tenant SQLite on one persistent-disk instance is a pilot bridge, not the long-term PostgreSQL multi-tenant architecture.
