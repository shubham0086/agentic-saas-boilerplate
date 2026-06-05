# SETUP.md — Get Running in 5 Minutes

## Prerequisites

- Python 3.10+
- Node.js 18+
- Git

---

## 1. Clone

```bash
git clone https://github.com/shubham0086/agent-saas-boilerplate.git
cd agent-saas-boilerplate
```

## 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and fill in your webhook secrets (or leave the mock defaults for local testing).

## 3. Backend

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

Backend runs at: `http://localhost:8000`

API docs (auto-generated): `http://localhost:8000/docs`

## 4. Frontend

Open a second terminal from the project root:

```bash
npm install
npm run dev:frontend
```

Dashboard runs at: `http://localhost:3000`

## 5. Run Tests

```bash
cd backend
pytest tests/ -v
```

Expected: all tests pass (no live API keys required — everything runs on mock data).

## 6. Trigger a Mock Pipeline

With both servers running, open `http://localhost:3000` and click **Run Pipeline**.

You will see real-time SSE updates stream from the backend DAG execution into the dashboard.

To trigger via curl:

```bash
curl -X POST http://localhost:8000/api/run-pipeline \
  -H "Content-Type: application/json" \
  -d '{"task": "Generate a marketing campaign"}'
```

Then subscribe to the stream in a second terminal:

```bash
curl -N http://localhost:8000/api/stream
```

## 7. Docker (Optional)

```bash
docker-compose up --build
```

This starts the FastAPI backend in a container on port 8000.

---

## Webhook Testing

Use the included mock webhook simulator to test billing flows locally:

```bash
npm run test:mock-webhooks
```

This fires simulated Stripe and Razorpay payloads at the local server with correct HMAC signatures.

For real webhook testing with Stripe CLI:

```bash
stripe listen --forward-to localhost:8000/api/billing/webhook/stripe
```

---

## Troubleshooting

**`ModuleNotFoundError`** — Make sure you activated the virtualenv before running pytest or uvicorn.

**Port already in use** — Change `BACKEND_PORT` in `.env` and pass `--port` to uvicorn accordingly.

**SSE stream empty** — Trigger a pipeline run first (`POST /api/run-pipeline`). The stream only delivers events during active runs.
