# -*- coding: utf-8 -*-
"""단축키 표 (기능 → 키). 기본값 + 사용자가 바꾼 것(설정 파일 "keys")을 합쳐 쓴다.

키 글자는 Qt 표기("Ctrl+Shift+N"). 한 기능에 키 여러 개는 ";" 로 구분 ("Backspace; Alt+Up").
scope: "view" = 파일 목록에 포커스가 있을 때만 / "window" = 창 어디서나
"""
import logging
from i18n import T   # 화면 문구 번역

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

log = logging.getLogger("QE.keys")

# (기능 id, 표시 이름, 기본 키, 범위)
ACTIONS = [
    ("open", T("열기"), "Return; Enter", "view"),
    ("open_new_tab", T("폴더를 새 탭으로 열기"), "Ctrl+Return; Ctrl+Enter", "view"),
    ("up", T("상위 폴더"), "Backspace; Alt+Up", "view"),
    ("back", T("뒤로"), "Alt+Left", "view"),
    ("fwd", T("앞으로"), "Alt+Right", "view"),
    ("refresh", T("새로 고침"), "F5", "view"),
    ("rename", T("이름 바꾸기"), "F2", "view"),
    ("delete", T("삭제 (휴지통)"), "Delete", "view"),
    ("delete_perm", T("영구 삭제"), "Shift+Delete", "view"),
    ("new_folder", T("새 폴더"), "Ctrl+Shift+N", "view"),
    ("copy", T("복사"), "Ctrl+C", "view"),
    ("cut", T("잘라내기"), "Ctrl+X", "view"),
    ("paste", T("붙여넣기"), "Ctrl+V", "view"),
    ("send_copy", T("다른 칸으로 복사"), "F6", "view"),
    ("send_move", T("다른 칸으로 이동"), "Shift+F6", "view"),
    ("undo", T("되돌리기"), "Ctrl+Z", "view"),
    ("copy_path", T("경로 복사"), "Ctrl+Shift+C", "view"),
    ("properties", T("속성"), "Alt+Return; Alt+Enter", "view"),
    ("new_window", T("새 창"), "Ctrl+N", "window"),
    ("new_tab", T("새 탭"), "Ctrl+T", "window"),
    ("close_tab", T("탭 닫기"), "Ctrl+W", "window"),
    ("reopen_tab", T("닫은 탭 다시 열기"), "Ctrl+Shift+T", "window"),
    ("next_tab", T("다음 탭"), "Ctrl+Tab", "window"),
    ("prev_tab", T("이전 탭"), "Ctrl+Shift+Tab", "window"),
    ("focus_addr", T("주소창으로"), "Ctrl+L; Alt+D; F4", "window"),
    ("focus_filter", T("빠른 필터"), "Ctrl+F", "window"),
    ("global_search", T("전체 검색"), "Ctrl+Shift+F", "window"),
    ("toggle_hidden", T("숨긴 항목 보이기/숨기기"), "Ctrl+H", "window"),
    ("add_fav", T("현재 폴더를 즐겨찾기에 추가"), "Ctrl+D", "window"),
    ("toggle_chrome", T("메뉴·즐겨찾기 접기/펼치기"), "Ctrl+Shift+M", "window"),
] + [(f"pane{i + 1}", T('{0}번 칸으로').format(i + 1), f"Ctrl+{i + 1}", "window") for i in range(6)]

LABEL = {a: lbl for a, lbl, _, _ in ACTIONS}
SCOPE = {a: sc for a, _, _, sc in ACTIONS}
DEFAULT = {a: k for a, _, k, _ in ACTIONS}


def norm(seq):
    """키 글자 정규화 (대소문자·순서 차이 제거)"""
    return QtGui.QKeySequence(seq.strip()).toString(QtGui.QKeySequence.PortableText) if seq and seq.strip() else ""


def split(keys):
    return [norm(k) for k in (keys or "").split(";") if norm(k)]


def current(custom):
    """{기능: [키, ...]} — 사용자 설정(custom)이 있으면 그것, 없으면 기본"""
    return {a: split(custom.get(a, DEFAULT[a])) for a in DEFAULT}


def conflicts(km):
    """같은 키가 두 기능에 걸린 것 [(키, [기능...])]"""
    seen = {}
    for a, keys in km.items():
        for k in keys:
            seen.setdefault(k, []).append(a)
    return [(k, v) for k, v in seen.items() if len(v) > 1]


def event_key(ev):
    """키 입력 이벤트 → 정규화된 키 글자"""
    return norm(QtGui.QKeySequence(ev.keyCombination()).toString(QtGui.QKeySequence.PortableText))


# ================================================================ 설정 창
class KeyDialog(QtWidgets.QDialog):
    def __init__(self, custom, parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("단축키 설정 (Shortcuts)"))
        self.resize(560, 640)
        self.result_keys = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(T("칸을 클릭하고 원하는 키를 누르면 바뀝니다. 기능마다 2개까지. 지우기는 Del 버튼.")))
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(T("🔍 기능 이름이나 키로 찾기 (예: 탭, Ctrl+W)"))
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.tbl = QtWidgets.QTableWidget(len(ACTIONS), 3)
        self.tbl.setHorizontalHeaderLabels([T("기능"), T("단축키 1"), T("단축키 2")])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tbl.setColumnWidth(1, 150)
        self.tbl.setColumnWidth(2, 150)
        km = current(custom)
        self.edits = {}
        for r, (a, lbl, _d, sc) in enumerate(ACTIONS):
            it = QtWidgets.QTableWidgetItem(lbl + ("" if sc == "window" else T("  (파일 목록에서)")))
            it.setFlags(Qt.ItemIsEnabled)
            self.tbl.setItem(r, 0, it)
            eds = []
            for c in (1, 2):
                e = QtWidgets.QKeySequenceEdit()
                e.setMaximumSequenceLength(1)
                e.setClearButtonEnabled(True)
                keys = km[a]
                if len(keys) >= c:
                    e.setKeySequence(QtGui.QKeySequence(keys[c - 1]))
                self.tbl.setCellWidget(r, c, e)
                eds.append(e)
            self.edits[a] = eds
        lay.addWidget(self.tbl, 1)
        self.warn = QtWidgets.QLabel()
        self.warn.setStyleSheet("color:#c62828;")
        self.warn.setWordWrap(True)
        lay.addWidget(self.warn)
        row = QtWidgets.QHBoxLayout()
        b_def = QtWidgets.QPushButton(T("전부 기본값으로"))
        b_def.clicked.connect(self._defaults)
        b_ok = QtWidgets.QPushButton(T("저장"))
        b_ok.setDefault(False)
        b_ok.setAutoDefault(False)
        b_ok.clicked.connect(self._save)
        b_no = QtWidgets.QPushButton(T("취소"))
        b_no.setAutoDefault(False)
        b_no.clicked.connect(self.reject)
        row.addWidget(b_def)
        row.addStretch(1)
        row.addWidget(b_ok)
        row.addWidget(b_no)
        lay.addLayout(row)

    def _filter(self, t):
        t = t.strip().lower()
        for r, (a, lbl, _d, _s) in enumerate(ACTIONS):
            keys = " ".join(e.keySequence().toString() for e in self.edits[a]).lower()
            self.tbl.setRowHidden(r, bool(t) and t not in lbl.lower() and t not in keys)

    def _defaults(self):
        for a, eds in self.edits.items():
            ks = split(DEFAULT[a])
            for i, e in enumerate(eds):
                e.setKeySequence(QtGui.QKeySequence(ks[i]) if i < len(ks) else QtGui.QKeySequence())
        self.warn.clear()

    def collect(self):
        return {a: [norm(e.keySequence().toString(QtGui.QKeySequence.PortableText)) for e in eds if not e.keySequence().isEmpty()]
                for a, eds in self.edits.items()}

    def _save(self):
        km = self.collect()
        bad = conflicts(km)
        if bad:
            self.warn.setText(T("같은 키가 여러 기능에 걸려 있습니다: ") +
                              " / ".join(f"{k} = {', '.join(LABEL[a] for a in acts)}" for k, acts in bad))
            return
        # 기본과 다른 것만 저장
        self.result_keys = {a: "; ".join(ks) for a, ks in km.items() if ks != split(DEFAULT[a])}
        self.accept()
