# -*- coding: utf-8 -*-
"""4Dir 윈도우 셸 연동 부품.

맥스 안전 원칙:
- 파일/일반 폴더 아이콘·종류 이름은 SHGFI_USEFILEATTRIBUTES 로 '확장자만' 보고 가져온다 (파일을 열지 않음 → 썸네일/아이콘 핸들러 호출 없음).
- 실제 대상을 읽는 아이콘은 드라이브와 특수 폴더(바탕 화면·문서 등)뿐, 작업 스레드에서 시간 제한을 두고 읽는다.
- 우클릭 셸 메뉴는 사용자가 누를 때만 만든다.
- 파일 복사/이동/삭제는 윈도우 기본 SHFileOperation (진행창·휴지통·되돌리기 지원), 별도 스레드에서 실행.
"""
import os
import re
import logging
from i18n import T   # 화면 문구 번역
import threading
import time
import ctypes
import struct
import subprocess
import functools
import winreg

from PySide6 import QtGui
from win32com.shell import shell, shellcon
import win32con
import win32gui

log = logging.getLogger("QE.shell")

FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_NORMAL = 0x80

# ---------------------------------------------------------------- 시스템 아이콘 목록 (크기별)
_IMAGELIST_IID = None
_imagelists = {}          # shil -> IImageList 포인터
_SHIL = {16: 1, 32: 0, 48: 2, 256: 4}   # SHIL_SMALL, SHIL_LARGE, SHIL_EXTRALARGE, SHIL_JUMBO


def _shil_for(size):
    for s in (16, 32, 48, 256):
        if size <= s:
            return s
    return 256


def _imagelist(px):
    """IImageList 포인터 (shell32 #727 SHGetImageList)"""
    global _IMAGELIST_IID
    if px in _imagelists:
        return _imagelists[px]
    if _IMAGELIST_IID is None:
        _IMAGELIST_IID = _guid("{46EB5926-582E-4017-9FDF-E8998DAA0950}")
    f = ctypes.windll.shell32[727]
    f.argtypes = [ctypes.c_int, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    f.restype = ctypes.c_long
    p = ctypes.c_void_p()
    hr = f(_SHIL[px], ctypes.byref(_IMAGELIST_IID), ctypes.byref(p))
    _imagelists[px] = p.value if hr >= 0 else None
    if hr < 0:
        log.warning("SHGetImageList(%d) 실패 hr=0x%08X", px, hr & 0xFFFFFFFF)
    return _imagelists[px]


_icon_by_idx = {}         # (sysidx, px) -> QIcon


def icon_by_index(idx, size=16):
    """시스템 아이콘 번호 → QIcon (GUI 스레드에서만)"""
    px = _shil_for(size)
    key = (idx, px)
    if key in _icon_by_idx:
        return _icon_by_idx[key]
    icon = QtGui.QIcon()
    il = _imagelist(px)
    if il and idx is not None and idx >= 0:
        h = ctypes.c_void_p()
        # IImageList::GetIcon (vtable 10), ILD_TRANSPARENT=1
        if _com(il, 10, [ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)], idx, 1, ctypes.byref(h)) >= 0 and h.value:
            icon = QtGui.QIcon(QtGui.QPixmap.fromImage(QtGui.QImage.fromHICON(h.value)))
            win32gui.DestroyIcon(h.value)
    _icon_by_idx[key] = icon
    return icon


# ---------------------------------------------------------------- 확장자 기준 아이콘/종류 (파일을 열지 않음)
_ext_info = {}            # key -> (sysidx, 종류이름)


def _ext_key(name, is_dir):
    if is_dir:
        return "<dir>"
    ext = os.path.splitext(name)[1].lower()
    return ext or "<noext>"


def _query(key):
    if key == "<dir>":
        fake, attr = "folder", FILE_ATTRIBUTE_DIRECTORY
    elif key == "<noext>":
        fake, attr = "file", FILE_ATTRIBUTE_NORMAL
    else:
        fake, attr = "file" + key, FILE_ATTRIBUTE_NORMAL
    flags = shellcon.SHGFI_USEFILEATTRIBUTES | shellcon.SHGFI_SYSICONINDEX | shellcon.SHGFI_TYPENAME
    idx, tname = -1, ""
    try:
        ret, info = shell.SHGetFileInfo(fake, attr, flags)
        _h, idx, _a, _d, tname = info
    except Exception:
        log.exception("SHGetFileInfo 실패 key=%s", key)
    _ext_info[key] = (idx, tname or (key.lstrip(".").upper() + T(" 파일") if key.startswith(".") else ""))


def ext_index(name, is_dir):
    key = _ext_key(name, is_dir)
    if key not in _ext_info:
        _query(key)
    return _ext_info[key][0]


def icon_for(name, is_dir, size=16, sysidx=None):
    return icon_by_index(sysidx if sysidx is not None else ext_index(name, is_dir), size)


def type_for(name, is_dir):
    key = _ext_key(name, is_dir)
    if key not in _ext_info:
        _query(key)
    return _ext_info[key][1]


# ---------------------------------------------------------------- 드라이브·특수 폴더 (실제 대상 읽음 → 작업 스레드 전용)
_KNOWN = [  # (FOLDERID, 기본 이름, User Shell Folders 값 이름)
    ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "바탕 화면", "Desktop"),
    ("{374DE290-123F-4565-9164-39C4925E467B}", "다운로드", "{374DE290-123F-4565-9164-39C4925E467B}"),
    ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "문서", "Personal"),
    ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", "사진", "My Pictures"),
    ("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "동영상", "My Video"),
    ("{4BD8D571-6D19-48D3-BE97-422220080E43}", "음악", "My Music"),
]


def _user_shell_folder(name):
    """레지스트리의 현재 위치 (HKCU ...\\User Shell Folders) — 매번 읽음. 없으면 ''"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return os.path.expandvars(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


def known_folders():
    """[(이름, 경로)] — 리디렉션된 실제 경로 (예: 다운로드 = E:\\Downloads).
    v0.9.55: 레지스트리를 먼저 매번 읽음 — SHGetKnownFolderPath 는 프로세스 안에 위치를 기억해서, 4Dir 가 켜진 뒤
    다른 프로그램이 위치를 바꾸면 옛 위치를 계속 줌(10/21 실측: 다운로드가 바탕 화면으로 잘못 가 있던 때 켠 4Dir 가
    고친 뒤에도 '내 PC'에 바탕 화면 두 개). 레지스트리 값이 없을 때만 SHGetKnownFolderPath"""
    out = []
    f = ctypes.windll.shell32.SHGetKnownFolderPath
    f.argtypes = [ctypes.POINTER(_GUID), ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    for gid, label, regname in _KNOWN:
        fp = _user_shell_folder(regname)
        if not fp:
            p = ctypes.c_wchar_p()
            if f(ctypes.byref(_guid(gid)), 0, None, ctypes.byref(p)) >= 0 and p.value:
                fp = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
        if fp:
            out.append((label, fp))
    return out


def _net_remote(letter):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Network\\" + letter[0]) as k:
            return winreg.QueryValueEx(k, "RemotePath")[0]
    except OSError:
        return ""


def real_info(path, timeout=2.0):
    """(표시이름, 시스템아이콘번호) — 드라이브/특수폴더용. 작업 스레드에서 호출. 응답 없으면 (대체이름, None)"""
    box = {}

    def run():
        import pythoncom
        pythoncom.CoInitialize()
        try:
            _r, info = shell.SHGetFileInfo(path, 0, shellcon.SHGFI_SYSICONINDEX | shellcon.SHGFI_DISPLAYNAME)
            box["v"] = (info[3], info[1])
        except Exception as e:
            box["e"] = e
        finally:
            pythoncom.CoUninitialize()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if "v" in box:
        return box["v"]
    fallback = path
    if len(path) <= 3 and path[1:2] == ":":
        remote = _net_remote(path)
        fallback = f"{os.path.basename(remote.rstrip(chr(92))) or remote} ({path[:2]})" if remote else f"({path[:2]})"
    log.warning("대상 정보 응답 없음/실패 %s (%s) → %s", path, box.get("e", "시간 초과"), fallback)
    return fallback, None


# ---------------------------------------------------------------- 정렬 (탐색기와 같은 자연 정렬)
_StrCmpLogicalW = ctypes.windll.shlwapi.StrCmpLogicalW
_StrCmpLogicalW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_StrCmpLogicalW.restype = ctypes.c_int
natural_key = functools.cmp_to_key(_StrCmpLogicalW)


# ---------------------------------------------------------------- 파일 작업
FO_NAMES = {shellcon.FO_COPY: "copy", shellcon.FO_MOVE: "move",
            shellcon.FO_DELETE: "delete", shellcon.FO_RENAME: "rename"}


def file_op(hwnd, func, srcs, dst=None, flags=0, done=None):
    """SHFileOperation 을 별도 스레드에서 실행 (UI 멈춤 방지). done(result, aborted) 콜백은 작업 스레드에서 호출됨."""
    srcs = [os.path.normpath(s) for s in srcs]

    def run():
        name = FO_NAMES.get(func, str(func))
        log.info("파일작업 시작 %s n=%d dst=%s flags=0x%x first=%s", name, len(srcs), dst, flags, srcs[:1])
        res, aborted = -1, False
        try:
            res, aborted = shell.SHFileOperation((hwnd, func, "\0".join(srcs), dst, flags))
        except Exception:
            log.exception("SHFileOperation 예외")
        log.info("파일작업 끝 %s result=%s aborted=%s", name, res, aborted)
        if done:
            try:
                done(res, aborted)
            except Exception:
                log.exception("file_op done 콜백 예외")

    threading.Thread(target=run, daemon=True).start()


def copy_or_move(hwnd, srcs, dst_dir, move, done=None):
    flags = shellcon.FOF_ALLOWUNDO
    # 같은 폴더에 붙여넣기 = 탐색기처럼 '- 복사본' 으로 이름 바꿔 복사
    if not move and any(os.path.normcase(os.path.dirname(os.path.normpath(s))) == os.path.normcase(os.path.normpath(dst_dir)) for s in srcs):
        flags |= shellcon.FOF_RENAMEONCOLLISION
    if move:
        srcs = [s for s in srcs if os.path.normcase(os.path.dirname(os.path.normpath(s))) != os.path.normcase(os.path.normpath(dst_dir))]
        if not srcs:
            log.info("이동 생략: 같은 폴더")
            return
    file_op(hwnd, shellcon.FO_MOVE if move else shellcon.FO_COPY, srcs, dst_dir, flags, done)


def delete(hwnd, srcs, permanent=False, done=None, silent=False):
    flags = 0 if permanent else shellcon.FOF_ALLOWUNDO
    if silent:   # 되돌리기로 방금 만든 빈 폴더 지울 때 (휴지통, 묻지 않음)
        flags |= shellcon.FOF_NOCONFIRMATION
    file_op(hwnd, shellcon.FO_DELETE, srcs, None, flags, done)


def restore_from_recycle(paths):
    """휴지통에 버린 것을 원래 자리로 (탐색기의 Ctrl+Z 삭제 되돌리기와 같은 '복원' 동사). (복원한 경로, 못 찾은 경로)
    같은 경로가 여러 번 버려졌으면 가장 최근 것. 작업 스레드에서 부름(휴지통 훑기 수 초)."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    want = {os.path.normcase(os.path.normpath(p)): p for p in paths}
    best = {}
    t0 = time.time()
    try:
        rb = win32com.client.Dispatch("Shell.Application").NameSpace(10)
        for it in rb.Items():
            try:
                frm = it.ExtendedProperty("System.Recycle.DeletedFrom") or ""
                fn = it.ExtendedProperty("System.FileName") or it.Name
                when = str(it.ExtendedProperty("System.Recycle.DateDeleted") or "")
            except Exception:
                continue
            k = os.path.normcase(os.path.normpath(os.path.join(frm, fn)))
            if k in want and (k not in best or when > best[k][0]):
                best[k] = (when, it)
        done = []
        for k, (_w, it) in best.items():
            if os.path.exists(want[k]):
                log.warning("복원 건너뜀(같은 이름이 이미 있음) %s", want[k])
                continue
            it.InvokeVerb("undelete")
            done.append(want[k])
        miss = [p for k, p in want.items() if p not in done]
        log.info("휴지통 복원 %d개, 못 찾음 %d개 (%.0fms)", len(done), len(miss), (time.time() - t0) * 1000)
        return done, miss
    except Exception:
        log.exception("휴지통 복원 실패")
        return [], list(paths)
    finally:
        pythoncom.CoUninitialize()


# ---------------------------------------------------------------- 클립보드 (탐색기와 호환)
DROPEFFECT_COPY, DROPEFFECT_MOVE = 1, 2
_PDE_MIME = 'application/x-qt-windows-mime;value="Preferred DropEffect"'


_CLIP_SEQ = [0]   # 우리가 복사한 직후 윈도우 클립보드 순번 (붙여넣기 때 다른 프로그램이 바꿨는지 비교)


def clipboard_info():
    """진단용: 윈도우 클립보드 순번·파일(CF_HDROP) 있음·마지막에 바꾼 프로그램·형식 몇 개 (10/8 붙여넣기 안 됨 간헐 — 원인 확정용)"""
    u = ctypes.windll.user32
    info = {"seq": u.GetClipboardSequenceNumber(), "files": bool(u.IsClipboardFormatAvailable(15)), "owner": "?", "formats": []}
    try:
        h = u.GetClipboardOwner()
        if h:
            pid = _wt.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            info["owner"] = "4Dir" if pid.value == os.getpid() else _proc_name(pid.value)
        else:
            info["owner"] = "(없음)"
        u.GetClipboardFormatNameW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_int]
        f, n = 0, 0
        if u.OpenClipboard(None):
            try:
                while n < 12:
                    f = u.EnumClipboardFormats(f)
                    if not f:
                        break
                    b = ctypes.create_unicode_buffer(64)
                    info["formats"].append(b.value if u.GetClipboardFormatNameW(f, b, 64) else str(f))
                    n += 1
            finally:
                u.CloseClipboard()
        else:
            info["formats"] = ["(열기 실패 — 다른 프로그램이 잡고 있음)"]
    except Exception as ex:
        info["err"] = str(ex)
    return info


def _proc_name(pid):
    k = ctypes.windll.kernel32
    ph = k.OpenProcess(0x1000, False, pid)
    if not ph:
        return f"pid {pid}"
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = _wt.DWORD(520)
        return os.path.basename(buf.value) if k.QueryFullProcessImageNameW(ph, 0, buf, ctypes.byref(n)) else f"pid {pid}"
    finally:
        k.CloseHandle(ph)


def _set_clipboard_qt(paths, cut):
    """예전 방식(Qt 자료): 파일 목록(CF_HDROP)+주소(URL) 형식뿐 — 윈도우 셸 방식이 실패할 때만"""
    from PySide6 import QtCore
    md = QtCore.QMimeData()
    md.setUrls([QtCore.QUrl.fromLocalFile(p) for p in paths])
    md.setData(_PDE_MIME, QtCore.QByteArray((DROPEFFECT_MOVE if cut else DROPEFFECT_COPY).to_bytes(4, "little")))
    QtGui.QGuiApplication.clipboard().setMimeData(md)


def _set_hglobal(do, cf, data, what):
    """자료 객체 do 에 형식 cf 의 메모리 자료를 넣음 (IDataObject::SetData, fRelease=TRUE → 자료 객체가 메모리 해제)"""
    k32 = ctypes.windll.kernel32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = k32.GlobalUnlock.argtypes = k32.GlobalFree.argtypes = [ctypes.c_void_p]
    hg = k32.GlobalAlloc(0x0042, len(data))   # GMEM_MOVEABLE | GMEM_ZEROINIT
    ctypes.memmove(k32.GlobalLock(hg), data, len(data))
    k32.GlobalUnlock(hg)
    fe = _FORMATETC(cf, None, 1, -1, 1)   # DVASPECT_CONTENT, TYMED_HGLOBAL
    sm = _STGMEDIUM(1, hg, None)
    hr = _com(do.value, 7, [ctypes.POINTER(_FORMATETC), ctypes.POINTER(_STGMEDIUM), _wt.BOOL],
              ctypes.byref(fe), ctypes.byref(sm), True)
    if hr < 0:
        k32.GlobalFree(hg)
    _check(hr, what)


def _set_clipboard_shell(paths, cut):
    """윈도우 탐색기와 같은 방식 (v0.9.53): 셸이 만든 파일 자료 객체를 그대로 클립보드에.
    → Shell IDList Array·FileNameW·FileContents 등 탐색기와 같은 형식 (10/21 사용자: 4Dir 에서 복사한 apk 가
    다른 프로그램에 안 붙음, 탐색기 복사는 됨 — 형식 비교로 원인 확정). 같은 폴더면 그 폴더의 GetUIObjectOf
    (탐색기와 동일), 여러 폴더(검색 결과)면 SHCreateDataObject(바탕화면 기준 전체 경로). 잘라내기 표시는 SetData."""
    pidls, kids, psf, do = [], [], ctypes.c_void_p(), ctypes.c_void_p()
    try:
        for p in paths:
            pidls.append(_parse(os.path.normpath(p)))
        same = len({os.path.dirname(os.path.normcase(os.path.normpath(p))) for p in paths}) == 1
        if same:
            for i, pidl in enumerate(pidls):
                sf, child = ctypes.c_void_p(), ctypes.c_void_p()
                _check(_shell32.SHBindToParent(pidl, ctypes.byref(IID_IShellFolder), ctypes.byref(sf), ctypes.byref(child)), "상위폴더")
                kids.append(child.value)
                if i == 0:
                    psf = sf
                else:
                    _release(sf.value)
            arr = (ctypes.c_void_p * len(kids))(*kids)
            _check(_com(psf.value, 10, [_wt.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(_GUID),
                                        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
                        None, len(kids), arr, ctypes.byref(IID_IDataObject), None, ctypes.byref(do)), "GetUIObjectOf(자료)")
        else:
            arr = (ctypes.c_void_p * len(pidls))(*[x.value for x in pidls])
            _check(_shell32.SHCreateDataObject(None, len(pidls), arr, None, ctypes.byref(IID_IDataObject), ctypes.byref(do)),
                   "SHCreateDataObject")
            # 바탕화면 기준 자료 객체는 파일 목록(CF_HDROP)을 안 만듦(실측) → 직접 넣음 (DROPFILES, 유니코드)
            body = ("\0".join(os.path.normpath(p) for p in paths) + "\0\0").encode("utf-16-le")
            _set_hglobal(do, 15, struct.pack("<IiiII", 20, 0, 0, 0, 1) + body, "SetData(CF_HDROP)")
            # 셸 항목 목록(Shell IDList Array = CIDA): 부모 = 바탕화면(빈 목록), 항목 = 전체 경로 항목
            items = [ctypes.string_at(x.value, _shell32.ILGetSize(x)) for x in pidls]
            head = 4 * (len(items) + 2)
            offs, cur = [head], head + 2
            for it in items:
                offs.append(cur)
                cur += len(it)
            cida = struct.pack(f"<{len(items) + 2}I", len(items), *offs) + b"\0\0" + b"".join(items)
            _set_hglobal(do, ctypes.windll.user32.RegisterClipboardFormatW("Shell IDList Array"), cida, "SetData(Shell IDList Array)")
        # 잘라내기/복사 표시 (Preferred DropEffect, DWORD) — 탐색기 붙여넣기가 이걸 보고 이동/복사를 정함
        _set_hglobal(do, ctypes.windll.user32.RegisterClipboardFormatW("Preferred DropEffect"),
                     struct.pack("<I", DROPEFFECT_MOVE if cut else DROPEFFECT_COPY), "SetData(Preferred DropEffect)")
        _check(_ole32.OleSetClipboard(do), "OleSetClipboard")   # 클립보드가 참조를 따로 잡음
    finally:
        _release(do.value)
        _release(psf.value)
        for x in pidls:
            _ole32.CoTaskMemFree(x)


def set_clipboard(paths, cut):
    try:
        _set_clipboard_shell(paths, cut)
        how = "탐색기 방식"
    except Exception as ex:
        log.warning("클립보드 탐색기 방식 실패 → 예전 방식: %s", ex)
        _set_clipboard_qt(paths, cut)
        how = "예전 방식"
    info = clipboard_info()
    _CLIP_SEQ[0] = info["seq"]
    if info["files"] and info["owner"] == "4Dir":
        log.info("클립보드 %s n=%d %s (윈도우 확인: 파일 있음, 순번 %d)", "잘라내기" if cut else "복사", len(paths), how, info["seq"])
    else:   # 윈도우 클립보드에 안 들어감 — 다른 프로그램이 잡고 있었거나 바로 덮어씀
        log.warning("클립보드 %s n=%d 실패? 윈도우 확인: %s", "잘라내기" if cut else "복사", len(paths), info)
    return info["files"]


def get_clipboard():
    """(경로목록, 잘라내기여부)"""
    md = QtGui.QGuiApplication.clipboard().mimeData()
    if md is None or not md.hasUrls():
        return [], False
    paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
    cut = False
    if md.hasFormat(_PDE_MIME):
        b = bytes(md.data(_PDE_MIME))
        if len(b) >= 4:
            cut = bool(int.from_bytes(b[:4], "little") & DROPEFFECT_MOVE)
    return paths, cut


# ---------------------------------------------------------------- 윈도우 11 새 메뉴에만 있는 기능 (v0.9.54)
# 4Dir 우클릭은 윈도우 클래식 메뉴라 윈도우 11 의 '압축·즐겨찾기에 고정·경로로 복사·터미널에서 열기'가 안 보임(사용자 제보)
TAR_EXE = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")   # 윈도우 내장 bsdtar(libarchive) — 윈도우 11 압축과 같은 엔진
_ARC_OPTS = {"zip": ["--options", "zip:hdrcharset=UTF-8"],   # 없으면 한글 이름이 CP949 로 들어감(실측)
             "7z": [], "tar": ["--options", "hdrcharset=UTF-8"]}


def compress(folder, names, fmt):
    """folder 안의 names 를 <첫 항목 이름>.<fmt> 로 압축 (같은 이름 있으면 ' (2)'). 반환 (만든 경로, 걸린 초). 실패 시 OSError"""
    t0 = time.time()
    first = names[0]
    stem = os.path.splitext(first)[0] if os.path.isfile(os.path.join(folder, first)) else first
    out, i = os.path.join(folder, f"{stem}.{fmt}"), 2
    while os.path.exists(out):
        out, i = os.path.join(folder, f"{stem} ({i}).{fmt}"), i + 1
    log.info("압축 시작 %s ← %d개 %s (%s)", out, len(names), names[:5], fmt)
    if os.path.exists(TAR_EXE):
        r = subprocess.run([TAR_EXE, *_ARC_OPTS[fmt], "-a", "-c", "-f", out, "--", *names], cwd=folder,
                           capture_output=True, creationflags=0x08000000)   # CREATE_NO_WINDOW
        if r.returncode != 0:
            err = (r.stderr or b"").decode("mbcs", "replace").strip()
            if os.path.exists(out):
                os.remove(out)
            log.warning("압축 실패 rc=%d %s", r.returncode, err[:500])
            raise OSError(err.splitlines()[0] if err else f"tar rc={r.returncode}")   # 첫 줄 = 어떤 파일이 왜 실패했는지
    elif fmt == "zip":   # tar.exe 없는 윈도우(1803 이전) → 파이썬 zip
        import zipfile
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for nm in names:
                p = os.path.join(folder, nm)
                if os.path.isdir(p):
                    for a, _, fs in os.walk(p):
                        for f in fs:
                            z.write(os.path.join(a, f), os.path.relpath(os.path.join(a, f), folder))
                else:
                    z.write(p, nm)
    else:
        raise OSError(T("이 윈도우에는 압축 도구(tar.exe)가 없습니다"))
    sec = time.time() - t0
    log.info("압축 완료 %s %.1fMB %.1f초", out, os.path.getsize(out) / 1048576, sec)
    return out, sec


def link_target(lnk):
    """바로 가기(.lnk)의 대상 경로 (v0.9.55). 찾아다니기(Resolve) 안 함 — 적힌 경로만 읽음(빠름, 창 안 뜸).
    경로가 없는 특수 대상(제어판 등)이거나 읽기 실패면 '' """
    import pythoncom
    try:
        sl = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        sl.QueryInterface(pythoncom.IID_IPersistFile).Load(lnk, 0)
        return sl.GetPath(shell.SLGP_RAWPATH)[0] or ""
    except Exception as ex:
        log.warning("바로 가기 읽기 실패 %s: %s", lnk, ex)
        return ""


def copy_as_path(paths):
    """탐색기 '경로로 복사'와 같은 글자: 따옴표로 감싼 전체 경로, 여러 개면 줄바꿈"""
    QtGui.QGuiApplication.clipboard().setText("\r\n".join(f'"{os.path.normpath(p)}"' for p in paths))
    log.info("경로로 복사 %d개", len(paths))


def shell_verb(path, verb):
    """윈도우 셸 동사 실행(예: pintohome, pintostartscreen). 실패하면 OSError"""
    try:
        shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_INVOKEIDLIST | 0x400, lpVerb=verb, lpFile=path, nShow=win32con.SW_SHOWNORMAL)   # 0x400 = 오류 창 안 띄움
        log.info("셸 동사 %s %s", verb, path)
    except Exception as ex:
        log.warning("셸 동사 실패 %s %s: %s", verb, path, ex)
        raise OSError(str(ex))


def open_terminal(folder):
    """윈도우 터미널(있으면) 또는 파워셸을 그 폴더에서 엶"""
    import shutil
    wt = shutil.which("wt.exe")
    if wt:
        subprocess.Popen([wt, "-d", folder.rstrip("\\") + "\\."])   # 끝 \ 가 따옴표를 먹는 wt 문제 피함
    else:
        subprocess.Popen(["powershell.exe", "-NoExit"], cwd=folder, creationflags=0x00000010)   # CREATE_NEW_CONSOLE
    log.info("터미널 열기 %s (%s)", folder, "wt" if wt else "powershell")


# ---------------------------------------------------------------- 우클릭 셸 메뉴 (ctypes COM 직접 호출)
# pywin32 는 IContextMenu2/3 클라이언트가 없어(실측) '새로 만들기/보내기/연결 프로그램' 하위메뉴를 못 채움 → ctypes 로 vtable 직접 호출
from ctypes import wintypes as _wt

_ole32 = ctypes.windll.ole32
_shell32 = ctypes.windll.shell32


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    _ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


IID_IShellFolder = _guid("{000214E6-0000-0000-C000-000000000046}")
IID_IContextMenu = _guid("{000214E4-0000-0000-C000-000000000046}")
IID_IContextMenu2 = _guid("{000214F4-0000-0000-C000-000000000046}")
IID_IContextMenu3 = _guid("{BCFCE0A0-EC17-11D0-8D10-00A0C90F2719}")

_shell32.SHParseDisplayName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
_shell32.SHParseDisplayName.restype = ctypes.c_long
_shell32.SHBindToParent.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.POINTER(ctypes.c_void_p)]
_shell32.SHBindToParent.restype = ctypes.c_long
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
IID_IDataObject = _guid("{0000010E-0000-0000-C000-000000000046}")
_shell32.SHCreateDataObject.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
_shell32.SHCreateDataObject.restype = ctypes.c_long
_shell32.ILGetSize.argtypes = [ctypes.c_void_p]
_shell32.ILGetSize.restype = ctypes.c_uint
_ole32.OleSetClipboard.argtypes = [ctypes.c_void_p]
_ole32.OleSetClipboard.restype = ctypes.c_long


class _FORMATETC(ctypes.Structure):
    _fields_ = [("cfFormat", ctypes.c_ushort), ("ptd", ctypes.c_void_p), ("dwAspect", _wt.DWORD),
                ("lindex", ctypes.c_long), ("tymed", _wt.DWORD)]


class _STGMEDIUM(ctypes.Structure):
    _fields_ = [("tymed", _wt.DWORD), ("hGlobal", ctypes.c_void_p), ("pUnkForRelease", ctypes.c_void_p)]


def _com(ptr, idx, argtypes, *args):
    """COM 객체 ptr 의 vtable[idx] 호출, HRESULT 반환"""
    vt = ctypes.cast(ctypes.c_void_p.from_address(ptr).value, ctypes.POINTER(ctypes.c_void_p))
    fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vt[idx])
    return fn(ptr, *args)


def _release(ptr):
    if ptr:
        _com(ptr, 2, [])


def _check(hr, what):
    if hr < 0:
        raise OSError(f"{what} 실패 hr=0x{hr & 0xFFFFFFFF:08X}")


class _CMICEX(ctypes.Structure):
    _fields_ = [("cbSize", _wt.DWORD), ("fMask", _wt.DWORD), ("hwnd", _wt.HWND),
                ("lpVerb", ctypes.c_void_p), ("lpParameters", ctypes.c_char_p), ("lpDirectory", ctypes.c_char_p),
                ("nShow", ctypes.c_int), ("dwHotKey", _wt.DWORD), ("hIcon", _wt.HANDLE),
                ("lpTitle", ctypes.c_char_p), ("lpVerbW", ctypes.c_void_p), ("lpParametersW", ctypes.c_wchar_p),
                ("lpDirectoryW", ctypes.c_wchar_p), ("lpTitleW", ctypes.c_wchar_p), ("ptInvoke", _wt.POINT)]


CMIC_MASK_UNICODE, CMIC_MASK_PTINVOKE = 0x4000, 0x20000000
WM_INITMENUPOPUP, WM_DRAWITEM, WM_MEASUREITEM, WM_MENUCHAR = 0x0117, 0x002B, 0x002C, 0x0120
MENU_MSGS = (WM_INITMENUPOPUP, WM_DRAWITEM, WM_MEASUREITEM, WM_MENUCHAR)


def _menu_spec(x):
    """메뉴 항목 표기 통일: "-" → None(구분선), "글자" → {"t"}, ("글자", [하위]) → {"t", "sub"}, dict 그대로"""
    if x == "-":
        return None
    if isinstance(x, str):
        return {"t": x}
    if isinstance(x, tuple):
        return {"t": x[0], "sub": x[1]}
    return x


def _menu_flags(s):
    return (win32con.MF_STRING | (win32con.MF_GRAYED if s.get("off") else 0)
            | (win32con.MF_CHECKED if s.get("chk") else 0))


def _menu_text(h, i):
    b = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetMenuStringW(h, i, b, 256, win32con.MF_BYPOSITION)
    return b.value


def _menu_plain(s):
    """'새 폴더(&N)' → '새 폴더' (단축 글자·& 빼고 소문자)"""
    return re.sub(r"\s*\(&?\w\)\s*$", "", s.split("\t")[0]).replace("&", "").strip().lower()


def _parse(path):
    pidl = ctypes.c_void_p()
    _check(_shell32.SHParseDisplayName(path, None, ctypes.byref(pidl), 0, None), "경로해석 " + path)
    return pidl


class ShellMenu:
    """윈도우 클래식 우클릭 메뉴(TortoiseSVN·압축·새로 만들기·보내기·연결 프로그램 포함).
    메뉴가 떠 있는 동안 current 에 자신을 두고, 메인창 nativeEvent 가 하위메뉴 메시지를 forward() 로 넘긴다."""
    EXTRA_BASE = 0x8000  # 우리 항목 id (셸 항목 1~0x7FFF 와 겹치지 않음)
    current = None

    def __init__(self, hwnd, folder, names, extras=(), extended=False, tail=(), newfolder=None):
        self.cm = None
        self.newfolder_id = None   # 윈도우 '새 폴더' 자리에 넣은 우리 항목 id
        self.cm_hi = None   # (ptr, 3|2)  IContextMenu3 또는 2
        self.hmenu = None
        self._pidls = []
        psf = ctypes.c_void_p()
        cm = ctypes.c_void_p()
        try:
            if names:
                kids = []
                for i, n in enumerate(names):
                    pidl = _parse(os.path.join(folder, n))
                    self._pidls.append(pidl)
                    sf, child = ctypes.c_void_p(), ctypes.c_void_p()
                    _check(_shell32.SHBindToParent(pidl, ctypes.byref(IID_IShellFolder), ctypes.byref(sf), ctypes.byref(child)), "상위폴더")
                    kids.append(child.value)
                    if i == 0:
                        psf = sf
                    else:
                        _release(sf.value)
                arr = (ctypes.c_void_p * len(kids))(*kids)
                _check(_com(psf.value, 10, [_wt.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(_GUID),
                                            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
                            hwnd, len(kids), arr, ctypes.byref(IID_IContextMenu), None, ctypes.byref(cm)), "GetUIObjectOf")
            else:
                pidl = _parse(folder)
                self._pidls.append(pidl)
                parent, child = ctypes.c_void_p(), ctypes.c_void_p()
                _check(_shell32.SHBindToParent(pidl, ctypes.byref(IID_IShellFolder), ctypes.byref(parent), ctypes.byref(child)), "상위폴더")
                try:
                    _check(_com(parent.value, 5, [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)],
                                child, None, ctypes.byref(IID_IShellFolder), ctypes.byref(psf)), "BindToObject")
                finally:
                    _release(parent.value)
                _check(_com(psf.value, 8, [_wt.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)],
                            hwnd, ctypes.byref(IID_IContextMenu), ctypes.byref(cm)), "CreateViewObject")
        except Exception:
            self.close()
            raise
        finally:
            _release(psf.value)
        self.cm = cm.value
        for iid, lvl in ((IID_IContextMenu3, 3), (IID_IContextMenu2, 2)):
            p = ctypes.c_void_p()
            if _com(self.cm, 0, [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(iid), ctypes.byref(p)) >= 0 and p.value:
                self.cm_hi = (p.value, lvl)
                break
        self.hmenu = win32gui.CreatePopupMenu()
        flags = shellcon.CMF_NORMAL | shellcon.CMF_EXPLORE | shellcon.CMF_CANRENAME
        if extended:
            flags |= shellcon.CMF_EXTENDEDVERBS
        _check(_com(self.cm, 3, [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint],
                    self.hmenu, 0, 1, 0x7FFF, flags), "QueryContextMenu")
        # 우리 항목 id 는 펼친 순서대로 EXTRA_BASE+n : extras → tail → newfolder (부르는 쪽 콜백 목록도 같은 순서)
        n = 0
        if extras:
            # extras 항목: "글자" | "-"(구분선) | ("글자", [하위…]) | {"t": 글자, "off": 흐림, "chk": 체크, "sub": [하위…],
            #   "unless": {"verb", …}}  ← 윈도우 메뉴에 이 동사가 이미 있으면 우리 항목은 숨김(번호는 그대로 소비, v0.9.54
            #   윈도우 11 클래식 메뉴엔 없는 '즐겨찾기에 고정·경로로 복사' 등을 넣되 윈도우 10 에선 겹치지 않게)
            #   하위: "-" | "글자" | {"t", "off", "chk"}
            shell_verbs = set()
            for i in range(win32gui.GetMenuItemCount(self.hmenu)):
                idc = ctypes.windll.user32.GetMenuItemID(self.hmenu, i)
                if 0 < idc < ShellMenu.EXTRA_BASE:
                    v = self.verb(idc - 1)
                    if v:
                        shell_verbs.add(v.lower())
            win32gui.InsertMenu(self.hmenu, 0, win32con.MF_BYPOSITION | win32con.MF_SEPARATOR, 0, None)
            pos = -1
            for ex in extras:
                pos += 1
                ex = _menu_spec(ex)
                if ex is not None and {v.lower() for v in ex.get("unless", ())} & shell_verbs:
                    log.info("셸메뉴 우리 항목 숨김 (윈도우에 이미 있음) %s", ex["t"])
                    n += len([t for t in ex["sub"] if _menu_spec(t) is not None]) if "sub" in ex else 1
                    pos -= 1
                    continue
                if ex is None:
                    win32gui.InsertMenu(self.hmenu, pos, win32con.MF_BYPOSITION | win32con.MF_SEPARATOR, 0, None)
                elif "sub" in ex:
                    sub = win32gui.CreatePopupMenu()
                    for t in ex["sub"]:
                        t = _menu_spec(t)
                        if t is None:
                            if win32gui.GetMenuItemCount(sub):   # 맨 앞 구분선은 생략
                                win32gui.AppendMenu(sub, win32con.MF_SEPARATOR, 0, "")   # None 은 pywin32 가 거부(10/2 실제 오류)
                        else:
                            win32gui.AppendMenu(sub, _menu_flags(t), ShellMenu.EXTRA_BASE + n, t["t"])
                            n += 1
                    win32gui.InsertMenu(self.hmenu, pos, win32con.MF_BYPOSITION | win32con.MF_POPUP, sub, ex["t"])
                else:
                    win32gui.InsertMenu(self.hmenu, pos, win32con.MF_BYPOSITION | _menu_flags(ex),
                                        ShellMenu.EXTRA_BASE + n, ex["t"])
                    n += 1
        if tail:
            # 메뉴 맨 아래에 붙이는 우리 항목
            win32gui.AppendMenu(self.hmenu, win32con.MF_SEPARATOR, 0, "")
            for t in tail:
                win32gui.AppendMenu(self.hmenu, win32con.MF_STRING, ShellMenu.EXTRA_BASE + n, t)
                n += 1
        if newfolder:
            # 윈도우 빈 곳 메뉴의 '새 폴더' (verb 없음 — 글자로 찾음) 를 빼고 그 자리에 우리 항목(예: 되돌리기)
            # — '새 폴더' 는 우리가 맨 위에 따로 둠(이름 편집 상태로 만들기 위해). 못 찾으면 셸 항목 끝에 붙임
            spec, names_ = _menu_spec(newfolder[0]), {_menu_plain(s) for s in newfolder[1]}
            pos = None
            for i in range(win32gui.GetMenuItemCount(self.hmenu)):
                idc = ctypes.windll.user32.GetMenuItemID(self.hmenu, i)
                if 0 < idc < ShellMenu.EXTRA_BASE and _menu_plain(_menu_text(self.hmenu, i)) in names_ and not self.verb(idc - 1):
                    pos = i
                    win32gui.DeleteMenu(self.hmenu, i, win32con.MF_BYPOSITION)
                    break
            self.newfolder_id = ShellMenu.EXTRA_BASE + n
            if pos is None:
                win32gui.AppendMenu(self.hmenu, _menu_flags(spec), self.newfolder_id, spec["t"])
            else:
                win32gui.InsertMenu(self.hmenu, pos, win32con.MF_BYPOSITION | _menu_flags(spec), self.newfolder_id, spec["t"])
            log.info("셸메뉴 윈도우 '새 폴더' %s", f"{pos}번째 자리를 바꿈" if pos is not None else "못 찾음 → 끝에 붙임")
        log.info("셸메뉴 구성 folder=%s n=%d 항목=%d 하위메뉴지원=IContextMenu%s", folder, len(names),
                 win32gui.GetMenuItemCount(self.hmenu), self.cm_hi[1] if self.cm_hi else "없음")

    def handle(self, msg, wparam, lparam):
        """하위메뉴 메시지를 셸 메뉴에 전달. 반환 (처리됨, 결과)"""
        if not self.cm_hi:
            return False, 0
        ptr, lvl = self.cm_hi
        try:
            if lvl == 3:
                res = ctypes.c_ssize_t(0)
                hr = _com(ptr, 7, [ctypes.c_uint, _wt.WPARAM, _wt.LPARAM, ctypes.POINTER(ctypes.c_ssize_t)],
                          msg, wparam, lparam, ctypes.byref(res))
                return hr >= 0, res.value
            hr = _com(ptr, 6, [ctypes.c_uint, _wt.WPARAM, _wt.LPARAM], msg, wparam, lparam)
            return hr >= 0, 0
        except Exception:
            log.exception("HandleMenuMsg 실패 msg=0x%x", msg)
            return False, 0

    def verb(self, idcmd):
        buf = ctypes.create_unicode_buffer(256)
        try:
            if _com(self.cm, 5, [ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint],
                    idcmd, shellcon.GCS_VERBW, None, ctypes.cast(buf, ctypes.c_void_p), 256) >= 0:
                return buf.value
        except Exception:
            pass
        return ""

    def invoke(self, hwnd, idcmd, folder, x, y):
        ci = _CMICEX()
        ci.cbSize = ctypes.sizeof(_CMICEX)
        ci.fMask = CMIC_MASK_UNICODE | CMIC_MASK_PTINVOKE
        ci.hwnd = hwnd
        ci.lpVerb = idcmd
        ci.lpVerbW = idcmd
        ci.lpDirectoryW = folder
        ci.nShow = win32con.SW_SHOWNORMAL
        ci.ptInvoke = _wt.POINT(x, y)
        hr = _com(self.cm, 4, [ctypes.POINTER(_CMICEX)], ctypes.byref(ci))
        log.info("셸메뉴 실행 id=%d hr=0x%08X", idcmd, hr & 0xFFFFFFFF)

    def close(self):
        if self.hmenu:
            win32gui.DestroyMenu(self.hmenu)
            self.hmenu = None
        if self.cm_hi:
            _release(self.cm_hi[0])
            self.cm_hi = None
        if self.cm:
            _release(self.cm)
            self.cm = None
        for p in self._pidls:
            _ole32.CoTaskMemFree(p)
        self._pidls = []

    # ------------------------------------------------------------ 메인창에서 부르는 진입점
    @staticmethod
    def show(hwnd, folder, names, x, y, extras=(), extended=False, tail=(), newfolder=None):
        """반환: ('extra', 번호) | ('rename', None) | ('invoked', verb) | None(취소)"""
        log.info("셸메뉴 folder=%s names=%s", folder, names[:5])
        m = ShellMenu(hwnd, folder, names, extras, extended, tail, newfolder)
        ShellMenu.current = m
        try:
            cmd = win32gui.TrackPopupMenu(m.hmenu, win32con.TPM_RETURNCMD | win32con.TPM_RIGHTBUTTON,
                                          x, y, 0, hwnd, None)
            ShellMenu.current = None
            if not cmd:
                log.info("셸메뉴 취소")
                return None
            if cmd >= ShellMenu.EXTRA_BASE:
                log.info("셸메뉴 우리항목 %d", cmd - ShellMenu.EXTRA_BASE)
                return ("extra", cmd - ShellMenu.EXTRA_BASE)
            verb = m.verb(cmd - 1)
            log.info("셸메뉴 선택 id=%d verb=%s", cmd - 1, verb)
            if verb.lower() == "rename":
                return ("rename", None)
            m.invoke(hwnd, cmd - 1, folder, x, y)
            return ("invoked", verb)
        finally:
            ShellMenu.current = None
            m.close()

    @staticmethod
    def forward(msg, wparam, lparam):
        """메인창 nativeEvent 에서 호출. 반환 (처리됨, 결과)"""
        m = ShellMenu.current
        if m is None or msg not in MENU_MSGS:
            return False, 0
        return m.handle(msg, wparam, lparam)


def properties(hwnd, folder, names):
    """속성 창 (Alt+Enter). 여러 개면 탐색기처럼 하나의 묶음 속성 창. names 가 없으면 폴더 자체.
    우클릭 메뉴를 띄우지 않고 그 안의 'properties' 명령만 실행"""
    sm = None
    try:
        sm = ShellMenu(hwnd, folder, names)
        target = None
        for pos in range(win32gui.GetMenuItemCount(sm.hmenu)):
            idc = win32gui.GetMenuItemID(sm.hmenu, pos)
            if 0 < idc < ShellMenu.EXTRA_BASE and sm.verb(idc - 1).lower() == "properties":
                target = idc - 1
                break
        log.info("속성 창 folder=%s n=%d verb번호=%s", folder, len(names), target)
        if target is not None:
            sm.invoke(hwnd, target, folder, 0, 0)
            return True
    except Exception:
        log.exception("속성 창 실패 %s %s", folder, names[:3])
    finally:
        if sm is not None:
            sm.close()
    return False
