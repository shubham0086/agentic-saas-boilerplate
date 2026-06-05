"""
WorkflowEngine — extracted from ace-engine/app/services/workflows/engine.py

Manages run lifecycle: start, execute, broadcast, deliver.

Production features preserved:
  - Per-run subscriber queues (not global broadcast — each client subscribes to a run_id)
  - Task reference set to prevent garbage collection mid-execution
  - 5-minute timeout with clean failure broadcast
  - _compact_context(): passes last N node outputs as context to the next agent
  - Deliverables system: agent outputs are packaged and available for download
  - "summarizer" pseudo-agent: local text summarization without an LLM call

The one production dependency removed: get_orchestrator() is replaced by
AgentRegistry — a dict of async callables keyed by agent name. Register
your agent functions before starting runs.

  from core.engine import engine, AgentRegistry

  async def my_planner(prompt, context, **params):
      # call your LLM here
      return "plan output"

  engine.registry["planner"] = my_planner
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import textwrap
import uuid
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .workflow import Node, NodeState, Workflow, WorkflowRun

logger = logging.getLogger("workflow_engine")

# Users register agent callables here: name -> async fn(prompt, context, **params) -> str
AgentRegistry: Dict[str, Callable[..., Coroutine[Any, Any, str]]] = {}

WORKFLOW_TIMEOUT_SECONDS = 300
BUILDS_DIR = Path("builds")


class WorkflowEngine:
    """
    Executes Workflow graphs with per-run SSE subscriber queues.

    Flow:
      run_id = await engine.start(wf=workflow)
      queue  = engine.subscribe(run_id)        # in your SSE handler
      ...                                       # queue receives JSON event strings
      engine.unsubscribe(run_id, queue)

    Events broadcast per run:
      {"type": "run_start"}
      {"type": "node_start",  "node": id, "agent": name, "index": int}
      {"type": "node_done",   "node": id, "status": "done"|"failed", "preview": str}
      {"type": "zip_created", "zip_path": str, "file_count": int}
      {"type": "run_end",     "status": "done"|"failed"}
    """

    def __init__(self) -> None:
        self._runs:  Dict[str, WorkflowRun]         = {}
        self._subs:  Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self._tasks: set                             = set()
        self._lock   = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, run_id: str) -> Optional[WorkflowRun]:
        return self._runs.get(run_id)

    def list_runs(self) -> List[Dict[str, Any]]:
        return [
            {"run_id": r.run_id, "status": r.status, "nodes": len(r.nodes)}
            for r in self._runs.values()
        ]

    def subscribe(self, run_id: str) -> asyncio.Queue:
        """Get a queue that receives all events for this run."""
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subs[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(run_id) or []
        if q in subs:
            subs.remove(q)
        try:
            q.put_nowait(None)     # unblock any waiting consumer
        except Exception:
            pass

    async def start(self, *, wf: Workflow) -> str:
        run_id = str(uuid.uuid4())
        async with self._lock:
            self._runs[run_id] = WorkflowRun(
                run_id=run_id,
                nodes={nid: NodeState(id=nid, agent=wf.nodes[nid].agent) for nid in wf.nodes},
            )

        task = asyncio.create_task(self._run_with_timeout(run_id, wf))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        await self._broadcast(run_id, {"type": "run_start"})
        return run_id

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _broadcast(self, run_id: str, evt: Dict[str, Any]) -> None:
        evt.setdefault("ts", datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z")
        evt.setdefault("run_id", run_id)
        payload = json.dumps(evt, ensure_ascii=False)
        for q in list(self._subs.get(run_id) or []):
            try:
                await q.put(payload)
            except Exception:
                try:
                    self._subs[run_id].remove(q)
                except Exception:
                    pass

    async def _run_with_timeout(self, run_id: str, wf: Workflow) -> None:
        try:
            async with asyncio.timeout(WORKFLOW_TIMEOUT_SECONDS):
                await self._execute(run_id, wf)
        except asyncio.TimeoutError:
            logger.error(f"Run {run_id} timed out after {WORKFLOW_TIMEOUT_SECONDS}s")
            run = self._runs.get(run_id)
            if run:
                run.status = "failed"
                for ns in run.nodes.values():
                    if ns.status == "running":
                        ns.status = "failed"
                        ns.error = f"Timeout after {WORKFLOW_TIMEOUT_SECONDS}s"
                await self._broadcast(run_id, {"type": "run_end", "status": "failed",
                                               "error": f"Timeout after {WORKFLOW_TIMEOUT_SECONDS}s"})
        except Exception as e:
            logger.error(f"Run {run_id} failed: {e}")
            run = self._runs.get(run_id)
            if run:
                run.status = "failed"
                await self._broadcast(run_id, {"type": "run_end", "status": "failed", "error": str(e)})

    async def _execute(self, run_id: str, wf: Workflow) -> None:
        run = self._runs[run_id]
        try:
            order = wf.topological_order()

            for idx, nid in enumerate(order):
                node   = wf.nodes[nid]
                nstate = run.nodes[nid]
                nstate.status = "running"
                await self._broadcast(run_id, {
                    "type": "node_start", "node": nid, "agent": node.agent, "index": idx
                })

                base_prompt = node.params.get("prompt") or f"Execute role: {node.agent}"
                use_ctx     = node.params.get("use_context", True)

                # "summarizer" is a built-in pseudo-agent — no LLM call needed
                if node.agent == "summarizer":
                    ctx_blob = self._compact_context(run, order[:idx], last_n=4, max_chars=2000)
                    summary  = self._local_summary((ctx_blob or "") + "\n" + base_prompt)
                    nstate.prompt_used = "[local-summarizer]"
                    nstate.output      = summary
                    nstate.status      = "done"
                    run.context["summary"] = summary
                    run.context[nid]       = {"agent": node.agent, "output": summary}
                    await self._broadcast(run_id, {"type": "node_done", "node": nid, "status": "done"})
                    self._runs[run_id] = run
                    continue

                ctx_block = self._compact_context(run, order[:idx]) if use_ctx else ""
                prompt    = base_prompt + (ctx_block if ctx_block else "")
                nstate.prompt_used = prompt

                try:
                    out = await self._call_agent(node, prompt, run.context)

                    nstate.status = "done"
                    nstate.output = out
                    run.context[nid] = {"agent": node.agent, "output": out}

                    # Collect deliverables from code/design agents
                    agent_key = node.agent.removesuffix("_agent")
                    if agent_key in {"implementer", "code_generator", "designer", "copywriter"} and len(out or "") > 200:
                        ext = "html" if "<html" in out.lower() else "txt"
                        run.deliverables.append({
                            "type": "code" if agent_key in {"implementer", "code_generator"} else "content",
                            "path": f"{agent_key}_output.{ext}",
                            "content": out,
                            "agent": agent_key,
                        })

                    await self._broadcast(run_id, {
                        "type": "node_done", "node": nid, "status": "done",
                        "preview": (out[:120] + "…" if out and len(out) > 120 else out or ""),
                    })

                except Exception as e:
                    logger.error(f"Agent {node.agent} failed: {e}")
                    nstate.status = "failed"
                    nstate.error  = f"{type(e).__name__}: {e}"
                    run.status    = "failed"
                    await self._broadcast(run_id, {
                        "type": "node_done", "node": nid, "status": "failed", "error": nstate.error
                    })
                    self._runs[run_id] = run
                    await self._broadcast(run_id, {"type": "run_end", "status": "failed"})
                    return

            # Aggregate final output from last 3 nodes
            run.aggregated_output = "\n\n".join(
                run.nodes[n].output or ""
                for n in order[-3:]
                if run.nodes[n].output
            ).strip()

            if run.deliverables:
                await self._package_zip(run_id, run)

            run.status = "done"

        finally:
            self._runs[run_id] = run
            await self._broadcast(run_id, {"type": "run_end", "status": run.status})

    async def _call_agent(self, node: Node, prompt: str, context: Dict[str, Any]) -> str:
        """
        Dispatch to a registered agent function.
        Falls back to a stub if the agent isn't registered yet — useful during dev.
        Replace stubs with real LLM calls by registering your functions in AgentRegistry.
        """
        fn = AgentRegistry.get(node.agent)
        if fn:
            return await fn(prompt=prompt, context=context, **{
                k: v for k, v in node.params.items() if k not in {"prompt", "use_context"}
            })

        # Stub: logs a warning and returns a placeholder so the pipeline keeps running
        logger.warning(f"No agent registered for '{node.agent}' — returning stub output")
        await asyncio.sleep(0.1)
        return f"[{node.agent}] stub output — register a real function in AgentRegistry"

    def _compact_context(self, run: WorkflowRun, order: List[str],
                         last_n: int = 2, max_chars: int = 1500) -> str:
        """Summarise the last N completed node outputs into a context block."""
        recent = []
        for nid in reversed(order):
            st = run.nodes.get(nid)
            if not st or st.status != "done" or not (st.output or "").strip():
                continue
            snippet = (st.output or "")[:200]
            if len(st.output or "") > 200:
                snippet += "…"
            recent.append(f"- {nid} ({st.agent}): {snippet}")
            if len(recent) >= last_n:
                break
        blob = "\n".join(reversed(recent))
        if not blob:
            return ""
        if len(blob) > max_chars:
            blob = blob[-max_chars:]
        return "\n\n### Prior context\n" + blob

    def _local_summary(self, text: str, max_lines: int = 10, max_chars: int = 1000) -> str:
        text = " ".join(text.split())
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        lines = textwrap.wrap(text, 110)[:max_lines]
        return "[SUMMARY]\n" + "\n".join(lines)

    async def _package_zip(self, run_id: str, run: WorkflowRun) -> None:
        try:
            BUILDS_DIR.mkdir(exist_ok=True)
            zip_path = BUILDS_DIR / f"{run_id}.zip"

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                readme = (
                    f"# Run {run_id}\n"
                    f"Generated: {datetime.datetime.utcnow().isoformat()}Z\n\n"
                    "## Files\n"
                    + "\n".join(f"- {d['path']}: {d['type']} from {d['agent']}" for d in run.deliverables)
                )
                zf.writestr("README.md", readme)
                for d in run.deliverables:
                    zf.writestr(d["path"], d.get("content", ""))
                if run.aggregated_output:
                    zf.writestr("workflow_output.txt", run.aggregated_output)

            run.artifacts["zip"]       = str(zip_path)
            run.artifacts["zip_exists"] = zip_path.exists()

            await self._broadcast(run_id, {
                "type": "zip_created",
                "zip_path": str(zip_path),
                "file_count": len(run.deliverables) + 1,
            })
        except Exception as e:
            await self._broadcast(run_id, {"type": "zip_error", "error": str(e)})


# Module-level singleton — import and use directly
engine = WorkflowEngine()
