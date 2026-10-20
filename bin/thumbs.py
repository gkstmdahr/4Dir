# -*- coding: utf-8 -*-
"""그림 미리보기(썸네일) — 아이콘 보기에서 그림 파일을 미리보기로 (10/6 사용자 요청)

- 윈도우 미리보기(IShellItemImageFactory, 탐색기와 같은 캐시) 사용 → PNG·JPG 뿐 아니라 PSD·TGA 등도
  PC 에 미리보기 지원이 깔려 있으면 탐색기처럼 나옴.
- 화면에 보이는 것만: 목록이 그릴 때 물어본 그림만 요청(목록 모델 data()) → 작업 스레드 1개가 뒤에서 만듦.
- 작업 스레드는 '백그라운드 모드'(낮은 CPU·디스크 우선순위) — 3ds Max 등 다른 프로그램 우선.
- 최근 요청 먼저(스크롤하면 지금 보이는 것부터), 폴더를 옮기면 이전 요청은 버림.
- 만든 것은 메모리에 기억(약 120MB 까지, 오래된 것부터 버림) → 같은 폴더로 돌아오면 바로.
실측(10/6, 40장 96px): 윈도우 미리보기 처음 1.0~1.3초, 두 번째 0.4~0.5초.
"""
import os
import time
import ctypes
import logging
import threading
from collections import OrderedDict
from ctypes import wintypes

from PySide6 import QtCore, QtGui

log = logging.getLogger("QE.thumb")
VERSION = "1.0.0"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".psd", ".dds", ".tif", ".tiff", ".webp", ".ico", ".exr", ".hdr"}
CACHE_BYTES = 120 * 1024 * 1024

ole = ctypes.windll.ole32
gdi = ctypes.windll.gdi32
kernel = ctypes.windll.kernel32


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    ole.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", ctypes.c_ushort), ("bmBitsPixel", ctypes.c_ushort), ("bmBits", ctypes.c_void_p)]


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


_IID_FACTORY = _guid("{bcc18b79-ba16-442f-80c4-8a59c30c463b}")   # IShellItemImageFactory
_SHCreate = ctypes.windll.shell32.SHCreateItemFromParsingName
_SHCreate.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
SIIGBF_THUMBNAILONLY = 0x8


def is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXT


def shell_thumbnail(path, px):
    """윈도우 미리보기 → QImage (실패하면 None). 작업 스레드에서 부름 (COM 초기화된 상태)"""
    p = ctypes.c_void_p()
    if _SHCreate(path, None, ctypes.byref(_IID_FACTORY), ctypes.byref(p)) != 0 or not p:
        return None
    vt = ctypes.cast(ctypes.cast(p, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, _SIZE, ctypes.c_int, ctypes.POINTER(wintypes.HBITMAP))(vt[3])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
    hb = wintypes.HBITMAP()
    try:
        hr = get_image(p, _SIZE(px, px), SIIGBF_THUMBNAILONLY, ctypes.byref(hb))
    finally:
        release(p)
    if hr != 0 or not hb:
        return None
    try:
        bm = _BITMAP()
        gdi.GetObjectW(hb, ctypes.sizeof(bm), ctypes.byref(bm))
        w, h = bm.bmWidth, bm.bmHeight
        if w <= 0 or h <= 0:
            return None
        bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)   # 위→아래, 32비트
        buf = ctypes.create_string_buffer(w * h * 4)
        dc = ctypes.windll.user32.GetDC(None)
        gdi.GetDIBits(dc, hb, 0, h, buf, ctypes.byref(bih), 0)
        ctypes.windll.user32.ReleaseDC(None, dc)
        fmt = QtGui.QImage.Format_ARGB32_Premultiplied if bm.bmBitsPixel == 32 else QtGui.QImage.Format_RGB32
        img = QtGui.QImage(buf.raw, w, h, w * 4, fmt).copy()   # copy = 버퍼를 Qt 가 가짐
        if bm.bmBitsPixel == 32 and _all_clear(img):   # 알파가 0 으로 오는 그림(일부 형식) → 불투명으로
            img = QtGui.QImage(buf.raw, w, h, w * 4, QtGui.QImage.Format_RGB32).copy()
        return img
    finally:
        gdi.DeleteObject(hb)


def _all_clear(img):
    w, h = img.width(), img.height()
    for x, y in ((w // 2, h // 2), (w // 4, h // 4), (3 * w // 4, 3 * h // 4), (w // 2, h // 4)):
        if img.pixelColor(x, y).alpha() != 0:
            return False
    return True


class Thumbs(QtCore.QObject):
    """요청(경로, 수정 시각, 크기) → 뒤에서 만들어 ready(경로, 크기) 신호. get() 은 있으면 QPixmap, 없으면 요청하고 None"""
    ready = QtCore.Signal(str, int)

    def __init__(self):
        super().__init__()
        self.cache = OrderedDict()   # (경로 소문자, mtime, px) → QImage
        self.bytes = 0
        self.pix = {}                # 같은 키의 QPixmap (화면 스레드에서만)
        self.want = OrderedDict()    # 기다리는 요청 (최근이 뒤)
        self.failed = set()
        self.lock = threading.Lock()
        self.ev = threading.Event()
        self.alive = True
        self.done_n = 0
        self.ms = 0.0
        self.th = threading.Thread(target=self._run, daemon=True, name="thumbs")
        self.th.start()
        log.info("그림 미리보기 준비 v%s (메모리 최대 %dMB)", VERSION, CACHE_BYTES // 1048576)

    def get(self, path, mtime, px):
        key = (path.lower(), mtime, px)
        pm = self.pix.get(key)
        if pm is not None:
            return pm
        with self.lock:
            img = self.cache.get(key)
            if img is not None:
                self.cache.move_to_end(key)
            elif key not in self.failed:
                self.want[key] = path
                self.want.move_to_end(key)
                self.ev.set()
                return None
            else:
                return None
        pm = QtGui.QPixmap.fromImage(img)
        self.pix[key] = pm
        if len(self.pix) > 1500:
            self.pix.clear()
        return pm

    def drop_pending(self, folder):
        """그 폴더를 떠남 → 그 폴더의 아직 안 만든 요청 버림 (다른 칸 요청은 그대로)"""
        f = os.path.normcase(os.path.normpath(folder))
        with self.lock:
            gone = [k for k, p in self.want.items() if os.path.normcase(os.path.dirname(p)) == f]
            for k in gone:
                del self.want[k]
            n = len(gone)
        if n:
            log.debug("미리보기 요청 %d개 버림 (폴더 이동)", n)

    def stop(self):
        self.alive = False
        self.ev.set()

    def _run(self):
        ole.CoInitializeEx(None, 0)   # MTA (실측: STA 보다 첫 호출 빠름)
        try:
            kernel.SetThreadPriority(kernel.GetCurrentThread(), 0x00010000)   # THREAD_MODE_BACKGROUND_BEGIN (낮은 CPU·디스크 우선순위)
        except Exception:
            pass
        batch_ms, batch_n = 0.0, 0
        while self.alive:
            self.ev.wait(1.0)
            while self.alive:
                with self.lock:
                    if not self.want:
                        self.ev.clear()
                        break
                    key, path = self.want.popitem(last=True)   # 최근 요청 먼저
                t = time.perf_counter()
                try:
                    img = shell_thumbnail(path, key[2])
                except Exception:
                    log.exception("미리보기 실패 %s", path)
                    img = None
                dt = (time.perf_counter() - t) * 1000
                self.ms += dt
                batch_ms += dt
                with self.lock:
                    if img is None or img.isNull():
                        self.failed.add(key)
                    else:
                        self.cache[key] = img
                        self.bytes += img.sizeInBytes()
                        while self.bytes > CACHE_BYTES and self.cache:
                            _, old = self.cache.popitem(last=False)
                            self.bytes -= old.sizeInBytes()
                self.done_n += 1
                batch_n += 1
                if img is not None:
                    self.ready.emit(path, key[2])
            if batch_n:
                log.info("미리보기 %d개 %.0fms (누적 %d개, 메모리 %.1fMB)", batch_n, batch_ms, self.done_n, self.bytes / 1048576)
                batch_ms, batch_n = 0.0, 0
