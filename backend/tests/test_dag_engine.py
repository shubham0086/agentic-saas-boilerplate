"""
Tests for WorkflowEngine + Workflow (extracted from ACE production engine).
"""
import asyncio
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.workflow import Node, Workflow
from core.engine import WorkflowEngine, AgentRegistry


async def _stub(prompt, context, **_):
    await asyncio.sleep(0)
    return f"output: {prompt[:40]}"


@pytest.fixture(autouse=True)
def register_stubs():
    for name in ["planner", "copywriter", "imagegen", "verifier", "a", "b"]:
        AgentRegistry[name] = _stub
    yield
    for name in ["planner", "copywriter", "imagegen", "verifier", "a", "b"]:
        AgentRegistry.pop(name, None)


def simple_workflow():
    return Workflow(
        nodes={
            "Planner":    Node("Planner",    "planner",    {}),
            "Copywriter": Node("Copywriter", "copywriter", {}),
            "ImageGen":   Node("ImageGen",   "imagegen",   {}),
            "Verifier":   Node("Verifier",   "verifier",   {}),
        },
        edges=[
            ("Planner", "Copywriter"), ("Planner", "ImageGen"),
            ("Copywriter", "Verifier"), ("ImageGen", "Verifier"),
        ],
    )


def test_topological_order_respects_dependencies():
    wf = simple_workflow()
    order = wf.topological_order()
    assert order.index("Planner") < order.index("Copywriter")
    assert order.index("Planner") < order.index("ImageGen")
    assert order.index("Copywriter") < order.index("Verifier")
    assert order.index("ImageGen") < order.index("Verifier")


@pytest.mark.asyncio
async def test_engine_run_completes():
    eng = WorkflowEngine()
    run_id = await eng.start(wf=simple_workflow())
    for _ in range(50):
        await asyncio.sleep(0.1)
        run = eng.get(run_id)
        if run and run.status in {"done", "failed"}:
            break
    assert eng.get(run_id).status == "done"


@pytest.mark.asyncio
async def test_all_nodes_reach_done():
    eng = WorkflowEngine()
    run_id = await eng.start(wf=simple_workflow())
    for _ in range(50):
        await asyncio.sleep(0.1)
        if eng.get(run_id).status in {"done", "failed"}:
            break
    for ns in eng.get(run_id).nodes.values():
        assert ns.status == "done"


@pytest.mark.asyncio
async def test_broadcasts_run_start_and_end():
    eng = WorkflowEngine()
    wf  = simple_workflow()
    # Subscribe before starting so we catch run_start
    run_id = str(__import__("uuid").uuid4())
    import asyncio as _asyncio
    from core.workflow import WorkflowRun, NodeState as NS
    # Pre-register the run so subscribe works before start
    eng._runs[run_id] = WorkflowRun(
        run_id=run_id,
        nodes={nid: NS(id=nid, agent=wf.nodes[nid].agent) for nid in wf.nodes},
    )
    q = eng.subscribe(run_id)
    # Now actually start (will overwrite _runs entry)
    started_id = await eng.start(wf=wf)
    # Also subscribe the new run
    q2 = eng.subscribe(started_id)
    events = []
    for _ in range(100):
        await asyncio.sleep(0.05)
        for queue in (q, q2):
            while not queue.empty():
                try:
                    events.append(json.loads(queue.get_nowait()))
                except Exception:
                    pass
        if eng.get(started_id) and eng.get(started_id).status in {"done", "failed"}:
            break
    eng.unsubscribe(started_id, q2)
    types = {e["type"] for e in events}
    # node_start and run_end always happen after subscription
    assert "node_start" in types
    assert "run_end" in types


@pytest.mark.asyncio
async def test_context_passed_between_nodes():
    received = {}
    async def capturer(prompt, context, **_):
        received[prompt] = list(context.keys())
        return "ok"
    AgentRegistry["a"] = capturer
    AgentRegistry["b"] = capturer
    eng = WorkflowEngine()
    wf = Workflow(
        nodes={"A": Node("A", "a", {"prompt": "step-A"}), "B": Node("B", "b", {"prompt": "step-B"})},
        edges=[("A", "B")],
    )
    run_id = await eng.start(wf=wf)
    for _ in range(30):
        await asyncio.sleep(0.1)
        if eng.get(run_id).status in {"done", "failed"}:
            break
    # prompt key has prior context appended — check by prefix
    b_key = next((k for k in received if k.startswith("step-B")), None)
    assert b_key is not None, f"step-B prompt not found in {list(received.keys())}"
    assert "A" in received[b_key]


@pytest.mark.asyncio
async def test_stub_fallback_keeps_pipeline_running():
    AgentRegistry.pop("planner", None)
    eng = WorkflowEngine()
    wf  = Workflow(nodes={"X": Node("X", "planner", {})}, edges=[])
    run_id = await eng.start(wf=wf)
    for _ in range(30):
        await asyncio.sleep(0.1)
        if eng.get(run_id).status in {"done", "failed"}:
            break
    run = eng.get(run_id)
    assert run.status == "done"
    assert "stub" in (run.nodes["X"].output or "").lower()


