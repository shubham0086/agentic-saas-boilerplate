# CLAUDE.md — Agent Workspace Context & Coding Rules

This repository is a production-ready SaaS Boilerplate for Multi-Agent AI Applications, featuring a zero-dependency DAG scheduler, Server-Sent Events (SSE) streaming updates, and Stripe/Razorpay webhook gateways.

---

## 🛠️ Build & Dev Commands

### 1. Setup Environment
Ensure you have Python 3.10+ and Node.js 18+ configured:
```bash
# Python setup
cd backend
python -m venv venv
source venv/bin/activate  # venv\Scripts\activate on Windows
pip install -r requirements.txt

# Frontend setup
cd ..
npm install
```

### 2. Run Local Servers
To run the full stack in development mode:
```bash
# Run FastAPI Backend (from backend/ directory)
uvicorn main:app --port 8000 --reload

# Run Static Frontend (from root directory)
npm run dev:frontend
```
*   Backend API runs at: `http://localhost:8000`
*   Frontend Dashboard runs at: `http://localhost:3000`

### 3. Verification & Testing
To execute backend verification checks:
```bash
# Run pytest tests
pytest backend/tests/

# Trigger mock billing webhook simulations
npm run test:mock-webhooks
```

---

## 📐 Project Directory Structure

```
agent-saas-boilerplate/
├── package.json              ← Node script registry
├── requirements.txt          ← Root python requirements
├── docker-compose.yml        ← Container orchestration
├── CLAUDE.md                 ← This context guideline
├── README.md                 ← Public showcase landing page
│
├── backend/                  ← FastAPI Python backend
│   ├── main.py               ← App entry-point & routers
│   ├── dag_engine.py         ← Zero-Dependency DAG scheduler
│   ├── sse_broadcaster.py    ← Real-time Server-Sent Events broker
│   ├── billing_router.py     ← Geo-routed Stripe + Razorpay billing
│   ├── circuit_breaker.py    ← Stateful LLM api failover wrapper
│   ├── Dockerfile            ← Container runner
│   └── tests/                ← Unit testing files
│
├── frontend/                 ← Dashboard Client UI
│   ├── index.html            ← Glassmorphic dashboard template
│   └── dashboard.js          ← EventSource handler for real-time SSE
│
├── docs/                     ← Step-by-step learning modules
│   ├── 01-dag-agent-scheduler.md
│   ├── 02-fastapi-sse-streaming.md
│   └── 03-stripe-razorpay-securing.md
│
└── memory/
    └── reality/
        └── reality.yaml      ← Verification test logs
```

---

## 🎨 Coding & Style Guidelines

### 1. Python Style Rules (Backend)
*   **Version**: Python 3.11+ async standards. Use native async/await for I/O routes.
*   **Frameworks**: Use standard Pydantic v2 schemas for request validation.
*   **Security**: Verify all Stripe/Razorpay webhook signatures using constant-time cryptographic functions (`hmac.compare_digest`).
*   **Formatting**: Keep standard import sorting (standard libraries -> third-party -> local files).

### 2. JavaScript Style Rules (Frontend)
*   **Type**: Pure modern ESModules (ESM) using `"type": "module"`.
*   **UI Standards**: CSS-first layout with smooth transitions, flexbox/grid alignments, and glassmorphic colors. Avoid massive external script frameworks where native `EventSource` web APIs suffice.
*   **Real-time Streaming**: Connect to the backend using standard browser `EventSource` connections for unidirection streaming SSE, closing connections gracefully on page unload.
