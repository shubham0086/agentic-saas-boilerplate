import asyncio
import pytest
from sse_broadcaster import EventBroadcaster


@pytest.mark.asyncio
async def test_add_client_returns_queue():
    broadcaster = EventBroadcaster()
    q = broadcaster.add_client()
    assert q is not None
    assert len(broadcaster.active_queues) == 1


@pytest.mark.asyncio
async def test_remove_client():
    broadcaster = EventBroadcaster()
    q = broadcaster.add_client()
    broadcaster.remove_client(q)
    assert len(broadcaster.active_queues) == 0


@pytest.mark.asyncio
async def test_publish_delivers_to_all_clients():
    broadcaster = EventBroadcaster()
    q1 = broadcaster.add_client()
    q2 = broadcaster.add_client()

    await broadcaster.publish("test_event", {"value": 42})

    msg1 = q1.get_nowait()
    msg2 = q2.get_nowait()
    assert msg1["event"] == "test_event"
    assert msg1["data"]["value"] == 42
    assert msg2["data"]["value"] == 42


@pytest.mark.asyncio
async def test_publish_no_clients_does_not_raise():
    broadcaster = EventBroadcaster()
    await broadcaster.publish("event", {"key": "val"})  # should not raise


@pytest.mark.asyncio
async def test_multiple_events_queue_in_order():
    broadcaster = EventBroadcaster()
    q = broadcaster.add_client()

    await broadcaster.publish("first", {"n": 1})
    await broadcaster.publish("second", {"n": 2})

    e1 = q.get_nowait()
    e2 = q.get_nowait()
    assert e1["event"] == "first"
    assert e2["event"] == "second"
