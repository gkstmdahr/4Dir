# -*- coding: utf-8 -*-
"""도구 아이콘 (TOOLICONS_VER 1.0.0, 0.9.111 빌드 4 — 사용자 11/6 '계산기 아이콘, 각 도구마다 아이콘')

- 그림 파일 없이 코드로 그림(20칸 기준 좌표 → 원하는 크기로, 화면 배율 2배로 선명하게)
- icon(이름, 크기) → QIcon (도구 메뉴·도구줄) · hbitmap(이름, 크기) → 윈도우 메뉴용 HBITMAP (우클릭 '4Dir 도구 ▸' 항목, shellops 가 붙임)
- 이름: calc sync treemap ftp tag group userbtn dupes flat compare pattern rename attrs imgbatch sha hexview mediaedit check palette
"""
import ctypes
import logging

from PySide6 import QtCore, QtGui
from PySide6.QtCore import Qt

TOOLICONS_VER = "1.1.0"   # 1.1.0 (0.9.116 빌드 2): 기본 파일 작업·탭·보기 아이콘 (My메뉴 단추)
log = logging.getLogger("QE.icons")
P = QtCore.QPointF
R = QtCore.QRectF
_cache = {}
_bmp = {}


def _c(h):
    return QtGui.QColor(h)


def _draw(p, name):
    """20x20 칸 안에 그림"""
    pen = lambda col, w=1.2: QtGui.QPen(_c(col), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    if name == "calc":   # 회색 몸통 · 초록 화면 · 단추 3x3
        p.setPen(pen("#4b5563", 1.0))
        p.setBrush(_c("#e5e7eb"))
        p.drawRoundedRect(R(3.5, 1.5, 13, 17), 2, 2)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#3fae68"))
        p.drawRoundedRect(R(5.5, 3.5, 9, 4), 1, 1)
        for r in range(3):
            for c in range(3):
                p.setBrush(_c("#f97316") if (r, c) == (2, 2) else _c("#6b7280"))
                p.drawRoundedRect(R(5.6 + c * 3.1, 9.2 + r * 3, 2.3, 2.1), 0.6, 0.6)
    elif name == "sync":   # 두 폴더 사이 오가는 화살표
        p.setPen(Qt.NoPen)
        for x, col in ((1.5, "#f2c14e"), (11, "#f2c14e")):
            p.setBrush(_c("#d9a420"))
            p.drawRoundedRect(R(x, 4, 4, 2.5), 0.8, 0.8)
            p.setBrush(_c(col))
            p.drawRoundedRect(R(x, 5.2, 7.5, 6.3), 1, 1)
        p.setPen(pen("#2563eb", 1.6))
        p.drawLine(P(5, 14.5), P(15, 14.5))
        p.drawLine(P(12.5, 12.5), P(15, 14.5))
        p.drawLine(P(12.5, 16.5), P(15, 14.5))
        p.setPen(pen("#16a34a", 1.6))
        p.drawLine(P(15, 18.2), P(5, 18.2))
        p.drawLine(P(7.5, 16.4), P(5, 18.2))
    elif name == "treemap":   # 색 사각형 나눔
        p.setPen(pen("#ffffff", 0.8))
        for rc, col in ((R(2, 2, 9, 16), "#3e7bd6"), (R(11, 2, 7, 9), "#e5484d"), (R(11, 11, 4, 7), "#8e4ec6"), (R(15, 11, 3, 7), "#f76b15")):
            p.setBrush(_c(col))
            p.drawRect(rc)
    elif name == "ftp":   # 지구 + 위아래 화살표
        p.setPen(pen("#1d6fd6", 1.2))
        p.setBrush(_c("#dbeafe"))
        p.drawEllipse(R(2, 2, 13, 13))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(R(5.8, 2, 5.4, 13))
        p.drawLine(P(2.5, 8.5), P(14.5, 8.5))
        p.setPen(pen("#16a34a", 1.6))
        p.drawLine(P(17, 18.5), P(17, 11))
        p.drawLine(P(15, 13), P(17, 11))
        p.drawLine(P(19, 13), P(17, 11))
    elif name == "tag":   # 주황 꼬리표
        path = QtGui.QPainterPath()
        path.moveTo(2.5, 9)
        path.lineTo(9, 2.5)
        path.lineTo(17, 2.5)
        path.lineTo(17, 10.5)
        path.lineTo(10.5, 17)
        path.closeSubpath()
        p.setPen(pen("#c2410c", 1.0))
        p.setBrush(_c("#fb923c"))
        p.drawPath(path)
        p.setBrush(_c("#ffffff"))
        p.drawEllipse(R(12.2, 5, 2.6, 2.6))
    elif name == "group":   # 겹친 카드 (가상 그룹)
        for i, col in enumerate(("#c4b5fd", "#a78bfa", "#7c3aed")):
            p.setPen(pen("#5b21b6", 0.9))
            p.setBrush(_c(col))
            p.drawRoundedRect(R(2 + i * 2.5, 3 + i * 2.8, 11, 8), 1.2, 1.2)
    elif name == "userbtn":   # 둥근 단추 + 손가락(누름)
        p.setPen(pen("#1e40af", 1.0))
        p.setBrush(_c("#60a5fa"))
        p.drawRoundedRect(R(1.5, 3, 14, 9), 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#ffffff"))
        p.drawPolygon(QtGui.QPolygonF([P(6.5, 5.3), P(6.5, 9.7), P(10.5, 7.5)]))
        p.setPen(pen("#374151", 1.0))
        p.setBrush(_c("#fde68a"))
        p.drawRoundedRect(R(12, 10, 4.2, 8), 2, 2)
    elif name == "dupes":   # 같은 문서 두 장 + =
        for x, y in ((2, 2), (7, 5.5)):
            p.setPen(pen("#475569", 1.0))
            p.setBrush(_c("#ffffff"))
            p.drawRect(R(x, y, 9, 11.5))
            p.setPen(pen("#94a3b8", 0.9))
            for k in range(3):
                p.drawLine(P(x + 2, y + 3 + k * 2.6), P(x + 7, y + 3 + k * 2.6))
        p.setPen(pen("#dc2626", 1.6))
        p.drawLine(P(14.5, 2.5), P(18.5, 2.5))
        p.drawLine(P(14.5, 5), P(18.5, 5))
    elif name == "flat":   # 폴더 아래 → 한 줄 목록
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#d9a420"))
        p.drawRoundedRect(R(2, 2, 4, 2.3), 0.8, 0.8)
        p.setBrush(_c("#f2c14e"))
        p.drawRoundedRect(R(2, 3.3, 8, 5.7), 1, 1)
        p.setPen(pen("#2563eb", 1.5))
        p.drawLine(P(6, 10.5), P(6, 13.5))
        p.drawLine(P(4.5, 12), P(6, 13.5))
        p.drawLine(P(7.5, 12), P(6, 13.5))
        p.setPen(pen("#475569", 1.3))
        for k in range(4):
            p.drawLine(P(11, 3 + k * 4.5), P(18, 3 + k * 4.5))
    elif name == "compare":   # 두 기둥 ↔
        p.setPen(pen("#475569", 1.0))
        p.setBrush(_c("#e2e8f0"))
        p.drawRect(R(1.5, 3, 6, 14))
        p.drawRect(R(12.5, 3, 6, 14))
        p.setPen(pen("#16a34a", 1.2))
        p.drawLine(P(3, 7), P(6, 7))
        p.setPen(pen("#dc2626", 1.2))
        p.drawLine(P(14, 11), P(17, 11))
        p.setPen(pen("#2563eb", 1.5))
        p.drawLine(P(8.5, 10), P(11.5, 10))
        p.drawLine(P(9.6, 8.8), P(8.5, 10))
        p.drawLine(P(10.4, 11.2), P(11.5, 10))
    elif name == "pattern":   # *.jpg 별표
        p.setPen(pen("#2563eb", 1.0))
        p.setBrush(_c("#dbeafe"))
        p.drawRoundedRect(R(1.5, 3, 17, 14), 2.5, 2.5)
        f = p.font()
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(_c("#1d4ed8"))
        p.drawText(R(1.5, 3.5, 17, 14), Qt.AlignCenter, "*.*")
    elif name == "rename":   # 이름 칸 + 글자 커서
        p.setPen(pen("#475569", 1.0))
        p.setBrush(_c("#ffffff"))
        p.drawRoundedRect(R(1.5, 5, 17, 10), 1.5, 1.5)
        p.setPen(pen("#2563eb", 1.6))
        p.drawLine(P(4, 10), P(10, 10))
        p.setPen(pen("#111827", 1.1))
        p.drawLine(P(13, 3.5), P(13, 16.5))
        p.drawLine(P(11.5, 3.5), P(14.5, 3.5))
        p.drawLine(P(11.5, 16.5), P(14.5, 16.5))
    elif name == "attrs":   # 달력 + 시계
        p.setPen(pen("#475569", 1.0))
        p.setBrush(_c("#ffffff"))
        p.drawRoundedRect(R(1.5, 3, 13, 13), 1.5, 1.5)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#e5484d"))
        p.drawRect(R(2, 3.5, 12, 3.2))
        p.setBrush(_c("#94a3b8"))
        for r in range(2):
            for c in range(3):
                p.drawRect(R(3.5 + c * 3.5, 8.5 + r * 3, 2, 1.8))
        p.setPen(pen("#1d4ed8", 1.0))
        p.setBrush(_c("#dbeafe"))
        p.drawEllipse(R(11, 11, 8, 8))
        p.drawLine(P(15, 15), P(15, 12.6))
        p.drawLine(P(15, 15), P(16.8, 15))
    elif name == "imgbatch":   # 그림(산·해) + 줄이기 화살표
        p.setPen(pen("#475569", 1.0))
        p.setBrush(_c("#e0f2fe"))
        p.drawRect(R(1.5, 2.5, 13, 10.5))
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#16a34a"))
        p.drawPolygon(QtGui.QPolygonF([P(2, 12.5), P(6.5, 7), P(10, 11), P(12, 9), P(14, 12.5)]))
        p.setBrush(_c("#facc15"))
        p.drawEllipse(R(10, 4, 3, 3))
        p.setPen(pen("#2563eb", 1.6))
        p.drawLine(P(18.5, 18.5), P(13, 15))
        p.drawLine(P(18.5, 18.5), P(18.5, 15.5))
        p.drawLine(P(18.5, 18.5), P(15.5, 18.5))
    elif name == "sha":   # 방패 + 확인
        path = QtGui.QPainterPath()
        path.moveTo(10, 1.5)
        path.lineTo(17, 4)
        path.cubicTo(17, 12, 14, 16, 10, 18.5)
        path.cubicTo(6, 16, 3, 12, 3, 4)
        path.closeSubpath()
        p.setPen(pen("#15803d", 1.0))
        p.setBrush(_c("#4ade80"))
        p.drawPath(path)
        p.setPen(pen("#ffffff", 1.8))
        p.drawPolyline([P(6.5, 10), P(9, 12.5), P(13.5, 7)])
    elif name == "hexview":   # 0x 글자 판
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#1e293b"))
        p.drawRoundedRect(R(1.5, 3, 17, 14), 2, 2)
        f = QtGui.QFont("Consolas")
        f.setPixelSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(_c("#4ade80"))
        p.drawText(R(1.5, 3, 17, 7.5), Qt.AlignCenter, "0x1F")
        p.setPen(_c("#93c5fd"))
        p.drawText(R(1.5, 9.5, 17, 7.5), Qt.AlignCenter, "Ab")
    elif name == "mediaedit":   # 필름 + 가위
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#7c3aed"))
        p.drawRoundedRect(R(1.5, 3, 12, 14), 1.2, 1.2)
        p.setBrush(_c("#ffffff"))
        for k in range(4):
            p.drawRect(R(2.5, 4.5 + k * 3.3, 1.6, 1.6))
            p.drawRect(R(10.9, 4.5 + k * 3.3, 1.6, 1.6))
        p.setBrush(_c("#ddd6fe"))
        p.drawRect(R(5, 5, 4.6, 10))
        p.setPen(pen("#dc2626", 1.3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(R(12.5, 14, 3.2, 3.2))
        p.drawEllipse(R(16, 14, 3.2, 3.2))
        p.drawLine(P(15.2, 14.2), P(18.5, 8.5))
        p.drawLine(P(16.5, 14.2), P(13.5, 8.5))
    elif name == "check":   # 돋보기 + 확인
        p.setPen(pen("#1d4ed8", 1.6))
        p.setBrush(_c("#dbeafe"))
        p.drawEllipse(R(2, 2, 11, 11))
        p.drawLine(P(11.5, 11.5), P(17.5, 17.5))
        p.setPen(pen("#16a34a", 1.6))
        p.drawPolyline([P(4.8, 7.6), P(6.8, 9.6), P(10.2, 5.4)])
    elif name == "palette":   # 명령 찾기: > _
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#f1f5f9"))
        p.drawRoundedRect(R(1.5, 3, 17, 14), 2, 2)
        p.setPen(pen("#2563eb", 1.6))
        p.drawPolyline([P(5, 7), P(8, 10), P(5, 13)])
        p.drawLine(P(10, 13), P(15, 13))
    else:
        return _draw_more(p, name)
    return True


EXTERNAL = {}   # 0.9.116: 새 모듈이 직접 그리는 아이콘 {이름: 함수(크기) → QIcon} — register() 로 넣음


def register(name, fn):
    EXTERNAL[name] = fn


def pixmap(name, sz=20, dpr=2):
    key = (name, sz, dpr)
    if key in _cache:
        return _cache[key]
    if name in EXTERNAL:
        try:
            ic = EXTERNAL[name](sz)
            pm = ic.pixmap(QtCore.QSize(sz * dpr, sz * dpr))
            pm.setDevicePixelRatio(dpr)
            _cache[key] = pm if not pm.isNull() else None
        except Exception:
            log.exception("아이콘 %s 못 그림", name)
            _cache[key] = None
        return _cache[key]
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
    p.scale(sz * dpr / 20.0, sz * dpr / 20.0)
    ok = _draw(p, name)
    p.end()
    pm.setDevicePixelRatio(dpr)
    _cache[key] = pm if ok else None
    return _cache[key]


def icon(name, sz=20):
    pm = pixmap(name, sz)
    return QtGui.QIcon(pm) if pm is not None else QtGui.QIcon()


def hbitmap(name, sz=None):
    """윈도우 메뉴 항목 그림 (32비트 투명 HBITMAP, 한 번 만들고 계속 씀). 실패하면 None"""
    try:
        sz = sz or ctypes.windll.user32.GetSystemMetrics(49) or 16   # SM_CXSMICON (화면 배율 반영)
        key = (name, sz)
        if key in _bmp:
            return _bmp[key]
        pm = pixmap(name, sz, dpr=1)
        if pm is None:
            _bmp[key] = None
            return None
        im = pm.toImage().convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                        ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                        ("biSizeImage", ctypes.c_uint32), ("x", ctypes.c_int32), ("y", ctypes.c_int32),
                        ("c1", ctypes.c_uint32), ("c2", ctypes.c_uint32)]
        g = ctypes.windll.gdi32
        g.CreateDIBSection.restype = ctypes.c_void_p
        g.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint]
        w, h = im.width(), im.height()
        bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = g.CreateDIBSection(None, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
        if not bmp or not bits.value:
            raise OSError("CreateDIBSection 실패")
        data = bytes(im.constBits())[: w * h * 4]
        ctypes.memmove(bits.value, data, len(data))
        _bmp[key] = bmp
        return bmp
    except Exception as ex:
        log.warning("메뉴 아이콘 못 만듦 %s: %s", name, ex)
        _bmp[(name, sz)] = None
        return None


def _folder(p, x=1.5, y=3.5, w=13, h=10, col="#f2c14e", tab="#d9a420"):
    p.setPen(Qt.NoPen)
    p.setBrush(_c(tab))
    p.drawRoundedRect(R(x, y, w * 0.45, 3), 0.8, 0.8)
    p.setBrush(_c(col))
    p.drawRoundedRect(R(x, y + 1.6, w, h - 1.6), 1.2, 1.2)


def _page(p, x, y, w, h, lines=3):
    p.setPen(QtGui.QPen(_c("#475569"), 1.0))
    p.setBrush(_c("#ffffff"))
    p.drawRect(R(x, y, w, h))
    p.setPen(QtGui.QPen(_c("#94a3b8"), 0.9))
    for k in range(lines):
        p.drawLine(P(x + 2, y + 3 + k * 2.6), P(x + w - 2, y + 3 + k * 2.6))


def _arrow(p, pts, col, w=1.6):
    """꺾은선 + 끝 화살촉"""
    p.setPen(QtGui.QPen(_c(col), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPolyline([P(*q) for q in pts])
    (x0, y0), (x1, y1) = pts[-2], pts[-1]
    import math
    a = math.atan2(y1 - y0, x1 - x0)
    for d in (2.5, -2.5):
        p.drawLine(P(x1, y1), P(x1 - 3.2 * math.cos(a + d * 0.3), y1 - 3.2 * math.sin(a + d * 0.3)))


def _x(p, cx, cy, r=2.6, col="#dc2626"):
    p.setPen(QtGui.QPen(_c(col), 1.7, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(P(cx - r, cy - r), P(cx + r, cy + r))
    p.drawLine(P(cx - r, cy + r), P(cx + r, cy - r))


def _plus(p, cx, cy, r=3, col="#16a34a"):
    p.setPen(Qt.NoPen)
    p.setBrush(_c(col))
    p.drawEllipse(R(cx - r - 1, cy - r - 1, 2 * r + 2, 2 * r + 2))
    p.setPen(QtGui.QPen(_c("#ffffff"), 1.5, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(P(cx - r + 1, cy), P(cx + r - 1, cy))
    p.drawLine(P(cx, cy - r + 1), P(cx, cy + r - 1))


def _tab(p, col="#dbeafe"):
    p.setPen(QtGui.QPen(_c("#2563eb"), 1.0))
    p.setBrush(_c(col))
    path = QtGui.QPainterPath()
    path.moveTo(1.5, 17)
    path.lineTo(1.5, 6)
    path.lineTo(3, 3.5)
    path.lineTo(9, 3.5)
    path.lineTo(10.5, 6)
    path.lineTo(18.5, 6)
    path.lineTo(18.5, 17)
    path.closeSubpath()
    p.drawPath(path)


def _text(p, rect, s, col, px=9, bold=True, family=None):
    f = QtGui.QFont(family) if family else p.font()
    f.setPixelSize(px)
    f.setBold(bold)
    p.setFont(f)
    p.setPen(_c(col))
    p.drawText(rect, Qt.AlignCenter, s)


def _draw_more(p, name):
    """0.9.116 빌드 2 (사용자 게시판 11/8: My메뉴의 4Dir 기능 단추에 아이콘이 없다) — 기본 파일 작업·탭·보기 아이콘"""
    pen = lambda col, w=1.2: QtGui.QPen(_c(col), w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    if name == "open":
        _folder(p, 1.5, 4, 14, 12)
        _arrow(p, [(9, 14), (17.5, 5.5)], "#2563eb")
    elif name == "newfolder":
        _folder(p, 1.5, 3.5, 14, 12)
        _plus(p, 15, 14.5)
    elif name in ("trash", "trashx"):
        p.setPen(pen("#475569", 1.0))
        p.setBrush(_c("#cbd5e1"))
        p.drawRect(R(4.5, 6, 11, 12))
        p.drawLine(P(3, 4.5), P(17, 4.5))
        p.drawLine(P(8, 4.5), P(8.5, 2.5))
        p.drawLine(P(12, 4.5), P(11.5, 2.5))
        p.drawLine(P(8.5, 2.5), P(11.5, 2.5))
        p.setPen(pen("#64748b", 1.0))
        for x in (7.5, 10, 12.5):
            p.drawLine(P(x, 8.5), P(x, 15.5))
        if name == "trashx":
            p.setPen(Qt.NoPen)
            p.setBrush(_c("#ffffff"))
            p.drawEllipse(R(11, 11, 8.5, 8.5))
            _x(p, 15.2, 15.2, 2.3)
    elif name == "copy":
        _page(p, 2, 2, 10, 12)
        _page(p, 8, 6, 10, 12)
    elif name == "cut":
        p.setPen(pen("#475569", 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(R(2.5, 12.5, 5, 5))
        p.drawEllipse(R(12.5, 12.5, 5, 5))
        p.drawLine(P(6.8, 13.2), P(14, 2.5))
        p.drawLine(P(13.2, 13.2), P(6, 2.5))
    elif name == "paste":
        p.setPen(pen("#92400e", 1.0))
        p.setBrush(_c("#d6a15c"))
        p.drawRoundedRect(R(3, 3, 12, 15.5), 1.5, 1.5)
        p.setBrush(_c("#64748b"))
        p.drawRoundedRect(R(6, 1.5, 6, 3), 1, 1)
        _page(p, 9, 8, 9, 10.5, 2)
    elif name in ("sendcopy", "sendmove"):
        p.setPen(pen("#475569", 1.0))
        p.setBrush(_c("#e2e8f0"))
        p.drawRect(R(1.5, 3, 6.5, 14))
        p.drawRect(R(12, 3, 6.5, 14))
        _arrow(p, [(4.5, 10), (15.5, 10)], "#16a34a" if name == "sendcopy" else "#f97316", 1.8)
    elif name == "undo":
        p.setPen(pen("#2563eb", 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawArc(R(4, 5, 13, 11), 90 * 16, -230 * 16)
        p.drawPolyline([P(3, 6), P(7.5, 4.8), P(6.5, 9.5)])
    elif name == "path":
        p.setPen(pen("#475569", 1.0))
        p.setBrush(_c("#f8fafc"))
        p.drawRoundedRect(R(1, 5, 18, 10), 2, 2)
        _text(p, R(1, 5, 18, 10), "C:\\", "#1d4ed8", 8, True, "Consolas")
    elif name == "props":
        p.setPen(pen("#1d4ed8", 1.0))
        p.setBrush(_c("#3b82f6"))
        p.drawEllipse(R(2, 2, 16, 16))
        _text(p, R(2, 2.5, 16, 16), "i", "#ffffff", 12, True, "Georgia")
    elif name in ("eye", "hidden"):
        path = QtGui.QPainterPath()
        path.moveTo(1.5, 10)
        path.quadTo(10, 1, 18.5, 10)
        path.quadTo(10, 19, 1.5, 10)
        p.setPen(pen("#334155", 1.1))
        p.setBrush(_c("#ffffff"))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#2563eb"))
        p.drawEllipse(R(6.8, 6.8, 6.4, 6.4))
        p.setBrush(_c("#0f172a"))
        p.drawEllipse(R(8.7, 8.7, 2.6, 2.6))
        if name == "hidden":
            p.setPen(pen("#dc2626", 1.8))
            p.drawLine(P(3, 17), P(17, 3))
    elif name == "newwin":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#ffffff"))
        p.drawRect(R(1.5, 3, 15, 12))
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#2563eb"))
        p.drawRect(R(2, 3.5, 14, 2.5))
        _plus(p, 15.5, 15.5)
    elif name in ("newtab", "closetab", "reopen", "tabnext", "tabprev"):
        _tab(p)
        if name == "newtab":
            _plus(p, 14, 13)
        elif name == "closetab":
            _x(p, 10, 11.5, 3)
        elif name == "reopen":
            p.setPen(pen("#16a34a", 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawArc(R(5.5, 8, 9, 7.5), 30 * 16, 280 * 16)
            p.drawPolyline([P(14.5, 7.5), P(14, 10.3), P(11.5, 9.5)])
        else:
            pts = [(5, 11.5), (15, 11.5)] if name == "tabnext" else [(15, 11.5), (5, 11.5)]
            _arrow(p, pts, "#2563eb", 1.8)
    elif name == "lock":
        p.setPen(pen("#475569", 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawArc(R(6, 2.5, 8, 9), 0, 180 * 16)
        p.drawLine(P(6, 7), P(6, 9))
        p.drawLine(P(14, 7), P(14, 9))
        p.setPen(pen("#92400e", 1.0))
        p.setBrush(_c("#f59e0b"))
        p.drawRoundedRect(R(3.5, 9, 13, 9.5), 1.5, 1.5)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#78350f"))
        p.drawEllipse(R(8.8, 12, 2.4, 2.4))
    elif name == "addr":
        p.setPen(pen("#475569", 1.0))
        p.setBrush(_c("#ffffff"))
        p.drawRoundedRect(R(1, 5, 18, 10), 2, 2)
        p.setPen(pen("#2563eb", 1.4))
        p.drawPolyline([P(4, 8), P(6.3, 10), P(4, 12)])
        p.drawPolyline([P(9, 8), P(11.3, 10), P(9, 12)])
        p.setPen(pen("#111827", 1.0))
        p.drawLine(P(15, 7.5), P(15, 12.5))
    elif name == "filter":
        p.setPen(pen("#1d4ed8", 1.0))
        p.setBrush(_c("#93c5fd"))
        p.drawPolygon(QtGui.QPolygonF([P(2, 3), P(18, 3), P(11.5, 10.5), P(11.5, 17), P(8.5, 15.5), P(8.5, 10.5)]))
    elif name == "search":
        p.setPen(pen("#334155", 1.8))
        p.setBrush(_c("#e0f2fe"))
        p.drawEllipse(R(2, 2, 11, 11))
        p.drawLine(P(11.5, 11.5), P(17.5, 17.5))
    elif name == "star":
        import math
        pts = []
        for k in range(10):
            r = 8.5 if k % 2 == 0 else 3.8
            a = -math.pi / 2 + k * math.pi / 5
            pts.append(P(10 + r * math.cos(a), 10.6 + r * math.sin(a)))
        p.setPen(pen("#b45309", 1.0))
        p.setBrush(_c("#fbbf24"))
        p.drawPolygon(QtGui.QPolygonF(pts))
    elif name == "chrome":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#f1f5f9"))
        p.drawRect(R(2, 2, 16, 16))
        p.setPen(pen("#2563eb", 1.8))
        p.drawPolyline([P(6, 11), P(10, 7), P(14, 11)])
        p.drawPolyline([P(6, 15), P(10, 11), P(14, 15)])
    elif name == "nav":
        p.setPen(pen("#64748b", 1.0))
        p.drawLine(P(4, 5), P(4, 15))
        p.drawLine(P(4, 10), P(8, 10))
        p.drawLine(P(4, 15), P(8, 15))
        _folder(p, 1.5, 1.5, 7, 5)
        _folder(p, 8.5, 7.5, 7, 5)
        _folder(p, 8.5, 12.5, 7, 5)
    elif name == "pin":
        p.setPen(pen("#991b1b", 1.0))
        p.setBrush(_c("#ef4444"))
        p.drawEllipse(R(6, 1.5, 8, 8))
        p.setPen(pen("#475569", 1.6))
        p.drawLine(P(10, 9.5), P(10, 18.5))
    elif name == "cpu":
        p.setPen(pen("#475569", 1.0))
        for k in range(3):
            o = 6 + k * 4
            p.drawLine(P(o, 1.5), P(o, 4))
            p.drawLine(P(o, 16), P(o, 18.5))
            p.drawLine(P(1.5, o), P(4, o))
            p.drawLine(P(16, o), P(18.5, o))
        p.setBrush(_c("#334155"))
        p.drawRoundedRect(R(4, 4, 12, 12), 1.5, 1.5)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#22c55e"))
        p.drawRect(R(7, 7, 6, 6))
    elif name == "keyboard":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#e5e7eb"))
        p.drawRoundedRect(R(1, 5, 18, 11), 1.5, 1.5)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#64748b"))
        for r in range(2):
            for c in range(5):
                p.drawRect(R(2.8 + c * 3.1, 7 + r * 2.8, 2.2, 1.9))
        p.drawRect(R(5.5, 12.8, 9, 1.8))
    elif name == "colors":
        for (x, y), col in (((2, 2), "#ef4444"), ((10, 2), "#22c55e"), ((6, 9.5), "#3b82f6")):
            p.setPen(pen("#ffffff", 0.8))
            p.setBrush(_c(col))
            p.drawEllipse(R(x, y, 8.5, 8.5))
    elif name == "workspace":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#ffffff"))
        p.drawRect(R(1.5, 2.5, 17, 13))
        p.setBrush(_c("#bfdbfe"))
        p.drawRect(R(3, 5, 6.5, 9))
        p.drawRect(R(10.5, 5, 6.5, 9))
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#2563eb"))
        p.drawRect(R(2, 3, 16, 1.6))
        p.setPen(pen("#16a34a", 1.6))
        p.drawLine(P(10, 15.5), P(10, 19))
    elif name in ("export", "import"):
        p.setPen(pen("#92400e", 1.0))
        p.setBrush(_c("#fcd34d"))
        p.drawRect(R(2.5, 10, 15, 8))
        _arrow(p, [(10, 13), (10, 2)] if name == "export" else [(10, 1.5), (10, 12.5)], "#2563eb", 1.8)
    elif name == "report":
        _page(p, 3, 1.5, 12, 16, 0)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#dc2626"))
        p.drawEllipse(R(10, 10, 9, 9))
        _text(p, R(10, 10.3, 9, 9), "!", "#ffffff", 8)
    elif name == "log":
        _page(p, 3.5, 1.5, 13, 17, 5)
    elif name == "update":
        p.setPen(pen("#16a34a", 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawArc(R(3, 3, 14, 14), 40 * 16, 140 * 16)
        p.drawArc(R(3, 3, 14, 14), 220 * 16, 140 * 16)
        p.drawPolyline([P(15.8, 2.8), P(15.4, 6.2), P(12, 5.6)])
        p.drawPolyline([P(4.2, 17.2), P(4.6, 13.8), P(8, 14.4)])
    elif name == "refresh":
        p.setPen(pen("#2563eb", 1.8))
        p.setBrush(Qt.NoBrush)
        p.drawArc(R(3, 3, 14, 14), 60 * 16, 290 * 16)
        p.drawPolyline([P(15.5, 2), P(13.8, 5.2), P(10.5, 3.6)])
    elif name == "guide":
        p.setPen(pen("#1d4ed8", 1.0))
        p.setBrush(_c("#3b82f6"))
        p.drawEllipse(R(2, 2, 16, 16))
        _text(p, R(2, 2.5, 16, 16), "?", "#ffffff", 12)
    elif name in ("up", "back", "fwd"):
        pts = {"up": [(10, 17), (10, 3)], "back": [(17, 10), (3, 10)], "fwd": [(3, 10), (17, 10)]}[name]
        _arrow(p, pts, "#2563eb", 2.0)
    elif name == "sort":
        _arrow(p, [(5, 17), (5, 3)], "#2563eb", 1.6)
        p.setPen(pen("#475569", 1.5))
        for k, w in enumerate((8, 6, 4)):
            p.drawLine(P(9, 5 + k * 5), P(9 + w, 5 + k * 5))
    elif name == "view":
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#3b82f6"))
        for r in range(2):
            for c in range(2):
                p.drawRoundedRect(R(2.5 + c * 8, 2.5 + r * 8, 6.5, 6.5), 1, 1)
    elif name == "theme":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#ffffff"))
        p.drawEllipse(R(2, 2, 16, 16))
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#334155"))
        p.drawPie(R(2, 2, 16, 16), 90 * 16, 180 * 16)
    elif name == "showopt":
        p.setPen(pen("#2563eb", 1.2))
        p.setBrush(_c("#ffffff"))
        p.drawRoundedRect(R(2.5, 2.5, 15, 15), 2, 2)
        p.setPen(pen("#16a34a", 2.0))
        p.drawPolyline([P(5.5, 10), P(8.5, 13), P(14.5, 6.5)])
    elif name == "gear":
        import math
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#64748b"))
        for k in range(8):
            a = k * math.pi / 4
            p.save()
            p.translate(10, 10)
            p.rotate(math.degrees(a))
            p.drawRect(R(-1.6, -9, 3.2, 4))
            p.restore()
        p.drawEllipse(R(3.5, 3.5, 13, 13))
        p.setBrush(_c("#ffffff"))
        p.drawEllipse(R(7.3, 7.3, 5.4, 5.4))
    elif name == "drive":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#cbd5e1"))
        p.drawRoundedRect(R(1.5, 6, 17, 8), 1.5, 1.5)
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#22c55e"))
        p.drawEllipse(R(14, 9, 2.4, 2.4))
    elif name == "layers":
        for k, col in enumerate(("#93c5fd", "#60a5fa", "#2563eb")):
            p.setPen(pen("#1e3a8a", 0.8))
            p.setBrush(_c(col))
            y = 10 - k * 3.5
            p.drawPolygon(QtGui.QPolygonF([P(10, y), P(18, y + 4), P(10, y + 8), P(2, y + 4)]))
    elif name == "pane":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#ffffff"))
        p.drawRect(R(2, 3, 16, 14))
        p.drawLine(P(10, 3), P(10, 17))
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#3b82f6"))
        p.drawRect(R(2.5, 3.5, 7, 13))
    elif name == "hotkey":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#e5e7eb"))
        p.drawRoundedRect(R(1.5, 4, 17, 12), 2.5, 2.5)
        _text(p, R(1.5, 4.5, 17, 12), "⌘", "#1d4ed8", 10)
    elif name == "print":
        p.setPen(pen("#334155", 1.0))
        p.setBrush(_c("#ffffff"))
        p.drawRect(R(5, 2, 10, 6))
        p.setBrush(_c("#94a3b8"))
        p.drawRoundedRect(R(1.5, 7, 17, 8), 1.5, 1.5)
        p.setBrush(_c("#ffffff"))
        p.drawRect(R(5, 12, 10, 6.5))
        p.setPen(pen("#94a3b8", 0.9))
        p.drawLine(P(7, 14.5), P(13, 14.5))
        p.drawLine(P(7, 16.5), P(12, 16.5))
        p.setPen(Qt.NoPen)
        p.setBrush(_c("#22c55e"))
        p.drawEllipse(R(15, 9, 2, 2))
    else:
        return False
    return True


# 기능 id → 아이콘 이름 (0.9.116 빌드 2, main.action_icon 이 먼저 보는 ACTION_ICONS 에 없는 것)
ACTION_MORE = {
    "open": "open", "open_new_tab": "newtab", "up": "up", "back": "back", "fwd": "fwd", "refresh": "refresh",
    "delete": "trash", "delete_perm": "trashx", "new_folder": "newfolder", "copy": "copy", "cut": "cut", "paste": "paste",
    "send_copy": "sendcopy", "send_move": "sendmove", "undo": "undo", "copy_path": "path", "properties": "props",
    "quick_preview": "eye", "new_window": "newwin", "new_tab": "newtab", "close_tab": "closetab", "lock_tab": "lock",
    "reopen_tab": "reopen", "next_tab": "tabnext", "prev_tab": "tabprev", "focus_addr": "addr", "focus_filter": "filter",
    "global_search": "search", "global_hotkey": "keyboard", "toggle_hidden": "hidden", "add_fav": "star", "toggle_chrome": "chrome",
    "toggle_nav": "nav", "side_shared": "nav", "toggle_favbar": "star", "fav_organize": "star", "fav_import": "star",
    "toggle_sysmon": "cpu", "toggle_on_top": "pin", "settings": "gear", "keys_settings": "keyboard", "color_settings": "colors",
    "search_roots": "drive", "overlay_order": "layers", "export_settings": "export", "import_settings": "import",
    "guide": "guide", "check_update": "update", "open_logs": "log", "save_report": "report",
    "ws_save": "workspace", "ws_latest": "workspace", "ws_slot1": "workspace", "ws_slot2": "workspace",
}
ACTION_PREFIX = (("rate_", "star"), ("view_", "view"), ("show_", "showopt"), ("sort_", "sort"), ("theme_", "theme"), ("set_", "gear"), ("pane", "pane"))


def action_name(a):
    """기능 id → 이 파일 아이콘 이름 (없으면 None)"""
    if a in ACTION_MORE:
        return ACTION_MORE[a]
    for pre, n in ACTION_PREFIX:
        if a.startswith(pre):
            return n
    return None
