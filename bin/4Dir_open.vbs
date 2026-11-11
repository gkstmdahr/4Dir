' 4Dir_open.vbs 1.1.0 - 4Dir hands files to open here (via explorer), this opens them and exits.
' Why: the Windows Photos app lists the whole folder only when the program that opened the picture has already exited.
' 4Dir keeps running, so it writes requests to 4Dir_open.tmp (UTF-16, one per line) next to this file and starts this script.
' Line = a file path (open with its default app), or 'openwith' TAB pythonw TAB helper TAB app TAB file [TAB file...]
' (1.1.0: 'Open with > app' from the right-click menu, run by the small helper openwith.py(.pyc) that exits right away)
Option Explicit
Dim fso, sh, d, q, t, f, ln, a, i, cmd
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
  If Left(ln, 9) = "openwith" & vbTab Then
    a = Split(ln, vbTab)
    If UBound(a) >= 4 Then
      cmd = ""
      For i = 1 To UBound(a)
        cmd = cmd & " """ & a(i) & """"
      Next
      sh.Run Mid(cmd, 2), 1, False
    End If
  ElseIf Len(ln) > 0 And fso.FileExists(ln) Then
    sh.Run """" & ln & """", 1, False
  End If
Loop
f.Close
fso.DeleteFile t, True
