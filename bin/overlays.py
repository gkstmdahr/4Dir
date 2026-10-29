# -*- coding: utf-8 -*-
"""버전 관리 표시 (윈도우 겹침 아이콘) — SVN 이 아닌 폴더에서 Git·Perforce 등 표시 (10/6 사용자 요청)

- 그 PC 에 깔린 연동 도구(TortoiseGit, P4EXP, Plastic 등)가 탐색기에 그리는 겹침 아이콘을 그대로 받아와 4Dir 아이콘에 얹음.
  4Dir 는 Git·Perforce 를 몰라도 됨. SVN 폴더는 4Dir 가 직접 읽는 배지(svnstat)를 씀 → 여기는 안 씀.
- 화면에 보이는 것만: 목록이 그릴 때 물어본 항목만 요청 → 작업 스레드 1개(백그라운드 모드)가 뒤에서.
- 아이콘은 윈도우 시스템 아이콘 목록에서 겹침을 얹은 채로 꺼냄 (IImageList::GetIcon + INDEXTOOVERLAYMASK).
실측(10/6, 보이는 40줄): SVN 0.14~0.15초, 일반 0.05~0.06초, 구글드라이브 0.25~0.29초.
윈도우는 겹침 아이콘을 앞에서 11개만 씀(+ 윈도우 자체 4칸) → overlayorder.py 로 순서 정리.
"""
import os
import time
import ctypes
import logging
import threading
from collections import OrderedDict
from ctypes import wintypes

from PySide6 import QtCore, QtGui

log = logging.getLogger("QE.ovl")
VERSION = "1.0.1"

shell32 = ctypes.windll.shell32
ole = ctypes.windll.ole32
user32 = ctypes.windll.user32
kernel = ctypes.windll.kernel32
# 1.0.1 (v0.9.72): 인자 형식을 알려 줌 — 안 하면 64비트 아이콘 핸들이 32비트 숫자로 넘어가다 'int too long to convert' 로
# 멈춰 그 파일 겹침 표시가 빠지고 아이콘도 안 지워졌음(10/29 로그 13번 실측)
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL
shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
shell32.SHGetFileInfoW.restype = ctypes.c_size_t


class _FI(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int), ("attr", wintypes.DWORD),
                ("name", wintypes.WCHAR * 260), ("type", wintypes.WCHAR * 80)]


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    ole.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


_IID_IImageList = _guid("{46EB5926-582E-4017-9FDF-E8998DAA0950}")
SHGFI_ICON, SHGFI_SYSICONINDEX, SHGFI_OVERLAYINDEX, SHGFI_SMALLICON = 0x100, 0x4000, 0x40, 0x1
ILD_TRANSPARENT = 0x1
SHIL = {16: 1, 32: 0, 48: 2, 256: 4}   # SHIL_SMALL, SHIL_LARGE, SHIL_EXTRALARGE, SHIL_JUMBO


def _shil_for(px):
    for s in (16, 32, 48, 256):
        if px <= s:
            return s
    return 256


def overlay_icon(path, px):
    """(겹침 번호, QImage 또는 None). 겹침이 없으면 (0, None). 작업 스레드에서 부름"""
    fi = _FI()
    # SHGFI_OVERLAYINDEX 는 SHGFI_ICON 과 같이 써야 함(없으면 늘 0 — 10/6 실측)
    if not shell32.SHGetFileInfoW(path, 0, ctypes.byref(fi), ctypes.sizeof(fi), SHGFI_ICON | SHGFI_SYSICONINDEX | SHGFI_OVERLAYINDEX | SHGFI_SMALLICON):
        return 0, None
    if fi.hIcon:
        user32.DestroyIcon(fi.hIcon)
    ov = (fi.iIcon >> 24) & 0xFF
    idx = fi.iIcon & 0xFFFFFF
    if not ov:
        return 0, None
    size = _shil_for(px)
    p = ctypes.c_void_p()
    if shell32.SHGetImageList(SHIL[size], ctypes.byref(_IID_IImageList), ctypes.byref(p)) != 0 or not p:
        return ov, None
    vt = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    get_icon = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(wintypes.HICON))(vt[10])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
    hi = wintypes.HICON()
    try:
        hr = get_icon(p, idx, ILD_TRANSPARENT | (ov << 8), ctypes.byref(hi))   # INDEXTOOVERLAYMASK(ov) = ov << 8
    finally:
        release(p)
    if hr != 0 or not hi:
        return ov, None
    try:
        img = QtGui.QImage.fromHICON(int(hi.value))
    finally:
        user32.DestroyIcon(hi)
    if img.isNull():
        return ov, None
    return ov, img


class Overlays(QtCore.QObject):
    """get(경로, mtime, px) → QPixmap(겹침 얹은 아이콘) / False(겹침 없음) / None(아직 모름, 요청함)"""
    ready = QtCore.Signal(str, int)

    def __init__(self):
        super().__init__()
        self.cache = OrderedDict()   # (경로 소문자, mtime, px) → QImage | False
        self.pix = {}
        self.want = OrderedDict()
        self.lock = threading.Lock()
        self.ev = threading.Event()
        self.alive = True
        self.done_n = 0
        self.th = threading.Thread(target=self._run, daemon=True, name="overlays")
        self.th.start()
        log.info("버전 관리 표시(윈도우 겹침 아이콘) 준비 v%s", VERSION)

    def get(self, path, mtime, px):
        key = (path.lower(), mtime, px)
        pm = self.pix.get(key)
        if pm is not None:
            return pm
        with self.lock:
            if key in self.cache:
                img = self.cache[key]
                if img is False:
                    return False
            else:
                self.want[key] = path
                self.want.move_to_end(key)
                self.ev.set()
                return None
        pm = QtGui.QPixmap.fromImage(img)
        self.pix[key] = pm
        if len(self.pix) > 3000:
            self.pix.clear()
        return pm

    def forget(self, folder):
        """폴더를 다시 읽음 → 그 폴더 결과는 다시 물어봄 (커밋 등으로 상태가 바뀌었을 수 있음)"""
        f = os.path.normcase(os.path.normpath(folder))
        with self.lock:
            for k in [k for k in self.cache if os.path.normcase(os.path.dirname(k[0])) == f]:
                del self.cache[k]
                self.pix.pop(k, None)
            for k in [k for k, p in self.want.items() if os.path.normcase(os.path.dirname(p)) == f]:
                del self.want[k]

    def stop(self):
        self.alive = False
        self.ev.set()

    def _run(self):
        ole.CoInitializeEx(None, 0)
        try:
            kernel.SetThreadPriority(kernel.GetCurrentThread(), 0x00010000)   # 백그라운드 모드
        except Exception:
            pass
        batch_ms, batch_n, found = 0.0, 0, 0
        while self.alive:
            self.ev.wait(1.0)
            while self.alive:
                with self.lock:
                    if not self.want:
                        self.ev.clear()
                        break
                    key, path = self.want.popitem(last=True)
                t = time.perf_counter()
                try:
                    ov, img = overlay_icon(path, key[2])
                except Exception:
                    log.exception("겹침 아이콘 실패 %s", path)
                    ov, img = 0, None
                batch_ms += (time.perf_counter() - t) * 1000
                batch_n += 1
                self.done_n += 1
                with self.lock:
                    self.cache[key] = img if img is not None else False
                    while len(self.cache) > 20000:
                        self.cache.popitem(last=False)
                if img is not None:
                    found += 1
                    self.ready.emit(path, key[2])
            if batch_n:
                log.info("겹침 아이콘 %d개 확인 %.0fms (표시 있음 %d개, 누적 %d개)", batch_n, batch_ms, found, self.done_n)
                batch_ms, batch_n, found = 0.0, 0, 0
