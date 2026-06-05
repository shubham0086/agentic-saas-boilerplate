import time
import logging
from typing import Callable, Any

logger = logging.getLogger("circuit_breaker")

class CircuitBreakerOpenException(Exception):
    """Raised when request is blocked because the breaker is in OPEN state."""
    pass

class CircuitBreaker:
    """Implements state machine logic (CLOSED, OPEN, HALF_OPEN) to prevent API cascade blocks."""
    def __init__(self, name: str, failure_threshold: int = 2, recovery_timeout: float = 10.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failure_count = 0
        self.last_failure_time = 0.0

    def _check_recovery(self):
        """Transition from OPEN to HALF_OPEN if cooling period expired."""
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info(f"CircuitBreaker '{self.name}': Recovery cooling period expired. Transited to HALF_OPEN.")

    async def call(self, async_func: Callable[..., Any], *args, **kwargs) -> Any:
        """Executes the wrapped asynchronous function and manages state updates."""
        self._check_recovery()

        if self.state == "OPEN":
            logger.warning(f"CircuitBreaker '{self.name}': Call blocked immediately (State: OPEN).")
            raise CircuitBreakerOpenException(f"Circuit breaker '{self.name}' is OPEN. API calls disabled.")

        try:
            # Execute wrapped network call
            result = await async_func(*args, **kwargs)
            
            # If we reached here, the call succeeded
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info(f"CircuitBreaker '{self.name}': Probe call succeeded. Reset to CLOSED.")
                
            return result

        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            logger.error(f"CircuitBreaker '{self.name}': Call failed ({e}). Failure count: {self.failure_count}")

            if self.state in ("CLOSED", "HALF_OPEN") and self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.error(f"CircuitBreaker '{self.name}': Failure threshold met. TRIPPED to OPEN.")

            raise e
            
# Self-test demonstration if executed directly
if __name__ == "__main__":
    import asyncio

    # Setup basic breaker
    breaker = CircuitBreaker("TestAPI", failure_threshold=2, recovery_timeout=3.0)

    # Simulated unstable API call
    should_fail = True
    async def fetch_data():
        if should_fail:
            raise ConnectionError("API connection timeout.")
        return "Success data"

    async def main():
        global should_fail
        
        # Call 1 (Will fail, breaker increments count)
        try:
            await breaker.call(fetch_data)
        except Exception:
            pass

        # Call 2 (Will fail, breaker trips to OPEN)
        try:
            await breaker.call(fetch_data)
        except Exception:
            pass

        # Call 3 (Will fail immediately because breaker is OPEN)
        try:
            await breaker.call(fetch_data)
        except CircuitBreakerOpenException as e:
            print(f"Catched Expected Block: {e}")

        # Wait for recovery cooling timeout
        print("Waiting for recovery cooling window...")
        await asyncio.sleep(4.0)

        # Call 4 (Breaker will be in HALF_OPEN, we fix API first)
        should_fail = False
        print("API healed. Probing breaker...")
        data = await breaker.call(fetch_data)
        print(f"Result: {data} (Breaker is now: {breaker.state})")

    asyncio.run(main())
