Set WshShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
strPath = objFSO.GetParentFolderName(WScript.ScriptFullName)

WshShell.CurrentDirectory = strPath

' Use python.exe instead of pythonw.exe to prevent stdout print crashes, but keep the window hidden (0)
WshShell.Run chr(34) & strPath & "\.venv\Scripts\python.exe" & Chr(34) & " worker_main.py", 0

Set WshShell = Nothing
