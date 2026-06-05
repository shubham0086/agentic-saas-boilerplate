# 🔮 Future Plans & Roadmap: Enterprise Scaling Techniques

The current implementation of **Agent-SaaS-Boilerplate** provides the foundational infrastructure (DAG scheduling, SSE streaming, and secure geo-routed payment billing) needed to launch a multi-agent SaaS. 

This document serves as an advanced engineering roadmap, detailing 5 production-hardened scaling techniques (numbered 4 to 8) tested in our core platforms to be added in future iterations:

---

## 4. Step-Level Resumption & State Hydration (Save-State Engine)
*   **The Concept**: Long-horizon agent runs (e.g. running 7–10 nodes in a complex graph) represent substantial API costs and execution time. If Node 6 fails due to a temporary network timeout, restarting the entire pipeline from Node 1 is extremely wasteful.
*   **The Implementation**:
    *   Implement a database schema (`dag_runs`) that records the serialized JSON representation of the `Blackboard` state and accumulated artifacts at the completion of every single node.
    *   Expose a `/api/run-pipeline/resume` endpoint accepting a `run_id`.
    *   The scheduler checks the database for the last successfully completed step, hydrates the state, and triggers the DAG executor to resume execution exactly at the failed node.
*   **Why It Matters**: Prevents duplicate billing, saves token spend, and enhances UX during API outages.

## 5. Dynamic Token Cost Optimizer & Budget Guard
*   **The Concept**: AI agents running in recursive loops or digesting large raw web scrapes can run up massive API bills within minutes. A secure SaaS must protect both the operator's balance and user quotas.
*   **The Implementation**:
    *   **Context Pruning**: Implement a text-processing utility that strips redundant whitespace, comments, and boilerplate HTML from crawled research content before passing it to LLM prompts.
    *   **Token Estimation**: Integrate `tiktoken` (for OpenAI) or similar local tokenizer libraries to calculate precise input/output token counts pre-flight.
    *   **Budget Guard**: Set a hard maximum cost limit (e.g. `$0.10` USD) on each pipeline trigger. If the accumulative cost calculated during execution crosses this threshold, the `dag_engine` terminates the run immediately and logs a `BudgetExceededError`.
*   **Why It Matters**: Prevents infinite loops from draining your API balances.

## 6. Concurrency Locks for Parallel Node Execution (Blackboard Mutex)
*   **The Concept**: When executing independent nodes concurrently in the DAG (e.g., running `DeveloperAgent` and `TesterAgent` at the same time), both agents will attempt to read and write to the shared memory or write local files. Without protection, this leads to race conditions and corrupted data.
*   **The Implementation**:
    *   Introduce an asynchronous lock manager (`BlackboardMutex`) or utilize Redis-based distributed locks (`Redlock`).
    *   Ensure any node attempting to write back to the shared state dictionary must acquire the lock:
        ```python
        async with state_lock:
            state["notes"].append(new_note)
        ```
*   **Why It Matters**: Guarantees data consistency and prevents state corruption during concurrent agent operations.

## 7. Adaptive Rate-Limit Backoff (429 Interceptor)
*   **The Concept**: High-throughput multi-agent systems quickly exhaust model rate-limit limits (RPM/TPM), returning `HTTP 429 (Too Many Requests)` errors mid-run.
*   **The Implementation**:
    *   Create a request decorator or interceptor wrapping the HTTP client.
    *   If a 429 status code is received, inspect the headers (e.g. `x-ratelimit-reset-requests`, `retry-after`).
    *   If reset headers exist, parse them and pause the thread for that duration. If not, schedule retries using **Exponential Backoff with Jitter** (randomized sleep windows to prevent thundering-herd issues on the gateway).
*   **Why It Matters**: Prevents entire runs from failing due to simple rate limit spikes.

## 8. Sandboxed Workspace Isolation (Multi-User Workspaces)
*   **The Concept**: Multiple tenants running agent scripts simultaneously on the same server must be strictly isolated at the OS and folder levels to prevent directory traversal exploits.
*   **The Implementation**:
    *   For every triggered run, the workspace manager creates a dedicated folder in a temporary mount: `/tmp/workspaces/run-<id>/`.
    *   All agent file read/write operations must resolve path strings relative to this sandbox.
    *   Verify paths before execution using:
        ```python
        resolved_path = os.path.abspath(target_path)
        if not resolved_path.startswith(sandbox_root):
            raise PermissionError("Access outside workspace forbidden.")
        ```
*   **Why It Matters**: Ensures multi-user security, privacy, and compliance.
