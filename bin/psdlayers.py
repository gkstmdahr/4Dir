# -*- coding: utf-8 -*-
"""PSD 레이어 목록 미리보기 (PSDLAYERS_VER 1.0.0, 0.9.116 — 사용자 11/8 요청 '미리보기 창에서 형식별로 보기: PSD 레이어')

- 미리보기 창에 끼우는 위젯: can_handle(path) (.psd .psb, 확장자만) · make_widget(path, parent) -> QWidget|None
- read_layers(path) -> dict : PSD 파일 형식을 직접 읽음 (헤더 → 색 모드 → 그림 자원 → 레이어·마스크 정보 구역)
  레이어 이름(유니코드 이름 'luni' 우선) · 보임/숨김 · 불투명도 · 섞는 방식 · 위치·크기 · 그룹 시작/끝(lsct) → 들여쓰기
  레이어 픽셀은 읽지 않음 (필요한 앞부분 기록만 건너뛰며 읽어 빠름). 16·32비트 문서(Lr16/Lr32) · PSB(길이 8바이트) 처리
- 깨진 파일은 dict["error"] 에 안내 글 (읽은 데까지 헤더 정보는 남김)
- 화면: 위에 전체 크기·색 모드·비트 깊이·레이어 수, 아래 나무(이름 · 보임 · 불투명도 · 섞는 방식 · 위치·크기). 읽기는 뒤 스레드
로그: bin\\log\\4Dir.log [QE.psdlayers]
"""
import os
import time
import struct
import logging
import threading

from i18n import T
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

PSDLAYERS_VER = "1.0.0"
log = logging.getLogger("QE.psdlayers")
EXTS = {".psd", ".psb"}
MAX_LAYERS = 20000

MODES = {0: "Bitmap", 1: "Grayscale", 2: "Indexed", 3: "RGB", 4: "CMYK", 7: "Multichannel", 8: "Duotone", 9: "Lab"}
# 섞는 방식 열쇠 → 포토샵 화면 이름 (한국어판 이름)
BLEND = {"pass": "통과", "norm": "표준", "diss": "디졸브", "dark": "어둡게 하기", "mul ": "곱하기", "idiv": "색상 번",
         "lbrn": "선형 번", "dkCl": "어두운 색상", "lite": "밝게 하기", "scrn": "스크린", "div ": "색상 닷지",
         "lddg": "선형 닷지(추가)", "lgCl": "밝은 색상", "over": "오버레이", "sLit": "소프트 라이트", "hLit": "하드 라이트",
         "vLit": "선명한 라이트", "lLit": "선형 라이트", "pLit": "핀 라이트", "hMix": "하드 혼합", "diff": "차이",
         "smud": "제외", "fsub": "빼기", "fdiv": "나누기", "hue ": "색조", "sat ": "채도", "colr": "색상", "lum ": "광도"}
# PSB 에서 길이가 8바이트인 추가 정보 열쇠
_LONG_KEYS = {b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16", b"Mt32", b"Mtrn", b"Alph", b"FMsk", b"lnk2", b"FEid",
              b"FXid", b"PxSD"}



def _narrow(lab):
    """줄 바꿈 글자표: 폭은 창에 맞춰 줄고 늘되, 높이는 글 길이에 맞게 (heightForWidth 유지)"""
    sp = lab.sizePolicy()
    sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
    lab.setSizePolicy(sp)
    lab.setMinimumWidth(1)

def can_handle(path):
    return os.path.splitext(path or "")[1].lower() in EXTS


class PsdError(Exception):
    pass


class _R:
    """파일에서 순서대로 읽기"""

    def __init__(self, f, psb):
        self.f = f
        self.psb = psb

    def read(self, n):
        b = self.f.read(n)
        if len(b) != n:
            raise PsdError(T("파일이 중간에 끊김"))
        return b

    def u8(self):
        return self.read(1)[0]

    def u16(self):
        return struct.unpack(">H", self.read(2))[0]

    def i16(self):
        return struct.unpack(">h", self.read(2))[0]

    def u32(self):
        return struct.unpack(">I", self.read(4))[0]

    def i32(self):
        return struct.unpack(">i", self.read(4))[0]

    def ulen(self):
        """PSD 4바이트 / PSB 8바이트 길이"""
        return struct.unpack(">Q", self.read(8))[0] if self.psb else self.u32()

    def tell(self):
        return self.f.tell()

    def seek(self, p):
        self.f.seek(p)


def _parse_layer_info(r, end, out):
    """레이어 정보(길이 다음부터) → out['layers'] 에 바닥→위 순서로 넣음"""
    cnt = r.i16()
    if cnt < 0:
        out["merged_alpha"] = True
        cnt = -cnt
    if cnt > MAX_LAYERS:
        raise PsdError(T("레이어 수가 이상함 ({0})").format(cnt))
    out["count_raw"] = cnt
    recs = []
    for i in range(cnt):
        top, left, bottom, right = r.i32(), r.i32(), r.i32(), r.i32()
        nch = r.u16()
        if nch > 64:
            raise PsdError(T("레이어 기록이 깨짐"))
        r.read(nch * (10 if r.psb else 6))
        sig = r.read(4)
        if sig != b"8BIM":
            raise PsdError(T("레이어 기록이 깨짐"))
        key = r.read(4).decode("latin-1")
        opacity, clipping, flags, _ = r.u8(), r.u8(), r.u8(), r.u8()
        elen = r.u32()
        estart = r.tell()
        eend = estart + elen
        mlen = r.u32()           # 마스크
        r.seek(r.tell() + mlen)
        blen = r.u32()           # 섞기 범위
        r.seek(r.tell() + blen)
        nlen = r.u8()
        name = r.read(nlen).decode("cp1252", "replace") if nlen else ""
        pad = (4 - (1 + nlen) % 4) % 4
        r.seek(r.tell() + pad)
        uname = None
        sect = None
        extra_keys = []
        while r.tell() + 12 <= eend:
            s = r.read(4)
            if s not in (b"8BIM", b"8B64"):
                break
            k = r.read(4)
            ln = r.ulen() if (r.psb and k in _LONG_KEYS) else r.u32()
            dstart = r.tell()
            extra_keys.append(k.decode("latin-1"))
            if k == b"luni" and ln >= 4:
                n = r.u32()
                uname = r.read(min(n * 2, ln - 4)).decode("utf-16-be", "replace").rstrip("\x00")
            elif k in (b"lsct", b"lsdk") and ln >= 4:
                sect = r.u32()
                if ln >= 12:
                    if r.read(4) == b"8BIM":
                        key = r.read(4).decode("latin-1")
            r.seek(dstart + ln)
        r.seek(eend)
        kind = "layer"
        if sect in (1, 2):
            kind = "group"
        elif sect == 3:
            kind = "end"
        recs.append({"name": uname if uname is not None else name, "visible": not (flags & 2),
                     "opacity": round(opacity * 100 / 255), "blend": key, "top": top, "left": left,
                     "width": right - left, "height": bottom - top, "kind": kind, "open": sect == 1,
                     "clipping": bool(clipping), "keys": extra_keys})
    out["layers_raw"] = recs


def _build_tree(recs):
    """바닥→위 기록 → 위→아래 순서 + 들여쓰기(depth)"""
    out = []
    depth = 0
    for rec in reversed(recs):
        if rec["kind"] == "end":
            depth = max(0, depth - 1)
            continue
        e = dict(rec)
        e["depth"] = depth
        out.append(e)
        if rec["kind"] == "group":
            depth += 1
    return out


def read_layers(path):
    """PSD/PSB → dict(version, width, height, channels, depth, mode, mode_name, layers=[...], count, groups, error?)"""
    t0 = time.time()
    out = {"path": path, "layers": [], "count": 0, "groups": 0}
    try:
        with open(path, "rb") as f:
            r = _R(f, False)
            if r.read(4) != b"8BPS":
                raise PsdError(T("PSD 파일이 아님"))
            ver = r.u16()
            if ver not in (1, 2):
                raise PsdError(T("모르는 PSD 판 ({0})").format(ver))
            r.psb = ver == 2
            r.read(6)
            out.update(version=ver, channels=r.u16(), height=r.u32(), width=r.u32(), depth=r.u16(), mode=r.u16())
            out["mode_name"] = MODES.get(out["mode"], str(out["mode"]))
            size = os.fstat(f.fileno()).st_size
            cm = r.u32()
            r.seek(r.tell() + cm)
            ir = r.u32()
            r.seek(r.tell() + ir)
            lm_len = r.ulen()
            lm_start = r.tell()
            lm_end = lm_start + lm_len
            if lm_end > size:
                raise PsdError(T("파일이 중간에 끊김"))
            if lm_len:
                li_len = r.ulen()
                li_start = r.tell()
                if li_len:
                    _parse_layer_info(r, li_start + li_len, out)
                # 16·32비트 문서는 레이어가 뒤쪽 추가 정보(Lr16/Lr32)에 있음
                if not out.get("layers_raw"):
                    r.seek(li_start + li_len)
                    if r.tell() + 4 <= lm_end:
                        gm = r.u32()
                        r.seek(r.tell() + gm)
                    while r.tell() + 12 <= lm_end:
                        s = r.read(4)
                        if s not in (b"8BIM", b"8B64"):
                            break
                        k = r.read(4)
                        ln = r.ulen() if (r.psb and k in _LONG_KEYS) else r.u32()
                        ds = r.tell()
                        if k in (b"Lr16", b"Lr32", b"Layr") and ln:
                            _parse_layer_info(r, ds + ln, out)
                            break
                        r.seek(ds + ln)
    except PsdError as ex:
        out["error"] = str(ex)
    except (OSError, struct.error, ValueError) as ex:
        out["error"] = T("파일이 깨졌거나 읽을 수 없음: {0}").format(ex)
    recs = out.pop("layers_raw", [])
    out["layers"] = _build_tree(recs)
    out["count"] = sum(1 for x in out["layers"] if x["kind"] == "layer")
    out["groups"] = sum(1 for x in out["layers"] if x["kind"] == "group")
    log.info("읽음 %s 판=%s %sx%s %s %s비트 레이어 %d 그룹 %d 오류=%s %.0fms", path, out.get("version"), out.get("width"),
             out.get("height"), out.get("mode_name"), out.get("depth"), out["count"], out["groups"], out.get("error"),
             (time.time() - t0) * 1000)
    return out


# ---------------------------------------------------------------- 화면
class _Bridge(QtCore.QObject):
    done = QtCore.Signal(object)


def _eye_icon(on, col):
    pm = QtGui.QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    c = QtGui.QColor(col)
    if not on:
        c.setAlpha(70)
    p.setPen(QtGui.QPen(c, 1.4))
    p.drawEllipse(QtCore.QRectF(1.5, 4.5, 13, 7))
    if on:
        p.setBrush(c)
        p.drawEllipse(QtCore.QRectF(5.5, 5.5, 5, 5))
    else:
        p.drawLine(2, 14, 14, 2)
    p.end()
    return QtGui.QIcon(pm)


class PsdView(QtWidgets.QWidget):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.data = None
        self.cancel = threading.Event()
        self.destroyed.connect(self.cancel.set)
        self.setMinimumWidth(150)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.info = QtWidgets.QLabel(T("읽는 중…"))
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        _narrow(self.info)
        lay.addWidget(self.info)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([T("레이어"), T("보임"), T("불투명도"), T("섞는 방식"), T("위치·크기")])
        self.tree.setUniformRowHeights(True)
        self.tree.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tree.setIndentation(14)
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for i in (1, 2, 3, 4):
            h.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeToContents)
        lay.addWidget(self.tree, 1)
        log.info("열기 %s", path)
        br = _Bridge(self)
        br.done.connect(self._on_done)
        cancel = self.cancel

        def work():
            try:
                d = read_layers(path)
            except Exception as ex:
                log.exception("읽기 실패")
                d = {"error": str(ex), "layers": [], "count": 0, "groups": 0}
            if cancel.is_set():
                return
            try:
                br.done.emit(d)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True, name="psdlayers").start()

    def _on_done(self, d):
        self.data = d
        lines = []
        if d.get("width"):
            lines.append(T("크기: {0} × {1}").format(d["width"], d["height"]) +
                         ("  (PSB)" if d.get("version") == 2 else ""))
            lines.append(T("색 모드: {0} · {1}비트").format(d["mode_name"], d["depth"]))
            lines.append(T("레이어 {0}개 · 그룹 {1}개").format(d["count"], d["groups"]))
        if d.get("error"):
            lines.append(T("읽지 못한 부분: {0}").format(d["error"]))
        elif not d["layers"]:
            lines.append(T("레이어가 없음 (한 장짜리 그림)"))
        self.info.setText("\n".join(lines))
        if d.get("error"):
            self.info.setStyleSheet("color:#d04040;")
        dark = self.palette().color(QtGui.QPalette.Base).lightness() < 128
        fg = "#dfe3e8" if dark else "#333333"
        eye_on, eye_off = _eye_icon(True, fg), _eye_icon(False, fg)
        folder = self.style().standardIcon(QtWidgets.QStyle.SP_DirIcon)
        stack = [self.tree.invisibleRootItem()]
        hidden_col = self.palette().color(QtGui.QPalette.PlaceholderText)
        for e in d["layers"]:
            while len(stack) > e["depth"] + 1:
                stack.pop()
            parent = stack[-1]
            pos = "" if e["kind"] == "group" else "%d,%d  %d×%d" % (e["left"], e["top"], e["width"], e["height"])
            it = QtWidgets.QTreeWidgetItem(parent, [e["name"] or "(" + T("이름 없음") + ")", "", "%d%%" % e["opacity"],
                                                    T(BLEND.get(e["blend"], e["blend"])), pos])
            it.setIcon(1, eye_on if e["visible"] else eye_off)
            it.setToolTip(1, T("보임") if e["visible"] else T("숨김"))
            if e["kind"] == "group":
                it.setIcon(0, folder)
                stack.append(it)
                it.setExpanded(True)
            if not e["visible"]:
                for c in (0, 2, 3, 4):
                    it.setForeground(c, hidden_col)
        self.tree.expandAll()


def make_widget(path, parent=None):
    if not can_handle(path) or not os.path.isfile(path):
        return None
    try:
        return PsdView(path, parent)
    except Exception:
        log.exception("위젯 만들기 실패 %s", path)
        return None
