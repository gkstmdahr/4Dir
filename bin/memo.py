# -*- coding: utf-8 -*-
"""메모 창 (MEMO_VER 2.1.0, v0.9.108 사용자 11/5: 사내 galleryV8 메모가 반응 좋음 → 아이디어 참고해 새로 만듦)

- 4Dir 창 밖 따로 창(main.MemoWindow), 모든 창이 같은 메모, 자동 저장 bin\\4Dir_memos.json, 그림은 bin\\memo_images\\
- 윗줄: ＋ 새 메모 · 검색칸(한글 상태로 친 영문도 찾음) · 색 거르기 · 📌 항상 위 · ⚙ (글꼴·지운 메모·체크 방식 등)
- 아랫줄 서식: − 크기 + | 굵게·기울임·밑줄·취소선·글자 색 | 체크박스·글머리·번호 | 정렬·자간 | 표·그림 (모자라면 ⋮)
- 메모지: 제목 줄 = 제목(길면 …, 전체는 풍선) · 📌고정 · 📁폴더 · ⏰알림 · 체크 진행(3/5) · 고친 시각 · ⋯ 메뉴
  제목 줄 빈 곳을 끌어 순서 바꾸기, 두 번 눌러 접기/펴기, 아래 손잡이로 높이
- 본문: 체크박스(누르면 ✔, 설정에 따라 취소선+회색), 글머리, 번호, 표, 그림, 링크(파랑, Ctrl+클릭으로 열기),
  줄 앞 '[] ' / '- ' / '1. ' 자동 변환, 파일·폴더를 끌어 넣으면 링크
- 2.0.0 (빌드 13): 링크·끌어 넣기·폴더 메모·자동 변환·접기·고정·진행 표시·알림·색 거르기·휴지통·그림
- 2.1.0 (빌드 14, 사용자 11/5): − 크기 + · 표 · 정렬 · 자간 · 글꼴 · 그림 단추 · 큰 아이콘 · 색 거르기 단추 · 링크 파랑 ·
  '1. ' 번호 · 체크 표시 ✔(직접 그림) · 체크 때 취소선·회색 끄기(⚙) · 회색 진하게 · 한글 상태 검색
- 2.2.0 (빌드 15, 사용자 11/5 구글 시트 도구 줄 참고): 두 줄로 정리 — 윗줄 ＋ · 검색 · 색 · 📌 · ⚙,
  아랫줄 서식(무리별 구분선, 자리가 모자라면 ⋮ 안으로). 글꼴은 ⚙ ▸ 글꼴
- 2.3.0 (빌드 16, 사용자 11/5): 체크박스가 여러 번 눌러야 되던 것 — Qt 도 체크 표시 위에서 손을 떼면 스스로 뒤집어
  (마우스가 먼저 지나가 있으면) 내 처리와 두 번 뒤집혀 그대로였음(재현) → 그 놓기·두 번 누르기를 먹음.
  GIF 움직임(QMovie), 그림은 메모 폭에 맞춰 늘고 줄며 부드럽게 줄여 그림, 우클릭 그림 크기(크게·중간·작게)
로그: bin\\log\\4Dir.log  [QE.memo]
"""
import os
import re
import json
import time
import logging

from i18n import T
import labels
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

MEMO_VER = "2.4.0"   # 2.4.0 (빌드 18 사용자 11/5): 그림 크기 자동 맞춤 없앰 — 넣을 때 한 번 정하고, 누르면 손잡이로 직접 조절
log = logging.getLogger("QE.memo")
FILE = "4Dir_memos.json"
IMG_DIR = "memo_images"
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
IMG_SIZES = [("원래 크기", "nat"), ("메모 폭에 맞추기", "fit"), ("50%", 0.5), ("25%", 0.25)]   # 빌드 18 — 누를 때 한 번만 적용 (이름은 쓸 때 T())
COLORS = [k for k, _l, _s in labels.TAB_COLORS]
DEFAULT_COLOR = "yellow" if "yellow" in COLORS else COLORS[0]
TEXT_COLORS = [("#222222", "검정"), ("#d93025", "빨강"), ("#e8710a", "주황"), ("#188038", "초록"),
               ("#1a73e8", "파랑"), ("#8430ce", "보라"), ("#c5221f", "진한 빨강"), ("#80868b", "회색")]
SIZES = [7, 8, 9, 9.5, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36]   # pt
BASE_SIZE = 9.5
MIN_H, DEF_H = 70, 170
TRASH_MAX = 50
LINK_COLOR = "#1a73e8"
DONE_GRAY = "#5f6368"        # 빌드 14 사용자: 체크한 글자가 너무 흐림 → 진하게 (전 #9aa0a6)
DONE_GRAY_DARK = "#a9aeb4"
CHECK_GREEN = "#188038"
SPACINGS = [("좁게", 92), ("보통", 100), ("넓게", 110), ("아주 넓게", 125)]   # 이름은 쓸 때 T()
ICON = 22                    # 빌드 14 사용자: 아이콘이 작음 (전 18)
BTN = 30
M_NONE = QtGui.QTextBlockFormat.MarkerType.NoMarker
M_OFF = QtGui.QTextBlockFormat.MarkerType.Unchecked
M_ON = QtGui.QTextBlockFormat.MarkerType.Checked
LINK_RE = re.compile(r'(https?://[^\s<>"]+|file:///[^\s<>"]+|[A-Za-z]:\\[^<>"|?*\r\n]*[^<>"|?*\r\n\s.,)]|\\\\[^\\\s<>"|?*]+\\[^<>"|?*\r\n]*[^<>"|?*\r\n\s.,)])')

# ---- 한글 상태로 친 영문 → 영문 (두벌식 자판 자리) — 검색용
_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ",
         "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
_KEY = dict(zip("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎㅏㅐㅑㅒㅓㅔㅕㅖㅗㅛㅜㅠㅡㅣ",
                "rRseEfaqQtTdwWczxvgkoiOjpuPhynbml"))
_KEY.update({"ㅘ": "hk", "ㅙ": "ho", "ㅚ": "hl", "ㅝ": "nj", "ㅞ": "np", "ㅟ": "nl", "ㅢ": "ml", "ㄳ": "rt", "ㄵ": "sw",
             "ㄶ": "sg", "ㄺ": "fr", "ㄻ": "fa", "ㄼ": "fq", "ㄽ": "ft", "ㄾ": "fx", "ㄿ": "fv", "ㅀ": "fg", "ㅄ": "qt"})


def ko_keys(s):
    """'ㅁㄴㅇㄹ' → 'asdf', '머메' → 'ajap' (한글 상태로 영문을 친 경우)"""
    out = []
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3:
            o -= 0xAC00
            out.append(_KEY[_CHO[o // 588]] + _KEY[_JUNG[(o % 588) // 28]] + (_KEY[_JONG[o % 28]] if o % 28 else ""))
        else:
            out.append(_KEY.get(ch, ch))
    return "".join(out)


def has_hangul(s):
    return any(0xAC00 <= ord(c) <= 0xD7A3 or 0x3131 <= ord(c) <= 0x318E for c in s)


def _mix(a, b, t):
    return labels._mix(a, b, t)


def paper(color, dark):
    """메모지 본문 색 · 제목 줄 색 · 글자 색"""
    h = labels.tab_hex(color) or "#f2c94c"
    if dark:
        return _mix(h, "#1e1f22", 0.70), _mix(h, "#1e1f22", 0.50), "#e8e6e1"
    return _mix(h, "#ffffff", 0.80), _mix(h, "#ffffff", 0.58), "#222222"


def size_text(v):
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


# ---------------------------------------------------------------- 아이콘 (그려서 — 빌드 13·14 사용자: 명확하게, 크게)
def fmt_icon(kind, fg="#3a4652", accent="#d93025", sz=20):
    dpr = 2
    pm = QtGui.QPixmap(sz * dpr, sz * dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
    p.scale(dpr, dpr)
    s = sz / 20.0
    col = QtGui.QColor(fg)
    P = QtCore.QPointF

    def letter(ch, bold=False, italic=False, size=14, y=15.5, x=None, family="Segoe UI"):
        ff = QtGui.QFont(family)
        ff.setPixelSize(max(1, int(size * s)))
        ff.setBold(bold)
        ff.setItalic(italic)
        p.setFont(ff)
        p.setPen(col)
        w = QtGui.QFontMetricsF(ff).horizontalAdvance(ch)
        p.drawText(P((x if x is not None else (sz - w) / 2), y * s), ch)

    def pen(w=1.4, c=None):
        p.setPen(QtGui.QPen(c or col, w * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def hline(x0, x1, y, w=1.4):
        pen(w)
        p.drawLine(P(x0 * s, y * s), P(x1 * s, y * s))
    if kind == "bold":
        letter("B", bold=True)
    elif kind == "italic":
        letter("I", italic=True, size=16, family="Times New Roman")
    elif kind == "underline":
        letter("U", size=13, y=13.5)
        hline(5, 15, 17)
    elif kind == "strike":
        letter("S", size=14)
        hline(3.5, 16.5, 10.5)
    elif kind == "check":   # 네모 + 그 안에 체크 (겹치지 않게)
        pen(1.4)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(3 * s, 3 * s, 14 * s, 14 * s), 2.5 * s, 2.5 * s)
        pen(2.0, QtGui.QColor(CHECK_GREEN))
        p.drawPolyline([P(6 * s, 10.2 * s), P(8.8 * s, 13 * s), P(14 * s, 7 * s)])
    elif kind == "bullet":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        for y in (5, 10, 15):
            p.drawEllipse(P(4.5 * s, y * s), 1.6 * s, 1.6 * s)
        for y in (5, 10, 15):
            hline(8, 17, y)
    elif kind == "number":
        for i, y in enumerate((6.5, 11.5, 16.5)):
            letter(str(i + 1), size=6.5, y=y + 1.7, x=2 * s)
        for y in (5, 10, 15):
            hline(8, 17, y)
    elif kind == "color":   # 구글 시트처럼 A + 그 아래 지금 색 막대
        letter("A", bold=True, size=13, y=12.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(accent))
        p.drawRect(QtCore.QRectF(3 * s, 14.5 * s, 14 * s, 3.5 * s))
    elif kind in ("align_left", "align_center", "align_right"):
        for y, ln in ((4, 14), (8, 9), (12, 14), (16, 9)):
            x0 = 3 if kind == "align_left" else (3 + (14 - ln) / 2 if kind == "align_center" else 17 - ln)
            hline(x0, x0 + ln, y)
    elif kind == "spacing":   # A ↔ A
        letter("A", size=10, y=10, x=1.5 * s)
        letter("A", size=10, y=10, x=11.5 * s)
        pen(1.3)
        p.drawLine(P(3 * s, 15 * s), P(17 * s, 15 * s))
        p.drawPolyline([P(5.5 * s, 13 * s), P(3 * s, 15 * s), P(5.5 * s, 17 * s)])
        p.drawPolyline([P(14.5 * s, 13 * s), P(17 * s, 15 * s), P(14.5 * s, 17 * s)])
    elif kind == "table":
        pen(1.3)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(2.5 * s, 3.5 * s, 15 * s, 13 * s), 1.5 * s, 1.5 * s)
        p.drawLine(P(2.5 * s, 8 * s), P(17.5 * s, 8 * s))
        p.drawLine(P(2.5 * s, 12.3 * s), P(17.5 * s, 12.3 * s))
        p.drawLine(P(7.5 * s, 3.5 * s), P(7.5 * s, 16.5 * s))
        p.drawLine(P(12.5 * s, 3.5 * s), P(12.5 * s, 16.5 * s))
    elif kind == "image":
        pen(1.3)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(2.5 * s, 3.5 * s, 15 * s, 13 * s), 1.5 * s, 1.5 * s)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#e8a400"))
        p.drawEllipse(P(7 * s, 7.5 * s), 1.6 * s, 1.6 * s)
        p.setBrush(QtGui.QColor(CHECK_GREEN))
        p.drawPolygon(QtGui.QPolygonF([P(3.5 * s, 15.5 * s), P(8.5 * s, 10 * s), P(11 * s, 12.5 * s), P(13 * s, 10.5 * s), P(16.5 * s, 15.5 * s)]))
    elif kind == "filter":   # 색 거르기: 색 점 넷 (accent 가 있으면 그 색 하나)
        p.setPen(Qt.NoPen)
        if accent:
            p.setBrush(QtGui.QColor(accent))
            p.drawRoundedRect(QtCore.QRectF(3 * s, 3 * s, 14 * s, 14 * s), 3 * s, 3 * s)
        else:
            for (x, y), c in zip(((6, 6), (14, 6), (6, 14), (14, 14)), ("#f2c94c", "#eb5757", "#2f80ed", "#27ae60")):
                p.setBrush(QtGui.QColor(c))
                p.drawEllipse(P(x * s, y * s), 3.4 * s, 3.4 * s)
    elif kind == "more":   # ⋮
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        for y in (4.5, 10, 15.5):
            p.drawEllipse(P(10 * s, y * s), 1.7 * s, 1.7 * s)
    elif kind == "plus":
        pen(2.4)
        p.drawLine(P(10 * s, 4 * s), P(10 * s, 16 * s))
        p.drawLine(P(4 * s, 10 * s), P(16 * s, 10 * s))
    elif kind == "minus":
        pen(1.8)
        p.drawLine(P(5 * s, 10 * s), P(15 * s, 10 * s))
    elif kind == "plus_small":
        pen(1.8)
        p.drawLine(P(10 * s, 5 * s), P(10 * s, 15 * s))
        p.drawLine(P(5 * s, 10 * s), P(15 * s, 10 * s))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QtGui.QIcon(pm)


# ---------------------------------------------------------------- 저장
class MemoStore(QtCore.QObject):
    """메모 목록 (프로그램에 하나) — 바뀌면 0.6초 뒤 파일에 저장, changed(보낸 패널)로 다시 그림.
    알림 시각이 된 메모는 remind(메모) — 알림 있는 메모가 있을 때만 30초마다 확인(없으면 타이머 멈춤)"""
    changed = QtCore.Signal(object)
    remind = QtCore.Signal(dict)

    def __init__(self, bin_dir):
        super().__init__()
        self.path = os.path.join(bin_dir, FILE)
        self.img_dir = os.path.join(bin_dir, IMG_DIR)
        self.memos, self.trash, self.prefs = [], [], {}
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self.memos, self.trash, self.prefs = d.get("memos", []), d.get("trash", []), d.get("prefs", {})
        except FileNotFoundError:
            pass
        except Exception:
            log.exception("메모 파일 읽기 실패 %s", self.path)
        self.prefs.setdefault("done_strike", True)   # 체크하면 취소선+회색 (⚙ 에서 끔)
        self._t = QtCore.QTimer(self)
        self._t.setSingleShot(True)
        self._t.setInterval(600)
        self._t.timeout.connect(self.save_now)
        self._rt = QtCore.QTimer(self)
        self._rt.setInterval(30000)
        self._rt.timeout.connect(self.check_reminders)
        self.arm_reminders()
        log.info("메모 %d장 · 휴지통 %d장 불러옴 (%s) 설정 %s", len(self.memos), len(self.trash), self.path, self.prefs)

    def touch(self, origin=None, structure=False):
        self._t.start()
        if structure:
            self.changed.emit(origin)

    def save_now(self):
        self._t.stop()
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"ver": MEMO_VER, "memos": self.memos, "trash": self.trash[-TRASH_MAX:], "prefs": self.prefs},
                          f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            log.exception("메모 저장 실패 %s", self.path)

    def add(self, origin=None):
        n = {"id": f"m{int(time.time() * 1000)}", "t": time.time(), "title": time.strftime("%m/%d"),
             "color": DEFAULT_COLOR, "html": "", "h": DEF_H, "fs": BASE_SIZE}
        at = sum(1 for m in self.memos if m.get("pin"))   # 고정한 메모 다음
        self.memos.insert(at, n)
        log.info("메모 추가 %s", n["id"])
        self.touch(origin, structure=True)
        return n

    def remove(self, mid, origin=None):
        m = self.get(mid)
        if m is None:
            return
        self.memos = [x for x in self.memos if x["id"] != mid]
        m["deleted"] = time.time()
        self.trash.append(m)
        del self.trash[:-TRASH_MAX]
        log.info("메모 휴지통으로 %s (남은 %d, 휴지통 %d)", mid, len(self.memos), len(self.trash))
        self.touch(origin, structure=True)

    def restore(self, mid, origin=None):
        m = next((x for x in self.trash if x["id"] == mid), None)
        if m is None:
            return False
        self.trash = [x for x in self.trash if x["id"] != mid]
        m.pop("deleted", None)
        self.memos.insert(sum(1 for x in self.memos if x.get("pin")), m)
        log.info("메모 되살림 %s", mid)
        self.touch(origin, structure=True)
        return True

    def empty_trash(self, origin=None):
        n = len(self.trash)
        self.trash = []
        log.info("메모 휴지통 비움 %d장", n)
        self.touch(origin, structure=True)

    def move(self, mid, step, origin=None):
        i = next((k for k, m in enumerate(self.memos) if m["id"] == mid), None)
        j = None if i is None else i + step
        if i is None or not 0 <= j < len(self.memos):
            return False
        self.memos[i], self.memos[j] = self.memos[j], self.memos[i]
        log.info("메모 순서 %s %+d", mid, step)
        self.touch(origin, structure=True)
        return True

    def move_to(self, mid, idx, origin=None):
        """끌어 놓기로 순서 바꾸기 — idx = 놓을 자리(빼기 전 목록 기준)"""
        i = next((k for k, m in enumerate(self.memos) if m["id"] == mid), None)
        if i is None:
            return False
        if idx > i:
            idx -= 1
        idx = max(0, min(idx, len(self.memos) - 1))
        if idx == i:
            return False
        self.memos.insert(idx, self.memos.pop(i))
        log.info("메모 끌어 순서 %s %d → %d", mid, i, idx)
        self.touch(origin, structure=True)
        return True

    def set_pin(self, mid, on, origin=None):
        m = self.get(mid)
        if m is None:
            return
        m["pin"] = bool(on)
        self.memos.remove(m)
        self.memos.insert(0 if on else sum(1 for x in self.memos if x.get("pin")), m)
        log.info("메모 고정 %s %s", mid, on)
        self.touch(origin, structure=True)

    def get(self, mid):
        return next((m for m in self.memos if m["id"] == mid), None)

    def for_folder(self, path):
        nc = os.path.normcase(os.path.normpath(path or ""))
        return [m for m in self.memos if m.get("folder") and os.path.normcase(os.path.normpath(m["folder"])) == nc]

    # ---- 알림
    def arm_reminders(self):
        if any(m.get("remind") for m in self.memos):
            if not self._rt.isActive():
                self._rt.start()
        else:
            self._rt.stop()

    def check_reminders(self):
        now = time.time()
        for m in list(self.memos):
            r = m.get("remind")
            if r and r <= now:
                m.pop("remind", None)
                m["reminded"] = now
                log.info("메모 알림 %s '%s'", m["id"], m.get("title"))
                self.remind.emit(m)
                self.touch(None, structure=True)
        self.arm_reminders()


# ---------------------------------------------------------------- 본문
class MemoEdit(QtWidgets.QTextEdit):
    """메모 본문: 서식 있는 글 + 체크박스 + 링크 + 표 + 그림"""
    edited = QtCore.Signal()

    def __init__(self, card):
        super().__init__()
        self.card = card
        self.setAcceptRichText(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setPlaceholderText(T("메모…"))
        self.setToolTip(T("Ctrl+클릭 = 링크·폴더 열기 · 줄 앞 '[] ' = 체크박스, '- ' = 글머리, '1. ' = 번호 · 파일·폴더를 끌어 넣으면 링크"))
        self.document().setDocumentMargin(6)
        self.textChanged.connect(self.edited.emit)
        # 빌드 14: 다른 창 동기화용으로 포커스 들어올 때 다시 읽던 것 뺌 — 메모 창은 하나뿐이고,
        #   누르는 순간 문서를 갈아 끼우면 체크박스 누르기가 헛도는 원인이 될 수 있음(사용자 '마지막 체크박스 체크 안 됨', 재현 실패)

    def event(self, ev):
        if ev.type() == QtCore.QEvent.ShortcutOverride:   # 4Dir 단축키보다 글자 입력이 먼저 (Esc 는 빼고)
            if ev.key() != Qt.Key_Escape and not (ev.modifiers() & Qt.AltModifier):
                ev.accept()
                return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        k, mods = ev.key(), ev.modifiers()
        ctrl, shift = bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier)
        if k == Qt.Key_Escape:
            self.clearFocus()
            return
        if ctrl and not shift and k == Qt.Key_B:
            return self.fmt_bold()
        if ctrl and not shift and k == Qt.Key_I:
            return self.fmt_toggle("italic")
        if ctrl and not shift and k == Qt.Key_U:
            return self.fmt_toggle("underline")
        if ctrl and shift and k == Qt.Key_X:
            return self.fmt_toggle("strike")
        if ctrl and shift and k == Qt.Key_C:
            return self.toggle_list("check")
        if ctrl and shift and k == Qt.Key_L:
            return self.toggle_list("bullet")
        if ctrl and shift and k == Qt.Key_N:
            return self.toggle_list("number")
        if ctrl and k == Qt.Key_BracketRight:
            return self.step_size(+1)
        if ctrl and k == Qt.Key_BracketLeft:
            return self.step_size(-1)
        if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab) and not ctrl:
            self.linkify(self.textCursor().block())        # 방금 친 주소·경로 → 파란 링크
            self._end_link_format()                        # 링크 뒤에 치는 글자는 보통 글자로
        if k == Qt.Key_Space and not ctrl and self._auto_list():   # 줄 앞 '[] ' / '- ' / '1. '
            return
        if k in (Qt.Key_Return, Qt.Key_Enter) and not shift:
            c = self.textCursor()
            b = c.block()
            if b.textList() is not None and not b.text().strip():   # 빈 목록 줄 + Enter = 목록 끝
                self._unlist(c)
                return
            if b.textList() is not None and b.blockFormat().marker() != M_NONE:
                super().keyPressEvent(ev)
                nc = self.textCursor()   # 새 줄은 체크 안 된 상태로
                bf = nc.blockFormat()
                bf.setMarker(M_OFF)
                nc.setBlockFormat(bf)
                cf = nc.charFormat()
                cf.setFontStrikeOut(False)
                cf.setForeground(QtGui.QColor(self.card.text_color))
                nc.setCharFormat(cf)
                self.setTextCursor(nc)
                return
        super().keyPressEvent(ev)

    def _end_link_format(self):
        cf = self.currentCharFormat()
        if cf.isAnchor():
            cf.setAnchor(False)
            cf.setAnchorHref("")
            cf.setFontUnderline(False)
            cf.setForeground(QtGui.QColor(self.card.text_color))
            self.setCurrentCharFormat(cf)

    def linkify(self, block=None):
        """글 속 웹 주소·경로를 파란 밑줄 링크로 (빌드 14 사용자: 링크는 파란 글자). block=None 이면 메모 전체"""
        blocks = [block] if block is not None else []
        if block is None:
            b = self.document().firstBlock()
            while b.isValid():
                blocks.append(b)
                b = b.next()
        n = 0
        for b in blocks:
            for m in LINK_RE.finditer(b.text()):
                c = QtGui.QTextCursor(b)
                c.setPosition(b.position() + m.start())
                c.setPosition(b.position() + m.end(), QtGui.QTextCursor.KeepAnchor)
                href = m.group(0)
                c2 = QtGui.QTextCursor(b)
                c2.setPosition(b.position() + m.start() + 1)
                cur = c2.charFormat()
                if cur.isAnchor() and cur.anchorHref() == href:
                    continue
                cf = QtGui.QTextCharFormat()
                cf.setAnchor(True)
                cf.setAnchorHref(href)
                cf.setForeground(QtGui.QColor(LINK_COLOR))
                cf.setFontUnderline(True)
                c.mergeCharFormat(cf)
                n += 1
        if n:
            log.info("메모 링크 파랑 %d개", n)
        return n

    def _auto_list(self):
        c = self.textCursor()
        b = c.block()
        if b.textList() is not None or c.hasSelection():
            return False
        before = b.text()[:c.positionInBlock()]
        kind = {"[]": "check", "[ ]": "check", "-": "bullet", "*": "bullet", "1.": "number", "1)": "number"}.get(before)
        if not kind:
            return False
        c.beginEditBlock()
        c.movePosition(QtGui.QTextCursor.StartOfBlock)
        c.movePosition(QtGui.QTextCursor.Right, QtGui.QTextCursor.KeepAnchor, len(before))
        c.removeSelectedText()
        c.endEditBlock()
        self.setTextCursor(c)
        self.toggle_list(kind)
        log.info("메모 자동 변환 '%s' → %s", before, kind)
        return True

    # ---- 누르기: 체크박스 · Ctrl+클릭 링크
    def _box_rect(self, block):
        """체크박스 그릴 자리 (뷰포트 좌표)"""
        r = self.cursorRect(QtGui.QTextCursor(block))
        sz = max(11, min(16, r.height() - 3))
        return QtCore.QRectF(r.left() - sz - 7, r.center().y() - sz / 2 + 0.5, sz, sz), r

    def _box_at(self, pos):
        """그 자리가 체크 표시면 그 줄"""
        b = self.cursorForPosition(pos).block()
        if b.textList() is not None and b.blockFormat().marker() != M_NONE:
            r = self.cursorRect(QtGui.QTextCursor(b))
            if r.left() - 26 <= pos.x() < r.left() and r.top() - 2 <= pos.y() <= r.bottom() + 2:
                return b
        return None

    # ---- 그림 고르기 + 손잡이로 크기 (빌드 18, 워드처럼)
    HANDLE = 9

    def _img_rect(self, name):
        """화면(뷰포트) 위 그림 자리 QRect — 없으면 None"""
        for pos, ln, fmt in self._images():
            if fmt.name() == name:
                c = QtGui.QTextCursor(self.document())
                c.setPosition(pos)
                r = self.cursorRect(c)
                w, h = int(round(fmt.width())), int(round(fmt.height()))
                return QtCore.QRect(r.x(), r.bottom() - h + 1, w, h)
        return None

    def _handle_rect(self):
        r = self._img_rect(self._sel_img) if getattr(self, "_sel_img", None) else None
        if r is None:
            return None
        k = self.HANDLE
        return QtCore.QRect(r.right() - k // 2, r.bottom() - k // 2, k, k)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            pos = ev.position().toPoint()
            hr = self._handle_rect()
            if hr is not None and hr.adjusted(-3, -3, 3, 3).contains(pos):
                r = self._img_rect(self._sel_img)
                self._img_drag = (pos, r.width(), self._sel_img)
                self._ate = True
                return
            name = self.image_at(pos)
            r = self._img_rect(name) if name else None
            new = name if r is not None and r.contains(pos) else None
            if new != getattr(self, "_sel_img", None):
                self._sel_img = new
                self.viewport().update()
            if ev.modifiers() & Qt.ControlModifier:
                link = self.link_at(pos)
                if link:
                    self.card.panel.open_link(link)
                    return
            b = self._box_at(pos)
            if b is not None:
                self.setFocus()
                self._ate = True   # 이 누름의 '놓기'는 Qt 에 안 넘김 (Qt 도 체크를 뒤집어 두 번 뒤집힘)
                self.set_checked(b, b.blockFormat().marker() != M_ON)
                return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        """빨리 두 번 누르면 두 번째는 '두 번 누르기'로 옴 → 체크 표시 위면 한 번 더 누른 것으로"""
        if ev.button() == Qt.LeftButton and not ev.modifiers():
            b = self._box_at(ev.position().toPoint())
            if b is not None:
                self._ate = True
                self.set_checked(b, b.blockFormat().marker() != M_ON)
                return
        super().mouseDoubleClickEvent(ev)

    def mouseReleaseEvent(self, ev):
        drag = getattr(self, "_img_drag", None)
        if drag is not None:
            self._img_drag = None
            r = self._img_rect(drag[2])
            self.set_img_w(drag[2], r.width() if r is not None else drag[1])   # 저장
        if getattr(self, "_ate", False):
            self._ate = False
            return
        super().mouseReleaseEvent(ev)

    def mouseMoveEvent(self, ev):
        drag = getattr(self, "_img_drag", None)
        if drag is not None:
            dx = ev.position().toPoint().x() - drag[0].x()
            self.set_img_w(drag[2], max(16, drag[1] + dx), save=False)   # 가로세로 비율은 refit 이 지킴
            self.viewport().update()
            return
        hr = self._handle_rect()
        if hr is not None and hr.adjusted(-3, -3, 3, 3).contains(ev.position().toPoint()):
            self.viewport().setCursor(Qt.SizeFDiagCursor)
            return
        if ev.modifiers() & Qt.ControlModifier and self.link_at(ev.position().toPoint()):
            self.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.viewport().setCursor(Qt.IBeamCursor)
        super().mouseMoveEvent(ev)

    def paintEvent(self, ev):
        """Qt 기본 체크 표시(☒, X 모양)를 지우고 ✔ 상자를 그림 (빌드 14 사용자: X 말고 체크 표시)"""
        super().paintEvent(ev)
        p = QtGui.QPainter(self.viewport())
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        bg = self.palette().color(QtGui.QPalette.Base)
        dark = bg.lightness() < 128
        rect = ev.rect()
        b = self.document().firstBlock()
        while b.isValid():
            if b.isVisible() and b.textList() is not None and b.blockFormat().marker() != M_NONE:
                box, r = self._box_rect(b)
                if r.bottom() >= rect.top() and r.top() <= rect.bottom():
                    p.fillRect(QtCore.QRectF(r.left() - 26, r.top(), 25, r.height()), bg)   # Qt 가 그린 표시 지움
                    on = b.blockFormat().marker() == M_ON
                    if on:
                        p.setPen(Qt.NoPen)
                        p.setBrush(QtGui.QColor(CHECK_GREEN))
                        p.drawRoundedRect(box, 3, 3)
                        pen = QtGui.QPen(QtGui.QColor("#ffffff"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                        p.setPen(pen)
                        x, y, w, h = box.x(), box.y(), box.width(), box.height()
                        p.drawPolyline([QtCore.QPointF(x + w * 0.22, y + h * 0.52), QtCore.QPointF(x + w * 0.42, y + h * 0.72),
                                        QtCore.QPointF(x + w * 0.78, y + h * 0.30)])
                    else:
                        p.setPen(QtGui.QPen(QtGui.QColor("#c8ccd0" if dark else "#6b7177"), 1.4))
                        p.setBrush(QtGui.QColor(255, 255, 255, 40 if dark else 200))
                        p.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), 3, 3)
            b = b.next()
        r = self._img_rect(self._sel_img) if getattr(self, "_sel_img", None) else None
        if r is not None:   # 고른 그림: 테두리 + 오른쪽 아래 손잡이
            p.setRenderHint(QtGui.QPainter.Antialiasing, False)
            p.setPen(QtGui.QPen(QtGui.QColor("#2f6fd0"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(0, 0, -1, -1))
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawRect(self._handle_rect())
        p.end()

    def link_at(self, pos):
        """그 자리의 링크: 글 속 웹 주소·경로 우선, 없으면 끌어 넣은 링크(앵커)"""
        c = self.cursorForPosition(pos)
        txt, at = c.block().text(), c.positionInBlock()
        for m in LINK_RE.finditer(txt):
            if m.start() <= at <= m.end():
                s = m.group(0)
                if s.startswith(("http://", "https://", "file:///")):
                    return s
                # 경로는 띄어쓰기가 있을 수 있음 → 실제로 있는 데까지 뒤 낱말을 떼어 봄 ('F:\\링크 폴더 보기' → 'F:\\링크 폴더')
                cut = s
                while not os.path.exists(cut) and " " in cut:
                    cut = cut[:cut.rfind(" ")].rstrip()
                return cut if os.path.exists(cut) else s
        return self.anchorAt(pos) or None

    def set_checked(self, block, on):
        strike = bool(self.card.store.prefs.get("done_strike", True))
        c = QtGui.QTextCursor(block)
        c.beginEditBlock()
        bf = block.blockFormat()
        bf.setMarker(M_ON if on else M_OFF)
        c.setBlockFormat(bf)
        if strike or not on:   # 끌 때는 취소선·회색을 늘 지움 (설정을 끈 뒤에도 예전 것 정리)
            c.movePosition(QtGui.QTextCursor.StartOfBlock)
            c.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
            cf = QtGui.QTextCharFormat()
            cf.setFontStrikeOut(on)
            cf.setForeground(QtGui.QColor(self.card.done_gray if on else self.card.text_color))
            c.mergeCharFormat(cf)
        c.endEditBlock()
        got = self.document().findBlockByNumber(block.blockNumber()).blockFormat().marker()
        log.info("메모 체크 %s 줄%d '%s' → 표시 %s (취소선 %s)", on, block.blockNumber(), block.text()[:30],
                 {M_ON: "체크", M_OFF: "빈칸", M_NONE: "없음"}.get(got, got), strike)
        self.viewport().update()

    def progress(self):
        """체크박스 (끝난 수, 전체 수)"""
        done = total = 0
        b = self.document().firstBlock()
        while b.isValid():
            mk = b.blockFormat().marker()
            if b.textList() is not None and mk != M_NONE:
                total += 1
                done += mk == M_ON
            b = b.next()
        return done, total

    # ---- 끌어 넣기 · 붙여넣기 (파일·폴더 = 링크, 그림 = 저장해서 넣음)
    def canInsertFromMimeData(self, md):
        return md.hasUrls() or md.hasImage() or super().canInsertFromMimeData(md)

    def insertFromMimeData(self, md):
        if md.hasImage() and not md.hasUrls():
            img = QtGui.QImage(md.imageData())
            if not img.isNull():
                return self.insert_image(img)
        if md.hasUrls():
            locs = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            imgs = [x for x in locs if os.path.isfile(x) and x.lower().endswith(IMG_EXT)]
            for x in imgs:   # 그림 파일은 그림으로 (GIF 는 움직임 그대로)
                self.insert_image_file(x)
            locs = [x for x in locs if x not in imgs]
            if locs:
                c = self.textCursor()
                for p in locs:
                    isd = os.path.isdir(p)
                    name = os.path.basename(p.rstrip("\\/")) or p
                    url = QtCore.QUrl.fromLocalFile(p).toString()
                    c.insertHtml(f'<a href="{url}" style="color:{LINK_COLOR};">{"📁" if isd else "📄"} {name}</a>&nbsp;')
                    c.insertBlock()
                self._end_link_format()
                log.info("메모 링크 넣음 %d개 %s", len(locs), locs[:2])
            if locs or imgs:
                return
        super().insertFromMimeData(md)
        if md.hasText():
            self.linkify()

    def _new_img_path(self, ext):
        d = self.card.store.img_dir
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{self.card.data['id']}_{int(time.time() * 1000)}{ext}")

    def _put_img(self, p):
        self.textCursor().insertHtml(f'<img src="{QtCore.QUrl.fromLocalFile(p).toString()}"><br>')
        self.refit_images()

    def insert_image(self, img):
        """복사한 그림 (클립보드) → png 로 저장해 넣음"""
        p = self._new_img_path(".png")
        img.save(p, "PNG")
        self._put_img(p)
        log.info("메모 그림 넣음 %s (%dx%d)", p, img.width(), img.height())
        return p

    def insert_image_file(self, fn):
        """그림 파일 → 그대로 복사해 넣음 (GIF 움직임 유지)"""
        import shutil
        ext = os.path.splitext(fn)[1].lower() or ".png"
        p = self._new_img_path(ext)
        try:
            shutil.copyfile(fn, p)
        except OSError:
            log.exception("메모 그림 복사 실패 %s", fn)
            return None
        self._put_img(p)
        log.info("메모 그림 파일 넣음 %s → %s", fn, p)
        return p

    def pick_image(self):
        """그림 단추 — 파일에서 골라 넣기 (memo_images 로 복사)"""
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, T("그림 넣기"), "", T("그림") + " (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        if not fn:
            return None
        return self.insert_image_file(fn)

    # ---- 그림 크기·움직임 (빌드 16 사용자: 작은 메모에 넣은 큰 그림이 찌그러진 채 안 커짐, GIF 안 움직임)
    def _images(self):
        """메모 속 그림들: (조각 시작, 길이, QTextImageFormat)"""
        out = []
        b = self.document().begin()
        while b.isValid():
            it = b.begin()
            while not it.atEnd():
                f = it.fragment()
                if f.isValid() and f.charFormat().isImageFormat():
                    out.append((f.position(), f.length(), f.charFormat().toImageFormat()))
                it += 1
            b = b.next()
        return out

    def _img_info(self, name):
        info = self._imgcache.get(name) if hasattr(self, "_imgcache") else None
        if info is None:
            if not hasattr(self, "_imgcache"):
                self._imgcache = {}
            path = QtCore.QUrl(name).toLocalFile() or name
            rd = QtGui.QImageReader(path)
            info = {"path": path, "nat": rd.size(), "gif": path.lower().endswith(".gif") and rd.supportsAnimation(), "movie": None, "size": None}
            self._imgcache[name] = info
        return info

    @staticmethod
    def _key(name):
        return os.path.basename(QtCore.QUrl(name).toLocalFile() or name)

    def img_w(self, name, nat):
        """그림 가로 픽셀 (빌드 18) — 사용자가 정한 크기 그대로. 처음(값 없음)이면 min(원래 크기 × 옛 비율, 지금 메모 폭) 으로 한 번 정함"""
        d = self.card.data.setdefault("img_w", {})
        k = self._key(name)
        if k not in d:
            old = float((self.card.data.get("img_scale") or {}).get(k, 1.0))   # 2.3.0 까지 비율
            d[k] = max(16, min(int(nat.width() * old), max(60, self.viewport().width() - 28)))
        return int(d[k])

    def set_img_w(self, name, w, save=True):
        self.card.data.setdefault("img_w", {})[self._key(name)] = max(16, int(w))
        self.refit_images()
        if save:
            log.info("메모 그림 크기 %s → %dpx", self._key(name), int(w))
            self.card.store.touch(self.card.panel)

    def set_img_size(self, name, how):
        nat = self._img_info(name)["nat"]
        if not nat.isValid():
            return
        w = nat.width() if how == "nat" else (max(60, self.viewport().width() - 28) if how == "fit" else nat.width() * how)
        self.set_img_w(name, w)

    def refit_images(self):
        """그림을 사용자가 정한 크기로 (빌드 18: 메모 폭이 바뀌어도 그대로 — 넓으면 가로 스크롤), 미리 부드럽게 줄인 그림을 넣어 깨짐 없음"""
        imgs = self._images()
        if not imgs:
            return
        dpr = self.devicePixelRatioF() or 1.0
        doc = self.document()
        was = self.blockSignals(True)   # 크기 맞춤은 '고침'이 아님 (저장·시각 안 바꿈)
        try:
            for pos, ln, fmt in imgs:
                name = fmt.name()
                info = self._img_info(name)
                nat = info["nat"]
                if not nat.isValid() or nat.width() <= 0:
                    continue
                w = self.img_w(name, nat)
                h = max(1, round(nat.height() * w / nat.width()))
                if info["size"] != (w, h):
                    info["size"] = (w, h)
                    if info["gif"]:
                        mv = info["movie"]
                        if mv is None:
                            mv = QtGui.QMovie(info["path"])
                            mv.setCacheMode(QtGui.QMovie.CacheAll)
                            mv.frameChanged.connect(lambda _f, n=name, m=mv: self._gif_frame(n, m))
                            info["movie"] = mv
                        mv.setScaledSize(QtCore.QSize(int(w * dpr), int(h * dpr)))
                        if self.isVisible():
                            mv.start()
                    else:
                        im = QtGui.QImage(info["path"])
                        if not im.isNull():
                            im = im.scaled(int(w * dpr), int(h * dpr), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                            im.setDevicePixelRatio(dpr)
                            doc.addResource(QtGui.QTextDocument.ImageResource, QtCore.QUrl(name), im)
                if abs(fmt.width() - w) > 0.5 or abs(fmt.height() - h) > 0.5:
                    c = QtGui.QTextCursor(doc)
                    c.setPosition(pos)
                    c.setPosition(pos + ln, QtGui.QTextCursor.KeepAnchor)
                    nf = QtGui.QTextImageFormat(fmt)
                    nf.setWidth(w)
                    nf.setHeight(h)
                    c.setCharFormat(nf)
        finally:
            self.blockSignals(was)
        self.viewport().update()

    def _gif_frame(self, name, mv):
        im = mv.currentImage()
        if im.isNull():
            return
        im.setDevicePixelRatio(self.devicePixelRatioF() or 1.0)
        self.document().addResource(QtGui.QTextDocument.ImageResource, QtCore.QUrl(name), im)
        self.viewport().update()

    def _movies(self, run):
        for info in getattr(self, "_imgcache", {}).values():
            mv = info.get("movie")
            if mv is not None:
                if run:
                    mv.start() if mv.state() != QtGui.QMovie.Running else None
                else:
                    mv.setPaused(True) if mv.state() == QtGui.QMovie.Running else None

    def showEvent(self, ev):
        super().showEvent(ev)
        self.refit_images()
        self._movies(True)

    def hideEvent(self, ev):   # 안 보이면 GIF 멈춤 (놀 때 CPU 안 씀)
        self._movies(False)
        super().hideEvent(ev)


    def image_at(self, pos):
        c = self.cursorForPosition(pos)
        for p in (c.position(), c.position() + 1):
            cc = QtGui.QTextCursor(self.document())
            cc.setPosition(max(0, p))
            f = cc.charFormat()
            if f.isImageFormat():
                return f.toImageFormat().name()
        return None

    # ---- 표
    def insert_table(self, rows, cols):
        tf = QtGui.QTextTableFormat()
        tf.setBorder(1)
        tf.setBorderStyle(QtGui.QTextFrameFormat.BorderStyle_Solid)
        tf.setBorderBrush(QtGui.QBrush(QtGui.QColor("#9aa0a6")))
        tf.setBorderCollapse(True)
        tf.setCellPadding(3)
        tf.setCellSpacing(0)
        tf.setWidth(QtGui.QTextLength(QtGui.QTextLength.PercentageLength, 100))
        c = self.textCursor()
        c.insertTable(rows, cols, tf)
        self.setTextCursor(c)   # 커서를 첫 칸으로
        log.info("메모 표 넣음 %d×%d", rows, cols)

    def table_op(self, op):
        c = self.textCursor()
        t = c.currentTable()
        if t is None:
            return
        cell = t.cellAt(c)
        r, k = cell.row(), cell.column()
        if op == "row_above":
            t.insertRows(r, 1)
        elif op == "row_below":
            t.insertRows(r + 1, 1)
        elif op == "col_left":
            t.insertColumns(k, 1)
        elif op == "col_right":
            t.insertColumns(k + 1, 1)
        elif op == "del_row":
            t.removeRows(r, 1)
        elif op == "del_col":
            t.removeColumns(k, 1)
        elif op == "del_table":
            t.removeRows(0, t.rows())
        log.info("메모 표 %s (%d,%d)", op, r, k)

    # ---- 서식
    def _sel(self):
        c = self.textCursor()
        if not c.hasSelection():
            c.select(QtGui.QTextCursor.WordUnderCursor)
        return c

    def _sel_or_all(self):
        """고른 글자, 없으면 메모 전체 (크기·글꼴·자간)"""
        c = self.textCursor()
        if c.hasSelection():
            return c, False
        c = QtGui.QTextCursor(self.document())
        c.select(QtGui.QTextCursor.Document)
        return c, True

    def fmt_bold(self):
        c = self._sel()
        cf = QtGui.QTextCharFormat()
        cf.setFontWeight(QtGui.QFont.Normal if c.charFormat().fontWeight() > QtGui.QFont.Normal else QtGui.QFont.Bold)
        c.mergeCharFormat(cf)
        self.mergeCurrentCharFormat(cf)

    def fmt_toggle(self, what):
        c = self._sel()
        cur = c.charFormat()
        cf = QtGui.QTextCharFormat()
        if what == "italic":
            cf.setFontItalic(not cur.fontItalic())
        elif what == "underline":
            cf.setFontUnderline(not cur.fontUnderline())
        else:
            cf.setFontStrikeOut(not cur.fontStrikeOut())
        c.mergeCharFormat(cf)
        self.mergeCurrentCharFormat(cf)

    def set_color(self, hexc):
        c = self._sel()
        cf = QtGui.QTextCharFormat()
        cf.setForeground(QtGui.QColor(hexc or self.card.text_color))
        c.mergeCharFormat(cf)
        self.mergeCurrentCharFormat(cf)

    def cur_size(self):
        return self.textCursor().charFormat().fontPointSize() or self.card.data.get("fs", BASE_SIZE)

    def set_size(self, new):
        new = max(5.0, min(96.0, float(new)))
        cf = QtGui.QTextCharFormat()
        cf.setFontPointSize(new)
        c, whole = self._sel_or_all()
        c.mergeCharFormat(cf)
        if whole:
            self.card.data["fs"] = new
        self.mergeCurrentCharFormat(cf)
        log.info("메모 글자 크기 → %s (%s)", new, "전체" if whole else "고른 글자")
        return new

    def step_size(self, d):
        cur = self.cur_size()
        if d > 0:
            new = next((v for v in SIZES if v > cur + 0.01), SIZES[-1])
        else:
            new = next((v for v in reversed(SIZES) if v < cur - 0.01), SIZES[0])
        return self.set_size(new)

    def set_family(self, fam):
        cf = QtGui.QTextCharFormat()
        cf.setFontFamilies([fam])
        c, whole = self._sel_or_all()
        c.mergeCharFormat(cf)
        self.mergeCurrentCharFormat(cf)
        log.info("메모 글꼴 → %s (%s)", fam, "전체" if whole else "고른 글자")

    def set_spacing(self, pct):
        cf = QtGui.QTextCharFormat()
        cf.setFontLetterSpacingType(QtGui.QFont.PercentageSpacing)
        cf.setFontLetterSpacing(pct)
        c, whole = self._sel_or_all()
        c.mergeCharFormat(cf)
        self.mergeCurrentCharFormat(cf)
        log.info("메모 자간 → %s%% (%s)", pct, "전체" if whole else "고른 글자")

    def set_align(self, how):
        self.setAlignment({"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[how])
        log.info("메모 정렬 → %s", how)

    def _unlist(self, c):
        """목록에서 빼기 — Qt 는 목록에서 뺄 때 그 줄에 목록 들여쓰기를 남김 → 빼고 나서 들여쓰기 0"""
        b = c.block()
        lst = b.textList()
        if lst is not None:
            lst.remove(b)
        bf = b.blockFormat()
        bf.setMarker(M_NONE)
        bf.setIndent(0)
        bf.setTextIndent(0)
        c.setBlockFormat(bf)

    @staticmethod
    def _kind_of(b):
        lst = b.textList()
        if lst is None:
            return None
        if b.blockFormat().marker() != M_NONE:
            return "check"
        return "number" if lst.format().style() == QtGui.QTextListFormat.ListDecimal else "bullet"

    def toggle_list(self, kind):
        """체크박스 / 글머리 / 번호 — 고른 줄들 전부"""
        c = self.textCursor()
        c.beginEditBlock()
        doc = self.document()
        b0 = doc.findBlock(c.selectionStart())
        b1 = doc.findBlock(c.selectionEnd())
        want = M_OFF if kind == "check" else M_NONE
        same = self._kind_of(b0) == kind
        blocks, b = [], b0
        while b.isValid():
            blocks.append(b)
            if b == b1:
                break
            b = b.next()
        if same:
            for b in blocks:
                self._unlist(QtGui.QTextCursor(b))
        else:
            lf = QtGui.QTextListFormat()
            lf.setStyle(QtGui.QTextListFormat.ListDecimal if kind == "number" else QtGui.QTextListFormat.ListDisc)
            lf.setIndent(1)
            lst = None
            for b in blocks:
                bc = QtGui.QTextCursor(b)
                if b.textList() is not None:
                    b.textList().remove(b)
                if lst is None:
                    lst = bc.createList(lf)
                else:
                    lst.add(b)
                bf = b.blockFormat()
                bf.setMarker(want)
                bc.setBlockFormat(bf)
        c.endEditBlock()
        log.info("메모 %s %s (%d줄)", "목록 풂" if same else "목록", kind, len(blocks))

    def format_actions(self, m):
        """서식 항목 (우클릭 맨 위)"""
        fg = self.card.text_color
        m.addAction(fmt_icon("bold", fg), T("굵게") + "\tCtrl+B", self.fmt_bold)
        m.addAction(fmt_icon("italic", fg), T("기울임") + "\tCtrl+I", lambda: self.fmt_toggle("italic"))
        m.addAction(fmt_icon("underline", fg), T("밑줄") + "\tCtrl+U", lambda: self.fmt_toggle("underline"))
        m.addAction(fmt_icon("strike", fg), T("취소선") + "\tCtrl+Shift+X", lambda: self.fmt_toggle("strike"))
        m.addSeparator()
        m.addAction(fmt_icon("check", fg), T("체크박스") + "\tCtrl+Shift+C", lambda: self.toggle_list("check"))
        m.addAction(fmt_icon("bullet", fg), T("글머리") + "\tCtrl+Shift+L", lambda: self.toggle_list("bullet"))
        m.addAction(fmt_icon("number", fg), T("번호 목록") + "\tCtrl+Shift+N", lambda: self.toggle_list("number"))
        m.addSeparator()
        self.color_menu(m.addMenu(fmt_icon("color", fg), T("글자 색")))
        m.addAction(fmt_icon("plus_small", fg), T("글자 크게") + "\tCtrl+]", lambda: self.step_size(+1))
        m.addAction(fmt_icon("minus", fg), T("글자 작게") + "\tCtrl+[", lambda: self.step_size(-1))
        if self.textCursor().currentTable() is not None:
            m.addSeparator()
            tm = m.addMenu(fmt_icon("table", fg), T("표"))
            for label, op in ((T("위에 줄 넣기"), "row_above"), (T("아래에 줄 넣기"), "row_below"), (T("왼쪽에 칸 넣기"), "col_left"),
                              (T("오른쪽에 칸 넣기"), "col_right"), (None, None), (T("이 줄 지우기"), "del_row"),
                              (T("이 칸 지우기"), "del_col"), (T("표 지우기"), "del_table")):
                if label is None:
                    tm.addSeparator()
                else:
                    tm.addAction(label, lambda op=op: self.table_op(op))

    def color_menu(self, col, apply=None):
        apply = apply or self.set_color
        for hx, name in TEXT_COLORS:
            pm = QtGui.QPixmap(12, 12)
            pm.fill(QtGui.QColor(hx))
            col.addAction(QtGui.QIcon(pm), T(name), lambda hx=hx: apply(hx))
        col.addSeparator()
        col.addAction(T("기본 색"), lambda: apply(None))
        return col

    def contextMenuEvent(self, ev):
        """서식은 맨 위에 바로, 그 아래 링크 열기·복사·붙여넣기"""
        m = QtWidgets.QMenu(self)
        m.setToolTipsVisible(True)
        self.format_actions(m)
        img = self.image_at(ev.pos())
        if img:
            m.addSeparator()
            im = m.addMenu(fmt_icon("image", self.card.text_color), T("그림 크기"))
            for label, how in IMG_SIZES:
                im.addAction(T(label), lambda how=how: self.set_img_size(img, how))
            im.addSeparator()
            hint = im.addAction(T("그림을 누르고 오른쪽 아래 손잡이를 끌어 크기 조절"))
            hint.setEnabled(False)
        link = self.link_at(ev.pos())
        if link:
            m.addSeparator()
            m.addAction(T("링크 열기") + "\tCtrl+" + T("클릭"), lambda: self.card.panel.open_link(link))
        m.addSeparator()
        std = self.createStandardContextMenu()
        for a in std.actions():
            m.addAction(a)
        m.exec(ev.globalPos())
        std.deleteLater()


# ---------------------------------------------------------------- 서식 줄
class TablePicker(QtWidgets.QWidget):
    """표 크기 고르기 (구글 문서처럼 칸을 훑어 고름)"""
    picked = QtCore.Signal(int, int)
    N, C = 8, 18

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.sel = (1, 1)
        self.setFixedSize(self.N * self.C + 8, self.N * self.C + 26)

    def mouseMoveEvent(self, ev):
        p = ev.position()
        self.sel = (max(1, min(self.N, int((p.y() - 4) // self.C) + 1)), max(1, min(self.N, int((p.x() - 4) // self.C) + 1)))
        self.update()

    def mouseReleaseEvent(self, ev):
        self.picked.emit(*self.sel)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        for r in range(self.N):
            for c in range(self.N):
                on = r < self.sel[0] and c < self.sel[1]
                p.setPen(QtGui.QColor("#1a73e8" if on else "#b0b5ba"))
                p.setBrush(QtGui.QColor("#d2e3fc" if on else "#ffffff"))
                p.drawRect(4 + c * self.C, 4 + r * self.C, self.C - 3, self.C - 3)
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.drawText(QtCore.QRect(0, self.N * self.C + 4, self.width(), 20), Qt.AlignCenter, f"{self.sel[0]} × {self.sel[1]}")
        p.end()


FONTS = ["Malgun Gothic", "Gulim", "Dotum", "Batang", "NanumGothic", "Segoe UI", "Arial", "Consolas"]


class FormatBar(QtWidgets.QWidget):
    """서식 단추 한 줄 (빌드 15 사용자: 구글 시트 도구 줄처럼 무리 지어 정리, 자리가 모자라면 ⋮ 안으로).
    − 크기 + | 굵게 기울임 밑줄 취소선 글자색 | 체크박스 글머리 번호 | 정렬 자간 | 표 그림.
    지금(마지막으로) 쓴 메모에 적용, 단추는 포커스를 안 가져감. 글꼴은 ⚙ 메뉴로(fill_font_menu)"""

    def __init__(self, get_edit, fg="#3a4652"):
        super().__init__()
        self.get_edit = get_edit
        self.fg = fg
        self.last_color = "#d93025"
        self.btns = {}
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        tb = QtWidgets.QToolBar()
        tb.setIconSize(QtCore.QSize(ICON, ICON))
        tb.setStyleSheet("QToolBar{border:none; spacing:0px; padding:0px;}")
        outer.addWidget(tb)
        self.tb = tb
        self.call = call = self._call

        def b(kind, tip, fn=None, w=BTN):
            x = QtWidgets.QToolButton()
            x.setIcon(fmt_icon(kind, fg, sz=ICON))
            x.setIconSize(QtCore.QSize(ICON, ICON))
            x.setToolTip(tip)
            x.setAutoRaise(True)
            x.setFocusPolicy(Qt.NoFocus)
            x.setFixedSize(w, BTN)
            if fn:
                x.clicked.connect(fn)
            tb.addWidget(x)
            self.btns[kind] = x
            return x

        def menu_btn(kind, tip):
            x = b(kind, tip, w=BTN + 8)
            x.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            m = QtWidgets.QMenu(x)
            x.setMenu(m)
            return x, m

        # − 크기 +
        b("minus", T("글자 작게") + " (Ctrl+[)", lambda: call("step_size", -1), w=24)
        self.size_box = QtWidgets.QLineEdit()
        self.size_box.setToolTip(T("글자 크기 — 숫자를 치고 Enter (고른 글자, 없으면 메모 전체)"))
        self.size_box.setAlignment(Qt.AlignCenter)
        self.size_box.setFixedSize(36, BTN - 6)
        self.size_box.setStyleSheet("QLineEdit{border:1px solid #9aa0a6; border-radius:4px; background:transparent;}")
        self.size_box.setValidator(QtGui.QDoubleValidator(5, 96, 1))
        self.size_box.setText(size_text(BASE_SIZE))
        self.size_box.returnPressed.connect(lambda: call("set_size", float(self.size_box.text() or BASE_SIZE)))
        tb.addWidget(self.size_box)
        b("plus_small", T("글자 크게") + " (Ctrl+])", lambda: call("step_size", +1), w=24)
        tb.addSeparator()
        # 글자 모양
        b("bold", T("굵게") + " (Ctrl+B)", lambda: call("fmt_bold"))
        b("italic", T("기울임") + " (Ctrl+I)", lambda: call("fmt_toggle", "italic"))
        b("underline", T("밑줄") + " (Ctrl+U)", lambda: call("fmt_toggle", "underline"))
        b("strike", T("취소선") + " (Ctrl+Shift+X)", lambda: call("fmt_toggle", "strike"))
        c = b("color", T("글자 색 — 누르면 막대 색으로, ▾ 로 색 고르기"), lambda: call("set_color", self.last_color), w=BTN + 12)
        c.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        cm = QtWidgets.QMenu(c)

        def pick(hx):
            self.last_color = hx or "#222222"
            c.setIcon(fmt_icon("color", fg, self.last_color, sz=ICON))
            call("set_color", hx)
        for hx, name in TEXT_COLORS:
            pm = QtGui.QPixmap(12, 12)
            pm.fill(QtGui.QColor(hx))
            cm.addAction(QtGui.QIcon(pm), T(name), lambda hx=hx: pick(hx))
        cm.addSeparator()
        cm.addAction(T("기본 색"), lambda: pick(None))
        c.setMenu(cm)
        tb.addSeparator()
        # 목록
        b("check", T("체크박스") + " (Ctrl+Shift+C) — " + T("줄 앞에 '[] ' 를 쳐도 됨"), lambda: call("toggle_list", "check"))
        b("bullet", T("글머리") + " (Ctrl+Shift+L) — " + T("줄 앞에 '- ' 를 쳐도 됨"), lambda: call("toggle_list", "bullet"))
        b("number", T("번호 목록") + " (Ctrl+Shift+N) — " + T("줄 앞에 '1. ' 을 쳐도 됨"), lambda: call("toggle_list", "number"))
        tb.addSeparator()
        # 줄 모양
        al, am = menu_btn("align_left", T("정렬 — 왼쪽 · 가운데 · 오른쪽"))
        for how, label in (("left", T("왼쪽 정렬")), ("center", T("가운데 정렬")), ("right", T("오른쪽 정렬"))):
            am.addAction(fmt_icon("align_" + how, fg, sz=ICON), label, lambda how=how: (call("set_align", how),
                                                                                        al.setIcon(fmt_icon("align_" + how, fg, sz=ICON))))
        _s, sm = menu_btn("spacing", T("자간 (글자 사이 간격) — 고른 글자, 없으면 메모 전체"))
        for label, pct in SPACINGS:
            sm.addAction(f"{T(label)}  ({pct}%)", lambda pct=pct: call("set_spacing", pct))
        tb.addSeparator()
        # 넣기
        _t, tm = menu_btn("table", T("표 넣기 — 칸 수를 골라 누르기 (표 안 우클릭 = 줄·칸 넣기/지우기)"))
        tp = TablePicker()
        wa = QtWidgets.QWidgetAction(tm)
        wa.setDefaultWidget(tp)
        tm.addAction(wa)
        tp.picked.connect(lambda r, k: (tm.close(), call("insert_table", r, k)))
        b("image", T("그림 넣기 — 파일에서 고르기 (복사한 그림은 Ctrl+V)"), lambda: call("pick_image"))
        ext = tb.findChild(QtWidgets.QToolButton, "qt_toolbar_ext_button")   # 자리가 모자라면 ⋮ (구글 시트처럼)
        if ext is not None:
            ext.setIcon(fmt_icon("more", fg, sz=ICON))
            ext.setToolTip(T("가려진 서식 단추 더 보기"))
            # 창 밖 도구 줄은 Qt 기본 펼치기가 안 됨(실측) → 가려진 단추를 메뉴로 보여 줌
            xm = QtWidgets.QMenu(ext)
            xm.aboutToShow.connect(lambda: self._fill_more(xm))
            ext.setMenu(xm)
            ext.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.ext = ext

    def _fill_more(self, m):
        m.clear()
        n = 0
        for a in self.tb.actions():
            w = self.tb.widgetForAction(a)
            if a.isSeparator() or w is None or w.isVisible():
                continue
            if isinstance(w, QtWidgets.QToolButton):
                tip = w.toolTip().split(" — ")[0]
                if w.menu() is not None and w.popupMode() == QtWidgets.QToolButton.InstantPopup:
                    sub = m.addMenu(w.icon(), tip)
                    for x in w.menu().actions():
                        sub.addAction(x)
                else:
                    m.addAction(w.icon(), tip, w.click)
                n += 1
        log.info("메모 서식 ⋮ 가려진 단추 %d개", n)

    def _call(self, name, *a):
        ed = self.get_edit()
        if ed is not None:
            r = getattr(ed, name)(*a)
            ed.setFocus()
            self.sync(ed)
            return r

    def fill_font_menu(self, m):
        """⚙ ▸ 글꼴 (빌드 15 사용자: 글꼴은 잘 안 쓰니 설정 쪽으로)"""
        ed = self.get_edit()
        fams = ed.textCursor().charFormat().fontFamilies() if ed is not None else None
        cur = (fams[0] if isinstance(fams, (list, tuple)) and fams else None) or (ed.font().family() if ed is not None else "")
        have = set(QtGui.QFontDatabase.families())
        for f in FONTS:
            if f in have:
                a = m.addAction(f, lambda f=f: self._call("set_family", f))
                a.setFont(QtGui.QFont(f))
                a.setCheckable(True)
                a.setChecked(f == cur)
        m.addSeparator()
        m.addAction(T("다른 글꼴…"), self._other_font)

    def _other_font(self):
        ed = self.get_edit()
        ok, f = QtWidgets.QFontDialog.getFont(ed.currentFont() if ed is not None else QtGui.QFont(), self, T("글꼴"))
        if isinstance(ok, QtGui.QFont):   # PySide 판에 따라 (ok, font) / (font, ok)
            ok, f = f, ok
        if ok:
            self._call("set_family", f.family())

    def sync(self, ed):
        """지금 커서의 글자 크기를 칸에 보여 줌"""
        if ed is None:
            return
        if not self.size_box.hasFocus():
            self.size_box.setText(size_text(round(ed.cur_size(), 1)))


class Grip(QtWidgets.QFrame):
    """메모지 아래 높이 조절 손잡이"""
    def __init__(self, card):
        super().__init__()
        self.card = card
        self.setFixedHeight(7)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(T("끌어서 메모 높이 조절"))
        self._y = None

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 1))
        cx = self.width() // 2
        for dx in (-8, 0, 8):
            p.drawPoint(cx + dx, 3)
            p.drawPoint(cx + dx + 2, 3)
        p.end()

    def mousePressEvent(self, ev):
        self._y = ev.globalPosition().y()
        self._h = self.card.edit.height()

    def mouseMoveEvent(self, ev):
        if self._y is not None:
            self.card.set_height(max(MIN_H, int(self._h + ev.globalPosition().y() - self._y)))

    def mouseReleaseEvent(self, ev):
        if self._y is not None:
            self._y = None
            self.card.store.touch()
            log.info("메모 높이 %s → %d", self.card.data["id"], self.card.data["h"])


MEMO_MIME = "application/x-4dir-memo"


class ElideLabel(QtWidgets.QLabel):
    """자리가 모자라면 끝을 … 로 줄여 그리는 글자 (글자 자체는 전체 그대로)"""

    def minimumSizeHint(self):
        return QtCore.QSize(20, super().minimumSizeHint().height())

    def shown(self):
        return self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.contentsRect().width())

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.setFont(self.font())
        p.drawText(self.contentsRect(), int(Qt.AlignLeft | Qt.AlignVCenter), self.shown())
        p.end()


class DragHead(QtWidgets.QWidget):
    """메모지 제목 줄 — 빈 곳을 끌면 순서 바꾸기, 두 번 누르면 접기/펴기"""

    def __init__(self, card):
        super().__init__()
        self.card = card
        self._p = None
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(T("제목 줄: 끌어서 순서 바꾸기 · 두 번 누르면 접기/펴기"))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._p = ev.position().toPoint()
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        self.card.toggle_fold()

    def mouseMoveEvent(self, ev):
        if self._p is not None and (ev.position().toPoint() - self._p).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
            self._p = None
            md = QtCore.QMimeData()
            md.setData(MEMO_MIME, self.card.data["id"].encode())
            drag = QtGui.QDrag(self)
            drag.setMimeData(md)
            pm = self.card.grab()
            if pm.height() > 120:
                pm = pm.copy(0, 0, pm.width(), 120)
            drag.setPixmap(pm.scaledToWidth(min(220, pm.width()), Qt.SmoothTransformation))
            drag.setHotSpot(QtCore.QPoint(20, 10))
            drag.exec(Qt.MoveAction)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._p = None
        super().mouseReleaseEvent(ev)


class DropArea(QtWidgets.QWidget):
    """메모지 목록 — 끌어 온 메모지를 놓을 자리에 줄을 그어 보여 줌"""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setAcceptDrops(True)
        self._line = None

    def _index_at(self, y):
        vis = [c for c in self.panel.cards if c.isVisible()]
        for c in vis:
            if y < c.geometry().center().y():
                return self.panel.cards.index(c), c.geometry().top() - 4
        if vis:
            return len(self.panel.cards), vis[-1].geometry().bottom() + 4
        return 0, 0

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(MEMO_MIME):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(MEMO_MIME):
            ev.acceptProposedAction()
            self._line = self._index_at(ev.position().toPoint().y())[1]
            self.update()

    def dragLeaveEvent(self, ev):
        self._line = None
        self.update()

    def dropEvent(self, ev):
        self._line = None
        self.update()
        if not ev.mimeData().hasFormat(MEMO_MIME):
            return
        mid = bytes(ev.mimeData().data(MEMO_MIME)).decode()
        idx = self._index_at(ev.position().toPoint().y())[0]
        ev.acceptProposedAction()
        QtCore.QTimer.singleShot(0, lambda: self.panel.store.move_to(mid, idx))

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._line is not None:
            p = QtGui.QPainter(self)
            p.setPen(QtGui.QPen(QtGui.QColor("#2f7de1"), 3))
            p.drawLine(4, self._line, self.width() - 4, self._line)
            p.end()


class MemoCard(QtWidgets.QFrame):
    def __init__(self, panel, data):
        super().__init__()
        self.panel, self.store, self.data = panel, panel.store, data
        self.setObjectName("memoCard")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = DragHead(self)
        head.setObjectName("memoHead")
        hl = QtWidgets.QHBoxLayout(head)
        hl.setContentsMargins(8, 2, 2, 2)
        hl.setSpacing(3)
        self.title = ElideLabel()   # 빌드 13: 길면 … (전체는 풍선)
        self.title.setObjectName("memoTitle")
        self.title.setCursor(Qt.IBeamCursor)
        self.title.mousePressEvent = lambda ev: self.edit_title()
        self.title.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred)   # 글자만큼 → 나머지는 끄는 자리
        self.title_ed = QtWidgets.QLineEdit()
        self.title_ed.setVisible(False)
        self.title_ed.editingFinished.connect(self._title_done)
        hl.addWidget(self.title)
        hl.addWidget(self.title_ed, 10)   # 빌드 13: 고칠 때는 제목 줄 대부분을 씀
        self.spacer = QtWidgets.QWidget()
        self.spacer.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(self.spacer, 1)
        self.badges = QtWidgets.QLabel()   # 📌 · 📁 · ⏰ · 3/5
        self.badges.setObjectName("memoWhen")
        hl.addWidget(self.badges)
        self.when = QtWidgets.QLabel()
        self.when.setObjectName("memoWhen")
        hl.addWidget(self.when)
        self.btn = QtWidgets.QToolButton()
        self.btn.setText("⋯")
        self.btn.setAutoRaise(True)
        self.btn.setToolTip(T("메모 설정 — 색 · 고정 · 접기 · 폴더 · 알림 · 순서 · 삭제"))
        self.btn.clicked.connect(self.show_menu)
        hl.addWidget(self.btn)
        lay.addWidget(head)
        self.head = head
        self.edit = MemoEdit(self)
        lay.addWidget(self.edit)
        self.grip = Grip(self)
        lay.addWidget(self.grip)
        self.apply_style()
        if data.get("html"):
            self.edit.blockSignals(True)
            self.edit.setHtml(data["html"])
            self.edit.linkify()   # 예전 메모의 주소·경로도 파랑으로
            self.edit.blockSignals(False)
        self.edit.edited.connect(self._edited)
        self.set_height(int(data.get("h") or DEF_H))
        self._apply_fold()
        self._title_text()

    # ---- 제목 줄 글자
    def _title_text(self):
        full = self.data.get("title") or time.strftime("%m/%d", time.localtime(self.data.get("t", time.time())))
        self.title.setText(full)
        self.title.setToolTip(full + "\n" + T("눌러서 제목 바꾸기"))
        mt = self.data.get("mt") or self.data.get("t") or time.time()
        self.when.setText(time.strftime("%H:%M" if time.strftime("%Y%m%d", time.localtime(mt)) == time.strftime("%Y%m%d") else "%Y-%m-%d",
                                        time.localtime(mt)))
        bits, tips = [], []
        if self.data.get("pin"):
            bits.append("📌")
            tips.append(T("맨 위 고정"))
        if self.data.get("folder"):
            bits.append("📁")
            tips.append(T("폴더 메모: {0}").format(self.data["folder"]))
        if self.data.get("remind"):
            bits.append("⏰")
            tips.append(T("알림: {0}").format(time.strftime("%m-%d %H:%M", time.localtime(self.data["remind"]))))
        done, total = self.edit.progress()
        if total:
            bits.append(f"{done}/{total}")
            tips.append(T("체크박스 {0}개 중 {1}개 끝남").format(total, done))
        self.badges.setText(" ".join(bits))
        self.badges.setToolTip("\n".join(tips))

    def apply_style(self):
        dark = self.panel.dark()
        body, band, txt = paper(self.data.get("color", DEFAULT_COLOR), dark)
        self.text_color = txt
        self.done_gray = DONE_GRAY_DARK if dark else DONE_GRAY
        fs = self.data.get("fs", BASE_SIZE)
        self.setStyleSheet(
            f"#memoCard{{background:{body}; border:1px solid {band}; border-radius:6px;}}"
            f"#memoHead{{background:{band}; border-top-left-radius:6px; border-top-right-radius:6px;}}"
            f"#memoTitle{{color:{txt}; font-weight:bold;}} #memoWhen{{color:{txt}; font-size:8pt;}}"
            f"QTextEdit{{background:{body}; color:{txt}; font-size:{fs}pt; border:none;}}"
            f"QToolButton{{color:{txt};}} QLineEdit{{background:{body}; color:{txt};}}")
        pal = self.edit.palette() if hasattr(self, "edit") else None
        if pal is not None:
            pal.setColor(QtGui.QPalette.Link, QtGui.QColor(LINK_COLOR))
            self.edit.setPalette(pal)

    def set_height(self, h):
        self.data["h"] = h
        self.edit.setFixedHeight(h)

    def _edited(self):
        self.data["html"] = self.edit.toHtml()
        self.data["text"] = self.edit.toPlainText()[:200]
        self.data["mt"] = time.time()
        self._title_text()
        self.store.touch(self.panel)

    # ---- 접기
    def toggle_fold(self):
        self.data["fold"] = not self.data.get("fold")
        self._apply_fold()
        self.store.touch(self.panel)
        log.info("메모 접기 %s %s", self.data["id"], self.data["fold"])

    def _apply_fold(self):
        f = bool(self.data.get("fold"))
        self.edit.setVisible(not f)
        self.grip.setVisible(not f)

    # ---- 제목
    def edit_title(self):
        self.title.setVisible(False)
        self.title_ed.setText(self.data.get("title") or self.title.text())
        self.title_ed.setVisible(True)
        self.spacer.setVisible(False)
        self.title_ed.setFocus()
        self.title_ed.selectAll()

    def _title_done(self):
        if not self.title_ed.isVisible():
            return
        t = self.title_ed.text().strip()
        self.data["title"] = t or time.strftime("%m/%d", time.localtime(self.data.get("t", time.time())))
        self.title_ed.setVisible(False)
        self.spacer.setVisible(True)
        self.title.setVisible(True)
        self._title_text()
        self.store.touch(self.panel, structure=True)
        log.info("메모 제목 %s = %s", self.data["id"], self.data["title"])

    # ---- ⋯ 메뉴
    def show_menu(self):
        m = QtWidgets.QMenu(self)
        cm = m.addMenu(T("메모 색"))
        for k, lbl, _s in labels.TAB_COLORS:
            _b, band, _t = paper(k, self.panel.dark())
            pm = QtGui.QPixmap(14, 14)
            pm.fill(QtGui.QColor(band))
            a = cm.addAction(QtGui.QIcon(pm), lbl, lambda k=k: self.set_color(k))
            a.setCheckable(True)
            a.setChecked(self.data.get("color") == k)
        m.addAction(T("제목 바꾸기"), self.edit_title)
        a = m.addAction(T("맨 위 고정"), lambda: self.store.set_pin(self.data["id"], not self.data.get("pin")))
        a.setCheckable(True)
        a.setChecked(bool(self.data.get("pin")))
        a = m.addAction(T("접기 (제목 줄 두 번 누르기)"), self.toggle_fold)
        a.setCheckable(True)
        a.setChecked(bool(self.data.get("fold")))
        m.addSeparator()
        cur = self.panel.cur_folder() if self.panel.cur_folder else None
        if self.data.get("folder"):
            m.addAction(T("폴더 열기: {0}").format(os.path.basename(self.data["folder"].rstrip("\\/")) or self.data["folder"]),
                        lambda: self.panel.open_link(self.data["folder"]))
            m.addAction(T("폴더에서 떼기"), lambda: self.set_folder(None))
        if cur:
            m.addAction(T("지금 폴더에 붙이기: {0}").format(os.path.basename(cur.rstrip("\\/")) or cur), lambda: self.set_folder(cur))
        m.addAction(T("알림 설정…"), self.ask_remind)
        if self.data.get("remind"):
            m.addAction(T("알림 지우기"), lambda: self.set_remind(None))
        m.addSeparator()
        i = next((k for k, x in enumerate(self.store.memos) if x["id"] == self.data["id"]), 0)
        a = m.addAction(T("위로"), lambda: self.store.move(self.data["id"], -1))
        a.setEnabled(i > 0)
        a = m.addAction(T("아래로"), lambda: self.store.move(self.data["id"], +1))
        a.setEnabled(i < len(self.store.memos) - 1)
        m.addSeparator()
        m.addAction(T("이 메모 삭제 (휴지통으로)"), self.delete)
        m.exec(self.btn.mapToGlobal(QtCore.QPoint(0, self.btn.height())))

    def set_color(self, k):
        self.data["color"] = k
        self.apply_style()
        self.store.touch(self.panel, structure=True)
        log.info("메모 색 %s = %s", self.data["id"], k)

    def set_folder(self, path):
        if path:
            self.data["folder"] = path
        else:
            self.data.pop("folder", None)
        log.info("메모 폴더 %s = %s", self.data["id"], path)
        self.store.touch(self.panel, structure=True)

    def ask_remind(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(T("알림 설정"))
        lay = QtWidgets.QVBoxLayout(dlg)
        lay.addWidget(QtWidgets.QLabel(T("이 시각에 메모 창을 띄우고 이 메모를 알려 줍니다.")))
        de = QtWidgets.QDateTimeEdit(QtCore.QDateTime.fromSecsSinceEpoch(int(self.data.get("remind") or time.time() + 3600)))
        de.setCalendarPopup(True)
        de.setDisplayFormat("yyyy-MM-dd HH:mm")
        lay.addWidget(de)
        row = QtWidgets.QHBoxLayout()
        for label, mins in ((T("10분 뒤"), 10), (T("1시간 뒤"), 60), (T("내일 9시"), None)):
            b = QtWidgets.QPushButton(label)

            def setv(mins=mins):
                if mins is None:
                    t = QtCore.QDateTime(QtCore.QDate.currentDate().addDays(1), QtCore.QTime(9, 0))
                else:
                    t = QtCore.QDateTime.currentDateTime().addSecs(mins * 60)
                de.setDateTime(t)
            b.clicked.connect(lambda *_, f=setv: f())
            row.addWidget(b)
        lay.addLayout(row)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec():
            self.set_remind(de.dateTime().toSecsSinceEpoch())

    def set_remind(self, ts):
        if ts:
            self.data["remind"] = float(ts)
        else:
            self.data.pop("remind", None)
        log.info("메모 알림 %s = %s", self.data["id"], time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else None)
        self.store.arm_reminders()
        self.store.touch(self.panel, structure=True)

    def delete(self):
        self.store.remove(self.data["id"])   # 휴지통으로 (⚙ ▸ 지운 메모에서 되살림)
        self.panel.notify(T("메모를 휴지통으로 옮겼습니다 — ⚙ ▸ 지운 메모에서 되살릴 수 있습니다"))

    def flash(self):
        """알림·폴더 메모 등으로 이 메모를 가리킬 때 잠깐 테두리"""
        base = self.styleSheet()
        self.setStyleSheet(base + "#memoCard{border:3px solid #2f7de1;}")
        QtCore.QTimer.singleShot(1600, lambda: self.setStyleSheet(base))


class MemoPanel(QtWidgets.QFrame):
    """메모 창 안 — 같은 MemoStore 를 보여 줌"""

    def __init__(self, store, dark_fn, on_side=None, on_close=None):
        super().__init__()
        self.store, self.dark, self.on_side, self.on_close = store, dark_fn, on_side, on_close
        self.open_path = None    # 4Dir 쪽: 폴더·파일 경로 열기
        self.cur_folder = None   # 4Dir 쪽: 지금 칸 폴더
        self.fill_settings = None
        self.on_pin = None
        self.color_filter = None
        self.setObjectName("memoPanel")
        self.setMinimumWidth(180)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(2)
        fg = "#e8e6e1" if dark_fn() else "#3a4652"
        self.btn_add = QtWidgets.QPushButton()
        self.btn_add.setObjectName("memoAdd")
        self.btn_add.setIcon(fmt_icon("plus", fg, sz=ICON))
        self.btn_add.setIconSize(QtCore.QSize(ICON, ICON))
        self.btn_add.setToolTip(T("새 메모"))
        self.btn_add.setCursor(Qt.PointingHandCursor)
        self.btn_add.setFixedSize(36, 32)
        self.btn_add.clicked.connect(lambda *_: self.add())
        top.addWidget(self.btn_add, 0, Qt.AlignTop)
        top.addSpacing(2)
        self.cur_edit = None
        self.bar = FormatBar(self._target, fg)
        self.search = QtWidgets.QLineEdit()   # 빌드 15 사용자: 윗줄 = ＋ · 검색 · 색 · 📌 · ⚙
        self.search.setPlaceholderText("🔍 " + T("검색…"))
        self.search.setToolTip(T("제목·내용으로 메모 거르기 (한글 상태로 친 영문도 찾음)"))
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(28)
        for x in self.search.findChildren(QtWidgets.QToolButton):   # Qt 가 만든 ✕ 단추에도 설명
            x.setToolTip(T("검색 지우기"))
        self.search.textChanged.connect(self.apply_filter)
        top.addWidget(self.search, 1)
        self.btn_cf = QtWidgets.QToolButton()   # 색으로 거르기 (빌드 14 사용자: 🎨 이 작아 뭔지 모름 → 그린 아이콘 + '색')
        self.btn_cf.setIcon(fmt_icon("filter", fg, None, sz=ICON))
        self.btn_cf.setIconSize(QtCore.QSize(18, 18))
        self.btn_cf.setText(T("색"))
        self.btn_cf.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_cf.setToolTip(T("색으로 거르기 — 고른 색 메모만 보기"))
        self.btn_cf.setAutoRaise(True)
        self.btn_cf.setMinimumHeight(28)
        self.btn_cf.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        cfm = QtWidgets.QMenu(self.btn_cf)
        cfm.aboutToShow.connect(lambda: self._fill_cf(cfm))
        self.btn_cf.setMenu(cfm)
        top.addWidget(self.btn_cf)
        self.btn_pin = QtWidgets.QToolButton()
        self.btn_pin.setText("📌")
        self.btn_pin.setToolTip(T("메모 창 항상 위에 표시"))
        self.btn_pin.setCheckable(True)
        self.btn_pin.setAutoRaise(True)
        self.btn_pin.setFixedSize(BTN, BTN)
        self.btn_pin.clicked.connect(lambda on: self.on_pin and self.on_pin(on))
        top.addWidget(self.btn_pin, 0, Qt.AlignTop)
        self.btn_set = QtWidgets.QToolButton()
        self.btn_set.setText("⚙")
        self.btn_set.setToolTip(T("메모 설정 — 글꼴 · 지운 메모 · 체크 표시 방식 · 항상 위 · 파일 위치"))
        self.btn_set.setAutoRaise(True)
        self.btn_set.setFixedSize(BTN, BTN)
        self.btn_set.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        sm = QtWidgets.QMenu(self.btn_set)
        sm.aboutToShow.connect(lambda: self._fill_set(sm))
        self.btn_set.setMenu(sm)
        top.addWidget(self.btn_set, 0, Qt.AlignTop)
        lay.addLayout(top)
        lay.addWidget(self.bar)
        self.note = QtWidgets.QLabel()   # 잠깐 안내 (휴지통 등)
        self.note.setObjectName("favLabel")
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        lay.addWidget(self.note)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inner = DropArea(self)
        self.vl = QtWidgets.QVBoxLayout(self.inner)
        self.vl.setContentsMargins(0, 0, 4, 0)
        self.vl.setSpacing(8)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, 1)
        self.cards = []
        store.changed.connect(self._on_store)
        QtWidgets.QApplication.instance().focusChanged.connect(self._focus_bar)
        self.rebuild()

    # ---- 설정 ⚙ · 색 거르기
    def _fill_set(self, m):
        m.clear()
        fm = QtWidgets.QMenu(T("글꼴 (고른 글자, 없으면 메모 전체)"), m)
        m.addMenu(fm)
        self.bar.fill_font_menu(fm)
        m.addSeparator()
        tm = QtWidgets.QMenu(T("지운 메모 ({0})").format(len(self.store.trash)), m)   # 부모를 줘야 함수가 끝나도 안 지워짐
        m.addMenu(tm)
        for x in reversed(self.store.trash[-20:]):
            t = (x.get("title") or "") + "  " + (x.get("text") or "")[:20].replace("\n", " ")
            tm.addAction(T("되살리기: {0}").format(t.strip()), lambda mid=x["id"]: self.store.restore(mid, self))
        if self.store.trash:
            tm.addSeparator()
            tm.addAction(T("휴지통 비우기"), lambda: self.store.empty_trash(self))
        else:
            tm.addAction(T("(없음)")).setEnabled(False)
        a = m.addAction(T("체크하면 취소선 + 회색 글자"), self._toggle_strike)
        a.setCheckable(True)
        a.setChecked(bool(self.store.prefs.get("done_strike", True)))
        a.setToolTip(T("끄면 체크 표시만 바뀌고 글자는 그대로"))
        m.addSeparator()
        if self.fill_settings:
            self.fill_settings(m)

    def _toggle_strike(self):
        self.store.prefs["done_strike"] = not self.store.prefs.get("done_strike", True)
        log.info("메모 설정: 체크하면 취소선 %s", self.store.prefs["done_strike"])
        self.store.touch()

    def _fill_cf(self, m):
        m.clear()
        a = m.addAction(T("모든 색"), lambda: self.set_color_filter(None))
        a.setCheckable(True)
        a.setChecked(self.color_filter is None)
        used = []
        for x in self.store.memos:
            if x.get("color") not in used:
                used.append(x.get("color"))
        for k, lbl, _s in labels.TAB_COLORS:
            if k in used:
                _b, band, _t = paper(k, self.dark())
                pm = QtGui.QPixmap(14, 14)
                pm.fill(QtGui.QColor(band))
                a = m.addAction(QtGui.QIcon(pm), lbl, lambda k=k: self.set_color_filter(k))
                a.setCheckable(True)
                a.setChecked(self.color_filter == k)

    def set_color_filter(self, k):
        self.color_filter = k
        fg = "#e8e6e1" if self.dark() else "#3a4652"
        if k is None:
            self.btn_cf.setIcon(fmt_icon("filter", fg, None, sz=ICON))
        else:
            self.btn_cf.setIcon(fmt_icon("filter", fg, paper(k, self.dark())[1], sz=ICON))
        self.apply_filter()

    def notify(self, text, ms=5000):
        self.note.setText(text)
        self.note.setVisible(True)
        QtCore.QTimer.singleShot(ms, lambda: self.note.setVisible(False))

    # ---- 링크 열기 (4Dir 쪽에 맡김)
    def open_link(self, link):
        if link.startswith("file:///"):
            link = QtCore.QUrl(link).toLocalFile()
        log.info("메모 링크 열기 %s", link)
        if re.match(r"https?://", link):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(link))
        elif self.open_path:
            self.open_path(link)
        else:
            os.startfile(link)

    def _focus_bar(self, old, new):
        for c in self.cards:
            if new is c.edit:
                self.cur_edit = c.edit
                self.bar.sync(c.edit)

    def _target(self):
        ed = self.cur_edit
        try:
            if ed is not None and any(c.edit is ed for c in self.cards):
                return ed
        except RuntimeError:
            pass
        return self.cards[0].edit if self.cards else None

    def apply_filter(self, *_):
        q = self.search.text().strip().lower()
        alt = ko_keys(q).lower() if q and has_hangul(q) else None   # 한글 상태로 친 영문 ('ㅁㄴㅇㄹ' → 'asdf')
        hits = 0
        for c in self.cards:
            hay = ((c.data.get("title") or "") + "\n" + c.edit.toPlainText()).lower()
            hit = not q or q in hay or (alt is not None and alt in hay)
            if self.color_filter is not None and c.data.get("color") != self.color_filter:
                hit = False
            c.setVisible(hit)
            hits += hit
        if q or self.color_filter:
            log.info("메모 거르기 '%s'%s 색=%s → %d/%d", q, f" (영문 {alt})" if alt else "", self.color_filter, hits, len(self.cards))

    def _on_store(self, origin):
        self.rebuild(keep_focus=True)

    def rebuild(self, keep_focus=False):
        fid = None
        fw = QtWidgets.QApplication.focusWidget()
        for c in self.cards:
            if fw is c.edit:
                fid = (c.data["id"], c.edit.textCursor().position())
        while self.vl.count():
            it = self.vl.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
                it.widget().deleteLater()
        self.cards = []
        if not self.store.memos:
            self.empty = QtWidgets.QLabel(T("메모가 없습니다.\n위 ＋ 를 누르세요."))
            self.empty.setAlignment(Qt.AlignCenter)
            self.empty.setObjectName("favLabel")
            self.vl.addWidget(self.empty)
        for n in self.store.memos:
            c = MemoCard(self, n)
            c.edit.cursorPositionChanged.connect(lambda ed=c.edit: ed is self.cur_edit and self.bar.sync(ed))
            self.cards.append(c)
            self.vl.addWidget(c)
        self.vl.addStretch(1)
        self.apply_filter()
        if keep_focus and fid:
            for c in self.cards:
                if c.data["id"] == fid[0]:
                    c.edit.setFocus()
                    cur = c.edit.textCursor()
                    cur.setPosition(min(fid[1], len(c.edit.toPlainText())))
                    c.edit.setTextCursor(cur)

    def add(self):
        if self.search.text():
            self.search.clear()
        if self.color_filter is not None:
            self.set_color_filter(None)
        n = self.store.add(self)
        for c in self.cards:
            if c.data["id"] == n["id"]:
                c.edit.setFocus()
                self.scroll.ensureWidgetVisible(c)
        return n

    def reveal(self, mid):
        """이 메모로 스크롤하고 잠깐 강조 (알림·폴더 메모)"""
        if self.search.text():
            self.search.clear()
        self.set_color_filter(None)
        for c in self.cards:
            if c.data["id"] == mid:
                if c.data.get("fold"):
                    c.toggle_fold()
                self.scroll.ensureWidgetVisible(c)
                c.flash()
                return c
        return None

    def restyle(self):
        for c in self.cards:
            c.apply_style()
