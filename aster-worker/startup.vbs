Set objShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Derive the worker directory from this script's own location (portable across machines)
workerDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Use the bundled virtual environment Python for a fully silent, self-contained launch
pythonExe = fso.BuildPath(workerDir, ".venv\Scripts\pythonw.exe")
If Not fso.FileExists(pythonExe) Then
    pythonExe = fso.BuildPath(workerDir, ".venv\Scripts\python.exe")
End If

' Construct the silent execution command
cmd = "cmd.exe /c cd /d """ & workerDir & """ && """ & pythonExe & """ worker_main.py --aster-worker"

' Run the command completely hidden (0) and do not wait for it to return (False)
objShell.Run cmd, 0, False
