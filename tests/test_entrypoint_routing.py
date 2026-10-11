"""Process-role routing tests that do not start Qt or the ASTER worker."""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import main


def run_tests():
    assert main.resolve_mode([]) == "gui"
    assert main.resolve_mode(["--host", "192.168.1.20"]) == "gui"
    assert main.resolve_mode(["--overseer", "--host", "192.168.1.20"]) == "overseer"
    assert main.resolve_mode(["--overseer-client"]) == "overseer"
    assert main.resolve_mode(["--remote-overseer"]) == "overseer"
    assert main.resolve_mode(["--aster-worker"]) == "worker"
    assert main.resolve_mode(["--worker"]) == "worker"
    assert main.resolve_mode(["--host-node"]) == "worker"

    try:
        main.resolve_mode(["--overseer", "--aster-worker"])
        raise AssertionError("Conflicting process roles must be rejected")
    except ValueError:
        pass

    command, cwd = main.build_worker_command(
        str(ROOT_DIR),
        ["--worker", "--host", "0.0.0.0", "--port", "9000", "--token", "secret"],
    )
    assert Path(cwd) == ROOT_DIR
    assert Path(command[1]) == ROOT_DIR / "worker_main.py"
    assert command[2] == "--aster-worker"
    assert "--worker" not in command
    assert command[-6:] == ["--host", "0.0.0.0", "--port", "9000", "--token", "secret"]
    print("[TEST] ENTRYPOINT ROUTING PASSED")


if __name__ == "__main__":
    run_tests()