# -*- coding: utf-8 -*-
"""파일 색 규칙 (COLORRULES_VER 1.0.0, 0.9.127 빌드 5 — 사용자 11/10 토탈 커맨더 '파일 종류별 색' 참고)

- 규칙 = 이름 패턴(* ? , 여러 개는 ;) + 대상(파일/폴더/모두) + 최근 N일 안에 바뀐 것만(0 = 상관없음) + 글자색
- 위에 있는 규칙부터 보고 처음 맞는 것의 색. 맞는 게 없으면 원래 색
- 목록 그릴 때마다 불리므로 (이름, 폴더?, 수정 시각) → 색 을 기억해 둠 (규칙이 바뀌거나 1시간 지나면 비움)
설정: SETTINGS["color_rules"] = [{"on", "pat", "target", "days", "color"}]
로그: bin\\log\\4Dir.log [QE.colors]
"""
import time
import fnmatch
import logging

from i18n import T
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt

COLORRULES_VER = "1.0.0"
log = logging.getLogger("QE.colors")
TARGETS = (("file", "파일"), ("dir", "폴더"), ("all", "파일·폴더"))


class Rules:
    def __init__(self):
        self.rules = []     # [(패턴들, 대상, 초, QColor)]
        self._cache = {}
        self._hour = 0

    def load(self, data):
        out = []
        for r in data or []:
            try:
                if not r.get("on", True):
                    continue
                pats = [x.strip().lower() for x in (r.get("pat") or "").split(";") if x.strip()]
                pats = [x if ("*" in x or "?" in x) else f"*{x}*" for x in pats] or ["*"]
                c = QtGui.QColor(r.get("color") or "")
                if not c.isValid():
                    continue
                out.append((pats, r.get("target") or "file", max(0, int(r.get("days") or 0)) * 86400, c))
            except Exception:
                log.exception("색 규칙 읽기 실패 %r", r)
        self.rules = out
        self._cache = {}
        log.info("파일 색 규칙 %d개 켬", len(out))

    def color(self, name, is_dir, mtime):
        """맞는 규칙의 색 (없으면 None)"""
        h = int(time.time() // 3600)
        if h != self._hour:
            self._hour, self._cache = h, {}
        k = (name, is_dir, mtime)
        if k in self._cache:
            return self._cache[k]
        low, now, res = name.lower(), time.time(), None
        for pats, tgt, secs, c in self.rules:
            if (tgt == "file" and is_dir) or (tgt == "dir" and not is_dir):
                continue
            if secs and (not mtime or now - mtime > secs):
                continue
            if any(fnmatch.fnmatch(low, p) for p in pats):
                res = c
                break
        if len(self._cache) > 50000:
            self._cache = {}
        self._cache[k] = res
        return res


class RulesDialog(QtWidgets.QDialog):
    """규칙 표 편집: 사용 · 이름 패턴 · 대상 · 최근 N일 · 색"""

    def __init__(self, parent, data):
        super().__init__(parent)
        self.setWindowTitle(T("파일 색 규칙"))
        self.resize(640, 380)
        lay = QtWidgets.QVBoxLayout(self)
        tip = QtWidgets.QLabel(T("이름 패턴에 맞는 파일·폴더의 글자색을 바꿉니다. 위에 있는 규칙이 먼저 적용됩니다.\n"
                                 "패턴 예:  *.max      *.psd; *.png      *_final*      (비워 두면 전부)"))
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.tbl = QtWidgets.QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels([T("사용"), T("이름 패턴"), T("적용 대상"), T("최근 며칠 안에 바뀐 것만"), T("색")])
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        for c in (0, 2, 3, 4):
            hh.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        lay.addWidget(self.tbl, 1)
        bl = QtWidgets.QHBoxLayout()
        for txt, fn in ((T("추가"), lambda: self.add_row({})), (T("지우기"), self.del_row),
                        (T("위로"), lambda: self.move_row(-1)), (T("아래로"), lambda: self.move_row(1))):
            b = QtWidgets.QPushButton(txt)
            b.clicked.connect(fn)
            bl.addWidget(b)
        bl.addStretch(1)
        lay.addLayout(bl)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText(T("저장"))
        bb.button(QtWidgets.QDialogButtonBox.Cancel).setText(T("취소"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for r in data or []:
            self.add_row(r)

    def _color_btn(self, color):
        b = QtWidgets.QPushButton()
        b.setFixedWidth(70)
        b.setProperty("color", color)

        def paint():
            b.setText(b.property("color"))
            b.setStyleSheet(f"QPushButton {{ color: {b.property('color')}; font-weight: bold; }}")

        def pick():
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor(b.property("color")), self, T("색"))
            if c.isValid():
                b.setProperty("color", c.name())
                paint()
        b.clicked.connect(pick)
        paint()
        return b

    def add_row(self, r):
        i = self.tbl.rowCount()
        self.tbl.insertRow(i)
        self._set_row(i, r)
        self.tbl.selectRow(i)

    def _set_row(self, i, r):
        on = QtWidgets.QTableWidgetItem()
        on.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        on.setCheckState(Qt.Checked if r.get("on", True) else Qt.Unchecked)
        self.tbl.setItem(i, 0, on)
        self.tbl.setItem(i, 1, QtWidgets.QTableWidgetItem(r.get("pat", "")))
        cb = QtWidgets.QComboBox()
        for k, lbl in TARGETS:
            cb.addItem(T(lbl), k)
        cb.setCurrentIndex(max(0, [k for k, _ in TARGETS].index(r.get("target", "file")) if r.get("target", "file") in [k for k, _ in TARGETS] else 0))
        self.tbl.setCellWidget(i, 2, cb)
        sp = QtWidgets.QSpinBox()
        sp.setRange(0, 3650)
        sp.setSpecialValueText(T("상관없음"))
        sp.setSuffix(" " + T("일"))
        sp.setValue(int(r.get("days") or 0))
        self.tbl.setCellWidget(i, 3, sp)
        self.tbl.setCellWidget(i, 4, self._color_btn(r.get("color") or "#1f6fd0"))

    def row_data(self, i):
        it = self.tbl.item(i, 1)
        return {"on": self.tbl.item(i, 0).checkState() == Qt.Checked, "pat": it.text().strip() if it else "",
                "target": self.tbl.cellWidget(i, 2).currentData(), "days": self.tbl.cellWidget(i, 3).value(),
                "color": self.tbl.cellWidget(i, 4).property("color")}

    def del_row(self):
        i = self.tbl.currentRow()
        if i >= 0:
            self.tbl.removeRow(i)

    def move_row(self, d):
        i = self.tbl.currentRow()
        j = i + d
        if i < 0 or not (0 <= j < self.tbl.rowCount()):
            return
        a = self.row_data(i)   # 줄을 빼서 새 자리에 다시 넣음 (칸 안 위젯을 덮어쓰면 옛 위젯 그림이 남음 — qe258 캡처)
        self.tbl.removeRow(i)
        self.tbl.insertRow(j)
        self._set_row(j, a)
        self.tbl.selectRow(j)

    def result_rules(self):
        return [self.row_data(i) for i in range(self.tbl.rowCount())]
