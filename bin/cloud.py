# -*- coding: utf-8 -*-
"""클라우드 동기화 폴더(원드라이브 등) 상태 (CLOUD_VER 1.0.0, v0.9.94 사용자 의견 11/4: '원드라이브 상태 표시')

- 동기화 폴더 = 윈도우 클라우드 파일 등록(HKLM\\...\\Explorer\\SyncRootManager\\<id>\\UserSyncRoots 값 = 폴더 경로).
  원드라이브·구글 드라이브·드롭박스 등 윈도우 클라우드 파일 방식을 쓰는 프로그램 공통. 1분마다 한 번만 다시 읽음.
- 파일 상태 = 목록 읽을 때 이미 받은 파일 속성만 봄 (디스크·네트워크 추가 읽기 없음):
    클라우드에만 있음 = RECALL_ON_DATA_ACCESS(0x400000)·RECALL_ON_OPEN(0x40000)·OFFLINE(0x1000)
    항상 이 PC 에 유지 = PINNED(0x80000)
    그 밖(동기화 폴더 안) = 이 PC 에 있음
- '동기화 중'(파란 화살표)은 속성에 없음 → 아직 안 함 (실제 원드라이브에서 재 보고 정할 것)
"""
import os
import time
import logging

from i18n import T

log = logging.getLogger("QE.cloud")

CLOUD_VER = "1.0.0"
A_OFFLINE, A_RECALL_OPEN, A_PINNED, A_UNPINNED, A_RECALL_ACCESS = 0x1000, 0x40000, 0x80000, 0x100000, 0x400000
_roots = {"t": 0.0, "list": []}
TTL = 60.0

# 상태 → (정렬 순서, 풍선 글자)
STATES = {"cloud": (1, T("클라우드에만 있음 (열면 내려받음)")),
          "local": (2, T("이 PC 에 있음")),
          "pinned": (3, T("항상 이 PC 에 유지"))}


def _read_roots():
    import winreg
    out = []
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError:
        return out
    with k:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(k, sub + r"\UserSyncRoots") as u:
                    j = 0
                    while True:
                        try:
                            _sid, val, _t = winreg.EnumValue(u, j)
                        except OSError:
                            break
                        j += 1
                        if isinstance(val, str) and val:
                            out.append((os.path.normcase(os.path.normpath(val)), sub))
            except OSError:
                continue
    return out


def roots():
    """[(정규화 경로, 이름)] — 1분 기억"""
    now = time.time()
    if now - _roots["t"] > TTL:
        try:
            _roots["list"] = _read_roots()
        except Exception:
            log.exception("동기화 폴더 목록 못 읽음")
            _roots["list"] = []
        _roots["t"] = now
        log.info("동기화 폴더 %d개 %s", len(_roots["list"]), [r for r, _n in _roots["list"]][:5])
    return _roots["list"]


def root_of(path):
    """path 가 동기화 폴더 안이면 그 동기화 폴더 이름(등록 이름), 아니면 None"""
    if not path or path.startswith("::"):
        return None
    p = os.path.normcase(os.path.normpath(path))
    for r, name in roots():
        if p == r or p.startswith(r.rstrip("\\") + "\\"):
            return name
    return None


def state(attrs):
    """동기화 폴더 안 항목의 상태 이름 (속성만 봄)"""
    attrs = attrs or 0
    if attrs & (A_RECALL_ACCESS | A_RECALL_OPEN | A_OFFLINE):
        return "cloud"
    if attrs & A_PINNED:
        return "pinned"
    return "local"


_icons = {}


def icon(st, px=16):
    """탐색기와 비슷한 상태 그림: 구름(파란 테두리) · 초록 테두리 체크 · 초록 동그라미 흰 체크"""
    key = (st, px)
    if key in _icons:
        return _icons[key]
    from PySide6 import QtGui, QtCore
    from PySide6.QtCore import Qt
    dpr = 2
    pm = QtGui.QPixmap(px * dpr, px * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.scale(dpr, dpr)
    s = px / 16.0
    if st == "cloud":
        pen = QtGui.QPen(QtGui.QColor("#1f6fd1"), 1.3 * s)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QtGui.QPainterPath()
        path.moveTo(4 * s, 12 * s)
        path.arcTo(QtCore.QRectF(1.5 * s, 7.5 * s, 5 * s, 4.5 * s), 270, -180)
        path.arcTo(QtCore.QRectF(4 * s, 3.5 * s, 7.5 * s, 7 * s), 160, -150)
        path.arcTo(QtCore.QRectF(10 * s, 6.5 * s, 5 * s, 5.5 * s), 90, -180)
        path.lineTo(4 * s, 12 * s)
        p.drawPath(path)
    else:
        green = QtGui.QColor("#1e8e3e")
        r = QtCore.QRectF(2 * s, 2 * s, 12 * s, 12 * s)
        if st == "pinned":
            p.setPen(Qt.NoPen)
            p.setBrush(green)
            p.drawEllipse(r)
            ck = QtGui.QColor("#ffffff")
        else:
            p.setPen(QtGui.QPen(green, 1.3 * s))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)
            ck = green
        p.setPen(QtGui.QPen(ck, 1.6 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QtCore.QPointF(5 * s, 8.2 * s), QtCore.QPointF(7.2 * s, 10.3 * s), QtCore.QPointF(11 * s, 6 * s)])
    p.end()
    pm.setDevicePixelRatio(dpr)
    _icons[key] = pm
    return pm
