' 4Dir_open.vbs 1.0.0 - 4Dir hands files to open here (via explorer), this opens them and exits.
' Why: the Windows Photos app lists the whole folder only when the program that opened the picture has already exited.
' 4Dir keeps running, so it writes the paths to 4Dir_open.tmp (UTF-16, one per line) next to this file and starts this script.
Option Explicit
Dim fso, sh, d, q, t, f, ln
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
d = fso.GetParentFolderName(WScript.ScriptFullName)
q = d & "\4Dir_open.tmp"
If Not fso.FileExists(q) Then WScript.Quit 0
Randomize
t = d & "\4Dir_open_" & CStr(Int(Timer * 1000)) & "_" & CStr(Int(Rnd * 100000)) & ".tmp"
On Error Resume Next
fso.MoveFile q, t
If Err.Number <> 0 Then WScript.Quit 0
On Error GoTo 0
Set f = fso.OpenTextFile(t, 1, False, -1)
Do Until f.AtEndOfStream
  ln = Trim(f.ReadLine)
  If Len(ln) > 0 And fso.FileExists(ln) Then sh.Run """" & ln & """", 1, False
Loop
f.Close
fso.DeleteFile t, True
