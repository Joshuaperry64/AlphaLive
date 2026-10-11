"""
AlphaLive // Overseer presence-gate verification.

Asserts that WorkspaceServer only reports an Overseer as 'present' for
*authenticated* clients, and that presence clears when they disconnect. This is the
signal that drives the fail-closed autonomy gate in aster-worker/worker_main.py.

Run: python tests/test_overseer_gate.py
"""
import os
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.workspace_bridge import WorkspaceServer, WorkspaceClient, resolve_bridge_token

TEST_PORT = 8799


def _wait_for(predicate, timeout=6.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def main():
    token = resolve_bridge_token()
    assert token, "A BridgeToken must be configured in config.json for this test to be meaningful."
    print(f"[TEST] Using configured BridgeToken (len={len(token)}).")

    server = WorkspaceServer(host="127.0.0.1", port=TEST_PORT, token=token)
    server.start()
    time.sleep(0.6)
    assert server.overseer_count() == 0, "Fresh server must report zero overseers."
    assert server.has_overseer() is False, "Fresh server must report no overseer."
    print("[TEST] Fresh server: count=0, has_overseer()=False.")

    # 1. Authenticated client registers as present.
    good = WorkspaceClient(host="127.0.0.1", port=TEST_PORT, token=token)
    good.connect()
    assert _wait_for(lambda: server.has_overseer()), "Authenticated client must register as present."
    assert server.overseer_count() == 1, "Exactly one authenticated overseer expected."
    print("[TEST] Authenticated client: has_overseer()=True, count=1.")

    # 2. Unauthenticated client must NOT count.
    bad = WorkspaceClient(host="127.0.0.1", port=TEST_PORT, token="definitely-wrong-token")
    bad.connect()
    time.sleep(1.5)
    assert server.overseer_count() == 1, "Unauthenticated client must never count as an overseer."
    print("[TEST] Unauthenticated client rejected: count still 1.")
    bad.disconnect()

    # 3. Disconnect clears presence.
    good.disconnect()
    assert _wait_for(lambda: not server.has_overseer()), "Presence must clear after disconnect."
    assert server.overseer_count() == 0, "Zero overseers expected after disconnect."
    print("[TEST] After disconnect: has_overseer()=False, count=0.")

    server.stop()
    time.sleep(0.3)
    print("[TEST] =====================================================")
    print("[TEST] OVERSEER PRESENCE-GATE TESTS PASSED")
    print("[TEST] =====================================================")


if __name__ == "__main__":
    main()
