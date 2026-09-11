import os
import sys
import subprocess

def _excepthook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.exit(0)
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = _excepthook

def main():
    print("[AlphaLive] Booting through main.py entrypoint...")
    venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv")
    
    if os.name == "nt":
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_path, "bin", "python")

    # If the user is running this with their system python, but a venv exists, spawn the venv python.
    # If the user is already in the venv, sys.executable should match python_exe.
    if os.path.exists(python_exe) and os.path.abspath(sys.executable) != os.path.abspath(python_exe):
        print(f"[AlphaLive] Routing through venv: {python_exe}")
        # Relaunch gui.py using the venv
        gui_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui.py")
        try:
            ret = subprocess.call([python_exe, gui_script])
            sys.exit(ret)
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        # We are already in the venv (or venv doesn't exist, which will probably crash anyway without deps)
        print("[AlphaLive] Starting GUI...")
        try:
            import gui
            gui.main()
        except KeyboardInterrupt:
            sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

