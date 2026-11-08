# -*- coding: utf-8 -*-
"""스프라이트 시트 만들기·자르기·밀착 인화 (SHEETS_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '스프라이트 시트 합치기·자르기, 검수용 한 장')

- open_pack(parent, paths): 고른 그림들(이름순, 연번이면 번호순 = 숫자 크기순)을 격자 한 장으로
  가로 칸 수(0 = 정사각에 가깝게) · 칸 사이 간격 · 바깥 여백 · 칸 크기 = 가장 큰 그림 기준(작은 건 가운데/왼쪽 위) · 배경 투명/색
  [저장] = 첫 그림 폴더 '이름_sheet.png' + 같은 이름 .json (칸마다 name·x·y·w·h, 그림이 실제 놓인 자리 sx·sy·sw·sh)
- open_slice(parent, path): 한 장을 [가로×세로 칸 수] 또는 [칸 크기 px] 로 잘라 저장 ('이름_slices' 새 폴더에 이름_000.png…)
  미리보기 위에 격자 선, 빈(완전 투명) 칸 빼기, 칸 크기로 자를 때 남는 가장자리는 버림
- open_contact(parent, paths): 밀착 인화(검수용 한 장) — 작은 그림 + 파일 이름(길면 줄임), 맨 위 제목(폴더·날짜·장수)
  칸 크기 128/192/256, 가로 칸 수. 못 읽는 파일은 회색 칸 + 이름. 저장 = 같은 폴더 '폴더이름_contact.png'
- 그림 읽기·합치기는 뒤 스레드(QImage 만), 화면 그림(QPixmap)은 화면 스레드에서만. 원본은 건드리지 않음, 같은 이름이면 ' (1)'
- pack_icon(sz) · slice_icon(sz) · contact_icon(sz)
로그: bin\\log\\4Dir.log [QE.sheets] (입력 장수·옵션·결과 크기·저장 경로·시간)
"""
import os
import re
import json
import math
import time
import logging
import datetime
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

SHEETS_VER = "1.0.0"
log = logging.getLogger("QE.sheets")
R = QtCore.QRectF
_NUM = re.compile(r"(\d+)")


def nat_key(path):
    """이름순 (숫자는 크기순 → walk_2 가 walk_10 보다 앞)"""
    b = os.path.basename(path).lower()
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in _NUM.split(b) if t != ""]


def unique(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{stem} ({i}){ext}"):
        i += 1
    return f"{stem} ({i}){ext}"


def base_of(paths):
    """'walk_0001.png'… → 'walk' (공통 앞부분), 못 찾으면 첫 파일 이름"""
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    pre = os.path.commonprefix(stems) if len(stems) > 1 else stems[0]
    pre = pre.rstrip("0123456789").rstrip(" _.-#")
    return pre or stems[0]


def auto_cols(n):
    return max(1, int(math.ceil(math.sqrt(max(1, n)))))


class _Sig(QtCore.QObject):
    progress = QtCore.Signal(int, int)
    done = QtCore.Signal(object)


class _Job:
    """뒤 스레드 일 하나 — fn(cancel_event, progress_cb) 결과를 done 신호로 (화면 스레드에서 받음)"""

    def __init__(self, fn, on_done, on_progress=None):
        self.sig = _Sig()
        self.sig.done.connect(on_done)
        if on_progress:
            self.sig.progress.connect(on_progress)
        self.cancel = threading.Event()
        self.th = threading.Thread(target=self._run, args=(fn,), daemon=True, name="sheets-job")
        self.th.start()

    def _run(self, fn):
        try:
            r = fn(self.cancel, lambda a, b: self.sig.progress.emit(a, b))
        except Exception as e:
            log.exception("뒤 작업 오류")
            r = e
        if not self.cancel.is_set():
            self.sig.done.emit(r)

    def stop(self):
        self.cancel.set()
        self.th.join(3)


def load_images(paths, cancel=None, progress=None):
    out = []
    for i, p in enumerate(paths):
        if cancel is not None and cancel.is_set():
            return None
        rd = QtGui.QImageReader(p)
        rd.setAutoTransform(True)
        im = rd.read()
        if im.isNull():
            log.info("그림 못 읽음 %s (%s)", p, rd.errorString())
            im = None
        else:
            im = im.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)
        out.append(im)
        if progress:
            progress(i + 1, len(paths))
    return out


# ---------------------------------------------------------------- 합치기
def pack_layout(sizes, cols=0, gap=0, margin=0):
    """sizes = [(w,h)] → (시트 w, h, 칸 w, h, cols, rows)"""
    n = len(sizes)
    cols = cols if cols and cols > 0 else auto_cols(n)
    cols = min(cols, max(1, n))
    rows = int(math.ceil(n / cols)) if n else 0
    cw = max([w for w, _ in sizes] or [1])
    ch = max([h for _, h in sizes] or [1])
    W = margin * 2 + cols * cw + (cols - 1) * gap
    H = margin * 2 + rows * ch + max(0, rows - 1) * gap
    return W, H, cw, ch, cols, rows


def pack_images(images, names, cols=0, gap=0, margin=0, align="center", bg=None):
    """QImage 목록 → (시트 QImage, 칸 정보 목록). 못 읽은 그림(None)은 빈 칸. bg=None 투명"""
    sizes = [(im.width(), im.height()) if im is not None else (0, 0) for im in images]
    W, H, cw, ch, cols, rows = pack_layout(sizes, cols, gap, margin)
    sheet = QtGui.QImage(max(1, W), max(1, H), QtGui.QImage.Format_ARGB32_Premultiplied)
    sheet.fill(QtGui.QColor(bg) if bg else QtGui.QColor(0, 0, 0, 0))
    p = QtGui.QPainter(sheet)
    frames = []
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        x = margin + c * (cw + gap)
        y = margin + r * (ch + gap)
        w, h = sizes[i]
        if align == "center":
            sx, sy = x + (cw - w) // 2, y + (ch - h) // 2
        else:
            sx, sy = x, y
        if im is not None:
            p.drawImage(sx, sy, im)
        frames.append({"name": names[i], "x": x, "y": y, "w": cw, "h": ch, "sx": sx, "sy": sy, "sw": w, "sh": h})
    p.end()
    return sheet, {"cols": cols, "rows": rows, "cell_w": cw, "cell_h": ch, "w": W, "h": H, "frames": frames}


def save_pack(sheet, info, folder, base, gap, margin, align, bg):
    stem = os.path.join(folder, base + "_sheet")
    k = 0
    while True:     # .png·.json 둘 다 없는 이름
        s = stem if k == 0 else f"{stem} ({k})"
        png, js = s + ".png", s + ".json"
        if not os.path.exists(png) and not os.path.exists(js):
            break
        k += 1
    if not sheet.save(png, "PNG"):
        raise OSError(T("저장하지 못했습니다") + ": " + png)
    data = {"image": os.path.basename(png), "size": {"w": info["w"], "h": info["h"]},
            "cell": {"w": info["cell_w"], "h": info["cell_h"]}, "cols": info["cols"], "rows": info["rows"],
            "gap": gap, "margin": margin, "align": align, "background": bg or "transparent",
            "frames": info["frames"], "made_by": "4Dir sheets " + SHEETS_VER}
    with open(js, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    log.info("시트 저장 %s (%dx%d, %d칸) + %s", png, info["w"], info["h"], len(info["frames"]), js)
    return png, js


# ---------------------------------------------------------------- 자르기
def slice_grid(w, h, mode, a, b):
    """mode='count' → a×b 칸 / 'size' → a×b px 칸. 돌려줌 [(x,y,w,h)], (cols, rows)"""
    if mode == "count":
        cols, rows = max(1, a), max(1, b)
        cw, ch = w / cols, h / rows
        rects = []
        for r in range(rows):
            for c in range(cols):
                x0, y0 = int(round(c * cw)), int(round(r * ch))
                x1, y1 = int(round((c + 1) * cw)), int(round((r + 1) * ch))
                rects.append((x0, y0, x1 - x0, y1 - y0))
        return rects, (cols, rows)
    cw, ch = max(1, a), max(1, b)
    cols, rows = w // cw, h // ch
    return [(c * cw, r * ch, cw, ch) for r in range(rows) for c in range(cols)], (cols, rows)


def is_empty(img):
    """완전 투명한가 (알파 0 만)"""
    if not img.hasAlphaChannel():
        return False
    im = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    mv = bytes(im.constBits())
    bpl, w = im.bytesPerLine(), im.width()
    if bpl == w * 4:
        return max(mv[3::4], default=0) == 0
    for y in range(im.height()):
        row = mv[y * bpl: y * bpl + w * 4]
        if max(row[3::4], default=0):
            return False
    return True


def do_slice(path, mode, a, b, skip_empty, cancel=None, progress=None):
    t0 = time.time()
    img = QtGui.QImage(path)
    if img.isNull():
        raise OSError(T("그림을 읽지 못했습니다") + ": " + path)
    rects, (cols, rows) = slice_grid(img.width(), img.height(), mode, a, b)
    stem = os.path.splitext(os.path.basename(path))[0]
    folder = unique(os.path.join(os.path.dirname(path), stem + "_slices"))
    os.makedirs(folder)
    saved = skipped = 0
    for i, (x, y, w, h) in enumerate(rects):
        if cancel is not None and cancel.is_set():
            break
        cell = img.copy(x, y, w, h)
        if skip_empty and is_empty(cell):
            skipped += 1
        else:
            cell.save(os.path.join(folder, f"{stem}_{i:03d}.png"), "PNG")
            saved += 1
        if progress:
            progress(i + 1, len(rects))
    log.info("자르기 %s %s %sx%s → %s 저장 %d · 빈 칸 뺌 %d (%.2f초)", path, mode, a, b, folder, saved, skipped, time.time() - t0)
    return {"folder": folder, "saved": saved, "skipped": skipped, "cols": cols, "rows": rows}


# ---------------------------------------------------------------- 밀착 인화
def contact_sheet(paths, cell=192, cols=0, title=None, cancel=None, progress=None):
    """→ QImage. 칸 = 정사각 그림 자리 + 아래 이름 한 줄"""
    n = len(paths)
    cols = cols if cols and cols > 0 else min(8, auto_cols(n))
    rows = int(math.ceil(n / cols)) if n else 1
    pad, name_h, head_h = 8, 20, 44
    W = pad + cols * (cell + pad)
    H = head_h + pad + rows * (cell + name_h + pad)
    img = QtGui.QImage(W, H, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor("#ffffff"))
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    f = QtGui.QFont("Malgun Gothic")
    f.setPixelSize(18)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QtGui.QColor("#111111"))
    p.drawText(QtCore.QRect(pad, 0, W - pad * 2, head_h), Qt.AlignVCenter | Qt.AlignLeft, title or "")
    f2 = QtGui.QFont("Malgun Gothic")
    f2.setPixelSize(12)
    p.setFont(f2)
    fm = QtGui.QFontMetrics(f2)
    bad = 0
    for i, path in enumerate(paths):
        if cancel is not None and cancel.is_set():
            p.end()
            return None
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad)
        y = head_h + pad + r * (cell + name_h + pad)
        box = QtCore.QRect(x, y, cell, cell)
        rd = QtGui.QImageReader(path)
        rd.setAutoTransform(True)
        sz = rd.size()
        if sz.isValid() and (sz.width() > cell or sz.height() > cell):
            rd.setScaledSize(sz.scaled(cell, cell, Qt.KeepAspectRatio))
        im = rd.read()
        if im.isNull():
            bad += 1
            p.fillRect(box, QtGui.QColor("#9ca3af"))
            p.setPen(QtGui.QColor("#ffffff"))
            p.drawText(box, Qt.AlignCenter, T("못 읽음"))
        else:
            p.fillRect(box, QtGui.QColor("#eeeeee"))
            for yy in range(0, cell, 16):     # 투명한 곳이 보이게 바둑판
                for xx in range((yy // 16 % 2) * 16, cell, 32):
                    p.fillRect(QtCore.QRect(x + xx, y + yy, min(16, cell - xx), min(16, cell - yy)), QtGui.QColor("#dddddd"))
            if im.width() > cell or im.height() > cell:
                im = im.scaled(cell, cell, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawImage(x + (cell - im.width()) // 2, y + (cell - im.height()) // 2, im)
        p.setPen(QtGui.QColor("#222222"))
        name = fm.elidedText(os.path.basename(path), Qt.ElideMiddle, cell)
        p.drawText(QtCore.QRect(x, y + cell, cell, name_h), Qt.AlignCenter, name)
        if progress:
            progress(i + 1, n)
    p.end()
    log.info("밀착 인화 %d장 (못 읽음 %d) 칸 %d · %d칸 → %dx%d", n, bad, cell, cols, W, H)
    return img


def contact_title(paths):
    folder = os.path.dirname(os.path.abspath(paths[0])) if paths else ""
    return T("{0} · {1} · {2}장").format(os.path.basename(folder) or folder, datetime.date.today().isoformat(), len(paths))


# ---------------------------------------------------------------- 공통 창
class _Preview(QtWidgets.QWidget):
    """그림 미리보기 (맞춤 크기) + 격자 선 (자르기용)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pm = None
        self.rects = []
        self.empty = set()
        self.setMinimumSize(360, 260)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def set_image(self, img):
        self.pm = QtGui.QPixmap.fromImage(img) if img is not None else None
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        r = self.rect()
        p.fillRect(r, self.palette().color(QtGui.QPalette.Window).darker(112))
        if self.pm is None or self.pm.isNull():
            p.setPen(self.palette().color(QtGui.QPalette.WindowText))
            p.drawText(r, Qt.AlignCenter, T("읽는 중…"))
            return
        s = self.pm.size().scaled(r.size() - QtCore.QSize(8, 8), Qt.KeepAspectRatio)
        if s.width() > self.pm.width() * 8:
            s = self.pm.size() * 8
        tr = QtCore.QRect(QtCore.QPoint(0, 0), s)
        tr.moveCenter(r.center())
        for yy in range(tr.top(), tr.bottom(), 10):      # 바둑판 (투명 보기)
            for xx in range(tr.left() + ((yy - tr.top()) // 10 % 2) * 10, tr.right(), 20):
                p.fillRect(QtCore.QRect(xx, yy, min(10, tr.right() - xx + 1), min(10, tr.bottom() - yy + 1)), QtGui.QColor("#d4d4d4"))
        p.fillRect(tr, QtGui.QColor(255, 255, 255, 120))
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, s.width() < self.pm.width())
        p.drawPixmap(tr, self.pm)
        if self.rects:
            k = tr.width() / self.pm.width()
            for i, (x, y, w, h) in enumerate(self.rects):
                rr = QtCore.QRectF(tr.left() + x * k, tr.top() + y * k, w * k, h * k)
                if i in self.empty:
                    p.fillRect(rr, QtGui.QColor(220, 38, 38, 60))
                p.setPen(QtGui.QPen(QtGui.QColor("#ff2d55"), 1, Qt.DashLine))
                p.drawRect(rr)
        p.end()


class _Base(QtWidgets.QDialog):
    def __init__(self, parent, title, icon):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.setWindowIcon(icon)
        self.jobs = []
        self.lay = QtWidgets.QVBoxLayout(self)
        self.opts = QtWidgets.QGridLayout()
        self.lay.addLayout(self.opts)
        self.view = _Preview()
        self.lay.addWidget(self.view, 1)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lay.addWidget(self.info)
        row = QtWidgets.QHBoxLayout()
        self.bar = QtWidgets.QProgressBar()
        self.bar.setVisible(False)
        row.addWidget(self.bar, 1)
        self.b_save = QtWidgets.QPushButton(T("저장"))
        self.b_close = QtWidgets.QPushButton(T("닫기"))
        self.b_save.clicked.connect(self.save)
        self.b_close.clicked.connect(self.close)
        row.addWidget(self.b_save)
        row.addWidget(self.b_close)
        self.lay.addLayout(row)
        self._redo = QtCore.QTimer(self)    # 옵션 바꿀 때만 한 번 (쉬는 동안 안 돎)
        self._redo.setSingleShot(True)
        self._redo.setInterval(150)
        self._redo.timeout.connect(self.refresh)
        self.resize(820, 660)

    def later(self, *_a):
        self._redo.start()

    def run(self, fn, on_done):
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)

        def prog(a, b):
            self.bar.setRange(0, b)
            self.bar.setValue(a)

        def done(r):
            self.bar.setVisible(False)
            if job in self.jobs:
                self.jobs.remove(job)
            on_done(r)
        job = _Job(fn, done, prog)
        self.jobs.append(job)
        return job

    def busy(self):
        return bool(self.jobs)

    def refresh(self):
        pass

    def save(self):
        pass

    def closeEvent(self, e):
        self._redo.stop()
        for j in list(self.jobs):
            j.stop()
        self.jobs.clear()
        super().closeEvent(e)


def _spin(lo, hi, val, suffix=""):
    s = QtWidgets.QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    return s


class PackDialog(_Base):
    def __init__(self, parent, paths):
        super().__init__(parent, T("스프라이트 시트 만들기"), pack_icon(16))
        self.paths = sorted(paths, key=nat_key)
        self.names = [os.path.basename(p) for p in self.paths]
        self.images = None
        self.sheet = None
        self.sheet_info = None
        self.bgcol = "#ffffff"
        o = self.opts
        self.cols = _spin(0, 999, 0)
        self.cols.setSpecialValueText(T("자동"))
        self.gap = _spin(0, 512, 0, " px")
        self.margin = _spin(0, 512, 0, " px")
        self.align = QtWidgets.QComboBox()
        self.align.addItem(T("가운데"), "center")
        self.align.addItem(T("왼쪽 위"), "topleft")
        self.bg = QtWidgets.QComboBox()
        self.bg.addItem(T("투명"), "")
        self.bg.addItem(T("색"), "color")
        self.b_col = QtWidgets.QPushButton()
        self.b_col.setFixedWidth(40)
        self._paint_col()
        self.b_col.clicked.connect(self.pick_col)
        o.addWidget(QtWidgets.QLabel(T("가로 칸 수")), 0, 0)
        o.addWidget(self.cols, 0, 1)
        o.addWidget(QtWidgets.QLabel(T("칸 사이 간격")), 0, 2)
        o.addWidget(self.gap, 0, 3)
        o.addWidget(QtWidgets.QLabel(T("바깥 여백")), 0, 4)
        o.addWidget(self.margin, 0, 5)
        o.addWidget(QtWidgets.QLabel(T("작은 그림 자리")), 1, 0)
        o.addWidget(self.align, 1, 1)
        o.addWidget(QtWidgets.QLabel(T("배경")), 1, 2)
        o.addWidget(self.bg, 1, 3)
        o.addWidget(self.b_col, 1, 4)
        o.setColumnStretch(6, 1)
        for w in (self.cols, self.gap, self.margin):
            w.valueChanged.connect(self.later)
        self.align.currentIndexChanged.connect(self.later)
        self.bg.currentIndexChanged.connect(self.later)
        self.b_save.setEnabled(False)
        self.info.setText(T("그림 {0}장 읽는 중…").format(len(self.paths)))
        log.info("시트 만들기 창 %d장 (첫 %s)", len(self.paths), self.paths[0] if self.paths else "-")
        self.run(lambda c, pr: load_images(self.paths, c, pr), self._loaded)

    def _paint_col(self):
        pm = QtGui.QPixmap(24, 14)
        pm.fill(QtGui.QColor(self.bgcol))
        self.b_col.setIcon(QtGui.QIcon(pm))

    def pick_col(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.bgcol), self, T("배경 색"))
        if c.isValid():
            self.bgcol = c.name()
            self._paint_col()
            if self.bg.currentData() != "color":
                self.bg.setCurrentIndex(1)
            else:
                self.later()

    def opt(self):
        return dict(cols=self.cols.value(), gap=self.gap.value(), margin=self.margin.value(),
                    align=self.align.currentData(), bg=self.bgcol if self.bg.currentData() == "color" else None)

    def _loaded(self, imgs):
        if isinstance(imgs, Exception) or imgs is None:
            self.info.setText(T("⚠ 그림을 읽지 못했습니다"))
            return
        self.images = imgs
        bad = sum(1 for i in imgs if i is None)
        if bad:
            log.info("시트: 못 읽은 그림 %d장 → 빈 칸", bad)
        self.refresh()

    def refresh(self):
        if self.images is None:
            return
        if self.busy():
            self.later()
            return
        o = self.opt()
        self.run(lambda c, pr: pack_images(self.images, self.names, **o), self._packed)

    def _packed(self, r):
        if isinstance(r, Exception):
            self.info.setText(T("⚠ 만들지 못했습니다") + f": {r}")
            return
        self.sheet, self.sheet_info = r
        self.view.set_image(self.sheet)
        i = self.sheet_info
        bad = sum(1 for im in self.images if im is None)
        self.info.setText(T("{0}장 → {1}×{2} 칸 · 칸 {3}×{4} px · 시트 {5}×{6} px").format(
            len(self.images), i["cols"], i["rows"], i["cell_w"], i["cell_h"], i["w"], i["h"])
            + (" · " + T("못 읽은 그림 {0}장은 빈 칸").format(bad) if bad else ""))
        self.b_save.setEnabled(True)

    def save(self):
        if self.sheet is None:
            return
        o = self.opt()
        try:
            png, js = save_pack(self.sheet, self.sheet_info, os.path.dirname(self.paths[0]), base_of(self.paths),
                                o["gap"], o["margin"], o["align"], o["bg"])
        except Exception as e:
            log.exception("시트 저장 실패")
            self.info.setText(T("⚠ 저장하지 못했습니다") + f": {e}")
            return
        self.last_saved = (png, js)
        self.info.setText(T("저장했습니다: {0}").format(png) + "\n" + js)


class SliceDialog(_Base):
    def __init__(self, parent, path):
        super().__init__(parent, T("시트 자르기"), slice_icon(16))
        self.path = path
        self.img = QtGui.QImage(path)
        o = self.opts
        self.m_count = QtWidgets.QRadioButton(T("칸 수"))
        self.m_size = QtWidgets.QRadioButton(T("칸 크기"))
        self.m_count.setChecked(True)
        self.cols = _spin(1, 999, 4)
        self.rows = _spin(1, 999, 4)
        self.cw = _spin(1, 16384, 64, " px")
        self.ch = _spin(1, 16384, 64, " px")
        self.skip = QtWidgets.QCheckBox(T("빈(완전 투명) 칸 빼기"))
        self.skip.setChecked(True)
        o.addWidget(self.m_count, 0, 0)
        o.addWidget(QtWidgets.QLabel(T("가로")), 0, 1)
        o.addWidget(self.cols, 0, 2)
        o.addWidget(QtWidgets.QLabel(T("세로")), 0, 3)
        o.addWidget(self.rows, 0, 4)
        o.addWidget(self.m_size, 1, 0)
        o.addWidget(QtWidgets.QLabel(T("가로")), 1, 1)
        o.addWidget(self.cw, 1, 2)
        o.addWidget(QtWidgets.QLabel(T("세로")), 1, 3)
        o.addWidget(self.ch, 1, 4)
        o.addWidget(self.skip, 2, 0, 1, 5)
        o.setColumnStretch(5, 1)
        for w in (self.cols, self.rows, self.cw, self.ch):
            w.valueChanged.connect(self.later)
        for w in (self.m_count, self.m_size, self.skip):
            w.toggled.connect(self.later)
        log.info("자르기 창 %s %s", path, "" if self.img.isNull() else f"{self.img.width()}x{self.img.height()}")
        if self.img.isNull():
            self.info.setText(T("⚠ 그림을 읽지 못했습니다"))
            self.b_save.setEnabled(False)
        else:
            self.view.set_image(self.img)
            self.refresh()

    def mode(self):
        return ("count", self.cols.value(), self.rows.value()) if self.m_count.isChecked() else ("size", self.cw.value(), self.ch.value())

    def refresh(self):
        if self.img.isNull():
            return
        m, a, b = self.mode()
        rects, (cols, rows) = slice_grid(self.img.width(), self.img.height(), m, a, b)
        self.view.rects = rects
        empty = set()
        if self.skip.isChecked() and len(rects) <= 4096:
            empty = {i for i, (x, y, w, h) in enumerate(rects) if is_empty(self.img.copy(x, y, w, h))}
        self.view.empty = empty
        self.view.update()
        txt = T("{0}×{1} = {2}칸").format(cols, rows, len(rects))
        if self.skip.isChecked():
            txt += " · " + T("빈 칸 {0}개 빼고 {1}장 저장").format(len(empty), len(rects) - len(empty))
        if m == "size":
            rw, rh = self.img.width() - cols * a, self.img.height() - rows * b
            if rw or rh:
                txt += " · " + T("남는 가장자리 버림 (가로 {0}px, 세로 {1}px)").format(rw, rh)
        self.info.setText(txt)
        self.b_save.setEnabled(bool(rects) and not self.busy())

    def save(self):
        if self.busy() or self.img.isNull():
            return
        m, a, b = self.mode()
        sk = self.skip.isChecked()
        self.b_save.setEnabled(False)
        self.run(lambda c, pr: do_slice(self.path, m, a, b, sk, c, pr), self._done)

    def _done(self, r):
        self.b_save.setEnabled(True)
        if isinstance(r, Exception):
            self.info.setText(T("⚠ 저장하지 못했습니다") + f": {r}")
            return
        self.last_result = r
        self.info.setText(T("저장했습니다: {0}").format(r["folder"]) + " · " + T("{0}장 (빈 칸 {1}개 뺌)").format(r["saved"], r["skipped"]))


class ContactDialog(_Base):
    def __init__(self, parent, paths):
        super().__init__(parent, T("밀착 인화 (검수용 한 장)"), contact_icon(16))
        self.paths = sorted(paths, key=nat_key)
        self.sheet = None
        o = self.opts
        self.cell = QtWidgets.QComboBox()
        for v in (128, 192, 256):
            self.cell.addItem(f"{v} px", v)
        self.cell.setCurrentIndex(1)
        self.cols = _spin(0, 100, 0)
        self.cols.setSpecialValueText(T("자동"))
        o.addWidget(QtWidgets.QLabel(T("칸 크기")), 0, 0)
        o.addWidget(self.cell, 0, 1)
        o.addWidget(QtWidgets.QLabel(T("가로 칸 수")), 0, 2)
        o.addWidget(self.cols, 0, 3)
        o.setColumnStretch(4, 1)
        self.cell.currentIndexChanged.connect(self.later)
        self.cols.valueChanged.connect(self.later)
        self.b_save.setEnabled(False)
        log.info("밀착 인화 창 %d장", len(self.paths))
        self.refresh()

    def refresh(self):
        if self.busy():
            self.later()
            return
        cell, cols = self.cell.currentData(), self.cols.value()
        title = contact_title(self.paths)
        self.b_save.setEnabled(False)
        self.info.setText(T("만드는 중…"))
        self.run(lambda c, pr: contact_sheet(self.paths, cell, cols, title, c, pr), self._made)

    def _made(self, img):
        if isinstance(img, Exception) or img is None:
            self.info.setText(T("⚠ 만들지 못했습니다"))
            return
        self.sheet = img
        self.view.set_image(img)
        self.info.setText(T("{0}장 · {1}×{2} px").format(len(self.paths), img.width(), img.height()))
        self.b_save.setEnabled(True)

    def save(self):
        if self.sheet is None:
            return
        folder = os.path.dirname(os.path.abspath(self.paths[0]))
        dst = unique(os.path.join(folder, (os.path.basename(folder) or "contact") + "_contact.png"))
        if self.sheet.save(dst, "PNG"):
            log.info("밀착 인화 저장 %s", dst)
            self.last_saved = dst
            self.info.setText(T("저장했습니다: {0}").format(dst))
        else:
            log.error("밀착 인화 저장 실패 %s", dst)
            self.info.setText(T("⚠ 저장하지 못했습니다") + ": " + dst)


def open_pack(parent, paths):
    d = PackDialog(parent, list(paths))
    d.show()
    return d


def open_slice(parent, path):
    d = SliceDialog(parent, path)
    d.show()
    return d


def open_contact(parent, paths):
    d = ContactDialog(parent, list(paths))
    d.show()
    return d


# ---------------------------------------------------------------- 아이콘
def _icon(sz, draw):
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(sz * dpr / 20.0, sz * dpr / 20.0)
    draw(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


def pack_icon(sz=16):
    def d(p):   # 2×2 색 칸 격자
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#475569"))
        p.drawRoundedRect(R(1, 1, 18, 18), 2, 2)
        cols = ("#38bdf8", "#f472b6", "#a3e635", "#fbbf24")
        for k in range(4):
            r, c = divmod(k, 2)
            p.setBrush(QtGui.QColor(cols[k]))
            p.drawRoundedRect(R(2.5 + c * 8, 2.5 + r * 8, 7, 7), 1, 1)
    return _icon(sz, d)


def slice_icon(sz=16):
    def d(p):   # 그림 + 빨간 점선 칼금
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#0ea5e9"))
        p.drawRoundedRect(R(1, 1, 18, 18), 2, 2)
        p.setBrush(QtGui.QColor("#e0f2fe"))
        p.drawEllipse(R(4, 4, 5, 5))
        p.setBrush(QtGui.QColor("#0369a1"))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(2, 17), QtCore.QPointF(8, 9), QtCore.QPointF(13, 17)]))
        pen = QtGui.QPen(QtGui.QColor("#ef4444"), 1.6, Qt.DashLine)
        pen.setDashPattern([2, 1.4])
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(10, 0.5), QtCore.QPointF(10, 19.5))
        p.drawLine(QtCore.QPointF(0.5, 10), QtCore.QPointF(19.5, 10))
    return _icon(sz, d)


def contact_icon(sz=16):
    def d(p):   # 흰 종이 + 작은 그림 3×2 + 이름 줄
        p.setPen(QtGui.QPen(QtGui.QColor("#64748b"), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawRect(R(1.5, 1.5, 17, 17))
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#334155"))
        p.drawRect(R(3, 3, 10, 1.6))
        cols = ("#60a5fa", "#f97316", "#22c55e", "#a855f7", "#eab308", "#ec4899")
        for k in range(6):
            r, c = divmod(k, 3)
            p.setBrush(QtGui.QColor(cols[k]))
            p.drawRect(R(3 + c * 5, 6 + r * 6, 4, 3.4))
            p.setBrush(QtGui.QColor("#94a3b8"))
            p.drawRect(R(3 + c * 5, 9.9 + r * 6, 4, 0.9))
    return _icon(sz, d)
