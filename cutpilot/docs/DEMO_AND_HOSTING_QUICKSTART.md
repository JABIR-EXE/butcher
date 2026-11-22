# CutPilot demo and hosted launch quickstart

## Record a demo now (local preview)

```powershell
py -m pip install -r requirements.txt
py app.py
```

Visit `http://127.0.0.1:8765`. Load the demo workspace or import the included product and sales samples. This local mode has no customer login and is not a public service.

## Demonstrate the account flow locally

Use a separate terminal and the SaaS test settings below. This uses a separate isolated data folder and turns off email verification only for local tests:

```powershell
$env:CUTPILOT_MODE = "saas"
$env:CUTPILOT_HOST = "127.0.0.1"
$env:CUTPILOT_DATA_DIR = "$PWD\saas-test-data"
$env:CUTPILOT_REQUIRE_EMAIL_VERIFICATION = "0"
$env:CUTPILOT_COOKIE_SECURE = "0"
py app.py
```

Open `/`, then `/pricing`, create a test account at `/signup`, then sign in at `/login`. Create a second account with a different email and shop name. Verify the two workspaces cannot see each other's products. This is a local functional test; it is not public hosting.

## Public hosted pilot

1. A responsible adult/business owner creates or supervises the hosting, domain and transactional email accounts.
2. Put the project in a private Git repository without databases, exports or secrets.
3. Create a Render paid web service from the included `render.yaml` blueprint. It attaches a persistent disk for the account and tenant SQLite databases.
4. Configure the real `CUTPILOT_BASE_URL`, SMTP host/user/password/from address and secure cookies in Render's environment settings.
5. Confirm email verification and password reset work over HTTPS.
6. Test with two separate test businesses and check cross-tenant data isolation.
7. Back up and restore the data directory.
8. Keep registration invite-only or closed until a developer has reviewed the server and tenant isolation.
9. Billing is still not active. Do not present the plan cards as a working checkout until provider approval, prices, signed webhooks and subscription state have been implemented and tested.

See `HOSTED_SAAS_SETUP.md` for detailed limitations and deployment requirements.
