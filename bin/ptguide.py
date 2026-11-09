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

PTGUIDE_VER = "1.2.0"   # 1.2.0 (빌드 4): PowerToys 화면 이름 = 설치된 PowerToys 의 공식 번역(ptlabels.json, 10개 언어), 긴 이름은 단추에 맞게 줄임 /   # 1.1.0 (0.9.120, 사용자 11/10 '그림이 실제 메뉴와 다름'): PowerToys 0.102 실제 화면대로 다시 그림, 한국어 윈도우면 PowerToys 한국어 이름
log = logging.getLogger("QE.ptguide")
W, H = 520, 210
BLUE, LINE, TXT, SUB, BG, WIN_BG = "#2f6fd0", "#c9ced6", "#1f2328", "#5f6b7a", "#f7f8fa", "#ffffff"


def _canvas(h=None):
    h = h or H
    dpr = 2
    pm = QtGui.QPixmap(W * dpr, h * dpr)
    pm.fill(QtGui.QColor(BG))
    pm.setDevicePixelRatio(dpr)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
    return pm, p


def _font(px, bold=False):
    try:   # 빌드 4: 그림 글자는 PowerToys 화면 언어(윈도우 언어)에 맞는 글꼴 — 일본어 'ー' 가 Segoe UI 로는 줄표처럼 보였음
        import i18n
        fam = i18n.FONTS.get(i18n.windows_lang(), i18n.DEFAULT_FONT)
    except Exception:
        fam = "Segoe UI"
    f = QtGui.QFont(fam)
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
    px = 12   # 빌드 4: 언어마다 이름 길이가 달라 → 단추에 맞게 글자를 줄이고(9px 까지), 그래도 길면 …
    f = _font(px, primary)
    while px > 9 and QtGui.QFontMetrics(f).horizontalAdvance(text) > r.width() - 8:
        px -= 1
        f = _font(px, primary)
    p.setFont(f)
    p.drawText(r, Qt.AlignCenter, QtGui.QFontMetrics(f).elidedText(text, Qt.ElideRight, int(r.width() - 6)))


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
    b = QtCore.QRectF(tile.right() + 20, tile.top() + 66, 130, 28)
    _button(p, b, T("설치") + " (Get)", True)
    _ring(p, b)
    p.end()
    return pm


_PTL = None


def P(key):
    """PowerToys 화면 이름 — 윈도우 표시 언어에 맞는 PowerToys 공식 번역 (bin\\ptlabels.json, 설치된 PowerToys 0.102 의
    리소스(PRI)에서 뽑음, 0.9.120 빌드 4). 4Dir 가 모르는 언어면 영어"""
    global _PTL
    if _PTL is None:
        import os, json
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ptlabels.json"), encoding="utf-8") as f:
                _PTL = json.load(f)
        except Exception:
            log.exception("PowerToys 이름표 읽기 실패")
            _PTL = {}
    try:
        import i18n
        lang = i18n.windows_lang()
    except Exception:
        lang = "en"
    d = _PTL.get(key) or {}
    return d.get(lang) or d.get("en") or key


def _toggle(p, r, on=True):
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(BLUE if on else "#c9ced6"))
    p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawEllipse(QtCore.QPointF(r.right() - r.height() / 2 if on else r.left() + r.height() / 2, r.center().y()), r.height() / 2 - 4, r.height() / 2 - 4)


def _nav(p, r):
    """PowerToys 0.102 설정 창 왼쪽 메뉴 (11/10 회사 PC 실측 화면을 본뜸) — Keyboard Manager 칸 돌려줌"""
    nav = QtCore.QRectF(r.left() + 1, r.top() + 27, 168, r.height() - 28)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#f1f3f6"))
    p.drawRect(nav)
    items = [(P("home"), 0), (P("general"), 0), (P("system_tools"), 0), (P("windowing"), 0),
             (P("input_output"), 0), (P("kbm"), 1), (P("mouse_utils"), 1)]
    sel = None
    for i, (t, sub) in enumerate(items):
        ir = QtCore.QRectF(nav.left() + 6 + sub * 14, nav.top() + 6 + i * 21, nav.width() - 12 - sub * 14, 19)
        if t == P("kbm"):
            p.setBrush(QtGui.QColor("#dde8fb"))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(ir, 4, 4)
            sel = ir
        p.setPen(QtGui.QColor(TXT if t == P("kbm") else SUB))
        p.setFont(_font(11, t == P("kbm")))
        p.drawText(ir.adjusted(6, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, t)
    return nav, sel


def step2():
    """PowerToys 설정 → 입력/출력 → Keyboard Manager → 켜기"""
    pm, p = _canvas()
    r = QtCore.QRectF(20, 14, W - 40, H - 28)
    _window(p, r, P("pt_settings"))
    nav, sel = _nav(p, r)
    _ring(p, sel)
    x = nav.right() + 18
    p.setPen(QtGui.QColor(TXT))
    p.setFont(_font(16, True))
    p.drawText(QtCore.QPointF(x, nav.top() + 30), P("kbm"))
    card = QtCore.QRectF(x, nav.top() + 50, r.right() - x - 14, 40)
    p.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawRoundedRect(card, 6, 6)
    p.setPen(QtGui.QColor(TXT))
    p.setFont(_font(12))
    p.drawText(card.adjusted(12, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, P("kbm"))
    tg = QtCore.QRectF(card.right() - 56, card.center().y() - 10, 42, 20)
    _toggle(p, tg, True)
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(11))
    p.drawText(QtCore.QRectF(tg.left() - 50, tg.top(), 44, 20), Qt.AlignVCenter | Qt.AlignRight, P("on"))
    _ring(p, tg)
    p.end()
    return pm


def step3():
    """편집기 열기 → + 새 항목"""
    pm, p = _canvas()
    r = QtCore.QRectF(20, 14, W - 40, H - 28)
    _window(p, r, P("pt_settings") + "  ›  " + P("kbm"))
    p.setPen(QtGui.QColor(TXT))
    p.setFont(_font(12, True))
    p.drawText(QtCore.QPointF(r.left() + 20, r.top() + 54), P("editor"))
    card = QtCore.QRectF(r.left() + 20, r.top() + 64, 200, 46)
    p.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawRoundedRect(card, 6, 6)
    b = QtCore.QRectF(card.right() - 112, card.center().y() - 13, 102, 26)
    _button(p, b, P("open_editor"), True)
    _ring(p, b)
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(18, True))
    p.drawText(QtCore.QPointF(card.right() + 14, card.center().y() + 6), "→")
    w2 = QtCore.QRectF(card.right() + 44, r.top() + 36, r.right() - card.right() - 58, 130)
    _window(p, w2, P("kbm"))
    a = QtCore.QRectF(w2.left() + 14, w2.top() + 40, 96, 26)
    _button(p, a, "+  " + P("new"), True)
    _ring(p, a)
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(11, True))
    p.drawText(QtCore.QPointF(w2.left() + 14, w2.top() + 92), P("programs"))
    p.end()
    return pm


def step4(prog, args, start):
    """새로운 다시 매핑 추가: 트리거 Win+E · 작업 '앱 열기' · 경로·인수·시작 폴더 · 이미 실행 중인 경우 '다른 시작...' · 저장"""
    H4 = 262
    pm, p = _canvas(H4)
    r = QtCore.QRectF(10, 4, W - 20, H4 - 8)
    _window(p, r, P("add_remap"))
    lx, y0 = r.left() + 14, r.top() + 34
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(10, True))
    p.drawText(QtCore.QPointF(lx, y0 + 8), P("trigger"))
    _button(p, QtCore.QRectF(lx, y0 + 14, 160, 20), P("key_or_shortcut") + "  ▾")
    k1, k2 = QtCore.QRectF(lx + 28, y0 + 44, 44, 22), QtCore.QRectF(lx + 78, y0 + 44, 30, 22)
    _button(p, k1, "Win")
    _button(p, k2, "E")
    _ring(p, QtCore.QRectF(k1.left(), k1.top(), k2.right() - k1.left(), 22))
    p.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
    p.drawLine(QtCore.QPointF(lx + 172, y0), QtCore.QPointF(lx + 172, r.bottom() - 34))
    rx = lx + 186
    p.setPen(QtGui.QColor(SUB))
    p.setFont(_font(10, True))
    p.drawText(QtCore.QPointF(rx, y0 + 8), P("action"))
    act = QtCore.QRectF(rx, y0 + 14, 120, 20)
    _button(p, act, P("open_app") + "  ▾")
    _ring(p, act)

    def fld(y, label, value, w=270, ring=False):
        p.setPen(QtGui.QColor(SUB))
        p.setFont(_font(10))
        p.drawText(QtCore.QPointF(rx, y), label)
        fr = QtCore.QRectF(rx, y + 5, w, 19)
        p.setPen(QtGui.QPen(QtGui.QColor(LINE), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawRoundedRect(fr, 3, 3)
        p.setPen(QtGui.QColor(TXT))
        p.drawText(fr.adjusted(5, 0, -5, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   QtGui.QFontMetrics(_font(10)).elidedText(value, Qt.ElideMiddle, int(fr.width() - 10)))
        if ring:
            _ring(p, fr)
    fld(y0 + 54, P("program_path"), prog)
    fld(y0 + 92, P("args"), args)
    fld(y0 + 130, P("start_in"), start)
    fld(y0 + 168, P("if_running"), P("start_another"), 130, True)
    sv = QtCore.QRectF(r.left() + 14, r.bottom() - 28, 150, 22)
    _button(p, sv, P("save"), True)
    _ring(p, sv)
    p.end()
    return pm


class PtGuide(QtWidgets.QDialog):
    def __init__(self, parent, prog, args, start, on_auto=None):
        super().__init__(parent)
        self.setWindowTitle(T("Win+E 를 4Dir 로 — PowerToys 연결 방법"))
        self.resize(640, 760)
        lay = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel(T("윈도우 11 26H2 부터는 윈도우가 Win+E 를 다른 프로그램에 넘기는 기본 방식을 막습니다. "
                                  "그래서 마이크로소프트의 무료 도구 PowerToys 의 '키보드 관리자'가 Win+E 를 받아 4Dir 를 엽니다.") + "\n" +
                                T("1·2단계(설치·키보드 관리자 켜기)만 하면, 아래 [자동으로 연결] 이 3·4단계를 대신 합니다."))
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
            (T("2. 키보드 관리자 켜기"),
             T("PowerToys 설정 왼쪽 '{0}' 아래 '{1}' 를 누르고 켭니다. (4Dir 설정의 [키보드 관리자 켜러 가기] 가 이 화면을 바로 엽니다)").format(P("input_output"), P("kbm")), step2()),
            (T("3. {0} → {1}").format(P("open_editor"), P("new")),
             T("같은 화면의 [{0}] 를 누르고, 열린 {1} 창에서 [+ {2}] 을 누릅니다.").format(P("open_editor"), P("kbm"), P("new")), step3()),
            (T("4. Win+E → 4Dir"),
             T("'{0}' 칸을 누르고 Win+E 를 누릅니다. '{1}'을 '{2}'(으)로 바꾸고 아래 값을 넣은 뒤, '{3}'을 '{4}'(으)로 → {5}.").format(
                 P("trigger"), P("action"), P("open_app"), P("if_running"), P("start_another"), P("save")),
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
