# -*- coding: utf-8 -*-
"""연번 그림(이미지 시퀀스) 묶기·재생·내보내기 (SEQUENCE_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '연번 그림 묶어 보기·재생·MP4/GIF')

- find_sequences(names) → [Seq]: '앞글자 + 숫자 + 뒷글자.확장자' 가 같은 것끼리 묶음 (3장 이상만). 숫자가 여러 곳이면 마지막 숫자 묶음이 번호
  자리수 맞춤(0001)·안 맞춤(1,2,…10) 둘 다. 같은 이름이 자리수만 다르면(walk_01 / walk_1) 다른 묶음. 1만 장 0.2초 안 (로그에 시간)
- seq_of(path) → 그 파일이 든 묶음 (없으면 None)
- open_player(parent, folder, seq_or_path) → 재생 창: 장면 막대·재생/멈춤·한 장씩(← →)·fps(12/24/30/60)·반복. 빠진 번호 칸은 빨간 '빠짐 0045'
  그림은 뒤 스레드가 미리 읽음 — 메모리 한도(600MB)를 넘으면 지금 장면 앞뒤 일부만 읽어 둠 (쉬는 동안 일 안 함: 조건 변수로 기다림)
- [MP4 만들기] [GIF 만들기]: runtime\\ffmpeg\\ffmpeg.exe 를 QProcess 로 (창 없음, 진행 표시·취소, 창 닫으면 끝냄)
  번호가 이어지면 '%04d' 꼴 입력, 빠진 번호가 있으면 목록 파일(concat). GIF 는 색표(palettegen/paletteuse). 투명 → MP4 는 흰/검정 바탕
  결과는 같은 폴더 '폴더이름_walk.mp4' (있으면 ' (1)'), 원본은 건드리지 않음
- tool_icon(sz) — 필름 띠 + 숫자
로그: bin\\log\\4Dir.log [QE.sequence] (묶기 시간·장수, 읽기 한도·창 크기, ffmpeg 명령·결과)
"""
import os
import re
import time
import shutil
import logging
import tempfile
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

SEQUENCE_VER = "1.0.0"
log = logging.getLogger("QE.sequence")
IMG_EXT = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp", ".gif", ".exr", ".dpx", ".psd", ".jfif"}
MIN_COUNT = 3
MEM_LIMIT = 600 * 1024 * 1024
MAX_SIDE = 2048            # 재생용으로 읽을 때 긴 쪽 최대 (메모리 절약)
MAX_SLOTS = 50000          # 빠진 칸까지 장면으로 넣는 최대 (번호가 너무 듬성듬성하면 있는 장면만)
_RX = re.compile(r"^(.*?)(\d+)(\D*)$")


class Seq:
    """묶음 하나. nums = 번호(정수, 오름차순), names/paths = 같은 차례"""
    __slots__ = ("folder", "prefix", "suffix", "ext", "pad", "nums", "names", "paths", "first", "last",
                 "missing", "missing_count", "display", "_size", "_sizes")

    def __init__(self, folder, prefix, suffix, ext, pad, items, sizes=None):
        items.sort()
        self.folder = folder
        self.prefix, self.suffix, self.ext, self.pad = prefix, suffix, ext, pad
        self.nums = [n for n, _ in items]
        self.names = [nm for _, nm in items]
        self.paths = [os.path.join(folder, nm) if folder else nm for nm in self.names]
        self.first, self.last = self.nums[0], self.nums[-1]
        self.missing_count = (self.last - self.first + 1) - len(self.nums)
        self.missing = []
        if self.missing_count:
            have = set(self.nums)
            lim = 100000
            for k in range(self.first, self.last + 1):
                if k not in have:
                    self.missing.append(k)
                    if len(self.missing) >= lim:
                        break
        self.display = prefix + ("#" * pad if pad else "#") + suffix + ext
        self._sizes = sizes
        self._size = None

    @property
    def count(self):
        return len(self.nums)

    @property
    def contiguous(self):
        return self.missing_count == 0

    @property
    def size(self):
        """합계 크기(바이트) — 처음 물을 때 한 번 셈 (sizes 를 받았으면 그것으로)"""
        if self._size is None:
            tot = 0
            for nm, p in zip(self.names, self.paths):
                s = self._sizes.get(nm) if self._sizes else None
                if s is None:
                    try:
                        s = os.path.getsize(p)
                    except OSError:
                        s = 0
                tot += s
            self._size = tot
        return self._size

    def num_text(self, n):
        return str(n).zfill(self.pad) if self.pad else str(n)

    def name_of(self, n):
        return self.prefix + self.num_text(n) + self.suffix + self.ext

    def base_name(self):
        """'walk_' → 'walk' (내보내기 이름용)"""
        b = self.prefix.rstrip(" _.-#") or self.suffix.strip(" _.-") or "seq"
        return b

    def info_text(self):
        s = T("{0}장 · {1}~{2}").format(self.count, self.num_text(self.first), self.num_text(self.last))
        if self.missing_count:
            shown = ", ".join(str(k) for k in self.missing[:10]) + (", …" if self.missing_count > 10 else "")
            s += " · " + T("빠진 번호 {0}개: {1}").format(self.missing_count, shown)
        return s

    def __repr__(self):
        return f"Seq({self.display!r} {self.count}장 {self.first}~{self.last} 빠짐 {self.missing_count})"


def find_sequences(names, folder=None, sizes=None, exts=IMG_EXT, min_count=MIN_COUNT):
    """파일 이름(또는 경로) 목록 → [Seq] (큰 묶음 먼저). exts=None 이면 모든 확장자.
    sizes = {이름: 바이트} 를 주면 크기 셈에 씀. folder 를 주면 paths = folder\\이름"""
    t0 = time.perf_counter()
    groups = {}
    match = _RX.match
    for nm in names:
        d, base = os.path.split(nm)
        stem, ext = os.path.splitext(base)
        el = ext.lower()
        if exts is not None and el not in exts:
            continue
        m = match(stem)
        if not m:
            continue
        pre, num, suf = m.group(1), m.group(2), m.group(3)
        groups.setdefault((d, pre.lower(), suf.lower(), el), []).append((num, nm, pre, suf, ext))
    out = []
    for (d, _p, _s, _e), lst in groups.items():
        if len(lst) < min_count:
            continue
        padded = {}      # 자리수 → [(번호, 이름)]
        loose = []
        lens_zero = {len(num) for num, *_ in lst if len(num) > 1 and num[0] == "0"}
        for num, nm, pre, suf, ext in lst:
            L = len(num)
            if L in lens_zero:
                padded.setdefault(L, []).append((int(num), nm))
            else:
                loose.append((int(num), nm))
        first = lst[0]
        pre, suf, ext = first[2], first[3], first[4]
        fold = folder if folder is not None else d
        subs = [(L, v) for L, v in padded.items()] + ([(0, loose)] if loose else [])
        for pad, items in subs:
            if len(items) < min_count:
                continue
            seen, uniq = set(), []
            for n, nm in items:
                if n not in seen:
                    seen.add(n)
                    uniq.append((n, os.path.basename(nm) if fold else nm))
            if len(uniq) < min_count:
                continue
            out.append(Seq(fold, pre, suf, ext, pad, uniq, sizes))
    out.sort(key=lambda s: (-s.count, s.display.lower()))
    dt = time.perf_counter() - t0
    log.info("묶기 %d개 이름 → %d묶음 (%.3f초)%s", len(names) if hasattr(names, "__len__") else -1, len(out), dt,
             "" if not out else " 첫 묶음 " + repr(out[0]))
    return out


def scan_folder(folder):
    """폴더 안 연번 묶음 (os.scandir — 크기도 함께)"""
    names, sizes = [], {}
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_file():
                        names.append(e.name)
                        sizes[e.name] = e.stat().st_size
                except OSError:
                    pass
    except OSError:
        log.exception("폴더 읽기 실패 %s", folder)
        return []
    return find_sequences(names, folder=folder, sizes=sizes)


def seq_of(path):
    """파일 하나 → 그 파일이 든 묶음 (없으면 None)"""
    folder, base = os.path.split(os.path.abspath(path))
    for s in scan_folder(folder):
        if base in s.names:
            return s
    return None


def ffmpeg_path():
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime", "ffmpeg", "ffmpeg.exe")
    return p if os.path.isfile(p) else None


def out_name(folder, base, ext):
    stem = os.path.join(folder, base)
    p = stem + ext
    i = 1
    while os.path.exists(p):
        p = f"{stem} ({i}){ext}"
        i += 1
    return p


def export_name(seq, ext):
    fname = os.path.basename(os.path.normpath(seq.folder)) or "seq"
    return out_name(seq.folder, f"{fname}_{seq.base_name()}", ext)


def _q(p):
    """concat 목록 파일용 따옴표"""
    return "'" + p.replace("\\", "/").replace("'", "'\\''") + "'"


def build_args(seq, dst, kind, fps=24, scale=100, bg="white", list_dir=None):
    """ffmpeg 인자. kind='mp4'|'gif'. 번호가 이어지지 않으면 list_dir 에 목록 파일을 만들고 concat 입력.
    돌려줌: (인자 목록, 목록 파일 경로 또는 None)"""
    fps = max(1, min(120, int(fps)))
    args = ["-hide_banner", "-y", "-nostats", "-progress", "pipe:1"]
    lst = None
    if seq.contiguous:
        pat = (seq.prefix.replace("%", "%%") + ("%0{0}d".format(seq.pad) if seq.pad else "%d")
               + seq.suffix.replace("%", "%%") + seq.ext.replace("%", "%%"))
        args += ["-framerate", str(fps), "-start_number", str(seq.first), "-i", os.path.join(seq.folder, pat)]
    else:
        lst = os.path.join(list_dir or tempfile.gettempdir(), "seq_list.txt")
        dur = 1.0 / fps
        lines = ["ffconcat version 1.0"]
        for p in seq.paths:
            lines.append("file " + _q(p))
            lines.append(f"duration {dur:.6f}")
        lines.append("file " + _q(seq.paths[-1]))   # 마지막 장면 시간이 들어가게 한 번 더
        with open(lst, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        args += ["-f", "concat", "-safe", "0", "-i", lst]
    out_n = ["-frames:v", str(seq.count)]    # 마지막 장면을 두 번 적은 만큼 한 장 더 나오지 않게
    pre = []
    sc = max(5, min(400, int(scale)))
    if kind == "mp4":
        pre.append("format=rgba")
        if bg == "white":   # 흰 바탕에 얹기: 색 뒤집기 → 알파 곱하기(검정 바탕) → 다시 뒤집기
            pre += ["lutrgb=r=negval:g=negval:b=negval", "premultiply=inplace=1", "lutrgb=r=negval:g=negval:b=negval"]
        else:
            pre.append("premultiply=inplace=1")
        f = sc / 100.0
        pre.append(f"scale=trunc(iw*{f}/2)*2:trunc(ih*{f}/2)*2:flags=lanczos")
        pre.append("format=yuv420p")
        args += ["-vf", ",".join(pre), "-r", str(fps), "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", "-movflags", "+faststart", "-an"] + out_n + [dst]
    else:
        if sc != 100:
            f = sc / 100.0
            pre.append(f"scale=trunc(iw*{f}):trunc(ih*{f}):flags=lanczos")
        head = ",".join(pre) + "," if pre else ""
        args += ["-filter_complex", f"[0:v]{head}split[a][b];[a]palettegen=reserve_transparent=1:stats_mode=full[p];[b][p]paletteuse=dither=sierra2_4a:alpha_threshold=128",
                 "-r", str(fps), "-loop", "0"] + out_n + [dst]
    return args, lst


# ---------------------------------------------------------------- 그림 미리 읽기 (뒤 스레드)
def _read(path, max_side=MAX_SIDE):
    rd = QtGui.QImageReader(path)
    rd.setAutoTransform(True)
    sz = rd.size()
    if sz.isValid() and max(sz.width(), sz.height()) > max_side:
        rd.setScaledSize(sz.scaled(max_side, max_side, Qt.KeepAspectRatio))
    im = rd.read()
    return im if not im.isNull() else None


class FrameCache:
    """장면 그림 보관. 한도 안이면 전부, 넘으면 지금 장면 앞뒤 win 장만. 뒤 스레드가 가까운 것부터 읽음"""

    def __init__(self, paths, limit=MEM_LIMIT):
        self.paths = paths          # 장면 칸 → 경로 (빠진 칸 None)
        self.limit = limit
        self.imgs = {}
        self.cur = 0
        self.win = len(paths)
        self.cv = threading.Condition()
        self.stop = False
        self.loaded = 0
        self.th = None

    def start(self, frame_bytes):
        n = len(self.paths)
        if frame_bytes * n > self.limit:
            self.win = max(4, int(self.limit / max(1, frame_bytes)) // 2)
        log.info("미리 읽기: 장면 %d칸 · 한 장 %.1fMB · 한도 %dMB → %s", n, frame_bytes / 1048576, self.limit // 1048576,
                 "전부" if self.win >= n else f"앞뒤 {self.win}장씩")
        self.th = threading.Thread(target=self._run, name="seq-cache", daemon=True)
        self.th.start()

    def _want(self, i):
        return abs(i - self.cur) <= self.win if self.win < len(self.paths) else True

    def _next(self):
        n = len(self.paths)
        c = self.cur
        span = min(n, self.win if self.win < n else n)
        for d in range(0, span + 1):
            for i in (c + d, c - d) if d else (c,):
                if self.win >= n:
                    i %= n
                if 0 <= i < n and self.paths[i] and i not in self.imgs:
                    return i
        return None

    def _run(self):
        while True:
            with self.cv:
                while not self.stop:
                    i = self._next()
                    if i is not None:
                        break
                    self.cv.wait()
                if self.stop:
                    return
                path = self.paths[i]
            im = _read(path)
            with self.cv:
                if self.stop:
                    return
                if self._want(i):
                    self.imgs[i] = im
                    self.loaded += 1
                if self.win < len(self.paths):
                    for k in [k for k in self.imgs if not self._want(k)]:
                        del self.imgs[k]

    def set_current(self, i):
        with self.cv:
            self.cur = i
            self.cv.notify()

    def get(self, i):
        with self.cv:
            if i in self.imgs:
                return self.imgs[i]
        p = self.paths[i]
        if not p:
            return None
        im = _read(p)        # 아직 못 읽었으면 바로 읽음 (한 장)
        with self.cv:
            if self._want(i):
                self.imgs[i] = im
        return im

    def close(self):
        with self.cv:
            self.stop = True
            self.cv.notify_all()
        if self.th:
            self.th.join(2)
        self.imgs.clear()


# ---------------------------------------------------------------- 화면
class _View(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.img = None
        self.miss = None
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._chk = None

    def set_frame(self, img, miss_text=None):
        self.img, self.miss = img, miss_text
        self.update()

    def _checker(self):
        if self._chk is None:
            pm = QtGui.QPixmap(16, 16)
            pm.fill(QtGui.QColor("#ffffff"))
            p = QtGui.QPainter(pm)
            p.fillRect(0, 0, 8, 8, QtGui.QColor("#d9d9d9"))
            p.fillRect(8, 8, 8, 8, QtGui.QColor("#d9d9d9"))
            p.end()
            self._chk = pm
        return self._chk

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        r = self.rect()
        p.fillRect(r, self.palette().color(QtGui.QPalette.Window).darker(115))
        if self.miss is not None:
            p.fillRect(r.adjusted(8, 8, -8, -8), QtGui.QColor("#b91c1c"))
            f = p.font()
            f.setPixelSize(max(16, min(r.width(), r.height()) // 8))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(r, Qt.AlignCenter, self.miss)
        elif self.img is not None and not self.img.isNull():
            s = self.img.size().scaled(r.size(), Qt.KeepAspectRatio)
            if s.width() > self.img.width() * 4:
                s = self.img.size() * 4
            tr = QtCore.QRect(QtCore.QPoint(0, 0), s)
            tr.moveCenter(r.center())
            p.drawTiledPixmap(tr, self._checker())
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, s.width() < self.img.width())
            p.drawImage(tr, self.img)
        else:
            p.setPen(self.palette().color(QtGui.QPalette.WindowText))
            p.drawText(r, Qt.AlignCenter, T("그림을 읽지 못했습니다"))
        p.end()


class Player(QtWidgets.QWidget):
    def __init__(self, seq, parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.seq = seq
        self.proc = None
        self.tmp = None
        self.dst = None
        self._cancelled = False
        self.setWindowTitle(T("연번 그림 재생") + " — " + seq.display)
        self.setWindowIcon(tool_icon(16))
        span = seq.last - seq.first + 1
        if span <= MAX_SLOTS:   # 빠진 칸까지 장면으로
            have = dict(zip(seq.nums, seq.paths))
            self.slot_num = list(range(seq.first, seq.last + 1))
            slot_path = [have.get(n) for n in self.slot_num]
        else:
            self.slot_num = list(seq.nums)
            slot_path = list(seq.paths)
        log.info("재생 창 %s 장면 %d칸 (%s)", seq.display, len(self.slot_num), seq.folder)
        self.cache = FrameCache(slot_path)
        first = _read(seq.paths[0])
        fb = (first.width() * first.height() * 4) if first is not None else 1024 * 1024 * 4
        self.cache.imgs[slot_path.index(seq.paths[0])] = first
        self.cache.start(fb)
        self.idx = 0
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)

        lay = QtWidgets.QVBoxLayout(self)
        self.info = QtWidgets.QLabel(seq.info_text())
        self.info.setWordWrap(True)
        f = self.info.font()
        f.setBold(True)
        self.info.setFont(f)
        lay.addWidget(self.info)
        sub = QtWidgets.QLabel(f"{seq.display} · {seq.size / 1048576:.1f}MB · {seq.folder}")
        sub.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sub.setWordWrap(True)
        lay.addWidget(sub)
        self.view = _View()
        lay.addWidget(self.view, 1)
        row = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(Qt.Horizontal)
        self.slider.setRange(0, len(self.slot_num) - 1)
        self.slider.valueChanged.connect(self.go)
        self.pos_lbl = QtWidgets.QLabel()
        self.pos_lbl.setMinimumWidth(130)
        row.addWidget(self.slider, 1)
        row.addWidget(self.pos_lbl)
        lay.addLayout(row)

        ctl = QtWidgets.QHBoxLayout()
        self.b_prev = QtWidgets.QPushButton("◀")
        self.b_prev.setToolTip(T("한 장 앞 (←)"))
        self.b_play = QtWidgets.QPushButton(T("▶ 재생"))
        self.b_next = QtWidgets.QPushButton("▶")
        self.b_next.setToolTip(T("한 장 뒤 (→)"))
        for b in (self.b_prev, self.b_play, self.b_next):
            b.setFocusPolicy(Qt.NoFocus)
            ctl.addWidget(b)
        self.b_prev.clicked.connect(lambda: self.step(-1))
        self.b_next.clicked.connect(lambda: self.step(1))
        self.b_play.clicked.connect(self.toggle_play)
        self.loop = QtWidgets.QCheckBox(T("반복"))
        self.loop.setChecked(True)
        self.loop.setFocusPolicy(Qt.NoFocus)
        ctl.addWidget(self.loop)
        ctl.addSpacing(12)
        ctl.addWidget(QtWidgets.QLabel("fps"))
        self.fps = QtWidgets.QSpinBox()
        self.fps.setRange(1, 120)
        self.fps.setValue(24)
        self.fps.valueChanged.connect(self._fps_changed)
        ctl.addWidget(self.fps)
        for v in (12, 24, 30, 60):
            b = QtWidgets.QToolButton()
            b.setText(str(v))
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, v=v: self.fps.setValue(v))
            ctl.addWidget(b)
        ctl.addStretch(1)
        lay.addLayout(ctl)

        ex = QtWidgets.QHBoxLayout()
        ex.addWidget(QtWidgets.QLabel(T("크기")))
        self.scale = QtWidgets.QSpinBox()
        self.scale.setRange(5, 400)
        self.scale.setValue(100)
        self.scale.setSuffix(" %")
        ex.addWidget(self.scale)
        ex.addWidget(QtWidgets.QLabel(T("MP4 바탕")))
        self.bg = QtWidgets.QComboBox()
        self.bg.addItem(T("흰색"), "white")
        self.bg.addItem(T("검정"), "black")
        self.bg.setToolTip(T("투명한 곳을 채울 색 (MP4 는 투명을 못 담음)"))
        ex.addWidget(self.bg)
        self.b_mp4 = QtWidgets.QPushButton(T("MP4 만들기"))
        self.b_gif = QtWidgets.QPushButton(T("GIF 만들기"))
        self.b_mp4.clicked.connect(lambda: self.export("mp4"))
        self.b_gif.clicked.connect(lambda: self.export("gif"))
        self.ff = ffmpeg_path()
        for b in (self.b_mp4, self.b_gif):
            b.setFocusPolicy(Qt.NoFocus)
            b.setEnabled(bool(self.ff))
            ex.addWidget(b)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        ex.addWidget(self.bar, 1)
        self.b_cancel = QtWidgets.QPushButton(T("취소"))
        self.b_cancel.setVisible(False)
        self.b_cancel.clicked.connect(self.cancel)
        ex.addWidget(self.b_cancel)
        if not self.ff:
            ex.addWidget(QtWidgets.QLabel(T("⚠ ffmpeg 가 없어 내보낼 수 없습니다")))
        else:
            ex.addStretch(0)
        lay.addLayout(ex)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)
        self.resize(900, 700)
        self.go(0)

    # ---- 재생
    def go(self, i):
        n = len(self.slot_num)
        i = max(0, min(n - 1, int(i)))
        self.idx = i
        if self.slider.value() != i:
            self.slider.blockSignals(True)
            self.slider.setValue(i)
            self.slider.blockSignals(False)
        num = self.slot_num[i]
        path = self.cache.paths[i]
        self.cache.set_current(i)
        if path is None:
            self.view.set_frame(None, T("빠짐 {0}").format(self.seq.num_text(num)))
        else:
            self.view.set_frame(self.cache.get(i))
        self.pos_lbl.setText(f"{self.seq.num_text(num)}  ({i + 1}/{n})")

    def step(self, d):
        n = len(self.slot_num)
        i = self.idx + d
        if self.loop.isChecked():
            i %= n
        self.go(i)

    def toggle_play(self):
        if self.timer.isActive():
            self.timer.stop()
            self.b_play.setText(T("▶ 재생"))
        else:
            if self.idx >= len(self.slot_num) - 1 and not self.loop.isChecked():
                self.go(0)
            self.timer.start(max(1, int(round(1000 / self.fps.value()))))
            self.b_play.setText(T("❚❚ 멈춤"))

    def _fps_changed(self, v):
        if self.timer.isActive():
            self.timer.setInterval(max(1, int(round(1000 / v))))

    def _tick(self):
        if self.idx >= len(self.slot_num) - 1 and not self.loop.isChecked():
            self.toggle_play()
            return
        self.step(1)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Left:
            self.step(-1)
        elif k == Qt.Key_Right:
            self.step(1)
        elif k == Qt.Key_Space:
            self.toggle_play()
        elif k == Qt.Key_Home:
            self.go(0)
        elif k == Qt.Key_End:
            self.go(len(self.slot_num) - 1)
        elif k == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    # ---- 내보내기
    def export(self, kind):
        if not self.ff or self.proc is not None:
            return
        ext = ".mp4" if kind == "mp4" else ".gif"
        self.dst = export_name(self.seq, ext)
        self.tmp = tempfile.mkdtemp(prefix="4dir_seq_")
        args, _lst = build_args(self.seq, self.dst, kind, self.fps.value(), self.scale.value(), self.bg.currentData(), self.tmp)
        log.info("ffmpeg %s", " ".join(args))
        self.total = self.seq.count
        self.proc = QtCore.QProcess(self)
        self.proc.setProgram(self.ff)
        self.proc.setArguments(args)
        self.proc.setProcessChannelMode(QtCore.QProcess.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._progress)
        self.proc.readyReadStandardError.connect(self._stderr)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(lambda e: log.error("ffmpeg 실행 오류 %s", e))
        self._err = b""
        self._cancelled = False
        self.t0 = time.time()
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.b_cancel.setVisible(True)
        self.b_mp4.setEnabled(False)
        self.b_gif.setEnabled(False)
        self.status.setText(T("만드는 중… {0}").format(os.path.basename(self.dst)))
        self.proc.start()

    def _stderr(self):
        if self.proc is not None:
            self._err = (self._err + bytes(self.proc.readAllStandardError()))[-6000:]

    def _progress(self):
        if self.proc is None:
            return
        out = bytes(self.proc.readAllStandardOutput()).decode("ascii", "replace")
        for m in re.finditer(r"frame=(\d+)", out):
            self.bar.setValue(min(1000, int(int(m.group(1)) / max(1, self.total) * 1000)))

    def _finished(self, code, _st):
        sec = time.time() - self.t0
        ok = code == 0 and not self._cancelled and os.path.isfile(self.dst) and os.path.getsize(self.dst) > 0
        err = self._err.decode("utf-8", "replace").strip().splitlines()[-6:]
        log.info("ffmpeg 끝 코드 %s %.1f초 → %s %s", code, sec, self.dst, "" if ok else " / ".join(err))
        self.proc = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None
        self.bar.setVisible(False)
        self.b_cancel.setVisible(False)
        self.b_mp4.setEnabled(True)
        self.b_gif.setEnabled(True)
        if ok:
            self.status.setText(T("만들었습니다: {0} ({1:.1f}MB, {2:.1f}초)").format(self.dst, os.path.getsize(self.dst) / 1048576, sec))
        else:
            if self._cancelled and os.path.isfile(self.dst):
                try:
                    os.remove(self.dst)   # 취소로 덜 만든 파일
                except OSError:
                    pass
            self.status.setText(T("취소했습니다") if self._cancelled else T("⚠ 만들지 못했습니다") + ("\n" + "\n".join(err) if err else ""))
        self.last_ok = ok

    def cancel(self):
        if self.proc is not None:
            self._cancelled = True
            self.proc.kill()

    def closeEvent(self, e):
        self.timer.stop()
        if self.proc is not None:
            self._cancelled = True
            self.proc.kill()
            self.proc.waitForFinished(3000)
        self.cache.close()
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None
        log.info("재생 창 닫음 %s", self.seq.display)
        super().closeEvent(e)


def open_player(parent, folder, seq_or_path):
    """재생 창을 띄워 돌려줌. seq_or_path = Seq 또는 묶음 안 파일 하나(경로·이름). 묶음이 아니면 None"""
    seq = seq_or_path
    if not isinstance(seq, Seq):
        p = seq_or_path if os.path.isabs(str(seq_or_path)) or not folder else os.path.join(folder, seq_or_path)
        seq = seq_of(p)
        if seq is None:
            log.info("연번 묶음이 아님: %s", p)
            return None
    w = Player(seq, parent)
    w.show()
    return w


# ---------------------------------------------------------------- 아이콘
def tool_icon(sz=16):
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
    p.scale(sz * dpr / 20.0, sz * dpr / 20.0)
    R = QtCore.QRectF
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#334155"))     # 필름 띠
    p.drawRoundedRect(R(0.5, 4, 19, 12), 1.5, 1.5)
    p.setBrush(QtGui.QColor("#ffffff"))
    for k in range(5):
        p.drawRect(R(1.8 + k * 3.8, 4.9, 1.6, 1.3))
        p.drawRect(R(1.8 + k * 3.8, 13.8, 1.6, 1.3))
    cols = ("#38bdf8", "#fbbf24", "#f87171")
    for k in range(3):
        p.setBrush(QtGui.QColor(cols[k]))
        p.drawRect(R(1.6 + k * 6, 7, 5, 6))
    f = p.font()
    f.setPixelSize(5)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QtGui.QColor("#0f172a"))
    for k in range(3):
        p.drawText(R(1.6 + k * 6, 7, 5, 6), Qt.AlignCenter, str(k + 1))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)
