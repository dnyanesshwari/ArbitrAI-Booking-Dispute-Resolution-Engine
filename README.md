# ArbitrAI — AI Booking Dispute & Resolution Engine

ArbitrAI is a take-home demonstration for reviewing booking disputes in a coworking marketplace. Customers can submit disputes and follow their status. Administrators can investigate cases with Gemini, review deterministic policy checks, and record a final decision. **No payments or refunds are processed.**

## Features and architecture

- React 19 and Vite provide the customer portal and existing administrator dashboard. FastAPI serves the `/api` routes; Vite proxies those requests to the backend during development.
- Gemini returns structured issue extraction, evidence assessment, policy references, uncertainty and a proposed outcome. Python validates the response schema and applies deterministic checks against `Backend/policies.md`.
- Backend JSON storage persists the supplied listings and disputes, account records, hashed session tokens, AI proposals, decision history and audit entries. The first backend read copies `Backend/data.example.json` to the ignored runtime file `Backend/data.json`; older data files are migrated with owner and authentication fields.
- bcrypt hashes account passwords. Public registration creates customers only. Expiring HttpOnly, SameSite=Lax session cookies identify users. Customers can access their own cases; administrators can access all cases and the analysis, statistics and decision endpoints.
- The five legacy disputes have no account owner and are visible to administrators only. New case ownership is assigned on the server from the signed-in session.

## Prerequisites

The tested versions in this workspace were Python 3.13.14, Node.js 24.19.0 and npm 11.17.0. Vite 8 requires Node.js 20.19+ or 22.12+.

## Windows setup

Run these commands from the project root in PowerShell:

```powershell
py -3 -m venv Backend\.venv
Backend\.venv\Scripts\python.exe -m pip install -r Backend\requirements.txt
Copy-Item Backend\.env.example Backend\.env
notepad Backend\.env
```

Set `GEMINI_API_KEY` in `Backend\.env`. `GEMINI_MODEL` defaults to `gemini-2.5-flash`; use a model available to your API key. `.env`, virtual environments, frontend dependencies, build output and runtime JSON data are ignored by Git. Do not commit or paste secrets into logs or source files.

### Provision the initial administrator

Before starting the backend, open a PowerShell window at the project root:

```powershell
Set-Location Backend
.\.venv\Scripts\python.exe -m auth provision-admin
```

The one-time command prompts for an email, display name and password (at least 12 characters, at most 72 UTF-8 bytes). It refuses to provision an additional administrator if one already exists. No demo administrator credentials are stored in the repository.

For HTTPS deployments, set `ARBITRAI_COOKIE_SECURE=1` in the backend environment. Leave it unset for local HTTP development.

### Start the backend and frontend

In the backend window, after provisioning:

```powershell
Set-Location Backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

In a second PowerShell window:

```powershell
Set-Location Frontend
npm.cmd install
npm.cmd run dev
```

Open <http://localhost:5173>. The Vite proxy forwards `/api` to `http://127.0.0.1:8000`. Set `VITE_API_TARGET` in the frontend environment to override that backend URL. Sign in as the provisioned administrator at `/login`; customers can create accounts at `/register`.

## Demonstration workflows

### Customer

1. Register and sign in.
2. Submit a dispute with a listing, booking amount, date and time, complaint, and optional evidence references.
3. Confirm the case appears in that account’s portal and inspect its status after administrator review. A customer cannot read another customer’s case by changing its ID.

### Administrator

1. Sign in with the provisioned admin account and review the dashboard, search and status filters.
2. Open a seeded dispute or customer submission. Compare the booking, original listing promises, statements, evidence references and AI assessment.
3. Run analysis and review policy references, evidence gaps and the proposed outcome. Provider errors are reported; the app does not invent a substitute analysis.
4. Approve an eligible proposal, reject it for manual investigation, or modify it with a reason. The authenticated admin account is recorded as reviewer.
5. Refresh the case and confirm the stored decision, original AI proposal and audit history. A rejected proposal remains in Manual Review until a separate final decision is recorded.

## Supplied dispute scenarios and policy behavior

`Backend/data.example.json` contains all five original scenarios; `Backend/policies.md` is the policy source of truth.

| Case | Expected outcome | Policy clause |
| --- | --- |
| C-1001 Projector failure | 30% for the admitted projector fault; disputed Wi-Fi is not verified | P1 |
| C-1002 Denied cabin access | 100% when denied access and no accepted equivalent are established | P2 |
| C-1003 Cancellation 30 minutes before start | 0% under the less-than-two-hour cancellation window | P3 |
| C-1004 Disputed property damage | Manual review without verified photos or timestamped evidence | P4, P6 |
| C-1005 Noise on an open-plan floor | No refund because quiet was not promised | P5 |

The guardrails also apply P6: unresolved outcome-critical facts lead to manual investigation. Evidence references and filenames are descriptions only. Administrators can record a structured verification attestation; this records their review, not independent proof of an artifact. Admin analysis and final decisions are separate, and no decision calls a payment service.

## AI limitations

Gemini can misread statements, miss context, or return incomplete output. Its result is a proposal only. Deterministic checks validate policy references, allowed refund percentages, evidence gates, and selected outcomes; they cannot establish the authenticity of evidence or replace administrator judgment. Provider failures stop analysis and can be retried.

## Handling uncertain or conflicting evidence

Keep submitted references distinct from verified facts. Administrators should inspect the underlying material, record its type and the specific claim it supports, and leave conflicting or outcome-critical unresolved facts for manual review under P6. An attestation records who reviewed an item and when; it does not make a filename or claim self-proving. Preserve both customer and owner statements when they conflict.

## Design choices

- FastAPI and a small JSON store keep the demonstration easy to run and inspect; atomic writes protect the file from partial replacement.
- Gemini handles extraction and proposal generation, while Python owns policy checks and final decision validation.
- Administrator sessions control case analysis, evidence attestations, decisions, and message drafts. Draft messages are deterministic, labeled as unsent, and never trigger external communication.
- Customer and owner messages are generated from finalized outcomes and cited policy references without an additional LLM call.

## Environment variables

| Variable | Used by | Purpose / default |
| --- | --- | --- |
| `GEMINI_API_KEY` | Backend | Required for Gemini analysis; keep it in `Backend/.env` and out of source control. |
| `GEMINI_MODEL` | Backend | Gemini model name; defaults to `gemini-2.5-flash`. |
| `VITE_API_TARGET` | Frontend | Optional Vite proxy target; defaults to `http://127.0.0.1:8000`. |
| `ARBITRAI_COOKIE_SECURE` | Backend | Set to `1`/`true`/`yes` for HTTPS secure session cookies; unset for local HTTP. |

## Screenshots

Add screenshots under `docs/` when available:

- `docs/dashboard.png` — administrator dashboard.
- `docs/case-review.png` — evidence review and final decision.
- `docs/customer-portal.png` — customer case status.

## AI, policy and storage limitations

Gemini output is a proposal, not a decision. Its structured response is schema-validated, policy IDs are checked against the supplied rules, refund calculations and evidence gates are evaluated in Python, and unresolved critical unknowns take precedence. The model can still misunderstand narrative details; administrators remain responsible for reviewing evidence and deciding the case. An unavailable provider, invalid configuration or exhausted quota results in an error that can be retried; it does not produce a default refund.

The JSON store uses atomic file replacement and in-process write locking. It is suitable for this single-instance demonstration, not concurrent multi-process or horizontally scaled production service. The app does not implement password reset, email verification, rate limiting or an independent security audit. Sessions and accounts are lost if the local runtime JSON file is deleted. Set secure cookie mode when serving over HTTPS.

## Tests and frontend checks

From the project root:

```powershell
Backend\.venv\Scripts\python.exe -m unittest discover -s Backend\tests
Set-Location Frontend
npm.cmd run build
npm.cmd run lint
```

Backend tests use mocked Gemini responses and cover all five supplied cases, policy/evidence guardrails, malformed and failed AI requests, password hashing, authentication and ownership permissions, decision finalization, audit history and JSON persistence. They do not require a live Gemini API key.

cd backend
venv\Scripts\activate.bat
python -m uvicorn main:app --reload

cd Frontend
npm.cmd run dev
