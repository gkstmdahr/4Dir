# -*- coding: utf-8 -*-
"""이름 일괄 변경 (BatchNamer 방식) — 4Dir 안의 창

- 버튼마다 '바뀔이름'만 바꿈(누적). 디스크는 [실제로 적용] 을 눌러야 바뀜.
- 버튼은 선택과 상관없이 전체 줄에 적용 (BatchNamer 와 같게). 선택은 위/아래 이동·직접 수정·Delete(목록에서 빼기)에만.
- 같은 이름 겹침·못 쓰는 글자·이미 있는 파일은 빨간 줄 → 적용 막음.
- 적용은 2단계(임시 이름 → 새 이름)라 a↔b 처럼 서로 바꾸기도 안전. 실패하면 되돌림.
- 적용한 것은 4Dir 의 Ctrl+Z(되돌리기) 한 번으로 전부 되돌림.
"""
import os
import re
import time
import shutil
import logging

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from i18n import T
import shellops

log = logging.getLogger("QE.rename")
BAD = re.compile(r'[\\/:*?"<>|]')
VERSION = "1.0.7"


def split_ext(name, is_dir, orig=None):
    """(이름, 확장자). orig = 원래 파일 이름 — '전체 지우기'로 '.max' 만 남은 경우를 확장자로 알아봄"""
    if is_dir:
        return name, ""
    if orig is not None:  # 원래 확장자만 남은 것('전체 지우기' 뒤) → 이름 없음 + 확장자
        o_stem, o_ext = os.path.splitext(orig)
        if o_stem and o_ext and name.lower() == o_ext.lower():
            return "", name
    stem, ext = os.path.splitext(name)
    if not stem:          # .gitignore 같은 이름
        return name, ""
    return stem, ext


class Item:
    __slots__ = ("src", "is_dir", "new_name", "new_dir", "size", "mtime", "ctime")

    def __init__(self, path):
        self.src = os.path.normpath(path)
        self.is_dir = os.path.isdir(path)
        self.new_name = os.path.basename(self.src)
        self.new_dir = os.path.dirname(self.src)
        try:
            st = os.stat(path)
            self.size, self.mtime, self.ctime = (-1 if self.is_dir else st.st_size), st.st_mtime, st.st_ctime
        except OSError:
            self.size, self.mtime, self.ctime = -1, 0, 0

    @property
    def name(self):
        return os.path.basename(self.src)

    @property
    def folder(self):
        return os.path.dirname(self.src)

    @property
    def target(self):
        return os.path.join(self.new_dir, self.new_name)

    def changed(self):
        return os.path.normcase(self.target) != os.path.normcase(self.src) or self.target != self.src


# ---------------------------------------------------------------- 값 묻는 작은 창
def ask(parent, title, fields, store):
    """fields = [(키, 표시, 종류, 기본값, 고를것)] 종류: text|int|bool|choice. 마지막 값 기억(store). 취소면 None"""
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setWindowModality(Qt.WindowModal)   # 이 도구 창만 막음 — 4Dir 본창에서 이름 고르기·복사 가능 (10/5 사용자 요청)
    dlg.setMinimumWidth(720)   # 긴 이름·정규식도 한눈에 (예전 약 240 → 3배, 10/5 사용자 요청)
    form = QtWidgets.QFormLayout(dlg)
    form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
    w = {}
    mem = store.setdefault(title, {})
    for key, label, kind, default, opts in fields:
        v = mem.get(key, default)
        if kind == "int":
            e = QtWidgets.QSpinBox()
            e.setRange(-99999, 99999)
            e.setValue(int(v))
        elif kind == "bool":
            e = QtWidgets.QCheckBox()
            e.setChecked(bool(v))
        elif kind == "choice":
            e = QtWidgets.QComboBox()
            e.addItems(opts)
            e.setCurrentIndex(min(int(v), len(opts) - 1))
        else:
            e = QtWidgets.QLineEdit(str(v))
        w[key] = (kind, e)
        form.addRow(label, e)
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    form.addRow(bb)
    first = next(iter(w.values()))[1] if w else None
    if isinstance(first, QtWidgets.QLineEdit):
        first.selectAll()
    if not dlg.exec():
        return None
    out = {}
    for key, (kind, e) in w.items():
        out[key] = e.value() if kind == "int" else e.isChecked() if kind == "bool" else \
            e.currentIndex() if kind == "choice" else e.text()
    mem.update(out)
    return out


# ---------------------------------------------------------------- 표 (고른 줄을 4Dir 목록처럼 진하게)
class SelTable(QtWidgets.QTableWidget):
    """고른 줄: 선택 색 칠 + 줄 전체 파란 테두리 (윈도우 탐색기·4Dir 목록과 같게, 10/5 사용자 요청)"""
    border = QtGui.QColor("#3f94dc")

    def paintEvent(self, ev):
        super().paintEvent(ev)
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        if not rows:
            return
        p = QtGui.QPainter(self.viewport())
        p.setPen(QtGui.QPen(self.border, 1))
        p.setBrush(Qt.NoBrush)
        w = min(self.viewport().width(), self.horizontalHeader().length() - self.horizontalHeader().offset()) - 1
        for r in rows:
            y, h = self.rowViewportPosition(r), self.rowHeight(r)
            if y + h >= 0 and y <= self.viewport().height():
                p.drawRect(0, y, w, h - 1)
        p.end()


# ---------------------------------------------------------------- 창
class BatchRename(QtWidgets.QWidget):
    COLS = [T("현재이름"), T("바뀔이름"), T("현재폴더"), T("바뀔폴더"), T("파일크기"), T("변경시각"), T("생성시각"), T("전체경로")]

    def __init__(self, paths, settings, on_done=None, parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(T("이름 일괄 변경") + f"  (v{VERSION})")
        self.resize(1300, 520)
        self.settings = settings          # 4Dir 설정 (마지막 입력값 기억)
        self.store = dict(settings.data.get("batch_rename") or {})
        self.on_done = on_done            # on_done(pairs) — 적용 후 4Dir 쪽(되돌리기 기록·새로 읽기)
        self.items = []
        self.setAcceptDrops(True)

        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        right = QtWidgets.QVBoxLayout()
        self.table = SelTable(0, len(self.COLS))
        t = settings[settings.theme_key()]
        sel = QtGui.QColor(t.get("sel", "#cce8ffff")[:7])
        SelTable.border = QtGui.QColor(t.get("sel_border", "#3f94dcff")[:7])
        self.table.setStyleSheet("QTableWidget::item:selected { background:%s; color:%s; }"
                                 % (sel.name(), "#ffffff" if settings["dark"] else "#000000"))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)                 # 줄바꿈하면 경로가 'C:...' 로만 보임(실측)
        self.table.setTextElideMode(Qt.ElideMiddle)   # 긴 경로: 드라이브와 마지막 폴더가 보이게 가운데를 줄임
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.horizontalHeader().setStretchLastSection(True)
        for c, wd in enumerate((260, 260, 200, 200, 80, 140, 140)):
            self.table.setColumnWidth(c, wd)
        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._sel_status)
        center = QtWidgets.QVBoxLayout()
        center.addWidget(self.table, 1)
        self.status = QtWidgets.QLabel()
        center.addWidget(self.status)

        def btn(box, text, fn, tip=""):
            b = QtWidgets.QPushButton(text)
            b.setMinimumWidth(96)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            box.addWidget(b)
            return b

        self.btn_apply = btn(left, T("실제로 적용"), self.apply, T("바뀔이름대로 디스크의 이름을 바꿈 (4Dir 에서 Ctrl+Z 로 되돌림)"))
        self.btn_apply.setStyleSheet("font-weight:bold;")
        btn(left, T("문자열 교체"), self.op_replace)
        btn(left, T("앞에 추가"), lambda: self.op_add(front=True))
        btn(left, T("뒤에 추가"), lambda: self.op_add(front=False))
        btn(left, T("전체 지우기"), self.op_clear, T("이름을 비움 (확장자는 남김) — 이어서 번호 붙이기 등에"))
        btn(left, T("선택 지우기"), self.op_cut, T("앞이나 뒤에서 몇 번째 글자부터 몇 글자 지우기"))
        btn(left, T("숫자 남기기"), lambda: self.op_digits(keep=True))
        btn(left, T("숫자 지우기"), lambda: self.op_digits(keep=False))
        btn(left, T("자릿수 맞춤"), self.op_pad, T("이름 속 숫자를 같은 자릿수로 (1 → 001)"))
        btn(left, T("번호 붙이기"), self.op_number)
        btn(left, T("대소문자"), self.op_case)
        left.addStretch(1)
        btn(right, T("이름 되돌림"), self.op_reset, T("바뀔이름을 현재이름으로"))
        btn(right, T("목록 비우기"), self.op_empty)
        btn(right, T("목록 정렬"), self.op_sort)
        btn(right, T("직접 수정"), self.op_edit, T("바뀔이름 칸 직접 고치기 (F2 또는 두 번 클릭)"))
        btn(right, T("위로 이동"), lambda: self.op_move(-1))
        btn(right, T("아래로 이동"), lambda: self.op_move(1))
        btn(right, T("폴더 변경"), self.op_folder, T("다른 폴더로 옮기며 이름 바꾸기"))
        btn(right, T("확장자 삭제"), lambda: self.op_ext("del"))
        btn(right, T("확장자 추가"), lambda: self.op_ext("add"))
        btn(right, T("확장자 변경"), lambda: self.op_ext("set"))
        right.addStretch(1)
        lay.addLayout(left)
        lay.addLayout(center, 1)
        lay.addLayout(right)
        self.table.doubleClicked.connect(lambda i: self.op_edit())
        QtGui.QShortcut(QtGui.QKeySequence("F2"), self.table, self.op_edit)
        QtGui.QShortcut(QtGui.QKeySequence("Delete"), self.table, self.op_remove_rows)
        self.add_paths(paths)
        log.info("이름 일괄 변경 열기 %d개", len(self.items))

    # ------------------------------------------------------------ 목록
    def add_paths(self, paths):
        have = {os.path.normcase(i.src) for i in self.items}
        for p in paths:
            if p and os.path.exists(p) and os.path.normcase(os.path.normpath(p)) not in have:
                self.items.append(Item(p))
                have.add(os.path.normcase(os.path.normpath(p)))
        self.refresh()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        self.add_paths([u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()])

    def targets(self):
        """적용 대상 줄: 언제나 전체 (BatchNamer 와 같게 — 선택은 위/아래 이동·직접 수정·목록에서 빼기에만, 10/5 사용자 요청)"""
        return list(range(len(self.items)))

    def problems(self):
        """줄 번호 → 문제 설명"""
        out = {}
        moving = {os.path.normcase(i.src) for i in self.items if i.changed()}
        seen = {}
        for r, it in enumerate(self.items):
            nm = it.new_name
            if not nm.strip():
                out[r] = T("이름이 비어 있음")
            elif BAD.search(nm):
                out[r] = T('못 쓰는 글자: \\ / : * ? " < > |')
            elif nm != nm.rstrip(" ."):
                out[r] = T("이름 끝에 점·공백은 못 씀")
            if not it.changed():
                continue
            k = os.path.normcase(it.target)
            if k in seen:
                out[r] = out.get(r) or T("다른 줄과 같은 이름")
                out[seen[k]] = out.get(seen[k]) or T("다른 줄과 같은 이름")
            seen[k] = r
            if os.path.exists(it.target) and k not in moving and k != os.path.normcase(it.src):
                out[r] = out.get(r) or T("이미 있는 파일")
        # 바뀌지 않는 줄과 겹치는 경우
        for r, it in enumerate(self.items):
            if not it.changed() and os.path.normcase(it.src) in seen and seen[os.path.normcase(it.src)] != r:
                out[seen[os.path.normcase(it.src)]] = out.get(seen[os.path.normcase(it.src)]) or T("다른 줄과 같은 이름")
        return out

    def refresh(self):
        probs = self.problems()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        red = QtGui.QColor(255, 210, 210)
        for r, it in enumerate(self.items):
            vals = [it.name, it.new_name, it.folder, it.new_dir,
                    "" if it.size < 0 else f"{it.size:,}",
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(it.mtime)) if it.mtime else "",
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(it.ctime)) if it.ctime else "",
                    it.src]
            for c, v in enumerate(vals):
                cell = QtWidgets.QTableWidgetItem(v)
                if c != 1:
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                else:
                    cell.setFlags(cell.flags() | Qt.ItemIsEditable)
                if c == 0:
                    cell.setIcon(shellops.icon_for(it.name, it.is_dir))
                if c == 4:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if r in probs:
                    cell.setBackground(red)
                    cell.setToolTip(probs[r])
                elif c in (1, 3) and it.changed():
                    f = cell.font()
                    f.setBold(True)
                    cell.setFont(f)
                    cell.setForeground(QtGui.QColor("#0a62c9"))
                self.table.setItem(r, c, cell)
        self.table.blockSignals(False)
        n = sum(1 for i in self.items if i.changed())
        txt = T('{0}개 · 바뀔 것 {1}개').format(len(self.items), n)
        if probs:
            txt += "  ·  " + T('⚠ 문제 {0}개 (빨간 줄에 마우스를 올리면 이유)').format(len(probs))
        self.status.setText(txt)
        self.btn_apply.setEnabled(n > 0 and not probs)

    def _sel_status(self):
        pass

    def _edited(self, cell):
        if cell.column() == 1 and cell.row() < len(self.items):
            self.items[cell.row()].new_name = cell.text()
            QtCore.QTimer.singleShot(0, self.refresh)

    def _each(self, fn):
        """대상 줄마다 fn(item, stem, ext, 순번) → (stem, ext)"""
        for k, r in enumerate(self.targets()):
            it = self.items[r]
            stem, ext = split_ext(it.new_name, it.is_dir, it.name)
            stem, ext = fn(it, stem, ext, k)
            it.new_name = stem + ext
        self.refresh()

    # ------------------------------------------------------------ 버튼 (바뀔이름만 바꿈)
    def op_replace(self):
        while True:   # 찾을 글자가 하나도 없으면 알리고 같은 창을 다시 엶 (오타 고치기, 10/12 사용자 요청)
            a = ask(self, T("문자열 교체"), [("find", T("찾을 글자"), "text", "", None), ("rep", T("바꿀 글자"), "text", "", None),
                                        ("case", T("대소문자 구분"), "bool", False, None), ("regex", T("정규식"), "bool", False, None),
                                        ("ext", T("확장자도 포함"), "bool", False, None)], self.store)
            if not a or not a["find"]:
                return
            flags = 0 if a["case"] else re.IGNORECASE
            try:
                pat = re.compile(a["find"] if a["regex"] else re.escape(a["find"]), flags)
            except re.error as ex:
                QtWidgets.QMessageBox.warning(self, T("문자열 교체"), T('정규식 오류: {0}').format(ex))
                continue
            hits = 0
            for r in self.targets():
                it = self.items[r]
                stem, ext = split_ext(it.new_name, it.is_dir, it.name)
                hits += bool(pat.search(stem + ext if a["ext"] else stem))
            log.info("문자열 교체 찾기 %r → %d/%d 줄", a["find"], hits, len(self.targets()))
            if hits:
                break
            QtWidgets.QMessageBox.warning(self, T("문자열 교체"),
                                          T("'{0}' 을(를) 찾지 못했습니다.\n바뀐 것이 없습니다. 찾을 글자를 확인해 주세요.").format(a["find"]))
        rep = a["rep"] if a["regex"] else a["rep"].replace("\\", "\\\\")

        def f(it, stem, ext, k):
            if a["ext"]:
                s = pat.sub(rep, stem + ext)
                return split_ext(s, it.is_dir, it.name) if not it.is_dir else (s, "")
            return pat.sub(rep, stem), ext
        self._each(f)

    def op_add(self, front):
        title = T("앞에 추가") if front else T("뒤에 추가")
        a = ask(self, title, [("text", T("붙일 글자"), "text", "", None)], self.store)
        if a and a["text"]:
            self._each(lambda it, s, e, k: ((a["text"] + s) if front else (s + a["text"]), e))

    def op_clear(self):
        self._each(lambda it, s, e, k: ("", e))

    def op_cut(self):
        a = ask(self, T("선택 지우기"), [("from", T("기준"), "choice", 0, [T("앞에서"), T("뒤에서")]),
                                    ("pos", T("몇 번째 글자부터 (1 = 첫 글자)"), "int", 1, None),
                                    ("n", T("몇 글자"), "int", 1, None)], self.store)
        if not a:
            return
        p, n = max(1, a["pos"]), max(0, a["n"])

        def f(it, s, e, k):
            if a["from"] == 0:
                return s[:p - 1] + s[p - 1 + n:], e
            end = len(s) - (p - 1)
            return s[:max(0, end - n)] + s[end:], e
        self._each(f)

    def op_digits(self, keep):
        self._each(lambda it, s, e, k: ("".join(ch for ch in s if ch.isdigit()) if keep else re.sub(r"\d", "", s), e))

    def op_pad(self):
        a = ask(self, T("자릿수 맞춤"), [("w", T("자릿수"), "int", 3, None),
                                    ("which", T("맞출 숫자"), "choice", 0, [T("모든 숫자"), T("첫 번째 숫자"), T("마지막 숫자")])], self.store)
        if not a:
            return
        w = max(1, a["w"])

        def f(it, s, e, k):
            ms = list(re.finditer(r"\d+", s))
            if not ms:
                return s, e
            pick = ms if a["which"] == 0 else [ms[0]] if a["which"] == 1 else [ms[-1]]
            for m in reversed(pick):
                s = s[:m.start()] + m.group().zfill(w) + s[m.end():]
            return s, e
        self._each(f)

    def op_number(self):
        a = ask(self, T("번호 붙이기"), [("start", T("시작 번호"), "int", 1, None), ("step", T("증가"), "int", 1, None),
                                    ("w", T("자릿수"), "int", 2, None), ("pos", T("위치"), "choice", 1, [T("앞"), T("뒤")]),
                                    ("sep", T("구분 글자"), "text", "_", None)], self.store)
        if not a:
            return

        def f(it, s, e, k):
            num = str(a["start"] + k * a["step"]).zfill(max(1, a["w"]))
            if not s:
                return num, e
            return (num + a["sep"] + s, e) if a["pos"] == 0 else (s + a["sep"] + num, e)
        self._each(f)

    def op_case(self):
        a = ask(self, T("대소문자"), [("mode", T("바꾸기"), "choice", 0, [T("모두 소문자"), T("모두 대문자"), T("단어 첫 글자만 대문자")]),
                                  ("ext", T("확장자도"), "bool", False, None)], self.store)
        if not a:
            return
        fn = [str.lower, str.upper, lambda x: re.sub(r"[A-Za-z]+", lambda m: m.group()[0].upper() + m.group()[1:].lower(), x)][a["mode"]]
        self._each(lambda it, s, e, k: (fn(s), fn(e) if a["ext"] else e))

    def op_ext(self, mode):
        if mode == "del":
            self._each(lambda it, s, e, k: (s, ""))
            return
        a = ask(self, T("확장자 추가") if mode == "add" else T("확장자 변경"),
                [("ext", T("확장자 (예: txt)"), "text", "", None)], self.store)
        if not a or not a["ext"].strip(". "):
            return
        x = "." + a["ext"].strip().lstrip(".")
        self._each(lambda it, s, e, k: (s, e + x) if mode == "add" else (s, x if not it.is_dir else e))

    def op_reset(self):
        for r in self.targets():
            it = self.items[r]
            it.new_name, it.new_dir = it.name, it.folder
        self.refresh()

    def op_empty(self):
        self.items = []
        self.refresh()

    def op_remove_rows(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()}, reverse=True)
        for r in rows:
            del self.items[r]
        self.refresh()

    def op_sort(self):
        self.items.sort(key=lambda it: (os.path.normcase(it.folder), not it.is_dir, shellops.natural_key(it.name)))
        self.refresh()

    def op_edit(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.editItem(self.table.item(r, 1))

    def op_move(self, d):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if not rows or (d < 0 and rows[0] == 0) or (d > 0 and rows[-1] == len(self.items) - 1):
            return
        for r in (rows if d < 0 else reversed(rows)):
            self.items[r], self.items[r + d] = self.items[r + d], self.items[r]
        self.refresh()
        sm = self.table.selectionModel()
        sm.clearSelection()
        for r in rows:
            sm.select(self.table.model().index(r + d, 0), QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)

    def op_folder(self):
        rows = self.targets()
        if not rows:
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(self, T("옮길 폴더"), self.items[rows[0]].new_dir)
        if d:
            for r in rows:
                self.items[r].new_dir = os.path.normpath(d)
            self.refresh()

    # ------------------------------------------------------------ 적용
    def apply(self):
        probs = self.problems()
        todo = [it for it in self.items if it.changed()]
        if probs or not todo:
            self.refresh()
            return
        pairs = rename_all([(it.src, it.target) for it in todo])
        if pairs is None:
            QtWidgets.QMessageBox.warning(self, T("이름 일괄 변경"), T("바꾸다가 오류가 나서 원래대로 되돌렸습니다. 로그를 확인하세요."))
            self.refresh()
            return
        for it in todo:   # 새 이름이 '현재이름'이 됨
            it.src = os.path.normpath(it.target)
            it.new_dir = it.folder
        self.settings.data["batch_rename"] = self.store
        self.settings.save()
        if self.on_done:
            self.on_done(pairs)
        self.refresh()
        self.status.setText(self.status.text() + "  ·  " + T('✔ {0}개 바꿈 (4Dir 에서 Ctrl+Z 로 되돌리기)').format(len(pairs)))


def _move(a, b):
    if os.path.splitdrive(a)[0].lower() == os.path.splitdrive(b)[0].lower():
        os.rename(a, b)
    else:
        shutil.move(a, b)


def rename_all(moves):
    """[(원래, 새)] 를 안전하게: 1) 모두 임시 이름으로 2) 새 이름으로. 실패하면 한 것 되돌림.
    성공하면 [(새, 원래)] (되돌리기용), 실패하면 None"""
    stamp = f"{os.getpid()}_{int(time.time() * 1000) % 100000}"
    step1, step2 = [], []
    try:
        for k, (src, dst) in enumerate(moves):
            tmp = os.path.join(os.path.dirname(src), f".~4dir_{stamp}_{k}")
            os.rename(src, tmp)
            step1.append((src, tmp))
        for (src, tmp), (_, dst) in zip(step1, moves):
            _move(tmp, dst)
            step2.append((tmp, dst))
        log.info("이름 일괄 변경 %d개 완료 (첫: %s → %s)", len(moves), moves[0][0], moves[0][1])
        return [(dst, src) for src, dst in moves]
    except OSError:
        log.exception("이름 일괄 변경 실패 → 되돌림 (임시 %d, 완료 %d)", len(step1), len(step2))
        for tmp, dst in reversed(step2):
            try:
                _move(dst, tmp)
            except OSError:
                log.exception("되돌림 실패 %s", dst)
        for src, tmp in reversed(step1):
            try:
                os.rename(tmp, src)
            except OSError:
                log.exception("되돌림 실패 %s", tmp)
        return None
