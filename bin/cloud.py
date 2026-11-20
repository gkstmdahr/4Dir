# -*- coding: utf-8 -*-
"""클라우드 동기화 폴더(원드라이브 등) 상태 (CLOUD_VER 1.0.0, v0.9.94 사용자 의견 11/4: '원드라이브 상태 표시')

- 동기화 폴더 = 윈도우 클라우드 파일 등록(HKLM\\...\\Explorer\\SyncRootManager\\<id>\\UserSyncRoots 값 = 폴더 경로).
  원드라이브·구글 드라이브·드롭박스 등 윈도우 클라우드 파일 방식을 쓰는 프로그램 공통. 1분마다 한 번만 다시 읽음.
- 파일 상태 = 목록 읽을 때 이미 받은 파일 속성만 봄 (디스크·네트워크 추가 읽기 없음):
    클라우드에만 있음 = RECALL_ON_DATA_ACCESS(0x400000)·RECALL_ON_OPEN(0x40000)·OFFLINE(0x1000)
    항상 이 PC 에 유지 = PINNED(0x80000)
    그 밖(동기화 폴더 안) = 이 PC 에 있음
- '동기화 중'(파란 화살표)은 속성에 없음 → 아직 안 함 (실제 원드라이브에서 재 보고 정할 것)
"""
import os
import time
import logging

from i18n import T

log = logging.getLogger("QE.cloud")

CLOUD_VER = "1.2.0"   # 1.2.0: 폴더 상태는 원드라이브에 물어봄(folder_states) + 동기화 중 상태 / 1.1.0: nav_roots — 탐색 창에 원드라이브 등 (0.9.142)
A_OFFLINE, A_RECALL_OPEN, A_PINNED, A_UNPINNED, A_RECALL_ACCESS = 0x1000, 0x40000, 0x80000, 0x100000, 0x400000
_roots = {"t": 0.0, "list": []}
TTL = 60.0

# 상태 → (정렬 순서, 풍선 글자)
STATES = {"sync": (0, T("동기화 중")),   # 1.2.0 탐색기 파란 화살표 (폴더·바로 가기 등 — 원드라이브에 물어 본 값)
          "cloud": (1, T("클라우드에만 있음 (열면 내려받음)")),
          "local": (2, T("이 PC 에 있음")),
          "pinned": (3, T("항상 이 PC 에 유지"))}


def _read_roots():
    import winreg
    out = []
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return out
    with k:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(k, sub + r"\UserSyncRoots") as u:
                    j = 0
                    while True:
                        try:
                            _sid, val, _t = winreg.EnumValue(u, j)
                        except OSError:
                            break
                        j += 1
                        if isinstance(val, str) and val:
                            out.append((os.path.normcase(os.path.normpath(val)), sub))
            except OSError:
                continue
    return out


def _label(sub, path):
    """동기화 폴더 표시 이름: 등록 값 DisplayNameResource('OneDrive', '@파일,-번호' 꼴이면 윈도우로 풀어 읽음) → 없으면 폴더 이름"""
    import winreg
    try:   # 탐색기와 같은 이름 ('승목 - 개인' 처럼 원드라이브가 셸에 알려 준 이름)
        from win32com.shell import shell, shellcon
        it = shell.SHCreateItemFromParsingName(path, None, shell.IID_IShellItem)
        name = it.GetDisplayName(shellcon.SIGDN_NORMALDISPLAY)
        if name:
            return name
    except Exception:
        log.debug("셸 표시 이름 못 읽음 %s", path, exc_info=True)
    name = ""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager\\" + sub) as k:
            name = winreg.QueryValueEx(k, "DisplayNameResource")[0] or ""
    except OSError:
        pass
    if name.startswith("@"):
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shlwapi.SHLoadIndirectString(name, buf, 260, None) == 0:
            name = buf.value
        else:
            name = ""
    return name or os.path.basename(path.rstrip("\\")) or path


def nav_roots():
    """1.1.0 (0.9.142 사용자 11/20 '원드라이브 탐색 창에 넣어'): 탐색 창에 보일 동기화 폴더 [(실제 경로, 표시 이름)].
    지금 사용자 것만(UserSyncRoots 값 이름 = 내 SID), 실제로 있는 폴더만. 같은 이름이 둘 이상이면 '이름 - 폴더 이름'.
    칸마다 탐색 창이 있어도 1분 안에는 한 번만 읽음"""
    now = time.time()
    if now - _nav["t"] < TTL:
        return list(_nav["list"])
    _nav["list"] = _nav_read()
    _nav["t"] = now
    return list(_nav["list"])


_nav = {"t": 0.0, "list": []}


def _nav_read():
    out = []
    try:
        import winreg
        sid = _my_sid()
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub + r"\UserSyncRoots") as u:
                        j = 0
                        while True:
                            try:
                                vsid, val, _t = winreg.EnumValue(u, j)
                            except OSError:
                                break
                            j += 1
                            if isinstance(val, str) and val and (not sid or vsid.lower() == sid.lower()) and os.path.isdir(val):
                                out.append((os.path.normpath(val), _label(sub, val)))
                except OSError:
                    continue
    except Exception:
        log.exception("탐색 창용 동기화 폴더 못 읽음")
        return []
    names = [n for _p, n in out]
    out = [(p, n if names.count(n) == 1 else f"{n} - {os.path.basename(p)}") for p, n in out]
    seen, uniq = set(), []
    for p, n in out:
        if os.path.normcase(p) not in seen:
            seen.add(os.path.normcase(p)); uniq.append((p, n))
    log.info("탐색 창 동기화 폴더 %d개 %s", len(uniq), uniq[:5])
    return uniq


def _my_sid():
    """지금 사용자 SID 글자 (못 구하면 '' → 거르지 않음)"""
    try:
        import win32api, win32security
        tok = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(tok, win32security.TokenUser)[0])
    except Exception:
        log.exception("SID 못 읽음")
        return ""

def roots():
    """[(정규화 경로, 이름)] — 1분 기억"""
    now = time.time()
    if now - _roots["t"] > TTL:
        try:
            _roots["list"] = _read_roots()
        except Exception:
            log.exception("동기화 폴더 목록 못 읽음")
            _roots["list"] = []
        _roots["t"] = now
        log.info("동기화 폴더 %d개 %s", len(_roots["list"]), [r for r, _n in _roots["list"]][:5])
    return _roots["list"]


def root_of(path):
    """path 가 동기화 폴더 안이면 그 동기화 폴더 이름(등록 이름), 아니면 None"""
    if not path or path.startswith("::"):
        return None
    p = os.path.normcase(os.path.normpath(path))
    for r, name in roots():
        if p == r or p.startswith(r.rstrip("\\") + "\\"):
            return name
    return None


def state(attrs):
    """동기화 폴더 안 항목의 상태 이름 (속성만 봄)"""
    attrs = attrs or 0
    if attrs & (A_RECALL_ACCESS | A_RECALL_OPEN | A_OFFLINE):
        return "cloud"
    if attrs & A_PINNED:
        return "pinned"
    return "local"


_icons = {}


def icon(st, px=16):
    """탐색기와 비슷한 상태 그림: 구름(파란 테두리) · 초록 테두리 체크 · 초록 동그라미 흰 체크"""
    key = (st, px)
    if key in _icons:
        return _icons[key]
    from PySide6 import QtGui, QtCore
    from PySide6.QtCore import Qt
    dpr = 2
    pm = QtGui.QPixmap(px * dpr, px * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(dpr, dpr)
    s = px / 16.0
    if st == "sync":   # 1.2.0 두 화살표가 도는 모양 (탐색기 동기화 중)
        pen = QtGui.QPen(QtGui.QColor("#1f6fd1"), 1.4 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = QtCore.QRectF(3 * s, 3 * s, 10 * s, 10 * s)
        p.drawArc(r, 20 * 16, 140 * 16)
        p.drawArc(r, 200 * 16, 140 * 16)
        p.drawPolyline([QtCore.QPointF(2.6 * s, 4.6 * s), QtCore.QPointF(3.6 * s, 7.4 * s), QtCore.QPointF(6.2 * s, 6.4 * s)])
        p.drawPolyline([QtCore.QPointF(13.4 * s, 11.4 * s), QtCore.QPointF(12.4 * s, 8.6 * s), QtCore.QPointF(9.8 * s, 9.6 * s)])
    elif st == "cloud":
        pen = QtGui.QPen(QtGui.QColor("#1f6fd1"), 1.3 * s)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QtGui.QPainterPath()
        path.moveTo(4 * s, 12 * s)
        path.arcTo(QtCore.QRectF(1.5 * s, 7.5 * s, 5 * s, 4.5 * s), 270, -180)
        path.arcTo(QtCore.QRectF(4 * s, 3.5 * s, 7.5 * s, 7 * s), 160, -150)
        path.arcTo(QtCore.QRectF(10 * s, 6.5 * s, 5 * s, 5.5 * s), 90, -180)
        path.lineTo(4 * s, 12 * s)
        p.drawPath(path)
    else:
        green = QtGui.QColor("#1e8e3e")
        r = QtCore.QRectF(2 * s, 2 * s, 12 * s, 12 * s)
        if st == "pinned":
            p.setPen(Qt.NoPen)
            p.setBrush(green)
            p.drawEllipse(r)
            ck = QtGui.QColor("#ffffff")
        else:
            p.setPen(QtGui.QPen(green, 1.3 * s))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)
            ck = green
        p.setPen(QtGui.QPen(ck, 1.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QtCore.QPointF(5 * s, 8.2 * s), QtCore.QPointF(7.2 * s, 10.3 * s), QtCore.QPointF(11 * s, 6 * s)])
    p.end()
    pm.setDevicePixelRatio(dpr)
    _icons[key] = pm
    return pm

def nav_icon(path, px=16):
    """탐색 창 아이콘 = 등록 값 IconResource('...OneDrive.exe,-501') 의 아이콘 (탐색기 파란 구름). 못 읽으면 None"""
    key = ("nav", path, px)
    if key in _icons:
        return _icons[key]
    ico = None
    try:
        import winreg, ctypes
        from PySide6 import QtGui
        pc = os.path.normcase(os.path.normpath(path))
        res = ""
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
        for r, sub in roots():
            if r == pc:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + "\\" + sub) as k:
                    res = winreg.QueryValueEx(k, "IconResource")[0] or ""
                break
        if res and "," in res:
            f, idx = res.rsplit(",", 1)
            f = os.path.expandvars(f.strip().strip('"'))
            big, small = ctypes.c_void_p(), ctypes.c_void_p()
            n = ctypes.windll.shell32.ExtractIconExW(f, int(idx), ctypes.byref(big), ctypes.byref(small), 1)
            h = big.value or small.value
            if n and h:
                img = QtGui.QImage.fromHICON(h)
                for x in (big.value, small.value):
                    if x:
                        ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(x))
                if not img.isNull():
                    ico = QtGui.QIcon(QtGui.QPixmap.fromImage(img))
        log.info("탐색 창 동기화 폴더 아이콘 %s ← %s %s", path, res, "있음" if ico else "없음")
    except Exception:
        log.exception("동기화 폴더 아이콘 못 읽음 %s", path)
    _icons[key] = ico
    return ico

# 1.2.0 (0.9.142 빌드 2, 사용자 11/20 '왜 2개 아이콘이 달라?'): 폴더는 속성만으로는 상태를 모름(원드라이브가 폴더 속성은 그대로 둠)
# → 탐색기처럼 원드라이브에 물어 봄: 셸 속성 System.StorageProviderState (항목 하나 약 16ms 라 폴더만, 뒤 스레드에서)
_PSTATE = {1: "cloud", 2: "local", 3: "pinned", 4: "sync", 5: "sync", 6: "sync", 10: "sync"}


def folder_states(paths, limit=500):
    """{경로: 상태 이름} — 원드라이브 등이 알려 준 값. 못 읽거나 모르는 값은 빠짐(→ 속성으로 판정). 뒤 스레드에서 부를 것(COM 준비함)"""
    out = {}
    if not paths:
        return out
    import pythoncom
    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
    t0 = time.time()
    raw = {}
    try:
        from win32com.shell import shell
        from win32com.propsys import propsys
        key = propsys.PSGetPropertyKeyFromName("System.StorageProviderState")
        for p in paths[:limit]:
            try:
                v = shell.SHCreateItemFromParsingName(p, None, shell.IID_IShellItem2).GetProperty(key)
                raw[os.path.basename(p)] = v
                if v in _PSTATE:
                    out[p] = _PSTATE[v]
            except Exception:
                continue
    except Exception:
        log.exception("동기화 상태(셸) 못 읽음")
    finally:
        pythoncom.CoUninitialize()
    log.info("동기화 상태 폴더 %d개 물어봄 %.0fms → %s", min(len(paths), limit), (time.time() - t0) * 1000, dict(list(raw.items())[:8]))
    return out
