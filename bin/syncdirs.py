# -*- coding: utf-8 -*-
"""폴더 맞추기 (SYNCDIRS_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '폴더 맞추기(동기화)')

- 두 칸 폴더(왼쪽 A · 오른쪽 B)를 하위 폴더까지 비교 → 무엇을 어디로 복사할지 목록으로 보여 줌 → 사용자가 고르고 [실행]
- 방향: A → B (B 를 A 에 맞춤) · A ← B · 양쪽(더 새것이 이김)
- 판정: 한쪽에만 있음 / 날짜가 더 새것(2초 오차 허용, FAT·네트워크) / 날짜 같고 크기 다름 = '다름'(방향대로)
- '반대쪽에만 있는 것 지우기'(거울 맞춤): 기본 끔, 켜면 휴지통으로(되돌리기 가능)
- 복사는 뒤 스레드에서 shutil.copy2(날짜 유지), 진행·취소. 덮어쓰는 파일은 그대로 덮음(목록에서 미리 보여 줌)
로그: bin\\log\\4Dir.log [QE.sync]
"""
import os
import time
import shutil
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

SYNCDIRS_VER = "1.0.0"
log = logging.getLogger("QE.sync")
SKIP_DIRS = {"$recycle.bin", "system volume information"}
TOL = 2.0


def scan(root, cancel=lambda: False):
    """{상대 경로(소문자): (상대 경로, 폴더?, 크기, 날짜)}"""
    out = {}
    stack = [""]
    while stack:
        if cancel():
            return out
        rel = stack.pop()
        d = os.path.join(root, rel) if rel else root
        try:
            it = os.scandir(d)
        except OSError as ex:
            log.warning("읽기 실패 %s: %s", d, ex)
            continue
        with it:
            for de in it:
                r = os.path.join(rel, de.name) if rel else de.name
                try:
                    isd = de.is_dir(follow_symlinks=False)
                    st = de.stat(follow_symlinks=False)
                except OSError:
                    continue
                if isd and de.name.lower() in SKIP_DIRS:
                    continue
                out[r.lower()] = (r, isd, -1 if isd else st.st_size, st.st_mtime)
                if isd:
                    stack.append(r)
    return out


def plan(a_root, b_root, direction, mirror, cancel=lambda: False):
    """[(동작, 상대 경로, 이유)] 동작 = 'a2b' 'b2a' 'del_b' 'del_a'. direction = 'a2b' 'b2a' 'both'"""
    A = scan(a_root, cancel)
    B = scan(b_root, cancel)
    ops = []
    for key in sorted(set(A) | set(B)):
        a, b = A.get(key), B.get(key)
        if a and b:
            if a[1] or b[1]:
                continue   # 폴더끼리(안쪽은 따로 비교) · 폴더↔파일 같은 이름은 건드리지 않음
            if abs(a[3] - b[3]) <= TOL:
                if a[2] == b[2]:
                    continue
                if direction == "both":
                    continue   # 날짜가 같은데 크기만 다르면 어느 쪽이 맞는지 모름 → 양쪽 모드에서는 건너뜀
                ops.append((direction, a[0], "diff"))
                continue
            newer_a = a[3] > b[3]
            if direction == "both":
                ops.append(("a2b" if newer_a else "b2a", a[0], "newer"))
            elif direction == "a2b":
                ops.append(("a2b", a[0], "newer" if newer_a else "older"))
            else:
                ops.append(("b2a", a[0], "newer" if not newer_a else "older"))
        elif a:
            if direction in ("a2b", "both"):
                ops.append(("a2b", a[0], "only"))
            elif mirror:
                ops.append(("del_a", a[0], "only"))
        else:
            if direction in ("b2a", "both"):
                ops.append(("b2a", b[0], "only"))
            elif mirror:
                ops.append(("del_b", b[0], "only"))
    # 폴더째 복사·지우기면 그 안쪽 항목은 따로 할 필요 없음
    whole = {(op, rel.lower()) for op, rel, why in ops if why == "only" and os.path.isdir(os.path.join(a_root if op in ("a2b", "del_a") else b_root, rel))}
    out = []
    for op, rel, why in ops:
        parent = os.path.dirname(rel).lower()
        skip = False
        while parent:
            if (op, parent) in whole:
                skip = True
                break
            parent = os.path.dirname(parent)
        if not skip:
            out.append((op, rel, why))
    return out


def _copy(src, dst, cancel):
    if os.path.isdir(src):
        if os.path.exists(dst):
            for n in os.listdir(src):
                if cancel():
                    return
                _copy(os.path.join(src, n), os.path.join(dst, n), cancel)
        else:
            shutil.copytree(src, dst, copy_function=shutil.copy2)
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        try:
            os.chmod(dst, 0o666)   # 읽기 전용이면 덮어쓰기 전에 풂
        except OSError:
            pass
    shutil.copy2(src, dst)


class _Sig(QtCore.QObject):
    planned = QtCore.Signal(list, str)
    progress = QtCore.Signal(int, int, str)
    finished = QtCore.Signal(int, list)


class SyncDialog(QtWidgets.QDialog):
    OPS = {"a2b": "→", "b2a": "←", "del_a": "✕A", "del_b": "✕B"}

    def __init__(self, a_root, b_root, trash, refresh, parent=None):
        """trash(경로들, 다 끝나면 부를 함수) = 휴지통으로 · refresh() = 두 칸 다시 읽기"""
        super().__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.a, self.b = a_root, b_root
        self.trash, self.refresh = trash, refresh
        self.sig = _Sig()
        self.sig.planned.connect(self._on_plan)
        self.sig.progress.connect(self._on_progress)
        self.sig.finished.connect(self._on_finished)
        self.stop = False
        self.busy = False
        self.setWindowTitle(T("폴더 맞추기"))
        self.resize(900, 600)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(f"A: {a_root}\nB: {b_root}"))
        row = QtWidgets.QHBoxLayout()
        self.dir_box = QtWidgets.QComboBox()
        self.dir_box.addItem(T("A → B  (B 를 A 에 맞춤)"), "a2b")
        self.dir_box.addItem(T("A ← B  (A 를 B 에 맞춤)"), "b2a")
        self.dir_box.addItem(T("양쪽  (더 새것이 반대쪽으로)"), "both")
        row.addWidget(self.dir_box)
        self.mirror = QtWidgets.QCheckBox(T("받는 쪽에만 있는 것 지우기 (휴지통)"))
        self.mirror.setToolTip(T("켜면 받는 쪽이 보내는 쪽과 똑같아집니다 — 받는 쪽에만 있던 파일은 휴지통으로"))
        row.addWidget(self.mirror)
        row.addStretch(1)
        self.b_cmp = QtWidgets.QPushButton(T("다시 비교"))
        row.addWidget(self.b_cmp)
        lay.addLayout(row)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels([T("동작"), T("경로"), T("이유"), T("A 크기·날짜"), T("B 크기·날짜")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        lay.addWidget(self.tree, 1)
        self.info = QtWidgets.QLabel()
        lay.addWidget(self.info)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        bot = QtWidgets.QHBoxLayout()
        bot.addStretch(1)
        self.b_run = QtWidgets.QPushButton(T("실행"))
        self.b_run.setDefault(True)
        self.b_stop = QtWidgets.QPushButton(T("멈춤"))
        self.b_stop.setEnabled(False)
        self.b_close = QtWidgets.QPushButton(T("닫기"))
        for b in (self.b_run, self.b_stop, self.b_close):
            bot.addWidget(b)
        lay.addLayout(bot)
        self.b_cmp.clicked.connect(self.compare)
        self.dir_box.currentIndexChanged.connect(lambda _i: self.compare())
        self.mirror.toggled.connect(lambda _o: self.compare())
        self.b_run.clicked.connect(self.run)
        self.b_stop.clicked.connect(lambda: setattr(self, "stop", True))
        self.b_close.clicked.connect(self.close)
        self.ops = []
        QtCore.QTimer.singleShot(0, self.compare)

    def compare(self):
        if self.busy:
            return
        self.busy = True
        self.tree.clear()
        self.info.setText(T("비교하는 중…"))
        self.b_run.setEnabled(False)
        d, mir = self.dir_box.currentData(), self.mirror.isChecked()

        def work():
            t0 = time.time()
            try:
                ops = plan(self.a, self.b, d, mir, lambda: self.stop)
                err = ""
            except Exception as ex:
                log.exception("비교 실패")
                ops, err = [], str(ex)
            log.info("폴더 맞추기 비교 %s ↔ %s 방향 %s 지우기 %s → %d개 %.1f초", self.a, self.b, d, mir, len(ops), time.time() - t0)
            self.sig.planned.emit(ops, err)
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _desc(p):
        try:
            st = os.stat(p)
        except OSError:
            return ""
        sz = "" if os.path.isdir(p) else f"{st.st_size:,}  "
        return sz + time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))

    def _on_plan(self, ops, err):
        self.busy = False
        self.ops = ops
        why_t = {"only": T("한쪽에만"), "newer": T("더 새것"), "older": T("더 옛것(덮어씀)"), "diff": T("날짜 같고 크기 다름")}
        for op, rel, why in ops:
            it = QtWidgets.QTreeWidgetItem([self.OPS[op], rel, why_t.get(why, why),
                                            self._desc(os.path.join(self.a, rel)), self._desc(os.path.join(self.b, rel))])
            it.setCheckState(0, Qt.Checked)
            it.setData(0, Qt.UserRole, (op, rel))
            if op.startswith("del"):
                it.setForeground(0, QtGui.QColor("#d33"))
            elif why == "older":
                it.setForeground(2, QtGui.QColor("#c60"))
            self.tree.addTopLevelItem(it)
        for c in (0, 2, 3, 4):
            self.tree.resizeColumnToContents(c)
        n = {k: sum(1 for o in ops if o[0] == k) for k in self.OPS}
        self.info.setText(err or T("A → B {0}개 · A ← B {1}개 · 지우기 {2}개 — 체크한 것만 실행합니다").format(n["a2b"], n["b2a"], n["del_a"] + n["del_b"])
                          if ops or err else T("두 폴더가 이미 같습니다"))
        self.b_run.setEnabled(bool(ops))
        if getattr(self, "last_msg", ""):   # 실행 끝 결과를 다시 비교한 결과 앞에
            self.info.setText(self.last_msg + " — " + self.info.text())
            self.last_msg = ""

    def checked(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked:
                out.append(it.data(0, Qt.UserRole))
        return out

    def run(self):
        todo = self.checked()
        if not todo or self.busy:
            return
        dels = [(self.a if op == "del_a" else self.b, rel) for op, rel in todo if op.startswith("del")]
        if dels and QtWidgets.QMessageBox.question(self, T("폴더 맞추기"), T("{0}개를 휴지통으로 보냅니다. 계속할까요?").format(len(dels))) != QtWidgets.QMessageBox.Yes:
            return
        self.busy = True
        self.stop = False
        self.b_run.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.bar.setVisible(True)
        self.bar.setRange(0, len(todo))
        copies = [(op, rel) for op, rel in todo if not op.startswith("del")]

        def work():
            t0 = time.time()
            done, errs = 0, []
            for i, (op, rel) in enumerate(copies):
                if self.stop:
                    break
                src, dst = (self.a, self.b) if op == "a2b" else (self.b, self.a)
                self.sig.progress.emit(i, len(todo), rel)
                try:
                    _copy(os.path.join(src, rel), os.path.join(dst, rel), lambda: self.stop)
                    done += 1
                except Exception as ex:
                    errs.append(f"{rel}: {ex}")
                    log.warning("맞추기 복사 실패 %s: %s", rel, ex)
            log.info("폴더 맞추기 복사 %d/%d 실패 %d %.1f초 멈춤=%s", done, len(copies), len(errs), time.time() - t0, self.stop)
            self.sig.finished.emit(done, errs)
        self._dels = [os.path.join(r, rel) for r, rel in dels]
        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, i, n, rel):
        self.bar.setValue(i)
        self.info.setText(T("복사 중 {0}/{1}: {2}").format(i + 1, n, rel))

    def _on_finished(self, done, errs):
        def end():
            self.busy = False
            self.bar.setVisible(False)
            self.b_stop.setEnabled(False)
            self.refresh()
            msg = T("복사 {0}개 끝").format(done) + (T(" · 지움 {0}개").format(len(self._dels)) if self._dels and not self.stop else "")
            if errs:
                msg += " · " + T("실패 {0}개").format(len(errs))
                QtWidgets.QMessageBox.warning(self, T("폴더 맞추기"), "\n".join(errs[:30]))
            self.last_msg = msg
            self.compare()
        if self._dels and not self.stop:
            self.trash(self._dels, lambda: QtCore.QTimer.singleShot(0, end))
        else:
            end()

    def closeEvent(self, ev):
        self.stop = True
        super().closeEvent(ev)
