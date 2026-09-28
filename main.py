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

def main():
    print("[AlphaLive] Booting through main.py entrypoint...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
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
        print(f"[AlphaLive] Routing through venv: {target_python}")
        # Relaunch gui.py using the venv
        gui_script = os.path.join(base_dir, "ui", "gui.py")
        try:
            ret = subprocess.call([target_python, gui_script])
            sys.exit(ret)
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        # We are already in the venv (or venv doesn't exist, which will probably crash anyway without deps)
        print("[AlphaLive] Starting GUI...")
        try:
            from ui import gui
            gui.main()
        except KeyboardInterrupt:
            sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

