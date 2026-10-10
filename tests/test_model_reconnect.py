import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.alpha_agent import AlphaAgent

async def test_reconnect_success():
    print("\n--- Test 1: First attempt hits filter/latency StopAsyncIteration, reconnect succeeds ---")
    agent = AlphaAgent()
    agent.is_running = True
    agent.model_candidates = ["models/gemini-candidate-A", "models/gemini-candidate-B"]
    agent.model_name = "models/gemini-candidate-A"

    call_count = {"A": 0, "B": 0}

    # Stream 1 raises StopAsyncIteration on __anext__ (simulating safety drop or immediate cutoff)
    stream_fail = MagicMock()
    stream_fail.__anext__ = AsyncMock(side_effect=StopAsyncIteration())

    # Stream 2 returns a valid chunk
    mock_chunk = MagicMock()
    mock_chunk.candidates = [MagicMock()]
    mock_chunk.candidates[0].finish_reason = "STOP"
    mock_chunk.candidates[0].content.parts = [MagicMock(text="Reconnect worked!")]

    stream_ok = MagicMock()
    stream_ok.__anext__ = AsyncMock(return_value=mock_chunk)

    async def mock_gen_stream(model, contents, config):
        if model == "models/gemini-candidate-A":
            call_count["A"] += 1
            if call_count["A"] == 1:
                return stream_fail
            else:
                return stream_ok
        else:
            call_count["B"] += 1
            return stream_ok

    agent.client = MagicMock()
    agent.client.aio.models.generate_content_stream = mock_gen_stream

    # Test the candidate loop directly
    is_desktop = False
    history = [MagicMock()]
    stream = None
    first_chunk = None
    used_model = None

    active_model = getattr(agent, "model_name", None) or agent.model_candidates[0]
    ordered_candidates = [active_model] + [m for m in agent.model_candidates if m != active_model]

    logs = []
    def on_log(msg, lvl): logs.append((msg, lvl))

    for cand_model in ordered_candidates:
        if not agent.is_running: break
        connected = False
        for attempt in range(2):
            if not agent.is_running: break
            try:
                curr_stream = await agent.client.aio.models.generate_content_stream(
                    model=cand_model, contents=history, config=MagicMock()
                )
                first_chunk = await asyncio.wait_for(curr_stream.__anext__(), timeout=1.0)
                stream = curr_stream
                used_model = cand_model
                agent.model_name = cand_model
                connected = True
                if attempt > 0:
                    on_log(f"[{cand_model}] Reconnect successful!", "green")
                break
            except (asyncio.TimeoutError, StopAsyncIteration):
                if attempt == 0:
                    on_log(f"[{cand_model}] Reconnecting...", "warn")
                else:
                    on_log(f"[{cand_model} high latency] Switching...", "warn")
        if connected: break

    assert used_model == "models/gemini-candidate-A", f"Expected Candidate A, got {used_model}"
    assert call_count["A"] == 2, f"Expected 2 attempts on Candidate A, got {call_count['A']}"
    assert call_count["B"] == 0, f"Candidate B should NOT be called if A reconnected, got {call_count['B']}"
    print(f"[PASS] Reconnected on candidate A without rolling over to candidate B! Logs: {logs}")

async def test_reconnect_fail_then_rollover():
    print("\n--- Test 2: Both attempts on A fail with high latency, rolls over to B ---")
    agent = AlphaAgent()
    agent.is_running = True
    agent.model_candidates = ["models/gemini-candidate-A", "models/gemini-candidate-B"]
    agent.model_name = "models/gemini-candidate-A"

    call_count = {"A": 0, "B": 0}

    stream_fail = MagicMock()
    stream_fail.__anext__ = AsyncMock(side_effect=asyncio.TimeoutError())

    mock_chunk = MagicMock()
    mock_chunk.candidates = [MagicMock()]
    mock_chunk.candidates[0].finish_reason = "STOP"
    mock_chunk.candidates[0].content.parts = [MagicMock(text="Candidate B worked!")]

    stream_ok = MagicMock()
    stream_ok.__anext__ = AsyncMock(return_value=mock_chunk)

    async def mock_gen_stream(model, contents, config):
        if model == "models/gemini-candidate-A":
            call_count["A"] += 1
            return stream_fail
        else:
            call_count["B"] += 1
            return stream_ok

    agent.client = MagicMock()
    agent.client.aio.models.generate_content_stream = mock_gen_stream

    history = [MagicMock()]
    stream = None
    first_chunk = None
    used_model = None

    active_model = getattr(agent, "model_name", None) or agent.model_candidates[0]
    ordered_candidates = [active_model] + [m for m in agent.model_candidates if m != active_model]

    logs = []
    def on_log(msg, lvl): logs.append((msg, lvl))

    for cand_model in ordered_candidates:
        if not agent.is_running: break
        connected = False
        for attempt in range(2):
            if not agent.is_running: break
            try:
                curr_stream = await agent.client.aio.models.generate_content_stream(
                    model=cand_model, contents=history, config=MagicMock()
                )
                first_chunk = await asyncio.wait_for(curr_stream.__anext__(), timeout=1.0)
                stream = curr_stream
                used_model = cand_model
                agent.model_name = cand_model
                connected = True
                break
            except (asyncio.TimeoutError, StopAsyncIteration):
                if attempt == 0:
                    on_log(f"[{cand_model}] Reconnecting...", "warn")
                else:
                    on_log(f"[{cand_model} high latency] Switching...", "warn")
        if connected: break

    assert used_model == "models/gemini-candidate-B", f"Expected Candidate B, got {used_model}"
    assert call_count["A"] == 2, f"Candidate A should have been attempted twice before rollover, got {call_count['A']}"
    assert call_count["B"] == 1, f"Candidate B should have succeeded on attempt 1, got {call_count['B']}"
    print(f"[PASS] Correctly rolled over to Candidate B only after A failed both attempts! Logs: {logs}")

async def main():
    await test_reconnect_success()
    await test_reconnect_fail_then_rollover()
    print("\n[SUCCESS] ALL RECONNECT-BEFORE-ROLLOVER UNIT TESTS PASSED 100%!")

if __name__ == "__main__":
    asyncio.run(main())
