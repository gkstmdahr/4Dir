# -*- coding: utf-8 -*-
"""사용자 단추 (USERBTNS_VER 1.0.0, 0.9.109 빌드 3 — 사용자 11/6 '추가 기능 전부', 경쟁 앱 조사 '사용자 단추 묶음')

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

USERBTNS_VER = "1.1.0"   # 1.1.0: 따옴표·끝 \ 처리, 한 번에 바꿈
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
    cmd = os.path.expandvars(item.get("cmd", "").strip().strip('"'))
    if cmd and os.path.exists(cmd):
        ic = QtWidgets.QFileIconProvider().icon(QtCore.QFileInfo(cmd))
        if not ic.isNull():
            return ic
    return QtGui.QIcon()


class EditDialog(QtWidgets.QDialog):
    """사용자 단추 목록 편집"""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("사용자 단추 편집"))
        self.resize(720, 420)
        self.items = [dict(x) for x in items]
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.lst = QtWidgets.QListWidget()
        left.addWidget(self.lst, 1)
        row = QtWidgets.QHBoxLayout()
        for t, fn in (("＋", self.add), ("－", self.remove), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1))):
            b = QtWidgets.QPushButton(t)
            b.setFixedWidth(36)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        left.addLayout(row)
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
        f.addRow(T("이름"), self.e_name)
        f.addRow(T("실행할 것"), cr)
        f.addRow(T("넘길 값"), self.e_args)
        right.addLayout(f)
        help_ = QtWidgets.QLabel(T("넘길 값에 쓸 수 있는 자리 글자:\n{file} 고른 첫 파일\n{files} 고른 것 전부\n{name} 고른 첫 파일 이름(확장자 빼고)\n{folder} 지금 폴더\n{other} 다른 칸 폴더\n\n예) 포토샵 + {files} = 고른 그림을 포토샵으로 엶"))
        help_.setWordWrap(True)
        right.addWidget(help_)
        right.addStretch(1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
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
        for e in (self.e_name, self.e_cmd, self.e_args):
            e.setEnabled(on)
        it = self.items[r] if on else {}
        self.e_name.setText(it.get("name", ""))
        self.e_cmd.setText(it.get("cmd", ""))
        self.e_args.setText(it.get("args", ""))

    def _store(self, *_):
        r = self.lst.currentRow()
        if 0 <= r < len(self.items):
            self.items[r] = {"name": self.e_name.text().strip(), "cmd": self.e_cmd.text().strip(), "args": self.e_args.text()}
            self.lst.item(r).setText(self.items[r]["name"] or T("(이름 없음)"))

    def add(self):
        self.items.append({"name": T("새 단추"), "cmd": "", "args": "{files}"})
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
            if not self.e_name.text().strip() or self.e_name.text() == T("새 단추"):
                self.e_name.setText(os.path.splitext(os.path.basename(p))[0])
            self._store()
            r = self.lst.currentRow()
            if 0 <= r < len(self.items):
                self.lst.item(r).setIcon(icon_for(self.items[r]))

    def result_items(self):
        return [x for x in self.items if x.get("cmd")]
