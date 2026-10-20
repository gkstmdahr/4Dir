# -*- coding: utf-8 -*-
"""4Dir 화면 부품: 줄바꿈 배치(FlowLayout), 앱 아이콘, 색상 테마·설정 파일"""
import os
import json
import logging
from i18n import T   # 화면 문구 번역

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

log = logging.getLogger("QE.ui")
BIN_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BIN_DIR, "4Dir_settings.json")


# ================================================================ 설정 (색상·즐겨찾기 바 펼침·항상 위) — 세션과 무관한 전역 설정
# 색: "#rrggbbaa" (aa = 알파, ff=불투명). (설명, 밝은 테마 기본, 어두운 테마 기본)
THEME_KEYS = {
    "win_bg":   (T("창 바탕 (칸 사이 간격)"), "#eef1f4ff", "#17191cff"),
    "top_bg":   (T("상단 메뉴·즐겨찾기 바"), "#fafbfcff", "#24272bff"),
    "head_bg":  (T("칸 머리줄 (주소줄)"), "#f6f8faff", "#26292eff"),
    "tab_row":  (T("탭 줄 바탕"), "#eaeef2ff", "#1f2226ff"),
    "tab":      (T("선택 안 된 탭"), "#dfe4eaff", "#2e3238ff"),
    "status":   (T("칸 아래 상태줄"), "#f6f8faff", "#26292eff"),
    "side_bg":  (T("탐색 창 (사이드바)"), "#fafbfcff", "#1e2023ff"),
    "accent":   (T("선택된 칸 테두리"), "#2f7de1ff", "#3d8bf0ff"),
    "border":   (T("칸 테두리"), "#c3cad2ff", "#3a3f46ff"),
    # 윈도우 11 기본 스타일의 선택색은 너무 옅어 안 보였음(10/2 사용자 지적) → 탐색기와 비슷한 하늘색, 다른 칸 선택도 보이게
    "sel":      (T("선택한 항목"), "#cce8ffff", "#2f5f9eff"),
    "sel_off":  (T("선택한 항목 (다른 칸)"), "#dde5eeff", "#3a4656ff"),
    "sel_border": (T("선택한 항목 테두리"), "#3f94dcff", "#6a9fe0ff"),
    "sel_border_off": (T("선택한 항목 테두리 (다른 칸)"), "#a7bbd0ff", "#5a6878ff"),
    "hover":    (T("마우스 올린 항목"), "#e5f3ffff", "#2c3138ff"),   # 밝게 = 윈도우 11 탐색기 마우스 올림 색
}
THEME_DEFAULT = {k: (v[0], v[1]) for k, v in THEME_KEYS.items()}          # (호환) 밝은 테마
THEME_DARK_DEFAULT = {k: (v[0], v[2]) for k, v in THEME_KEYS.items()}
# 색상 설정에 안 나오는 고정색 (테마별)
FIXED = {
    False: {"pane_bg": "#ffffff", "text": "#1f262e", "sub": "#56616d", "tab_text": "#2d3640", "tab_sel": "#ffffff",
            "tab_sel_text": "#000000", "tab_hover": "#f2f4f7", "notice_bg": "#fff3c4", "notice_fg": "#5a4500",
            "crumb_hover": "#e0e0e0", "crumb_press": "#cccccc"},
    True:  {"pane_bg": "#1e1f22", "text": "#dfe3e8", "sub": "#9aa4af", "tab_text": "#c4cad1", "tab_sel": "#1e1f22",
            "tab_sel_text": "#ffffff", "tab_hover": "#383d44", "notice_bg": "#4a3f12", "notice_fg": "#ffe9a6",
            "crumb_hover": "#3d4148", "crumb_press": "#4a4f57"},
}


class Settings:
    def __init__(self, path=SETTINGS_FILE):
        self.path = path
        self.data = {"theme": {k: v[1] for k, v in THEME_KEYS.items()},
                     "theme_dark": {k: v[2] for k, v in THEME_KEYS.items()},
                     "theme_mode": "system",  # 화면 테마: system(윈도우 설정 따름) / light / dark
                     "dark": False,          # 지금 실제로 어두운지 (theme_mode 로 계산됨)
                     "fav_expanded": True, "on_top": False,
                     "allow_multi": False,   # False = 창 하나만 (다시 실행하면 기존 창을 앞으로)
                     "sysmon": True,         # 상단에 CPU·GPU 사용량 표시
                     "breadcrumb": True,     # 주소를 경로 버튼으로 (기본: 경로 버튼, 빈 곳 클릭하면 입력칸)
                     "batch_rename": {},     # 이름 일괄 변경 창의 마지막 입력값
                     "guide_shown": False,   # 처음 실행 때 사용법 창을 보여줬는지
                     "update_check": True,   # 시작할 때 새 버전 확인 (하루 한 번, 버전 정보 파일만 읽음)
                     "update_last": "",      # 마지막으로 확인한 날 (YYYY-MM-DD)
                     "resume_after_reboot": True,   # 켜 둔 채 윈도우 종료·재부팅하면 다음 로그인 때 다시 열기 (10/12)
                     "keys": {},             # 바꾼 단축키만 {기능: "Ctrl+X; F7"} (keymap.py)
                     "search_roots": None,   # 검색 범위 [{path, on}] (None = 기본: 로컬 NTFS 드라이브)
                     "chrome_collapsed": False,   # 상단 메뉴줄+즐겨찾기 바 접음 (Ctrl+Shift+M)
                     "lang": None}           # 화면 언어 코드 (None = 윈도우 표시 언어 따름, i18n.py) — 다시 시작하면 적용
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                for tk in ("theme", "theme_dark"):
                    self.data[tk].update({k: v for k, v in d.get(tk, {}).items() if k in THEME_KEYS})
                if "theme_mode" not in d and d.get("dark"):   # 0.6.2 이전: 다크 모드 켜둔 사람은 '어둡게' 유지
                    self.data["theme_mode"] = "dark"
                for k in ("theme_mode", "dark", "fav_expanded", "on_top", "allow_multi", "sysmon", "breadcrumb", "keys", "search_roots", "lang", "chrome_collapsed", "batch_rename", "guide_shown", "update_check", "update_last", "resume_after_reboot"):
                    if k in d:
                        self.data[k] = d[k]
            except Exception:
                log.exception("설정 파일 깨짐 → 기본값")

    def theme_key(self):
        return "theme_dark" if self.data["dark"] else "theme"

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()


def css(c):
    """#rrggbbaa → rgba(r,g,b,a) (스타일시트용)"""
    q = qcolor(c)
    return f"rgba({q.red()},{q.green()},{q.blue()},{q.alpha()})"


def qcolor(c):
    c = c.lstrip("#")
    if len(c) == 8:
        return QtGui.QColor(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16))
    return QtGui.QColor("#" + c)


def hexa(q):
    return "#{:02x}{:02x}{:02x}{:02x}".format(q.red(), q.green(), q.blue(), q.alpha())


_ORIG = {}


def system_dark():
    """윈도우 설정 > 개인 설정 > 색 > '앱 모드'가 어둡게인지 (읽기만 함)"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def apply_palette(app, dark):
    """목록·입력칸·메뉴 등 기본 위젯 색. 다크 = Fusion 스타일 + 어두운 팔레트, 밝게 = 원래대로"""
    if "style" not in _ORIG:
        _ORIG["style"] = app.style().name()
        _ORIG["palette"] = QtGui.QPalette(app.palette())
    if not dark:
        app.setStyle(_ORIG["style"])
        app.setPalette(_ORIG["palette"])
        return
    app.setStyle("Fusion")
    P, C = QtGui.QPalette, QtGui.QColor
    p = P()
    for role, col in ((P.Window, "#26292e"), (P.WindowText, "#dfe3e8"), (P.Base, "#1e1f22"), (P.AlternateBase, "#25272b"),
                      (P.ToolTipBase, "#2e3238"), (P.ToolTipText, "#e6e6e6"), (P.Text, "#dfe3e8"), (P.Button, "#2e3238"),
                      (P.ButtonText, "#dfe3e8"), (P.BrightText, "#ffffff"), (P.Highlight, "#2f6fd0"),
                      (P.HighlightedText, "#ffffff"), (P.Link, "#6aa9ff"), (P.PlaceholderText, "#7d868f"), (P.Mid, "#3a3f46"),
                      (P.Dark, "#15171a"), (P.Light, "#3a3f46")):
        p.setColor(role, C(col))
    for role in (P.Text, P.WindowText, P.ButtonText):
        p.setColor(P.Disabled, role, C("#6b737c"))
    app.setPalette(p)


def build_style(t, dark=False):
    T = {k: css(v) for k, v in t.items()}
    F = FIXED[bool(dark)]
    return f"""
QMainWindow, #central {{ background:{T['win_bg']}; }}
#topBar {{ background:{T['top_bg']}; border:none; border-bottom:1px solid {T['border']}; spacing:2px; padding:1px 4px; }}
#favPanel {{ background:{T['top_bg']}; border-bottom:1px solid {T['border']}; }}
#favLabel {{ color:{F['sub']}; font-weight:bold; }}
#favPanel QToolButton {{ padding:1px 4px; }}
#notice {{ background:{F['notice_bg']}; border:1px solid #e0b84a; border-radius:3px; padding:2px 8px; color:{F['notice_fg']}; }}
#noticeAct {{ background:#1a73e8; color:white; border:none; border-radius:3px; padding:3px 12px; font-weight:bold; }}
#noticeAct:hover {{ background:#1765cc; }}
#pane {{ background:{F['pane_bg']}; border:1px solid {T['border']}; }}
#pane[active="true"] {{ border:2px solid {T['accent']}; }}
#paneHead {{ background:{T['head_bg']}; border-bottom:1px solid {T['border']}; }}
#tabRow {{ background:{T['tab_row']}; border-bottom:1px solid {T['border']}; }}
QTabBar::tab {{ background:{T['tab']}; color:{F['tab_text']}; border:1px solid {T['border']}; border-bottom:none;
               padding:3px 8px; margin-right:2px; border-top-left-radius:4px; border-top-right-radius:4px; min-width:60px; }}
QTabBar::tab:selected {{ background:{F['tab_sel']}; color:{F['tab_sel_text']}; font-weight:bold; }}
QTabBar::tab:hover:!selected {{ background:{F['tab_hover']}; }}
#plusTab {{ font-weight:bold; font-size:20px; padding:0 0 2px 0; border-radius:4px; }}
#plusTab:hover {{ background:{F['tab_sel']}; }}
#paneStatus {{ background:{T['status']}; border-top:1px solid {T['border']}; color:{F['sub']}; padding:2px 6px; }}
#sidebar {{ background:{T['side_bg']}; border:none; border-right:1px solid {T['border']}; }}
#topBar QToolButton:hover:!checked, #paneHead QToolButton:hover:!checked, #favPanel QToolButton:hover:!checked {{
    background:{F['crumb_hover']}; border:1px solid transparent; border-radius:4px; }}   /* 마우스 올리면 회색 (10/8 사용자: 눈에 안 띔) */
#topBar QToolButton:pressed, #paneHead QToolButton:pressed, #favPanel QToolButton:pressed {{
    background:{F['crumb_press']}; border:1px solid transparent; border-radius:4px; }}
#crumbs {{ background:{F['pane_bg']}; border:1px solid {T['border']}; border-radius:2px; }}
#crumbs QToolButton {{ padding:0 4px; border:none; border-radius:3px; background:transparent; }}
#crumbs QToolButton:hover {{ background:{F['crumb_hover']}; }}   /* 윈도우 탐색기처럼 마우스 올리면 회색 */
#crumbs QToolButton:pressed {{ background:{F['crumb_press']}; }}
QTreeView::item:hover, QListView::item:hover {{ background:{T['hover']}; }}
QTreeView::item:selected, QListView::item:selected {{ background:{T['sel_off']}; color:{F['text']}; }}
#pane[active="true"] QTreeView::item:selected, #pane[active="true"] QListView::item:selected {{ background:{T['sel']}; color:{F['text']}; }}
QListView::item:selected {{ border:1px solid {T['sel_border_off']}; }}
#pane[active="true"] QListView::item:selected {{ border:1px solid {T['sel_border']}; }}
QSplitter::handle {{ background:{T['win_bg']}; }}
QSplitter::handle:hover {{ background:#8fb3e6; }}
"""


# ================================================================ 줄바꿈 배치 (Qt 예제 FlowLayout 이식)
class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None, spacing=2):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QtCore.QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QtCore.QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def row_height(self):
        return max((it.sizeHint().height() for it in self.items), default=22)

    def _do(self, r, test):
        x, y, line = r.x(), r.y(), 0
        sp = self.spacing()
        for it in self.items:
            if it.widget() is not None and not it.widget().isVisibleTo(it.widget().parentWidget()):
                continue
            sh = it.sizeHint()
            nx = x + sh.width() + sp
            if nx - sp > r.right() and line > 0:
                x, y = r.x(), y + line + sp
                nx = x + sh.width() + sp
                line = 0
            if not test:
                it.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), sh))
            x = nx
            line = max(line, sh.height())
        return y + line - r.y()


# ================================================================ 앱 아이콘 (4분할 창 — 코드로 그림)
def app_icon():
    icon = QtGui.QIcon()
    for s in (16, 20, 24, 32, 48, 64, 128, 256):
        pm = QtGui.QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        m = max(1, s // 16)
        rad = max(2, s // 8)
        outer = QtCore.QRectF(m, m, s - 2 * m, s - 2 * m)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#24425f"))
        p.drawRoundedRect(outer, rad, rad)
        g = max(1, s // 16)           # 칸 사이 간격
        inner = outer.adjusted(g * 1.5, g * 1.5, -g * 1.5, -g * 1.5)
        cw, ch = (inner.width() - g) / 2, (inner.height() - g) / 2
        cols = ["#ffc845", "#4fa3f7", "#5ccf8a", "#f27c6b"]   # 폴더 노랑 + 파랑·초록·주황
        for i in range(4):
            cx = inner.x() + (i % 2) * (cw + g)
            cy = inner.y() + (i // 2) * (ch + g)
            p.setBrush(QtGui.QColor(cols[i]))
            p.drawRoundedRect(QtCore.QRectF(cx, cy, cw, ch), rad / 2, rad / 2)
            if s >= 24:  # 칸 위쪽 '탭' 줄 느낌
                p.setBrush(QtGui.QColor(255, 255, 255, 110))
                p.drawRect(QtCore.QRectF(cx, cy, cw, max(1.5, ch * 0.22)))
        p.end()
        icon.addPixmap(pm)
    return icon
