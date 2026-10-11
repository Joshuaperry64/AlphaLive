import os
import sys
import subprocess

# Ensure we can import from sibling packages
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _excepthook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.exit(0)
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = _excepthook

WORKER_FLAGS = {"--aster-worker", "--worker", "--host-node"}
OVERSEER_FLAGS = {"--overseer-client", "--remote-overseer", "--overseer"}


def resolve_mode(argv=None):
    """Resolve process role without treating connection options as mode selectors."""
    args = list(sys.argv[1:] if argv is None else argv)
    worker = any(arg in WORKER_FLAGS for arg in args)
    overseer = any(arg in OVERSEER_FLAGS for arg in args)
    if worker and overseer:
        raise ValueError("Choose either worker mode or Overseer mode, not both.")
    if worker:
        return "worker"
    if overseer:
        return "overseer"
    return "gui"


def build_worker_command(base_dir, argv=None):
    """Build the isolated canonical Workplace 2 worker command."""
    args = list(sys.argv[1:] if argv is None else argv)
    worker_dir = base_dir
    scripts_dir = os.path.join(base_dir, ".venv", "Scripts")
    python_exe = os.path.join(scripts_dir, "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable
    worker_script = os.path.join(base_dir, "worker_main.py")
    forwarded = [arg for arg in args if arg not in WORKER_FLAGS]
    return [python_exe, worker_script, "--aster-worker", *forwarded], worker_dir

def main():
    if sys.stdout: print("[AlphaLive] Booting AlphaCore Autonomous Desktop Agent...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    mode = resolve_mode()

    if mode == "worker":
        command, worker_dir = build_worker_command(base_dir)
        if sys.stdout: print(f"[AlphaLive] Routing to canonical ASTER worker: {command[0]}")
        try:
            sys.exit(subprocess.call(command, cwd=worker_dir))
        except KeyboardInterrupt:
            sys.exit(0)

    venv_path = os.path.join(base_dir, ".venv")
    is_windowless = "pythonw" in os.path.basename(sys.executable).lower()
    
    if os.name == "nt":
        python_exe = os.path.join(venv_path, "Scripts", "pythonw.exe" if is_windowless else "python.exe")
        fallback_exe = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_path, "bin", "python")
        fallback_exe = python_exe

    target_python = python_exe if os.path.exists(python_exe) else fallback_exe

    # If the user is running this with their system python, but a venv exists, spawn the venv python.
    venv_scripts = os.path.normcase(os.path.abspath(os.path.join(venv_path, "Scripts" if os.name == "nt" else "bin")))
    in_venv = os.path.normcase(os.path.abspath(os.path.dirname(sys.executable))) == venv_scripts

    if os.path.exists(target_python) and not in_venv:
        if sys.stdout: print(f"[AlphaLive] Routing through venv: {target_python}")
        try:
            ret = subprocess.call([target_python, os.path.abspath(__file__)] + sys.argv[1:], creationflags=0x08000000 if os.name == 'nt' else 0)
            sys.exit(ret)
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        if mode == "overseer":
            from ui import overseer_dashboard
            overseer_dashboard.main()
            return


        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("alphacore.alphalive.agent.v4")
        except Exception:
            pass

        # Directly launch AlphaCore Autonomous Agent GUI
        from ui import agent_gui
        agent_gui.main()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
