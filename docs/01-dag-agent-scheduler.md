# Learning Module 01: Designing a Zero-Dependency DAG Agent Scheduler

Multi-agent applications often need to execute complex, dependent workflows. Traditional systems use linear sequential execution (e.g., Agent A $\rightarrow$ Agent B $\rightarrow$ Agent C). However, real-world development and business tasks require parallel branching and conditional validation.

This guide explains how to design and build a lightweight, zero-dependency Directed Acyclic Graph (DAG) scheduler using **Kahn's Algorithm** for topological sorting and Python's native `asyncio` for parallel execution.

---

## 🏛️ Linear Chains vs. Directed Acyclic Graphs

In a linear chain, if Agent B and Agent C are independent of each other but both depend on Agent A, they must still execute one after the other. This wastes valuable execution time, especially when calling remote LLM APIs with latencies of 2–10 seconds.

A DAG allows tasks to be represented as **Nodes** and dependencies as **Directed Edges** (e.g., Node A $\rightarrow$ Node B). If multiple nodes have no outstanding dependencies, they can be scheduled to run in parallel.

```
      [ Planner ]
       /       \
      /         \
[ Copywriter ]  [ ImageGenerator ]  (Concurrent parallel execution)
      \         /
       \       /
      [ Verifier ]
```

---

## 📐 The Mathematics: Kahn's Algorithm

To schedule nodes, we must sort them topologically. A topological sort is an ordering of nodes where for every directed edge $U \rightarrow V$, node $U$ comes before node $V$ in the ordering. If the graph contains a cycle (e.g., A $\rightarrow$ B $\rightarrow$ A), no topological sort is possible, and the graph is invalid.

**Kahn's Algorithm** solves this in $O(V + E)$ time:
1.  Calculate the **in-degree** of every node (the number of incoming edges).
2.  Queue all nodes with an in-degree of `0` (nodes that have no dependencies).
3.  While the queue is not empty:
    *   Dequeue a node $U$ and add it to the execution list.
    *   For each neighbor $V$ of $U$ (nodes that depend on $U$), decrement its in-degree by 1.
    *   If $V$'s in-degree becomes `0`, add it to the queue.
4.  If the number of visited nodes does not equal the total number of nodes in the graph, a cycle exists, and execution must abort.

---

## 💻 Python Implementation

Here is the simplified implementation from `backend/dag_engine.py`:

### 1. Defining Node Contracts
Each node represents a specialized agent step:

```python
class Node:
    def __init__(self, name: str, dependencies: List[str], system_prompt: str):
        self.name = name
        self.dependencies = dependencies
        self.system_prompt = system_prompt

    async def execute(self, state: dict) -> dict:
        # Simulate execution payload / LLM connection
        await asyncio.sleep(2)
        return {"node": self.name, "output": "Success"}
```

### 2. Building the Scheduler
We build adjacency lists and in-degree maps:

```python
class DAGEngine:
    def __init__(self, nodes: List[Node]):
        self.nodes = {node.name: node for node in nodes}
        self.adjacency_list = {node.name: set() for node in nodes}
        self.in_degree = {node.name: 0 for node in nodes}
        self._build_graph()

    def _build_graph(self):
        for node in self.nodes.values():
            for dep in node.dependencies:
                self.adjacency_list[dep].add(node.name)
                self.in_degree[node.name] += 1
```

### 3. Concurrent Execution Loop
We run independent nodes concurrently using `asyncio.wait(..., return_when=FIRST_COMPLETED)` to instantly update in-degrees and start new ready nodes as soon as a parent node resolves:

```python
async def execute_graph(self, initial_state: dict):
    in_deg = self.in_degree.copy()
    queue = [name for name, deg in in_deg.items() if deg == 0]
    active_tasks = {}
    state = initial_state.copy()

    while queue or active_tasks:
        # Start all nodes with 0 dependencies
        for node_name in list(queue):
            if node_name not in active_tasks:
                node = self.nodes[node_name]
                active_tasks[node_name] = asyncio.create_task(node.execute(state))
                queue.remove(node_name)

        # Wait for any running node to finish
        done, _ = await asyncio.wait(active_tasks.values(), return_when=asyncio.FIRST_COMPLETED)

        # Process finished nodes and find new nodes with 0 in-degree
        for task in done:
            completed_node = [name for name, t in active_tasks.items() if t == task][0]
            result = task.result()
            del active_tasks[completed_node]

            for neighbor in self.adjacency_list[completed_node]:
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)
```

---

## 🎯 Verification Exercise
1. Run the test script `python backend/dag_engine.py`.
2. Confirm the console print logs: `Planner` executes first, then both `Copywriter` and `ImageGenerator` execute concurrently, and finally `Verifier` executes once both finish.
