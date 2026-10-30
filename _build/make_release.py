# -*- coding: utf-8 -*-
"""4Dir 배포판 자동 생성 (MAKE_VER 1.6.0)

결과: <4Dir>\\_release\\4Dir_v<버전>\\  +  4Dir_v<버전>.zip
구성:
  4Dir.vbs        실행기 (runtime\\pythonw.exe 사용)
  사용법.txt
  お読みください.txt     일본어 설명서 (1.6.0)
  bin\\                   프로그램 (*.pyc 컴파일본만 — 원본 .py 는 넣지 않음, 탐색기 점검.vbs) — 개인 파일(상태·즐겨찾기·세션·로그·설정·백업) 제외
  licenses\\              함께 들어가는 파이썬·PySide6(Qt)·pywin32 라이선스 문서
_release 에 함께 생기는 것: 4Dir_v<버전>.zip.sha256.txt (정품 확인용 지문), 웹게시_안내_v<버전>.txt
백업: 이전 배포판 → _release\백업\배포판 (최근 10개), 버전마다 소스 → _release\백업\소스 (지우지 않음)
  runtime\\               python.org 공식 휴대용 파이썬(파이썬 재단 서명) + PySide6(필요한 Qt 만) + pywin32
보안: exe 를 새로 만들지 않음, PowerShell 안 씀, 서명된 python 실행 파일만 사용.
로그: _build\\build_log.txt
"""
import os
import re
import sys
import shutil
import zipfile
import time
import urllib.request
import site
import subprocess

MAKE_VER = "1.6.0"   # 1.6.0: 일본어 설명서 お読みください.txt (Vector 掲載基準) / 1.5.0: qwebp·qjpeg 포함, imgconvert 가져오기 확인 / 1.4.1: 프로그램 안 사용법 그림은 ko·en p1~p6 만 / 1.4.0: qgif.dll(GIF 재생) 포함 / 1.3.0: 회사 글자 목록 별도 파일(corp_words.txt, 비공개), 4Dir 본체 GPL-3.0 라이선스 포함, 패키지 정보 없을 때 버전·pywin32 라이선스 대체 / 1.2.5: 소스 백업에 _dev(시험·번역) 포함 / 1.2.4: overlays·overlayorder 가져오기 확인 / 1.2.3: thumbs 가져오기 확인 / 1.2.2: 사용법에 즐겨찾기 정리·탭 끌기·일괄 변경 / 1.2.1: favorg 가져오기 확인 / 1.2.0: 이전 배포판은 _release\백업\배포판 으로 옮김(최근 10개), 버전마다 소스 백업 _release\백업\소스 / 1.1.5: 사용법 그림(bin\guide, 사용법 그림\ko·en) / 1.1.4: batchrename 가져오기 확인 / 1.1.3: 회사 관련 글자 검사(있으면 배포 중단) / 1.1.1: 언어 파일(bin\lang) 포함·영어 안내 / 1.1.0: .pyc 배포, SHA256 지문 파일, 라이선스 문서, 사용법(차단 해제 안내) 갱신
# PySide6·Qt 라이선스 원문 (LGPLv3 는 GPLv3 를 참조). gnu.org 는 이 네트워크에서 응답 없음(10/2 실측) → SPDX 공식 원문 저장소
LICENSE_URLS = {"LGPL-3.0.txt": "https://raw.githubusercontent.com/spdx/license-list-data/main/text/LGPL-3.0-only.txt",
                "GPL-3.0.txt": "https://raw.githubusercontent.com/spdx/license-list-data/main/text/GPL-3.0-only.txt"}
# 배포판에 들어가면 안 되는 회사·사내 관련 글자 (소문자 비교)
# 회사 관련 글자 목록은 공개 저장소에 안 올리는 별도 파일 (1.3.0) — 한 줄에 하나, 없으면 배포 중단
_CW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corp_words.txt")
CORP_WORDS = [w.strip() for w in open(_CW, encoding="utf-8").read().splitlines() if w.strip()] if os.path.exists(_CW) else None
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin")
CACHE = os.path.join(HERE, "cache")
REL = os.path.join(ROOT, "_release")
LOG = os.path.join(HERE, "build_log.txt")
PYVER = "{}.{}.{}".format(*sys.version_info[:3])          # 개발 PC 파이썬과 같은 버전(패키지 호환)
EMBED = f"python-{PYVER}-embed-amd64.zip"
EMBED_URL = f"https://www.python.org/ftp/python/{PYVER}/{EMBED}"

# bin 에서 배포하지 않는 것 (개인 데이터)
BIN_SKIP_DIRS = {"__pycache__", "log", "sessions", "workspaces", "index"}   # index = 검색 색인(개인 데이터)
BIN_SKIP_FILES = re.compile(r"(4Dir_(state|favorites|settings).*|.*\.running|.*\.tmp|.*백업.*)$", re.I)

# PySide6 에서 필요한 것만 (이름 규칙)
PYSIDE_KEEP = re.compile(r"^(__init__\.py|_config\.py|_git_pyside_version\.py|"
                         r"Qt(Core|Gui|Widgets|Network)\.pyd|pyside6\.abi3\.dll|"
                         r"Qt6(Core|Gui|Widgets|Network)\.dll|"
                         r"(msvcp|vcruntime|concrt)\d*(_\w+)?\.dll)$", re.I)
PYSIDE_PLUGINS = ["platforms/qwindows.dll", "styles/qmodernwindowsstyle.dll", "imageformats/qico.dll",
                  "imageformats/qgif.dll", "imageformats/qwebp.dll", "imageformats/qjpeg.dll"]   # 1.5.0: webp·jpg (그림 변환 v0.9.66)   # 1.4.0: GIF 움직임 재생(미리보기 창). runtime 에 없으면 _build\qt_plugins 에서 (PyPI PySide6-Essentials 6.11.1 원본)
QT_PLUGINS_EXTRA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qt_plugins")
PYWIN_DIRS = ["win32", "win32com", "win32comext", "pywin32_system32"]
PYWIN_FILES = ["pywin32.pth", "pywin32.version.txt", "pythoncom.py"]   # pythoncom.py 는 site-packages 바로 아래(실측)

_logf = None
BACKUP = os.path.join(REL, "백업")
KEEP_RELEASES = 10   # 배포판 zip 은 최근 10개만 (소스 백업은 지우지 않음)
SRC_ROOT_FILES = ["4Dir.vbs", "_HANDOFF_4Dir.md"]
SRC_DIRS = {"bin": BIN_SKIP_DIRS, "_build": {"cache", "__pycache__"}, "_maxtest": {"__pycache__"},
            "_dev": {"__pycache__", "svnt", "old0926", "old0931"}}   # _dev = 시험 스크립트·번역 작업 파일 (배포판엔 안 들어감)


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    _logf.write(line + "\n")
    _logf.flush()


def size_mb(p):
    if os.path.isfile(p):
        return os.path.getsize(p) / 1048576
    return sum(os.path.getsize(os.path.join(a, f)) for a, _, fs in os.walk(p) for f in fs) / 1048576


def app_version():
    s = open(os.path.join(BIN, "main.py"), encoding="utf-8").read()
    return re.search(r'QE_VERSION = "([^"]+)"', s).group(1)


def get_embed():
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, EMBED)
    if os.path.exists(p) and os.path.getsize(p) > 5_000_000:
        log(f"휴대용 파이썬 캐시 사용 {p} ({size_mb(p):.1f}MB)")
        return p
    log(f"휴대용 파이썬 내려받기 {EMBED_URL}")
    tmp = p + ".part"
    with urllib.request.urlopen(EMBED_URL, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, p)
    log(f"내려받음 {size_mb(p):.1f}MB")
    return p


def compile_bin(bindir):
    """bin 의 .py → 같은 이름 .pyc (이 파이썬 = 배포 runtime 과 같은 버전), 원본 .py 삭제.
    오류 기록에는 'bin\\main.py' 처럼 원래 파일 이름·줄 번호가 그대로 찍힘"""
    import py_compile
    done = []
    for f in sorted(os.listdir(bindir)):
        if f.endswith(".py"):
            src = os.path.join(bindir, f)
            py_compile.compile(src, cfile=src + "c", dfile="bin\\" + f, doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            os.remove(src)
            done.append(f + "c")
    return done


def get_license(name, url):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if not (os.path.exists(p) and os.path.getsize(p) > 5000):
        log(f"라이선스 문서 내려받기 {url}")
        with urllib.request.urlopen(url, timeout=60) as r, open(p + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(p + ".part", p)
    return p


def write_licenses(out, sp_src, rt):
    lic = os.path.join(out, "licenses")
    os.makedirs(lic)
    shutil.copy2(os.path.join(rt, "LICENSE.txt"), os.path.join(lic, "Python_LICENSE.txt"))
    for name, url in LICENSE_URLS.items():
        shutil.copy2(get_license(name, url), os.path.join(lic, "PySide6_Qt_" + name))
    pw = [d for d in os.listdir(sp_src) if d.lower().startswith("pywin32-") and d.endswith(".dist-info")]
    if pw:
        src = os.path.join(sp_src, pw[0], "licenses", "win32", "License.txt")
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(lic, "pywin32_License.txt"))
    if not os.path.exists(os.path.join(lic, "pywin32_License.txt")):   # 패키지 정보 없는 파이썬으로 만들 때 (1.3.0)
        shutil.copy2(os.path.join(CACHE, "pywin32_License.txt"), os.path.join(lic, "pywin32_License.txt"))
    shutil.copy2(get_license("GPL-3.0.txt", LICENSE_URLS["GPL-3.0.txt"]), os.path.join(lic, "4Dir_GPL-3.0.txt"))
    with open(os.path.join(lic, "라이선스_안내.txt"), "w", encoding="utf-8-sig") as f:
        f.write(LICENSE_NOTE.format(py=PYVER, qt=_pkg_ver(sp_src, "pyside6"), pw=_pkg_ver(sp_src, "pywin32")))
    return sorted(os.listdir(lic))


def _pkg_ver(sp_src, name):
    for d in os.listdir(sp_src):
        if d.lower().startswith(name + "-") and d.endswith(".dist-info"):
            return d[len(name) + 1:-len(".dist-info")]
    try:   # 패키지 정보(dist-info) 없는 파이썬 (1.3.0)
        if name == "pyside6":
            import PySide6
            return PySide6.__version__
        if name == "pywin32":
            return open(os.path.join(sp_src, "pywin32.version.txt"), encoding="utf-8").read().strip()
    except Exception:
        pass
    return "?"


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def copy_tree(src, dst, skip_dirs=(), skip_re=None):
    for a, ds, fs in os.walk(src):
        ds[:] = [d for d in ds if d not in skip_dirs and d != "__pycache__"]
        rel = os.path.relpath(a, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in fs:
            if skip_re and skip_re.match(f):
                continue
            shutil.copy2(os.path.join(a, f), os.path.join(dst, rel, f))


def backup_old_releases(ver):
    """지금 만들 버전이 아닌 이전 배포판 zip·지문·웹게시 안내 → _release\백업\배포판 (풀린 폴더는 zip 에 다 있으니 지움).
    배포판 zip 은 최근 KEEP_RELEASES 개만 남김"""
    dst = os.path.join(BACKUP, "배포판")
    os.makedirs(dst, exist_ok=True)
    pat = re.compile(r"^(4Dir_v|웹게시_안내_v)(\d+\.\d+\.\d+)(\.zip|\.zip\.sha256\.txt|\.txt)?$")
    for f in os.listdir(REL):
        m = pat.match(f)
        if not m or m.group(2) == ver:
            continue
        p = os.path.join(REL, f)
        if os.path.isdir(p):
            if os.path.exists(os.path.join(REL, f + ".zip")) or os.path.exists(os.path.join(dst, f + ".zip")):
                shutil.rmtree(p)
                log(f"이전 배포 폴더 지움(zip 은 백업에 있음) {f}")
            continue
        shutil.move(p, os.path.join(dst, f))
        log(f"이전 배포판 백업으로 옮김 {f}")
    vkey = lambda f: tuple(int(x) for x in re.search(r"v(\d+)\.(\d+)\.(\d+)", f).groups())
    zips = sorted((f for f in os.listdir(dst) if re.match(r"^4Dir_v[\d.]+\.zip$", f)), key=vkey)
    for f in zips[:-KEEP_RELEASES]:
        v = re.search(r"v([\d.]+)\.zip", f).group(1)
        for g in (f, f + ".sha256.txt", f"웹게시_안내_v{v}.txt"):
            if os.path.exists(os.path.join(dst, g)):
                os.remove(os.path.join(dst, g))
        log(f"오래된 배포판 정리 (최근 {KEEP_RELEASES}개만) {f}")


def backup_source(ver):
    """버전마다 소스 백업 → _release\백업\소스\4Dir_소스_v<버전>.zip (개인 데이터·색인·캐시 제외, 지우지 않음)"""
    dst = os.path.join(BACKUP, "소스")
    os.makedirs(dst, exist_ok=True)
    zp = os.path.join(dst, f"4Dir_소스_v{ver}.zip")
    n = 0
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for f in SRC_ROOT_FILES:
            if os.path.exists(os.path.join(ROOT, f)):
                z.write(os.path.join(ROOT, f), f)
                n += 1
        for d, skip in SRC_DIRS.items():
            base = os.path.join(ROOT, d)
            for a, ds, fs in os.walk(base):
                ds[:] = [x for x in ds if x not in skip]
                for f in fs:
                    if d == "bin" and BIN_SKIP_FILES.match(f):
                        continue
                    if d == "_build" and f == "build_log.txt":
                        continue
                    full = os.path.join(a, f)
                    z.write(full, os.path.join(d, os.path.relpath(full, base)))
                    n += 1
    log(f"소스 백업 {zp} ({n}개, {size_mb(zp):.1f}MB)")


def main():
    global _logf
    # 화면 출력 인코딩이 한글을 못 받는 환경(파이프 등)에서도 멈추지 않게 — 10/2 출력 없이 끝난 적 있음
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    _logf = open(LOG, "w", encoding="utf-8")
    ver = app_version()
    log(f"배포판 만들기 v{MAKE_VER} — 4Dir v{ver}, 파이썬 {PYVER}")
    backup_old_releases(ver)
    out = os.path.join(REL, f"4Dir_v{ver}")
    if os.path.exists(out):
        shutil.rmtree(out)
        log(f"이전 같은 버전 결과 지움 {out}")
    os.makedirs(out)

    # 1. 휴대용 파이썬
    rt = os.path.join(out, "runtime")
    with zipfile.ZipFile(get_embed()) as z:
        z.extractall(rt)
    pth = [f for f in os.listdir(rt) if f.endswith("._pth")][0]
    zipname = [f for f in os.listdir(rt) if re.match(r"python\d+\.zip$", f)][0]
    with open(os.path.join(rt, pth), "w", encoding="ascii") as f:
        f.write(f"{zipname}\n.\nLib\\site-packages\nimport site\n")   # site-packages + .pth(pywin32) 사용
    log(f"runtime 풀기 완료, {pth} 설정")

    # 2. 패키지 복사 (개발 PC site-packages 에서)
    sp_src = site.getsitepackages()[-1]
    sp = os.path.join(rt, "Lib", "site-packages")
    os.makedirs(sp)
    copy_tree(os.path.join(sp_src, "shiboken6"), os.path.join(sp, "shiboken6"))
    ps_src, ps_dst = os.path.join(sp_src, "PySide6"), os.path.join(sp, "PySide6")
    os.makedirs(ps_dst)
    kept = [f for f in os.listdir(ps_src) if os.path.isfile(os.path.join(ps_src, f)) and PYSIDE_KEEP.match(f)]
    for f in kept:
        shutil.copy2(os.path.join(ps_src, f), os.path.join(ps_dst, f))
    for rel in PYSIDE_PLUGINS:
        s = os.path.join(ps_src, "plugins", rel)
        if not os.path.exists(s) and os.path.exists(os.path.join(QT_PLUGINS_EXTRA, rel)):
            s = os.path.join(QT_PLUGINS_EXTRA, rel)
            log(f"  plugins/{rel} ← _build/qt_plugins")
        if os.path.exists(s):
            os.makedirs(os.path.dirname(os.path.join(ps_dst, "plugins", rel)), exist_ok=True)
            shutil.copy2(s, os.path.join(ps_dst, "plugins", rel))
        else:
            log(f"  (없음, 건너뜀) plugins/{rel}")
    log(f"PySide6 {len(kept)}개 파일 + 플러그인 {len(PYSIDE_PLUGINS)}개 ({size_mb(ps_dst):.1f}MB, 원본 {size_mb(ps_src):.0f}MB)")
    for d in PYWIN_DIRS:
        copy_tree(os.path.join(sp_src, d), os.path.join(sp, d), skip_dirs={"test", "Demos", "demos"})
    for f in PYWIN_FILES:
        if os.path.exists(os.path.join(sp_src, f)):
            shutil.copy2(os.path.join(sp_src, f), os.path.join(sp, f))
    log(f"pywin32 복사 ({sum(size_mb(os.path.join(sp, d)) for d in PYWIN_DIRS):.1f}MB)")

    # 3. 프로그램
    copy_tree(BIN, os.path.join(out, "bin"), skip_dirs=BIN_SKIP_DIRS, skip_re=BIN_SKIP_FILES)
    shutil.copy2(os.path.join(ROOT, "4Dir.vbs"), os.path.join(out, "4Dir.vbs"))
    shipped = sorted(os.listdir(os.path.join(out, "bin")))
    log(f"bin 파일: {shipped}")
    leaked = [f for f in shipped if BIN_SKIP_FILES.match(f)]
    if leaked:
        raise SystemExit(f"개인 파일이 섞였습니다: {leaked}")
    with open(os.path.join(out, "사용법.txt"), "w", encoding="utf-8-sig") as f:
        f.write(USAGE.format(ver=ver))
    with open(os.path.join(out, "お読みください.txt"), "w", encoding="utf-8-sig") as f:
        f.write(USAGE_JA.format(ver=ver))
    # 사용법 그림 (설명까지 한 장 — 웹 게시용): bin/guide/<언어>/full_pN.png → 사용법 그림/<언어>/사용법_N.png
    gdir = os.path.join(BIN, "guide")
    nimg = 0
    for lg in ("ko", "en"):
        src = os.path.join(gdir, lg)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(out, "사용법 그림", lg)
        os.makedirs(dst, exist_ok=True)
        for fn in sorted(os.listdir(src)):
            if fn.startswith("full_p") and fn.endswith(".png"):
                shutil.copy2(os.path.join(src, fn), os.path.join(dst, ("사용법_" if lg == "ko" else "guide_") + fn[6:]))
                nimg += 1
        for fn in [x for x in os.listdir(os.path.join(out, "bin", "guide", lg)) if x.startswith("full_p")]:
            os.remove(os.path.join(out, "bin", "guide", lg, fn))   # 프로그램 안에는 화면 그림(pN)만
    # 1.4.1: 프로그램 안 사용법 창(guide.py)은 ko·en 의 p1..p6 만 씀 → 사이트용 다른 언어·p7~ 그림은 빼서 zip 을 가볍게
    gout = os.path.join(out, "bin", "guide")
    keep = {f"p{i}.png" for i in range(1, 7)}
    for lg in os.listdir(gout):
        d = os.path.join(gout, lg)
        if lg not in ("ko", "en"):
            shutil.rmtree(d)
            continue
        for fn in os.listdir(d):
            if fn not in keep:
                os.remove(os.path.join(d, fn))
    log(f"사용법 그림 {nimg}장 → 사용법 그림 (ko·en), 프로그램 안 그림 ko·en p1~p6 만 ({size_mb(gout):.1f}MB)")
    if not nimg:
        raise SystemExit("사용법 그림 없음 — _build 의 make_guide.py ko / en 먼저 실행")
    pycs = compile_bin(os.path.join(out, "bin"))
    left = [f for f in os.listdir(os.path.join(out, "bin")) if f.endswith(".py")]
    log(f"컴파일(.pyc) {len(pycs)}개: {pycs} / 남은 .py {left}")
    if left or "main.pyc" not in pycs:
        raise SystemExit("컴파일 실패 — 로그 확인")
    lics = write_licenses(out, sp_src, rt)
    log(f"라이선스 문서: {lics}")

    # 4. 실행 확인 (이 runtime 만으로 필요한 모듈이 다 불러와지는지 — 개발 PC 파이썬 경로를 섞지 않음)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "CONDA"))}
    env["PATH"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    chk = subprocess.run([os.path.join(rt, "python.exe"), "-B", "-c",   # -B: 배포 폴더에 __pycache__ 안 남김
                          "import sys;sys.path.insert(0,r'%s');"
                          "from PySide6 import QtCore,QtGui,QtWidgets,QtNetwork;import win32gui,win32con,pythoncom;"
                          "from win32com.shell import shell;import i18n,shellops,sysmon,favorites,session,ui_parts,keymap,search_index,explorer_check,svnstat,batchrename,guide,favorg,thumbs,overlays,overlayorder,imgconvert;"
                          "print('모듈 OK', sys.version.split()[0], QtCore.qVersion(), search_index.__file__)" % os.path.join(out, "bin")],
                         capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    log(f"실행 확인 rc={chk.returncode} {chk.stdout.strip()} {chk.stderr.strip()[-500:]}")
    if chk.returncode != 0:
        raise SystemExit("runtime 실행 확인 실패 — 로그 확인")
    # 4-2. 컴파일본을 직접 실행할 수 있는지 (색인 작업 프로세스 = search_index.pyc --build)
    tmp_idx = os.path.join(HERE, "_chk_index.bin")
    chk = subprocess.run([os.path.join(rt, "python.exe"), "-B", "-X", "utf8", os.path.join(out, "bin", "search_index.pyc"),
                          "--build", tmp_idx, str(os.getpid()), os.path.join(out, "bin")],
                         capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    ok = chk.returncode == 0 and "OK" in chk.stdout and os.path.exists(tmp_idx)
    log(f"컴파일본 직접 실행 확인 rc={chk.returncode} {chk.stdout.strip()[-200:]} {chk.stderr.strip()[-300:]}")
    if os.path.exists(tmp_idx):
        os.remove(tmp_idx)
    if not ok:
        raise SystemExit("컴파일본 실행 확인 실패 — 로그 확인")
    # 4-3. 회사 관련 글자 검사 (runtime 제외 전체 파일, .pyc 내부 글자 포함) — 하나라도 있으면 중단
    if not CORP_WORDS:
        raise SystemExit("회사 관련 글자 목록(_build\\corp_words.txt)이 없음 — 검사 없이 배포하지 않음")
    hits = []
    for a, _, fs in os.walk(out):
        if os.path.relpath(a, out).split(os.sep)[0] == "runtime":
            continue
        for f in fs:
            p = os.path.join(a, f)
            data = (f + "\n").encode("utf-8") + open(p, "rb").read()
            for w in CORP_WORDS:
                if w.encode("utf-8").lower() in data.lower():
                    hits.append(f"{os.path.relpath(p, out)}: {w}")
    log(f"회사 관련 글자 검사: {len(hits)}건 {hits}")
    if hits:
        raise SystemExit("회사 관련 글자가 배포판에 있음 — 로그 확인")

    # 5. zip
    zp = os.path.join(REL, f"4Dir_v{ver}.zip")
    if os.path.exists(zp):
        os.remove(zp)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for a, _, fs in os.walk(out):
            for f in fs:
                full = os.path.join(a, f)
                z.write(full, os.path.join(f"4Dir_v{ver}", os.path.relpath(full, out)))
    digest = sha256(zp)
    zname = os.path.basename(zp)
    with open(zp + ".sha256.txt", "w", encoding="ascii", newline="\r\n") as f:
        f.write(f"{digest} *{zname}\n")
    with open(os.path.join(REL, f"웹게시_안내_v{ver}.txt"), "w", encoding="utf-8-sig") as f:
        f.write(WEB_NOTE.format(ver=ver, zname=zname, mb=size_mb(zp), digest=digest))
    backup_source(ver)
    log(f"완료: 폴더 {size_mb(out):.0f}MB, zip {size_mb(zp):.1f}MB, SHA256 {digest}")
    log(f"  {zp}")
    _logf.close()


USAGE = """4Dir v{ver} — 여러 칸 분할(최대 20칸) + 탭 파일 관리자 (3ds Max 와 같이 써도 느려지지 않게 만듦)

[English quick start]
  1. Before extracting: right-click the downloaded zip > Properties > check 'Unblock' > OK.
  2. Copy this folder anywhere on your PC and double-click 4Dir.vbs. No installation, no Python needed.
  3. Language: View > Language (follows the Windows display language by default; restart 4Dir to apply).
     Tabs: drag a tab to another pane to move it, or outside the window to open a new window. Favorites > Organize favorites.
  4. Problems: Tools > 'Save log for problem report' creates a zip in the 4Dir 'reports' folder (opened for you) — please send it.

[설치]
  0. (인터넷에서 받은 경우) 압축을 풀기 전에 zip 파일 우클릭 > 속성 > 아래쪽 '차단 해제' 체크 > 확인.
     이걸 안 하면 4Dir.vbs 를 실행할 때마다 윈도우 '보안 경고' 창이 뜹니다.
     (이미 풀었다면: 4Dir.vbs 우클릭 > 속성 > '차단 해제' 체크)
  1. 이 폴더를 원하는 곳(예: D:\\Tools\\4Dir)에 통째로 복사합니다. 설치 과정은 없습니다.
     (네트워크 드라이브에서 바로 실행하지 말고 내 PC 로 복사해서 쓰세요.)
  2. 4Dir.vbs 를 더블클릭하면 실행됩니다. 파이썬 설치 필요 없음(runtime 폴더에 들어 있음).
  3. 바탕화면 바로가기: 4Dir.vbs 우클릭 > 보내기 > 바탕 화면에 바로 가기 만들기.
  지우기: 이 폴더를 통째로 지우면 끝입니다(레지스트리·시스템에 남기는 것 없음).

[자주 쓰는 기능]
  - 상단 레이아웃 아이콘: 1 / 2 / 3 / 4 / 6칸, 격자 버튼 = 직접 지정(가로 x 세로, 최대 5 x 4)
  - 칸마다 탭: Ctrl+T 새 탭, Ctrl+W 닫기, Ctrl+Shift+T 닫은 탭 다시 열기, 가운데 클릭 = 새 탭/닫기
  - 전체 검색: Ctrl+Shift+F (드라이브 전체 이름 검색, 처음 한 번 색인을 만드는 데 몇 분 걸림)
    검색 범위는 도구 > 검색 범위 설정 (외장하드·네트워크·구글드라이브는 켜야 검색됨)
  - 즐겨찾기: 폴더를 즐겨찾기 줄에 끌어다 놓기 / 폴더 우클릭 > ★ 4Dir 즐겨찾기에 추가 / Ctrl+D
    즐겨찾기 > 즐겨찾기 정리: 여러 개 삭제·순서 바꾸기·묶음(폴더처럼 모으기)·없어진 폴더 찾기
  - 탭 끌기: 탭줄 안에서 좌우 = 순서, 탭을 끌어 다른 칸에 놓으면 그 칸으로 옮김, 4Dir 창 밖에 놓으면 새 창
  - 이름 일괄 변경: 여러 개 선택 후 F2 (또는 도구 > 이름 일괄 변경) / Ctrl+Z = 마지막 작업 되돌리기
  - 빠른 필터: Ctrl+F (현재 폴더에서 이름으로 거르기)
  - 다른 칸으로 복사 F6, 이동 Shift+F6 (직전에 쓰던 칸으로)
  - 버전 관리 표시: SVN 은 4Dir 가 직접, Git·Perforce 등은 PC 에 깔린 연동 도구(TortoiseGit·P4EXP 등)의 표시를 그대로 보여 줌
    표시가 안 나오면 도구 > 겹침 아이콘 순서 정리 (윈도우는 앞의 11개만 씀)
  - 아이콘 보기(작은·보통·큰 아이콘)에서는 그림 파일을 미리보기로 보여 줌 (보기 > 표시 > 그림 미리보기로 끄기)
  - 보기 메뉴: 자세히/아이콘, 숨긴 항목, 확장명, 경로 버튼, 화면 테마(시스템/밝게/어둡게), 색상, 항상 위, CPU·GPU 표시
  - 보기 > 언어 (Language): 10개 언어. 기본은 윈도우 표시 언어. 다시 시작하면 적용.
    번역은 bin\\lang\\<언어>.json — 메모장으로 고칠 수 있습니다.
  - 창 저장/불러오기: 지금 탭 구성을 이름 붙여 저장 / 갑자기 꺼졌을 때 자동 기록에서 복구
  - 도구 > Explorer Check(탐색기 점검): 윈도우 탐색기가 느릴 때 원인 점검·해결
    (4Dir 가 안 열릴 때는 bin\\탐색기 점검.vbs 를 직접 실행)

[문제가 생기면]
  도구 > '문제 보고용 로그 저장' 을 누르면 4Dir 폴더 안 reports 에 zip 파일이 생기고 탐색기로 보여 줍니다. 그 파일을 보내 주세요.
  (4Dir 가 아예 안 열리면 bin\\log 폴더를 통째로 보내 주세요.)

[라이선스]
  함께 들어 있는 파이썬·PySide6(Qt)·pywin32 의 라이선스는 licenses 폴더에 있습니다.
"""

# 1.6.0: 일본어 설명서 — Vector 掲載基準(概要·連絡先·取り扱い種別·動作環境·インストール/アンインストール·外部通信の明記)을 채움
USAGE_JA = """4Dir v{ver} — 最大20分割・各ペインにタブを持つファイラー

■概要
1つのウィンドウを最大20ペイン(5×4)まで分割でき、どのペインにも独立したタブがあるファイラーです。
3ds Max などの重いアプリの横で使っても軽く動くように作りました。
- 1・2・3・4・6分割はボタン1つ、格子ボタンで横×縦を自由に指定
- 自前の索引による、入力と同時のファイル名検索(管理者権限不要)
- 画像・PSD・3ds Max ファイルのサムネイル、プレビューウィンドウ、動く GIF の再生
- Windows の右クリックメニューをそのまま使用。ZIP/7z/TAR 圧縮、WebP → PNG/JPG 変換
- SVN の状態表示、エクスプローラーとのドラッグ&ドロップ、一括リネーム、セッション復元
- Ctrl+Alt+F でどのアプリからでも全体検索
- ライト/ダーク表示、10言語(日本語を含む)

■取り扱い種別
フリーソフト(オープンソース、GNU GPL v3)。広告なし、アカウント不要。

■動作環境
Windows 10 / 11(64ビット)。Python は同梱しているため、別途必要なソフトはありません。

■インストール
1. 展開する前に、ダウンロードした zip を右クリック > プロパティ > 下の「許可する」にチェック > OK。
   (これをしないと 4Dir.vbs を実行するたびに Windows のセキュリティ警告が出ます)
2. このフォルダーを好きな場所(例: D:\\Tools\\4Dir)にフォルダーごとコピーします。
   (ネットワークドライブ上で直接実行せず、自分の PC にコピーして使ってください)
3. 4Dir.vbs をダブルクリックすると起動します。
4. 表示言語: 表示 > 言語(初期値は Windows の表示言語。再起動で反映)

■アンインストール
このフォルダーをフォルダーごと削除すれば完了です。レジストリやシステムには何も残しません。
(「プログラムの追加と削除」には表示されません)

■主な操作
- Ctrl+T 新しいタブ、Ctrl+W タブを閉じる、Ctrl+Shift+T 閉じたタブを開き直す
- Ctrl+Shift+F 全体検索(初回のみ索引作成に数分)、検索範囲は ツール > 検索範囲
- Ctrl+F 現在のフォルダーで名前を絞り込み、F2(複数選択時) 一括で名前を変更
- F6 隣のペインへコピー、Shift+F6 移動、Ctrl+D お気に入りに追加
- タブをほかのペインへドラッグで移動、ウィンドウの外へドラッグで新しいウィンドウ
- 詳しい使い方(画像付き): https://4dir.net/ja/guide.html

■外部への通信について(誤検出の可能性)
- 起動時に1日1回、新しいバージョンがあるかを確認します(4dir.net のバージョン情報ファイルを読むだけ)。
  ツール > 「起動時に新しいバージョンを確認（1日1回）」でオフにできます。個人情報は送信しません。
- まだコード署名がないため、初回に SmartScreen が表示されることがあります。
- 実行には同梱の Python(python.org 公式の署名付き配布物)を使い、exe は新たに作っていません。

■連絡先
作者: gkstmdahr
メール: support@4dir.net
紹介ページ: https://4dir.net/ja/
ソースコード: https://github.com/gkstmdahr/4Dir
問題が起きたら: ツール > 問題報告用ログを保存 → 4Dir フォルダー内 reports にできた zip を送ってください。

■同梱しているほかの著作物
Python(PSF License)、PySide6 / Qt 6(GNU LGPL v3)、pywin32(PSF License)。
いずれも使用が許可されているもので、ライセンス文書は licenses フォルダーにあります。
"""

LICENSE_NOTE = """4Dir 에 함께 들어 있는 구성 요소와 라이선스

1. Python {py} (python.org 공식 휴대용 배포판) — runtime 폴더
   라이선스: PSF License — Python_LICENSE.txt
   출처: https://www.python.org/

2. PySide6 / Shiboken6 / Qt 6 ({qt}) — runtime\\Lib\\site-packages\\PySide6, shiboken6
   라이선스: GNU LGPL v3 — PySide6_Qt_LGPL-3.0.txt (LGPL v3 가 참조하는 GPL v3 원문: PySide6_Qt_GPL-3.0.txt)
   원본 소스: https://code.qt.io/  ·  https://download.qt.io/official_releases/QtForPython/
   변경하지 않은 공식 배포 파일(DLL·pyd)을 그대로 넣었으며, 사용자는 이 파일들을 같은 버전 또는 호환 버전으로 바꿔 쓸 수 있습니다.

3. pywin32 ({pw}) — runtime\\Lib\\site-packages\\win32, win32com, pywin32_system32 등
   라이선스: PSF License — pywin32_License.txt
   출처: https://github.com/mhammond/pywin32

4Dir 본체(bin 폴더)는 위 구성 요소를 사용하는 별도 프로그램입니다.

4. 4Dir 본체 — bin 폴더, 4Dir.vbs
   라이선스: GNU GPL v3 — 4Dir_GPL-3.0.txt (자유 소프트웨어, 원본 소스는 공개 저장소)
"""

WEB_NOTE = """[웹 게시용] 4Dir v{ver}

올릴 파일: {zname} ({mb:.1f}MB)
정품 확인 지문(SHA256): {digest}

--- 다운로드 페이지에 적을 문구 (복사해서 쓰세요) ---
4Dir v{ver} — 여러 칸 분할 + 탭 파일 관리자 (설치 없음, 압축 풀고 4Dir.vbs 실행)

설치 전에: 받은 zip 파일 우클릭 > 속성 > '차단 해제' 체크 > 확인 → 그다음 압축 풀기.
  (안 하면 실행할 때마다 윈도우 보안 경고 창이 뜹니다)

정품 확인(선택): 명령 프롬프트(cmd)에서
  certutil -hashfile {zname} SHA256
결과가 아래 지문과 같으면 받은 파일이 고쳐지지 않은 정품입니다.
  {digest}

문제가 생기면: 4Dir 의 도구 > '문제 보고용 로그 저장' → 4Dir 폴더 안 reports 에 생긴 zip 파일을 보내 주세요.
"""

if __name__ == "__main__":
    main()
