' Explorer Check launcher (same folder as explorer_check.py)
' - uses bundled ..\runtime\pythonw.exe (release build) if present, otherwise pythonw on PATH
Set fso = CreateObject("Scripting.FileSystemObject")
d = fso.GetParentFolderName(WScript.ScriptFullName)
py = fso.GetParentFolderName(d) & "\runtime\pythonw.exe"
If Not fso.FileExists(py) Then py = "pythonw"
app = d & "\explorer_check.py"
If Not fso.FileExists(app) Then app = d & "\explorer_check.pyc"   ' release build = .pyc
Set sh = CreateObject("WScript.Shell")
sh.Run """" & py & """ """ & app & """", 1, False
