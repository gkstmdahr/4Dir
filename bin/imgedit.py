# -*- coding: utf-8 -*-
"""그림 편집 창 (IMGEDIT_VER 1.0.0, 4Dir 0.9.118 — 사용자 11/8 '편집툴을 따로 창으로', 1단계)

참고한 공개 프로젝트(구조만, 코드 복사 없음): Greenshot·ShareX 편집기(그린 것을 나중에도 옮기고 고칠 수 있는 '표시 물체' 방식),
kImageAnnotator(Qt 장면 + 되돌리기 묶음), Flameshot(도구 단추 줄), Pinta·drawing(자르기·크기·밝기 같은 그림 자체 손질).

구조
- QGraphicsScene: 맨 아래 = 바탕 그림(QGraphicsPixmapItem, self.base QImage), 그 위 = 표시 물체(펜·형광펜·직선·화살표·네모·원·글자·번호).
  표시 물체는 [선택] 도구로 옮기기·지우기(Delete)·색/굵기 바꾸기 가능 — 저장할 때 한 장으로 합침(flatten).
- 그림 자체를 바꾸는 것(자르기·회전·뒤집기·크기·밝기 대비 감마·흑백·모자이크)은 RasterCmd:
  필요하면 먼저 표시 물체를 바탕에 합친 뒤(자르기·회전·뒤집기·크기) 바탕을 바꿈. 되돌리면 바탕과 물체가 그대로 돌아옴.
- 되돌리기·다시 하기 = QUndoStack (물체 넣기·지우기·옮기기·그림 바꾸기 모두)
- 밝기·대비·감마 = 256칸 표를 채널마다 bytes.translate (파이썬 픽셀 반복 없음), 흑백 = Qt 회색 변환 + 원래 투명도
- 저장: 같은 이름(덮어쓰기 확인) / 다른 이름(기본 '이름_편집.png') / 클립보드 복사. JPG 는 품질 95 로 다시 압축(EXIF 는 안 남음 — 안내)
  저장하면 on_saved(경로) — main 이 그 폴더 칸을 다시 읽고 미리보기를 새로 그림
- 휠 = 확대/축소(마우스 위치 기준), 가운데 버튼 끌기 = 이동, [맞춤] [1:1]
로그: bin\\log\\4Dir.log [QE.imgedit]
"""
import os
import math
import time
import logging

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

IMGEDIT_VER = "1.1.1"   # 1.1.0: 도구·되돌리기 아이콘 직접 그림(글자 뺌), 지금 색 칸 구분, 흑백 다시 누르면 칼라
log = logging.getLogger("QE.imgedit")
P = QtCore.QPointF
R = QtCore.QRectF

TOOLS = [  # (id, 표시 글자, 설명)
    ("select", "↖", "선택·옮기기 (V) — 그린 것을 옮기거나 Delete 로 지움"),
    ("crop", "⛶", "자르기 (C) — 끌어서 남길 곳을 고름"),
    ("pen", "✎", "펜 (P)"),
    ("marker", "▌", "형광펜 (H)"),
    ("line", "╱", "직선 (L)"),
    ("arrow", "➔", "화살표 (A)"),
    ("rect", "▭", "네모 (R)"),
    ("ellipse", "◯", "원 (E)"),
    ("text", "T", "글자 (T) — 누른 곳에 글자 쓰기"),
    ("number", "①", "번호 (N) — 누를 때마다 1, 2, 3…"),
    ("mosaic", "▦", "모자이크 (M) — 끌어서 가릴 곳을 고름"),
    ("pick", "💧", "스포이트 (I) — 그 색을 지금 색으로"),
]
TOOL_KEYS = {"V": "select", "C": "crop", "P": "pen", "H": "marker", "L": "line", "A": "arrow", "R": "rect",
             "E": "ellipse", "T": "text", "N": "number", "M": "mosaic", "I": "pick"}
WRITABLE = None


def writable_formats():
    global WRITABLE
    if WRITABLE is None:
        WRITABLE = {bytes(f).decode("ascii", "ignore").lower() for f in QtGui.QImageWriter.supportedImageFormats()}
    return WRITABLE


def can_edit(path):
    """Qt 가 읽을 수 있는 정지 그림이면 편집 가능 (저장은 쓸 수 있는 형식이 아니면 '다른 이름으로 PNG')"""
    ext = os.path.splitext(path or "")[1].lower().lstrip(".")
    if ext in ("gif", "ico", "psd", "psb", "exr", "hdr", "max", "") or not os.path.isfile(path or ""):
        return False
    fm = {bytes(f).decode("ascii", "ignore").lower() for f in QtGui.QImageReader.supportedImageFormats()}
    return ext in fm or (ext in ("jpg", "jpeg") and "jpeg" in fm)


# ---------------------------------------------------------------- 아이콘 (1.1.0 — 글꼴 기호는 작고 흐려 직접 그림, 20칸 기준)
def _ic(draw, color, sz=22):
    pm = QtGui.QPixmap(sz * 2, sz * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(sz * 2 / 20.0, sz * 2 / 20.0)
    draw(p, QtGui.QColor(color))
    p.end()
    pm.setDevicePixelRatio(2)
    return QtGui.QIcon(pm)


def _pn(c, w=1.6):
    return QtGui.QPen(c, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)


def _d_select(p, c):
    p.setPen(_pn(c, 1.0)); p.setBrush(c)
    p.drawPolygon(QtGui.QPolygonF([P(5, 2.5), P(5, 16), P(8.4, 12.8), P(10.8, 18), P(13, 17), P(10.6, 11.9), P(15, 11.6)]))


def _d_crop(p, c):
    p.setPen(_pn(c, 2.0)); p.setBrush(Qt.NoBrush)
    p.drawPolyline(QtGui.QPolygonF([P(5.5, 1.5), P(5.5, 14.5), P(18.5, 14.5)]))
    p.drawPolyline(QtGui.QPolygonF([P(1.5, 5.5), P(14.5, 5.5), P(14.5, 18.5)]))


def _d_pen(p, c):
    p.setPen(_pn(c, 1.3)); p.setBrush(Qt.NoBrush)
    p.drawPolygon(QtGui.QPolygonF([P(14.5, 2.5), P(17.5, 5.5), P(7, 16), P(3, 17), P(4, 13)]))
    p.drawLine(P(12.5, 4.5), P(15.5, 7.5))
    p.setBrush(c); p.drawPolygon(QtGui.QPolygonF([P(3, 17), P(4, 13), P(7, 16)]))


def _d_marker(p, c):
    """형광펜 (그림판처럼): 아래로 향한 굵은 펜 몸통 + 넓고 비스듬한 노란 끝 + 노란 줄"""
    hl = QtGui.QColor("#f6c915")
    p.setPen(_pn(c, 1.3)); p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(R(5.5, 1.5, 9, 7.5), 1.2, 1.2)                     # 뚜껑 쪽 몸통
    p.drawPolygon(QtGui.QPolygonF([P(5.5, 9), P(14.5, 9), P(13, 12.5), P(7, 12.5)]))   # 목
    p.setPen(_pn(c, 1.0)); p.setBrush(hl)
    p.drawPolygon(QtGui.QPolygonF([P(7, 12.5), P(13, 12.5), P(13, 15.2), P(7, 16.6)]))   # 넓은 비스듬한 끝
    p.setPen(Qt.NoPen); p.setBrush(hl)
    p.drawRect(R(2, 17.6, 16, 1.8))


def _d_line(p, c):
    p.setPen(_pn(c, 2.0)); p.drawLine(P(3.5, 16.5), P(16.5, 3.5))


def _d_arrow(p, c):
    p.setPen(_pn(c, 2.0)); p.drawLine(P(3.5, 16.5), P(13.5, 6.5))
    p.setPen(_pn(c, 1.0)); p.setBrush(c)
    p.drawPolygon(QtGui.QPolygonF([P(17, 3), P(9.5, 5.2), P(14.8, 10.5)]))


def _d_rect(p, c):
    p.setPen(_pn(c, 1.9)); p.setBrush(Qt.NoBrush); p.drawRect(R(3, 5, 14, 10))


def _d_ellipse(p, c):
    p.setPen(_pn(c, 1.9)); p.setBrush(Qt.NoBrush); p.drawEllipse(R(2.5, 4.5, 15, 11))


def _d_text(p, c):
    f = QtGui.QFont("Times New Roman"); f.setPixelSize(17); f.setBold(True)
    p.setFont(f); p.setPen(c); p.drawText(R(0, 0, 20, 20), Qt.AlignCenter, "T")


def _d_number(p, c):
    p.setPen(Qt.NoPen); p.setBrush(c); p.drawEllipse(R(2.5, 2.5, 15, 15))
    f = QtGui.QFont(); f.setPixelSize(11); f.setBold(True)
    p.setFont(f); p.setPen(QtGui.QColor("#ffffff") if c.lightness() < 140 else QtGui.QColor("#000000"))
    p.drawText(R(2.5, 2.5, 15, 15), Qt.AlignCenter, "1")


def _d_mosaic(p, c):
    p.setPen(Qt.NoPen)
    for i in range(3):
        for j in range(3):
            g = QtGui.QColor(c); g.setAlpha((70, 160, 255)[(i + j * 2) % 3]); p.setBrush(g)
            p.drawRect(R(2.5 + i * 5, 2.5 + j * 5, 4.6, 4.6))


def _d_pick(p, c):
    """스포이트: 오른쪽 위 고무 머리 + 비스듬한 유리관 + 왼쪽 아래 뾰족한 끝"""
    p.setPen(Qt.NoPen); p.setBrush(c)
    p.drawEllipse(R(12.2, 1.8, 6, 6))
    p.drawPolygon(QtGui.QPolygonF([P(10.2, 6.6), P(13.4, 9.8), P(14.6, 8.6), P(11.4, 5.4)]))   # 목
    p.setPen(_pn(c, 1.3)); p.setBrush(Qt.NoBrush)
    p.drawPolygon(QtGui.QPolygonF([P(11.6, 8.0), P(4.6, 15.0), P(3.6, 17.4), P(6.0, 16.4), P(13.0, 9.4)]))   # 관
    p.setPen(Qt.NoPen); p.setBrush(c)
    p.drawPolygon(QtGui.QPolygonF([P(6.6, 13.0), P(4.6, 15.0), P(3.6, 17.4), P(6.0, 16.4), P(8.0, 14.4)]))   # 끝에 든 색


def _d_undo(p, c, redo=False):
    if redo:
        p.translate(20, 0); p.scale(-1, 1)
    p.setPen(_pn(c, 2.0)); p.setBrush(Qt.NoBrush)
    path = QtGui.QPainterPath(P(6, 8))
    path.lineTo(12, 8)
    path.cubicTo(P(17.5, 8), P(17.5, 16), P(12, 16))
    path.lineTo(8, 16)
    p.drawPath(path)
    p.setPen(_pn(c, 1.0)); p.setBrush(c)
    p.drawPolygon(QtGui.QPolygonF([P(2, 8), P(7, 4), P(7, 12)]))


def _d_flip(p, c, horizontal=True):
    if horizontal:   # 가운데 세로 점선 + 왼쪽 채운 세모 / 오른쪽 빈 세모
        p.setPen(QtGui.QPen(c, 1.2, Qt.DashLine)); p.drawLine(P(10, 2), P(10, 18))
        p.setPen(_pn(c, 1.0)); p.setBrush(c)
        p.drawPolygon(QtGui.QPolygonF([P(8.5, 4), P(8.5, 16), P(2, 16)]))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(QtGui.QPolygonF([P(11.5, 4), P(11.5, 16), P(18, 16)]))
    else:            # 가운데 가로 점선 + 위 채운 세모 / 아래 빈 세모
        p.setPen(QtGui.QPen(c, 1.2, Qt.DashLine)); p.drawLine(P(2, 10), P(18, 10))
        p.setPen(_pn(c, 1.0)); p.setBrush(c)
        p.drawPolygon(QtGui.QPolygonF([P(4, 8.5), P(16, 8.5), P(16, 2)]))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(QtGui.QPolygonF([P(4, 11.5), P(16, 11.5), P(16, 18)]))


TOOL_DRAW = {"select": _d_select, "crop": _d_crop, "pen": _d_pen, "marker": _d_marker, "line": _d_line, "arrow": _d_arrow,
             "rect": _d_rect, "ellipse": _d_ellipse, "text": _d_text, "number": _d_number, "mosaic": _d_mosaic, "pick": _d_pick}


def tool_icon_of(tid, color, sz=22):
    return _ic(TOOL_DRAW[tid], color, sz)


def undo_icon(color, redo=False, sz=20):
    return _ic(lambda p, c: _d_undo(p, c, redo), color, sz)


# ---------------------------------------------------------------- 그림 계산
def _argb(img):
    return img if img.format() == QtGui.QImage.Format_ARGB32 else img.convertToFormat(QtGui.QImage.Format_ARGB32)


def make_lut(bright=0, contrast=0, gamma=1.0):
    """bright·contrast = -100~100, gamma 0.1~3 → 256칸 bytes"""
    c = max(-99.0, min(99.0, contrast)) / 100.0
    k = (1 + c) / (1 - c)
    b = bright / 100.0
    g = max(0.05, gamma)
    out = bytearray(256)
    for v in range(256):
        x = v / 255.0
        x = (x - 0.5) * k + 0.5 + b
        x = min(1.0, max(0.0, x))
        x = x ** (1.0 / g)
        out[v] = int(round(x * 255))
    return bytes(out)


def apply_lut(img, lut):
    """B·G·R 채널에만 표 적용 (투명도 그대로). 바이트 건너뛰기 자르기 + translate"""
    t0 = time.perf_counter()
    img = _argb(img)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    raw = bytearray(bytes(img.constBits())[:bpl * h])
    for ch in (0, 1, 2):
        raw[ch::4] = bytes(raw[ch::4]).translate(lut)
    out = QtGui.QImage(bytes(raw), w, h, bpl, QtGui.QImage.Format_ARGB32).copy()
    log.debug("밝기 표 적용 %dx%d %.0fms", w, h, (time.perf_counter() - t0) * 1000)
    return out


def grayscale(img):
    img = _argb(img)
    g = img.convertToFormat(QtGui.QImage.Format_Grayscale8).convertToFormat(QtGui.QImage.Format_ARGB32)
    if img.hasAlphaChannel():
        p = QtGui.QPainter(g)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, img)
        p.end()
    return g


def pixelate(img, rect, block=None):
    """img 의 rect 부분을 모자이크 (작게 줄였다 가장 가까운 픽셀로 키움)"""
    rect = rect.intersected(img.rect())
    if rect.width() < 2 or rect.height() < 2:
        return img
    block = block or max(6, min(rect.width(), rect.height()) // 12)
    part = img.copy(rect)
    small = part.scaled(max(1, rect.width() // block), max(1, rect.height() // block), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    big = small.scaled(rect.width(), rect.height(), Qt.IgnoreAspectRatio, Qt.FastTransformation)
    out = img.copy()
    p = QtGui.QPainter(out)
    p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
    p.drawImage(rect.topLeft(), big)
    p.end()
    return out


# ---------------------------------------------------------------- 표시 물체
FLAGS = QtWidgets.QGraphicsItem.ItemIsSelectable | QtWidgets.QGraphicsItem.ItemIsMovable


def _pen(color, width, cap=Qt.RoundCap):
    return QtGui.QPen(QtGui.QColor(color), width, Qt.SolidLine, cap, Qt.RoundJoin)


class ArrowItem(QtWidgets.QGraphicsPathItem):
    def __init__(self, p1, p2, color, width):
        super().__init__()
        self.p1, self.p2, self.color, self.w = P(p1), P(p2), QtGui.QColor(color), width
        self.setFlags(FLAGS)
        self.rebuild()

    def set_end(self, p2):
        self.p2 = P(p2)
        self.rebuild()

    def set_style(self, color=None, width=None):
        if color is not None:
            self.color = QtGui.QColor(color)
        if width is not None:
            self.w = width
        self.rebuild()

    def rebuild(self):
        a, b = self.p1, self.p2
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        head = max(10.0, self.w * 4.0)
        base = P(b.x() - head * 0.8 * math.cos(ang), b.y() - head * 0.8 * math.sin(ang))
        path = QtGui.QPainterPath(a)
        path.lineTo(base)
        tip = QtGui.QPolygonF([b, P(b.x() - head * math.cos(ang - 0.45), b.y() - head * math.sin(ang - 0.45)),
                               P(b.x() - head * math.cos(ang + 0.45), b.y() - head * math.sin(ang + 0.45))])
        path.addPolygon(tip)
        path.closeSubpath()
        self.setPath(path)
        self.setPen(_pen(self.color, self.w))
        self.setBrush(QtGui.QBrush(self.color))

    def paint(self, painter, option, widget=None):   # 열린 선은 채우지 않게: 선 + 머리 따로
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(_pen(self.color, self.w))
        a, b = self.p1, self.p2
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        head = max(10.0, self.w * 4.0)
        painter.drawLine(a, P(b.x() - head * 0.8 * math.cos(ang), b.y() - head * 0.8 * math.sin(ang)))
        painter.setPen(_pen(self.color, 1))
        painter.setBrush(self.color)
        painter.drawPolygon(QtGui.QPolygonF([b, P(b.x() - head * math.cos(ang - 0.45), b.y() - head * math.sin(ang - 0.45)),
                                             P(b.x() - head * math.cos(ang + 0.45), b.y() - head * math.sin(ang + 0.45))]))
        if self.isSelected():
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 120, 215), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())


class NumberItem(QtWidgets.QGraphicsItem):
    def __init__(self, n, color, width):
        super().__init__()
        self.n, self.color, self.w = n, QtGui.QColor(color), width
        self.setFlags(FLAGS)

    def radius(self):
        return max(12.0, self.w * 3.5)

    def set_style(self, color=None, width=None):
        self.prepareGeometryChange()
        if color is not None:
            self.color = QtGui.QColor(color)
        if width is not None:
            self.w = width
        self.update()

    def boundingRect(self):
        r = self.radius() + 2
        return R(-r, -r, r * 2, r * 2)

    def paint(self, painter, option, widget=None):
        r = self.radius()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2))
        painter.setBrush(self.color)
        painter.drawEllipse(P(0, 0), r, r)
        f = painter.font()
        f.setBold(True)
        f.setPixelSize(int(r * 1.15))
        painter.setFont(f)
        lum = 0.299 * self.color.red() + 0.587 * self.color.green() + 0.114 * self.color.blue()
        painter.setPen(QtGui.QColor("#000000" if lum > 170 else "#ffffff"))
        painter.drawText(R(-r, -r, r * 2, r * 2), Qt.AlignCenter, str(self.n))
        if self.isSelected():
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 120, 215), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())


def set_item_style(it, color, width):
    """선택한 물체의 색·굵기 바꾸기 (종류별)"""
    if isinstance(it, (ArrowItem, NumberItem)):
        it.set_style(color, width)
    elif isinstance(it, QtWidgets.QGraphicsTextItem):
        it.setDefaultTextColor(QtGui.QColor(color))
        f = it.font(); f.setPixelSize(max(10, int(width * 5))); it.setFont(f)
    elif isinstance(it, QtWidgets.QAbstractGraphicsShapeItem):
        marker = it.data(1) == "marker"
        c = QtGui.QColor(color)
        if marker:
            c.setAlpha(110)
        pen = it.pen(); pen.setColor(c); pen.setWidthF(width * (4 if marker else 1)); it.setPen(pen)


# ---------------------------------------------------------------- 되돌리기
class AddCmd(QtGui.QUndoCommand):
    def __init__(self, ed, items, text):
        super().__init__(text)
        self.ed, self.items = ed, list(items)

    def redo(self):
        for it in self.items:
            if it.scene() is None:
                self.ed.scene.addItem(it)

    def undo(self):
        for it in self.items:
            if it.scene() is not None:
                self.ed.scene.removeItem(it)


class DelCmd(AddCmd):
    def redo(self):
        AddCmd.undo(self)

    def undo(self):
        AddCmd.redo(self)


class MoveCmd(QtGui.QUndoCommand):
    def __init__(self, moves):
        super().__init__(T("옮기기"))
        self.moves = moves   # [(물체, 전, 후)]

    def redo(self):
        for it, _a, b in self.moves:
            it.setPos(b)

    def undo(self):
        for it, a, _b in self.moves:
            it.setPos(a)


class RasterCmd(QtGui.QUndoCommand):
    """바탕 그림 바꾸기. flatten=True 면 표시 물체를 먼저 합침(되돌리면 물체도 돌아옴)"""

    def __init__(self, ed, text, fn, flatten):
        super().__init__(text)
        self.ed, self.fn, self.flatten = ed, fn, flatten
        self.before = ed.base
        self.items = ed.marks() if flatten else []
        self.after = None

    def redo(self):
        src = self.ed.flatten() if self.flatten else self.before
        if self.after is None:
            t0 = time.perf_counter()
            self.after = self.fn(src)
            log.info("그림 바꿈 '%s' %dx%d → %dx%d %.0fms", self.text(), src.width(), src.height(),
                     self.after.width(), self.after.height(), (time.perf_counter() - t0) * 1000)
        for it in self.items:
            if it.scene() is not None:
                self.ed.scene.removeItem(it)
        self.ed.set_base(self.after)

    def undo(self):
        self.ed.set_base(self.before)
        for it in self.items:
            if it.scene() is None:
                self.ed.scene.addItem(it)


# ---------------------------------------------------------------- 보기 (도구 처리)
class EditView(QtWidgets.QGraphicsView):
    def __init__(self, ed):
        super().__init__(ed.scene)
        self.ed = ed
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
        self.setMouseTracking(True)
        self.drag = None          # 그리는 중인 물체 / 상태
        self.start = None
        self.pan = None
        self.moving = None
        self.temp = None          # 자르기·모자이크 점선 네모
        self.auto_fit = True
        c1, c2 = QtGui.QColor("#ffffff"), QtGui.QColor("#d8d8d8")
        pm = QtGui.QPixmap(16, 16); pm.fill(c1)
        q = QtGui.QPainter(pm); q.fillRect(0, 0, 8, 8, c2); q.fillRect(8, 8, 8, 8, c2); q.end()
        self.checker = QtGui.QBrush(pm)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, self.palette().color(QtGui.QPalette.Dark))
        painter.fillRect(self.ed.scene.sceneRect().intersected(rect), self.checker)

    def fit(self):
        self.auto_fit = True
        self.fitInView(self.ed.scene.sceneRect(), Qt.KeepAspectRatio)
        self.ed.zoom_changed()

    def actual(self):
        self.auto_fit = False
        self.resetTransform()
        self.ed.zoom_changed()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.auto_fit:
            self.fit()

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if not d:
            return
        f = 1.2 if d > 0 else 1 / 1.2
        s = self.transform().m11() * f
        if 0.02 <= s <= 64:
            self.auto_fit = False
            self.scale(f, f)
            self.ed.zoom_changed()

    # --- 마우스
    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self.pan = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)
        tool = self.ed.tool
        p = self.mapToScene(e.position().toPoint())
        self.start = p
        col, w = self.ed.color, self.ed.pen_w
        if tool == "select":
            super().mousePressEvent(e)
            self.moving = [(it, it.pos()) for it in self.ed.scene.selectedItems()]
            return
        if tool == "pick":
            img = self.ed.flatten()
            x, y = int(p.x()), int(p.y())
            if 0 <= x < img.width() and 0 <= y < img.height():
                c = img.pixelColor(x, y)
                c.setAlpha(255)
                self.ed.set_color(c)
                log.info("편집 스포이트 (%d,%d) %s", x, y, c.name())
            return
        if tool == "text":
            hit = [it for it in self.ed.scene.items(p) if isinstance(it, QtWidgets.QGraphicsTextItem)]
            if hit:
                hit[0].setTextInteractionFlags(Qt.TextEditorInteraction)
                hit[0].setFocus()
                return super().mousePressEvent(e)
            it = QtWidgets.QGraphicsTextItem()
            it.setDefaultTextColor(col)
            f = it.font(); f.setPixelSize(max(10, int(w * 5))); f.setBold(True); it.setFont(f)
            it.setPos(p)
            it.setFlags(FLAGS | QtWidgets.QGraphicsItem.ItemIsFocusable)
            it.setTextInteractionFlags(Qt.TextEditorInteraction)
            self.ed.undo.push(AddCmd(self.ed, [it], T("글자")))
            it.setFocus()
            return
        if tool == "number":
            n = 1 + max([it.n for it in self.ed.scene.items() if isinstance(it, NumberItem)] or [0])
            it = NumberItem(n, col, w)
            it.setPos(p)
            self.ed.undo.push(AddCmd(self.ed, [it], T("번호")))
            return
        if tool in ("pen", "marker"):
            path = QtGui.QPainterPath(p)
            it = QtWidgets.QGraphicsPathItem()
            it.setPath(path)   # ★PySide6 6.11: QGraphicsPathItem(path) 로 만들면 경로가 비어 (0,0) 부터 선이 생김 (실측) → setPath 따로
            c = QtGui.QColor(col)
            if tool == "marker":
                c.setAlpha(110)
                it.setData(1, "marker")
            it.setPen(_pen(c, w * (4 if tool == "marker" else 1), Qt.FlatCap if tool == "marker" else Qt.RoundCap))
            it.setFlags(FLAGS)
            self.ed.scene.addItem(it)
            self.drag = it
            return
        if tool == "line":
            it = QtWidgets.QGraphicsLineItem(QtCore.QLineF(p, p))
            it.setPen(_pen(col, w)); it.setFlags(FLAGS)
        elif tool == "arrow":
            it = ArrowItem(p, p, col, w)
        elif tool == "rect":
            it = QtWidgets.QGraphicsRectItem(R(p, p))
            it.setPen(_pen(col, w, Qt.SquareCap)); it.setFlags(FLAGS)
        elif tool == "ellipse":
            it = QtWidgets.QGraphicsEllipseItem(R(p, p))
            it.setPen(_pen(col, w)); it.setFlags(FLAGS)
        elif tool in ("crop", "mosaic"):
            it = QtWidgets.QGraphicsRectItem(R(p, p))
            pen = QtGui.QPen(QtGui.QColor(0, 120, 215), 0, Qt.DashLine)
            it.setPen(pen)
            it.setBrush(QtGui.QColor(0, 120, 215, 40))
            it.setZValue(1e6)
            self.ed.scene.addItem(it)
            self.temp = it
            return
        else:
            return
        self.ed.scene.addItem(it)
        self.drag = it

    def mouseMoveEvent(self, e):
        if self.pan is not None:
            d = e.position() - self.pan
            self.pan = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        p = self.mapToScene(e.position().toPoint())
        self.ed.show_pos(p)
        it = self.drag
        if it is None and self.temp is None:
            return super().mouseMoveEvent(e)
        a = self.start
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        if self.temp is not None:
            self.temp.setRect(R(a, p).normalized())
            return
        if isinstance(it, QtWidgets.QGraphicsPathItem) and not isinstance(it, ArrowItem):
            path = it.path(); path.lineTo(p); it.setPath(path)
        elif isinstance(it, QtWidgets.QGraphicsLineItem):
            it.setLine(QtCore.QLineF(a, self._snap(a, p) if shift else p))
        elif isinstance(it, ArrowItem):
            it.set_end(self._snap(a, p) if shift else p)
        elif isinstance(it, (QtWidgets.QGraphicsRectItem, QtWidgets.QGraphicsEllipseItem)):
            if shift:   # 정사각형·정원
                s = max(abs(p.x() - a.x()), abs(p.y() - a.y()))
                p = P(a.x() + math.copysign(s, p.x() - a.x()), a.y() + math.copysign(s, p.y() - a.y()))
            it.setRect(R(a, p).normalized())

    @staticmethod
    def _snap(a, p):
        """Shift: 45도 단위"""
        dx, dy = p.x() - a.x(), p.y() - a.y()
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        ln = math.hypot(dx, dy)
        return P(a.x() + ln * math.cos(ang), a.y() + ln * math.sin(ang))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton and self.pan is not None:
            self.pan = None
            self.setCursor(Qt.ArrowCursor)
            return
        if e.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(e)
        tool = self.ed.tool
        if tool == "select":
            super().mouseReleaseEvent(e)
            mv = [(it, a, it.pos()) for it, a in (self.moving or []) if it.pos() != a]
            self.moving = None
            if mv:
                self.ed.undo.push(MoveCmd(mv))
            return
        if self.temp is not None:
            r = self.temp.rect().toAlignedRect().intersected(self.ed.base.rect())
            self.ed.scene.removeItem(self.temp)
            self.temp = None
            if r.width() >= 4 and r.height() >= 4:
                if tool == "crop":
                    self.ed.do_raster(T("자르기"), lambda img, r=r: img.copy(r), flatten=True)
                else:
                    self.ed.do_raster(T("모자이크"), lambda img, r=r: pixelate(img, r), flatten=False)
            return
        it, self.drag = self.drag, None
        if it is None:
            return
        br = it.boundingRect()
        if br.width() < 3 and br.height() < 3 and tool not in ("pen", "marker"):
            self.ed.scene.removeItem(it)
            return
        self.ed.scene.removeItem(it)
        self.ed.undo.push(AddCmd(self.ed, [it], dict((t, d) for t, _g, d in TOOLS).get(tool, tool).split(" (")[0]))


# ---------------------------------------------------------------- 대화 상자
class ResizeDialog(QtWidgets.QDialog):
    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("크기 바꾸기"))
        self.w0, self.h0 = w, h
        f = QtWidgets.QFormLayout(self)
        self.sw = QtWidgets.QSpinBox(); self.sw.setRange(1, 30000); self.sw.setValue(w)
        self.sh = QtWidgets.QSpinBox(); self.sh.setRange(1, 30000); self.sh.setValue(h)
        self.pc = QtWidgets.QSpinBox(); self.pc.setRange(1, 1000); self.pc.setValue(100); self.pc.setSuffix(" %")
        self.keep = QtWidgets.QCheckBox(T("비율 유지")); self.keep.setChecked(True)
        f.addRow(T("가로"), self.sw); f.addRow(T("세로"), self.sh); f.addRow(T("비율"), self.pc); f.addRow("", self.keep)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._busy = False
        self.sw.valueChanged.connect(lambda v: self._sync("w"))
        self.sh.valueChanged.connect(lambda v: self._sync("h"))
        self.pc.valueChanged.connect(lambda v: self._sync("p"))

    def _sync(self, src):
        if self._busy:
            return
        self._busy = True
        try:
            if src == "p":
                self.sw.setValue(max(1, round(self.w0 * self.pc.value() / 100)))
                self.sh.setValue(max(1, round(self.h0 * self.pc.value() / 100)))
            elif self.keep.isChecked():
                if src == "w":
                    self.sh.setValue(max(1, round(self.h0 * self.sw.value() / self.w0)))
                else:
                    self.sw.setValue(max(1, round(self.w0 * self.sh.value() / self.h0)))
        finally:
            self._busy = False

    def wh(self):
        return self.sw.value(), self.sh.value()


class AdjustDialog(QtWidgets.QDialog):
    """밝기·대비·감마 — 움직이면 바로 그림에 보임(확인 전까지 임시)"""

    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed
        self.setWindowTitle(T("밝기·대비"))
        self.orig = ed.base
        small = self.orig
        if small.width() * small.height() > 2_000_000:   # 미리보기는 줄인 그림으로 (빠르게)
            small = small.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.small = small
        f = QtWidgets.QFormLayout(self)
        self.sl = {}
        for k, lo, hi, v in (("bright", -100, 100, 0), ("contrast", -100, 100, 0), ("gamma", 10, 300, 100)):
            s = QtWidgets.QSlider(Qt.Horizontal); s.setRange(lo, hi); s.setValue(v)
            s.valueChanged.connect(self._preview)
            self.sl[k] = s
        f.addRow(T("밝기"), self.sl["bright"]); f.addRow(T("대비"), self.sl["contrast"]); f.addRow(T("감마"), self.sl["gamma"])
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Reset)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        bb.button(QtWidgets.QDialogButtonBox.Reset).clicked.connect(self._reset)
        f.addRow(bb)

    def values(self):
        return self.sl["bright"].value(), self.sl["contrast"].value(), self.sl["gamma"].value() / 100.0

    def _reset(self):
        self.sl["bright"].setValue(0); self.sl["contrast"].setValue(0); self.sl["gamma"].setValue(100)

    def _preview(self):
        img = apply_lut(self.small, make_lut(*self.values()))
        if img.size() != self.orig.size():
            img = img.scaled(self.orig.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.ed.pix.setPixmap(QtGui.QPixmap.fromImage(img))

    def done(self, r):
        self.ed.pix.setPixmap(QtGui.QPixmap.fromImage(self.orig))   # 임시 보기 되돌림 (확인이면 RasterCmd 가 다시 그림)
        super().done(r)


# ---------------------------------------------------------------- 창
def _sw_icon(c, sz=18):
    pm = QtGui.QPixmap(sz, sz)
    pm.fill(QtGui.QColor(c))
    p = QtGui.QPainter(pm); p.setPen(QtGui.QColor("#666666")); p.drawRect(0, 0, sz - 1, sz - 1); p.end()
    return QtGui.QIcon(pm)


class ImageEditor(QtWidgets.QMainWindow):
    saved = QtCore.Signal(str)

    def __init__(self, path, parent=None, on_saved=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.path = path
        self.on_saved = on_saved
        self.tool = "pen"
        self.color = QtGui.QColor("#e53935")
        self.pen_w = 4
        self.ask_overwrite = True    # 시험에서는 끔
        self.scene = QtWidgets.QGraphicsScene(self)
        self.undo = QtGui.QUndoStack(self)
        self.undo.cleanChanged.connect(lambda _c: self._title())
        rd = QtGui.QImageReader(path)
        rd.setAutoTransform(True)
        img = rd.read()
        if img.isNull():
            raise ValueError(T("이 그림을 읽을 수 없습니다") + f": {rd.errorString()}")
        del rd
        self.base = _argb(img)
        self.pix = self.scene.addPixmap(QtGui.QPixmap.fromImage(self.base))
        self.pix.setZValue(-1e6)
        self.pix.setTransformationMode(Qt.SmoothTransformation)
        self.scene.setSceneRect(R(self.base.rect()))
        self.view = EditView(self)
        self.setCentralWidget(self.view)
        self._build_bars()
        self.set_tool("pen")
        self.resize(1100, 760)
        self._title()
        log.info("그림 편집 열기 %s %dx%d", path, self.base.width(), self.base.height())
        QtCore.QTimer.singleShot(0, self.view.fit)

    # --- 바탕 그림
    def set_base(self, img):
        self.base = img
        self.pix.setPixmap(QtGui.QPixmap.fromImage(img))
        self.scene.setSceneRect(R(img.rect()))
        self._size_label()
        if self.view.auto_fit:
            self.view.fit()

    def marks(self):
        return [it for it in self.scene.items() if it is not self.pix and it.parentItem() is None and it is not self.view.temp]

    def flatten(self):
        """바탕 + 표시 물체 → 한 장 (선택 표시·글자 커서 없이)"""
        sel = self.scene.selectedItems()
        for it in sel:
            it.setSelected(False)
        foc = self.scene.focusItem()
        self.scene.clearFocus()
        editing = [(it, it.textInteractionFlags()) for it in self.scene.items() if isinstance(it, QtWidgets.QGraphicsTextItem)]
        for it, _f in editing:   # 글자 입력 커서가 저장 그림에 찍히지 않게 (편집 끄고 초점도 뺌)
            it.setTextInteractionFlags(Qt.NoTextInteraction)
            it.clearFocus()
        self.scene.setFocusItem(None)
        out = QtGui.QImage(self.base.size(), QtGui.QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        p = QtGui.QPainter(out)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        p.drawImage(0, 0, self.base)
        self.pix.setVisible(False)
        texts = [it for it, _f in editing if it.isVisible()]
        for it in texts:   # 글자는 따로 그림 — 장면 그리기는 편집을 꺼도 입력 커서를 찍음(실측)
            it.setVisible(False)
        self.scene.render(p, R(out.rect()), R(out.rect()))
        for it in texts:
            it.setVisible(True)
            p.save()
            p.setTransform(it.sceneTransform(), True)
            ctx = QtGui.QAbstractTextDocumentLayout.PaintContext()
            ctx.palette.setColor(QtGui.QPalette.Text, it.defaultTextColor())
            ctx.cursorPosition = -1
            it.document().documentLayout().draw(p, ctx)
            p.restore()
        self.pix.setVisible(True)
        p.end()
        for it, f in editing:
            it.setTextInteractionFlags(f)
        for it in sel:
            it.setSelected(True)
        if foc is not None:
            foc.setFocus()
        return out

    def do_raster(self, text, fn, flatten):
        self.undo.push(RasterCmd(self, text, fn, flatten))

    # --- 막대
    def _build_bars(self):
        st = ("QToolButton{padding:3px 6px; border:1px solid transparent; border-radius:4px;}"
              "QToolButton:hover{border-color:palette(mid);}"
              "QToolButton:checked{background:palette(highlight); color:palette(highlighted-text);}")
        tb = QtWidgets.QToolBar(T("도구")); tb.setObjectName("editTools"); tb.setMovable(False)
        tb.setOrientation(Qt.Vertical)
        tb.setStyleSheet(st)
        tb.setIconSize(QtCore.QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        fg = self.palette().color(QtGui.QPalette.ButtonText).name()
        self.tool_acts = {}
        grp = QtGui.QActionGroup(self); grp.setExclusive(True)
        for tid, glyph, tip in TOOLS:
            a = QtGui.QAction(tool_icon_of(tid, fg), T(tip).split(" (")[0], self)
            a.setCheckable(True)
            a.setToolTip(T(tip))
            a.triggered.connect(lambda _=False, tid=tid: self.set_tool(tid))
            grp.addAction(a); tb.addAction(a)
            self.tool_acts[tid] = a
        self.addToolBar(Qt.LeftToolBarArea, tb)

        top = QtWidgets.QToolBar(T("편집")); top.setObjectName("editTop"); top.setMovable(False)
        top.setStyleSheet(st)
        top.setToolButtonStyle(Qt.ToolButtonTextOnly)
        ua = self.undo.createUndoAction(self, T("되돌리기")); ua.setShortcut(QtGui.QKeySequence.Undo)
        ra = self.undo.createRedoAction(self, T("다시 하기")); ra.setShortcuts([QtGui.QKeySequence("Ctrl+Y"), QtGui.QKeySequence("Ctrl+Shift+Z")])
        ua.setIcon(undo_icon(fg)); ra.setIcon(undo_icon(fg, redo=True))   # 1.1.0: 글자 빼고 아이콘만 (사용자)
        ua.setToolTip(T("되돌리기") + " (Ctrl+Z)"); ra.setToolTip(T("다시 하기") + " (Ctrl+Y)")
        self.undo.undoTextChanged.connect(lambda _t: ua.setToolTip(T("되돌리기") + " (Ctrl+Z)"))
        self.undo.redoTextChanged.connect(lambda _t: ra.setToolTip(T("다시 하기") + " (Ctrl+Y)"))
        top.addAction(ua); top.addAction(ra)
        for a_ in (ua, ra):
            top.widgetForAction(a_).setToolButtonStyle(Qt.ToolButtonIconOnly)
        top.addSeparator()
        for txt, sc, fn in ((T("저장"), "Ctrl+S", lambda: self.save()), (T("다른 이름으로 저장…"), "Ctrl+Shift+S", lambda: self.save_as()),
                            (T("복사"), "", lambda: self.copy_clipboard())):   # ★QAction.triggered 가 넘기는 참·거짓이 save_as(dst=False) 로 들어가 TypeError 였음 (사용자 로그)   # 1.1.0: 창이 좁으면 맨 오른쪽이 잘려 안 보여 앞으로
            a = QtGui.QAction(txt, self)
            if sc:
                a.setShortcut(QtGui.QKeySequence(sc))
                a.setToolTip(f"{txt} ({sc})")
            a.triggered.connect(fn); top.addAction(a)
        top.addSeparator()
        top.addWidget(QtWidgets.QLabel(" " + T("지금 색") + " "))   # 1.1.0: 지금 색 칸과 아래 자주 쓰는 색이 헷갈려(사용자) 이름표·구분선
        self.b_color = QtWidgets.QToolButton(); self.b_color.setToolTip(T("지금 색 — 눌러서 다른 색 고르기"))
        self.b_color.setIconSize(QtCore.QSize(26, 26))
        self.b_color.setStyleSheet("QToolButton{border:2px solid palette(text); border-radius:4px; padding:1px;}")
        self.b_color.clicked.connect(self.pick_color)
        top.addWidget(self.b_color)
        top.addSeparator()
        b_pal = QtWidgets.QToolButton(); b_pal.setText("🎨")   # 사용자: 색 칸을 누르면 팔레트가 나오는 걸 모름 → 자주 쓰는 색(빨강) 앞에 팔레트 그림만
        f_ = b_pal.font(); f_.setPointSizeF(f_.pointSizeF() + 3); b_pal.setFont(f_)
        b_pal.setToolTip(T("색 고르기 (팔레트)")); b_pal.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b_pal.clicked.connect(self.pick_color)
        top.addWidget(b_pal)
        self.b_pal = b_pal
        self.recent = []
        self.recent_btns = []
        for c in ("#e53935", "#fdd835", "#43a047", "#1e88e5", "#000000", "#ffffff"):
            b = QtWidgets.QToolButton(); b.setIcon(_sw_icon(c, 14)); b.setToolTip(c)
            b.clicked.connect(lambda _=False, c=c: self.set_color(QtGui.QColor(c)))
            top.addWidget(b)
        top.addSeparator()
        top.addWidget(QtWidgets.QLabel(" " + T("굵기") + " "))
        self.sp_w = QtWidgets.QSpinBox(); self.sp_w.setRange(1, 60); self.sp_w.setValue(self.pen_w)
        self.sp_w.valueChanged.connect(self.set_width)
        top.addWidget(self.sp_w)
        self.addToolBar(Qt.TopToolBarArea, top)   # 1.1.0: 한 줄이면 창이 좁을 때 오른쪽이 잘려 두 줄로
        self.addToolBarBreak(Qt.TopToolBarArea)
        top2 = QtWidgets.QToolBar(T("그림 손질")); top2.setObjectName("editTop2"); top2.setMovable(False)
        top2.setStyleSheet(st)
        top2.setToolButtonStyle(Qt.ToolButtonTextOnly)
        top = top2
        import imginspect   # 미리보기와 같은 회전 아이콘
        fg = self.palette().color(QtGui.QPalette.ButtonText).name()
        for txt, tip, fn, ic in (("↺", T("왼쪽으로 돌리기"), lambda: self.rotate(False), imginspect.rotate_icon(False, fg)),
                                 ("↻", T("오른쪽으로 돌리기"), lambda: self.rotate(True), imginspect.rotate_icon(True, fg)),
                                 ("⇆", T("좌우 뒤집기"), lambda: self.flip(True), _ic(lambda p, c: _d_flip(p, c, True), fg, 20)),
                                 ("⇅", T("상하 뒤집기"), lambda: self.flip(False), _ic(lambda p, c: _d_flip(p, c, False), fg, 20))):
            a = QtGui.QAction(txt, self); a.setToolTip(tip); a.triggered.connect(fn)
            if ic is not None:
                a.setIcon(ic)
            top.addAction(a)
            if ic is not None:
                top.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        top.addSeparator()
        for txt, fn in ((T("크기…"), self.resize_dialog), (T("밝기·대비…"), self.adjust_dialog)):
            a = QtGui.QAction(txt, self); a.triggered.connect(fn); top.addAction(a)
        self.a_gray = QtGui.QAction(T("흑백"), self)   # 1.1.0: 다시 누르면 칼라로 (사용자)
        self.a_gray.setCheckable(True)
        self.a_gray.setToolTip(T("흑백 — 다시 누르면 칼라로"))
        self.a_gray.triggered.connect(self.toggle_gray)
        top.addAction(self.a_gray)
        self.gray_cmd = None
        self.undo.indexChanged.connect(lambda _i: self._sync_gray())
        top.addSeparator()
        for txt, tip, fn in ((T("맞춤"), T("창에 맞춤"), self.view.fit), ("1:1", T("실제 크기"), self.view.actual)):
            a = QtGui.QAction(txt, self); a.setToolTip(tip); a.triggered.connect(fn); top.addAction(a)

        self.addToolBar(Qt.TopToolBarArea, top)
        for k, tid in TOOL_KEYS.items():
            sc = QtGui.QShortcut(QtGui.QKeySequence(k), self)
            sc.activated.connect(lambda tid=tid: self._key_tool(tid))
        QtGui.QShortcut(QtGui.QKeySequence.Delete, self).activated.connect(self.delete_selected)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+C"), self).activated.connect(self._ctrl_c)
        self.lb_size = QtWidgets.QLabel(); self.lb_pos = QtWidgets.QLabel(); self.lb_zoom = QtWidgets.QLabel()
        self.lb_msg = QtWidgets.QLabel()
        sb = self.statusBar()
        sb.addWidget(self.lb_size); sb.addWidget(self.lb_pos); sb.addWidget(self.lb_msg, 1); sb.addPermanentWidget(self.lb_zoom)
        self._size_label()
        self.set_color(self.color)

    def _editing_text(self):
        f = self.scene.focusItem()
        return isinstance(f, QtWidgets.QGraphicsTextItem) and bool(f.textInteractionFlags() & Qt.TextEditorInteraction)

    def _key_tool(self, tid):
        if not self._editing_text():
            self.set_tool(tid)

    def _ctrl_c(self):
        if not self._editing_text():
            self.copy_clipboard()

    def set_tool(self, tid):
        self.tool = tid
        self.tool_acts[tid].setChecked(True)
        sel = tid == "select"
        self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag if sel else QtWidgets.QGraphicsView.NoDrag)
        self.view.viewport().setCursor(Qt.ArrowCursor if sel else Qt.CrossCursor)
        if not sel:
            self.scene.clearSelection()
        for it in self.scene.items():   # 글자 편집 끝내기
            if isinstance(it, QtWidgets.QGraphicsTextItem) and tid != "text":
                it.setTextInteractionFlags(Qt.NoTextInteraction)
        log.info("편집 도구 %s", tid)

    def set_color(self, c):
        self.color = QtGui.QColor(c)
        self.b_color.setIcon(_sw_icon(self.color, 26))
        for it in self.scene.selectedItems():
            set_item_style(it, self.color, self.pen_w)

    def set_width(self, v):
        self.pen_w = v
        for it in self.scene.selectedItems():
            set_item_style(it, self.color, self.pen_w)

    def pick_color(self):
        c = QtWidgets.QColorDialog.getColor(self.color, self, T("색 고르기"))
        if c.isValid():
            self.set_color(c)

    def delete_selected(self):
        if self._editing_text():
            return
        its = [it for it in self.scene.selectedItems() if it is not self.pix]
        if its:
            self.undo.push(DelCmd(self, its, T("지우기")))

    # --- 그림 손질
    def rotate(self, cw):
        tr = QtGui.QTransform().rotate(90 if cw else -90)
        self.do_raster(T("돌리기"), lambda img: img.transformed(tr), flatten=True)

    def flip(self, horizontal):
        self.do_raster(T("뒤집기"), lambda img: img.flipped(Qt.Horizontal if horizontal else Qt.Vertical), flatten=True)

    def resize_dialog(self):
        dlg = ResizeDialog(self.base.width(), self.base.height(), self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            w, h = dlg.wh()
            if (w, h) != (self.base.width(), self.base.height()):
                self.do_raster(T("크기 바꾸기"), lambda img: img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation), flatten=True)

    def adjust_dialog(self):
        dlg = AdjustDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            b, c, g = dlg.values()
            if (b, c, g) != (0, 0, 1.0):
                lut = make_lut(b, c, g)
                self.do_raster(T("밝기·대비"), lambda img: apply_lut(img, lut), flatten=False)

    def to_gray(self):
        cmd = RasterCmd(self, T("흑백"), grayscale, flatten=False)
        self.gray_cmd = cmd
        self.undo.push(cmd)

    def _gray_index(self):
        """흑백 명령이 아직 살아 있으면(되돌리지 않음) 그 순번, 아니면 -1"""
        if self.gray_cmd is None:
            return -1
        gi = -1
        for i in range(self.undo.index()):
            c = self.undo.command(i)
            if c is self.gray_cmd:
                gi = i
            elif gi >= 0 and getattr(c, "ungray", False):
                gi = -1
        return gi

    def _sync_gray(self):
        self.a_gray.setChecked(self._gray_index() >= 0)

    def toggle_gray(self, on):
        """흑백 켜기/끄기. 끌 때: 흑백 뒤에 그림 자체를 바꾼 일이 없으면 칼라 그림으로 되돌림(그 뒤 그린 것은 그대로)"""
        gi = self._gray_index()
        if on and gi < 0:
            self.to_gray()
            return
        elif not on and gi >= 0:
            later = [self.undo.command(i) for i in range(gi + 1, self.undo.index())]
            if gi == self.undo.index() - 1:
                self.undo.undo()
            elif not any(isinstance(c, RasterCmd) for c in later):
                color = self.gray_cmd.before
                cmd = RasterCmd(self, T("칼라로"), lambda _img: color, flatten=False)
                cmd.ungray = True
                self.undo.push(cmd)
            else:
                self.lb_msg.setText(T("흑백 다음에 자르기·회전 등을 해서 바로 칼라로 못 돌립니다 — ↶ 되돌리기로 흑백 전까지 돌아가세요"))
                log.info("흑백 끄기 못 함 (뒤에 그림 바꾼 일 있음)")
        self._sync_gray()

    # --- 저장
    def _write(self, dst):
        img = self.flatten()
        ext = os.path.splitext(dst)[1].lower().lstrip(".")
        if ext in ("jpg", "jpeg", "bmp"):
            bg = QtGui.QImage(img.size(), QtGui.QImage.Format_RGB32)
            bg.fill(QtGui.QColor("#ffffff"))
            p = QtGui.QPainter(bg); p.drawImage(0, 0, img); p.end()
            img = bg
        tmp = dst + ".4dir_tmp." + (ext or "png")
        wr = QtGui.QImageWriter(tmp, (ext if ext != "jpg" else "jpeg").encode() or b"png")
        if ext in ("jpg", "jpeg", "webp"):
            wr.setQuality(95)
        ok = wr.write(img)
        err = wr.errorString()
        del wr
        if not ok:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise OSError(err)
        os.replace(tmp, dst)
        log.info("그림 편집 저장 %s %dx%d", dst, img.width(), img.height())
        self.undo.setClean()
        self.lb_msg.setText(T("저장함: {0}").format(os.path.basename(dst)))
        self.saved.emit(dst)
        if self.on_saved:
            try:
                self.on_saved(dst)
            except Exception:
                log.exception("저장 뒤 알림 실패")
        return dst

    def save(self):
        ext = os.path.splitext(self.path)[1].lower().lstrip(".")
        if ext not in writable_formats() and not (ext in ("jpg", "jpeg") and "jpeg" in writable_formats()):
            return self.save_as()
        if self.ask_overwrite:
            msg = T("원본 파일에 덮어씁니다. 되돌릴 수 없습니다.")
            if ext in ("jpg", "jpeg"):
                msg += "\n" + T("JPG 는 다시 압축되고 촬영 정보(EXIF)는 남지 않습니다.")
            r = QtWidgets.QMessageBox.question(self, T("저장"), msg, QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel)
            if r != QtWidgets.QMessageBox.Save:
                return None
        try:
            return self._write(self.path)
        except OSError as ex:
            log.exception("저장 실패 %s", self.path)
            QtWidgets.QMessageBox.warning(self, T("저장"), T("저장하지 못했습니다") + f": {ex}")
            return None

    def default_as_name(self):
        d, nm = os.path.split(self.path)
        stem = os.path.splitext(nm)[0]
        cand = os.path.join(d, stem + "_" + T("편집") + ".png")
        i = 1
        while os.path.exists(cand):
            cand = os.path.join(d, f"{stem}_{T('편집')} ({i}).png")
            i += 1
        return cand

    def save_as(self, dst=None):
        if dst is None:
            dst, _f = QtWidgets.QFileDialog.getSaveFileName(self, T("다른 이름으로 저장"), self.default_as_name(),
                                                           "PNG (*.png);;JPG (*.jpg *.jpeg);;WebP (*.webp);;BMP (*.bmp)")
            if not dst:
                return None
        try:
            out = self._write(dst)
            self.path = dst
            self._title()
            return out
        except OSError as ex:
            log.exception("저장 실패 %s", dst)
            QtWidgets.QMessageBox.warning(self, T("저장"), T("저장하지 못했습니다") + f": {ex}")
            return None

    def copy_clipboard(self):
        QtWidgets.QApplication.clipboard().setImage(self.flatten())
        self.lb_msg.setText(T("클립보드에 복사함"))
        log.info("그림 편집 클립보드 복사 %dx%d", self.base.width(), self.base.height())

    # --- 표시
    def _title(self):
        dirty = "" if self.undo.isClean() else "● "
        self.setWindowTitle(f"{dirty}{os.path.basename(self.path)} — {T('그림 편집')}")

    def _size_label(self):
        self.lb_size.setText(f"{self.base.width()} x {self.base.height()}")

    def show_pos(self, p):
        x, y = int(p.x()), int(p.y())
        self.lb_pos.setText(f"x {x}, y {y}" if 0 <= x < self.base.width() and 0 <= y < self.base.height() else "")

    def zoom_changed(self):
        self.lb_zoom.setText(f"{self.view.transform().m11() * 100:.0f}%")

    def closeEvent(self, e):
        if not self.undo.isClean() and self.ask_overwrite:
            r = QtWidgets.QMessageBox.question(self, T("그림 편집"), T("바꾼 것을 저장할까요?"),
                                               QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel)
            if r == QtWidgets.QMessageBox.Cancel:
                e.ignore()
                return
            if r == QtWidgets.QMessageBox.Save and self.save() is None:
                e.ignore()
                return
        log.info("그림 편집 닫음 %s", self.path)
        self.undo.clear()
        self.scene.clear()
        super().closeEvent(e)


def open_editor(parent, path, on_saved=None):
    """편집 창 — 화면 안에 들어오게 (부모가 오른쪽 끝 작은 미리보기 창이면 그 가운데에 놓여 화면 밖으로 나갔음, 사용자 11/8)"""
    w = ImageEditor(path, parent, on_saved)
    scr = (parent.screen() if parent is not None else None) or QtGui.QGuiApplication.primaryScreen()
    av = scr.availableGeometry()
    ww, hh = min(1100, int(av.width() * 0.9)), min(760, int(av.height() * 0.9))
    w.resize(ww, hh)
    fr = w.frameGeometry()
    fr.moveCenter(av.center())
    w.move(max(av.left(), fr.left()), max(av.top(), fr.top()))
    w.show()
    log.info("편집 창 위치 %s 화면 %s", w.frameGeometry().getRect(), av.getRect())
    return w


def tool_icon(sz=16):
    """붓 + 그림"""
    pm = QtGui.QPixmap(sz * 2, sz * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(sz * 2 / 20.0, sz * 2 / 20.0)
    p.setPen(QtGui.QPen(QtGui.QColor("#475569"), 1.0))
    p.setBrush(QtGui.QColor("#dbeafe"))
    p.drawRect(R(2, 4, 13, 12))
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#22c55e"))
    p.drawPolygon(QtGui.QPolygonF([P(3, 15), P(8, 9), P(12, 15)]))
    p.setPen(QtGui.QPen(QtGui.QColor("#b45309"), 2.2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(P(18, 2), P(11, 11))
    p.setPen(QtGui.QPen(QtGui.QColor("#e53935"), 3.0, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(P(11, 11), P(9.5, 13))
    p.end()
    pm.setDevicePixelRatio(2)
    return QtGui.QIcon(pm)
