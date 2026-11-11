# -*- coding: utf-8 -*-
"""폴더 미리보기 (FOLDERPREV_VER 2.0.0, 4Dir 0.9.117 — 사용자 11/8 '미리보기에 폴더는 왜 하는거지?' → 1번 '폴더 내용 미리보기')

미리보기 창에서 폴더를 고르면:
- 맨 위 줄: [하위 폴더까지] 체크 · 가로 개수: [nn칸] (2.0.0, 0.9.132 사용자 11/11 '체크하면 하위까지 주르륵, 가로 몇 개 배치할지';
  2.1.0 사용자 '게이지 막대 길 필요 없음 → 삭제, 입력칸은 숫자 2자리+칸 만큼만') — 값은 설정(folder_prev)에 저장, 다음 폴더에도 그대로
- 체크 끔: 폴더 바로 안 그림(이름 순, 숫자는 크기 순) 앞 MAX_PICS 장. 그림이 없으면 바로 안 항목 이름 몇 개를 아이콘과 함께
- 체크 켬: 하위 폴더까지 그림·동영상(첫 장면)을 폴더 순서대로 아래로 계속 — 폴더가 바뀌는 곳마다 폴더 이름 띠.
  뒤 스레드(낮은 우선순위)가 폴더 순서대로 훑으며 찾는 대로 붙임, 최대 MAX_SUB 장 · 항목 COUNT_LIMIT 개 · SUB_SEC 초까지
- 그림은 화면에 보이는 칸(+위아래 한 화면)만 main 의 그림 미리보기(thumbs, 같은 기억·낮은 우선순위)에 요청,
  멀리 스크롤해 간 칸의 그림은 놓음(메모리). 두 번 누르면 open_cb(경로) — main 이 그 파일을 기본 프로그램으로 엶
- 2.2.0: 좁은 창이면 맨 위 줄 '가로 개수' 를 아랫줄로 내림(체크박스 글자 안 잘리게)
- 2.3.0 (사용자 11/11 'mp4 재생 안 됨, jpg 메뉴·좌우 없음 → 확장자마다 기존 미리보기 화면'): main 이 pick_cb 를 주면 누름 = pick_cb(경로, 목록 순서)
  → main 이 이 위젯을 park()(멈추지 않고 숨김) 하고 원래 파일 화면, '폴더 목록으로' 면 resume() 해서 다시 붙임(스크롤·찾은 목록 그대로).
  2.4.0: 2.2.0 의 칸 안 큰 그림 보기는 지움(사용자 '지우고') — pick_cb 가 없으면 누름은 아무것도 안 함
- 파일 n개 · 폴더 n개 · 전체 크기 — 뒤 스레드가 하위 폴더까지 셈(링크·연결 지점은 안 따라감), 0.3초마다 중간 값,
  다른 것을 고르거나 창이 숨으면 바로 멈춤(alive 끔)
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

FOLDERPREV_VER = "2.4.0"   # 2.3.0: pick_cb 가 있으면 누른 파일을 미리보기 창 원래 화면(형식별)으로 — park/resume   # 1.1.0: info_cb 가 있으면 개수·크기를 미리보기 창 정보 표로 넘기고 아래 줄은 안 보임 · 2.0.0 하위 폴더까지·칸 수
log = logging.getLogger("QE.folderprev")
MAX_PICS = 12
MAX_SUB = 2000        # 하위 폴더까지: 그림 이만큼까지
SUB_SEC = 30.0        # 하위 폴더까지 훑기 시간 한도
COLS_MAX = 20         # 가로 개수 입력칸 최대 (2자리)
SCAN_LIMIT = 5000     # 바로 안 목록은 이만큼만 훑음
COUNT_LIMIT = 300_000  # 하위까지 세기는 항목 이만큼 / COUNT_SEC 초까지만 (드라이브 맨 위 등) — 넘으면 '넘음' 표시
COUNT_SEC = 15.0
try:   # 그림 형식은 그림 미리보기(thumbs)와 같은 목록 (사본 안 둠)
    from thumbs import IMAGE_EXT
except Exception:
    IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".psd", ".dds", ".tif", ".tiff", ".webp", ".ico", ".exr", ".hdr", ".max"}
try:
    from video import EXTS as VIDEO_EXT
except Exception:
    VIDEO_EXT = set()
SUB_EXT = set(IMAGE_EXT) | set(VIDEO_EXT)
OPTS = {"sub": False, "cols": 3}   # main 이 설정(folder_prev) 의 같은 dict 를 넘기면 그것을 씀
R_PATH, R_MT, R_HEAD, R_PM = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3
NAME_H = 18           # 칸 아래 파일 이름 줄 높이
HEAD_H = 24           # 폴더 이름 띠 높이


def can_handle(path):
    return bool(path) and os.path.isdir(path)


def make_widget(path, parent=None, thumb=None, open_cb=None, icon_for=None, info_cb=None, opts=None, save_cb=None, pick_cb=None):
    return FolderPreview(path, parent, thumb, open_cb, icon_for, info_cb, opts, save_cb, pick_cb)


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


def _low_priority():
    try:   # 낮은 CPU·디스크 우선순위 (다른 프로그램 먼저)
        import ctypes
        ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), 0x00010000)
    except Exception:
        pass


def _is_link(d):
    try:
        return d.is_symlink() or bool(d.stat(follow_symlinks=False).st_file_attributes & 0x400)   # 연결 지점(링크) 안 따라감
    except OSError:
        return True


class _Sig(QtCore.QObject):
    progress = QtCore.Signal(int, int, int, int)   # 파일, 폴더, 바이트, 상태(0 세는 중 · 1 끝 · 2 한도 넘어 멈춤)
    found = QtCore.Signal(str, object)             # 하위 폴더까지: (폴더, [(경로, mtime)])
    done = QtCore.Signal(int, int, int)            # 하위 폴더까지 끝: (그림 수, 그림 있는 폴더 수, 상태 1 끝 · 2 한도)


class _Counter:
    """하위 폴더까지 파일·폴더·크기 세기 (뒤 스레드). stop() 하면 곧 멈춤"""

    def __init__(self, root, sig):
        self.root, self.sig, self.alive = root, sig, True
        threading.Thread(target=self._run, daemon=True, name="folderprev-count").start()

    def stop(self):
        self.alive = False

    def _run(self):
        _low_priority()
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
                                if not _is_link(d):
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


class _Finder:
    """하위 폴더까지 그림·동영상 찾기 (뒤 스레드, 2.0.0). 폴더 순서(이름 순, 이 폴더 파일 먼저 → 하위 폴더)대로
    폴더 하나 다 읽을 때마다 found(폴더, 목록). stop() 하면 곧 멈춤"""

    def __init__(self, root, sig):
        self.root, self.sig, self.alive = root, sig, True
        threading.Thread(target=self._run, daemon=True, name="folderprev-find").start()

    def stop(self):
        self.alive = False

    def _run(self):
        _low_priority()
        t0 = time.time()
        total = nfold = seen = 0
        state = 1
        stack = [self.root]
        while stack and self.alive:
            cur = stack.pop()
            files, subs = [], []
            try:
                with os.scandir(cur) as it:
                    for d in it:
                        if not self.alive:
                            break
                        seen += 1
                        try:
                            if d.is_dir(follow_symlinks=False):
                                if not _is_link(d):
                                    subs.append(d.path)
                            elif os.path.splitext(d.name)[1].lower() in SUB_EXT:
                                files.append((d.path, int(d.stat(follow_symlinks=False).st_mtime)))
                        except OSError:
                            continue
            except OSError as ex:
                log.info("하위 폴더 못 읽음 %s: %s", cur, ex)
                continue
            if files and self.alive:
                files.sort(key=lambda t: _natkey(os.path.basename(t[0])))
                files = files[:MAX_SUB - total]
                total += len(files)
                nfold += 1
                try:
                    self.sig.found.emit(cur, files)
                except RuntimeError:
                    self.alive = False
                    break
            subs.sort(key=lambda p: _natkey(os.path.basename(p)), reverse=True)   # 꺼낼 때 이름 순
            stack.extend(subs)
            if total >= MAX_SUB or seen > COUNT_LIMIT or time.time() - t0 > SUB_SEC:
                state = 2 if stack or total >= MAX_SUB else 1
                break
        log.info("하위 폴더까지 그림 %s %d장 폴더 %d곳 훑은 항목 %d %.2f초%s", self.root, total, nfold, seen, time.time() - t0,
                 "" if self.alive else " (멈춤)" if state == 1 else " (한도)")
        if self.alive:
            try:
                self.sig.done.emit(total, nfold, state)
            except RuntimeError:
                pass


class _Cell(QtWidgets.QStyledItemDelegate):
    """칸 그리기: 폴더 이름 띠 (한 줄 전체) / 그림 칸 (정사각형 + 아래 파일 이름)"""

    def __init__(self, fp):
        super().__init__(fp)
        self.fp = fp

    def sizeHint(self, opt, idx):
        if idx.data(R_HEAD):
            return QtCore.QSize(max(40, self.fp.row_w), HEAD_H)
        c = self.fp.cell
        return QtCore.QSize(c, c + NAME_H)

    def paint(self, p, opt, idx):
        r = opt.rect
        pal = opt.palette
        head = idx.data(R_HEAD)
        p.save()
        if head:
            p.fillRect(r.adjusted(0, 2, 0, -2), pal.color(QtGui.QPalette.AlternateBase))
            f = QtGui.QFont(opt.font)
            f.setBold(True)
            p.setFont(f)
            p.setPen(pal.color(QtGui.QPalette.WindowText))
            p.drawText(r.adjusted(6, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       QtGui.QFontMetrics(f).elidedText("📁 " + head, Qt.ElideMiddle, r.width() - 12))
            p.restore()
            return
        box = QtCore.QRect(r.x(), r.y(), r.width(), r.height() - NAME_H)
        p.fillRect(box, QtGui.QColor(128, 128, 128, 30))
        pm = idx.data(R_PM)
        if isinstance(pm, QtGui.QPixmap) and not pm.isNull():
            s = pm.size().scaled(box.size(), Qt.KeepAspectRatio)
            if s.width() > pm.width() * 2:   # 작은 그림은 2배까지만 키움
                s = pm.size() * 2
            tgt = QtCore.QRect(0, 0, s.width(), s.height())
            tgt.moveCenter(box.center())
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(tgt, pm)
        if opt.state & QtWidgets.QStyle.State_Selected:
            pen = QtGui.QPen(pal.color(QtGui.QPalette.Highlight), 2)
            p.setPen(pen)
            p.drawRect(r.adjusted(1, 1, -1, -1))
        p.setPen(pal.color(QtGui.QPalette.WindowText))
        nm = os.path.basename(idx.data(R_PATH) or "")
        p.drawText(QtCore.QRect(r.x() + 2, r.bottom() - NAME_H + 1, r.width() - 4, NAME_H), Qt.AlignCenter,
                   opt.fontMetrics.elidedText(nm, Qt.ElideMiddle, r.width() - 4))
        p.restore()


class FolderPreview(QtWidgets.QWidget):
    def __init__(self, path, parent=None, thumb=None, open_cb=None, icon_for=None, info_cb=None, opts=None, save_cb=None, pick_cb=None):
        super().__init__(parent)
        self.info_cb = info_cb
        self.pick_cb = pick_cb
        self.parked = False
        self.last_count = None
        self.focus_path = None
        self.path = path
        self.thumb = thumb
        self.open_cb = open_cb
        self.icon_for = icon_for
        self.opts = opts if isinstance(opts, dict) else OPTS
        self.opts.setdefault("sub", False)
        self.opts.setdefault("cols", 3)
        self.save_cb = save_cb
        self.finder = None
        self._connected = False
        self.cell = 96
        self.row_w = 200
        self.px = 128
        self.items = {}       # 경로(normcase) → 항목
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        # 맨 위 줄: 하위 폴더까지 · 칸 수
        bar = QtWidgets.QWidget()
        self.bar_lay = bl = QtWidgets.QGridLayout(bar)   # 2.2.0: 좁으면 '가로 개수' 를 아랫줄로 (_place_bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setHorizontalSpacing(14)
        bl.setVerticalSpacing(4)
        self.cb_sub = QtWidgets.QCheckBox(T("하위 폴더까지"))
        self.cb_sub.setToolTip(T("켜면 하위 폴더 안 그림·동영상까지 폴더별로 아래로 계속 보여 줍니다 (최대 {0}장)").format(f"{MAX_SUB:,}"))
        self.cb_sub.setChecked(bool(self.opts.get("sub")))
        self.cb_sub.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)   # 좁은 창에서도 글자 안 잘림
        bl.addWidget(self.cb_sub, 0, 0)
        self.colsw = QtWidgets.QWidget()
        cl = QtWidgets.QHBoxLayout(self.colsw)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        lb = QtWidgets.QLabel(T("가로 개수:"))
        cl.addWidget(lb)
        self.sp_cols = QtWidgets.QSpinBox()
        self.sp_cols.setRange(1, COLS_MAX)
        self.sp_cols.setSuffix(T("칸"))
        self.sp_cols.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)   # 폭 = 숫자 2자리+'칸' (최대값 기준 sizeHint)
        tip = T("한 줄에 그림 몇 장씩 놓을지")
        for w in (lb, self.sp_cols):
            w.setToolTip(tip)
        n = max(1, min(COLS_MAX, int(self.opts.get("cols") or 3)))
        self.sp_cols.setValue(n)
        cl.addWidget(self.sp_cols)
        self.colsw.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._bar_two = None
        self._place_bar()
        lay.addWidget(bar)
        self.bar = bar
        self.head = QtWidgets.QLabel()
        self.head.setWordWrap(True)
        self.head.setStyleSheet("QLabel{color:palette(mid);}")
        lay.addWidget(self.head)
        self.grid = QtWidgets.QListWidget()
        self.grid.setResizeMode(QtWidgets.QListView.Adjust)
        self.grid.setMovement(QtWidgets.QListView.Static)
        self.grid.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.grid.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.grid.verticalScrollBar().setSingleStep(40)
        self.grid.itemDoubleClicked.connect(self._open)
        self.grid.itemClicked.connect(self._clicked)
        self.delegate = _Cell(self)
        lay.addWidget(self.grid, 1)
        self.lb_count = QtWidgets.QLabel(T("세는 중…"))
        self.lb_count.setAlignment(Qt.AlignHCenter)
        self.lb_count.setWordWrap(True)
        lay.addWidget(self.lb_count)
        self.lb_count.setVisible(info_cb is None)
        self.load_t = QtCore.QTimer(self)   # 스크롤·크기 바뀜·새 칸 → 잠깐 묶어 보이는 칸 그림 요청 (유휴 시 안 돎)
        self.load_t.setSingleShot(True)
        self.load_t.setInterval(60)
        self.load_t.timeout.connect(self._load_visible)
        self.grid.verticalScrollBar().valueChanged.connect(lambda _v: self.load_t.start())
        self.sig = _Sig()
        self.sig.progress.connect(self._on_count)
        self.sig.found.connect(self._on_found)
        self.sig.done.connect(self._on_done)
        self.cb_sub.toggled.connect(self._on_sub)
        self.sp_cols.valueChanged.connect(self._on_cols)
        if thumb is not None:
            thumb.ready.connect(self._on_ready)
            self._connected = True
        self._populate()
        self.counter = _Counter(path, self.sig)

    # ---- 채우기 ----
    def _grid_mode(self, pics):
        g = self.grid
        if pics:
            g.setViewMode(QtWidgets.QListView.IconMode)
            g.setFlow(QtWidgets.QListView.LeftToRight)
            g.setWrapping(True)
            g.setUniformItemSizes(False)
            g.setGridSize(QtCore.QSize())
            g.setSpacing(4)
            g.setItemDelegate(self.delegate)
        else:   # 이름 목록
            g.setItemDelegate(QtWidgets.QStyledItemDelegate(g))
            g.setViewMode(QtWidgets.QListView.ListMode)
            g.setWrapping(False)
            g.setSpacing(0)
            g.setIconSize(QtCore.QSize(16, 16))

    def _populate(self):
        t0 = time.time()
        if self.finder is not None:
            self.finder.stop()
            self.finder = None
        self.grid.clear()
        self.items = {}
        self._measure()
        if self.opts.get("sub"):
            self._grid_mode(True)
            self.n_sub = 0
            self.head.setText(T("하위 폴더까지 찾는 중…"))
            self.finder = _Finder(self.path, self.sig)
            log.info("폴더 미리보기(하위까지) %s 칸 %d", self.path, self.sp_cols.value())
            return
        pics, others, npics, nscan, full = list_top(self.path)
        self.pics = pics[:MAX_PICS]
        self._grid_mode(bool(self.pics))
        if self.pics:
            for p, mt in self.pics:
                self._add_pic(p, mt)
            self.head.setText(T("그림 {0}장").format(f"{npics:,}" + ("+" if not full else "")) +
                              (T(" (앞 {0}장 보기)").format(len(self.pics)) if npics > len(self.pics) else ""))
        else:
            for name, isdir in others[:30]:
                it = QtWidgets.QListWidgetItem(name)
                if self.icon_for is not None:
                    try:
                        it.setIcon(self.icon_for(name, isdir))
                    except Exception:
                        pass
                it.setData(Qt.UserRole, os.path.join(self.path, name))
                self.grid.addItem(it)
            if not others:
                self.grid.addItem(QtWidgets.QListWidgetItem(T("빈 폴더")))
            self.head.setText(T("그림 없음 — 안에 든 것"))
        self.load_t.start()
        log.info("폴더 미리보기 %s 그림 %d(보임 %d) 항목 %d %s 칸 %d %.0fms", self.path, npics, len(self.pics), nscan,
                 "" if full else "(앞부분만)", self.sp_cols.value(), (time.time() - t0) * 1000)

    def _add_pic(self, p, mt):
        it = QtWidgets.QListWidgetItem()
        it.setToolTip(os.path.basename(p))
        it.setData(R_PATH, p)
        it.setData(R_MT, mt)
        self.grid.addItem(it)
        self.items[os.path.normcase(p)] = it

    def _on_found(self, folder, files):
        if self.finder is None or not self.finder.alive:
            return
        rel = os.path.relpath(folder, self.path)
        hd = QtWidgets.QListWidgetItem()
        hd.setData(R_HEAD, os.path.basename(self.path) if rel == "." else rel)
        hd.setFlags(Qt.NoItemFlags)
        hd.setToolTip(folder)
        self.grid.addItem(hd)
        for p, mt in files:
            self._add_pic(p, mt)
        self.n_sub += len(files)
        self.head.setText(T("그림 {0}장 찾는 중…").format(f"{self.n_sub:,}"))
        self.load_t.start()

    def _on_done(self, total, nfold, state):
        if self.finder is None or not self.finder.alive:
            return
        if not total:
            self._grid_mode(False)
            self.grid.addItem(QtWidgets.QListWidgetItem(T("하위 폴더까지 그림 없음")))
        txt = T("그림 {0}장 · 폴더 {1}곳").format(f"{total:,}", f"{nfold:,}")
        if state == 2:
            txt += "  " + T("(최대 {0}장까지만 표시)").format(f"{MAX_SUB:,}") if total >= MAX_SUB else "  " + T("(너무 많아 여기까지만)")
        self.head.setText(txt)

    # ---- 칸 크기 ----
    def _measure(self):
        """칸 크기 = (목록 안쪽 폭 − 사이) ÷ 칸 수. 바뀌었으면 True"""
        n = self.sp_cols.value()
        sb = self.grid.verticalScrollBar().sizeHint().width()
        vw = max(60, self.width() - sb - 6)   # 목록 안쪽 폭은 이 시점에 아직 옛 값이라 내 폭 기준
        c = max(40, (vw - 4 * (n + 1)) // n - 1)
        px = 128 if c <= 128 else 256 if c <= 256 else 512
        changed = (c, vw) != (self.cell, self.row_w)
        if px != self.px:
            self.px = px
            for it in self.items.values():   # 크기가 바뀌면 다시 요청
                it.setData(R_PM, None)
        self.cell, self.row_w = c, vw - 8
        return changed

    def _relayout(self):
        if self._measure():
            self.grid.doItemsLayout()
        self.load_t.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_bar()
        self._relayout()

    def _place_bar(self):
        """체크박스 + 가로 개수가 한 줄에 다 안 들어가면 가로 개수를 아랫줄로"""
        need = self.cb_sub.sizeHint().width() + self.bar_lay.horizontalSpacing() + self.colsw.sizeHint().width()
        two = self.width() < need
        if two == self._bar_two:
            return
        self._bar_two = two
        self.bar_lay.removeWidget(self.colsw)
        if two:
            self.bar_lay.addWidget(self.colsw, 1, 0, Qt.AlignLeft)
        else:
            self.bar_lay.addWidget(self.colsw, 0, 1, Qt.AlignLeft)
        self.bar_lay.setColumnStretch(0, 0)
        self.bar_lay.setColumnStretch(1, 0)
        self.bar_lay.setColumnStretch(2, 1)

    def _clicked(self, it):
        p = it.data(R_PATH)
        if not p or it.data(R_HEAD) or os.path.splitext(p)[1].lower() not in SUB_EXT:
            return
        if self.pick_cb is None:
            return
        paths = [self.grid.item(i).data(R_PATH) for i in range(self.grid.count())
                 if not self.grid.item(i).data(R_HEAD) and self.grid.item(i).data(R_PATH)
                 and os.path.splitext(self.grid.item(i).data(R_PATH))[1].lower() in SUB_EXT]
        log.info("폴더 미리보기 누름 → 원래 파일 화면 %s (목록 %d개)", p, len(paths))
        self.pick_cb(p, paths)

    def park(self):
        """main 이 원래 파일 화면을 보여 주는 동안 숨김 — 뒤 작업·그림 연결은 그대로 (hideEvent 에서 멈추지 않음)"""
        self.parked = True
        self.scroll_y = self.grid.verticalScrollBar().value()

    def resume(self):
        """다시 붙음: 스크롤 위치 그대로, 본 파일 칸 선택, 개수·크기 표 다시 알림"""
        self.parked = False
        if self.last_count is not None and self.info_cb is not None:
            try:
                self.info_cb(*self.last_count)
            except RuntimeError:
                pass
        sy = getattr(self, "scroll_y", 0)
        fp = self.focus_path
        it = self.items.get(os.path.normcase(fp)) if fp else None

        def _restore():
            self.grid.verticalScrollBar().setValue(sy)
            if it is not None:
                self.grid.setCurrentItem(it)
                self.grid.scrollToItem(it)   # ◀ ▶ 로 멀리 갔으면 그 칸이 보이게
            self.load_t.start()
        QtCore.QTimer.singleShot(0, _restore)
        log.info("폴더 미리보기 다시 붙음 %s (스크롤 %d, 본 파일 %s)", self.path, sy, os.path.basename(fp) if fp else "-")

    def _on_cols(self, n):
        if self.opts.get("cols") != n:
            self.opts["cols"] = n
            log.info("폴더 미리보기 칸 수 → %d", n)
            self._save()
        self._relayout()

    def _on_sub(self, on):
        self.opts["sub"] = bool(on)
        log.info("폴더 미리보기 하위 폴더까지 → %s", on)
        self._save()
        self._populate()

    def _save(self):
        if self.save_cb is not None:
            try:
                self.save_cb()
            except Exception:
                log.exception("폴더 미리보기 설정 저장 실패")

    # ---- 그림 ----
    def _load_visible(self):
        """보이는 칸(+위아래 한 화면)만 그림 요청, 세 화면 넘게 멀어진 칸은 그림 놓음"""
        if self.thumb is None or not self.items:
            return
        vp = self.grid.viewport().rect()
        h = vp.height()
        near = vp.adjusted(0, -h, 0, h)
        far = vp.adjusted(0, -3 * h, 0, 3 * h)
        asked = dropped = 0
        for it in self.items.values():
            r = self.grid.visualItemRect(it)
            has = it.data(R_PM) is not None
            if r.intersects(near):
                if not has:
                    pm = self.thumb.get(it.data(R_PATH), it.data(R_MT), self.px)
                    asked += 1
                    if pm is not None:
                        it.setData(R_PM, pm)
            elif has and not r.intersects(far):
                it.setData(R_PM, None)
                dropped += 1
        if asked or dropped:
            log.debug("폴더 미리보기 그림 요청 %d 놓음 %d (px %d)", asked, dropped, self.px)

    def _on_ready(self, path, px):
        if self.thumb is None:
            return
        if px != self.px:
            return
        it = self.items.get(os.path.normcase(path))
        if it is not None:
            pm = self.thumb.get(path, it.data(R_MT), self.px)
            if pm is not None:
                it.setData(R_PM, pm)

    def _on_count(self, files, dirs, size, state):
        if not self.counter.alive:   # 멈춘 뒤 늦게 도착한 값(다른 것을 고른 뒤)은 버림
            return
        self.last_count = (files, dirs, size, state)
        if self.info_cb is not None and not self.parked:
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
        if self.finder is not None:
            self.finder.stop()
        if self.thumb is not None and self._connected:
            try:
                self.thumb.ready.disconnect(self._on_ready)
            except (RuntimeError, TypeError):
                pass
            self._connected = False
        self.thumb = None

    def hideEvent(self, e):
        if not self.parked:   # 2.3.0: 파일 화면 보는 동안 숨긴 것은 멈추지 않음
            self.stop()
        super().hideEvent(e)
