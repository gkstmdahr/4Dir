# -*- coding: utf-8 -*-
"""단축키 표 (기능 → 키). 기본값 + 사용자가 바꾼 것(설정 파일 "keys")을 합쳐 쓴다.
v0.9.83: 마우스 버튼 표 (설정 파일 "mouse" = {"Ctrl+middle": 기능, ...}, 기본 동작과 다른 것만) — 같은 설정 창의 '마우스' 탭

키 글자는 Qt 표기("Ctrl+Shift+N"). 한 기능에 키 여러 개는 ";" 로 구분 ("Backspace; Alt+Up").
scope: "view" = 파일 목록에 포커스가 있을 때만 / "window" = 창 어디서나
"""
import logging
import json
import os
from i18n import T   # 화면 문구 번역

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

log = logging.getLogger("QE.keys")

# (기능 id, 표시 이름, 기본 키, 범위)
ACTIONS = [
    ("open", T("열기"), "Return; Enter", "view"),
    ("open_new_tab", T("폴더를 새 탭으로 열기 (파일이면 그 폴더 위치)"), "Ctrl+Return; Ctrl+Enter", "view"),   # v0.9.94 Everything 경로 열기처럼
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
    ("select_pattern", T("패턴으로 고르기…"), "Ctrl+Shift+A", "view"),   # v0.9.89
    ("sha256", T("확인값(SHA256) 보기"), "", "view"),   # v0.9.89
    ("quick_preview", T("미리보기 창 바로 보기/닫기"), "Space", "view"),   # 빌드 20 (다른 파일 관리자처럼 스페이스)
    ("flat_view", T("하위 폴더 펼쳐 보기 (모든 파일 한 목록)"), "", "view"),   # 빌드 20
    ("find_dupes", T("중복 파일 찾기…"), "", "view"),   # 빌드 20
    ("view_file", T("글자·16진수로 보기"), "F3", "view"),   # 0.9.109 빌드 3
    ("file_attrs", T("날짜·속성 바꾸기…"), "", "view"),
    ("img_batch", T("그림 크기·형식 바꾸기…"), "", "view"),
    ("space_map", T("디스크 사용량 트리맵"), "", "view"),
    ("new_window", T("새 창"), "Ctrl+N", "window"),
    ("new_tab", T("새 탭"), "Ctrl+T", "window"),
    ("close_tab", T("탭 닫기"), "Ctrl+W", "window"),
    ("lock_tab", T("탭 잠금/잠금 해제"), "", "window"),
    ("toggle_chips", T("형식 단추 줄 보이기/숨기기"), "", "window"),   # 빌드 27 위쪽 단추와 같음   # v0.9.95 (기본 키 없음 — 단축키 설정에서)
    ("reopen_tab", T("닫은 탭 다시 열기"), "Ctrl+Shift+T", "window"),
    ("next_tab", T("다음 탭"), "Ctrl+Tab", "window"),
    ("prev_tab", T("이전 탭"), "Ctrl+Shift+Tab", "window"),
    ("focus_addr", T("주소창으로"), "Ctrl+L; Alt+D; F4", "window"),
    ("focus_filter", T("빠른 필터"), "Ctrl+F", "window"),
    ("global_search", T("전체 검색"), "Ctrl+Shift+F", "window"),
    ("toggle_hidden", T("숨긴 항목 보이기/숨기기"), "Ctrl+H", "window"),
    ("add_fav", T("현재 폴더를 즐겨찾기에 추가"), "Ctrl+D", "window"),
    ("toggle_chrome", T("메뉴·즐겨찾기 접기/펼치기"), "Ctrl+Shift+M", "window"),
    ("toggle_preview", T("미리보기 창 보이기/숨기기"), "Alt+P", "window"),
    ("toggle_nav", T("탐색 창 보이기/숨기기"), "", "window"),
    ("toggle_memo", T("메모 창 보이기/숨기기"), "Alt+M", "window"),   # v0.9.108   # v0.9.101 공용이면 공용 탐색 창, 칸마다면 지금 칸 (기본 키 없음)
    ("compare", T("두 칸 비교"), "Shift+F2", "window"),
    ("sync_dirs", T("폴더 맞추기 (두 칸)…"), "", "window"),   # 0.9.109 빌드 3
    ("ftp_connect", T("FTP 연결…"), "", "window"),
    ("user_buttons", T("사용자 단추 편집…"), "", "window"),   # v0.9.89 (토탈 커맨더와 같은 키)
    ("palette", T("명령 찾기…"), "Ctrl+Shift+P", "window"),
    ("settings", T("설정…"), "Ctrl+,", "window"),   # v0.9.104 설정 창
    ("ws_latest", T("최근 저장한 창 구성 불러오기"), "", "window"),   # v0.9.98 이슈 #1 (기본 키 없음 — 단축키 설정에서)
    ("ws_slot1", T("지정 1 창 구성 불러오기"), "", "window"),
    ("ws_slot2", T("지정 2 창 구성 불러오기"), "", "window"),   # v0.9.89   # 탐색기와 같은 키 (v0.9.58)
    # v0.9.68: 다른 프로그램을 쓰다가도 이 키 하나로 4Dir 를 앞으로 불러 전체 검색칸에 바로 입력 (윈도우 전역 단축키 RegisterHotKey)
    ("global_hotkey", T("4Dir 불러서 전체 검색 (다른 프로그램 쓰는 중에도)"), "Ctrl+Alt+F", "global"),
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


# ================================================================ 마우스 버튼 (v0.9.83 사용자 의견: 단축키처럼 버튼마다 기능)
# v0.9.84 사용자: 키보드처럼 왼쪽 = 기능, 오른쪽 = 마우스 칸 2개. 칸을 누르고 원하는 버튼을(수정키 아무 조합이나 같이) 눌러 지정.
# 그냥 왼쪽 클릭만 고정(고르기·열기·끌기가 전부 이것). 원래 쓰임(여러 개 고르기 등)을 바꾸거나 다른 기능에서 옮겨 와도 막지 않음 —
# 옆 칸에 빨갛게 알려 주고 저장은 사용자가 정함 (사용자 11/3: 팝업으로 막지 말 것)
# 설정 "mouse" = {조합: 기능} 기본(MOUSE_DEFAULT)과 다른 것만, "" = 기본 조합을 뺌(아무것도 안 함)
BUTTONS = [("left", T("왼쪽 클릭")), ("right", T("오른쪽 클릭")), ("middle", T("가운데 클릭")),
           ("back", T("뒤로 버튼(4번)")), ("fwd", T("앞으로 버튼(5번)"))]
MODS = [("Ctrl", Qt.ControlModifier), ("Shift", Qt.ShiftModifier), ("Alt", Qt.AltModifier)]
FIXED = ("left",)
BUILTIN, NONE, MENU = "builtin", "none", "menu"
MOUSE_DEFAULT = {"right": MENU, "middle": "open_new_tab", "back": "back", "fwd": "fwd"}   # 원래 하던 것 그대로
_QBTN = {Qt.LeftButton: "left", Qt.RightButton: "right", Qt.MiddleButton: "middle", Qt.BackButton: "back", Qt.ForwardButton: "fwd"}


def combo_label(c):
    parts = c.split("+")
    return " + ".join(parts[:-1] + [dict(BUTTONS)[parts[-1]]])


def builtin_use(c):
    """그 조합의 원래 쓰임 (기본 표에 없는 것) — 지정하면 옆 칸에 '원래: …' 로 알림"""
    if c in MOUSE_DEFAULT:
        return ""
    b = c.rpartition("+")[2]
    return {"Ctrl+left": T("여러 개 고르기"), "Shift+left": T("범위 고르기")}.get(c) or \
        {"left": T("고르기 (그냥 클릭과 같음)"), "right": T("우클릭 메뉴"), "middle": T("폴더를 새 탭으로 열기"), "back": T("뒤로"), "fwd": T("앞으로")}.get(b, "")


def mouse_rows():
    """설정 창 기능 줄 [(id, 이름)] — 우클릭 메뉴 + 단축키 기능 전부(어디서나 단축키 제외)"""
    return [(MENU, T("우클릭 메뉴"))] + [(a, lbl) for a, lbl, _k, sc in ACTIONS if sc != "global"]


def mouse_combo(button, mods):
    """눌린 버튼 + 수정키 → 조합 글자 ("Ctrl+Shift+middle"). 모르는 버튼이면 None"""
    b = _QBTN.get(button)
    if b is None:
        return None
    return "".join(m + "+" for m, f in MODS if mods & f) + b


def mouse_map(custom):
    """{조합: 기능} — 기본 + 사용자 지정 ("" 는 뺌)"""
    m = dict(MOUSE_DEFAULT)
    m.update(custom or {})
    return {c: a for c, a in m.items() if a and a not in (NONE, BUILTIN) and (a == MENU or a in LABEL)}


def mouse_action(custom, combo):
    """조합 → 기능 id. BUILTIN = 원래대로(Qt·4Dir 기본 처리), NONE = 아무것도 안 함"""
    if not combo or combo in FIXED:
        return BUILTIN
    c = custom or {}
    if c.get(combo) in ("", NONE):
        return NONE
    a = mouse_map(c).get(combo)
    if a is None or a == MOUSE_DEFAULT.get(combo):
        return BUILTIN   # 지정 없음, 또는 원래 하던 그대로
    return a


def event_key(ev):
    """키 입력 이벤트 → 정규화된 키 글자.
    0.9.109 (이슈 #7): 숫자패드 Enter 는 Qt 가 KeypadModifier 를 붙여 'Num+Enter' 가 됨 → 기본 키('Enter')와 안 맞아 목록에서 안 열림.
    Enter 만 숫자패드 표시를 뺌 (다른 숫자패드 키 구분은 그대로)"""
    kc = ev.keyCombination()
    if kc.key() in (Qt.Key_Enter, Qt.Key_Return) and kc.keyboardModifiers() & Qt.KeypadModifier:
        kc = QtCore.QKeyCombination(kc.keyboardModifiers() & ~Qt.KeypadModifier, kc.key())
    return norm(QtGui.QKeySequence(kc).toString(QtGui.QKeySequence.PortableText))


def _mark(it, base, notes):
    """기능 칸: 겹침·옮김 알림이 있으면 이름 뒤에 붙이고 빨갛게 (v0.9.85 사용자: 알림 칸 따로 말고 기능 쪽에)"""
    it.setText(base + ("   ⚠ " + " / ".join(notes) if notes else ""))
    it.setToolTip(it.text() if notes else "")
    it.setForeground(QtGui.QColor("#c62828") if notes else QtGui.QBrush())
    it.setFlags(Qt.ItemIsEnabled)


# ================================================================ 설정 창
_PAD_NAV = (Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
            Qt.Key_Clear, Qt.Key_Insert, Qt.Key_Delete)


def _numlock_on():
    """Num Lock 켜짐? (켜져 있는데 숫자패드에서 이동 키가 오면 Shift 를 같이 누른 것)"""
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetKeyState(0x90) & 1)
    except Exception:
        return False


class KeyDialog(QtWidgets.QDialog):
    def __init__(self, custom, parent=None, mouse=None):
        super().__init__(parent)
        self.setWindowTitle(T("단축키 설정 (Shortcuts)"))
        self.resize(820, 680)
        self.result_keys = None
        self.result_mouse = None
        outer = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        outer.addWidget(self.tabs, 1)
        kb = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(kb)
        lay.setContentsMargins(6, 6, 6, 6)
        self.tabs.addTab(kb, T("키보드 (Keyboard)"))
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
        self.kbase = {}
        for r, (a, lbl, _d, sc) in enumerate(ACTIONS):
            self.kbase[a] = lbl + {"window": "", "view": T("  (파일 목록에서)"), "global": T("  (어디서나)")}[sc]
            it = QtWidgets.QTableWidgetItem(self.kbase[a])
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
                e.keySequenceChanged.connect(lambda *_, e=e, a=a: self._key_set(e, a))
                # v0.9.99 사용자 11/5: 한글 입력 상태면 글자 키가 입력기로 가서 칸에 안 들어감 → 키 칸은 입력기 끔 + 진단 로그
                for w in [e] + e.findChildren(QtWidgets.QLineEdit):
                    w.setAttribute(Qt.WA_InputMethodEnabled, False)
                    w.installEventFilter(self)
                e.setProperty("qe_action", a)
                self.tbl.setCellWidget(r, c, e)
                eds.append(e)
            self.edits[a] = eds
        lay.addWidget(self.tbl, 1)
        self.tbl.setColumnWidth(1, 170)
        self.tbl.setColumnWidth(2, 170)
        self._kmv = []   # 키보드 옮김 기록 [(키, 원래 기능, 새 기능)] — 알림 글자용
        self._build_mouse(mouse or {})
        self._key_notes()
        lay = outer
        self.warn = QtWidgets.QLabel()
        self.warn.setStyleSheet("color:#c62828;")
        self.warn.setWordWrap(True)
        lay.addWidget(self.warn)
        self.info = QtWidgets.QLabel()   # v0.9.99 내보내기·가져오기 결과 (빨강 아님)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        row = QtWidgets.QHBoxLayout()
        b_def = QtWidgets.QPushButton(T("전부 기본값으로"))
        b_def.clicked.connect(self._defaults)
        # 되돌리기·다시 하기 (v0.9.86 사용자: 바꿨는데 겹쳐서 옮겨졌으면 되돌려 이전 단축키로)
        # 키 칸에 커서가 있으면 Ctrl+Z 는 그 칸의 새 단축키로 들어감 → 버튼은 언제나, 단축키는 키 칸 밖에서
        self.b_undo = QtWidgets.QPushButton(T("↶ 되돌리기 (Ctrl+Z)"))
        self.b_redo = QtWidgets.QPushButton(T("↷ 다시 하기 (Ctrl+Y)"))
        for b, fn, k in ((self.b_undo, self.undo, "Ctrl+Z"), (self.b_redo, self.redo, "Ctrl+Y")):
            b.setAutoDefault(False)
            b.clicked.connect(fn)
            QtGui.QShortcut(QtGui.QKeySequence(k), self, fn)
        self._hist, self._redo, self._busy = [], [], False
        self._last = self._snap()
        b_ok = QtWidgets.QPushButton(T("저장"))
        b_ok.setDefault(False)
        b_ok.setAutoDefault(False)
        b_ok.clicked.connect(self._save)
        b_no = QtWidgets.QPushButton(T("취소"))
        b_no.setAutoDefault(False)
        b_no.clicked.connect(self.reject)
        row.addWidget(b_def)
        row.addWidget(self.b_undo)
        row.addWidget(self.b_redo)
        # v0.9.99 사용자 11/5: 단축키만 따로 저장·불러오기 (탭·창 구성은 안 건드림)
        self.b_exp = QtWidgets.QPushButton(T("단축키 내보내기…"))
        self.b_imp = QtWidgets.QPushButton(T("단축키 가져오기…"))
        for b, fn in ((self.b_exp, self.export_keys), (self.b_imp, self.import_keys)):
            b.setAutoDefault(False)
            b.clicked.connect(lambda *_, fn=fn: fn())
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_ok)
        row.addWidget(b_no)
        lay.addLayout(row)
        self._hist_buttons()

    def _build_mouse(self, mouse):
        """마우스 탭 (v0.9.84): 키보드 탭과 같은 모양 — 왼쪽 기능(알림은 기능 칸에 빨갛게, v0.9.85), 오른쪽 마우스 칸 2개"""
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        self.tabs.addTab(w, T("마우스 (Mouse)"))
        lb = QtWidgets.QLabel(T("칸을 클릭한 뒤 원하는 마우스 버튼을 누르면 바뀝니다 (Ctrl·Shift·Alt 를 같이 눌러도 됨, 그냥 왼쪽 클릭은 지정 불가). 지우기는 ✕, 취소는 Esc."))
        lb.setWordWrap(True)
        lay.addWidget(lb)
        rows = mouse_rows()
        self.mtbl = QtWidgets.QTableWidget(len(rows), 3)
        self.mtbl.setHorizontalHeaderLabels([T("기능"), T("마우스 1"), T("마우스 2")])
        self.mtbl.verticalHeader().setVisible(False)
        self.mtbl.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)   # 기능 칸(알림 포함)이 남는 폭을 씀
        for c in (1, 2):
            self.mtbl.setColumnWidth(c, 200)
        self.mbase = dict(rows)
        by_act = {}
        for c, a in sorted(mouse_map(mouse).items(), key=lambda x: (x[0].count("+"), x[0])):
            by_act.setdefault(a, []).append(c)
        self.medits = {}
        for r, (a, lbl) in enumerate(rows):
            it = QtWidgets.QTableWidgetItem(lbl)
            it.setFlags(Qt.ItemIsEnabled)
            self.mtbl.setItem(r, 0, it)
            eds = []
            for k in (0, 1):
                e = MouseEdit(self)
                cs = by_act.get(a, [])
                if k < len(cs):
                    e.set_combo(cs[k])
                e.changed.connect(lambda e=e: self._mouse_set(e))
                self.mtbl.setCellWidget(r, k + 1, e)
                eds.append(e)
            self.medits[a] = eds
        self._mmv = []   # 마우스 옮김 기록 [(조합, 원래 기능, 새 기능)]
        self._mouse_notes()
        lay.addWidget(self.mtbl, 1)

    # ---------------------------------------------------------- 되돌리기·다시 하기
    def _snap(self):
        """지금 표 전체 (키보드·마우스·옮김 기록)"""
        return ({a: [e.keySequence().toString(QtGui.QKeySequence.PortableText) for e in eds] for a, eds in self.edits.items()},
                {a: [e.combo for e in eds] for a, eds in self.medits.items()}, list(self._kmv), list(self._mmv))

    def _restore(self, st):
        kb, mb, self._kmv, self._mmv = st[0], st[1], list(st[2]), list(st[3])
        for a, eds in self.edits.items():
            for e, k in zip(eds, kb[a]):
                e.blockSignals(True)
                e.setKeySequence(QtGui.QKeySequence(k))
                e.blockSignals(False)
        for a, eds in self.medits.items():
            for e, c in zip(eds, mb[a]):
                e.set_combo(c)
        self._last = st
        self._key_notes()
        self._mouse_notes()
        self._hist_buttons()

    def _changed(self):
        """사용자가 한 번 바꿀 때마다 (옮김까지 끝난 뒤) — 바꾸기 전 상태를 되돌리기 목록에"""
        if self._busy:
            return
        now = self._snap()
        if now[:2] != self._last[:2]:
            self._hist.append(self._last)
            self._redo.clear()
        self._last = now
        self._hist_buttons()

    def _hist_buttons(self):
        if hasattr(self, "b_undo"):
            self.b_undo.setEnabled(bool(self._hist))
            self.b_redo.setEnabled(bool(self._redo))

    def undo(self):
        if not self._hist:
            return
        self._redo.append(self._snap())
        st = self._hist.pop()
        log.info("단축키 설정 되돌리기 (남은 %d)", len(self._hist))
        self._restore(st)
        self.warn.clear()

    def redo(self):
        if not self._redo:
            return
        self._hist.append(self._snap())
        st = self._redo.pop()
        log.info("단축키 설정 다시 하기 (남은 %d)", len(self._redo))
        self._restore(st)

    # ---------------------------------------------------------- 단축키만 내보내기·가져오기 (v0.9.99)
    def _keys_dir(self):
        return os.path.join(os.path.expanduser("~"), "Documents")

    def export_keys(self, path=None):
        """지금 표(저장 전 바꾼 것 포함)의 키보드·마우스 단축키 전부 → json 파일 하나"""
        if path is None:
            path, _f = QtWidgets.QFileDialog.getSaveFileName(self, T("단축키 내보내기"),
                                                             os.path.join(self._keys_dir(), "4Dir_shortcuts.json"), "json (*.json)")
            if not path:
                return None
        data = {"app": "4Dir", "kind": "shortcuts", "format": 1,
                "keys": {a: [k for k in ks if k] for a, ks in self.collect().items()},
                "mouse": {e.combo: a for a, eds in self.medits.items() for e in eds if e.combo}}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception as ex:
            log.exception("단축키 내보내기 실패 %s", path)
            self.warn.setText(T("단축키를 저장하지 못했습니다: {0}").format(ex))
            return None
        log.info("단축키 내보내기 %s (키보드 %d · 마우스 %d)", path, sum(1 for v in data["keys"].values() if v), len(data["mouse"]))
        self.warn.clear()
        self.info.setText(T("단축키를 파일로 저장했습니다: {0}").format(path))
        return path

    def import_keys(self, path=None):
        """단축키 파일 → 표에 채움(저장을 눌러야 적용, 되돌리기로 취소). 파일에 없는 기능(새 버전 기능)은 지금 값 그대로"""
        if path is None:
            path, _f = QtWidgets.QFileDialog.getOpenFileName(self, T("단축키 가져오기"), self._keys_dir(), "json (*.json)")
            if not path:
                return False
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            ok = isinstance(data, dict) and data.get("app") == "4Dir" and data.get("kind") == "shortcuts"
        except Exception:
            log.exception("단축키 파일 읽기 실패 %s", path)
            ok = False
        if not ok:
            log.info("단축키 파일 아님 %s", path)
            self.info.clear()
            self.warn.setText(T("4Dir 단축키 파일이 아닙니다: {0}").format(path))
            return False
        cur = self._snap()
        fk, fm = data.get("keys") or {}, data.get("mouse") or {}
        kb = {}
        for a in self.edits:
            ks = [str(k) for k in fk[a] if k][:2] if isinstance(fk.get(a), list) else cur[0][a]
            kb[a] = (list(ks) + ["", ""])[:2]
        by = {}
        for c, a in fm.items():
            if a in self.medits:
                by.setdefault(a, []).append(c)
        mb = {a: (by.get(a, [])[:2] + ["", ""])[:2] for a in self.medits}
        self._hist.append(cur)
        self._redo.clear()
        self._restore((kb, mb, [], []))
        log.info("단축키 가져오기 %s (키보드 %d · 마우스 %d, 저장 전)", path, sum(1 for v in kb.values() if any(v)), len(fm))
        self.warn.clear()
        self.info.setText(T("단축키를 가져왔습니다: {0} — [저장]을 눌러야 적용됩니다 (되돌리기로 취소)").format(os.path.basename(path)))
        return True

    # ---------------------------------------------------------- 키보드
    def eventFilter(self, obj, ev):
        """키 칸에 들어온 키를 로그로 + 한글 입력기가 먹은 키(VK_PROCESSKEY 229)면 영어로 바꾸라고 알림 (v0.9.99)"""
        t = ev.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease) and ev.key() in (
                Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr):
            # 사용자 11/5 실기(재현 확인): Shift+숫자패드 뒤 Windows 가 Shift 를 다시 눌러 보냄 → Qt 키 칸은 키가 들어간 뒤
            #   다음 키 누름(수정키 혼자여도)을 '새 입력 시작'으로 보고 칸을 비움 → 수정키 혼자 누름·뗌은 칸에 안 넘김
            return True
        if t == QtCore.QEvent.KeyPress and ev.modifiers() & Qt.KeypadModifier and ev.key() in _PAD_NAV and _numlock_on():
            # 사용자 11/5: Shift+숫자패드 = Num Lock 켜짐인데 숫자 대신 End·PgDown 등이 옴(Windows 가 바꿔 줌, 어떤 숫자였는지 알 수 없음)
            #   → 지정 안 함 + 빨간 안내 (사용자 '해결 못 하면 빨간 글씨로')
            log.info("키 칸: Shift+숫자패드(→%s) 지정 안 함", QtGui.QKeySequence(ev.key()).toString())
            self.info.clear()
            self.warn.setText(T("Shift+숫자패드는 Windows 가 다른 키(End·PgDown 등)로 바꿔 보내서 지정할 수 없습니다. Shift 없이 누르거나 다른 키를 쓰세요."))
            return True
        if t == QtCore.QEvent.KeyPress:
            vk = ev.nativeVirtualKey()
            log.info("키 칸 입력 key=0x%x vk=%d text=%r mods=%s (%s)", ev.key(), vk, ev.text(),
                     int(ev.modifiers().value) if hasattr(ev.modifiers(), "value") else int(ev.modifiers()),
                     obj.property("qe_action") or (obj.parent() and obj.parent().property("qe_action")))
            if ev.key() in (0, Qt.Key_unknown) and vk != 229:
                # 사용자 11/5 실기: Alt+숫자패드 = Windows 'Alt 코드' 글자 입력 → Alt 를 떼면 글자만 옴(key 0, 예 '쿰'). 한글 아님 → 무시
                log.info("키 칸: 키 없는 글자 %r 무시 (Alt+숫자패드 Alt 코드 등)", ev.text())
                return True
            if vk == 229:
                self.warn.setText(T("한글 입력 상태라 키를 읽지 못했습니다. 한/영 키로 영어로 바꾼 뒤 다시 누르세요."))
            else:   # v0.9.99: Qt 6.11 키 칸은 Ctrl+Shift+Alt+글자를 못 받음(재현 확인) → 비어 있으면 직접 넣음
                ed = obj if isinstance(obj, QtWidgets.QKeySequenceEdit) else obj.parent()
                # v0.9.99 사용자 11/5 '연타하다 어느 순간 입력 안 됨': Qt 키 칸은 한 번 키가 들어가면 다음 키를 무시(재현 확인)
                #   → 수정키 아닌 키가 오면 먼저 비워서(신호 막음) 새 키가 늘 앞 키를 바꾸게
                if isinstance(ed, QtWidgets.QKeySequenceEdit) and ev.key() not in (
                        Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
                    ed.blockSignals(True)
                    ed.clear()
                    ed.blockSignals(False)
                mods = ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
                key = (Qt.Key(Qt.Key_A.value + vk - 0x41) if 0x41 <= vk <= 0x5A else
                       Qt.Key(Qt.Key_0.value + vk - 0x30) if 0x30 <= vk <= 0x39 else None)
                if key is None and ev.key() not in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr,
                                                    Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape, 0, Qt.Key_unknown):
                    key = Qt.Key(ev.key())   # 사용자 11/5 실기: Shift+숫자패드 → Windows 가 End·PgDown 등으로 바꿔 줌, Qt 칸이 못 받음 → 그 키로
                if isinstance(ed, QtWidgets.QKeySequenceEdit) and key is not None and mods:
                    QtCore.QTimer.singleShot(0, lambda ed=ed, k=QtCore.QKeyCombination(mods, key): self._key_fallback(ed, k))
        elif t == QtCore.QEvent.InputMethod and ev.commitString() + ev.preeditString():
            log.info("키 칸 입력기 글자 %r → 무시", ev.commitString() + ev.preeditString())
            self.warn.setText(T("한글 입력 상태라 키를 읽지 못했습니다. 한/영 키로 영어로 바꾼 뒤 다시 누르세요."))
            return True
        return super().eventFilter(obj, ev)

    def _key_fallback(self, ed, comb):
        """Qt 키 칸이 못 받은 조합을 직접 넣음 (비어 있을 때만)"""
        log.info("키 칸 처리 뒤 %r (빈칸이면 직접 넣음 %s)", ed.keySequence().toString(QtGui.QKeySequence.PortableText),
                 QtGui.QKeySequence(comb).toString(QtGui.QKeySequence.PortableText))
        if ed.keySequence().isEmpty():
            ed.setKeySequence(QtGui.QKeySequence(comb))
            log.info("키 칸 직접 넣음 %s", ed.keySequence().toString(QtGui.QKeySequence.PortableText))
            ed.clearFocus()

    def _key_set(self, e, a):
        """키 칸에 새 키 → 다른 기능에 있던 같은 키는 비우고(새로 넣은 쪽만 남김) 양쪽 기능 칸에 빨갛게 알림 (v0.9.86)"""
        if self._busy:
            return
        k = norm(e.keySequence().toString(QtGui.QKeySequence.PortableText))
        if k:
            for o, eds in self.edits.items():
                for x in eds:
                    if x is not e and norm(x.keySequence().toString(QtGui.QKeySequence.PortableText)) == k:
                        x.blockSignals(True)
                        x.clear()
                        x.blockSignals(False)
                        self._kmv.append((k, o, a))
                        log.info("단축키 %s : %s → %s 로 옮김", k, o, a)
        self.warn.clear()
        self._key_notes()
        self._changed()

    def _key_notes(self):
        """키보드 기능 칸 알림 (빨강): 옮겨 온 키 '…에서 옮김' · 빼앗긴 쪽 '…로 옮겨짐' · (예전 설정에 남은) 겹침"""
        km = self.collect()
        notes = {}
        for k, src, dst in self._kmv:
            if k in km.get(dst, []):   # 아직 그대로일 때만
                notes.setdefault(dst, []).append(T("{0}: '{1}'에서 옮김").format(k, LABEL[src]))
                if k not in km.get(src, []):
                    notes.setdefault(src, []).append(T("{0}: '{1}'(으)로 옮겨짐").format(k, LABEL[dst]))
        for k, acts in conflicts(km):
            for a in acts:
                notes.setdefault(a, []).append(T("{0}: '{1}'와 겹침").format(k, ", ".join(LABEL[o] for o in acts if o != a)))
        for r, (a, *_x) in enumerate(ACTIONS):
            _mark(self.tbl.item(r, 0), self.kbase[a], list(dict.fromkeys(notes.get(a, []))))
            for e in self.edits[a]:   # Qt 기본 'Press shortcut' 대신 — 키를 바꾸거나 지울 때마다 Qt 가 영어로 되돌려서 매번 (실측)
                le = e.findChild(QtWidgets.QLineEdit)
                if le is not None and le.placeholderText() != T("키를 누르세요"):
                    le.setPlaceholderText(T("키를 누르세요"))

    # ---------------------------------------------------------- 마우스
    def _mouse_set(self, e):
        """마우스 칸에 새 조합 → 다른 기능에 있던 같은 조합은 빼고 양쪽에 알림 (막지 않음)"""
        c = e.combo
        a_new = next(a for a, eds in self.medits.items() if e in eds)
        if c:
            for a, eds in self.medits.items():
                for o in eds:
                    if o is not e and o.combo == c:
                        o.set_combo("")
                        self._mmv.append((c, a, a_new))
                        log.info("마우스 %s : %s → %s 로 옮김", c, a, a_new)
        self.warn.clear()
        self._mouse_notes()
        self._changed()

    def _mouse_notes(self):
        """기능 칸: 옮겨 온 조합·빼앗긴 쪽·원래 쓰임을 바꾼 조합(여러 개 고르기 등)을 빨갛게"""
        now = {a: [e.combo for e in eds if e.combo] for a, eds in self.medits.items()}
        name = lambda a: self.mbase.get(a, a)
        notes = {}
        for c, src, dst in self._mmv:
            if c in now.get(dst, []):
                notes.setdefault(dst, []).append(T("{0}: '{1}'에서 옮김").format(combo_label(c), name(src)))
                if c not in now.get(src, []):
                    notes.setdefault(src, []).append(T("{0}: '{1}'(으)로 옮겨짐").format(combo_label(c), name(dst)))
        for a, cs in now.items():
            for c in cs:
                if builtin_use(c) and MOUSE_DEFAULT.get(c) != a and not any(m[0] == c and m[2] == a for m in self._mmv):
                    notes.setdefault(a, []).append(T("{0}: 원래 {1}").format(combo_label(c), builtin_use(c)))
        for r, a in enumerate(self.medits):
            _mark(self.mtbl.item(r, 0), self.mbase[a], list(dict.fromkeys(notes.get(a, []))))

    def mouse_collect(self):
        """설정에 넣을 것 — 기본과 다른 것만 ({조합: 기능}, 기본 조합을 뺐으면 "")"""
        now = {e.combo: a for a, eds in self.medits.items() for e in eds if e.combo}
        out = {c: a for c, a in now.items() if MOUSE_DEFAULT.get(c) != a}
        out.update({c: "" for c in MOUSE_DEFAULT if c not in now})
        return out

    def _filter(self, t):
        t = t.strip().lower()
        for r, (a, lbl, _d, _s) in enumerate(ACTIONS):
            keys = " ".join(e.keySequence().toString() for e in self.edits[a]).lower()
            self.tbl.setRowHidden(r, bool(t) and t not in lbl.lower() and t not in keys)

    def _defaults(self):
        self._busy = True   # 한꺼번에 바꿈 → 되돌리기 한 번에 전부
        try:
            for a, eds in self.edits.items():
                ks = split(DEFAULT[a])
                for i, e in enumerate(eds):
                    e.setKeySequence(QtGui.QKeySequence(ks[i]) if i < len(ks) else QtGui.QKeySequence())
            for a, eds in self.medits.items():
                cs = [c for c, x in MOUSE_DEFAULT.items() if x == a]
                for k, e in enumerate(eds):
                    e.set_combo(cs[k] if k < len(cs) else "")
            self._kmv, self._mmv = [], []
        finally:
            self._busy = False
        self._mouse_notes()
        self.warn.clear()
        self._key_notes()
        self._changed()

    def collect(self):
        return {a: [norm(e.keySequence().toString(QtGui.QKeySequence.PortableText)) for e in eds if not e.keySequence().isEmpty()]
                for a, eds in self.edits.items()}

    def _save(self):
        km = self.collect()
        bad = conflicts(km)
        if bad:
            self.tabs.setCurrentIndex(0)
            self.warn.setText(T("같은 키가 여러 기능에 걸려 있습니다: ") +
                              " / ".join(f"{k} = {', '.join(LABEL[a] for a in acts)}" for k, acts in bad))
            return
        # 기본과 다른 것만 저장
        self.result_keys = {a: "; ".join(ks) for a, ks in km.items() if ks != split(DEFAULT[a])}
        self.result_mouse = self.mouse_collect()
        self.accept()


class MouseEdit(QtWidgets.QWidget):
    """마우스 칸 하나 (v0.9.84): 클릭 → '버튼을 누르세요' → 다음에 누른 버튼+수정키를 기록. ✕ = 지우기, Esc = 취소"""
    changed = QtCore.Signal()

    def __init__(self, dlg):
        super().__init__()
        self.dlg, self.combo, self.listening = dlg, "", False
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(2, 0, 2, 0)
        h.setSpacing(2)
        self.lab = QtWidgets.QLabel()
        self.lab.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.clr = QtWidgets.QToolButton()
        self.clr.setText("✕")
        self.clr.setAutoRaise(True)
        self.clr.clicked.connect(lambda: (self.set_combo(""), self.changed.emit()))
        h.addWidget(self.lab, 1)
        h.addWidget(self.clr)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.PreventContextMenu)   # 오른쪽 버튼도 지정할 수 있게
        self._show()

    def set_combo(self, c):
        self.combo, self.listening = c, False
        self._show()

    def _show(self):
        self.lab.setText(T("버튼을 누르세요…") if self.listening else combo_label(self.combo) if self.combo else "")
        self.lab.setStyleSheet("color:#1565c0;" if self.listening else "")
        self.clr.setVisible(bool(self.combo) and not self.listening)

    def mousePressEvent(self, ev):
        if not self.listening:
            if ev.button() == Qt.LeftButton:
                self.listening = True
                self.setFocus()
                self._show()
            return
        c = mouse_combo(ev.button(), ev.modifiers())
        if not c:
            return
        if c in FIXED:
            self.dlg.warn.setText(T("그냥 왼쪽 클릭은 지정할 수 없습니다 (고르기·열기·끌기에 씀) — 다른 버튼이나 Ctrl·Shift·Alt 와 같이 누르세요"))
            return
        self.set_combo(c)
        self.changed.emit()

    def mouseDoubleClickEvent(self, ev):
        self.mousePressEvent(ev)

    def keyPressEvent(self, ev):
        if self.listening and ev.key() == Qt.Key_Escape:
            self.listening = False
            self._show()
            return
        super().keyPressEvent(ev)

    def focusOutEvent(self, ev):
        if self.listening:
            self.listening = False
            self._show()
        super().focusOutEvent(ev)

