# -*- coding: utf-8 -*-
"""연결 프로그램 도우미 (OPENWITH_VER 1.0.0, 0.9.131 — 사용자 11/11 문의 '연결 프로그램 ▸ 사진으로 열면 1장만')

- 윈도우 우클릭 '연결 프로그램 ▸ 앱' 은 원래 4Dir 안에서 바로 실행됨 → 사진 앱은 연 프로그램(계속 켜져 있는 4Dir)에게
  같은 폴더 목록을 받으려다 못 받아 1장만 보여 줌 (실측: 연 프로그램 살아 있음 1장 / 바로 끝남 10장).
- 그래서 4Dir 는 고른 앱 이름만 넘기고(탐색기 → 4Dir_open.vbs → 이 파일을 pythonw 로), 이 도우미가 그 앱으로 열고 바로 끝남.
- handlers(ext) / find(ext, 글자) : 윈도우 '연결 프로그램' 목록 (SHAssocEnumHandlers) — 4Dir 가 고른 항목이 어느 앱인지 찾을 때
- invoke(paths, name) : 그 앱으로 열기 (IAssocHandler::Invoke, 파일 여러 개 = 같은 폴더)
- 도우미 실행: pythonw openwith.py(.pyc) <앱 이름(GetName)> <파일>… → bin\\log\\openwith.log 에 기록
"""
import os
import sys
import time
import ctypes
from ctypes import wintypes, POINTER, byref, c_void_p, c_wchar_p, HRESULT

OPENWITH_VER = "1.1.0"   # 1.1.0: 파일 하나면 앱 ProgId 로 ShellExecuteEx (Invoke 는 도우미가 끝난 뒤 사진 창이 25초 늦게 뜸, ProgId 는 3.6초 — 실측)
_ole32 = ctypes.windll.ole32
_shell32 = ctypes.windll.shell32
_shell32.SHAssocEnumHandlers.argtypes = (c_wchar_p, ctypes.c_int, POINTER(c_void_p))
_shell32.SHCreateItemFromParsingName.argtypes = (c_wchar_p, c_void_p, c_void_p, POINTER(c_void_p))
_shell32.ILCreateFromPathW.restype = c_void_p
_shell32.ILCreateFromPathW.argtypes = (c_wchar_p,)
_shell32.ILFree.argtypes = (c_void_p,)
_shell32.SHCreateShellItemArrayFromIDLists.argtypes = (wintypes.UINT, POINTER(c_void_p), POINTER(c_void_p))


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    _ole32.CLSIDFromString(c_wchar_p(s), byref(g))
    return g


IID_IDataObject = _guid("{0000010e-0000-0000-C000-000000000046}")
BHID_DataObject = _guid("{B8C0BD9F-ED24-455c-83E6-D5390C4FE8C4}")


def _vcall(obj, idx, restype, *args, argtypes=()):
    vt = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vt[idx])(obj, *args)


def _release(obj):
    if obj:
        try:
            _vcall(obj, 2, wintypes.ULONG)
        except Exception:
            pass


def _co_free(p):
    if p:
        _ole32.CoTaskMemFree(ctypes.cast(p, c_void_p))


def clean(text):
    """메뉴 글자 → 앱 이름: '사진(&P)' · '&사진' → '사진'"""
    t = (text or "").split("\t")[0]
    if t.endswith(")") and "(&" in t:
        t = t[:t.rfind("(&")]
    return t.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def _enum(ext):
    """[(IAssocHandler 포인터, 보이는 이름, GetName)] — 포인터는 부른 쪽이 _release"""
    out = []
    enum = c_void_p()
    if _shell32.SHAssocEnumHandlers(ext, 0, byref(enum)) != 0 or not enum:
        return out
    try:
        while True:
            h, n = c_void_p(), wintypes.ULONG()
            if _vcall(enum, 3, HRESULT, 1, byref(h), byref(n), argtypes=(wintypes.ULONG, POINTER(c_void_p), POINTER(wintypes.ULONG))) != 0 or not n.value:
                break
            nm, ui = c_wchar_p(), c_wchar_p()
            name = uiname = ""
            if _vcall(h, 3, HRESULT, byref(nm), argtypes=(POINTER(c_wchar_p),)) == 0:   # GetName
                name = nm.value or ""
                _co_free(nm)
            if _vcall(h, 4, HRESULT, byref(ui), argtypes=(POINTER(c_wchar_p),)) == 0:   # GetUIName
                uiname = ui.value or ""
                _co_free(ui)
            out.append((h, uiname, name))
    finally:
        _release(enum)
    return out


def handlers(ext):
    """[(보이는 이름, GetName)]"""
    lst = _enum(ext)
    for h, _u, _n in lst:
        _release(h)
    return [(u, n) for _h, u, n in lst]


def find(ext, menu_text):
    """메뉴 글자와 같은 이름의 앱 → GetName (없으면 None — 'Microsoft Store 검색' 같은 것)"""
    want = clean(menu_text).casefold()
    if not want:
        return None
    return next((n for u, n in handlers(ext) if clean(u).casefold() == want), None)


def _indirect(s):
    if not s or not s.startswith("@"):
        return s
    buf = ctypes.create_unicode_buffer(512)
    return buf.value if ctypes.windll.shlwapi.SHLoadIndirectString(s, buf, 512, None) == 0 else ""


def progid_for(ext, menu_text):
    """확장자의 연결 후보(HKCR\\<ext>\\OpenWithProgids) 중 앱 이름이 메뉴 글자와 같은 스토어 앱 ProgId (예: 사진 → AppX4mntx…). 없으면 None"""
    import winreg
    want = clean(menu_text).casefold()
    try:
        k = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ext + r"\OpenWithProgids")
    except OSError:
        return None
    with k:
        i = 0
        while True:
            try:
                pid = winreg.EnumValue(k, i)[0]
            except OSError:
                return None
            i += 1
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, pid + r"\Application") as a:
                    nm = _indirect(winreg.QueryValueEx(a, "ApplicationName")[0])
            except OSError:
                continue
            if nm and clean(nm).casefold() == want:
                return pid


class _SEI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND), ("lpVerb", c_wchar_p),
                ("lpFile", c_wchar_p), ("lpParameters", c_wchar_p), ("lpDirectory", c_wchar_p), ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE), ("lpIDList", c_void_p), ("lpClass", c_wchar_p), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def open_class(path, progid):
    """ProgId 로 열기 (SEE_MASK_CLASSNAME | 오류 창 없음) → True"""
    sei = _SEI()
    sei.cbSize = ctypes.sizeof(_SEI)
    sei.fMask = 0x1 | 0x400
    sei.lpVerb = "open"
    sei.lpFile = os.path.normpath(path)
    sei.lpClass = progid
    sei.nShow = 1
    return bool(ctypes.windll.shell32.ShellExecuteExW(byref(sei)))


def is_path_app(name):
    """GetName 이 exe 경로면 보통 프로그램 (넘김 필요 없음), 아니면 스토어 앱(사진 등)"""
    return bool(name) and (name.lower().endswith(".exe") or os.path.isabs(name))


def _data_object(paths):
    pidls = [_shell32.ILCreateFromPathW(os.path.normpath(p)) for p in paths]
    try:
        if not all(pidls):
            raise OSError("경로 해석 실패")
        arr = (c_void_p * len(pidls))(*pidls)
        items = c_void_p()
        hr = _shell32.SHCreateShellItemArrayFromIDLists(len(pidls), arr, byref(items))
        if hr != 0:
            raise OSError(f"항목 묶음 실패 hr=0x{hr & 0xFFFFFFFF:08X}")
    finally:
        for p in pidls:
            if p:
                _shell32.ILFree(p)
    dobj = c_void_p()
    try:   # IShellItemArray::BindToHandler (3)
        hr = _vcall(items, 3, HRESULT, None, byref(BHID_DataObject), byref(IID_IDataObject), byref(dobj),
                    argtypes=(c_void_p, POINTER(_GUID), POINTER(_GUID), POINTER(c_void_p)))
    finally:
        _release(items)
    if hr != 0 or not dobj:
        raise OSError(f"데이터 객체 실패 hr=0x{hr & 0xFFFFFFFF:08X}")
    return dobj


def invoke(paths, name):
    """name(GetName) 앱으로 paths 열기 → hr (0 = 성공). 앱을 못 찾으면 OSError"""
    ext = os.path.splitext(paths[0])[1]
    lst = _enum(ext)
    try:
        h = next((h for h, _u, n in lst if n == name), None)
        if h is None:
            raise OSError(f"연결 앱 없음 {name!r} ({ext})")
        dobj = _data_object(paths)
        try:
            return _vcall(h, 8, HRESULT, dobj, argtypes=(c_void_p,)) & 0xFFFFFFFF   # IAssocHandler::Invoke
        finally:
            _release(dobj)
    finally:
        for h, _u, _n in lst:
            _release(h)


def main(argv):
    """도우미: openwith.py <GetName> <파일>… — 열고 바로 끝남 (사진 앱이 폴더를 직접 읽게)"""
    here = os.path.dirname(os.path.abspath(__file__))
    logd = os.path.join(here, "log")
    try:
        os.makedirs(logd, exist_ok=True)
        logf = open(os.path.join(logd, "openwith.log"), "a", encoding="utf-8")
    except OSError:
        logf = None

    def log(m):
        if logf:
            logf.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")
            logf.flush()
    t0 = time.time()
    if len(argv) < 2:
        log(f"인자 부족 {argv!r}")
        return 2
    name, paths = argv[0], [p for p in argv[1:] if p]
    log(f"v{OPENWITH_VER} 열기 앱={name!r} 파일 {len(paths)}개 첫={paths[0]!r}")
    _ole32.CoInitializeEx(None, 2)
    if name.startswith("class:") and len(paths) == 1:   # 1.1.0
        ok = open_class(paths[0], name[6:])
        log(f"ShellExecuteEx(ProgId) {'성공' if ok else '실패 err=%d' % ctypes.GetLastError()} ({(time.time() - t0) * 1000:.0f}ms) → 끝냄")
        if logf:
            logf.close()
        return 0 if ok else 1
    try:
        hr = invoke(paths, name)
        log(f"Invoke hr=0x{hr:08X} ({(time.time() - t0) * 1000:.0f}ms) → 끝냄")
        return 0 if hr == 0 else 1
    except Exception as ex:
        log(f"실패 {ex!r}")
        return 1
    finally:
        if logf:
            logf.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
