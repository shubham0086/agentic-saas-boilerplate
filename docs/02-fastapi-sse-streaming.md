# Learning Module 02: Implementing Real-Time Observability Streaming (FastAPI + SSE)

AI workflows (running agents, searching webs, compiling code, rendering videos) take time. Waiting 15 to 90 seconds for an HTTP response leads to browser timeouts and a horrible user experience.

This guide explains how to stream real-time updates from your background AI engine directly to a browser client using **Server-Sent Events (SSE)** inside **FastAPI**, bypassing the complexity of full-duplex WebSockets.

---

## 📡 Polling vs. WebSockets vs. SSE

| Dimension | HTTP Short Polling | WebSockets | Server-Sent Events (SSE) |
| :--- | :--- | :--- | :--- |
| **Protocol** | Standard HTTP | ws:// (TCP Upgrade) | Standard HTTP |
| **Direction** | Unidirectional (Client $\rightarrow$ Server) | Bidirectional (Duplex) | Unidirectional (Server $\rightarrow$ Client) |
| **Complexity** | Low (wasteful request spam) | High (custom frame handlers) | Low (Uses standard Web API stream) |
| **Reconnection** | Manual | Manual | Automatic (browser-native) |
| **Firewall Friendliness**| Yes | No (often blocked by proxies)| Yes |

Since AI agent execution state tracking is **unidirectional** (the server pushes progress updates, the client merely listens and displays them), **SSE** is the optimal design choice.

---

## ⚙️ How SSE Works (Under the Hood)
SSE is a standard HTTP protocol defined under HTML5. The client initiates a standard HTTP GET request with the header `Accept: text/event-stream`. The server keeps this connection open and streams messages formatted as simple text blocks:

```txt
event: step_status
data: {"node": "Planner", "status": "running"}

event: step_status
data: {"node": "Planner", "status": "success"}

: ping
```
*   `event:` specifies the channel name (helps client filter messages).
*   `data:` contains the stringified JSON payload.
*   `: comment` blocks (such as `: ping`) are ignored by the browser but keep connection routers from closing idle links.

---

## 💻 Backend Implementation in FastAPI

We manage active client connections in `backend/sse_broadcaster.py` by maintaining a list of asynchronous queues:

### 1. The Broadcaster Class
```python
class EventBroadcaster:
    def __init__(self):
        self.active_queues: Set[asyncio.Queue] = set()

    def add_client(self) -> asyncio.Queue:
        queue = asyncio.Queue()
        self.active_queues.add(queue)
        return queue

    async def publish(self, event_type: str, data: dict):
        payload = {"event": event_type, "data": data}
        for queue in self.active_queues:
            await queue.put(payload)
```

### 2. The Stream Router
In `backend/main.py`, we expose a `/api/stream` endpoint returning a FastAPI `StreamingResponse`:

```python
@app.get("/api/stream")
async def sse_subscribe(request: Request):
    client_queue = sse_broadcaster.add_client()
    return StreamingResponse(
        sse_broadcaster.event_generator(request, client_queue),
        media_type="text/event-stream"
    )
```

---

## 🖥️ Frontend Implementation (Vanilla JavaScript)

Connecting the browser is incredibly simple using the native `EventSource` web API:

```javascript
// 1. Establish SSE stream link
const eventSource = new EventSource("http://localhost:8000/api/stream");

// 2. Listen to named event channels
eventSource.addEventListener("step_status", (event) => {
  const payload = JSON.parse(event.data);
  const { node, status } = payload;
  
  console.log(`Node ${node} updated to ${status}`);
  // Update visual style elements on screen
});

eventSource.addEventListener("run_complete", (event) => {
  const payload = JSON.parse(event.data);
  console.log("Run completed successfully: ", payload.artifacts);
});

// 3. Graceful cleanup
window.addEventListener("beforeunload", () => {
  eventSource.close();
});
```

---

## 🎯 Verification Exercise
1. Start the FastAPI backend and open `frontend/index.html` in your browser.
2. Click "Execute Agent Workflow".
3. Check the developer console network tab: verify that a single persistent connection named `stream` stays open, and inspect the incoming raw events as they fire.
