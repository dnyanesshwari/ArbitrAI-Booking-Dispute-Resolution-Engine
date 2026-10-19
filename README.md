
# ArbitrAI — AI-Powered Booking Dispute & Resolution Engine

ArbitrAI is an AI-assisted dispute resolution system for a coworking-space booking marketplace. Customers can submit booking disputes and track their cases, while administrators review disputes, evaluate AI-generated recommendations, and record final decisions.

The system combines **Gemini AI analysis with deterministic Python policy guardrails** to support consistent, policy-based dispute handling.

> **Note:** ArbitrAI is a demonstration project. It does not issue real refunds or replace human judgment.

## ✨ Features

- **Customer Portal:** Register, log in, submit disputes, and track personal cases.
- **Admin Dashboard:** View and review disputes across customers.
- **AI-Assisted Analysis:** Generate proposed dispute outcomes using Gemini.
- **Policy Guardrails:** Validate proposed outcomes against predefined business rules.
- **Human-in-the-Loop Review:** Approve eligible proposals, send cases for manual investigation, or modify and finalize decisions.
- **Authentication and Authorization:** Separate customer and administrator access.
- **Persistent Demo Storage:** Store users, sessions, disputes, and decisions in JSON files.
- **Seeded Scenarios:** Explore predefined booking dispute examples.
- **Automated Tests:** Test application logic and access-control behavior.

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| Frontend | React, Vite |
| Backend | Python, FastAPI |
| AI | Google Gemini API |
| Data Storage | JSON |
| Authentication | Session tokens and password hashing |
| Testing | Python `unittest`, frontend build and lint checks |

## 🏗️ Architecture

```text
Customer / Administrator
          |
          v
    React + Vite
          |
          v
     FastAPI Backend
          |
          +---- Authentication & Authorization
          |
          +---- Dispute Management
          |
          +---- Gemini AI Analysis
          |
          +---- Python Policy Guardrails
          |
          v
       JSON Storage
```

## 🚀 Getting Started

### Prerequisites

Install the following before running the project:

- Python 3.10 or a compatible version supported by the dependencies
- Node.js and npm
- A Google Gemini API key for live AI analysis

Run the following commands from the project root in Windows PowerShell.

### 1. Set Up the Backend

Create a virtual environment:

```powershell
py -3 -m venv Backend\.venv
```

Install the dependencies:

```powershell
Backend\.venv\Scripts\python.exe -m pip install -r Backend\requirements.txt
```

Create your environment file:

```powershell
Copy-Item Backend\.env.example Backend\.env
notepad Backend\.env
```

Add your Gemini configuration to `Backend/.env`:

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
```

Replace `your_gemini_api_key` with your actual API key. Keep this key private and never commit it to GitHub.

### 2. Create an Administrator Account

Provision the administrator account using the project's CLI:

```powershell
Set-Location Backend
.\.venv\Scripts\python.exe -m auth provision-admin
```

Follow the prompts to enter the administrator's email, display name, and password.

Return to the project root after completing the setup:

```powershell
Set-Location ..
```

Public registration is intended for customer accounts. Administrator access should be provisioned through the supported administrative setup process.

### 3. Start the Backend Server

From the project root:

```powershell
Set-Location Backend
..\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

The backend should be available at:

- API: `http://127.0.0.1:8000`
- Swagger documentation: `http://127.0.0.1:8000/docs`

Keep this terminal open while using the application.

### 4. Start the Frontend

Open a second terminal in the project root:

```powershell
Set-Location Frontend
npm install
npm run dev
```

Open the URL displayed by Vite, normally:

`http://localhost:5173`

The frontend uses the Vite development proxy to forward `/api` requests to the backend at `http://127.0.0.1:8000`. If your backend runs elsewhere, configure `VITE_API_TARGET` as supported by the project.

## 🔐 Authentication and Roles

### Customer

- Register for an account and log in.
- Submit booking disputes.
- View and track their own disputes.
- Access only the records permitted by the backend authorization rules.

### Administrator

- Log in using the provisioned administrator account.
- View disputes across customers, including eligible seeded demo cases.
- Review AI-generated proposals and relevant policy rules.
- Approve, modify, or send cases for manual investigation, according to the implemented workflow.

### Session Security

The application is designed to use password hashing and expiring session tokens. Verify the implementation in the authentication module before relying on these settings in a production environment.

For deployment over HTTPS, configure secure cookies using the supported environment settings. Local HTTP development may require secure cookies to be disabled.

## 🧪 Demo Workflow

1. Start both the backend and frontend.
2. Register a customer account or sign in as the provisioned administrator.
3. As a customer, submit a booking dispute with the listing details, booking date, amount, complaint, and available evidence references.
4. Sign in as an administrator to review the dispute.
5. Run AI-assisted analysis when the Gemini API is available.
6. Examine the proposed outcome and the applicable policy rules.
7. Approve an eligible proposal, modify the decision, or send the case for manual investigation.
8. Refresh the application and verify that saved data persists.

### Example Dispute Scenarios

The demo includes scenarios covering:

- Amenity failure
- Denied access
- Last-minute cancellation
- Property damage
- Noise complaints

The exact outcome depends on the applicable rules in `Backend/policies.md` and the available, verified information.

## 📋 Policy and Evidence Handling

The file `Backend/policies.md` is the primary reference for the application's dispute-resolution rules.

The backend uses deterministic Python guardrails to validate AI-generated proposals. AI recommendations should not override mandatory review requirements or established policy constraints.

**Important limitations:**

- Evidence references are descriptions, not uploaded files or independently verified proof.
- Missing or uncertain facts may require manual investigation.
- A claim should not be treated as verified solely because a customer supplies an evidence filename or reference.
- Gemini output may be unavailable because of API configuration, quota, rate limits, or provider errors.
- The demonstration does not process actual refunds or payments.

## 🧰 Running Tests

### Backend Tests

Run from the project root:

```powershell
Backend\.venv\Scripts\python.exe -m unittest discover -s Backend\tests
```

AI provider calls may be mocked during tests. Passing these tests does not establish that live Gemini integration is working.

### Frontend Checks

Run from the frontend directory:

```powershell
Set-Location Frontend
npm run build
npm run lint
```

## 💾 Data Storage

ArbitrAI uses JSON-based storage for demonstration purposes. On a fresh checkout, the application may initialize its runtime data from `data.example.json`, depending on the implemented startup logic.

- Keep runtime data and credentials out of version control.
- Back up demo data before resetting the environment.
- Treat the JSON storage approach as a single-instance demonstration design.
- Use a transactional database and appropriate concurrency controls before deploying a multi-user production system.

## 🔮 Future Improvements

- PostgreSQL integration for reliable transactional storage
- Secure evidence uploads and evidence verification
- Audit logs for administrative decisions
- Improved AI failure handling and observability
- Expanded policy and regression test coverage
- Production deployment with hardened authentication and authorization
- Real payment/refund integration with appropriate safeguards

## 🎯 Project Goal

ArbitrAI demonstrates how AI-assisted analysis, deterministic policy validation, and human review can work together to make booking dispute handling more structured, transparent, and consistent.

**Built with React, FastAPI, Python, and Google Gemini.**
