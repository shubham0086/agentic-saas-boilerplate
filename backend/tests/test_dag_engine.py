import asyncio
import pytest
from dag_engine import Node, DAGEngine


def make_engine(*node_specs):
    nodes = [Node(name, deps, f"{name} prompt") for name, deps in node_specs]
    return DAGEngine(nodes)


# --- has_cycles ---

def test_no_cycles_linear():
    engine = make_engine(("A", []), ("B", ["A"]), ("C", ["B"]))
    assert engine.has_cycles() is False


def test_no_cycles_parallel_merge():
    engine = make_engine(("A", []), ("B", ["A"]), ("C", ["A"]), ("D", ["B", "C"]))
    assert engine.has_cycles() is False


def test_detects_cycle():
    engine = make_engine(("A", ["C"]), ("B", ["A"]), ("C", ["B"]))
    assert engine.has_cycles() is True


def test_single_node_no_cycle():
    engine = make_engine(("Solo", []))
    assert engine.has_cycles() is False


# --- execute_graph ---

@pytest.mark.asyncio
async def test_execute_linear_chain():
    engine = make_engine(("A", []), ("B", ["A"]))
    state = await engine.execute_graph({"task": "test"})
    names = [r["node"] for r in state["execution_log"]]
    assert names.index("A") < names.index("B")


@pytest.mark.asyncio
async def test_execute_parallel_nodes():
    engine = make_engine(("A", []), ("B", []), ("C", ["A", "B"]))
    state = await engine.execute_graph({"task": "parallel"})
    names = [r["node"] for r in state["execution_log"]]
    assert set(names) == {"A", "B", "C"}
    assert names.index("C") > max(names.index("A"), names.index("B"))


@pytest.mark.asyncio
async def test_execute_produces_artifacts():
    engine = make_engine(("Writer", []), ("Editor", ["Writer"]))
    state = await engine.execute_graph({"task": "content"})
    artifacts = state["packaged_artifacts"]
    assert artifacts["file_count"] == 2
    assert "Writer_output.txt" in artifacts["artifacts"]
    assert "Editor_output.txt" in artifacts["artifacts"]


@pytest.mark.asyncio
async def test_execute_raises_on_cycle():
    engine = make_engine(("X", ["Z"]), ("Y", ["X"]), ("Z", ["Y"]))
    with pytest.raises(ValueError, match="cycle"):
        await engine.execute_graph({})


@pytest.mark.asyncio
async def test_callback_fired_for_each_node():
    engine = make_engine(("A", []), ("B", ["A"]))
    events = []

    async def cb(node, status):
        events.append((node, status))

    await engine.execute_graph({"task": "t"}, cb)
    nodes_seen = {e[0] for e in events}
    assert nodes_seen == {"A", "B"}
