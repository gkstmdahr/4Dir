# -*- coding: utf-8 -*-
"""4Dir 화면 문구 번역 (언어 파일 방식)

- 원문 = 코드 안의 한국어 문구. T("한국어") → 지금 언어의 번역 (없으면 영어 → 그래도 없으면 한국어 그대로)
- 언어 파일: bin\\lang\\<코드>.json  {"한국어 원문": "번역", ...}  — 메모장으로 고치거나 새 언어 추가 가능
- 언어 선택: 4Dir_settings.json 의 "lang" (없으면 윈도우 표시 언어). 다시 시작하면 적용
- 형식 문자열은 {0} {1} 자리표시를 그대로 둬야 함 (T("{0}개 찾음").format(n))
"""
import os
import json
import ctypes
import logging

log = logging.getLogger("QE.i18n")
BIN_DIR = os.path.dirname(os.path.abspath(__file__))
LANG_DIR = os.path.join(BIN_DIR, "lang")
from datadir import DATA_DIR  # 0.9.114 스토어판이면 사용자 폴더
SETTINGS_FILE = os.path.join(DATA_DIR, "4Dir_settings.json")
# 0.9.152 (사용자 11/26 '유저가 언어 팩 고치기'): 사용자 번역 폴더 — 같은 이름 파일이 있으면 그 문구만 덮어씀.
#   압축판 = bin\lang_user (배포판·공개 소스에 안 들어감, 업데이트해도 남음) · 스토어판 = %LOCALAPPDATA%\4Dir\lang_user
USER_LANG_DIR = os.path.join(DATA_DIR, "lang_user")

# (코드, 그 언어로 쓴 이름) — 메뉴에 이 순서로 나옴
LANGS = [("ko", "한국어"), ("en", "English"), ("zh_CN", "简体中文"), ("zh_TW", "繁體中文"), ("ja", "日本語"),
         ("es", "Español"), ("de", "Deutsch"), ("fr", "Français"), ("pt_BR", "Português (Brasil)"), ("ru", "Русский"),
         # 0.9.137 빌드 9: 6개 언어 추가 (사용자 11/13 확정)
         ("it", "Italiano"), ("pl", "Polski"), ("nl", "Nederlands"), ("tr", "Türkçe"), ("uk", "Українська"), ("id", "Bahasa Indonesia"),
         # 0.9.152: 10개 언어 추가 (사용자 11/26)
         ("cs", "Čeština"), ("hu", "Magyar"), ("el", "Ελληνικά"), ("ro", "Română"), ("sv", "Svenska"), ("da", "Dansk"),
         ("fi", "Suomi"), ("nb", "Norsk (bokmål)"), ("vi", "Tiếng Việt"), ("th", "ไทย")]
# 언어별 화면 글꼴 (윈도우 기본 탑재)
FONTS = {"ko": "Malgun Gothic", "ja": "Yu Gothic UI", "zh_CN": "Microsoft YaHei UI", "zh_TW": "Microsoft JhengHei UI", "th": "Leelawadee UI"}
DEFAULT_FONT = "Segoe UI"

lang = "ko"
_tr = {}
_en = {}


def windows_lang():
    """윈도우 표시 언어 → 우리 언어 코드 (목록에 없으면 en)"""
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except Exception:
        return "en"
    prim, sub = lid & 0x3FF, lid >> 10
    if prim == 0x04:   # 중국어: 대만(1)·홍콩(3)·마카오(5) = 번체, 나머지 = 간체
        return "zh_TW" if sub in (1, 3, 5) else "zh_CN"
    return {0x12: "ko", 0x09: "en", 0x11: "ja", 0x0A: "es", 0x07: "de", 0x0C: "fr", 0x16: "pt_BR",
            0x19: "ru", 0x10: "it", 0x15: "pl", 0x13: "nl", 0x1F: "tr", 0x22: "uk", 0x21: "id",
            0x05: "cs", 0x0E: "hu", 0x08: "el", 0x18: "ro", 0x1D: "sv", 0x06: "da", 0x0B: "fi", 0x14: "nb", 0x2A: "vi", 0x1E: "th"}.get(prim, "en")


def chosen_setting():
    """설정 파일에 고른 언어 (None = 윈도우 따름)"""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            v = json.load(f).get("lang")
        return v if v in dict(LANGS) else None
    except Exception:
        return None


def _read(p):
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8-sig") as f:   # 메모장이 BOM 을 붙여도 읽게
            d = json.load(f)
        return {k: v for k, v in d.items() if isinstance(v, str) and v and not k.startswith("_")}
    except Exception:
        log.exception("언어 파일 읽기 실패 %s", p)
        return {}


def _load(code):
    d = _read(os.path.join(LANG_DIR, code + ".json"))
    u = _read(os.path.join(USER_LANG_DIR, code + ".json"))   # 0.9.152: 사용자가 고친 번역이 이김
    if u:
        n = sum(1 for k, v in u.items() if d.get(k) != v)
        d.update(u)
        log.info("사용자 번역 %s: %d개 중 %d개가 기본과 다름", os.path.join(USER_LANG_DIR, code + ".json"), len(u), n)
    return d


def init(code=None):
    global lang, _tr, _en
    lang = code or chosen_setting() or windows_lang()
    _tr = {} if lang == "ko" else _load(lang)
    _en = {} if lang in ("ko", "en") else _load("en")
    log.info("언어 %s (설정=%s, 윈도우=%s) 번역 %d개", lang, chosen_setting(), windows_lang(), len(_tr))


def T(s):
    if lang == "ko":
        return s
    return _tr.get(s) or _en.get(s) or s


def font_family():
    return FONTS.get(lang, DEFAULT_FONT)


def font_families():
    """글꼴. 한국어 = 맑은 고딕 하나 — 윈도우 탐색기 목록과 같은 글꼴(윈도우 아이콘 글꼴 = 맑은 고딕 -12px).
    10/6 실측: 맑은 고딕 9pt 를 Qt 기본 방식으로 그리면 탐색기와 픽셀 단위로 같음(글자 줄별 어두운 점 [2,9,7,92,56,44,62,45,47,76,4,25,5]).
    한때 Segoe UI 로 바꿨다가(v0.9.27) 소문자가 1px 낮아져 '납작'해 보인다는 지적 → 되돌림."""
    return [font_family()]


# 윈도우가 종류별(목록·머리줄·메뉴 등)로 따로 정해 주는 글꼴까지 덮어써야 함
# (한국어 윈도우에서 일본어로 띄우면 목록만 맑은 고딕으로 남아 가나가 벌어져 보였음 — 10/2 실측)
FONT_CLASSES = ("QAbstractItemView", "QTreeView", "QListView", "QHeaderView", "QMenu", "QMenuBar", "QToolTip",
                "QTabBar", "QToolButton", "QPushButton", "QLineEdit", "QComboBox", "QLabel", "QMessageBox")


_BASE_PT = {}   # 0.9.133: 종류별 윈도우 기본 글자 크기 (처음 한 번 기억 — 크기 % 를 여러 번 바꿔도 누적 안 되게)


def base_pt():
    """윈도우 기본 글자 크기(pt) — 설정 '글자 크기' 의 기본값 (한국어 윈도우 9)"""
    if None not in _BASE_PT:
        from PySide6.QtWidgets import QApplication
        f = QApplication.font()
        _BASE_PT[None] = f.pointSizeF() if f.pointSizeF() > 0 else 9.0
    return _BASE_PT[None]


def apply_font(app, family=None, pt=0):
    """family = 사용자가 고른 글꼴(빈칸 = 언어별 기본), pt = 글자 크기(0 = 윈도우 기본) (0.9.133 설정 > 일반).
    목록·메뉴 등 종류별 크기는 기본 크기와 같은 비율로"""
    from PySide6.QtWidgets import QApplication
    fams = [family] if family else font_families()
    b = base_pt()   # 처음 한 번 윈도우 기본 크기 기억 (빌드 2: pt=0 일 때 안 불려 KeyError — qe269 로 잡음)
    k = max(5.0, min(36.0, float(pt))) / b if pt else 1.0
    f = QApplication.font()
    f.setFamilies(fams)
    f.setPointSizeF(_BASE_PT[None] * k)
    QApplication.setFont(f)
    for c in FONT_CLASSES:
        cf = QApplication.font(c)
        if c not in _BASE_PT:
            _BASE_PT[c] = cf.pointSizeF() if cf.pointSizeF() > 0 else _BASE_PT[None]
        cf.setFamilies(fams)
        cf.setPointSizeF(_BASE_PT[c] * k)
        QApplication.setFont(cf, c)
    log.info("글꼴 적용 %s · 크기 %.1fpt (기본 %.1fpt)", fams, _BASE_PT[None] * k, _BASE_PT[None])


init()
