# -*- coding: utf-8 -*-
"""확인값(SHA256) 보기 (v0.9.89 사용자 11/4): 고른 파일들의 SHA256 — 받은 zip 이 같은 파일인지 등.
뒤 스레드에서 계산(큰 파일도 창이 안 멈춤), 창을 닫으면 중단. '모두 복사' = '확인값  이름' 줄들."""
import os
import time
import hashlib
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets

log = logging.getLogger("QE.hash")


def sha256(path, cancel=lambda: False, chunk=4 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            if cancel():
                return None
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class _Sig(QtCore.QObject):
    one = QtCore.Signal(int, str)   # (줄 번호, 확인값 또는 '⚠ 오류')


class HashDialog(QtWidgets.QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("확인값 (SHA256)"))
        self.paths = paths
        self.vals = [""] * len(paths)
        self.stop = False
        lay = QtWidgets.QVBoxLayout(self)
        self.tbl = QtWidgets.QTreeWidget()
        self.tbl.setHeaderLabels([T("이름"), "SHA256"])
        self.tbl.setRootIsDecorated(False)
        self.tbl.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        for p in paths:
            it = QtWidgets.QTreeWidgetItem([os.path.basename(p), T("계산 중…")])
            it.setToolTip(0, p)
            it.setFont(1, mono)
            self.tbl.addTopLevelItem(it)
        self.tbl.setColumnWidth(0, 220)
        lay.addWidget(self.tbl)
        row = QtWidgets.QHBoxLayout()
        self.info = QtWidgets.QLabel()
        row.addWidget(self.info, 1)
        b = QtWidgets.QPushButton(T("모두 복사"))
        b.clicked.connect(self.copy_all)
        row.addWidget(b)
        c = QtWidgets.QPushButton(T("닫기"))
        c.clicked.connect(self.close)
        row.addWidget(c)
        lay.addLayout(row)
        self.resize(860, min(520, 140 + 24 * len(paths)))
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.sig = _Sig()
        self.sig.one.connect(self._one)
        self.t0 = time.time()
        threading.Thread(target=self._work, daemon=True, name="sha256").start()

    def _work(self):
        for i, p in enumerate(self.paths):
            if self.stop:
                return
            try:
                v = sha256(p, lambda: self.stop)
                if v is None:
                    return
            except OSError as e:
                v = "⚠ " + str(e)
            try:
                self.sig.one.emit(i, v)
            except RuntimeError:
                return
        log.info("확인값 %d개 %.1f초", len(self.paths), time.time() - self.t0)

    def _one(self, i, v):
        self.vals[i] = v
        it = self.tbl.topLevelItem(i)
        if it is not None:
            it.setText(1, v)
        done = sum(1 for x in self.vals if x)
        self.info.setText(T("{0} / {1}개 완료").format(done, len(self.paths)))

    def copy_all(self):
        lines = [f"{v}  {os.path.basename(p)}" for p, v in zip(self.paths, self.vals) if v]
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))
        self.info.setText(T("{0}줄 복사함").format(len(lines)))

    def closeEvent(self, ev):
        self.stop = True
        super().closeEvent(ev)
