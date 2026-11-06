# -*- coding: utf-8 -*-
"""My메뉴 = 예전 사용자 단추 (USERBTNS_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '사용자 단추 묶음')

- 위쪽 도구줄에 내가 정한 단추를 붙임: 누르면 프로그램·배치 파일·폴더·웹 주소를 엶 (고른 파일을 넘겨 줄 수 있음)
- 편집: 도구 ▸ 사용자 단추 편집… (이름·실행할 것·넘길 값·아이콘은 실행 파일 것)
- 넘길 값의 자리 글자: {file} 고른 첫 파일 · {files} 고른 것 전부(따옴표로 묶어 띄어 씀) · {folder} 지금 폴더
  · {other} 다른 칸 폴더 · {name} 고른 첫 파일 이름(폴더 빼고)
- 실행은 윈도우 열기(ShellExecute)로 — 실행 파일이 아니어도(폴더·문서·주소) 됨. 4Dir 는 기다리지 않음
- 저장: 설정 user_buttons [{name, cmd, args}]
로그: bin\\log\\4Dir.log [QE.userbtn]
"""
import os
import re
import logging

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

USERBTNS_VER = "1.2.0"   # 1.2.0 (0.9.113): 이름 My메뉴, 4Dir 기능도 넣기 {name, action} / 1.1.0: 따옴표·끝 \ 처리, 한 번에 바꿈
ACTION_ICON = None   # main 이 넣음: 기능 id → QIcon (없으면 빈 아이콘)
log = logging.getLogger("QE.userbtn")


def _q(v):
    r"""명령줄용 따옴표 — 끝의 \ 는 두 번 (D:\ 를 "D:\" 로 감싸면 \" 가 따옴표로 읽혀 인자가 깨지던 것, 0.9.110 점검)"""
    if not v:
        return '""'
    m = re.search(r"\\+$", v)
    if m:
        v = v + m.group(0)
    return '"' + v + '"'


def expand(args, ctx):
    """ctx = {files: [...], folder, other} — 자리 글자를 한 번에 바꿈 (바꾼 값 안의 '{...}' 를 다시 바꾸지 않음)"""
    files = ctx.get("files") or []
    name = os.path.splitext(os.path.basename(files[0]))[0] if files else ""
    vals = {
        "files": (" ".join(_q(p) for p in files), None),
        "file": (_q(files[0]) if files else "", files[0] if files else ""),
        "name": (name, name),
        "folder": (_q(ctx["folder"]) if ctx.get("folder") else "", ctx.get("folder") or ""),
        "other": (_q(ctx["other"]) if ctx.get("other") else "", ctx.get("other") or ""),
    }

    def sub(m):
        k, quoted = m.group(2), bool(m.group(1))
        bare, raw = vals[k]
        if quoted:   # 사용자가 "{name}" 처럼 따옴표를 쳤으면 그 따옴표 안에 값 그대로 (끝 \ 는 두 번)
            if k == "files":
                return bare
            return _q(raw)
        return bare
    return re.sub(r'("?)\{(files|file|name|folder|other)\}\1', sub, args or "").strip()


def run(item, ctx):
    cmd = os.path.expandvars(item.get("cmd", "").strip().strip('"'))
    args = expand(item.get("args", ""), ctx)
    cwd = ctx.get("folder") if ctx.get("folder") and os.path.isdir(ctx.get("folder")) else None
    log.info("사용자 단추 '%s' 실행: %s %s (폴더 %s)", item.get("name"), cmd, args, cwd)
    if not cmd:
        raise OSError(T("실행할 것이 비어 있습니다"))
    os.startfile(cmd, "open", args, cwd) if args or cwd else os.startfile(cmd)


def icon_for(item):
    if item.get("action"):
        ic = ACTION_ICON(item["action"]) if ACTION_ICON else None
        return ic if ic is not None else QtGui.QIcon()
    cmd = os.path.expandvars(item.get("cmd", "").strip().strip('"'))
    if cmd and os.path.exists(cmd):
        ic = QtWidgets.QFileIconProvider().icon(QtCore.QFileInfo(cmd))
        if not ic.isNull():
            return ic
    return QtGui.QIcon()


class FuncPicker(QtWidgets.QDialog):
    """4Dir 기능 고르기 (0.9.113): 분류별 목록 + 찾기. groups = [(분류 이름, [(id, 이름)…])]"""

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("My메뉴에 넣을 기능"))
        self.resize(460, 560)
        self.chosen = None
        lay = QtWidgets.QVBoxLayout(self)
        self.find = QtWidgets.QLineEdit()
        self.find.setPlaceholderText(T("🔍 기능 이름으로 찾기"))
        self.find.textChanged.connect(self._filter)
        lay.addWidget(self.find)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAlternatingRowColors(True)   # 0.9.113 빌드 4: 기능 검색과 같은 줄 색
        dark = self.palette().base().color().lightness() < 128
        alt, head = ("#232b38", "#2c3e5c") if dark else ("#edf4ff", "#cfe0fa")
        self.tree.setStyleSheet(f"QTreeWidget {{ alternate-background-color: {alt}; }}")
        for cname, rows in groups:
            top = QtWidgets.QTreeWidgetItem([cname])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setFlags(Qt.ItemIsEnabled)
            top.setBackground(0, QtGui.QColor(head))
            self.tree.addTopLevelItem(top)
            for a, lbl in rows:
                it = QtWidgets.QTreeWidgetItem([lbl])
                it.setData(0, Qt.UserRole, a)
                ic = ACTION_ICON(a) if ACTION_ICON else None
                if ic is not None:
                    it.setIcon(0, ic)
                top.addChild(it)
        self.tree.expandAll()
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._ok())
        lay.addWidget(self.tree, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText(T("넣기"))
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText(T("취소"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.find.setFocus()

    def _filter(self, t):
        t = t.strip().lower()
        first = None
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            n = 0
            for j in range(top.childCount()):
                c = top.child(j)
                hide = bool(t) and t not in c.text(0).lower() and t not in top.text(0).lower()
                c.setHidden(hide)
                if not hide:
                    n += 1
                    first = first or c
            top.setHidden(n == 0)
        if t and first is not None:
            self.tree.setCurrentItem(first)

    def _ok(self):
        it = self.tree.currentItem()
        a = it.data(0, Qt.UserRole) if it is not None else None
        if not a:
            return
        self.chosen = (a, it.text(0))
        self.accept()


class EditDialog(QtWidgets.QDialog):
    """My메뉴 목록 편집 (예전 이름 '사용자 단추')"""

    def __init__(self, items, parent=None, groups=None):
        super().__init__(parent)
        self.groups = groups or []   # 0.9.113 4Dir 기능 [(분류 이름, [(id, 이름)…])]
        self.labels = {a: lbl for _c, rows in self.groups for a, lbl in rows}
        self.setWindowTitle(T("My메뉴 편집"))
        self.resize(720, 420)
        self.items = [dict(x) for x in items]
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.lst = QtWidgets.QListWidget()
        left.addWidget(self.lst, 1)
        row = QtWidgets.QHBoxLayout()
        self.b_func = QtWidgets.QPushButton(T("＋ 4Dir 기능"))   # 0.9.113
        self.b_func.clicked.connect(self.add_func)
        self.b_func.setEnabled(bool(self.groups))
        row.addWidget(self.b_func)
        b = QtWidgets.QPushButton(T("＋ 프로그램·폴더·주소"))
        b.clicked.connect(self.add)
        row.addWidget(b)
        lay_btn = QtWidgets.QHBoxLayout()
        for t, fn in (("－", self.remove), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1))):
            b = QtWidgets.QPushButton(t)
            b.setFixedWidth(36)
            b.clicked.connect(fn)
            lay_btn.addWidget(b)
        lay_btn.addStretch(1)
        row.addStretch(1)
        left.addLayout(row)
        left.addLayout(lay_btn)
        lay.addLayout(left, 1)
        right = QtWidgets.QVBoxLayout()
        f = QtWidgets.QFormLayout()
        self.e_name = QtWidgets.QLineEdit()
        self.e_cmd = QtWidgets.QLineEdit()
        self.e_cmd.setPlaceholderText(r"C:\Program Files\...\app.exe  /  D:\작업  /  https://…")
        pick = QtWidgets.QPushButton("…")
        pick.setFixedWidth(30)
        pick.clicked.connect(self.pick)
        cr = QtWidgets.QHBoxLayout()
        cr.addWidget(self.e_cmd)
        cr.addWidget(pick)
        self.e_args = QtWidgets.QLineEdit()
        self.e_args.setPlaceholderText("{files}")
        self.l_func = QtWidgets.QLabel()   # 0.9.113 4Dir 기능 항목이면 그 기능 이름
        self.l_func.setWordWrap(True)
        f.addRow(T("이름"), self.e_name)
        f.addRow(T("4Dir 기능"), self.l_func)
        f.addRow(T("실행할 것"), cr)
        f.addRow(T("넘길 값"), self.e_args)
        self.form, self.cmd_row, self.pick_btn = f, cr, pick
        right.addLayout(f)
        help_ = self.help_ = QtWidgets.QLabel(T("넘길 값에 쓸 수 있는 자리 글자:\n{file} 고른 첫 파일\n{files} 고른 것 전부\n{name} 고른 첫 파일 이름(확장자 빼고)\n{folder} 지금 폴더\n{other} 다른 칸 폴더\n\n예) 포토샵 + {files} = 고른 그림을 포토샵으로 엶"))
        help_.setWordWrap(True)
        right.addWidget(help_)
        right.addStretch(1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText(T("확인"))   # 0.9.113 영어 OK/Cancel 대신
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText(T("취소"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        lay.addLayout(right, 2)
        self.lst.currentRowChanged.connect(self._show)
        for e in (self.e_name, self.e_cmd, self.e_args):
            e.textEdited.connect(self._store)
        self._fill()

    def _fill(self, sel=0):
        self.lst.blockSignals(True)
        self.lst.clear()
        for it in self.items:
            li = QtWidgets.QListWidgetItem(icon_for(it), it.get("name") or T("(이름 없음)"))
            self.lst.addItem(li)
        self.lst.blockSignals(False)
        if self.items:
            self.lst.setCurrentRow(max(0, min(sel, len(self.items) - 1)))
        self._show(self.lst.currentRow())

    def _show(self, r):
        on = 0 <= r < len(self.items)
        it = self.items[r] if on else {}
        fn = bool(it.get("action"))
        self.e_name.setEnabled(on)
        for e in (self.e_cmd, self.e_args, self.pick_btn):
            e.setEnabled(on and not fn)
        for w in (self.e_cmd, self.pick_btn, self.e_args, self.help_):
            w.setVisible(not fn)
        for w in (self.e_cmd, self.e_args):
            lb = self.form.labelForField(w if w is self.e_args else self.cmd_row)
            if lb is not None:
                lb.setVisible(not fn)
        self.l_func.setVisible(fn)
        lb = self.form.labelForField(self.l_func)
        if lb is not None:
            lb.setVisible(fn)
        self.l_func.setText(self.labels.get(it.get("action"), it.get("action", "")) if fn else "")
        self.e_name.setText(it.get("name", ""))
        self.e_cmd.setText(it.get("cmd", ""))
        self.e_args.setText(it.get("args", ""))

    def _store(self, *_):
        r = self.lst.currentRow()
        if 0 <= r < len(self.items):
            if self.items[r].get("action"):
                self.items[r] = {"name": self.e_name.text().strip(), "action": self.items[r]["action"]}
            else:
                self.items[r] = {"name": self.e_name.text().strip(), "cmd": self.e_cmd.text().strip(), "args": self.e_args.text()}
            self.lst.item(r).setText(self.items[r]["name"] or T("(이름 없음)"))

    def add_func(self):
        """0.9.113 4Dir 기능 넣기 (기능 검색·단축키 표와 같은 기능 목록)"""
        dlg = FuncPicker(self.groups, self)
        dlg.setStyleSheet(self.styleSheet())
        if dlg.exec() and dlg.chosen:
            a, lbl = dlg.chosen
            name = lbl.rstrip("…").strip()
            self.items.append({"name": name, "action": a})
            log.info("My메뉴에 4Dir 기능 넣음 %s (%s)", a, name)
            self._fill(len(self.items) - 1)

    def add(self):
        self.items.append({"name": T("새 항목"), "cmd": "", "args": "{files}"})
        self._fill(len(self.items) - 1)
        self.e_name.setFocus()
        self.e_name.selectAll()

    def remove(self):
        r = self.lst.currentRow()
        if 0 <= r < len(self.items):
            self.items.pop(r)
            self._fill(r)

    def move(self, d):
        r = self.lst.currentRow()
        if 0 <= r < len(self.items) and 0 <= r + d < len(self.items):
            self.items[r], self.items[r + d] = self.items[r + d], self.items[r]
            self._fill(r + d)

    def pick(self):
        p, _f = QtWidgets.QFileDialog.getOpenFileName(self, T("실행할 것"), "", T("프로그램 (*.exe *.bat *.cmd *.lnk);;모든 파일 (*)"))
        if p:
            self.e_cmd.setText(os.path.normpath(p))
            if not self.e_name.text().strip() or self.e_name.text() in (T("새 단추"), T("새 항목")):
                self.e_name.setText(os.path.splitext(os.path.basename(p))[0])
            self._store()
            r = self.lst.currentRow()
            if 0 <= r < len(self.items):
                self.lst.item(r).setIcon(icon_for(self.items[r]))

    def result_items(self):
        return [x for x in self.items if x.get("cmd") or x.get("action")]
