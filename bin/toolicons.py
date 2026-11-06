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

TOOLICONS_VER = "1.0.0"
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
        return False
    return True


def pixmap(name, sz=20, dpr=2):
    key = (name, sz, dpr)
    if key in _cache:
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
