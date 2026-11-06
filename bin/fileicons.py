# -*- coding: utf-8 -*-
"""파일마다 아이콘이 다른 종류 (exe·ico 등) — 그 파일의 진짜 아이콘 (0.9.112, 사용자 제보 11/6 'exe 아이콘을 못 불러옴')

배경: 목록 아이콘은 빠르게 하려고 확장자로만 정함(파일을 안 엶) → 모든 exe 가 같은 기본 그림이었음.
여기서는 그런 종류만 화면이 물어본 것을 작업 스레드 1개(백그라운드 모드)가 실제 파일로 물어봐 시스템 아이콘 번호를 받음.
번호를 받기 전에는 기본 그림 → 받으면 그 줄만 다시 그림. 결과는 (경로, 수정 시각) 으로 기억.
휴대폰·압축 안·FTP 같은 가상 경로는 안 물어봄 (파일을 열어야 해서 느림).
"""
import os
import time
import ctypes
import logging
import threading
from collections import OrderedDict
from ctypes import wintypes

from PySide6 import QtCore

log = logging.getLogger("QE.ficon")
FILEICONS_VER = "1.0.0"
OWN_EXT = {".exe", ".ico", ".cur", ".ani", ".cpl", ".scr", ".msc", ".url", ".appref-ms"}

shell32 = ctypes.windll.shell32
ole = ctypes.windll.ole32
kernel = ctypes.windll.kernel32
shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
shell32.SHGetFileInfoW.restype = ctypes.c_size_t
SHGFI_SYSICONINDEX = 0x4000


class _FI(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int), ("attr", wintypes.DWORD),
                ("name", wintypes.WCHAR * 260), ("type", wintypes.WCHAR * 80)]


def wants(name, is_dir):
    return not is_dir and os.path.splitext(name)[1].lower() in OWN_EXT


def sys_index(path):
    """실제 파일의 시스템 아이콘 번호 (없으면 -1). 작업 스레드에서"""
    fi = _FI()
    if not shell32.SHGetFileInfoW(path, 0, ctypes.byref(fi), ctypes.sizeof(fi), SHGFI_SYSICONINDEX):
        return -1
    return int(fi.iIcon)


class FileIcons(QtCore.QObject):
    """get(경로, mtime) → 번호(int) / None(아직 모름, 요청함)"""
    ready = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.cache = OrderedDict()   # (경로 소문자, mtime) → 번호
        self.want = OrderedDict()
        self.lock = threading.Lock()
        self.ev = threading.Event()
        self.alive = True
        self.th = threading.Thread(target=self._run, daemon=True, name="fileicons")
        self.th.start()
        log.info("파일 고유 아이콘 준비 v%s (%s)", FILEICONS_VER, " ".join(sorted(OWN_EXT)))

    def get(self, path, mtime):
        key = (path.lower(), mtime)
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            self.want[key] = path
            self.want.move_to_end(key)
            self.ev.set()
        return None

    def stop(self):
        self.alive = False
        self.ev.set()

    def _run(self):
        ole.CoInitializeEx(None, 2)   # 셸 확장(아이콘 처리기)용 STA
        try:
            kernel.SetThreadPriority(kernel.GetCurrentThread(), 0x00010000)   # 백그라운드 모드
        except Exception:
            pass
        n, ms, changed = 0, 0.0, 0
        while self.alive:
            self.ev.wait(1.0)
            while self.alive:
                with self.lock:
                    if not self.want:
                        self.ev.clear()
                        break
                    key, path = self.want.popitem(last=True)   # 최근에 보인 것부터
                t = time.perf_counter()
                try:
                    idx = sys_index(path)
                except Exception:
                    log.exception("파일 아이콘 실패 %s", path)
                    idx = -1
                ms += (time.perf_counter() - t) * 1000
                n += 1
                with self.lock:
                    self.cache[key] = idx
                    while len(self.cache) > 20000:
                        self.cache.popitem(last=False)
                if idx >= 0:
                    changed += 1
                    self.ready.emit(path)
            if n:
                log.info("파일 고유 아이콘 %d개 %.0fms (번호 받음 %d개)", n, ms, changed)
                n, ms, changed = 0, 0.0, 0
