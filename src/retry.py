import asyncio
import logging

logger = logging.getLogger(__name__)

_NO_RETRY = (ValueError, TypeError, KeyError)


async def with_retry(
    fn,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
):
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except _NO_RETRY:
            raise
        except Exception as e:
            last_error = e
            if attempt == max_attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.warning("Retry %d/%d after %.1fs: %s", attempt, max_attempts, delay, e)
            await asyncio.sleep(delay)
    raise last_error
