"""
Workflow data structures — extracted from ace-engine/app/services/workflows/core.py

Node, Workflow, NodeState, WorkflowRun are the canonical state objects
that flow through the entire execution engine.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict, deque


@dataclass
class Node:
    id: str
    agent: str                           # matches a key in AgentRegistry
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    nodes: Dict[str, Node]
    edges: List[Tuple[str, str]]         # (from_node_id, to_node_id)

    def topological_order(self) -> List[str]:
        """Kahn's algorithm — returns nodes in dependency order."""
        indeg: Dict[str, int] = defaultdict(int)
        adj:   Dict[str, List[str]] = defaultdict(list)

        for u, v in self.edges:
            adj[u].append(v)
            indeg[v] += 1
            indeg.setdefault(u, 0)

        q = deque([n for n in self.nodes if indeg.get(n, 0) == 0])
        order, seen = [], set()

        while q:
            u = q.popleft()
            if u in seen:
                continue
            seen.add(u)
            order.append(u)
            for w in adj[u]:
                indeg[w] -= 1
                if indeg[w] == 0:
                    q.append(w)

        # Fallback to insertion order if graph has issues
        return order if len(order) == len(self.nodes) else list(self.nodes.keys())


@dataclass
class NodeState:
    id: str
    agent: str
    status: str = "pending"              # pending | running | done | failed
    output: Optional[str] = None
    error: Optional[str] = None
    prompt_used: Optional[str] = None


@dataclass
class WorkflowRun:
    run_id: str
    status: str = "running"             # running | done | failed
    nodes: Dict[str, NodeState] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    aggregated_output: Optional[str] = None
    deliverables: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
