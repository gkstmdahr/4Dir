# -*- coding: utf-8 -*-
"""기능 검색 창 (v0.9.89 '명령 찾기', Ctrl+Shift+P) — 기능 이름 몇 글자 → 바로 실행.
PALETTE_VER 2.0.0 (0.9.113 빌드 2, 사용자 11/6 '설정창처럼 분리'): 따로 창(옮기기·크기 바꾸기), 실행해도 닫히지 않음(Esc 로 닫기),
찾는 글자가 없으면 분류별 목록, 고른 기능의 설명을 아래에.
항목 = (이름, 단축키, 실행할 함수, 분류, 설명). 띄어 쓴 낱말이 모두(이름·단축키·분류·설명 어디든) 들어간 것만 보임."""
import logging

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

log = logging.getLogger("QE.palette")
PALETTE_VER = "2.1.0"   # 2.1.0: 줄 색 번갈아, 분류 제목 줄 색


def _norm(it):
    it = tuple(it) + ("", "", "")
    return it[0], it[1], it[2], it[3] or "", it[4] or ""


def match(text, items):
    """띄어 쓴 낱말이 모두 들어간 항목 — 이름 앞부분에 맞으면 위로, 이름에 들어가면 그다음"""
    words = [w for w in text.lower().split() if w]
    items = [_norm(x) for x in items]
    if not words:
        return items
    out = []
    for it in items:
        name = it[0].lower()
        hay = " ".join((name, it[1], it[3], it[4])).lower()
        if all(w in hay for w in words):
            out.append((0 if name.startswith(words[0]) else 1 if all(w in name for w in words) else 2, it))
    return [it for _r, it in sorted(out, key=lambda x: x[0])]


class Palette(QtWidgets.QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent, Qt.Window)
        self.setObjectName("palette")
        self.setWindowTitle(T("기능 검색"))
        self.items = [_norm(x) for x in items]
        self.ran = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText(T("기능 이름을 입력하세요 (예: 비교, 크기, 색)"))
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._refill)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit)
        self.lst = QtWidgets.QTreeWidget()
        self.lst.setHeaderHidden(True)
        self.lst.setColumnCount(2)
        self.lst.setUniformRowHeights(True)
        self.lst.setAlternatingRowColors(True)   # 0.9.113 빌드 3: 흰색·연한 파란색 번갈아 (이름과 단축키 줄 맞추기 쉽게)
        dark = self.palette().base().color().lightness() < 128
        self._alt, self._head = ("#232b38", "#2c3e5c") if dark else ("#edf4ff", "#cfe0fa")
        self.lst.setStyleSheet(f"QTreeWidget {{ alternate-background-color: {self._alt}; }}")
        hd = self.lst.header()   # 이름 칸이 남는 폭 전부, 오른쪽(단축키)은 글자만큼
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hd.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.lst.itemActivated.connect(lambda *_: self.run())   # 두 번 누르기·Enter
        self.lst.currentItemChanged.connect(lambda *_: self._show_desc())
        lay.addWidget(self.lst, 1)
        self.desc = QtWidgets.QLabel()
        self.desc.setWordWrap(True)
        self.desc.setMinimumHeight(36)
        self.desc.setStyleSheet("color:#6b7280;")
        lay.addWidget(self.desc)
        hint = QtWidgets.QLabel(T("Enter 또는 두 번 누르기 = 실행 · 실행해도 창은 그대로 · Esc = 닫기"))
        hint.setStyleSheet("color:#8a8f98; font-size:11px;")
        lay.addWidget(hint)
        self.resize(560, 620)
        self._refill("")

    def _row(self, it, parent=None):
        name, key, fn, cat, desc = it
        w = QtWidgets.QTreeWidgetItem([name, key])
        w.setForeground(1, QtGui.QColor("#8a8f98"))
        w.setTextAlignment(1, int(Qt.AlignRight | Qt.AlignVCenter))
        w.setData(0, Qt.UserRole, fn)
        w.setData(0, Qt.UserRole + 1, desc)
        w.setData(0, Qt.UserRole + 2, cat)
        if desc:
            w.setToolTip(0, desc)
        if parent is None:
            self.lst.addTopLevelItem(w)
        else:
            parent.addChild(w)
        return w

    def _refill(self, text):
        self.lst.clear()
        rows = match(text, self.items)
        first = None
        if text.strip():   # 찾는 중: 맞는 순서대로 한 줄씩 (오른쪽 = 단축키, 없으면 분류)
            self.lst.setRootIsDecorated(False)
            for it in rows:
                w = self._row((it[0], it[1] or it[3]) + it[2:])
                first = first or w
        else:   # 분류별
            self.lst.setRootIsDecorated(True)
            heads = {}
            for it in rows:
                c = it[3] or T("기타")
                if c not in heads:
                    h = QtWidgets.QTreeWidgetItem([c])
                    f = h.font(0)
                    f.setBold(True)
                    h.setFont(0, f)
                    h.setFlags(Qt.ItemIsEnabled)
                    for col in (0, 1):
                        h.setBackground(col, QtGui.QColor(self._head))
                    self.lst.addTopLevelItem(h)
                    heads[c] = h
                w = self._row(it, heads[c])
                first = first or w
            self.lst.expandAll()
        if first is not None:
            self.lst.setCurrentItem(first)
        self._show_desc()

    def _show_desc(self):
        it = self.lst.currentItem()
        d = it.data(0, Qt.UserRole + 1) if it is not None else ""
        self.desc.setText(d or "")

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                QtWidgets.QApplication.sendEvent(self.lst, ev)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.run()
                return True
        return super().eventFilter(obj, ev)

    def run(self):
        it = self.lst.currentItem()
        if it is None:
            return
        fn = it.data(0, Qt.UserRole)
        if not fn:   # 분류 제목
            return
        self.ran = it.text(0)
        log.info("기능 검색 → %s ('%s')", self.ran, self.edit.text())
        QtCore.QTimer.singleShot(0, fn)   # 이 처리 뒤 실행 (메뉴·대화상자가 이 창 이벤트 안에서 뜨지 않게)
