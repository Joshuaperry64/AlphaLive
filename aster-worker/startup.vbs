Set objShell = CreateObject("WScript.Shell")

' Enforce execution strictly in the local Worker directory
workerDir = "C:\Users\AlphaAI\Documents\Worker"

' Construct the silent execution command using the global python executable
cmd = "cmd.exe /c cd /d """ & workerDir & """ && py worker_main.py --aster-worker"

' Run the command completely hidden (0) and do not wait for it to return (False)
objShell.Run cmd, 0, False
