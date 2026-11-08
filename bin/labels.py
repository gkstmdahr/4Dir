# -*- coding: utf-8 -*-
"""색 라벨 (v0.9.89 사용자 11/4): 파일·폴더에 색을 칠해 둠 (작업 중·검수 대기 등).
4Dir 안에만 저장 (bin\\4Dir_labels.json {경로(소문자): 색 이름}) — 파일 자체는 건드리지 않음.
탭 색도 같은 색 표를 씀."""
import os
import json
import logging

from i18n import T

log = logging.getLogger("QE.labels")

# (이름, 표시 이름, 진한 색 = 탭 띠·메뉴 동그라미, 밝은 바탕 = 목록 줄, 어두운 테마 바탕)
COLORS = [
    ("red", T("빨강"), "#e5484d", "#fde4e4", "#4a2427"),
    ("orange", T("주황"), "#f76b15", "#feead9", "#4a3020"),
    ("yellow", T("노랑"), "#e2b203", "#fdf5c9", "#45401d"),
    ("green", T("초록"), "#30a46c", "#ddf3e4", "#1e3d2c"),
    ("blue", T("파랑"), "#0090ff", "#dcedfc", "#1d3550"),
    ("purple", T("보라"), "#8e4ec6", "#efe3fa", "#36264a"),
    ("gray", T("회색"), "#8b8d98", "#ececef", "#36383d"),
]
STRONG = {k: s for k, _l, s, _b, _d in COLORS}
LIGHT = {k: b for k, _l, _s, b, _d in COLORS}
DARK = {k: d for k, _l, _s, _b, d in COLORS}

# 추가 색 (v0.9.90 사용자 11/4 "탭 색 더 다양하게", 파일 색 라벨도 같이) — 바탕색은 bg() 가 섞어 만듦
TAB_EXTRA = [
    ("pink", T("분홍"), "#e93d82"),
    ("brown", T("갈색"), "#a07553"),
    ("lime", T("연두"), "#8db600"),
    ("teal", T("청록"), "#12a594"),
    ("sky", T("하늘"), "#3fb5e8"),
    ("indigo", T("남색"), "#3e63dd"),
]
# 메뉴 순서: 무지개 순으로 섞음
TAB_COLORS = [(k, l, s) for k, l, s, _b, _d in COLORS[:3]] + [TAB_EXTRA[2]] + [(k, l, s) for k, l, s, _b, _d in COLORS[3:4]] \
    + TAB_EXTRA[3:5] + [(k, l, s) for k, l, s, _b, _d in COLORS[4:5]] + TAB_EXTRA[5:6] \
    + [(k, l, s) for k, l, s, _b, _d in COLORS[5:6]] + TAB_EXTRA[0:2] + [(k, l, s) for k, l, s, _b, _d in COLORS[6:]]
TAB_HEX = {k: s for k, _l, s in TAB_COLORS}


def tab_hex(c):
    """탭 색 값 → '#rrggbb' (이름이면 표에서, '#rrggbb' 이면 직접 고른 색 그대로, 아니면 '')"""
    if not c:
        return ""
    if c in TAB_HEX:
        return TAB_HEX[c]
    if isinstance(c, str) and len(c) == 7 and c[0] == "#":
        try:
            int(c[1:], 16)
            return c.lower()
        except ValueError:
            pass
    return ""


def _mix(a, b, t):
    """색 a 를 b 쪽으로 t 만큼 섞음 ('#rrggbb')"""
    a, b = int(a[1:], 16), int(b[1:], 16)
    ch = [round(((a >> s) & 255) * (1 - t) + ((b >> s) & 255) * t) for s in (16, 8, 0)]
    return "#%02x%02x%02x" % tuple(ch)


def bg(c, dark):
    """파일 색 라벨 줄 바탕 (v0.9.90: 13색·직접 고른 색도) — 처음 7색은 손으로 고른 값, 나머지는 진한 색을 섞어 만듦"""
    if c in LIGHT:
        return DARK[c] if dark else LIGHT[c]
    h = tab_hex(c)
    if not h:
        return ""
    return _mix(h, "#1e1f22", 0.72) if dark else _mix(h, "#ffffff", 0.84)


class Store:
    def __init__(self, path):
        self.path = path
        self.data = {}
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    self.data = {k: v for k, v in json.load(f).items() if tab_hex(v)}
        except Exception:
            log.exception("색 라벨 파일 깨짐 → 빈 것으로 %s", path)

    def get(self, full):
        return self.data.get(os.path.normcase(full)) if self.data else None

    def set(self, paths, color):
        for p in paths:
            k = os.path.normcase(p)
            if color:
                self.data[k] = color
            else:
                self.data.pop(k, None)
        self.save()
        log.info("색 라벨 %s → %d개 %s", color or "없음", len(paths), paths[:3])

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            log.exception("색 라벨 저장 실패 %s", self.path)


class Ratings:
    """별점 1~5 (0.9.116 빌드 3, 사용자 11/8 #8 — Adobe Bridge·Eagle 처럼). 4Dir 안에만 저장 (4Dir_ratings.json {경로(소문자): 1~5})"""
    STARS = "★★★★★"

    def __init__(self, path):
        self.path = path
        self.data = {}
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    self.data = {k: int(v) for k, v in json.load(f).items() if str(v).isdigit() and 1 <= int(v) <= 5}
        except Exception:
            log.exception("별점 파일 깨짐 → 빈 것으로 %s", path)

    def get(self, full):
        return self.data.get(os.path.normcase(full), 0) if self.data else 0

    @staticmethod
    def text(n):
        return ("★" * n + "☆" * (5 - n)) if n else ""

    def set(self, paths, n):
        for p in paths:
            k = os.path.normcase(p)
            if n:
                self.data[k] = int(n)
            else:
                self.data.pop(k, None)
        self.save()
        log.info("별점 %s → %d개 %s", n or "없음", len(paths), paths[:3])

    def rename(self, old, new):
        """4Dir 안에서 이름 바꾸기·옮기기 → 따라감 (폴더면 그 안 것까지)"""
        o, nn = os.path.normcase(old), os.path.normcase(new)
        moved = {}
        for k in list(self.data):
            if k == o or k.startswith(o + os.sep):
                moved[nn + k[len(o):]] = self.data.pop(k)
        if moved:
            self.data.update(moved)
            self.save()

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            log.exception("별점 저장 실패 %s", self.path)
