Set WshShell = CreateObject("WScript.Shell")
' Hardcoded to Z:\ since this file will be moved to the Windows Startup folder
WshShell.CurrentDirectory = "Z:\"
WshShell.Run chr(34) & "Z:\.venv\Scripts\python.exe" & Chr(34) & " worker_main.py", 0
Set WshShell = Nothing
