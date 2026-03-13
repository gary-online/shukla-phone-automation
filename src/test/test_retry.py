import asyncio
import time

import pytest

from src.retry import with_retry


@pytest.mark.asyncio
async def test_succeeds_first_try():
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await with_retry(fn)
    assert result == "ok"
    assert call_count == 1


@pytest.mark.asyncio
async def test_succeeds_second_try():
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient")
        return "ok"

    result = await with_retry(fn, base_delay=0.01)
    assert result == "ok"
    assert call_count == 2


@pytest.mark.asyncio
async def test_exhausts_attempts():
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("always fails")

    with pytest.raises(RuntimeError, match="always fails"):
        await with_retry(fn, max_attempts=3, base_delay=0.01)
    assert call_count == 3


@pytest.mark.asyncio
async def test_no_retry_on_value_error():
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        raise ValueError("bad value")

    with pytest.raises(ValueError, match="bad value"):
        await with_retry(fn)
    assert call_count == 1


@pytest.mark.asyncio
async def test_no_retry_on_type_error():
    call_count = 0

    async def fn():
        nonlocal call_count
        call_count += 1
        raise TypeError("bad type")

    with pytest.raises(TypeError, match="bad type"):
        await with_retry(fn)
    assert call_count == 1


@pytest.mark.asyncio
async def test_exponential_backoff_timing():
    """Verify delays grow exponentially: ~0.1s, ~0.2s."""
    call_count = 0
    timestamps = []

    async def fn():
        nonlocal call_count
        call_count += 1
        timestamps.append(time.monotonic())
        if call_count < 3:
            raise RuntimeError("transient")
        return "ok"

    result = await with_retry(fn, max_attempts=3, base_delay=0.1, max_delay=10.0)
    assert result == "ok"
    assert call_count == 3

    delay1 = timestamps[1] - timestamps[0]
    delay2 = timestamps[2] - timestamps[1]

    # First delay should be ~0.1s (base_delay * 2^0)
    assert 0.08 <= delay1 <= 0.3
    # Second delay should be ~0.2s (base_delay * 2^1)
    assert 0.15 <= delay2 <= 0.5
    # Second delay should be roughly double the first
    assert delay2 > delay1 * 1.3
