# -*- coding: utf-8 -*-
"""단축키 표 (기능 → 키). 기본값 + 사용자가 바꾼 것(설정 파일 "keys")을 합쳐 쓴다.
v0.9.83: 마우스 버튼 표 (설정 파일 "mouse" = {"Ctrl+middle": 기능, ...}, 기본 동작과 다른 것만) — 같은 설정 창의 '마우스' 탭

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
    ("toggle_preview", T("미리보기 창 보이기/숨기기"), "Alt+P", "window"),
    ("compare", T("두 칸 비교"), "Shift+F2", "window"),   # v0.9.89 (토탈 커맨더와 같은 키)
    ("palette", T("명령 찾기…"), "Ctrl+Shift+P", "window"),   # v0.9.89   # 탐색기와 같은 키 (v0.9.58)
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
    """키 입력 이벤트 → 정규화된 키 글자"""
    return norm(QtGui.QKeySequence(ev.keyCombination()).toString(QtGui.QKeySequence.PortableText))


def _mark(it, base, notes):
    """기능 칸: 겹침·옮김 알림이 있으면 이름 뒤에 붙이고 빨갛게 (v0.9.85 사용자: 알림 칸 따로 말고 기능 쪽에)"""
    it.setText(base + ("   ⚠ " + " / ".join(notes) if notes else ""))
    it.setToolTip(it.text() if notes else "")
    it.setForeground(QtGui.QColor("#c62828") if notes else QtGui.QBrush())
    it.setFlags(Qt.ItemIsEnabled)


# ================================================================ 설정 창
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

    # ---------------------------------------------------------- 키보드
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

