# -*- coding: utf-8 -*-
"""PowerToys 로 Win+E 연결 — 그림 안내 창 (PTGUIDE_VER 1.0.0, 0.9.119 빌드 3 — 사용자 11/10 '그림으로 설명해서 넣어줘')

단계마다 직접 그린 설명 그림(실제 PowerToys 화면을 본뜬 단순 그림 — 화면 캡처 아님) + 한 줄 설명 + 넣을 값(복사 단추).
맨 위 [자동으로 연결] = ptlink.link (3·4단계를 대신 함). PowerToys 가 없으면 [PowerToys 받기].
로그: bin\\log\\4Dir.log [QE.ptguide]
"""
import logging

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

import ptlink

PTGUIDE_VER = "1.0.0"
log = logging.getLogger("QE.ptguide")
W, H = 520, 210
BLUE, LINE, TXT, SUB, BG, WIN_BG = "#2f6fd0", "#c9ced6", "#1f2328", "#5f6b7a", "#f7f8fa", "#ffffff"


def _canvas():
    dpr = 2
    pm = QtGui.QPixmap(W * dpr, H * dpr)
    pm.fill(QtGui.QColor(BG))
    pm.setDevicePixelRatio(dpr)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
    return pm, p


def _font(px, bold=False):
    f = QtGui.QFont("Segoe UI")
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def _window(p, r, title):
    """창 테두리 + 제목줄"""
    p.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
    p.setBrush(QtGui.QColor(WIN_BG))
    p.drawRoundedRect(r, 8, 8)
    p.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
    p.drawLine(QtCore.QPointF(r.left(), r.top() + 26), QtCore.QPointF(r.right(), r.top() + 26))
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(11, True))
    p.drawText(QtCore.QRectF(r.left() + 12, r.top(), r.width() - 24, 26), Qt.AlignVCenter | Qt.AlignLeft, title)
    for i, c in enumerate(("#e0e3e8", "#e0e3e8", "#e0e3e8")):
        p.setBrush(QtGui.QColor(c))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QtCore.QPointF(r.right() - 16 - i * 16, r.top() + 13), 4, 4)


def _button(p, r, text, primary=False):
    p.setPen(QtGui.QPen(QtGui.QColor(BLUE if primary else LINE), 1))
    p.setBrush(QtGui.QColor(BLUE if primary else "#ffffff"))
    p.drawRoundedRect(r, 5, 5)
    p.setPen(QtGui.QColor("#ffffff" if primary else TXT))
    p.setFont(_font(12, primary))
    p.drawText(r, Qt.AlignCenter, text)


def _ring(p, r):
    """눌러야 할 곳 빨간 동그라미"""
    p.setPen(QtGui.QPen(QtGui.QColor("#d93025"), 2.5))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r.adjusted(-6, -5, 6, 5), 10, 10)


def _field(p, x, y, label, value, w=300):
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(11))
    p.drawText(QtCore.QRectF(x, y, 110, 22), Qt.AlignVCenter | Qt.AlignLeft, label)
    r = QtCore.QRectF(x + 112, y, w, 22)
    p.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawRoundedRect(r, 4, 4)
    p.setPen(QtGui.QColor(TXT))
    p.setFont(_font(11))
    p.drawText(r.adjusted(6, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft,
               QtGui.QFontMetrics(_font(11)).elidedText(value, Qt.ElideMiddle, int(r.width() - 12)))
    return r


def step1():
    """PowerToys 설치 (Microsoft Store)"""
    pm, p = _canvas()
    r = QtCore.QRectF(20, 14, W - 40, H - 28)
    _window(p, r, "Microsoft Store")
    tile = QtCore.QRectF(r.left() + 24, r.top() + 46, 96, 96)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#3b2f7f"))
    p.drawRoundedRect(tile, 14, 14)
    p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 5, Qt.SolidLine, Qt.RoundCap))
    c = tile.center()
    p.drawLine(c + QtCore.QPointF(-22, 18), c + QtCore.QPointF(14, -18))   # 공구 모양 (본뜬 그림)
    p.drawEllipse(c + QtCore.QPointF(18, -22), 8, 8)
    p.setPen(QtGui.QColor(TXT))
    p.setFont(_font(20, True))
    p.drawText(QtCore.QPointF(tile.right() + 20, tile.top() + 30), "PowerToys")
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(12))
    p.drawText(QtCore.QPointF(tile.right() + 20, tile.top() + 52), "Microsoft Corporation")
    b = QtCore.QRectF(tile.right() + 20, tile.top() + 66, 96, 28)
    _button(p, b, T("설치") + " (Get)", True)
    _ring(p, b)
    p.end()
    return pm


def step2():
    """PowerToys 설정 → 키보드 관리자 켜기"""
    pm, p = _canvas()
    r = QtCore.QRectF(20, 14, W - 40, H - 28)
    _window(p, r, "PowerToys Settings")
    nav = QtCore.QRectF(r.left() + 1, r.top() + 27, 150, r.height() - 28)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#f1f3f6"))
    p.drawRect(nav)
    items = ["General", "FancyZones", "Keyboard Manager", "PowerRename", "Run"]
    sel = None
    for i, t in enumerate(items):
        ir = QtCore.QRectF(nav.left() + 8, nav.top() + 10 + i * 26, nav.width() - 16, 22)
        if t == "Keyboard Manager":
            p.setBrush(QtGui.QColor("#dde8fb"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(ir, 4, 4)
            sel = ir
        p.setPen(QtGui.QColor(TXT if t == "Keyboard Manager" else SUB))
        p.setFont(_font(11, t == "Keyboard Manager"))
        p.drawText(ir.adjusted(8, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, t)
    _ring(p, sel)
    p.setPen(QtGui.QColor(TXT))
    p.setFont(_font(15, True))
    p.drawText(QtCore.QPointF(nav.right() + 20, nav.top() + 30), "Keyboard Manager")
    p.setFont(_font(12))
    p.drawText(QtCore.QPointF(nav.right() + 20, nav.top() + 66), "Enable Keyboard Manager")
    tg = QtCore.QRectF(r.right() - 70, nav.top() + 52, 44, 22)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(BLUE))
    p.drawRoundedRect(tg, 11, 11)
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawEllipse(QtCore.QPointF(tg.right() - 11, tg.center().y()), 7, 7)
    _ring(p, tg)
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(11))
    p.drawText(QtCore.QPointF(nav.right() + 20, nav.top() + 104), T("켜짐 (On) 이 되게"))
    p.end()
    return pm


def step3():
    """바로 가기 키 다시 매핑 → 추가"""
    pm, p = _canvas()
    r = QtCore.QRectF(20, 14, W - 40, H - 28)
    _window(p, r, "PowerToys Settings  ›  Keyboard Manager")
    p.setPen(QtGui.QColor(TXT))
    p.setFont(_font(13, True))
    p.drawText(QtCore.QPointF(r.left() + 24, r.top() + 58), "Shortcuts")
    b = QtCore.QRectF(r.left() + 24, r.top() + 72, 170, 30)
    _button(p, b, "Remap a shortcut")
    _ring(p, b)
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(16, True))
    p.drawText(QtCore.QPointF(b.right() + 24, b.center().y() + 6), "→")
    w2 = QtCore.QRectF(b.right() + 56, r.top() + 40, r.right() - b.right() - 72, 120)
    _window(p, w2, "Remap shortcuts")
    a = QtCore.QRectF(w2.left() + 14, w2.top() + 44, 110, 28)
    _button(p, a, "+  Add", True)
    _ring(p, a)
    p.end()
    return pm


def step4(prog, args, start):
    """원래 키 Win+E / 동작 = 프로그램 실행 / 값 넣기 / 이미 실행 중 = 하나 더"""
    pm, p = _canvas()
    r = QtCore.QRectF(20, 8, W - 40, H - 16)
    _window(p, r, "Remap shortcuts")
    x, y = r.left() + 16, r.top() + 36
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(11))
    p.drawText(QtCore.QRectF(x, y, 110, 22), Qt.AlignVCenter, "Select / Shortcut")
    k1 = QtCore.QRectF(x + 112, y, 46, 22)
    k2 = QtCore.QRectF(x + 164, y, 30, 22)
    for k, t in ((k1, "Win"), (k2, "E")):
        _button(p, k, t)
    _ring(p, QtCore.QRectF(k1.left(), k1.top(), k2.right() - k1.left(), 22))
    p.setPen(QtGui.QColor(SUB))
    p.drawText(QtCore.QRectF(x + 210, y, 60, 22), Qt.AlignVCenter, "Action")
    act = QtCore.QRectF(x + 260, y, 130, 22)
    _button(p, act, "Run program  ▾")
    _ring(p, act)
    _field(p, x, y + 32, "Program (App)", prog, 330)
    _field(p, x, y + 58, "Args", args, 330)
    _field(p, x, y + 84, "Start in", start, 330)
    ir = _field(p, x, y + 110, "If running", "Start another", 150)
    _ring(p, ir)
    ok = QtCore.QRectF(r.right() - 90, r.bottom() - 30, 72, 24)
    _button(p, ok, "OK", True)
    p.end()
    return pm


class PtGuide(QtWidgets.QDialog):
    def __init__(self, parent, prog, args, start, on_auto=None):
        super().__init__(parent)
        self.setWindowTitle(T("Win+E 를 4Dir 로 — PowerToys 연결 방법"))
        self.resize(640, 760)
        lay = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel(T("윈도우 11 26H2 부터는 Win+E 를 바꾸는 기존 방식이 막힌 것으로 보입니다. "
                                  "마이크로소프트의 무료 도구 PowerToys 의 '키보드 관리자'로 Win+E 를 4Dir 에 연결하면 됩니다.") + "\n" +
                                T("PowerToys 를 설치·실행해 두면, 아래 [자동으로 연결] 이 3·4단계를 대신 합니다."))
        head.setWordWrap(True)
        lay.addWidget(head)
        row = QtWidgets.QHBoxLayout()
        installed = ptlink.exe_path() is not None
        self.btn_auto = QtWidgets.QPushButton("⚡ " + T("자동으로 연결"))
        self.btn_auto.setEnabled(installed and on_auto is not None)
        self.btn_auto.setToolTip(T("PowerToys 키보드 관리자에 'Win+E → 4Dir 새 창'을 넣습니다 (원래 설정은 보관)"))
        if on_auto:
            self.btn_auto.clicked.connect(lambda: (on_auto(), self._status()))
        row.addWidget(self.btn_auto)
        b = QtWidgets.QPushButton(T("PowerToys 받기 (Microsoft Store)"))
        b.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl(ptlink.STORE_URL)))
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.state = QtWidgets.QLabel()
        lay.addWidget(self.state)
        self._status()
        sc = QtWidgets.QScrollArea()
        sc.setWidgetResizable(True)
        inner = QtWidgets.QWidget()
        il = QtWidgets.QVBoxLayout(inner)
        steps = [
            (T("1. PowerToys 설치"), T("Microsoft Store 에서 PowerToys 를 받아 설치하고 실행합니다 (무료, 마이크로소프트 제작)."), step1()),
            (T("2. 키보드 관리자 켜기"), T("PowerToys 설정 창 왼쪽에서 Keyboard Manager(키보드 관리자)를 누르고 켭니다."), step2()),
            (T("3. 바로 가기 키 다시 매핑"), T("Remap a shortcut(바로 가기 키 다시 매핑)을 누르고, 열린 창에서 + Add(추가)를 누릅니다."), step3()),
            (T("4. Win+E → 4Dir"), T("Shortcut 칸에 Win+E, Action 은 Run program(프로그램 실행), 아래 세 칸에 이 값을 넣고 If running 은 Start another(하나 더 시작) → OK."),
             step4(prog, args, start)),
        ]
        for title, text, pm in steps:
            t = QtWidgets.QLabel(title)
            f = t.font()
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() + 1.5)
            t.setFont(f)
            il.addWidget(t)
            d = QtWidgets.QLabel(text)
            d.setWordWrap(True)
            il.addWidget(d)
            pic = QtWidgets.QLabel()
            pic.setPixmap(pm)
            il.addWidget(pic)
        vals = QtWidgets.QGroupBox(T("4단계에 넣을 값 (복사 단추)"))
        vl = QtWidgets.QFormLayout(vals)
        for label, v in (("Program", prog), ("Args", args), ("Start in", start)):
            h = QtWidgets.QHBoxLayout()
            e = QtWidgets.QLineEdit(v)
            e.setReadOnly(True)
            h.addWidget(e, 1)
            c = QtWidgets.QPushButton(T("복사"))
            c.clicked.connect(lambda *_, v=v: QtWidgets.QApplication.clipboard().setText(v))
            h.addWidget(c)
            vl.addRow(label, h)
        il.addWidget(vals)
        il.addStretch(1)
        sc.setWidget(inner)
        lay.addWidget(sc, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        log.info("PowerToys 안내 창 열림 (설치 %s, 연결 %s)", installed, ptlink.linked())

    def _status(self):
        inst = ptlink.exe_path() is not None
        if not inst:
            s = "⚪ " + T("PowerToys 가 설치되어 있지 않습니다")
        elif ptlink.linked():
            run = ptlink.running()
            s = "🟢 " + T("연결됨 — Win+E 를 누르면 4Dir 새 창") + ("" if run else "  ·  ⚠ " + T("PowerToys 를 실행해야 동작합니다"))
            if ptlink.kbm_enabled() is False:
                s += "  ·  ⚠ " + T("키보드 관리자가 꺼져 있습니다 (2단계)")
        else:
            s = "🟡 " + T("PowerToys 설치됨 — 아직 연결 안 됨")
        self.state.setText(s)
