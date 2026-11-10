# -*- coding: utf-8 -*-
r"""윈도우 '새로 만들기' 목록 (SHELLNEW_VER 1.0.0, 0.9.130 빌드 1 — 받은 의견 11/10 '단축키로 빈 txt 만들기,
My메뉴·단축키에 윈도우 새로 만들기 항목을 넣을 수 있게')

- 목록 = 탐색기가 우클릭 '새로 만들기'에 쓰는 것과 같은 곳:
  HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Discardable\PostSetup\ShellNew 의 Classes (탐색기가 만든 목록)
  없으면 HKCR 의 '.확장자' 전부에서 ShellNew 키를 찾음 (느리니 한 번만, 기억)
- 확장자마다 ShellNew 위치: HKCR\.ext\<ProgID>\ShellNew 먼저, 없으면 HKCR\.ext\ShellNew
- 만드는 방법 (탐색기와 같은 값): NullFile = 빈 파일 · Data = 그 바이트 · FileName = 서식 파일 복사
  (절대 경로 또는 %SystemRoot%\ShellNew · %APPDATA%\Microsoft\Windows\Templates · %ProgramData%\Microsoft\Windows\Templates)
  Command·Handler(바로 가기·구글 문서 등 프로그램이 만드는 것)는 4Dir 가 직접 못 만들어 목록에서 뺌 (우클릭 '새로 만들기'에는 그대로 있음)
- 이름 = '새 <형식 이름>.ext' (형식 이름은 윈도우가 주는 것 — '텍스트 문서'), 같은 이름이 있으면 ' (2)'…
로그: bin\log\4Dir.log [QE.shellnew]
"""
import os
import shutil
import logging
import winreg

log = logging.getLogger("QE.shellnew")
SHELLNEW_VER = "1.0.0"
_CACHE = None
SKIP = {"folder", ".library-ms", ".lnk"}   # 새 폴더는 따로 있음, 라이브러리·바로 가기는 마법사(Command)


def _val(key, name):
    try:
        return winreg.QueryValueEx(key, name)
    except OSError:
        return None


def _open(root, path):
    try:
        return winreg.OpenKey(root, path)
    except OSError:
        return None


def _classes():
    k = _open(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Discardable\PostSetup\ShellNew")
    if k is not None:
        v = _val(k, "Classes")
        winreg.CloseKey(k)
        if v and isinstance(v[0], list) and v[0]:
            return list(v[0]), "탐색기 목록"
    out = []   # 탐색기 목록이 없으면 전부 훑음
    i = 0
    while True:
        try:
            n = winreg.EnumKey(winreg.HKEY_CLASSES_ROOT, i)
        except OSError:
            break
        i += 1
        if n.startswith("."):
            out.append(n)
    return out, "전체 훑기"


def _shellnew_key(ext):
    """(ShellNew 키, ProgID) — 없으면 (None, None)"""
    k = _open(winreg.HKEY_CLASSES_ROOT, ext)
    if k is None:
        return None, None
    try:
        prog = (_val(k, "") or [None])[0]
        if prog:
            sk = _open(k, prog + r"\ShellNew")
            if sk is not None:
                return sk, prog
        return _open(k, "ShellNew"), prog
    finally:
        winreg.CloseKey(k)


def _template(name):
    name = os.path.expandvars(name)
    if os.path.isabs(name):
        return name if os.path.isfile(name) else None
    for d in (os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "ShellNew"),
              os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Templates"),
              os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Templates")):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def type_name(ext):
    """윈도우가 보여 주는 형식 이름 ('텍스트 문서') — 못 얻으면 'TXT 파일'"""
    try:
        from win32com.shell import shell, shellcon
        r = shell.SHGetFileInfo("x" + ext, 0x80, shellcon.SHGFI_TYPENAME | shellcon.SHGFI_USEFILEATTRIBUTES)
        n = (r[1][4] or "").strip()
        if n:
            return n
    except Exception:
        log.exception("형식 이름 못 얻음 %s", ext)
    return ext.lstrip(".").upper() + " File"


def types(refresh=False):
    """[(ext, 형식 이름, 만드는 법)] 만드는 법 = ('null',) / ('data', bytes) / ('file', 서식 경로). 이름 순"""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    out = []
    try:
        exts, src = _classes()
    except Exception:
        log.exception("새로 만들기 목록 못 읽음")
        exts, src = [], "오류"
    for ext in exts:
        if not ext.startswith(".") or ext.lower() in SKIP:
            continue
        sk, prog = _shellnew_key(ext)
        if sk is None:
            continue
        try:
            how = None
            if _val(sk, "NullFile") is not None:
                how = ("null",)
            elif _val(sk, "Data") is not None:
                d = _val(sk, "Data")[0]
                how = ("data", d if isinstance(d, bytes) else str(d).encode("mbcs", "replace"))
            elif _val(sk, "FileName") is not None:
                t = _template(str(_val(sk, "FileName")[0]))
                how = ("file", t) if t else None
            if how is None:
                log.info("새로 만들기 %s 건너뜀 (프로그램이 만드는 형식 또는 서식 없음: %s)", ext,
                         [n for n in ("Command", "Handler", "FileName") if _val(sk, n) is not None])
                continue
            out.append((ext.lower(), type_name(ext), how))
        finally:
            winreg.CloseKey(sk)
    out.sort(key=lambda x: x[1].lower())
    _CACHE = out
    log.info("새로 만들기 목록 %s (%s): %s", SHELLNEW_VER, src, [(e, n, h[0]) for e, n, h in out])
    return out


def find(ext):
    for e, n, h in types():
        if e == ext.lower():
            return e, n, h
    return None


def unique_name(folder, base, ext):
    name = base + ext
    n = 1
    while os.path.exists(os.path.join(folder, name)):
        n += 1
        name = f"{base} ({n}){ext}"
    return name


def create(folder, ext, base):
    """folder 에 새 파일 → 만든 경로. base = '새 텍스트 문서' (확장자 빼고). 실패하면 OSError"""
    t = find(ext)
    if t is None:
        raise OSError(f"새로 만들기 형식 없음: {ext}")
    e, _n, how = t
    p = os.path.join(folder, unique_name(folder, base, e))
    if how[0] == "file":
        shutil.copyfile(how[1], p)
    else:
        with open(p, "xb") as f:
            if how[0] == "data":
                f.write(how[1])
    log.info("새 파일 %s (%s, %s)", p, e, how[0] if how[0] != "file" else "서식 " + how[1])
    return p
