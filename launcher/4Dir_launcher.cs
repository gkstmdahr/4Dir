// 4Dir launcher (exe) v1.0.0 — 4Dir.vbs 와 같은 일을 하는 작은 실행 파일 (코드 서명용)
// - 1) 함께 들어 있는 runtime\pythonw.exe (배포판)
//   2) 없으면 PATH 의 pythonw.exe — 4Dir 를 돌릴 수 있을 때만 (Python 3.12+ 와 PySide6)
//   3) 그것도 없으면 안내 창(한국어 / 영어) + 받기 페이지 — 조용히 실패하지 않음
// - 배포판은 bin\main.pyc (컴파일본, 함께 든 파이썬 필요), 개발 폴더는 bin\main.py
// - 다른 프로그램을 내려받거나 설치하지 않음, 인터넷 접속 없음, 레지스트리 안 건드림
// - 로그: bin\log\launcher_exe.log (UTF-8)
// - 빌드: _build\make_launcher.py (윈도우 기본 csc.exe, 버전은 bin\main.py 의 QE_VERSION)
using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("4Dir")]
[assembly: AssemblyDescription("4Dir - 4-pane tabbed file manager")]
[assembly: AssemblyProduct("4Dir")]
[assembly: AssemblyCompany("4Dir project")]
[assembly: AssemblyCopyright("GPL-3.0 - https://4dir.net")]
[assembly: AssemblyVersion("@VER4@")]
[assembly: AssemblyFileVersion("@VER4@")]
[assembly: AssemblyInformationalVersion("@VER@")]

static class Launcher
{
    const string LAUNCHER_VER = "1.0.0";
    const string DL_URL = "https://github.com/gkstmdahr/4Dir/releases/latest";
    static string dir;
    static bool ko;

    static void L(string msg)
    {
        try
        {
            string b = Path.Combine(dir, "bin");
            if (!Directory.Exists(b)) return;
            string ld = Path.Combine(b, "log");
            Directory.CreateDirectory(ld);
            string p = Path.Combine(ld, "launcher_exe.log");
            if (File.Exists(p) && new FileInfo(p).Length > 200000) File.Delete(p);
            File.AppendAllText(p, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + msg + "\r\n", new UTF8Encoding(false));
        }
        catch { }
    }

    static int Fail(string kind, string detail)
    {
        L("FAIL " + kind + " : " + detail);
        string m;
        if (kind == "noapp")
            m = ko ? "4Dir 프로그램 파일(bin 폴더)을 찾을 수 없습니다.\r\n\r\n압축을 전부 풀었는지 확인하거나, 배포판 zip 을 다시 받아 주세요."
                   : "4Dir program files (bin folder) were not found.\r\n\r\nMake sure the whole zip was extracted, or download the release zip again.";
        else
            m = ko ? "4Dir 를 실행하는 데 필요한 파일(runtime 폴더)이 없습니다.\r\n\r\n"
                     + "- 깃허브의 초록색 'Code > Download ZIP' 으로 받았다면 소스 코드만 들어 있습니다.\r\n"
                     + "  배포판 zip (4Dir_v....zip) 을 받아 주세요.\r\n"
                     + "- 백신이 runtime 폴더 안의 파일을 격리했을 수도 있습니다.\r\n\r\n"
                     + "[확인]을 누르면 받기 페이지를 엽니다."
                   : "The files needed to run 4Dir (runtime folder) are missing.\r\n\r\n"
                     + "- If you used GitHub's green 'Code > Download ZIP', that is source code only.\r\n"
                     + "  Please download the release zip (4Dir_v....zip).\r\n"
                     + "- Your antivirus may also have quarantined files in the runtime folder.\r\n\r\n"
                     + "Click OK to open the download page.";
        if (MessageBox.Show(m, "4Dir", MessageBoxButtons.OKCancel, MessageBoxIcon.Exclamation) == DialogResult.OK)
        {
            L("open download page");
            try { Process.Start(DL_URL); } catch (Exception e) { L("open page error " + e.Message); }
        }
        return 1;
    }

    static string FindPy()
    {
        string path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (string raw in path.Split(';'))
        {
            string q = raw.Trim().Trim('"');
            // WindowsApps = 마이크로소프트 스토어 가짜 파일(실행하면 스토어가 열림)
            if (q == "" || q.IndexOf("\\WindowsApps", StringComparison.OrdinalIgnoreCase) >= 0) continue;
            try
            {
                string c = Path.Combine(q, "pythonw.exe");
                if (File.Exists(c)) return c;
            }
            catch { }
        }
        return "";
    }

    [STAThread]
    static int Main()
    {
        dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        ko = CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "ko";
        L("launcher " + LAUNCHER_VER + " in " + dir);

        string app = Path.Combine(dir, "bin", "main.py");
        if (!File.Exists(app)) app = Path.Combine(dir, "bin", "main.pyc");
        if (!File.Exists(app)) return Fail("noapp", dir + "\\bin\\main.py(c) missing");

        string py = Path.Combine(dir, "runtime", "pythonw.exe");
        if (!File.Exists(py))
        {
            if (app.EndsWith(".pyc", StringComparison.OrdinalIgnoreCase)) return Fail("noruntime", "release build without runtime\\pythonw.exe");
            py = FindPy();
            if (py == "") return Fail("noruntime", "no runtime, no pythonw.exe on PATH");
            int rc;
            try
            {
                var chk = new ProcessStartInfo(py, "-c \"import sys, PySide6; sys.exit(0 if sys.version_info >= (3, 12) else 3)\"");
                chk.UseShellExecute = false;
                chk.CreateNoWindow = true;
                using (var p = Process.Start(chk)) { p.WaitForExit(); rc = p.ExitCode; }
            }
            catch (Exception e) { rc = -1; L("check error " + e.Message); }
            L("check " + py + " rc=" + rc);
            if (rc != 0) return Fail("noruntime", py + " cannot run 4Dir (needs Python 3.12+ and PySide6), rc=" + rc);
        }
        L("start " + py + " " + app);
        try
        {
            var si = new ProcessStartInfo(py, "\"" + app + "\"");
            si.UseShellExecute = false;
            si.WorkingDirectory = dir;
            Process.Start(si);
        }
        catch (Exception e) { L("start error " + e.Message); return Fail("noruntime", "start failed: " + e.Message); }
        return 0;
    }
}
