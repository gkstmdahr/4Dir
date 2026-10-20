' 4Dir launcher
' - uses bundled runtime\pythonw.exe (release build) if present, otherwise pythonw on PATH (dev PC)
' - window style must be 1 (normal): 0 would hide the app's first window too
' - release build ships compiled bin\main.pyc (no .py); dev folder has main.py
Set fso = CreateObject("Scripting.FileSystemObject")
d = fso.GetParentFolderName(WScript.ScriptFullName)
py = d & "\runtime\pythonw.exe"
If Not fso.FileExists(py) Then py = "pythonw"
app = d & "\bin\main.py"
If Not fso.FileExists(app) Then app = d & "\bin\main.pyc"
Set sh = CreateObject("WScript.Shell")
sh.Run """" & py & """ """ & app & """", 1, False
