# -*- coding: utf-8 -*-
"""명령 찾기 창 (v0.9.89 사용자 11/4, Ctrl+Shift+P): 기능 이름 몇 글자 → 바로 실행.
항목 = (이름, 오른쪽 작은 글자(단축키·메뉴 위치), 실행할 함수). 띄어 쓴 낱말이 모두 들어간 것만 보임."""
import logging

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

log = logging.getLogger("QE.palette")


def match(text, items):
    """띄어 쓴 낱말이 모두 이름(또는 오른쪽 글자)에 들어간 항목 — 이름 앞부분에 맞으면 위로"""
    words = [w for w in text.lower().split() if w]
    if not words:
        return list(items)
    out = []
    for it in items:
        hay = (it[0] + " " + it[1]).lower()
        if all(w in hay for w in words):
            out.append((0 if it[0].lower().startswith(words[0]) else 1, it))
    return [it for _r, it in sorted(out, key=lambda x: x[0])]


class Palette(QtWidgets.QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("palette")
        self.items = items
        self.ran = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText(T("기능 이름을 입력하세요 (예: 비교, 크기, 색)"))
        self.edit.textChanged.connect(self._refill)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit)
        self.lst = QtWidgets.QTreeWidget()
        self.lst.setHeaderHidden(True)
        self.lst.setColumnCount(2)
        self.lst.setRootIsDecorated(False)
        self.lst.setUniformRowHeights(True)
        hd = self.lst.header()   # 이름 칸이 남는 폭 전부, 오른쪽(단축키·메뉴 위치)은 글자만큼
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hd.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.lst.itemActivated.connect(lambda *_: self.run())
        self.lst.itemClicked.connect(lambda *_: self.run())
        lay.addWidget(self.lst)
        self.resize(560, 420)
        self._refill("")

    def _refill(self, text):
        self.lst.clear()
        for name, hint, fn in match(text, self.items):
            it = QtWidgets.QTreeWidgetItem([name, hint])
            it.setForeground(1, QtGui.QColor("#8a8f98"))
            it.setTextAlignment(1, int(Qt.AlignRight | Qt.AlignVCenter))
            it.setData(0, Qt.UserRole, fn)
            self.lst.addTopLevelItem(it)
        if self.lst.topLevelItemCount():
            self.lst.setCurrentItem(self.lst.topLevelItem(0))

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
        self.ran = it.text(0)
        fn = it.data(0, Qt.UserRole)
        log.info("명령 찾기 → %s ('%s')", self.ran, self.edit.text())
        self.accept()
        if fn:
            QtCore.QTimer.singleShot(0, fn)   # 창이 닫힌 뒤 실행 (메뉴·대화상자가 이 창 위에 뜨지 않게)
