# -*- coding: utf-8 -*-
"""동영상·GIF 편집 (MEDIAEDIT_VER 1.0.0, 0.9.111 — 사용자 11/6 '미리보기에서 동영상·GIF 편집')

- 미리보기 조작줄 [✂ 편집] · 우클릭 ▸ 4Dir 도구 ▸ 동영상·GIF 편집… → 따로 창
- 구간: 장면 막대로 옮기고 [시작 I] [끝 O] — 그 사이만 저장
- 화면 자르기: 그림 위를 끌어 영역 (다시 끌면 바꿈, [영역 지우기])
- 크기(%) · 속도(0.25~4배) · GIF fps · 소리 빼기(동영상)
- 저장: MP4(H.264, 장면 정확) / GIF(색표 만들어 화질 유지) / '빠르게 자르기'(MP4·같은 형식, 다시 압축 안 함 — 키프레임 단위라 앞뒤가 조금 다를 수 있음)
- GIF 장면 편집: 장면 띠에서 고른 장면 지우기(Del) · 앞/뒤로 옮기기 · 장면 시간(ms) 바꾸기 → 저장 때 반영
- 원본은 절대 바꾸지 않음 — 같은 폴더에 '이름_edit.mp4/.gif' (있으면 '(1)')
- 실제 변환은 ffmpeg (runtime\\ffmpeg\\ffmpeg.exe, _build\\get_ffmpeg.py 로 받음) 를 QProcess 로 — 화면이 멈추지 않음, 취소 가능
로그: bin\\log\\4Dir.log [QE.edit] (ffmpeg 명령·결과·끝 부분 출력)
"""
import os
import re
import time
import shutil
import logging
import tempfile

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

MEDIAEDIT_VER = "1.2.0"   # 1.2.0: 저장 크고 파랗게·선택 영역 해제 작게·바꾸기 칸 촘촘 / 1.1.0: 구간 막대(손잡이·누른 자리·시각 표시)·재생·구간 반복·시작/끝 한 장면씩
log = logging.getLogger("QE.edit")
GIF_MAX_FRAMES = 2000
SPEEDS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]


def ffmpeg_path(root=None):
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(root, "runtime", "ffmpeg", "ffmpeg.exe")
    return p if os.path.isfile(p) else None


def can_edit(path):
    import video
    return bool(path) and (path.lower().endswith(".gif") or video.is_video(path)) and os.path.isfile(path)


def out_name(src, ext):
    base = os.path.splitext(src)[0] + "_edit"
    p = base + ext
    i = 1
    while os.path.exists(p):
        p = f"{base} ({i}){ext}"
        i += 1
    return p


def atempo(speed):
    """소리 속도 — atempo 는 한 번에 0.5~2 배 → 이어 붙임"""
    out, s = [], speed
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    out.append(f"atempo={s:.6f}")
    return ",".join(out)


def video_filters(crop, scale_pct, speed, even=True):
    """영상 필터 글자 (crop = (x,y,w,h) 원본 화소 · scale_pct 10~100 · speed)"""
    f = []
    if crop:
        x, y, w, h = crop
        if even:
            w, h = w // 2 * 2, h // 2 * 2
        f.append(f"crop={max(2, w)}:{max(2, h)}:{x}:{y}")
    if scale_pct and scale_pct != 100:
        f.append(f"scale=trunc(iw*{scale_pct / 100:.4f}/2)*2:-2:flags=lanczos" if even else f"scale=trunc(iw*{scale_pct / 100:.4f}):-1:flags=lanczos")
    elif even:
        f.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    if speed and abs(speed - 1.0) > 1e-6:
        f.append(f"setpts=PTS/{speed:.6f}")
    return f


def gif_palette_chain(pre):
    """GIF 화질: 색표 만들고 쓰기 (pre = 앞 필터들)"""
    head = ",".join(pre) + "," if pre else ""
    return f"[0:v]{head}split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a"


def build_args(src, dst, kind, opt, concat=None):
    """ffmpeg 인자. kind = 'video'|'gif' (원본) · opt = {a_s, b_s, crop, scale, speed, fps, mute, fast}
    concat = GIF 장면 편집 목록 파일 (있으면 그 장면들을 입력으로)"""
    ext = os.path.splitext(dst)[1].lower()
    args = ["-hide_banner", "-y", "-nostats", "-progress", "pipe:1"]
    if concat:
        args += ["-f", "concat", "-safe", "0", "-i", concat]
    else:
        if opt.get("a_s") is not None:
            args += ["-ss", f"{opt['a_s']:.3f}"]
        if opt.get("b_s") is not None:
            args += ["-to", f"{opt['b_s']:.3f}"]
        args += ["-i", src]
    if opt.get("fast") and not concat:
        return args + ["-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-avoid_negative_ts", "make_zero", dst]
    speed = 1.0 if concat else opt.get("speed", 1.0)   # GIF 장면 목록은 장면 시간으로 이미 속도 반영
    if ext == ".gif":
        pre = video_filters(opt.get("crop"), opt.get("scale", 100), speed, even=False)
        if opt.get("fps") and not concat:   # GIF 장면 목록은 장면별 시간 그대로 (fps 로 바꾸면 사라짐)
            pre.append(f"fps={opt['fps']}")
        args += ["-filter_complex", gif_palette_chain(pre), "-loop", "0"]
        if concat:
            args += ["-fps_mode", "vfr"]
        return args + [dst]
    vf = video_filters(opt.get("crop"), opt.get("scale", 100), speed, even=True)
    if concat or kind == "gif":
        vf.append(f"fps={opt.get('fps') or 30}")
    args += ["-vf", ",".join(vf)] if vf else []
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if kind == "video" and not concat and not opt.get("mute"):
        if abs(speed - 1.0) > 1e-6:
            args += ["-af", atempo(speed)]
        args += ["-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-an"]
    return args + [dst]


def gif_set_delays(path, delays_cs):
    """GIF 파일 안 장면별 시간(1/100초)을 차례로 고쳐 씀 — ffmpeg 가 장면별 시간을 정확히 못 옮겨서 (실측 520/80 번갈아)
    → 바꾼 장면 수 (GIF 구조: 머리 · 색표 · [확장 0x21 | 그림 0x2C]… · 0x3B)"""
    b = bytearray(open(path, "rb").read())
    if b[:3] != b"GIF":
        return 0
    pos = 13
    if b[10] & 0x80:
        pos += 3 * (2 ** ((b[10] & 7) + 1))
    k = 0
    while pos < len(b):
        t = b[pos]
        if t == 0x3B:
            break
        if t == 0x21:
            label = b[pos + 1]
            if label == 0xF9 and b[pos + 2] == 4 and k < len(delays_cs):
                d = max(2, min(65535, int(delays_cs[k])))
                b[pos + 4], b[pos + 5] = d & 0xFF, d >> 8
                k += 1
            pos += 2
            while pos < len(b) and b[pos]:
                pos += b[pos] + 1
            pos += 1
        elif t == 0x2C:
            flags = b[pos + 9]
            pos += 10
            if flags & 0x80:
                pos += 3 * (2 ** ((flags & 7) + 1))
            pos += 1   # LZW 최소 코드 크기
            while pos < len(b) and b[pos]:
                pos += b[pos] + 1
            pos += 1
        else:
            break
    open(path, "wb").write(b)
    return k


def load_gif(path, limit=GIF_MAX_FRAMES):
    """GIF → [(QImage, 지연 ms)]"""
    rd = QtGui.QImageReader(path)
    rd.setDecideFormatFromContent(True)
    out = []
    while len(out) < limit:
        im = rd.read()
        if im.isNull():
            break
        d = rd.nextImageDelay()
        out.append((im.convertToFormat(QtGui.QImage.Format_ARGB32), d if d > 0 else 100))
        if not rd.canRead():
            break
    return out


class Canvas(QtWidgets.QWidget):
    """그림 보기 + 끌어서 자르기 영역 (원본 화소 좌표)"""
    cropChanged = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.img = QtGui.QImage()
        self.crop = None
        self._drag = None
        self.setMinimumSize(320, 200)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip(T("끌어서 자를 영역을 고르세요"))

    def set_image(self, im):
        self.img = im
        self.update()

    def _geom(self):
        if self.img.isNull():
            return QtCore.QRectF(), 1.0
        s = min(self.width() / self.img.width(), self.height() / self.img.height())
        w, h = self.img.width() * s, self.img.height() * s
        return QtCore.QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), s

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(40, 40, 40))
        r, s = self._geom()
        if not self.img.isNull():
            p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
            p.drawImage(r, self.img)
        cr = self._crop_view(r, s)
        if cr is not None:
            dim = QtGui.QColor(0, 0, 0, 140)
            full = QtGui.QPainterPath()
            full.addRect(r)
            hole = QtGui.QPainterPath()
            hole.addRect(cr)
            p.fillPath(full.subtracted(hole), dim)
            p.setPen(QtGui.QPen(QtGui.QColor("#ffcc00"), 2, Qt.DashLine))
            p.drawRect(cr)
        p.end()

    def _crop_view(self, r, s):
        src = self._drag_rect() if self._drag else self.crop
        if not src:
            return None
        x, y, w, h = src
        return QtCore.QRectF(r.x() + x * s, r.y() + y * s, w * s, h * s)

    def _to_img(self, pt):
        r, s = self._geom()
        if s <= 0 or self.img.isNull():
            return None
        x = min(max(0.0, (pt.x() - r.x()) / s), self.img.width())
        y = min(max(0.0, (pt.y() - r.y()) / s), self.img.height())
        return x, y

    def _drag_rect(self):
        (x0, y0), (x1, y1) = self._drag
        x, y = int(min(x0, x1)), int(min(y0, y1))
        return x, y, int(abs(x1 - x0)), int(abs(y1 - y0))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self.img.isNull():
            a = self._to_img(ev.position())
            self._drag = (a, a)

    def mouseMoveEvent(self, ev):
        if self._drag:
            self._drag = (self._drag[0], self._to_img(ev.position()))
            self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag:
            r = self._drag_rect()
            self._drag = None
            self.crop = r if r[2] >= 8 and r[3] >= 8 else None
            self.update()
            self.cropChanged.emit(self.crop)


def tcode(sec):
    """00:00:17.07 (시:분:초.1/100)"""
    sec = max(0.0, sec)
    h, r = divmod(sec, 3600)
    m, s_ = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s_:05.2f}"


class RangeSlider(QtWidgets.QWidget):
    """구간 막대 (1.1.0, 사용자 11/6 그림): 어두운 줄 · 시작~끝 파란 구간 · 양 끝 손잡이(끌기) · 주황 재생 위치(위에 시각)
    누른 자리로 바로 감(한 칸씩 아님). QSlider 와 같은 이름: value · setValue · setRange · maximum · valueChanged"""
    valueChanged = QtCore.Signal(int)
    rangeChanged = QtCore.Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._min, self._max, self._v = 0, 0, 0
        self.a, self.b = 0, 0
        self._drag = None
        self.time_of = lambda n: 0.0
        self.setMinimumHeight(54)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---- QSlider 흉내
    def value(self):
        return self._v

    def maximum(self):
        return self._max

    def minimum(self):
        return self._min

    def setRange(self, lo, hi):
        self._min, self._max = lo, max(lo, hi)
        self._v = min(max(self._v, lo), self._max)
        self.a = min(max(self.a, lo), self._max)
        self.b = min(max(self.b, self.a), self._max)
        self.update()

    def setValue(self, v, emit=True):
        v = min(max(int(v), self._min), self._max)
        if v != self._v:
            self._v = v
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def setInOut(self, a, b):
        self.a, self.b = min(a, b), max(a, b)
        self.update()

    # ---- 그리기
    M = 14   # 좌우 여백 (손잡이 반)

    def _x(self, n):
        w = self.width() - 2 * self.M
        span = max(1, self._max - self._min)
        return self.M + (n - self._min) / span * w

    def _n(self, x):
        w = max(1, self.width() - 2 * self.M)
        return int(round((x - self.M) / w * (self._max - self._min))) + self._min

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        H = self.height()
        ty = H - 22   # 줄 가운데
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#2b2f36"))
        p.drawRoundedRect(QtCore.QRectF(self.M, ty - 4, self.width() - 2 * self.M, 8), 3, 3)
        xa, xb = self._x(self.a), self._x(self.b + 1 if self.b < self._max else self.b)
        p.setBrush(QtGui.QColor("#4a90e2"))
        p.drawRect(QtCore.QRectF(xa, ty - 4, max(2.0, xb - xa), 8))
        for x, left in ((xa, True), (xb, False)):   # 손잡이
            r = QtCore.QRectF(x - 7 if left else x - 7, ty - 9, 14, 18)
            p.setBrush(QtGui.QColor("#dfe6ee"))
            p.setPen(QtGui.QPen(QtGui.QColor("#7a8796"), 1))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QtGui.QPen(QtGui.QColor("#2a6fc9"), 1.6))
            cx, cy = r.center().x(), r.center().y()
            if left:
                p.drawPolyline([QtCore.QPointF(cx - 2, cy - 4), QtCore.QPointF(cx + 2, cy), QtCore.QPointF(cx - 2, cy + 4)])
            else:
                p.drawPolyline([QtCore.QPointF(cx + 2, cy - 4), QtCore.QPointF(cx - 2, cy), QtCore.QPointF(cx + 2, cy + 4)])
        xv = self._x(self._v)   # 재생 위치 (주황) + 위에 시각
        p.setPen(QtGui.QPen(QtGui.QColor("#ff9800"), 2))
        p.drawLine(QtCore.QPointF(xv, ty - 10), QtCore.QPointF(xv, ty + 10))
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#ff9800"))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(xv - 6, ty - 16), QtCore.QPointF(xv + 6, ty - 16), QtCore.QPointF(xv, ty - 9)]))
        txt = f"{tcode(self.time_of(self._v))}  ·  {self._v + 1}"
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(txt) + 10
        tx = min(max(0.0, xv - tw / 2), self.width() - tw)
        p.setBrush(QtGui.QColor(255, 152, 0, 55))
        p.drawRoundedRect(QtCore.QRectF(tx, 0, tw, fm.height() + 2), 3, 3)
        p.setPen(QtGui.QColor("#ffd08a"))   # 어두운 조작줄 위라 밝은 주황 글자
        p.drawText(QtCore.QRectF(tx, 0, tw, fm.height() + 2), Qt.AlignCenter, txt)
        p.end()

    # ---- 마우스: 손잡이 끌기 · 누른 자리로 바로
    def _hit(self, x):
        xa, xb = self._x(self.a), self._x(self.b + 1 if self.b < self._max else self.b)
        if abs(x - xa) <= 8:
            return "a"
        if abs(x - xb) <= 8:
            return "b"
        return "v"

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        x = ev.position().x()
        self._drag = self._hit(x)
        self._apply(x)

    def mouseMoveEvent(self, ev):
        if self._drag:
            self._apply(ev.position().x())
        else:
            h = self._hit(ev.position().x())
            self.setCursor(Qt.SizeHorCursor if h in ("a", "b") else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, ev):
        self._drag = None

    def _apply(self, x):
        n = min(max(self._n(x), self._min), self._max)
        if self._drag == "a":
            self.a = min(n, self.b)
            self.rangeChanged.emit(self.a, self.b)
            self.setValue(self.a)
        elif self._drag == "b":
            nb = max(self.a, (n - 1) if n > self.a else n)
            self.b = min(nb, self._max)
            self.rangeChanged.emit(self.a, self.b)
            self.setValue(self.b)
        else:
            self.setValue(n)
        self.update()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Left, Qt.Key_Right):
            self.setValue(self._v + (1 if ev.key() == Qt.Key_Right else -1))
            return
        super().keyPressEvent(ev)


class EditDialog(QtWidgets.QDialog):
    def __init__(self, path, start=0, done_cb=None, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.path = path
        self.done_cb = done_cb
        self.kind = "gif" if path.lower().endswith(".gif") else "video"
        self.ff = ffmpeg_path()
        self.proc = None
        self.tmp = None
        self.mv = None
        self.frames = []       # GIF: [[QImage, 지연 ms]] (장면 편집 결과)
        self.a = 0
        self.b = 0
        self.setWindowTitle(T("편집") + f" — {os.path.basename(path)}")
        self.resize(1000, 760)
        lay = QtWidgets.QVBoxLayout(self)
        self.canvas = Canvas()
        lay.addWidget(self.canvas, 1)
        # 1.1.0 (사용자 11/6 그림): 조작줄 = 지금/전체 시각 · 장면 이동·재생 / 구간 막대 / 구간 길이 · [ ] · 시작~끝 시각 · 구간 재생
        ctl = QtWidgets.QWidget()
        ctl.setObjectName("editCtl")
        ctl.setStyleSheet("#editCtl{background:#323844; border-radius:4px;} #editCtl QLabel{color:#dfe6ee;}"
                          " #editCtl QToolButton{color:#dfe6ee; border:none; padding:2px 6px; font-size:13pt;}"
                          " #editCtl QToolButton:hover{background:#465062;} #editCtl QToolButton:checked{background:#2a6fc9;}")
        cv = QtWidgets.QVBoxLayout(ctl)
        cv.setContentsMargins(10, 6, 10, 6)
        top = QtWidgets.QHBoxLayout()
        self.pos_lbl = QtWidgets.QLabel()
        top.addWidget(self.pos_lbl)
        top.addStretch(1)

        def tb(t, tip, fn, chk=False):
            b = QtWidgets.QToolButton()
            b.setText(t)
            b.setToolTip(tip)
            b.setCheckable(chk)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            top.addWidget(b)
            return b
        self.b_first = tb("|◀◀", T("구간 처음으로"), lambda: self.slider.setValue(self.a))
        self.b_prev = tb("◀|", T("한 장면 앞 (←)"), lambda: self.slider.setValue(self.slider.value() - 1))
        self.b_play = tb("▶", T("재생/멈춤 (스페이스)"), lambda: self.toggle_play())
        self.b_next = tb("|▶", T("한 장면 뒤 (→)"), lambda: self.slider.setValue(self.slider.value() + 1))
        self.b_last = tb("▶▶|", T("구간 끝으로"), lambda: self.slider.setValue(self.b))
        top.addStretch(1)
        self.loop = QtWidgets.QCheckBox(T("구간만 반복"))
        self.loop.setChecked(True)
        self.loop.setStyleSheet("color:#dfe6ee;")
        top.addWidget(self.loop)
        cv.addLayout(top)
        self.slider = RangeSlider()
        self.slider.time_of = lambda n: self.t_of(n)
        cv.addWidget(self.slider)
        mid = QtWidgets.QHBoxLayout()
        mid.addStretch(1)
        self.range_lbl = QtWidgets.QLabel()
        mid.addWidget(self.range_lbl)
        mid.addStretch(1)
        cv.addLayout(mid)
        bot = QtWidgets.QHBoxLayout()
        bot.addStretch(1)
        self.b_in = QtWidgets.QToolButton()
        self.b_in.setText("[")
        self.b_in.setToolTip(T("지금 위치를 시작으로 (I)"))
        self.b_out = QtWidgets.QToolButton()
        self.b_out.setText("]")
        self.b_out.setToolTip(T("지금 위치를 끝으로 (O)"))
        self.b_all = QtWidgets.QToolButton()
        self.b_all.setText("[ ]")
        self.b_all.setToolTip(T("처음~끝 전부"))
        for b_ in (self.b_in, self.b_out, self.b_all):
            b_.setFocusPolicy(Qt.NoFocus)
            bot.addWidget(b_)
        bot.addSpacing(12)

        def stepper(fn_dn, fn_up):
            w = QtWidgets.QWidget()
            l_ = QtWidgets.QVBoxLayout(w)
            l_.setContentsMargins(0, 0, 0, 0)
            l_.setSpacing(0)
            for t, fn in (("▴", fn_up), ("▾", fn_dn)):
                b_ = QtWidgets.QToolButton()
                b_.setText(t)
                b_.setFixedSize(18, 12)
                b_.setStyleSheet("font-size:8pt; padding:0;")
                b_.setFocusPolicy(Qt.NoFocus)
                b_.setAutoRepeat(True)
                b_.clicked.connect(fn)
                l_.addWidget(b_)
            return w
        bot.addWidget(stepper(lambda: self._nudge("a", -1), lambda: self._nudge("a", +1)))
        self.a_lbl = QtWidgets.QLabel()
        self.a_lbl.setToolTip(T("시작 — 옆 ▴▾ 로 한 장면씩"))
        bot.addWidget(self.a_lbl)
        bot.addWidget(QtWidgets.QLabel("~"))
        self.b_lbl = QtWidgets.QLabel()
        self.b_lbl.setToolTip(T("끝 — 옆 ▴▾ 로 한 장면씩"))
        bot.addWidget(self.b_lbl)
        bot.addWidget(stepper(lambda: self._nudge("b", -1), lambda: self._nudge("b", +1)))
        bot.addSpacing(12)
        self.b_playrange = QtWidgets.QToolButton()
        self.b_playrange.setText("[▶]")
        self.b_playrange.setToolTip(T("구간 처음부터 재생"))
        self.b_playrange.setFocusPolicy(Qt.NoFocus)
        self.b_playrange.clicked.connect(lambda: (self.slider.setValue(self.a), self.toggle_play(True)))
        bot.addWidget(self.b_playrange)
        bot.addStretch(1)
        cv.addLayout(bot)
        lay.addWidget(ctl)
        self.playing = False
        self._gif_timer = QtCore.QTimer(self)
        self._gif_timer.setSingleShot(True)
        self._gif_timer.timeout.connect(self._gif_tick)
        # GIF 장면 띠
        self.strip = QtWidgets.QListWidget()
        self.strip.setViewMode(QtWidgets.QListView.IconMode)
        self.strip.setFlow(QtWidgets.QListView.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setIconSize(QtCore.QSize(72, 54))
        self.strip.setFixedHeight(110)
        self.strip.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.strip.setMovement(QtWidgets.QListView.Static)
        srow = QtWidgets.QHBoxLayout()
        self.b_del = QtWidgets.QPushButton(T("고른 장면 지우기 (Del)"))
        self.b_left = QtWidgets.QPushButton(T("◀ 앞으로"))
        self.b_right = QtWidgets.QPushButton(T("뒤로 ▶"))
        self.delay = QtWidgets.QSpinBox()
        self.delay.setRange(10, 10000)
        self.delay.setSuffix(" ms")
        self.b_delay = QtWidgets.QPushButton(T("고른 장면 시간 바꾸기"))
        for w_ in (self.b_del, self.b_left, self.b_right, QtWidgets.QLabel(T("장면 시간")), self.delay, self.b_delay):
            srow.addWidget(w_)
        srow.addStretch(1)
        self.gif_box = QtWidgets.QWidget()
        gv = QtWidgets.QVBoxLayout(self.gif_box)
        gv.setContentsMargins(0, 0, 0, 0)
        gv.addWidget(self.strip)
        gv.addLayout(srow)
        lay.addWidget(self.gif_box)
        # 바꾸기 — 1.2.0 (사용자 11/6 '간격이 너무 멀다'): 한 줄씩 촘촘하게, 넓으면 오른쪽은 빈칸
        g = QtWidgets.QGroupBox(T("바꾸기"))
        gv2 = QtWidgets.QVBoxLayout(g)
        gv2.setContentsMargins(10, 6, 10, 6)
        gv2.setSpacing(4)
        r1 = QtWidgets.QHBoxLayout()
        r1.setSpacing(8)
        self.crop_lbl = QtWidgets.QLabel(T("자르기: 없음 (그림 위를 끌어서)"))
        self.b_crop_clear = QtWidgets.QToolButton()   # 1.2.0: 작고 눈에 덜 띄게 (사용자 '굉장히 중요한 버튼처럼 보임')
        self.b_crop_clear.setText(T("선택 영역 해제"))
        self.b_crop_clear.setAutoRaise(True)
        self.b_crop_clear.setStyleSheet("QToolButton{color:#2a6fc9; padding:0 4px;} QToolButton:disabled{color:#aaa;}")
        self.b_crop_clear.setEnabled(False)
        r1.addWidget(self.crop_lbl)
        r1.addWidget(self.b_crop_clear)
        r1.addStretch(1)
        gv2.addLayout(r1)
        r2 = QtWidgets.QHBoxLayout()
        r2.setSpacing(6)
        self.scale = QtWidgets.QSpinBox()
        self.scale.setRange(5, 100)
        self.scale.setValue(100)
        self.scale.setSuffix(" %")
        self.scale.setFixedWidth(80)
        self.speed = QtWidgets.QComboBox()
        for s_ in SPEEDS:
            self.speed.addItem(f"{s_:g}×", s_)
        self.speed.setCurrentIndex(SPEEDS.index(1.0))
        self.speed.setFixedWidth(70)
        self.fps = QtWidgets.QSpinBox()
        self.fps.setRange(1, 60)
        self.fps.setValue(15)
        self.fps.setFixedWidth(60)
        self.mute = QtWidgets.QCheckBox(T("소리 빼기"))
        self.fps_lbl = QtWidgets.QLabel("fps")
        for w_ in (QtWidgets.QLabel(T("크기")), self.scale, QtWidgets.QLabel("   " + T("속도")), self.speed,
                   self.fps_lbl, self.fps, self.mute):
            r2.addWidget(w_)
        r2.insertSpacing(4, 12)
        r2.addStretch(1)
        gv2.addLayout(r2)
        lay.addWidget(g)
        # 저장 — 1.2.0: [저장] 크고 파랗게 (사용자 그림)
        bot = QtWidgets.QHBoxLayout()
        bot.addWidget(QtWidgets.QLabel(T("저장 형식")))
        self.fmt = QtWidgets.QComboBox()
        self.fmt.addItem("MP4", ".mp4")
        self.fmt.addItem("GIF", ".gif")
        self.fast = QtWidgets.QCheckBox(T("빠르게 자르기 (다시 압축 안 함 · 키프레임 단위)"))
        bot.addWidget(self.fmt)
        bot.addWidget(self.fast)
        bot.addStretch(1)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        self.bar.setFixedWidth(200)
        bot.addWidget(self.bar)
        self.b_cancel = QtWidgets.QPushButton(T("닫기"))
        bot.addWidget(self.b_cancel)
        self.b_save = QtWidgets.QPushButton(T("저장"))
        self.b_save.setDefault(True)
        self.b_save.setObjectName("editSave")
        self.b_save.setMinimumSize(130, 38)
        self.b_save.setStyleSheet("QPushButton#editSave{background:#4a6fa5; color:white; font-weight:bold; font-size:11pt;"
                                  " border:none; border-radius:4px; padding:6px 24px;}"
                                  " QPushButton#editSave:hover{background:#5b82bd;} QPushButton#editSave:disabled{background:#9aa7b8;}")
        bot.addWidget(self.b_save)
        lay.addLayout(bot)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.info)
        # 연결
        self.slider.valueChanged.connect(self._seek)
        self.slider.rangeChanged.connect(self._range_drag)
        self.b_in.clicked.connect(self.set_in)
        self.b_out.clicked.connect(self.set_out)
        self.b_all.clicked.connect(self.set_all)
        self.canvas.cropChanged.connect(self._crop_ui)
        self.b_crop_clear.clicked.connect(lambda: (setattr(self.canvas, "crop", None), self.canvas.update(), self._crop_ui(None)))
        self.fmt.currentIndexChanged.connect(lambda _i: self._opts_ui())
        self.fast.toggled.connect(lambda _o: self._opts_ui())
        for w_ in (self.scale, self.fps):
            w_.valueChanged.connect(lambda _v: self._opts_ui())
        self.speed.currentIndexChanged.connect(lambda _i: self._opts_ui())
        self.b_save.clicked.connect(self.save)
        self.b_cancel.clicked.connect(self.cancel_or_close)
        self.b_del.clicked.connect(self.del_frames)
        self.b_left.clicked.connect(lambda: self.move_frames(-1))
        self.b_right.clicked.connect(lambda: self.move_frames(+1))
        self.b_delay.clicked.connect(self.set_delay)
        self.strip.currentRowChanged.connect(lambda r: r >= 0 and self.slider.setValue(r))
        QtGui.QShortcut(QtGui.QKeySequence("Space"), self, lambda: self.toggle_play())
        QtGui.QShortcut(QtGui.QKeySequence("I"), self, self.set_in)
        QtGui.QShortcut(QtGui.QKeySequence("O"), self, self.set_out)
        QtGui.QShortcut(QtGui.QKeySequence("Left"), self, lambda: self.slider.setValue(self.slider.value() - 1))
        QtGui.QShortcut(QtGui.QKeySequence("Right"), self, lambda: self.slider.setValue(self.slider.value() + 1))
        QtGui.QShortcut(QtGui.QKeySequence("Delete"), self.strip, self.del_frames)
        self.gif_box.setVisible(self.kind == "gif")
        self.mute.setVisible(self.kind == "video")
        self.fmt.setCurrentIndex(1 if self.kind == "gif" else 0)
        if not self.ff:
            self.info.setText(T("⚠ 편집 부품(ffmpeg)이 없습니다 — 4Dir 배포판을 새로 받아 풀면 들어 있습니다"))
            self.b_save.setEnabled(False)
        self._start_frame = start
        if self.kind == "gif":
            self._load_gif()
        else:
            self._load_video()
        log.info("편집 창 %s (%s) ffmpeg=%s", path, self.kind, self.ff)

    # ---------------------------------------------------- 불러오기
    def _load_gif(self):
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            fr = load_gif(self.path)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.frames = [[im, d] for im, d in fr]
        if not self.frames:
            self.info.setText(T("⚠ GIF 를 읽을 수 없습니다"))
            self.b_save.setEnabled(False)
            return
        avg = sum(d for _i, d in self.frames) / len(self.frames)
        self.fps.setValue(max(1, min(60, int(round(1000 / max(10, avg))))))
        self.delay.setValue(int(self.frames[0][1]))
        self._fill_strip()
        self.set_all()
        self.slider.setValue(min(self._start_frame, len(self.frames) - 1))
        self._seek(self.slider.value())
        if len(fr) >= GIF_MAX_FRAMES:
            self.info.setText(T("⚠ 장면이 많아 앞 {0}장만 불러왔습니다").format(GIF_MAX_FRAMES))

    def _fill_strip(self, sel=None):
        self.strip.blockSignals(True)
        self.strip.clear()
        for i, (im, d) in enumerate(self.frames):
            it = QtWidgets.QListWidgetItem(QtGui.QIcon(QtGui.QPixmap.fromImage(im.scaled(72, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))),
                                           f"{i + 1}\n{d}ms")
            self.strip.addItem(it)
        self.strip.blockSignals(False)
        self.slider.setRange(0, max(0, len(self.frames) - 1))
        for r in (sel or []):
            if 0 <= r < self.strip.count():
                self.strip.item(r).setSelected(True)

    def _load_video(self):
        import video
        if not video.available():
            self.info.setText(T("⚠ 동영상 부품이 없습니다"))
            return
        self.mv = video.VideoMovie(self.path, self, muted=True)
        self.mv.frameChanged.connect(self._video_frame)
        self.mv.ready.connect(self._video_ready)
        self.mv.failed.connect(lambda s: self.info.setText(T("⚠ 동영상을 열 수 없습니다: {0}").format(s)))
        self.mv.start()

    def _video_ready(self):
        self.mv.setPaused(True)
        n = self.mv.frameCount()
        self.slider.setRange(0, max(0, n - 1))
        self.fps.setValue(15)
        self.set_all()
        self.slider.setValue(min(self._start_frame, n - 1))
        self._seek(self.slider.value())

    # ---------------------------------------------------- 장면·구간
    def total(self):
        return len(self.frames) if self.kind == "gif" else (self.mv.frameCount() if self.mv else 0)

    def t_of(self, n):
        """n 번째 장면 시작 시각(초)"""
        if self.kind == "gif":
            return sum(d for _i, d in self.frames[:n]) / 1000.0
        return n * self.mv.fms / 1000.0 if self.mv else 0.0

    def _seek(self, n):
        if self.kind == "gif":
            if 0 <= n < len(self.frames):
                self.canvas.set_image(self.frames[n][0])
                self.delay.setValue(int(self.frames[n][1]))
        elif self.mv is not None:
            if self.playing:   # 재생 중에 막대를 누르면 멈추고 그 자리
                self.toggle_play(False)
            self.mv.jumpToFrame(n)
        self._pos_ui(n)

    def _pos_ui(self, n):
        self.pos_lbl.setText(f"{tcode(self.t_of(n))} / {tcode(self.t_of(self.total()))}   ·   {n + 1} / {self.total()} frame")

    # ---------------------------------------------------- 재생 (1.1.0)
    def toggle_play(self, on=None):
        on = (not self.playing) if on is None else bool(on)
        self.playing = on
        self.b_play.setText("⏸" if on else "▶")
        if self.kind == "gif":
            if on:
                self._gif_tick(first=True)
            else:
                self._gif_timer.stop()
        elif self.mv is not None:
            self.mv.setPaused(not on)

    def _gif_tick(self, first=False):
        if not self.playing or not self.frames:
            return
        n = self.slider.value()
        if not first:
            n += 1
            if n > self.b or n >= len(self.frames):
                if self.loop.isChecked() or n >= len(self.frames):
                    n = self.a if self.loop.isChecked() else 0
                    if not self.loop.isChecked():
                        self.toggle_play(False)
                        return
        self.slider.setValue(n, emit=False)
        self.canvas.set_image(self.frames[n][0])
        self._pos_ui(n)
        self._gif_timer.start(max(10, int(self.frames[n][1] / (self.speed.currentData() or 1.0))))

    def _video_frame(self, n):
        self.canvas.set_image(self.mv.currentImage())
        if self.playing:
            if self.loop.isChecked() and (n > self.b or n < self.a):
                self.mv.jumpToFrame(self.a)
                self.mv.setPaused(False)
                n = self.a
            self.slider.setValue(n, emit=False)
            self._pos_ui(n)

    def _range_drag(self, a, b):
        self.a, self.b = a, b
        self._range_ui()

    def _nudge(self, which, d):
        if which == "a":
            self.a = min(max(0, self.a + d), self.b)
            self.slider.setValue(self.a)
        else:
            self.b = min(max(self.a, self.b + d), max(0, self.total() - 1))
            self.slider.setValue(self.b)
        self._range_ui()

    def set_in(self):
        self.a = self.slider.value()
        self.b = max(self.b, self.a)
        self._range_ui()

    def set_out(self):
        self.b = self.slider.value()
        self.a = min(self.a, self.b)
        self._range_ui()

    def set_all(self):
        self.a, self.b = 0, max(0, self.total() - 1)
        self._range_ui()

    def _range_ui(self):
        a_s, b_s = self.t_of(self.a), self.t_of(self.b + 1)
        self.slider.setInOut(self.a, self.b)   # 1.1.0: 막대에 구간 표시
        self.range_lbl.setText(T("구간 길이 {0}  ({1} → {2} 장면)").format(tcode(max(0.0, b_s - a_s)), self.a + 1, self.b + 1))
        self.a_lbl.setText(tcode(a_s))
        self.b_lbl.setText(tcode(b_s))
        self._opts_ui()

    def _crop_ui(self, c):
        self.crop_lbl.setText(T("자르기: {0}×{1} (왼쪽 위 {2},{3})").format(c[2], c[3], c[0], c[1]) if c else T("자르기: 없음 (그림 위를 끌어서)"))
        self.b_crop_clear.setEnabled(bool(c))
        self._opts_ui()

    def _changed(self):
        return bool(self.canvas.crop) or self.scale.value() != 100 or abs(self.speed.currentData() - 1.0) > 1e-6

    def _opts_ui(self):
        gif_out = self.fmt.currentData() == ".gif"
        fast_ok = self.kind == "video" and not gif_out and not self._changed()
        self.fast.setEnabled(fast_ok)
        if not fast_ok and self.fast.isChecked():
            self.fast.setChecked(False)
        self.fps.setEnabled((gif_out and self.kind == "video") or (self.kind == "gif" and not gif_out))   # GIF→GIF 는 장면별 시간 그대로
        self.fps_lbl.setText(T("GIF fps") if gif_out else "fps")

    # ---------------------------------------------------- GIF 장면 편집
    def _sel_rows(self):
        return sorted({self.strip.row(it) for it in self.strip.selectedItems()} or ({self.slider.value()} if self.frames else set()))

    def del_frames(self):
        rows = self._sel_rows()
        if not rows or len(rows) >= len(self.frames):
            self.info.setText(T("⚠ 장면을 모두 지울 수는 없습니다"))
            return
        for r in reversed(rows):
            self.frames.pop(r)
        log.info("GIF 장면 지움 %s", [r + 1 for r in rows])
        self._fill_strip()
        self.set_all()
        self.slider.setValue(min(rows[0], len(self.frames) - 1))
        self._seek(self.slider.value())

    def move_frames(self, d):
        rows = self._sel_rows()
        if not rows or (d < 0 and rows[0] == 0) or (d > 0 and rows[-1] >= len(self.frames) - 1):
            return
        order = rows if d < 0 else list(reversed(rows))
        for r in order:
            self.frames[r + d], self.frames[r] = self.frames[r], self.frames[r + d]
        self._fill_strip([r + d for r in rows])
        self.slider.setValue(rows[0] + d)

    def set_delay(self):
        rows = self._sel_rows()
        for r in rows:
            self.frames[r][1] = self.delay.value()
        self._fill_strip(rows)
        self._range_ui()
        log.info("GIF 장면 시간 %dms ← %d장", self.delay.value(), len(rows))

    # ---------------------------------------------------- 저장
    def options(self):
        return {"a_s": self.t_of(self.a) if self.a > 0 else None,
                "b_s": self.t_of(self.b + 1) if self.b < self.total() - 1 else None,
                "crop": self.canvas.crop, "scale": self.scale.value(), "speed": self.speed.currentData(),
                "fps": self.fps.value() if (self.fmt.currentData() == ".gif" or self.kind == "gif") else None,
                "mute": self.mute.isChecked(), "fast": self.fast.isChecked() and self.fast.isEnabled()}

    def _write_seq(self, opt):
        """GIF→GIF: 장면을 f00000.png… 차례로 (장면 수 그대로) — 시간은 저장 뒤 gif_set_delays 로"""
        self.tmp = tempfile.mkdtemp(prefix="4dir_edit_")
        sp = opt.get("speed") or 1.0
        self.delays_cs = []
        for k, i in enumerate(range(self.a, self.b + 1)):
            im, d = self.frames[i]
            im.save(os.path.join(self.tmp, f"f{k:05d}.png"), "PNG")
            self.delays_cs.append(round(d / 10.0 / sp))
        return os.path.join(self.tmp, "f%05d.png")

    def _write_concat(self, opt):
        """GIF 장면 편집 결과 → 임시 PNG + concat 목록 (구간·속도 반영)"""
        self.tmp = tempfile.mkdtemp(prefix="4dir_edit_")
        lines = []
        sp = opt.get("speed") or 1.0
        last = None
        for i in range(self.a, self.b + 1):
            im, d = self.frames[i]
            p = os.path.join(self.tmp, f"f{i:05d}.png")
            im.save(p, "PNG")
            lines.append(f"file '{p.replace(chr(92), '/')}'")
            lines.append(f"duration {max(0.01, d / 1000.0 / sp):.4f}")
            last = p
        lines.append(f"file '{last.replace(chr(92), '/')}'")   # concat 은 마지막 장면을 한 번 더 써야 시간이 들어감
        lst = os.path.join(self.tmp, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return lst

    def save(self):
        if not self.ff or self.proc is not None:
            return
        opt = self.options()
        ext = self.fmt.currentData()
        if opt["fast"]:
            ext = os.path.splitext(self.path)[1].lower() or ext
        dst = out_name(self.path, ext)
        self.delays_cs = None
        if self.kind == "gif" and ext == ".gif":   # GIF→GIF: 장면 차례 입력 + 저장 뒤 시간 고쳐 씀
            seq = self._write_seq(opt)
            pre = video_filters(opt.get("crop"), opt.get("scale", 100), 1.0, even=False)
            args = ["-hide_banner", "-y", "-nostats", "-progress", "pipe:1", "-framerate", "100", "-i", seq,
                    "-filter_complex", gif_palette_chain(pre), "-fps_mode", "passthrough", "-loop", "0", dst]
            concat = seq
        else:
            concat = self._write_concat(opt) if self.kind == "gif" else None
            args = build_args(self.path, dst, self.kind, opt, concat)
        self.dst = dst
        self.expect = max(0.1, (self.t_of(self.b + 1) - self.t_of(self.a)) / (1.0 if concat else (opt["speed"] or 1.0)))
        log.info("ffmpeg %s", " ".join(args))
        self.proc = QtCore.QProcess(self)
        self.proc.setProgram(self.ff)
        self.proc.setArguments(args)
        self.proc.setProcessChannelMode(QtCore.QProcess.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._progress)
        self.proc.finished.connect(self._finished)
        self._err = b""
        self.proc.readyReadStandardError.connect(lambda: setattr(self, "_err", (self._err + bytes(self.proc.readAllStandardError()))[-6000:]))
        self.t0 = time.time()
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.b_save.setEnabled(False)
        self.b_cancel.setText(T("취소"))
        self.info.setText(T("저장하는 중… {0}").format(os.path.basename(dst)))
        self.proc.start()

    def _progress(self):
        out = bytes(self.proc.readAllStandardOutput()).decode("ascii", "replace")
        for m in re.finditer(r"out_time_(?:us|ms)=(\d+)", out):
            t = int(m.group(1)) / 1e6
            self.bar.setValue(min(1000, int(t / self.expect * 1000)))

    def _finished(self, code, _status):
        sec = time.time() - self.t0
        ok = code == 0 and os.path.isfile(self.dst) and os.path.getsize(self.dst) > 0
        if ok and self.delays_cs:
            n = gif_set_delays(self.dst, self.delays_cs)
            log.info("GIF 장면 시간 %d/%d장 고쳐 씀", n, len(self.delays_cs))
        err = self._err.decode("utf-8", "replace").strip().splitlines()[-6:]
        log.info("ffmpeg 끝 코드 %s %.1f초 → %s %s", code, sec, self.dst, "" if ok else " / ".join(err))
        self.proc = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None
        self.bar.setVisible(False)
        self.b_save.setEnabled(bool(self.ff))
        self.b_cancel.setText(T("닫기"))
        if ok:
            mb = os.path.getsize(self.dst) / 1048576
            self.info.setText(T("저장했습니다: {0} ({1:.1f}MB, {2:.1f}초)").format(self.dst, mb, sec))
            if self.done_cb:
                self.done_cb(self.dst)
        else:
            if os.path.isfile(self.dst) and getattr(self, "_cancelled", False):
                try:
                    os.remove(self.dst)   # 취소로 덜 만든 파일
                except OSError:
                    pass
            self.info.setText((T("취소했습니다") if getattr(self, "_cancelled", False) else T("⚠ 저장하지 못했습니다")) + ("\n" + "\n".join(err) if err and not getattr(self, "_cancelled", False) else ""))
        self._cancelled = False

    def cancel_or_close(self):
        if self.proc is not None:
            self._cancelled = True
            self.proc.kill()
            return
        self.close()

    def closeEvent(self, ev):
        self.playing = False
        self._gif_timer.stop()
        if self.proc is not None:
            self._cancelled = True
            self.proc.kill()
            self.proc.waitForFinished(3000)
        if self.mv is not None:
            self.mv.stop()
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
        super().closeEvent(ev)
