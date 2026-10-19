# ArbitrAI — Booking Dispute & Resolution Engine

ArbitrAI is a coworking marketplace dispute review demo. Customers submit disputes and track their own statuses. Administrators review all cases, inspect AI proposals and record final decisions. FastAPI stores cases, users, expiring sessions, proposals and decisions in `Backend/data.json`. Gemini creates a structured proposal; deterministic Python guardrails check it against `Backend/policies.md`. **No real refunds are processed.**

## Windows setup

Open PowerShell at the project root:

```powershell
py -3 -m venv Backend\.venv
Backend\.venv\Scripts\python.exe -m pip install -r Backend\requirements.txt
Copy-Item Backend\.env.example Backend\.env
notepad Backend\.env
```

Set `GEMINI_API_KEY` to a Gemini API key in `Backend\.env`. `GEMINI_MODEL` defaults to `gemini-2.5-flash`; change it only to a model enabled for your key. Keep `.env` private.

Start the backend in PowerShell window 1:

```powershell
Set-Location Backend
..\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Start the frontend in PowerShell window 2:

```powershell
Set-Location Frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to `http://127.0.0.1:8000`; set `VITE_API_TARGET` to override this target.

## Accounts and roles

Public registration always creates a customer account. Passwords are hashed with bcrypt. Sessions use random, expiring tokens in HttpOnly, SameSite=Lax cookies; only token hashes are stored in JSON. For local HTTP development the cookie is not marked Secure. Set `ARBITRAI_COOKIE_SECURE=1` when serving the API over HTTPS.

Provision the initial administrator once from PowerShell before starting the backend. From the project root:

```powershell
Set-Location Backend
.\.venv\Scripts\python.exe -m auth provision-admin
```

The command prompts for the email, display name and password (12–72 characters); it does not accept the password as a command-line argument. It refuses to provision another admin once one exists. Sign in with these credentials at `/login`. Do not place admin credentials in source control or share them in a demo. Customers can register at `/register`.

The five legacy seeded disputes remain available to administrators. They have no customer owner and are intentionally not exposed to customer accounts. Newly created cases receive their owner ID from the authenticated server session, never from submitted form data.

## Demonstration workflow

1. Sign in as the provisioned administrator to review the seeded disputes and live statistics. Register or sign in as a customer to use the customer portal.
2. As a customer, submit a dispute and verify it appears only in that account's case list. As an administrator, open a seeded or newly submitted case.
3. On the case page, compare the booking, listing promises, statements and evidence references.
4. Run **Analyze with AI**. Inspect the four information categories, policy clauses/rules, evidence gaps and proposed outcome. If the provider fails, use **Retry analysis** after addressing the displayed error.
5. Approve an eligible proposal, reject it into manual investigation, or modify the final outcome. Supply administrator identity and a reason.
6. Re-open or refresh the case. The final decision and original AI proposal are retained in JSON storage.

Seeded scenarios cover amenity failure, denied access, last-minute cancellation, disputed property damage and noise. Property damage without photos or timestamped evidence is a manual investigation. Noise without a quiet-environment listing promise receives no refund under P5.

## Policy, uncertainty and AI limitations

`Backend/policies.md` is the policy source. Python checks policy IDs, supported percentages, cancellation timing, evidence gates and manual-review requirements after model validation. Model output is a proposal and can still misread narrative context; a human administrator reviews it. Submitted evidence entries are descriptions or references, not uploaded files, so the app does not verify document/image contents. Disputed critical facts and insufficient evidence remain explicit unknowns and lead to manual review.

Disputed critical facts and insufficient evidence remain explicit unknowns and lead to manual review. Seeded disputes are admin-only because their historical submitters are not represented as accounts. JSON file storage is a lightweight single-instance demo store, not a horizontally scaled production database; sessions are invalidated if the JSON file is lost. This is a take-home implementation and has not been independently security audited. The application records refund decisions only and never calls a payment/refund service.

## Tests and build

```powershell
Backend\.venv\Scripts\python.exe -m unittest discover -s Backend\tests
Set-Location Frontend
npm run build
npm run lint
```

The backend tests mock provider responses and do not require an API key. On a fresh checkout, the backend creates its local `Backend/data.json` from the sample `Backend/data.example.json` on first run. Runtime data and credentials are not committed. Register a customer account and provision an administrator using the instructions above.
