# -*- coding: utf-8 -*-
"""폴더 미리보기 (FOLDERPREV_VER 1.0.0, 4Dir 0.9.117 — 사용자 11/8 '미리보기에 폴더는 왜 하는거지?' → 1번 '폴더 내용 미리보기')

미리보기 창에서 폴더를 고르면:
- 위: 폴더 바로 안 그림(이름 순, 숫자는 크기 순) 앞 MAX_PICS 장을 작은 그림으로 — 그림은 main 의 그림 미리보기(thumbs) 를
  같이 씀(같은 기억·낮은 우선순위 작업 스레드). 그림이 없으면 바로 안 항목 이름 몇 개를 아이콘과 함께.
  그림을 두 번 누르면 open_cb(경로) — main 이 그 파일을 기본 프로그램으로 엶
- 아래: 파일 n개 · 폴더 n개 · 전체 크기 — 뒤 스레드가 하위 폴더까지 셈(링크·연결 지점은 안 따라감), 0.3초마다 중간 값,
  다른 것을 고르거나 창이 숨으면 바로 멈춤(alive 끔). 바로 안 그림 수도 표시
- 바로 안 목록 읽기는 앞 SCAN_LIMIT 개까지만 (아주 큰 폴더에서도 화면이 멈추지 않게)
로그: bin\\log\\4Dir.log [QE.folderprev]
"""
import os
import re
import time
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

FOLDERPREV_VER = "1.1.0"   # 1.1.0: info_cb 가 있으면 개수·크기를 미리보기 창 정보 표로 넘기고 아래 줄은 안 보임
log = logging.getLogger("QE.folderprev")
MAX_PICS = 12
PIC_PX = 128          # 미리보기 요청 크기 (칸은 창 폭에 맞춰 줄여 그림)
SCAN_LIMIT = 5000     # 바로 안 목록은 이만큼만 훑음
COUNT_LIMIT = 300_000  # 하위까지 세기는 항목 이만큼 / COUNT_SEC 초까지만 (드라이브 맨 위 등) — 넘으면 '넘음' 표시
COUNT_SEC = 15.0
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".psd", ".dds", ".tif", ".tiff", ".webp", ".ico", ".exr", ".hdr", ".max"}


def can_handle(path):
    return bool(path) and os.path.isdir(path)


def make_widget(path, parent=None, thumb=None, open_cb=None, icon_for=None, info_cb=None):
    return FolderPreview(path, parent, thumb, open_cb, icon_for, info_cb)


def _natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s.lower())]


def size_text(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024.0


def list_top(folder, limit=SCAN_LIMIT):
    """바로 안: (그림 [(경로, mtime)] 이름 순, 그 밖의 항목 [(이름, 폴더?)] 앞 일부, 그림 수, 훑은 수, 다 훑었나)"""
    pics, others, n = [], [], 0
    full = True
    try:
        with os.scandir(folder) as it:
            for d in it:
                n += 1
                if n > limit:
                    full = False
                    break
                try:
                    isdir = d.is_dir(follow_symlinks=False)
                    if not isdir and os.path.splitext(d.name)[1].lower() in IMAGE_EXT:
                        pics.append((d.path, int(d.stat(follow_symlinks=False).st_mtime)))
                    elif len(others) < 200:
                        others.append((d.name, isdir))
                except OSError:
                    continue
    except OSError as ex:
        log.info("폴더 못 읽음 %s: %s", folder, ex)
    pics.sort(key=lambda t: _natkey(os.path.basename(t[0])))
    others.sort(key=lambda t: (not t[1], _natkey(t[0])))
    return pics, others, len(pics), min(n, limit), full


class _Sig(QtCore.QObject):
    progress = QtCore.Signal(int, int, int, int)   # 파일, 폴더, 바이트, 상태(0 세는 중 · 1 끝 · 2 한도 넘어 멈춤)


class _Counter:
    """하위 폴더까지 파일·폴더·크기 세기 (뒤 스레드). stop() 하면 곧 멈춤"""

    def __init__(self, root, sig):
        self.root, self.sig, self.alive = root, sig, True
        threading.Thread(target=self._run, daemon=True, name="folderprev-count").start()

    def stop(self):
        self.alive = False

    def _run(self):
        try:   # 낮은 CPU·디스크 우선순위 (다른 프로그램 먼저)
            import ctypes
            ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), 0x00010000)
        except Exception:
            pass
        t0 = time.time()
        last = t0
        files = dirs = size = 0
        stack = [self.root]
        while stack and self.alive:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for d in it:
                        if not self.alive:
                            break
                        try:
                            if d.is_dir(follow_symlinks=False):
                                dirs += 1
                                if not d.is_symlink() and not (d.stat(follow_symlinks=False).st_file_attributes & 0x400):   # 연결 지점(링크) 안 따라감
                                    stack.append(d.path)
                            else:
                                files += 1
                                size += d.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
            now = time.time()
            if (files + dirs > COUNT_LIMIT or now - t0 > COUNT_SEC) and self.alive:
                self._emit(files, dirs, size, 2)
                log.info("폴더 세기 한도에서 멈춤 %s 파일 %d 폴더 %d %.1f초", self.root, files, dirs, now - t0)
                return
            if now - last > 0.3 and self.alive:
                last = now
                self._emit(files, dirs, size, 0)
        if self.alive:
            self._emit(files, dirs, size, 1)
            log.info("폴더 세기 %s 파일 %d 폴더 %d %s %.2f초", self.root, files, dirs, size_text(size), time.time() - t0)
        else:
            log.info("폴더 세기 멈춤 %s (파일 %d 까지)", self.root, files)

    def _emit(self, *a):
        try:
            self.sig.progress.emit(*a)
        except RuntimeError:   # 위젯이 이미 지워짐
            self.alive = False


class FolderPreview(QtWidgets.QWidget):
    def __init__(self, path, parent=None, thumb=None, open_cb=None, icon_for=None, info_cb=None):
        super().__init__(parent)
        self.info_cb = info_cb
        self.path = path
        self.thumb = thumb
        self.open_cb = open_cb
        t0 = time.time()
        pics, others, npics, nscan, full = list_top(path)
        self.pics = pics[:MAX_PICS]
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.grid = QtWidgets.QListWidget()
        self.grid.setViewMode(QtWidgets.QListView.IconMode)
        self.grid.setResizeMode(QtWidgets.QListView.Adjust)
        self.grid.setMovement(QtWidgets.QListView.Static)
        self.grid.setWrapping(True)
        self.grid.setSpacing(4)
        self.grid.setUniformItemSizes(True)
        self.grid.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.grid.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.itemDoubleClicked.connect(self._open)
        self.items = {}
        self.pms = {}         # 경로 → 받은 미리보기 (창 폭 바뀌면 다시 줄여 그림)
        if self.pics:
            self._cell = 96
            self.grid.setIconSize(QtCore.QSize(self._cell, self._cell))
            self.grid.setGridSize(QtCore.QSize(self._cell + 8, self._cell + 8))
            ph = QtGui.QPixmap(self._cell, self._cell)
            ph.fill(QtGui.QColor(128, 128, 128, 40))
            for p, mt in self.pics:
                it = QtWidgets.QListWidgetItem(QtGui.QIcon(ph), "")
                it.setToolTip(os.path.basename(p))
                it.setData(Qt.UserRole, p)
                it.setSizeHint(QtCore.QSize(self._cell + 8, self._cell + 8))
                self.grid.addItem(it)
                self.items[os.path.normcase(p)] = (it, mt)
            if thumb is not None:
                thumb.ready.connect(self._on_ready)
                self._connected = True
                for p, mt in self.pics:
                    pm = thumb.get(p, mt, PIC_PX)
                    if pm is not None:
                        self._set_pm(p, pm)
        else:   # 그림이 없으면 바로 안 항목 이름
            self.grid.setViewMode(QtWidgets.QListView.ListMode)
            self.grid.setWrapping(False)
            self.grid.setIconSize(QtCore.QSize(16, 16))
            for name, isdir in others[:30]:
                it = QtWidgets.QListWidgetItem(name)
                if icon_for is not None:
                    try:
                        it.setIcon(icon_for(name, isdir))
                    except Exception:
                        pass
                it.setData(Qt.UserRole, os.path.join(path, name))
                self.grid.addItem(it)
            if not others:
                self.grid.addItem(QtWidgets.QListWidgetItem(T("빈 폴더")))
        lay.addWidget(self.grid, 1)
        head = QtWidgets.QLabel()
        head.setWordWrap(True)
        if npics:
            head.setText(T("그림 {0}장").format(f"{npics:,}" + ("+" if not full else "")) +
                         (T(" (앞 {0}장 보기)").format(len(self.pics)) if npics > len(self.pics) else ""))
        else:
            head.setText(T("그림 없음 — 안에 든 것"))
        head.setStyleSheet("QLabel{color:palette(mid);}")
        lay.insertWidget(0, head)
        self.lb_count = QtWidgets.QLabel(T("세는 중…"))
        self.lb_count.setAlignment(Qt.AlignHCenter)
        self.lb_count.setWordWrap(True)
        lay.addWidget(self.lb_count)
        self.lb_count.setVisible(info_cb is None)
        self.sig = _Sig()
        self.sig.progress.connect(self._on_count)
        self.counter = _Counter(path, self.sig)
        log.info("폴더 미리보기 %s 그림 %d(보임 %d) 항목 %d %s %.0fms", path, npics, len(self.pics), nscan,
                 "" if full else "(앞부분만)", (time.time() - t0) * 1000)

    def _set_pm(self, path, pm):
        hit = self.items.get(os.path.normcase(path))
        if hit is None or pm is None or (hasattr(pm, "isNull") and pm.isNull()):
            return
        self.pms[os.path.normcase(path)] = pm
        c = self._cell
        sc = pm.scaled(c, c, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        sc.setDevicePixelRatio(1.0)
        hit[0].setIcon(QtGui.QIcon(sc))

    def resizeEvent(self, e):
        """창 폭에 맞춰 한 줄에 3장(좁으면 2장) — 칸 크기 다시 정하고 받은 그림 다시 줄임"""
        super().resizeEvent(e)
        if not self.pics:
            return
        vw = self.width() - self.grid.verticalScrollBar().sizeHint().width() - 4   # 목록 안쪽 폭은 이 시점에 아직 옛 값이라 내 폭 기준
        n = 3 if vw >= 240 else 2
        c = max(48, (vw - 4) // n - 8)
        if c == getattr(self, "_cell", None) and self.grid.gridSize().width() == c + 8:
            return
        self._cell = c
        self.grid.setIconSize(QtCore.QSize(c, c))
        self.grid.setGridSize(QtCore.QSize(c + 8, c + 8))
        for k, (it, _mt) in self.items.items():
            it.setSizeHint(QtCore.QSize(c + 8, c + 8))
            if k in self.pms:
                sc = self.pms[k].scaled(c, c, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                sc.setDevicePixelRatio(1.0)
                it.setIcon(QtGui.QIcon(sc))

    def _on_ready(self, path, px):
        if px != PIC_PX or self.thumb is None:
            return
        hit = self.items.get(os.path.normcase(path))
        if hit is not None:
            self._set_pm(path, self.thumb.get(path, hit[1], PIC_PX))

    def _on_count(self, files, dirs, size, state):
        if not self.counter.alive:   # 멈춘 뒤 늦게 도착한 값(다른 것을 고른 뒤)은 버림
            return
        if self.info_cb is not None:
            try:
                self.info_cb(files, dirs, size, state)
            except RuntimeError:
                pass
        txt = T("파일 {0}개 · 폴더 {1}개 · {2}").format(f"{files:,}", f"{dirs:,}", size_text(size))
        self.lb_count.setText(txt if state == 1 else txt + "  " + (T("(세는 중…)") if state == 0 else T("(너무 많아 여기까지만 셈)")))

    def _open(self, it):
        p = it.data(Qt.UserRole)
        if p and self.open_cb:
            log.info("폴더 미리보기에서 열기 %s", p)
            self.open_cb(p)

    def stop(self):
        if getattr(self, "counter", None) is not None:
            self.counter.stop()
        if self.thumb is not None and getattr(self, "_connected", False):
            try:
                self.thumb.ready.disconnect(self._on_ready)
            except (RuntimeError, TypeError):
                pass
            self._connected = False
        self.thumb = None

    def hideEvent(self, e):
        self.stop()
        super().hideEvent(e)
