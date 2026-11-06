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
PINFIX_VER = "1.0.0"

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


def fix(root, ver, dirs=None, shell=None):
    """root = 지금 4Dir 폴더, ver = 지금 버전 문자열. 고친 바로가기 경로 목록"""
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
