' 4Dir launcher v1.1.0 (4Dir v0.9.52)
' - 1) bundled runtime\pythonw.exe (release build)
'   2) otherwise pythonw.exe on PATH, only if it can run 4Dir (Python 3.12+ with PySide6)
'   3) otherwise show a message (Korean / English) and offer the download page - never fail silently
'      (e.g. source zip from GitHub "Code > Download ZIP", or antivirus quarantined runtime files)
' - window style must be 1 (normal): 0 would hide the app's first window too
' - release build ships compiled bin\main.pyc (no .py, needs the bundled Python); dev folder has main.py
' - log: bin\log\launcher.log
Option Explicit
Const DL_URL = "https://github.com/gkstmdahr/4Dir/releases/latest"
Dim fso, sh, d, py, app, ko, rc
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
d = fso.GetParentFolderName(WScript.ScriptFullName)
ko = (GetLocale() = 1042)

Sub L(msg)
  On Error Resume Next
  Dim p, f
  If Not fso.FolderExists(d & "\bin") Then Exit Sub
  If Not fso.FolderExists(d & "\bin\log") Then fso.CreateFolder d & "\bin\log"
  p = d & "\bin\log\launcher.log"
  If fso.FileExists(p) Then
    If fso.GetFile(p).Size > 200000 Then fso.DeleteFile p
  End If
  Set f = fso.OpenTextFile(p, 8, True, -1)
  f.WriteLine Now & " " & msg
  f.Close
End Sub

Sub Fail(kind, detail)
  Dim m
  L "FAIL " & kind & " : " & detail
  If kind = "noapp" Then
    If ko Then
      m = "4Dir 프로그램 파일(bin 폴더)을 찾을 수 없습니다." & vbCrLf & vbCrLf & _
          "압축을 전부 풀었는지 확인하거나, 배포판 zip 을 다시 받아 주세요."
    Else
      m = "4Dir program files (bin folder) were not found." & vbCrLf & vbCrLf & _
          "Make sure the whole zip was extracted, or download the release zip again."
    End If
  Else
    If ko Then
      m = "4Dir 를 실행하는 데 필요한 파일(runtime 폴더)이 없습니다." & vbCrLf & vbCrLf & _
          "- 깃허브의 초록색 'Code > Download ZIP' 으로 받았다면 소스 코드만 들어 있습니다." & vbCrLf & _
          "  배포판 zip (4Dir_v....zip) 을 받아 주세요." & vbCrLf & _
          "- 백신이 runtime 폴더 안의 파일을 격리했을 수도 있습니다." & vbCrLf & vbCrLf & _
          "[확인]을 누르면 받기 페이지를 엽니다."
    Else
      m = "The files needed to run 4Dir (runtime folder) are missing." & vbCrLf & vbCrLf & _
          "- If you used GitHub's green 'Code > Download ZIP', that is source code only." & vbCrLf & _
          "  Please download the release zip (4Dir_v....zip)." & vbCrLf & _
          "- Your antivirus may also have quarantined files in the runtime folder." & vbCrLf & vbCrLf & _
          "Click OK to open the download page."
    End If
  End If
  If MsgBox(m, vbOKCancel + vbExclamation, "4Dir") = vbOK Then
    L "open download page"
    sh.Run DL_URL
  End If
  WScript.Quit 1
End Sub

Function FindPy()
  Dim q, c
  FindPy = ""
  For Each q In Split(sh.ExpandEnvironmentStrings("%PATH%"), ";")
    q = Trim(q)
    ' WindowsApps = Microsoft Store stub (would open the Store instead of running)
    If q <> "" And InStr(1, q, "\WindowsApps", 1) = 0 Then
      c = fso.BuildPath(q, "pythonw.exe")
      If fso.FileExists(c) Then
        FindPy = c
        Exit Function
      End If
    End If
  Next
End Function

app = d & "\bin\main.py"
If Not fso.FileExists(app) Then app = d & "\bin\main.pyc"
If Not fso.FileExists(app) Then Fail "noapp", d & "\bin\main.py(c) missing"

py = d & "\runtime\pythonw.exe"
If Not fso.FileExists(py) Then
  If LCase(Right(app, 4)) = ".pyc" Then Fail "noruntime", "release build without runtime\pythonw.exe"
  py = FindPy()
  If py = "" Then Fail "noruntime", "no runtime, no pythonw.exe on PATH"
  On Error Resume Next
  rc = sh.Run("""" & py & """ -c ""import sys, PySide6; sys.exit(0 if sys.version_info >= (3, 12) else 3)""", 0, True)
  If Err.Number <> 0 Then rc = -1
  On Error GoTo 0
  L "check " & py & " rc=" & rc
  If rc <> 0 Then Fail "noruntime", py & " cannot run 4Dir (needs Python 3.12+ and PySide6), rc=" & rc
End If
L "start " & py & " " & app
sh.Run """" & py & """ """ & app & """", 1, False
