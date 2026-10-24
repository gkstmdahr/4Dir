# -*- coding: utf-8 -*-
"""그림 미리보기(썸네일) — 아이콘 보기에서 그림 파일을 미리보기로 (10/6 사용자 요청)

- 윈도우 미리보기(IShellItemImageFactory, 탐색기와 같은 캐시) 사용 → PNG·JPG 뿐 아니라 PSD·TGA 등도
  PC 에 미리보기 지원이 깔려 있으면 탐색기처럼 나옴.
- 화면에 보이는 것만: 목록이 그릴 때 물어본 그림만 요청(목록 모델 data()) → 작업 스레드 1개가 뒤에서 만듦.
- 작업 스레드는 '백그라운드 모드'(낮은 CPU·디스크 우선순위) — 3ds Max 등 다른 프로그램 우선.
- 최근 요청 먼저(스크롤하면 지금 보이는 것부터), 폴더를 옮기면 이전 요청은 버림.
- 만든 것은 메모리에 기억(약 120MB 까지, 오래된 것부터 버림) → 같은 폴더로 돌아오면 바로.
실측(10/6, 40장 96px): 윈도우 미리보기 처음 1.0~1.3초, 두 번째 0.4~0.5초.
1.1.0 (v0.9.58): .max = 파일 안 미리보기를 직접 읽음(요약 정보의 윈도우 메타파일 안 비트맵, 1ms 안팎 —
  3ds Max·Autodesk 부품 필요 없음, 맥스 없는 PC 에서도 나옴). .psd = 파일 안 미리보기(JPEG)를 직접 읽어 GDI+ 로 풂
  (윈도우는 PSD 미리보기가 없음). 둘 다 실패하면 윈도우 미리보기. 파일은 앞부분·요약 정보만 읽음(전체 안 읽음).
"""
import os
import time
import struct
import ctypes
import logging
import threading
from collections import OrderedDict
from ctypes import wintypes

from PySide6 import QtCore, QtGui

log = logging.getLogger("QE.thumb")
VERSION = "1.2.0"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".psd", ".dds", ".tif", ".tiff", ".webp", ".ico", ".exr", ".hdr", ".max"}
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
    return _hbitmap_image(hb)


def _hbitmap_image(hb):
    """HBITMAP → QImage (HBITMAP 은 지움)"""
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


# ---------------------------------------------------------------- 파일 안 미리보기 직접 읽기 (1.1.0)
def _fit(img, px):
    if img is None or img.isNull():
        return None
    if img.width() > px or img.height() > px:
        img = img.scaled(px, px, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    return img


def _dib_image(dib):
    """CF_DIB(BITMAPINFOHEADER + 색표 + 점) → QImage (BMP 머리를 붙여 Qt 기본 BMP 읽기로)"""
    hsize, w, h, planes, bpp, comp, isize, xp, yp, used = struct.unpack_from("<IiiHHIIiiI", dib, 0)
    colors = used or ((1 << bpp) if bpp <= 8 else (3 if comp == 3 else 0))
    off = 14 + hsize + colors * 4
    return QtGui.QImage.fromData(b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, off) + dib, "BMP")


def max_preview(path):
    """.max (OLE 저장소) 요약 정보 PIDSI_THUMBNAIL(17) → VT_CF → CF_METAFILEPICT(WMF 안 StretchDIB) 또는 CF_DIB → QImage.
    없거나 형식이 다르면 None"""
    import pythoncom
    from win32com import storagecon
    stg = pythoncom.StgOpenStorage(path, None, storagecon.STGM_READ | storagecon.STGM_SHARE_DENY_NONE | storagecon.STGM_TRANSACTED)
    st = stg.OpenStream("SummaryInformation", None, storagecon.STGM_READ | storagecon.STGM_SHARE_EXCLUSIVE)
    data = b""
    while len(data) < 16 << 20:
        chunk = st.Read(1 << 20)
        if not chunk:
            break
        data += chunk
    off = struct.unpack_from("<I", data, 44)[0]
    for i in range(struct.unpack_from("<I", data, off + 4)[0]):
        pid, po = struct.unpack_from("<II", data, off + 8 + i * 8)
        if pid != 17:
            continue
        p = off + po
        vt, size, fmt = struct.unpack_from("<IIi", data, p)
        if vt != 0x47:   # VT_CF
            return None
        body, end = p + 12, p + 8 + size
        if fmt == -1:   # 윈도우 클립보드 형식 → 다음 4바이트가 형식 번호
            fmt = struct.unpack_from("<I", data, body)[0]
            body += 4
        blob = data[body:end]
        if fmt == 8:    # CF_DIB
            return _dib_image(blob)
        if fmt == 3:    # CF_METAFILEPICT: 머리 8 + WMF(머리 18) → StretchDIB(0x0F43)/DIBStretchBlt(0x0B41) 기록의 DIB
            wmf, q = blob[8:], 18
            while q + 6 <= len(wmf):
                rsz, fn = struct.unpack_from("<IH", wmf, q)
                if rsz < 3:
                    break
                if fn in (0x0F43, 0x0B41):
                    return _dib_image(wmf[q + 6 + (22 if fn == 0x0F43 else 20): q + rsz * 2])
                q += rsz * 2
        return None
    return None


_gdip = {"token": None}


def _gdiplus():
    if _gdip["token"] is None:
        class _SI(ctypes.Structure):
            _fields_ = [("ver", ctypes.c_uint32), ("cb", ctypes.c_void_p), ("bg", ctypes.c_int), ("codecs", ctypes.c_int)]
        tok = ctypes.c_size_t()
        if ctypes.windll.gdiplus.GdiplusStartup(ctypes.byref(tok), ctypes.byref(_SI(1, None, 0, 0)), None) != 0:
            raise OSError("GdiplusStartup")
        _gdip["token"] = tok
    return ctypes.windll.gdiplus


def jpeg_image(data):
    """JPEG 바이트 → QImage (윈도우 GDI+ 로 풂 — 배포판 Qt 에는 JPEG 읽기 부품이 없음)"""
    g = _gdiplus()
    shl = ctypes.windll.shlwapi
    shl.SHCreateMemStream.restype = ctypes.c_void_p
    shl.SHCreateMemStream.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    stream = shl.SHCreateMemStream(data, len(data))
    if not stream:
        return None
    bmp, hb = ctypes.c_void_p(), wintypes.HBITMAP()
    try:
        if g.GdipCreateBitmapFromStream(ctypes.c_void_p(stream), ctypes.byref(bmp)) != 0:
            return None
        if g.GdipCreateHBITMAPFromBitmap(bmp, ctypes.byref(hb), ctypes.c_uint32(0xFF000000)) != 0:
            return None
        img = _hbitmap_image(hb)
        return img.convertToFormat(QtGui.QImage.Format_RGB32) if img is not None else None
    finally:
        if bmp:
            g.GdipDisposeImage(bmp)
        vt = ctypes.cast(ctypes.cast(ctypes.c_void_p(stream), ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])(stream)


def psd_preview(path):
    """.psd 이미지 자원 1036(포토샵 5+, RGB JPEG) / 1033(옛, BGR JPEG) → QImage. 앞부분만 읽음. 없으면 None"""
    with open(path, "rb") as f:
        if f.read(4) != b"8BPS":
            return None
        f.seek(26)
        f.seek(struct.unpack(">I", f.read(4))[0], 1)        # 색 모드 자료 건너뜀
        end = struct.unpack(">I", f.read(4))[0] + f.tell()  # 이미지 자원 구역 끝
        while f.tell() + 12 <= end:
            if f.read(4) != b"8BIM":
                return None
            rid = struct.unpack(">H", f.read(2))[0]
            nl = f.read(1)[0]
            f.seek(nl + ((nl + 1) % 2), 1)                  # 이름(짝수 맞춤)
            size = struct.unpack(">I", f.read(4))[0]
            if rid in (1036, 1033) and size > 28:
                img = jpeg_image(f.read(size)[28:])          # 28바이트 머리 뒤가 JPEG
                if img is not None and rid == 1033:
                    img = img.rgbSwapped()
                return img
            f.seek(size + (size % 2), 1)
    return None


def make_image(path, px):
    """미리보기 하나 만들기 — .max·.psd 는 파일 안 미리보기 먼저, 없으면 윈도우 미리보기"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".max", ".psd"):
        try:
            img = _fit(max_preview(path) if ext == ".max" else psd_preview(path), px)
            if img is not None:
                return img
        except Exception as ex:
            log.debug("파일 안 미리보기 못 읽음 %s: %s", path, ex)
    return shell_thumbnail(path, px)


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

    def peek(self, path, mtime):
        """이미 만들어 둔 미리보기 중 가장 큰 것 (요청은 안 함) — 끌기 그림용 (thumbs 1.2.0, 4Dir v0.9.67). 없으면 None"""
        lp = path.lower()
        best = None
        for (kp, km, kpx), pm in list(self.pix.items()):
            if kp == lp and km == mtime and (best is None or kpx > best[0]):
                best = (kpx, pm)
        with self.lock:
            for (kp, km, kpx), img in self.cache.items():
                if kp == lp and km == mtime and (best is None or kpx > best[0]):
                    best = (kpx, img)
        if best is None:
            return None
        v = best[1]
        return v if isinstance(v, QtGui.QPixmap) else QtGui.QPixmap.fromImage(v)

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
                    img = make_image(path, key[2])
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
