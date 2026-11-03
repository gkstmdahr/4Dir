# -*- coding: utf-8 -*-
"""창의 윈도우 끌어 놓기 입구(IDropTarget) 감싸기 (OLEHOOK_VER 1.1.0, v0.9.78)

왜: Qt 는 끌어 온 데이터(IDataObject)를 감춰 두고, 'FileContents' 를 lindex -1·한 덩어리로만 꺼냄.
  → 웹 아웃룩(크롬 엔진) 본문 이미지는 0바이트, 여러 개를 한꺼번에 끌면 첫 개만 (v0.9.77 실측).
  탐색기는 lindex 0,1,2… 로 하나씩, 스트림(IStream)으로도 받아서 저장됨.
어떻게: Qt 가 창에 등록한 입구를 꺼내(창 속성 OleDropTargetInterface) 우리 입구로 바꿔 끼우고,
  모든 호출은 Qt 입구로 그대로 넘김(동작은 예전과 같음). 넘기기 전 끌어 온 IDataObject 주소만 잠깐 기억 → vfiles 가 직접 꺼냄.
★1.1.0: 입구는 ctypes 로 직접 만든 COM 객체. pywin32 의 IDropTarget(Drop 호출)은 힙을 깨뜨려 프로그램이 죽음
  (0xc0000374 — 감싸기 없이 Qt 입구를 pywin32 로 Drop 해도 똑같이 죽는 것 실측, 11/2).
실패해도 예전 방식(Qt 데이터)으로 돌아감 — 끌어 놓기 자체는 안 깨지게.
"""
import ctypes
import ctypes.wintypes as W
import logging

log = logging.getLogger("QE")

OLEHOOK_VER = "1.1.0"
_u = ctypes.windll.user32
_u.GetPropW.restype = ctypes.c_void_p
_u.GetPropW.argtypes = [W.HWND, W.LPCWSTR]
_ole = ctypes.windll.ole32
_ole.RegisterDragDrop.argtypes = [W.HWND, ctypes.c_void_p]
_ole.RevokeDragDrop.argtypes = [W.HWND]

HR = ctypes.c_long
_QI = ctypes.WINFUNCTYPE(HR, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_REF = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
# POINTL(8바이트)은 값으로 넘어옴 → 64비트 정수 하나로 받아 그대로 넘김
_ENTER = ctypes.WINFUNCTYPE(HR, ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.c_uint64, ctypes.POINTER(W.DWORD))
_OVER = ctypes.WINFUNCTYPE(HR, ctypes.c_void_p, W.DWORD, ctypes.c_uint64, ctypes.POINTER(W.DWORD))
_LEAVE = ctypes.WINFUNCTYPE(HR, ctypes.c_void_p)

_IID_UNKNOWN = b"\x00\x00\x00\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"
_IID_DROPTARGET = b"\x22\x01\x00\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46"

_HOOKS = {}       # hwnd → (우리 입구 주소, _Target)  — 창이 다시 만들어지면 새로 끼움
_KEEP = []        # 만든 입구는 프로그램 끝까지 붙잡음 (OLE 가 아직 쥐고 있을 수 있음)
_CUR = {"ptr": None}   # 지금 끌고 있는 IDataObject 주소 (끌기 중에만)


def _vt(p):
    """COM 객체 주소 → 함수표"""
    return ctypes.cast(ctypes.c_void_p.from_address(p).value, ctypes.POINTER(ctypes.c_void_p))


class _Target:
    """IDropTarget 하나 (ctypes). 모든 호출을 orig(Qt 입구)로 넘김"""

    def __init__(self, orig):
        self.orig = orig
        vt = _vt(orig)
        _REF(vt[1])(orig)   # Qt 입구를 붙잡음 (RevokeDragDrop 이 OLE 쪽 참조를 놓아도 살아 있게)
        self.o_enter, self.o_over = _ENTER(vt[3]), _OVER(vt[4])
        self.o_leave, self.o_drop = _LEAVE(vt[5]), _ENTER(vt[6])
        self.refs = 1
        self.fns = [_QI(self.qi), _REF(self.addref), _REF(self.release),
                    _ENTER(self.enter), _OVER(self.over), _LEAVE(self.leave), _ENTER(self.drop)]
        self.vtbl = (ctypes.c_void_p * 7)(*[ctypes.cast(f, ctypes.c_void_p).value for f in self.fns])
        self.obj = ctypes.c_void_p(ctypes.addressof(self.vtbl))   # 객체 = 함수표 주소 하나
        self.ptr = ctypes.addressof(self.obj)

    def qi(self, this, riid, ppv):
        iid = ctypes.string_at(riid, 16)
        if iid in (_IID_UNKNOWN, _IID_DROPTARGET):
            ppv[0] = this
            self.refs += 1
            return 0
        ppv[0] = None
        return -2147467262   # E_NOINTERFACE

    def addref(self, this):
        self.refs += 1
        return self.refs

    def release(self, this):
        self.refs -= 1
        return max(self.refs, 0)   # 메모리는 _KEEP 이 쥐고 있어 풀지 않음

    def enter(self, this, obj, keys, pt, eff):
        _CUR["ptr"] = obj
        return self.o_enter(self.orig, obj, keys, pt, eff)

    def over(self, this, keys, pt, eff):
        return self.o_over(self.orig, keys, pt, eff)

    def leave(self, this):
        _CUR["ptr"] = None
        return self.o_leave(self.orig)

    def drop(self, this, obj, keys, pt, eff):
        _CUR["ptr"] = obj   # Qt dropEvent(→ vfiles.save) 가 이 호출 안에서 돌아감
        try:
            return self.o_drop(self.orig, obj, keys, pt, eff)
        finally:
            _CUR["ptr"] = None


def install(hwnd):
    """창 hwnd 의 끌어 놓기 입구를 감쌈. 이미 감쌌으면 그대로. → 감싼 상태면 True"""
    if not hwnd:
        return False
    try:
        p = _u.GetPropW(hwnd, "OleDropTargetInterface")
        if not p:
            return False   # 아직 Qt 가 등록 안 함
        h = _HOOKS.get(hwnd)
        if h and h[0] == p:
            return True
        t = _Target(p)
        _KEEP.append(t)
        hr = _ole.RevokeDragDrop(hwnd)
        hr2 = _ole.RegisterDragDrop(hwnd, t.ptr)
        if hr2 != 0:
            _ole.RegisterDragDrop(hwnd, p)   # 되돌려 놓기
            log.warning("끌어 놓기 입구 감싸기 실패 hwnd=%s revoke=%s register=%s — 예전 방식으로", hwnd, hr, hr2)
            return False
        _HOOKS[hwnd] = (_u.GetPropW(hwnd, "OleDropTargetInterface"), t)
        log.info("끌어 놓기 입구 감쌈 hwnd=%s", hwnd)
        return True
    except Exception:
        log.exception("끌어 놓기 입구 감싸기 실패 hwnd=%s — 예전 방식으로", hwnd)
        return False


def current():
    """지금 끌어 놓는 중인 IDataObject (pywin32 객체, 없으면 None)"""
    p = _CUR["ptr"]
    if not p:
        return None
    try:
        import pythoncom
        return pythoncom.ObjectFromAddress(p, pythoncom.IID_IDataObject)
    except Exception:
        log.exception("끌어 온 데이터 꺼내기 실패")
        return None


def get_bytes(obj, fmt_name, lindex=-1):
    """IDataObject 에서 형식 fmt_name 을 바이트로 (한 덩어리 HGLOBAL 또는 스트림 둘 다) → bytes 또는 None"""
    import pythoncom
    import win32clipboard
    cf = win32clipboard.RegisterClipboardFormat(fmt_name)
    for tymed in (pythoncom.TYMED_HGLOBAL | pythoncom.TYMED_ISTREAM, pythoncom.TYMED_ISTREAM, pythoncom.TYMED_HGLOBAL):
        try:
            med = obj.GetData((cf, None, pythoncom.DVASPECT_CONTENT, lindex, tymed))
        except Exception as ex:
            log.debug("GetData %s lindex=%d tymed=%d 실패 %s", fmt_name, lindex, tymed, ex)
            continue
        if med.tymed == pythoncom.TYMED_ISTREAM:
            st, parts = med.data, []
            while True:
                b = st.Read(1 << 20)
                if not b:
                    break
                parts.append(b)
            return b"".join(parts)
        return bytes(med.data or b"")
    return None
