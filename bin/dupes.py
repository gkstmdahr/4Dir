# -*- coding: utf-8 -*-
"""중복 파일 찾기 (DUPES_VER 1.0.0, 빌드 20 — 사용자 11/5 '추천 5개 다', 경쟁 앱 조사 4번)

- 범위: 고른 폴더들(없으면 지금 폴더) 아래 전부, 0바이트·바로 가기(.lnk)는 뺌
- 판정: 크기가 같은 것끼리 → 앞 64KB 지문 → 전체 SHA256 이 같으면 '내용이 같은 파일' (이름은 상관없음)
- 뒤 스레드에서, 진행 표시·취소. 결과는 묶음(같은 내용)별로, 고른 것은 휴지통으로(되돌리기 가능)
- 파일을 고치지 않음(읽기만). 지우기는 사용자가 고르고 확인했을 때만, 휴지통으로
로그: bin\\log\\4Dir.log [QE.dupes]
"""
import os
import time
import hashlib
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

DUPES_VER = "1.0.0"
log = logging.getLogger("QE.dupes")
HEAD = 65536
SKIP_DIRS = {"$recycle.bin", "system volume information", ".svn", ".git"}


def size_text(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:,.0f} {u}" if u == "B" else f"{n:,.1f} {u}"
        n /= 1024.0


def _hash(path, limit=None, cancel=lambda: False):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        left = limit
        while True:
            if cancel():
                return None
            b = f.read(1048576 if left is None else min(1048576, left))
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
                if left <= 0:
                    break
    return h.hexdigest()


def find(roots, progress=lambda kind, n, total: None, cancel=lambda: False):
    """[(크기, [경로…])] — 내용이 같은 묶음, 낭비 큰 순"""
    t0 = time.time()
    by_size, n = {}, 0
    stack = list(roots)
    seen = set()
    while stack:
        if cancel():
            return []
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name.lower() not in SKIP_DIRS and not (e.stat(follow_symlinks=False).st_file_attributes & 0x400):
                                stack.append(e.path)
                            continue
                        if e.name.lower().endswith(".lnk"):
                            continue
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if st.st_size <= 0:
                        continue
                    key = os.path.normcase(e.path)
                    if key in seen:
                        continue
                    seen.add(key)
                    by_size.setdefault(st.st_size, []).append(e.path)
                    n += 1
                    if n % 2000 == 0:
                        progress("scan", n, 0)
        except OSError:
            pass
    cands = [(s, ps) for s, ps in by_size.items() if len(ps) > 1]
    total = sum(len(ps) for _s, ps in cands)
    log.info("중복 찾기 훑음 %d개 %.1f초, 크기 같은 후보 %d개(%d묶음)", n, time.time() - t0, total, len(cands))
    out, done = [], 0
    for size, ps in cands:
        groups = {}
        for p in ps:   # 앞부분 지문으로 먼저 거름
            if cancel():
                return []
            try:
                k = _hash(p, HEAD, cancel) if size > HEAD else _hash(p, None, cancel)
            except OSError:
                k = None
            done += 1
            if done % 50 == 0:
                progress("hash", done, total)
            if k:
                groups.setdefault(k, []).append(p)
        for g in groups.values():
            if len(g) < 2:
                continue
            if size <= HEAD:
                out.append((size, sorted(g)))
                continue
            full = {}
            for p in g:
                try:
                    k = _hash(p, None, cancel)
                except OSError:
                    k = None
                if k:
                    full.setdefault(k, []).append(p)
            out += [(size, sorted(x)) for x in full.values() if len(x) > 1]
    out.sort(key=lambda t: -(t[0] * (len(t[1]) - 1)))
    log.info("중복 찾기 끝: 묶음 %d개, 낭비 %s, 전체 %.1f초", len(out), size_text(sum(s * (len(g) - 1) for s, g in out)), time.time() - t0)
    return out


class _Sig(QtCore.QObject):
    progress = QtCore.Signal(str, int, int)
    done = QtCore.Signal(list)
    deleted = QtCore.Signal()   # 휴지통 작업 끝 (작업 스레드 → 화면)


class DupeDialog(QtWidgets.QDialog):
    """결과 창 (모달 아님): 묶음별 파일, 체크한 것을 휴지통으로. open_loc(경로) = 4Dir 에서 그 파일 위치, trash(경로들, done) = 휴지통"""

    def __init__(self, roots, open_loc, trash, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("중복 파일 찾기") + " — 4Dir")
        self.resize(820, 560)
        self.roots, self.open_loc, self.trash = roots, open_loc, trash
        self._cancel = False
        lay = QtWidgets.QVBoxLayout(self)
        self.lbl = QtWidgets.QLabel(T("찾는 곳: {0}").format("; ".join(roots)))
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        self.prog = QtWidgets.QProgressBar()
        self.prog.setRange(0, 0)
        lay.addWidget(self.prog)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels([T("이름"), T("위치"), T("수정한 날짜")])
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 330)
        self.tree.itemDoubleClicked.connect(self._open)
        self.tree.itemChanged.connect(lambda *_: self._count())
        lay.addWidget(self.tree, 1)
        row = QtWidgets.QHBoxLayout()
        self.btn_auto = QtWidgets.QPushButton(T("묶음마다 하나만 남기고 고르기"))
        self.btn_auto.setToolTip(T("묶음마다 가장 오래된 파일(원본일 가능성이 큰 것)을 남기고 나머지를 고릅니다"))
        self.btn_auto.clicked.connect(self._auto)
        self.btn_none = QtWidgets.QPushButton(T("고르기 풀기"))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_del = QtWidgets.QPushButton(T("고른 것 휴지통으로"))
        self.btn_del.clicked.connect(self._delete)
        self.btn_close = QtWidgets.QPushButton(T("닫기"))
        self.btn_close.clicked.connect(self.close)
        row.addWidget(self.btn_auto)
        row.addWidget(self.btn_none)
        row.addStretch(1)
        self.sel_lbl = QtWidgets.QLabel()
        row.addWidget(self.sel_lbl)
        row.addWidget(self.btn_del)
        row.addWidget(self.btn_close)
        lay.addLayout(row)
        for b in (self.btn_auto, self.btn_none, self.btn_del):
            b.setEnabled(False)
        self.sig = _Sig()
        self.sig.progress.connect(self._on_progress)
        self.sig.done.connect(self._on_done)
        self.sig.deleted.connect(self._after_delete)
        self.groups = []
        log.info("중복 찾기 시작 %s", roots)
        threading.Thread(target=self._run, daemon=True, name="dupes").start()

    def _run(self):
        try:
            res = find(self.roots, lambda k, n, t: self.sig.progress.emit(k, n, t), lambda: self._cancel)
        except Exception:
            log.exception("중복 찾기 실패")
            res = []
        try:
            self.sig.done.emit(res)
        except RuntimeError:
            pass

    def _on_progress(self, kind, n, total):
        if kind == "scan":
            self.lbl.setText(T("파일 훑는 중… {0:,}개").format(n))
        else:
            self.prog.setRange(0, max(1, total))
            self.prog.setValue(n)
            self.lbl.setText(T("내용 비교 중… {0:,} / {1:,}").format(n, total))

    def _on_done(self, groups):
        self.groups = groups
        self.prog.setRange(0, 1)
        self.prog.setValue(1)
        waste = sum(s * (len(g) - 1) for s, g in groups)
        self.lbl.setText(T("내용이 같은 파일 묶음 {0:,}개 · 정리하면 {1} 아낌").format(len(groups), size_text(waste)) if groups
                         else T("내용이 같은 파일이 없습니다"))
        self.tree.blockSignals(True)
        bold = self.tree.font()
        bold.setBold(True)
        for size, g in groups:
            top = QtWidgets.QTreeWidgetItem([T("{0}개 · 각 {1}").format(len(g), size_text(size)), "", ""])
            top.setFont(0, bold)
            top.setFlags(Qt.ItemIsEnabled)
            for p in g:
                try:
                    mt = os.path.getmtime(p)
                except OSError:
                    mt = 0
                it = QtWidgets.QTreeWidgetItem([os.path.basename(p), os.path.dirname(p), time.strftime("%Y-%m-%d %H:%M", time.localtime(mt)) if mt else ""])
                it.setData(0, Qt.UserRole, p)
                it.setData(2, Qt.UserRole, mt)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Unchecked)
                it.setToolTip(0, p)
                top.addChild(it)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        for b in (self.btn_auto, self.btn_none, self.btn_del):
            b.setEnabled(bool(groups))
        self._count()

    def _files(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            yield top, [top.child(j) for j in range(top.childCount())]

    def _auto(self):
        self.tree.blockSignals(True)
        for top, kids in self._files():
            keep = min(kids, key=lambda it: (it.data(2, Qt.UserRole) or 0, len(it.data(0, Qt.UserRole))))
            for it in kids:
                it.setCheckState(0, Qt.Unchecked if it is keep else Qt.Checked)
        self.tree.blockSignals(False)
        self._count()

    def _set_all(self, on):
        self.tree.blockSignals(True)
        for top, kids in self._files():
            for it in kids:
                it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        self.tree.blockSignals(False)
        self._count()

    def checked(self):
        return [it.data(0, Qt.UserRole) for top, kids in self._files() for it in kids if it.checkState(0) == Qt.Checked]

    def _count(self):
        ps = self.checked()
        tot = 0
        for p in ps:
            try:
                tot += os.path.getsize(p)
            except OSError:
                pass
        self.sel_lbl.setText(T("고름 {0:,}개 · {1}").format(len(ps), size_text(tot)) if ps else "")
        self.btn_del.setEnabled(bool(ps))

    def _delete(self):
        ps = self.checked()
        if not ps:
            return
        full = [kids for top, kids in self._files() if kids and all(it.checkState(0) == Qt.Checked for it in kids)]
        msg = T("고른 {0:,}개를 휴지통으로 보냅니다 (되돌리기·휴지통에서 복원 가능).").format(len(ps))
        if full:
            msg += "\n\n" + T("⚠ 묶음 {0}개는 모든 파일을 골랐습니다 — 그 내용이 하나도 남지 않습니다.").format(len(full))
        if QtWidgets.QMessageBox.question(self, T("중복 파일 찾기"), msg) != QtWidgets.QMessageBox.Yes:
            return
        log.info("중복 파일 휴지통으로 %d개 (전부 고른 묶음 %d)", len(ps), len(full))
        self.trash(ps, self.sig.deleted.emit)

    def _after_delete(self):
        self.tree.blockSignals(True)
        for top, kids in list(self._files()):
            for it in kids:
                if not os.path.exists(it.data(0, Qt.UserRole)):
                    top.removeChild(it)
            if top.childCount() < 2:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(top))
        self.tree.blockSignals(False)
        self._count()

    def _open(self, it, _col):
        p = it.data(0, Qt.UserRole)
        if p:
            self.open_loc(p)

    def closeEvent(self, ev):
        self._cancel = True
        super().closeEvent(ev)
