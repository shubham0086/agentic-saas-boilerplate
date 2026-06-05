import asyncio
import pytest
from circuit_breaker import CircuitBreaker, CircuitBreakerOpenException


async def success():
    return "ok"


async def fail():
    raise ConnectionError("boom")


@pytest.mark.asyncio
async def test_initial_state_is_closed():
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=10.0)
    assert cb.state == "CLOSED"


@pytest.mark.asyncio
async def test_passes_through_on_success():
    cb = CircuitBreaker("test", failure_threshold=2)
    result = await cb.call(success)
    assert result == "ok"
    assert cb.state == "CLOSED"
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_increments_failure_count():
    cb = CircuitBreaker("test", failure_threshold=3)
    with pytest.raises(ConnectionError):
        await cb.call(fail)
    assert cb.failure_count == 1
    assert cb.state == "CLOSED"


@pytest.mark.asyncio
async def test_trips_to_open_at_threshold():
    cb = CircuitBreaker("test", failure_threshold=2)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await cb.call(fail)
    assert cb.state == "OPEN"


@pytest.mark.asyncio
async def test_open_state_blocks_calls():
    cb = CircuitBreaker("test", failure_threshold=1)
    with pytest.raises(ConnectionError):
        await cb.call(fail)
    assert cb.state == "OPEN"
    with pytest.raises(CircuitBreakerOpenException):
        await cb.call(success)


@pytest.mark.asyncio
async def test_recovery_to_half_open(monkeypatch):
    import time
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=5.0)
    with pytest.raises(ConnectionError):
        await cb.call(fail)
    assert cb.state == "OPEN"

    # Simulate elapsed time past recovery_timeout
    monkeypatch.setattr(time, "time", lambda: cb.last_failure_time + 10.0)
    cb._check_recovery()
    assert cb.state == "HALF_OPEN"


@pytest.mark.asyncio
async def test_half_open_success_resets_to_closed(monkeypatch):
    import time
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=5.0)
    with pytest.raises(ConnectionError):
        await cb.call(fail)

    monkeypatch.setattr(time, "time", lambda: cb.last_failure_time + 10.0)
    cb._check_recovery()
    assert cb.state == "HALF_OPEN"

    result = await cb.call(success)
    assert result == "ok"
    assert cb.state == "CLOSED"
    assert cb.failure_count == 0
