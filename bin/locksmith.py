# -*- coding: utf-8 -*-
"""이 파일을 잡고 있는 프로그램 (LOCKSMITH_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '파일이 사용 중일 때 누가 잡고 있나')

- 윈도우 '다시 시작 관리자'(rstrtmgr.dll: RmStartSession · RmRegisterResources · RmGetList · RmEndSession)를 ctypes 로 부름
  (탐색기의 '다른 프로그램에서 사용 중' 과 같은 방식 · 관리자 권한 필요 없음)
- who_locks(paths) → [dict(pid, name, app_name, type, path)] — 폴더면 그 안 파일들(최대 MAX_FILES 개, 넘으면 로그에 남기고 앞 것만)
  파일이 적으면(PER_FILE 개 이하) 파일마다 따로 물어 어느 파일인지 알려 줌, 많으면 한꺼번에 묻고 path 는 고른 항목
- 창 open_dialog(parent, paths): 목록(프로그램 이름·번호·종류·파일) + [다시 찾기] [고른 프로그램 닫기]
  닫기: 창이 있으면 먼저 WM_CLOSE 로 정중히 → 5초 기다려도 안 닫히면 '강제 종료할까요?' 확인 후 TerminateProcess
  창이 없으면 바로 확인 후 강제 종료. 4Dir 자신·시스템 중요 프로세스(csrss winlogon services lsass smss wininit System)는 막음,
  explorer 는 '탐색기를 다시 시작하세요' 안내만. 닫은 뒤 다시 찾기
로그: bin\\log\\4Dir.log [QE.lock]
"""
import os
import time
import ctypes
import logging
from ctypes import wintypes

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

LOCKSMITH_VER = "1.0.0"
log = logging.getLogger("QE.lock")
MAX_FILES = 2000
PER_FILE = 60
ERROR_MORE_DATA = 234
PROTECTED = {"csrss.exe", "winlogon.exe", "services.exe", "lsass.exe", "smss.exe", "wininit.exe", "system",
             "registry", "memory compression", "svchost.exe", "dwm.exe", "fontdrvhost.exe"}
TYPE_NAMES = {0: "알 수 없음", 1: "창 프로그램", 2: "창 프로그램", 3: "서비스", 4: "탐색기", 5: "명령 창", 1000: "시스템 중요"}


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", FILETIME)]


class RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [("Process", RM_UNIQUE_PROCESS),
                ("strAppName", wintypes.WCHAR * 256),
                ("strServiceShortName", wintypes.WCHAR * 64),
                ("ApplicationType", ctypes.c_int),
                ("AppStatus", wintypes.ULONG),
                ("TSSessionId", wintypes.DWORD),
                ("bRestartable", wintypes.BOOL)]


_rm = None


def _lib():
    global _rm
    if _rm is None:
        rm = ctypes.WinDLL("rstrtmgr")
        rm.RmStartSession.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
        rm.RmRegisterResources.argtypes = [wintypes.DWORD, wintypes.UINT, ctypes.POINTER(wintypes.LPCWSTR),
                                           wintypes.UINT, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
        rm.RmGetList.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
                                 ctypes.POINTER(RM_PROCESS_INFO), ctypes.POINTER(wintypes.DWORD)]
        rm.RmEndSession.argtypes = [wintypes.DWORD]
        for f in (rm.RmStartSession, rm.RmRegisterResources, rm.RmGetList, rm.RmEndSession):
            f.restype = wintypes.DWORD
        _rm = rm
    return _rm


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_WNDENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_u32.EnumWindows.argtypes = [_WNDENUM, wintypes.LPARAM]
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_u32.IsWindowVisible.argtypes = [wintypes.HWND]
_u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_u32.GetWindow.restype = wintypes.HWND
_u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_CLOSE = 0x0010


def process_path(pid):
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value
        return ""
    finally:
        _k32.CloseHandle(h)


def _expand(paths):
    files = []
    over = False
    for p in paths:
        if os.path.isdir(p):
            for dp, dns, fns in os.walk(p):
                for fn in fns:
                    if len(files) >= MAX_FILES:
                        over = True
                        break
                    files.append((os.path.join(dp, fn), p))
                if over:
                    break
        else:
            files.append((p, p))
        if over:
            break
    if over:
        log.warning("파일이 너무 많아 앞 %d개만 확인 (%s)", MAX_FILES, paths[:3])
    return files[:MAX_FILES]


def _query(files):
    """다시 시작 관리자에 한 번 물음 → [RM_PROCESS_INFO 값 dict]"""
    rm = _lib()
    h = wintypes.DWORD(0)
    key = ctypes.create_unicode_buffer(33)
    r = rm.RmStartSession(ctypes.byref(h), 0, key)
    if r != 0:
        log.warning("RmStartSession 실패 %d", r)
        return None
    try:
        arr = (wintypes.LPCWSTR * len(files))(*files)
        r = rm.RmRegisterResources(h, len(files), arr, 0, None, 0, None)
        if r != 0:
            log.warning("RmRegisterResources 실패 %d (%d개)", r, len(files))
            return None
        need, cnt, reason = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
        r = rm.RmGetList(h, ctypes.byref(need), ctypes.byref(cnt), None, ctypes.byref(reason))
        if r == 0:
            return []
        if r != ERROR_MORE_DATA:
            log.warning("RmGetList 실패 %d", r)
            return None
        for _try in range(3):
            cnt = wintypes.UINT(need.value + 4)
            info = (RM_PROCESS_INFO * cnt.value)()
            r = rm.RmGetList(h, ctypes.byref(need), ctypes.byref(cnt), info, ctypes.byref(reason))
            if r == 0:
                return [dict(pid=info[i].Process.dwProcessId, app_name=info[i].strAppName,
                             type=info[i].ApplicationType, service=info[i].strServiceShortName)
                        for i in range(cnt.value)]
            if r != ERROR_MORE_DATA:
                log.warning("RmGetList(2) 실패 %d", r)
                return None
        return None
    finally:
        rm.RmEndSession(h)


def who_locks(paths):
    """paths(파일·폴더)를 잡고 있는 프로그램 목록"""
    t0 = time.perf_counter()
    if isinstance(paths, str):
        paths = [paths]
    paths = [os.path.normpath(p) for p in paths]
    files = _expand(paths)
    out, seen = [], set()

    def add(r, path):
        k = (r["pid"], path)
        if k in seen:
            return
        seen.add(k)
        exe = process_path(r["pid"])
        out.append(dict(pid=r["pid"], name=os.path.basename(exe) if exe else "", exe=exe,
                        app_name=r["app_name"] or os.path.basename(exe), type=r["type"],
                        service=r["service"], path=path))
    if len(files) <= PER_FILE:
        for f, _top in files:
            res = _query([f])
            for r in res or []:
                add(r, f)
    else:
        for i in range(0, len(files), 500):
            chunk = files[i:i + 500]
            res = _query([f for f, _t in chunk])
            tops = sorted({t for _f, t in chunk})
            for r in res or []:
                add(r, tops[0] if len(tops) == 1 else "; ".join(tops))
    log.info("잡고 있는 프로그램 %s (파일 %d개): %s %.0fms", paths[:3], len(files),
             [(x["pid"], x["name"]) for x in out], (time.perf_counter() - t0) * 1000)
    return out


def blocked_reason(pid, name):
    """닫으면 안 되는 프로세스면 이유 글자, 괜찮으면 None"""
    n = (name or "").lower()
    if pid == os.getpid():
        return T("4Dir 자신은 닫을 수 없습니다")
    if pid in (0, 4) or n in PROTECTED:
        return T("윈도우에 꼭 필요한 프로그램이라 닫을 수 없습니다")
    if n == "explorer.exe":
        return T("탐색기는 여기서 닫지 않습니다 — 작업 관리자에서 'Windows 탐색기'를 다시 시작하세요")
    return None


def windows_of(pid):
    """그 프로세스의 보이는 맨 위 창들"""
    hw = []

    def cb(h, _l):
        p = wintypes.DWORD()
        _u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and _u32.IsWindowVisible(h) and not _u32.GetWindow(h, 4):   # GW_OWNER 없음
            hw.append(h)
        return True
    _u32.EnumWindows(_WNDENUM(cb), 0)
    return hw


def request_close(pid):
    """창에 WM_CLOSE 보냄 → 보낸 창 수 (0 = 창 없음)"""
    hw = windows_of(pid)
    for h in hw:
        _u32.PostMessageW(h, WM_CLOSE, 0, 0)
    log.info("닫기 요청 pid %d 창 %d개", pid, len(hw))
    return len(hw)


def is_running(pid):
    h = _k32.OpenProcess(SYNCHRONIZE, False, pid)
    if not h:
        return False
    try:
        return _k32.WaitForSingleObject(h, 0) == 0x102   # WAIT_TIMEOUT = 아직 살아 있음
    finally:
        _k32.CloseHandle(h)


def terminate(pid):
    h = _k32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not h:
        log.warning("강제 종료 실패(열기) pid %d 오류 %d", pid, ctypes.get_last_error())
        return False
    try:
        ok = bool(_k32.TerminateProcess(h, 1))
        if ok:
            _k32.WaitForSingleObject(h, 3000)
        log.info("강제 종료 pid %d → %s", pid, ok)
        return ok
    finally:
        _k32.CloseHandle(h)


class LockDialog(QtWidgets.QDialog):
    WAIT_SEC = 5.0

    def __init__(self, parent, paths):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowIcon(lock_icon(32))
        self.paths = [paths] if isinstance(paths, str) else list(paths)
        self.setWindowTitle(T("잡고 있는 프로그램") + " — " + ", ".join(os.path.basename(p) or p for p in self.paths[:3]))
        self.resize(720, 380)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.head = QtWidgets.QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels([T("프로그램"), T("번호"), T("종류"), T("파일")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 100)
        lay.addWidget(self.tree, 1)
        bar = QtWidgets.QHBoxLayout()
        self.b_again = QtWidgets.QPushButton(T("다시 찾기"))
        self.b_close = QtWidgets.QPushButton(T("고른 프로그램 닫기"))
        self.status = QtWidgets.QLabel()
        bar.addWidget(self.b_again)
        bar.addWidget(self.b_close)
        bar.addWidget(self.status, 1)
        lay.addLayout(bar)
        self.b_again.clicked.connect(self.refresh)
        self.b_close.clicked.connect(self.close_selected)
        self.tree.itemSelectionChanged.connect(lambda: self.b_close.setEnabled(bool(self.tree.selectedItems()) and not self._waiting))
        self._waiting = {}
        self._timer = QtCore.QTimer(self)          # 닫기를 기다리는 동안만 돔
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)
        self.ask = self._ask_yes_no
        QtGui.QShortcut(QtGui.QKeySequence("F5"), self, self.refresh)
        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self, self.close)
        QtCore.QTimer.singleShot(0, self.refresh)

    def _ask_yes_no(self, title, text):
        return QtWidgets.QMessageBox.question(self, title, text) == QtWidgets.QMessageBox.Yes

    def refresh(self):
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.rows = who_locks(self.paths)
        except Exception:
            log.exception("잡은 프로그램 찾기 실패")
            self.rows = []
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.tree.clear()
        for r in self.rows:
            it = QtWidgets.QTreeWidgetItem([r["app_name"] or r["name"], str(r["pid"]),
                                            T(TYPE_NAMES.get(r["type"], "알 수 없음")), r["path"]])
            it.setToolTip(0, r.get("exe") or r["name"])
            it.setToolTip(3, r["path"])
            it.setData(0, Qt.UserRole, r)
            self.tree.addTopLevelItem(it)
        if self.rows:
            self.head.setText(T("이 항목을 잡고 있는 프로그램 {0}개 — 닫으면 파일을 지우거나 옮길 수 있습니다").format(len({r['pid'] for r in self.rows})))
        else:
            self.head.setText(T("잡고 있는 프로그램이 없습니다"))
        self.b_close.setEnabled(False)

    def close_selected(self):
        sel = [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]
        pids = {}
        for r in sel:
            pids[r["pid"]] = r
        msgs = []
        for pid, r in pids.items():
            why = blocked_reason(pid, r["name"]) or (T("윈도우에 꼭 필요한 프로그램이라 닫을 수 없습니다") if r["type"] == 1000 else None)
            if why:
                msgs.append(f"{r['app_name'] or r['name']} ({pid}): {why}")
                log.info("닫기 막음 pid %d %s: %s", pid, r["name"], why)
                continue
            if request_close(pid):
                self._waiting[pid] = (time.time(), r)
            else:
                self._force(pid, r, T("{0} ({1}) 는 창이 없어 정중히 닫을 수 없습니다.\n강제 종료할까요? 저장 안 한 내용은 사라집니다.").format(r["app_name"] or r["name"], pid))
        if msgs:
            self.status.setText(" / ".join(msgs))
        if self._waiting:
            self.b_close.setEnabled(False)
            self.status.setText(T("프로그램이 닫히기를 기다리는 중…"))
            self._timer.start()
        else:
            QtCore.QTimer.singleShot(300, self.refresh)

    def _force(self, pid, r, text):
        if self.ask(T("강제 종료"), text):
            ok = terminate(pid)
            if not ok:
                self.status.setText(T("닫지 못했습니다 (권한이 없을 수 있음): {0}").format(r["app_name"] or r["name"]))
        else:
            log.info("강제 종료 안 함 pid %d", pid)

    def _poll(self):
        now = time.time()
        for pid, (t, r) in list(self._waiting.items()):
            if not is_running(pid):
                log.info("pid %d 닫힘 (%.1f초)", pid, now - t)
                del self._waiting[pid]
            elif now - t > self.WAIT_SEC:
                del self._waiting[pid]
                self._force(pid, r, T("{0} ({1}) 가 {2}초 동안 닫히지 않았습니다.\n강제 종료할까요? 저장 안 한 내용은 사라집니다.").format(r["app_name"] or r["name"], pid, int(self.WAIT_SEC)))
        if not self._waiting:
            self._timer.stop()
            self.status.setText("")
            self.refresh()

    def closeEvent(self, ev):
        self._timer.stop()
        self._waiting.clear()
        super().closeEvent(ev)


def open_dialog(parent, paths):
    d = LockDialog(parent, paths)
    d.show()
    return d


def lock_icon(sz=16):
    """자물쇠"""
    def draw(p):
        p.setPen(QtGui.QPen(QtGui.QColor("#6b7280"), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QtCore.QRectF(5.5, 2, 9, 10), 0, 180 * 16)
        p.drawLine(QtCore.QPointF(5.5, 7), QtCore.QPointF(5.5, 9))
        p.drawLine(QtCore.QPointF(14.5, 7), QtCore.QPointF(14.5, 9))
        p.setPen(QtGui.QPen(QtGui.QColor("#b45309"), 1.0))
        p.setBrush(QtGui.QColor("#f2c14e"))
        p.drawRoundedRect(QtCore.QRectF(3.5, 8.5, 13, 9.5), 1.5, 1.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#7c4a03"))
        p.drawEllipse(QtCore.QPointF(10, 12.3), 1.5, 1.5)
        p.drawRect(QtCore.QRectF(9.4, 12.5, 1.2, 3))
    return _icon(sz, draw)


def _icon(sz, draw):
    pm = QtGui.QPixmap(sz * 2, sz * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(sz * 2 / 20.0, sz * 2 / 20.0)
    draw(p)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QtGui.QIcon(pm)
