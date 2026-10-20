# -*- coding: utf-8 -*-
"""윈도우 겹침 아이콘 순서 정리 (10/6 사용자 요청)

윈도우는 겹침 아이콘 처리기를 레지스트리 키 이름 순서(앞의 공백이 많을수록 앞)로 읽고, 앞의 11개만 씀(+ 윈도우 자체 4칸 = 15).
뒤로 밀린 것(예: TortoiseSVN 추가됨·버전관리 안 됨, TortoiseGit 일부)은 탐색기·4Dir 에 안 나옴.

- 4Dir 는 레지스트리를 직접 바꾸지 않음(관리자 권한 필요 — 4Dir 는 관리자 권한 안 씀).
  → 바꿀 순서대로 '적용 .reg' 와 지금 상태로 돌아가는 '되돌리기 .reg' 를 만들어 줌.
  사용자가 적용 .reg 를 더블클릭 → 윈도우가 관리자 확인 → 로그아웃/다시 로그인(또는 탐색기 다시 시작)하면 반영.
- 키 이름 앞 공백 수로 순서를 정함: 맨 위 = 공백 가장 많이. 값(처리기 CLSID)은 그대로.
- 드롭박스·구글드라이브 등은 업데이트 때 자기 키를 다시 앞으로 올리기도 함 → 그때 다시 정리.
"""
import os
import time
import winreg
import logging

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from i18n import T

log = logging.getLogger("QE.ovlorder")
VERSION = "1.0.0"
KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\ShellIconOverlayIdentifiers"
FULL = r"HKEY_LOCAL_MACHINE" + "\\" + KEY
USED = 11   # 윈도우가 쓰는 앞쪽 개수 (실측 10/6: 앞 11개만 번호가 붙고 12번째부터 0)


def read_entries():
    """[(키 이름, {값 이름: (값, 형식)}, 하위키 있음)] — 윈도우가 읽는 순서(이름 정렬)"""
    out = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY) as k:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            vals, has_sub = {}, False
            with winreg.OpenKey(k, name) as sk:
                j = 0
                while True:
                    try:
                        vn, vd, vt = winreg.EnumValue(sk, j)
                    except OSError:
                        break
                    vals[vn] = (vd, vt)
                    j += 1
                try:
                    winreg.EnumKey(sk, 0)
                    has_sub = True
                except OSError:
                    pass
            out.append((name, vals, has_sub))
    out.sort(key=lambda x: x[0].lower())
    return out


def clsid_dll(clsid):
    """처리기 CLSID → DLL 경로 (어느 프로그램인지 보여주기용)"""
    for root in (r"CLSID", r"WOW6432Node\CLSID"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, root + "\\" + clsid + r"\InprocServer32") as k:
                return winreg.QueryValue(k, None)
        except OSError:
            continue
    return ""


def _reg_val(name, data, typ):
    n = "@" if name == "" else '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if typ == winreg.REG_SZ:
        return n + '="' + str(data).replace("\\", "\\\\").replace('"', '\\"') + '"'
    if typ == winreg.REG_DWORD:
        return n + "=dword:%08x" % data
    raw = data.encode("utf-16-le") + b"\0\0" if isinstance(data, str) else bytes(data or b"")
    return n + "=hex(%x):" % typ + ",".join("%02x" % b for b in raw)


def build_reg(entries_in_order, current):
    """(적용 .reg 글자, 되돌리기 .reg 글자, [(옛 이름, 새 이름)])"""
    n = len(entries_in_order)
    renames = []
    for i, (name, vals, _sub) in enumerate(entries_in_order):
        new = " " * (n - i) + name.strip()
        renames.append((name, new, vals))
    head = "Windows Registry Editor Version 5.00\r\n\r\n"
    apply_lines, back_lines = [head], [head]
    for old, new, vals in renames:
        if old == new:
            continue
        apply_lines.append("[-%s\\%s]\r\n" % (FULL, old))
        apply_lines.append("[%s\\%s]\r\n" % (FULL, new))
        apply_lines += [_reg_val(vn, vd, vt) + "\r\n" for vn, (vd, vt) in vals.items()]
        apply_lines.append("\r\n")
        back_lines.append("[-%s\\%s]\r\n" % (FULL, new))
        back_lines.append("[%s\\%s]\r\n" % (FULL, old))
        back_lines += [_reg_val(vn, vd, vt) + "\r\n" for vn, (vd, vt) in vals.items()]
        back_lines.append("\r\n")
    return "".join(apply_lines), "".join(back_lines), [(o, nw) for o, nw, _ in renames]


class OverlayOrder(QtWidgets.QWidget):
    def __init__(self, out_dir, on_saved=None):
        super().__init__(None, Qt.Window)
        self.out_dir = out_dir
        self.on_saved = on_saved
        self.setWindowTitle(T("겹침 아이콘 순서 정리 (윈도우)"))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(860, 560)
        lay = QtWidgets.QVBoxLayout(self)
        tip = QtWidgets.QLabel(T("윈도우는 겹침 아이콘(Git·SVN·Perforce·구글드라이브 등 상태 표시)을 위에서부터 {0}개만 씁니다. "
                                 "필요한 것을 위로 올리고 [적용 파일 만들기]를 누르세요. 4Dir 는 레지스트리를 직접 바꾸지 않습니다.").format(USED))
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QtWidgets.QHBoxLayout()
        self.tbl = QtWidgets.QTreeWidget()
        self.tbl.setRootIsDecorated(False)
        self.tbl.setColumnCount(4)
        self.tbl.setHeaderLabels([T("순서"), T("이름"), T("상태"), T("프로그램(DLL)")])
        self.tbl.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tbl.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.tbl.header().resizeSection(0, 50)
        self.tbl.header().resizeSection(1, 300)
        self.tbl.header().resizeSection(2, 90)
        self.tbl.model().rowsMoved.connect(lambda *_: QtCore.QTimer.singleShot(0, self._renumber))
        row.addWidget(self.tbl, 1)
        side = QtWidgets.QVBoxLayout()
        for text, fn in ((T("맨 위로"), lambda: self.move_sel(-999)), (T("▲ 위로"), lambda: self.move_sel(-1)),
                         (T("▼ 아래로"), lambda: self.move_sel(1)), (T("맨 아래로"), lambda: self.move_sel(999))):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addSpacing(10)
        b = QtWidgets.QPushButton(T("처음 순서로"))
        b.clicked.connect(self.load)
        side.addWidget(b)
        side.addStretch(1)
        row.addLayout(side)
        lay.addLayout(row, 1)
        bot = QtWidgets.QHBoxLayout()
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        bot.addWidget(self.info, 1)
        save = QtWidgets.QPushButton(T("적용 파일 만들기 (.reg)"))
        save.setDefault(True)
        save.clicked.connect(self.save)
        close = QtWidgets.QPushButton(T("닫기"))
        close.clicked.connect(self.close)
        bot.addWidget(save)
        bot.addWidget(close)
        lay.addLayout(bot)
        self.load()
        log.info("겹침 아이콘 순서 창 v%s: %d개", VERSION, self.tbl.topLevelItemCount())

    def load(self):
        self.tbl.clear()
        try:
            self.current = read_entries()
        except OSError as e:
            log.exception("겹침 아이콘 목록 읽기 실패")
            self.info.setText(T("목록을 읽지 못했습니다: {0}").format(e))
            self.current = []
        for name, vals, sub in self.current:
            clsid = str(vals.get("", ("", 0))[0])
            it = QtWidgets.QTreeWidgetItem(["", name.strip(), "", clsid_dll(clsid) or clsid])
            it.setData(0, Qt.UserRole, name)
            it.setToolTip(1, repr(name) + "  " + clsid)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            if sub:
                it.setToolTip(2, T("하위 키가 있어 옮길 수 없음"))
            self.tbl.addTopLevelItem(it)
        self._renumber()

    def _renumber(self):
        gray = QtGui.QBrush(QtGui.QColor("#9aa0a6"))
        for i in range(self.tbl.topLevelItemCount()):
            it = self.tbl.topLevelItem(i)
            it.setText(0, str(i + 1))
            used = i < USED
            it.setText(2, T("사용됨") if used else T("안 쓰임"))
            for c in range(4):
                it.setForeground(c, QtGui.QBrush() if used else gray)
        changed = self.order_names() != [n for n, _v, _s in self.current]
        self.info.setText((T("순서가 바뀌었습니다 — [적용 파일 만들기]") if changed else T("지금 윈도우 순서")) +
                          "  ·  " + T("위에서 {0}개 = 사용됨, 나머지는 탐색기·4Dir 에 안 나옴").format(USED))

    def order_names(self):
        return [self.tbl.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.tbl.topLevelItemCount())]

    def move_sel(self, step):   # (move 는 QWidget 창 옮기기라 이름 다르게)
        """step: -1/+1 = 한 칸, -999/999 = 맨 위/맨 아래. 여러 개 선택해도 순서 유지"""
        self._sel_names = [it.data(0, Qt.UserRole) for it in self.tbl.selectedItems()]
        rows = sorted(self.tbl.indexOfTopLevelItem(it) for it in self.tbl.selectedItems())
        if not rows:
            return
        n = self.tbl.topLevelItemCount()
        if abs(step) > 1:
            items = [self.tbl.takeTopLevelItem(r) for r in reversed(rows)][::-1]
            at = 0 if step < 0 else self.tbl.topLevelItemCount()
            for k, it in enumerate(items):
                self.tbl.insertTopLevelItem(at + k, it)
        else:
            order = rows if step < 0 else list(reversed(rows))
            for r in order:
                t = r + step
                if 0 <= t < n and self.tbl.topLevelItem(t) not in self.tbl.selectedItems():
                    it = self.tbl.takeTopLevelItem(r)
                    self.tbl.insertTopLevelItem(t, it)
            items = None
        sel = [self.tbl.topLevelItem(i) for i in range(self.tbl.topLevelItemCount())]
        self.tbl.clearSelection()
        names = set(self._sel_names)
        for it in sel:
            if it.data(0, Qt.UserRole) in names:
                it.setSelected(True)
        self._renumber()

    def save(self):
        by_name = {n: (n, v, s) for n, v, s in self.current}
        order = [by_name[n] for n in self.order_names()]
        if any(s for _n, _v, s in order):
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), T("하위 키가 있는 항목이 있어 만들 수 없습니다."))
            return
        apply_txt, back_txt, renames = build_reg(order, self.current)
        os.makedirs(self.out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        ap = os.path.join(self.out_dir, T("겹침아이콘_순서적용_{0}.reg").format(stamp))
        bp = os.path.join(self.out_dir, T("겹침아이콘_되돌리기_{0}.reg").format(stamp))
        for p, txt in ((ap, apply_txt), (bp, back_txt)):
            with open(p, "w", encoding="utf-16") as f:   # .reg 5.00 = UTF-16 LE + BOM
                f.write(txt)
        log.info("겹침 아이콘 .reg 만듦 %s (바뀐 키 %d개) / 되돌리기 %s", ap, sum(1 for o, n in renames if o != n), bp)
        QtWidgets.QMessageBox.information(
            self, self.windowTitle(),
            T("두 파일을 만들었습니다.\n\n  적용: {0}\n  되돌리기: {1}\n\n"
              "적용 파일을 더블클릭 → 윈도우가 묻는 창에서 [예] (관리자 확인)\n"
              "→ 로그아웃했다가 다시 로그인하면(또는 PC 다시 시작) 반영됩니다.\n"
              "문제가 있으면 되돌리기 파일을 같은 방법으로 실행하세요.").format(os.path.basename(ap), os.path.basename(bp)))
        if self.on_saved:
            self.on_saved(ap)
