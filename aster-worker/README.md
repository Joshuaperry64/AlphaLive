# aster-worker (Workplace 2 / AI Node)

Headless ASTER worker node for AlphaLive. Runs the AI agent, executes desktop actions,
and streams telemetry to the Overseer cockpit over a WebSocket bridge.

## Entrypoints
- `worker_main.py` — headless worker: `python worker_main.py --aster-worker`
- `startup.vbs` — silent Windows autostart (derives paths from its own location)

## Network / auth
- The bridge server binds `127.0.0.1:8766` by default. Pass `--host 0.0.0.0` for LAN multi-PC.
- Shared-secret authentication is enforced whenever `BridgeToken` is set in `config.json`
  (or via the `ALPHALIVE_BRIDGE_TOKEN` environment variable). The Overseer client must
  supply the same token.
- The Overseer client accepts `--token` (see `run_overseer_client.py`).

## Mirrored sources
`core/` is a hard copy of the repo-root `core/` module tree (intentional, so this
directory remains a self-contained deployable). Keep both copies in sync when editing
`alpha_agent.py`, `workspace_bridge.py`, or `session_manager.py`.

## Note
`memory/` and `studio/` are NOT bundled here; the agent degrades gracefully (memory,
persona, and studio subsystems become `None`) in this isolated deployment. Copy them in
if the worker must have persistent memory/personas.