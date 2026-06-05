"""
FastAPI gateway — Agentic SaaS Boilerplate

Wires together:
  - WorkflowEngine (real production engine from ACE)
  - Per-run SSE subscriber queues
  - Billing webhooks (Stripe + Razorpay)
  - Circuit breaker on the execution path

Quick start:
  1. Register your agent functions in AgentRegistry (see bottom of this file)
  2. uvicorn main:app --reload
  3. POST /api/run-pipeline {"task": "..."}
  4. GET  /api/stream/{run_id} for live updates
"""
import asyncio
import json
import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from billing_router import router as billing_router
from circuit_breaker import CircuitBreaker, CircuitBreakerOpenException
from core.engine import AgentRegistry, engine
from core.workflow import Node, Workflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

app = FastAPI(
    title="Agentic SaaS Boilerplate",
    description="Multi-agent DAG execution with SSE streaming and dual-provider billing.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(billing_router)

llm_breaker = CircuitBreaker("LLM_Router", failure_threshold=3, recovery_timeout=30.0)


# ---------------------------------------------------------------------------
# SSE streaming — per-run subscriber queue
# ---------------------------------------------------------------------------

@app.get("/api/stream/{run_id}")
async def sse_stream(run_id: str, request: Request):
    """
    Subscribe to live events for a specific run.
    Each client gets its own queue; events are isolated per run_id.
    """
    q = engine.subscribe(run_id)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    if payload is None:            # sentinel — run ended
                        break
                    evt = json.loads(payload)
                    event_type = evt.get("type", "message")
                    yield f"event: {event_type}\ndata: {payload}\n\n"
                    q.task_done()
                except asyncio.TimeoutError:
                    yield ": ping\n\n"             # keep-alive
        finally:
            engine.unsubscribe(run_id, q)

    return StreamingResponse(generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Pipeline trigger
# ---------------------------------------------------------------------------

async def _run_pipeline(run_id: str, task: str) -> None:
    """
    Builds and executes the workflow. Runs as a background task.

    This demo pipeline: Planner → Copywriter + ImageGenerator (parallel) → Verifier
    Replace the agent implementations in AgentRegistry with your real LLM calls.
    """
    wf = Workflow(
        nodes={
            "Planner":        Node("Planner",        "planner",         {"prompt": f"Plan a campaign for: {task}"}),
            "Copywriter":     Node("Copywriter",     "copywriter",      {"prompt": "Write promotional copy based on the plan."}),
            "ImageGenerator": Node("ImageGenerator", "image_generator", {"prompt": "Generate visual asset prompts based on the plan."}),
            "Verifier":       Node("Verifier",       "verifier",        {"prompt": "Review all outputs for quality and consistency."}),
        },
        edges=[
            ("Planner", "Copywriter"),
            ("Planner", "ImageGenerator"),
            ("Copywriter", "Verifier"),
            ("ImageGenerator", "Verifier"),
        ],
    )

    try:
        async def execute():
            # engine.start() was already called to get run_id — just execute
            from core.workflow import WorkflowRun, NodeState
            run = engine.get(run_id)
            if not run:
                return
            await engine._execute(run_id, wf)

        await llm_breaker.call(execute)
    except CircuitBreakerOpenException:
        logger.error(f"Run {run_id}: blocked by circuit breaker")
    except Exception as e:
        logger.error(f"Run {run_id}: unhandled error — {e}")


@app.post("/api/run-pipeline")
async def trigger_pipeline(payload: dict, background_tasks: BackgroundTasks):
    """
    Triggers a DAG pipeline run. Returns run_id immediately.
    Subscribe to /api/stream/{run_id} for live updates.
    """
    task    = payload.get("task", "Generate marketing campaign")
    run_id  = str(uuid.uuid4())

    # Build workflow definition
    wf = Workflow(
        nodes={
            "Planner":        Node("Planner",        "planner",         {"prompt": f"Plan for: {task}"}),
            "Copywriter":     Node("Copywriter",     "copywriter",      {"prompt": "Write copy based on the plan."}),
            "ImageGenerator": Node("ImageGenerator", "image_generator", {"prompt": "Create visual prompts based on the plan."}),
            "Verifier":       Node("Verifier",       "verifier",        {"prompt": "Review all outputs."}),
        },
        edges=[
            ("Planner", "Copywriter"),
            ("Planner", "ImageGenerator"),
            ("Copywriter", "Verifier"),
            ("ImageGenerator", "Verifier"),
        ],
    )

    # Start run (registers run_id, fires background task)
    started_id = await engine.start(wf=wf)

    return {
        "status":  "queued",
        "run_id":  started_id,
        "stream":  f"/api/stream/{started_id}",
        "message": "Subscribe to the stream URL for live node updates.",
    }


# ---------------------------------------------------------------------------
# Status endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/runs")
async def list_runs():
    return {"runs": engine.list_runs()}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = engine.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id":   run.run_id,
        "status":   run.status,
        "nodes":    {nid: {"status": ns.status, "agent": ns.agent} for nid, ns in run.nodes.items()},
        "artifacts": run.artifacts,
    }


# ---------------------------------------------------------------------------
# AgentRegistry — register your agent functions here
#
# Each function receives:
#   prompt:  str          — the node's prompt + prior context summary
#   context: dict         — outputs from all previously completed nodes
#   **params              — any extra params from Node.params
#
# Return a string. The engine broadcasts it, stores it, passes it downstream.
#
# Example (swap asyncio.sleep for a real LLM call):
#
#   from llm_router import chat   # or any LLM client
#
#   async def real_planner(prompt, context, **_):
#       result = await chat([{"role": "user", "content": prompt}], task_class="content")
#       return result["content"]
#
#   AgentRegistry["planner"] = real_planner
# ---------------------------------------------------------------------------

async def _stub_agent(name: str, prompt: str, context: dict, **_) -> str:
    """Demo stub — replace with your real LLM call."""
    await asyncio.sleep(0.5)
    prior = list(context.keys())
    return (
        f"{name} completed.\n"
        f"Processed: {prompt[:120]}{'...' if len(prompt) > 120 else ''}\n"
        f"Context from: {prior if prior else 'none'}"
    )


AgentRegistry["planner"]         = lambda prompt, context, **k: _stub_agent("Planner",         prompt, context, **k)
AgentRegistry["copywriter"]      = lambda prompt, context, **k: _stub_agent("Copywriter",      prompt, context, **k)
AgentRegistry["image_generator"] = lambda prompt, context, **k: _stub_agent("ImageGenerator",  prompt, context, **k)
AgentRegistry["verifier"]        = lambda prompt, context, **k: _stub_agent("Verifier",         prompt, context, **k)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
