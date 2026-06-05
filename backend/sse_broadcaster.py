import json
import asyncio
import logging
from typing import Set
from fastapi import Request

logger = logging.getLogger("sse_broadcaster")

class EventBroadcaster:
    """Manages active Client connection queues and pushes real-time SSE updates."""
    def __init__(self):
        self.active_queues: Set[asyncio.Queue] = set()

    def add_client(self) -> asyncio.Queue:
        """Creates a queue for a new subscriber client."""
        queue = asyncio.Queue()
        self.active_queues.add(queue)
        logger.info(f"SSE: Client connected. Total active connections: {len(self.active_queues)}")
        return queue

    def remove_client(self, queue: asyncio.Queue):
        """Removes the queue for a disconnected client."""
        if queue in self.active_queues:
            self.active_queues.remove(queue)
            logger.info(f"SSE: Client disconnected. Total active connections: {len(self.active_queues)}")

    async def publish(self, event_type: str, data: dict):
        """Pushes an event payload to all active client queues concurrently."""
        if not self.active_queues:
            return

        payload = {
            "event": event_type,
            "data": data
        }
        
        # Add to all queues
        for queue in self.active_queues:
            await queue.put(payload)

    async def event_generator(self, request: Request, client_queue: asyncio.Queue):
        """
        Async generator reading from the client queue and yielding formatted SSE payloads.
        Includes a keep-alive ping loop to prevent network timeouts.
        """
        try:
            while True:
                # Disconnect check (if client closed tab/connection)
                if await request.is_disconnected():
                    logger.info("SSE: Client connection drop detected by gateway.")
                    break

                try:
                    # Wait for next event with a timeout (keep-alive mechanism)
                    event = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                    
                    # Format as standard Server-Sent Event block
                    # format:
                    # event: eventName\n
                    # data: {"json": "payload"}\n\n
                    yield f"event: {event['event']}\n"
                    yield f"data: {json.dumps(event['data'])}\n\n"
                    client_queue.task_done()
                    
                except asyncio.TimeoutError:
                    # Send a keep-alive comment block to keep the TCP connection alive
                    yield ": ping\n\n"

        except Exception as e:
            logger.error(f"Error in SSE event stream generator: {e}")
        finally:
            self.remove_client(client_queue)
