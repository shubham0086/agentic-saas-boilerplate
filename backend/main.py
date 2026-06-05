import logging
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from sse_broadcaster import EventBroadcaster
from billing_router import router as billing_router
from dag_engine import Node, DAGEngine
from circuit_breaker import CircuitBreaker, CircuitBreakerOpenException

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

app = FastAPI(
    title="Agent-SaaS-Boilerplate Backend",
    description="FastAPI Multi-Agent SaaS platform gateway with SSE streaming and secure webhook gateways."
)

# Enable CORS for frontend client interactions (port 3000 -> 8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instantiate shared brokers
sse_broadcaster = EventBroadcaster()
llm_breaker = CircuitBreaker("LLM_Router", failure_threshold=2, recovery_timeout=15.0)

# Include billing webhook endpoints
app.include_router(billing_router)

@app.get("/api/health")
async def health_check():
    """Health check ping endpoint."""
    return {"status": "healthy", "service": "agent-saas-boilerplate-backend"}

@app.get("/api/stream")
async def sse_subscribe(request: Request = None):
    """
    Subscribes the browser client to the Server-Sent Events (SSE) updates channel.
    Uses native StreamingResponse with text/event-stream media type.
    """
    # Create request placeholder if None (FastAPI DI fallback)
    from fastapi import Request as FastAPIRequest
    req = request if request else FastAPIRequest({"type": "http"})
    
    client_queue = sse_broadcaster.add_client()
    return StreamingResponse(
        sse_broadcaster.event_generator(req, client_queue),
        media_type="text/event-stream"
    )

# Async helper to execute the agent pipeline and stream updates
async def run_pipeline_task(task_description: str):
    logger.info(f"Pipeline: Starting task: '{task_description}'...")
    
    # 1. Define nodes
    planner = Node("Planner", [], "Create marketing campaign outline.")
    copywriter = Node("Copywriter", ["Planner"], "Draft promotional ad text.")
    image_generator = Node("ImageGenerator", ["Planner"], "Draft B-Roll asset prompt.")
    verifier = Node("Verifier", ["Copywriter", "ImageGenerator"], "Inspect content and check layout.")
    
    # 2. Build engine
    engine = DAGEngine([planner, copywriter, image_generator, verifier])
    
    # SSE tracking callback
    async def step_callback(node_name: str, status: str):
        # Publish real-time events to dashboard
        await sse_broadcaster.publish(
            "step_status", 
            {
                "node": node_name, 
                "status": status,
                "token_usage": {"input": 120, "output": 240},
                "run_cost_usd": 0.0018
            }
        )
        logger.info(f"SSE Broadcast: Node '{node_name}' status changed to '{status}'")

    try:
        # Wrap the execution in our Circuit Breaker to ensure safety under API load
        async def execute_call():
            return await engine.execute_graph(
                {"task": task_description}, 
                step_callback
            )

        # Triggers execution
        final_state = await llm_breaker.call(execute_call)
        
        # Publish final success event
        await sse_broadcaster.publish(
            "run_complete", 
            {
                "status": "success", 
                "artifacts": final_state["packaged_artifacts"]
            }
        )
        logger.info("Pipeline: Completed successfully.")
        
    except CircuitBreakerOpenException:
        logger.error("Pipeline: Blocked by active Circuit Breaker.")
        await sse_broadcaster.publish(
            "run_complete", 
            {
                "status": "failed", 
                "reason": "Upstream LLM API down. Circuit breaker active."
            }
        )
    except Exception as e:
        logger.error(f"Pipeline: execution error ({e})")
        await sse_broadcaster.publish(
            "run_complete", 
            {
                "status": "failed", 
                "reason": str(e)
            }
        )

@app.post("/api/run-pipeline")
async def trigger_pipeline(payload: dict, background_tasks: BackgroundTasks):
    """
    Triggers a long-running agent DAG workflow.
    Fires task asynchronously in the background and returns run token immediately.
    """
    task = payload.get("task", "Generate marketing campaign")
    
    # Add task to background executor so HTTP thread is freed instantly
    background_tasks.add_task(run_pipeline_task, task)
    
    return {
        "status": "queued",
        "run_id": "run_test_12345",
        "message": "Agent pipeline execution triggered in background. Subscribe to /api/stream for real-time updates."
    }

# Mock API request injection for dependency validation
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
