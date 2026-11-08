# -*- coding: utf-8 -*-
"""두 글자 파일 비교 (TEXTDIFF_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '글자 파일 비교')

- open_dialog(parent, path_a, path_b) → 창: 나란히 두 칸(왼쪽 A · 오른쪽 B), 줄 번호, 추가 초록 · 삭제 빨강 · 바뀜 노랑 배경,
  바뀐 줄 안에서 달라진 글자는 더 진하게. 두 칸이 함께 스크롤(한 화면에 같이 그림)
- 위에 '차이 N곳 · 추가 N줄 · 삭제 N줄' · [이전 차이] [다음 차이] (Shift+F8 / F8) · [공백 무시] [대소문자 무시]
- 줄 단위 비교는 difflib (뒤 스레드 — 큰 파일도 화면 안 멈춤). 바뀐 줄 안 글자 비교는 화면에 보일 때만 계산
- 글자 방식: BOM → UTF-8 → CP949. 5MB 넘는 파일은 경고 후 진행, 이진 파일(앞 8KB 에 0 바이트)이면 '글자 파일이 아닙니다'
- 밝게·어둡게 테마 색 두 벌
- diff_rows(a_lines, b_lines, ignore_space, ignore_case) → (줄 목록, 통계) — 창 없이 쓰는 순수 함수
로그: bin\\log\\4Dir.log [QE.diff]
"""
import os
import re
import time
import difflib
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

TEXTDIFF_VER = "1.0.0"
log = logging.getLogger("QE.diff")
BIG = 5 * 1048576
TAB = 4


def read_text(path):
    """→ (글자, 글자 방식) · 이진이면 (None, None)"""
    with open(path, "rb") as f:
        b = f.read()
    if b.startswith(b"\xef\xbb\xbf"):
        return b[3:].decode("utf-8", "replace"), "utf-8-sig"
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        return b.decode("utf-16", "replace"), "utf-16"
    if b"\x00" in b[:8192]:
        return None, None
    try:
        return b.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return b.decode("cp949", "replace"), "cp949"


def _key(s, ignore_space, ignore_case):
    if ignore_space:
        s = re.sub(r"\s+", "", s)
    if ignore_case:
        s = s.lower()
    return s


def _opcodes(ka, kb):
    """앞뒤 같은 줄은 먼저 떼고(빠름) 가운데만 difflib — 같은 줄이 아주 많은 큰 파일에서 느려지던 것"""
    n, m = len(ka), len(kb)
    pre = 0
    while pre < n and pre < m and ka[pre] == kb[pre]:
        pre += 1
    suf = 0
    while suf < n - pre and suf < m - pre and ka[n - 1 - suf] == kb[m - 1 - suf]:
        suf += 1
    out = []
    if pre:
        out.append(("equal", 0, pre, 0, pre))
    mid_a, mid_b = ka[pre:n - suf], kb[pre:m - suf]
    if mid_a or mid_b:
        sm = difflib.SequenceMatcher(None, mid_a, mid_b, autojunk=len(mid_a) + len(mid_b) > 20000)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            out.append((tag, i1 + pre, i2 + pre, j1 + pre, j2 + pre))
    if suf:
        out.append(("equal", n - suf, n, m - suf, m))
    return out


def diff_rows(a, b, ignore_space=False, ignore_case=False):
    """나란히 보기 줄 목록 [(종류, A번호|None, B번호|None, 덩어리번호)] 종류 = eq add del chg
    + 통계 dict(hunks, added, deleted, starts=[덩어리 시작 줄 위치])"""
    ka = [_key(x, ignore_space, ignore_case) for x in a] if (ignore_space or ignore_case) else a
    kb = [_key(x, ignore_space, ignore_case) for x in b] if (ignore_space or ignore_case) else b
    rows, starts = [], []
    added = deleted = 0
    for tag, i1, i2, j1, j2 in _opcodes(ka, kb):
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append(("eq", i1 + k, j1 + k, -1))
            continue
        h = len(starts)
        starts.append(len(rows))
        if tag == "delete":
            deleted += i2 - i1
            for k in range(i2 - i1):
                rows.append(("del", i1 + k, None, h))
        elif tag == "insert":
            added += j2 - j1
            for k in range(j2 - j1):
                rows.append(("add", None, j1 + k, h))
        else:
            added += j2 - j1
            deleted += i2 - i1
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                ia = i1 + k if k < i2 - i1 else None
                ib = j1 + k if k < j2 - j1 else None
                rows.append(("chg" if ia is not None and ib is not None else ("del" if ib is None else "add"), ia, ib, h))
    return rows, dict(hunks=len(starts), added=added, deleted=deleted, starts=starts)


def inline_spans(sa, sb):
    """바뀐 줄 안 달라진 글자 위치 → ([(시작,끝)] A, [(시작,끝)] B)"""
    sm = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    ra, rb = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            if i2 > i1:
                ra.append((i1, i2))
            if j2 > j1:
                rb.append((j1, j2))
    return ra, rb


def _colors(dark):
    if dark:
        return dict(add="#1e4a2a", del_="#5a2626", chg="#4d4318", add2="#2f7a45", del2="#8a3434", chg2="#8a7420",
                    pad="#2a2a2a", num="#8a8f98", cur="#4a9eff", line="#444444")
    return dict(add="#dcf5dc", del_="#ffdcdc", chg="#fff4bf", add2="#8fdc8f", del2="#ff9e9e", chg2="#ffd75e",
                pad="#f0f0f0", num="#9aa0a6", cur="#1d6fd6", line="#cccccc")


class DiffView(QtWidgets.QAbstractScrollArea):
    """두 칸을 한 위젯이 그림 → 스크롤이 저절로 같이 움직임"""

    def __init__(self, parent=None):
        super().__init__(parent)
        f = QtGui.QFont("Consolas")
        f.setStyleHint(QtGui.QFont.Monospace)
        f.setPointSize(10)
        self.setFont(f)
        self.viewport().setFont(f)
        self.a, self.b, self.rows = [], [], []
        self.cur_hunk = -1
        self._inl = {}
        self.xoff = 0
        fm = QtGui.QFontMetrics(f)
        self.lh = fm.height() + 2
        self.cw = fm.horizontalAdvance("0")
        self.verticalScrollBar().valueChanged.connect(self.viewport().update)
        self.horizontalScrollBar().valueChanged.connect(self._hscroll)

    def set_data(self, a, b, rows):
        self.a = [x.expandtabs(TAB) for x in a]
        self.b = [x.expandtabs(TAB) for x in b]
        self.rows = rows
        self._inl = {}
        self.cur_hunk = -1
        self.maxlen = max([len(x) for x in self.a] + [len(x) for x in self.b] + [1])
        self._range()
        self.viewport().update()

    def _numw(self):
        return self.cw * (len(str(max(len(self.a), len(self.b), 1))) + 1) + 6

    def _range(self):
        vis = max(1, self.viewport().height() // self.lh)
        sb = self.verticalScrollBar()
        sb.setRange(0, max(0, len(self.rows) - vis + 1))
        sb.setPageStep(vis)
        half = self.viewport().width() // 2 - self._numw()
        hs = self.horizontalScrollBar()
        hs.setRange(0, max(0, self.maxlen * self.cw - half + self.cw * 2) if self.rows else 0)
        hs.setPageStep(max(1, half))
        hs.setSingleStep(self.cw * 4)

    def _hscroll(self, v):
        self.xoff = v
        self.viewport().update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._range()

    def scroll_to_row(self, r):
        vis = max(1, self.viewport().height() // self.lh)
        self.verticalScrollBar().setValue(max(0, r - vis // 4))
        self.viewport().update()

    def _spans(self, idx, ia, ib):
        v = self._inl.get(idx)
        if v is None:
            v = self._inl[idx] = inline_spans(self.a[ia], self.b[ib])
        return v

    def paintEvent(self, ev):
        p = QtGui.QPainter(self.viewport())
        pal = self.palette()
        base = pal.color(QtGui.QPalette.Base)
        dark = base.lightness() < 128
        c = _colors(dark)
        txt = pal.color(QtGui.QPalette.Text)
        W, H = self.viewport().width(), self.viewport().height()
        p.fillRect(0, 0, W, H, base)
        nw = self._numw()
        half = W // 2
        first = self.verticalScrollBar().value()
        fm = QtGui.QFontMetrics(self.font())
        asc = fm.ascent() + 1
        cur = None
        for vi in range(H // self.lh + 2):
            idx = first + vi
            if idx >= len(self.rows):
                break
            tag, ia, ib, h = self.rows[idx]
            y = vi * self.lh
            spans = self._spans(idx, ia, ib) if tag == "chg" else ([], [])
            for side, (no, lines, x0) in enumerate(((ia, self.a, 0), (ib, self.b, half))):
                bg = None
                if tag == "add":
                    bg = c["add"] if side == 1 else c["pad"]
                elif tag == "del":
                    bg = c["del_"] if side == 0 else c["pad"]
                elif tag == "chg":
                    bg = c["chg"]
                if no is None and tag != "eq":
                    bg = c["pad"]
                if bg:
                    p.fillRect(x0, y, half, self.lh, QtGui.QColor(bg))
                if no is None:
                    continue
                p.setPen(QtGui.QColor(c["num"]))
                p.drawText(QtCore.QRect(x0, y, nw - 6, self.lh), Qt.AlignRight | Qt.AlignVCenter, str(no + 1))
                p.save()
                p.setClipRect(x0 + nw, y, half - nw, self.lh)
                tx = x0 + nw - self.xoff
                s = lines[no]
                if len(s) > 4000:
                    s = s[:4000]
                if tag == "chg":
                    for a1, a2 in spans[side]:
                        x1 = fm.horizontalAdvance(s[:a1])
                        p.fillRect(QtCore.QRectF(tx + x1, y, max(2, fm.horizontalAdvance(s[a1:a2])), self.lh), QtGui.QColor(c["chg2"]))
                p.setPen(txt)
                p.drawText(tx, y + asc, s)
                p.restore()
            if h >= 0 and h == self.cur_hunk:
                cur = (cur[0] if cur else y, y + self.lh)
        p.setPen(QtGui.QColor(c["line"]))
        p.drawLine(half, 0, half, H)
        if cur:
            p.setPen(QtGui.QPen(QtGui.QColor(c["cur"]), 2))
            p.drawLine(1, cur[0], 1, cur[1])
            p.drawLine(half + 1, cur[0], half + 1, cur[1])
        p.end()

    def wheelEvent(self, ev):
        d = ev.angleDelta()
        if abs(d.x()) > abs(d.y()) or ev.modifiers() & Qt.ShiftModifier:
            v = d.x() or d.y()
            hs = self.horizontalScrollBar()
            hs.setValue(hs.value() - v // 2)
        else:
            sb = self.verticalScrollBar()
            sb.setValue(sb.value() - d.y() // 40)


class _Bridge(QtCore.QObject):
    done = QtCore.Signal(object)


class DiffDialog(QtWidgets.QDialog):
    def __init__(self, parent, path_a, path_b, ask=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowIcon(diff_icon(32))
        self.pa, self.pb = path_a, path_b
        self.setWindowTitle(T("글자 파일 비교") + f" — {os.path.basename(path_a)} ↔ {os.path.basename(path_b)}")
        self.resize(1100, 700)
        self.ta = self.tb = None
        self.stats = None
        self._gen = 0
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        bar = QtWidgets.QHBoxLayout()
        self.summary = QtWidgets.QLabel(T("비교 중…"))
        f = self.summary.font()
        f.setBold(True)
        self.summary.setFont(f)
        self.b_prev = QtWidgets.QPushButton(T("이전 차이"))
        self.b_next = QtWidgets.QPushButton(T("다음 차이"))
        self.b_prev.setToolTip("Shift+F8")
        self.b_next.setToolTip("F8")
        self.c_space = QtWidgets.QCheckBox(T("공백 무시"))
        self.c_case = QtWidgets.QCheckBox(T("대소문자 무시"))
        bar.addWidget(self.summary, 1)
        for w in (self.c_space, self.c_case, self.b_prev, self.b_next):
            bar.addWidget(w)
        lay.addLayout(bar)
        names = QtWidgets.QHBoxLayout()
        self.la = QtWidgets.QLabel(path_a)
        self.lb = QtWidgets.QLabel(path_b)
        for l in (self.la, self.lb):
            l.setTextInteractionFlags(Qt.TextSelectableByMouse)
            l.setMinimumWidth(10)
            names.addWidget(l, 1)
        lay.addLayout(names)
        self.view = DiffView()
        lay.addWidget(self.view, 1)
        self.bridge = _Bridge()
        self.bridge.done.connect(self._on_done)
        self.b_next.clicked.connect(lambda: self.jump(1))
        self.b_prev.clicked.connect(lambda: self.jump(-1))
        self.c_space.toggled.connect(lambda _v: self.compare())
        self.c_case.toggled.connect(lambda _v: self.compare())
        QtGui.QShortcut(QtGui.QKeySequence("F8"), self, lambda: self.jump(1))
        QtGui.QShortcut(QtGui.QKeySequence("Shift+F8"), self, lambda: self.jump(-1))
        QtGui.QShortcut(QtGui.QKeySequence("Escape"), self, self.close)
        self.ask = ask or (lambda title, text: QtWidgets.QMessageBox.question(self, title, text) == QtWidgets.QMessageBox.Yes)
        self._set_nav(False)
        QtCore.QTimer.singleShot(0, self._load)

    def _set_nav(self, on):
        for w in (self.b_prev, self.b_next, self.c_space, self.c_case):
            w.setEnabled(on)

    def _load(self):
        try:
            sa, sb = os.path.getsize(self.pa), os.path.getsize(self.pb)
        except OSError as e:
            self.summary.setText(T("파일을 읽을 수 없습니다: {0}").format(e))
            return
        log.info("비교 열기 %s (%d) ↔ %s (%d)", self.pa, sa, self.pb, sb)
        if max(sa, sb) > BIG:
            if not self.ask(T("큰 파일"), T("파일이 큽니다 ({0:,} KB). 비교에 시간이 걸릴 수 있습니다. 계속할까요?").format(max(sa, sb) // 1024)):
                self.summary.setText(T("취소됨"))
                log.info("큰 파일 비교 취소")
                return
        try:
            ta, ea = read_text(self.pa)
            tb, eb = read_text(self.pb)
        except OSError as e:
            self.summary.setText(T("파일을 읽을 수 없습니다: {0}").format(e))
            log.warning("비교 읽기 실패: %s", e)
            return
        if ta is None or tb is None:
            bad = self.pa if ta is None else self.pb
            self.summary.setText(T("글자 파일이 아닙니다: {0}").format(os.path.basename(bad)))
            log.info("이진 파일이라 비교 안 함 %s", bad)
            return
        self.la.setText(f"{self.pa}  ({ea})")
        self.lb.setText(f"{self.pb}  ({eb})")
        self.ta, self.tb = ta.splitlines(), tb.splitlines()
        self.compare()

    def compare(self):
        if self.ta is None:
            return
        self._gen += 1
        g = self._gen
        self._set_nav(False)
        self.summary.setText(T("비교 중…"))
        a, b, sp, cs = self.ta, self.tb, self.c_space.isChecked(), self.c_case.isChecked()
        br = self.bridge

        def run():
            t0 = time.perf_counter()
            try:
                rows, st = diff_rows(a, b, sp, cs)
            except Exception:
                log.exception("비교 오류")
                rows, st = None, None
            log.info("비교 %d줄 ↔ %d줄 공백무시=%s 대소문자무시=%s → %s %.0fms", len(a), len(b), sp, cs,
                     st and {k: v for k, v in st.items() if k != "starts"}, (time.perf_counter() - t0) * 1000)
            br.done.emit((g, rows, st))
        threading.Thread(target=run, name="textdiff", daemon=True).start()

    def _on_done(self, res):
        g, rows, st = res
        if g != self._gen:
            return
        self.c_space.setEnabled(True)
        self.c_case.setEnabled(True)
        if rows is None:
            self.summary.setText(T("비교하다가 오류가 났습니다 (기록 파일 참고)"))
            return
        self.stats = st
        self.view.set_data(self.ta, self.tb, rows)
        if st["hunks"] == 0:
            self.summary.setText(T("두 파일 내용이 같습니다"))
        else:
            self.summary.setText(T("차이 {0}곳 · 추가 {1}줄 · 삭제 {2}줄").format(f"{st['hunks']:,}", f"{st['added']:,}", f"{st['deleted']:,}"))
            self.b_prev.setEnabled(True)
            self.b_next.setEnabled(True)
            self.jump(1)

    def jump(self, d):
        if not self.stats or not self.stats["hunks"]:
            return
        n = self.stats["hunks"]
        h = self.view.cur_hunk + d
        h = 0 if h >= n else (n - 1 if h < 0 else h)
        self.view.cur_hunk = h
        self.view.scroll_to_row(self.stats["starts"][h])
        self.setWindowTitle(T("글자 파일 비교") + f" — {os.path.basename(self.pa)} ↔ {os.path.basename(self.pb)}  [{h + 1}/{n}]")

    def closeEvent(self, ev):
        self._gen += 1
        try:
            self.bridge.done.disconnect()
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(ev)


def open_dialog(parent, path_a, path_b):
    d = DiffDialog(parent, path_a, path_b)
    d.show()
    return d


def diff_icon(sz=16):
    """두 장 + 초록·빨강 줄"""
    def draw(p):
        for x in (1.5, 10.5):
            p.setPen(QtGui.QPen(QtGui.QColor("#6b7280"), 1.0))
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawRect(QtCore.QRectF(x, 2.5, 8, 15))
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#e5484d"))
        p.drawRect(QtCore.QRectF(3, 8, 5, 2))
        p.setBrush(QtGui.QColor("#3fae68"))
        p.drawRect(QtCore.QRectF(12, 8, 5, 2))
        p.setBrush(QtGui.QColor("#f2c14e"))
        p.drawRect(QtCore.QRectF(3, 12, 5, 2))
        p.drawRect(QtCore.QRectF(12, 12, 5, 2))
        p.setBrush(QtGui.QColor("#9ca3af"))
        p.drawRect(QtCore.QRectF(3, 4.5, 5, 1.5))
        p.drawRect(QtCore.QRectF(12, 4.5, 5, 1.5))
    return _icon(sz, draw)


def _icon(sz, draw):
    pm = QtGui.QPixmap(sz * 2, sz * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(sz * 2 / 20.0, sz * 2 / 20.0)
    draw(p)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QtGui.QIcon(pm)
