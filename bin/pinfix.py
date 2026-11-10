# -*- coding: utf-8 -*-
"""작업 표시줄·시작 메뉴·바탕 화면에 고정된 4Dir 바로가기를 지금 버전 폴더로 고침 (0.9.112, 사용자 제보 11/6)

배경: 배포판은 버전마다 폴더가 다름(4Dir_v0.9.110, 4Dir_v0.9.111 ...). 작업 표시줄에 고정하면 윈도우가
그때 폴더의 4Dir.vbs 를 바로가기에 적어 둠 → 옛 폴더를 지우면 고정 단추가 '스크립트 파일을 찾을 수 없음' 오류.
새 버전을 한 번 실행하면 여기서 바로가기를 새 폴더로 바꿈.

바꾸는 조건 (다른 프로그램 바로가기는 건드리지 않음):
- 대상이 wscript.exe + 인자에 4Dir.vbs, 또는 대상이 4Dir.exe 인 바로가기만
- 그 4Dir 폴더가 없어졌거나, 폴더 이름의 버전(4Dir_v0.9.110)이 지금보다 낮을 때만
  (더 새 버전·같은 버전·버전 모를 폴더는 그대로 → 사용자가 일부러 다른 폴더를 고정했으면 존중)
"""
import os
import re
import glob
import logging

log = logging.getLogger("QE.pinfix")
PINFIX_VER = "1.1.1"
# 1.1.1 (11/10): 고정 위치 = %LOCALAPPDATA%\Programs\4Dir\pin (AppData\Local\4Dir 은 보안 규칙에 막힘). 옛 위치 실행기 가리키면 새 위치로
# 1.1.0 (0.9.127 빌드 3, 11/9 실측): 윈도우는 같은 앱(AppID)의 옛 고정 바로가기(User Pinned\ImplicitAppShortcuts)를
# 다시 써서, 고정을 풀었다 다시 해도 창의 새 고정 정보(pin\4Dir_pin.vbs)를 안 씀 → 작업 표시줄 고정 바로가기를
# 버전과 상관없는 고정 위치(%LOCALAPPDATA%\4Dir\pin)의 실행기·아이콘으로 직접 바꿈 (이미 고정한 사용자도 자동으로)

_VER_RE = re.compile(r"4dir[_\- ]?v?(\d+(?:\.\d+)+)", re.I)


def _vtuple(s):
    try:
        return tuple(int(x) for x in s.split("."))
    except ValueError:
        return None


def folder_version(root):
    m = _VER_RE.search(os.path.basename(os.path.normpath(root)))
    return _vtuple(m.group(1)) if m else None


def default_dirs():
    ap = os.environ.get("APPDATA", "")
    out = [os.path.join(ap, r"Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"),
           os.path.join(ap, r"Microsoft\Internet Explorer\Quick Launch\User Pinned\ImplicitAppShortcuts"),
           os.path.join(ap, r"Microsoft\Internet Explorer\Quick Launch\User Pinned\StartMenu"),
           os.path.join(ap, r"Microsoft\Windows\Start Menu\Programs"),
           os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")]
    return [d for d in out if d and os.path.isdir(d)]


def _old_root(target, args):
    """이 바로가기가 4Dir 것이면 그 4Dir 폴더, 아니면 None"""
    t = (target or "").strip().strip('"')
    if os.path.basename(t).lower() == "4dir.exe":
        return os.path.dirname(t)
    if os.path.basename(t).lower() == "wscript.exe":
        m = re.search(r'"([^"]*4Dir\.vbs)"|(\S*4Dir\.vbs)', args or "", re.I)
        if m:
            return os.path.dirname(m.group(1) or m.group(2))
    return None


def pin_dir():
    """작업 표시줄 고정용 실행기·아이콘 폴더 (버전 폴더와 상관없는 고정 위치)"""
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Programs", "4Dir", "pin")


def pin_home():
    """main._pin_home 이 만든 (실행기, 아이콘) — 없으면 (None, None)"""
    home = pin_dir()
    stub, ico = os.path.join(home, "4Dir_pin.vbs"), os.path.join(home, "4Dir.ico")
    return (stub if os.path.isfile(stub) else None), (ico if os.path.isfile(ico) else None)


def _is_pinned(p):
    return "user pinned" in os.path.normcase(p)


def _is_stub(args):
    return "4dir_pin.vbs" in (args or "").lower()


def fix(root, ver, dirs=None, shell=None, stub=None, stub_ico=None):
    """root = 지금 4Dir 폴더, ver = 지금 버전 문자열. 고친 바로가기 경로 목록
    stub/stub_ico = 고정 위치 실행기·아이콘 (None 이면 pin_home() 으로 찾음, '' 이면 안 씀 → 1.0.0 동작)"""
    if stub is None:
        stub, ico0 = pin_home()
        stub_ico = ico0 if stub_ico is None else stub_ico
    cur = _vtuple(ver)
    vbs = os.path.join(root, "4Dir.vbs")
    exe = os.path.join(root, "4Dir.exe")
    if not os.path.exists(vbs) and not os.path.exists(exe):
        log.info("pinfix %s: 실행기 없음(개발 폴더?) → 건너뜀 %s", PINFIX_VER, root)
        return []
    if shell is None:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
    fixed = []
    dirs = default_dirs() if dirs is None else dirs
    n = 0
    for d in dirs:
        for p in glob.glob(os.path.join(d, "*.lnk")) + glob.glob(os.path.join(d, "*", "*.lnk")):
            n += 1
            try:
                lk = shell.CreateShortcut(p)
                old = _old_root(lk.TargetPath, lk.Arguments)
            except Exception:
                log.exception("pinfix 바로가기 읽기 실패 %s", p)
                continue
            if stub and _is_pinned(p) and _is_stub(lk.Arguments):   # 이미 고정 위치 실행기 — 위치·아이콘만 맞춤
                want_a = f'"{stub}"'
                bad_a = os.path.normcase(lk.Arguments or "") != os.path.normcase(want_a)
                bad_i = stub_ico and os.path.normcase(lk.IconLocation or "") != os.path.normcase(stub_ico + ",0")
                if bad_a or bad_i:
                    try:
                        was = (lk.Arguments, lk.IconLocation)
                        if bad_a:
                            lk.Arguments = want_a
                            lk.WorkingDirectory = os.path.dirname(stub)
                        if bad_i:
                            lk.IconLocation = stub_ico + ",0"
                        lk.Save()
                        fixed.append(p)
                        log.info("pinfix 고정 실행기 위치·아이콘 고침 %s : %s → %s, %s", p, was, stub, stub_ico)
                    except Exception:
                        log.exception("pinfix 아이콘 고치기 실패 %s", p)
                continue
            if stub and old and _is_pinned(p):   # 작업 표시줄·시작 고정 → 고정 위치 실행기로 (지금 폴더·없어짐·옛 버전일 때)
                same = os.path.normcase(os.path.normpath(old)) == os.path.normcase(os.path.normpath(root))
                ov = folder_version(old)
                gone = not os.path.isdir(old)
                older = ov is not None and cur is not None and ov < cur
                if same or gone or older:
                    try:
                        was = (lk.TargetPath, lk.Arguments, lk.IconLocation)
                        lk.TargetPath = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wscript.exe")
                        lk.Arguments = f'"{stub}"'
                        lk.WorkingDirectory = os.path.dirname(stub)
                        if stub_ico:
                            lk.IconLocation = stub_ico + ",0"
                        lk.Save()
                        fixed.append(p)
                        log.info("pinfix 고정 위치로 바꿈 %s : %s → %s (옛 폴더 %s, 이유 %s)", p, was, stub, old,
                                 "지금 폴더" if same else ("없어짐" if gone else f"옛 버전 {ov}"))
                    except Exception:
                        log.exception("pinfix 고정 위치로 바꾸기 실패 %s", p)
                    continue
            if not old or os.path.normcase(os.path.normpath(old)) == os.path.normcase(os.path.normpath(root)):
                continue
            ov = folder_version(old)
            gone = not os.path.isdir(old)
            older = ov is not None and cur is not None and ov < cur
            if not (gone or older):
                log.info("pinfix 그대로 둠 %s → %s (있음, 버전 %s)", p, old, ov)
                continue
            try:
                was = (lk.TargetPath, lk.Arguments, lk.IconLocation)
                if os.path.basename(lk.TargetPath).lower() == "4dir.exe" and os.path.exists(exe):
                    lk.TargetPath = exe
                else:
                    lk.Arguments = f'"{vbs}"'
                lk.WorkingDirectory = root
                icon = lk.IconLocation or ""
                if old.lower() in icon.lower():
                    i = icon.lower().index(old.lower())
                    lk.IconLocation = icon[:i] + root + icon[i + len(old):]
                lk.Save()
                fixed.append(p)
                log.info("pinfix 고침 %s : %s → %s (옛 폴더 %s, 이유 %s)", p, was, root, old, "없어짐" if gone else f"옛 버전 {ov}")
            except Exception:
                log.exception("pinfix 바로가기 고치기 실패 %s", p)
    log.info("pinfix %s: 바로가기 %d개 확인, %d개 고침 (폴더 %s)", PINFIX_VER, n, len(fixed), dirs)
    return fixed
