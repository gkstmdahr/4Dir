# -*- coding: utf-8 -*-
"""즐겨찾기 정리 창 — 여러 개 삭제, 순서 바꾸기(끌기·위/아래), 이름 바꾸기, 묶음(폴더처럼 모으기), 없는 폴더 찾기

- 목록 맨 위 = 낱개 즐겨찾기와 묶음. 묶음 안 = 즐겨찾기 (묶음 안에 묶음은 없음).
- [확인] 을 눌러야 적용, [취소]·닫기 = 그대로. 띄워 둔 채 4Dir 를 계속 쓸 수 있음(창 모달 아님).
- 없는 폴더 확인은 뒤에서(끊긴 네트워크 경로가 창을 멈추지 않게).
"""
import os
import logging
import threading

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from i18n import T
import shellops

log = logging.getLogger("QE.favorg")
VERSION = "1.0.0"
PATH_ROLE = Qt.UserRole + 1     # 즐겨찾기 경로 (묶음은 None)
KIND_ROLE = Qt.UserRole + 2     # "fav" / "group"


class _Sig(QtCore.QObject):
    exists = QtCore.Signal(str, bool)


class FavTree(QtWidgets.QTreeWidget):
    """끌어서 순서 바꾸기. 묶음 안에 묶음·즐겨찾기 아래에 무엇을 넣는 것은 막음"""

    def dropEvent(self, ev):
        tgt = self.itemAt(ev.position().toPoint())
        pos = self.dropIndicatorPosition()
        moving = self.selectedItems()
        has_group = any(it.data(0, KIND_ROLE) == "group" for it in moving)
        into_group = tgt is not None and (
            (tgt.data(0, KIND_ROLE) == "group" and pos == QtWidgets.QAbstractItemView.OnItem)
            or (tgt.parent() is not None and pos != QtWidgets.QAbstractItemView.OnItem))
        if tgt is not None and tgt.data(0, KIND_ROLE) == "fav" and pos == QtWidgets.QAbstractItemView.OnItem:
            ev.ignore()   # 즐겨찾기 위에 겹쳐 놓기 = 안 됨
            return
        if has_group and into_group:
            ev.ignore()   # 묶음 안에 묶음 = 안 됨
            return
        super().dropEvent(ev)
        for it in moving:
            self._fix_flags(it)
            if it.data(0, KIND_ROLE) == "group":
                it.setExpanded(True)
        log.info("정리 창: 끌어서 옮김 %d개", len(moving))

    @staticmethod
    def _fix_flags(it):
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsEditable
        if it.data(0, KIND_ROLE) == "group":
            it.setFlags(base | Qt.ItemIsDropEnabled)
        else:
            it.setFlags(base)


class FavOrganizer(QtWidgets.QWidget):
    def __init__(self, fav, settings=None, select_group=None):
        super().__init__(None, Qt.Window)
        self.fav = fav
        self.setWindowTitle(T("즐겨찾기 정리"))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(760, 560)
        self.sig = _Sig()
        self.sig.exists.connect(self._mark_exists)
        self._missing = set()
        lay = QtWidgets.QVBoxLayout(self)
        tip = QtWidgets.QLabel(T("끌어서 순서 바꾸기·묶음에 넣기 · 여러 개 선택(Ctrl·Shift) 후 Delete · F2 이름 바꾸기 · [확인]을 눌러야 적용됩니다"))
        tip.setWordWrap(True)
        lay.addWidget(tip)
        row = QtWidgets.QHBoxLayout()
        self.tree = FavTree()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([T("이름"), T("경로")])
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.tree.setDefaultDropAction(Qt.MoveAction)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed)
        self.tree.header().resizeSection(0, 260)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        row.addWidget(self.tree, 1)
        side = QtWidgets.QVBoxLayout()

        def btn(text, fn, tip=None):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            if tip:
                b.setToolTip(tip)
            side.addWidget(b)
            return b
        self.b_up = btn(T("▲ 위로"), lambda: self.move_sel(-1))
        self.b_down = btn(T("▼ 아래로"), lambda: self.move_sel(1))
        side.addSpacing(8)
        self.b_ren = btn(T("이름 바꾸기 (F2)"), self.rename_sel)
        self.b_del = btn(T("삭제 (Delete)"), self.delete_sel)
        side.addSpacing(8)
        btn(T("새 묶음…"), self.new_group, T("선택한 즐겨찾기를 새 묶음으로 모읍니다 (선택 없으면 빈 묶음)"))
        self.b_out = btn(T("묶음에서 빼기"), self.take_out, T("선택한 즐겨찾기를 묶음 밖(맨 위 목록)으로"))
        self.b_ungroup = btn(T("묶음 풀기"), self.ungroup, T("묶음을 없애고 안의 즐겨찾기는 그 자리에 남김"))
        side.addSpacing(8)
        self.b_missing = btn(T("없는 폴더 선택"), self.select_missing, T("지워졌거나 옮겨진 폴더 (회색)"))
        side.addStretch(1)
        row.addLayout(side)
        lay.addLayout(row, 1)
        bot = QtWidgets.QHBoxLayout()
        self.info = QtWidgets.QLabel()
        bot.addWidget(self.info, 1)
        ok = QtWidgets.QPushButton(T("확인"))
        ok.setDefault(True)
        ok.clicked.connect(self.apply)
        cancel = QtWidgets.QPushButton(T("취소"))
        cancel.clicked.connect(self.close)
        bot.addWidget(ok)
        bot.addWidget(cancel)
        lay.addLayout(bot)
        QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Delete), self.tree, self.delete_sel)
        self.load(select_group)
        log.info("즐겨찾기 정리 창 열기 %d개 (v%s)", len(fav.items), VERSION)

    # ---------------------------------------------------------- 목록
    def _fav_item(self, d):
        it = QtWidgets.QTreeWidgetItem([d["name"], d["path"]])
        it.setIcon(0, shellops.icon_for("", True, 16))
        it.setData(0, PATH_ROLE, d["path"])
        it.setData(0, KIND_ROLE, "fav")
        it.setToolTip(1, d["path"])
        FavTree._fix_flags(it)
        return it

    def _group_item(self, name):
        it = QtWidgets.QTreeWidgetItem([name, ""])
        it.setIcon(0, group_icon(16))
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        it.setData(0, KIND_ROLE, "group")
        FavTree._fix_flags(it)
        return it

    def load(self, select_group=None):
        self.tree.clear()
        for start, end, g in self.fav.entries():
            if g:
                gi = self._group_item(g)
                self.tree.addTopLevelItem(gi)
                for d in self.fav.items[start:end]:
                    gi.addChild(self._fav_item(d))
                gi.setExpanded(True)
                if g == select_group:
                    gi.setSelected(True)
                    self.tree.scrollToItem(gi)
            else:
                self.tree.addTopLevelItem(self._fav_item(self.fav.items[start]))
        paths = [d["path"] for d in self.fav.items]
        threading.Thread(target=self._check_exists, args=(paths,), daemon=True, name="fav-exists").start()
        self._update_buttons()

    def _check_exists(self, paths):
        for p in paths:
            try:
                ok = os.path.isdir(p)
            except OSError:
                ok = False
            self.sig.exists.emit(p, ok)

    def _all_fav_items(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            t = self.tree.topLevelItem(i)
            if t.data(0, KIND_ROLE) == "group":
                out += [t.child(k) for k in range(t.childCount())]
            else:
                out.append(t)
        return out

    def _mark_exists(self, path, ok):
        try:
            for it in self._all_fav_items():
                if it.data(0, PATH_ROLE) == path:
                    gray = QtGui.QBrush(QtGui.QColor("#9aa0a6"))
                    for c in (0, 1):
                        it.setForeground(c, gray if not ok else QtGui.QBrush())
                    it.setToolTip(0, T("없는 폴더: {0}").format(path) if not ok else path)
            if not ok:
                self._missing.add(path)
            self._update_buttons()
        except RuntimeError:   # 창이 이미 닫힘
            pass

    def _update_buttons(self):
        sel = self.tree.selectedItems()
        self.b_up.setEnabled(bool(sel))
        self.b_down.setEnabled(bool(sel))
        self.b_ren.setEnabled(len(sel) == 1)
        self.b_del.setEnabled(bool(sel))
        self.b_out.setEnabled(any(it.parent() is not None for it in sel))
        self.b_ungroup.setEnabled(any(it.data(0, KIND_ROLE) == "group" for it in sel))
        favs = self._all_fav_items()
        n = len(favs)
        miss = sum(1 for it in favs if it.data(0, PATH_ROLE) in self._missing)
        self.b_missing.setEnabled(bool(miss))
        g = sum(1 for i in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(i).data(0, KIND_ROLE) == "group")
        self.info.setText(T("즐겨찾기 {0}개 · 묶음 {1}개 · 없는 폴더 {2}개").format(n, g, miss))

    # ---------------------------------------------------------- 편집
    def _parent_list(self, it):
        p = it.parent()
        return (p.childCount, p.indexOfChild, p.takeChild, p.insertChild) if p else \
            (self.tree.topLevelItemCount, self.tree.indexOfTopLevelItem, self.tree.takeTopLevelItem, self.tree.insertTopLevelItem)

    def move_sel(self, step):
        sel = self.tree.selectedItems()
        if not sel:
            return
        sel.sort(key=lambda it: self._parent_list(it)[1](it), reverse=step > 0)
        for it in sel:
            count, index, take, insert = self._parent_list(it)
            i = index(it)
            j = i + step
            if 0 <= j < count():
                exp = it.isExpanded()
                take(i)
                insert(j, it)
                it.setExpanded(exp)
        self.tree.clearSelection()
        for it in sel:
            it.setSelected(True)
        self.tree.scrollToItem(sel[0])

    def rename_sel(self):
        sel = self.tree.selectedItems()
        if len(sel) == 1:
            self.tree.editItem(sel[0], 0)

    def delete_sel(self):
        sel = self.tree.selectedItems()
        for it in sel:
            try:
                p = it.parent()
                if p is not None:
                    p.removeChild(it)
                else:
                    self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(it))
            except RuntimeError:
                pass
        log.info("정리 창: 삭제 %d개", len(sel))
        self._update_buttons()

    def _unique_group(self, base):
        names = {self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount())
                 if self.tree.topLevelItem(i).data(0, KIND_ROLE) == "group"}
        n, k = base, 2
        while n in names:
            n, k = f"{base} {k}", k + 1
        return n

    def new_group(self):
        name, ok = QtWidgets.QInputDialog.getText(self, T("새 묶음"), T("묶음 이름:"), text=self._unique_group(T("새 묶음")))
        if not ok or not name.strip():
            return
        name = self._unique_group(name.strip())
        favs = [it for it in self.tree.selectedItems() if it.data(0, KIND_ROLE) == "fav"]
        gi = self._group_item(name)
        if favs:   # 첫 선택 자리에 묶음
            count, index, take, insert = self._parent_list(favs[0])
            pos_top = favs[0] if favs[0].parent() is None else favs[0].parent()
            at = self.tree.indexOfTopLevelItem(pos_top)
            self.tree.insertTopLevelItem(at, gi)
            for it in favs:
                (it.parent().removeChild(it) if it.parent() else self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(it)))
                gi.addChild(it)
        else:
            self.tree.addTopLevelItem(gi)
        gi.setExpanded(True)
        self.tree.clearSelection()
        gi.setSelected(True)
        log.info("정리 창: 새 묶음 %s (%d개)", name, len(favs))
        self._update_buttons()

    def take_out(self):
        for it in [x for x in self.tree.selectedItems() if x.parent() is not None]:
            g = it.parent()
            g.removeChild(it)
            self.tree.insertTopLevelItem(self.tree.indexOfTopLevelItem(g) + 1, it)
            it.setSelected(True)
        self._update_buttons()

    def ungroup(self):
        for g in [x for x in self.tree.selectedItems() if x.data(0, KIND_ROLE) == "group"]:
            at = self.tree.indexOfTopLevelItem(g)
            kids = g.takeChildren()
            self.tree.takeTopLevelItem(at)
            for k, it in enumerate(kids):
                self.tree.insertTopLevelItem(at + k, it)
        self._update_buttons()

    def select_missing(self):
        self.tree.clearSelection()
        for it in self._all_fav_items():
            if it.data(0, PATH_ROLE) in self._missing:
                it.setSelected(True)
        self.tree.setFocus()

    # ---------------------------------------------------------- 적용
    def result_items(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            t = self.tree.topLevelItem(i)
            if t.data(0, KIND_ROLE) == "group":
                g = t.text(0).strip() or T("묶음")
                for k in range(t.childCount()):
                    c = t.child(k)
                    out.append({"name": c.text(0).strip() or os.path.basename(c.data(0, PATH_ROLE)), "path": c.data(0, PATH_ROLE), "group": g})
            else:
                out.append({"name": t.text(0).strip() or os.path.basename(t.data(0, PATH_ROLE)), "path": t.data(0, PATH_ROLE)})
        return out

    def apply(self):
        items = self.result_items()
        self.fav.replace_all(items)
        self.close()


def group_icon(px):
    """묶음 아이콘: 폴더 두 장 겹침 (코드로 그림)"""
    base = shellops.icon_for("", True, px).pixmap(px, px)
    dpr = base.devicePixelRatio() or 1.0
    pm = QtGui.QPixmap(int(px * dpr), int(px * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    s = px * 0.8
    p.drawPixmap(QtCore.QRectF(px - s, 0, s, s), base, QtCore.QRectF(base.rect()))
    p.drawPixmap(QtCore.QRectF(0, px - s, s, s), base, QtCore.QRectF(base.rect()))
    p.end()
    return QtGui.QIcon(pm)
