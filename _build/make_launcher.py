# -*- coding: utf-8 -*-
"""4Dir 실행 파일(4Dir.exe) 만들기 (MAKE_LAUNCHER_VER 1.0.0)

python make_launcher.py [출력 폴더]   → <출력 폴더>\\4Dir.exe  (기본: 4Dir\\_build\\launcher_out)
- 원본: 4Dir\\launcher\\4Dir_launcher.cs (4Dir.vbs 와 같은 일)
- 컴파일러: 윈도우에 기본으로 있는 .NET Framework 4 csc.exe (따로 설치할 것 없음, 깃허브 자동 빌드 PC 에도 있음)
- 버전: bin\\main.py 의 QE_VERSION → 파일 속성의 제품 이름·버전 (코드 서명 조건)
- 아이콘: bin\\4Dir.ico
로그: _build\\make_launcher_log.txt
"""
import os
import re
import sys
import time
import subprocess

MAKE_LAUNCHER_VER = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "launcher", "4Dir_launcher.cs")
ICON = os.path.join(ROOT, "bin", "4Dir.ico")
LOGF = os.path.join(HERE, "make_launcher_log.txt")
_logf = open(LOGF, "w", encoding="utf-8")


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    _logf.write(line + "\n")
    _logf.flush()


def app_version():
    s = open(os.path.join(ROOT, "bin", "main.py"), encoding="utf-8").read()
    return re.search(r'QE_VERSION = "([^"]+)"', s).group(1)


def find_csc():
    win = os.environ.get("SystemRoot", r"C:\Windows")
    for fw in ("Framework64", "Framework"):
        c = os.path.join(win, "Microsoft.NET", fw, "v4.0.30319", "csc.exe")
        if os.path.exists(c):
            return c
    raise SystemExit("csc.exe 를 찾을 수 없습니다 (.NET Framework 4)")


def main():
    out_dir = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "launcher_out")
    os.makedirs(out_dir, exist_ok=True)
    ver = app_version()
    nums = [int(x) for x in re.findall(r"\d+", ver)][:4]
    ver4 = ".".join(str(n) for n in nums + [0] * (4 - len(nums)))
    log(f"make_launcher {MAKE_LAUNCHER_VER}: 4Dir {ver} (파일 버전 {ver4}) → {out_dir}")

    src = open(SRC, encoding="utf-8").read().replace("@VER4@", ver4).replace("@VER@", ver)
    tmp = os.path.join(out_dir, "4Dir_launcher_build.cs")
    with open(tmp, "w", encoding="utf-8-sig") as f:
        f.write(src)
    exe = os.path.join(out_dir, "4Dir.exe")
    csc = find_csc()
    cmd = [csc, "/nologo", "/target:winexe", "/optimize+", "/codepage:65001", "/platform:anycpu",
           "/r:System.Windows.Forms.dll", f"/win32icon:{ICON}", f"/out:{exe}", tmp]
    log("컴파일: " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="cp949", errors="replace")
    os.remove(tmp)
    if r.stdout.strip():
        log(r.stdout.strip())
    if r.returncode != 0 or not os.path.exists(exe):
        raise SystemExit(f"컴파일 실패 rc={r.returncode}")
    log(f"완료: {exe} ({os.path.getsize(exe)} bytes)")


if __name__ == "__main__":
    main()
